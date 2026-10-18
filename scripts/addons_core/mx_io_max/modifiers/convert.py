# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Max modifiers to Blender modifiers (ROADMAP Phase 2d).

Each converter adds an equivalent Blender modifier, named after the Max modifier (its stack name when the user
renamed it) so the stack reads the same. Parameters use ``maxfile``'s names (lower_snake_case after the Max UI);
missing parameters take Max's defaults. Where Blender behaves differently the difference is listed in ``NOTES``
(and in ``docs/format/modifiers.md``).

Converters are ``f(obj, name, params, ctx)``; ``ctx`` is a :class:`ModContext` with what the stack knows about
the modifier (gizmo, input bounding box, per-node data) and the scene's unit scale. A converter returns the new
modifier, True when nothing needs adding (the modifier has no effect in Blender), or None when it can't convert
(the stack stops there). ``RESULT_PASS`` converters return :data:`SKIPPED`: the modifier is left out but the
stack goes on, because it doesn't change the shape (selection modifiers, UV modifiers that can't be applied).
"""

__all__ = (
    "CONVERTERS",
    "ModContext",
    "NOTES",
    "SKIPPED",
    "add_modifier",
    "changes_topology",
    "collapse",
    "converter_key",
)

import dataclasses
import math

import bpy
from mathutils import Matrix, Vector

AXES = ('X', 'Y', 'Z')
SKIPPED = "skipped"

NOTES = {
    "Shell": "Shell segments have no Blender equivalent (Solidify adds one layer)",
    "Chamfer": "Chamfer is approximated with Bevel on all edges",
    "Noise": "Per-axis noise strength is approximated with one strength along the normals",
    "MeshSmooth": "MeshSmooth is imported as Catmull-Clark subdivision",
    "Lattice": "Lattice is approximated with a Wireframe modifier",
    "Optimize": "Optimize is approximated with Decimate",
    "UVW_Map": "UVW Map coordinates are generated once on import (not live)",
}

# Blender modifier types that keep the mesh's vertex / face count and order.
DEFORM_TYPES = {'SIMPLE_DEFORM', 'DISPLACE', 'SMOOTH', 'LAPLACIANSMOOTH', 'CAST', 'WAVE', 'UV_PROJECT'}


@dataclasses.dataclass
class ModContext:
    """What the importer knows about one modifier in one node's stack."""
    unit_scale: float = 1.0             # Metres per scene unit.
    gizmo: object = None                # Gizmo transform (maxfile Transform) or None.
    center: tuple | None = None         # Gizmo centre position (Bend, Twist, Taper), scene units.
    context_tm: tuple | None = None     # Modifier context matrix rows (x, y, z axes, translation).
    bbox: tuple | None = None           # Input bounding box (min, max), object space, scene units.
    data: object = None                 # Per-node modifier data chunk (0x2512), when stored.
    to_object: Matrix = dataclasses.field(default_factory=lambda: Matrix.Identity(4))
    """Mesh coordinates (Blender) to Max object space (scene units)."""
    display_name: str | None = None
    notes: list = dataclasses.field(default_factory=list)

    def note(self, text):
        self.notes.append(text)

    def context_matrix(self):
        """The context matrix as a column-vector Matrix (object space to modifier context space)."""
        if self.context_tm is None:
            return Matrix.Identity(4)
        rows = self.context_tm
        return Matrix(((rows[0][0], rows[1][0], rows[2][0], rows[3][0]),
                       (rows[0][1], rows[1][1], rows[2][1], rows[3][1]),
                       (rows[0][2], rows[1][2], rows[2][2], rows[3][2]),
                       (0.0, 0.0, 0.0, 1.0)))

    def gizmo_matrix(self):
        """The gizmo in object space (scene units), or None when it is at the context's origin."""
        tm = self.context_matrix()
        gizmo = Matrix([list(r) for r in self.gizmo.matrix()]) if self.gizmo is not None else Matrix.Identity(4)
        result = tm.inverted_safe() @ gizmo
        return None if _is_identity(result) else result

    def to_mesh(self):
        """Max object space (scene units) to mesh coordinates."""
        return self.to_object.inverted_safe()


