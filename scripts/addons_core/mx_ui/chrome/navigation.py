# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Max's viewport navigation controls (bottom right): Zoom, Zoom All, Zoom Extents, Zoom Extents All, Field of
View / Zoom Region, Pan View, Orbit and Maximize Viewport Toggle, plus Isolate Selection.

The buttons live in the status line, outside the viewports, so they act on the *target viewport*: the Max
viewport the mouse was last over (recorded by the ViewCube gizmo, which Blender asks about every mouse move),
else the Perspective viewport. One-shot commands run there directly. The interactive ones are modes, as in
Max: the button stays pressed, dragging in any viewport zooms / pans / orbits it, and right-click or Esc ends
the mode. Zoom, Zoom All, Field-of-View, Pan and Orbit handle the drag themselves; Zoom Region starts Blender's
box zoom in the viewport clicked.
"""

import math

import bpy
from bpy.props import EnumProperty
from bpy.types import Menu, Operator
from bpy_extras.view3d_utils import region_2d_to_location_3d
from mathutils import Quaternion, Vector

from ..placeholder import placeholder
from . import _areas, frame_state

# Pointer of the 3D viewport area the mouse was last over.
_last_viewport = {"area": 0}


def note_viewport(area):
    if area is not None:
        _last_viewport["area"] = area.as_pointer()


def _window_region(area):
    return next((r for r in area.regions if r.type == 'WINDOW'), None)


def max_viewports(screen):
    return [a for a in screen.areas if a.type == 'VIEW_3D'] if screen is not None else []


def target_viewport(context):
    """``(area, region)`` of the viewport the navigation controls act on, or ``(None, None)``."""
    screen = getattr(context, "screen", None)
    areas = max_viewports(screen)
    if not areas:
        return None, None
    area = getattr(context, "area", None)
    if area is None or area.type != 'VIEW_3D':
        area = next((a for a in areas if a.as_pointer() == _last_viewport["area"]), None)
    if area is None:
        area = _areas.find_area(screen, 'PERSPECTIVE')
    if area is None or area.type != 'VIEW_3D':
        area = max(areas, key=lambda a: a.width * a.height)
    return area, _window_region(area)


def run_in_viewport(context, area, region, op, *args, **kwargs):
    with context.temp_override(window=context.window, screen=context.screen, area=area, region=region):
        if not op.poll():
            return {'CANCELLED'}
        return op(*args, **kwargs)


# -----------------------------------------------------------------------------
# One-shot commands

NAV_ACTIONS = (
    ('ZOOM_EXTENTS', "Zoom Extents", "Zoom the active viewport to all objects"),
    ('ZOOM_EXTENTS_SELECTED', "Zoom Extents Selected", "Zoom the active viewport to the selection"),
    ('ZOOM_EXTENTS_ALL', "Zoom Extents All", "Zoom every viewport to all objects"),
    ('ZOOM_EXTENTS_ALL_SELECTED', "Zoom Extents All Selected", "Zoom every viewport to the selection"),
    ('ISOLATE', "Isolate Selection Toggle", "Show only the selection in the active viewport, or show all again"),
)


class MXUI_OT_viewport_nav(Operator):
    """Viewport navigation command"""
    bl_idname = "mx_ui.viewport_nav"
    bl_label = "Viewport Navigation"
    bl_options = {'INTERNAL'}

    action: EnumProperty(name="Action", items=NAV_ACTIONS)

    @classmethod
    def description(cls, _context, properties):
        return next(item[2] for item in NAV_ACTIONS if item[0] == properties.action)

    @classmethod
    def poll(cls, context):
        return context.window is not None and context.screen is not None

    def execute(self, context):
        area, region = target_viewport(context)
        if area is None:
            self.report({'WARNING'}, "No viewport")
            return {'CANCELLED'}
        action = self.action
        if action == 'ISOLATE':
            return run_in_viewport(context, area, region, bpy.ops.view3d.localview, frame_selected=True)
        selected = action.endswith("_SELECTED")
        areas = max_viewports(context.screen) if action.startswith("ZOOM_EXTENTS_ALL") else [area]
        for target in areas:
            target_region = _window_region(target)
            if target_region is None:
                continue
            if selected and context.selected_objects:
                run_in_viewport(context, target, target_region, bpy.ops.view3d.view_selected)
            else:
                run_in_viewport(context, target, target_region, bpy.ops.view3d.view_all, center=False)
        return {'FINISHED'}


class MXUI_OT_viewport_maximize_toggle(Operator):
    """Maximize the active viewport, or go back to the viewport layout (Alt+W)"""
    bl_idname = "mx_ui.viewport_maximize_toggle"
    bl_label = "Maximize Viewport Toggle"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return context.window is not None and context.screen is not None

    def execute(self, context):
        area, region = target_viewport(context)
        if area is None:
            return {'CANCELLED'}
        if hasattr(bpy.types, "MX_KEYMAP_OT_viewport_maximize"):
            result = run_in_viewport(context, area, region, bpy.ops.mx_keymap.viewport_maximize)
        elif hasattr(bpy.types, "MX_UI_OT_max_viewport_maximize"):
            result = run_in_viewport(context, area, region, bpy.ops.mx_ui.max_viewport_maximize)
            if 'FINISHED' not in result:
                result = run_in_viewport(context, area, region, bpy.ops.screen.screen_full_area)
        else:
            result = run_in_viewport(context, area, region, bpy.ops.screen.screen_full_area)
        return result if 'FINISHED' in result else {'CANCELLED'}


# -----------------------------------------------------------------------------
# Interactive modes

NAV_MODES = (
    ('ZOOM', "Zoom", "Drag in a viewport to zoom it", 'VIEW_ZOOM'),
    ('ZOOM_ALL', "Zoom All", "Drag in a viewport to zoom all viewports", 'ZOOM_ALL'),
    ('FOV', "Field-of-View", "Drag in a perspective viewport to change its field of view", 'CAMERA_DATA'),
    ('ZOOM_REGION', "Zoom Region", "Drag a rectangle in a viewport to zoom to it", 'BORDERMOVE'),
    ('PAN', "Pan View", "Drag in a viewport to pan it", 'VIEW_PAN'),
    ('ORBIT', "Orbit", "Drag in a viewport to orbit around its center", 'ORIENTATION_GIMBAL'),
)

MODE_PROMPTS = {
    'ZOOM': "Click and drag to zoom a viewport (right-click to exit)",
    'ZOOM_ALL': "Click and drag to zoom all viewports (right-click to exit)",
    'FOV': "Click and drag to change the field of view (right-click to exit)",
    'ZOOM_REGION': "Drag to zoom to a region (right-click to exit)",
    'PAN': "Click and drag to pan a viewport (right-click to exit)",
    'ORBIT': "Click and drag to orbit a viewport (right-click to exit)",
}

_ZOOM_SPEED = 0.01
_FOV_SPEED = 0.15


def viewport_at(screen, x, y):
    """``(area, region)`` of the 3D viewport main region under window coordinates ``(x, y)``."""
    for area in max_viewports(screen):
        region = _window_region(area)
        if region is not None and region.x <= x < region.x + region.width and region.y <= y < region.y + region.height:
            return area, region
    return None, None


def zoom_view(rv3d, factor):
    rv3d.view_distance = max(rv3d.view_distance * factor, 1e-4)


def pan_view(region, rv3d, start, end):
    """Move the view so the point under region pixel ``start`` ends up under ``end``."""
    a = region_2d_to_location_3d(region, rv3d, start, rv3d.view_location)
    b = region_2d_to_location_3d(region, rv3d, end, rv3d.view_location)
    rv3d.view_location = rv3d.view_location - (b - a)


def orbit_view(rv3d, dx, dy, speed=0.01):
    """Turntable orbit around the view centre: ``dx`` turns around the world Z axis, ``dy`` tilts."""
    if rv3d.view_perspective == 'CAMERA':
        return
    if rv3d.is_orthographic_side_view:
        rv3d.is_orthographic_side_view = False
        if rv3d.view_perspective == 'ORTHO':
            # Leaving an axis view shows the scene in perspective, as Max does.
            rv3d.view_perspective = 'PERSP'
    rotation = rv3d.view_rotation
    turn = Quaternion((0.0, 0.0, 1.0), -dx * speed)
    tilt = Quaternion(rotation @ Vector((1.0, 0.0, 0.0)), dy * speed)
    rv3d.view_rotation = turn @ tilt @ rotation


def change_fov(space, delta):
    """Change a perspective viewport's lens by ``delta`` degrees of field of view."""
    sensor = 36.0
    fov = 2.0 * math.atan(sensor / (2.0 * space.lens))
    fov = min(max(fov + math.radians(delta), math.radians(1.0)), math.radians(170.0))
    space.lens = sensor / (2.0 * math.tan(fov / 2.0))


