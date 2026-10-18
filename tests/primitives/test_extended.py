# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Geometry of the extended live primitives (ChamferBox, ChamferCyl, Capsule, OilTank, Spindle, Gengon, Prism, L-Ext,
C-Ext, Torus Knot, Hedra), without Blender. Run with ``python3 -m pytest tests/primitives``.
"""

import math

import pytest

from test_geometry import (
    GEO_UV_RANGE,
    approx,
    assert_bbox,
    bbox,
    check_mesh,
    euler,
    geometry,
    newell_normal,
    signed_volume,
)

EXTENDED = ("CHAMFERBOX", "CHAMFERCYL", "CAPSULE", "OILTANK", "SPINDLE", "GENGON", "PRISM", "L_EXT", "C_EXT",
            "TORUS_KNOT", "HEDRA")


def check(data, kind=None, closed_euler=2):
    check_mesh(data, uv_range=GEO_UV_RANGE if kind == "HEDRA" else (0.0, 1.0))
    assert euler(data) == closed_euler


def planar(data, tol=1e-6):
    for face in data.faces:
        pts = [data.vertices[i] for i in face]
        n = newell_normal(pts)
        length = math.sqrt(sum(c * c for c in n))
        d0 = sum(n[k] * pts[0][k] for k in range(3)) / length
        assert all(abs(sum(n[k] * p[k] for k in range(3)) / length - d0) < tol for p in pts), face


def revolve_counts(sides, nodes, flat_caps=False):
    """Vertices and faces of a closed surface of revolution with ``nodes`` profile nodes from pole to pole."""
    if flat_caps:
        return sides * (nodes - 2), sides * (nodes - 3) + 2
    return sides * (nodes - 2) + 2, sides * (nodes - 1)


@pytest.mark.parametrize("kind", EXTENDED)
def test_defaults(kind):
    check(geometry.generate(kind), kind, 0 if kind == "TORUS_KNOT" else 2)


@pytest.mark.parametrize("kind", EXTENDED)
def test_parameters_have_limits_and_names(kind):
    assert kind in geometry.KIND_IDS
    for name, default in geometry.PARAMETERS[kind].items():
        if isinstance(default, str):
            assert default in geometry.ENUMS[name]


# -----------------------------------------------------------------------------
# ChamferBox

@pytest.mark.parametrize("ws,ls,hs,fs", [(1, 1, 1, 1), (1, 1, 1, 3), (2, 3, 4, 2), (3, 1, 2, 5)])
def test_chamfer_box_counts(ws, ls, hs, fs):
    data = geometry.generate("CHAMFERBOX", width=2.0, length=3.0, height=4.0, fillet=0.4, width_segments=ws,
                             length_segments=ls, height_segments=hs, fillet_segments=fs)
    check(data)
    flat = 2 * (ws * ls + ws * hs + ls * hs)
    edges = 4 * fs * (ws + ls + hs)
    corners = 8 * fs * (fs + 1) // 2
    assert len(data.faces) == flat + edges + corners
    # Each corner's rows of quads end in a triangle.
    assert sum(len(face) == 3 for face in data.faces) == 8 * fs
    assert_bbox(data, [(-1.0, 1.0), (-1.5, 1.5), (0.0, 4.0)])
    # Every vertex is the fillet radius away from the box shrunk by the fillet.
    inner = ((-0.6, 0.6), (-1.1, 1.1), (0.4, 3.6))
    for v in data.vertices:
        nearest = [min(max(v[k], inner[k][0]), inner[k][1]) for k in range(3)]
        assert approx(math.dist(v, nearest), 0.4)
    # The flat sides keep the Box's material IDs; the fillets have their own.
    assert sorted(set(data.material_ids)) == [0, 1, 2, 3, 4, 5, geometry.CHAMFERBOX_FILLET_MATERIAL]


def test_chamfer_box_classic_chamfer():
    # One fillet segment: 6 sides, 12 edge bevels, 8 corner triangles.
    data = geometry.generate("CHAMFERBOX", fillet_segments=1)
    assert (len(data.vertices), len(data.faces)) == (24, 26)


@pytest.mark.parametrize("fillet", [0.0, 0.5, 2.0])
def test_chamfer_box_fillet_extremes(fillet):
    data = geometry.generate("CHAMFERBOX", width=1.0, length=2.0, height=3.0, fillet=fillet)
    check(data)
    assert_bbox(data, [(-0.5, 0.5), (-1.0, 1.0), (0.0, 3.0)])
    if fillet == 0.0:
        assert (len(data.vertices), len(data.faces)) == (8, 6)


def test_chamfer_box_negative_height():
    data = geometry.generate("CHAMFERBOX", height=-2.0)
    check(data)
    assert_bbox(data, [(-0.5, 0.5), (-0.5, 0.5), (-2.0, 0.0)])


def test_chamfer_box_smoothing():
    assert set(geometry.generate("CHAMFERBOX").smoothing_groups) == {1}
    assert set(geometry.generate("CHAMFERBOX", smooth=False).smoothing_groups) == {0}


# -----------------------------------------------------------------------------
# ChamferCyl

@pytest.mark.parametrize("hs,fs,cs,sides", [(1, 1, 1, 12), (3, 2, 1, 8), (2, 4, 3, 7), (1, 1, 2, 3)])
def test_chamfer_cyl_counts(hs, fs, cs, sides):
    data = geometry.generate("CHAMFERCYL", radius=1.0, height=2.0, fillet=0.25, height_segments=hs,
                             fillet_segments=fs, cap_segments=cs, sides=sides)
    check(data)
    nodes = 2 * cs + 2 * fs + hs + 1
    assert (len(data.vertices), len(data.faces)) == revolve_counts(sides, nodes, flat_caps=cs == 1)
    lo, hi = bbox(data)[0]
    assert approx(hi, 1.0) and approx(bbox(data)[2][0], 0.0) and approx(bbox(data)[2][1], 2.0)
    # The rounded edges: every vertex off the caps' plane and off the side is on a fillet circle.
    for x, y, z in data.vertices:
        rho = math.hypot(x, y)
        if 0.25 < z < 1.75 or rho < 0.75 - 1e-9:
            continue
        zc = 0.25 if z < 1.0 else 1.75
        assert approx(math.hypot(rho - 0.75, z - zc), 0.25, 1e-6) or approx(rho, 1.0)


def test_chamfer_cyl_default_and_materials():
    data = geometry.generate("CHAMFERCYL")
    assert (len(data.vertices), len(data.faces)) == (48, 38)
    assert sorted(set(data.material_ids)) == [0, 1, 2]
    assert_bbox(data, [(-0.5, 0.5), (-0.5, 0.5), (0.0, 1.0)])


@pytest.mark.parametrize("fillet", [0.0, 0.5])
def test_chamfer_cyl_fillet_extremes(fillet):
    data = geometry.generate("CHAMFERCYL", radius=0.5, height=1.0, fillet=fillet, fillet_segments=3)
    check(data)
    assert_bbox(data, [(-0.5, 0.5), (-0.5, 0.5), (0.0, 1.0)])


@pytest.mark.parametrize("cs", [1, 2])
def test_chamfer_cyl_slice(cs):
    data = geometry.generate("CHAMFERCYL", cap_segments=cs, slice_on=True, slice_from=0.0, slice_to=math.pi)
    check(data)
    assert sum(1 for m in data.material_ids if m == geometry.CAP_MATERIALS["SLICE"]) == 2
    whole = geometry.generate("CHAMFERCYL", cap_segments=cs, sides=24)
    assert approx(signed_volume(data) * 2.0, signed_volume(whole), 0.01 * signed_volume(whole))


def test_chamfer_cyl_negative_height():
    data = geometry.generate("CHAMFERCYL", height=-1.0)
    check(data)
    assert_bbox(data, [(-0.5, 0.5), (-0.5, 0.5), (-1.0, 0.0)])


# -----------------------------------------------------------------------------
# Capsule

def test_capsule_matches_max():
    # An 8-sided Capsule converted to Editable Mesh in Max (corpus, radius 4.7323, overall height 118.7565): 66
    # vertices, 128 triangles; the top pole, rings from the top starting on +X with 4 bands per hemisphere; all
    # faces in smoothing group 3 and material ID 1.
    data = geometry.generate("CAPSULE", radius=4.7323, height=118.7565, sides=8, height_segments=1)
    check(data)
    assert len(data.vertices) == 66
    assert sum(len(face) - 2 for face in data.faces) == 128
    expected = {0: (0.0, 0.0, 118.7565), 1: (1.811, 0.0, 118.3963), 2: (1.2806, 1.2806, 118.3963),
                3: (0.0, 1.811, 118.3963), 25: (4.7323, 0.0, 114.0242), 33: (4.7323, 0.0, 4.7323), 65: (0, 0, 0)}
    for index, point in expected.items():
        assert all(abs(a - b) < 2e-4 for a, b in zip(data.vertices[index], point)), index
    assert data.faces[0] == (0, 1, 2)
    # Quads split as in Max's triangles (25, 33, 34) / (25, 34, 26); the bottom fan as (63, 65, 64), (64, 65, 57).
    assert (25, 33, 34, 26) in data.faces
    assert data.faces[-2:] == [(63, 65, 64), (64, 65, 57)]
    assert set(data.smoothing_groups) == {4} and set(data.material_ids) == {0}


@pytest.mark.parametrize("sides,hs", [(12, 1), (8, 3), (5, 2), (3, 1)])
def test_capsule_counts(sides, hs):
    data = geometry.generate("CAPSULE", radius=1.0, height=5.0, sides=sides, height_segments=hs)
    check(data)
    q = max(1, sides // 2)
    assert (len(data.vertices), len(data.faces)) == revolve_counts(sides, 2 * q + hs + 1)
    zs = [v[2] for v in data.vertices]
    assert approx(min(zs), 0.0) and approx(max(zs), 5.0)


def test_capsule_height_types():
    overall = geometry.generate("CAPSULE", radius=1.0, height=3.0, height_type="OVERALL")
    centres = geometry.generate("CAPSULE", radius=1.0, height=3.0, height_type="CENTERS")
    assert approx(bbox(overall)[2][1], 3.0) and approx(bbox(centres)[2][1], 5.0)
    # Overall heights below the diameter give a sphere (the bands of the cylinder merge).
    short = geometry.generate("CAPSULE", radius=1.0, height=1.0, sides=12)
    check(short)
    assert approx(bbox(short)[2][1], 2.0)
    assert (len(short.vertices), len(short.faces)) == revolve_counts(12, 13)


def test_capsule_slice():
    data = geometry.generate("CAPSULE", slice_on=True, slice_from=0.5, slice_to=2.0)
    check(data)
    assert sum(1 for m in data.material_ids if m == 1) == 2


# -----------------------------------------------------------------------------
# OilTank and Spindle

@pytest.mark.parametrize("sides,hs,blend", [(12, 1, 0.0), (14, 3, 0.0), (12, 2, 0.1), (5, 1, 0.05)])
def test_oil_tank_counts(sides, hs, blend):
    data = geometry.generate("OILTANK", radius=0.5, height=2.0, cap_height=0.3, blend=blend, sides=sides,
                             height_segments=hs)
    check(data)
    caps = max(2, (sides + 3) // 4)
    nodes = 2 * caps + hs + (3 if blend else 1)
    assert (len(data.vertices), len(data.faces)) == revolve_counts(sides, nodes)
    zs = [v[2] for v in data.vertices]
    assert approx(min(zs), 0.0) and approx(max(zs), 2.0)


def test_oil_tank_smoothing_like_max():
    # A converted OilTank: the caps in smoothing group 3, the cylinder in group 4, all material ID 1.
    data = geometry.generate("OILTANK", sides=14)
    assert set(data.material_ids) == {0}
    assert set(data.smoothing_groups) == {4, 8}
    assert sum(1 for g in data.smoothing_groups if g == 4) == 2 * 14 * 4
    blended = geometry.generate("OILTANK", blend=0.05)
    assert 12 in blended.smoothing_groups


def test_oil_tank_caps():
    data = geometry.generate("OILTANK", radius=1.0, height=4.0, cap_height=0.5, height_type="CENTERS")
    check(data)
    assert approx(bbox(data)[2][1], 5.0)
    flat = geometry.generate("OILTANK", cap_height=0.0)
    check(flat)
    assert approx(bbox(flat)[2][1], 2.0)
    data = geometry.generate("OILTANK", slice_on=True, slice_to=2.0, blend=0.1)
    check(data)


@pytest.mark.parametrize("cs,hs,blend", [(1, 1, 0.0), (3, 2, 0.0), (2, 1, 0.1)])
def test_spindle_counts(cs, hs, blend):
    data = geometry.generate("SPINDLE", radius=0.5, height=2.0, cap_height=0.5, cap_segments=cs,
                             height_segments=hs, blend=blend, sides=10)
    check(data)
    nodes = 2 * cs + hs + (3 if blend else 1)
    assert (len(data.vertices), len(data.faces)) == revolve_counts(10, nodes)
    # Pointed ends on the axis.
    assert approx(data.vertices[0][2], 2.0) and approx(data.vertices[-1][2], 0.0)
    assert approx(math.hypot(*data.vertices[0][:2]), 0.0)


def test_spindle_volume():
    data = geometry.generate("SPINDLE", radius=1.0, height=4.0, cap_height=1.0, sides=64, smooth=False)
    expected = math.pi * (2.0 + 2.0 / 3.0)
    assert approx(signed_volume(data), expected, 0.01 * expected)
    assert set(data.smoothing_groups) == {0}


def test_ring_start_extended():
    # Like Max's Cylinder and the converted Capsule: rings start at +X.
    for kind in ("CHAMFERCYL", "CAPSULE", "OILTANK", "SPINDLE"):
        data = geometry.generate(kind, sides=9)
        first = [v for v in data.vertices if math.hypot(v[0], v[1]) > 1e-9][0]
        assert approx(first[1], 0.0) and first[0] > 0.0, kind


# -----------------------------------------------------------------------------
# Gengon

@pytest.mark.parametrize("sides,fillet,fs,ss,hs", [(5, 0.0, 1, 1, 1), (6, 0.1, 3, 2, 2), (3, 0.05, 1, 1, 4),
                                                   (8, 0.2, 2, 3, 1)])
def test_gengon_counts(sides, fillet, fs, ss, hs):
    data = geometry.generate("GENGON", sides=sides, radius=1.0, fillet=fillet, height=2.0, fillet_segments=fs,
                             side_segments=ss, height_segments=hs)
    check(data)
    planar(data)
    outline = sides * ((fs if fillet else 0) + ss)
    assert len(data.vertices) == outline * (hs + 1)
    assert len(data.faces) == outline * hs + 2
    assert approx(bbox(data)[2][0], 0.0) and approx(bbox(data)[2][1], 2.0)
    if not fillet:
        # Corners on the radius, the first on +X.
        assert approx(bbox(data)[0][1], 1.0)
        assert approx(signed_volume(data), 2.0 * 0.5 * sides * math.sin(2.0 * math.pi / sides))


def test_gengon_full_fillet_is_round():
    data = geometry.generate("GENGON", sides=6, radius=1.0, fillet=5.0, fillet_segments=4)
    check(data)
    inradius = math.cos(math.pi / 6)
    assert all(approx(math.hypot(x, y), inradius) for x, y, _z in data.vertices)
    assert len(data.vertices) == 2 * 6 * 4


def test_gengon_materials():
    data = geometry.generate("GENGON")
    assert sorted(set(data.material_ids)) == [0, 1, 2]


# -----------------------------------------------------------------------------
# Prism

@pytest.mark.parametrize("a,b,c", [(1.0, 1.0, 1.0), (3.0, 2.0, 2.5), (2.0, 1.0, 1.5)])
@pytest.mark.parametrize("segments", [(1, 1, 1, 1), (2, 3, 4, 2)])
def test_prism(a, b, c, segments):
    s1, s2, s3, hs = segments
    data = geometry.generate("PRISM", side1_length=a, side2_length=b, side3_length=c, height=1.5,
                             side1_segments=s1, side2_segments=s2, side3_segments=s3, height_segments=hs)
    check(data)
    planar(data)
    outline = s1 + s2 + s3
    assert len(data.vertices) == outline * (hs + 1)
    assert len(data.faces) == outline * hs + 2
    # The triangle has the given sides: Heron's area.
    s = 0.5 * (a + b + c)
    area = math.sqrt(s * (s - a) * (s - b) * (s - c))
    assert approx(signed_volume(data), area * 1.5)
    assert approx(bbox(data)[0][0], 0.0) and approx(bbox(data)[0][1], max(a, (a * a + c * c - b * b) / (2 * a)))
    assert len(set(data.material_ids)) == 5


def test_prism_impossible_triangle_is_clamped():
    data = geometry.generate("PRISM", side1_length=1.0, side2_length=1.0, side3_length=5.0)
    check(data)


# -----------------------------------------------------------------------------
# L-Ext and C-Ext

@pytest.mark.parametrize("ss,fs,ws,hs", [(1, 1, 1, 1), (3, 2, 2, 1), (1, 4, 1, 3)])
def test_l_ext(ss, fs, ws, hs):
    data = geometry.generate("L_EXT", side_length=2.0, front_length=3.0, side_width=0.5, front_width=0.25,
                             height=1.0, side_segments=ss, front_segments=fs, width_segments=ws, height_segments=hs)
    check(data)
    planar(data)
    cells = ws * ws + fs * ws + ws * ss
    outline = 4 * ws + 2 * fs + 2 * ss
    points = (ws + 1) * (ws + 1 + fs + ss)
    assert len(data.faces) == 2 * cells + outline * hs
    assert len(data.vertices) == 2 * points + (hs - 1) * outline
    assert_bbox(data, [(-1.5, 1.5), (-1.0, 1.0), (0.0, 1.0)])
    assert approx(signed_volume(data), 3.0 * 0.25 + 0.5 * (2.0 - 0.25))
    # Six flat walls, each with its own material ID and smoothing group.
    assert sorted(set(data.material_ids)) == list(range(8))


def test_l_ext_negative_lengths_mirror():
    data = geometry.generate("L_EXT", side_length=-2.0, front_length=1.0)
    check(data)
    # The front leg is now at +Y.
    assert any(approx(v[1], 1.0) and approx(v[0], 0.5) for v in data.vertices)
    data = geometry.generate("L_EXT", side_length=-2.0, front_length=-1.0)
    check(data)


@pytest.mark.parametrize("bs,ss,fs,ws,hs", [(1, 1, 1, 1, 1), (2, 3, 1, 2, 2)])
def test_c_ext(bs, ss, fs, ws, hs):
    data = geometry.generate("C_EXT", back_length=2.0, side_length=3.0, front_length=1.5, back_width=0.3,
                             side_width=0.4, front_width=0.5, height=2.0, back_segments=bs, side_segments=ss,
                             front_segments=fs, width_segments=ws, height_segments=hs)
    check(data)
    planar(data)
    cells = 2 * ws * ws + ws * (fs + bs + ss)
    outline = 6 * ws + 2 * (fs + bs + ss)
    points = (ws + 1) * (2 * ws + 1 + fs + bs + ss)
    assert len(data.faces) == 2 * cells + outline * hs
    assert len(data.vertices) == 2 * points + (hs - 1) * outline
    assert_bbox(data, [(-1.0, 1.0), (-1.5, 1.5), (0.0, 2.0)])
    area = 1.5 * 0.5 + 2.0 * 0.3 + 0.4 * (3.0 - 0.5 - 0.3)
    assert approx(signed_volume(data), area * 2.0)
    assert sorted(set(data.material_ids)) == list(range(10))


def test_extrusions_empty_while_creating():
    # Zero widths (the start of the interactive width step) give an empty mesh rather than an error.
    for kind in ("L_EXT", "C_EXT"):
        widths = {name: 0.0 for name in ("side_width", "front_width", "back_width") if name in
                  geometry.PARAMETERS[kind]}
        data = geometry.generate(kind, **widths)
        assert data.faces == []
    assert geometry.generate("GENGON", radius=0.0).faces == []


# -----------------------------------------------------------------------------
# Torus Knot

@pytest.mark.parametrize("params", [{}, {"p": 3.0, "q": 5.0, "segments": 150, "sides": 7},
                                    {"twist": 4.0 * math.pi, "lumps": 3.0, "lump_height": 0.5, "eccentricity": 0.5},
                                    {"base_curve": "CIRCLE", "warp_count": 5.0, "warp_height": 0.25}])
def test_torus_knot(params):
    data = geometry.generate("TORUS_KNOT", **params)
    check(data, closed_euler=0)
    m = params.get("segments", 120)
    n = params.get("sides", 12)
    assert len(data.vertices) == m * n and len(data.faces) == m * n
    # The tube closes smoothly: the seam is no longer than the other steps along the knot.
    v = data.vertices
    steps = [max(math.dist(v[i * n + j], v[((i + 1) % m) * n + j]) for j in range(n)) for i in range(m)]
    assert steps[-1] < 1.5 * max(steps[:-1])


def test_torus_knot_circle_bounds():
    data = geometry.generate("TORUS_KNOT", base_curve="CIRCLE", radius=2.0, cross_section_radius=0.5,
                             segments=64, sides=16)
    assert_bbox(data, [(-2.5, 2.5), (-2.5, 2.5), (-0.5, 0.5)], tol=0.02)


def test_torus_knot_size_and_smoothing():
    data = geometry.generate("TORUS_KNOT", radius=3.0, cross_section_radius=0.2)
    assert max(math.sqrt(sum(c * c for c in v)) for v in data.vertices) <= 3.2 + 1e-6
    assert set(data.smoothing_groups) == {1}
    assert set(geometry.generate("TORUS_KNOT", smooth_mode="NONE").smoothing_groups) == {0}
    sides = geometry.generate("TORUS_KNOT", smooth_mode="SIDES", segments=30, sides=5)
    assert len(sides.sharp_edges()) == 30 * 5


# -----------------------------------------------------------------------------
# Hedra

@pytest.mark.parametrize("family,p,q,counts", [
    ("TETRA", 0.0, 0.0, (4, 4)), ("TETRA", 1.0, 0.0, (4, 4)), ("TETRA", 0.0, 1.0, (6, 8)),
    ("TETRA", 0.0, 0.5, (12, 8)), ("TETRA", 0.3, 0.3, (24, 14)),
    ("CUBE_OCTA", 0.0, 0.0, (6, 8)), ("CUBE_OCTA", 1.0, 0.0, (8, 6)), ("CUBE_OCTA", 0.0, 1.0, (12, 14)),
    ("CUBE_OCTA", 0.0, 0.5, (24, 14)), ("CUBE_OCTA", 0.5, 0.0, (24, 26)), ("CUBE_OCTA", 0.3, 0.3, (48, 26)),
    ("DODEC_ICOS", 0.0, 0.0, (12, 20)), ("DODEC_ICOS", 1.0, 0.0, (20, 12)), ("DODEC_ICOS", 0.0, 1.0, (30, 32)),
    ("DODEC_ICOS", 0.0, 0.4, (60, 32)), ("DODEC_ICOS", 0.3, 0.3, (120, 62)),
    ("STAR1", 0.0, 0.0, (32, 60)), ("STAR2", 0.0, 0.0, (32, 60)),
])
def test_hedra_families(family, p, q, counts):
    data = geometry.generate("HEDRA", family=family, family_p=p, family_q=q, radius=2.0)
    check(data, "HEDRA")
    assert (len(data.vertices), len(data.faces)) == counts
    if not family.startswith("STAR"):
        planar(data)
        assert approx(max(math.sqrt(sum(c * c for c in v)) for v in data.vertices), 2.0)
        # Convex: every vertex is behind every face.
        for face in data.faces:
            pts = [data.vertices[i] for i in face]
            n = newell_normal(pts)
            d0 = sum(n[k] * pts[0][k] for k in range(3))
            assert all(sum(n[k] * v[k] for k in range(3)) <= d0 + 1e-6 for v in data.vertices)


def test_hedra_p_plus_q_is_limited():
    a = geometry.generate("HEDRA", family="CUBE_OCTA", family_p=0.8, family_q=0.8)
    b = geometry.generate("HEDRA", family="CUBE_OCTA", family_p=0.5, family_q=0.5)
    assert len(a.vertices) == len(b.vertices)


def test_hedra_vertex_modes_and_axis_scaling():
    centre = geometry.generate("HEDRA", vertex_mode="CENTER")
    check(centre, "HEDRA")
    assert (len(centre.vertices), len(centre.faces)) == (8, 12)
    sides = geometry.generate("HEDRA", vertex_mode="CENTER_SIDES")
    check(sides, "HEDRA")
    assert (len(sides.vertices), len(sides.faces)) == (14, 12)
    pushed = geometry.generate("HEDRA", family="CUBE_OCTA", axis_scale_p=250.0)
    check(pushed, "HEDRA")
    assert len(pushed.faces) == 24
    assert max(math.sqrt(sum(c * c for c in v)) for v in pushed.vertices) > 0.5
    # Material IDs follow the face kinds: P faces 0, Q faces 1, R faces 2.
    mixed = geometry.generate("HEDRA", family="CUBE_OCTA", family_p=0.3, family_q=0.3)
    assert sorted(set(mixed.material_ids)) == [0, 1, 2]
