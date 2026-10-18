# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Math of Max-style interactive creation, with no Blender dependency (vectors are 3-tuples).

The operator turns mouse events into view rays and feeds them to a :class:`CreationSession`, which knows the
creation steps of each primitive kind (drag the base, then move for the height, ...) and turns rays into the
object's location and parameters. Everything here can be tested without a viewport.
"""

__all__ = (
    "Plane",
    "construction_plane",
    "ray_plane",
    "closest_on_line",
    "snap",
    "STEPS",
    "CreationSession",
)

import math

# Creation steps per kind. The first step is a drag (press, move, release); every later step is a mouse move
# confirmed by a click.
#   RECT    -- drag a rectangle from corner to corner on the construction plane (Ctrl: square).
#   RADIUS  -- drag from the centre outwards.
#   HEIGHT  -- move the mouse up or down.
#   RADIUS2 -- move the mouse towards or away from the centre.
STEPS = {
    "BOX": ("RECT", "HEIGHT"),
    "PLANE": ("RECT",),
    "PYRAMID": ("RECT", "HEIGHT"),
    "SPHERE": ("RADIUS",),
    "GEOSPHERE": ("RADIUS",),
    "TEST_SHAPE": ("RADIUS",),
    "CYLINDER": ("RADIUS", "HEIGHT"),
    "CONE": ("RADIUS", "HEIGHT", "RADIUS2"),
    "TUBE": ("RADIUS", "RADIUS2", "HEIGHT"),
    "TORUS": ("RADIUS", "RADIUS2"),
}

# Parameters set by the RECT step (along the plane's X, along its Y) and by the RADIUS step.
_RECT_PARAMS = {"BOX": ("width", "length"), "PLANE": ("width", "length"), "PYRAMID": ("width", "depth")}
_RADIUS_PARAM = {"CONE": "radius1", "TUBE": "radius1", "TORUS": "radius1"}

# Below this size (in Blender units) the first drag doesn't create anything, as in Max.
MIN_SIZE = 1e-6


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _scale(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _normalized(a):
    length = math.sqrt(_dot(a, a))
    return _scale(a, 1.0 / length) if length else a


def _axis_snap(v):
    """The world axis (with sign) closest to ``v``."""
    index = max(range(3), key=lambda i: abs(v[i]))
    result = [0.0, 0.0, 0.0]
    result[index] = 1.0 if v[index] >= 0.0 else -1.0
    return tuple(result)


class Plane:
    """A construction plane: an origin and an orthonormal, right-handed basis (``x_axis``, ``y_axis``, ``normal``)."""

    __slots__ = ("origin", "x_axis", "y_axis", "normal")

    def __init__(self, origin, x_axis, y_axis, normal):
        self.origin = tuple(origin)
        self.x_axis = tuple(x_axis)
        self.y_axis = tuple(y_axis)
        self.normal = tuple(normal)

    def __repr__(self):
        return "Plane(origin={!r}, x_axis={!r}, y_axis={!r}, normal={!r})".format(
            self.origin, self.x_axis, self.y_axis, self.normal)

    def to_local(self, point):
        """Coordinates ``(u, v, w)`` of a world point in the plane's basis."""
        d = _sub(point, self.origin)
        return (_dot(d, self.x_axis), _dot(d, self.y_axis), _dot(d, self.normal))

    def to_world(self, u, v, w=0.0):
        return _add(self.origin, _add(_scale(self.x_axis, u), _add(_scale(self.y_axis, v), _scale(self.normal, w))))

    def matrix(self):
        """Rotation matrix (rows) whose columns are the plane's axes: the orientation of objects created on it."""
        x, y, n = self.x_axis, self.y_axis, self.normal
        return ((x[0], y[0], n[0]), (x[1], y[1], n[1]), (x[2], y[2], n[2]))


