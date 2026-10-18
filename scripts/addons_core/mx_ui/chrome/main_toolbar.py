# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Max's main toolbar, drawn by :func:`draw_main_toolbar` into a header (the Max layout hosts it in a header-only
strip below the menu bar).

From left to right: Undo/Redo | Select and Link, Unlink Selection, Bind to Space Warp | Selection Filter |
Select Object, Select by Name, Selection Region flyout, Window/Crossing | Select and Move, Rotate, Scale
flyout, Place flyout | Reference Coordinate System | Pivot flyout | Select and Manipulate | Keyboard Shortcut
Override | Snaps flyout, Angle Snap, Percent Snap, Spinner Snap | Edit Named Selection Sets, Named Selection
Sets | Mirror, Align flyout | Toggle Scene Explorer, Layer Explorer, Ribbon | Curve Editor, Schematic View,
Material Editor flyout | Render Setup, Rendered Frame Window, Render flyout.

Flyouts work like Max's: click runs the button shown, press and hold opens the other variants
(``UILayout.operator_menu_hold``). The variant shown is the active one (tool, pivot) or the last one picked.

Session state lives on ``WindowManager.mx_ui`` (added to ``state.MXUI_State`` while registered):
``selection_filter`` (Max's Selection Filter, for the selection operators to use later), ``select_crossing``
(Window/Crossing) and ``ref_coord_sys`` (Max's Reference Coordinate System, mapped onto Blender's transform
orientation).
"""

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy.types import Menu, Operator

from .. import state
from .. import utils
from ..placeholder import placeholder
from . import menu_ops


# -----------------------------------------------------------------------------
# Session state

SELECTION_FILTERS = (
    ('ALL', "All", "Select any kind of object"),
    ('GEOMETRY', "Geometry", "Select geometry only"),
    ('SHAPES', "Shapes", "Select shapes (splines) only"),
    ('LIGHTS', "Lights", "Select lights only"),
    ('CAMERAS', "Cameras", "Select cameras only"),
    ('HELPERS', "Helpers", "Select helpers only"),
    ('WARPS', "Warps", "Select space warps only"),
    ('COMBOS', "Combos...", "Combination of categories"),
    ('BONE', "Bone", "Select bones only"),
    ('IK_CHAIN', "IK Chain Object", "Select IK chains only"),
    ('POINT', "Point", "Select point helpers only"),
    ('CAT_BONE', "CAT Bone", "Select character bones only"),
)

# Max's Reference Coordinate System → Blender transform orientation. "Screen" is Blender's View orientation too;
# Grid and Pick have no equivalent yet (choosing them leaves the orientation unchanged).
COORD_SYSTEMS = (
    ('VIEW', "View", "Viewport axes in orthographic views, World in perspective views", 'VIEW'),
    ('SCREEN', "Screen", "Axes of the active viewport's screen", 'VIEW'),
    ('WORLD', "World", "World coordinate system", 'GLOBAL'),
    ('PARENT', "Parent", "Coordinate system of the object's parent", 'PARENT'),
    ('LOCAL', "Local", "The object's own coordinate system", 'LOCAL'),
    ('GIMBAL', "Gimbal", "Euler rotation axes", 'GIMBAL'),
    ('GRID', "Grid", "Coordinate system of the active grid (not implemented yet)", None),
    ('WORKING', "Working", "Working pivot (Blender's 3D cursor)", 'CURSOR'),
    ('LOCAL_ALIGNED', "Local Aligned", "Aligned to the selected sub-objects (normal orientation)", 'NORMAL'),
    ('PICK', "Pick", "Coordinate system of another object (Blender custom orientations)", None),
)
_COORD_TO_BLENDER = {key: blender for key, _label, _description, blender in COORD_SYSTEMS}
_COORD_FROM_BLENDER = {
    'VIEW': 'VIEW', 'GLOBAL': 'WORLD', 'PARENT': 'PARENT', 'LOCAL': 'LOCAL', 'GIMBAL': 'GIMBAL',
    'CURSOR': 'WORKING', 'NORMAL': 'LOCAL_ALIGNED',
}
_COORD_INDEX = {item[0]: index for index, item in enumerate(COORD_SYSTEMS)}


def coord_system_from_blender(orientation):
    """Max coordinate system shown for a Blender transform orientation (custom orientations show as Pick)."""
    return _COORD_FROM_BLENDER.get(orientation, 'PICK')


def coord_system_to_blender(coord_system):
    """Blender transform orientation for a Max coordinate system, or None when there is no equivalent."""
    return _COORD_TO_BLENDER[coord_system]


def _get_coord_system(_self):
    scene = bpy.context.scene
    if scene is None:
        return 0
    return _COORD_INDEX[coord_system_from_blender(scene.transform_orientation_slots[0].type)]


def _set_coord_system(_self, value):
    scene = bpy.context.scene
    blender = coord_system_to_blender(COORD_SYSTEMS[value][0])
    if scene is not None and blender is not None:
        scene.transform_orientation_slots[0].type = blender


_STATE_PROPS = {
    "selection_filter": EnumProperty(
        name="Selection Filter",
        description="Kinds of objects selection picks (Max's Selection Filter)",
        items=SELECTION_FILTERS,
        default='ALL',
    ),
    "select_crossing": BoolProperty(
        name="Window/Crossing",
        description=(
            "Window: region selection picks objects completely inside the region. "
            "Crossing: it also picks objects crossing the region border"
        ),
        default=True,
    ),
    "named_selection_set": StringProperty(
        name="Named Selection Sets",
        description="Named selection set (not implemented yet)",
    ),
    "ref_coord_sys": EnumProperty(
        name="Reference Coordinate System",
        description="Coordinate system used for transforms",
        items=[(key, label, description, index) for index, (key, label, description, _b) in enumerate(COORD_SYSTEMS)],
        get=_get_coord_system,
        set=_set_coord_system,
    ),
}


# -----------------------------------------------------------------------------
# Flyouts

class Variant:
    """
    One button of a flyout. ``action`` is one of: ``('TOOL', tool_id)``, ``('SET', data_path, value, *aliases)``
    (an enum in the context; the variant is also shown as active for the ``aliases`` values),
    ``('OP', idname, props)``, ``('EDITOR', editor)`` or ``('PH',)`` (not implemented yet).
    """
    __slots__ = ("key", "text", "icon", "action")

    def __init__(self, key, text, icon, action):
        self.key = key
        self.text = text
        self.icon = icon
        self.action = action


_PH = ('PH',)

FLYOUTS = {
    'SELECT_REGION': (
        Variant('RECTANGULAR', "Rectangular Selection Region", 'SELECT_SET', ('TOOL', "builtin.select_box")),
        Variant('CIRCULAR', "Circular Selection Region", 'MESH_CIRCLE', _PH),
        Variant('FENCE', "Fence Selection Region", 'IPO_LINEAR', _PH),
        Variant('LASSO', "Lasso Selection Region", 'GP_SELECT_STROKES', ('TOOL', "builtin.select_lasso")),
        Variant('PAINT', "Paint Selection Region", 'BRUSHES_ALL', ('TOOL', "builtin.select_circle")),
    ),
    'SCALE': (
        Variant('UNIFORM', "Select and Uniform Scale", 'FULLSCREEN_ENTER', ('TOOL', "builtin.scale")),
        Variant('NON_UNIFORM', "Select and Non-uniform Scale", 'MOD_LENGTH', ('TOOL', "builtin.scale")),
        Variant('SQUASH', "Select and Squash", 'FULLSCREEN_EXIT', _PH),
    ),
    'PLACE': (
        Variant('PLACE', "Select and Place", 'ORIENTATION_NORMAL', _PH),
        Variant('ROTATE', "Select and Rotate (Place)", 'CON_ROTLIKE', _PH),
    ),
    'PIVOT': (
        Variant('PIVOT', "Use Pivot Point Center", 'PIVOT_INDIVIDUAL',
                ('SET', "tool_settings.transform_pivot_point", 'INDIVIDUAL_ORIGINS')),
        Variant('SELECTION', "Use Selection Center", 'PIVOT_BOUNDBOX',
                ('SET', "tool_settings.transform_pivot_point", 'BOUNDING_BOX_CENTER', 'MEDIAN_POINT')),
        Variant('TRANSFORM', "Use Transform Coordinate Center", 'PIVOT_CURSOR',
                ('SET', "tool_settings.transform_pivot_point", 'CURSOR')),
    ),
    'SNAP': (
        Variant('3D', "3D Snap", 'SNAP_ON', ('OP', "mx_ui.snap_toggle", {"kind": 'SNAP'})),
        Variant('2_5D', "2.5D Snap", 'SNAP_FACE', _PH),
        Variant('2D', "2D Snap", 'SNAP_GRID', _PH),
    ),
    'ALIGN': (
        Variant('ALIGN', "Align", 'ALIGN_CENTER', ('OP', "object.align", {"relative_to": 'OPT_4'})),
        Variant('QUICK', "Quick Align", 'ALIGN_FLUSH', ('OP', "view3d.snap_selected_to_active", {})),
        Variant('NORMAL', "Normal Align", 'NORMALS_FACE', _PH),
        Variant('HIGHLIGHT', "Place Highlight", 'LIGHT', _PH),
        Variant('CAMERA', "Align Camera", 'CAMERA_DATA', _PH),
        Variant('VIEW', "Align to View", 'VIEW_PERSPECTIVE', _PH),
    ),
    'MATERIAL_EDITOR': (
        Variant('COMPACT', "Compact Material Editor", 'MATERIAL', ('EDITOR', 'MATERIAL')),
        Variant('SLATE', "Slate Material Editor", 'NODE_MATERIAL', ('EDITOR', 'MATERIAL')),
    ),
    'RENDER': (
        Variant('PRODUCTION', "Render Production", 'RENDER_STILL', ('OP', "render.render", {"use_viewport": True})),
        Variant('ITERATIVE', "Render Iterative", 'FILE_REFRESH', ('OP', "render.render", {"use_viewport": True})),
        Variant('ACTIVESHADE', "ActiveShade", 'SHADING_RENDERED', ('OP', "mx_ui.active_shade", {})),
    ),
}

# Flyouts showing the active variant (tool, pivot) rather than the last one picked.
_SHOW_ACTIVE = {'SELECT_REGION', 'SCALE', 'PIVOT'}

# Last variant picked per flyout (session only, like Max's flyouts).
_chosen = {}


def _variant(flyout, key):
    return next((v for v in FLYOUTS[flyout] if v.key == key), None)


def active_tool_id(context):
    """The idname of the active 3D viewport tool, or None."""
    workspace = getattr(context, "workspace", None)
    if workspace is None:
        return None
    try:
        tool = workspace.tools.from_space_view3d_mode(context.mode, create=False)
    except (TypeError, ValueError, AttributeError):
        return None
    return tool.idname if tool is not None else None


def _resolve(context, data_path):
    owner = context
    for part in data_path.split("."):
        owner = getattr(owner, part, None)
        if owner is None:
            return None
    return owner


def variant_active(context, variant, tool_id=None):
    action = variant.action
    if action[0] == 'TOOL':
        return (tool_id or active_tool_id(context)) == action[1]
    if action[0] == 'SET':
        return _resolve(context, action[1]) in action[2:]
    return False


def shown_variant(context, flyout):
    """The variant a flyout button shows: the active one, else the last one picked, else the first."""
    variants = FLYOUTS[flyout]
    chosen = _variant(flyout, _chosen.get(flyout, "")) or variants[0]
    if flyout in _SHOW_ACTIVE:
        tool_id = active_tool_id(context)
        if variant_active(context, chosen, tool_id):
            return chosen
        for variant in variants:
            if variant_active(context, variant, tool_id):
                return variant
    return chosen


def _action_available(action):
    if action[0] == 'OP':
        return menu_ops.has_operator(action[1])
    return True


def _draw_action(layout, action, text, icon, menu=None, depress=False, feature=None):
    """Draw a button running ``action`` (with a press-and-hold ``menu`` when given)."""
    def button(idname):
        if menu:
            return layout.operator_menu_hold(idname, text=text, icon=icon, menu=menu, depress=depress)
        return layout.operator(idname, text=text, icon=icon, depress=depress)

    kind = action[0]
    if kind == 'TOOL':
        op = button("wm.tool_set_by_id")
        op.name = action[1]
        op.space_type = 'VIEW_3D'
    elif kind == 'SET':
        op = button("wm.context_set_enum")
        op.data_path = action[1]
        op.value = action[2]
    elif kind == 'OP' and _action_available(action):
        op = button(action[1])
        for key, value in action[2].items():
            setattr(op, key, value)
    elif kind == 'EDITOR' and not menu:
        op = menu_ops.open_editor(layout, action[1], text, icon=icon, depress=depress)
    elif kind == 'EDITOR':
        op = button(menu_ops.MXUI_OT_open_editor_window.bl_idname)
        op.editor = action[1]
    else:
        op = button("mx_ui.placeholder")
        op.feature = feature or text or "This feature"
    return op


class MXUI_OT_toolbar_flyout(Operator):
    bl_idname = "mx_ui.toolbar_flyout"
    bl_label = "Flyout"
    bl_options = {'INTERNAL'}

    flyout: StringProperty(name="Flyout", options={'SKIP_SAVE'})
    variant: StringProperty(name="Variant", options={'SKIP_SAVE'})

    @classmethod
    def description(cls, _context, properties):
        variant = _variant(properties.flyout, properties.variant) if properties.flyout in FLYOUTS else None
        if variant is None:
            return None
        if variant.action[0] == 'PH':
            return "{:s}: not implemented yet".format(variant.text)
        return variant.text

    def execute(self, context):
        variant = _variant(self.flyout, self.variant) if self.flyout in FLYOUTS else None
        if variant is None:
            return {'CANCELLED'}
        _chosen[self.flyout] = variant.key
        action = variant.action
        kind = action[0]
        try:
            if kind == 'TOOL':
                bpy.ops.wm.tool_set_by_id(name=action[1], space_type='VIEW_3D')
            elif kind == 'SET':
                owner_path, _, prop = action[1].rpartition(".")
                setattr(_resolve(context, owner_path), prop, action[2])
            elif kind == 'OP' and _action_available(action):
                category, _, name = action[1].partition(".")
                getattr(getattr(bpy.ops, category), name)('INVOKE_DEFAULT', **action[2])
            elif kind == 'EDITOR':
                if menu_ops.has_operator("mx_keymap.open_editor") and action[1] in {'MATERIAL', 'RENDER_SETUP'}:
                    bpy.ops.mx_keymap.open_editor(editor={'MATERIAL': 'MATERIAL'}.get(action[1], 'RENDER'))
                else:
                    bpy.ops.mx_ui.open_editor_window(editor=action[1])
            else:
                self.report({'INFO'}, "{:s} is not implemented yet".format(variant.text))
        except RuntimeError as ex:
            self.report({'WARNING'}, str(ex).strip())
            return {'CANCELLED'}
        for area in context.screen.areas if context.screen else ():
            area.tag_redraw()
        return {'FINISHED'}


def _flyout_menu_idname(flyout):
    return "TOPBAR_MT_mx_flyout_" + flyout.lower()


def _make_flyout_menu(flyout):
    idname = _flyout_menu_idname(flyout)

    def draw(self, context):
        layout = self.layout
        tool_id = active_tool_id(context)
        for variant in FLYOUTS[flyout]:
            active = variant_active(context, variant, tool_id)
            op = layout.operator(MXUI_OT_toolbar_flyout.bl_idname, text=variant.text, icon=variant.icon,
                                 depress=active)
            op.flyout = flyout
            op.variant = variant.key

    return type(idname, (Menu,), {"bl_idname": idname, "bl_label": flyout.replace("_", " ").title(), "draw": draw})


def draw_flyout(layout, context, flyout, depress=None):
    """A flyout button: the shown variant, with the others on press and hold."""
    variant = shown_variant(context, flyout)
    if depress is None:
        depress = flyout != 'SELECT_REGION' and variant_active(context, variant)
    return _draw_action(layout, variant.action, "", variant.icon, menu=_flyout_menu_idname(flyout),
                        depress=depress, feature=variant.text)


# -----------------------------------------------------------------------------
# Snaps

SNAP_KINDS = (
    ('SNAP', "Snaps Toggle", "Snapping for moves", "use_snap_translate"),
    ('ANGLE', "Angle Snap Toggle", "Angle increment snapping for rotations", "use_snap_rotate"),
    ('PERCENT', "Percent Snap Toggle", "Percentage increment snapping for scaling", "use_snap_scale"),
)
_SNAP_AFFECT = {key: prop for key, _label, _description, prop in SNAP_KINDS}


def snap_enabled(tool_settings, kind):
    return bool(tool_settings.use_snap and getattr(tool_settings, _SNAP_AFFECT[kind]))


def toggle_snap(tool_settings, kind):
    """
    Max's independent snap toggles on top of Blender's single snapping switch with per-transform "affect"
    options. Returns the new state of ``kind``.
    """
    states = {key: snap_enabled(tool_settings, key) for key in _SNAP_AFFECT}
    states[kind] = not states[kind]
    any_on = any(states.values())
    for key, prop in _SNAP_AFFECT.items():
        setattr(tool_settings, prop, states[key] or (key == 'SNAP' and not any_on))
    tool_settings.use_snap = any_on
    return states[kind]


class MXUI_OT_snap_toggle(Operator):
    bl_idname = "mx_ui.snap_toggle"
    bl_label = "Snap Toggle"

    kind: EnumProperty(name="Snap", items=[item[:3] for item in SNAP_KINDS])

    @classmethod
    def description(cls, _context, properties):
        return next(description for key, _label, description, _prop in SNAP_KINDS if key == properties.kind)

    @classmethod
    def poll(cls, context):
        return context.scene is not None

    def execute(self, context):
        on = toggle_snap(context.scene.tool_settings, self.kind)
        label = next(label for key, label, _description, _prop in SNAP_KINDS if key == self.kind)
        self.report({'INFO'}, "{:s}: {:s}".format(label.replace(" Toggle", ""), "on" if on else "off"))
        return {'FINISHED'}


def _draw_snap(layout, tool_settings, kind, icon):
    op = layout.operator(MXUI_OT_snap_toggle.bl_idname, text="", icon=icon,
                         depress=snap_enabled(tool_settings, kind))
    op.kind = kind


# -----------------------------------------------------------------------------
# Named selection sets (placeholder dropdown)

class TOPBAR_MT_mx_named_selection_sets(Menu):
    bl_idname = "TOPBAR_MT_mx_named_selection_sets"
    bl_label = "Create Selection Set"

    def draw(self, _context):
        placeholder(self.layout, "Create Selection Set")


# -----------------------------------------------------------------------------
# The toolbar

def _group(layout):
    layout.separator(factor=0.6)
    return layout.row(align=True)


def draw_main_toolbar(layout, context):
    """Draw Max's main toolbar into ``layout`` (one header row)."""
    wm_state = utils.get_state(context)
    scene = context.scene
    tool_settings = scene.tool_settings
    tool_id = active_tool_id(context)

    row = layout.row(align=True)
    row.operator_menu_hold("ed.undo", text="", icon='LOOP_BACK', menu="TOPBAR_MT_undo_history")
    row.operator("ed.redo", text="", icon='LOOP_FORWARDS')

    row = _group(layout)
    row.operator("object.parent_set", text="", icon='LINKED').keep_transform = True
    row.operator("object.parent_clear", text="", icon='UNLINKED').type = 'CLEAR_KEEP_TRANSFORM'
    placeholder(row, "", icon='FORCE_FORCE', feature="Bind to Space Warp")

    row = _group(layout)
    sub = row.row(align=True)
    sub.ui_units_x = 3.5
    if wm_state is not None and hasattr(wm_state, "selection_filter"):
        sub.prop(wm_state, "selection_filter", text="")

    row = _group(layout)
    selecting = tool_id in {"builtin.select_box", "builtin.select_circle", "builtin.select_lasso", "builtin.select"}
    region = shown_variant(context, 'SELECT_REGION')
    region_tool = region.action[1] if region.action[0] == 'TOOL' else "builtin.select_box"
    op = row.operator("wm.tool_set_by_id", text="", icon='RESTRICT_SELECT_OFF', depress=selecting)
    op.name = region_tool
    op.space_type = 'VIEW_3D'
    if menu_ops.has_operator("mx_keymap.select_by_name"):
        row.operator("mx_keymap.select_by_name", text="", icon='SORTALPHA')
    else:
        row.operator("object.select_pattern", text="", icon='SORTALPHA')
    draw_flyout(row, context, 'SELECT_REGION')
    if wm_state is not None and hasattr(wm_state, "select_crossing"):
        row.prop(wm_state, "select_crossing", text="", toggle=True,
                 icon='SELECT_INTERSECT' if wm_state.select_crossing else 'SELECT_SET')

    row = _group(layout)
    for tool, icon in (("builtin.move", 'EMPTY_ARROWS'), ("builtin.rotate", 'ORIENTATION_GIMBAL')):
        op = row.operator("wm.tool_set_by_id", text="", icon=icon, depress=tool_id == tool)
        op.name = tool
        op.space_type = 'VIEW_3D'
    draw_flyout(row, context, 'SCALE')
    draw_flyout(row, context, 'PLACE')

    row = _group(layout)
    sub = row.row(align=True)
    sub.ui_units_x = 4.0
    if wm_state is not None and hasattr(wm_state, "ref_coord_sys"):
        sub.prop(wm_state, "ref_coord_sys", text="")
    draw_flyout(row, context, 'PIVOT')

    row = _group(layout)
    placeholder(row, "", icon='GIZMO', feature="Select and Manipulate")
    placeholder(row, "", icon='KEY_EMPTY1', feature="Keyboard Shortcut Override Toggle")

    row = _group(layout)
    snap = shown_variant(context, 'SNAP')
    if snap.action[0] == 'PH':
        draw_flyout(row, context, 'SNAP', depress=False)
    else:
        op = row.operator_menu_hold(MXUI_OT_snap_toggle.bl_idname, text="", icon=snap.icon,
                                    menu=_flyout_menu_idname('SNAP'), depress=snap_enabled(tool_settings, 'SNAP'))
        op.kind = 'SNAP'
    _draw_snap(row, tool_settings, 'ANGLE', 'DRIVER_ROTATIONAL_DIFFERENCE')
    _draw_snap(row, tool_settings, 'PERCENT', 'SNAP_INCREMENT')
    placeholder(row, "", icon='ARROW_LEFTRIGHT', feature="Spinner Snap Toggle")

    row = _group(layout)
    placeholder(row, "", icon='BOOKMARKS', feature="Edit Named Selection Sets")
    sub = row.row(align=True)
    sub.ui_units_x = 7.5
    if wm_state is not None and hasattr(wm_state, "named_selection_set"):
        sub.prop(wm_state, "named_selection_set", text="", placeholder="Create Selection Set")
    sub.menu(TOPBAR_MT_mx_named_selection_sets.bl_idname, text="", icon='DOWNARROW_HLT')

    row = _group(layout)
    if menu_ops.has_operator("object.mx_mirror"):
        row.operator("object.mx_mirror", text="", icon='MOD_MIRROR')
    draw_flyout(row, context, 'ALIGN')

    row = _group(layout)
    placeholder(row, "", icon='OUTLINER', feature="Toggle Scene Explorer")
    placeholder(row, "", icon='RENDERLAYERS', feature="Toggle Layer Explorer")
    placeholder(row, "", icon='TOPBAR', feature="Toggle Ribbon")

    row = _group(layout)
    menu_ops.open_editor(row, 'CURVE_EDITOR', "", icon='GRAPH')
    placeholder(row, "", icon='NODETREE', feature="Schematic View")
    draw_flyout(row, context, 'MATERIAL_EDITOR')

    row = _group(layout)
    menu_ops.open_editor(row, 'RENDER_SETUP', "", icon='SCENE')
    row.operator("render.view_show", text="", icon='RENDER_RESULT')
    draw_flyout(row, context, 'RENDER')


classes = (
    MXUI_OT_toolbar_flyout,
    MXUI_OT_snap_toggle,
    TOPBAR_MT_mx_named_selection_sets,
    *(_make_flyout_menu(flyout) for flyout in FLYOUTS),
)


def register():
    for name, prop in _STATE_PROPS.items():
        setattr(state.MXUI_State, name, prop)


def unregister():
    for name in _STATE_PROPS:
        try:
            delattr(state.MXUI_State, name)
        except AttributeError:
            pass
    _chosen.clear()
