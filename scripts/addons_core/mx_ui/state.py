# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
UI state of the command panel, kept on the window manager (``context.window_manager.mx_ui``).

Max has one command panel per application, so its state (active tab, Create category, the name and
colour for the next object, ...) is session state rather than scene data.
"""

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import PropertyGroup

COMMAND_TABS = (
    ('CREATE', "Create", "Create objects: geometry, shapes, lights, cameras, helpers", 'ADD', 0),
    ('MODIFY', "Modify", "Name, colour, modifier stack and parameters of the selected object", 'MODIFIER', 1),
    ('HIERARCHY', "Hierarchy", "Pivot and link settings", 'ORIENTATION_PARENT', 2),
    ('DISPLAY', "Display", "Hide, freeze and display properties", 'HIDE_OFF', 3),
    ('UTILITIES', "Utilities", "Reset XForm, collapse, measure, units setup", 'TOOL_SETTINGS', 4),
)

CREATE_CATEGORIES = (
    ('GEOMETRY', "Geometry", "Standard primitives", 'MESH_UVSPHERE', 0),
    ('SHAPES', "Shapes", "Splines", 'CURVE_BEZCURVE', 1),
    ('LIGHTS', "Lights", "Lights", 'LIGHT', 2),
    ('CAMERAS', "Cameras", "Cameras", 'CAMERA_DATA', 3),
    ('HELPERS', "Helpers", "Dummies and points", 'EMPTY_AXIS', 4),
)

# Hide by Category: (state property, label, `SpaceView3D.show_object_viewport_*` suffixes).
HIDE_CATEGORIES = (
    ("hide_geometry", "Geometry", ("mesh", "surf", "meta", "font", "curves", "pointcloud", "volume")),
    ("hide_shapes", "Shapes", ("curve",)),
    ("hide_lights", "Lights", ("light", "light_probe")),
    ("hide_cameras", "Cameras", ("camera",)),
    ("hide_helpers", "Helpers", ("empty", "lattice", "speaker")),
    ("hide_bones", "Bone Objects", ("armature",)),
)


def _update_hide_category(self, context):
    from . import utils
    for prop, _label, kinds in HIDE_CATEGORIES:
        show = not getattr(self, prop)
        for space in utils.iter_view3d_spaces(context, all_screens=True):
            for kind in kinds:
                setattr(space, "show_object_viewport_" + kind, show)


def _update_display_color(self, context):
    from . import utils
    for space in utils.iter_view3d_spaces(context, all_screens=True):
        space.shading.wireframe_color_type = self.wire_display_color
        space.shading.color_type = self.shaded_display_color


def _update_next_color(self, _context):
    # Set by the user, or by `wirecolor` after creating an object: either way it is now meaningful.
    if not self.next_color_initialized:
        self.next_color_initialized = True


def _update_backface_cull(self, context):
    from . import utils
    for space in utils.iter_view3d_spaces(context, all_screens=True):
        space.shading.show_backface_culling = self.backface_cull


class MXUI_State(PropertyGroup):
    command_tab: EnumProperty(
        name="Command Panel Tab",
        items=COMMAND_TABS,
        default='CREATE',
    )
    create_category: EnumProperty(
        name="Create Category",
        items=CREATE_CATEGORIES,
        default='GEOMETRY',
    )

    # Name and Color rollout of the Create tab: applied to the next new object.
    next_name: StringProperty(
        name="Name",
        description="Name for the next object you create (leave empty for an automatic name)",
    )
    next_color: FloatVectorProperty(
        name="Color",
        description="Wire colour for the next object you create",
        subtype='COLOR_GAMMA',
        size=4,
        min=0.0,
        max=1.0,
        default=(0.6, 0.6, 0.85, 1.0),
        update=_update_next_color,
    )
    next_color_initialized: BoolProperty(options={'HIDDEN'})

    # Modify tab.
    stack_base_selected: StringProperty(
        name="Base Object Selected",
        description="Object whose base entry is selected in the modifier stack",
        options={'HIDDEN'},
    )

    # Display tab.
    wire_display_color: EnumProperty(
        name="Wireframe",
        items=(
            ('OBJECT', "Object Color", "Draw wireframes in the object (wire) colour"),
            ('THEME', "Theme", "Draw wireframes in the theme colour"),
            ('RANDOM', "Random", "Random colour per object"),
        ),
        default='OBJECT',
        update=_update_display_color,
    )
    shaded_display_color: EnumProperty(
        name="Shaded",
        items=(
            ('OBJECT', "Object Color", "Shade objects with their object (wire) colour"),
            ('MATERIAL', "Material Color", "Shade objects with their material colour"),
            ('RANDOM', "Random", "Random colour per object"),
            ('SINGLE', "Single", "One colour for every object"),
        ),
        default='OBJECT',
        update=_update_display_color,
    )
    backface_cull: BoolProperty(
        name="Backface Cull",
        description="Hide the back side of faces in every viewport",
        update=_update_backface_cull,
    )

    # Utilities > Measure results (computed on demand, not every redraw).
    measure_object: StringProperty(options={'HIDDEN'})
    measure_area: FloatProperty(name="Surface Area", unit='AREA', precision=4)
    measure_volume: FloatProperty(name="Volume", unit='VOLUME', precision=4)


for _prop, _label, _kinds in HIDE_CATEGORIES:
    MXUI_State.__annotations__[_prop] = BoolProperty(
        name=_label,
        description="Hide all objects of this category in every viewport",
        update=_update_hide_category,
    )
del _prop, _label, _kinds

classes = (
    MXUI_State,
)


def register():
    bpy.types.WindowManager.mx_ui = PointerProperty(type=MXUI_State)


def unregister():
    del bpy.types.WindowManager.mx_ui
