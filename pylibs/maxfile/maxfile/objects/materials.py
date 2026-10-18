# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Materials (superclass 0xC00), worked out on the local corpus (623 files, Max 2008-2018): 15,299 Standard,
2,119 Physical Material, 837 Arnold Standard Surface, 320 Multi/Sub-Object materials and ~40 rarer classes. The
evidence for every table is in the format notes (materials section); the short form is next to each table here.

``params`` holds values under the keys of the importer's converters
(``scripts/addons_core/mx_io_max/materials/convert.py``: the scripting names of the parameters), ``maps`` the
maps under ``<param>_map`` keys (Arnold: ``<param>_shader``), with ``<map key>_amount`` / ``<map key>_on`` in
``params`` where the material has them. ``class_name`` is the converters' class name (:data:`CLASS_NAMES`).

- **Name**: the MtlBase header, see :func:`maxfile.objects.maps.object_name` (all four main classes verified).
- **Standard** (class 0x2): references 1 = ``Texmaps`` (0x1200 / 0x1080), 2 = the shader (superclass 0x10B0:
  Blinn, Phong, ...), 3-7 = ParamBlock2s (3 shader basics, 4 extended, 5 supersampling, 6 a map table, 7
  dynamics), 8 = the sampler. The colours, specular level and glossiness are in the shader's ParamBlock2
  (shader reference 0). The maps are in the ``Texmaps`` object: reference 2i+1 = map i, 2i = its animated amount;
  chunk ``0x5003`` = bit mask of enabled maps; ``0x5100 + i`` = amount of map i (fraction; absent = 1.0). The map
  table in ParamBlock2 6 repeats this but is stale in 61 corpus materials (empty or other maps), so it is only a
  fallback. Which slot is which map depends on the shader (:data:`SHADERS`).
- **Physical Material**: one ParamBlock2 in reference 0, see :data:`PHYSICAL_PARAMS`.
- **Arnold Standard Surface**: parameters by name in ``aiPBParameter`` objects
  (:func:`maxfile.objects.maps.read_ai_parameters`).
- **Multi/Sub-Object** (0x200): reference 0 = ParamBlock2 (0 materials, 1 enabled, 2 names, 3 IDs), reference
  i+1 = sub-material i, chunk ``0x4002`` = count. The material table of the ParamBlock2 is empty in 131 of the 320
  corpus materials, so the references are used. IDs are stored 0-based: :attr:`MaterialData.sub_ids` adds 1.
- **Blend**, **Double Sided**, **Top/Bottom**, **Shellac**: the two materials in references 1 and 2
  (:attr:`MaterialData.components`), parameters in reference 0.

