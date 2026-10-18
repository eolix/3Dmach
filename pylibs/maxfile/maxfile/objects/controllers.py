# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Transform controllers: the static (non-animated) value of position, rotation, scale and float controllers.

Layouts from ``docs/format/overview.md`` §4.1, verified on the local corpus. Animation keys are ignored
(ROADMAP §2: animation is out of scope for v1).

Return values: position and scale controllers give a ``(x, y, z)`` tuple, rotation controllers a ``(w, x, y, z)``
quaternion, float controllers a ``float``, and Position/Rotation/Scale a :class:`maxfile.transform.Transform`.
"""

from ..chunks import f32s
from ..errors import DecodeError
from ..registry import decoder
from ..transform import Transform, euler_xyz_to_quat, quat_from_max

# Value chunks: the controller's value at the time of saving, present whether or not it has keys (keys are in
# 0x2520-0x2528, e.g. 0x2525 Bezier Float, 0x2526 Bezier Position / Point3, 0x2522 TCB Rotation, 0x2528 Bezier
# Scale). Verified on the corpus: every Bezier / TCB / Linear controller has exactly one of these.
CHUNK_FLOAT_VALUE = 0x2501      # f32 (Bezier / Linear Float); f32[3] in Bezier Point3 / Bezier Color
CHUNK_POSITION_VALUE = 0x2503   # f32[3]
CHUNK_ROTATION_VALUE = 0x2504   # f32[4] quaternion, file order (see quat_from_max)
CHUNK_SCALE_VALUE = 0x2505      # f32[3] scale, then f32[4] scale-axis quaternion (Bezier / TCB Scale)
CHUNK_BEZIER_FLOAT = 0x7127     # Bezier Float in some objects (7,287 of 222,296): container holding 0x2501


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


@decoder(0x2005, kind="controller.transform", name="Position/Rotation/Scale", superclass_id=0x9008, verified=True)
def position_rotation_scale(obj, ctx):
    """Position, rotation and scale from the three sub-controllers."""
    # Verified: references 0, 1, 2 hold position, rotation and scale controllers (superclasses 0x900B / C / D).
    return Transform(
        position=_sub_value(obj, ctx, 0, "position", _is_vec3),
        rotation=_sub_value(obj, ctx, 1, "rotation", _is_quat),
        scale=_sub_value(obj, ctx, 2, "scale", _is_vec3),
    )


@decoder(0x2008, 0x442312, kind="controller.position", name="Bezier Position / TCB Position", superclass_id=0x900B,
         verified=True)
def key_position(obj, ctx):
    """Position from the value chunk 0x2503."""
    return tuple(_floats(obj.chunk.find(CHUNK_POSITION_VALUE), 3, "position value")[:3])


@decoder(0xFFEE238A118F7E02, kind="controller.position", name="Position XYZ", superclass_id=0x900B, verified=True)
def position_xyz(obj, ctx):
    """Position from three float controllers (references 0, 1, 2)."""
    return _three_floats(obj, ctx, "position")


@decoder(0x442313, kind="controller.rotation", name="TCB Rotation", superclass_id=0x900C, verified=True)
def tcb_rotation(obj, ctx):
    """Rotation quaternion from the value chunk 0x2504 (component order and sign: see quat_from_max)."""
    return quat_from_max(_floats(obj.chunk.find(CHUNK_ROTATION_VALUE), 4, "rotation value"))


@decoder(0x2012, kind="controller.rotation", name="Euler XYZ", superclass_id=0x900C, verified=True)
def euler_xyz(obj, ctx):
    """Rotation from three float controllers (radians), converted to a quaternion."""
    # References 0, 1, 2 are X, Y, Z float controllers in radians (verified); the rotation order is unverified
    # (see euler_xyz_to_quat).
    return euler_xyz_to_quat(*_three_floats(obj, ctx, "rotation"))


@decoder(0xFEEE238B118F7C01, kind="controller.scale", name="ScaleXYZ", superclass_id=0x900D, verified=True)
def scale_xyz(obj, ctx):
    """Scale from three float controllers (references 0, 1, 2)."""
    return _three_floats(obj, ctx, "scale")


@decoder(0x2010, 0x442315, kind="controller.scale", name="Bezier Scale / TCB Scale", superclass_id=0x900D,
         verified=True)
def key_scale(obj, ctx):
    """Scale from the value chunk 0x2505 (the scale-axis rotation that follows it is ignored)."""
    return tuple(_floats(obj.chunk.find(CHUNK_SCALE_VALUE), 3, "scale value")[:3])


@decoder(0x2007, 0x2001, kind="controller.float", name="Bezier / Linear Float", superclass_id=0x9003,
         verified=True)
def bezier_float(obj, ctx):
    """Float value from 0x2501 (or 0x7127 -> 0x2501)."""
    chunk = obj.chunk.find(CHUNK_FLOAT_VALUE)
    if chunk is None:
        holder = obj.chunk.find(CHUNK_BEZIER_FLOAT)
        chunk = holder.find(CHUNK_FLOAT_VALUE) if holder is not None and holder.is_container else None
    return _floats(chunk, 1, "float value")[0]


@decoder(0x200A, 0x2011, kind="controller.point3", name="Bezier Point3 / Bezier Color", superclass_id=0x9005,
         verified=True)
def bezier_point3(obj, ctx):
    """Three floats from 0x2501 (colours are 0-1)."""
    return tuple(_floats(obj.chunk.find(CHUNK_FLOAT_VALUE), 3, "point3 value")[:3])


@decoder(0x4B4B1002, kind="controller.list", name="Position List", superclass_id=0x900B)
@decoder(0x4B4B1003, kind="controller.list", name="Rotation List", superclass_id=0x900C)
@decoder(0x4B4B1004, kind="controller.list", name="Scale List", superclass_id=0x900D)
@decoder(0x4B4B1000, kind="controller.list", name="Float List", superclass_id=0x9003)
@decoder(0x4B4B1001, kind="controller.list", name="Point3 List", superclass_id=0x9005)
def list_controller(obj, ctx):
    """The value of the first sub-controller (the others and the weights are ignored)."""
    # Simplification: the first reference is the first list entry; layered lists are not summed.
    return _first_reference(obj, ctx)


@decoder(0x3A90416731381913, kind="controller.wire", name="Rotation Wire", superclass_id=0x900C)
@decoder(0x71F11549498702E7, kind="controller.wire", name="Float Wire", superclass_id=0x9003)
def wire_controller(obj, ctx):
    """The value of the first referenced controller (the wire expression is not evaluated)."""
    # Guess (from the prior-art importer): the wired value is the first reference's; the expression is ignored.
    return _first_reference(obj, ctx)
