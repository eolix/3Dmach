# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Key controllers without keys (Bezier Float / Color / Position / Scale, TCB Rotation) and the Position/Rotation/Scale
transform controller, the inverse of :mod:`maxfile.objects.controllers` (overview.md §4.1).

Layout of a key controller in the 2015 corpus files (all 681 Bezier Positions, 578 TCB Rotations, 10,685 Bezier
Scales, the Bezier Colors / Floats of the render environment)::

    0x2035  u32 2: two reference slots, none used
    0x204B  0x2E
    value   0x2501 (float / colour), 0x2503 (position), 0x2504 (rotation), 0x2505 (scale + scale axis)
    0x2500  8 bytes: 0x80000000, 0x7FFFFFFF (the "forever" interval; 355 of 466 Bezier Positions, 3,891 of
            4,176 Bezier Scales, all render-environment colours)
    0x3002  u32 flags (0x20 on colours, 0 otherwise: dominant per class)
    0x3003  8 bytes 0x80000000, 0x80000000
    0x2532, 0x2533, 0x2534  empty
    0x3005  u32 0x186
    0x2535  u32 0
"""

__all__ = ("key_controller", "bezier_float", "bezier_color", "prs", "max_quaternion")

from . import classes
from .chunks import f32, leaf, u32
from .graph import MaxObject

FOREVER = u32(0x80000000, 0x7FFFFFFF)


def key_controller(cls, value_chunk, flags=0) -> MaxObject:
    obj = MaxObject(cls, num_refs=2)
    obj.chunks = [
        value_chunk,
        leaf(0x2500, FOREVER),
        leaf(0x3002, u32(flags)),
        leaf(0x3003, u32(0x80000000, 0x80000000)),
        leaf(0x2532),
        leaf(0x2533),
        leaf(0x2534),
        leaf(0x3005, u32(0x186)),
        leaf(0x2535, u32(0)),
    ]
    return obj


def bezier_float(value) -> MaxObject:
    return key_controller(classes.BEZIER_FLOAT, leaf(0x2501, f32(value)))


def bezier_color(rgb) -> MaxObject:
    # Corpus: 0x3002 = 0x20 on all 912 render-environment Bezier Colors of the 2015 files.
    return key_controller(classes.BEZIER_COLOR, leaf(0x2501, f32(*rgb)), flags=0x20)


def max_quaternion(q):
    """Blender ``(w, x, y, z)`` -> the file's ``x, y, z, w`` of the inverse rotation (overview.md §4.1)."""
    w, x, y, z = q
    n = (w * w + x * x + y * y + z * z) ** 0.5 or 1.0
    w, x, y, z = w / n, x / n, y / n, z / n
    if w < 0.0:     # Same rotation; keep w >= 0 like the corpus values.
        w, x, y, z = -w, -x, -y, -z
    return (-x, -y, -z, w)


def prs(position, rotation, scale) -> MaxObject:
    """Position/Rotation/Scale with Bezier Position, TCB Rotation and Bezier Scale sub-controllers."""
    pos = key_controller(classes.BEZIER_POSITION, leaf(0x2503, f32(*position)))
    rot = key_controller(classes.TCB_ROTATION, leaf(0x2504, f32(*max_quaternion(rotation))))
    # Scale axis: (-0, -0, -0, 1) in 3,545 of 4,176 Bezier Scales (the identity rotation either way).
    scl = key_controller(classes.BEZIER_SCALE, leaf(0x2505, f32(*scale, -0.0, -0.0, -0.0, 1.0)))
    obj = MaxObject(classes.PRS, refs={0: pos, 1: rot, 2: scl}, num_refs=3)
    # Corpus: all 11,824 Position/Rotation/Scale controllers: 0x7230 = 0, 0x7231 = 0, 0x2535 = 0.
    obj.chunks = [leaf(0x7230, u32(0)), leaf(0x7231, u32(0)), leaf(0x2535, u32(0))]
    return obj