def _is_identity(m, eps=1e-5):
    return all(abs(m[i][j] - (1.0 if i == j else 0.0)) < eps for i in range(4) for j in range(4))


def converter_key(class_name):
    """Converter table key of a Max modifier class name: "UVW Map" -> "UVW_Map", "Turn to Poly" -> "Turn_to_Poly"."""
    return class_name.strip().replace(" ", "_").replace(".", "").replace("(", "_").replace(")", "")


def _axis(params, key, default=0):
    value = params.get(key, default)
    return AXES[value] if isinstance(value, int) and 0 <= value < 3 else AXES[default]


def _helper_empty(obj, name, matrix):
    """An empty parented to ``obj`` at ``matrix`` (in ``obj``'s mesh space), for gizmo-driven modifiers."""
    empty = bpy.data.objects.new(name, None)
    empty.empty_display_type = 'ARROWS'
    empty.empty_display_size = max(0.05, max(obj.dimensions) * 0.25 if obj.data is not None else 0.25)
    for coll in obj.users_collection:
        coll.objects.link(empty)
    empty.parent = obj
    empty.matrix_parent_inverse = Matrix.Identity(4)
    empty.matrix_basis = matrix
    empty.hide_render = True
    empty["mx_gizmo_of"] = obj.name
    return empty


def _gizmo_empty(obj, name, ctx, center=None):
    """An empty at the modifier's gizmo (and centre) when it isn't at the object origin, else None."""
    gizmo = ctx.gizmo_matrix()
    if center is not None and any(abs(c) > 1e-6 for c in center):
        gizmo = (gizmo if gizmo is not None else Matrix.Identity(4)) @ Matrix.Translation(Vector(center))
    if gizmo is None:
        return None
    to_mesh = ctx.to_mesh()
    loc, rot, _scale = (to_mesh @ gizmo).decompose()
    return _helper_empty(obj, "{:s} {:s} Gizmo".format(obj.name, name),
                         Matrix.Translation(loc) @ rot.to_matrix().to_4x4())


def _subdivision(obj, name, params, ctx):
    mod = obj.modifiers.new(name, 'SUBSURF')
    iterations = params.get("iterations", 0 if name == "MeshSmooth" else 1)
    mod.levels = iterations
    if params.get("use_render_iterations"):
        mod.render_levels = params.get("render_iterations", iterations)
    else:
        mod.render_levels = iterations
    mod.quality = 3
    if params.get("subdivision_method", 2) != 2 and name == "MeshSmooth":
        ctx.note("MeshSmooth classic / quad output imported as NURMS-like Catmull-Clark")
    return mod


def _shell(obj, name, params, ctx):
    inner = params.get("inner_amount", 0.0)
    outer = params.get("outer_amount", 1.0)
    mod = obj.modifiers.new(name, 'SOLIDIFY')
    total = (inner + outer) * ctx.unit_scale
    mod.thickness = total
    mod.offset = (outer - inner) / (inner + outer) if inner + outer > 0.0 else 0.0
    mod.use_even_offset = True
    if params.get("segments", 1) > 1:
        ctx.note(NOTES["Shell"])
    return mod


def _symmetry(obj, name, params, ctx):
    mod = obj.modifiers.new(name, 'MIRROR')
    axis = params.get("axis", 0)
    axis = axis if isinstance(axis, int) and 0 <= axis < 3 else 0
    for i in range(3):
        mod.use_axis[i] = i == axis
        mod.use_bisect_axis[i] = i == axis and params.get("slice_along_mirror", True)
        mod.use_bisect_flip_axis[i] = i == axis and params.get("flip", False)
    mod.use_mirror_merge = params.get("weld_seam", True)
    mod.merge_threshold = params.get("threshold", 0.1) * ctx.unit_scale
    mod.use_clip = True
    gizmo = _gizmo_empty(obj, name, ctx)
    if gizmo is not None:
        mod.mirror_object = gizmo
    return mod


