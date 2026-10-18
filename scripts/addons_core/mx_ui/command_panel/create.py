# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Create tab: the category icons (Geometry, Shapes, Lights, Cameras, Helpers, Space Warps, Systems), the
sub-category dropdown, the "Object Type" rollout with every Max button of that sub-category
(``catalog.CREATE``), "Name and Color", and the parameters of the object just created.

Buttons run through ``object.mx_create_type``, which starts the real operator and keeps the button
highlighted like Max's creation modes: while an interactive creation runs (live primitives: click-drag in a
viewport), then as long as the new object stays selected. Buttons without an implementation are placeholders.

Shapes, lights, cameras and helpers are created here (``curve.mx_shape_add``, ``object.mx_create``) at the
3D cursor, with Max-style names ("Omni001", "Rectangle001").
"""

import math

import bpy
from bpy.props import EnumProperty, StringProperty
from bpy.types import Operator

from .. import utils
from ..placeholder import placeholder
from . import catalog, widgets

# Geometry > Standard Primitives, in Max's button order. The operator is provided by `mx_primitives`
# ('TEST_SHAPE' is our original stand-in for Max's Teapot, not the Utah teapot).
PRIMITIVES = (
    ('BOX', "Box"),
    ('CONE', "Cone"),
    ('SPHERE', "Sphere"),
    ('GEOSPHERE', "GeoSphere"),
    ('CYLINDER', "Cylinder"),
    ('TUBE', "Tube"),
    ('TORUS', "Torus"),
    ('PYRAMID', "Pyramid"),
    ('TEST_SHAPE', "Teapot"),
    ('PLANE', "Plane"),
)

# Shapes: Splines and Extended Splines.
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
    ('EGG', "Egg"),
    ('WRECTANGLE', "WRectangle"),
    ('CHANNEL', "Channel"),
    ('ANGLE', "Angle"),
    ('TEE', "Tee"),
    ('WIDE_FLANGE', "Wide Flange"),
)

# Extended Splines outlines (closed polylines, about 2 x 1.5 units).
_EXTENDED_SPLINES = {
    'CHANNEL': ((-1.0, -0.75), (1.0, -0.75), (1.0, -0.55), (-0.8, -0.55), (-0.8, 0.55), (1.0, 0.55),
                (1.0, 0.75), (-1.0, 0.75)),
    'ANGLE': ((-1.0, -0.75), (1.0, -0.75), (1.0, -0.55), (-0.8, -0.55), (-0.8, 0.75), (-1.0, 0.75)),
    'TEE': ((-1.0, 0.75), (1.0, 0.75), (1.0, 0.55), (0.1, 0.55), (0.1, -0.75), (-0.1, -0.75), (-0.1, 0.55),
            (-1.0, 0.55)),
    'WIDE_FLANGE': ((-1.0, -0.75), (1.0, -0.75), (1.0, -0.55), (0.1, -0.55), (0.1, 0.55), (1.0, 0.55),
                    (1.0, 0.75), (-1.0, 0.75), (-1.0, 0.55), (-0.1, 0.55), (-0.1, -0.55), (-1.0, -0.55)),
}

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
    elif kind == 'EGG':
        # Max's Egg: an egg outline (narrower at the top) with its inner outline.
        steps = 48
        for scale in (1.0, 0.9):
            coords = []
            for i in range(steps):
                t = 2.0 * math.pi * i / steps
                y = math.cos(t)
                coords.append((scale * 0.7 * math.sin(t) * (1.0 - 0.15 * y), scale * y))
            _poly_spline(curve, coords, cyclic=True)
    elif kind == 'WRECTANGLE':
        _poly_spline(curve, ((-1.0, -0.75), (1.0, -0.75), (1.0, 0.75), (-1.0, 0.75)), cyclic=True)
        _poly_spline(curve, ((-0.8, -0.55), (0.8, -0.55), (0.8, 0.55), (-0.8, 0.55)), cyclic=True)
    elif kind in _EXTENDED_SPLINES:
        _poly_spline(curve, _EXTENDED_SPLINES[kind], cyclic=True)
    else:
        raise ValueError("Unknown shape {!r}".format(kind))
    curve.dimensions = '2D'


def create_shape(context, kind):
    base = dict(SHAPES)[kind].replace(" ", "")
    if kind == 'TEXT':
        data = bpy.data.curves.new(base, 'FONT')
        data.body = "Max Text"
    else:
        data = bpy.data.curves.new(base, 'CURVE')
        data.dimensions = '3D'
        build_shape(kind, data)
    return _finish(context, bpy.data.objects.new(base, data), base)


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
# Create buttons: ``object.mx_create_type`` and Max's highlighted creation mode

def subcategory_prop(category):
    """Name of the state property holding the sub-category chosen for ``category``."""
    return "create_sub_" + category.lower()


def current_subcategory(state, category=None):
    cat = catalog.CATEGORY_BY_KEY[category or state.create_category]
    key = getattr(state, subcategory_prop(cat.key), None)
    return next((sub for sub in cat.subcategories if sub.key == key), cat.subcategories[0])


def button_available(button):
    """Implemented, and the add-on providing its operator (if any) is enabled."""
    if not button.implemented:
        return False
    if button.requires == catalog.PRIMITIVES:
        return utils.primitives_operator_available()
    return True


def is_highlighted(state, button, obj):
    """Max keeps the creation type's button active while creating and while the new object is selected."""
    if not button.key or state.create_active != button.key:
        return False
    return state.create_running or (obj is not None and obj.name == state.create_object)


