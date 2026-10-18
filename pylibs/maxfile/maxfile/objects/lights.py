# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Lights (superclass 0x30) and cameras (superclass 0x20): parameters, on/off and shadow flags, target nodes.

Everything here was worked out on the local corpus (623 files, Max 2008-2018: 502 lights, 252 cameras); the
evidence for each parameter is given next to it and in ``docs/format/lights.md``. Parameter **names** are the
lower_snake_case names the importer (``mx_io_max.lights``) reads; :attr:`LightData.class_name` /
:attr:`CameraData.class_name` are the scripting names it dispatches on (``Omnilight``, ``Free_Light``, ...).
Every parameter block value is also kept in :attr:`LightData.raw` (``"slot.param_id"`` -> value), named or not.

Layouts:

- **Standard lights** (Omni 0x1011, Target Spot 0x1012, Free Direct 0x1013, Free Spot 0x1014, Target Direct
  0x1015): an old ParamBlock (class 0x8) in reference slot 0 (15 parameters for Omni, 18 for target spot / direct,
  19 for the free ones), the shadow generator (Shadow Map, Ray Traced Shadows, ...) in slot 3, a second old
  ParamBlock (5 parameters, meaning unknown) in slot 4, a projector map in slot 2 when one is set (guess). Switches
  are ``u16`` leaf chunks of the light object itself (:data:`STANDARD_FLAGS`).
