# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Math of interactive primitive creation (``scripts/addons_core/mx_primitives/creation.py``), without Blender."""

import importlib.util
import math
import os

import pytest

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
_spec = importlib.util.spec_from_file_location(
    "mx_primitives_creation", os.path.join(ROOT, "scripts", "addons_core", "mx_primitives", "creation.py"))
creation = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(creation)

_geo_spec = importlib.util.spec_from_file_location(
    "mx_primitives_geometry", os.path.join(ROOT, "scripts", "addons_core", "mx_primitives", "geometry.py"))
geometry = importlib.util.module_from_spec(_geo_spec)
_geo_spec.loader.exec_module(geometry)


def close(a, b, tol=1e-9):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def rows(columns):
    """3x3 matrix rows from its three columns."""
    return tuple(tuple(columns[c][r] for c in range(3)) for r in range(3))


# View rotations as (screen right, screen up, towards viewer), as in Blender's axis views.
TOP = rows(((1, 0, 0), (0, 1, 0), (0, 0, 1)))
BOTTOM = rows(((1, 0, 0), (0, -1, 0), (0, 0, -1)))
FRONT = rows(((1, 0, 0), (0, 0, 1), (0, -1, 0)))
BACK = rows(((-1, 0, 0), (0, 0, 1), (0, 1, 0)))
RIGHT = rows(((0, 1, 0), (0, 0, 1), (1, 0, 0)))
LEFT = rows(((0, -1, 0), (0, 0, 1), (-1, 0, 0)))


def test_steps_cover_kinds():
    assert set(creation.STEPS) == set(geometry.KIND_IDS)


def test_ground_plane_for_perspective():
    plane = creation.construction_plane(FRONT, axis_aligned_ortho=False)
    assert plane.normal == (0.0, 0.0, 1.0)


@pytest.mark.parametrize("view,normal", [
    (TOP, (0, 0, 1)), (BOTTOM, (0, 0, -1)), (FRONT, (0, -1, 0)), (BACK, (0, 1, 0)), (RIGHT, (1, 0, 0)),
    (LEFT, (-1, 0, 0)),
])
def test_construction_plane_faces_viewer(view, normal):
    plane = creation.construction_plane(view, axis_aligned_ortho=True)
    assert close(plane.normal, normal)
    # Right-handed basis, so objects created on it are only rotated.
    x, y, n = plane.x_axis, plane.y_axis, plane.normal
    assert close(creation._cross(x, y), n)
    m = plane.matrix()
    det = (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
           + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))
    assert abs(det - 1.0) < 1e-9


def test_front_view_plane_axes():
    # In the front view the object's width runs along X and its length up the screen (world Z).
    plane = creation.construction_plane(FRONT, True)
    assert close(plane.x_axis, (1, 0, 0)) and close(plane.y_axis, (0, 0, 1))


def test_ray_plane():
    plane = creation.GROUND_PLANE
    assert close(creation.ray_plane((1, 2, 5), (0, 0, -1), plane), (1, 2, 0))
    assert creation.ray_plane((1, 2, 5), (1, 0, 0), plane) is None
    assert creation.ray_plane((1, 2, 5), (0, 0, 1), plane) is None
    assert close(creation.ray_plane((0, 0, 5), (0, 0, -1), plane, offset=2.0), (0, 0, 2))


def test_closest_on_line():
    # Vertical line through (1, 0, 0), ray along -Y at height 3.
    t = creation.closest_on_line((1, 0, 0), (0, 0, 1), (1, 10, 3), (0, -1, 0))
    assert abs(t - 3.0) < 1e-9
    assert creation.closest_on_line((0, 0, 0), (0, 0, 1), (5, 5, 5), (0, 0, -1)) is None


def test_snap():
    assert creation.snap(0.26, 0.1) == pytest.approx(0.3)
    assert creation.snap(-0.24, 0.5) == pytest.approx(-0.0)
    assert creation.snap(0.26, 0.0) == 0.26


def down_ray(x, y):
    return (x, y, 10.0), (0.0, 0.0, -1.0)


def test_box_session():
    session = creation.CreationSession("BOX", creation.GROUND_PLANE)
    session.press((1.0, 1.0, 0.0))
    session.update(*down_ray(3.0, 2.0))
    assert session.params["width"] == pytest.approx(2.0)
    assert session.params["length"] == pytest.approx(1.0)
    assert close(session.location, (2.0, 1.5, 0.0))
    assert session.advance() == "CONTINUE"
    assert session.step_name == "HEIGHT"
    # Looking along -Y at the vertical line through the release point (3, 2): height 4.
    session.update((3.0, -10.0, 4.0), (0.0, 1.0, 0.0))
    assert session.params["height"] == pytest.approx(4.0)
    # Straight down the height axis: the fallback (screen movement) is used.
    session.update((3.0, 2.0, 10.0), (0.0, 0.0, -1.0), fallback_height=1.5)
    assert session.params["height"] == pytest.approx(1.5)
    assert session.advance() == "FINISHED"
    params = geometry.normalize_params("BOX", session.params)
    assert params["height"] == pytest.approx(1.5)


