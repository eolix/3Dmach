# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Which areas of a screen are parts of the Max window frame, and header ``draw`` overrides.

Blender areas can't carry custom data, so the Max Layout records its areas on the screen (an ID) instead:
``screen["mx_chrome_areas"]`` maps each role (``'MAIN_TOOLBAR'``, ``'EXPLORER'``, ``'TOP'``, ...) to the area's
index in ``screen.areas``, its editor type and its rectangle as fractions of the screen. Areas are saved in
order, so the index survives saving and loading; when the user has changed the layout since (split, joined or
closed areas), each role is matched again to the area of the same editor type whose rectangle is closest.
The result is cached per screen until an area moves or changes type. See
``docs/decisions/0009-max-chrome-frame.md``.

Max editors that are ordinary Blender editors (3D viewports, the Outliner, the Timeline) don't need a mark:
every such editor in the Max Layout *workspace* (``workspace["mx_max_layout"]``) is drawn the Max way, which
also covers the temporary screen of a maximised viewport (Alt+W).

This module is not registered (its name starts with ``_``); the registered modules use it.
"""

import bpy

from .. import utils

WORKSPACE_KEY = "mx_max_layout"
SCREEN_KEY = "mx_chrome_areas"
# Name of the workspace built by `layout.py` (also recognised without the mark, for layouts built before it).
WORKSPACE_NAME = "Max Layout"

# Strips: roles drawn by overriding a rarely used editor, only where the layout marked them.
# Horizontal strips (main toolbar, explorer rows, the first status row) are Info editors shrunk to their header;
# vertical strips are narrow Properties editors showing the Collection tab pinned to the scene collection, where
# Blender draws no panels (see `setup_strip`).
STRIP_TYPES = {
    'MAIN_TOOLBAR': 'INFO',
    'EXPLORER_MENUS': 'INFO',
    'EXPLORER_FIND': 'INFO',
    'EXPLORER_FOOTER': 'INFO',
    'STATUS_ROW': 'INFO',
    'TAB_BAR': 'PROPERTIES',
    'FILTER_BAR': 'PROPERTIES',
}

# Strip drawers, ``kind -> draw(layout, context)``, filled in by the modules drawing them.
DRAWERS = {}

# Rectangle distance (in screen fractions) beyond which a recorded role is considered gone.
_MATCH_LIMIT = 0.3


# -----------------------------------------------------------------------------
# Workspace

def is_max_workspace(workspace):
    if workspace is None:
        return False
    try:
        if workspace.get(WORKSPACE_KEY):
            return True
    except (TypeError, ReferenceError):
        return False
    return workspace.name == WORKSPACE_NAME


def mark_workspace(workspace):
    workspace[WORKSPACE_KEY] = True


def max_context(context):
    """True when ``context`` is in the Max Layout workspace with the Max chrome enabled."""
    return utils.use_max_chrome(context) and is_max_workspace(getattr(context, "workspace", None))


def max_window(context, window):
    return utils.use_max_chrome(context) and window is not None and is_max_workspace(window.workspace)


# -----------------------------------------------------------------------------
# Marking areas

def _screen_rect(screen):
    areas = list(screen.areas)
    if not areas:
        return 0, 0, 1, 1
    x0 = min(a.x for a in areas)
    y0 = min(a.y for a in areas)
    x1 = max(a.x + a.width for a in areas)
    y1 = max(a.y + a.height for a in areas)
    return x0, y0, max(x1 - x0, 1), max(y1 - y0, 1)


def _area_rect(area, screen_rect):
    x0, y0, w, h = screen_rect
    return [(area.x - x0) / w, (area.y - y0) / h, area.width / w, area.height / h]


def mark_areas(screen, roles):
    """Record ``roles`` (``{role: area}``) on ``screen``."""
    screen_rect = _screen_rect(screen)
    areas = list(screen.areas)
    data = {}
    for role, area in roles.items():
        index = next((i for i, a in enumerate(areas) if a == area), -1)
        if index < 0:
            continue
        data[role] = {"index": index, "type": area.type, "rect": _area_rect(area, screen_rect)}
    screen[SCREEN_KEY] = data
    _cache.pop(screen.as_pointer(), None)


def recorded_roles(screen):
    data = screen.get(SCREEN_KEY) if screen is not None else None
    if not data:
        return {}
    return {role: data[role].to_dict() for role in data.keys()}


def _signature(screen):
    return tuple((a.as_pointer(), a.type, a.x, a.y, a.width, a.height) for a in screen.areas)


# screen pointer -> (signature, {area pointer: role})
_cache = {}


def resolve_roles(screen):
    """``{area pointer: role}`` for the areas of ``screen`` that the Max Layout recorded."""
    if screen is None:
        return {}
    key = screen.as_pointer()
    signature = _signature(screen)
    cached = _cache.get(key)
    if cached is not None and cached[0] == signature:
        return cached[1]
    result = {}
    recorded = recorded_roles(screen)
    if recorded:
        areas = list(screen.areas)
        screen_rect = _screen_rect(screen)
        rects = [_area_rect(a, screen_rect) for a in areas]
        taken = set()
        for role, entry in recorded.items():
            best, best_dist = None, _MATCH_LIMIT
            for i, area in enumerate(areas):
                if area.type != entry.get("type") or i in taken:
                    continue
                dist = sum(abs(a - b) for a, b in zip(rects[i], entry.get("rect", ())))
                if i == entry.get("index"):
                    dist *= 0.5
                if dist < best_dist:
                    best, best_dist = i, dist
            if best is not None:
                taken.add(best)
                result[areas[best].as_pointer()] = role
    _cache[key] = (signature, result)
    return result


def area_role(screen, area):
    if area is None or screen is None:
        return None
    try:
        return resolve_roles(screen).get(area.as_pointer())
    except ReferenceError:
        return None


def find_area(screen, role):
    """The area recorded for ``role`` in ``screen``, or None."""
    if screen is None:
        return None
    pointers = {ptr for ptr, r in resolve_roles(screen).items() if r == role}
    return next((a for a in screen.areas if a.as_pointer() in pointers), None)


def strip_kind(context):
    """The strip kind of ``context.area`` when it is a Max strip being drawn with the chrome on, else None."""
    area = getattr(context, "area", None)
    if area is None or not utils.use_max_chrome(context):
        return None
    role = area_role(getattr(context, "screen", None), area)
    if role in STRIP_TYPES and STRIP_TYPES[role] == area.type:
        return role
    return None


def explorer_space(context):
    """The Scene Explorer's Outliner space in the current screen (the recorded one, else the first Outliner)."""
    screen = getattr(context, "screen", None)
    if screen is None:
        return None
    area = find_area(screen, 'EXPLORER')
    if area is None or area.type != 'OUTLINER':
        area = next((a for a in screen.areas if a.type == 'OUTLINER'), None)
    return area.spaces.active if area is not None else None