- **Photometric lights** (Free / Target Light and the Rectangle, Disc, Sphere, Cylinder variants): six references,
  ParamBlock2s in slots 0 (main), 1 (shadow parameters), 2 (spotlight cone), 3 (photometric web), 5 (shape and
  target distance), the shadow generator in slot 4. Chunk 0x0858 of the light holds the emitter outline (three
  ``f32`` per point: one point at the origin for Free / Target Light, the rectangle's corners for rectangles).
- **Arnold Light**, **Skylight**, **Sun Positioner**, **mr Sun / mr Sky**, **Physical** camera: one ParamBlock2
  in slot 0.
- **Free / Target camera** (0x1001 / 0x1002): an old ParamBlock (9 parameters) in slot 0, the multi-pass effect
  (Depth of Field, Motion Blur) in slot 2; empty marker chunks 0x2682-0x268C on the camera object.

**Targets**: a camera or light node with a target has a "Look At" transform controller (class 0x2006, superclass
0x9008) whose reference slot 0 is the target node (slot 1 position, 2 roll, 3 scale controllers). Verified on the
corpus: all 393 Look At light / camera nodes point at a node whose object is "Target" (0x1020, superclass 0x10) and
whose node flags have bit 14 set; no light or camera node with another controller has a target; Physical cameras
and Arnold lights flag "targeted" exactly on those nodes (48 of 67, 4 of 33). :func:`target_node_of` and
:func:`target_distance_of` work per node; the decoded data gives the first node's target.
"""

__all__ = (
    "CameraData",
    "LightData",
    "LOOK_AT",
    "look_at_position",
    "nodes_of",
    "target_distance_of",
    "target_node_of",
)

import dataclasses
import math
import struct
from typing import Any

from ..classes import ClassID
from ..errors import DecodeError
from ..registry import decoder
from ..transform import IDENTITY

SUPER_CAMERA = 0x20
SUPER_LIGHT = 0x30
SUPER_TRANSFORM = 0x9008
LOOK_AT = ClassID(0x2006)      # "Look At" transform controller (superclass 0x9008).
LOOK_AT_TARGET, LOOK_AT_POSITION = 0, 1

# Free / Target camera markers: empty leaf chunks on the camera object.
CAMERA_TARGETED_MARKER = 0x2682     # Verified: on all 112 Target cameras, on none of the 73 Free cameras.


@dataclasses.dataclass
class LightData:
    """A decoded light. ``params`` uses the importer's names; units are Max's (scene units, degrees, ...)."""
    class_name: str                 # Scripting-style name the importer dispatches on, e.g. "Omnilight".
    params: dict[str, Any]
    source_class: str = ""          # The class name stored in the file, e.g. "Free Rectangle".
    target_node: int | None = None  # Object index of the target node (first node instancing this light).
    nodes: list[int] = dataclasses.field(default_factory=list)   # Nodes instancing this light.
    shadow_generator: str | None = None     # Class of the shadow generator ("Shadow Map", ...), when referenced.
    animated: list[str] = dataclasses.field(default_factory=list)
    """Parameters driven by a controller (their value in ``params`` is the controller's static value; parameters
    whose controller could not be read are left out of ``params``)."""
    raw: dict[str, Any] = dataclasses.field(default_factory=dict, repr=False)
    """Every parameter block value as ``"slot.param_id"`` -> value, named in ``params`` or not."""
    flags: dict[int, int | None] = dataclasses.field(default_factory=dict, repr=False)
    """Switch chunks of the light object: chunk type -> u16 value (None for empty marker chunks)."""


@dataclasses.dataclass
class CameraData:
    """A decoded camera. ``params`` uses the importer's names; units are Max's (scene units, degrees, mm)."""
    class_name: str                 # "Freecamera", "Targetcamera" or "Physical".
    params: dict[str, Any]
    source_class: str = ""
    target_node: int | None = None
    nodes: list[int] = dataclasses.field(default_factory=list)
    effect: str | None = None       # Free / Target cameras: class of the multi-pass effect object (slot 2).
    animated: list[str] = dataclasses.field(default_factory=list)
    raw: dict[str, Any] = dataclasses.field(default_factory=dict, repr=False)
    flags: dict[int, int | None] = dataclasses.field(default_factory=dict, repr=False)


# -----------------------------------------------------------------------------
# Nodes and targets.

def nodes_of(scene, obj_index: int) -> list:
    """The nodes whose object (reference slot 1) is ``obj_index``, cached per scene."""
    table = scene.cache.get("lights.nodes_by_object")
    if table is None:
        table = {}
        for node in scene.nodes:
            if node.object is not None:
                table.setdefault(node.object.index, []).append(node)
        scene.cache["lights.nodes_by_object"] = table
    return table.get(obj_index, [])


def _is_look_at(controller) -> bool:
    return (controller is not None and controller.class_id == LOOK_AT
            and controller.superclass_id == SUPER_TRANSFORM)


def target_node_of(scene, node):
    """The target :class:`~maxfile.scene.Node` of a camera / light ``node`` (Look At slot 0), or None."""
    controller = node.controller
    if not _is_look_at(controller):
        return None
    index = controller.references.get(LOOK_AT_TARGET)
    return scene.node(index) if index is not None else None


def _apply(matrix, p):
    return tuple(matrix[i][0] * p[0] + matrix[i][1] * p[1] + matrix[i][2] * p[2] + matrix[i][3] for i in range(3))


def look_at_position(scene, node):
    """
    World position of ``node``: from its decoded transform, or for a Look At node (whose transform isn't
    decoded) from the Look At's position controller (slot 1). None when unknown.
    """
    parent = node.parent.world_matrix() if node.parent is not None else IDENTITY
    if node.transform is not None and node.transform.position is not None:
        return _apply(parent, node.transform.position)
    controller = node.controller
    if not _is_look_at(controller) or LOOK_AT_POSITION not in controller.references:
        return None
    value = scene.decode(scene.objects[controller.references[LOOK_AT_POSITION]])
    if not (isinstance(value, tuple) and len(value) == 3):
        return None
    return _apply(parent, value)


def target_distance_of(scene, node) -> float | None:
    """
    Distance from a camera / light ``node`` to its target node, in scene units (None without a target).

    Verified: equals the Physical camera's stored target distance on 47 of its 48 targeted cameras (the other
    is animated) and the Arnold light's on 3 of 4.
    """
    target = target_node_of(scene, node)
    if target is None:
        return None
    a, b = look_at_position(scene, node), look_at_position(scene, target)
    if a is None or b is None:
        return None
    return math.dist(a, b)


# -----------------------------------------------------------------------------
# Helpers.

class _Reader:
    """Collects named parameters from the object's parameter blocks."""

    def __init__(self, obj, ctx, result):
        self.obj = obj
        self.ctx = ctx
        self.result = result
        self.blocks = {}
        for slot, index in sorted(obj.references.items()):
            block = ctx.scene.param_block(ctx.scene.objects[index])
            if block is not None:
                self.blocks[slot] = block
                for pid, param in block.params.items():
                    result.raw["{:d}.{:d}".format(slot, pid)] = param.value

    def block(self, slot, required=False):
        block = self.blocks.get(slot)
        if block is None and required:
            raise DecodeError("no parameter block in reference slot {:d}".format(slot))
        return block

    def get(self, slot, pid, name, convert=None):
        """Store parameter ``pid`` of the block in ``slot`` as ``name``; returns the value (None when absent)."""
        block = self.blocks.get(slot)
        param = block.get(pid) if block is not None else None
        if param is None:
            return None
        if param.animated:
            self.result.animated.append(name)
        value = param.value
        if value is None:
            return None
        if convert is not None:
            value = convert(value)
        self.result.params[name] = value
        return value


