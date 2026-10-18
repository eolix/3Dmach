# SPDX-FileCopyrightText: 2026 3Dmach Authors
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
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import PropertyGroup

# Max's command panel tabs, in Max's order (shown as an icon row).
COMMAND_TABS = (
    ('CREATE', "Create", "Create objects: geometry, shapes, lights, cameras, helpers, space warps, systems",
     'ADD', 0),
    ('MODIFY', "Modify", "Name, colour, modifier stack and parameters of the selected object", 'MODIFIER', 1),
    ('HIERARCHY', "Hierarchy", "Pivot, IK and link settings", 'OUTLINER', 2),
    ('MOTION', "Motion", "Controllers, keys and motion paths", 'ANIM', 3),
    ('DISPLAY', "Display", "Display colour, hide, freeze and display properties", 'HIDE_OFF', 4),
    ('UTILITIES', "Utilities", "Collapse, measure, Reset XForm and other utilities", 'TOOL_SETTINGS', 5),
)

# Create tab categories, in Max's order (an icon row under the tabs).
CREATE_CATEGORIES = (
    ('GEOMETRY', "Geometry", "Primitives, compound objects and other geometry", 'MESH_UVSPHERE', 0),
    ('SHAPES', "Shapes", "Splines and other shapes", 'CURVE_BEZCURVE', 1),
    ('LIGHTS', "Lights", "Photometric and standard lights", 'LIGHT', 2),
    ('CAMERAS', "Cameras", "Physical, target and free cameras", 'CAMERA_DATA', 3),
    ('HELPERS', "Helpers", "Dummies, points and other helpers", 'EMPTY_AXIS', 4),
    ('SPACE_WARPS', "Space Warps", "Forces, deflectors and deformers", 'FORCE_WIND', 5),
    ('SYSTEMS', "Systems", "Bones, arrays and daylight systems", 'PREFERENCES', 6),
)

HIERARCHY_MODES = (
    ('PIVOT', "Pivot", "Adjust the pivot (object origin) and transforms"),
    ('IK', "IK", "Inverse kinematics settings"),
    ('LINK_INFO', "Link Info", "Transform locks and inheritance"),
)

MOTION_MODES = (
    ('PARAMETERS', "Parameters", "Controllers and keys of the selected object"),
    ('MOTION_PATHS', "Motion Paths", "Edit the trajectory of the selected object"),
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

    # Create tab: the creation type whose button is highlighted, like Max's active creation mode.
    create_active: StringProperty(name="Active Creation Type", options={'HIDDEN'})
    create_object: StringProperty(name="Created Object", options={'HIDDEN'})
    create_running: BoolProperty(name="Creating", options={'HIDDEN'})

    # Modify tab.
    stack_base_selected: StringProperty(
        name="Base Object Selected",
        description="Object whose base entry is selected in the modifier stack",
        options={'HIDDEN'},
    )
    stack_expanded: BoolProperty(
        name="Show Sub-Object Levels",
        description="Show the sub-object levels of the base object in the stack",
        default=True,
    )
    pin_object: StringProperty(
        name="Pinned Object",
        description="Object whose stack stays in the Modify tab while other objects are selected",
        options={'HIDDEN'},
    )
    edit_command_active: StringProperty(name="Active Edit Command", options={'HIDDEN'})
    weld_threshold: FloatProperty(
        name="Weld Threshold",
        description="Distance below which Weld merges selected vertices",
        default=0.001, min=0.0, soft_max=1.0, unit='LENGTH', precision=4,
    )
    material_id: IntProperty(
        name="Set ID",
        description="Material ID (material slot number) for the selected polygons",
        default=1, min=1, max=32767,
    )
    select_material_id: IntProperty(
        name="Select ID",
        description="Material ID (material slot number) to select polygons by",
        default=1, min=1, max=32767,
    )
    select_id_clear: BoolProperty(
        name="Clear Selection",
        description="Deselect the other polygons when selecting by ID",
        default=True,
    )
    auto_smooth_angle: FloatProperty(
        name="Auto Smooth Threshold",
        description="Polygons meeting at a smaller angle are smoothed together",
        default=0.785398, min=0.0, max=3.141593, subtype='ANGLE',
    )

    # Hierarchy and Motion tabs.
    hierarchy_mode: EnumProperty(name="Hierarchy Mode", items=HIERARCHY_MODES, default='PIVOT')
    affect_object_only: BoolProperty(
        name="Affect Object Only",
        description="The alignment buttons move the object onto its pivot instead of the pivot onto the object "
        "(moving the object alone with the transform tools is not implemented yet)",
    )
    motion_mode: EnumProperty(name="Motion Mode", items=MOTION_MODES, default='PARAMETERS')

    # Utilities tab: the utility whose rollout is open below the Utilities rollout.
    utility_active: StringProperty(name="Active Utility", options={'HIDDEN'})

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
