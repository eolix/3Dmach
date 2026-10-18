# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Scene-level import of synthetic .max files (layouts as verified on real files, no bytes from them): targets,
node flags, shapes with Extrude / Lathe, Unwrap UVW and UVW Map, Editable Mesh polygons, lights that become the
World, Blend materials and maps.
"""

import dataclasses
import math
import os
import struct
import sys
import tempfile
import unittest

import addon_utils
import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _runner_util

ROOT = os.environ.get("MX_TEST_ROOT", os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.insert(0, os.path.join(ROOT, "pylibs", "maxfile", "tests"))
import synth_max as sm  # noqa: E402
from synth_max import NULL, cont, f32, leaf, refs_ordered, u32  # noqa: E402

ID = {   # key: (class ID (a, b), superclass)
    "node": ((1, 0), 1),
    "pb": ((0x8, 0), 0x8),
    "target_cam": ((0x1002, 0), 0x20),
    "target_obj": ((0x1020, 0), 0x10),
    "prs": ((0x2005, 0), 0x9008),
    "look_at": ((0x2006, 0), 0x9008),
    "bezier_pos": ((0x2008, 0), 0x900B),
    "line": ((0x1040, 0), 0x40),
    "extrude": ((0x7E57, 0x0020), 0x810),     # Not in maxfile's registry: the stored name is used.
    "lathe": ((0x7E57, 0x0021), 0x810),
    "unwrap": ((0x02DF2E3A, 0x72BA4E1F), 0x810),
    "uvw_map": ((0xF72B1, 0), 0x810),
    "poly": ((0x1BF8338D, 0x192F6098), 0x10),
    "emesh": ((0xE44F10B3, 0), 0x10),
}
NAMES = {"extrude": "Extrude", "lathe": "Lathe", "unwrap": "Unwrap UVW", "uvw_map": "UVW Map"}
DERIVED = 0x2032
HIDDEN, FROZEN, TARGET = 1 << 20, 1 << 9, 1 << 14


class Builder(sm.SceneBuilder):
    def __init__(self):
        super().__init__()
        self.c = {key: self.cls(NAMES.get(key, key), cid, sup) for key, (cid, sup) in ID.items()}

    def add(self, key, *children):
        return self.obj(self.c[key], *children)

    def old_pb(self, values):
        children = [leaf(0x0001, u32(len(values)))]
        for index, value in sorted(values.items()):
            if isinstance(value, tuple):
                body = leaf(0x0102, f32(*value))
            elif isinstance(value, int):
                body = leaf(0x0101, struct.pack("<i", value))
            else:
                body = leaf(0x0100, f32(value))
            children.append(cont(0x0002, leaf(0x0003, u32(index)), body))
        return self.add("pb", *children)

    def pos(self, xyz):
        return self.add("bezier_pos", leaf(0x2503, f32(*xyz)))

    def prs(self, xyz):
        return self.add("prs", refs_ordered(self.pos(xyz)))

    def scene_node(self, name, obj, controller, flags=0, wire=None):
        extra = []
        if flags:
            extra.append(leaf(0x0960, u32(NULL, flags)))
        if wire is not None:
            extra.append(leaf(0x0974, bytes((*wire, 0))))
        return self.node(self.c["node"], name, refs=[controller, obj], extra=extra)


def knot(position, in_handle=None, out_handle=None, knot_type=1):
    in_handle = in_handle or position
    out_handle = out_handle or position
    return struct.pack("<IIf9fI", knot_type, 0, 1.0, *position, *in_handle, *out_handle, 0)


def polygon_knots(points):
    n = len(points)
    out = []
    for i, p in enumerate(points):
        prev, nxt = points[i - 1], points[(i + 1) % n]
        out.append(knot(p, tuple(p[k] + (prev[k] - p[k]) / 3 for k in range(3)),
                        tuple(p[k] + (nxt[k] - p[k]) / 3 for k in range(3))))
    return out


def line_object(b, points, closed=True):
    spline = cont(0x1010, leaf(0x2900, u32(len(points))), leaf(0x2904, u32(0)),
                  leaf(0x290A, b"".join(polygon_knots(points))), leaf(0x290D, u32(int(closed))))
    body = cont(0x2000, leaf(0x2000, u32(1)), cont(0x1010, spline), leaf(0x1060, u32(6)), leaf(0x10C0, u32(1)),
                leaf(0x10D0, u32(0)))
    return b.add("line", refs_ordered(NULL, NULL), body)


def mod_context(data=None):
    children = [leaf(0x2510, f32(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0) + u32(0)),
                leaf(0x2511, f32(-1, -1, 0, 1, 1, 0))]
    if data is not None:
        children.append(data)
    return cont(0x2500, *children)


SQUARE = [(-1.0, -1.0, 0.0), (1.0, -1.0, 0.0), (1.0, 1.0, 0.0), (-1.0, 1.0, 0.0)]


def scene_file():
    b = Builder()
    # Target camera with roll, its target, and node flags.
    cam_pb = b.old_pb({0: math.radians(60.0), 1: 0.0, 2: 1.0, 3: 1000.0, 4: 0.0, 5: 1000.0, 6: 0, 7: 0, 8: 0})
    camera = b.add("target_cam", refs_ordered(cam_pb))
    target = b.scene_node("Camera01.Target", b.add("target_obj"), b.prs((0.0, 100.0, 0.0)), flags=TARGET)
    look_at = b.add("look_at", refs_ordered(target, b.pos((0.0, 0.0, 0.0))))
    b.scene_node("Camera01", camera, look_at)
    # Shapes: a plain closed Line, the same profile extruded, a Lathe profile.
    b.scene_node("Outline", line_object(b, SQUARE), b.prs((0.0, 0.0, 0.0)), wire=(255, 0, 0))
    extrude_pb = b.old_pb({0: 5.0, 1: 2, 2: 1, 3: 1, 4: 0, 5: 1, 6: 0, 7: 1, 8: 0, 9: 1})
    extrude = b.add("extrude", refs_ordered(extrude_pb))
    stack = b.obj(DERIVED, refs_ordered(extrude, line_object(b, SQUARE)), mod_context())
    b.scene_node("Extruded", stack, b.prs((10.0, 0.0, 0.0)), flags=FROZEN)
    lathe_pb = b.old_pb({0: 360.0, 1: 12, 2: 1, 3: 1, 4: 0, 5: 0, 6: 1})
    lathe = b.add("lathe", refs_ordered(b.prs((0.0, 0.0, 0.0)), lathe_pb))
    profile = line_object(b, [(1.0, 0.0, 0.0), (2.0, 0.0, 0.0), (2.0, 3.0, 0.0), (1.0, 3.0, 0.0)])
    b.scene_node("Lathed", b.obj(DERIVED, refs_ordered(lathe, profile), mod_context()), b.prs((20, 0, 0)),
                 flags=HIDDEN)
    # Editable Poly quad with an Unwrap UVW storing its UVs, and a plane with a planar UVW Map.
    quad = b.add("poly", sm.poly_mesh(SQUARE, [(0, 1, 2, 3)]))
    tverts = u32(4) + b"".join(struct.pack("<3fIIi", u, v, 0.0, 0, 0xFFFFFFFF, 0)
                               for u, v in ((0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9)))
    faces = u32(1) + struct.pack("<I4I3I4I", 4, 0, 1, 2, 3, 0, 0, 0, 0, 1, 2, 3)
    unwrap_data = cont(0x2512, leaf(0x0860, tverts), leaf(0x0870, faces))
    unwrap = b.add("unwrap")
    b.scene_node("Unwrapped", b.obj(DERIVED, refs_ordered(unwrap, quad), mod_context(unwrap_data)),
                 b.prs((0.0, 20.0, 0.0)))
    uvw_pb = b.old_pb({0: 0, 1: 1.0, 2: 1.0, 3: 1.0, 9: 2.0, 10: 2.0, 11: 1.0, 12: 2, 13: 1})
    uvw = b.add("uvw_map", refs_ordered(b.prs((0.0, 0.0, 0.0)), uvw_pb))
    plane = b.add("poly", sm.poly_mesh(SQUARE, [(0, 1, 2, 3)]))
    b.scene_node("Mapped", b.obj(DERIVED, refs_ordered(uvw, plane), mod_context()), b.prs((0.0, 30.0, 0.0)))
    # Editable Mesh cube side: two triangles sharing a hidden diagonal.
    tris = b.add("emesh", sm.tri_mesh(SQUARE, [(0, 1, 2), (0, 2, 3)], edge_flags=[0b011, 0b110]))
    b.scene_node("Triangles", tris, b.prs((0.0, 40.0, 0.0)))
    return b.build()


class SceneImportTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.path = os.path.join(cls.tmp.name, "scene.max")
        with open(cls.path, "wb") as fh:
            fh.write(scene_file())

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        addon_utils.enable("mx_io_max", default_set=True)
        self.assertEqual(bpy.ops.import_scene.mx_max(filepath=self.path, units='meters'), {'FINISHED'})
        self.report = bpy.data.texts["Import Report"].as_string()

    def test_target_camera(self):
        cam, target = bpy.data.objects["Camera01"], bpy.data.objects["Camera01.Target"]
        self.assertEqual(target.type, 'EMPTY')
        self.assertEqual(target.empty_display_type, 'CUBE')
        con = cam.constraints[0]
        self.assertEqual((con.type, con.target), ('TRACK_TO', target))
        bpy.context.view_layer.update()
        forward = cam.matrix_world.to_3x3() @ __import__("mathutils").Vector((0.0, 0.0, -1.0))
        self.assertAlmostEqual(forward.y, 1.0, places=4)
        self.assertIs(bpy.context.scene.camera, cam)
        self.assertNotIn("object: Target", self.report)
        self.assertIn("targets: 1", self.report)

    def test_node_flags(self):
        outline, extruded, lathed = (bpy.data.objects[n] for n in ("Outline", "Extruded", "Lathed"))
        self.assertAlmostEqual(outline.color[0], 1.0, places=5)
        self.assertAlmostEqual(outline.color[1], 0.0, places=5)
        self.assertTrue(extruded.hide_select)
        self.assertTrue(extruded.get("mx_frozen"))
        self.assertTrue(lathed.hide_get())
        self.assertTrue(lathed.hide_render)

    def test_shapes(self):
        outline = bpy.data.objects["Outline"]
        self.assertEqual(outline.type, 'CURVE')
        spline = outline.data.splines[0]
        self.assertTrue(spline.use_cyclic_u)
        self.assertEqual(len(spline.bezier_points), 4)
        extruded = bpy.data.objects["Extruded"]
        self.assertEqual(extruded.type, 'MESH')
        mesh = extruded.data
        self.assertEqual(len(mesh.polygons), 8 + 4)        # 2 segments x 4 sides + 2 triangulated caps.
        self.assertAlmostEqual(max(v.co.z for v in mesh.vertices), 5.0, places=5)
        from mx_io_max import mesh_build
        self.assertEqual(sorted(set(mesh_build.face_material_ids(mesh).tolist())), [1, 2, 3])
        lathed = bpy.data.objects["Lathed"]
        screw = lathed.modifiers["Lathe"]
        self.assertEqual((screw.type, screw.steps), ('SCREW', 12))
        self.assertAlmostEqual(screw.angle, 2.0 * math.pi, places=5)
        self.assertEqual(len(lathed.data.edges), 4)

    def test_uv_modifiers(self):
        unwrapped = bpy.data.objects["Unwrapped"].data
        uvs = sorted(tuple(round(c, 4) for c in d.uv) for d in unwrapped.uv_layers["UVMap"].data)
        self.assertEqual(uvs, [(0.1, 0.1), (0.1, 0.9), (0.9, 0.1), (0.9, 0.9)])
        mapped = bpy.data.objects["Mapped"].data
        us = sorted(round(d.uv[0], 4) for d in mapped.uv_layers["UVMap"].data)
        self.assertEqual(us, [0.0, 0.0, 1.0, 1.0])
        self.assertEqual(len(bpy.data.objects["Mapped"].modifiers), 0)

    def test_triangles_become_polygons(self):
        mesh = bpy.data.objects["Triangles"].data
        self.assertEqual([len(p.vertices) for p in mesh.polygons], [4])


# Decoded stand-ins (the dataclass names are what the builder matches on).

@dataclasses.dataclass
class LightData:
    class_name: str
    params: dict
    target_node: int | None = None


@dataclasses.dataclass
class MaterialData:
    class_name: str
    name: str
    params: dict
    maps: dict
    sub_materials: list | None = None
    sub_ids: list | None = None
    components: list | None = None
    index: int | None = None


@dataclasses.dataclass
class MapData:
    class_name: str
    name: str = ""
    params: dict = dataclasses.field(default_factory=dict)
    path: str | None = None
    sub_maps: list = dataclasses.field(default_factory=list)
    index: int | None = None


@dataclasses.dataclass
class MeshData:
    positions: list
    faces: list
    material_ids: list
    smoothing_groups: list
    map_channels: dict
    edge_visibility: list | None = None


def two_node_file():
    b = Builder()
    geo = b.add("target_obj")
    other = b.add("target_obj")
    b.scene_node("A", geo, b.prs((0.0, 0.0, 0.0)))
    b.scene_node("B", other, b.prs((1.0, 0.0, 0.0)))
    b.scene_node("C", b.add("target_obj"), b.prs((2.0, 0.0, 0.0)))
    return b.build()


class DecodedImportTest(unittest.TestCase):
    """The builder fed with decoded stand-ins for the two nodes' objects (and A's material)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.path = os.path.join(cls.tmp.name, "two.max")
        with open(cls.path, "wb") as fh:
            fh.write(two_node_file())

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def build(self, a, b, material=None):
        import maxfile
        from mx_common.report import ImportReport
        from mx_io_max import build_scene
        bpy.ops.wm.read_factory_settings(use_empty=True)
        addon_utils.enable("mx_io_max", default_set=True)
        report = ImportReport()
        with maxfile.open(self.path) as mf:
            scene = mf.scene
            nodes = {n.name: n for n in mf.nodes}
            decoded = {nodes["A"].object.index: a, nodes["B"].object.index: b}
            if material is not None:
                holder = nodes["C"].object      # Any scene object works as the material's stand-in.
                nodes["A"].material = holder
                decoded[holder.index] = material
            original = scene.decode
            scene.decode = lambda obj: decoded.get(obj.index) if obj is not None and obj.index in decoded \
                else original(obj)
            builder = build_scene.SceneBuilder(bpy.context, self.path, build_scene.ImportSettings(units='meters'),
                                               report)
            builder.build(mf)
        return report

    def test_sky_and_sun_lights(self):
        report = self.build(LightData("Skylight", {"color": (0.2, 0.4, 0.6), "multiplier": 2.0}),
                            LightData("Sun_Positioner", {"sun_direction": (0.0, 0.0, 1.0)}))
        world = bpy.context.scene.world
        bg = next(n for n in world.node_tree.nodes if n.type == 'BACKGROUND')
        self.assertAlmostEqual(bg.inputs["Strength"].default_value, 2.0)
        self.assertEqual(bpy.data.objects["A"].type, 'EMPTY')
        sun = bpy.data.objects["B"]
        self.assertEqual((sun.type, sun.data.type), ('LIGHT', 'SUN'))
        bpy.context.view_layer.update()
        down = sun.matrix_world.to_3x3() @ __import__("mathutils").Vector((0.0, 0.0, -1.0))
        self.assertAlmostEqual(down.z, -1.0, places=4)
        self.assertEqual(report.imported["world"], 1)

    def test_blend_material_with_maps(self):
        mesh = MeshData([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [(0, 1, 2, 3)], [1], [1], {})
        noise = MapData("Noise", params={"size": 10.0, "color2": (1.0, 0.0, 0.0)}, index=900)
        red = MaterialData("PhysicalMaterial", "Red", {"base_color": (1.0, 0.0, 0.0)}, {"base_color_map": noise},
                           index=901)
        blue = MaterialData("Standardmaterial", "Blue", {"diffuse": (0.0, 0.0, 1.0)}, {}, index=902)
        blend = MaterialData("Blend", "Mixed", {"mix_amount": 0.5, "components": ["material1", "material2"]}, {},
                             components=[red, blue], index=903)
        self.build(mesh, mesh, material=blend)
        mat = bpy.data.objects["A"].material_slots[0].material
        self.assertEqual(mat.name, "Mixed")
        types = {n.type for n in mat.node_tree.nodes}
        self.assertIn('MIX_SHADER', types)
        self.assertIn('TEX_NOISE', types)


if __name__ == "__main__":
    _runner_util.main()