def _rgb(value):
    return tuple(float(v) for v in value[:3])


def _flags(obj):
    """u16 switch chunks of a light / camera object (empty markers as None)."""
    flags = {}
    for child in obj.chunk.children:
        if child.is_container or child.type in (0x2034, 0x2035, 0x204B):
            continue
        if child.payload_size == 0:
            flags[child.type] = None
        elif child.payload_size == 2:
            flags[child.type] = struct.unpack_from("<H", child.data)[0]
    return flags


def _link_nodes(obj, ctx, result, targeted):
    """Fill ``nodes``, ``target_node`` and (for targeted objects) a geometric ``target_distance``."""
    nodes = nodes_of(ctx.scene, obj.index)
    result.nodes = [node.index for node in nodes]
    targets = [target_node_of(ctx.scene, node) for node in nodes]
    first = next((t for t in targets if t is not None), None)
    if first is not None:
        result.target_node = first.index
        if len({t.index for t in targets if t is not None}) > 1:
            ctx.warn("object {:d} ({:s}): instanced by nodes with different targets; target_node is the first's"
                     .format(obj.index, obj.class_label()))
        node = nodes[targets.index(first)]
        distance = target_distance_of(ctx.scene, node)
        if distance is not None:
            result.params["target_distance"] = distance
    elif targeted and nodes:
        ctx.warn("object {:d} ({:s}): targeted, but no node has a Look At controller with a target".format(
            obj.index, obj.class_label()))


def _ref_class(ctx, obj, slot):
    ref = ctx.ref(obj, slot)
    return ref.class_label() if ref is not None else None


# -----------------------------------------------------------------------------
# Standard lights.

# Class ID -> (importer class name, kind).
STANDARD_LIGHTS = {
    ClassID(0x1011): ("Omnilight", "omni"),
    ClassID(0x1012): ("Targetspot", "spot"),
    ClassID(0x1014): ("Freespot", "spot"),
    ClassID(0x1013): ("Directionallight", "direct"),
    ClassID(0x1015): ("TargetDirectionallight", "direct"),
}

# Old ParamBlock (slot 0) index -> name. Evidence (corpus: 149 Omni, 176 spots, 18 directs):
#   color: point3, white on 53 Omni / 113 Target Spots (the default), animated by a Bezier Color when animated.
#   multiplier: 1.0 on 62 Omni / 82 spots (the default), other values 0.07-38.5.
#   hotspot / falloff: 43 / 45 on 147 / 144 of 172 Target Spots (Max's default cone) and hotspot <= falloff on all
#     180 spots and directs; spots: full cone angles in **degrees** (max 100); directs: beam radii in scene units
#     (values up to 908, so not angles).
#   near / far attenuation start, end: defaults 0 / 40 / 80 / 200, edited on 12 of 13 lights with the "use near"
#     switch and 30 of 30 with the "use far" switch, against 29 of 330 and 22 of 313 without.
#   decay_start: default 40; edited on all 11 lights with a decay type, on 15 of 332 without.
# Guess (names only, from default value and range): contrast (0-100, default 0), soften_diffuse_edge (0-100,
#   50 or 0), aspect (spot, always 1.0), shadow_color (always black but 4), shadow_density (default 1.0, 0.25-2).
# Guess: target_distance of free spots / directs (19th parameter, default 240 like the photometric lights' target
#   distance; 8 lights).
OMNI_PARAMS = {
    0: ("color", _rgb), 1: ("multiplier", None), 2: ("contrast", None), 3: ("soften_diffuse_edge", None),
    4: ("near_atten_start", None), 5: ("near_atten_end", None), 6: ("far_atten_start", None),
    7: ("far_atten_end", None), 8: ("decay_start", None), 9: ("shadow_color", _rgb), 13: ("shadow_density", None),
}
SPOT_PARAMS = {
    0: ("color", _rgb), 1: ("multiplier", None), 2: ("contrast", None), 3: ("soften_diffuse_edge", None),
    4: ("hotspot", None), 5: ("falloff", None), 6: ("aspect", None),
    7: ("near_atten_start", None), 8: ("near_atten_end", None), 9: ("far_atten_start", None),
    10: ("far_atten_end", None), 11: ("decay_start", None), 12: ("shadow_color", _rgb), 16: ("shadow_density", None),
    18: ("target_distance", None),
}

