# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Tiny vector / quaternion / matrix helpers, so :mod:`maxfile` doesn't depend on ``mathutils`` or NumPy.

Conventions used throughout :mod:`maxfile`:

- vectors are ``(x, y, z)`` tuples of floats;
- quaternions are ``(w, x, y, z)`` tuples;
- matrices are 4x4 tuples of rows for **column vectors** (``M @ v``, translation in the last column), the same
  convention as Blender's ``mathutils.Matrix``, so ``mathutils.Matrix(m)`` gives the same transform.

How Max's on-disk rotations map onto these conventions is not verified yet (overview.md §4.1, "To verify" #6).
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

    Whether Max's "Euler XYZ" controller uses this order and sign is not verified (overview.md §4.1).
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
    Reorder a quaternion as stored in the file (four ``f32``) into ``(w, x, y, z)``.

    Unverified (overview.md §4.1): the prior-art importer uses ``(w, x, y, z) = (q[3], q[2], q[1], q[0])``.
    Whether that is right, and whether Max's rotation sign matches Blender's, must be checked on a reference export.
    """
    return (q[3], q[2], q[1], q[0])


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
        """``T @ R @ S``. The composition order is our convention, not verified against Max."""
        return compose(self.position, self.rotation, self.scale)

    def is_empty(self) -> bool:
        return self.position is None and self.rotation is None and self.scale is None