Other classes get their name, the maps they reference directly (:attr:`MaterialData.unassigned_maps`) and their
parameter blocks (:attr:`MaterialData.param_blocks`, for investigation with ``maxdump --object N --decode``).
"""

__all__ = (
    "CLASS_NAMES",
    "MATERIALS",
    "MaterialData",
    "PHYSICAL_PARAMS",
    "SHADERS",
    "read_material",
)

import dataclasses
import struct

from ..classes import ClassID
from .. import registry
from ..registry import decoder
from .maps import (AI_SHADER, TEXMAP_SUPERCLASS, MapData, ai_key, object_name, read_ai_parameters,
                   read_map)

MATERIAL_SUPERCLASS = 0xC00

STANDARD = ClassID(0x2)
MULTI_SUB = ClassID(0x200)
PHYSICAL = ClassID.from_u64(0xDEADC0013D6B1CEC)
ARNOLD_SURFACE = ClassID.from_u64(0x62F74B4C7E73161F)
BLEND = ClassID(0x250)
DOUBLE_SIDED = ClassID(0x210)
TOP_BOTTOM = ClassID(0x100)
SHELLAC = ClassID.from_u64(0x46EE536A)

# Class -> class name used by the importer's converters (their scripting names).
CLASS_NAMES = {
    STANDARD: "Standardmaterial",
    MULTI_SUB: "Multimaterial",
    PHYSICAL: "PhysicalMaterial",
    ARNOLD_SURFACE: "ai_standard_surface",
    BLEND: "Blend",
    DOUBLE_SIDED: "DoubleSided",
    TOP_BOTTOM: "TopBottom",
    SHELLAC: "Shellac",
    # Unverified: not in the corpus; class IDs from overview.md §5 (no parameters are read for them).
    ClassID.from_u64(0x7034695C37BF3F2F): "VRayMtl",
    ClassID.from_u64(0x11731B4B6066686A): "VRay2SidedMtl",
    ClassID.from_u64(0x448931DD70BE6506): "CoronaMtl",
    ClassID.from_u64(0x871517206912AB89): "CoronaPhysicalMtl",
    ClassID.from_u64(0x8425554E65486584): "CoronaLayeredMtl",
    ClassID.from_u64(0x44CFDE95BEC41C73): "CoronaSkinMtl",
    ClassID.from_u64(0xCA41F54622C05DD6): "CoronaHairMtl",
}
MATERIALS = CLASS_NAMES     # Old name.

# Other material classes of the corpus that get a decoder (name, maps, parameter blocks only).
OTHER_MATERIALS = (
    ClassID.from_u64(0x4A16365470B05735),   # Arch & Design
    ClassID.from_u64(0x329B106E27190FF4),   # Raytrace
    ClassID.from_u64(0x4D3960A501A8169A),   # Ink 'n Paint
    ClassID.from_u64(0x213DAAF81ED415E4),   # Autodesk Material
    ClassID.from_u64(0x13640AF661DC0CD7),   # Composite
    ClassID(0x260),                         # Matte/Shadow
    ClassID.from_u64(0x7A10ACA56926BA21),   # mental ray
    ClassID.from_u64(0x6CFF42F72914493D),   # Advanced Lighting Override
    ClassID.from_u64(0xA964C1587E73161F),   # Standard Hair (Arnold)
    ClassID.from_u64(0x691E303713D11BBE),   # Architectural
    ClassID.from_u64(0xC25EA83B7773160F),   # ProMaterials: Plastic/Vinyl
    ClassID.from_u64(0xB9544C137773160F),   # ProMaterials: Metal
    ClassID.from_u64(0xA5605F307773160F),   # ProMaterials: Generic
    ClassID.from_u64(0xB96170207773160F),   # ProMaterials: Metallic Paint
    ClassID.from_u64(0x4D4EB17C7773160F),   # ProMaterials: Solid Glass
    ClassID.from_u64(0xBB0E4F267773160F),   # ProMaterials: Mirror
    ClassID.from_u64(0x572151887E73161F),   # Atmospheric Volume / Scattering (Arnold)
    ClassID.from_u64(0x72928E198CCDF7BC),   # Map to Material
    ClassID.from_u64(0xAB3C62177773160F),   # Subsurface Scattering Fast Material
    ClassID.from_u64(0x6133DAF20ED995E4),   # DirectX Shader
)

# -----------------------------------------------------------------------------
# Standard

# Shader parameters (ParamBlock2 in reference 0 of the shader). id -> (key, scale). "percent" values are stored as
# fractions; the converters want Max's percent numbers, hence the scale 100.
# Verified on 14,799 Blinn, 302 Phong and 23 Metal blocks: ids 0-2 are colours with the defaults 0.588 grey /
# 0.588 grey / 0.9 grey; 0 and 1 are equal in 11,878 of the 12,289 blocks where bool 4 is on (the
# ambient/diffuse lock) and differ in 2,695 of 2,835 where it is off, so 0 = ambient, 1 = diffuse (1 carries the
# varied colours); 9 = specular level (0 default; 0.05, 1.0 common), 10 = glossiness (0.1 default = 10),
# 11 = soften (0.1 in 760 of 773); 7 = self-illumination amount (> 0 only in particle materials such as
# "SparksShader", "FireFlies"), 8 its colour.
BLINN_PARAMS = {
    0: ("ambient", None), 1: ("diffuse", None), 2: ("specular", None),
    3: ("ad_texture_lock", None),           # Guess: on in 771 of 773.
    4: ("ambient_diffuse_lock", None),
    5: ("diffuse_specular_lock", None),     # On in 9 blocks, all with specular == diffuse.
    6: ("use_self_illum_color", None),      # The colour (8) is non-black in 134 blocks with 6 on, 5 with it off.
    7: ("self_illum_amount", 100.0), 8: ("self_illum_color", None),
    9: ("specular_level", 100.0), 10: ("glossiness", 100.0), 11: ("soften", None),
}
# Other shaders: the first three colours follow the same pattern (Anisotropic, Oren-Nayar-Blinn, Translucent:
# ids 0 and 1 equal with the lock, 2 = 0.9 grey default). Multi-Layer and Strauss: guesses from the values.
COLOR_PARAMS = {0: ("ambient", None), 1: ("diffuse", None), 2: ("specular", None)}

# Map slots of the Texmaps object (index -> name; the key is name + "_map"). The first slots belong to the shader,
# then come bump, reflection, refraction and displacement. Verified for Blinn/Phong from file names and map
# classes of the corpus: 1 diffuse ("_diffuse", Checker), 2 "specular", 3 "specular.jpg", 4 "gloss.jpg",
# 5 "emissive.jpg" and Falloff maps, 6 "_alpha" and Mask maps, 8 "_bump" and Normal Bump maps (default amount 0.3
# in 13,946 materials), 9 Raytrace / Flat Mirror / "cubemap", 10 Raytrace. Anisotropic: 11 "_bmp" (bump);
# Oren-Nayar-Blinn: 10 bump, 13 "bodydisplace"; Multi-Layer: 17 bump, 18 Reflect/Refract.
_TAIL = ("bump", "reflection", "refraction", "displacement")


def _maps(head, tail_start):
    table = dict(head)
    if tail_start is not None:
        table.update({tail_start + i: name for i, name in enumerate(_TAIL)})
    return table


BLINN_MAPS = _maps({0: "ambient", 1: "diffuse", 2: "specular", 3: "specular_level", 4: "glossiness",
                    5: "self_illum", 6: "opacity", 7: "filter"}, 8)

# Shader class (superclass 0x10B0) -> (name, shader parameters, map slots). The shader index stored in
# ParamBlock2 3 (parameter 0) matches these classes in all 1,130 materials used in the corpus scenes (0 Anisotropic,
# 1 Blinn, 2 Metal, 3 Multi-Layer, 4 Oren-Nayar-Blinn, 5 Phong, 6 Strauss, 7 Translucent).
SHADERS = {
    ClassID(0x38): ("Blinn", BLINN_PARAMS, BLINN_MAPS),
    ClassID(0x37): ("Phong", BLINN_PARAMS, BLINN_MAPS),
    ClassID(0x39): ("Metal", BLINN_PARAMS, BLINN_MAPS),        # Same 12 parameters as Blinn (23 blocks).
    ClassID.from_u64(0x2857F460): ("Anisotropic", COLOR_PARAMS, _maps({1: "diffuse"}, 11)),
    ClassID.from_u64(0x2857F421): ("Oren-Nayar-Blinn", COLOR_PARAMS, _maps({1: "diffuse"}, 10)),
    ClassID.from_u64(0x2857F470): ("Multi-Layer", {0: ("ambient", None), 1: ("diffuse", None)},   # Guess.
                                   _maps({1: "diffuse"}, 17)),
    ClassID.from_u64(0x2857F450): ("Strauss", {0: ("diffuse", None)}, {0: "diffuse"}),           # Guess.
    ClassID.from_u64(0x2857F480): ("Translucent Shader", COLOR_PARAMS, {1: "diffuse"}),          # Guess.
}
SHADER_SUPERCLASS = 0x10B0

# ParamBlock2 3 (shader basics). Verified: 0 = shader index (see SHADERS); 1 = wire (on in materials named "wire",
# "body wire", "grid", "Edges"); 2 = two-sided (on in "Leaf", "Flag", "teeth01", ...); 3 = face map (on in
# particle materials); 4 = faceted (Guess: never on).
STANDARD_BASIC = {0: ("shader_type", None), 1: ("wire", None), 2: ("two_sided", None), 3: ("face_map", None),
                  4: ("faceted", None)}
# ParamBlock2 4 (extended). Verified: 1 = opacity (1.0 default; 0.0 in smoke, dust and fire particle materials
# that use opacity maps), 2 = filter colour (0.5 grey default), 6 = index of refraction (1.5 default).
STANDARD_EXTENDED = {
    1: ("opacity", 100.0), 2: ("filter_color", None), 6: ("ior", None),
    4: ("opacity_type", None),          # Guess: int 0-1 (filter / subtractive / additive in the UI).
    5: ("opacity_falloff", 100.0),      # Guess: percent, 0 default.
    7: ("wire_size", None),             # Guess: 1.0 default.
}
TEXMAPS_ENABLED = 0x5003
TEXMAPS_AMOUNT = 0x5100
TEXMAPS_COUNT = 24

# -----------------------------------------------------------------------------
# Physical Material: ParamBlock2 in reference 0 (115 parameters in all 2,119 corpus materials). id -> key.
# Evidence: defaults (base weight 1.0, reflectivity 1.0, BRDF 0.05 / 1.0 / 5.0, SSS depth 10 / scale 1 / scatter
# colour (1, 0.5, 0.25), emission 1500 cd/m2 and 6500 K) and names: metalness 1.0 in "Metal", "chrome", "Wheels",
# "Metal - Steel, Polished", 0.5 in "Vehicle_Body"; transparency 1.0 in "Solid Glass", "Glass", 0.85 in
# "Windows_Glass"; trans_ior 1.33 in "water", 1.5-1.52 in glass; thin_walled on in window glass; roughness 0.6
# with the inversion off in "Wall Paint", "Laminate - Linen,Matte" and 1.0 / 0.9 with it on (glossiness) in
# "Chrome metal", "Metal - Steel, Polished", "Mirror"; emission 1.0 in "Template Plankton shader".
PHYSICAL_PARAMS = {
    0: "material_mode", 1: "base_weight", 2: "base_color", 3: "reflectivity", 4: "roughness", 5: "roughness_inv",
    6: "metalness", 10: "refl_color", 11: "diff_roughness", 12: "brdf_mode", 13: "brdf_low", 14: "brdf_high",
    15: "brdf_curve",
    20: "anisotropy", 21: "anisoangle", 22: "aniso_mode", 23: "aniso_channel",     # Guess (rarely changed).
    30: "transparency", 31: "trans_color", 32: "trans_depth", 33: "trans_ior",
    34: "trans_roughness_lock", 35: "trans_roughness", 36: "trans_roughness_inv",   # Guess (types and order).
    37: "thin_walled",
    40: "scattering", 41: "sss_color", 42: "sss_depth", 43: "sss_scale", 44: "sss_scatter_color",
    50: "emission", 51: "emit_color", 52: "emit_luminance", 54: "emit_kelvin",
    60: "coating", 61: "coat_color", 62: "coat_roughness", 63: "coat_roughness_inv", 64: "coat_affect_color",
    65: "coat_affect_roughness", 66: "coat_ior",
    230: "bump_map_amt", 231: "clearcoat_bump_map_amt", 232: "displacement_map_amt",
}
# Maps 100-120 (enabled flags 150-170) follow the parameters' order: 101 holds 319 Bitmaps (base colour), 104
# Tiles and Falloff (roughness), 110 / 114 Color Correction (colours), 117 "emissive.jpg" / "background.tif"
# (emission colour). A map is never present with its flag off.
PHYSICAL_MAPS = ("base_weight", "base_color", "reflectivity", "refl_color", "roughness", "metalness",
                 "diff_rough", "anisotropy", "aniso_angle", "transparency", "trans_color", "trans_rough",
                 "trans_ior", "scattering", "sss_color", "sss_scale", "emission", "emit_color", "coat",
                 "coat_color", "coat_rough")
PHYSICAL_MAP_BASE = 100
PHYSICAL_MAP_ON_BASE = 150
# 130-133 (flags 180-183): bump (Bitmap, Noise, Smoke, Tiles: verified), coating bump, displacement (Noise masks on
# flower petals), cutout (a Mix on "feather"). Guess for 131-133: order only.
PHYSICAL_SPECIAL_MAPS = {130: "bump_map", 131: "coat_bump_map", 132: "displacement_map", 133: "cutout_map"}
PHYSICAL_SPECIAL_ON_BASE = 180

# -----------------------------------------------------------------------------
# Multi/Sub-Object ParamBlock2 (reference 0).
MULTI_MATERIALS, MULTI_ENABLED, MULTI_NAMES, MULTI_IDS = 0, 1, 2, 3
MULTI_COUNT = 0x4002
# Verified on the corpus: IDs are 0-based on disk. Of 1,064 meshes using a Multi/Sub-Object material, the face
# material IDs as stored (0-based) are all in the stored ID list for 1,029; with 1 added they are for only 647, and
# never when the stored ones aren't. The UI shows them 1-based.
MULTI_ID_OFFSET = 1

# Two-material classes: class -> (component names, reference 0 parameters id -> key).
COMPOSITES = {
    BLEND: (("material1", "material2"), {
        0: "mix_amount", 1: "lower", 2: "upper", 3: "use_curve",
        8: "map1_enabled", 9: "map2_enabled", 10: "mask_enabled",     # Guess: order of the UI check boxes.
    }),
    DOUBLE_SIDED: (("front", "back"), {4: "translucency"}),
    TOP_BOTTOM: (("top", "bottom"), {4: "blend", 5: "position", 6: "coordinates"}),
    SHELLAC: (("base", "shellac"), {2: "shellac_color_blend"}),
}
BLEND_MASK_SLOT = 3


@dataclasses.dataclass
class MaterialData:
    """A material: name, parameters, maps and sub-materials."""
    class_name: str                     # Converter class name (CLASS_NAMES), else the class name in the file.
    name: str | None
    params: dict                        # Parameters under the converters' keys.
    maps: dict[str, MapData | None]     # Maps under "<param>_map" ("<param>_shader" for Arnold) keys.
    sub_materials: "list[MaterialData | None] | None"   # Multi/Sub-Object only.
    sub_ids: list[int] | None           # Multi/Sub-Object: material ID of each sub-material, 1-based as in Max.
    index: int | None = None            # Object index of the material.
    unassigned_maps: dict[int, MapData] = dataclasses.field(default_factory=dict)
    """Maps whose meaning is unknown: by Texmaps slot for Standard materials, else by reference slot."""
    param_blocks: list[int] = dataclasses.field(default_factory=list)
    """Object indices of the material's parameter blocks (for investigation)."""
    sub_names: list[str | None] | None = None
    """Multi/Sub-Object: the name given to each sub-material slot (often empty)."""
    components: "list[MaterialData | None] | None" = None
    """Blend, Double Sided, Top/Bottom, Shellac and other materials made of materials: the materials they combine,
    in reference order (names in params["components"])."""
    source_class: str | None = None     # The class name stored in the file.


