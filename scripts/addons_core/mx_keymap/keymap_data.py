# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Max-style key-map data.

The key-map starts from Blender's own default key-map (``blender_default.py``, left-click select, so every editor
is covered) and overrides the 3D viewport bindings with Max-style ones. Bindings that collide with an override are
removed from the key-maps where they would shadow it; everything else is kept.

This module does not import ``bpy``: it works on the plain key-map data format of ``bl_keymap_utils.io``
(a list of ``(name, {"space_type": ..., "region_type": ...}, {"items": [(idname, event, data), ...]})``),
so it can be tested and diffed outside Blender. ``keyconfig.py`` feeds it Blender's default data.
"""

__all__ = (
    "KEYCONFIG_NAME",
    "QUAD_MENU",
    "base_params",
    "events_conflict",
    "generate_keymaps",
    "find_items",
)

KEYCONFIG_NAME = "Max-Style"

# Provided by the `mx_ui` add-on. When it isn't registered, `wm.call_menu_pie` reports an error and does nothing.
QUAD_MENU = "VIEW3D_MT_mx_quad"

_MODIFIERS = ("shift", "ctrl", "alt", "oskey", "hyper")
_MOUSE_BUTTONS = {
    'LEFTMOUSE', 'MIDDLEMOUSE', 'RIGHTMOUSE', 'BUTTON4MOUSE', 'BUTTON5MOUSE', 'BUTTON6MOUSE', 'BUTTON7MOUSE',
}

# Key-maps active in the 3D viewport in object and edit modes, in which a Max binding placed in "3D View"
# must not be shadowed. Paint, sculpt, particle, text (font) and Grease Pencil modes keep their own keys.
VIEWPORT_KEYMAPS = (
    "3D View",
    "3D View Generic",
    "Object Mode",
    "Object Non-modal",
    "Frames",
    "Mesh",
    "Curve",
    "Curves",
    "Armature",
    "Metaball",
    "Lattice",
    "Point Cloud",
    "Pose",
)

TRANSFORM_TOOL_KEYMAPS = (
    "3D View Tool: Move",
    "3D View Tool: Rotate",
    "3D View Tool: Scale",
    "3D View Tool: Transform",
)

SELECT_TOOL_KEYMAPS = (
    "3D View Tool: Tweak",
    "3D View Tool: Select Box",
    "3D View Tool: Select Circle",
    "3D View Tool: Select Lasso",
)

FALLBACK_TOOL_KEYMAPS = tuple(name + " (fallback)" for name in SELECT_TOOL_KEYMAPS)

_REGION_SELECT_OPERATORS = {"view3d.select_box", "view3d.select_circle", "view3d.select_lasso"}


def base_params(*, use_mouse_emulate_3_button=False):
    """Keyword arguments for ``blender_default.Params`` that the Max-style key-map is built on."""
    return {
        "select_mouse": 'LEFT',
        "use_mouse_emulate_3_button": use_mouse_emulate_3_button,
        # Space is "lock selection" in the viewport; elsewhere it keeps playing animation.
        "spacebar_action": 'PLAY',
        "use_key_activate_tools": False,
        "use_select_all_toggle": False,
        "use_gizmo_drag": True,
        "use_fallback_tool": True,
        "use_v3d_tab_menu": False,
        "use_v3d_shade_ex_pie": False,
        # Middle mouse pans, like Max (and two-finger trackpad pans too).
        "use_v3d_mmb_pan": True,
        "use_alt_tool_or_cursor": False,
        "use_alt_click_leader": False,
        "use_pie_click_drag": False,
        # Alt during a transform passes through to navigation, so Alt+MMB orbits mid-drag.
        "use_alt_navigation": True,
        "use_file_single_click": False,
        "v3d_tilde_action": 'VIEW',
        "v3d_alt_mmb_drag_action": 'RELATIVE',
    }


# ------------------------------------------------------------------------------
# Item helpers

def ev(event_type, value='PRESS', **kwargs):
    """Key-map item event arguments."""
    return {"type": event_type, "value": value, **kwargs}


def op(idname, event, *props):
    return (idname, event, {"properties": list(props)} if props else None)


def op_tool(tool, event, *, cycle=False):
    props = [("name", tool)]
    if cycle:
        props.append(("cycle", True))
    return ("wm.tool_set_by_id", event, {"properties": props})


def _mod_state(event, mod):
    if event.get("any"):
        return -1
    value = event.get(mod, 0)
    if value == -1:
        return -1
    return 1 if value else 0


def _modifiers_overlap(a, b):
    for mod in _MODIFIERS:
        x = _mod_state(a, mod)
        y = _mod_state(b, mod)
        if x != -1 and y != -1 and x != y:
            return False
    return True


def _values_overlap(a, b):
    va = a.get("value", 'PRESS')
    vb = b.get("value", 'PRESS')
    if va == vb or 'ANY' in {va, vb}:
        return True
    # Handling a press stops Blender from generating the click, drag and double-click events that follow it.
    if 'PRESS' in {va, vb}:
        other = vb if va == 'PRESS' else va
        return other in {'CLICK', 'CLICK_DRAG', 'DOUBLE_CLICK'}
    return False


def events_conflict(a, b):
    """True when the key-map events ``a`` and ``b`` can be triggered by the same input."""
    if a["type"] != b["type"]:
        return False
    if a.get("key_modifier", 'NONE') != b.get("key_modifier", 'NONE'):
        return False
    return _modifiers_overlap(a, b) and _values_overlap(a, b)


def find_items(keyconfig_data, keymap_name, idname=None, event_type=None):
    """Items of ``keymap_name`` matching ``idname`` / ``event_type`` (``None`` matches any)."""
    for name, _args, content in keyconfig_data:
        if name != keymap_name:
            continue
        return [
            item for item in content["items"]
            if (idname is None or item[0] == idname) and (event_type is None or item[1]["type"] == event_type)
        ]
    return []


def _keymap_items(keymaps, name):
    try:
        return keymaps[name][2]["items"]
    except KeyError:
        raise KeyError("key-map {!r} not found in the base key-map".format(name)) from None


def _remove_conflicts(keymaps, scope, event):
    for name in scope:
        if name not in keymaps:
            continue
        items = _keymap_items(keymaps, name)
        items[:] = [item for item in items if not events_conflict(item[1], event)]


def _prepend(keymaps, name, new_items, *, scope=()):
    """Put ``new_items`` first in key-map ``name``, removing conflicting items from the key-maps in ``scope``."""
    for item in new_items:
        _remove_conflicts(keymaps, scope, item[1])
    items = _keymap_items(keymaps, name)
    items[:0] = new_items


def _mods_of(event):
    return frozenset(mod for mod in _MODIFIERS if event.get(mod))


def _prop_dict(item):
    data = item[2]
    if not data:
        return {}
    return dict(data.get("properties", ()))


# ------------------------------------------------------------------------------
# Max bindings

def _items_view3d():
    """Viewport bindings that apply in every object and edit mode."""
    return [
        # Navigation.
        op("view3d.rotate", ev('MIDDLEMOUSE', alt=True)),
        op("view3d.move", ev('MIDDLEMOUSE')),
        op("view3d.zoom", ev('MIDDLEMOUSE', ctrl=True, alt=True)),
        op("view3d.zoom", ev('LEFT_BRACKET', repeat=True), ("delta", 1)),
        op("view3d.zoom", ev('RIGHT_BRACKET', repeat=True), ("delta", -1)),
        op("mx_keymap.zoom_extents", ev('Z')),
        op("view3d.view_all", ev('Z', ctrl=True, alt=True), ("center", False)),
        op("view3d.zoom_border", ev('W', ctrl=True)),
        op("mx_keymap.viewport_maximize", ev('W', alt=True)),
        # Views.
        op("mx_keymap.view_axis", ev('T'), ("type", 'TOP')),
        op("mx_keymap.view_axis", ev('B'), ("type", 'BOTTOM')),
        op("mx_keymap.view_axis", ev('F'), ("type", 'FRONT')),
        op("mx_keymap.view_axis", ev('L'), ("type", 'LEFT')),
        op("mx_keymap.view_projection", ev('P'), ("mode", 'PERSP')),
        op("mx_keymap.view_projection", ev('U'), ("mode", 'ORTHO')),
        op("mx_keymap.view_camera", ev('C')),
        # Persistent transform tools. Q cycles the selection region shape like Max, R cycles scale tools.
        op_tool("builtin.select_box", ev('Q'), cycle=True),
        op_tool("builtin.move", ev('W')),
        op_tool("builtin.rotate", ev('E')),
        op_tool("builtin.scale", ev('R'), cycle=True),
        # Sub-object levels.
        *(op("mx_keymap.subobject_level", ev(key), ("level", level))
          for level, key in enumerate(('ONE', 'TWO', 'THREE', 'FOUR', 'FIVE', 'SIX'), start=1)),
        # Display.
        op("view3d.toggle_shading", ev('F3'), ("type", 'WIREFRAME')),
        op("wm.context_toggle", ev('F4'), ("data_path", "space_data.overlay.show_wireframes")),
        op("mx_keymap.toggle_grid", ev('G')),
        op("wm.context_toggle", ev('X'), ("data_path", "space_data.show_gizmo_tool")),
        op("view3d.toggle_xray", ev('X', alt=True)),
        op("view3d.localview", ev('Q', alt=True)),
        # Snaps.
        op("mx_keymap.snap_toggle", ev('S'), ("kind", 'SNAP')),
        op("mx_keymap.snap_toggle", ev('A'), ("kind", 'ANGLE')),
        # Dialogs and editors.
        op("mx_keymap.select_by_name", ev('H')),
        op("mx_keymap.open_editor", ev('M'), ("editor", 'MATERIAL')),
    ]


def _items_view3d_select():
    """Click selection: click = select, Ctrl = add, Alt = remove (Shift toggles, as in Blender)."""
    lmb = 'LEFTMOUSE'
    return [
        op("view3d.select", ev(lmb, 'CLICK'), ("deselect_all", True)),
        op("view3d.select", ev(lmb, 'CLICK', ctrl=True), ("extend", True)),
        op("view3d.select", ev(lmb, 'CLICK', alt=True), ("deselect", True)),
        op("view3d.select", ev(lmb, 'CLICK', shift=True), ("toggle", True)),
    ]


def _items_lock_guard(*values):
    """While the selection is locked these swallow the event, so the selection items after them don't run."""
    return [op("mx_keymap.selection_lock_guard", ev('LEFTMOUSE', value, any=True)) for value in values]


