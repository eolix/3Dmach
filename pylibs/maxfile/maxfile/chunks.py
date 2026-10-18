# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Chunk trees: the generic structure inside most streams of a ``.max`` file.

Layout, as documented in ``docs/format/overview.md`` §2.1 (all of it unverified on real files so far)::

    u16  type
    u32  size        # whole chunk, header included; bit 31 = container flag
    u64  size64      # only when size == 0: the real size, bit 63 = container flag (14-byte header)
    ...  payload     # container: child chunks; leaf: raw bytes

Parsing is **lazy and one level at a time**: a container's children are parsed the first time
:attr:`Chunk.children` is read. Nothing is recursive, so deep trees can't hit Python's recursion limit, and a
tool that only looks at the top of a large stream doesn't pay for the rest. Payloads are not copied until
:attr:`Chunk.data` is read.

A malformed chunk header never raises from :attr:`Chunk.children`: parsing of that level stops, the chunks read
so far are kept, and :attr:`Chunk.error` describes the problem (with its offset in the stream). Use
:func:`walk` / :meth:`ChunkStream.errors` to find such problems.
"""

__all__ = (
    "Chunk",
    "ChunkStream",
    "GZIP_MAGIC",
    "decompress_stream",
    "walk",
    "utf16",
    "u16s",
    "u32s",
    "i32s",
    "f32s",
)

import dataclasses
import functools
import struct
import zlib

from .errors import ChunkError

# gzip member header: ID1 ID2 and CM = 8 (deflate). Unverified (overview.md §2.2): the prior-art importer checks
# for 1F 8B plus a few hard-coded header bytes; we accept any stream that starts with these three bytes *and*
# decompresses cleanly.
GZIP_MAGIC = b"\x1F\x8B\x08"

_HEADER = struct.Struct("<HI")
_SIZE64 = struct.Struct("<Q")
_CONTAINER32 = 0x80000000
_CONTAINER64 = 0x8000000000000000


@dataclasses.dataclass(slots=True, eq=False)
class Chunk:
    """One chunk. Offsets are relative to the start of the (decompressed) stream data."""
    type: int
    is_container: bool
    offset: int                 # Offset of the chunk header.
    header_size: int            # 6, or 14 for the extended (64-bit size) header.
    size: int                   # Whole chunk, header included.
    _buf: bytes = dataclasses.field(repr=False)
    _children: list | None = dataclasses.field(default=None, repr=False)
    error: str | None = None
    """Why parsing this container's children stopped early (None when they parsed cleanly)."""

    @property
    def payload_offset(self) -> int:
        """Offset of the first payload byte."""
        return self.offset + self.header_size

    @property
    def payload_size(self) -> int:
        return self.size - self.header_size

    @property
    def end(self) -> int:
        """Offset just past the chunk."""
        return self.offset + self.size

    @property
    def data(self) -> bytes:
        """The payload bytes (for a container: its children, still encoded)."""
        return bytes(self._buf[self.payload_offset:self.end])

    @property
    def children(self) -> list:
        """Child chunks (parsed on first access); empty for a leaf."""
        if self._children is None:
            if self.is_container:
                self._children, self.error = _parse_level(self._buf, self.payload_offset, self.end)
            else:
                self._children = []
        return self._children

    def find(self, chunk_type: int):
        """The first direct child of the given type, or None."""
        for child in self.children:
            if child.type == chunk_type:
                return child
        return None

    def find_all(self, chunk_type: int) -> list:
        """All direct children of the given type."""
        return [child for child in self.children if child.type == chunk_type]

    def string(self) -> str:
        """The payload as a UTF-16LE string (see :func:`utf16`)."""
        return utf16(self.data)

    def u32s(self) -> tuple[int, ...]:
        return u32s(self.data)

    def f32s(self) -> tuple[float, ...]:
        return f32s(self.data)


def _parse_level(buf, start, end):
    """Parse the chunks in ``buf[start:end]``. Returns ``(chunks, error_message_or_None)``."""
    chunks = []
    pos = start
    while pos < end:
        left = end - pos
        if left < 6:
            return chunks, "{:d} byte(s) left at 0x{:X}, too short for a chunk header".format(left, pos)
        chunk_type, raw = _HEADER.unpack_from(buf, pos)
        if raw == 0:
            # Unverified (overview.md §2.1): a zero 32-bit size means a 64-bit size follows.
            if left < 14:
                return chunks, "chunk 0x{:04X} at 0x{:X}: extended header cut short".format(chunk_type, pos)
            (raw64,) = _SIZE64.unpack_from(buf, pos + 6)
            container = bool(raw64 & _CONTAINER64)
            size = raw64 & ~_CONTAINER64
            header_size = 14
        else:
            # Unverified (overview.md §2.1): bit 31 marks a container.
            container = bool(raw & _CONTAINER32)
            size = raw & ~_CONTAINER32
            header_size = 6
        if size < header_size:
            return chunks, "chunk 0x{:04X} at 0x{:X}: size {:d} is smaller than its {:d}-byte header".format(
                chunk_type, pos, size, header_size)
        if size > left:
            return chunks, "chunk 0x{:04X} at 0x{:X}: size {:d} runs past the end of its parent ({:d} bytes left)" \
                .format(chunk_type, pos, size, left)
        chunks.append(Chunk(chunk_type, container, pos, header_size, size, buf))
        pos += size
    return chunks, None


