# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
The Modifier List: Max modifier names mapped onto Blender modifiers.

Everything about the mapping is data in ``MODIFIERS`` below; ``add_modifier()`` applies an entry.
An entry either adds one Blender modifier (named after the Max modifier, with Max-like default settings),
runs a setup function for mappings that need more than a modifier (FFD creates a lattice, Noise a texture),
or performs an action (Edit Poly enters edit mode). Entries without a Blender equivalent are listed with
``available=False`` so the list matches what Max users look for, and report that they are coming later.

The same mapping can be reused by the ``.max`` importer (ROADMAP 2d) once it reads modifier parameters.
"""

import math
from dataclasses import dataclass, field

import bpy
from bpy.props import EnumProperty
from bpy.types import Menu, Operator

from . import utils

# Modifier sets, in the order the Modifier List shows them.
CATEGORIES = (
    ('SELECTION', "Selection & Editing"),
    ('SUBDIVISION', "Subdivision Surfaces"),
    ('PARAMETRIC', "Parametric Deformers"),
    ('FREEFORM', "Free Form Deformers"),
    ('SURFACE', "Surface"),
    ('MESH', "Mesh Editing"),
    ('UV', "UV Coordinates"),
    ('SPLINE', "Spline / Shape"),
)

MESH = frozenset({'MESH'})
MESH_CURVE = frozenset({'MESH', 'CURVE', 'SURFACE', 'FONT'})
CURVE = frozenset({'CURVE', 'FONT'})


@dataclass(frozen=True)
class MaxModifier:
    key: str
    """Identifier used by the operator (``object.mx_modifier_add(kind=key)``)."""
    label: str
    """The Max name, also used as the Blender modifier name."""
    category: str
    blender_type: str = ""
    """Blender modifier type ('' for action-only entries)."""
    settings: dict = field(default_factory=dict)
    """Attribute → value for the new modifier (Max defaults where they make sense)."""
    setup: str = ""
    """Name of a function in this module called as ``setup(context, obj, mod)`` after adding the modifier
    (or ``setup(context, obj, None)`` for action-only entries)."""
    object_types: frozenset = MESH_CURVE
    available: bool = True
    description: str = ""


MODIFIERS = (
    # Selection & editing.
    MaxModifier("EDIT_POLY", "Edit Poly", 'SELECTION', setup="setup_edit_mode", object_types=MESH,
                description="Edit the mesh at sub-object level (enters Edit Mode on the base object)"),
    MaxModifier("EDIT_MESH", "Edit Mesh", 'SELECTION', setup="setup_edit_mode", object_types=MESH,
                description="Edit the mesh at sub-object level (enters Edit Mode on the base object)"),
    MaxModifier("MESH_SELECT", "Mesh Select", 'SELECTION', available=False, object_types=MESH,
                description="Stack-level sub-object selection needs Phase 3 work"),

    # Subdivision surfaces.
    MaxModifier("TURBOSMOOTH", "TurboSmooth", 'SUBDIVISION', 'SUBSURF',
                {"levels": 1, "render_levels": 1, "subdivision_type": 'CATMULL_CLARK'},
                description="Subdivision Surface"),
    MaxModifier("MESHSMOOTH", "MeshSmooth", 'SUBDIVISION', 'SUBSURF',
                {"levels": 1, "render_levels": 1, "subdivision_type": 'CATMULL_CLARK'},
                description="Subdivision Surface"),
    MaxModifier("OPENSUBDIV", "OpenSubdiv", 'SUBDIVISION', 'SUBSURF',
                {"levels": 1, "render_levels": 1, "subdivision_type": 'CATMULL_CLARK'},
                description="Subdivision Surface"),
    MaxModifier("TESSELLATE", "Tessellate", 'SUBDIVISION', 'SUBSURF',
                {"levels": 1, "render_levels": 1, "subdivision_type": 'SIMPLE'},
                description="Simple subdivision without smoothing"),

    # Parametric deformers (Max defaults: zero amounts, so adding them changes nothing until edited).
    MaxModifier("BEND", "Bend", 'PARAMETRIC', 'SIMPLE_DEFORM',
                {"deform_method": 'BEND', "angle": 0.0, "deform_axis": 'Z'},
                description="Simple Deform, Bend"),
    MaxModifier("TWIST", "Twist", 'PARAMETRIC', 'SIMPLE_DEFORM',
                {"deform_method": 'TWIST', "angle": 0.0, "deform_axis": 'Z'},
                description="Simple Deform, Twist"),
    MaxModifier("TAPER", "Taper", 'PARAMETRIC', 'SIMPLE_DEFORM',
                {"deform_method": 'TAPER', "factor": 0.0, "deform_axis": 'Z'},
                description="Simple Deform, Taper"),
    MaxModifier("STRETCH", "Stretch", 'PARAMETRIC', 'SIMPLE_DEFORM',
                {"deform_method": 'STRETCH', "factor": 0.0, "deform_axis": 'Z'},
                description="Simple Deform, Stretch"),
    MaxModifier("NOISE", "Noise", 'PARAMETRIC', 'DISPLACE',
                {"direction": 'RGB_TO_XYZ', "mid_level": 0.5, "strength": 0.0, "texture_coords": 'LOCAL'},
                setup="setup_noise", description="Displace driven by a 3D noise texture"),
    MaxModifier("PUSH", "Push", 'PARAMETRIC', 'DISPLACE',
                {"direction": 'NORMAL', "mid_level": 0.0, "strength": 0.0},
                description="Displace along normals by a uniform amount"),
    MaxModifier("DISPLACE", "Displace", 'PARAMETRIC', 'DISPLACE', {"strength": 0.0},
                description="Displace"),
    MaxModifier("SPHERIFY", "Spherify", 'PARAMETRIC', 'CAST', {"cast_type": 'SPHERE', "factor": 1.0},
                description="Cast to sphere"),
    MaxModifier("WAVE", "Wave", 'PARAMETRIC', 'WAVE', {"use_x": True, "use_y": False, "height": 0.0},
                description="Linear wave"),
    MaxModifier("RIPPLE", "Ripple", 'PARAMETRIC', 'WAVE', {"use_x": True, "use_y": True, "height": 0.0},
                description="Radial wave"),
    MaxModifier("RELAX", "Relax", 'PARAMETRIC', 'SMOOTH', {"factor": 0.5, "iterations": 1},
                description="Smooth (relax vertex positions)"),
    MaxModifier("MIRROR", "Mirror", 'PARAMETRIC', 'MIRROR',
                {"use_axis": (True, False, False), "use_mirror_merge": False},
                description="Mirror"),
    MaxModifier("SYMMETRY", "Symmetry", 'PARAMETRIC', 'MIRROR',
                {"use_axis": (True, False, False), "use_bisect_axis": (True, False, False),
                 "use_mirror_merge": True, "use_clip": True},
                description="Mirror with bisect and welded seam"),
    MaxModifier("SKIN_WRAP", "Skin Wrap", 'PARAMETRIC', 'SURFACE_DEFORM', object_types=MESH,
                description="Surface Deform (pick the target in the parameters)"),
    MaxModifier("ARRAY", "Array", 'PARAMETRIC', 'ARRAY', {"count": 2}, description="Array"),

    # Free form deformers: a lattice fitted to the object.
    MaxModifier("FFD_2", "FFD 2x2x2", 'FREEFORM', 'LATTICE', setup="setup_ffd_2",
                description="Lattice, 2x2x2 control points"),
    MaxModifier("FFD_3", "FFD 3x3x3", 'FREEFORM', 'LATTICE', setup="setup_ffd_3",
                description="Lattice, 3x3x3 control points"),
    MaxModifier("FFD_4", "FFD 4x4x4", 'FREEFORM', 'LATTICE', setup="setup_ffd_4",
                description="Lattice, 4x4x4 control points"),
    MaxModifier("FFD_BOX", "FFD(box)", 'FREEFORM', 'LATTICE', setup="setup_ffd_box",
                description="Lattice, 4x4x4 control points"),

    # Surface.
    MaxModifier("SHELL", "Shell", 'SURFACE', 'SOLIDIFY',
                {"thickness": 0.1, "offset": -1.0, "use_even_offset": True, "use_rim": True},
                object_types=MESH, description="Solidify (inner amount)"),
    MaxModifier("SMOOTH", "Smooth", 'SURFACE', setup="setup_smooth_by_angle", object_types=MESH,
                description="Smooth by Angle (auto smooth, 30 degrees threshold)"),
    MaxModifier("NORMAL", "Normal", 'SURFACE', 'NODES', setup="setup_flip_normals", object_types=MESH,
                description="Flip normals (a small Geometry Nodes group)"),
    MaxModifier("WEIGHTED_NORMALS", "Weighted Normals", 'SURFACE', 'WEIGHTED_NORMAL',
                {"weight": 50, "keep_sharp": True}, object_types=MESH, description="Weighted Normal"),

    # Mesh editing.
    MaxModifier("CHAMFER", "Chamfer", 'MESH', 'BEVEL',
                {"affect": 'EDGES', "width": 0.1, "segments": 1, "limit_method": 'NONE'},
                object_types=MESH, description="Bevel"),
    MaxModifier("OPTIMIZE", "Optimize", 'MESH', 'DECIMATE',
                {"decimate_type": 'DISSOLVE', "angle_limit": math.radians(4.0)},
                object_types=MESH, description="Decimate, planar (face threshold 4 degrees)"),
    MaxModifier("PROOPTIMIZER", "ProOptimizer", 'MESH', 'DECIMATE',
                {"decimate_type": 'COLLAPSE', "ratio": 0.5},
                object_types=MESH, description="Decimate, collapse (50% of the vertices)"),
    MaxModifier("MULTIRES", "MultiRes", 'MESH', 'DECIMATE',
                {"decimate_type": 'COLLAPSE', "ratio": 1.0},
                object_types=MESH, description="Decimate, collapse"),
    MaxModifier("VERTEX_WELD", "Vertex Weld", 'MESH', 'WELD', {"merge_threshold": 0.001},
                object_types=MESH, description="Weld"),
    MaxModifier("WELD", "Weld", 'MESH', 'WELD', {"merge_threshold": 0.001},
                object_types=MESH, description="Weld"),
    MaxModifier("LATTICE", "Lattice", 'MESH', 'WIREFRAME',
                {"thickness": 0.05, "use_even_offset": True, "use_relative_offset": False},
                object_types=MESH, description="Wireframe (struts on every edge)"),
    MaxModifier("TURN_TO_MESH", "Turn to Mesh", 'MESH', 'TRIANGULATE', object_types=MESH,
                description="Triangulate"),
    MaxModifier("TURN_TO_POLY", "Turn to Poly", 'MESH', available=False, object_types=MESH,
                description="Blender meshes are already polygon meshes"),
    MaxModifier("BOOLEAN", "Boolean", 'MESH', 'BOOLEAN', {"operation": 'DIFFERENCE'},
                object_types=MESH, description="Boolean (pick the operand in the parameters)"),
    MaxModifier("SLICE", "Slice", 'MESH', available=False, object_types=MESH,
                description="No direct Blender equivalent yet"),
    MaxModifier("CAP_HOLES", "Cap Holes", 'MESH', available=False, object_types=MESH,
                description="No direct Blender equivalent yet"),

    # UV coordinates.
    MaxModifier("UVW_MAP", "UVW Map", 'UV', available=False, object_types=MESH,
                description="Max-style projections are coming later (ROADMAP 2d)"),
    MaxModifier("UNWRAP_UVW", "Unwrap UVW", 'UV', available=False, object_types=MESH,
                description="Coming later; use the UV Editing workspace meanwhile"),

    # Splines.
    MaxModifier("LATHE", "Lathe", 'SPLINE', 'SCREW', {"axis": 'Y', "steps": 16, "render_steps": 16},
                object_types=MESH_CURVE, description="Screw (360 degrees around Y)"),
    MaxModifier("RENDERABLE_SPLINE", "Renderable Spline", 'SPLINE', setup="setup_renderable_spline",
                object_types=CURVE, description="Sets the curve's bevel depth (thickness)"),
)

BY_KEY = {entry.key: entry for entry in MODIFIERS}


def entries_for(obj):
    """The entries that apply to ``obj``'s type, in list order."""
    obj_type = obj.type if obj else None
    return [entry for entry in MODIFIERS if obj_type in entry.object_types]