GROUND_PLANE = Plane((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


def construction_plane(view_rotation, axis_aligned_ortho):
    """
    The construction plane for a view, as in Max: the ground (XY) plane in perspective and user views, and the plane
    facing the viewer through the world origin in axis-aligned orthographic views (top, bottom, front, back, left,
    right). Objects created on it get the plane's orientation, so their local Z points at the viewer.

    :arg view_rotation: the view's 3x3 rotation matrix as rows; its columns are screen right, screen up and the
       direction towards the viewer (Blender's ``RegionView3D.view_rotation`` as a matrix).
    :arg axis_aligned_ortho: whether the view is orthographic and aligned to a world axis.
    """
    if not axis_aligned_ortho:
        return GROUND_PLANE
    right = _axis_snap([view_rotation[i][0] for i in range(3)])
    normal = _axis_snap([view_rotation[i][2] for i in range(3)])
    if abs(_dot(right, normal)) > 0.5:
        return GROUND_PLANE
    if normal == (0.0, 0.0, 1.0):
        # Top view: the ground plane itself, whichever way the view is spun.
        return GROUND_PLANE
    return Plane((0.0, 0.0, 0.0), right, _cross(normal, right), normal)


def ray_plane(ray_origin, ray_direction, plane, offset=0.0):
    """Intersection of a ray with ``plane`` moved by ``offset`` along its normal; ``None`` if there is none."""
    denom = _dot(ray_direction, plane.normal)
    if abs(denom) < 1e-9:
        return None
    origin = _add(plane.origin, _scale(plane.normal, offset))
    t = _dot(_sub(origin, ray_origin), plane.normal) / denom
    if t < 0.0:
        # Behind the viewer (perspective views looking away from the plane).
        return None
    return _add(ray_origin, _scale(ray_direction, t))


def closest_on_line(line_origin, line_direction, ray_origin, ray_direction):
    """
    Parameter ``t`` of the point ``line_origin + t * line_direction`` closest to the line through the ray,
    or ``None`` when they are (nearly) parallel.
    """
    w0 = _sub(line_origin, ray_origin)
    a = _dot(line_direction, line_direction)
    b = _dot(line_direction, ray_direction)
    c = _dot(ray_direction, ray_direction)
    d = _dot(line_direction, w0)
    e = _dot(ray_direction, w0)
    denom = a * c - b * b
    if denom <= 1e-6 * a * c:
        return None
    return (b * e - c * d) / denom


def snap(value, step):
    """``value`` rounded to a multiple of ``step`` (no snapping when ``step`` is 0)."""
    if step <= 0.0:
        return value
    return round(value / step) * step


class CreationSession:
    """
    State of one interactive creation.

    Usage: :meth:`press` with the point under the mouse on the construction plane, :meth:`update` with the view ray
    on every mouse move, :meth:`advance` on release (first step) or click (later steps) until it returns
    ``"FINISHED"``. :attr:`location`, :attr:`params` and :attr:`plane` describe the object at any time.

    :arg snap_step: grid size for snapping points and heights, 0 for no snapping.
    """

    def __init__(self, kind, plane, snap_step=0.0):
        self.kind = kind
        self.steps = STEPS[kind]
        self.plane = plane
        self.snap_step = snap_step
        self.step = 0
        self.anchor = None
        self.current = None
        self.location = plane.origin
        self.params = {}

    @property
    def step_name(self):
        return self.steps[self.step]

    def _snap_local(self, point):
        u, v, _w = self.plane.to_local(point)
        return (snap(u, self.snap_step), snap(v, self.snap_step))

    def press(self, point):
        """Start the first step at ``point`` (a world point on the construction plane)."""
        self.anchor = self.current = self._snap_local(point)
        self.step = 0
        self.params = {}
        if self.kind in _RECT_PARAMS:
            for name in _RECT_PARAMS[self.kind]:
                self.params[name] = 0.0
        else:
            self.params[_RADIUS_PARAM.get(self.kind, "radius")] = 0.0
        if "HEIGHT" in self.steps:
            self.params["height"] = 0.0
        self._update_dependent()
        self._update_location()

    def _update_location(self):
        if self.steps[0] == "RECT":
            # Pivot at the centre of the rectangle.
            u = (self.anchor[0] + self.current[0]) * 0.5
            v = (self.anchor[1] + self.current[1]) * 0.5
        else:
            u, v = self.anchor
        self.location = self.plane.to_world(u, v)

    def _update_dependent(self):
        # Second radii follow the first one until their own step.
        if self.kind in ("CONE", "TUBE") and self.step < self.steps.index("RADIUS2"):
            self.params["radius2"] = self.params["radius1"]
        elif self.kind == "TORUS" and self.step == 0:
            self.params["radius2"] = self.params["radius1"] * 0.1

    def update(self, ray_origin, ray_direction, square=False, fallback_height=None):
        """
        Update from the view ray under the mouse. ``square`` constrains a rectangle to a square (Ctrl in Max).
        ``fallback_height`` is used for the height when the ray is parallel to the height axis (the mouse's vertical
        movement on screen converted to world units, e.g. in the top view).
        """
        name = self.step_name
        if name in ("RECT", "RADIUS"):
            hit = ray_plane(ray_origin, ray_direction, self.plane)
            if hit is None:
                return
            self.current = self._snap_local(hit)
            du = self.current[0] - self.anchor[0]
            dv = self.current[1] - self.anchor[1]
            if name == "RECT":
                if square:
                    side = max(abs(du), abs(dv))
                    du = math.copysign(side, du)
                    dv = math.copysign(side, dv)
                    self.current = (self.anchor[0] + du, self.anchor[1] + dv)
                width_name, length_name = _RECT_PARAMS[self.kind]
                self.params[width_name] = abs(du)
                self.params[length_name] = abs(dv)
            else:
                self.params[_RADIUS_PARAM.get(self.kind, "radius")] = math.hypot(du, dv)
            self._update_location()
        elif name == "HEIGHT":
            # Height along the plane normal, measured on the vertical line through the last point of the base.
            base = self.plane.to_world(*self.current)
            height = None
            if abs(_dot(_normalized(ray_direction), self.plane.normal)) < 0.999:
                height = closest_on_line(base, self.plane.normal, ray_origin, ray_direction)
            if height is None:
                height = fallback_height
            if height is not None:
                self.params["height"] = snap(height, self.snap_step)
        elif name == "RADIUS2":
            # A cone's top radius is measured on its top plane, the others on the construction plane.
            offset = self.params.get("height", 0.0) if self.kind == "CONE" else 0.0
            hit = ray_plane(ray_origin, ray_direction, self.plane, offset)
            if hit is None:
                return
            u, v = self._snap_local(hit)
            distance = math.hypot(u - self.anchor[0], v - self.anchor[1])
            if self.kind == "TORUS":
                # Radius 2 is the distance from the ring.
                distance = abs(distance - self.params["radius1"])
            self.params["radius2"] = distance
        self._update_dependent()

    def is_valid(self):
        """Whether the base drawn in the first step is big enough to create an object."""
        if self.steps[0] == "RECT":
            return all(self.params[name] > MIN_SIZE for name in _RECT_PARAMS[self.kind])
        return self.params[_RADIUS_PARAM.get(self.kind, "radius")] > MIN_SIZE

    def advance(self):
        """
        Confirm the current step: returns ``"INVALID"`` (first step too small, nothing to create), ``"CONTINUE"``
        or ``"FINISHED"``.
        """
        if self.step == 0 and not self.is_valid():
            return "INVALID"
        self.step += 1
        if self.step >= len(self.steps):
            self.step = len(self.steps) - 1
            return "FINISHED"
        self._update_dependent()
        return "CONTINUE"
