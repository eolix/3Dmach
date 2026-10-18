# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Standard and extended primitives (superclass 0x10): their parameters, and Max's cached mesh when a file has one.

**Where the parameters are.** Every primitive references one parameter block in reference slot 0: a
ParamBlock2 (Max 2009 and later files) or an old ParamBlock (class 0x8, older files and objects created by
older plug-in versions). Both are read by :mod:`maxfile.objects.paramblock`; the old block's parameter *indices*
equal the ParamBlock2 parameter *IDs* (verified on the corpus: both layouts give the same types in the same order
for Box, Sphere, Cylinder, Torus, Cone, Tube, Teapot, ChamferBox and ChamferCyl, and the bounding-box checks below
pass on objects of both layouts).

**Evidence.** No primitive in the corpus caches its mesh (no 0x08FE or other mesh chunk in any of the 1,533
primitive objects: their children are only 0x0100, 0x2034/0x2035, 0x204B, 0x2150 (AppData) and once 0x21B0), so the
parameter IDs were established from:

- *Modifier-context bounding boxes.* A derived object (0x2032) keeps one 0x2500 context per modifier, in the
  modifier reference order; its 0x2511 child is the bounding box (6 floats, min then max) of the modifier's input
  in object space. For the bottom modifier that is the primitive's own box. Box: X extent = id 1, Y extent = id 0,
  Z extent = |id 2| on 100 of 106 objects; Plane 92 of 92 (X = id 1, Y = id 0); Cylinder radius id 0 / height id 1
  with the X/Y extents of an ``id 4``-sided polygon on 46 of 48; Cone ``id 5`` sides (10 and 9 sides give the
  exact polygon extents, ``id 3`` does not); Tube ``id 3`` sides (87, 24 and 18 sides); Torus Z extent = 2 x
  radius2 x sin(polygon) with ``id 5`` sides; Sphere radius id 0 (Z extent 2 r on 34 of 47; the others are
  polygonal or animated) and hemisphere id 3 (0.5 gives Z from 0 to r); ChamferBox 18 of 20; ChamferCyl 9 of 9
  with ``id 5`` sides; Capsule 7 of 7 (height = overall height); GeoSphere, Teapot (box 3.217 r x 2 r x 1.575 r).
- *Bend axis.* Bend modifiers on Boxes and Planes bend along the axis that has the segments: the Box with
  width segments in ``id 3`` and the Planes with them in ``id 2`` are bent along X (Bend axis 0, which is X:
  tall Cylinders and Cones are bent with axis 2). So the first segment count is the one along X (width).
- *Vertex counts* stored by Edit Poly modifiers on top of primitives (Box 3x3x3 = 56, 1x1x1 = 8, 3x3x1 = 32
  vertices; Cylinder with 18 sides and 5 height segments: 108 polygon-mesh vertices).
- *Value ranges and defaults* (segment counts are ints >= 1, sides >= 3, flags 0/1, slices are angles,
  height may be negative, default sides / segments as in the Max UI).

Parameters whose meaning still rests only on the UI order are listed in :attr:`PrimitiveData.guessed` and marked
``# Guess:`` below.

