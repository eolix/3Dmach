# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Blender-independent parts of the scene import: maps, UV generation, Unwrap UVW data, Extrude geometry, primitive
parameters, Arnold / sun lights. Run with: pytest tests/importer
"""

import dataclasses
import importlib
import importlib.util
import math
import os
import struct
import sys

import pytest

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
ADDON = os.path.join(ROOT, "scripts", "addons_core", "mx_io_max")
sys.path.insert(0, os.path.join(ROOT, "pylibs", "maxfile"))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


uv = _load("mx_uv", os.path.join(ADDON, "modifiers", "uv.py"))
shapes = _load("mx_shapes", os.path.join(ADDON, "shapes.py"))
prim = _load("mx_prim_convert", os.path.join(ADDON, "primitives", "convert.py"))
lights = _load("mx_lights2", os.path.join(ADDON, "lights.py"))
_spec = importlib.util.spec_from_file_location(
    "mx_materials2", os.path.join(ADDON, "materials", "__init__.py"),
    submodule_search_locations=[os.path.join(ADDON, "materials")])
_pkg = importlib.util.module_from_spec(_spec)
sys.modules["mx_materials2"] = _pkg
_spec.loader.exec_module(_pkg)
model = importlib.import_module("mx_materials2.model")
maps = importlib.import_module("mx_materials2.maps")


# Stand-ins with maxfile's field names.

@dataclasses.dataclass
class MapData:
    class_name: str
    name: str = ""
    params: dict = dataclasses.field(default_factory=dict)
    path: str | None = None
    sub_maps: list = dataclasses.field(default_factory=list)
    index: int | None = None
    resolved_path: str | None = None


@dataclasses.dataclass
class Knot:
    position: tuple
    in_handle: tuple
    out_handle: tuple
    knot_type: str = "corner"
    segment_type: str = "curve"


@dataclasses.dataclass
class Spline:
    knots: list
    closed: bool


def corner(p, prev, nxt):
    return Knot(p, tuple(p[i] + (prev[i] - p[i]) / 3 for i in range(3)),
                tuple(p[i] + (nxt[i] - p[i]) / 3 for i in range(3)))


def square(size, ccw=True):
    h = size / 2.0
    pts = [(-h, -h, 0.0), (h, -h, 0.0), (h, h, 0.0), (-h, h, 0.0)]
    if not ccw:
        pts.reverse()
    return Spline([corner(p, pts[i - 1], pts[(i + 1) % 4]) for i, p in enumerate(pts)], True)


def fan_tessellate(polys):
    """Stand-in for mathutils.geometry.tessellate_polygon on one convex polygon."""
    n = len(polys[0])
    return [(0, i, i + 1) for i in range(1, n - 1)]


# Maps.

class TestMaps:

    def test_bitmap_w_angle_resolved_path_and_channel(self):
        conv = maps.MapConverter()
        tex = conv.convert(MapData("Bitmaptexture", "wood", {"w_angle": 0.5, "u_tiling": 2.0, "map_channel": 2},
                                   path="C:\\maps\\wood.jpg", index=3, resolved_path="D:\\x\\wood.jpg"))
        assert isinstance(tex, model.Bitmap)
        assert tex.rotation == 0.5 and tex.tiling == (2.0, 1.0) and tex.uv_channel == 2
        assert tex.resolved_path == "D:\\x\\wood.jpg"

    def test_checker_noise_mix_normal(self):
        conv = maps.MapConverter()
        bitmap = MapData("Bitmaptexture", path="a.png", index=1)
        checker = conv.convert(MapData("Checker", params={"color1": (1, 0, 0), "map2": bitmap}, index=2))
        assert checker.color1 == (1.0, 0.0, 0.0) and isinstance(checker.map2, model.Bitmap)
        noise = conv.convert(MapData("Noise", params={"size": 10.0, "noise_type": 2, "levels": 4.0}, index=4))
        assert (noise.size, noise.kind, noise.levels) == (10.0, "TURBULENCE", 4.0)
        mix = conv.convert(MapData("Mix", params={"mix_amount": 0.25, "color1": (0, 0, 0), "color2": (1, 1, 1)},
                                   index=5))
        assert mix.amount == 0.25 and mix.a == (0.0, 0.0, 0.0)
        masked = conv.convert(MapData("Mix", params={"mask": bitmap, "mask_on": True}, index=6))
        assert isinstance(masked.amount, model.Bitmap)
        normal = conv.convert(MapData("Normal_Bump", params={"normal_map": bitmap, "mult_spin": 0.5,
                                                             "flip_green": True}, index=7))
        assert isinstance(normal, model.NormalMap) and normal.strength == 0.5 and normal.flip_green

    def test_param_block_maps(self):
        bitmap = MapData("Bitmaptexture", path="a.png", index=11)
        raw = {
            20: {0: (0.0, 0.0, 0.0), 4: (1.0, 1.0, 1.0), 6: 11, 7: True, 8: 2, 12: 1.33},
            21: {0: (0.1, 0.1, 0.1), 1: (0.5, 0.5, 0.5), 2: (0.9, 0.9, 0.9), 9: 0.3, 10: 1},
            22: {0: 11, 1: 11, 2: True, 3: True, 4: False},
            23: {1: 11, 7: 30.0, 8: -50.0},
        }
        conv = maps.MapConverter(param_reader=lambda tex, slot: raw.get(tex.index))
        falloff = conv.convert(MapData("Falloff", sub_maps=[bitmap], index=20))
        assert falloff.kind == "FRESNEL" and falloff.ior == 1.33 and isinstance(falloff.far, model.Bitmap)
        gradient = conv.convert(MapData("Gradient", index=21))
        assert gradient.kind == "RADIAL" and gradient.position2 == 0.3 and gradient.colors[2] == (0.9, 0.9, 0.9)
        mask = conv.convert(MapData("Mask", sub_maps=[bitmap], index=22))
        assert isinstance(mask, model.Mix) and isinstance(mask.amount, model.Bitmap)
        cc = conv.convert(MapData("Color Correction", sub_maps=[bitmap], index=23))
        assert isinstance(cc, model.ColorCorrection) and cc.hue == 30.0 and cc.saturation == -50.0

    def test_pass_through_and_unsupported(self):
        missing, notes = [], []
        conv = maps.MapConverter(unsupported=missing.append, note=notes.append)
        out = conv.convert(MapData("Output", sub_maps=[MapData("Bitmaptexture", path="b.png", index=9)], index=8))
        assert isinstance(out, model.Bitmap) and notes
        assert conv.convert(MapData("Smoke", index=10)) is None and missing == ["Smoke"]

    def test_uv_centre_rotation(self):
        (lx, ly), rz = maps.rotate_uv_center((1.0, 1.0), (0.0, 0.0), 0.0)
        assert (lx, ly, rz) == (0.0, 0.0, -0.0)
        # A quarter turn keeps the map centre in place.
        (lx, ly), rz = maps.rotate_uv_center((1.0, 1.0), (0.0, 0.0), math.pi / 2)
        c, s = math.cos(rz), math.sin(rz)
        assert (c * 0.5 - s * 0.5 + lx, s * 0.5 + c * 0.5 + ly) == pytest.approx((0.5, 0.5))


# UV modifiers.

IDENTITY = ((1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1))
HALF_TURN = ((-1, 0, 0, 0), (0, -1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1))     # The gizmo's rest rotation.


class TestUV:

    def test_planar_default_gizmo(self):
        corners = [(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)]
        uvs = uv.uvw_map(corners, [4], [(0, 0, 1)], {"map_type": 0, "width": 2.0, "length": 2.0}, HALF_TURN)
        assert uvs == pytest.approx([(0, 0), (1, 0), (1, 1), (0, 1)])

    def test_box_and_tiles(self):
        corners = [(1, -1, -1), (1, 1, -1), (1, 1, 1), (1, -1, 1)]
        params = {"map_type": 4, "width": 2, "length": 2, "height": 2, "u_tile": 2.0}
        uvs = uv.uvw_map(corners, [4], [(1, 0, 0)], params, HALF_TURN)
        assert uvs == pytest.approx([(0, 0), (2, 0), (2, 1), (0, 1)])

    def test_cylindrical_seam(self):
        corners = [(-1, -0.01, 0), (-1, 0.01, 0), (-1, 0.01, 1), (-1, -0.01, 1)]
        uvs = uv.uvw_map(corners, [4], [(-1, 0, 0)], {"map_type": 1, "height": 2.0}, IDENTITY)
        us = [u for u, _v in uvs]
        assert max(us) - min(us) < 0.1
        assert uv.uvw_map(corners, [4], [(-1, 0, 0)], {"map_type": 5}, IDENTITY) is None

    def test_parse_unwrap(self):
        class Chunk:
            def __init__(self, kind, data=b"", children=()):
                self.type, self.data, self.children, self.is_container = kind, data, list(children), bool(children)

            def find(self, kind):
                return next((c for c in self.children if c.type == kind), None)
        tverts = struct.pack("<I", 3) + b"".join(struct.pack("<3fIIi", u, v, 0, 0, 0xFFFFFFFF, 0)
                                                 for u, v in ((0, 0), (1, 0), (0, 1)))
        faces = struct.pack("<I", 1) + struct.pack("<I3I3I3I", 3, 0, 1, 2, 0, 0, 0, 5, 6, 7)
        data = Chunk(0x2512, children=[Chunk(0x0860, tverts), Chunk(0x0870, faces)])
        tv, fs = uv.parse_unwrap(data)
        assert tv[1] == (1.0, 0.0) and fs == [((0, 1, 2), (5, 6, 7))]
        bad = Chunk(0x2512, children=[Chunk(0x0860, tverts), Chunk(0x0870, faces + b"x")])
        assert uv.parse_unwrap(bad) is None


# Shapes.

class TestShapes:

    def test_polyline_straight_and_curved(self):
        pts, owners = shapes.polyline(square(2.0), steps=4)
        assert len(pts) == 4 and owners == [0, 1, 2, 3]
        curved = Spline([Knot((0, 0, 0), (0, 0, 0), (1, 1, 0)), Knot((3, 0, 0), (2, 1, 0), (3, 0, 0))], False)
        pts, owners = shapes.polyline(curved, steps=4)
        assert len(pts) == 6 and owners[0] == 0 and owners[-1] == 1

    def test_extrude_box(self):
        positions, faces, mat_ids, groups, sharp = shapes.extrude_mesh(
            [square(2.0, ccw=False)], 3.0, segments=2, tessellate=fan_tessellate)
        assert len(positions) == 12 and len(faces) == 8 + 4
        assert sorted(set(mat_ids)) == [1, 2, 3] and mat_ids.count(3) == 8
        assert max(p[2] for p in positions) == 3.0
        assert len(sharp) == 8      # Vertical edges at the 4 corner knots, 2 segments each.
        # Side normals point outwards although the spline was clockwise.
        a, b, c = (positions[i] for i in faces[0][:3])
        nx = (b[1] - a[1]) * (c[2] - a[2]) - (b[2] - a[2]) * (c[1] - a[1])
        ny = (b[2] - a[2]) * (c[0] - a[0]) - (b[0] - a[0]) * (c[2] - a[2])
        mid = [sum(positions[i][k] for i in faces[0]) / 4 for k in range(2)]
        assert nx * mid[0] + ny * mid[1] > 0.0
        # Caps face down (start) and up (end).
        for face, mid_id in zip(faces[8:], mat_ids[8:]):
            a, b, c = (positions[i] for i in face)
            nz = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
            assert (nz > 0) == (mid_id == 2)

    def test_extrude_hole_orientation(self):
        outer, hole = square(4.0, ccw=False), square(2.0, ccw=True)
        positions, faces, *_rest = shapes.extrude_mesh([outer, hole], 1.0, cap_start=False, cap_end=False)
        assert len(faces) == 8


# Primitives and lights.

def test_primitive_params():
    available = {"BOX": {"length": 1.0, "width": 1.0, "height": 1.0, "length_segments": 1},
                 "TEST_SHAPE": {"radius": 0.5, "segments": 4}}
    kind, params, notes = prim.builder_params("BOX", {"length": 10.0, "length_segments": 3, "odd": 1}, available,
                                              0.0254)
    assert kind == "BOX" and params["length"] == pytest.approx(0.254) and params["length_segments"] == 3
    assert notes and "odd" in notes[0]
    assert prim.builder_params("TEAPOT", {"radius": 2.0}, available)[0] == "TEST_SHAPE"
    kind, params, notes = prim.builder_params("CHAMFERBOX", {"length": 2.0, "fillet": 0.1}, available)
    assert kind == "BOX" and "fillet" not in params and notes
    assert prim.builder_params("HEDRA", {}, available)[0] is None


def test_lux_distance_in_scene_units():
    inches = lights.light_from_params("Free_Light", {"intensity": 100.0, "intensity_type": "lux",
                                                     "lux_at_distance": 39.370079}, unit_scale=0.0254)
    metres = lights.light_from_params("Free_Light", {"intensity": 100.0, "intensity_type": "lux",
                                                     "lux_at_distance": 1.0}, unit_scale=1.0)
    assert inches.power == pytest.approx(metres.power, rel=1e-5)


def test_arnold_and_world_lights():
    quad = lights.light_from_params("Arnold_Light", {"type": "quad", "quad_x": 2.0, "quad_y": 1.0,
                                                     "intensity": 1.0, "exposure": 3.0}, unit_scale=1.0)
    assert (quad.kind, quad.shape, quad.size, quad.size_y, quad.exposure) == ("AREA", "RECTANGLE", 2.0, 1.0, 3.0)
    spot = lights.light_from_params("Arnold_Light", {"type": "spot", "spot_cone_angle": 40.0}, unit_scale=0.01)
    assert spot.kind == "SPOT" and spot.spot_size == pytest.approx(math.radians(40.0))
    assert spot.power == pytest.approx(4.0 * math.pi * 1e-4)
    assert lights.light_from_params("Arnold_Light", {"type": "skydome"}) is None
    dome = lights.world_from_light("Arnold_Light", {"type": "skydome", "intensity": 2.0, "exposure": 1.0})
    assert dome.strength == 4.0
    sky = lights.world_from_light("Skylight", {"color": (0.5, 0.6, 0.7), "multiplier": 1.5})
    assert sky.color == (0.5, 0.6, 0.7) and sky.strength == 1.5
    sun = lights.light_from_params("Sun_Positioner", {"sun_direction": (0.0, 0.6, 0.8)})
    assert sun.kind == "SUN" and sun.direction == (-0.0, -0.6, -0.8)
    assert lights.world_from_light("Sun_Positioner", {"sun_direction": (0.0, 0.6, 0.8)}).sky


def test_exposure_from_ev():
    assert lights.exposure_from_ev(6.0) == pytest.approx(2.29, abs=0.01)
    assert lights.exposure_from_ev(8.0) - lights.exposure_from_ev(9.0) == pytest.approx(1.0)


def test_standard_far_attenuation():
    omni = lights.light_from_params("Omnilight", {"use_far_atten": True, "far_atten_end": 200.0})
    assert omni.cutoff_distance == 200.0