def _items_drag_on_object():
    """Shift-drag clones, drag on an object selects and transforms it (with the Move/Rotate/Scale tools)."""
    return [
        op("mx_keymap.clone_drag", ev('LEFTMOUSE', 'CLICK_DRAG', shift=True)),
        op("mx_keymap.select_drag", ev('LEFTMOUSE', 'CLICK_DRAG')),
    ]


def _items_region_select(operator, value, *, base_props=()):
    """Region selection with Max modifiers: drag = new, Ctrl = add, Alt = remove (Shift adds, as in Blender)."""
    event = ev('LEFTMOUSE', value)
    return [
        op(operator, event, *base_props),
        op(operator, {**event, "ctrl": True}, *base_props, ("mode", 'ADD')),
        op(operator, {**event, "alt": True}, *base_props, ("mode", 'SUB')),
        op(operator, {**event, "shift": True}, *base_props, ("mode", 'ADD')),
    ]


def _items_select_pick(*, passthrough):
    """Press-to-select items of the Tweak tool, through a wrapper that respects the selection lock."""
    lmb = ev('LEFTMOUSE', 'PRESS')
    plain = [("deselect_all", True)]
    if passthrough:
        plain.append(("select_passthrough", True))
    return [
        op("mx_keymap.select_pick", lmb, *plain),
        op("mx_keymap.select_pick", {**lmb, "ctrl": True}, ("extend", True)),
        op("mx_keymap.select_pick", {**lmb, "alt": True}, ("deselect", True)),
        op("mx_keymap.select_pick", {**lmb, "shift": True}, ("toggle", True)),
    ]