**Names.** ``params`` uses the names of the live-primitive builder (``mx_primitives.geometry.PARAMETERS``:
``length_segments``, ``cap_segments``, ``generate_uvs``, ``hemisphere_mode`` = ``"CHOP"`` / ``"SQUASH"``, ...)
and holds only names that builder accepts for its kinds (BOX, SPHERE, GEOSPHERE, CYLINDER, TUBE, CONE, TORUS,
PLANE), because it rejects unknown names. Everything else goes to :attr:`PrimitiveData.extra_params`. Sizes are
in scene units, angles in radians (both parameter block kinds store radians: Tube slices of +-1.0472 in old blocks).
"""

__all__ = (
    "PrimitiveData",
    "PRIMITIVES",
    "PRIMITIVE_PARAMS",
)

import dataclasses
from typing import Any

from ..classes import ClassID
from ..registry import decoder
from .geometry import CHUNK_MESH, MeshData, read_tri_mesh

# Builder kinds: their names must be accepted by mx_primitives.geometry.normalize_params.
BUILDER_KINDS = {"BOX", "SPHERE", "GEOSPHERE", "CYLINDER", "TUBE", "CONE", "TORUS", "PLANE"}

# Enumerations stored as ints.
# Guess: 0 = Chop (the Max default; 290 of 291 corpus spheres), 1 = Squash.
HEMISPHERE_MODES = {0: "CHOP", 1: "SQUASH"}
# Guess: UI order; 2 = Icosa is the Max default and the value of all 88 corpus GeoSpheres.
GEOSPHERE_BASES = {0: "TETRA", 1: "OCTA", 2: "ICOSA"}
# Guess: 2 is the value of all 18 corpus tori and Max's default is "All"; the other values are unknown.
TORUS_SMOOTH = {2: "ALL"}

# Parameter entry: (param_id, name, conversion, verified, extra). conversion: "float", "int", "bool", or a dict
# mapping stored ints to enumeration names. extra: the name goes to extra_params (not a builder parameter).
F, I, B = "float", "int", "bool"
V, G = True, False          # Verified / guess.


def _slice(first):
    """Slice On, Slice From, Slice To at three consecutive IDs. Guess: UI order (a bool then two angles; the
    angles are 0 on almost every corpus object, pi on one Cylinder and three ChamferCyls)."""
    return [(first, "slice_on", B, G, False), (first + 1, "slice_from", F, G, False),
            (first + 2, "slice_to", F, G, False)]


PRIMITIVE_PARAMS = {
    "BOX": [
        (0, "length", F, V, False),             # Y extent (context bbox, 100 objects).
        (1, "width", F, V, False),              # X extent.
        (2, "height", F, V, False),             # Z extent; negative heights occur (built downwards).
        (3, "width_segments", I, V, False),     # Segments along X (Bend axis evidence, see the module docstring).
        (4, "length_segments", I, V, False),    # Segments along Y (by elimination).
        (5, "height_segments", I, G, False),    # Guess: last of the three counts (UI order).
        (6, "generate_uvs", B, G, False),       # Guess: the only bool; off on 161 of 249 ParamBlock2 boxes.
    ],
    "SPHERE": [
        (0, "radius", F, V, False),
        (1, "segments", I, V, False),           # Int, default 32; 18 segments give the polygonal extents seen.
        (2, "smooth", B, G, False),
        (3, "hemisphere", F, V, False),         # Fraction cut off (0.5: Z from 0 to r on 2 files).
        (4, "hemisphere_mode", HEMISPHERE_MODES, G, False),
        (5, "slice_on", B, G, False),            # Guess: the bool before the two angles' block.
        (6, "generate_uvs", B, G, False),       # Not base-to-pivot: spheres with it set still start at -r.
        (7, "base_to_pivot", B, G, False),      # Guess: never set in the corpus.
        (8, "slice_from", F, G, False),
        (9, "slice_to", F, G, False),
    ],
    "GEOSPHERE": [
        (0, "radius", F, V, False),
        (1, "segments", I, G, False),           # Int 2..6, default 4.
        (2, "base_type", GEOSPHERE_BASES, G, False),
        (3, "hemisphere_on", B, G, False),
        (4, "smooth", B, G, False),             # True on all 88 (Max default on).
        (5, "base_to_pivot", B, G, False),
        (6, "generate_uvs", B, G, False),
    ],
    "CYLINDER": [
        (0, "radius", F, V, False),
        (1, "height", F, V, False),
        (2, "height_segments", I, G, False),    # Default 5; Edit Poly vertex count 108 = 18 sides x (5 + 1).
        (3, "cap_segments", I, G, False),
        (4, "sides", I, V, False),              # Polygon extents on 46 of 48 objects.
        (5, "smooth", B, G, False),
        *_slice(6),
        (9, "generate_uvs", B, G, False),
    ],
    "CONE": [
        (0, "radius1", F, V, False),            # Base radius (X/Y extent = 2 x max(radius1, radius2)).
        (1, "radius2", F, V, False),
        (2, "height", F, V, False),
        (3, "height_segments", I, G, False),
        (4, "cap_segments", I, G, False),
        (5, "sides", I, V, False),              # 10 and 9 sides give the exact polygon extents.
        (6, "smooth", B, G, False),
        *_slice(7),
        (10, "generate_uvs", B, G, False),
    ],
    "TUBE": [
        (0, "radius1", F, V, False),
        (1, "radius2", F, V, False),
        (2, "height", F, V, False),
        (3, "sides", I, V, False),              # 87 / 24 / 18 sides match the extents (the order differs from Cone).
        (4, "cap_segments", I, G, False),
        (5, "height_segments", I, G, False),    # 1 or 5 (default 5).
        (6, "smooth", B, G, False),
        *_slice(7),
        (10, "generate_uvs", B, G, False),
    ],
    "TORUS": [
        (0, "radius1", F, V, False),            # Ring radius: X/Y extent = 2 (radius1 + radius2).
        (1, "radius2", F, V, False),            # Cross-section radius: Z extent.
        (2, "rotation", F, G, False),
        (3, "twist", F, G, False),
        (4, "segments", I, V, False),           # 41 segments / 6 sides give the extents of Vortex-Tornado's torus.
        (5, "sides", I, V, False),
        (6, "smooth_mode", TORUS_SMOOTH, G, False),
        *_slice(7),
        (10, "generate_uvs", B, G, False),
    ],
    "PLANE": [
        (0, "length", F, V, False),             # Y extent (92 objects).
        (1, "width", F, V, False),              # X extent.
        (2, "width_segments", I, V, False),     # Segments along X (Bend axis evidence, 4 planes).
        (3, "length_segments", I, V, False),
        (4, "render_scale", F, G, True),        # Guess: render multipliers (1.0 on 324 of 327).
        (5, "render_density", F, G, True),
        (6, "generate_uvs", B, G, False),
    ],
    "TEAPOT": [
        (0, "radius", F, V, False),             # Bounding box 3.217 r x 2 r x 1.575 r on 6 objects.
        (1, "segments", I, G, False),           # Default 4.
        (2, "smooth", B, G, False),
        # id 3: an int, -1 on all 62 corpus teapots; meaning unknown (left in extra_values).
        (4, "part_body", B, G, False),
        (5, "part_handle", B, G, False),
        (6, "part_spout", B, G, False),
        (7, "part_lid", B, G, False),
        (8, "generate_uvs", B, G, False),
    ],
    "CHAMFERBOX": [
        (0, "length", F, V, False),
        (1, "width", F, V, False),
        (2, "height", F, V, False),             # 18 of 20 context boxes.
        (3, "fillet", F, G, False),
        (4, "width_segments", I, G, False),     # Guess: same order as Box.
        (5, "length_segments", I, G, False),
        (6, "height_segments", I, G, False),
        (7, "fillet_segments", I, G, False),
        (8, "smooth", B, G, False),
        (9, "generate_uvs", B, G, False),
    ],
    "CHAMFERCYL": [
        (0, "radius", F, V, False),
        (1, "height", F, V, False),
        (2, "fillet", F, G, False),
        (3, "height_segments", I, G, False),
        (4, "fillet_segments", I, G, False),
        (5, "sides", I, V, False),              # 9 of 9 context boxes.
        (6, "cap_segments", I, G, False),
        (7, "smooth", B, G, False),
        *_slice(8),
        (11, "generate_uvs", B, G, False),
    ],
    "CAPSULE": [
        (0, "radius", F, V, False),
        (1, "height", F, V, False),             # Overall height (caps included) when height_type is 0: 7 of 7.
        (2, "height_type", I, G, False),        # Guess: 0 = overall, 1 = centres (0 on all 7).
        (3, "sides", I, G, False),
        (4, "height_segments", I, G, False),
        (5, "smooth", B, G, False),
        *_slice(6),
        (9, "generate_uvs", B, G, False),
    ],
    "TORUS_KNOT": [
        # Guess: from defaults only (2 objects): 120 segments, 12 sides, p = 2, q = 3.
        (0, "radius", F, G, False),
        (1, "cross_section_radius", F, G, False),
        (4, "segments", I, G, False),
        (5, "sides", I, G, False),
        (7, "p", F, G, False),
        (8, "q", F, G, False),
    ],
}

# Class ID (superclass 0x10) -> kind. Verified: class IDs and names from the class directories of the corpus.
PRIMITIVES = {
    ClassID(0x10): "BOX",
    ClassID(0x11): "SPHERE",
    ClassID(0x12): "CYLINDER",
    ClassID(0x20): "TORUS",
    ClassID.from_u64(0x00000000A86C23DD): "CONE",
    ClassID.from_u64(0x77566F65081F1DFC): "PLANE",
    ClassID.from_u64(0x00007F9E00000000): "GEOSPHERE",
    ClassID.from_u64(0xACAD26D9ACAD13D3): "TEAPOT",
    ClassID.from_u64(0x0000000000007B21): "TUBE",
    ClassID.from_u64(0x0000000000000720): "TORUS_KNOT",
    ClassID.from_u64(0x48EA0F971AD73F40): "CHAMFERBOX",
    ClassID.from_u64(0x21A446A17B9A546E): "CHAMFERCYL",
    ClassID.from_u64(0x79C939A96D3D77AC): "CAPSULE",
}

SLOT_PARAM_BLOCK = 0        # Verified: slot 0 holds the block on all 1,533 corpus primitives.


@dataclasses.dataclass
class PrimitiveData:
    """A primitive's parameters, and Max's own mesh for them when the file caches one."""
    kind: str                       # "BOX", "SPHERE", "CYLINDER", "TORUS", "CONE", "PLANE", "GEOSPHERE", ...
    params: dict[str, Any]          # Builder parameter names (see the module docstring), scene units / radians.
    cached_mesh: MeshData | None
    encoding: str | None = None     # Parameter block kind: "pb2" (ParamBlock2) or "pb" (old ParamBlock).
    extra_values: list = dataclasses.field(default_factory=list)  # Values of parameter IDs we have no name for.
    param_block: int | None = None  # Object index of the parameter block read.
    extra_params: dict[str, Any] = dataclasses.field(default_factory=dict)  # Named, not builder parameters.
    unknown_params: dict[int, Any] = dataclasses.field(default_factory=dict)  # Parameter ID -> value, unnamed.
    guessed: list[str] = dataclasses.field(default_factory=list)  # Names whose meaning is a guess.
    animated: list[str] = dataclasses.field(default_factory=list)  # Names driven by a controller.


def _convert(conversion, value):
    if conversion == F:
        return float(value)
    if conversion == I:
        return int(value)
    if conversion == B:
        return bool(value)
    return conversion.get(int(value))   # Enumeration (None when the stored value is unknown).


def read_primitive(kind, block, prim, warn):
    """Fill ``prim`` (a :class:`PrimitiveData`) from ``block`` (a ParamBlockData) for primitive ``kind``."""
    table = PRIMITIVE_PARAMS[kind]
    known = {entry[0] for entry in table}
    for param_id, name, conversion, verified, extra in table:
        param = block.get(param_id)
        if param is None:
            warn("parameter {:d} ({:s}) missing".format(param_id, name))
            continue
        if param.value is None or isinstance(param.value, list):
            warn("parameter {:d} ({:s}) has no static value".format(param_id, name))
            continue
        try:
            value = _convert(conversion, param.value)
        except (TypeError, ValueError):
            warn("parameter {:d} ({:s}): unexpected value {!r}".format(param_id, name, param.value))
            continue
        if value is None:
            # Unknown enumeration value: keep the raw number where it can't upset the builder.
            prim.extra_params[name] = param.value
            warn("parameter {:d} ({:s}): unknown value {!r}".format(param_id, name, param.value))
            continue
        target = prim.extra_params if extra else prim.params
        target[name] = value
        if not verified:
            prim.guessed.append(name)
        if param.animated:
            prim.animated.append(name)
    for param in block.entries:
        if param.param_id not in known:
            prim.unknown_params[param.param_id] = param.value
            prim.extra_values.append(param.value)
    return prim


def _decode(obj, ctx):
    kind = PRIMITIVES[obj.class_id]
    prim = PrimitiveData(kind, {}, None)

    def warn(message):
        ctx.warn("object {:d} ({:s}): {:s}".format(obj.index, obj.class_label(), message))

    # No corpus primitive caches a mesh. Should a file have a 0x08FE container, read it with the Editable Mesh layout.
    mesh_chunk = obj.chunk.find(CHUNK_MESH)
    if mesh_chunk is not None and mesh_chunk.is_container:
        # Unverified (no corpus example): the cache uses the Editable Mesh layout.
        prim.cached_mesh = read_tri_mesh(mesh_chunk, "primitive_cache")
        for message in prim.cached_mesh.warnings:
            warn("cached mesh: " + message)

    block_obj = ctx.ref(obj, SLOT_PARAM_BLOCK)
    block = ctx.scene.param_block(block_obj) if block_obj is not None else None
    if block is None:
        warn("no parameter block in reference slot 0")
        return prim
    prim.param_block = block_obj.index
    prim.encoding = block.kind
    for problem in block.problems:
        warn("parameter block: " + problem)
    return read_primitive(kind, block, prim, warn)


@decoder(*PRIMITIVES, kind="geometry.primitive", name="Primitives", superclass_id=0x10, verified=True)
def primitive(obj, ctx):
    """Primitive kind and parameters (from the parameter block in slot 0), and cached mesh when present."""
    return _decode(obj, ctx)