# Switch chunks (u16, 1 = on). Evidence:
#   0x2580 on: set on 145 of 149 Omni and 170 of 172 Target Spots; off on the two Omni of Lighting-Vertex.max
#     (lighting baked into vertex colours) and on a few template lights.
#   0x2570 cast_shadows: set on the "Main Light" of the Cornell box scenes, clear on its fill lights; set on 115 of
#     172 spots, 23 of 149 Omni (Guess: name from that pattern only).
#   0x2561 / 0x2562 use_near_atten / use_far_atten: see the attenuation values above.
#   0x25D0 decay_type: present only on the 11 lights whose decay start was edited; 1 / 2 -> "inverse" /
#     "inverse_square" (Guess: order of Max's list "None, Inverse, Inverse Square"); absent = "none".
#   0x25B0 / 0x25B1 (empty markers): Guess "affect diffuse" / "affect specular" off: 0x25B1 on 20 fill lights
#     ("Omni - Fill01", ...), 0x25B0 on two "luz brillo" ("highlight light") Omni.
FLAG_ON = 0x2580
FLAG_SHADOWS = 0x2570
FLAG_NEAR_ATTEN = 0x2561
FLAG_FAR_ATTEN = 0x2562
FLAG_DECAY = 0x25D0
FLAG_NO_DIFFUSE = 0x25B0
FLAG_NO_SPECULAR = 0x25B1
STANDARD_FLAGS = {FLAG_ON: "on", FLAG_SHADOWS: "cast_shadows", FLAG_NEAR_ATTEN: "use_near_atten",
                  FLAG_FAR_ATTEN: "use_far_atten"}
DECAY_TYPES = {0: "none", 1: "inverse", 2: "inverse_square"}


@decoder(*STANDARD_LIGHTS, kind="light", name="Standard lights", superclass_id=SUPER_LIGHT, verified=True)
def standard_light(obj, ctx):
    """Omni, spot and directional lights: colour, multiplier, cone, attenuation, switches, target."""
    class_name, kind = STANDARD_LIGHTS[obj.class_id]
    result = LightData(class_name, {}, source_class=obj.class_label())
    reader = _Reader(obj, ctx, result)
    reader.block(0, required=True)
    table = OMNI_PARAMS if kind == "omni" else SPOT_PARAMS
    for pid, (name, convert) in table.items():
        reader.get(0, pid, name, convert)
    result.flags = _flags(obj)
    for chunk_type, name in STANDARD_FLAGS.items():
        value = result.flags.get(chunk_type)
        if value is not None:
            result.params[name] = bool(value & 1)
    decay = result.flags.get(FLAG_DECAY, 0) or 0
    result.params["decay_type"] = DECAY_TYPES.get(decay, "none")
    if decay not in DECAY_TYPES:
        ctx.warn("object {:d} ({:s}): unknown decay type {:d}".format(obj.index, obj.class_label(), decay))
    result.params["affect_diffuse"] = FLAG_NO_DIFFUSE not in result.flags       # Guess, see above.
    result.params["affect_specular"] = FLAG_NO_SPECULAR not in result.flags     # Guess, see above.
    result.shadow_generator = _ref_class(ctx, obj, 3)
    targeted = class_name.startswith("Target")
    if targeted:
        result.params.pop("target_distance", None)
    _link_nodes(obj, ctx, result, targeted)
    return result


# -----------------------------------------------------------------------------
# Photometric lights.

# Class ID -> (importer class name, shape). The shape follows from the class: verified by the emitter outline
# (chunk 0x0858): a single point at the origin for all 63 Free / Target Light, the rectangle's four corners for all
# 20 rectangles. Target Sphere / Cylinder and the line lights don't occur in the corpus (class IDs unknown).
PHOTOMETRIC_LIGHTS = {
    ClassID.from_u64(0x0B025CF032375FCC): ("Free_Light", "point"),
    ClassID.from_u64(0x72CD4259658D4F97): ("Target_Light", "point"),
    ClassID.from_u64(0x105A1A4736507D92): ("Free_Light", "rectangle"),
    ClassID.from_u64(0x70AE52F271794F9D): ("Target_Light", "rectangle"),
    ClassID.from_u64(0x0C4F430E5BCC6D42): ("Free_Light", "disc"),
    ClassID.from_u64(0x201758B338732348): ("Target_Light", "disc"),
    ClassID.from_u64(0x1ABB6B327CA93582): ("Free_Light", "sphere"),
    ClassID.from_u64(0x0A327AAF46F634E3): ("Free_Light", "cylinder"),
}

