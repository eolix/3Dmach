# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Compound File Binary (OLE2 / "structured storage") container access.

`.max` files are stored in the Compound File Binary format, which Microsoft documents publicly as [MS-CFB]:
https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-cfb/

This module is written from that specification and knows nothing about `.max` files. In short:

- The file is a sequence of fixed-size *sectors* (512 bytes in version 3, 4096 bytes in version 4) after a
  header. Sector ``n`` starts at byte ``(n + 1) * sector_size`` ([MS-CFB] 2.2).
- The *FAT* (file allocation table) is an array of sector numbers: ``fat[n]`` is the sector that follows ``n``
  in its chain. The FAT's own sectors are listed by the *DIFAT*: 109 entries in the header, the rest in a chain
  of DIFAT sectors ([MS-CFB] 2.3, 2.5).
- Streams smaller than the *mini stream cutoff* (4096 bytes) live in the *mini stream*, which is cut into
  64-byte mini sectors chained by the *mini FAT* ([MS-CFB] 2.4). The mini stream itself is the data of the root
  directory entry.
- The *directory* is a chain of 128-byte entries. Each storage's children form a red-black tree through their
  left/right sibling links; the storage points at the tree's root with its child link ([MS-CFB] 2.6).

Everything the reader finds wrong raises :class:`~maxfile.errors.ContainerError` (or a subclass) with a message
that names the broken structure. Sector chains and the directory tree are checked for cycles and out-of-range
indices, so a corrupt file can't make the reader loop or index outside the file.
"""

__all__ = (
    "CFB_SIGNATURE",
    "has_cfb_signature",
    "is_compound_file",
    "CompoundFile",
    "DirEntry",
)

import array
import dataclasses
import mmap
import os
import struct
import sys

from .errors import ContainerError, NotCompoundFileError, StreamNotFoundError, UnsupportedFormatError

# First 8 bytes of every Compound File ([MS-CFB] section 2.2, "Header Signature").
CFB_SIGNATURE = b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1"

# Special sector numbers ([MS-CFB] 2.1).
MAXREGSECT = 0xFFFFFFFA
DIFSECT = 0xFFFFFFFC
FATSECT = 0xFFFFFFFD
ENDOFCHAIN = 0xFFFFFFFE
FREESECT = 0xFFFFFFFF
# "No entry" in directory sibling/child links ([MS-CFB] 2.6.1).
NOSTREAM = 0xFFFFFFFF

HEADER_DIFAT_COUNT = 109
DIRENTRY_SIZE = 128
MINI_SECTOR_SHIFT = 6
MINI_STREAM_CUTOFF = 4096

# Header fields up to the in-header DIFAT array ([MS-CFB] 2.2).
_HEADER = struct.Struct("<8s16s5H6s9I")
# One directory entry ([MS-CFB] 2.6.1).
_DIRENTRY = struct.Struct("<64sHBBIII16sIQQIQ")

# Directory entry object types.
_TYPE_UNALLOCATED = 0
_TYPE_STORAGE = 1
_TYPE_STREAM = 2
_TYPE_ROOT = 5
_KIND_NAMES = {_TYPE_STORAGE: "storage", _TYPE_STREAM: "stream", _TYPE_ROOT: "root"}


def has_cfb_signature(data: bytes) -> bool:
    """Return True when ``data`` starts with the Compound File signature."""
    return data[:len(CFB_SIGNATURE)] == CFB_SIGNATURE


def is_compound_file(path: str | os.PathLike) -> bool:
    """
    Return True when the file at ``path`` starts with the Compound File signature.

    This is a cheap sniff, not a validation: a True result does not mean the file is a
    readable ``.max`` scene. Raises ``OSError`` when the file cannot be read.
    """
    with open(path, "rb") as fh:
        return has_cfb_signature(fh.read(len(CFB_SIGNATURE)))


@dataclasses.dataclass(frozen=True, slots=True)
class DirEntry:
    """A storage or stream in the container's directory."""
    id: int                     # Index of the entry in the directory.
    name: str
    kind: str                   # "root", "storage" or "stream".
    path: tuple[str, ...]       # Names from the root (excluded) down to this entry.
    size: int                   # Stream size in bytes (for the root: size of the mini stream).
    start_sector: int
    in_mini_stream: bool        # True when the data lives in the mini stream.

    @property
    def path_str(self) -> str:
        """The path joined with ``/``, e.g. ``"Scene"`` or ``"Storage/Stream"``."""
        return "/".join(self.path)


