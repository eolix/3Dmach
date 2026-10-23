# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Parameter blocks: ParamBlock2 (class 0x82) and the old ParamBlock (class 0x8), the inverse of
:mod:`maxfile.objects.paramblock` (``docs/format/overview.md`` §5).

ParamBlock2 object layout written (the order of every 2015 corpus block)::

    0x0009  u32 descriptor version, u16 block ID, u32 Max version, u16 record count, u32 owner object index
    0x100E  one per parameter: u16 id, u32 type, u16 flags_a, u32 flags_b, u16 (0 or 2), u8 value flags, value
    ...     chunks that follow a record (asset reference 0x000F after a file name, bitmap info 0x0003)
    0x1005  optional: scripting names of table items
    0x000C  u32 n, then n x (u32, u16 0): one entry per rollout (Edit Poly: 15, Standard blocks: 1), probably the
            rollouts' open / closed state; written as the dominant corpus value per block
    0x0011  u8 1

The record heads (type and flag words) are not decoded beyond what the reader needs; the writer emits the heads
the corpus blocks of each class have (given per class next to the parameter values).
"""

__all__ = ("R", "Table", "pb2", "old_pb", "OLD_FLOAT", "OLD_INT", "OLD_POINT3", "OLD_COLOR", "MAX_VERSION_WORD")

import dataclasses
import struct

from . import classes
from .chunks import cont, f32, i32, leaf, pstr16, u16, u32, u8
from .graph import NULL, MaxObject

# Corpus: the Max version word of the 0x0009 header in 2015 files: 0x42042B08 in 147 of 357 sampled blocks of
# Standard materials, 0x42042B0A in 120, 0x42042B06 in 90 (the high word is the release, 16900).
MAX_VERSION_WORD = 0x42042B08

# Value layouts by parameter type (overview.md §5.1).
_SCALAR = {0: "<f", 5: "<f", 6: "<f", 7: "<f", 1: "<i", 12: "<i", 13: "<i", 19: "<i", 4: "<I", 2: "<3f",
           3: "<3f", 23: "<4f"}
_REF_TYPES = (14, 15, 17, 18)


def encode_value(ptype, value):
    """The value bytes of a non-table record of type ``ptype`` (references: an object or None, as callables)."""
    base = ptype & 0x7FF
    if base in _REF_TYPES:
        return _ref(value)
    if base in (8, 9):
        return pstr16(value)
    if base == 16:
        return u8(int(value))
    fmt = _SCALAR[base]
    if isinstance(value, (tuple, list)):
        return struct.pack(fmt, *value)
    if fmt in ("<i", "<I"):
        return struct.pack(fmt, int(value))
    return struct.pack(fmt, value)


def _ref(obj):
    """An inline object index, resolved when the stream is written."""
    if obj is None:
        return u32(NULL)
    return lambda index_of: u32(index_of(obj))


@dataclasses.dataclass
class Table:
    """A table value (type | 0x800): ``items`` are values (or objects for reference tables)."""
    items: list
    item_flag: int = 0x40           # Corpus: 0x40 on every inline table item of the blocks written here.


@dataclasses.dataclass
class R:
    """One ParamBlock2 record. ``value`` is encoded by type; ``raw`` overrides it with bytes."""
    id: int
    type: int
    flags_a: int
    flags_b: int
    extra: int
    value_flags: int
    value: object = None
    after: list = dataclasses.field(default_factory=list)     # Chunks written right after the record.
    raw: bytes | None = None

    def head(self):
        return struct.pack("<HIHIHB", self.id, self.type, self.flags_a, self.flags_b, self.extra, self.value_flags)

    def parts(self):
        """The record payload as a list of bytes / callables."""
        if self.raw is not None:
            return [self.head(), self.raw]
        if self.type & 0x800:
            table = self.value if isinstance(self.value, Table) else Table(list(self.value))
            out = [self.head(), u32(len(table.items))]
            base = self.type & 0x7FF
            for item in table.items:
                out.append(u8(table.item_flag))
                if base in _REF_TYPES:
                    if self.flags_a & 0x0100:       # Inline index (overview.md §5.1).
                        out.append(_ref(item))
                else:
                    out.append(encode_value(base, item))
            return out
        return [self.head(), encode_value(self.type, self.value)]


def _join(parts):
    if any(callable(p) for p in parts):
        def build(index_of):
            return b"".join(p(index_of) if callable(p) else p for p in parts)
        return build
    return b"".join(parts)


def _leaf_lazy(chunk_type, parts):
    payload = _join(parts)
    if callable(payload):
        return lambda index_of: leaf(chunk_type, payload(index_of))
    return leaf(chunk_type, payload)


def pb2(owner: MaxObject, desc_version: int, block_id: int, records, rollouts=(0,), names=None,
        refs=None, num_refs=None, version_word=MAX_VERSION_WORD, extra_chunks=()) -> MaxObject:
    """
    A ParamBlock2 object owned by ``owner`` (whose index goes into the header).

    ``rollouts`` are the 0x000C entries (one u32 per rollout); ``names`` the optional 0x1005 table-item names
    ``[(name, param id, item index)]``; ``refs`` the block's own references (animated values, slot references).
    """
    records = list(records)
    obj = MaxObject(classes.PARAM_BLOCK2, refs=refs, num_refs=num_refs)
    obj.chunks.append(lambda index_of: leaf(0x0009, struct.pack(
        "<IHIHI", desc_version, block_id, version_word, len(records), index_of(owner))))
    for record in records:
        obj.chunks.append(_leaf_lazy(0x100E, record.parts()))
        obj.chunks.extend(record.after)
    if names:
        body = [u32(len(names))]
        for name, param_id, index in names:
            raw = (name + "\0").encode("utf-16-le")
            body.append(u32(len(raw)) + raw + struct.pack("<HI", param_id, index))
        obj.chunks.append(leaf(0x1005, b"".join(body)))
    obj.chunks.append(leaf(0x000C, u32(len(rollouts)) + b"".join(struct.pack("<IH", r, 0) for r in rollouts)))
    obj.chunks.append(leaf(0x0011, u8(1)))
    obj.chunks.extend(extra_chunks)
    return obj


# Old ParamBlock value chunks (overview.md §5.2).
OLD_FLOAT, OLD_INT, OLD_POINT3, OLD_COLOR = 0x0100, 0x0101, 0x0102, 0x0103


def old_pb(version: int, params, refs=None) -> MaxObject:
    """
    An old ParamBlock: ``params`` is a list of ``(value chunk type, value[, animatable])``; parameter i has
    index i. Animatable parameters (the default) carry the empty 0x0004 marker.
    """
    obj = MaxObject(classes.PARAM_BLOCK, refs=refs)
    obj.chunks.append(leaf(0x0001, u32(len(params))))
    obj.chunks.append(leaf(0x0005, u16(version)))
    for index, param in enumerate(params):
        kind, value = param[0], param[1]
        animatable = param[2] if len(param) > 2 else True
        if kind == OLD_FLOAT:
            payload = f32(value)
        elif kind in (OLD_POINT3, OLD_COLOR):
            payload = f32(*value)
        else:
            payload = i32(int(value))
        children = [leaf(0x0003, u32(index))]
        if animatable:
            children.append(leaf(0x0004))
        children.append(leaf(kind, payload))
        obj.chunks.append(cont(0x0002, *children))
    return obj
