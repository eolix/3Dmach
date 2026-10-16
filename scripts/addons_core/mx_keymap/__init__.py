# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Max-style hotkeys and viewport navigation (ROADMAP Phase 1a).

Enabling the add-on only makes the "Max-Style" keymap available (Preferences > Keymap, or the "Activate" button in
the add-on preferences); it doesn't change the active keymap or any preference by itself.
The binding reference is ``docs/keymap.md``, the design ``docs/decisions/0005-keymap.md``.
"""

bl_info = {
    "name": "Max-Style Keymap",
    "author": "PROJECT_NAME Authors",
    "version": (0, 1, 0),
    "blender": (5, 2, 0),
    "location": "Preferences > Keymap, Preferences > Add-ons > Max-Style Keymap",
    "description": "Max-style hotkeys, navigation, selection and Shift-drag cloning",
    "warning": "Early development",
    "category": "Interface",
}

import bpy

from . import (
    keyconfig,
    prefs,
    view,
    subobject,
    selection,
    clone,
)

_classes = (
    *prefs.classes,
    *view.classes,
    *subobject.classes,
    *selection.classes,
    *clone.classes,
)

_registered = False


def is_registered():
    """Used by the preset file to tell a startup load (operators not registered yet) from an activation."""
    return _registered


def on_preset_loaded(kc, filepath):
    """Entry point for ``presets/keyconfig/Max-Style.py``."""
    keyconfig.on_preset_loaded(kc, filepath)


@bpy.app.handlers.persistent
def _reset_session_state(_filepath):
    # The window manager is saved in .blend files; the selection lock and sub-object level are per session.
    wm = bpy.context.window_manager
    if wm is not None:
        wm.mx_keymap_selection_locked = False
        wm.mx_keymap_subobject_level = 0


def register():
    global _registered
    for cls in _classes:
        bpy.utils.register_class(cls)
    subobject.register_props()
    selection.register_props()
    bpy.app.handlers.load_post.append(_reset_session_state)
    keyconfig.register_preset_path()
    _registered = True
    # Blender loaded the active keymap preset before registering add-ons: fill it now that the operators exist.
    keyconfig.restore_on_register()


def unregister():
    global _registered
    _registered = False
    # Empty the keymap (it refers to this add-on's operators) but keep it as the active choice, so a script reload
    # finds it again. When the add-on was really disabled, `after_unregister` switches back to Blender's keymap.
    keyconfig.clear()
    if not bpy.app.background:
        bpy.app.timers.register(keyconfig.after_unregister, first_interval=0.0)
    keyconfig.unregister_preset_path()
    if _reset_session_state in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_reset_session_state)
    selection.unregister_props()
    subobject.unregister_props()
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
