# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Chunk encoding: the inverse of :mod:`maxfile.chunks` (``docs/format/overview.md`` §2.1).

A chunk is ``u16 type, u32 size`` (size including the 6-byte header, bit 31 set for containers), or, when the size
doesn't fit in 31 bits, ``u16 type, u32 0, u64 size`` (bit 63 = container). Chunks are built bottom-up as
``bytes``; helpers below encode the payload types the format uses.
"""

__all__ = (
    "leaf", "cont", "u8", "u16", "u32", "i32", "f32", "u32_array", "f32_array", "text", "pstr16",
)

import array
import struct
import sys

_HEADER = struct.Struct("<HI")
_HEADER64 = struct.Struct("<HIQ")
_MAX32 = 0x7FFFFFFF


def _header(chunk_type, size, container):
    if size + 6 <= _MAX32:
        return _HEADER.pack(chunk_type, (size + 6) | (0x80000000 if container else 0))
    return _HEADER64.pack(chunk_type, 0, (size + 14) | ((1 << 63) if container else 0))


def leaf(chunk_type: int, payload: bytes = b"") -> bytes:
    """A leaf chunk."""
    return _header(chunk_type, len(payload), False) + payload


def cont(chunk_type: int, *children) -> bytes:
    """A container chunk; ``children`` are encoded chunks (bytes) or iterables of them."""
    parts = []
    for child in children:
        if isinstance(child, (bytes, bytearray)):
            parts.append(child)
        else:
            parts.extend(child)
    payload = b"".join(parts)
    return _header(chunk_type, len(payload), True) + payload


def u8(*values) -> bytes:
    return bytes(values)


def u16(*values) -> bytes:
    return struct.pack("<{:d}H".format(len(values)), *values)


def u32(*values) -> bytes:
    return struct.pack("<{:d}I".format(len(values)), *(v & 0xFFFFFFFF for v in values))


def i32(*values) -> bytes:
    return struct.pack("<{:d}i".format(len(values)), *values)


def f32(*values) -> bytes:
    return struct.pack("<{:d}f".format(len(values)), *values)


def _le(arr):
    if sys.byteorder == "big":  # pragma: no cover
        arr.byteswap()
    return arr.tobytes()


def u32_array(values) -> bytes:
    """Many u32 values (fast path for meshes)."""
    arr = array.array("I")
    if arr.itemsize != 4:  # pragma: no cover
        arr = array.array("L")
    arr.extend(values)
    return _le(arr)


def f32_array(values) -> bytes:
    """Many f32 values (fast path for meshes)."""
    return _le(array.array("f", values))


def text(value: str) -> bytes:
    """UTF-16LE without a terminator (node names, class names, material names ...)."""
    return value.encode("utf-16-le")


def pstr16(value) -> bytes:
    """``u32 byte length`` + UTF-16LE with a terminating NUL (ParamBlock2 strings, §5.1); None -> 0xFFFFFFFF."""
    if value is None:
        return u32(0xFFFFFFFF)
    raw = (value + "\0").encode("utf-16-le")
    return u32(len(raw)) + raw
