# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Compound File reader tests.

Fixtures come from ``cfb_writer``, a small writer built from the [MS-CFB] spec in these tests; nothing here is
specific to .max files.
"""

import random
import struct
import time

import pytest

from cfb_writer import ENDOFCHAIN, FREESECT, build_cfb, patch_dir_entry, patch_fat, sector_offset
from maxfile import container
from maxfile.errors import ContainerError, MaxFileError, NotCompoundFileError, StreamNotFoundError, \
    UnsupportedFormatError


def _payload(size, seed=0):
    rng = random.Random(seed)
    return bytes(rng.getrandbits(8) for _ in range(size))


STREAMS = {
    "Scene": _payload(10000, 1),            # Regular sectors.
    "ClassDirectory3": _payload(700, 2),    # Mini stream.
    "Tiny": b"x",
    "Empty": b"",
    "Exactly4096": _payload(4096, 3),       # At the cutoff: regular sectors.
    "Storage/Inner": _payload(100, 4),
    "Storage/Nested/Deep": _payload(5000, 5),
}


# -----------------------------------------------------------------------------
# Signature sniffing (kept from the skeleton)

def test_signature_recognised():
    assert container.has_cfb_signature(container.CFB_SIGNATURE + b"\0" * 504)


@pytest.mark.parametrize("data", [
    b"",
    container.CFB_SIGNATURE[:-1],
    b"PK\x03\x04" + b"\0" * 60,  # ZIP.
    b"BLENDER-v502",
])
def test_signature_rejected(data):
    assert not container.has_cfb_signature(data)


def test_is_compound_file(tmp_path):
    good = tmp_path / "good.bin"
    good.write_bytes(container.CFB_SIGNATURE + b"\0" * 504)
    bad = tmp_path / "bad.bin"
    bad.write_bytes(b"not a compound file")
    empty = tmp_path / "empty.bin"
    empty.write_bytes(b"")

    assert container.is_compound_file(good)
    assert container.is_compound_file(str(good))
    assert not container.is_compound_file(bad)
    assert not container.is_compound_file(empty)


def test_is_compound_file_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        container.is_compound_file(tmp_path / "missing.max")


# -----------------------------------------------------------------------------
# Reading well-formed files

@pytest.mark.parametrize("version", [3, 4])
def test_read_streams(version):
    data, _ = build_cfb(STREAMS, version=version)
    cf = container.CompoundFile(data)
    assert cf.version == version
    assert cf.sector_size == (512 if version == 3 else 4096)
    assert cf.warnings == []
    for path, payload in STREAMS.items():
        assert cf.read_stream(path) == payload, path
    assert sorted(e.path_str for e in cf.streams()) == sorted(STREAMS)
    assert sorted(e.path_str for e in cf.storages()) == ["Storage", "Storage/Nested"]
    sizes = {e.path_str: e.size for e in cf.streams()}
    assert sizes == {k: len(v) for k, v in STREAMS.items()}


def test_mini_stream_flags():
    data, layout = build_cfb(STREAMS)
    cf = container.CompoundFile(data)
    assert cf.find("ClassDirectory3").in_mini_stream
    assert cf.find("Tiny").in_mini_stream
    assert not cf.find("Exactly4096").in_mini_stream
    assert not cf.find("Scene").in_mini_stream
    assert "ClassDirectory3" in layout["mini"]


def test_no_mini_stream():
    # Every stream is at or above the cutoff, so the file has no mini stream and no mini FAT.
    data, layout = build_cfb({"Big": _payload(9000), "Big2": _payload(4096)})
    assert layout["mini_fat"] == []
    cf = container.CompoundFile(data)
    assert cf.read_stream("Big") == _payload(9000)


def test_case_insensitive_lookup():
    data, _ = build_cfb(STREAMS)
    cf = container.CompoundFile(data)
    assert cf.read_stream("scene") == STREAMS["Scene"]
    assert cf.read_stream("CLASSDIRECTORY3") == STREAMS["ClassDirectory3"]
    assert cf.read_stream("storage/NESTED/deep") == STREAMS["Storage/Nested/Deep"]
    assert cf.read_stream(("Storage", "Inner")) == STREAMS["Storage/Inner"]
    assert cf.find("storage").kind == "storage"


def test_missing_stream():
    data, _ = build_cfb(STREAMS)
    cf = container.CompoundFile(data)
    with pytest.raises(StreamNotFoundError, match="no stream named"):
        cf.read_stream("Nope")
    with pytest.raises(StreamNotFoundError, match="is a storage"):
        cf.read_stream("Storage")
    assert cf.find("Nope") is None


def test_many_streams_tree():
    # Enough siblings for a deep red-black-ish tree spanning several directory sectors.
    streams = {"S{:03d}".format(i): bytes([i % 256]) * (i * 37 % 5000) for i in range(200)}
    data, _ = build_cfb(streams)
    cf = container.CompoundFile(data)
    assert len(cf.streams()) == 200
    for name, payload in streams.items():
        assert cf.read_stream(name) == payload


@pytest.mark.parametrize("version", [3, 4])
def test_difat_sectors(version):
    # More than 109 FAT sectors forces DIFAT sectors (the extra FAT sectors are all FREESECT, which is valid).
    per_difat = 512 // 4 - 1 if version == 3 else 4096 // 4 - 1
    extra = 109 + per_difat + 5     # Needs two DIFAT sectors.
    data, layout = build_cfb(STREAMS, version=version, extra_fat_sectors=extra)
    assert len(layout["difat"]) == 2
    cf = container.CompoundFile(data)
    for path, payload in STREAMS.items():
        assert cf.read_stream(path) == payload
    assert cf.warnings == []


def test_open_from_path(tmp_path):
    data, _ = build_cfb(STREAMS)
    path = tmp_path / "file.cfb"
    path.write_bytes(data)
    with container.CompoundFile(path) as cf:
        assert cf.read_stream("Scene") == STREAMS["Scene"]
    with pytest.raises(ValueError):
        cf.read_stream("Scene")


def test_v3_size_high_bits_ignored():
    data, _ = build_cfb({"A": _payload(5000)})
    cf = container.CompoundFile(data)
    entry_id = cf.find("A").id
    _, layout = build_cfb({"A": _payload(5000)})
    data = patch_dir_entry(data, layout, entry_id, "size", 5000 | (0xDEAD << 32))
    assert container.CompoundFile(data).read_stream("A") == _payload(5000)


# -----------------------------------------------------------------------------
# Corrupt input: always a MaxFileError, never a hang or another exception

def test_not_a_compound_file():
    with pytest.raises(NotCompoundFileError):
        container.CompoundFile(b"PK\x03\x04" + b"\0" * 1000)
    with pytest.raises(NotCompoundFileError):
        container.CompoundFile(b"")


def test_empty_file_on_disk(tmp_path):
    path = tmp_path / "empty.max"
    path.write_bytes(b"")
    with pytest.raises(NotCompoundFileError):
        container.CompoundFile(path)


def test_truncated_header():
    data, _ = build_cfb(STREAMS)
    with pytest.raises(ContainerError, match="truncated"):
        container.CompoundFile(data[:300])


def test_truncated_v4_header():
    data, _ = build_cfb(STREAMS, version=4)
    with pytest.raises(ContainerError, match="truncated"):
        container.CompoundFile(data[:2000])


def test_chain_points_outside_file():
    data, layout = build_cfb(STREAMS)
    sid = layout["streams"]["Scene"][3]
    bad = patch_fat(data, layout, sid, 10**6)
    cf = container.CompoundFile(bad)
    with pytest.raises(ContainerError, match="beyond the allocation table|outside the file"):
        cf.read_stream("Scene")


def test_truncated_file_tail():
    data, layout = build_cfb({"Big": _payload(9000)})
    # Remove the FAT sector at the end of the file.
    with pytest.raises(ContainerError):
        container.CompoundFile(data[:-100])


def _set_header(data, offset, fmt, value):
    return data[:offset] + struct.pack(fmt, value) + data[offset + struct.calcsize(fmt):]


@pytest.mark.parametrize("offset,fmt,value,error,match", [
    (26, "<H", 5, UnsupportedFormatError, "major version"),
    (28, "<H", 0xFEFF, ContainerError, "byte order"),
    (30, "<H", 12, ContainerError, "sector shift"),
    (32, "<H", 7, ContainerError, "mini sector shift"),
    (56, "<I", 1000, ContainerError, "cutoff"),
    (44, "<I", 0x7FFFFFFF, ContainerError, "FAT sectors"),
    (48, "<I", 0xFFFFFFF0, ContainerError, "directory"),
])
def test_bad_header_fields(offset, fmt, value, error, match):
    data, _ = build_cfb(STREAMS)
    with pytest.raises(error, match=match):
        container.CompoundFile(_set_header(data, offset, fmt, value))


def test_cyclic_fat_chain():
    data, layout = build_cfb(STREAMS)
    sids = layout["streams"]["Scene"]
    bad = patch_fat(data, layout, sids[5], sids[2])
    cf = container.CompoundFile(bad)
    with pytest.raises(ContainerError, match="loops back"):
        cf.read_stream("Scene")


def test_chain_ends_early():
    data, layout = build_cfb(STREAMS)
    sids = layout["streams"]["Scene"]
    bad = patch_fat(data, layout, sids[5], ENDOFCHAIN)
    cf = container.CompoundFile(bad)
    with pytest.raises(ContainerError, match="chain ends after"):
        cf.read_stream("Scene")


def test_cyclic_directory_chain():
    data, layout = build_cfb(STREAMS)
    dir_sids = layout["directory"]
    assert len(dir_sids) > 1
    bad = patch_fat(data, layout, dir_sids[-1], dir_sids[0])
    with pytest.raises(ContainerError, match="loops back"):
        container.CompoundFile(bad)


def test_cyclic_mini_chain():
    data, layout = build_cfb(STREAMS)
    cf = container.CompoundFile(data)
    sids = layout["mini"]["ClassDirectory3"]
    # Mini FAT entry sids[3] -> sids[1].
    offset = sector_offset(layout, layout["mini_fat"][0]) + sids[3] * 4
    bad = data[:offset] + struct.pack("<I", sids[1]) + data[offset + 4:]
    cf = container.CompoundFile(bad)
    with pytest.raises(ContainerError, match="loops back"):
        cf.read_stream("ClassDirectory3")


def test_mini_sector_out_of_range():
    data, layout = build_cfb(STREAMS)
    cf = container.CompoundFile(data)
    entry = cf.find("Tiny")
    bad = patch_dir_entry(data, layout, entry.id, "start", 100000)
    with pytest.raises(ContainerError, match="beyond the allocation table"):
        container.CompoundFile(bad).read_stream("Tiny")


def test_directory_tree_cycle():
    data, layout = build_cfb(STREAMS)
    cf = container.CompoundFile(data)
    storage = cf.find("Storage")
    # Make the storage's own subtree point back at the storage.
    bad = patch_dir_entry(data, layout, storage.id, "child", storage.id)
    with pytest.raises(ContainerError, match="cycle"):
        container.CompoundFile(bad)


def test_directory_index_out_of_range():
    data, layout = build_cfb(STREAMS)
    cf = container.CompoundFile(data)
    bad = patch_dir_entry(data, layout, cf.find("Tiny").id, "left", 5000)
    with pytest.raises(ContainerError, match="beyond the directory"):
        container.CompoundFile(bad)


def test_directory_link_to_unused_entry():
    data, layout = build_cfb({"A": b"a" * 10})  # Root + A: two of the four entries in the sector are unused.
    bad = patch_dir_entry(data, layout, 1, "left", 3)
    with pytest.raises(ContainerError, match="unused entry"):
        container.CompoundFile(bad)


def test_bad_directory_name_length():
    data, layout = build_cfb({"A": b"a" * 10})
    bad = patch_dir_entry(data, layout, 1, "name_len", 80)
    with pytest.raises(ContainerError, match="name length"):
        container.CompoundFile(bad)


def test_root_entry_missing():
    data, layout = build_cfb({"A": b"a" * 10})
    bad = patch_dir_entry(data, layout, 0, "type", 1)
    with pytest.raises(ContainerError, match="root entry"):
        container.CompoundFile(bad)


def test_difat_cycle():
    data, layout = build_cfb(STREAMS, extra_fat_sectors=109 + 127 + 5)
    difat = layout["difat"]
    # Point the first DIFAT sector's "next" link at itself.
    offset = sector_offset(layout, difat[0]) + 512 - 4
    bad = data[:offset] + struct.pack("<I", difat[0]) + data[offset + 4:]
    with pytest.raises(ContainerError, match="DIFAT chain loops"):
        container.CompoundFile(bad)


def test_difat_chain_too_short():
    data, layout = build_cfb(STREAMS, extra_fat_sectors=109 + 127 + 5)
    offset = sector_offset(layout, layout["difat"][0]) + 512 - 4
    bad = data[:offset] + struct.pack("<I", ENDOFCHAIN) + data[offset + 4:]
    with pytest.raises(ContainerError, match="DIFAT chain ends"):
        container.CompoundFile(bad)


def test_fat_sector_listed_twice():
    data, layout = build_cfb(STREAMS, extra_fat_sectors=3)
    first = layout["fat"][0]
    bad = data[:76 + 4] + struct.pack("<I", first) + data[76 + 8:]
    with pytest.raises(ContainerError, match="listed twice"):
        container.CompoundFile(bad)


def test_free_sector_in_difat():
    data, layout = build_cfb(STREAMS)
    bad = data[:76] + struct.pack("<I", FREESECT) + data[80:]
    with pytest.raises(ContainerError, match="FREESECT"):
        container.CompoundFile(bad)


def _try_read_everything(data):
    try:
        cf = container.CompoundFile(data)
    except MaxFileError:
        return
    for entry in cf.streams():
        try:
            cf.read_stream(entry.path)
        except MaxFileError:
            pass


def test_fuzz_mutations_never_crash_or_hang():
    """Random byte corruption gives a result or a MaxFileError, quickly; never another exception."""
    data, _ = build_cfb(STREAMS)
    rng = random.Random(1234)
    start = time.monotonic()
    for _ in range(400):
        mutated = bytearray(data)
        for _ in range(rng.randint(1, 8)):
            # Bias towards the header, FAT and directory, where corruption matters most.
            pos = rng.randrange(512) if rng.random() < 0.4 else rng.randrange(len(mutated))
            mutated[pos] = rng.getrandbits(8)
        _try_read_everything(bytes(mutated))
    for cut in range(0, len(data), 97):
        _try_read_everything(data[:cut])
    assert time.monotonic() - start < 60