def _mirror(obj, name, params, ctx):
    axis = params.get("mirror_axis", 0)
    axes = {0: (0,), 1: (1,), 2: (2,), 3: (0, 1), 4: (1, 2), 5: (2, 0)}.get(axis, (0,))
    offset = params.get("offset", 0.0)
    center = None
    if offset:
        center = [0.0, 0.0, 0.0]
        for i in axes:
            center[i] = offset / 2.0
    gizmo = _gizmo_empty(obj, name, ctx, center)
    if not params.get("copy", False):
        # Max mirrors the object itself (no copy): scale by -1 about the gizmo, then flip the faces.
        mod = obj.modifiers.new(name, 'NODES')
        mod.node_group = _flip_group(axes)
        if gizmo is not None:
            ctx.note("Mirror without copy about a moved gizmo is mirrored about the object origin")
            bpy.data.objects.remove(gizmo)
        return mod
    mod = obj.modifiers.new(name, 'MIRROR')
    for i in range(3):
        mod.use_axis[i] = i in axes
    mod.use_mirror_merge = False
    if gizmo is not None:
        mod.mirror_object = gizmo
    return mod


def _chamfer(obj, name, params, ctx):
    mod = obj.modifiers.new(name, 'BEVEL')
    mod.width = params.get("amount", 1.0) * ctx.unit_scale
    mod.segments = params.get("segments", 1)
    mod.affect = 'EDGES'
    mod.limit_method = 'ANGLE'
    mod.angle_limit = math.radians(params.get("min_angle", 30.0))
    ctx.note(NOTES["Chamfer"])
    return mod


def _limits(params, axis_index, ctx, center):
    """Blender Simple Deform limits (fractions of the input's extent along the axis) from Max's limits."""
    if not params.get("limit_effect", False):
        return None
    if ctx.bbox is None:
        ctx.note("deformation limits not applied (no input bounding box)")
        return None
    lo_box, hi_box = ctx.bbox[0][axis_index], ctx.bbox[1][axis_index]
    extent = hi_box - lo_box
    if extent <= 1e-9:
        return None
    c = center[axis_index] if center is not None else 0.0
    lower = c + params.get("lower_limit", 0.0)
    upper = c + params.get("upper_limit", 0.0)
    lo = min(max((lower - lo_box) / extent, 0.0), 1.0)
    hi = min(max((upper - lo_box) / extent, 0.0), 1.0)
    return (min(lo, hi), max(lo, hi))


def _deform(method):
    def convert(obj, name, params, ctx):
        mod = obj.modifiers.new(name, 'SIMPLE_DEFORM')
        mod.deform_method = method
        if method == 'BEND':
            mod.angle = math.radians(params.get("bend_angle", 0.0))
            mod.deform_axis = _axis(params, "bend_axis", 2)
            if abs(params.get("bend_direction", 0.0)) > 1e-3:
                ctx.note("Bend direction other than 0 is not applied")
        elif method == 'TWIST':
            mod.angle = math.radians(params.get("angle", 0.0))
            mod.deform_axis = _axis(params, "axis", 2)
            if abs(params.get("bias", 0.0)) > 1e-3:
                ctx.note("Twist bias is not applied")
        else:
            mod.factor = params.get("amount", 0.0)
            mod.deform_axis = _axis(params, "primary_axis", 2)
            if abs(params.get("curve", 0.0)) > 1e-3:
                ctx.note("Taper curve is not applied")
        axis_index = AXES.index(mod.deform_axis)
        gizmo = _gizmo_empty(obj, name, ctx, ctx.center)
        if gizmo is not None:
            mod.origin = gizmo
        limits = _limits(params, axis_index, ctx, ctx.center)
        if limits is not None:
            mod.limits = limits
        return mod
    return convert


