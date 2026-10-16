# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Materials (``docs/format/overview.md`` §5, §5.1, §5.3).

What the overview documents, and therefore all this module reads (unverified on real files):

- the material classes (§5 table);
- where each class stores its **name** (§5.1);
- that parameters live in **parameter blocks reached through the material's references**, found by a u16
  parameter index at the start of a chunk payload, with the value at the end of the payload;
- the parameter indices of **VRayMtl** ``diffuse`` (0x01) and ``reflection_glossiness`` (0x06), the only
  indices it names;
- **Arnold Standard Surface** sockets: one referenced object per socket, name in child ``0x1``, value in ``0x3``;
- **Multi/Sub-Object** sub-materials through references; the material ID list is not documented, so
  :attr:`MaterialData.sub_ids` is None.

``params`` therefore holds only those values, under the keys the importer's converters use
(``scripts/addons_core/mx_io_max/materials/convert.py``), and ``class_name`` uses the converters' class names.
Every other parameter is left out on purpose: to find more, look at :attr:`MaterialData.param_blocks` with
``maxdump --object N --decode``.
"""

__all__ = (
    "MaterialData",
    "MATERIALS",
)

import dataclasses
import struct

from .. import registry
from ..classes import ClassID
from ..registry import decoder
from .maps import MapData, is_map_like, read_map
from .paramblock import read_param_block

# Name storage rules. Unverified (overview.md §5.1).
NAME_0x4000_FIRST_CHILD = "0x4000/first"    # Standard: first child of container 0x4000
NAME_0x100_0x4001 = "0x0100/0x4001"         # Physical: 0x4001 inside 0x0100
NAME_0x5431 = "0x5431"                      # VRayMtl
NAME_0x0FA0 = "0x0FA0"                      # Corona materials
NAME_AFTER_AT = "0x0100@"                   # Raytrace, Arnold, Architectural: text after "@" in 0x0100

# Documented parameter indices. Unverified (overview.md §5.1): index -> (converter key, value kind).
VRAY_PARAMS = {
    0x01: ("diffuse", "color"),
    0x06: ("reflection_glossiness", "float"),
}

# Class ID -> (class name used by the converters, name rule, documented parameters, Arnold-style sockets).
MATERIALS = {
    ClassID(0x0002): ("Standardmaterial", NAME_0x4000_FIRST_CHILD, None, False),
    ClassID(0x0006): ("Legacy", None, None, False),
    ClassID(0x0200): ("Multimaterial", None, None, False),
    ClassID.from_u64(0xDEADC0013D6B1CEC): ("PhysicalMaterial", NAME_0x100_0x4001, None, False),
    ClassID.from_u64(0x7034695C37BF3F2F): ("VRayMtl", NAME_0x5431, VRAY_PARAMS, False),
    ClassID.from_u64(0x11731B4B6066686A): ("VRay2SidedMtl", None, None, False),
    ClassID.from_u64(0x448931DD70BE6506): ("CoronaMtl", NAME_0x0FA0, None, False),
    ClassID.from_u64(0x871517206912AB89): ("CoronaPhysicalMtl", NAME_0x0FA0, None, False),
    ClassID.from_u64(0x8425554E65486584): ("CoronaLayeredMtl", NAME_0x0FA0, None, False),
    ClassID.from_u64(0x44CFDE95BEC41C73): ("CoronaSkinMtl", NAME_0x0FA0, None, False),
    ClassID.from_u64(0xCA41F54622C05DD6): ("CoronaHairMtl", NAME_0x0FA0, None, False),
    ClassID.from_u64(0x62F74B4C7E73161F): ("ai_standard_surface", NAME_AFTER_AT, None, True),
    ClassID.from_u64(0x329B106E27190FF4): ("Raytrace", NAME_AFTER_AT, None, False),
    ClassID.from_u64(0x4A16365470B05735): ("Architectural", NAME_AFTER_AT, None, False),
    ClassID.from_u64(0x0000000046EE536A): ("Shellac", None, None, False),
}
MULTI_SUB = ClassID(0x0200)

# Arnold sockets. Unverified (overview.md §5.1).
SOCKET_NAME = 0x0001
SOCKET_VALUE = 0x0003


@dataclasses.dataclass
class MaterialData:
    """A material: name, the documented parameters, maps and sub-materials."""
    class_name: str                     # Converter class name (see MATERIALS), else the registry/file name.
    name: str | None
    params: dict                        # Only documented parameters, under the converters' keys.
    maps: dict[str, MapData | None]     # Maps whose parameter is known, under the converters' keys.
    sub_materials: "list[MaterialData | None] | None"
    sub_ids: list[int] | None           # Material ID per sub-material; None = not known (not documented yet).
    index: int | None = None            # Object index of the material.
    unassigned_maps: dict[int, MapData] = dataclasses.field(default_factory=dict)
    """Referenced maps whose parameter is unknown, by reference slot."""
    param_blocks: list[int] = dataclasses.field(default_factory=list)
    """Object indices of the referenced objects treated as parameter blocks (for investigation)."""


def _name(obj, rule):
    chunk = obj.chunk
    if rule == NAME_0x4000_FIRST_CHILD:
        holder = chunk.find(0x4000)
        if holder is not None and holder.is_container and holder.children:
            return holder.children[0].string()
    elif rule == NAME_0x100_0x4001:
        holder = chunk.find(0x0100)
        found = holder.find(0x4001) if holder is not None else None
        if found is not None:
            return found.string()
    elif rule in (NAME_0x5431, NAME_0x0FA0):
        found = chunk.find(int(rule, 16))
        if found is not None and not found.is_container:
            return found.string()
    elif rule == NAME_AFTER_AT:
        found = chunk.find(0x0100)
        if found is not None and not found.is_container:
            text = found.string()
            if "@" in text:
                return text.split("@", 1)[1]
    return None


def is_material(obj) -> bool:
    if obj.class_id is None:
        return False
    if obj.class_id in MATERIALS:
        return True
    known = registry.known_class(obj.class_id, obj.superclass_id)
    return known is not None and known.category == "material"


def _socket_value(chunk):
    """Guess an Arnold socket value from its size: f32, f32[3] colour, or f32[4] colour (alpha dropped)."""
    data = chunk.data
    if len(data) == 4:
        return struct.unpack("<f", data)[0]
    if len(data) == 12:
        return struct.unpack("<3f", data)
    if len(data) == 16:
        return struct.unpack("<4f", data)[:3]
    return None


def _read_sockets(mat, refs, ctx, obj):
    for slot, ref in refs:
        name_chunk = ref.chunk.find(SOCKET_NAME)
        if name_chunk is None or name_chunk.is_container:
            continue
        socket = name_chunk.string()
        if not socket:
            continue
        key = socket.replace(".", "_")
        if socket.endswith(".shader"):
            # Guess: where a shader socket keeps its map isn't documented; we take its first reference.
            target = ctx.first_ref(ref)
            mat.maps[key] = read_map(target, ctx) if target is not None else None
            continue
        value_chunk = ref.chunk.find(SOCKET_VALUE)
        value = _socket_value(value_chunk) if value_chunk is not None and not value_chunk.is_container else None
        if value is None:
            ctx.warn("object {:d} ({:s}): socket {!r} value not understood".format(obj.index, mat.class_name, socket))
            continue
        mat.params[key] = value


def _read_params(mat, table, blocks, ctx, obj):
    for param_id, (key, kind) in table.items():
        for block in blocks:
            entry = read_param_block(block).get(param_id)
            if entry is None:
                continue
            value = entry.as_color() if kind == "color" else entry.as_float()
            if value is not None:
                mat.params[key] = value
                break
        else:
            ctx.warn("object {:d} ({:s}): parameter 0x{:02X} ({:s}) not found".format(
                obj.index, mat.class_name, param_id, key))


@decoder(*MATERIALS, kind="material", name="Materials (name, documented parameters, sub-materials)")
def material(obj, ctx):
    """Name, documented parameters, maps and sub-materials."""
    class_name, name_rule, table, sockets = MATERIALS[obj.class_id]
    if class_name == "Legacy":
        class_name = obj.class_label()
    mat = MaterialData(class_name, _name(obj, name_rule), {}, {}, None, None, index=obj.index)

    # Unverified (overview.md §5.1, §5.3): classify the references as sub-materials, maps or parameter blocks.
    refs = ctx.refs(obj)
    sub_refs, blocks = [], []
    for slot, ref in refs:
        if is_material(ref):
            sub_refs.append(ref)
        elif is_map_like(ref, ctx):
            mat.unassigned_maps[slot] = read_map(ref, ctx)
        else:
            blocks.append(ref)
    mat.param_blocks = [b.index for b in blocks]

    if sub_refs or obj.class_id == MULTI_SUB:
        subs = []
        for ref in sub_refs:
            value = ctx.decode(ref)
            subs.append(value if isinstance(value, MaterialData) else None)
        mat.sub_materials = subs
        if obj.class_id == MULTI_SUB:
            ctx.warn("object {:d} (Multi/Sub-Object): sub-material IDs not decoded (layout unknown)".format(
                obj.index))
    if table:
        _read_params(mat, table, blocks, ctx, obj)
    if sockets:
        _read_sockets(mat, refs, ctx, obj)
    return mat
