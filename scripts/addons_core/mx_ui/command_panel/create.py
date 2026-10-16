# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Create tab: Geometry (live primitives from ``mx_primitives``), Shapes, Lights, Cameras, Helpers,
plus the Name and Color rollout for the next object.

Shapes, lights, cameras and helpers are created here (``curve.mx_shape_add``, ``object.mx_create``) at the
3D cursor, with Max-style names ("Omni001", "Rectangle001").
"""

import math

import bpy
from bpy.props import EnumProperty
from bpy.types import Operator

from .. import utils
from ..state import CREATE_CATEGORIES

_CATEGORY_LABELS = {item[0]: item[1] for item in CREATE_CATEGORIES}

# Geometry > Standard Primitives, in Max's button order. The operator is provided by `mx_primitives`.
PRIMITIVES = (
    ('BOX', "Box"),
    ('CONE', "Cone"),
    ('SPHERE', "Sphere"),
    ('GEOSPHERE', "GeoSphere"),
    ('CYLINDER', "Cylinder"),
    ('TUBE', "Tube"),
    ('TORUS', "Torus"),
    ('PYRAMID', "Pyramid"),
    ('TEST_SHAPE', "Test Shape"),
    ('PLANE', "Plane"),
)

# Shapes > Splines.
SHAPES = (
    ('LINE', "Line"),
    ('RECTANGLE', "Rectangle"),
    ('CIRCLE', "Circle"),
    ('ELLIPSE', "Ellipse"),
    ('ARC', "Arc"),
    ('DONUT', "Donut"),
    ('NGON', "NGon"),
    ('STAR', "Star"),
    ('TEXT', "Text"),
    ('HELIX', "Helix"),
)

# Lights, cameras and helpers: (kind, button label, Max base name, group, available).
OBJECTS = (
    ('TARGET_SPOT', "Target Spot", "Spot", 'LIGHTS_STANDARD', True),
    ('FREE_SPOT', "Free Spot", "Spot", 'LIGHTS_STANDARD', True),
    ('TARGET_DIRECT', "Target Direct", "Direct", 'LIGHTS_STANDARD', True),
    ('FREE_DIRECT', "Free Direct", "Direct", 'LIGHTS_STANDARD', True),
    ('OMNI', "Omni", "Omni", 'LIGHTS_STANDARD', True),
    ('SKYLIGHT', "Skylight", "Skylight", 'LIGHTS_STANDARD', True),
    ('TARGET_LIGHT', "Target Light", "PhotometricLight", 'LIGHTS_PHOTOMETRIC', True),
    ('FREE_LIGHT', "Free Light", "PhotometricLight", 'LIGHTS_PHOTOMETRIC', True),
    ('SUN_POSITIONER', "Sun Positioner", "SunPositioner", 'LIGHTS_PHOTOMETRIC', True),
    ('PHYSICAL_CAMERA', "Physical", "PhysCamera", 'CAMERAS', True),
    ('TARGET_CAMERA', "Target", "Camera", 'CAMERAS', True),
    ('FREE_CAMERA', "Free", "Camera", 'CAMERAS', True),
    ('DUMMY', "Dummy", "Dummy", 'HELPERS', True),
    ('POINT', "Point", "Point", 'HELPERS', True),
    ('GRID', "Grid", "Grid", 'HELPERS', False),
    ('TAPE', "Tape", "Tape", 'HELPERS', False),
)
OBJECTS_BY_KIND = {kind: (label, base, group, available) for kind, label, base, group, available in OBJECTS}

GROUP_LABELS = {
    'LIGHTS_STANDARD': "Standard",
    'LIGHTS_PHOTOMETRIC': "Photometric",
    'CAMERAS': "Standard",
    'HELPERS': "Standard",
}
CATEGORY_GROUPS = {
    'LIGHTS': ('LIGHTS_STANDARD', 'LIGHTS_PHOTOMETRIC'),
    'CAMERAS': ('CAMERAS',),
    'HELPERS': ('HELPERS',),
}


# -----------------------------------------------------------------------------
# Building objects

def _finish(context, obj, base_name):
    obj.name = utils.max_style_name(base_name)
    obj.location = context.scene.cursor.location
    utils.link_to_scene(context, obj)
    utils.make_active(context, obj)
    return obj


def _add_target(context, obj, look_from_offset):
    """Max target objects: an empty "<name>.Target" that ``obj`` keeps pointing at (Track To)."""
    target = bpy.data.objects.new(obj.name + ".Target", None)
    target.empty_display_type = 'CUBE'
    target.empty_display_size = 0.1
    target.location = obj.location.copy()
    target.color = obj.color
    utils.link_to_scene(context, target)
    obj.location = obj.location + look_from_offset
    con = obj.constraints.new('TRACK_TO')
    con.target = target
    con.track_axis = 'TRACK_NEGATIVE_Z'
    con.up_axis = 'UP_Y'
    return target


def create_object(context, kind):
    """Create a light, camera or helper of the given kind. Returns the new (main) object."""
    from mathutils import Vector
    label, base, _group, available = OBJECTS_BY_KIND[kind]
    if not available:
        raise ValueError("{:s} is not available yet".format(label))

    if kind == 'SKYLIGHT':
        return _create_skylight(context)

    if kind in {'TARGET_SPOT', 'FREE_SPOT'}:
        data = bpy.data.lights.new(base, 'SPOT')
    elif kind in {'TARGET_DIRECT', 'FREE_DIRECT', 'SUN_POSITIONER'}:
        data = bpy.data.lights.new(base, 'SUN')
    elif kind in {'OMNI', 'TARGET_LIGHT', 'FREE_LIGHT'}:
        data = bpy.data.lights.new(base, 'POINT')
    elif kind in {'PHYSICAL_CAMERA', 'TARGET_CAMERA', 'FREE_CAMERA'}:
        data = bpy.data.cameras.new(base)
    else:
        data = None

    obj = _finish(context, bpy.data.objects.new(base, data), base)
    if kind == 'DUMMY':
        obj.empty_display_type = 'CUBE'
        obj.empty_display_size = 0.5
    elif kind == 'POINT':
        obj.empty_display_type = 'PLAIN_AXES'
        obj.empty_display_size = 0.5

    if kind in {'TARGET_SPOT', 'TARGET_DIRECT', 'TARGET_LIGHT'}:
        _add_target(context, obj, Vector((0.0, -4.0, 6.0)))
    elif kind == 'TARGET_CAMERA':
        _add_target(context, obj, Vector((0.0, -10.0, 5.0)))
    elif kind in {'FREE_SPOT', 'FREE_DIRECT', 'FREE_LIGHT', 'FREE_CAMERA', 'PHYSICAL_CAMERA'}:
        # Free lights and cameras point down the view (-Z): along the world -Z for lights, forward for cameras.
        if data is not None and isinstance(data, bpy.types.Camera):
            obj.rotation_euler = (math.radians(90.0), 0.0, 0.0)
    if kind == 'PHYSICAL_CAMERA':
        data.lens_unit = 'MILLIMETERS'
        data.dof.use_dof = False
    utils.make_active(context, obj)
    return obj


def _create_skylight(context):
    """Skylight placeholder: a bright sky-blue world background (dome lighting in Cycles and EEVEE)."""
    scene = context.scene
    world = scene.world
    if world is None:
        world = scene.world = bpy.data.worlds.new("World")
    world.color = (0.55, 0.65, 0.8)
    tree = world.node_tree
    if tree is not None:
        background = next((node for node in tree.nodes if node.type == 'BACKGROUND'), None)
        if background is not None:
            background.inputs["Color"].default_value = (0.55, 0.65, 0.8, 1.0)
            background.inputs["Strength"].default_value = 1.0
    return None


def _poly_spline(curve, points, cyclic):
    spline = curve.splines.new('POLY')
    spline.points.add(len(points) - 1)
    for point, co in zip(spline.points, points):
        point.co = (co[0], co[1], co[2] if len(co) > 2 else 0.0, 1.0)
    spline.use_cyclic_u = cyclic
    return spline


def _bezier_circle(curve, radius_x, radius_y):
    # Four-point Bezier circle (handle length for a quarter arc: 0.5523 * radius).
    k = 0.5523
    spline = curve.splines.new('BEZIER')
    spline.bezier_points.add(3)
    for i, point in enumerate(spline.bezier_points):
        angle = i * math.pi / 2.0
        cos_a, sin_a = math.cos(angle), math.sin(angle)
        point.co = (radius_x * cos_a, radius_y * sin_a, 0.0)
        tangent = (-radius_x * sin_a * k, radius_y * cos_a * k, 0.0)
        point.handle_left = (point.co[0] - tangent[0], point.co[1] - tangent[1], 0.0)
        point.handle_right = (point.co[0] + tangent[0], point.co[1] + tangent[1], 0.0)
        point.handle_left_type = point.handle_right_type = 'ALIGNED'
    spline.use_cyclic_u = True
    return spline


def build_shape(kind, curve):
    """Fill ``curve`` with the splines of a Max shape (default sizes in scene units)."""
    if kind == 'LINE':
        _poly_spline(curve, ((-1.0, 0.0), (0.0, 1.0), (1.0, 0.0)), cyclic=False)
    elif kind == 'RECTANGLE':
        _poly_spline(curve, ((-1.0, -0.75), (1.0, -0.75), (1.0, 0.75), (-1.0, 0.75)), cyclic=True)
    elif kind == 'CIRCLE':
        _bezier_circle(curve, 1.0, 1.0)
    elif kind == 'ELLIPSE':
        _bezier_circle(curve, 1.0, 0.6)
    elif kind == 'DONUT':
        _bezier_circle(curve, 1.0, 1.0)
        _bezier_circle(curve, 0.6, 0.6)
    elif kind == 'ARC':
        steps = 16
        _poly_spline(curve, [(math.cos(math.pi * i / steps), math.sin(math.pi * i / steps))
                             for i in range(steps + 1)], cyclic=False)
    elif kind == 'NGON':
        sides = 6
        _poly_spline(curve, [(math.cos(2.0 * math.pi * i / sides), math.sin(2.0 * math.pi * i / sides))
                             for i in range(sides)], cyclic=True)
    elif kind == 'STAR':
        points = 6
        coords = []
        for i in range(points * 2):
            radius = 1.0 if i % 2 == 0 else 0.5
            angle = math.pi * i / points
            coords.append((radius * math.cos(angle), radius * math.sin(angle)))
        _poly_spline(curve, coords, cyclic=True)
    elif kind == 'HELIX':
        turns, steps = 3, 48
        _poly_spline(curve, [(math.cos(2.0 * math.pi * turns * i / steps),
                              math.sin(2.0 * math.pi * turns * i / steps),
                              2.0 * i / steps) for i in range(steps + 1)], cyclic=False)
        return
    else:
        raise ValueError("Unknown shape {!r}".format(kind))
    curve.dimensions = '2D'


def create_shape(context, kind):
    label = dict(SHAPES)[kind]
    if kind == 'TEXT':
        data = bpy.data.curves.new(label, 'FONT')
        data.body = "Max Text"
    else:
        data = bpy.data.curves.new(label, 'CURVE')
        data.dimensions = '3D'
        build_shape(kind, data)
    return _finish(context, bpy.data.objects.new(label, data), label)


# -----------------------------------------------------------------------------
# Operators

class OBJECT_OT_mx_create(Operator):
    """Create a light, camera or helper at the 3D cursor"""
    bl_idname = "object.mx_create"
    bl_label = "Create Object"
    bl_options = {'REGISTER', 'UNDO'}

    kind: EnumProperty(name="Type", items=[(kind, label, "") for kind, label, *_rest in OBJECTS])

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    @classmethod
    def description(cls, _context, properties):
        entry = OBJECTS_BY_KIND.get(properties.kind)
        if entry is None:
            return None
        if properties.kind == 'SKYLIGHT':
            return "Light the scene with a sky-coloured world background"
        return "Create a {:s} at the 3D cursor".format(entry[0])

    def execute(self, context):
        try:
            create_object(context, self.kind)
        except ValueError as ex:
            self.report({'WARNING'}, str(ex))
            return {'CANCELLED'}
        return {'FINISHED'}


class CURVE_OT_mx_shape_add(Operator):
    """Create a Max-style shape (spline) at the 3D cursor"""
    bl_idname = "curve.mx_shape_add"
    bl_label = "Add Shape"
    bl_options = {'REGISTER', 'UNDO'}

    kind: EnumProperty(name="Shape", items=[(kind, label, "") for kind, label in SHAPES])

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def execute(self, context):
        create_shape(context, self.kind)
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Drawing

def _button_grid(layout):
    return layout.grid_flow(row_major=True, columns=2, even_columns=True, even_rows=True, align=True)


def draw_geometry(layout, _context):
    available = utils.primitives_operator_available()
    header, body = layout.panel("MXUI_create_object_type")
    header.label(text="Object Type")
    if body is None:
        return
    body.label(text="Standard Primitives")
    grid = _button_grid(body)
    grid.enabled = available
    icons = getattr(utils.primitives_module(), "ICONS", {})
    for kind, label in PRIMITIVES:
        if available:
            props = grid.operator(utils.PRIMITIVE_OPERATOR_IDNAME, text=label, icon=icons.get(kind, 'NONE'))
            props.kind = kind
        else:
            grid.label(text=label)
    if not available:
        col = body.column()
        col.active = False
        col.label(text="Enable the Max-Style Primitives add-on", icon='INFO')
        col.label(text="for live primitives.")


def draw_shapes(layout, _context):
    header, body = layout.panel("MXUI_create_object_type_shapes")
    header.label(text="Object Type")
    if body is None:
        return
    body.label(text="Splines")
    grid = _button_grid(body)
    for kind, label in SHAPES:
        grid.operator(CURVE_OT_mx_shape_add.bl_idname, text=label).kind = kind


def draw_objects(layout, _context, category):
    header, body = layout.panel("MXUI_create_object_type_" + category.lower())
    header.label(text="Object Type")
    if body is None:
        return
    for group in CATEGORY_GROUPS[category]:
        body.label(text=GROUP_LABELS[group])
        grid = _button_grid(body)
        for kind, label, _base, item_group, available in OBJECTS:
            if item_group != group:
                continue
            cell = grid.row()
            cell.enabled = available
            cell.operator(OBJECT_OT_mx_create.bl_idname, text=label).kind = kind


def draw_name_and_color(layout, context):
    state = utils.get_state(context)
    header, body = layout.panel("MXUI_create_name_color")
    header.label(text="Name and Color")
    if body is None:
        return
    row = body.row(align=True)
    row.prop(state, "next_name", text="", placeholder="Automatic")
    sub = row.row(align=True)
    sub.ui_units_x = 2.0
    sub.prop(state, "next_color", text="")


def draw(layout, context):
    state = utils.get_state(context)
    row = layout.row(align=True)
    row.prop(state, "create_category", expand=True, icon_only=True)
    category = state.create_category
    layout.label(text=_CATEGORY_LABELS[category])

    if category == 'GEOMETRY':
        draw_geometry(layout, context)
    elif category == 'SHAPES':
        draw_shapes(layout, context)
    else:
        draw_objects(layout, context, category)
    draw_name_and_color(layout, context)


classes = (
    OBJECT_OT_mx_create,
    CURVE_OT_mx_shape_add,
)