def _scaled(value, scale):
    if scale is None or value is None:
        return value
    if isinstance(value, tuple):
        return tuple(v * scale for v in value)
    return value * scale


def _rgb(value):
    """Colours as 3-tuples (RGBA parameters drop alpha)."""
    if isinstance(value, tuple) and len(value) == 4:
        return value[:3]
    return value


def _apply(params, block, table):
    if block is None:
        return
    for param_id, (key, scale) in table.items():
        value = block.value(param_id)
        if value is not None:
            params[key] = _scaled(value, scale) if not isinstance(value, bool) else value


def _map(index, ctx):
    if index is None:
        return None
    obj = ctx.scene.objects[index]
    return read_map(obj, ctx) if obj.superclass_id == TEXMAP_SUPERCLASS else None


def _sub_material(obj, ctx):
    if obj is None or obj.superclass_id != MATERIAL_SUPERCLASS:
        return None
    value = ctx.decode(obj)
    if isinstance(value, MaterialData):
        return value
    return read_material(obj, ctx)


def _table_strings(param):
    """
    A ``table:string`` parameter re-read from its record: names are UTF-16LE in newer files (ParamBlock2 records
    0x100E), which the parameter-block reader returns cut after the first character. Falls back to its value.
    """
    raw = param.raw
    try:
        pos = 15
        (count,) = struct.unpack_from("<I", raw, pos)
        pos += 4
        out = []
        for _ in range(count):
            pos += 1                                        # Item flags.
            (n,) = struct.unpack_from("<I", raw, pos)
            pos += 4
            if n == 0xFFFFFFFF:
                out.append(None)
                continue
            data = raw[pos:pos + n]
            if len(data) != n:
                raise ValueError("short string")
            pos += n
            if n >= 2 and n % 2 == 0 and data.endswith(b"\0\0"):
                text = data.decode("utf-16-le", errors="replace")
            else:
                text = data.decode("latin-1")
            out.append(text.split("\0", 1)[0] or None)
        return out
    except (struct.error, ValueError):
        return [v or None for v in (param.value or [])]