# Main block (slot 0) parameter ID -> name. Evidence (95 photometric lights):
#   distribution (int): 0 on 54 of 60 Free Light and all spheres / cylinders, 2 on 15 of 20 rectangles and lights
#     named "*Area*", 1 on the two lights whose cone (slot 2) was edited (75 / 178), 3 on the lights named
#     "...-ies-..." / "wallwash" of IES lights_ART.max, which reference a web file.
#   rgb: filter colour (white on 92). intensity: 1500 on 69 (Max's default 1500 cd). kelvin: 3600 default, 6500 /
#     2800 / 5000 exactly where use_kelvin (bool) is set.
#   intensity_type (int): 1 on 84 (candelas, the default unit); 2 on the 11 lights whose "at distance" value was
#     edited (lux at that distance); 0 = lumens (Guess: the remaining unit).
#   lux_at_distance: 1 m in scene units by default (39.37008, 100, 3.28084, 1000 in inch / cm / foot / mm scenes);
#     in **scene units**, not metres.
# Guess: on (always true), cast_shadows (false on one light), use_dimmer / dimmer (percent, default 100).
PHOTOMETRIC_MAIN = {
    2: ("on", None), 3: ("cast_shadows", None), 5: ("rgb", _rgb), 6: ("intensity", None), 8: ("kelvin", None),
    10: ("use_kelvin", None), 13: ("lux_at_distance", None), 18: ("use_dimmer", None), 19: ("dimmer", None),
}
DISTRIBUTIONS = {0: "uniform_spherical", 1: "spotlight", 2: "uniform_diffuse", 3: "web"}
INTENSITY_TYPES = {0: "lumens", 1: "candelas", 2: "lux"}
PHOTOMETRIC_SPOT_SLOT, PHOTOMETRIC_WEB_SLOT, PHOTOMETRIC_SHAPE_SLOT = 2, 3, 5
# Shape block (slot 5): 7 target distance of free lights (default 240), 11 / 12 / 13 sizes. Verified on the 20
# rectangles: parameter 12 is the outline's extent along local X, 11 along local Y (e.g. 66.33 x 5.906 against
# corners at x = +-33.165, y = +-2.953), so ``length`` (the importer's Blender X size) is parameter 12. Disc and
# sphere radius: parameter 13 (default 5.5 / 2, the only one edited on discs and spheres). Guess: cylinder length
# = parameter 11 (one cylinder, default values).
PHOTOMETRIC_SHAPE_PARAMS = {
    "rectangle": {12: "length", 11: "width"},
    "disc": {13: "radius"},
    "sphere": {13: "radius"},
    "cylinder": {11: "length", 13: "radius"},
    "point": {},
}
CHUNK_PB2_RECORDS = (0x100E, 0x000E)
CHUNK_ASSET_REF = 0x000F        # Container after a file-name record whose value is 0xFFFFFFFE: 0x0002 = asset GUID.


def _asset_guid(block_obj, param_id):
    """The asset GUID (32 hex digits, as stored) of file-name parameter ``param_id`` stored by asset reference."""
    children = block_obj.chunk.children
    for i, child in enumerate(children):
        if child.type not in CHUNK_PB2_RECORDS or child.is_container or child.payload_size < 19:
            continue
        pid, code = struct.unpack_from("<HI", child.data)
        value = struct.unpack_from("<I", child.data, 15)[0]
        if pid != param_id or code != 9 or value != 0xFFFFFFFE:
            continue
        holder = children[i + 1] if i + 1 < len(children) else None
        if holder is not None and holder.type == CHUNK_ASSET_REF and holder.is_container:
            guid = holder.find(0x0002)
            if guid is not None and guid.payload_size == 16:
                return bytes(guid.data).hex()
    return None