def clear_cache():
    _cache.clear()


# -----------------------------------------------------------------------------
# Strip editors

def setup_strip(area, kind):
    """Set up ``area`` as a strip of ``kind``: change its editor type and settings (no screen operators)."""
    area.type = STRIP_TYPES[kind]
    space = area.spaces.active
    if area.type == 'PROPERTIES':
        # The Collection tab pinned to the scene's own collection: Blender's collection panels all poll False
        # for it, so the editor shows only the strip panel.
        for prop in space.bl_rna.properties:
            if prop.identifier.startswith("show_properties_"):
                setattr(space, prop.identifier, prop.identifier == "show_properties_collection")
        pin_strip(space, bpy.context.scene)
        space.show_region_header = False
    else:
        space.show_region_header = True


def pin_strip(space, scene):
    if scene is None:
        return
    space.pin_id = scene.collection
    space.use_pin_id = True
    space.context = 'COLLECTION'


def strip_needs_repin(space, scene):
    return scene is not None and (space.pin_id != scene.collection or space.context != 'COLLECTION')


# -----------------------------------------------------------------------------
# Header draw overrides that keep functions other add-ons appended

def _base_index(cls, funcs):
    suffix = cls.__name__ + ".draw"
    for i, func in enumerate(funcs):
        if getattr(func, "__qualname__", "").endswith(suffix):
            return i
    return 0


def override_draw(cls, draw_max):
    """
    Replace the original ``draw`` of the UI class ``cls`` by a function calling ``draw_max(self, context)`` and,
    when that returns False, the original. Functions appended to the class by other add-ons keep running.
    """
    funcs = cls._dyn_ui_initialize()
    index = _base_index(cls, funcs)
    original = funcs[index]

    def draw(self, context):
        if not draw_max(self, context):
            original(self, context)

    draw._mx_original = original
    draw.__qualname__ = "mx_override_" + cls.__name__
    funcs[index] = draw
    return draw


def restore_draw(cls, override):
    funcs = cls._dyn_ui_initialize()
    for i, func in enumerate(funcs):
        if func is override:
            funcs[i] = override._mx_original
            return True
    return False
