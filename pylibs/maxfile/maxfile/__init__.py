# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Reader for .max scene files.

This package must never import Blender modules (`bpy`, `mathutils`, `bmesh`, ...).
It turns a file into plain Python data; `mx_io_max` turns that data into Blender objects.

Typical use::

    import maxfile

    with maxfile.open("scene.max") as mf:
        for node in mf.nodes:
            print(node.name, node.object.class_label() if node.object else None)
        for usage in mf.unknown_classes():
            print("unknown:", usage.entry.label(), usage.count)
        print(mf.warnings)

Every problem caused by the file's contents raises a :class:`MaxFileError` subclass (when the file can't be read
at all) or is collected in :attr:`MaxFile.warnings` (when only part of it is unreadable).
"""

__version__ = "0.1.0"

__all__ = (
    "open",
    "MaxFile",
    "ClassUsage",
    "MaxFileError",
    "ContainerError",
    "NotCompoundFileError",
    "UnsupportedFormatError",
    "StreamNotFoundError",
    "ChunkError",
    "DecodeError",
)

import dataclasses
import functools
import os

from . import registry
from .assets import AssetMetadata, read_asset_metadata
from .chunks import ChunkStream
from .classes import (
    CLASS_DIRECTORY_STREAMS,
    DLL_DIRECTORY_STREAM,
    ClassDirectory,
    ClassEntry,
    DllDirectory,
    parse_class_directory,
    parse_dll_directory,
)
from .container import CompoundFile, DirEntry
from .errors import (
    ChunkError,
    ContainerError,
    DecodeError,
    MaxFileError,
    NotCompoundFileError,
    StreamNotFoundError,
    UnsupportedFormatError,
)
from .scene import SCENE_STREAM, Node, Scene, SceneObject, parse_scene


@dataclasses.dataclass(frozen=True, slots=True)
class ClassUsage:
    """How often a class-directory entry is used by scene objects, and what we know about it."""
    entry: ClassEntry
    count: int
    known: registry.KnownClass | None
    decoder: registry.DecoderInfo | None


class MaxFile:
    """
    An open ``.max`` file. Create with :func:`maxfile.open`.

    The container is read when the file is opened; the class directory, DLL directory and scene are parsed on
    first access and cached.
    """

    def __init__(self, source):
        self.path = os.fspath(source) if isinstance(source, (str, os.PathLike)) else None
        self.container = CompoundFile(source)
        self._streams: dict[str, ChunkStream] = {}
        try:
            # Unverified (overview.md §1): every .max file has a "Scene" stream.
            if self.container.find(SCENE_STREAM) is None:
                raise MaxFileError("no {:s} stream: this Compound File is not a .max scene".format(SCENE_STREAM))
        except BaseException:
            self.close()
            raise

    def close(self):
        """Release the file. Already-parsed data stays usable; reading more streams raises ``ValueError``."""
        self.container.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -------------------------------------------------------------------------
    # Streams

    @property
    def streams(self) -> list[DirEntry]:
        """All streams in the container, sorted by path."""
        return self.container.streams()

    def raw_stream(self, name) -> bytes:
        """A stream's bytes as stored (possibly compressed). Raises :class:`StreamNotFoundError`."""
        return self.container.read_stream(name)

    def stream(self, name) -> ChunkStream:
        """A stream decompressed and parsed as a chunk tree (cached). Raises :class:`StreamNotFoundError`."""
        entry = self.container.find(name)
        if entry is None or entry.kind != "stream":
            return ChunkStream(self.raw_stream(name))  # Raises StreamNotFoundError.
        key = entry.path_str.upper()
        if key not in self._streams:
            self._streams[key] = ChunkStream(self.container.read_stream(entry.path), entry.path_str)
        return self._streams[key]

    def _optional_stream(self, *names) -> ChunkStream | None:
        for name in names:
            if self.container.find(name) is not None:
                return self.stream(name)
        return None

    # -------------------------------------------------------------------------
    # Parsed data

    @functools.cached_property
    def dll_directory(self) -> DllDirectory:
        return parse_dll_directory(self._optional_stream(DLL_DIRECTORY_STREAM))

    @functools.cached_property
    def class_directory(self) -> ClassDirectory:
        return parse_class_directory(self._optional_stream(*CLASS_DIRECTORY_STREAMS), self.dll_directory)

    @functools.cached_property
    def scene(self) -> Scene:
        scene = parse_scene(self._optional_stream(SCENE_STREAM), self.class_directory)
        scene._asset_loader = lambda: self.asset_metadata
        return scene

    @functools.cached_property
    def asset_metadata(self) -> AssetMetadata:
        """Bitmap paths from the asset metadata stream (best effort, see :mod:`maxfile.assets`)."""
        return read_asset_metadata(self.container)

    @property
    def objects(self) -> list[SceneObject]:
        """All scene objects, by object index."""
        return self.scene.objects

    @property
    def nodes(self) -> list[Node]:
        """All scene nodes, in object order."""
        return self.scene.nodes

    @property
    def warnings(self) -> list[str]:
        """Every non-fatal problem found so far (container, directories, scene, decoders)."""
        found = list(self.container.warnings)
        found.extend(self.dll_directory.warnings)
        found.extend(self.class_directory.warnings)
        found.extend(self.scene.warnings)
        if "asset_metadata" in self.__dict__:
            found.extend(self.asset_metadata.warnings)
        return found

    def class_usage(self) -> list[ClassUsage]:
        """Every class-directory entry with its object count, registry entry and decoder; most used first."""
        counts = self.scene.class_counts()
        usage = []
        for entry in self.class_directory.entries:
            usage.append(ClassUsage(
                entry=entry,
                count=counts.get(entry.index, 0),
                known=registry.known_class(entry.class_id, entry.superclass_id),
                decoder=registry.find_decoder(entry.class_id, entry.superclass_id),
            ))
        usage.sort(key=lambda u: (-u.count, u.entry.index))
        return usage

    def unknown_classes(self) -> list[ClassUsage]:
        """Classes used by at least one object that the registry doesn't know; most used first."""
        return [u for u in self.class_usage() if u.count and u.known is None]


def open(path) -> MaxFile:
    """
    Open a ``.max`` file (a path, or a bytes-like object holding the file). Use as a context manager.

    Raises :class:`MaxFileError` (or a subclass) when the file isn't a readable ``.max`` scene, and ``OSError``
    when it can't be read.
    """
    return MaxFile(path)
