# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Session state of the Max window frame (``WindowManager.mx_ui_frame``): the mini-listener, the status line's
transform type-in fields, the active viewport navigation mode and the ViewCube switch.

The transform type-in (X / Y / Z) fields read and write the selection directly through property getters and
setters: position, rotation or scale depending on the active tool, as in Max. In "Offset" mode they read 0
(100 % for scale) and typing a value moves the selection by it.
"""

import math
import traceback

import bpy
from bpy.props import BoolProperty, FloatProperty, PointerProperty, StringProperty
from bpy.types import PropertyGroup

# -----------------------------------------------------------------------------
# Mini-listener (Max's MAXScript mini-listener runs Python here)

LISTENER_NAME = "<listener>"


def listener_namespace(context):
    import mathutils
    return {
        "bpy": bpy,
        "C": context,
        "D": bpy.data,
        "math": math,
        "mathutils": mathutils,
        "Vector": mathutils.Vector,
    }


def run_listener(code, context=None):
    """
    Run one line of Python. Returns ``(ok, text)``: the value of an expression (``repr``), "OK" for a
    statement, or the error message.
    """
    context = context or bpy.context
    code = code.strip()
    if not code:
        return True, ""
    namespace = listener_namespace(context)
    try:
        try:
            compiled = compile(code, LISTENER_NAME, 'eval')
        except SyntaxError:
            compiled = None
        if compiled is not None:
            return True, repr(eval(compiled, namespace))
        exec(compile(code, LISTENER_NAME, 'exec'), namespace)
        return True, "OK"
    except Exception as ex:
        traceback.print_exc()
        return False, "-- {:s}: {:s}".format(type(ex).__name__, str(ex))


def _listener_update(self, context):
    code = self.listener_input
    if not code.strip():
        return
    ok, text = run_listener(code, context)
    self.listener_result = text
    self.listener_ok = ok


# -----------------------------------------------------------------------------
# Transform type-in

def transform_kind(context):
    """'LOCATION', 'ROTATION' or 'SCALE', from the active tool, like Max's type-in follows the transform mode."""
    try:
        tool = context.workspace.tools.from_space_view3d_mode(context.mode, create=False)
    except (AttributeError, TypeError, RuntimeError):
        tool = None
    idname = tool.idname if tool is not None else ""
    if idname == "builtin.rotate":
        return 'ROTATION'
    if idname in {"builtin.scale", "builtin.scale_cage"}:
        return 'SCALE'
    return 'LOCATION'


def transform_targets(context):
    """Objects the type-in fields edit: the selected objects, active first (object mode only)."""
    if getattr(context, "mode", 'OBJECT') != 'OBJECT':
        return []
    view_layer = getattr(context, "view_layer", None)
    if view_layer is None:
        return []
    active = view_layer.objects.active
    selected = [obj for obj in view_layer.objects if obj.select_get(view_layer=view_layer)]
    if active is not None and active in selected:
        selected.remove(active)
        selected.insert(0, active)
    return selected


def _read(obj, kind, axis):
    if kind == 'LOCATION':
        return obj.location[axis]
    if kind == 'ROTATION':
        if obj.rotation_mode in {'QUATERNION', 'AXIS_ANGLE'}:
            return obj.matrix_basis.to_euler()[axis]
        return obj.rotation_euler[axis]
    return obj.scale[axis] * 100.0


def _write(obj, kind, axis, value, offset):
    if kind == 'LOCATION':
        obj.location[axis] = obj.location[axis] + value if offset else value
    elif kind == 'ROTATION':
        if obj.rotation_mode in {'QUATERNION', 'AXIS_ANGLE'}:
            return
        obj.rotation_euler[axis] = obj.rotation_euler[axis] + value if offset else value
    else:
        obj.scale[axis] = obj.scale[axis] * value / 100.0 if offset else value / 100.0


def _neutral(kind):
    return 100.0 if kind == 'SCALE' else 0.0


def _make_accessors(kind, axis):
    def get(self):
        context = bpy.context
        if self.coord_offset:
            return _neutral(kind)
        targets = transform_targets(context)
        return _read(targets[0], kind, axis) if targets else _neutral(kind)

    def set(self, value):
        context = bpy.context
        targets = transform_targets(context)
        offset = self.coord_offset
        if offset and value == _neutral(kind):
            return
        for obj in targets:
            if obj.is_editable:
                _write(obj, kind, axis, value, offset)
        if targets:
            try:
                bpy.ops.ed.undo_push(message="Transform Type-In")
            except RuntimeError:
                pass
    return get, set


def _coord_props():
    props = {}
    specs = (
        ('LOCATION', "coord", {'subtype': 'DISTANCE', 'unit': 'LENGTH', 'precision': 3}),
        ('ROTATION', "rot", {'subtype': 'ANGLE', 'unit': 'ROTATION', 'precision': 3}),
        ('SCALE', "scale", {'subtype': 'NONE', 'precision': 1}),
    )
    for kind, prefix, kwargs in specs:
        for axis, letter in enumerate("xyz"):
            get, set = _make_accessors(kind, axis)
            props[prefix + "_" + letter] = FloatProperty(
                name=letter.upper(),
                description="{:s} {:s} of the selection (Absolute), or the amount to add (Offset)".format(
                    letter.upper(), kind.lower()),
                get=get, set=set, step=10, **kwargs)
    return props


def coord_property_names(kind):
    prefix = {'LOCATION': "coord", 'ROTATION': "rot", 'SCALE': "scale"}[kind]
    return [prefix + "_" + letter for letter in "xyz"]


# -----------------------------------------------------------------------------

class MXUI_PG_frame_state(PropertyGroup):
    __annotations__ = {
        "listener_input": StringProperty(
            name="Mini-Listener",
            description="Type a line of Python and press Enter to run it (Max's MAXScript mini-listener)",
            update=_listener_update, options={'SKIP_SAVE'}),
        "listener_result": StringProperty(
            name="Listener Result", description="Result of the last line run in the mini-listener",
            options={'SKIP_SAVE'}),
        "listener_ok": BoolProperty(default=True, options={'SKIP_SAVE'}),
        "coord_offset": BoolProperty(
            name="Absolute/Offset Mode Transform Type-In",
            description="Off: the fields show and set the selection's transform. On: typed values are added to it",
            options={'SKIP_SAVE'}),
        "nav_mode": StringProperty(
            name="Navigation Mode", description="The active viewport navigation mode", options={'SKIP_SAVE'}),
        "show_viewcube": BoolProperty(
            name="Show the ViewCube", description="Show the ViewCube in the Max viewports", default=True),
        "show_world_axis": BoolProperty(
            name="Display World Axis", description="Show the world axis tripod in the Max viewports", default=True),
        **_coord_props(),
    }


def get(context=None):
    context = context or bpy.context
    wm = getattr(context, "window_manager", None)
    return getattr(wm, "mx_ui_frame", None) if wm is not None else None


classes = (
    MXUI_PG_frame_state,
)


def register():
    bpy.types.WindowManager.mx_ui_frame = PointerProperty(type=MXUI_PG_frame_state)


def unregister():
    del bpy.types.WindowManager.mx_ui_frame