def _remap_region_select(keymaps, name):
    """Replace the Blender modifiers of region-select items (Shift add, Ctrl subtract) with Max ones."""
    items = _keymap_items(keymaps, name)
    result = []
    done = set()
    for item in items:
        idname, event, _data = item
        if idname not in _REGION_SELECT_OPERATORS or event["type"] != 'LEFTMOUSE':
            result.append(item)
            continue
        if _mods_of(event):
            # Re-created from the unmodified item below.
            continue
        if idname in done:
            continue
        done.add(idname)
        base_props = [(k, v) for k, v in _prop_dict(item).items() if k != "mode"]
        result.extend(_items_region_select(idname, event["value"], base_props=base_props))
    items[:] = result


def _replace_tweak_select(keymaps, name):
    """Swap the press-to-select items of a Tweak key-map for lock-aware wrappers."""
    items = _keymap_items(keymaps, name)
    selects = [item for item in items if item[0] == "view3d.select" and item[1]["value"] == 'PRESS']
    if not selects:
        return
    passthrough = any(_prop_dict(item).get("select_passthrough") for item in selects)
    rest = [item for item in items if not (item[0] == "view3d.select" and item[1]["value"] == 'PRESS')]
    items[:] = _items_select_pick(passthrough=passthrough) + rest


