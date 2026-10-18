# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Add-on preferences: one-click activation of the keymap and the navigation preferences that go with it."""

import json

import bpy
from bpy.props import BoolProperty, StringProperty
from bpy.types import AddonPreferences, Operator

from . import keyconfig


def get():
    addon = bpy.context.preferences.addons.get(__package__)
    return addon.preferences if addon is not None else None


class MX_KEYMAP_AddonPreferences(AddonPreferences):
    bl_idname = __package__

    apply_navigation: BoolProperty(
        name="Max-Like Navigation",
        description=(
            "When the Max-Style keymap is activated, also set the navigation preferences: "
            "orbit around the selection, zoom to the mouse position, "
            "keep orthographic views orthographic when orbiting, turntable orbit"
        ),
        default=True,
    )
    # The navigation preferences from before the first activation, as JSON (empty when nothing to restore).
    saved_navigation: StringProperty(options={'HIDDEN'})

    def remember_navigation(self, previous):
        # Keep the values from before the *first* activation, so activating twice doesn't lose them.
        if not self.saved_navigation:
            self.saved_navigation = json.dumps(previous)

    def draw(self, context):
        layout = self.layout
        col = layout.column()
        if keyconfig.is_active(context):
            col.label(text="The Max-Style keymap is active", icon='CHECKMARK')
        else:
            col.label(text="Active keymap: " + bpy.path.display_name(context.window_manager.keyconfigs.active.name))
        row = col.row()
        row.scale_y = 1.4
        row.operator("mx_keymap.keyconfig_activate", icon='KEYINGSET')
        col.prop(self, "apply_navigation")
        sub = col.row()
        sub.enabled = bool(self.saved_navigation)
        sub.operator("mx_keymap.navigation_restore", icon='LOOP_BACK')
        col.separator()
        col.label(text="To go back to Blender's keymap, pick \"Blender\" in Preferences > Keymap.", icon='INFO')
        col.label(text="The keymap reference is in docs/keymap.md.")


class MX_KEYMAP_OT_keyconfig_activate(Operator):
    """Make Max-Style the active keymap (the same as picking it in Preferences > Keymap)"""
    bl_idname = "mx_keymap.keyconfig_activate"
    bl_label = "Activate Max-Style Keymap"

    def execute(self, context):
        if not keyconfig.activate(report=self.report):
            return {'CANCELLED'}
        context.preferences.is_dirty = True
        self.report({'INFO'}, "Max-Style keymap activated")
        return {'FINISHED'}


class MX_KEYMAP_OT_navigation_restore(Operator):
    """Restore the navigation preferences from before the Max-Style keymap was first activated"""
    bl_idname = "mx_keymap.navigation_restore"
    bl_label = "Restore Previous Navigation Preferences"

    @classmethod
    def poll(cls, context):
        addon_prefs = get()
        return addon_prefs is not None and bool(addon_prefs.saved_navigation)

    def execute(self, context):
        addon_prefs = get()
        try:
            previous = json.loads(addon_prefs.saved_navigation)
        except ValueError:
            previous = {}
        keyconfig.restore_navigation_preferences(previous, context.preferences)
        addon_prefs.saved_navigation = ""
        context.preferences.is_dirty = True
        return {'FINISHED'}


classes = (
    MX_KEYMAP_AddonPreferences,
    MX_KEYMAP_OT_keyconfig_activate,
    MX_KEYMAP_OT_navigation_restore,
)