def _u32_array(data) -> array.array:
    values = array.array("I")
    if values.itemsize != 4:  # pragma: no cover - no supported platform has a 2-byte unsigned int.
        values = array.array("L")
    values.frombytes(data)
    if sys.byteorder == "big":  # pragma: no cover
        values.byteswap()
    return values


class CompoundFile:
    """
    A read-only Compound File.

    ``source`` is a path (the file is memory-mapped and must be closed: use the object as a context manager or
    call :meth:`close`), or a bytes-like object holding the whole file.

    Construction reads and checks the header, the FAT, the mini FAT and the directory; stream data is read on
    demand with :meth:`read_stream`. Names are matched case-insensitively, as in [MS-CFB].
    """

    def __init__(self, source):
        self._fh = None
        self._mmap = None
        if isinstance(source, (str, os.PathLike)):
            self._fh = open(source, "rb")
            try:
                size = os.fstat(self._fh.fileno()).st_size
                if size == 0:
                    buf = b""
                else:
                    try:
                        self._mmap = mmap.mmap(self._fh.fileno(), 0, access=mmap.ACCESS_READ)
                        buf = self._mmap
                    except (OSError, ValueError):
                        buf = self._fh.read()
            except BaseException:
                self.close()
                raise
        else:
            buf = source
        self._buf = buf
        self._size = len(buf)
        self.warnings: list[str] = []
        """Non-fatal oddities found while reading the container."""
        try:
            self._read_header()
            self._read_fat()
            self._read_directory()
            self._read_mini_fat()
        except BaseException:
            self.close()
            raise

    # -------------------------------------------------------------------------
    # Public API

    def close(self):
        """Release the file. Reading streams after this raises ``ValueError``."""
        if self._mmap is not None:
            self._mmap.close()
            self._mmap = None
        if self._fh is not None:
            self._fh.close()
            self._fh = None
        self._buf = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    @property
    def entries(self) -> list[DirEntry]:
        """All storages and streams reachable from the root (root excluded), sorted by path."""
        return list(self._entries)

    def streams(self) -> list[DirEntry]:
        """All streams, sorted by path."""
        return [e for e in self._entries if e.kind == "stream"]

    def storages(self) -> list[DirEntry]:
        """All storages (excluding the root), sorted by path."""
        return [e for e in self._entries if e.kind == "storage"]

    def find(self, name) -> DirEntry | None:
        """
        Look up a storage or stream by name, case-insensitively.

        ``name`` is a single name (``"Scene"``), a ``/``-separated path (``"Storage/Stream"``) or a tuple of names.
        """
        return self._by_path.get(self._key(name))

    def read_stream(self, name) -> bytes:
        """
        Return the whole contents of a stream (see :meth:`find` for ``name``).

        Raises :class:`~maxfile.errors.StreamNotFoundError` when there is no such stream and
        :class:`~maxfile.errors.ContainerError` when its sector chain is broken.
        """
        entry = self.find(name)
        if entry is None or entry.kind != "stream":
            label = name if isinstance(name, str) else "/".join(name)
            if entry is None:
                raise StreamNotFoundError("no stream named {!r} in the file".format(label))
            raise StreamNotFoundError("{!r} is a storage, not a stream".format(label))
        return self._read_entry(entry)

    # -------------------------------------------------------------------------
    # Header ([MS-CFB] 2.2)

    def _read_header(self):
        if self._size < 512 or not has_cfb_signature(self._buf[:8]):
            if has_cfb_signature(self._buf[:8]):
                raise ContainerError("file is truncated: {:d} bytes, shorter than the 512-byte header".format(
                    self._size))
            raise NotCompoundFileError("not a Compound File (missing D0 CF 11 E0 A1 B1 1A E1 signature)")
        (_sig, _clsid, _minor, major, byte_order, sector_shift, mini_shift, _reserved,
         num_dir_sectors, num_fat_sectors, first_dir, _txn, cutoff,
         first_mini_fat, num_mini_fat, first_difat, num_difat) = _HEADER.unpack_from(self._buf, 0)

        if byte_order != 0xFFFE:
            raise ContainerError("bad byte order mark 0x{:04X} in header (expected 0xFFFE)".format(byte_order))
        if major == 3:
            expected_shift = 9
        elif major == 4:
            expected_shift = 12
        else:
            raise UnsupportedFormatError("unsupported Compound File major version {:d} (expected 3 or 4)".format(
                major))
        if sector_shift != expected_shift:
            raise ContainerError("sector shift {:d} doesn't match version {:d} (expected {:d})".format(
                sector_shift, major, expected_shift))
        if mini_shift != MINI_SECTOR_SHIFT:
            raise ContainerError("mini sector shift {:d} (expected {:d})".format(mini_shift, MINI_SECTOR_SHIFT))
        if cutoff != MINI_STREAM_CUTOFF:
            raise ContainerError("mini stream cutoff {:d} (expected {:d})".format(cutoff, MINI_STREAM_CUTOFF))

        self.version = major
        """Compound File major version: 3 (512-byte sectors) or 4 (4096-byte sectors)."""
        self.sector_size = 1 << sector_shift
        self.mini_sector_size = 1 << mini_shift
        self.mini_stream_cutoff = cutoff
        self._shift = sector_shift
        if self._size < self.sector_size:
            raise ContainerError("file is truncated: {:d} bytes, shorter than the {:d}-byte header".format(
                self._size, self.sector_size))
        # Sectors after the header; the last one may be cut short in a truncated file.
        self._num_sectors = (self._size - self.sector_size + self.sector_size - 1) >> sector_shift
        if major == 3 and num_dir_sectors != 0:
            self.warnings.append("version 3 header has a non-zero directory sector count ({:d})".format(
                num_dir_sectors))
        for label, count in (("FAT", num_fat_sectors), ("DIFAT", num_difat), ("mini FAT", num_mini_fat)):
            if count > self._num_sectors:
                raise ContainerError("header claims {:d} {:s} sectors but the file only has {:d} sectors".format(
                    count, label, self._num_sectors))
        self._num_fat_sectors = num_fat_sectors
        self._first_dir = first_dir
        self._first_mini_fat = first_mini_fat
        self._num_mini_fat = num_mini_fat
        self._first_difat = first_difat
        self._num_difat = num_difat
        self._header_difat = struct.unpack_from("<{:d}I".format(HEADER_DIFAT_COUNT), self._buf, _HEADER.size)

    # -------------------------------------------------------------------------
    # Sector helpers

    def _check_sector(self, sid, what):
        if sid > MAXREGSECT or sid >= self._num_sectors:
            raise ContainerError("{:s}: sector {:s} is outside the file ({:d} sectors)".format(
                what, _sector_label(sid), self._num_sectors))

    def _sector(self, sid, what) -> bytes:
        """The full bytes of one sector; raises when the file ends inside it."""
        self._check_sector(sid, what)
        start = (sid + 1) << self._shift
        data = self._buf[start:start + self.sector_size]
        if len(data) != self.sector_size:
            raise ContainerError("{:s}: sector {:d} is cut short, the file is truncated".format(what, sid))
        return data

    @staticmethod
    def _chain(start, table, limit, what, unit="sector"):
        """
        Follow a chain through ``table`` (FAT or mini FAT) from ``start``.

        Returns at most ``limit`` sector numbers. Raises on out-of-range links and cycles.
        """
        sids = []
        seen = set()
        sid = start
        count = len(table)
        while sid != ENDOFCHAIN and len(sids) < limit:
            if sid >= count:
                raise ContainerError("{:s}: {:s} chain points to {:s} {:s}, beyond the allocation table ({:d} "
                                     "entries)".format(what, unit, unit, _sector_label(sid), count))
            if sid in seen:
                raise ContainerError("{:s}: {:s} chain loops back to {:s} {:d}".format(what, unit, unit, sid))
            seen.add(sid)
            sids.append(sid)
            sid = table[sid]
        return sids

    def _gather(self, sids, size, what) -> bytes:
        """Concatenate regular sectors ``sids`` and cut the result to ``size`` bytes."""
        parts = []
        remaining = size
        ss = self.sector_size
        i = 0
        n = len(sids)
        # Contiguous runs are copied in one slice: most writers allocate streams sequentially.
        while i < n and remaining > 0:
            first = sids[i]
            self._check_sector(first, what)
            j = i + 1
            while j < n and sids[j] == sids[j - 1] + 1:
                j += 1
            last = sids[j - 1]
            self._check_sector(last, what)
            start = (first + 1) << self._shift
            length = min((j - i) * ss, remaining)
            part = self._buf[start:start + length]
            if len(part) != length:
                raise ContainerError("{:s}: data runs past the end of the file, the file is truncated".format(what))
            parts.append(part)
            remaining -= length
            i = j
        if remaining > 0:
            raise ContainerError("{:s}: sector chain ends after {:d} of {:d} bytes".format(
                what, size - remaining, size))
        return b"".join(parts)

    # -------------------------------------------------------------------------
    # FAT via DIFAT ([MS-CFB] 2.3, 2.5)

    def _read_fat(self):
        wanted = self._num_fat_sectors
        fat_sids = [sid for sid in self._header_difat[:min(wanted, HEADER_DIFAT_COUNT)]]
        if wanted > HEADER_DIFAT_COUNT:
            per_sector = self.sector_size // 4 - 1
            sid = self._first_difat
            seen = set()
            while len(fat_sids) < wanted:
                if sid == ENDOFCHAIN or sid == FREESECT:
                    raise ContainerError("DIFAT chain ends after {:d} of {:d} FAT sectors".format(
                        len(fat_sids), wanted))
                if sid in seen:
                    raise ContainerError("DIFAT chain loops back to sector {:d}".format(sid))
                seen.add(sid)
                values = struct.unpack("<{:d}I".format(per_sector + 1), self._sector(sid, "DIFAT"))
                fat_sids.extend(values[:min(per_sector, wanted - len(fat_sids))])
                sid = values[-1]
            if len(seen) != self._num_difat:
                self.warnings.append("header says {:d} DIFAT sectors, the chain has {:d}".format(
                    self._num_difat, len(seen)))
        seen = set()
        fat = _u32_array(b"")
        for index, sid in enumerate(fat_sids):
            if sid in seen:
                raise ContainerError("FAT sector {:d} is listed twice in the DIFAT".format(sid))
            seen.add(sid)
            fat.frombytes(self._sector(sid, "FAT sector #{:d}".format(index)))
        if sys.byteorder == "big":  # pragma: no cover
            fat.byteswap()
        self._fat = fat

    # -------------------------------------------------------------------------
    # Directory ([MS-CFB] 2.6)

    def _read_directory(self):
        sids = self._chain(self._first_dir, self._fat, len(self._fat), "directory")
        if not sids:
            raise ContainerError("the directory is empty (no root entry)")
        raw = []
        for sid in sids:
            data = self._sector(sid, "directory")
            for offset in range(0, len(data), DIRENTRY_SIZE):
                raw.append(self._parse_dir_entry(data, offset, len(raw)))

        root = raw[0]
        if root is None or root[1] != _TYPE_ROOT:
            raise ContainerError("directory entry 0 is not the root entry")
        root_name, _, _, _, root_child, root_start, root_size = root
        self._root = DirEntry(0, root_name, "root", (), root_size, root_start, False)

        entries = []
        visited = {0}
        # Iterative walk: storages can nest deeply in a corrupt file, and sibling trees can be degenerate lists.
        stack = [(root_child, (), "root entry")]
        while stack:
            eid, parent_path, linked_from = stack.pop()
            if eid == NOSTREAM:
                continue
            if eid >= len(raw):
                raise ContainerError("directory link from {:s} points to entry {:d}, beyond the directory ({:d} "
                                     "entries)".format(linked_from, eid, len(raw)))
            if eid in visited:
                raise ContainerError("directory tree has a cycle: entry {:d} is reached twice".format(eid))
            visited.add(eid)
            item = raw[eid]
            if item is None:
                raise ContainerError("directory link from {:s} points to unused entry {:d}".format(linked_from, eid))
            name, obj_type, left, right, child, start, size = item
            if obj_type == _TYPE_ROOT:
                raise ContainerError("directory entry {:d} is a second root entry".format(eid))
            path = parent_path + (name,)
            in_mini = obj_type == _TYPE_STREAM and size < self.mini_stream_cutoff
            entries.append(DirEntry(eid, name, _KIND_NAMES[obj_type], path, size, start, in_mini))
            label = "entry {:d}".format(eid)
            stack.append((right, parent_path, label))
            stack.append((left, parent_path, label))
            if obj_type == _TYPE_STORAGE:
                stack.append((child, path, label))
            elif child != NOSTREAM:
                self.warnings.append("stream entry {:d} ({!r}) has a child link; ignored".format(eid, name))

        entries.sort(key=lambda e: tuple(n.upper() for n in e.path))
        self._entries = entries
        self._by_path = {}
        for entry in entries:
            key = tuple(n.upper() for n in entry.path)
            if key in self._by_path:
                self.warnings.append("duplicate directory name {!r}; using the first".format(entry.path_str))
                continue
            self._by_path[key] = entry

    def _parse_dir_entry(self, data, offset, eid):
        (name_raw, name_len, obj_type, _color, left, right, child, _clsid, _state, _ctime, _mtime,
         start, size) = _DIRENTRY.unpack_from(data, offset)
        if obj_type == _TYPE_UNALLOCATED:
            return None
        if obj_type not in _KIND_NAMES:
            raise ContainerError("directory entry {:d} has unknown object type {:d}".format(eid, obj_type))
        if name_len > 64 or name_len % 2:
            raise ContainerError("directory entry {:d} has a bad name length {:d}".format(eid, name_len))
        # The length includes the terminating null character.
        name = name_raw[:max(name_len - 2, 0)].decode("utf-16-le", errors="replace")
        if self.version == 3:
            # [MS-CFB] 2.6.3: version 3 writers may leave garbage in the high 32 bits of the size.
            size &= 0xFFFFFFFF
        return (name, obj_type, left, right, child, start, size)

    # -------------------------------------------------------------------------
    # Mini FAT and mini stream ([MS-CFB] 2.4)

    def _read_mini_fat(self):
        self._mini_stream = None
        if self._num_mini_fat == 0 or self._first_mini_fat == ENDOFCHAIN:
            self._mini_fat = _u32_array(b"")
            return
        sids = self._chain(self._first_mini_fat, self._fat, len(self._fat), "mini FAT")
        if len(sids) != self._num_mini_fat:
            self.warnings.append("header says {:d} mini FAT sectors, the chain has {:d}".format(
                self._num_mini_fat, len(sids)))
        self._mini_fat = _u32_array(b"".join(self._sector(sid, "mini FAT") for sid in sids))

    def _get_mini_stream(self) -> bytes:
        if self._mini_stream is None:
            root = self._root
            if root.size == 0:
                self._mini_stream = b""
            else:
                needed = (root.size + self.sector_size - 1) >> self._shift
                sids = self._chain(root.start_sector, self._fat, needed, "mini stream")
                self._mini_stream = self._gather(sids, root.size, "mini stream")
        return self._mini_stream

    # -------------------------------------------------------------------------
    # Stream data

    def _read_entry(self, entry: DirEntry) -> bytes:
        if self._buf is None:
            raise ValueError("I/O operation on a closed CompoundFile")
        what = "stream {!r}".format(entry.path_str)
        if entry.size == 0:
            return b""
        if not entry.in_mini_stream:
            needed = (entry.size + self.sector_size - 1) >> self._shift
            sids = self._chain(entry.start_sector, self._fat, needed, what)
            return self._gather(sids, entry.size, what)

        mini = self._get_mini_stream()
        mss = self.mini_sector_size
        needed = (entry.size + mss - 1) // mss
        sids = self._chain(entry.start_sector, self._mini_fat, needed, what, unit="mini sector")
        if len(sids) < needed:
            raise ContainerError("{:s}: mini sector chain ends after {:d} of {:d} mini sectors".format(
                what, len(sids), needed))
        view = memoryview(mini)
        parts = []
        remaining = entry.size
        for sid in sids:
            start = sid * mss
            length = min(mss, remaining)
            if start + length > len(mini):
                raise ContainerError("{:s}: mini sector {:d} is outside the mini stream ({:d} bytes)".format(
                    what, sid, len(mini)))
            parts.append(view[start:start + length])
            remaining -= length
        return b"".join(parts)

    @staticmethod
    def _key(name) -> tuple[str, ...]:
        if isinstance(name, str):
            parts = [p for p in name.split("/") if p]
        else:
            parts = list(name)
        return tuple(p.upper() for p in parts)


def _sector_label(sid) -> str:
    names = {DIFSECT: "DIFSECT", FATSECT: "FATSECT", ENDOFCHAIN: "ENDOFCHAIN", FREESECT: "FREESECT"}
    return names.get(sid, "{:d}".format(sid))
