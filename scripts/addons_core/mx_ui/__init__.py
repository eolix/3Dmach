# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Max-style interface (ROADMAP Phase 1b): quad menu, command panel, freeze, scene explorer, theme,
startup layout and units setup.

The add-on works on a stock Blender 5.2 and is meant to ship enabled by default in the fork.
See ``docs/decisions/0007-max-ui.md`` for the design choices.
"""

bl_info = {
    "name": "Max-Style Interface",
    "author": "PROJECT_NAME Authors",
    "version": (0, 1, 0),
    "blender": (5, 2, 0),
    "location": "3D Viewport right-click, Properties > Tool tab, Top bar",
    "description": "Quad menu, command panel, freeze, theme and four-viewport layout in a Max-style workflow",
    "warning": "Early development",
    "category": "Interface",
}

if "bpy" in locals():
    import importlib
    for _mod in _modules:
        importlib.reload(_mod)
    del _mod

import bpy

from . import (
    utils,
    placeholder,
    state,
    prefs,
    modifier_map,
    freeze,
    wirecolor,
    units,
    layers,
    groups,
    quad_menu,
    topbar,
    layout,
    theme,
)
from . import command_panel
from . import chrome

# Registration order matters: property groups before the classes that point to them.
_modules = (
    utils,
    placeholder,
    state,
    prefs,
    modifier_map,
    freeze,
    wirecolor,
    units,
    layers,
    groups,
    quad_menu,
    command_panel,
    topbar,
    layout,
    theme,
    chrome,
)


def register():
    for mod in _modules:
        for cls in getattr(mod, "classes", ()):
            bpy.utils.register_class(cls)
        if hasattr(mod, "register"):
            mod.register()


def unregister():
    for mod in reversed(_modules):
        if hasattr(mod, "unregister"):
            mod.unregister()
        for cls in reversed(getattr(mod, "classes", ())):
            bpy.utils.unregister_class(cls)