def _noise(obj, name, params, ctx):
    tex = bpy.data.textures.new(name, 'CLOUDS')
    tex.noise_scale = params.get("scale", 100.0) * ctx.unit_scale
    tex.noise_depth = int(params.get("iterations", 6.0)) if params.get("fractal", False) else 0
    mod = obj.modifiers.new(name, 'DISPLACE')
    mod.texture = tex
    mod.texture_coords = 'LOCAL'
    strength = params.get("strength", (0.0, 0.0, 0.0))
    if isinstance(strength, (tuple, list)):
        mod.strength = max(abs(c) for c in strength) * ctx.unit_scale
        nonzero = [i for i, c in enumerate(strength) if abs(c) > 1e-9]
        if len(nonzero) == 1:
            mod.direction = AXES[nonzero[0]]
        else:
            ctx.note(NOTES["Noise"])
    else:
        mod.strength = float(strength) * ctx.unit_scale
    mod.mid_level = 0.5
    return mod


def _push(obj, name, params, ctx):
    mod = obj.modifiers.new(name, 'DISPLACE')
    mod.strength = params.get("push_value", 0.0) * ctx.unit_scale
    mod.mid_level = 0.0
    mod.direction = 'NORMAL'
    return mod


def _relax(obj, name, params, ctx):
    mod = obj.modifiers.new(name, 'SMOOTH')
    mod.factor = params.get("relax_value", 0.5)
    mod.iterations = params.get("iterations", 1)
    return mod


def _optimize(obj, name, params, ctx):
    mod = obj.modifiers.new(name, 'DECIMATE')
    if "vertex_percent" in params:
        mod.ratio = params["vertex_percent"] / 100.0
    else:
        mod.decimate_type = 'DISSOLVE'
        mod.angle_limit = params.get("face_threshold", math.radians(4.0))
    ctx.note(NOTES["Optimize"])
    return mod


def _lattice(obj, name, params, ctx):
    mod = obj.modifiers.new(name, 'WIREFRAME')
    mod.thickness = params.get("strut_radius", 0.5) * 2.0 * ctx.unit_scale
    mod.use_replace = params.get("geometry_type", 2) != 2
    ctx.note(NOTES["Lattice"])
    return mod


