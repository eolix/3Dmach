# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Building, registering and activating the "Max-Style" key configuration.

How it fits together (see ``docs/decisions/0005-keymap.md``):

- ``presets/keyconfig/Max-Style.py`` is a small key configuration preset, like Blender's own ``Blender.py``.
  The fork ships the same file in ``scripts/presets/keyconfig/``. On stock Blender the add-on registers its own
  ``presets`` directory, so "Max-Style" shows up in Preferences > Keymap while the add-on is enabled.
- Running the preset (picking it in Preferences, or the add-on's "Activate" button) calls
  :func:`on_preset_loaded`, which fills the key configuration from ``keymap_data``.
- Blender loads the active preset at startup *before* add-ons are registered, when the add-on's operators don't
  exist yet. The preset then only creates an empty "Max-Style" key configuration (keeping it active) and the
  add-on fills it from ``register()``.
- On stock Blender the preset must be found again at the next startup, before the add-on registers its preset
  directory, so activating it copies the preset into the user's ``scripts/presets/keyconfig`` (what Blender's own
  "Import Key Configuration" does).
"""

import os
import shutil
import sys

import bpy

from . import keymap_data

IDNAME = keymap_data.KEYCONFIG_NAME
ADDON_DIR = os.path.dirname(os.path.abspath(__file__))
PRESET_FILENAME = IDNAME + ".py"
ADDON_PRESET = os.path.join(ADDON_DIR, "presets", "keyconfig", PRESET_FILENAME)

# Max-like navigation, applied (when the add-on preference is on) each time the keymap is activated.
NAVIGATION_PREFERENCES = (
    # Orbit around the selection.
    ("use_rotate_around_active", True),
    # Zoom towards the mouse position.
    ("use_zoom_to_mouse", True),
    # Orbiting an orthographic view keeps it orthographic (Max turns it into an "Orthographic" user view).
    ("use_auto_perspective", False),
    # Orbit keeps the horizon level.
    ("view_rotate_method", 'TURNTABLE'),
)

_state = {
    "preset_path_registered": False,
}


# ------------------------------------------------------------------------------
# Key-map data

def _blender_default_path():
    for directory in bpy.utils.preset_paths("keyconfig"):
        path = os.path.join(directory, "keymap_data", "blender_default.py")
        if os.path.exists(path):
            return path
    raise RuntimeError("Blender's default key-map data (keymap_data/blender_default.py) was not found")


def generate_keyconfig_data():
    """The Max-style key-map data, for the current platform and input preferences."""
    prefs = bpy.context.preferences
    blender_default = bpy.utils.execfile(_blender_default_path())
    use_mouse_emulate_3_button = (
        prefs.inputs.use_mouse_emulate_3_button and
        prefs.inputs.mouse_emulate_3_button_modifier == 'ALT'
    )
    data = keymap_data.generate_keymaps(blender_default, use_mouse_emulate_3_button=use_mouse_emulate_3_button)
    if sys.platform == "darwin":
        from bl_keymap_utils.platform_helpers import keyconfig_data_oskey_from_ctrl_for_macos
        data = keyconfig_data_oskey_from_ctrl_for_macos(data)
    return data


def fill(kc=None):
    """(Re)build the Max-Style key configuration ``kc`` (created if needed). Returns it."""
    from bl_keymap_utils.io import keyconfig_init_from_data
    wm = bpy.context.window_manager
    if kc is None or len(kc.keymaps):
        # `keyconfigs.new` returns the existing key configuration cleared, keeping it active if it was.
        kc = wm.keyconfigs.new(IDNAME)
    keyconfig_init_from_data(kc, generate_keyconfig_data())
    return kc


def clear():
    """Empty the key configuration (leaving it, and the active choice, in place)."""
    wm = bpy.context.window_manager
    if wm.keyconfigs.get(IDNAME) is not None:
        wm.keyconfigs.new(IDNAME)


def is_active(context=None):
    context = context or bpy.context
    return context.window_manager.keyconfigs.active.name == IDNAME


# ------------------------------------------------------------------------------
# Presets

def _same_dir(a, b):
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def installed_preset_path():
    """The Max-Style preset Blender finds at startup (system, user or script directories), or None."""
    addon_dir = os.path.dirname(ADDON_PRESET)
    for directory in bpy.utils.preset_paths("keyconfig"):
        if _same_dir(directory, addon_dir):
            continue
        path = os.path.join(directory, PRESET_FILENAME)
        if os.path.exists(path):
            return path
    return None


def user_preset_dir():
    return bpy.utils.user_resource('SCRIPTS', path=os.path.join("presets", "keyconfig"), create=True)


def register_preset_path():
    """Make the preset selectable in Preferences > Keymap, unless an installed copy already is."""
    if _state["preset_path_registered"] or installed_preset_path() is not None:
        return
    bpy.utils.register_preset_path(ADDON_DIR)
    _state["preset_path_registered"] = True


def unregister_preset_path():
    if _state["preset_path_registered"]:
        bpy.utils.unregister_preset_path(ADDON_DIR)
        _state["preset_path_registered"] = False


def install_user_preset():
    """Copy the preset to the user's presets so Blender finds it at startup. Returns its path."""
    path = installed_preset_path()
    if path is None:
        path = os.path.join(user_preset_dir(), PRESET_FILENAME)
        shutil.copyfile(ADDON_PRESET, path)
    # The installed copy is listed now, don't show the preset twice.
    unregister_preset_path()
    return path