@decoder(*PHOTOMETRIC_LIGHTS, kind="light", name="Photometric lights", superclass_id=SUPER_LIGHT, verified=True)
def photometric_light(obj, ctx):
    """Free / Target Light and its shape variants: intensity and units, distribution, colour, shape, target."""
    class_name, shape = PHOTOMETRIC_LIGHTS[obj.class_id]
    result = LightData(class_name, {"shape": shape}, source_class=obj.class_label())
    reader = _Reader(obj, ctx, result)
    reader.block(0, required=True)
    for pid, (name, convert) in PHOTOMETRIC_MAIN.items():
        reader.get(0, pid, name, convert)
    distribution = reader.block(0).value(1)
    if distribution is not None:
        result.params["distribution"] = DISTRIBUTIONS.get(distribution, "unknown:{:d}".format(distribution))
    units = reader.block(0).value(14)
    if units is not None:
        result.params["intensity_type"] = INTENSITY_TYPES.get(units, "unknown:{:d}".format(units))
    # Spotlight cone, full angles in degrees (stored as plain floats; defaults 30 / 60).
    reader.get(PHOTOMETRIC_SPOT_SLOT, 0, "hotspot")
    reader.get(PHOTOMETRIC_SPOT_SLOT, 1, "falloff")
    # Photometric web: the file is stored as an asset reference (a GUID into the file's asset metadata).
    web = ctx.ref(obj, PHOTOMETRIC_WEB_SLOT)
    if web is not None and result.params.get("distribution") == "web":
        reader.get(PHOTOMETRIC_WEB_SLOT, 0, "web_file")
        guid = _asset_guid(web, 0)
        if guid is not None:
            result.params["web_file_asset"] = guid
        # Guess: rotation of the web distribution about X / Y / Z, degrees (0 but one 90).
        for pid, name in ((1, "web_rotate_x"), (2, "web_rotate_y"), (3, "web_rotate_z")):
            reader.get(PHOTOMETRIC_WEB_SLOT, pid, name)
    for pid, name in PHOTOMETRIC_SHAPE_PARAMS[shape].items():
        reader.get(PHOTOMETRIC_SHAPE_SLOT, pid, name)
    if class_name == "Free_Light":
        reader.get(PHOTOMETRIC_SHAPE_SLOT, 7, "target_distance")
    result.flags = _flags(obj)
    result.shadow_generator = _ref_class(ctx, obj, 4)
    _link_nodes(obj, ctx, result, class_name == "Target_Light")
    return result


# -----------------------------------------------------------------------------
# Arnold, sky and sun.

# Arnold light type (parameter 18). Evidence: 6 on the two "*Skydome" lights, 2 on the three targeted lights with
# an edited cone angle (parameter 52) and on the light converted from a photometric spotlight, 3 on
# "ArnoldLightQuad-001" and the four "ArnoldPortal*", 8 on the four lights that reference a mesh node (parameter
# 48), 5 on the light converted from a photometric cylinder.
# Guess: 0 point, 1 distant, 4 disk (one light), 7 photometric (the remaining positions of Arnold's usual order).
ARNOLD_TYPES = {0: "point", 1: "distant", 2: "spot", 3: "quad", 4: "disk", 5: "cylinder", 6: "skydome",
                7: "photometric", 8: "mesh"}
# Evidence: targeted (bool) exactly on the 4 Look At nodes; target_distance matches the node distance on 3 of 4;
# quad_x / quad_y equal the photometric rectangles' X / Y extents in the converted Studio scene; kelvin 6500 /
# 3600 / 4200 with use_kelvin set on the edited ones; spot_cone_angle default 60, edited on spots only.
# Guess: on (false on one skydome), color, intensity (default 1), exposure (default 8 on quads), cast_shadows.
ARNOLD_PARAMS = {
    0: ("on", None), 1: ("targeted", None), 2: ("target_distance", None), 4: ("color", _rgb),
    7: ("use_kelvin", None), 8: ("kelvin", None), 10: ("intensity", None), 11: ("exposure", None),
    12: ("cast_shadows", None), 33: ("quad_x", None), 34: ("quad_y", None), 48: ("mesh_node", None),
    52: ("spot_cone_angle", None),
}


@decoder(0xCA131D056705F00D, kind="light", name="Arnold Light", superclass_id=SUPER_LIGHT, verified=True)
def arnold_light(obj, ctx):
    """Arnold Light: type, colour, intensity / exposure, quad size, cone, target (class name ``Arnold_Light``)."""
    result = LightData("Arnold_Light", {}, source_class=obj.class_label())
    reader = _Reader(obj, ctx, result)
    reader.block(0, required=True)
    for pid, (name, convert) in ARNOLD_PARAMS.items():
        reader.get(0, pid, name, convert)
    light_type = reader.block(0).value(18)
    if light_type is not None:
        result.params["type"] = ARNOLD_TYPES.get(light_type, "unknown:{:d}".format(light_type))
    result.flags = _flags(obj)
    _link_nodes(obj, ctx, result, bool(result.params.get("targeted")))
    return result