class MXUI_OT_viewport_nav_mode(Operator):
    """Viewport navigation mode: drag in a viewport, right-click to exit"""
    bl_idname = "mx_ui.viewport_nav_mode"
    bl_label = "Viewport Navigation Mode"
    bl_options = {'INTERNAL'}

    mode: EnumProperty(name="Mode", items=[item[:3] for item in NAV_MODES])

    @classmethod
    def description(cls, _context, properties):
        item = next(item for item in NAV_MODES if item[0] == properties.mode)
        return "{:s}: {:s}".format(item[1], item[2].lower())

    @classmethod
    def poll(cls, context):
        return context.window is not None and context.screen is not None

    def invoke(self, context, _event):
        state = frame_state.get(context)
        if state is None:
            return {'CANCELLED'}
        if state.nav_mode == self.mode:
            # Clicking the pressed button again ends the mode.
            state.nav_mode = ""
            return {'CANCELLED'}
        state.nav_mode = self.mode
        self._drag = None
        context.window_manager.modal_handler_add(self)
        self._redraw(context)
        return {'RUNNING_MODAL'}

    def _redraw(self, context):
        for area in context.screen.areas:
            if area.type in {'VIEW_3D', 'DOPESHEET_EDITOR'}:
                area.tag_redraw()
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()

    def _finish(self, context):
        state = frame_state.get(context)
        if state is not None and state.nav_mode == self.mode:
            state.nav_mode = ""
        self._redraw(context)
        return {'FINISHED'}

    def modal(self, context, event):
        state = frame_state.get(context)
        if state is None or state.nav_mode != self.mode:
            # Another mode (or the same button again) took over.
            return {'FINISHED'}
        if self._drag is not None:
            return self._modal_drag(context, event)
        if event.type in {'RIGHTMOUSE', 'ESC'} and event.value == 'PRESS':
            return self._finish(context)
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            area, region = viewport_at(context.screen, event.mouse_x, event.mouse_y)
            if area is None:
                return {'PASS_THROUGH'}
            note_viewport(area)
            return self._start(context, event, area, region)
        return {'PASS_THROUGH'}

    def _start(self, context, event, area, region):
        mode = self.mode
        if mode == 'ZOOM_REGION':
            run_in_viewport(context, area, region, bpy.ops.view3d.zoom_border, 'INVOKE_DEFAULT')
            return {'RUNNING_MODAL'}
        space = area.spaces.active
        if mode == 'ZOOM_ALL':
            views = [a.spaces.active.region_3d for a in max_viewports(context.screen)]
        else:
            views = [space.region_3d]
        rv3d = space.region_3d
        self._drag = {
            "y": event.mouse_y,
            "prev": (event.mouse_x, event.mouse_y),
            "distances": [view.view_distance for view in views],
            "views": views,
            "space": space,
            "region": region,
            "lens": space.lens,
            "location": rv3d.view_location.copy(),
            "rotation": rv3d.view_rotation.copy(),
        }
        return {'RUNNING_MODAL'}

    def _restore(self, drag):
        for rv3d, distance in zip(drag["views"], drag["distances"]):
            rv3d.view_distance = distance
        space = drag["space"]
        space.lens = drag["lens"]
        space.region_3d.view_location = drag["location"]
        space.region_3d.view_rotation = drag["rotation"]

    def _modal_drag(self, context, event):
        drag = self._drag
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            self._drag = None
            return {'RUNNING_MODAL'}
        if event.type in {'RIGHTMOUSE', 'ESC'}:
            self._restore(drag)
            self._drag = None
            self._redraw(context)
            return {'RUNNING_MODAL'}
        if event.type == 'MOUSEMOVE':
            mode = self.mode
            region = drag["region"]
            rv3d = drag["space"].region_3d
            prev = drag["prev"]
            current = (event.mouse_x, event.mouse_y)
            drag["prev"] = current
            if mode == 'PAN':
                pan_view(region, rv3d, (prev[0] - region.x, prev[1] - region.y),
                         (current[0] - region.x, current[1] - region.y))
            elif mode == 'ORBIT':
                orbit_view(rv3d, current[0] - prev[0], current[1] - prev[1])
            elif mode == 'FOV':
                drag["space"].lens = drag["lens"]
                change_fov(drag["space"], -(event.mouse_y - drag["y"]) * _FOV_SPEED)
            else:
                factor = math.exp(-(event.mouse_y - drag["y"]) * _ZOOM_SPEED)
                for view, distance in zip(drag["views"], drag["distances"]):
                    view.view_distance = max(distance * factor, 1e-4)
            self._redraw(context)
        return {'RUNNING_MODAL'}


