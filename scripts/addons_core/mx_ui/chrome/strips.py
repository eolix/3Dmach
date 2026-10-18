# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Strips of the Max window frame (``_areas.STRIP_TYPES``): toolbars drawn in editors that the Max Layout marked.

- Horizontal strips (main toolbar, Scene Explorer menu, find and footer rows, status row 1) are Info editors
  shrunk to their header; ``INFO_HT_header.draw`` draws the strip in marked areas and Blender's Info header elsewhere.
- Vertical strips (viewport layout tab bar, Scene Explorer filter bar) are narrow Properties editors without
  header and tabs, showing the Collection tab pinned to the scene collection, for which Blender's own panels
  don't draw; `MXUI_PT_strip` draws the strip there.

The main toolbar's contents come from ``chrome.main_toolbar.draw_main_toolbar(layout, context)`` when that
module exists; this module only hosts it. The viewport layout tab bar is drawn here.
"""

import sys

import bpy
from bpy.props import EnumProperty
from bpy.types import Menu, Operator, Panel

from ..placeholder import placeholder
from . import _areas

_MAIN_TOOLBAR_MODULE = __package__ + ".main_toolbar"


# -----------------------------------------------------------------------------
# Main toolbar host

def main_toolbar_function():
    mod = sys.modules.get(_MAIN_TOOLBAR_MODULE)
    return getattr(mod, "draw_main_toolbar", None) if mod is not None else None


def draw_main_toolbar_strip(layout, context):
    func = main_toolbar_function()
    if func is None:
        row = layout.row()
        row.active = False
        row.label(text="Main Toolbar", icon='TOOL_SETTINGS')
        return
    func(layout, context)


# -----------------------------------------------------------------------------
# Viewport layout tab bar

class SCREEN_MT_mx_viewport_layouts(Menu):
    bl_idname = "SCREEN_MT_mx_viewport_layouts"
    bl_label = "Standard Viewport Layouts"

    def draw(self, _context):
        layout = self.layout
        layout.operator(SCREEN_OT_mx_viewport_layout.bl_idname, text="4 Viewports", icon='VIEW3D').preset = 'QUAD'
        layout.operator(SCREEN_OT_mx_viewport_layout.bl_idname, text="1 Viewport (Maximized)",
                        icon='FULLSCREEN_ENTER').preset = 'SINGLE'
        layout.separator()
        for text in ("2 Viewports, Vertical Split", "2 Viewports, Horizontal Split", "3 Viewports, Big Left",
                     "3 Viewports, Big Right", "3 Viewports, Big Top", "3 Viewports, Big Bottom",
                     "4 Viewports, Big Left", "4 Viewports, Big Right", "4 Viewports, Big Top"):
            placeholder(layout, text, feature="Viewport layout \"{:s}\"".format(text))
        layout.separator()
        placeholder(layout, "Save Configuration as Preset", icon='PRESET_NEW')
        placeholder(layout, "Load Preset...", icon='FILEBROWSER')


class SCREEN_OT_mx_viewport_layout(Operator):
    """Switch the viewport layout"""
    bl_idname = "screen.mx_viewport_layout"
    bl_label = "Viewport Layout"
    bl_options = {'INTERNAL'}

    preset: EnumProperty(
        name="Layout",
        items=(
            ('QUAD', "4 Viewports", "Top, Front, Left and Perspective"),
            ('SINGLE', "1 Viewport", "The active viewport maximized"),
        ),
    )

    def execute(self, context):
        maximized = bool(context.screen and context.screen.show_fullscreen)
        if (self.preset == 'SINGLE') != maximized:
            return bpy.ops.mx_ui.viewport_maximize_toggle()
        return {'FINISHED'}


def draw_tab_bar(layout, context):
    region = context.region
    ui_scale = context.preferences.system.ui_scale or 1.0
    unit = 20.0 * ui_scale
    col = layout.column(align=True)
    # The tabs sit at the bottom of the strip, like Max's.
    rows = int(region.height / (unit * 1.1)) - 4 if region is not None else 0
    if rows > 0:
        spacer = col.column()
        spacer.ui_units_y = rows
        spacer.label(text="")
    col.menu(SCREEN_MT_mx_viewport_layouts.bl_idname, text="", icon='RIGHTARROW')
    col.separator()
    maximized = bool(context.screen and context.screen.show_fullscreen)
    col.operator(SCREEN_OT_mx_viewport_layout.bl_idname, text="", icon='MESH_GRID',
                 depress=not maximized).preset = 'QUAD'


# -----------------------------------------------------------------------------
# Drawing and the header override

_areas.DRAWERS.update({
    'MAIN_TOOLBAR': draw_main_toolbar_strip,
    'TAB_BAR': draw_tab_bar,
})


def draw_strip(layout, context, kind):
    drawer = _areas.DRAWERS.get(kind)
    if drawer is None:
        layout.label(text=kind.replace("_", " ").title())
        return
    drawer(layout, context)


def _draw_info_header(self, context):
    kind = _areas.strip_kind(context)
    if kind is None:
        return False
    draw_strip(self.layout, context, kind)
    return True


def _repin_strips():
    for window in bpy.context.window_manager.windows:
        screen = window.screen
        for area in screen.areas:
            if area.type != 'PROPERTIES' or _areas.area_role(screen, area) not in _areas.STRIP_TYPES:
                continue
            space = area.spaces.active
            if _areas.strip_needs_repin(space, window.scene):
                _areas.pin_strip(space, window.scene)
    return None


class MXUI_PT_strip(Panel):
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "collection"
    bl_label = "Max Strip"
    bl_options = {'HIDE_HEADER'}

    @classmethod
    def poll(cls, context):
        return _areas.strip_kind(context) is not None

    def draw(self, context):
        space = context.space_data
        if _areas.strip_needs_repin(space, context.scene) and not bpy.app.timers.is_registered(_repin_strips):
            # Another scene: pin its collection (data can't change while drawing).
            bpy.app.timers.register(_repin_strips, first_interval=0.0)
        draw_strip(self.layout, context, _areas.strip_kind(context))


_override = None

classes = (
    SCREEN_MT_mx_viewport_layouts,
    SCREEN_OT_mx_viewport_layout,
    MXUI_PT_strip,
)


def register():
    global _override
    _override = _areas.override_draw(bpy.types.INFO_HT_header, _draw_info_header)


def unregister():
    global _override
    if _override is not None:
        _areas.restore_draw(bpy.types.INFO_HT_header, _override)
        _override = None
    _areas.clear_cache()
