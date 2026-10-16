# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
The command panel: one column with the Create / Modify / Hierarchy / Display / Utilities tabs.

Container: the Properties editor's **Tool** tab. Blender draws the 3D viewport's sidebar panels of the
"Tool" category there (with the 3D viewport's mode contexts), so a panel registered as
``VIEW_3D`` / ``UI`` / ``bl_category = "Tool"`` with ``HIDE_HEADER`` appears at the top of that tab. A
Properties editor is a full-height, per-window editor like Max's command panel, while a viewport sidebar
would repeat it in every viewport. The Max Layout hides the editor's other tabs, navigation bar and header,
so it only shows the command panel. See ``docs/decisions/0007-max-ui.md``.

Each tab is a module with a ``draw(layout, context)`` function; rollouts use ``layout.panel()``. What the
tabs contain (every button, and whether it is implemented or a placeholder) is data in ``catalog``.
"""

if "bpy" in locals():
    import importlib
    for _mod in _modules:
        importlib.reload(_mod)
    del _mod

import bpy
from bpy.types import Panel

from .. import utils
from ..state import COMMAND_TABS
from . import catalog, widgets, edit_commands, create, modify, hierarchy, motion, display, utilities

_modules = (catalog, widgets, edit_commands, create, modify, hierarchy, motion, display, utilities)

TAB_DRAW = {
    'CREATE': create.draw,
    'MODIFY': modify.draw,
    'HIERARCHY': hierarchy.draw,
    'MOTION': motion.draw,
    'DISPLAY': display.draw,
    'UTILITIES': utilities.draw,
}
assert set(TAB_DRAW) == {tab[0] for tab in COMMAND_TABS}

PROPERTIES_TABS = [prop.identifier for prop in bpy.types.SpaceProperties.bl_rna.properties
                   if prop.identifier.startswith("show_properties_")]


def is_command_panel_space(space):
    """A Properties editor set up as a dedicated command panel: every tab hidden except Tool."""
    if space is None or space.type != 'PROPERTIES':
        return False
    return space.show_properties_tool and not any(
        getattr(space, name) for name in PROPERTIES_TABS if name != "show_properties_tool")


def setup_command_panel_space(space):
    """Make a Properties editor a dedicated command panel (see `is_command_panel_space`)."""
    for name in PROPERTIES_TABS:
        setattr(space, name, name == "show_properties_tool")
    space.context = 'TOOL'


def draw_tab_row(layout, _context, state):
    # Max's tab row: icons only (the tooltips name the tabs).
    row = layout.row(align=True)
    row.scale_y = 1.3
    row.prop(state, "command_tab", expand=True, icon_only=True)


def draw_command_panel(layout, context):
    state = utils.get_state(context)
    if state is None:
        return
    draw_tab_row(layout, context, state)
    layout.separator(factor=0.5)
    TAB_DRAW[state.command_tab](layout, context)


class VIEW3D_PT_mx_command_panel(Panel):
    bl_idname = "VIEW3D_PT_mx_command_panel"
    bl_label = "Command Panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Tool"
    bl_options = {'HIDE_HEADER'}

    @classmethod
    def poll(cls, context):
        space = context.space_data
        prefs = utils.get_prefs(context)
        if space is None:
            return False
        if space.type == 'VIEW_3D':
            return bool(prefs and prefs.command_panel_in_sidebar)
        if space.type != 'PROPERTIES':
            return False
        if prefs is None or prefs.command_panel_everywhere:
            return True
        return is_command_panel_space(space)

    def draw(self, context):
        draw_command_panel(self.layout, context)


classes = (
    *(cls for mod in _modules for cls in getattr(mod, "classes", ())),
    VIEW3D_PT_mx_command_panel,
)


def register():
    for mod in _modules:
        if hasattr(mod, "register"):
            mod.register()


def unregister():
    for mod in reversed(_modules):
        if hasattr(mod, "unregister"):
            mod.unregister()
