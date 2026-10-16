# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Add-on preferences and the optional add-on keymap entry for the quad menu."""

import bpy
from bpy.props import BoolProperty, EnumProperty
from bpy.types import AddonPreferences

from . import utils

QUAD_MENU_IDNAME = "VIEW3D_MT_mx_quad"

# Name of the keyconfig provided by `mx_keymap`, which binds the quad menu itself.
MAX_KEYCONFIG_NAME = "Max-Style"

# Keymaps the standalone right-click binding goes into (mode keymaps run before "3D View").
QUAD_MENU_KEYMAPS = (
    ("Object Mode", 'EMPTY'),
    ("Mesh", 'EMPTY'),
    ("Curve", 'EMPTY'),
)

_addon_keymap_items = []


def max_keyconfig_active(context=None):
    context = context or bpy.context
    keyconfigs = context.window_manager.keyconfigs
    active = keyconfigs.active
    if not active:
        return False

    def normalize(name):
        return name.lower().replace("_", " ").replace("-", " ")

    return normalize(active.name).startswith(normalize(MAX_KEYCONFIG_NAME))


def quad_binding_wanted(prefs, context=None):
    mode = prefs.quad_menu_binding if prefs else 'AUTO'
    if mode == 'ALWAYS':
        return True
    if mode == 'NEVER':
        return False
    return not max_keyconfig_active(context)


def keymap_unregister():
    for km, kmi in _addon_keymap_items:
        try:
            km.keymap_items.remove(kmi)
        except (ReferenceError, RuntimeError):
            pass
    _addon_keymap_items.clear()


def keymap_register(context=None):
    """(Re)create the add-on keymap entries according to the preferences."""
    keymap_unregister()
    context = context or bpy.context
    keyconfig = context.window_manager.keyconfigs.addon
    if keyconfig is None:  # Background mode.
        return
    if not quad_binding_wanted(utils.get_prefs(context), context):
        return
    for name, space_type in QUAD_MENU_KEYMAPS:
        km = keyconfig.keymaps.new(name=name, space_type=space_type)
        kmi = km.keymap_items.new("wm.call_menu_pie", 'RIGHTMOUSE', 'PRESS')
        kmi.properties.name = QUAD_MENU_IDNAME
        _addon_keymap_items.append((km, kmi))


def _update_keymap(_self, context):
    keymap_register(context)


class MXUI_AddonPreferences(AddonPreferences):
    bl_idname = utils.ADDON_ID

    quad_menu_binding: EnumProperty(
        name="Right-Click Quad Menu",
        description="Open the quad menu with the right mouse button in the 3D viewport",
        items=(
            ('AUTO', "Automatic",
             "Bind right-click unless the Max-Style keymap is active (it binds the quad menu itself)"),
            ('ALWAYS', "Always", "Always bind right-click to the quad menu"),
            ('NEVER', "Never", "Leave right-click to the active keymap"),
        ),
        default='AUTO',
        update=_update_keymap,
    )
    random_wire_colors: BoolProperty(
        name="Random Wire Colors",
        description="Give each new object a random object (wire) colour, as Max does",
        default=True,
    )
    frozen_in_gray: BoolProperty(
        name="Show Frozen in Gray",
        description="Draw frozen objects in gray (their own colour is restored when unfrozen)",
        default=True,
    )
    use_max_layout_for_new_files: BoolProperty(
        name="Use Max Layout for New Files",
        description=(
            "Switch new, unsaved files to the four-viewport Max Layout workspace "
            "(the workspace is created when missing)"
        ),
        default=True,
    )
    command_panel_everywhere: BoolProperty(
        name="Command Panel in Every Properties Editor",
        description=(
            "Show the command panel in the Tool tab of every Properties editor. "
            "When disabled it only shows in Properties editors whose other tabs are all hidden, "
            "like the one in the Max Layout"
        ),
        default=True,
    )
    command_panel_in_sidebar: BoolProperty(
        name="Command Panel in Viewport Sidebar",
        description="Also show the command panel in the Tool tab of the 3D viewport sidebar",
        default=False,
    )
    show_top_menus: BoolProperty(
        name="Max-Style Menus",
        description="Add Create, Modifiers and Group menus to the top bar",
        default=True,
    )
    show_main_toolbar: BoolProperty(
        name="Main Toolbar",
        description="Add a compact Max-style main toolbar to the top bar",
        default=True,
    )

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        col = layout.column(heading="Quad Menu")
        col.prop(self, "quad_menu_binding", text="Right-Click")
        if self.quad_menu_binding == 'AUTO':
            sub = col.row()
            sub.active = False
            sub.label(text="Max-Style keymap active" if max_keyconfig_active(context) else "Bound to right-click",
                      icon='INFO')

        col = layout.column(heading="Objects")
        col.prop(self, "random_wire_colors")
        col.prop(self, "frozen_in_gray")

        col = layout.column(heading="Command Panel")
        col.prop(self, "command_panel_everywhere", text="Every Properties Editor")
        col.prop(self, "command_panel_in_sidebar", text="Viewport Sidebar")

        col = layout.column(heading="Top Bar")
        col.prop(self, "show_top_menus")
        col.prop(self, "show_main_toolbar")

        col = layout.column(heading="Layout")
        col.prop(self, "use_max_layout_for_new_files", text="New Files")
        col.operator("screen.mx_max_layout", icon='VIEW3D')

        col = layout.column(heading="Theme")
        row = col.row(align=True)
        row.operator("preferences.mx_apply_theme", icon='COLOR')
        row.operator("preferences.reset_default_theme", text="Blender Default")
        col.operator("preferences.mx_install_theme", icon='PRESET')


classes = (
    MXUI_AddonPreferences,
)


def register():
    keymap_register()


def unregister():
    keymap_unregister()