def enum_items():
    """Items for an `EnumProperty`, grouped by category (a flat list suits the search popup)."""
    order = {cat_id: index for index, (cat_id, _label) in enumerate(CATEGORIES)}
    entries = sorted(MODIFIERS, key=lambda entry: order[entry.category])
    return [(entry.key, entry.label, entry.description) for entry in entries]


class ModifierNotAvailable(Exception):
    pass


def add_modifier(context, obj, key):
    """
    Apply the Modifier List entry ``key`` to ``obj``. Returns the new modifier (None for action-only entries).
    Raises `ModifierNotAvailable` for entries without a Blender equivalent and `ValueError` for unsupported
    object types.
    """
    entry = BY_KEY[key]
    if not entry.available:
        raise ModifierNotAvailable("{:s}: {:s}".format(entry.label, entry.description))
    if obj.type not in entry.object_types:
        raise ValueError("{:s} can't be applied to a {:s} object".format(entry.label, obj.type.lower()))

    mod = None
    if entry.blender_type:
        mod = obj.modifiers.new(name=entry.label, type=entry.blender_type)
        if mod is None:
            raise ValueError("{:s} can't be applied to this object".format(entry.label))
        for attr, value in entry.settings.items():
            setattr(mod, attr, value)
        obj.modifiers.active = mod
    if entry.setup:
        result = globals()[entry.setup](context, obj, mod)
        if result is not None:
            mod = result
    return mod