def decompress_stream(data: bytes) -> tuple[bytes, bool, str | None]:
    """
    Undo whole-stream gzip compression, if present.

    Returns ``(data, compressed, warning)``. A stream that starts with the gzip magic but doesn't decompress
    cleanly is returned unchanged with a warning, since it may be an uncompressed chunk stream whose first bytes
    happen to match.
    """
    # Unverified (overview.md §2.2): compression applies to the whole stream, never to single chunks.
    if data[:3] != GZIP_MAGIC:
        return data, False, None
    parts = []
    rest = data
    try:
        # A gzip file may hold several members back to back.
        while rest[:3] == GZIP_MAGIC:
            dec = zlib.decompressobj(wbits=31)
            parts.append(dec.decompress(rest))
            if not dec.eof:
                raise zlib.error("compressed data ends early")
            rest = dec.unused_data
    except zlib.error as ex:
        return data, False, "starts with the gzip magic but doesn't decompress ({:s}); read as uncompressed".format(
            str(ex))
    warning = None
    if rest.strip(b"\0"):
        warning = "{:d} byte(s) of non-gzip data after the compressed data; ignored".format(len(rest))
    return b"".join(parts), True, warning


class ChunkStream:
    """
    A stream parsed as a chunk tree.

    :attr:`data` is the (decompressed) stream contents, :attr:`chunks` the top-level chunks.
    """

    def __init__(self, raw: bytes, name: str = "<bytes>"):
        self.name = name
        self.stored_size = len(raw)
        """Size in the container (compressed size when :attr:`compressed`)."""
        self.data, self.compressed, warning = decompress_stream(raw)
        self.warnings: list[str] = []
        if warning:
            self.warnings.append("{:s}: {:s}".format(name, warning))
        self.chunks, self.error = _parse_level(self.data, 0, len(self.data))
        """Top-level chunks, and why top-level parsing stopped early (None when it didn't)."""

    @property
    def size(self) -> int:
        """Size of :attr:`data` (decompressed)."""
        return len(self.data)

    def walk(self, max_depth=None):
        """Iterate ``(depth, chunk)`` over the whole tree; see :func:`walk`."""
        return walk(self.chunks, max_depth)

    def errors(self) -> list[str]:
        """Every chunk-header problem in the whole tree (parses it completely)."""
        found = [self.error] if self.error else []
        found.extend(chunk.error for _, chunk in self.walk() if chunk.error)
        return found

    def check(self):
        """Raise :class:`~maxfile.errors.ChunkError` for the first problem in the tree, if any."""
        found = self.errors()
        if found:
            raise ChunkError("{:s}: {:s}".format(self.name, found[0]))


def walk(chunks, max_depth=None):
    """
    Iterate ``(depth, chunk)`` over ``chunks`` and their descendants, depth first, in file order.

    Top-level chunks have depth 0. With ``max_depth``, chunks deeper than that are neither visited nor parsed.
    Iterative, so arbitrarily deep trees are fine.
    """
    stack = [(0, iter(chunks))]
    while stack:
        depth, it = stack[-1]
        chunk = next(it, None)
        if chunk is None:
            stack.pop()
            continue
        yield depth, chunk
        if chunk.is_container and (max_depth is None or depth < max_depth):
            stack.append((depth + 1, iter(chunk.children)))


# -----------------------------------------------------------------------------
# Payload helpers. Trailing bytes that don't fill a whole value are ignored.

def utf16(data: bytes) -> str:
    """Decode UTF-16LE text, dropping trailing NUL characters; undecodable bytes become U+FFFD."""
    if len(data) % 2:
        data = data[:-1]
    return data.decode("utf-16-le", errors="replace").rstrip("\0")


@functools.lru_cache(maxsize=256)
def _struct(fmt, n):
    return struct.Struct("<{:d}{:s}".format(n, fmt))


def _array(fmt, size, data, count):
    n = len(data) // size if count is None else count
    if n * size > len(data):
        raise ChunkError("need {:d} bytes for {:d} value(s), have {:d}".format(n * size, n, len(data)))
    return _struct(fmt, n).unpack_from(data, 0)


def u16s(data: bytes, count=None) -> tuple[int, ...]:
    """Little-endian ``u16`` values (all that fit, or exactly ``count``; raises ChunkError if too short)."""
    return _array("H", 2, data, count)


def u32s(data: bytes, count=None) -> tuple[int, ...]:
    """Little-endian ``u32`` values (all that fit, or exactly ``count``)."""
    return _array("I", 4, data, count)


def i32s(data: bytes, count=None) -> tuple[int, ...]:
    """Little-endian ``i32`` values (all that fit, or exactly ``count``)."""
    return _array("i", 4, data, count)


def f32s(data: bytes, count=None) -> tuple[float, ...]:
    """Little-endian ``f32`` values (all that fit, or exactly ``count``)."""
    return _array("f", 4, data, count)
