# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Chunk tree tests.

The chunk header layout and the gzip rule tested here are the *documented, unverified* assumptions of
``docs/format/overview.md`` §2.1-2.2; synthetic streams are built by ``synth_max``.
"""

import gzip
import struct

import pytest

from maxfile import chunks
from maxfile.errors import ChunkError
from synth_max import cont, f32, leaf, text, u32


def test_leaf_and_container():
    data = cont(0x0001, leaf(0x0962, text("Box001")), leaf(0x096A, f32(1, 2, 3))) + leaf(0x0002, b"\xAA\xBB")
    stream = chunks.ChunkStream(data)
    assert stream.error is None and not stream.compressed
    top, tail = stream.chunks
    assert top.type == 0x0001 and top.is_container and top.offset == 0
    assert top.size == len(data) - 8 and top.header_size == 6
    name, pos = top.children
    assert name.type == 0x0962 and not name.is_container and name.string() == "Box001"
    assert name.offset == 6 and name.payload_offset == 12
    assert pos.f32s() == (1.0, 2.0, 3.0)
    assert tail.data == b"\xAA\xBB" and tail.children == []
    assert top.find(0x096A) is pos and top.find(0x1234) is None
    assert top.find_all(0x0962) == [name]
    assert stream.errors() == []
    stream.check()


def test_extended_header():
    # Unverified (overview.md §2.1): u32 size 0 -> u64 size with bit 63 = container.
    inner = leaf(0x0100, u32(7, 8), extended=True)
    data = cont(0x0010, inner, leaf(0x0101, b"z"), extended=True)
    stream = chunks.ChunkStream(data)
    (top,) = stream.chunks
    assert top.is_container and top.header_size == 14 and top.size == len(data)
    first, second = top.children
    assert first.header_size == 14 and not first.is_container and first.u32s() == (7, 8)
    assert second.header_size == 6 and second.data == b"z"


def test_container_flag_masked_from_size():
    data = cont(0x0001, leaf(0x0002, b"abcd"))
    (raw,) = struct.unpack_from("<I", data, 2)
    assert raw & 0x80000000
    (top,) = chunks.ChunkStream(data).chunks
    assert top.size == len(data)


def test_empty_stream():
    stream = chunks.ChunkStream(b"")
    assert stream.chunks == [] and stream.error is None


def test_empty_container():
    (top,) = chunks.ChunkStream(cont(0x0005)).chunks
    assert top.is_container and top.children == [] and top.error is None


@pytest.mark.parametrize("data,match", [
    (b"\x01\x00\x03", "too short for a chunk header"),
    (struct.pack("<HI", 1, 3) + b"xxx", "smaller than its 6-byte header"),
    (struct.pack("<HI", 1, 100) + b"xxx", "runs past the end"),
    (struct.pack("<HI", 1, 0) + b"\0\0", "extended header cut short"),
    (struct.pack("<HIQ", 1, 0, 10), "smaller than its 14-byte header"),
    (struct.pack("<HI", 1, 0x80000000), "smaller than its 6-byte header"),
])
def test_bad_top_level_headers(data, match):
    stream = chunks.ChunkStream(data)
    assert match in stream.error
    with pytest.raises(ChunkError, match=match):
        stream.check()


def test_bad_child_header_keeps_parsed_siblings():
    good = leaf(0x0002, b"ok")
    bad = struct.pack("<HI", 0x0003, 999) + b"zz"
    payload = good + bad
    data = struct.pack("<HI", 0x0001, (len(payload) + 6) | 0x80000000) + payload
    stream = chunks.ChunkStream(data)
    (top,) = stream.chunks
    assert [c.type for c in top.children] == [0x0002]
    assert "chunk 0x0003 at 0xE" in top.error
    assert top.data == payload      # The raw payload stays available.
    assert stream.errors() == [top.error]


def test_lazy_parsing():
    data = cont(0x0001, cont(0x0002, leaf(0x0003, b"abc")))
    (top,) = chunks.ChunkStream(data).chunks
    assert top._children is None
    (mid,) = top.children
    assert mid._children is None


def test_deep_tree_is_not_recursive():
    depth = 5000    # Far beyond Python's default recursion limit.
    data = leaf(0x0FFF, b"bottom")
    for _ in range(depth):
        data = cont(0x0001, data)
    stream = chunks.ChunkStream(data)
    items = list(stream.walk())
    assert len(items) == depth + 1
    assert items[-1][0] == depth and items[-1][1].data == b"bottom"
    assert stream.errors() == []


def test_walk_order_and_depth_limit():
    data = cont(0x0001, leaf(0x0002), cont(0x0003, leaf(0x0004)), leaf(0x0005)) + leaf(0x0006)
    stream = chunks.ChunkStream(data)
    assert [(d, c.type) for d, c in stream.walk()] == [(0, 1), (1, 2), (1, 3), (2, 4), (1, 5), (0, 6)]
    assert [(d, c.type) for d, c in stream.walk(max_depth=1)] == [(0, 1), (1, 2), (1, 3), (1, 5), (0, 6)]
    assert [(d, c.type) for d, c in stream.walk(max_depth=0)] == [(0, 1), (0, 6)]


# -----------------------------------------------------------------------------
# Whole-stream gzip (unverified, overview.md §2.2)

def test_gzip_stream():
    raw = cont(0x0001, leaf(0x0962, text("Teapot")))
    packed = gzip.compress(raw)
    stream = chunks.ChunkStream(packed, "Scene")
    assert stream.compressed and stream.data == raw
    assert stream.stored_size == len(packed) and stream.size == len(raw)
    assert stream.chunks[0].children[0].string() == "Teapot"
    assert stream.warnings == []


def test_gzip_multiple_members():
    a, b = leaf(0x0001, b"a"), leaf(0x0002, b"b")
    stream = chunks.ChunkStream(gzip.compress(a) + gzip.compress(b))
    assert stream.compressed and [c.type for c in stream.chunks] == [1, 2]


def test_gzip_magic_but_not_gzip():
    # A chunk of type 0x8B1F whose size starts with 0x08 begins with 1F 8B 08 but is not compressed.
    data = struct.pack("<HI", 0x8B1F, 0x0808) + b"\0" * (0x0808 - 6)
    stream = chunks.ChunkStream(data, "Odd")
    assert data[:3] == chunks.GZIP_MAGIC
    assert not stream.compressed
    assert stream.chunks[0].type == 0x8B1F
    assert len(stream.warnings) == 1 and "read as uncompressed" in stream.warnings[0]


def test_gzip_truncated():
    data = gzip.compress(leaf(0x0001, b"x" * 1000))[:-20]
    stream = chunks.ChunkStream(data)
    assert not stream.compressed and stream.warnings


def test_gzip_trailing_garbage():
    data = gzip.compress(leaf(0x0001, b"x")) + b"junk"
    out, compressed, warning = chunks.decompress_stream(data)
    assert compressed and out == leaf(0x0001, b"x") and "non-gzip data" in warning


# -----------------------------------------------------------------------------
# Payload helpers

def test_helpers():
    assert chunks.utf16(text("abc") + b"\0\0") == "abc"
    assert chunks.utf16(text("abc") + b"\0") == "abc"           # Odd length.
    assert chunks.utf16(b"\x00\xD8") == "�"                # Lone surrogate.
    assert chunks.u32s(u32(1, 2) + b"\x01") == (1, 2)           # Trailing byte ignored.
    assert chunks.u32s(u32(1, 2, 3), 2) == (1, 2)
    assert chunks.i32s(u32(0xFFFFFFFF)) == (-1,)
    assert chunks.u16s(b"\x01\x00\x02\x00") == (1, 2)
    assert chunks.f32s(f32(0.5)) == (0.5,)
    with pytest.raises(ChunkError):
        chunks.f32s(f32(1.0), 2)
