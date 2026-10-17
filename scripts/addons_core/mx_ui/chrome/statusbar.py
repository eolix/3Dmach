# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Max's status line and animation / navigation controls: the two rows at the bottom of the window.

Row 1 is a strip (an Info editor shrunk to its header, ``strips.py``) under the Timeline, row 2 Blender's status bar
(``STATUSBAR_HT_header.draw``, replaced while the window shows the Max Layout with the chrome on):

    | mini-listener      | None Selected          | iso lock | abs X [ ] Y [ ] Z [ ] | Grid = 10.0 | ...
    | listener result    | Click and drag to ...  | (reports, jobs)  | Adaptive Degr. | Add Time Tag | ...

    ... | Auto Key [Selected] | |< <| > |> >| | zoom, zoom all, extents, extents all |
    ... | Set Key  Key Filters | key mode, frame, time configuration | fov, pan, orbit, maximize |
"""

import bpy
from bpy.types import Operator, Panel

from ..placeholder import placeholder
from . import _areas, frame_state, navigation

# Widths (UI units) of the columns shared by both rows, so they line up.
LISTENER_WIDTH = 9.0
STATUS_WIDTH = 11.0
COORD_WIDTH = 5.0

TOOL_PROMPTS = {
    "builtin.select": "Click to select objects",
    "builtin.select_box": "Click or click-and-drag to select objects",
    "builtin.select_circle": "Click and drag to select objects with a circle",
    "builtin.select_lasso": "Click and drag to select objects with a lasso",
    "builtin.move": "Click and drag to select and move objects",
    "builtin.rotate": "Click and drag to select and rotate objects",
    "builtin.scale": "Click and drag to select and scale objects",
    "builtin.scale_cage": "Click and drag to select and scale objects",
    "builtin.transform": "Click and drag to select and transform objects",
    "builtin.cursor": "Click to place the 3D cursor",
    "builtin.annotate": "Click and drag to annotate",
    "builtin.measure": "Click and drag to measure",
}


def selection_text(context):
    """Max's selection count: "None Selected", "1 Object Selected", "3 Objects Selected"."""
    view_layer = getattr(context, "view_layer", None)
    if view_layer is None:
        return "None Selected"
    count = sum(1 for obj in view_layer.objects if obj.select_get(view_layer=view_layer))
    if count == 0:
        return "None Selected"
    if count == 1:
        return "1 Object Selected"
    return "{:d} Objects Selected".format(count)


def prompt_text(context):
    """The prompt line: what a click in a viewport does now."""
    state = frame_state.get(context)
    if state is not None and state.nav_mode:
        return navigation.MODE_PROMPTS.get(state.nav_mode, "")
    try:
        tool = context.workspace.tools.from_space_view3d_mode(context.mode, create=False)
    except (AttributeError, TypeError, RuntimeError):
        tool = None
    idname = tool.idname if tool is not None else ""
    if context.mode != 'OBJECT':
        text = TOOL_PROMPTS.get(idname, "Click or click-and-drag to select sub-objects")
        return text.replace("objects", "sub-objects")
    return TOOL_PROMPTS.get(idname, "Click or click-and-drag to select objects")


def grid_text(context):
    """"Grid = 10.0" with the target viewport's grid spacing, in scene units."""
    area, _region = navigation.target_viewport(context)
    scale = area.spaces.active.overlay.grid_scale if area is not None else 1.0
    scene = context.scene
    try:
        value = bpy.utils.units.to_string(
            scene.unit_settings.system, 'LENGTH', scale * scene.unit_settings.scale_length, precision=3,
            split_unit=False, compatible_unit=False)
    except (ValueError, AttributeError):
        value = "{:g}".format(scale)
    return "Grid = " + value


class MXUI_OT_listener_run(Operator):
    """Run a line of Python (the mini-listener)"""
    bl_idname = "mx_ui.listener_run"
    bl_label = "Run Listener Line"
    bl_options = {'INTERNAL'}

    code: bpy.props.StringProperty(name="Code")

    def execute(self, context):
        state = frame_state.get(context)
        ok, text = frame_state.run_listener(self.code, context)
        if state is not None:
            state.listener_result = text
            state.listener_ok = ok
        if not ok:
            self.report({'WARNING'}, text)
        return {'FINISHED'}


class DOPESHEET_PT_mx_time_configuration(Panel):
    bl_space_type = 'DOPESHEET_EDITOR'
    bl_region_type = 'HEADER'
    bl_label = "Time Configuration"
    bl_ui_units_x = 12

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        layout.use_property_split = True
        layout.use_property_decorate = False
        col = layout.column(heading="Frame Rate")
        col.prop(scene.render, "fps", text="FPS")
        col.prop(scene.render, "fps_base", text="Base")
        col = layout.column(heading="Time Display")
        col.prop(context.preferences.view, "timecode_style", text="Timecode")
        col = layout.column(heading="Playback")
        col.prop(scene, "sync_mode", text="Sync")
        col.prop(scene, "use_audio_scrub", text="Scrubbing Audio")
        col = layout.column(align=True)
        col.label(text="Animation")
        col.prop(scene, "frame_start", text="Start Time")
        col.prop(scene, "frame_end", text="End Time")
        col.prop(scene, "frame_step", text="Frame Step")
        col.prop(scene, "frame_current", text="Current Time")


