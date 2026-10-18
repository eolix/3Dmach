# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Texture maps (superclass 0xC10), worked out on the local corpus (1,779 Bitmaps in 330 files and every other map
class it has; see ``docs/format/materials.md`` of the format notes for the evidence).

**Names** (all material and map classes): the "MtlBase header" is a container whose first child is ``0x4001``
(UTF-16 name) followed by ``0x4003`` (flags), ``0x4020``, ``0x4030``... The container is ``0x4000`` for the
classic classes, ``0x0100`` for Physical Material / Arnold / mental ray classes, ``0x1000`` or ``0x1100`` for a few
others; scripted classes put ``0x4001`` / ``0x4003`` directly in the object. :func:`object_name` reads all of
these (verified: every corpus object of 70 of the 81 material and map classes has one).

**Bitmap** (class 0x240): references 0 = ``Placement`` (UVGen, class 0x100 / superclass 0xC20), 1 = its
ParamBlock2 (17 parameters in all 1,779 corpus Bitmaps), 2 = ``Output`` (0xC40), 3 = a ParamBlock2 of time
settings. The file is found through an **asset ID**:

- parameter 16, type 9 (file name): ``u32 0xFFFFFFFE`` instead of a string, and the record is followed by a
  container ``0x000F`` whose child ``0x0002`` holds the 16-byte asset ID (1,740 Bitmaps; the parameter-block reader
  returns it as an ``AssetRef``). ``0xFFFFFFFF`` = no file (39 Bitmaps);
- parameter 13 (type 16) is followed by the bitmap-info container ``0x0003`` (``0x1201`` settings, ``0x1260`` /
  ``0x0002`` the same asset ID, ``0x1240`` the image-format name, e.g. "JPEG File"). It also names the file in 13
  Bitmaps whose parameter 16 is empty; in 1,739 of the 1,740 others both IDs are equal.

