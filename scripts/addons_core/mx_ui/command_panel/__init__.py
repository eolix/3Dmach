# SPDX-FileCopyrightText: 2026 3Dmach Authors
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


# -----------------------------------------------------------------------------
# Blender's own Tool panels (Active Tool, Options, Workspace, ...) are hidden in dedicated command panel
# editors, so the command panel looks like Max's: their poll is wrapped while the add-on is enabled.

_wrapped_polls = []


def _all_subclasses(cls):
    for sub in cls.__subclasses__():
        yield sub
        yield from _all_subclasses(sub)


def _registered_panels():
    return [cls for cls in set(_all_subclasses(Panel)) if getattr(cls, "is_registered", False)]


def blender_tool_panels():
    """Blender's registered 3D viewport sidebar panels of the Tool category (not our own)."""
    for cls in _registered_panels():
        if (getattr(cls, "bl_space_type", None) == 'VIEW_3D' and getattr(cls, "bl_region_type", None) == 'UI'
                and getattr(cls, "bl_category", None) == "Tool" and not getattr(cls, "bl_parent_id", "")
                and cls.__module__.startswith("bl_ui")):
            yield cls


def _hiding_poll(original):
    def poll(cls, context):
        if is_command_panel_space(getattr(context, "space_data", None)):
            return False
        return True if original is None else original.__func__(cls, context)
    return classmethod(poll)


def _children(panels, parent):
    """Sub-panels of ``parent`` (recursively), parents before children."""
    result = []
    for cls in panels:
        if getattr(cls, "bl_parent_id", "") == parent.bl_rna.identifier:
            result.append(cls)
            result.extend(_children(panels, cls))
    return result


def _reregister(cls, set_poll):
    """Blender only calls a panel's poll if it had one when registered: register it (and sub-panels) again."""
    children = _children(_registered_panels(), cls)
    for child in reversed(children):
        bpy.utils.unregister_class(child)
    bpy.utils.unregister_class(cls)
    set_poll()
    bpy.utils.register_class(cls)
    for child in children:
        bpy.utils.register_class(child)


def _hide_blender_tool_panels():
    for cls in list(blender_tool_panels()):
        own = cls.__dict__.get("poll")
        had_poll = hasattr(cls, "poll")
        original = own if own is not None else (classmethod(cls.poll.__func__) if had_poll else None)
        if had_poll:
            cls.poll = _hiding_poll(original)
        else:
            _reregister(cls, lambda cls=cls: setattr(cls, "poll", _hiding_poll(None)))
        _wrapped_polls.append((cls, own, had_poll))


def _restore_blender_tool_panels():
    for cls, own, had_poll in reversed(_wrapped_polls):
        if own is not None:
            cls.poll = own
        elif had_poll:
            del cls.poll
        elif cls.is_registered:
            _reregister(cls, lambda cls=cls: delattr(cls, "poll"))
    _wrapped_polls.clear()


def register():
    for mod in _modules:
        if hasattr(mod, "register"):
            mod.register()
    _hide_blender_tool_panels()


def unregister():
    _restore_blender_tool_panels()
    for mod in reversed(_modules):
        if hasattr(mod, "unregister"):
            mod.unregister()