def _read_standard(obj, ctx, mat):
    params, scene = mat.params, ctx.scene
    shader = ctx.ref(obj, 2)
    info = SHADERS.get(shader.class_id) if shader is not None and shader.superclass_id == SHADER_SUPERCLASS else None
    shader_block = scene.param_block(ctx.ref(shader, 0)) if shader is not None else None
    if info is None:
        ctx.warn("object {:d} (Standard): shader {!s} not known".format(
            obj.index, shader.class_label() if shader is not None else None))
        shader_name, shader_params, map_names = (shader.class_label() if shader else None), COLOR_PARAMS, {}
    else:
        shader_name, shader_params, map_names = info
    params["shader"] = shader_name
    _apply(params, shader_block, shader_params)
    blocks = {slot: scene.param_block(ctx.ref(obj, slot)) for slot in (3, 4, 5, 6, 7)}
    _apply(params, blocks[3], STANDARD_BASIC)
    _apply(params, blocks[4], STANDARD_EXTENDED)
    mat.param_blocks = [b.object_index for b in [shader_block] + list(blocks.values()) if b is not None]

    texmaps = ctx.ref(obj, 1)
    table = blocks[6]
    table_maps = table.value(1) if table is not None else None
    table_on = table.value(0) if table is not None else None
    enabled_mask, amounts = None, {}
    if texmaps is not None:
        for chunk in texmaps.chunk.children:
            if chunk.is_container or chunk.payload_size < 4:
                continue
            if chunk.type == TEXMAPS_ENABLED:
                enabled_mask = chunk.u32s()[0]
            elif TEXMAPS_AMOUNT <= chunk.type < TEXMAPS_AMOUNT + TEXMAPS_COUNT:
                amounts[chunk.type - TEXMAPS_AMOUNT] = chunk.f32s()[0]
    for i in range(TEXMAPS_COUNT):
        index = texmaps.references.get(2 * i + 1) if texmaps is not None else None
        if index is None and isinstance(table_maps, list) and i < len(table_maps):
            index = table_maps[i]
        tex = _map(index, ctx)
        if tex is None:
            continue
        if enabled_mask is not None:
            enabled = bool(enabled_mask >> i & 1)
        else:
            enabled = bool(table_on[i]) if isinstance(table_on, list) and i < len(table_on) else True
        amount = amounts.get(i, 1.0)
        controller = ctx.ref(texmaps, 2 * i) if texmaps is not None else None
        if controller is not None:
            value = ctx.decode(controller)
            if isinstance(value, float):
                amount = value
        name = map_names.get(i)
        if name is None:
            mat.unassigned_maps[i] = tex
            continue
        key = name + "_map"
        mat.maps[key] = tex
        params[key + "_amount"] = amount
        params[key + "_on"] = enabled


