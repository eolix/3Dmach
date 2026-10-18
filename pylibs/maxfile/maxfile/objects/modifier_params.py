# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Object-space modifiers (superclass 0x810): their parameters, display name and state markers.

**Layout of a modifier object** (verified on the 6,500-odd modifier objects of the corpus):

- one parameter block (ParamBlock2 or old ParamBlock) in a fixed reference slot per class: slot 0 for most;
  slot 1 for UVW Map and Mirror (slot 0 is the gizmo's Position/Rotation/Scale controller); slot 2 for Bend,
  Taper, Twist and Noise (slot 0 gizmo transform, slot 1 gizmo centre position); slot 95 for Unwrap UVW.
  :func:`find_param_block` takes the block from the class's slot, or else the first reference that is one.
- ``0x39BF`` container: child ``0x0100`` = the name shown in the modifier stack, UTF-16 (empty when the user kept
  the class name: 1,900-odd of the objects; otherwise e.g. "UVW Mapping", "MSmth-RFore..."). Edit Poly nests it
  in ``0x0080``. Sometimes also empty marker leaves ``0x0110`` (about 110 objects), ``0x0120`` (about 50) and
  ``0x0130`` (once). These are the best candidates for the modifier's on / off states (Max has three: Off,
  Off in Viewport, Off in Renderer), but which marker is which could not be established from the files:
  :attr:`ModifierData.state_flags` lists them raw and :attr:`ModifierData.enabled` stays None.
  Evidence so far: they cluster on heavy modifiers (TurboSmooth / MeshSmooth / Flex / Skin, 0x0120 almost only on
  TurboSmooth / MeshSmooth), which suits "off in viewport"; whether a lower modifier passes its input through
  unchanged (compared with the next modifier context's bounding box) does not separate flagged from unflagged
  modifiers, because context boxes are not refreshed after the modifier is added.
- The per-node data of a modifier (its "mod context": gizmo matrix, input bounding box, local data such as Edit
  Poly edits or Unwrap UVW's texture vertices) is stored in the derived object (0x2032 / 0x2033), not here; see
  :mod:`maxfile.objects.modifiers`.

**Parameters** are returned under the names the importer's converters use (``scripts/addons_core/mx_io_max/
modifiers/convert.py``), lower_snake_case after the Max UI, in the units those converters expect: Bend / Twist
angles and Chamfer's minimum angle in degrees (Bend, Twist and Chamfer store degrees as plain floats: 90.0,
101.5, 30.0), distances in scene units, axes as 0 = X, 1 = Y, 2 = Z. ParamBlock2 "angle" parameters (radians) are
converted to degrees only where noted. Names whose meaning is a guess are listed in :attr:`ModifierData.guessed`.
"""

__all__ = (
    "ModifierData",
    "MODIFIER_PARAMS",
    "find_param_block",
    "read_state",
)

import dataclasses
import math
from typing import Any

from ..classes import ClassID
from ..registry import decoder

CHUNK_MOD_STATE = 0x39BF        # Container: 0x0100 name, optional 0x0110 / 0x0120 / 0x0130 markers.
CHUNK_MOD_NAME = 0x0100
CHUNK_EDIT_POLY_WRAPPER = 0x0080    # Edit Poly keeps 0x39BF inside this container.
CHUNK_UNWRAP_CHANNEL = 0x0190   # Unwrap UVW: u32. Guess: the map channel (1 on 111 of 112 objects, 0 once).


@dataclasses.dataclass
class ModifierData:
    """A modifier's parameters."""
    class_name: str                 # The class name as stored in the file ("TurboSmooth", "UVW Map", ...).
    params: dict[str, Any]
    enabled: bool | None = None     # Not established from the files yet (see the module docstring).
    name: str | None = None         # Name shown in the stack when the user renamed the modifier.
    state_flags: tuple[int, ...] = ()   # Marker chunk types found in 0x39BF besides the name (0x0110, ...).
    param_block: int | None = None  # Object index of the parameter block read.
    gizmo: int | None = None        # Object index of the gizmo's transform controller, when the class has one.
    guessed: list[str] = dataclasses.field(default_factory=list)  # Parameter names whose meaning is a guess.
    unknown_params: dict[int, Any] = dataclasses.field(default_factory=dict)  # Unnamed parameter ID -> value.
    unresolved: list[str] = dataclasses.field(default_factory=list)  # Animated, controller value not readable.
    notes: list[str] = dataclasses.field(default_factory=list)


F, I, B = "float", "int", "bool"
DEG = "deg"                 # ParamBlock2 angle (radians) returned in degrees.
V, G = True, False          # Verified / guess.

