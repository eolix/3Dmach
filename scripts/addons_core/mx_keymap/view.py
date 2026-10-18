# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Viewport operators: views, zoom extents, maximize, grid and snap toggles, editor windows."""

import bpy
from bpy.props import EnumProperty
from bpy.types import Operator


def _view3d_poll(context):
    return context.area is not None and context.area.type == 'VIEW_3D' and context.region_data is not None


# ------------------------------------------------------------------------------
# Plain functions (testable without a window)

def set_projection(rv3d, mode, camera=None):
    """
    Switch ``rv3d`` to ``'PERSP'`` or ``'ORTHO'`` keeping the current viewing angle.

    Leaving a camera view keeps the camera's viewpoint (Max's P/U in a camera view), when ``camera`` is given.
    """
    if rv3d.view_perspective == 'CAMERA' and camera is not None:
        rv3d.view_matrix = camera.matrix_world.inverted_safe()
    rv3d.view_perspective = mode


def has_selection(context):
    """Whether there is anything selected to zoom to, in object or edit mode."""
    obj = context.edit_object
    if obj is not None:
        if obj.type == 'MESH':
            return any(
                ob.data.total_vert_sel for ob in (context.objects_in_mode or [obj]) if ob.type == 'MESH'
            )
        # Other edit modes: let Blender's "Frame Selected" decide.
        return True
    if context.mode != 'OBJECT':
        return True
    return any(ob.visible_get() for ob in context.selected_objects)


def toggle_snap_state(use_snap, translate, rotate, kind):
    """
    New ``(use_snap, use_snap_translate, use_snap_rotate)`` after toggling Max's snap (S) or angle snap (A).

    Blender has a single snapping switch with per-transform "affect" options, Max has independent toggles:
    S is snapping for moves, A is angle snapping for rotations. Either one switches snapping on.
    """
    snap_on = use_snap and translate
    angle_on = use_snap and rotate
    if kind == 'SNAP':
        snap_on = not snap_on
    else:
        angle_on = not angle_on
    # With both off, leave "affect translation" on, which is Blender's default.
    return (snap_on or angle_on, snap_on or not angle_on, angle_on)


# ------------------------------------------------------------------------------
# Operators

class MX_KEYMAP_OT_view_axis(Operator):
    """Orthographic view along an axis (Top, Bottom, Front, Left, ...)"""
    bl_idname = "mx_keymap.view_axis"
    bl_label = "View Axis"

    type: EnumProperty(
        name="View",
        items=(
            ('TOP', "Top", ""),
            ('BOTTOM', "Bottom", ""),
            ('FRONT', "Front", ""),
            ('BACK', "Back", ""),
            ('LEFT', "Left", ""),
            ('RIGHT', "Right", ""),
        ),
    )

    @classmethod
    def poll(cls, context):
        return _view3d_poll(context)

    def execute(self, context):
        rv3d = context.region_data
        if rv3d.view_perspective != 'ORTHO':
            rv3d.view_perspective = 'ORTHO'
        return bpy.ops.view3d.view_axis(type=self.type)


class MX_KEYMAP_OT_view_projection(Operator):
    """Perspective or orthographic ("User") view, keeping the current angle"""
    bl_idname = "mx_keymap.view_projection"
    bl_label = "View Projection"

    mode: EnumProperty(
        name="Projection",
        items=(
            ('PERSP', "Perspective", "Perspective view at the current angle"),
            ('ORTHO', "User", "Orthographic view at the current angle"),
        ),
    )

    @classmethod
    def poll(cls, context):
        return _view3d_poll(context)

    def execute(self, context):
        set_projection(context.region_data, self.mode, camera=context.scene.camera)
        context.area.tag_redraw()
        return {'FINISHED'}


class MX_KEYMAP_OT_view_camera(Operator):
    """View through the selected camera, or the scene camera"""
    bl_idname = "mx_keymap.view_camera"
    bl_label = "Camera View"

    @classmethod
    def poll(cls, context):
        return _view3d_poll(context)

    def execute(self, context):
        obj = context.active_object
        if obj is not None and obj.type == 'CAMERA' and obj.select_get() and context.mode == 'OBJECT':
            return bpy.ops.view3d.object_as_camera()
        if context.scene.camera is None:
            self.report({'WARNING'}, "There is no camera in the scene")
            return {'CANCELLED'}
        if context.region_data.view_perspective != 'CAMERA':
            return bpy.ops.view3d.view_camera()
        return {'FINISHED'}


class MX_KEYMAP_OT_zoom_extents(Operator):
    """Zoom to the selection, or to everything when nothing is selected"""
    bl_idname = "mx_keymap.zoom_extents"
    bl_label = "Zoom Extents Selected"

    @classmethod
    def poll(cls, context):
        return _view3d_poll(context)

    def execute(self, context):
        if has_selection(context):
            return bpy.ops.view3d.view_selected(use_all_regions=False)
        return bpy.ops.view3d.view_all(use_all_regions=False, center=False)


# Areas whose quad view was turned off by "Maximize Viewport" (by area pointer), to turn it back on.
_quad_maximized = set()


