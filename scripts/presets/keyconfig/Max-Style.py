# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

# Max-Style key configuration preset.
#
# The key-map itself is built by the "Max-Style Keymap" add-on (`mx_keymap`), which must be enabled.
# This file is shipped twice with identical contents: in the add-on (`mx_keymap/presets/keyconfig/`)
# and in the fork's `scripts/presets/keyconfig/`. See `docs/decisions/0005-keymap.md`.

import os
import sys

import bpy

IDNAME = os.path.splitext(os.path.basename(__file__))[0]
ADDON = "mx_keymap"


def addon_module_name():
    for addon in bpy.context.preferences.addons:
        if addon.module == ADDON or addon.module.endswith("." + ADDON):
            return addon.module
    return None


def load():
    name = addon_module_name()
    if name is None:
        raise RuntimeError(
            "The {:s} keymap needs the \"Max-Style Keymap\" add-on, "
            "enable it in Preferences > Add-ons".format(IDNAME)
        )
    kc = bpy.context.window_manager.keyconfigs.new(IDNAME)
    mod = sys.modules.get(name)
    if mod is not None and getattr(mod, "is_registered", lambda: False)():
        mod.on_preset_loaded(kc, __file__)
    # Otherwise Blender is starting up and has not registered add-ons yet:
    # the add-on fills this (still empty) key configuration when it registers.


if __name__ == "__main__":
    load()