# Per class: (param block slot, gizmo slot or None, entries). Entry: (param_id, name, conversion, verified).
MODIFIER_PARAMS = {
    "TurboSmooth": (0, None, [
        (0, "iterations", I, V),                # 1 on 90 of 98 (default 1).
        (1, "use_render_iterations", B, V),     # True <=> render iterations set (55 of 56 have id 2 > 0).
        (2, "render_iterations", I, V),
        (3, "isoline_display", B, G),
        (4, "smooth_result", B, G),             # True on all 98 (Max default on).
        (5, "separate_by_materials", B, G),
        (6, "separate_by_smoothing_groups", B, G),
        (7, "update_mode", I, G),               # Index; 0 (Always) on all 98.
        (8, "explicit_normals", B, G),
    ]),
    "OpenSubdiv": (0, None, [
        (0, "iterations", I, V),                # Same pattern as TurboSmooth: (0, True, 2) on GlassGoblet.
        (1, "use_render_iterations", B, G),
        (2, "render_iterations", I, G),
    ]),
    "MeshSmooth": (0, None, [
        (0, "strength", F, G),                  # 0.5 on all 144 (classic / quad output strength default).
        (1, "relax", F, G),                     # 0.0 on all.
        (2, "smoothness", F, G),                # 1.0 on all.
        (4, "iterations", I, V),                # FishAnim: 46-vertex mesh (44 quads) -> 706 vertices = 2 iterations.
        (9, "subdivision_method", I, G),        # 2 on 126 (NURMS, the default), 1 on 18.
        (12, "use_render_smoothness", B, G),    # True exactly where id 16 is 0.0.
        (13, "use_render_iterations", B, V),    # True <=> id 14 > 0 (one exception, unchecked with a value).
        (14, "render_iterations", I, V),
        (16, "render_smoothness", F, G),
    ]),
    "Shell": (0, None, [
        (0, "inner_amount", F, G),              # Partly verified: outward growth of Maxine's shells ~ id 1.
        (1, "outer_amount", F, G),
        (12, "segments", I, G),                 # The only count that varies (1 / 2).
        (14, "auto_smooth_edge", B, G),
        (15, "auto_smooth_angle", F, G),        # 45.0 on all 15 (degrees, default 45).
    ]),
    "Symmetry": (0, 1, [
        (0, "axis", I, V),                      # 0 = X: the kept side changes only the X extent (TigerTank).
        (1, "slice_along_mirror", B, G),
        (2, "weld_seam", B, G),
        (3, "threshold", F, V),                 # 0.1 on 15 of 20 (Max default 0.1).
        (4, "flip", B, V),                      # True: the -axis side is kept (4 stacks); False: +axis (1).
    ]),
    "Mirror": (1, 0, [
        (0, "mirror_axis", I, G),               # 0 / 2 in the corpus; guess 0-2 X / Y / Z, 3-5 XY / YZ / ZX.
        (1, "copy", B, G),
        (2, "offset", F, G),
    ]),
    "Chamfer": (0, None, [
        (0, "amount", F, G),                    # World distance 0.2-0.5.
        (1, "segments", I, G),                  # 1 or 3.
        (2, "tension", F, G),                   # 1.0 on all 12.
        (12, "min_angle", F, G),                # 30.0 on all 12, degrees.
    ]),
    "Bend": (2, 0, [
        (0, "bend_angle", F, V),                # Degrees (90.0, 101.5, -144.0, ...).
        (1, "bend_direction", F, G),            # Degrees (0 / 90 / -107 / 84).
        (2, "bend_axis", I, V),                 # 2 = Z on tall Cylinders / Cones; 0 = X on X-long Boxes / Planes.
        (3, "limit_effect", B, G),
        (4, "lower_limit", F, V),               # Always <= 0 (e.g. -6.553, -13.8): the lower limit.
        (5, "upper_limit", F, V),               # Always >= 0 (6.553, 117.13).
    ]),
    "Twist": (2, 0, [
        (0, "angle", F, V),                     # Degrees (180.0, 300.0).
        (1, "bias", F, G),
        (2, "axis", I, G),                      # Guess: same coding as Bend (2 on the twisted extrusions).
        (3, "limit_effect", B, G),
        (4, "lower_limit", F, G),               # Guess: same order as Bend.
        (5, "upper_limit", F, G),
    ]),
    "Taper": (2, 0, [
        (0, "amount", F, G),                    # -0.65, 1.74, ... (Max range -10..10).
        (1, "curve", F, G),
        (2, "primary_axis", I, V),              # 2 = Z on the tall tapered Cylinders (Torch, wall).
        (3, "effect_axis", I, G),               # 2 on 45 of 56 (Max default XY for primary Z).
        (4, "symmetry", B, G),
        (5, "limit_effect", B, G),
        (6, "lower_limit", F, G),               # Guess: same order as Bend (1.7 and 3.84 on the only set pair).
        (7, "upper_limit", F, G),
    ]),
    "Noise": (2, 0, [
        (0, "seed", I, G),
        (1, "scale", F, V),                     # 100.0 = Max default, the most common value.
        (2, "fractal", B, G),
        (3, "roughness", F, G),                 # 0.0 unless fractal is on (all non-zero ones have id 2 = 1).
        (4, "iterations", F, V),                # 6.0 on 95 of 102 (default 6.0).
        (5, "animate_noise", B, G),
        (6, "frequency", F, V),                 # 0.25 on 91 of 102 (default 0.25).
        (7, "phase", I, G),                     # Always animated.
        (8, "strength", "vec", V),              # The only 3-component value: X, Y, Z strength.
    ]),
    "Push": (0, None, [
        (0, "push_value", F, V),                # The block's only parameter.
    ]),
    "Relax": (0, None, [
        (0, "relax_value", F, V),               # 0.5 on 5 of 6 (default 0.5).
        (1, "iterations", I, V),                # 1 / 2 / 21 (default 1).
        (2, "keep_boundary_points_fixed", B, G),
        (3, "save_outer_corners", B, G),
    ]),
    "Optimize": (0, None, [
        # ParamBlock (old): two levels of detail; thresholds are angles in radians.
        (2, "face_threshold", F, G),            # 0.1745 / 0.0698 (10 / 4 degrees).
        (3, "edge_threshold", F, G),            # 0.0175 (1 degree, the default).
        (4, "bias", F, G),                      # 0.1 (default).
    ]),
    "Lattice": (0, None, [
        (0, "geometry_type", I, G),             # 0 or 2; guess 2 = both (Max default).
        (1, "strut_radius", F, G),
        (2, "strut_segments", I, G),
        (3, "strut_sides", I, G),               # 3 / 4 (default 4).
        (7, "joint_radius", F, G),              # 5.0 = default joint radius.
    ]),
    "Normal": (0, None, [
        (0, "unify", B, G),
        (1, "flip", B, G),                      # 1 on all 13 (the modifier exists to flip normals).
    ]),
    "UVW Map": (1, 0, [
        (0, "map_type", I, G),                  # Guess: 0 planar, 1 cylindrical, 2 spherical, 3 shrink wrap, 4 box,
                                                # 5 face, 6 XYZ to UVW (4 on 535, 0 on 342).
        (1, "u_tile", F, G),
        (2, "v_tile", F, G),
        (3, "w_tile", F, G),
        (4, "u_flip", B, G),
        (5, "v_flip", B, G),
        (6, "w_flip", B, G),
        (7, "cap", B, G),                       # Set only on cylindrical maps.
        (9, "length", F, G),
        (10, "width", F, G),
        (11, "height", F, V),                   # Equals the input's Z extent on 430+ Z-aligned maps.
        (12, "axis", I, G),                     # 2 on 858 of 913 (default Z).
        (13, "channel", I, V),                  # 1 on 892 (default map channel 1), 2 / 3 otherwise.
    ]),
    "Unwrap UVW": (95, 0, []),
    "Edit Poly": (0, 1, []),
    "Turn to Mesh": (0, None, []),
    "Turn to Poly": (0, None, []),
}