The asset ID is looked up in the asset metadata stream (:mod:`maxfile.assets`). 1,753 Bitmaps resolve to a path;
the other 26 have no ID at all (no file loaded). No corpus file stores the path as a string; reading a plain
string file name and a ``0x1230`` string (the prior-art importer's scheme for files older than the corpus) is kept
as an unverified fallback.

**UVGen** (``Placement``, class 0x100, superclass 0xC20): an old ParamBlock in reference 0 with 13 parameters,
see :data:`UVGEN_PARAMS`, plus leaf chunks in the object: ``0x900B`` map channel, ``0x9002`` tiling flags,
``0x9005`` texture (0) / environment (1) mapping.

**Arnold maps** (and the Arnold material, :mod:`.materials`): no fixed parameter IDs. Reference 0 is a
ParamBlock2 whose parameter 0 is a table of three ``aiPBParameter`` group objects (class 0x3DE3000E38E67D6E,
superclass 0x200) named "results", "parameters" and "connections"; each group references one ``aiPBParameter``
object per parameter, see :func:`read_ai_parameters` (verified on 177,824 objects in 41 files).

``class_name`` is the importer-facing name: "Bitmaptexture" for Bitmap (what the importer's converters expect),
the scripting name for the other decoded classes (:data:`MAP_CLASS_NAMES`), else the name stored in the file.
"""

__all__ = (
    "AI_SHADER",
    "AiParam",
    "BITMAP",
    "MAP_CLASS_NAMES",
    "MapData",
    "TEXMAP_SUPERCLASS",
    "UVGEN_PARAMS",
    "ai_key",
    "is_map_like",
    "object_name",
    "read_ai_parameters",
    "read_map",
)

import dataclasses
import struct

from ..chunks import walk
from ..classes import ClassID
from .. import registry
from ..registry import decoder

TEXMAP_SUPERCLASS = 0xC10
UVGEN_SUPERCLASS = 0xC20            # "Placement" of 2D maps (Bitmap, Checker, Gradient, ...).

BITMAP = ClassID(0x240)
CHECKER = ClassID(0x200)
NOISE = ClassID(0x234)
MIX = ClassID(0x230)
NORMAL_BUMP = ClassID.from_u64(0x63F6A014243E22C6)

AI_PARAMETER = ClassID.from_u64(0x3DE3000E38E67D6E)
AI_PARAMETER_SUPERCLASS = 0x200

MAP_CLASS_NAMES = {
    BITMAP: "Bitmaptexture",
    CHECKER: "Checker",
    NOISE: "Noise",
    MIX: "Mix",
    NORMAL_BUMP: "Normal_Bump",
}

# MtlBase header chunks (see the module docstring).
CHUNK_NAME = 0x4001
CHUNK_HEADER_FLAGS = 0x4003

CHUNK_ASSET_ID = 0x0002
CHUNK_BITMAP_INFO = 0x0003
CHUNK_BITMAP_INFO_ASSET = 0x1260
# Unverified (overview.md §5.2, prior-art importer): a UTF-16 path string in older files. Not in the corpus.
CHUNK_LEGACY_PATH = 0x1230

# UVGen old ParamBlock (reference 0 of the Placement object): index -> key. Verified on the 1,779 corpus Bitmaps:
# 0-6 from their defaults (0, 0, 1, 1, 0, 0, 0) and value ranges (tiling 0.0254..10 and -1 for flipped maps,
# angles 1.5708 / 3.1416 = 90 / 180 degrees in radians, only id 6 varies: W angle); 7 blur (1.0, or the minimum
# 0.01); 8-11 the noise group: in the two Bitmaps with noise on, 8 = 13.6, 9 = 0.581, 10 = 3 (int), 11 = 0.35, and
# defaults 1, 1, 1, 0 elsewhere.
UVGEN_PARAMS = {
    0: "u_offset", 1: "v_offset", 2: "u_tiling", 3: "v_tiling", 4: "u_angle", 5: "v_angle", 6: "w_angle",
    7: "blur",
    8: "noise_amount", 9: "noise_size", 10: "noise_levels", 11: "noise_phase",
    12: "blur_offset",      # Guess: the last float of the UI's "Blur offset"; 0 in 1,776 Bitmaps.
}
# UVGen leaf chunks.
CHUNK_UV_FLAGS = 0x9002         # Bits 0 / 1: U / V tiling (0x...03 in 1,766 Bitmaps; 0 in decal-like ones).
CHUNK_UV_ENVIRONMENT = 0x9005   # 1 in the 33 Bitmaps used as environment / reflection maps, else 0.
CHUNK_UV_MAPPING = 0x9009       # 4 for texture maps (explicit channel); 1 for most environment maps. Raw value.
CHUNK_UV_CHANNEL = 0x900B       # Map channel: 1 in 1,770 Bitmaps; 2 only on objects with UVW Map modifiers.

# Parameters of the other decoded map classes: parameter ID -> key. Established from types, defaults and the
# classes of the referenced maps over the corpus (130 Checkers, 386 Noises, 59 Mixes, 65 Normal Bumps). Keys whose
# value is a map hold a MapData.
CHECKER_PARAMS = {0: "soften", 1: "color1", 2: "color2", 3: "map1", 4: "map2", 5: "map1_on", 6: "map2_on"}
NOISE_PARAMS = {0: "color1", 1: "color2", 2: "map1", 3: "map2", 4: "map1_on", 5: "map2_on", 6: "size",
                7: "phase", 8: "levels", 9: "threshold_low", 10: "threshold_high",
                11: "noise_type"}       # Guess for 11: 0 regular, 1 fractal, 2 turbulence (values 0-2).
MIX_PARAMS = {0: "mix_amount", 1: "lower", 2: "upper", 3: "use_curve", 4: "color1", 5: "color2", 6: "map1",
              7: "map2", 8: "mask", 9: "map1_on", 10: "map2_on", 11: "mask_on"}
NORMAL_BUMP_PARAMS = {0: "mult_spin", 1: "bump_spin", 2: "normal_map", 3: "bump_map", 4: "map1on", 5: "map2on",
                      6: "method",      # Guess: 0 = tangent space (0 in every corpus Normal Bump).
                      7: "flip_red", 8: "flip_green", 9: "swap_rg"}     # Guess: order of the UI check boxes.
# Class -> (reference slot of the ParamBlock2, table).
MAP_PARAMS = {
    CHECKER: (1, CHECKER_PARAMS),
    NOISE: (1, NOISE_PARAMS),
    MIX: (0, MIX_PARAMS),
    NORMAL_BUMP: (0, NORMAL_BUMP_PARAMS),
}

# aiPBParameter: chunk 0x0001 name, 0x0002 type, container 0x0003 with 0x0004 (1), 0x0005 (always 0xFFFFFFFF in
# the corpus) and 0x0006 the value. Type codes from the value sizes of all 175,022 parameter objects and the names.
AI_FLOAT, AI_INT, AI_RGB, AI_VECTOR, AI_BOOL, AI_SHADER, AI_GROUP, AI_RGBA = 0, 1, 2, 3, 4, 15, 21, 23
_AI_FORMATS = {AI_FLOAT: "<f", AI_INT: "<i", AI_RGB: "<3f", AI_VECTOR: "<3f", AI_BOOL: "<I", AI_RGBA: "<4f"}


@dataclasses.dataclass
class MapData:
    """A texture map: importer-facing class name, name, parameters, file path (bitmaps) and child maps."""
    class_name: str
    name: str | None
    params: dict
    path: str | None                    # Bitmaps: the file path as stored (see :mod:`maxfile.assets`).
    sub_maps: list                      # Child maps (MapData), in parameter order.
    index: int | None = None            # Object index of the map.
    path_source: str | None = None
    """Where the path came from: "asset:filename" (the file name parameter's asset ID), "asset:bitmap_info" (the
    bitmap-info asset ID), "filename" (a plain string, unverified), "0x1230" (legacy chunk, unverified)."""
    asset_index: int | None = None      # Position of the asset in the asset metadata stream.
    asset_guid: str | None = None       # The asset ID (:func:`maxfile.assets.format_guid`).
    resolved_path: str | None = None    # The absolute path Max last resolved the asset to (FileAssetMetaData3).
    source_class: str | None = None     # The class name stored in the file (e.g. "Bitmap").


@dataclasses.dataclass
class AiParam:
    """One Arnold parameter (an ``aiPBParameter`` object)."""
    name: str
    type: int
    value: object = None                # float, int, bool or tuple; None for shaders and unknown types.
    map_index: int | None = None        # Shaders: object index of the connected map (reference slot 0).
    index: int | None = None            # Object index of the parameter object.


def object_name(obj) -> str | None:
    """The name of a material or map (see the module docstring), None when it has none or it is empty."""
    chunk = obj.chunk
    for child in chunk.children:
        if child.is_container and child.children and child.children[0].type == CHUNK_NAME:
            if child.find(CHUNK_HEADER_FLAGS) is not None and not child.children[0].is_container:
                return child.children[0].string() or None
    top = chunk.find(CHUNK_NAME)
    if top is not None and not top.is_container and chunk.find(CHUNK_HEADER_FLAGS) is not None:
        return top.string() or None
    return None


def is_map_like(obj, ctx) -> bool:
    """True for texture maps (superclass 0xC10), and for objects carrying the legacy path chunk (unverified)."""
    if obj.superclass_id == TEXMAP_SUPERCLASS:
        return True
    key = ("map_like", obj.index)
    if key not in ctx.cache:
        ctx.cache[key] = _legacy_path(obj, ctx) is not None
    return ctx.cache[key]


# -----------------------------------------------------------------------------
# Bitmap file

def _bitmap_file(pb_obj, ctx):
    """
    ``(asset ID or None, plain path or None, source)`` from a Bitmap's ParamBlock2 object (reference 1). The asset
    ID is a :class:`~maxfile.objects.paramblock.AssetRef` (file name parameter) or 16 raw bytes (bitmap info).
    """
    block = ctx.scene.param_block(pb_obj)
    if block is not None:
        for param in block.entries:
            if param.kind != "filename":
                continue
            if isinstance(param.value, str) and param.value:
                return None, param.value, "filename"    # Unverified: no corpus Bitmap stores a plain file name.
            if param.value is not None and getattr(param.value, "raw", None):
                return param.value, None, "asset:filename"
            break
    info = pb_obj.chunk.find(CHUNK_BITMAP_INFO)
    if info is not None and info.is_container:
        holder = info.find(CHUNK_BITMAP_INFO_ASSET)
        found = holder.find(CHUNK_ASSET_ID) if holder is not None and holder.is_container else None
        if found is not None and found.payload_size == 16:
            return found.data, None, "asset:bitmap_info"
    return None, None, None


def _legacy_path(obj, ctx):
    """Unverified fallback: a ``0x1230`` UTF-16 path below the object or its direct references (depth 3)."""
    for candidate in [o for _slot, o in ctx.refs(obj)] + [obj]:
        for _depth, chunk in walk([candidate.chunk], 3):
            if chunk.type == CHUNK_LEGACY_PATH and not chunk.is_container:
                return chunk.string()
    return None


def _read_bitmap(obj, ctx, result):
    pb_obj = ctx.ref(obj, 1)
    guid, text, source = _bitmap_file(pb_obj, ctx) if pb_obj is not None else (None, None, None)
    if guid is not None:
        from ..assets import format_guid
        result.asset_guid = format_guid(getattr(guid, "raw", guid))
        assets = ctx.asset_metadata()
        entry = assets.get(guid) if assets is not None else None
        if entry is not None:
            result.path = entry.path
            result.resolved_path = entry.resolved_path
            result.asset_index = entry.index
            result.path_source = source
        else:
            ctx.warn("object {:d} (Bitmap): asset {:s} not in the asset metadata".format(
                obj.index, result.asset_guid))
    elif text is not None:
        result.path, result.path_source = text, source
    _read_uvgen(ctx.ref(obj, 0), ctx, result.params)


def _read_uvgen(uv, ctx, params):
    if uv is None or uv.superclass_id != UVGEN_SUPERCLASS:
        return
    block = ctx.scene.param_block(ctx.ref(uv, 0))
    if block is not None:
        for index, key in UVGEN_PARAMS.items():
            value = block.value(index)
            if value is not None:
                params[key] = value
    for chunk in uv.chunk.children:
        if chunk.is_container or chunk.payload_size < 4:
            continue
        value = chunk.u32s()[0]
        if chunk.type == CHUNK_UV_CHANNEL:
            params["map_channel"] = value
        elif chunk.type == CHUNK_UV_FLAGS:
            params["u_tile"] = bool(value & 0x1)
            params["v_tile"] = bool(value & 0x2)
            params["u_mirror"] = bool(value & 0x4)      # Guess: bit 2 (set with tiling 1 x 7, 2 x 1.5).
            params["v_mirror"] = bool(value & 0x8)      # Guess.
            params["uv_flags"] = value                  # Raw: higher bits not understood (0x50000000, 0x08000000).
        elif chunk.type == CHUNK_UV_ENVIRONMENT:
            params["environment"] = bool(value)
        elif chunk.type == CHUNK_UV_MAPPING:
            params["mapping"] = value


# -----------------------------------------------------------------------------
# Arnold parameters

def _ai_name(obj):
    found = obj.chunk.find(0x0001)
    return found.string() if found is not None and not found.is_container else None


def _is_ai_parameter(obj):
    return obj.class_id == AI_PARAMETER and obj.superclass_id == AI_PARAMETER_SUPERCLASS


def _ai_param(obj):
    name = _ai_name(obj)
    type_chunk = obj.chunk.find(0x0002)
    if name is None or type_chunk is None or type_chunk.payload_size < 4:
        return None
    ptype = type_chunk.u32s()[0]
    param = AiParam(name, ptype, index=obj.index)
    holder = obj.chunk.find(0x0003)
    value_chunk = holder.find(0x0006) if holder is not None and holder.is_container else None
    if ptype == AI_SHADER:
        param.map_index = obj.references.get(0)
    elif value_chunk is not None and ptype in _AI_FORMATS:
        fmt = _AI_FORMATS[ptype]
        if value_chunk.payload_size >= struct.calcsize(fmt):
            values = struct.unpack_from(fmt, value_chunk.data)
            if ptype == AI_BOOL:
                param.value = bool(values[0])
            else:
                param.value = values[0] if len(values) == 1 else tuple(values)
    return param


def read_ai_parameters(obj, ctx, group="parameters") -> dict[str, AiParam] | None:
    """
    The Arnold parameters of ``obj`` by name, from its ``group`` group ("parameters"; "connections" holds the same
    values and maps in all 837 corpus Standard Surface materials), or None when ``obj`` isn't built that way.
    """
    block = ctx.scene.param_block(ctx.ref(obj, 0))
    if block is None:
        return None
    table = block.value(0)
    if not isinstance(table, list):
        return None
    for index in table:
        if index is None:
            continue
        holder = ctx.scene.objects[index]
        if not _is_ai_parameter(holder):
            return None
        if _ai_name(holder) != group:
            continue
        params = {}
        for _slot, child in ctx.refs(holder):
            if _is_ai_parameter(child):
                param = _ai_param(child)
                if param is not None:
                    params[param.name] = param
        return params
    return None


def ai_key(name: str) -> str:
    """Scripting-style key of an Arnold parameter: lower case, "." -> "_" ("specular_IOR" -> "specular_ior")."""
    return name.lower().replace(".", "_")


def _read_ai_map(params, ctx, result):
    for name, param in params.items():
        if param.type == AI_SHADER:
            if param.map_index is not None:
                child = read_map(ctx.scene.objects[param.map_index], ctx)
                result.params[ai_key(name)] = child
                result.sub_maps.append(child)
        elif param.value is not None:
            result.params[ai_key(name)] = param.value


# -----------------------------------------------------------------------------

def _map_value(index, ctx):
    if index is None:
        return None
    obj = ctx.scene.objects[index]
    return read_map(obj, ctx) if obj.superclass_id == TEXMAP_SUPERCLASS else None


def _read_table(obj, ctx, result, slot, table):
    block = ctx.scene.param_block(ctx.ref(obj, slot))
    if block is None:
        ctx.warn("object {:d} ({:s}): no parameter block in reference {:d}".format(
            obj.index, result.class_name, slot))
        return
    for param_id, key in table.items():
        param = block.get(param_id)
        if param is None:
            continue
        if param.kind == "texmap":
            child = _map_value(param.value, ctx)
            if child is not None:
                result.params[key] = child
                result.sub_maps.append(child)
        elif param.value is not None:
            result.params[key] = param.value


def _generic_sub_maps(obj, ctx, result):
    """Child maps of a map we have no table for: maps in its references and in its parameter blocks' tables."""
    seen = set()
    for _slot, ref in ctx.refs(obj):
        candidates = []
        if ref.superclass_id == TEXMAP_SUPERCLASS:
            candidates.append(ref.index)
        else:
            block = ctx.scene.param_block(ref)
            if block is not None:
                for param in block.entries:
                    if param.kind == "texmap":
                        candidates.append(param.value)
                    elif param.kind == "table:texmap":
                        candidates.extend(param.value or [])
        for index in candidates:
            if index is None or index in seen or index == obj.index:
                continue
            seen.add(index)
            child = _map_value(index, ctx)
            if child is not None:
                result.sub_maps.append(child)


def read_map(obj, ctx) -> MapData:
    """Read ``obj`` as a map (cached per scene; a map met again while being read is returned unfinished)."""
    key = ("map", obj.index)
    if key in ctx.cache:
        return ctx.cache[key]
    label = obj.class_label()
    class_name = MAP_CLASS_NAMES.get(obj.class_id, label) if obj.superclass_id == TEXMAP_SUPERCLASS else label
    result = MapData(class_name, object_name(obj), {}, None, [], index=obj.index, source_class=label)
    ctx.cache[key] = result
    if obj.superclass_id == TEXMAP_SUPERCLASS and obj.class_id == BITMAP:
        _read_bitmap(obj, ctx, result)
    elif obj.superclass_id == TEXMAP_SUPERCLASS and obj.class_id in MAP_PARAMS:
        slot, table = MAP_PARAMS[obj.class_id]
        _read_table(obj, ctx, result, slot, table)
        if obj.class_id in (CHECKER, NOISE):
            _read_uvgen(ctx.ref(obj, 0), ctx, result.params)
    else:
        ai_params = read_ai_parameters(obj, ctx)
        if ai_params is not None:
            _read_ai_map(ai_params, ctx, result)
        else:
            _generic_sub_maps(obj, ctx, result)
    if result.path is None and obj.class_id != BITMAP:
        legacy = _legacy_path(obj, ctx)
        if legacy is not None:
            result.path, result.path_source = legacy, "0x1230"
    return result


# Map classes with a decoder (others are still read by read_map() when a material references them).
DECODED_MAPS = (
    BITMAP, CHECKER, NOISE, MIX, NORMAL_BUMP,
    ClassID(0x270),                         # Gradient
    ClassID.from_u64(0x6EC3730C),           # Falloff
    ClassID(0x220),                         # Mask
    ClassID(0x2D0),                         # Color Correction
    ClassID.from_u64(0x43383A511DEC5B86),   # Gradient Ramp
    ClassID(0x280),                         # Composite
    ClassID.from_u64(0xB65F556E7E73161F),   # Bump 2D (Arnold)
    ClassID.from_u64(0x111940BBC90017A5),   # Cellular
    ClassID.from_u64(0x69664CDC64035FB9),   # Tiles
    ClassID(0x290),                         # RGB Multiply
    ClassID(0x218),                         # Dent
    ClassID.from_u64(0x0A845E7C),           # Smoke
    ClassID.from_u64(0x284441BC00000000),   # Raytrace (map)
)


# Only classes the registry knows get the decoder (the decoder list must name them); the rest are listed in
# NEEDS_REGISTRY until they are added there.
NEEDS_REGISTRY = tuple(c for c in DECODED_MAPS if registry.known_class(c, TEXMAP_SUPERCLASS) is None)


@decoder(*(c for c in DECODED_MAPS if c not in NEEDS_REGISTRY), kind="texmap",
         name="Texture maps (Bitmap path, UV placement, child maps)",
         superclass_id=TEXMAP_SUPERCLASS, verified=True)
def texture_map(obj, ctx):
    """Name, parameters, file path (Bitmap) and child maps."""
    return read_map(obj, ctx)
