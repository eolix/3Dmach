# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Compound File writer ([MS-CFB]), version 4, as used by every ``.max`` file of the corpus.

Written from Microsoft's public specification. Layout of the files it writes: the 4096-byte header sector, then
the stream sectors (streams of 4096 bytes and more), the mini stream (smaller streams, in 64-byte mini sectors),
the mini FAT, the directory and the FAT; no DIFAT sectors until the FAT outgrows the 109 header slots.

The directory of each storage is a red-black tree ordered as [MS-CFB] 2.6.4 requires (shorter names first, then
case-insensitive): a balanced tree whose deepest level is coloured red when it isn't full, which satisfies the
red-black rules.

[MS-CFB]: https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-cfb/
"""

__all__ = ("write_compound_file", "MAX_ROOT_CLSID")

import struct
import uuid

SIGNATURE = b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1"
SECTOR = 4096                   # Version 4.
MINI_SECTOR = 64
MINI_CUTOFF = 4096
DIFSECT = 0xFFFFFFFC
FATSECT = 0xFFFFFFFD
ENDOFCHAIN = 0xFFFFFFFE
FREESECT = 0xFFFFFFFF
NOSTREAM = 0xFFFFFFFF
_PER_SECTOR = SECTOR // 4
_DIR_ENTRY = struct.Struct("<64sHBBIII16sIQQIQ")
_RED, _BLACK = 0, 1
_STORAGE, _STREAM, _ROOT = 1, 2, 5

# Corpus: the root entry of all 623 files (Max 2008-2018) has this CLSID, {1CDD8C7B-81C0-45A0-9FED-04143144CC1E}.
MAX_ROOT_CLSID = uuid.UUID("1cdd8c7b-81c0-45a0-9fed-04143144cc1e")


class _Entry:
    __slots__ = ("name", "kind", "data", "children", "id", "left", "right", "child", "color", "start", "size",
                 "clsid", "mtime")

    def __init__(self, name, kind, data=b""):
        self.name = name
        self.kind = kind
        self.data = data
        self.children = {}
        self.id = None
        self.left = self.right = self.child = NOSTREAM
        self.color = _BLACK
        self.start = ENDOFCHAIN
        self.size = 0
        self.clsid = b"\0" * 16
        self.mtime = 0


def _sort_key(name):
    # [MS-CFB] 2.6.4: compare the length first, then the upper-case names.
    return (len(name), name.upper())


def _build_tree(children):
    """Link ``children`` into a balanced red-black tree; returns the root entry's id."""
    ordered = sorted(children, key=lambda e: _sort_key(e.name))
    depth_of = {}

    def build(lo, hi, depth):
        if lo >= hi:
            return NOSTREAM
        mid = (lo + hi) // 2
        node = ordered[mid]
        depth_of[node.id] = depth
        node.left = build(lo, mid, depth + 1)
        node.right = build(mid + 1, hi, depth + 1)
        return node.id

    root = build(0, len(ordered), 0)
    if ordered:
        deepest = max(depth_of.values())
        full = len(ordered) == (1 << (deepest + 1)) - 1
        for node in ordered:
            # Every path to a leaf has the same number of black nodes once the (incomplete) deepest level is red.
            node.color = _RED if (depth_of[node.id] == deepest and not full and deepest > 0) else _BLACK
    return root


def _chain(fat, sids):
    for a, b in zip(sids, sids[1:]):
        fat[a] = b
    if sids:
        fat[sids[-1]] = ENDOFCHAIN


def _filetime(value):
    return int(value or 0)