# Class IDs (superclass 0x810) of the classes above. Verified: class directories of the corpus.
CLASS_IDS = {
    "TurboSmooth": 0x491D29A70D727B3E,
    "OpenSubdiv": 0x9ABC45FC73CCF34A,
    "MeshSmooth": 0x00007F9E00000032,
    "Shell": 0x6D84E8D03B9B1A16,
    "Symmetry": 0x0BE41A6E2D7E702B,
    "Mirror": 0x511BBE75EF92AA7C,
    "Chamfer": 0x38BB548C332C9510,
    "Bend": 0x10,
    "Twist": 0x90,
    "Taper": 0x20,
    "Noise": 0xF997B124,
    "Push": 0x67AD0ADF0618372D,
    "Relax": 0x00007F9E00000064,
    "Optimize": 0xC4D31,
    "Lattice": 0x2ED9401C148132A1,
    "Normal": 0xF8614,
    "UVW Map": 0xF72B1,
    "Unwrap UVW": 0x72BA4E1F02DF2E3A,
    "Edit Poly": 0x71A075B779AA6E1D,
    "Turn to Mesh": 0x60397CA15C5B50F7,
    # Turn to Poly: no instance in the corpus, so its class ID is unknown; it can't be registered.
}
_BY_CLASS = {ClassID.from_u64(cid): name for name, cid in CLASS_IDS.items()}


