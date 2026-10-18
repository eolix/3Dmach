# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Small helpers shared by the ``mx_ui`` modules."""

import random
import re
import sys

import bpy

ADDON_ID = __package__

# Operator and module names of the sibling add-on providing live primitives (built separately).
PRIMITIVES_MODULE = "mx_primitives"
PRIMITIVE_OPERATOR = "MESH_OT_mx_primitive_add"
PRIMITIVE_OPERATOR_IDNAME = "mesh.mx_primitive_add"


def use_max_chrome(context=None):
    """True when the Max-style chrome (menu bar, toolbars, headers, status bar) should be drawn."""
    prefs = get_prefs(context)
    return bool(prefs and prefs.use_max_chrome)


def get_prefs(context=None):
    """The add-on preferences, or None when the add-on is not enabled (e.g. while unregistering)."""
    context = context or bpy.context
    addon = context.preferences.addons.get(ADDON_ID)
    return addon.preferences if addon else None


def get_state(context=None):
    """The per-session UI state (`state.MXUI_State`) stored on the window manager."""
    context = context or bpy.context
    wm = context.window_manager
    return getattr(wm, "mx_ui", None) if wm else None


# -----------------------------------------------------------------------------
# Max-style object names: "Box001", "Omni002", ...

_NAME_NUMBER_RE = re.compile(r"^(.*?)(\d{3,})$")


def max_style_name(base, existing=None):
    """
    The next free Max-style name for ``base``: ``base`` followed by a three-digit counter starting at 001.
    ``existing`` is a collection of names in use (default: all objects).
    """
    if existing is None:
        existing = bpy.data.objects.keys()
    used = set()
    for name in existing:
        match = _NAME_NUMBER_RE.match(name)
        if match and match.group(1) == base:
            used.add(int(match.group(2)))
    number = 1
    while number in used:
        number += 1
    return "{:s}{:03d}".format(base, number)


# -----------------------------------------------------------------------------
# Wire colours

def random_wire_color(rng=random):
    """A random, reasonably saturated colour as RGBA, like the object colours Max hands out."""
    import colorsys
    hue = rng.random()
    sat = 0.45 + 0.45 * rng.random()
    val = 0.55 + 0.4 * rng.random()
    return (*colorsys.hsv_to_rgb(hue, sat, val), 1.0)


# -----------------------------------------------------------------------------
# Context helpers

def selected_objects(context):
    return list(getattr(context, "selected_objects", None) or ())


def iter_view3d_spaces(context=None, all_screens=False):
    """Every 3D viewport space in the window's screen (or in all screens)."""
    context = context or bpy.context
    if all_screens:
        screens = bpy.data.screens
    else:
        screen = getattr(context, "screen", None)
        screens = (screen,) if screen else ()
    for screen in screens:
        for area in screen.areas:
            for space in area.spaces:
                if space.type == 'VIEW_3D':
                    yield space


def object_context_override(context, obj, objects=None):
    """Keyword arguments for `context.temp_override` that make ``obj`` active and ``objects`` selected."""
    objects = list(objects) if objects is not None else [obj]
    return {
        "object": obj,
        "active_object": obj,
        "selected_objects": objects,
        "selected_editable_objects": objects,
    }


def make_active(context, obj, deselect_others=True):
    view_layer = context.view_layer
    if deselect_others:
        for other in view_layer.objects:
            if other.select_get(view_layer=view_layer):
                other.select_set(False, view_layer=view_layer)
    obj.select_set(True, view_layer=view_layer)
    view_layer.objects.active = obj


def link_to_scene(context, obj):
    """Link a new object to the active collection (falling back to the scene collection)."""
    collection = context.collection or context.scene.collection
    if collection.library or collection.override_library:
        collection = context.scene.collection
    collection.objects.link(obj)


# -----------------------------------------------------------------------------
# Sibling add-on: live primitives

def primitives_operator_available():
    return hasattr(bpy.types, PRIMITIVE_OPERATOR)


def primitives_module():
    """The ``mx_primitives`` module when that add-on is enabled, else None."""
    if not primitives_operator_available():
        return None
    return sys.modules.get(PRIMITIVES_MODULE)


def is_live_primitive(obj):
    mod = primitives_module()
    if mod is None or obj is None:
        return False
    try:
        return bool(mod.is_live_primitive(obj))
    except Exception:
        return False


# -----------------------------------------------------------------------------
# Sibling add-on: keymap. Its operators are used where they exist, so behaviour matches the hotkeys.

KEYMAP_SUBOBJECT_OPERATOR = "MX_KEYMAP_OT_subobject_level"

# Max sub-object level numbers (keys 1-6) as used by `mx_keymap.subobject_level`.
SUBOBJECT_LEVEL_NUMBERS = {'VERTEX': 1, 'EDGE': 2, 'BORDER': 3, 'POLYGON': 4, 'ELEMENT': 5, 'TOP': 6}


def keymap_operator_available(type_name):
    return hasattr(bpy.types, type_name)


def keymap_subobject_level(context):
    """The sub-object level `mx_keymap` tracks (0 = object level), or None without that add-on."""
    if not keymap_operator_available(KEYMAP_SUBOBJECT_OPERATOR):
        return None
    return getattr(context.window_manager, "mx_keymap_subobject_level", None)


def subobject_operator(layout, level, text="", icon='NONE', depress=False):
    """A button switching to a sub-object level, through `mx_keymap` when it is enabled."""
    if keymap_operator_available(KEYMAP_SUBOBJECT_OPERATOR):
        props = layout.operator("mx_keymap.subobject_level", text=text, icon=icon, depress=depress)
        props.level = SUBOBJECT_LEVEL_NUMBERS[level]
    else:
        props = layout.operator("object.mx_ui_subobject_level", text=text, icon=icon, depress=depress)
        props.level = level
    return props