def _read_physical(obj, ctx, mat):
    block = ctx.scene.param_block(ctx.ref(obj, 0))
    if block is None:
        ctx.warn("object {:d} (Physical Material): no parameter block".format(obj.index))
        return
    mat.param_blocks = [block.object_index]
    for param_id, key in PHYSICAL_PARAMS.items():
        value = block.value(param_id)
        if value is not None:
            mat.params[key] = _rgb(value)
    specials = {PHYSICAL_MAP_BASE + i: (name + "_map", PHYSICAL_MAP_ON_BASE + i)
                for i, name in enumerate(PHYSICAL_MAPS)}
    specials.update({pid: (key, PHYSICAL_SPECIAL_ON_BASE + pid - 130) for pid, key in PHYSICAL_SPECIAL_MAPS.items()})
    for param_id, (key, on_id) in specials.items():
        tex = _map(block.value(param_id), ctx)
        if tex is None:
            continue
        mat.maps[key] = tex
        on = block.value(on_id)
        if on is not None:
            mat.params[key + "_on"] = bool(on)


def _read_arnold(obj, ctx, mat):
    params = read_ai_parameters(obj, ctx)
    if params is None:
        ctx.warn("object {:d} ({:s}): Arnold parameters not found".format(obj.index, mat.class_name))
        return
    connected = {}
    for name, param in params.items():
        if name.endswith(".connected"):
            connected[name[:-len(".connected")]] = param.value
    for name, param in params.items():
        key = ai_key(name)
        if param.type == AI_SHADER:
            tex = _map(param.map_index, ctx)
            if tex is not None:
                mat.maps[key] = tex
                base = name[:-len(".shader")] if name.endswith(".shader") else name
                if connected.get(base) is not None:
                    mat.params[key + "_on"] = bool(connected[base])
        elif not name.endswith(".connected") and param.value is not None:
            mat.params[key] = param.value