def write_compound_file(streams, root_clsid=MAX_ROOT_CLSID, modified=0) -> bytes:
    """
    The bytes of a version 4 Compound File holding ``streams``.

    ``streams`` is a sequence of ``(path, data)`` pairs (``"Name"`` or ``"Storage/Name"``); the directory order
    follows it. ``modified`` is the root entry's modification time as a Windows FILETIME (0: not set).
    """
    root = _Entry("Root Entry", _ROOT)
    root.clsid = root_clsid.bytes_le if root_clsid is not None else b"\0" * 16
    root.mtime = _filetime(modified)
    entries = [root]
    for path, data in streams:
        parts = path.split("/")
        parent = root
        for name in parts[:-1]:
            key = name.upper()
            if key not in parent.children:
                storage = _Entry(name, _STORAGE)
                storage.id = len(entries)
                entries.append(storage)
                parent.children[key] = storage
            parent = parent.children[key]
        if len(parts[-1]) > 31:
            raise ValueError("stream name too long: {!r}".format(parts[-1]))
        entry = _Entry(parts[-1], _STREAM, bytes(data))
        entry.id = len(entries)
        entries.append(entry)
        parent.children[parts[-1].upper()] = entry
    for entry in entries:
        if entry.kind in (_STORAGE, _ROOT):
            entry.child = _build_tree(list(entry.children.values()))

    sectors = []
    fat = {}

    def allocate(data):
        first = len(sectors)
        for offset in range(0, len(data), SECTOR):
            sectors.append(bytes(data[offset:offset + SECTOR]).ljust(SECTOR, b"\0"))
        sids = list(range(first, len(sectors)))
        _chain(fat, sids)
        return sids

    # Big streams first, then the mini stream holding the small ones.
    mini_stream = bytearray()
    mini_fat = []
    for entry in entries:
        if entry.kind != _STREAM:
            continue
        entry.size = len(entry.data)
        if entry.size == 0:
            entry.start = ENDOFCHAIN
        elif entry.size >= MINI_CUTOFF:
            entry.start = allocate(entry.data)[0]
    for entry in entries:
        if entry.kind != _STREAM or entry.size == 0 or entry.size >= MINI_CUTOFF:
            continue
        first = len(mini_stream) // MINI_SECTOR
        count = -(-entry.size // MINI_SECTOR)
        mini_stream += entry.data.ljust(count * MINI_SECTOR, b"\0")
        sids = list(range(first, first + count))
        mini_fat.extend([FREESECT] * count)
        for a, b in zip(sids, sids[1:]):
            mini_fat[a] = b
        mini_fat[sids[-1]] = ENDOFCHAIN
        entry.start = sids[0]
    if mini_stream:
        root.start = allocate(bytes(mini_stream))[0]
        root.size = len(mini_stream)
        packed = struct.pack("<{:d}I".format(len(mini_fat)), *mini_fat)
        packed += struct.pack("<I", FREESECT) * ((-len(mini_fat)) % _PER_SECTOR)
        mini_fat_sids = allocate(packed)
    else:
        mini_fat_sids = []

    directory = bytearray()
    for entry in entries:
        name = entry.name.encode("utf-16-le") + b"\0\0"
        directory += _DIR_ENTRY.pack(name, len(name), entry.kind, entry.color, entry.left, entry.right,
                                     entry.child, entry.clsid, 0, 0, entry.mtime, entry.start, entry.size)
    while len(directory) % SECTOR:
        directory += _DIR_ENTRY.pack(b"", 0, 0, 0, NOSTREAM, NOSTREAM, NOSTREAM, b"\0" * 16, 0, 0, 0, 0, 0)
    dir_sids = allocate(bytes(directory))

    # FAT (and DIFAT) sectors must also describe themselves.
    used = len(sectors)
    n_fat = 1
    while True:
        n_difat = max(0, -(-(n_fat - 109) // (_PER_SECTOR - 1)))
        if used + n_fat + n_difat <= n_fat * _PER_SECTOR:
            break
        n_fat += 1
    difat_sids = list(range(used, used + n_difat))
    fat_sids = list(range(used + n_difat, used + n_difat + n_fat))
    for sid in difat_sids:
        fat[sid] = DIFSECT
    for sid in fat_sids:
        fat[sid] = FATSECT
    rest = fat_sids[109:]
    for i, sid in enumerate(difat_sids):
        part = rest[i * (_PER_SECTOR - 1):(i + 1) * (_PER_SECTOR - 1)]
        values = part + [FREESECT] * (_PER_SECTOR - 1 - len(part))
        values.append(difat_sids[i + 1] if i + 1 < len(difat_sids) else ENDOFCHAIN)
        sectors.append(struct.pack("<{:d}I".format(_PER_SECTOR), *values))
    table = [fat.get(i, FREESECT) for i in range(n_fat * _PER_SECTOR)]
    for i in range(n_fat):
        sectors.append(struct.pack("<{:d}I".format(_PER_SECTOR), *table[i * _PER_SECTOR:(i + 1) * _PER_SECTOR]))

    header_difat = fat_sids[:109] + [FREESECT] * (109 - min(109, len(fat_sids)))
    header = struct.pack(
        "<8s16sHHHHH6sIIIIIIIII",
        SIGNATURE, b"\0" * 16,
        0x003E, 4,                  # Minor version 0x3E (all corpus files), major version 4.
        0xFFFE, 12, 6, b"\0" * 6,   # Little-endian, 4096-byte sectors, 64-byte mini sectors.
        len(dir_sids), n_fat, dir_sids[0], 0, MINI_CUTOFF,
        mini_fat_sids[0] if mini_fat_sids else ENDOFCHAIN, len(mini_fat_sids),
        difat_sids[0] if difat_sids else ENDOFCHAIN, n_difat,
    ) + struct.pack("<109I", *header_difat)
    return header.ljust(SECTOR, b"\0") + b"".join(sectors)
