# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Standard primitives: parameters and cached meshes (``docs/format/overview.md`` §6.1, §6.3, §6.4).

Unverified on real files. In particular the overview gives parameter *order* only for the first few parameters
of each primitive (no segment counts, no flags); any further values found are reported in
:attr:`PrimitiveData.extra_values` instead of being guessed into ``params``.
"""

__all__ = (
    "PrimitiveData",
    "PRIMITIVES",
    "read_primitive_values",
)

import dataclasses
import struct

from ..chunks import f32s
from ..classes import ClassID
from ..registry import decoder
from .geometry import (
    CHUNK_MESH,
    MESH_MAP_FACES,
    MESH_MAP_FACES_0x19,
    MESH_MAP_VERTICES,
    MESH_MAP_VERTICES_0x19,
    MeshData,
    read_tri_mesh,
)

# Class ID -> (kind, parameter names in stored order, whether a cached 0x08FE mesh is documented).
# Unverified (overview.md §6.1, §6.4). 0x14 and 0x19 are read as Box by the prior-art importer; 0x16 is a primitive
# of unknown kind (only its cached mesh is documented).
PRIMITIVES = {
    ClassID(0x10): ("BOX", ("length", "width", "height"), True),
    ClassID(0x11): ("SPHERE", ("radius",), True),
    ClassID(0x12): ("CYLINDER", ("radius", "height"), True),
    ClassID(0x14): ("BOX", ("length", "width", "height"), False),
    ClassID(0x16): ("UNKNOWN", (), True),
    ClassID(0x19): ("BOX", ("length", "width", "height"), True),
    ClassID(0x20): ("TORUS", ("radius1", "radius2"), False),
    ClassID.from_u64(0x00000000A86C23DD): ("CONE", ("radius1", "radius2", "height"), False),
    ClassID.from_u64(0x77566F65081F1DFC): ("PLANE", ("length", "width"), False),
}

CHUNK_PARAM_VALUE = 0x0100      # Encoding 2: child chunk holding the f32.
_RECORD = struct.Struct("<HIHHBff")     # Encoding 3: u16, u32, u16, u16, u8, f32, f32 (value last).
_REFERENCE_CHUNKS = (0x2034, 0x2035)    # Never parameter entries.


@dataclasses.dataclass
class PrimitiveData:
    """A primitive's documented parameters, and Max's own mesh for them when the file caches one."""
    kind: str                       # "BOX", "SPHERE", "CYLINDER", "TORUS", "CONE", "PLANE" or "UNKNOWN".
    params: dict[str, float]        # Only the parameter names overview.md documents, in scene units.
    cached_mesh: MeshData | None
    encoding: str | None = None     # How the values were stored: "leaf", "record", "0x0100", or a mix.
    extra_values: list[float] = dataclasses.field(default_factory=list)  # Values beyond the documented ones.
    param_block: int | None = None  # Object index of the parameter block read.


def read_primitive_values(block_chunk) -> tuple[list[float], list[str]]:
    """
    Values from a primitive's parameter block, in stored order, and the encoding of each.

    Unverified (overview.md §6.4), three encodings: (1) a leaf longer than 11 bytes, value = last f32;
    (2) a container with a 0x0100 child holding the f32; (3) a fixed record ``u16, u32, u16, u16, u8, f32, f32``,
    value = last field (a 19-byte leaf, so it also satisfies rule 1). Other chunks are not parameter entries.
    """
    values, encodings = [], []
    for child in block_chunk.children:
        if child.type in _REFERENCE_CHUNKS:
            continue
        if child.is_container:
            holder = child.find(CHUNK_PARAM_VALUE)
            if holder is not None and holder.payload_size >= 4:
                values.append(f32s(holder.data, 1)[0])
                encodings.append("0x0100")
        elif child.payload_size == _RECORD.size:
            values.append(_RECORD.unpack(child.data)[-1])
            encodings.append("record")
        elif child.payload_size > 11:
            values.append(f32s(child.data)[-1])
            encodings.append("leaf")
    return values, encodings


def _decode(obj, ctx):
    kind, names, has_cache = PRIMITIVES[obj.class_id]
    cached = None
    mesh_chunk = obj.chunk.find(CHUNK_MESH)
    if has_cache and mesh_chunk is not None and mesh_chunk.is_container:
        # Unverified (overview.md §6.3): class 0x19 uses 0x0916 / 0x0918 for map data, the others 0x2394 / 0x2396.
        if obj.class_id == ClassID(0x19):
            cached = read_tri_mesh(mesh_chunk, "primitive_cache", MESH_MAP_VERTICES_0x19, MESH_MAP_FACES_0x19)
        else:
            cached = read_tri_mesh(mesh_chunk, "primitive_cache", MESH_MAP_VERTICES, MESH_MAP_FACES)
        for message in cached.warnings:
            ctx.warn("object {:d} ({:s}) cached mesh: {:s}".format(obj.index, obj.class_label(), message))

    # Unverified (overview.md §6.4): the parameter block is the first reference.
    block = ctx.first_ref(obj)
    prim = PrimitiveData(kind, {}, cached)
    if block is None:
        ctx.warn("object {:d} ({:s}): no parameter block reference".format(obj.index, obj.class_label()))
        return prim
    prim.param_block = block.index
    values, encodings = read_primitive_values(block.chunk)
    prim.params = dict(zip(names, values))
    prim.extra_values = values[len(names):]
    kinds = sorted(set(encodings))
    prim.encoding = "+".join(kinds) if kinds else None
    if len(values) < len(names):
        ctx.warn("object {:d} ({:s}): {:d} of {:d} documented parameters found".format(
            obj.index, obj.class_label(), len(values), len(names)))
    if prim.extra_values:
        ctx.warn("object {:d} ({:s}): {:d} undocumented parameter value(s) not named".format(
            obj.index, obj.class_label(), len(prim.extra_values)))
    return prim


@decoder(*PRIMITIVES, kind="geometry.primitive", name="Standard primitives")
def primitive(obj, ctx):
    """Primitive kind, documented parameters and cached mesh."""
    return _decode(obj, ctx)