class MX_KEYMAP_OT_viewport_maximize(Operator):
    """Maximize the viewport under the mouse, or restore the layout"""
    bl_idname = "mx_keymap.viewport_maximize"
    bl_label = "Maximize Viewport Toggle"

    @classmethod
    def poll(cls, context):
        return _view3d_poll(context)

    def execute(self, context):
        # In the Max Layout (mx_ui), maximize within the viewport block and keep the rest of the interface.
        if hasattr(bpy.types, "MX_UI_OT_max_viewport_maximize") and bpy.ops.mx_ui.max_viewport_maximize.poll():
            return bpy.ops.mx_ui.max_viewport_maximize()
        area = context.area
        key = area.as_pointer()
        if context.space_data.region_quadviews:
            # Blender's quad view: keep the view under the mouse. A locked (axis) view would be swapped for the
            # user view when leaving quad view, so unlock it first.
            rv3d = context.region_data
            rv3d.lock_rotation = False
            rv3d.show_sync_view = False
            rv3d.use_box_clip = False
            result = bpy.ops.screen.region_quadview()
            if 'FINISHED' in result:
                _quad_maximized.add(key)
            return result
        if key in _quad_maximized:
            _quad_maximized.discard(key)
            return bpy.ops.screen.region_quadview()
        # Separate viewports: maximize the area (or restore it).
        return bpy.ops.screen.screen_full_area()


class MX_KEYMAP_OT_toggle_grid(Operator):
    """Show or hide the home grid"""
    bl_idname = "mx_keymap.toggle_grid"
    bl_label = "Toggle Grid"

    @classmethod
    def poll(cls, context):
        return _view3d_poll(context)

    def execute(self, context):
        overlay = context.space_data.overlay
        show = not (overlay.show_floor or overlay.show_ortho_grid)
        overlay.show_floor = show
        overlay.show_ortho_grid = show
        return {'FINISHED'}


class MX_KEYMAP_OT_snap_toggle(Operator):
    """Toggle snapping (S) or angle snapping (A)"""
    bl_idname = "mx_keymap.snap_toggle"
    bl_label = "Snap Toggle"

    kind: EnumProperty(
        name="Snap",
        items=(
            ('SNAP', "Snap", "Snapping for moves"),
            ('ANGLE', "Angle Snap", "Angle increment snapping for rotations"),
        ),
    )

    @classmethod
    def poll(cls, context):
        return context.scene is not None

    def execute(self, context):
        ts = context.tool_settings
        ts.use_snap, ts.use_snap_translate, ts.use_snap_rotate = toggle_snap_state(
            ts.use_snap, ts.use_snap_translate, ts.use_snap_rotate, self.kind)
        if self.kind == 'SNAP':
            state = ts.use_snap and ts.use_snap_translate
            self.report({'INFO'}, "Snap " + ("on" if state else "off"))
        else:
            state = ts.use_snap and ts.use_snap_rotate
            msg = "Angle snap {:s} ({:.4g}°)".format(
                "on" if state else "off", ts.snap_angle_increment_3d * 57.29577951308232)
            if state and 'INCREMENT' not in ts.snap_elements:
                msg += ", add the Increment snap target for angle steps"
            self.report({'INFO'}, msg)
        return {'FINISHED'}


# Windows opened by `open_editor`, by editor kind -> window pointer, so the key toggles them like Max dialogs.
_editor_windows = {}


def _find_window(pointer):
    for window in bpy.context.window_manager.windows:
        if window.as_pointer() == pointer:
            return window
    return None


class MX_KEYMAP_OT_open_editor(Operator):
    """Open (or close) a material editor or render setup window"""
    bl_idname = "mx_keymap.open_editor"
    bl_label = "Open Editor Window"

    editor: EnumProperty(
        name="Editor",
        items=(
            ('MATERIAL', "Material Editor", "Shader Editor in a new window"),
            ('RENDER', "Render Setup", "Render properties in a new window"),
        ),
    )

    @classmethod
    def poll(cls, context):
        return context.window is not None and context.area is not None and not context.screen.is_temporary

    def execute(self, context):
        window = _find_window(_editor_windows.get(self.editor, 0))
        if window is not None:
            # Pressing the key again closes the window, like Max's dialogs.
            with context.temp_override(window=window):
                bpy.ops.wm.window_close()
            _editor_windows.pop(self.editor, None)
            return {'FINISHED'}

        windows_before = {w.as_pointer() for w in context.window_manager.windows}
        if 'FINISHED' not in bpy.ops.screen.area_dupli('INVOKE_DEFAULT'):
            return {'CANCELLED'}
        new = [w for w in context.window_manager.windows if w.as_pointer() not in windows_before]
        if not new:
            return {'CANCELLED'}
        window = new[0]
        area = window.screen.areas[0]
        if self.editor == 'MATERIAL':
            area.type = 'NODE_EDITOR'
            area.ui_type = 'ShaderNodeTree'
        else:
            area.type = 'PROPERTIES'
            area.spaces.active.context = 'RENDER'
        _editor_windows[self.editor] = window.as_pointer()
        return {'FINISHED'}


class MX_KEYMAP_OT_delete_subobject(Operator):
    """Delete the selected vertices, edges or faces (no confirmation)"""
    bl_idname = "mx_keymap.delete_subobject"
    bl_label = "Delete Sub-Objects"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        vert, edge, _face = context.tool_settings.mesh_select_mode
        kind = 'VERT' if vert else 'EDGE' if edge else 'FACE'
        return bpy.ops.mesh.delete(type=kind)


classes = (
    MX_KEYMAP_OT_view_axis,
    MX_KEYMAP_OT_view_projection,
    MX_KEYMAP_OT_view_camera,
    MX_KEYMAP_OT_zoom_extents,
    MX_KEYMAP_OT_viewport_maximize,
    MX_KEYMAP_OT_toggle_grid,
    MX_KEYMAP_OT_snap_toggle,
    MX_KEYMAP_OT_open_editor,
    MX_KEYMAP_OT_delete_subobject,
)