def _new_group(name):
    group = bpy.data.node_groups.new(name, 'GeometryNodeTree')
    group.interface.new_socket("Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
    group.interface.new_socket("Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
    inp = group.nodes.new("NodeGroupInput")
    out = group.nodes.new("NodeGroupOutput")
    inp.location, out.location = (-400.0, 0.0), (400.0, 0.0)
    return group, inp, out


def _flip_faces_group():
    group = bpy.data.node_groups.get("Flip Normals")
    if group is not None:
        return group
    group, inp, out = _new_group("Flip Normals")
    flip = group.nodes.new("GeometryNodeFlipFaces")
    group.links.new(inp.outputs[0], flip.inputs["Mesh"])
    group.links.new(flip.outputs["Mesh"], out.inputs[0])
    return group


def _flip_group(axes):
    """Mirror the geometry about the origin on ``axes`` (scale -1) and flip its faces."""
    label = "".join(AXES[i] for i in axes)
    name = "Mirror " + label
    group = bpy.data.node_groups.get(name)
    if group is not None:
        return group
    group, inp, out = _new_group(name)
    transform = group.nodes.new("GeometryNodeTransform")
    transform.location = (-150.0, 0.0)
    scale = [1.0, 1.0, 1.0]
    for i in axes:
        scale[i] = -1.0
    transform.inputs["Scale"].default_value = scale
    group.links.new(inp.outputs[0], transform.inputs["Geometry"])
    last = transform.outputs["Geometry"]
    if len(axes) % 2:
        flip = group.nodes.new("GeometryNodeFlipFaces")
        flip.location = (150.0, 0.0)
        group.links.new(last, flip.inputs["Mesh"])
        last = flip.outputs["Mesh"]
    group.links.new(last, out.inputs[0])
    return group


def _normal(obj, name, params, ctx):
    if not params.get("flip", True):
        return True
    mod = obj.modifiers.new(name, 'NODES')
    mod.node_group = _flip_faces_group()
    return mod


def _nothing(obj, name, params, ctx):
    # Blender meshes are already polygons: Turn to Poly / Turn to Mesh change nothing.
    return True


def _skip(reason):
    def convert(obj, name, params, ctx):
        ctx.note(reason)
        return SKIPPED
    return convert


def _uvw_map(obj, name, params, ctx):
    """Generate the UVs once, on the mesh as it is (the stack so far must not have changed the topology)."""
    from . import uv
    from ..materials.nodes import uv_layer_name
    if changes_topology(obj):
        ctx.note("UVW Map above modifiers that change the topology: not applied")
        return SKIPPED
    if any(m.type in DEFORM_TYPES for m in obj.modifiers):
        ctx.note("UVW Map above deforming modifiers: mapped on the undeformed mesh")
    mesh = obj.data
    if params.get("map_type", 0) not in (0, 1, 2, 3, 4):
        ctx.note("UVW Map type {!s} not converted".format(uv.MAP_TYPES.get(params.get("map_type"), "?")))
        return SKIPPED
    gizmo = ctx.gizmo_matrix() or Matrix.Identity(4)
    to_gizmo = gizmo.inverted_safe() @ ctx.to_object
    loops = [0] * len(mesh.loops)
    mesh.loops.foreach_get("vertex_index", loops)
    co = [0.0] * (len(mesh.vertices) * 3)
    mesh.vertices.foreach_get("co", co)
    sizes = [0] * len(mesh.polygons)
    mesh.polygons.foreach_get("loop_total", sizes)
    normals = [0.0] * (len(mesh.polygons) * 3)
    mesh.polygons.foreach_get("normal", normals)
    corners = [(co[3 * i], co[3 * i + 1], co[3 * i + 2]) for i in loops]
    # Normals are directions: the object-space conversion is applied to them by uv_map's gizmo matrix too.
    face_normals = [tuple((ctx.to_object.to_3x3() @ Vector(normals[3 * i:3 * i + 3])).normalized())
                    for i in range(len(sizes))]
    rows = [tuple(r) for r in to_gizmo]
    uvs = uv.uvw_map(corners, sizes, face_normals, params, rows)
    if uvs is None:
        return SKIPPED
    layer_name = uv_layer_name(params.get("channel", 1))
    layer = mesh.uv_layers.get(layer_name) or mesh.uv_layers.new(name=layer_name, do_init=False)
    layer.data.foreach_set("uv", [c for p in uvs for c in p])
    ctx.note(NOTES["UVW_Map"])
    return True


def _unwrap(obj, name, params, ctx):
    """Apply the UVs Unwrap UVW stored for this node, when they fit the mesh at this point of the stack."""
    from . import uv
    from ..materials.nodes import uv_layer_name
    if ctx.data is None:
        ctx.note("Unwrap UVW without stored coordinates: skipped")
        return SKIPPED
    parsed = uv.parse_unwrap(ctx.data)
    if parsed is None:
        ctx.note("Unwrap UVW coordinates not readable: skipped")
        return SKIPPED
    if changes_topology(obj):
        ctx.note("Unwrap UVW above modifiers that change the topology: its coordinates are not applied")
        return SKIPPED
    tverts, faces = parsed
    mesh = obj.data
    if len(faces) != len(mesh.polygons):
        ctx.note("Unwrap UVW coordinates don't match the mesh (face count): skipped")
        return SKIPPED
    loops = [0] * len(mesh.loops)
    mesh.loops.foreach_get("vertex_index", loops)
    starts = [0] * len(mesh.polygons)
    mesh.polygons.foreach_get("loop_start", starts)
    uvs = [0.0] * (len(loops) * 2)
    for start, (tv, geo) in zip(starts, faces):
        if tuple(loops[start:start + len(geo)]) != geo:
            ctx.note("Unwrap UVW coordinates don't match the mesh (vertex order): skipped")
            return SKIPPED
        for k, t in enumerate(tv):
            uvs[2 * (start + k)], uvs[2 * (start + k) + 1] = tverts[t]
    layer_name = uv_layer_name(params.get("channel", 1) or 1)
    layer = mesh.uv_layers.get(layer_name) or mesh.uv_layers.new(name=layer_name, do_init=False)
    layer.data.foreach_set("uv", uvs)
    return True


def _stop(reason):
    def convert(obj, name, params, ctx):
        ctx.note(reason)
        return None
    return convert


CONVERTERS = {
    "TurboSmooth": _subdivision,
    "MeshSmooth": _subdivision,
    "OpenSubdiv": _subdivision,
    "Shell": _shell,
    "Symmetry": _symmetry,
    "Mirror": _mirror,
    "Chamfer": _chamfer,
    "Bend": _deform('BEND'),
    "Twist": _deform('TWIST'),
    "Taper": _deform('TAPER'),
    "Noise": _noise,
    "Push": _push,
    "Relax": _relax,
    "Optimize": _optimize,
    "ProOptimizer": _optimize,
    "Lattice": _lattice,
    "Normal": _normal,
    "Turn_to_Poly": _nothing,
    "Turn_to_Mesh": _nothing,
    "Turn_to_Patch": _nothing,
    "UVW_Map": _uvw_map,
    "Unwrap_UVW": _unwrap,
    # Modifiers that don't change the shape: left out, the stack goes on.
    "Mesh_Select": _skip("selection modifiers are left out: the modifiers above them apply to the whole object"),
    "Poly_Select": _skip("selection modifiers are left out: the modifiers above them apply to the whole object"),
    "Vol_Select": _skip("selection modifiers are left out: the modifiers above them apply to the whole object"),
    "Attribute_Holder": _skip("Attribute Holder left out (it only holds custom attributes)"),
    "Arnold_Properties": _skip("Arnold Properties left out (render settings)"),
    "MapScaler": _skip("MapScaler (world-space UV scaling) not applied"),
    # Modifiers whose result isn't stored: the stack is imported up to them.
    "Edit_Poly": _stop("Edit Poly stores its edits, not its result: the stack is imported up to it"),
    "Edit_Mesh": _stop("Edit Mesh stores its edits, not its result: the stack is imported up to it"),
}


def changes_topology(obj):
    """Whether the Blender modifiers on ``obj`` change its vertex / face count or order."""
    return any(m.type not in DEFORM_TYPES for m in obj.modifiers)


def add_modifier(obj, class_name, params, enabled=None, ctx=None, name=None):
    """
    Add the Blender equivalent of a Max modifier.

    Returns True when it was converted (or needs nothing in Blender), :data:`SKIPPED` when it was left out
    without stopping the stack, and False when it is not supported (the caller stops the stack).
    """
    converter = CONVERTERS.get(converter_key(class_name))
    if converter is None:
        return False
    if ctx is None:
        ctx = ModContext()
    params = {k: v for k, v in params.items() if not k.startswith("_")}
    label = name or class_name
    if ctx.display_name:
        label = ctx.display_name
    mod = converter(obj, label, params, ctx)
    if mod is None:
        return False
    if mod == SKIPPED:
        return SKIPPED
    if isinstance(mod, bpy.types.Modifier) and enabled is not None:
        mod.show_viewport = mod.show_render = bool(enabled)
    return True


def collapse(obj):
    """Apply the whole modifier stack (Max "Collapse All"), giving the object its own evaluated mesh."""
    if not obj.modifiers:
        return
    depsgraph = bpy.context.evaluated_depsgraph_get()
    mesh = bpy.data.meshes.new_from_object(obj.evaluated_get(depsgraph), preserve_all_data_layers=True,
                                           depsgraph=depsgraph)
    obj.modifiers.clear()
    old = obj.data
    obj.data = mesh
    if old.users == 0:
        bpy.data.meshes.remove(old)