# ------------------------------------------------------------------------------
# Activation

def _in_keyconfig_init():
    """True when Blender (re)loads the active key configuration, rather than the user picking it."""
    frame = sys._getframe(1)
    while frame is not None:
        code = frame.f_code
        if code.co_name == "keyconfig_init" and os.path.basename(os.path.dirname(code.co_filename)) == "utils":
            return True
        frame = frame.f_back
    return False


def apply_navigation_preferences(prefs=None):
    """Apply the Max-like navigation preferences. Returns the previous values (for restoring them)."""
    inputs = (prefs or bpy.context.preferences).inputs
    previous = {}
    for attr, value in NAVIGATION_PREFERENCES:
        previous[attr] = getattr(inputs, attr)
        setattr(inputs, attr, value)
    return previous


def restore_navigation_preferences(previous, prefs=None):
    inputs = (prefs or bpy.context.preferences).inputs
    for attr, value in previous.items():
        if hasattr(inputs, attr):
            setattr(inputs, attr, value)


def on_preset_loaded(kc, filepath):
    """Called by the preset file once its key configuration exists (the add-on is registered)."""
    fill(kc)
    if _in_keyconfig_init():
        # Startup or a key-map reload (e.g. after changing "Emulate 3 Button Mouse"): nothing was activated.
        return
    if _same_dir(os.path.dirname(filepath), os.path.dirname(ADDON_PRESET)):
        install_user_preset()
    from . import prefs
    addon_prefs = prefs.get()
    if addon_prefs is not None and addon_prefs.apply_navigation:
        addon_prefs.remember_navigation(apply_navigation_preferences())


def activate(report=None):
    """Make Max-Style the active key configuration (what picking it in Preferences > Keymap does)."""
    path = installed_preset_path() or ADDON_PRESET
    return bpy.utils.keyconfig_set(path, report=report)


def restore_on_register():
    """Fill the key configuration the preset created at startup (or that ``unregister`` emptied)."""
    if bpy.context.window_manager.keyconfigs.get(IDNAME) is not None:
        fill(bpy.context.window_manager.keyconfigs.get(IDNAME))


def addon_enabled():
    module = __package__
    return any(addon.module == module for addon in bpy.context.preferences.addons)


def after_unregister():
    """Once the add-on has really been disabled (not reloaded), stop using its empty key configuration."""
    if addon_enabled():
        return None
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.get(IDNAME)
    if kc is not None and not len(kc.keymaps):
        # Removing the active key configuration makes Blender's default active again.
        wm.keyconfigs.remove(kc)
    return None
