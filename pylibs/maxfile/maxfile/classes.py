# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Class directory and DLL directory.

Every object in the ``Scene`` stream is tagged with an index into the *class directory*, which names the class
(class ID, superclass ID, name) and the plugin DLL that implements it (an index into the *DLL directory*).
See ``docs/format/overview.md`` §2.3 and §2.4; none of the layouts here are verified on real files yet.

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

# Unverified (overview.md §1): newer files use "ClassDirectory3", older ones presumably "ClassDirectory".
CLASS_DIRECTORY_STREAMS = ("ClassDirectory3", "ClassDirectory")
DLL_DIRECTORY_STREAM = "DllDirectory"

# Chunk types inside a class directory entry (unverified, overview.md §2.3).
CHUNK_CLASS_HEADER = 0x2060     # u32 dll_index, u32 class_id_a, u32 class_id_b, u32 superclass_id
CHUNK_CLASS_NAME = 0x2042       # UTF-16LE
# Chunk types inside a DLL directory entry (unverified, overview.md §2.4). Which one is the file name and which
# the description is not known yet, so they are kept under their chunk types.
CHUNK_DLL_STRINGS = (0x2037, 0x2039)

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
        """Build from the 64-bit form (``a`` = low 32 bits). Unverified word order (overview.md §2.3)."""
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

    def label(self) -> str:
        """All strings, for display."""
        return " | ".join(self.strings[t] for t in sorted(self.strings)) or "(no strings)"


@dataclasses.dataclass(slots=True)
class DllDirectory:
    """The DLL directory: plugin DLLs referenced by the class directory."""
    entries: list[DllEntry]
    warnings: list[str] = dataclasses.field(default_factory=list)

    def __len__(self):
        return len(self.entries)

    def __getitem__(self, index) -> DllEntry:
        return self.entries[index]

    def get(self, index: int) -> DllEntry | None:
        """The entry at ``index``, or None when out of range (built-in classes, presumably)."""
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
    # Unverified (overview.md §2.4): every top-level chunk is one entry, indexed by position.
    for index, chunk in enumerate(stream.chunks):
        strings = {}
        if chunk.is_container:
            for child in chunk.children:
                if child.type in CHUNK_DLL_STRINGS:
                    strings[child.type] = child.string()
            if chunk.error:
                warnings.append("{:s} entry {:d}: {:s}".format(stream.name, index, chunk.error))
        entries.append(DllEntry(index, strings, chunk))
    return DllDirectory(entries, warnings)


def parse_class_directory(stream: ChunkStream | None, dlls: DllDirectory | None = None) -> ClassDirectory:
    """Read the class directory from its chunk stream (None gives an empty directory)."""
    if stream is None:
        return ClassDirectory(None, [], ["no class directory stream ({:s})".format(
            " / ".join(CLASS_DIRECTORY_STREAMS))])
    warnings = list(stream.warnings)
    if stream.error:
        warnings.append("{:s}: {:s}".format(stream.name, stream.error))
    entries = []
    # Unverified (overview.md §2.3): every top-level chunk is one class; its position is the class index.
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
            # Unverified (overview.md §2.3): u32 dll_index, then the class ID words a, b, then the superclass ID.
            dll_index, a, b, superclass = _CLASS_HEADER.unpack_from(header.data)
            entry.dll_index = dll_index
            entry.class_id = ClassID(a, b)
            entry.superclass_id = superclass
            if dlls is not None:
                entry.dll = dlls.get(dll_index)
        name = chunk.find(CHUNK_CLASS_NAME)
        if name is not None:
            entry.name = name.string()
        if chunk.error:
            entry.error = chunk.error if entry.error is None else entry.error + "; " + chunk.error
        if entry.error:
            warnings.append("{:s} entry {:d}: {:s}".format(stream.name, index, entry.error))
    return ClassDirectory(stream.name, entries, warnings)