def _fixed(layout, units, align=True):
    sub = layout.row(align=align)
    sub.ui_units_x = units
    return sub


def draw_row1(layout, context):
    """Row 1: listener input, selection count, locks, transform type-in, grid; Auto Key; playback; zoom."""
    state = frame_state.get(context)
    scene = context.scene
    tool_settings = scene.tool_settings
    wm = context.window_manager

    sub = _fixed(layout, LISTENER_WIDTH)
    if state is not None:
        sub.prop(state, "listener_input", text="", icon='CONSOLE', placeholder="Python mini-listener")
    sub = _fixed(layout, STATUS_WIDTH)
    sub.label(text=selection_text(context))

    row = layout.row(align=True)
    row.operator(navigation.MXUI_OT_viewport_nav.bl_idname, text="", icon='HIDE_OFF',
                 depress=navigation.isolate_active(context)).action = 'ISOLATE'
    if hasattr(wm, "mx_keymap_selection_locked"):
        locked = wm.mx_keymap_selection_locked
        row.prop(wm, "mx_keymap_selection_locked", text="", icon='LOCKED' if locked else 'UNLOCKED')
    else:
        placeholder(row, "", icon='UNLOCKED', feature="Selection Lock Toggle")

    row = layout.row(align=True)
    if state is not None:
        offset = state.coord_offset
        row.prop(state, "coord_offset", text="", icon='DRIVER_DISTANCE' if offset else 'EMPTY_ARROWS')
        kind = frame_state.transform_kind(context)
        fields = layout.row(align=False)
        fields.active = bool(frame_state.transform_targets(context))
        for name, letter in zip(frame_state.coord_property_names(kind), "XYZ"):
            cell = _fixed(fields, COORD_WIDTH)
            cell.prop(state, name, text=letter)

    layout.label(text=grid_text(context))
    layout.separator_spacer()

    row = layout.row(align=True)
    row.prop(tool_settings, "use_keyframe_insert_auto", text="Auto Key", toggle=True)
    placeholder(row, "Selected", icon='DOWNARROW_HLT', feature="Key Set (Selected)")

    row = layout.row(align=True)
    row.operator("screen.frame_jump", text="", icon='REW').end = False
    row.operator("screen.keyframe_jump", text="", icon='PREV_KEYFRAME').next = False
    if context.screen is not None and context.screen.is_animation_playing:
        row.operator("screen.animation_cancel", text="", icon='PAUSE').restore_frame = False
    else:
        row.operator("screen.animation_play", text="", icon='PLAY')
    row.operator("screen.keyframe_jump", text="", icon='NEXT_KEYFRAME').next = True
    row.operator("screen.frame_jump", text="", icon='FF').end = True

    navigation.draw_nav_row(layout, context, 0)


def draw_row2(layout, context):
    """Row 2: listener result, prompt line, messages, Add Time Tag; Set Key, Key Filters; frame; navigation."""
    state = frame_state.get(context)
    scene = context.scene

    sub = _fixed(layout, LISTENER_WIDTH)
    if state is not None and state.listener_result:
        sub.alert = not state.listener_ok
        sub.label(text=state.listener_result)
    else:
        sub.label(text="")
    sub = layout.row()
    sub.label(text=prompt_text(context))

    layout.template_reports_banner()
    layout.template_running_jobs()
    layout.separator_spacer()

    row = layout.row(align=True)
    placeholder(row, "", icon='MOD_DECIM', feature="Adaptive Degradation")
    placeholder(row, "Add Time Tag", feature="Add Time Tag")

    row = layout.row(align=True)
    row.operator("anim.keyframe_insert", text="Set Key", icon='KEY_HLT')
    placeholder(row, "Key Filters...", feature="Key Filters")

    row = layout.row(align=True)
    placeholder(row, "", icon='KEYFRAME', feature="Key Mode Toggle")
    sub = _fixed(row, 3.5)
    sub.prop(scene, "frame_current", text="")
    row.popover(DOPESHEET_PT_mx_time_configuration.__name__, text="", icon='TIME')

    navigation.draw_nav_row(layout, context, 1)


_areas.DRAWERS['STATUS_ROW'] = draw_row1


def _draw_statusbar(self, context):
    if not _areas.max_window(context, context.window):
        return False
    draw_row2(self.layout, context)
    return True


_override = None

classes = (
    MXUI_OT_listener_run,
    DOPESHEET_PT_mx_time_configuration,
)


def register():
    global _override
    _override = _areas.override_draw(bpy.types.STATUSBAR_HT_header, _draw_statusbar)


def unregister():
    global _override
    if _override is not None:
        _areas.restore_draw(bpy.types.STATUSBAR_HT_header, _override)
        _override = None
