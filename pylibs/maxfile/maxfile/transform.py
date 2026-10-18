# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Tiny vector / quaternion / matrix helpers, so :mod:`maxfile` doesn't depend on ``mathutils`` or NumPy.

Conventions used throughout :mod:`maxfile`:

- vectors are ``(x, y, z)`` tuples of floats;
- quaternions are ``(w, x, y, z)`` tuples;
- matrices are 4x4 tuples of rows for **column vectors** (``M @ v``, translation in the last column), the same
  convention as Blender's ``mathutils.Matrix``, so ``mathutils.Matrix(m)`` gives the same transform.

How Max's on-disk rotations map onto these conventions was verified against the node matrices that the Skin
modifier stores (overview.md §4.1): see :func:`quat_from_max`.
"""

__all__ = (
    "Vec3",
    "Quat",
    "Matrix4",
    "IDENTITY",
    "Transform",
    "quat_to_matrix3",
    "euler_xyz_to_quat",
    "compose",
    "matmul",
    "quat_from_max",
    "matrix3_to_quat",
    "look_at_matrix3",
)

import dataclasses
import math

Vec3 = tuple[float, float, float]
Quat = tuple[float, float, float, float]
Matrix4 = tuple[tuple[float, float, float, float], ...]

IDENTITY: Matrix4 = (
    (1.0, 0.0, 0.0, 0.0),
    (0.0, 1.0, 0.0, 0.0),
    (0.0, 0.0, 1.0, 0.0),
    (0.0, 0.0, 0.0, 1.0),
)


def quat_to_matrix3(q: Quat) -> tuple[tuple[float, float, float], ...]:
    """Rotation matrix (rows, column-vector convention) of a quaternion ``(w, x, y, z)``; normalises first."""
    w, x, y, z = q
    n = math.sqrt(w * w + x * x + y * y + z * z)
    if n == 0.0:
        return ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    w, x, y, z = w / n, x / n, y / n, z / n
    return (
        (1.0 - 2.0 * (y * y + z * z), 2.0 * (x * y - w * z), 2.0 * (x * z + w * y)),
        (2.0 * (x * y + w * z), 1.0 - 2.0 * (x * x + z * z), 2.0 * (y * z - w * x)),
        (2.0 * (x * z - w * y), 2.0 * (y * z + w * x), 1.0 - 2.0 * (x * x + y * y)),
    )


def euler_xyz_to_quat(x: float, y: float, z: float) -> Quat:
    """
    Quaternion ``(w, x, y, z)`` for rotating about X, then Y, then Z (fixed axes), angles in radians.

    Verified for Max's "Euler XYZ" controller: radians, and the sign (on 11 corpus scenes whose skinned mesh nodes
    use Euler rotations, negated angles don't reproduce the Skin modifier's stored node matrix). The order isn't
    discriminated by those scenes (single-axis rotations); fixed-axes XYZ is assumed.
    """
    cx, sx = math.cos(x * 0.5), math.sin(x * 0.5)
    cy, sy = math.cos(y * 0.5), math.sin(y * 0.5)
    cz, sz = math.cos(z * 0.5), math.sin(z * 0.5)
    return (
        cx * cy * cz + sx * sy * sz,
        sx * cy * cz - cx * sy * sz,
        cx * sy * cz + sx * cy * sz,
        cx * cy * sz - sx * sy * cz,
    )


def quat_from_max(q) -> Quat:
    """
    A quaternion as stored in the file (four ``f32``) as ``(w, x, y, z)`` in Blender's convention.

    Files store ``x, y, z, w`` of the *inverse* rotation, so the vector part is negated: ``(w, x, y, z) =
    (q[3], -q[0], -q[1], -q[2])``. Verified against the node matrices the Skin modifier keeps (4x3 matrices, no
    quaternions): with this mapping 71 of the 75 skinned nodes of the corpus reproduce the stored matrix, including
    every node with a non-trivial rotation; the prior-art mapping ``(q[3], q[2], q[1], q[0])`` fails on 10 of them.
    The remaining 4 are nodes that moved after skinning.
    """
    return (q[3], -q[0], -q[1], -q[2])


def matrix3_to_quat(m) -> Quat:
    """Quaternion ``(w, x, y, z)`` of a rotation matrix (rows, column-vector convention)."""
    trace = m[0][0] + m[1][1] + m[2][2]
    if trace > 0.0:
        s = math.sqrt(trace + 1.0) * 2.0
        return (0.25 * s, (m[2][1] - m[1][2]) / s, (m[0][2] - m[2][0]) / s, (m[1][0] - m[0][1]) / s)
    if m[0][0] > m[1][1] and m[0][0] > m[2][2]:
        s = math.sqrt(1.0 + m[0][0] - m[1][1] - m[2][2]) * 2.0
        return ((m[2][1] - m[1][2]) / s, 0.25 * s, (m[0][1] + m[1][0]) / s, (m[0][2] + m[2][0]) / s)
    if m[1][1] > m[2][2]:
        s = math.sqrt(1.0 + m[1][1] - m[0][0] - m[2][2]) * 2.0
        return ((m[0][2] - m[2][0]) / s, (m[0][1] + m[1][0]) / s, 0.25 * s, (m[1][2] + m[2][1]) / s)
    s = math.sqrt(1.0 + m[2][2] - m[0][0] - m[1][1]) * 2.0
    return ((m[1][0] - m[0][1]) / s, (m[0][2] + m[2][0]) / s, (m[1][2] + m[2][1]) / s, 0.25 * s)


def look_at_matrix3(eye: Vec3, target: Vec3, roll: float = 0.0):
    """
    World rotation (rows, column vectors) of an object at ``eye`` whose local -Z axis points at ``target``, local
    +Y up as far as possible (world +Z up; world +Y when looking straight up or down), turned by ``roll`` radians
    about the viewing axis. Returns None when ``eye`` and ``target`` coincide.
    """
    z = tuple(e - t for e, t in zip(eye, target))
    length = math.sqrt(sum(c * c for c in z))
    if length == 0.0:
        return None
    z = tuple(c / length for c in z)
    up = (0.0, 0.0, 1.0) if abs(z[2]) < 0.999999 else (0.0, 1.0, 0.0)
    x = (up[1] * z[2] - up[2] * z[1], up[2] * z[0] - up[0] * z[2], up[0] * z[1] - up[1] * z[0])
    n = math.sqrt(sum(c * c for c in x))
    x = tuple(c / n for c in x)
    y = (z[1] * x[2] - z[2] * x[1], z[2] * x[0] - z[0] * x[2], z[0] * x[1] - z[1] * x[0])
    if roll:
        c, s = math.cos(roll), math.sin(roll)
        x, y = tuple(c * a + s * b for a, b in zip(x, y)), tuple(-s * a + c * b for a, b in zip(x, y))
    return tuple((x[i], y[i], z[i]) for i in range(3))


def compose(position: Vec3 | None, rotation: Quat | None, scale: Vec3 | None) -> Matrix4:
    """``T @ R @ S`` as a 4x4 matrix; None components are the identity."""
    px, py, pz = position if position is not None else (0.0, 0.0, 0.0)
    sx, sy, sz = scale if scale is not None else (1.0, 1.0, 1.0)
    r = quat_to_matrix3(rotation) if rotation is not None else ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    return (
        (r[0][0] * sx, r[0][1] * sy, r[0][2] * sz, px),
        (r[1][0] * sx, r[1][1] * sy, r[1][2] * sz, py),
        (r[2][0] * sx, r[2][1] * sy, r[2][2] * sz, pz),
        (0.0, 0.0, 0.0, 1.0),
    )


def matmul(a: Matrix4, b: Matrix4) -> Matrix4:
    """The matrix product ``a @ b``."""
    return tuple(
        tuple(sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4))
        for i in range(4)
    )


@dataclasses.dataclass(frozen=True, slots=True)
class Transform:
    """Position / rotation / scale. A None component wasn't stored or couldn't be decoded (identity in maths)."""
    position: Vec3 | None = None
    rotation: Quat | None = None    # (w, x, y, z)
    scale: Vec3 | None = None

    def matrix(self) -> Matrix4:
        """``T @ R @ S`` (verified with the Skin matrices above, including nodes with object offsets)."""
        return compose(self.position, self.rotation, self.scale)

    def is_empty(self) -> bool:
        return self.position is None and self.rotation is None and self.scale is None