# -----------------------------------------------------------------------------
# Setup functions

def setup_edit_mode(context, obj, _mod):
    view_layer = context.view_layer
    view_layer.objects.active = obj
    obj.select_set(True, view_layer=view_layer)
    with context.temp_override(**utils.object_context_override(context, obj)):
        bpy.ops.object.mode_set(mode='EDIT')


def setup_noise(_context, obj, mod):
    tex = bpy.data.textures.new(name="{:s} Noise".format(obj.name), type='CLOUDS')
    tex.cloud_type = 'COLOR'
    tex.noise_scale = 1.0
    mod.texture = tex


def _setup_ffd(context, obj, mod, resolution):
    from mathutils import Vector
    # Fit the lattice to the object's local bounding box, parented so it moves with the object
    # (Max's FFD gizmo lives in the object's space).
    corners = [Vector(c) for c in obj.bound_box]
    bb_min = Vector(min(c[i] for c in corners) for i in range(3))
    bb_max = Vector(max(c[i] for c in corners) for i in range(3))
    size = bb_max - bb_min
    center = (bb_min + bb_max) * 0.5
    eps = 1e-3

    lattice = bpy.data.lattices.new(name="{:s} {:s}".format(obj.name, mod.name))
    lattice.points_u, lattice.points_v, lattice.points_w = resolution
    lattice.interpolation_type_u = lattice.interpolation_type_v = lattice.interpolation_type_w = 'KEY_BSPLINE'
    lat_obj = bpy.data.objects.new(lattice.name, lattice)
    for collection in obj.users_collection:
        collection.objects.link(lat_obj)
    if not lat_obj.users_collection:
        utils.link_to_scene(context, lat_obj)
    lat_obj.parent = obj
    lat_obj.matrix_parent_inverse.identity()
    lat_obj.location = center
    lat_obj.scale = tuple(max(s, eps) for s in size)
    lat_obj.color = obj.color
    mod.object = lat_obj


