# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
The Max-style interface chrome: menu bar, main toolbar, ribbon, Scene Explorer, viewport labels, ViewCube,
time slider and status line (``docs/design/max-ui-chrome.md``).

Every module in this package is registered automatically, in alphabetical order: its ``classes`` tuple is
registered, then its ``register()`` is called (reverse order on unregister). Modules that replace a Blender
header ``draw`` function must restore it in ``unregister()``, and draw Blender's original when
``utils.use_max_chrome()`` is off.
"""

import importlib
import pkgutil

import bpy


def _modules():
    names = sorted(info.name for info in pkgutil.iter_modules(__path__) if not info.name.startswith("_"))
    return [importlib.import_module("." + name, __name__) for name in names]


_registered = []


def register():
    for mod in _modules():
        for cls in getattr(mod, "classes", ()):
            bpy.utils.register_class(cls)
        if hasattr(mod, "register"):
            mod.register()
        _registered.append(mod)


def unregister():
    for mod in reversed(_registered):
        if hasattr(mod, "unregister"):
            mod.unregister()
        for cls in reversed(getattr(mod, "classes", ())):
            bpy.utils.unregister_class(cls)
    _registered.clear()