# Skylight (0x522E47057BF61478; 6 in the corpus). Guess names from defaults: color (0.95, 0.95, 1), multiplier
# (1.0 or 1.5), sky_map (texmap reference), rays_per_sample (20), on (always true).
SKYLIGHT_PARAMS = {0: ("color", _rgb), 2: ("sky_map", None), 3: ("on", None), 4: ("rays_per_sample", None),
                   10: ("multiplier", None)}


@decoder(0x522E47057BF61478, kind="light", name="Skylight", superclass_id=SUPER_LIGHT)
def skylight(obj, ctx):
    """Skylight (world lighting; the importer has no conversion for it yet)."""
    result = LightData("Skylight", {}, source_class=obj.class_label())
    reader = _Reader(obj, ctx, result)
    reader.block(0, required=True)
    for pid, (name, convert) in SKYLIGHT_PARAMS.items():
        reader.get(0, pid, name, convert)
    result.flags = _flags(obj)
    _link_nodes(obj, ctx, result, False)
    return result


# Sun Positioner (0x716F5B2527FE329C; 21). Verified: parameters 16 / 17 are the Julian day and the second of the day
# (2457925 / 43200 = 21 June 2017, 12:00) and agree with year / month / day / hour / minute (8 / 7 / 6 / 4 / 5);
# latitude / longitude 37.795 / -122.394 (San Francisco, Max's default location) with time zone -8; azimuth /
# altitude 128.71 / 69.17 degrees, the sun's position for that place and time with daylight saving (10).
# Guess: north_direction (degrees, 14), compass_radius / sun_distance (world, 1 / 2), and the sense of the north
# rotation in sun_direction.
SUN_PARAMS = {
    1: ("compass_radius", None), 2: ("sun_distance", None), 4: ("hour", None), 5: ("minute", None),
    6: ("day", None), 7: ("month", None), 8: ("year", None), 9: ("time_zone", None), 10: ("daylight_saving", None),
    12: ("latitude", None), 13: ("longitude", None), 14: ("north_direction", None), 18: ("azimuth", None),
    19: ("altitude", None),
}


@decoder(0x716F5B2527FE329C, kind="light", name="Sun Positioner", superclass_id=SUPER_LIGHT, verified=True)
def sun_positioner(obj, ctx):
    """Sun Positioner: place, date and time, sun azimuth / altitude and direction (class ``Sun_Positioner``)."""
    result = LightData("Sun_Positioner", {}, source_class=obj.class_label())
    reader = _Reader(obj, ctx, result)
    reader.block(0, required=True)
    for pid, (name, convert) in SUN_PARAMS.items():
        reader.get(0, pid, name, convert)
    azimuth, altitude = result.params.get("azimuth"), result.params.get("altitude")
    if azimuth is not None and altitude is not None:
        # Unit vector towards the sun: azimuth clockwise from north, north = +Y turned by north_direction
        # (Guess: counter-clockwise seen from above).
        heading = math.radians(90.0 + result.params.get("north_direction", 0.0) - azimuth)
        alt = math.radians(altitude)
        result.params["sun_direction"] = (math.cos(heading) * math.cos(alt), math.sin(heading) * math.cos(alt),
                                          math.sin(alt))
    result.flags = _flags(obj)
    _link_nodes(obj, ctx, result, False)
    return result


@decoder(0x25E2112471503BBB, 0x799B5B5626EE3350, kind="light", name="mr Sun / mr Sky", superclass_id=SUPER_LIGHT)
def mental_ray_sun_sky(obj, ctx):
    """mental ray sun and sky (6 each, in 2 files): parameters kept in ``raw`` only, no names established."""
    name = "mr_Sun" if obj.class_id == ClassID.from_u64(0x25E2112471503BBB) else "mr_Sky"
    result = LightData(name, {}, source_class=obj.class_label())
    _Reader(obj, ctx, result).block(0, required=True)
    result.flags = _flags(obj)
    _link_nodes(obj, ctx, result, False)
    return result


# -----------------------------------------------------------------------------
# Cameras.

