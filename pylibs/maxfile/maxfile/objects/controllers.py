# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Transform controllers: the static (non-animated) value of position, rotation, scale and float controllers.

Layouts from ``docs/format/overview.md`` §4.1, all unverified on real files. Animation keys are ignored
(ROADMAP §2: animation is out of scope for v1).

Return values: position and scale controllers give a ``(x, y, z)`` tuple, rotation controllers a ``(w, x, y, z)``
quaternion, float controllers a ``float``, and Position/Rotation/Scale a :class:`maxfile.transform.Transform`.
"""

from ..chunks import f32s
from ..errors import DecodeError
from ..registry import decoder
from ..transform import Transform, euler_xyz_to_quat, quat_from_max

# Value chunks. Unverified (overview.md §4.1).
CHUNK_FLOAT_VALUE = 0x2501      # f32 (Bezier Float, below 0x7127); also used by Bezier Scale / TCB Zoom
CHUNK_POSITION_VALUE = 0x2503   # f32[3]
CHUNK_ROTATION_VALUE = 0x2504   # f32[4] quaternion, file order (see quat_from_max)
CHUNK_SCALE_VALUE = 0x2505      # Bezier Scale / TCB Zoom alternative to 0x2501
CHUNK_BEZIER_FLOAT = 0x7127     # Bezier Float: container holding 0x2501


def _floats(chunk, count, what):
    if chunk is None:
        raise DecodeError("no {:s} chunk".format(what))
    values = f32s(chunk.data)
    if len(values) < count:
        raise DecodeError("{:s} chunk 0x{:04X} has {:d} float(s), expected {:d}".format(
            what, chunk.type, len(values), count))
    return values


def _is_vec3(value):
    return isinstance(value, tuple) and len(value) == 3


def _is_quat(value):
    return isinstance(value, tuple) and len(value) == 4


def _sub_value(obj, ctx, slot, what, check):
    """Decode the controller in reference ``slot``; None when absent or not decodable (``ctx`` reports why)."""
    ref = ctx.ref(obj, slot)
    if ref is None:
        return None
    value = ctx.decode(ref)
    if value is None:
        return None
    if not check(value):
        ctx.warn("object {:d}: {:s} controller (object {:d}) gave {!r}, not a {:s} value".format(
            obj.index, what, ref.index, value, what))
        return None
    return value


def _three_floats(obj, ctx, what):
    values = []
    for slot, axis in enumerate("XYZ"):
        ref = ctx.ref(obj, slot)
        if ref is None:
            raise DecodeError("no {:s} {:s} controller in reference slot {:d}".format(what, axis, slot))
        value = ctx.decode(ref)
        if not isinstance(value, float):
            raise DecodeError("{:s} {:s} controller (object {:d}) not decoded".format(what, axis, ref.index))
        values.append(value)
    return tuple(values)


def _first_reference(obj, ctx):
    ref = ctx.first_ref(obj)
    if ref is None:
        raise DecodeError("no references")
    return ctx.decode(ref)


@decoder(0x2005, kind="controller.transform", name="Position/Rotation/Scale")
def position_rotation_scale(obj, ctx):
    """Position, rotation and scale from the three sub-controllers."""
    # Unverified (overview.md §4.1): references 0, 1, 2 are the position, rotation and scale controllers.
    return Transform(
        position=_sub_value(obj, ctx, 0, "position", _is_vec3),
        rotation=_sub_value(obj, ctx, 1, "rotation", _is_quat),
        scale=_sub_value(obj, ctx, 2, "scale", _is_vec3),
    )


@decoder(0x2008, 0x442312, kind="controller.position", name="Bezier Position / TCB Position")
def key_position(obj, ctx):
    """Position from the value chunk 0x2503."""
    # Unverified (overview.md §4.1): 0x2503 holds f32[3].
    return tuple(_floats(obj.chunk.find(CHUNK_POSITION_VALUE), 3, "position value")[:3])


@decoder(0xFFEE238A118F7E02, kind="controller.position", name="Position XYZ")
def position_xyz(obj, ctx):
    """Position from three float controllers (references 0, 1, 2)."""
    # Unverified (overview.md §4.1).
    return _three_floats(obj, ctx, "position")


@decoder(0x442313, kind="controller.rotation", name="TCB Rotation")
def tcb_rotation(obj, ctx):
    """Rotation quaternion from the value chunk 0x2504."""
    # Unverified (overview.md §4.1): 0x2504 holds f32[4], reordered by quat_from_max.
    return quat_from_max(_floats(obj.chunk.find(CHUNK_ROTATION_VALUE), 4, "rotation value"))


@decoder(0x2012, kind="controller.rotation", name="Euler XYZ")
def euler_xyz(obj, ctx):
    """Rotation from three float controllers (radians), converted to a quaternion."""
    # Unverified (overview.md §4.1): references 0, 1, 2 are X, Y, Z in radians. The rotation order is also
    # unverified (see euler_xyz_to_quat).
    return euler_xyz_to_quat(*_three_floats(obj, ctx, "rotation"))


@decoder(0xFEEE238B118F7C01, kind="controller.scale", name="Scale XYZ")
def scale_xyz(obj, ctx):
    """Scale from three float controllers (references 0, 1, 2)."""
    # Unverified (overview.md §4.1).
    return _three_floats(obj, ctx, "scale")


@decoder(0x2010, 0x442315, kind="controller.scale", name="Bezier Scale / TCB Zoom")
def key_scale(obj, ctx):
    """Scale from the value chunk 0x2501 or 0x2505."""
    # Unverified (overview.md §4.1): the value is in 0x2501, else 0x2505. Their layout isn't documented; we take
    # the first three floats as the scale, and a single float as a uniform scale.
    chunk = obj.chunk.find(CHUNK_FLOAT_VALUE) or obj.chunk.find(CHUNK_SCALE_VALUE)
    values = _floats(chunk, 1, "scale value")
    if len(values) >= 3:
        return tuple(values[:3])
    return (values[0],) * 3


@decoder(0x2007, kind="controller.float", name="Bezier Float")
def bezier_float(obj, ctx):
    """Float value from 0x7127 -> 0x2501."""
    # Unverified (overview.md §4.1): container 0x7127 holds 0x2501 = f32.
    holder = obj.chunk.find(CHUNK_BEZIER_FLOAT)
    if holder is None:
        raise DecodeError("no 0x{:04X} chunk".format(CHUNK_BEZIER_FLOAT))
    return _floats(holder.find(CHUNK_FLOAT_VALUE), 1, "float value")[0]


@decoder(0x4B4B1002, 0x4B4B1003, kind="controller.list", name="Position / Scale / Rotation List")
def list_controller(obj, ctx):
    """The value of the first sub-controller (the others and the weights are ignored)."""
    # Unverified (overview.md §4.1): the prior-art importer uses the first reference.
    return _first_reference(obj, ctx)


@decoder(0x3A90416731381913, 0x71F11549498702E7, kind="controller.wire", name="Rotation Wire / Float Wire")
def wire_controller(obj, ctx):
    """The value of the first referenced controller (the wire expression is not evaluated)."""
    # Unverified (overview.md §4.1): the prior-art importer uses the first reference.
    return _first_reference(obj, ctx)