def _read_multi(obj, ctx, mat):
    block = ctx.scene.param_block(ctx.ref(obj, 0))
    ids = block.value(MULTI_IDS) if block is not None else None
    count_chunk = obj.chunk.find(MULTI_COUNT)
    if isinstance(ids, list):
        count = len(ids)
    elif count_chunk is not None and count_chunk.payload_size >= 4:
        count = count_chunk.u32s()[0]
    else:
        count = max((s for s in obj.references if s > 0), default=0)
    table = block.value(MULTI_MATERIALS) if block is not None else None
    subs = []
    for i in range(count):
        sub = ctx.ref(obj, i + 1)
        if sub is None and isinstance(table, list) and i < len(table) and table[i] is not None:
            sub = ctx.scene.objects[table[i]]
        subs.append(_sub_material(sub, ctx))
    mat.sub_materials = subs
    if isinstance(ids, list) and all(isinstance(v, int) for v in ids):
        mat.sub_ids = [v + MULTI_ID_OFFSET for v in ids]
    else:
        mat.sub_ids = list(range(1, count + 1))
        ctx.warn("object {:d} (Multi/Sub-Object): no material ID list, using 1..{:d}".format(obj.index, count))
    if block is not None:
        names = block.get(MULTI_NAMES)
        if names is not None and names.kind == "table:string":
            mat.sub_names = _table_strings(names)
        enabled = block.value(MULTI_ENABLED)
        if isinstance(enabled, list):
            mat.params["sub_enabled"] = [bool(v) for v in enabled]
        mat.param_blocks = [block.object_index]