def setup_ffd_2(context, obj, mod):
    _setup_ffd(context, obj, mod, (2, 2, 2))


def setup_ffd_3(context, obj, mod):
    _setup_ffd(context, obj, mod, (3, 3, 3))


def setup_ffd_4(context, obj, mod):
    _setup_ffd(context, obj, mod, (4, 4, 4))


def setup_ffd_box(context, obj, mod):
    _setup_ffd(context, obj, mod, (4, 4, 4))


FLIP_NORMALS_GROUP = "MX Normal"


def flip_normals_group():
    """A Geometry Nodes group that flips face orientation (reused across objects)."""
    group = bpy.data.node_groups.get(FLIP_NORMALS_GROUP)
    if group is not None and group.bl_idname == 'GeometryNodeTree':
        return group
    group = bpy.data.node_groups.new(FLIP_NORMALS_GROUP, 'GeometryNodeTree')
    group.is_modifier = True
    group.interface.new_socket("Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
    group.interface.new_socket("Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
    nodes = group.nodes
    node_in = nodes.new('NodeGroupInput')
    node_flip = nodes.new('GeometryNodeFlipFaces')
    node_out = nodes.new('NodeGroupOutput')
    node_in.location = (-250, 0)
    node_out.location = (250, 0)
    group.links.new(node_in.outputs[0], node_flip.inputs["Mesh"])
    group.links.new(node_flip.outputs["Mesh"], node_out.inputs[0])
    return group


def setup_flip_normals(_context, _obj, mod):
    mod.node_group = flip_normals_group()


def setup_smooth_by_angle(context, obj, _mod):
    before = set(obj.modifiers.keys())
    with context.temp_override(**utils.object_context_override(context, obj)):
        bpy.ops.object.shade_auto_smooth(use_auto_smooth=True, angle=math.radians(30.0))
    added = [mod for mod in obj.modifiers if mod.name not in before]
    if not added:
        return None
    mod = added[0]
    mod.name = BY_KEY["SMOOTH"].label
    obj.modifiers.active = mod
    return mod


def setup_renderable_spline(_context, obj, _mod):
    curve = obj.data
    if curve.bevel_depth == 0.0:
        curve.bevel_depth = 0.05
    curve.bevel_resolution = max(curve.bevel_resolution, 2)
    curve.use_fill_caps = True


# -----------------------------------------------------------------------------
# Parameters shown for a selected stack entry, per Blender modifier type.
# Anything not listed falls back to every editable property of the modifier.

PARAMETERS = {
    'SUBSURF': ("levels", "render_levels", "subdivision_type", "quality", "use_limit_surface"),
    'SIMPLE_DEFORM': ("deform_method", "angle", "factor", "deform_axis", "origin", "limits", "lock_x", "lock_y"),
    'DISPLACE': ("strength", "mid_level", "direction", "space", "texture", "texture_coords"),
    'CAST': ("cast_type", "factor", "radius", "size", "use_x", "use_y", "use_z", "object"),
    'WAVE': ("height", "width", "narrowness", "speed", "use_x", "use_y", "use_cyclic", "use_normal", "time_offset"),
    'SMOOTH': ("factor", "iterations", "use_x", "use_y", "use_z"),
    'MIRROR': ("use_axis", "use_bisect_axis", "use_bisect_flip_axis", "use_mirror_merge", "merge_threshold",
               "use_clip", "mirror_object"),
    'SURFACE_DEFORM': ("target", "falloff", "strength"),
    'ARRAY': ("fit_type", "count", "use_relative_offset", "relative_offset_displace", "use_constant_offset",
              "constant_offset_displace", "use_merge_vertices", "merge_threshold"),
    'LATTICE': ("object", "strength"),
    'SOLIDIFY': ("thickness", "offset", "use_even_offset", "use_rim", "use_flip_normals"),
    'WEIGHTED_NORMAL': ("mode", "weight", "thresh", "keep_sharp", "use_face_influence"),
    'BEVEL': ("affect", "offset_type", "width", "segments", "limit_method", "angle_limit", "profile",
              "harden_normals"),
    'DECIMATE': ("decimate_type", "ratio", "iterations", "angle_limit", "use_collapse_triangulate"),
    'WELD': ("mode", "merge_threshold"),
    'WIREFRAME': ("thickness", "offset", "use_even_offset", "use_relative_offset", "use_replace"),
    'TRIANGULATE': ("quad_method", "ngon_method", "min_vertices", "keep_custom_normals"),
    'BOOLEAN': ("operation", "operand_type", "object", "collection", "solver"),
    'SCREW': ("angle", "screw_offset", "iterations", "axis", "object", "steps", "render_steps",
              "use_merge_vertices", "use_normal_flip"),
}

# Shown only for some values of another property: {type: {prop: (controlling prop, allowed values)}}.
PARAMETER_CONDITIONS = {
    'SIMPLE_DEFORM': {
        "angle": ("deform_method", {'BEND', 'TWIST'}),
        "factor": ("deform_method", {'TAPER', 'STRETCH'}),
    },
    'DECIMATE': {
        "ratio": ("decimate_type", {'COLLAPSE'}),
        "use_collapse_triangulate": ("decimate_type", {'COLLAPSE'}),
        "iterations": ("decimate_type", {'UNSUBDIV'}),
        "angle_limit": ("decimate_type", {'DISSOLVE'}),
    },
    'BEVEL': {
        "angle_limit": ("limit_method", {'ANGLE'}),
    },
    'BOOLEAN': {
        "object": ("operand_type", {'OBJECT'}),
        "collection": ("operand_type", {'COLLECTION'}),
    },
}

# Generic fallback: these are part of every modifier and drawn by the stack itself.
_COMMON_PROPS = {
    "rna_type", "name", "type", "show_viewport", "show_render", "show_in_editmode", "show_on_cage",
    "show_expanded", "is_active", "use_pin_to_last", "is_override_data", "use_apply_on_spline",
    "execution_time", "persistent_uid",
}


def parameter_names(mod):
    """Names of the properties to draw for ``mod``, in order."""
    props = mod.bl_rna.properties
    names = PARAMETERS.get(mod.type)
    if names is None:
        names = [p.identifier for p in props
                 if p.identifier not in _COMMON_PROPS and not p.is_readonly and p.type != 'COLLECTION']
    conditions = PARAMETER_CONDITIONS.get(mod.type, {})
    result = []
    for name in names:
        if name not in props:
            continue
        condition = conditions.get(name)
        if condition and getattr(mod, condition[0]) not in condition[1]:
            continue
        result.append(name)
    return result


# -----------------------------------------------------------------------------
# Operator and menu

class OBJECT_OT_mx_modifier_add(Operator):
    """Add a modifier from the Max-style Modifier List"""
    bl_idname = "object.mx_modifier_add"
    bl_label = "Add Modifier"
    bl_options = {'REGISTER', 'UNDO'}
    bl_property = "kind"

    kind: EnumProperty(
        name="Modifier",
        items=enum_items(),
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type in MESH_CURVE and context.mode in {'OBJECT', 'EDIT_MESH', 'EDIT_CURVE'}

    @classmethod
    def description(cls, _context, properties):
        entry = BY_KEY.get(properties.kind)
        if entry is None:
            return None
        if not entry.available:
            return "{:s} (not available yet: {:s})".format(entry.label, entry.description)
        return "{:s} ({:s})".format(entry.label, entry.description)

    def invoke(self, context, _event):
        # Without an explicit kind, show a searchable list (like typing in Max's Modifier List).
        if not self.properties.is_property_set("kind"):
            context.window_manager.invoke_search_popup(self)
            return {'RUNNING_MODAL'}
        return self.execute(context)

    def execute(self, context):
        obj = context.active_object
        was_edit = obj.mode == 'EDIT'
        if was_edit and BY_KEY[self.kind].blender_type:
            # Modifiers can be added in edit mode, but setup functions may need object data in sync.
            obj.update_from_editmode()
        try:
            mod = add_modifier(context, obj, self.kind)
        except ModifierNotAvailable as ex:
            self.report({'WARNING'}, str(ex))
            return {'CANCELLED'}
        except (ValueError, RuntimeError) as ex:
            self.report({'ERROR'}, str(ex))
            return {'CANCELLED'}
        state = utils.get_state(context)
        if state is not None and mod is not None:
            state.stack_base_selected = ""
        return {'FINISHED'}


class OBJECT_MT_mx_modifier_list(Menu):
    bl_idname = "OBJECT_MT_mx_modifier_list"
    bl_label = "Modifier List"
    bl_options = {'SEARCH_ON_KEY_PRESS'}

    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        obj_type = obj.type if obj else None
        flow = layout.column_flow(columns=2)
        for cat_id, cat_label in CATEGORIES:
            entries = [entry for entry in MODIFIERS if entry.category == cat_id]
            if not entries:
                continue
            col = flow.column()
            col.label(text=cat_label)
            for entry in entries:
                row = col.row()
                row.enabled = entry.available and obj_type in entry.object_types
                row.operator(OBJECT_OT_mx_modifier_add.bl_idname, text=entry.label).kind = entry.key
            col.separator()


classes = (
    OBJECT_OT_mx_modifier_add,
    OBJECT_MT_mx_modifier_list,
)
