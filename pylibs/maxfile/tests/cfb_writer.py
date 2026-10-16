# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
A minimal Compound File *writer*, for building test fixtures.

Written from Microsoft's public [MS-CFB] specification, independently of the reader in ``maxfile.container``
(it shares no code with it), so the tests check the reader against the spec rather than against itself.

Layout of the files it writes: stream data sectors, then the mini stream, the mini FAT, the directory, the DIFAT
sectors and the FAT sectors. Every storage's children form a balanced binary search tree ordered as [MS-CFB]
2.6.4 requires (shorter names first, then case-insensitive); all nodes are written black, which readers don't
check.

[MS-CFB]: https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-cfb/
"""

import struct

SIGNATURE = b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1"
DIFSECT = 0xFFFFFFFC
FATSECT = 0xFFFFFFFD
ENDOFCHAIN = 0xFFFFFFFE
FREESECT = 0xFFFFFFFF
NOSTREAM = 0xFFFFFFFF
MINI_SECTOR = 64
CUTOFF = 4096


class _Entry:
    def __init__(self, name, kind, data=b""):
        self.name = name
        self.kind = kind            # 1 storage, 2 stream, 5 root
        self.data = data
        self.children = {}
        self.id = None
        self.left = self.right = self.child = NOSTREAM
        self.start = ENDOFCHAIN
        self.size = 0


def _sort_key(name):
    return (len(name), name.upper())


def _build_tree(children):
    """Assign left/right links for a balanced BST of ``children``; return the root's id."""
    ordered = sorted(children, key=lambda e: _sort_key(e.name))

    def build(lo, hi):
        if lo >= hi:
            return NOSTREAM
        mid = (lo + hi) // 2
        node = ordered[mid]
        node.left = build(lo, mid)
        node.right = build(mid + 1, hi)
        return node.id
    return build(0, len(ordered))


def _chain(fat, sids):
    for a, b in zip(sids, sids[1:]):
        fat[a] = b
    if sids:
        fat[sids[-1]] = ENDOFCHAIN


