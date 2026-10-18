# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Max modifiers to Blender modifiers (ROADMAP Phase 2d).

Each converter adds an equivalent Blender modifier, named after the Max modifier so the stack reads the same.
Parameters use the modifier's own parameter names in lower_snake_case; missing parameters take Max's
defaults. Where Blender behaves differently the difference is listed in ``NOTES`` (and in the docs).
"""

__all__ = (
    "CONVERTERS",
    "NOTES",
    "add_modifier",
    "collapse",
)

import math

import bpy

AXES = ('X', 'Y', 'Z')

NOTES = {
    "Shell": "Shell segments have no Blender equivalent (Solidify adds one layer)",
    "Chamfer": "Chamfer is approximated with Bevel on all edges",
    "Bend": "Bend direction other than 0 is not applied",
    "Noise": "Per-axis noise strength is approximated with one strength along the normals",
    "Symmetry": "Symmetry is mirrored about the object origin (the Max gizmo position is not read yet)",
}


def _axis(params, key, default=0):
    value = params.get(key, default)
    return AXES[value] if isinstance(value, int) and 0 <= value < 3 else AXES[default]


def _subdivision(obj, name, params):
    mod = obj.modifiers.new(name, 'SUBSURF')
    iterations = params.get("iterations", 1 if name == "TurboSmooth" else 0 if name == "MeshSmooth" else 1)
    mod.levels = iterations
    mod.render_levels = params.get("render_iterations", iterations) if params.get("use_render_iterations") \
        else iterations
    mod.quality = 3
    return mod


def _shell(obj, name, params):
    inner = params.get("inner_amount", 0.0)
    outer = params.get("outer_amount", 1.0)
    mod = obj.modifiers.new(name, 'SOLIDIFY')
    total = inner + outer
    mod.thickness = total
    mod.offset = (outer - inner) / total if total > 0.0 else 0.0
    mod.use_even_offset = True
    return mod


def _symmetry(obj, name, params):
    mod = obj.modifiers.new(name, 'MIRROR')
    axis = params.get("axis", 0)
    axis = axis if isinstance(axis, int) and 0 <= axis < 3 else 0
    for i in range(3):
        mod.use_axis[i] = i == axis
        mod.use_bisect_axis[i] = i == axis
        mod.use_bisect_flip_axis[i] = i == axis and params.get("flip", False)
    mod.use_mirror_merge = params.get("weld_seam", True)
    mod.merge_threshold = params.get("threshold", 0.001)
    mod.use_clip = True
    return mod


def _mirror(obj, name, params):
    mod = obj.modifiers.new(name, 'MIRROR')
    axis = params.get("mirror_axis", 0)
    for i in range(3):
        mod.use_axis[i] = i == axis
    mod.use_mirror_merge = False
    return mod


def _chamfer(obj, name, params):
    mod = obj.modifiers.new(name, 'BEVEL')
    mod.width = params.get("amount", 1.0)
    mod.segments = params.get("segments", 1)
    mod.affect = 'EDGES'
    mod.limit_method = 'ANGLE'
    mod.angle_limit = math.radians(params.get("min_angle", 30.0))
    return mod


def _deform(method):
    def convert(obj, name, params):
        mod = obj.modifiers.new(name, 'SIMPLE_DEFORM')
        mod.deform_method = method
        if method == 'BEND':
            mod.angle = math.radians(params.get("bend_angle", 0.0))
            mod.deform_axis = _axis(params, "bend_axis", 2)
        elif method == 'TWIST':
            mod.angle = math.radians(params.get("angle", 0.0))
            mod.deform_axis = _axis(params, "axis", 2)
        else:
            mod.factor = params.get("amount", 0.0)
            mod.deform_axis = _axis(params, "primary_axis", 2)
        if "upper_limit" in params or "lower_limit" in params:
            # Max limits are distances from the gizmo centre; Blender's are fractions of the object's extent.
            mod.limits = (0.0, 1.0)
        return mod
    return convert


def _noise(obj, name, params):
    tex = bpy.data.textures.new(name, 'CLOUDS')
    tex.noise_scale = params.get("scale", 100.0) * params.get("_unit_scale", 1.0)
    tex.noise_depth = int(params.get("iterations", 6.0)) if params.get("fractal", False) else 0
    mod = obj.modifiers.new(name, 'DISPLACE')
    mod.texture = tex
    strength = params.get("strength", (0.0, 0.0, 0.0))
    mod.strength = max(abs(c) for c in strength) if isinstance(strength, (tuple, list)) else float(strength)
    mod.mid_level = 0.5
    return mod


def _push(obj, name, params):
    mod = obj.modifiers.new(name, 'DISPLACE')
    mod.strength = params.get("push_value", 0.0)
    mod.mid_level = 0.0
    mod.direction = 'NORMAL'
    return mod


def _relax(obj, name, params):
    mod = obj.modifiers.new(name, 'SMOOTH')
    mod.factor = params.get("relax_value", 0.5)
    mod.iterations = params.get("iterations", 1)
    return mod


def _optimize(obj, name, params):
    mod = obj.modifiers.new(name, 'DECIMATE')
    mod.ratio = params.get("vertex_percent", 100.0) / 100.0 if "vertex_percent" in params else 0.5
    return mod


def _lattice(obj, name, params):
    mod = obj.modifiers.new(name, 'WIREFRAME')
    mod.thickness = params.get("strut_radius", 0.5) * 2.0
    mod.use_replace = params.get("geometry_type", 2) != 2
    return mod


def _flip_faces_group():
    group = bpy.data.node_groups.get("Flip Normals")
    if group is not None:
        return group
    group = bpy.data.node_groups.new("Flip Normals", 'GeometryNodeTree')
    group.interface.new_socket("Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
    group.interface.new_socket("Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
    nodes = group.nodes
    inp = nodes.new("NodeGroupInput")
    out = nodes.new("NodeGroupOutput")
    flip = nodes.new("GeometryNodeFlipFaces")
    inp.location, flip.location, out.location = (-300.0, 0.0), (0.0, 0.0), (300.0, 0.0)
    group.links.new(inp.outputs[0], flip.inputs["Mesh"])
    group.links.new(flip.outputs["Mesh"], out.inputs[0])
    return group


def _normal(obj, name, params):
    if not params.get("flip", True):
        return None
    mod = obj.modifiers.new(name, 'NODES')
    mod.node_group = _flip_faces_group()
    return mod


def _turn_to_poly(obj, name, params):
    # Blender meshes are already polygons: nothing to do, but the step is kept visible in the stack name.
    return True


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
    "Turn_to_Poly": _turn_to_poly,
}


def add_modifier(obj, class_name, params, enabled=None):
    """Add the Blender equivalent of a Max modifier. Returns False when the modifier is not supported."""
    converter = CONVERTERS.get(class_name)
    if converter is None:
        return False
    mod = converter(obj, class_name, params)
    if mod is None:
        return False
    # The modifier is named after the Max class (modifiers can't hold custom properties).
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