def test_box_square_and_negative_drag():
    session = creation.CreationSession("BOX", creation.GROUND_PLANE)
    session.press((0.0, 0.0, 0.0))
    session.update(*down_ray(-2.0, 0.5), square=True)
    assert session.params["width"] == pytest.approx(2.0) and session.params["length"] == pytest.approx(2.0)
    assert close(session.location, (-1.0, 1.0, 0.0))


def test_tiny_drag_is_invalid():
    session = creation.CreationSession("SPHERE", creation.GROUND_PLANE)
    session.press((1.0, 1.0, 0.0))
    session.update(*down_ray(1.0, 1.0))
    assert session.advance() == "INVALID"


def test_sphere_session_finishes_on_release():
    session = creation.CreationSession("SPHERE", creation.GROUND_PLANE)
    session.press((1.0, 1.0, 0.0))
    session.update(*down_ray(4.0, 5.0))
    assert session.params == {"radius": pytest.approx(5.0)}
    assert close(session.location, (1.0, 1.0, 0.0))
    assert session.advance() == "FINISHED"


def test_snapping():
    session = creation.CreationSession("CYLINDER", creation.GROUND_PLANE, snap_step=1.0)
    session.press((0.2, -0.1, 0.0))
    assert close(session.location, (0.0, 0.0, 0.0))
    session.update(*down_ray(2.6, 0.3))
    assert session.params["radius"] == pytest.approx(3.0)
    session.advance()
    session.update((3.0, -10.0, 1.4), (0.0, 1.0, 0.0))
    assert session.params["height"] == pytest.approx(1.0)


def test_cone_session():
    session = creation.CreationSession("CONE", creation.GROUND_PLANE)
    session.press((0.0, 0.0, 0.0))
    session.update(*down_ray(2.0, 0.0))
    assert session.params["radius2"] == pytest.approx(2.0)
    assert session.advance() == "CONTINUE"
    session.update((2.0, -10.0, 3.0), (0.0, 1.0, 0.0))
    assert session.params["height"] == pytest.approx(3.0)
    assert session.params["radius2"] == pytest.approx(2.0)
    assert session.advance() == "CONTINUE"
    assert session.step_name == "RADIUS2"
    # Radius 2 is measured on the top plane (z = 3).
    session.update((0.5, 0.0, 10.0), (0.0, 0.0, -1.0))
    assert session.params["radius2"] == pytest.approx(0.5)
    assert session.advance() == "FINISHED"


def test_tube_session():
    session = creation.CreationSession("TUBE", creation.GROUND_PLANE)
    session.press((0.0, 0.0, 0.0))
    session.update(*down_ray(0.0, 2.0))
    session.advance()
    session.update(*down_ray(1.5, 0.0))
    assert session.params["radius1"] == pytest.approx(2.0) and session.params["radius2"] == pytest.approx(1.5)
    assert session.advance() == "CONTINUE"
    assert session.step_name == "HEIGHT"
    session.update((1.5, -10.0, 2.0), (0.0, 1.0, 0.0))
    assert session.params["height"] == pytest.approx(2.0)
    assert session.advance() == "FINISHED"


def test_torus_session():
    session = creation.CreationSession("TORUS", creation.GROUND_PLANE)
    session.press((0.0, 0.0, 0.0))
    session.update(*down_ray(2.0, 0.0))
    session.advance()
    session.update(*down_ray(2.5, 0.0))
    assert session.params["radius2"] == pytest.approx(0.5)
    session.update(*down_ray(1.2, 0.0))
    assert session.params["radius2"] == pytest.approx(0.8)
    assert session.advance() == "FINISHED"


def test_front_view_box():
    plane = creation.construction_plane(FRONT, True)
    session = creation.CreationSession("BOX", plane)
    # Rays from the viewer (at -Y) towards +Y.
    session.press(creation.ray_plane((0.0, -10.0, 0.0), (0.0, 1.0, 0.0), plane))
    session.update((2.0, -10.0, 1.0), (0.0, 1.0, 0.0))
    assert session.params["width"] == pytest.approx(2.0) and session.params["length"] == pytest.approx(1.0)
    assert close(session.location, (1.0, 0.0, 0.5))


@pytest.mark.parametrize("kind", sorted(creation.STEPS))
def test_every_kind_completes(kind):
    session = creation.CreationSession(kind, creation.GROUND_PLANE)
    session.press((0.0, 0.0, 0.0))
    session.update(*down_ray(1.0, 1.0))
    result = session.advance()
    while result == "CONTINUE":
        session.update((0.5, -10.0, 0.7), (0.0, 1.0, 0.0), fallback_height=0.7)
        session.update(*down_ray(0.5, 0.0))
        result = session.advance()
    assert result == "FINISHED"
    # The parameters are valid input for the geometry.
    geometry.generate(kind, **session.params)