# -----------------------------------------------------------------------------
# Flyouts and drawing

class VIEW3D_MT_mx_zoom_extents(Menu):
    bl_idname = "VIEW3D_MT_mx_zoom_extents"
    bl_label = "Zoom Extents"

    def draw(self, _context):
        layout = self.layout
        layout.operator(MXUI_OT_viewport_nav.bl_idname, text="Zoom Extents",
                        icon='ZOOM_ALL').action = 'ZOOM_EXTENTS'
        layout.operator(MXUI_OT_viewport_nav.bl_idname, text="Zoom Extents Selected",
                        icon='ZOOM_SELECTED').action = 'ZOOM_EXTENTS_SELECTED'


class VIEW3D_MT_mx_zoom_extents_all(Menu):
    bl_idname = "VIEW3D_MT_mx_zoom_extents_all"
    bl_label = "Zoom Extents All"

    def draw(self, _context):
        layout = self.layout
        layout.operator(MXUI_OT_viewport_nav.bl_idname, text="Zoom Extents All",
                        icon='ZOOM_ALL').action = 'ZOOM_EXTENTS_ALL'
        layout.operator(MXUI_OT_viewport_nav.bl_idname, text="Zoom Extents All Selected",
                        icon='ZOOM_SELECTED').action = 'ZOOM_EXTENTS_ALL_SELECTED'