def read_state(obj) -> tuple[str | None, tuple[int, ...]]:
    """``(display name or None, marker chunk types)`` from the modifier's 0x39BF container."""
    state = obj.chunk.find(CHUNK_MOD_STATE)
    if state is None:
        wrapper = obj.chunk.find(CHUNK_EDIT_POLY_WRAPPER)
        state = wrapper.find(CHUNK_MOD_STATE) if wrapper is not None and wrapper.is_container else None
    if state is None or not state.is_container:
        return None, ()
    name = None
    flags = []
    for child in state.children:
        if child.type == CHUNK_MOD_NAME and not child.is_container:
            name = child.string() or None
        else:
            flags.append(child.type)
    return name, tuple(flags)


def find_param_block(obj, ctx, slot):
    """``(object, ParamBlockData)`` of the modifier's parameter block: the one in ``slot``, else the first
    reference that is a parameter block; ``(None, None)`` when there is none."""
    candidates = []
    if slot is not None:
        candidates.append(ctx.ref(obj, slot))
    candidates.extend(other for _slot, other in ctx.refs(obj))
    for other in candidates:
        if other is None:
            continue
        block = ctx.scene.param_block(other)
        if block is not None:
            return other, block
    return None, None


def _convert(conversion, value):
    if conversion == F:
        return float(value)
    if conversion == I:
        return int(value)
    if conversion == B:
        return bool(value)
    if conversion == DEG:
        return math.degrees(value)
    if conversion == "vec":
        return tuple(float(v) for v in value)
    raise ValueError(conversion)


def read_modifier(obj, ctx, class_name):
    """Decode ``obj`` with the table entry for ``class_name``."""
    slot, gizmo_slot, table = MODIFIER_PARAMS[class_name]
    stored_name = obj.cls.label() if obj.cls is not None else class_name
    data = ModifierData(stored_name, {})
    data.name, data.state_flags = read_state(obj)

    def warn(message):
        ctx.warn("object {:d} ({:s}): {:s}".format(obj.index, obj.class_label(), message))

    if gizmo_slot is not None:
        gizmo = ctx.ref(obj, gizmo_slot)
        data.gizmo = gizmo.index if gizmo is not None and gizmo.superclass_id in (0x9008, 0x900B) else None
    block_obj, block = find_param_block(obj, ctx, slot)
    if block is None:
        if table:
            warn("no parameter block")
        return data
    data.param_block = block_obj.index
    for problem in block.problems:
        warn("parameter block: " + problem)
    known = set()
    for param_id, name, conversion, verified in table:
        known.add(param_id)
        param = block.get(param_id)
        if param is None:
            continue
        if param.value is None or isinstance(param.value, list):
            data.unresolved.append(name)
            continue
        try:
            data.params[name] = _convert(conversion, param.value)
        except (TypeError, ValueError):
            warn("parameter {:d} ({:s}): unexpected value {!r}".format(param_id, name, param.value))
            continue
        if not verified:
            data.guessed.append(name)
    data.unknown_params = {p.param_id: p.value for p in block.entries if p.param_id not in known}
    return data


@decoder(*_BY_CLASS, kind="modifier", name="Modifier parameters", superclass_id=0x810)
def modifier(obj, ctx):
    """Modifier parameters by name, stack display name and state markers (see maxfile.objects.modifier_params)."""
    class_name = _BY_CLASS[obj.class_id]
    data = read_modifier(obj, ctx, class_name)
    if class_name == "Unwrap UVW":
        chunk = obj.chunk.find(CHUNK_UNWRAP_CHANNEL)
        if chunk is not None and chunk.payload_size >= 4 and not chunk.is_container:
            data.params["channel"] = chunk.u32s()[0]
            data.guessed.append("channel")
        data.notes.append("the UVs are stored per node in the derived object's modifier context (0x2512: 0x0860 "
                          "texture vertices, 0x0870 faces, 0x0330 geometry positions), not in the modifier")
    elif class_name == "Edit Poly":
        data.notes.append("Edit Poly stores its edits, not its result: per-node operation records in the derived "
                          "object's modifier context (0x2512), e.g. vertex offsets for every input vertex")
    return data