def _read_composite(obj, ctx, mat):
    names, table = COMPOSITES[obj.class_id]
    mat.components = [_sub_material(ctx.ref(obj, slot), ctx) for slot in (1, 2)]
    mat.params["components"] = list(names)
    block = ctx.scene.param_block(ctx.ref(obj, 0))
    if block is not None:
        mat.param_blocks = [block.object_index]
        for param_id, key in table.items():
            value = block.value(param_id)
            if value is not None:
                mat.params[key] = value
    if obj.class_id == BLEND:
        mask = _map(obj.references.get(BLEND_MASK_SLOT), ctx)
        if mask is not None:
            mat.maps["mask_map"] = mask


def _read_generic(obj, ctx, mat):
    components = []
    for slot, ref in ctx.refs(obj):
        if ref.superclass_id == TEXMAP_SUPERCLASS:
            mat.unassigned_maps[slot] = read_map(ref, ctx)
        elif ref.superclass_id == MATERIAL_SUPERCLASS:
            components.append(_sub_material(ref, ctx))
        elif ctx.scene.param_block(ref) is not None:
            mat.param_blocks.append(ref.index)
    if components:
        mat.components = components


_READERS = {
    STANDARD: _read_standard,
    PHYSICAL: _read_physical,
    ARNOLD_SURFACE: _read_arnold,
    MULTI_SUB: _read_multi,
    BLEND: _read_composite,
    DOUBLE_SIDED: _read_composite,
    TOP_BOTTOM: _read_composite,
    SHELLAC: _read_composite,
}


def read_material(obj, ctx) -> MaterialData:
    """Read any material object (cached per scene)."""
    key = ("material", obj.index)
    if key in ctx.cache:
        return ctx.cache[key]
    label = obj.class_label()
    mat = MaterialData(CLASS_NAMES.get(obj.class_id, label), object_name(obj), {}, {}, None, None,
                       index=obj.index, source_class=label)
    ctx.cache[key] = mat
    reader = _READERS.get(obj.class_id, _read_generic)
    reader(obj, ctx, mat)
    return mat


# Only classes the registry knows get the decoder (the decoder list must name them); the rest are listed in
# NEEDS_REGISTRY until they are added there. Materials of those classes are still read when referenced by another
# material (read_material).
NEEDS_REGISTRY = tuple(c for c in (*CLASS_NAMES, *OTHER_MATERIALS)
                       if registry.known_class(c, MATERIAL_SUPERCLASS) is None)


@decoder(*(c for c in (*CLASS_NAMES, *OTHER_MATERIALS) if c not in NEEDS_REGISTRY), kind="material",
         name="Materials (name, parameters, maps, sub-materials)", superclass_id=MATERIAL_SUPERCLASS, verified=True)
def material(obj, ctx):
    """Name, parameters under the converters' keys, maps and sub-materials."""
    return read_material(obj, ctx)
