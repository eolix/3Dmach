# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Geometry of the Max-style live primitives (``scripts/addons_core/mx_primitives/geometry.py``), without Blender.

Run with ``python3 -m pytest tests/primitives``.
"""

import ast
import importlib.util
import math
import os

import pytest

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
ADDON_DIR = os.path.join(ROOT, "scripts", "addons_core", "mx_primitives")


def _load(name):
    spec = importlib.util.spec_from_file_location("mx_primitives_" + name, os.path.join(ADDON_DIR, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


geometry = _load("geometry")

TAU = 2.0 * math.pi
# GeoSphere UVs are a spherical projection: faces across the seam continue past u = 1 (the texture tiles).
GEO_UV_RANGE = (0.0, 1.5)


# -----------------------------------------------------------------------------
# Mesh checks

def newell_normal(points):
    nx = ny = nz = 0.0
    for i, (x0, y0, z0) in enumerate(points):
        x1, y1, z1 = points[(i + 1) % len(points)]
        nx += (y0 - y1) * (z0 + z1)
        ny += (z0 - z1) * (x0 + x1)
        nz += (x0 - x1) * (y0 + y1)
    return (nx * 0.5, ny * 0.5, nz * 0.5)


def signed_volume(data):
    volume = 0.0
    for face in data.faces:
        a = data.vertices[face[0]]
        for k in range(1, len(face) - 1):
            b, c = data.vertices[face[k]], data.vertices[face[k + 1]]
            volume += (a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0])
                       + a[2] * (b[0] * c[1] - b[1] * c[0])) / 6.0
    return volume


def edges(data):
    return {tuple(sorted((face[k], face[(k + 1) % len(face)]))) for face in data.faces for k in range(len(face))}


def euler(data):
    return len(data.vertices) - len(edges(data)) + len(data.faces)


def triangles(data):
    return sum(len(face) - 2 for face in data.faces)


def bbox(data):
    return [(min(v[i] for v in data.vertices), max(v[i] for v in data.vertices)) for i in range(3)]


def check_mesh(data, closed=True, uv_range=(0.0, 1.0), min_area=1e-9):
    nv = len(data.vertices)
    nf = len(data.faces)
    assert nv > 0 and nf > 0
    assert len(data.smoothing_groups) == nf
    assert len(data.material_ids) == nf
    used = set()
    directed = set()
    for face in data.faces:
        assert len(face) >= 3
        assert len(set(face)) == len(face), "repeated vertex in face {!r}".format(face)
        assert all(0 <= i < nv for i in face)
        used.update(face)
        normal = newell_normal([data.vertices[i] for i in face])
        assert math.sqrt(sum(c * c for c in normal)) > min_area, "degenerate face {!r}".format(face)
        for k in range(len(face)):
            edge = (face[k], face[(k + 1) % len(face)])
            assert edge not in directed, "inconsistent winding or non-manifold edge {!r}".format(edge)
            directed.add(edge)
    assert used == set(range(nv)), "unused vertices"
    if closed:
        open_edges = [e for e in directed if (e[1], e[0]) not in directed]
        assert not open_edges, "open edges: {!r}".format(open_edges[:5])
        assert signed_volume(data) > 0.0, "faces point inwards"
    if data.uvs is not None:
        assert len(data.uvs) == nf
        lo, hi = uv_range
        for face, uvs in zip(data.faces, data.uvs):
            assert len(uvs) == len(face)
            for u, v in uvs:
                assert lo - 1e-9 <= u <= hi + 1e-9 and 0.0 - 1e-9 <= v <= 1.0 + 1e-9, (u, v)
    for group in data.smoothing_groups:
        assert 0 <= group < (1 << 32)
    for material in data.material_ids:
        assert material >= 0


def approx(a, b, tol=1e-6):
    return abs(a - b) <= tol


def assert_bbox(data, expected, tol=1e-6):
    for axis, ((lo, hi), (elo, ehi)) in enumerate(zip(bbox(data), expected)):
        message = "axis {:d}: {!r} != {!r}".format(axis, (lo, hi), (elo, ehi))
        assert approx(lo, elo, tol) and approx(hi, ehi, tol), message


# -----------------------------------------------------------------------------
# API

def test_no_blender_imports():
    for name in ("geometry.py", "creation.py"):
        with open(os.path.join(ADDON_DIR, name), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            else:
                continue
            for module in modules:
                assert module.split(".")[0] not in {"bpy", "mathutils", "bmesh", "bpy_extras", "gpu"}, (name, module)


def test_kinds():
    assert set(geometry.KIND_IDS) == {
        "BOX", "SPHERE", "GEOSPHERE", "CYLINDER", "TUBE", "CONE", "TORUS", "PYRAMID", "PLANE", "TEST_SHAPE"}


def test_parameter_types_consistent():
    # Parameters with the same name share one Blender property, so their type must agree across kinds.
    types = {}
    for params in geometry.PARAMETERS.values():
        for name, default in params.items():
            types.setdefault(name, type(default))
            assert types[name] is type(default), name
    for name in geometry.ENUMS:
        assert types[name] is str


@pytest.mark.parametrize("kind", geometry.KIND_IDS)
def test_defaults_generate(kind):
    data = geometry.generate(kind)
    check_mesh(data, closed=kind != "PLANE", uv_range=GEO_UV_RANGE if kind == "GEOSPHERE" else (0.0, 1.0))


def test_normalize_params():
    params = geometry.normalize_params("SPHERE", {"segments": 2, "radius": -1, "hemisphere": 2})
    assert params["segments"] == 4
    assert params["radius"] == 0.0
    assert params["hemisphere"] == 1.0
    assert geometry.normalize_params("BOX", {"length_segments": 2.6})["length_segments"] == 3
    with pytest.raises(TypeError):
        geometry.normalize_params("BOX", {"radius": 1.0})
    with pytest.raises(ValueError):
        geometry.normalize_params("NOPE", {})
    with pytest.raises(ValueError):
        geometry.normalize_params("TORUS", {"smooth_mode": "SOME"})


def test_no_uvs():
    assert geometry.generate("BOX", generate_uvs=False).uvs is None


def test_sharp_edges_helper():
    data = geometry.generate("BOX")
    assert len(data.sharp_edges()) == 12
    assert not any(data.flat_faces())


# -----------------------------------------------------------------------------
# Box

@pytest.mark.parametrize("ws,ls,hs", [(1, 1, 1), (2, 3, 4), (5, 1, 2)])
def test_box_counts(ws, ls, hs):
    data = geometry.generate("BOX", width=2.0, length=3.0, height=4.0,
                             width_segments=ws, length_segments=ls, height_segments=hs)
    check_mesh(data)
    assert len(data.vertices) == 2 * (ws + 1) * (ls + 1) + (hs - 1) * 2 * (ws + ls)
    assert len(data.faces) == 2 * (ws * ls + ws * hs + ls * hs)
    assert all(len(face) == 4 for face in data.faces)
    assert_bbox(data, [(-1.0, 1.0), (-1.5, 1.5), (0.0, 4.0)])
    assert approx(signed_volume(data), 24.0)
    assert euler(data) == 2
    # One material ID and one smoothing group per side.
    assert sorted(set(data.material_ids)) == [0, 1, 2, 3, 4, 5]
    assert len(set(data.smoothing_groups)) == 6
    assert len(data.sharp_edges()) == 4 * (ws + ls + hs)


def test_box_side_ids():
    data = geometry.generate("BOX", width=2.0, length=2.0, height=2.0)
    expected = {
        (0.0, 0.0, -1.0): "BOTTOM", (0.0, 0.0, 1.0): "TOP", (0.0, -1.0, 0.0): "FRONT",
        (1.0, 0.0, 0.0): "RIGHT", (0.0, 1.0, 0.0): "BACK", (-1.0, 0.0, 0.0): "LEFT",
    }
    for face, material, group in zip(data.faces, data.material_ids, data.smoothing_groups):
        normal = newell_normal([data.vertices[i] for i in face])
        length = math.sqrt(sum(c * c for c in normal))
        key = tuple(round(c / length, 6) + 0.0 for c in normal)
        assert (material, group) == geometry.BOX_SIDES[expected[key]]


def test_box_matches_max_layout():
    # A 1x1x1 Box converted to Editable Poly in Max (corpus): vertex order, faces with their first corner,
    # material IDs (Max's 1-based 2, 1, 5, 4, 6, 3) and smoothing groups.
    data = geometry.generate("BOX", width=2.0, length=4.0, height=1.0)
    assert [tuple(round(c, 6) + 0.0 for c in v) for v in data.vertices] == [
        (-1.0, -2.0, 0.0), (1.0, -2.0, 0.0), (-1.0, 2.0, 0.0), (1.0, 2.0, 0.0),
        (-1.0, -2.0, 1.0), (1.0, -2.0, 1.0), (-1.0, 2.0, 1.0), (1.0, 2.0, 1.0)]
    assert data.faces == [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (1, 3, 7, 5), (3, 2, 6, 7), (2, 0, 4, 6)]
    assert data.material_ids == [1, 0, 4, 3, 5, 2]
    assert data.smoothing_groups == [2, 4, 8, 16, 32, 64]


def test_box_negative_height_faces_out():
    data = geometry.generate("BOX", height=-2.0)
    check_mesh(data)
    assert_bbox(data, [(-0.5, 0.5), (-0.5, 0.5), (-2.0, 0.0)])


# -----------------------------------------------------------------------------
# Plane

def test_plane():
    data = geometry.generate("PLANE", length=4.0, width=2.0, length_segments=3, width_segments=5)
    check_mesh(data, closed=False)
    assert len(data.vertices) == 6 * 4
    assert len(data.faces) == 15
    assert_bbox(data, [(-1.0, 1.0), (-2.0, 2.0), (0.0, 0.0)])
    for face in data.faces:
        assert newell_normal([data.vertices[i] for i in face])[2] > 0.0
    uvs = [uv for face_uvs in data.uvs for uv in face_uvs]
    assert min(u for u, v in uvs) == 0.0 and max(u for u, v in uvs) == 1.0


# -----------------------------------------------------------------------------
# Sphere

def test_sphere_default_matches_max_counts():
    # A default 32-segment Max sphere has 482 vertices and 960 triangles.
    data = geometry.generate("SPHERE", radius=2.0)
    check_mesh(data)
    assert len(data.vertices) == 482
    assert triangles(data) == 960
    assert len(data.faces) == 32 * 16
    assert sum(len(face) == 3 for face in data.faces) == 64
    assert_bbox(data, [(-2.0, 2.0), (-2.0, 2.0), (-2.0, 2.0)], tol=1e-2)
    assert all(approx(math.sqrt(sum(c * c for c in v)), 2.0) for v in data.vertices)
    assert data.sharp_edges() == []


def test_sphere_matches_max_layout():
    # A 10-segment Sphere converted to Editable Poly in Max (corpus): the top pole, rings from the top down starting
    # at +Y, the bottom pole; the top fan, bands of quads, the bottom fan, each face starting at the same corner.
    data = geometry.generate("SPHERE", radius=1.0, segments=10)
    assert len(data.vertices) == 42 and len(data.faces) == 50
    assert approx(data.vertices[0][2], 1.0) and approx(data.vertices[41][2], -1.0)
    first = data.vertices[1]
    assert approx(first[0], 0.0) and first[1] > 0.0
    assert math.degrees(math.atan2(data.vertices[2][1], data.vertices[2][0])) == pytest.approx(126.0)
    assert data.faces[:2] == [(0, 1, 2), (0, 2, 3)] and data.faces[9] == (0, 10, 1)
    assert data.faces[10] == (1, 11, 12, 2) and data.faces[19] == (10, 20, 11, 1)
    assert data.faces[40] == (41, 32, 31) and data.faces[49] == (41, 31, 40)


@pytest.mark.parametrize("kind,start", [("SPHERE", 90.0), ("TUBE", 90.0), ("TORUS", 90.0), ("CYLINDER", 0.0),
                                        ("CONE", 0.0)])
def test_ring_start_angle(kind, start):
    # Max starts the rings of spheres, tubes and tori at +Y, those of cylinders and cones at +X (corpus bounding
    # boxes of odd segment counts, see geometry.RING_START).
    params = {"segments": 9} if kind in ("SPHERE", "TORUS") else {"sides": 9}
    data = geometry.generate(kind, **params)
    ring = [v for v in data.vertices if math.hypot(v[0], v[1]) > 1e-6][0]
    assert math.degrees(math.atan2(ring[1], ring[0])) == pytest.approx(start)
    # With an odd count the extent along the start axis is asymmetric.
    lo, hi = bbox(data)[0 if start == 0.0 else 1]
    assert hi > -lo + 1e-6


@pytest.mark.parametrize("segments", [4, 5, 7, 12, 33])
def test_sphere_segments(segments):
    data = geometry.generate("SPHERE", segments=segments)
    check_mesh(data)
    rows = segments // 2
    assert len(data.vertices) == (rows - 1) * segments + 2
    assert euler(data) == 2


def test_sphere_not_smooth():
    data = geometry.generate("SPHERE", smooth=False, segments=8)
    assert all(data.flat_faces())


@pytest.mark.parametrize("mode", ["CHOP", "SQUASH"])
@pytest.mark.parametrize("hemisphere", [0.25, 0.5, 0.8])
def test_sphere_hemisphere(mode, hemisphere):
    data = geometry.generate("SPHERE", radius=1.0, hemisphere=hemisphere, hemisphere_mode=mode)
    check_mesh(data)
    assert euler(data) == 2
    cut = 1.0 - 2.0 * hemisphere
    zs = [v[2] for v in data.vertices]
    assert approx(min(zs), cut) and approx(max(zs), 1.0)
    if mode == "SQUASH":
        # Squash keeps the vertex count (plus the base centre) and the bands.
        # Squash keeps all 16 bands; the 16th ring is the cut, plus the top pole and the base centre.
        assert len(data.vertices) == 16 * 32 + 2
    else:
        # Chop keeps the rings above the cut and adds one at the cut.
        kept = sum(1 for k in range(1, 16) if math.pi * k / 16 < math.acos(cut) - 1e-9)
        assert len(data.vertices) == (kept + 1) * 32 + 2
    based = geometry.generate("SPHERE", radius=1.0, hemisphere=hemisphere, hemisphere_mode=mode, base_to_pivot=True)
    assert approx(min(v[2] for v in based.vertices), 0.0)


def test_sphere_base_to_pivot():
    data = geometry.generate("SPHERE", radius=1.5, base_to_pivot=True)
    zs = [v[2] for v in data.vertices]
    assert approx(min(zs), 0.0) and approx(max(zs), 3.0)


@pytest.mark.parametrize("slice_from,slice_to", [(0.0, math.pi / 2), (math.radians(30), math.radians(300)),
                                                 (math.radians(200), math.radians(10))])
@pytest.mark.parametrize("hemisphere", [0.0, 0.5])
def test_sphere_slice(slice_from, slice_to, hemisphere):
    data = geometry.generate("SPHERE", segments=16, slice_on=True, slice_from=slice_from, slice_to=slice_to,
                             hemisphere=hemisphere)
    check_mesh(data)
    assert euler(data) == 2
    full = geometry.generate("SPHERE", segments=16, hemisphere=hemisphere)
    assert 0.0 < signed_volume(data) < signed_volume(full)
    arc = (slice_to - slice_from) % TAU
    assert approx(signed_volume(data) / signed_volume(full), arc / TAU, 0.05)


def test_slice_equal_angles_is_whole():
    sliced = geometry.generate("CYLINDER", slice_on=True, slice_from=1.0, slice_to=1.0)
    whole = geometry.generate("CYLINDER")
    assert len(sliced.vertices) == len(whole.vertices)


# -----------------------------------------------------------------------------
# GeoSphere

@pytest.mark.parametrize("base_type,per_f2,faces_per_f2", [("TETRA", 2, 4), ("OCTA", 4, 8), ("ICOSA", 10, 20)])
@pytest.mark.parametrize("segments", [1, 2, 3, 4])
def test_geosphere_counts(base_type, per_f2, faces_per_f2, segments):
    data = geometry.generate("GEOSPHERE", radius=1.0, segments=segments, base_type=base_type)
    check_mesh(data, uv_range=GEO_UV_RANGE)
    assert len(data.vertices) == per_f2 * segments * segments + 2
    assert len(data.faces) == faces_per_f2 * segments * segments
    assert all(approx(math.sqrt(sum(c * c for c in v)), 1.0) for v in data.vertices)
    assert any(approx(v[2], 1.0) for v in data.vertices), "vertex at the top pole"


def test_geosphere_default_matches_max_counts():
    # Max's default GeoSphere (icosa, 4 segments): 162 vertices, 320 faces.
    data = geometry.generate("GEOSPHERE")
    assert (len(data.vertices), len(data.faces)) == (162, 320)


@pytest.mark.parametrize("base_type", ["TETRA", "OCTA", "ICOSA"])
@pytest.mark.parametrize("segments", [1, 2, 3, 4])
def test_geosphere_hemisphere(base_type, segments):
    data = geometry.generate("GEOSPHERE", radius=1.0, segments=segments, base_type=base_type, hemisphere_on=True)
    check_mesh(data, uv_range=GEO_UV_RANGE)
    assert euler(data) == 2
    assert approx(min(v[2] for v in data.vertices), 0.0)
    # One flat base face.
    assert sum(all(approx(data.vertices[i][2], 0.0) for i in face) for face in data.faces) == 1
    if base_type != "TETRA" and segments % 2 == 0:
        full = geometry.generate("GEOSPHERE", radius=1.0, segments=segments, base_type=base_type)
        assert len(data.faces) == len(full.faces) // 2 + 1


def test_geosphere_base_to_pivot():
    data = geometry.generate("GEOSPHERE", radius=2.0, base_to_pivot=True)
    assert approx(min(v[2] for v in data.vertices), 0.0) and approx(max(v[2] for v in data.vertices), 4.0)


# -----------------------------------------------------------------------------
# Cylinder, Cone, Tube

def test_cylinder_default():
    data = geometry.generate("CYLINDER", radius=1.0, height=2.0)
    check_mesh(data)
    assert len(data.vertices) == 18 * 6
    assert len(data.faces) == 18 * 5 + 2
    assert triangles(data) == 18 * 10 + 2 * 16
    assert_bbox(data, [(-1.0, 1.0), (-math.sin(math.radians(80)), math.sin(math.radians(80))), (0.0, 2.0)])
    # Smooth sides, sharp rims.
    assert len(data.sharp_edges()) == 36
    assert sorted(set(data.material_ids)) == [0, 1, 2]


@pytest.mark.parametrize("hs,cs,sides", [(1, 1, 3), (3, 2, 8), (5, 4, 18)])
def test_cylinder_counts(hs, cs, sides):
    data = geometry.generate("CYLINDER", height_segments=hs, cap_segments=cs, sides=sides)
    check_mesh(data)
    assert euler(data) == 2
    centres = 2 if cs > 1 else 0
    assert len(data.vertices) == sides * (hs + 1) + 2 * sides * (cs - 1) + centres
    assert len(data.faces) == sides * hs + (2 * sides * cs if cs > 1 else 2)


@pytest.mark.parametrize("cs", [1, 3])
@pytest.mark.parametrize("hs", [1, 4])
def test_cylinder_slice(hs, cs):
    data = geometry.generate("CYLINDER", radius=1.0, height=1.0, height_segments=hs, cap_segments=cs, sides=12,
                             slice_on=True, slice_from=0.0, slice_to=math.pi)
    check_mesh(data)
    assert euler(data) == 2
    # The 12 sides are spread over the half that is kept.
    assert approx(signed_volume(data), 12 * 0.5 * math.sin(math.pi / 12), 1e-6)
    # The slice faces have cs * hs quads each.
    slice_faces = [m for m in data.material_ids if m == geometry.CAP_MATERIALS["SLICE"]]
    assert len(slice_faces) == 2 * cs * hs


def test_cylinder_negative_height():
    data = geometry.generate("CYLINDER", height=-1.0)
    check_mesh(data)
    assert approx(min(v[2] for v in data.vertices), -1.0)


def test_cylinder_not_smooth():
    data = geometry.generate("CYLINDER", smooth=False)
    assert all(data.flat_faces()[i] for i, m in enumerate(data.material_ids) if m == geometry.CAP_MATERIALS["SIDES"])


def test_cone_default_is_pointed():
    data = geometry.generate("CONE", radius1=1.0, radius2=0.0, height=2.0)
    check_mesh(data)
    assert len(data.vertices) == 24 * 5 + 1
    apex = [i for i, v in enumerate(data.vertices) if approx(v[2], 2.0)]
    assert len(apex) == 1
    assert sum(len(face) == 3 for face in data.faces) == 24


@pytest.mark.parametrize("r1,r2", [(1.0, 0.5), (0.5, 1.0), (0.0, 1.0), (1.0, 0.0)])
@pytest.mark.parametrize("slice_on", [False, True])
@pytest.mark.parametrize("cs", [1, 2])
def test_cone_variants(r1, r2, slice_on, cs):
    data = geometry.generate("CONE", radius1=r1, radius2=r2, height=1.0, cap_segments=cs, sides=16,
                             slice_on=slice_on, slice_from=0.2, slice_to=4.0)
    check_mesh(data)
    assert euler(data) == 2
    expected = math.pi / 3.0 * (r1 * r1 + r1 * r2 + r2 * r2)
    if slice_on:
        expected *= (4.0 - 0.2) / TAU
    assert approx(signed_volume(data), expected, 0.05 * expected)


@pytest.mark.parametrize("r1,r2", [(1.0, 0.6), (0.6, 1.0)])
@pytest.mark.parametrize("hs,cs", [(1, 1), (3, 2)])
def test_tube(r1, r2, hs, cs):
    data = geometry.generate("TUBE", radius1=r1, radius2=r2, height=2.0, height_segments=hs, cap_segments=cs,
                             sides=12)
    check_mesh(data)
    assert euler(data) == 0
    assert len(data.vertices) == 2 * 12 * (hs + 1) + 2 * 12 * (cs - 1)
    assert len(data.faces) == 2 * 12 * hs + 2 * 12 * cs
    assert_bbox(data, [(-1.0, 1.0), (-1.0, 1.0), (0.0, 2.0)])
    assert len(set(data.material_ids)) == 4


@pytest.mark.parametrize("hs,cs", [(1, 1), (3, 2)])
def test_tube_slice(hs, cs):
    data = geometry.generate("TUBE", radius1=1.0, radius2=0.5, height=1.0, height_segments=hs, cap_segments=cs,
                             sides=12, slice_on=True, slice_from=0.0, slice_to=math.pi)
    check_mesh(data)
    assert euler(data) == 2
    slice_faces = [m for m in data.material_ids if m == geometry.TUBE_MATERIALS["SLICE"]]
    assert len(slice_faces) == 2 * cs * hs


# -----------------------------------------------------------------------------
# Torus

def test_torus_default():
    data = geometry.generate("TORUS", radius1=1.0, radius2=0.25)
    check_mesh(data)
    assert euler(data) == 0
    assert len(data.vertices) == 24 * 12
    assert len(data.faces) == 24 * 12
    assert_bbox(data, [(-1.25, 1.25), (-1.25, 1.25), (-0.25, 0.25)], tol=1e-2)
    # Polygonal cross-section and ring: a little less than the smooth torus.
    smooth_volume = 2 * math.pi ** 2 * 1.0 * 0.25 ** 2
    assert 0.9 * smooth_volume < signed_volume(data) < smooth_volume


@pytest.mark.parametrize("mode,sharp", [("ALL", 0), ("NONE", None), ("SIDES", 24 * 12), ("SEGMENTS", 24 * 12)])
def test_torus_smoothing(mode, sharp):
    data = geometry.generate("TORUS", smooth_mode=mode)
    if sharp is None:
        assert all(data.flat_faces())
    else:
        assert len(data.sharp_edges()) == sharp


@pytest.mark.parametrize("segments,sides", [(3, 3), (7, 5), (24, 12)])
def test_torus_smoothing_odd_counts(segments, sides):
    for mode in ("SIDES", "SEGMENTS"):
        data = geometry.generate("TORUS", segments=segments, sides=sides, smooth_mode=mode)
        edge_faces = data.edge_faces()
        groups = data.smoothing_groups
        # Every edge between two sides (SIDES) or two segments (SEGMENTS) is sharp, every other edge smooth.
        expected = segments * sides
        assert len(data.sharp_edges()) == expected
        assert all(len(f) == 2 for f in edge_faces.values())
        assert all(g != 0 for g in groups)


def test_torus_twist_rotation_slice():
    data = geometry.generate("TORUS", rotation=0.3, twist=math.pi, slice_on=True, slice_from=0.0, slice_to=math.pi)
    check_mesh(data)
    assert euler(data) == 2
    assert len(data.vertices) == 25 * 12
    assert len(data.faces) == 24 * 12 + 2


# -----------------------------------------------------------------------------
# Pyramid

@pytest.mark.parametrize("ws,ds,hs", [(1, 1, 1), (2, 3, 4)])
def test_pyramid(ws, ds, hs):
    data = geometry.generate("PYRAMID", width=2.0, depth=4.0, height=3.0,
                             width_segments=ws, depth_segments=ds, height_segments=hs)
    check_mesh(data)
    assert euler(data) == 2
    assert len(data.vertices) == (ws + 1) * (ds + 1) + (hs - 1) * 2 * (ws + ds) + 1
    assert len(data.faces) == ws * ds + hs * 2 * (ws + ds)
    assert_bbox(data, [(-1.0, 1.0), (-2.0, 2.0), (0.0, 3.0)])
    assert approx(signed_volume(data), 2.0 * 4.0 * 3.0 / 3.0)
    # Base and four sides are separately smoothed.
    assert len(set(data.smoothing_groups)) == 5


# -----------------------------------------------------------------------------
# Test shape

def test_test_shape():
    data = geometry.generate("TEST_SHAPE", radius=1.0)
    check_mesh(data)
    assert sorted(set(data.material_ids)) == [0, 1, 2, 3]
    zs = [v[2] for v in data.vertices]
    assert approx(min(zs), 0.0)
    # Each part is a closed shell of its own.
    for material in range(4):
        part = geometry.MeshData(data.vertices, [f for f, m in zip(data.faces, data.material_ids) if m == material],
                                 None, [], [])
        directed = {(f[k], f[(k + 1) % len(f)]) for f in part.faces for k in range(len(f))}
        assert all((b, a) in directed for a, b in directed)


@pytest.mark.parametrize("segments", [1, 2, 6])
def test_test_shape_parts(segments):
    for part in ("part_body", "part_handle", "part_spout", "part_lid"):
        others = {name: name == part for name in ("part_body", "part_handle", "part_spout", "part_lid")}
        data = geometry.generate("TEST_SHAPE", segments=segments, **others)
        check_mesh(data)
        assert euler(data) == 2
