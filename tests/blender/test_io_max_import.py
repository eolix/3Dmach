# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
End-to-end import of synthetic .max files (built by maxfile's test helpers to the layouts verified on real files),
plus the scene builder's geometry/material/modifier paths driven by stand-in decoded data.
"""

import dataclasses
import math
import os
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


def synthetic_scene():
    """Root > Box001 (at 1, 2, 3 inches, child Box002 at 0, 0, 10), plus an unknown plugin object."""
    b = sm.SceneBuilder()
    node = b.cls("Node", (1, 0), 1)
    prs = b.cls("PRS", (0x2005, 0), 0x9008)
    bez = b.cls("BezPos", (0x2008, 0), 0x900B)
    weird = b.cls("WeirdPlugin", (0xABCD, 0x1234), 0x10)
    p1 = b.obj(bez, sm.leaf(0x2503, sm.f32(1, 2, 3)))
    c1 = b.obj(prs, sm.refs_ordered(p1))
    p2 = b.obj(bez, sm.leaf(0x2503, sm.f32(0, 0, 10)))
    c2 = b.obj(prs, sm.refs_ordered(p2))
    geo = b.obj(weird)
    root = b.node(node, "Root")
    box1 = b.node(node, "Box001", parent=root, refs=[c1, geo])
    b.node(node, "Box002", parent=box1, refs=[c2, geo])
    return b.build(compress=("Scene",))


# Stand-ins with the dataclass names the builder matches on (see maxfile's decoder contract).

@dataclasses.dataclass
class MapChannel:
    vertices: list
    faces: list


@dataclasses.dataclass
class MeshData:
    positions: list
    faces: list
    material_ids: list
    smoothing_groups: list
    map_channels: dict
    source: str = "test"


@dataclasses.dataclass
class MaterialData:
    class_name: str
    name: str
    params: dict
    maps: dict
    sub_materials: list | None = None
    sub_ids: list | None = None


CUBE = MeshData(
    positions=[(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0), (0, 0, 10), (10, 0, 10), (10, 10, 10), (0, 10, 10)],
    faces=[(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)],
    material_ids=[1, 2, 3, 3, 3, 3],
    smoothing_groups=[1, 2, 4, 4, 4, 4],
    map_channels={1: MapChannel(vertices=[(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)],
                                faces=[(0, 1, 2, 3)] * 6)},
)


class ImportTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        addon_utils.enable("mx_io_max", default_set=True)
        cls.tmp = tempfile.TemporaryDirectory()
        cls.path = os.path.join(cls.tmp.name, "synthetic.max")
        with open(cls.path, "wb") as fh:
            fh.write(synthetic_scene())

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()
        addon_utils.disable("mx_io_max", default_set=True)

    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        addon_utils.enable("mx_io_max", default_set=True)

    def test_hierarchy_transforms_units(self):
        result = bpy.ops.import_scene.mx_max(filepath=self.path, units='inches')
        self.assertEqual(result, {'FINISHED'})
        coll = bpy.data.collections["synthetic"]
        names = sorted(o.name for o in coll.objects)
        self.assertEqual(names, ["Box001", "Box002", "Root"])
        box1, box2 = bpy.data.objects["Box001"], bpy.data.objects["Box002"]
        self.assertIs(box1.parent, bpy.data.objects["Root"])
        self.assertIs(box2.parent, box1)
        bpy.context.view_layer.update()
        inch = 0.0254
        for got, want in zip(box1.matrix_world.translation, (1 * inch, 2 * inch, 3 * inch)):
            self.assertAlmostEqual(got, want, places=6)
        self.assertAlmostEqual(box2.matrix_world.translation.z, 13 * inch, places=6)
        self.assertEqual(tuple(box1.scale), (1.0, 1.0, 1.0))
        report = bpy.data.texts["Import Report"].as_string()
        self.assertIn("object: WeirdPlugin x2", report)
        self.assertIn("empties: 3", report)

    def test_unit_choice_and_scale(self):
        bpy.ops.import_scene.mx_max(filepath=self.path, units='meters', global_scale=2.0, use_collection=False)
        bpy.context.view_layer.update()
        self.assertAlmostEqual(bpy.data.objects["Box001"].matrix_world.translation.x, 2.0, places=6)
        self.assertNotIn("synthetic", bpy.data.collections)

    def test_bad_files(self):
        bad = os.path.join(self.tmp.name, "bad.max")
        with open(bad, "wb") as fh:
            fh.write(b"not a compound file")
        with self.assertRaisesRegex(RuntimeError, "Not a .max file"):
            bpy.ops.import_scene.mx_max(filepath=bad)
        truncated = os.path.join(self.tmp.name, "truncated.max")
        with open(truncated, "wb") as fh:
            fh.write(synthetic_scene()[:700])
        with self.assertRaisesRegex(RuntimeError, "Cannot import"):
            bpy.ops.import_scene.mx_max(filepath=truncated)
        self.assertEqual(len(bpy.data.objects), 0)

    def builder_with_decoded(self, decoded):
        """Import the synthetic file with `scene.decode` answering from ``decoded`` (object index -> data)."""
        import maxfile
        from mx_common.report import ImportReport
        from mx_io_max import build_scene
        report = ImportReport()
        settings = build_scene.ImportSettings(units='centimeters')
        with maxfile.open(self.path) as mf:
            scene = mf.scene
            original = scene.decode
            scene.decode = lambda obj: decoded.get(obj.index) if obj is not None and obj.index in decoded \
                else original(obj)
            builder = build_scene.SceneBuilder(bpy.context, self.path, settings, report)
            builder.build(mf)
        return builder, report

    def geometry_index(self):
        import maxfile
        with maxfile.open(self.path) as mf:
            return next(n.object.index for n in mf.nodes if n.name == "Box001")

    def test_mesh_instances(self):
        geo = self.geometry_index()
        builder, report = self.builder_with_decoded({geo: CUBE})
        box1, box2 = bpy.data.objects["Box001"], bpy.data.objects["Box002"]
        self.assertEqual(box1.type, 'MESH')
        self.assertIs(box1.data, box2.data)    # Instances share the mesh.
        mesh = box1.data
        self.assertEqual(len(mesh.polygons), 6)
        self.assertAlmostEqual(max(v.co.x for v in mesh.vertices), 0.1, places=6)  # 10 cm.
        self.assertIn("UVMap", mesh.uv_layers)
        marked = sum(1 for v in mesh.attributes["sharp_edge"].data if v.value)
        self.assertEqual(marked, 8)
        self.assertEqual(report.imported["instances"], 1)

    def test_material_slots_from_multi_sub(self):
        import maxfile
        geo = self.geometry_index()
        with maxfile.open(self.path) as mf:
            # Use the controller of Root as a stand-in material object (any scene object index works).
            mat_index = next(n.index for n in mf.nodes if n.name == "Root")
        multi = MaterialData("MultiMaterial", "Multi", {}, {}, sub_materials=[
            MaterialData("VRayMtl", "Red", {"diffuse": (1.0, 0.0, 0.0)}, {}),
            MaterialData("PhysicalMaterial", "Blue", {"base_color": (0.0, 0.0, 1.0)}, {}),
            MaterialData("SomeOddMtl", "Odd", {"diffuse": (0.5, 0.5, 0.5)}, {}),
        ], sub_ids=[1, 2, 3])
        from mx_common.report import ImportReport
        from mx_io_max import build_scene
        with maxfile.open(self.path) as mf:
            scene = mf.scene
            node = next(n for n in mf.nodes if n.name == "Box001")
            node.material = scene.objects[mat_index]
            original = scene.decode
            decoded = {geo: CUBE, mat_index: multi}
            scene.decode = lambda obj: decoded.get(obj.index) if obj is not None and obj.index in decoded \
                else original(obj)
            report = ImportReport()
            builder = build_scene.SceneBuilder(bpy.context, self.path, build_scene.ImportSettings(), report)
            builder.build(mf)
        box1 = bpy.data.objects["Box001"]
        self.assertEqual([s.material.name for s in box1.material_slots], ["Red", "Blue", "Odd"])
        self.assertEqual([p.material_index for p in box1.data.polygons], [0, 1, 2, 2, 2, 2])
        self.assertEqual(report.imported["materials"], 2)
        self.assertEqual(report.unsupported[("material", "SomeOddMtl")], 1)

    def write(self, data, name):
        path = os.path.join(self.tmp.name, name)
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def poly_scene(self):
        """Two nodes instancing one Editable Poly cube; the second through a nested modifier stack."""
        b = sm.SceneBuilder()
        node = b.cls("Node", (1, 0), 1)
        poly = b.cls("Editable Poly", (0x1BF8338D, 0x192F6098), 0x10)
        derived = 0x2032    # Derived objects: the chunk type itself is the class (not in the class directory).
        smooth = b.cls("TurboSmooth", (0x7E57, 0x0010), 0x810)
        shell = b.cls("Shell", (0x7E57, 0x0011), 0x810)
        odd = b.cls("OddModifier", (0x7E57, 0x0012), 0x810)
        uvs = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]
        geo = b.obj(poly, sm.poly_mesh(
            [tuple(c / 10 for c in p) for p in CUBE.positions], CUBE.faces,
            material_ids=[0, 1, 2, 2, 2, 2], smoothing=[1, 2, 4, 4, 4, 4],
            channels={1: (uvs, [(0, 1, 2, 3)] * 6)}))
        m_smooth, m_shell, m_odd = b.obj(smooth), b.obj(shell), b.obj(odd)
        inner = b.obj(derived, sm.refs_ordered(m_smooth, geo))             # TurboSmooth at the bottom.
        outer = b.obj(derived, sm.refs_ordered(m_odd, m_shell, inner))     # Then Shell, then OddModifier.
        b.node(node, "Plain", refs=[sm.NULL, geo])
        b.node(node, "Stacked", refs=[sm.NULL, outer])
        return b.build()

    def test_editable_poly_end_to_end(self):
        path = self.write(self.poly_scene(), "poly.max")
        self.assertEqual(bpy.ops.import_scene.mx_max(filepath=path, units='meters'), {'FINISHED'})
        plain, stacked = bpy.data.objects["Plain"], bpy.data.objects["Stacked"]
        self.assertEqual(plain.type, 'MESH')
        self.assertIs(plain.data, stacked.data)
        mesh = plain.data
        self.assertEqual((len(mesh.vertices), len(mesh.polygons)), (8, 6))
        self.assertEqual(sum(1 for v in mesh.attributes["sharp_edge"].data if v.value), 8)
        self.assertIn("UVMap", mesh.uv_layers)
        self.assertEqual(list(mesh["mx_material_ids"]), [1, 2, 3, 3, 3, 3])
        # Stack imported bottom-up, stopping at the unsupported modifier.
        self.assertEqual([m.name for m in stacked.modifiers], ["TurboSmooth", "Shell"])
        report = bpy.data.texts["Import Report"].as_string()
        self.assertIn("modifier: OddModifier x1", report)

    def test_collapse_on_import(self):
        path = self.write(self.poly_scene(), "poly2.max")
        bpy.ops.import_scene.mx_max(filepath=path, units='meters', keep_modifier_stack=False)
        stacked = bpy.data.objects["Stacked"]
        self.assertEqual(len(stacked.modifiers), 0)
        self.assertIsNot(stacked.data, bpy.data.objects["Plain"].data)
        self.assertGreater(len(stacked.data.polygons), 6)


class ModifierConvertTest(unittest.TestCase):

    def test_converters(self):
        addon_utils.enable("mx_io_max", default_set=True)
        from mx_io_max.modifiers import convert
        mesh = bpy.data.meshes.new("m")
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
        obj = bpy.data.objects.new("o", mesh)
        bpy.context.scene.collection.objects.link(obj)
        self.assertTrue(convert.add_modifier(obj, "TurboSmooth", {"iterations": 2}))
        self.assertTrue(convert.add_modifier(obj, "Shell", {"inner_amount": 1.0, "outer_amount": 0.0}))
        self.assertTrue(convert.add_modifier(obj, "Symmetry", {"axis": 1, "flip": True}))
        self.assertTrue(convert.add_modifier(obj, "Bend", {"bend_angle": 90.0, "bend_axis": 0}, enabled=False))
        self.assertTrue(convert.add_modifier(obj, "Normal", {}))
        self.assertTrue(convert.add_modifier(obj, "Noise", {"strength": (0.0, 0.0, 2.0)}))
        self.assertTrue(convert.add_modifier(obj, "Turn_to_Poly", {}))
        self.assertFalse(convert.add_modifier(obj, "Edit_Poly", {}))
        mods = obj.modifiers
        self.assertEqual(mods["TurboSmooth"].levels, 2)
        self.assertEqual(mods["Shell"].offset, -1.0)
        self.assertEqual(tuple(mods["Symmetry"].use_bisect_flip_axis), (False, True, False))
        self.assertAlmostEqual(mods["Bend"].angle, math.pi / 2)
        self.assertEqual(mods["Bend"].deform_axis, 'X')
        self.assertFalse(mods["Bend"].show_viewport)
        self.assertEqual(mods["Normal"].node_group.name, "Flip Normals")
        self.assertEqual(mods["Noise"].strength, 2.0)
        # Collapse applies the stack (on its own object: the flipped Symmetry above cuts this triangle away).
        smooth = bpy.data.objects.new("s", mesh.copy())
        bpy.context.scene.collection.objects.link(smooth)
        convert.add_modifier(smooth, "TurboSmooth", {"iterations": 1})
        convert.collapse(smooth)
        self.assertEqual(len(smooth.modifiers), 0)
        self.assertEqual(len(smooth.data.polygons), 3)


if __name__ == "__main__":
    _runner_util.main()