# Modal creation operators watched by `_watch_creation` (identifiers as `Window.modal_operators` reports them).
_MODAL_CREATORS = {"MESH_OT_mx_primitive_add", "mesh.mx_primitive_add"}
_watch = {"previous": ""}


def _active_object_any_window():
    wm = bpy.context.window_manager
    for window in wm.windows:
        return window.view_layer.objects.active
    return None


def _creation_running():
    wm = bpy.context.window_manager
    return any(op.bl_idname in _MODAL_CREATORS for window in wm.windows for op in window.modal_operators)


def _watch_creation():
    """Timer: when the interactive creation ends, keep the button lit for the new object, or turn it off."""
    state = utils.get_state()
    if state is None:
        return None
    if _creation_running():
        return 0.25
    state.create_running = False
    obj = _active_object_any_window()
    if obj is not None and obj.name != _watch["previous"]:
        state.create_object = obj.name
    else:
        state.create_active = ""
    from .edit_commands import tag_redraw_panels
    tag_redraw_panels()
    return None


def run_create_button(context, button, execution='EXEC_DEFAULT'):
    """Run a Create button's operator. Returns the operator's result set; raises ValueError when impossible."""
    from .edit_commands import operator_function, push_undo
    if not button.implemented:
        raise ValueError("{:s} is not implemented yet".format(button.label))
    if not button_available(button):
        raise ValueError("{:s} needs the Max-Style Primitives add-on".format(button.label))
    obj = context.active_object
    if button.needs_selection:
        if obj is None or obj.type != 'MESH':
            raise ValueError("{:s}: select a mesh object first".format(button.label))
    elif obj is not None and obj.mode != 'OBJECT':
        with context.temp_override(**utils.object_context_override(context, obj)):
            bpy.ops.object.mode_set(mode='OBJECT')
    func = operator_function(button.operator)
    try:
        return func(execution, push_undo(), **button.props)
    except RuntimeError as ex:
        raise ValueError(str(ex).replace("Error: ", "").strip()) from ex


class OBJECT_OT_mx_create_type(Operator):
    """Create an object of this type"""
    bl_idname = "object.mx_create_type"
    bl_label = "Create"
    bl_options = {'INTERNAL'}

    entry: StringProperty(name="Object Type", options={'SKIP_SAVE'})

    @classmethod
    def description(cls, _context, properties):
        button = catalog.CREATE_BY_KEY.get(properties.entry)
        if button is None:
            return None
        if button.description:
            return button.description
        if button.requires == catalog.PRIMITIVES:
            return "{:s}: click-drag in a viewport to create it, like Max (live parameters)".format(button.label)
        return "Create a {:s} at the 3D cursor".format(button.label)

    def _run(self, context, execution):
        button = catalog.CREATE_BY_KEY.get(self.entry)
        if button is None:
            self.report({'ERROR'}, "Unknown object type {!r}".format(self.entry))
            return {'CANCELLED'}
        state = utils.get_state(context)
        previous = context.active_object
        _watch["previous"] = previous.name if previous is not None else ""
        try:
            result = run_create_button(context, button, execution)
        except ValueError as ex:
            self.report({'WARNING'}, str(ex))
            return {'CANCELLED'}
        if state is None:
            return {'FINISHED'}
        if 'RUNNING_MODAL' in result:
            state.create_active = button.key
            state.create_running = True
            state.create_object = ""
            if not bpy.app.timers.is_registered(_watch_creation):
                bpy.app.timers.register(_watch_creation, first_interval=0.25)
            return {'FINISHED'}
        if 'FINISHED' not in result:
            return {'CANCELLED'}
        obj = context.view_layer.objects.active
        state.create_active = button.key
        state.create_running = False
        state.create_object = obj.name if obj is not None else ""
        return {'FINISHED'}

    def execute(self, context):
        return self._run(context, 'EXEC_DEFAULT')

    def invoke(self, context, _event):
        button = catalog.CREATE_BY_KEY.get(self.entry)
        interactive = button is not None and button.requires == catalog.PRIMITIVES
        return self._run(context, 'INVOKE_DEFAULT' if interactive else 'EXEC_DEFAULT')