# Free / Target camera, old ParamBlock in slot 0. Evidence (185 cameras):
#   fov: radians; 0.7854 (45 degrees, Max's default) on 93 of 112 Target and 45 of 73 Free cameras. Given in
#     degrees, as the importer expects.
#   target_distance (Free): default 160 (18 of 73). Target cameras don't keep it up to date (0 on 77 of 112, the
#     stored value matches the node distance on 6): their target_distance is computed from the target node.
#   near_clip / far_clip and near_env_range / far_env_range: defaults 1 / 1000 and 0 / 1000, scaled by unit
#     rescaling (0.3937 / 393.7, 0.0394 / 39.37 in rescaled scenes).
# Guess: multipass_effect (int 1 on 10 of the 14 cameras whose effect is Motion Blur, 0 on all 171 Depth of Field
#   ones), fov_type (always 0, taken as horizontal). The markers 0x2684-0x268C (orthographic, clip manually, show
#   cone / horizon / ranges?) are not interpreted: they are in ``flags``.
CAMERA_PARAMS = {
    1: ("target_distance", None), 2: ("near_clip", None), 3: ("far_clip", None), 4: ("near_env_range", None),
    5: ("far_env_range", None), 6: ("multipass_effect", bool),
}
FOV_TYPES = {0: "horizontal"}
STANDARD_CAMERAS = {ClassID(0x1001): "Freecamera", ClassID(0x1002): "Targetcamera"}


@decoder(*STANDARD_CAMERAS, kind="camera", name="Free / Target camera", superclass_id=SUPER_CAMERA, verified=True)
def standard_camera(obj, ctx):
    """Free and Target cameras: field of view, clipping, target."""
    class_name = STANDARD_CAMERAS[obj.class_id]
    result = CameraData(class_name, {}, source_class=obj.class_label())
    reader = _Reader(obj, ctx, result)
    reader.block(0, required=True)
    reader.get(0, 0, "fov", math.degrees)
    for pid, (name, convert) in CAMERA_PARAMS.items():
        reader.get(0, pid, name, convert)
    fov_type = reader.block(0).value(8)
    if fov_type is not None:
        result.params["fov_type"] = FOV_TYPES.get(fov_type, "unknown:{:d}".format(fov_type))  # Guess.
    result.flags = _flags(obj)
    result.effect = _ref_class(ctx, obj, 2)
    targeted = class_name == "Targetcamera"
    if targeted:
        result.params.pop("target_distance", None)
    _link_nodes(obj, ctx, result, targeted)
    return result


# Physical camera (0x28E8008D46697218), ParamBlock2 in slot 0. Evidence (67 cameras):
#   targeted: true exactly on the 48 Look At nodes. target_distance: equals the distance to the target node on 47
#     of those 48. film_width_mm 36 (66 of 67), focal_length_mm 40 default (and consistent with the stored FOV when
#     both are default), f_number 8 default (1.0 on the two DOF_* sample cameras).
#   clip_on: set on exactly the 5 cameras whose near_clip / far_clip differ from the defaults (1 / 1000 or 0 / 1000
#     m in scene units).
# Guess: zoom_factor (always 1), focus_distance (custom focus, 5 m by default, used when parameter 10 is 1, else
#   the target distance), use_dof (the two DOF_* cameras and one other), specify_fov / fov (degrees; specify_fov
#   set only on cameras imported from other applications), motion_blur (DragonFlying motion-blur scene),
#   exposure_value (EV, default 6), white_balance_kelvin (default 6500), shutter_duration (frames, 0.5).
PHYSICAL_PARAMS = {
    0: ("targeted", None), 1: ("specify_fov", None), 4: ("film_width_mm", None), 5: ("focal_length_mm", None),
    6: ("f_number", None), 7: ("zoom_factor", None), 11: ("use_dof", None), 15: ("shutter_duration", None),
    18: ("motion_blur", None), 20: ("fov", None), 24: ("exposure_value", None), 27: ("white_balance_kelvin", None),
    47: ("clip_on", None), 48: ("near_clip", None), 49: ("far_clip", None), 50: ("near_env_range", None),
    51: ("far_env_range", None),
}


@decoder(0x28E8008D46697218, kind="camera", name="Physical camera", superclass_id=SUPER_CAMERA, verified=True)
def physical_camera(obj, ctx):
    """Physical camera: film, lens, aperture, focus, clipping, target."""
    result = CameraData("Physical", {}, source_class=obj.class_label())
    reader = _Reader(obj, ctx, result)
    block = reader.block(0, required=True)
    for pid, (name, convert) in PHYSICAL_PARAMS.items():
        reader.get(0, pid, name, convert)
    stored_distance = reader.get(0, 8, "target_distance")
    custom_focus = block.value(10) == 1
    result.flags = _flags(obj)
    _link_nodes(obj, ctx, result, bool(result.params.get("targeted")))
    if custom_focus:
        reader.get(0, 9, "focus_distance")
    else:
        distance = result.params.get("target_distance", stored_distance)
        if distance is not None:
            result.params["focus_distance"] = distance
    return result