def _items_select_all(operator):
    return [
        op(operator, ev('A', ctrl=True), ("action", 'SELECT')),
        op(operator, ev('D', ctrl=True), ("action", 'DESELECT')),
        op(operator, ev('I', ctrl=True), ("action", 'INVERT')),
    ]


def _items_select_hierarchy(operator):
    return [
        op(operator, ev('PAGE_UP', repeat=True), ("direction", 'PARENT'), ("extend", False)),
        op(operator, ev('PAGE_DOWN', repeat=True), ("direction", 'CHILD'), ("extend", False)),
    ]


def _bound_operator(keymaps, name, suffix, event_type):
    """The ``*<suffix>`` operator Blender binds to ``event_type`` (no modifiers) in key-map ``name``, if any."""
    for idname, event, _data in _keymap_items(keymaps, name):
        if idname.endswith(suffix) and event["type"] == event_type and not _mods_of(event):
            return idname
    return None


def apply_max_overrides(keyconfig_data):
    """Turn Blender's default key-map data (left-click select) into the Max-style key-map, in place."""
    keymaps = {km[0]: km for km in keyconfig_data}
    viewport = tuple(name for name in VIEWPORT_KEYMAPS if name in keymaps)

    # Select all / none / invert: Ctrl+A / Ctrl+D / Ctrl+I in object mode and every edit mode, because A
    # (angle snap) replaces Blender's select all. Select parent / child: Page Up / Page Down, because [ and ]
    # zoom. Looked up before the Blender keys are removed.
    select_all = {name: _bound_operator(keymaps, name, ".select_all", 'A') for name in viewport}
    select_hierarchy = {name: _bound_operator(keymaps, name, ".select_hierarchy", 'LEFT_BRACKET') for name in viewport}

    # Bindings shared by every viewport mode.
    _prepend(keymaps, "3D View", _items_view3d(), scope=viewport)
    _prepend(keymaps, "3D View", _items_view3d_select(), scope=viewport)
    _prepend(keymaps, "3D View", _items_lock_guard('CLICK', 'DOUBLE_CLICK'))
    # '/' plays animation (Max); Blender's '/' local view is replaced by Alt+Q.
    items = _keymap_items(keymaps, "3D View")
    items[:] = [item for item in items if not (item[0] == "view3d.localview" and item[1]["type"] == 'SLASH')]

    for name, operator in select_all.items():
        if operator is not None:
            _prepend(keymaps, name, _items_select_all(operator), scope=(name,))
    for name, operator in select_hierarchy.items():
        if operator is not None:
            _prepend(keymaps, name, _items_select_hierarchy(operator), scope=(name,))

    # Space: lock selection in the 3D viewport (the operator only polls there), play animation elsewhere.
    _prepend(keymaps, "Frames", [op("mx_keymap.selection_lock_toggle", ev('SPACE'))])
    _prepend(keymaps, "Frames", [op("screen.animation_play", ev('SLASH'))], scope=("Frames",))

    # Object mode. Ctrl+V clones in place (Max's Edit > Clone); Blender's object paste moves to Ctrl+Shift+V.
    _prepend(keymaps, "Object Mode", [
        op("wm.call_menu_pie", ev('RIGHTMOUSE'), ("name", QUAD_MENU)),
        op("mx_keymap.clone", ev('V', ctrl=True)),
    ], scope=("Object Mode",))
    for item in _keymap_items(keymaps, "3D View"):
        if item[0] == "view3d.pastebuffer" and item[1]["type"] == 'V' and _mods_of(item[1]) == {"ctrl"}:
            item[1]["shift"] = True

    # Mesh edit mode.
    lmb_click = ev('LEFTMOUSE', 'CLICK')
    _prepend(keymaps, "Mesh", [
        op("wm.call_menu_pie", ev('RIGHTMOUSE'), ("name", QUAD_MENU)),
        op("mx_keymap.delete_subobject", ev('DEL')),
        op("mesh.dissolve_mode", ev('BACK_SPACE')),
        op("mesh.loop_select", ev('LEFTMOUSE', 'DOUBLE_CLICK')),
        op("mesh.loop_select", ev('LEFTMOUSE', 'DOUBLE_CLICK', ctrl=True), ("extend", True)),
        op("mesh.loop_select", ev('LEFTMOUSE', 'DOUBLE_CLICK', alt=True), ("deselect", True)),
    ], scope=("Mesh",))
    # Border (3) and element (5) levels pick whole boundary loops / connected elements. These only poll at those
    # levels, otherwise the click falls through to the regular selection in "3D View".
    _prepend(keymaps, "Mesh", [
        *(op(idname, event, *props)
          for idname in ("mx_keymap.select_border_pick", "mx_keymap.select_element_pick")
          for event, props in (
              (lmb_click, ()),
              ({**lmb_click, "ctrl": True}, (("extend", True),)),
              ({**lmb_click, "alt": True}, (("deselect", True),)),
        )),
    ])
    _prepend(keymaps, "Mesh", _items_lock_guard('CLICK', 'DOUBLE_CLICK'))

    # Tools: dragging on an object transforms it, dragging on empty space draws a selection rectangle.
    for name in TRANSFORM_TOOL_KEYMAPS:
        if name not in keymaps:
            continue
        items = _keymap_items(keymaps, name)
        items[:] = [
            *_items_drag_on_object(),
            *_items_lock_guard('CLICK_DRAG'),
            *_items_region_select("view3d.select_box", 'CLICK_DRAG'),
        ]
    for name in SELECT_TOOL_KEYMAPS + FALLBACK_TOOL_KEYMAPS:
        if name not in keymaps:
            continue
        _remap_region_select(keymaps, name)
        _replace_tweak_select(keymaps, name)
    for name in FALLBACK_TOOL_KEYMAPS:
        if name in keymaps:
            _prepend(keymaps, name, [*_items_drag_on_object(), *_items_lock_guard('CLICK', 'CLICK_DRAG')])
    for name in SELECT_TOOL_KEYMAPS:
        if name in keymaps:
            values = ('PRESS', 'CLICK_DRAG') if name.endswith("Circle") else ('CLICK', 'CLICK_DRAG')
            _prepend(keymaps, name, _items_lock_guard(*values))

    # Shift-drag on the transform gizmo clones too.
    if "Generic Gizmo Maybe Drag" in keymaps:
        _prepend(keymaps, "Generic Gizmo Maybe Drag", [
            op("mx_keymap.clone_gizmo_drag", ev('LEFTMOUSE', 'CLICK_DRAG', shift=True)),
        ])

    # Shift means "clone" while dragging, not "precision" as in Blender.
    if "Transform Modal Map" in keymaps:
        items = _keymap_items(keymaps, "Transform Modal Map")
        items[:] = [item for item in items if item[0] != "PRECISION"]

    # Window-wide: render, render setup, redo.
    window = tuple(name for name in ("Window", "Screen") if name in keymaps)
    _prepend(keymaps, "Window", [
        op("mx_keymap.open_editor", ev('F10'), ("editor", 'RENDER')),
        op("render.render", ev('Q', shift=True), ("use_viewport", True)),
        op("render.render", ev('F9'), ("use_viewport", True)),
    ], scope=window)
    _prepend(keymaps, "Screen", [
        op("ed.redo", ev('Y', ctrl=True, repeat=True)),
    ], scope=window)

    return keyconfig_data


def generate_keymaps(blender_default, *, use_mouse_emulate_3_button=False):
    """
    Generate the Max-style key-map data.

    :arg blender_default: Blender's ``blender_default.py`` key-map module (loaded with ``bpy.utils.execfile``).
    """
    params = blender_default.Params(**base_params(use_mouse_emulate_3_button=use_mouse_emulate_3_button))
    return apply_max_overrides(blender_default.generate_keymaps(params))