# -----------------------------------------------------------------------------
# Drawing

# Max's "Creation Method" choices for the primitives that have one.
_CREATION_METHODS = {
    'BOX': ("Cube", "Box"),
    'PLANE': ("Rectangle", "Square"),
    'PYRAMID': ("Base/Apex", "Center"),
}


def draw_create_button(layout, context, button, state):
    if not button.implemented:
        placeholder(layout, button.label)
        return
    cell = layout.row()
    cell.enabled = button_available(button)
    depress = is_highlighted(state, button, context.active_object)
    cell.operator(OBJECT_OT_mx_create_type.bl_idname, text=button.label, depress=depress).entry = button.key


def draw_object_type(layout, context, state, category, sub):
    body = widgets.rollout(layout, "create_object_type_" + category.lower(), "Object Type")
    if body is None:
        return
    row = body.row()
    row.alignment = 'CENTER'
    placeholder(row, "AutoGrid", icon='CHECKBOX_DEHLT', emboss=False)
    grid = widgets.two_columns(body)
    for button in sub.buttons:
        draw_create_button(grid, context, button, state)
    if any(button.requires == catalog.PRIMITIVES for button in sub.buttons) and \
            not utils.primitives_operator_available():
        col = body.column()
        col.active = False
        col.label(text="Enable the Max-Style Primitives add-on", icon='INFO')
        col.label(text="for live primitives.")


def draw_name_and_color(layout, context):
    state = utils.get_state(context)
    body = widgets.rollout(layout, "create_name_color", "Name and Color")
    if body is None:
        return
    obj = context.active_object
    row = body.row(align=True)
    if obj is not None and is_highlighted(state, catalog.CREATE_BY_KEY.get(state.create_active, catalog.P("")),
                                          obj):
        # Like Max: right after creation, the rollout shows (and edits) the new object.
        row.prop(obj, "name", text="")
        sub = row.row(align=True)
        sub.ui_units_x = 1.5
        sub.prop(obj, "color", text="")
        return
    row.prop(state, "next_name", text="", placeholder="Automatic")
    sub = row.row(align=True)
    sub.ui_units_x = 1.5
    sub.prop(state, "next_color", text="")


def draw_created_object(layout, context, state, sub):
    """Max shows the new object's creation rollouts while its creation type is active (and shown)."""
    obj = context.active_object
    button = catalog.CREATE_BY_KEY.get(state.create_active)
    if button is None or obj is None or not is_highlighted(state, button, obj) or button not in sub.buttons:
        return
    if button.requires == catalog.PRIMITIVES:
        kind = button.props.get("kind")
        methods = _CREATION_METHODS.get(kind, ("Edge", "Center"))
        body = widgets.rollout(layout, "create_creation_method", "Creation Method")
        if body is not None:
            row = body.row()
            for method in methods:
                placeholder(row, method, icon='RADIOBUT_OFF', emboss=False)
        body = widgets.rollout(layout, "create_keyboard_entry", "Keyboard Entry", default_closed=True)
        if body is not None:
            placeholder(body, "Create", feature="Keyboard Entry")
    if obj.name != state.create_object:
        return
    from . import modify
    if obj.type in {'MESH', 'CURVE'} and not modify.is_live_primitive(obj):
        return
    body = widgets.rollout(layout, "create_parameters", "Parameters")
    if body is not None:
        modify.draw_object_parameters(body, context, obj)


def draw(layout, context):
    state = utils.get_state(context)
    row = layout.row(align=True)
    row.scale_y = 1.1
    row.prop(state, "create_category", expand=True, icon_only=True)
    category = state.create_category
    sub = current_subcategory(state, category)
    layout.prop(state, subcategory_prop(category), text="")
    draw_object_type(layout, context, state, category, sub)
    draw_name_and_color(layout, context)
    draw_created_object(layout, context, state, sub)


def register():
    from ..state import MXUI_State
    for cat in catalog.CREATE:
        setattr(MXUI_State, subcategory_prop(cat.key), EnumProperty(
            name=cat.label + " Type",
            description="{:s} sub-category".format(cat.label),
            items=[(sub.key, sub.label, "") for sub in cat.subcategories],
        ))


def unregister():
    from ..state import MXUI_State
    for cat in catalog.CREATE:
        delattr(MXUI_State, subcategory_prop(cat.key))
    if bpy.app.timers.is_registered(_watch_creation):
        bpy.app.timers.unregister(_watch_creation)


classes = (
    OBJECT_OT_mx_create,
    CURVE_OT_mx_shape_add,
    OBJECT_OT_mx_create_type,
)