class VIEW3D_MT_mx_fov(Menu):
    bl_idname = "VIEW3D_MT_mx_fov"
    bl_label = "Field-of-View / Zoom Region"

    def draw(self, _context):
        layout = self.layout
        layout.operator(MXUI_OT_viewport_nav_mode.bl_idname, text="Field-of-View", icon='CAMERA_DATA').mode = 'FOV'
        layout.operator(MXUI_OT_viewport_nav_mode.bl_idname, text="Zoom Region",
                        icon='BORDERMOVE').mode = 'ZOOM_REGION'


class VIEW3D_MT_mx_orbit(Menu):
    bl_idname = "VIEW3D_MT_mx_orbit"
    bl_label = "Orbit"

    def draw(self, _context):
        layout = self.layout
        layout.operator(MXUI_OT_viewport_nav_mode.bl_idname, text="Orbit", icon='ORIENTATION_GIMBAL').mode = 'ORBIT'
        placeholder(layout, "Orbit Selected", icon='PIVOT_ACTIVE')
        placeholder(layout, "Orbit SubObject", icon='PIVOT_INDIVIDUAL')
        placeholder(layout, "Orbit Point of Interest", icon='PIVOT_CURSOR')


def _mode_button(layout, state, mode, menu=None):
    icon = next(item[3] for item in NAV_MODES if item[0] == mode)
    depress = state is not None and state.nav_mode == mode
    if menu is not None:
        props = layout.operator_menu_hold(MXUI_OT_viewport_nav_mode.bl_idname, menu=menu, text="", icon=icon,
                                          depress=depress)
    else:
        props = layout.operator(MXUI_OT_viewport_nav_mode.bl_idname, text="", icon=icon, depress=depress)
    props.mode = mode


def draw_nav_row(layout, context, row_index):
    """One of the two rows of Max's viewport navigation controls."""
    state = frame_state.get(context)
    row = layout.row(align=True)
    if row_index == 0:
        _mode_button(row, state, 'ZOOM')
        _mode_button(row, state, 'ZOOM_ALL')
        row.operator_menu_hold(MXUI_OT_viewport_nav.bl_idname, menu=VIEW3D_MT_mx_zoom_extents.bl_idname,
                               text="", icon='ZOOM_SELECTED').action = 'ZOOM_EXTENTS'
        row.operator_menu_hold(MXUI_OT_viewport_nav.bl_idname, menu=VIEW3D_MT_mx_zoom_extents_all.bl_idname,
                               text="", icon='FULLSCREEN_EXIT').action = 'ZOOM_EXTENTS_ALL'
    else:
        mode = 'ZOOM_REGION' if state is not None and state.nav_mode == 'ZOOM_REGION' else 'FOV'
        _mode_button(row, state, mode, menu=VIEW3D_MT_mx_fov.bl_idname)
        _mode_button(row, state, 'PAN')
        _mode_button(row, state, 'ORBIT', menu=VIEW3D_MT_mx_orbit.bl_idname)
        maximized = bool(context.screen and context.screen.show_fullscreen)
        row.operator(MXUI_OT_viewport_maximize_toggle.bl_idname, text="",
                     icon='FULLSCREEN_EXIT' if maximized else 'FULLSCREEN_ENTER', depress=maximized)


def isolate_active(context):
    area, _region = target_viewport(context)
    return area is not None and area.spaces.active.local_view is not None


classes = (
    MXUI_OT_viewport_nav,
    MXUI_OT_viewport_maximize_toggle,
    MXUI_OT_viewport_nav_mode,
    VIEW3D_MT_mx_zoom_extents,
    VIEW3D_MT_mx_zoom_extents_all,
    VIEW3D_MT_mx_fov,
    VIEW3D_MT_mx_orbit,
)