def build_cfb(streams, version=3, extra_fat_sectors=0, use_mini_stream=True):
    """
    Build a Compound File holding ``streams`` (``{"Name" or "Storage/Name": bytes}``).

    ``extra_fat_sectors`` adds unused FAT sectors (all FREESECT), which is valid and lets a small file need DIFAT
    sectors (more than 109 FAT sectors). Returns ``(file_bytes, layout)``; ``layout`` gives the sector numbers of
    each structure so tests can corrupt them.
    """
    assert version in (3, 4)
    ss = 512 if version == 3 else 4096
    per_fat = ss // 4

    root = _Entry("Root Entry", 5)
    for path, data in streams.items():
        parts = path.split("/")
        parent = root
        for name in parts[:-1]:
            parent = parent.children.setdefault(name.upper(), _Entry(name, 1))
        parent.children[parts[-1].upper()] = _Entry(parts[-1], 2, bytes(data))

    entries = []
    stack = [root]
    while stack:
        entry = stack.pop()
        entry.id = len(entries)
        entries.append(entry)
        stack.extend(sorted(entry.children.values(), key=lambda e: _sort_key(e.name), reverse=True))
    for entry in entries:
        if entry.kind in (1, 5):
            entry.child = _build_tree(list(entry.children.values()))

    layout = {"sector_size": ss, "streams": {}, "mini": {}}
    sectors = []  # Sector contents, in order.
    fat = {}

    def allocate(data):
        first = len(sectors)
        for offset in range(0, len(data), ss):
            sectors.append(data[offset:offset + ss].ljust(ss, b"\0"))
        sids = list(range(first, len(sectors)))
        _chain(fat, sids)
        return sids

    path_of = {}
    stack = [(root, "")]
    while stack:
        entry, prefix = stack.pop()
        for child in entry.children.values():
            path_of[child.id] = prefix + child.name
            stack.append((child, prefix + child.name + "/"))

    mini_stream = bytearray()
    mini_fat = []
    for entry in entries:
        if entry.kind != 2:
            continue
        entry.size = len(entry.data)
        if entry.size == 0:
            continue
        if use_mini_stream and entry.size < CUTOFF:
            first = len(mini_stream) // MINI_SECTOR
            mini_stream += entry.data.ljust(-(-entry.size // MINI_SECTOR) * MINI_SECTOR, b"\0")
            sids = list(range(first, len(mini_stream) // MINI_SECTOR))
            mini_fat.extend([0] * len(sids))
            for a, b in zip(sids, sids[1:]):
                mini_fat[a] = b
            mini_fat[sids[-1]] = ENDOFCHAIN
            entry.start = sids[0]
            layout["mini"][path_of[entry.id]] = sids
        else:
            sids = allocate(entry.data)
            entry.start = sids[0]
            layout["streams"][path_of[entry.id]] = sids

    if mini_stream:
        sids = allocate(bytes(mini_stream))
        root.start = sids[0]
        root.size = len(mini_stream)
        layout["mini_stream"] = sids
        mini_fat_bytes = struct.pack("<{:d}I".format(len(mini_fat)), *mini_fat)
        mini_fat_bytes += struct.pack("<I", FREESECT) * ((-len(mini_fat)) % per_fat)
        layout["mini_fat"] = allocate(mini_fat_bytes)
    else:
        layout["mini_fat"] = []

    directory = bytearray()
    for entry in entries:
        name = entry.name.encode("utf-16-le") + b"\0\0"
        directory += struct.pack(
            "<64sHBBIII16sIQQIQ", name, len(name), entry.kind, 1, entry.left, entry.right, entry.child,
            b"\0" * 16, 0, 0, 0, entry.start, entry.size)
    while len(directory) % ss:
        directory += struct.pack("<64sHBBIII16sIQQIQ", b"", 0, 0, 0, NOSTREAM, NOSTREAM, NOSTREAM,
                                 b"\0" * 16, 0, 0, 0, 0, 0)
    layout["directory"] = allocate(bytes(directory))

    # Number of FAT and DIFAT sectors: they must also cover themselves.
    used = len(sectors)
    n_fat = 1
    while True:
        n_fat_total = n_fat + extra_fat_sectors
        n_difat = max(0, -(-(n_fat_total - 109) // (per_fat - 1)))
        if used + n_fat_total + n_difat <= n_fat_total * per_fat:
            break
        n_fat += 1
    n_fat = n_fat_total
    difat_sids = list(range(used, used + n_difat))
    fat_sids = list(range(used + n_difat, used + n_difat + n_fat))
    for sid in difat_sids:
        fat[sid] = DIFSECT
    for sid in fat_sids:
        fat[sid] = FATSECT
    layout["difat"] = difat_sids
    layout["fat"] = fat_sids

    rest = fat_sids[109:]
    for i, sid in enumerate(difat_sids):
        chunk = rest[i * (per_fat - 1):(i + 1) * (per_fat - 1)]
        values = chunk + [FREESECT] * (per_fat - 1 - len(chunk))
        values.append(difat_sids[i + 1] if i + 1 < len(difat_sids) else ENDOFCHAIN)
        sectors.append(struct.pack("<{:d}I".format(per_fat), *values))
    table = [fat.get(i, FREESECT) for i in range(n_fat * per_fat)]
    for i in range(n_fat):
        sectors.append(struct.pack("<{:d}I".format(per_fat), *table[i * per_fat:(i + 1) * per_fat]))

    header_difat = fat_sids[:109] + [FREESECT] * (109 - min(109, len(fat_sids)))
    header = struct.pack(
        "<8s16sHHHHH6sIIIIIIIII",
        SIGNATURE, b"\0" * 16, 0x003E, version, 0xFFFE, 9 if version == 3 else 12, 6, b"\0" * 6,
        len(layout["directory"]) if version == 4 else 0, n_fat, layout["directory"][0], 0, CUTOFF,
        layout["mini_fat"][0] if layout["mini_fat"] else ENDOFCHAIN, len(layout["mini_fat"]),
        difat_sids[0] if difat_sids else ENDOFCHAIN, n_difat,
    ) + struct.pack("<109I", *header_difat)
    header = header.ljust(ss, b"\0")
    return header + b"".join(sectors), layout


def sector_offset(layout, sid):
    """Byte offset of sector ``sid`` in the file."""
    return (sid + 1) * layout["sector_size"]


def patch_fat(data, layout, sid, value):
    """Return ``data`` with FAT entry ``sid`` set to ``value``."""
    per_fat = layout["sector_size"] // 4
    fat_sector = layout["fat"][sid // per_fat]
    offset = sector_offset(layout, fat_sector) + (sid % per_fat) * 4
    return data[:offset] + struct.pack("<I", value) + data[offset + 4:]


def patch_dir_entry(data, layout, entry_id, field, value):
    """Return ``data`` with one field (``"left"``, ``"right"``, ``"child"``, ``"start"``, ``"size"``) changed."""
    ss = layout["sector_size"]
    per_sector = ss // 128
    sid = layout["directory"][entry_id // per_sector]
    base = sector_offset(layout, sid) + (entry_id % per_sector) * 128
    offset, fmt = {"left": (68, "<I"), "right": (72, "<I"), "child": (76, "<I"), "type": (66, "<B"),
                   "start": (116, "<I"), "size": (120, "<Q"), "name_len": (64, "<H")}[field]
    packed = struct.pack(fmt, value)
    return data[:base + offset] + packed + data[base + offset + len(packed):]
