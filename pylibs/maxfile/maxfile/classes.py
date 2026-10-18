# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Class directory and DLL directory.

Every object in the ``Scene`` stream is tagged with an index into the *class directory*, which names the class
(class ID, superclass ID, name) and the plugin DLL that implements it (an index into the *DLL directory*).
See ``docs/format/overview.md`` §2.3 and §2.4. Verified on the 623 files of the local corpus (Max 2008-2018).

The mapping from class IDs to human names and decoders is in :mod:`maxfile.registry`.
"""

__all__ = (
    "ClassID",
    "ClassEntry",
    "ClassDirectory",
    "DllEntry",
    "DllDirectory",
    "CLASS_DIRECTORY_STREAMS",
    "DLL_DIRECTORY_STREAM",
    "parse_class_directory",
    "parse_dll_directory",
)

import dataclasses
import struct

from .chunks import Chunk, ChunkStream

# Every corpus file (Max 2008-2018) has "ClassDirectory3". Older files presumably use "ClassDirectory" (none in
# the corpus to check).
CLASS_DIRECTORY_STREAMS = ("ClassDirectory3", "ClassDirectory")
DLL_DIRECTORY_STREAM = "DllDirectory"

# Class directory (verified, overview.md §2.3): one 0x2040 container per class, in class-index order.
CHUNK_CLASS_ENTRY = 0x2040
CHUNK_CLASS_HEADER = 0x2060     # u32 dll_index, u32 class_id_a, u32 class_id_b, u32 superclass_id
CHUNK_CLASS_NAME = 0x2042       # UTF-16LE
# DLL directory (verified, overview.md §2.4): a 0x21C0 header, then one 0x2038 container per DLL.
CHUNK_DLL_HEADER = 0x21C0       # u32: low u16 build (?), high u16 = Max release x 1000 (e.g. 20000 = Max 2018)
CHUNK_DLL_ENTRY = 0x2038
CHUNK_DLL_FILE = 0x2037         # UTF-16LE file name, e.g. "mtl.dlt"
CHUNK_DLL_DESCRIPTION = 0x2039  # UTF-16LE description, e.g. "Standard Materials and Textures (Autodesk)"
CHUNK_DLL_STRINGS = (CHUNK_DLL_FILE, CHUNK_DLL_DESCRIPTION)
# dll_index values meaning "built into the core, no DLL": 0xFFFFFFFF (most) and 0xFFFFFFFE (a few classes).
DLL_NONE = (0xFFFFFFFF, 0xFFFFFFFE)

_CLASS_HEADER = struct.Struct("<IIII")


@dataclasses.dataclass(frozen=True, slots=True, order=True)
class ClassID:
    """
    A class ID: two 32-bit words, ``a`` first on disk.

    ``str()`` gives the two-word form ``0x1BF8338D, 0x192F6098``; :attr:`u64` / :meth:`u64_str` give the single
    64-bit form used in ``docs/format/overview.md`` (``0x192F60981BF8338D``), with ``a`` in the low half.
    """
    a: int
    b: int = 0

    @classmethod
    def from_u64(cls, value: int) -> "ClassID":
        """Build from the 64-bit form (``a`` = low 32 bits; verified: Editable Poly is stored as a, b below)."""
        return cls(value & 0xFFFFFFFF, (value >> 32) & 0xFFFFFFFF)

    @property
    def u64(self) -> int:
        return (self.b << 32) | self.a

    def u64_str(self) -> str:
        return "0x{:016X}".format(self.u64)

    def __str__(self) -> str:
        return "0x{:08X}, 0x{:08X}".format(self.a, self.b)

    def __format__(self, spec: str) -> str:
        return format(str(self), spec)


@dataclasses.dataclass(slots=True, eq=False)
class DllEntry:
    """One entry of the DLL directory."""
    index: int
    strings: dict[int, str]     # Chunk type (0x2037, 0x2039) -> text.
    chunk: Chunk = dataclasses.field(repr=False)

    @property
    def file_name(self) -> str | None:
        """The plugin file name (chunk 0x2037), e.g. ``"mtl.dlt"``."""
        return self.strings.get(CHUNK_DLL_FILE)

    @property
    def description(self) -> str | None:
        """The plugin description (chunk 0x2039)."""
        return self.strings.get(CHUNK_DLL_DESCRIPTION)

    def label(self) -> str:
        """File name and description, for display."""
        parts = [s for s in (self.file_name, self.description) if s]
        parts.extend(self.strings[t] for t in sorted(self.strings) if t not in CHUNK_DLL_STRINGS)
        return " | ".join(parts) or "(no strings)"


@dataclasses.dataclass(slots=True)
class DllDirectory:
    """The DLL directory: plugin DLLs referenced by the class directory."""
    entries: list[DllEntry]
    warnings: list[str] = dataclasses.field(default_factory=list)
    header: int | None = None
    """The 0x21C0 header value; its high 16 bits are the Max release x 1000 (see :attr:`max_release`)."""

    @property
    def max_release(self) -> int | None:
        """Max release number the file was saved with, x 1000 (e.g. 20000 = Max 2018, 12900 = Max 2010)."""
        return self.header >> 16 if self.header is not None else None

    def __len__(self):
        return len(self.entries)

    def __getitem__(self, index) -> DllEntry:
        return self.entries[index]

    def get(self, index: int) -> DllEntry | None:
        """The entry at ``index``, or None when out of range (0xFFFFFFFF / 0xFFFFFFFE: built-in classes)."""
        return self.entries[index] if 0 <= index < len(self.entries) else None


@dataclasses.dataclass(slots=True, eq=False)
class ClassEntry:
    """One entry of the class directory. ``index`` is the value scene objects of this class use as chunk type."""
    index: int
    name: str | None                # Class name as stored in the file.
    class_id: ClassID | None
    superclass_id: int | None
    dll_index: int | None           # Raw value; see ``dll``.
    dll: DllEntry | None = None     # Resolved DLL entry; None when dll_index is out of range.
    chunk: Chunk | None = dataclasses.field(default=None, repr=False)
    error: str | None = None        # Why the entry couldn't be read completely.

    def label(self) -> str:
        """Short display form: the stored name, or the class ID when there is none."""
        if self.name:
            return self.name
        if self.class_id is not None:
            return "<{:s}>".format(self.class_id)
        return "<class #{:d}>".format(self.index)


@dataclasses.dataclass(slots=True)
class ClassDirectory:
    """The class directory of a file."""
    stream_name: str | None         # The stream it was read from, None when the file has none.
    entries: list[ClassEntry]
    warnings: list[str] = dataclasses.field(default_factory=list)

    def __len__(self):
        return len(self.entries)

    def __getitem__(self, index) -> ClassEntry:
        return self.entries[index]

    def get(self, index: int) -> ClassEntry | None:
        """The entry at ``index`` (a scene object's chunk type), or None when out of range."""
        return self.entries[index] if 0 <= index < len(self.entries) else None


def parse_dll_directory(stream: ChunkStream | None) -> DllDirectory:
    """Read the DLL directory from its chunk stream (None gives an empty directory)."""
    if stream is None:
        return DllDirectory([], ["no {:s} stream".format(DLL_DIRECTORY_STREAM)])
    warnings = list(stream.warnings)
    if stream.error:
        warnings.append("{:s}: {:s}".format(stream.name, stream.error))
    entries = []
    header = None
    # Verified on 623 corpus files: a 0x21C0 header, then 0x2038 entries; the class directory's dll_index counts
    # the 0x2038 entries only (so the header is not entry 0).
    for chunk in stream.chunks:
        if chunk.type == CHUNK_DLL_HEADER and not chunk.is_container:
            if chunk.payload_size >= 4:
                header = struct.unpack_from("<I", chunk.data)[0]
            continue
        if chunk.type != CHUNK_DLL_ENTRY:
            warnings.append("{:s}: unexpected top-level chunk 0x{:04X} skipped".format(stream.name, chunk.type))
            continue
        index = len(entries)
        strings = {}
        if chunk.is_container:
            for child in chunk.children:
                if child.type in CHUNK_DLL_STRINGS:
                    strings[child.type] = child.string()
            if chunk.error:
                warnings.append("{:s} entry {:d}: {:s}".format(stream.name, index, chunk.error))
        entries.append(DllEntry(index, strings, chunk))
    return DllDirectory(entries, warnings, header)


def parse_class_directory(stream: ChunkStream | None, dlls: DllDirectory | None = None) -> ClassDirectory:
    """Read the class directory from its chunk stream (None gives an empty directory)."""
    if stream is None:
        return ClassDirectory(None, [], ["no class directory stream ({:s})".format(
            " / ".join(CLASS_DIRECTORY_STREAMS))])
    warnings = list(stream.warnings)
    if stream.error:
        warnings.append("{:s}: {:s}".format(stream.name, stream.error))
    entries = []
    # Verified (623 corpus files): every top-level chunk is a 0x2040 class entry; its position is the class index.
    for index, chunk in enumerate(stream.chunks):
        entry = ClassEntry(index, None, None, None, None, chunk=chunk)
        entries.append(entry)
        header = chunk.find(CHUNK_CLASS_HEADER)
        if not chunk.is_container:
            entry.error = "entry is a leaf chunk (type 0x{:04X}), expected a container".format(chunk.type)
        elif header is None:
            entry.error = "no 0x{:04X} header chunk".format(CHUNK_CLASS_HEADER)
        elif header.payload_size < _CLASS_HEADER.size:
            entry.error = "0x{:04X} header is {:d} bytes, expected {:d}".format(
                CHUNK_CLASS_HEADER, header.payload_size, _CLASS_HEADER.size)
        else:
            # Verified: u32 dll_index, then the class ID words a, b, then the superclass ID.
            dll_index, a, b, superclass = _CLASS_HEADER.unpack_from(header.data)
            entry.dll_index = dll_index
            entry.class_id = ClassID(a, b)
            entry.superclass_id = superclass
            if dlls is not None and dll_index not in DLL_NONE:
                entry.dll = dlls.get(dll_index)
                if entry.dll is None:
                    warnings.append("{:s} entry {:d}: DLL index {:d} outside the DLL directory".format(
                        stream.name, index, dll_index))
        name = chunk.find(CHUNK_CLASS_NAME)
        if name is not None:
            entry.name = name.string()
        if chunk.error:
            entry.error = chunk.error if entry.error is None else entry.error + "; " + chunk.error
        if entry.error:
            warnings.append("{:s} entry {:d}: {:s}".format(stream.name, index, entry.error))
    return ClassDirectory(stream.name, entries, warnings)
