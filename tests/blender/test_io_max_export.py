# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
The experimental .max export (``export_scene.mx_max``): export a scene, read it back with ``maxfile`` and
re-import it with ``import_scene.mx_max``, then compare objects, transforms, geometry and materials.
"""

import math
import os
import sys
import tempfile
import unittest

import addon_utils
import bpy
from mathutils import Euler, Matrix, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _runner_util


def new_material(name, color, roughness=0.5, alpha=1.0, image_path=None):
    mat = bpy.data.materials.new(name)
    if mat.node_tree is None:
        mat.use_nodes = True
    bsdf = next(n for n in mat.node_tree.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Alpha"].default_value = alpha
    if image_path is not None:
        image = bpy.data.images.new(os.path.basename(image_path), 4, 4)
        image.filepath_raw = image_path
        image.file_format = 'PNG'
        image.save()
        tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
        tex.image = image
        mapping = mat.node_tree.nodes.new("ShaderNodeMapping")
        mapping.inputs["Scale"].default_value = (2.0, 3.0, 1.0)
        mat.node_tree.links.new(mapping.outputs["Vector"], tex.inputs["Vector"])
        mat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    return mat


def mesh_object(name, size=1.0, location=(0, 0, 0)):
    bpy.ops.mesh.primitive_cube_add(size=size, location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.data.name = name + "_mesh"
    return obj


class ExportTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        addon_utils.enable("mx_io_max", default_set=True)

    def path(self, name):
        return os.path.join(self.tmp.name, name)

    def build_scene(self):
        scene = bpy.context.scene
        scene.unit_settings.system = 'METRIC'
        scene.unit_settings.length_unit = 'CENTIMETERS'
        parent = mesh_object("Parent", 2.0, (1.0, 2.0, 0.5))
        parent.rotation_euler = Euler((0.0, 0.0, math.radians(30)))
        parent.scale = (1.0, 2.0, 1.0)
        child = mesh_object("Child", 0.5, (0, 0, 0))
        child.parent = parent
        child.matrix_parent_inverse = Matrix.Identity(4)
        child.location = (0.0, 0.0, 1.5)
        child.rotation_euler = Euler((math.radians(90), 0.0, 0.0))
        child.color = (1.0, 0.0, 0.0, 1.0)
        red = new_material("Red", (0.8, 0.1, 0.1), roughness=0.25)
        tex = new_material("Textured", (0.5, 0.5, 0.5), image_path=self.path("checker.png"))
        parent.data.materials.append(red)
        parent.data.materials.append(tex)
        for i, poly in enumerate(parent.data.polygons):
            poly.material_index = i % 2
        child.data.materials.append(red)
        # A modifier that changes the topology: baked into the Editable Poly.
        child.modifiers.new("Subdivision", 'SUBSURF').levels = 1
        bpy.ops.object.empty_add(type='CUBE', location=(-3.0, 0.0, 0.0))
        bpy.context.active_object.name = "Helper"
        bpy.ops.object.light_add(type='POINT', location=(0, 0, 5))
        bpy.ops.object.camera_add(location=(0, -5, 0))
        bpy.context.view_layer.update()
        return parent, child

    def test_export_reimport(self):
        parent, child = self.build_scene()
        world_parent = parent.matrix_world.copy()
        world_child = child.matrix_world.copy()
        path = self.path("scene.max")
        result = bpy.ops.export_scene.mx_max(filepath=path)
        self.assertEqual(result, {'FINISHED'})
        report = bpy.data.texts["Export Report"].as_string()
        self.assertIn("Export report", report)
        self.assertIn("object: camera x1", report)
        self.assertIn("object: light x1", report)

        import maxfile
        with maxfile.open(path) as mf:
            self.assertEqual(mf.warnings, [])
            self.assertEqual(mf.units.unit, "centimeters")
            nodes = {n.name: n for n in mf.nodes}
            self.assertEqual(sorted(nodes), ["Child", "Helper", "Parent"])
            self.assertIs(nodes["Child"].parent, nodes["Parent"])
            # Positions in centimetres.
            for got, want in zip(nodes["Parent"].transform.position, (100.0, 200.0, 50.0)):
                self.assertAlmostEqual(got, want, places=3)
            self.assertEqual(nodes["Child"].wire_color, (255, 0, 0))
            mesh = mf.scene.decode(nodes["Parent"].object)
            self.assertEqual(len(mesh.positions), 8)
            self.assertEqual(len(mesh.faces), 6)
            self.assertAlmostEqual(max(p[0] for p in mesh.positions), 100.0, places=3)
            self.assertEqual(mesh.material_ids, [1, 2, 1, 2, 1, 2])
            self.assertIn(1, mesh.map_channels)
            child_mesh = mf.scene.decode(nodes["Child"].object)
            self.assertEqual(len(child_mesh.faces), 24)         # Subdivided once: baked.
            multi = mf.scene.decode(nodes["Parent"].material)
            self.assertEqual(multi.class_name, "Multimaterial")
            self.assertEqual([m.name for m in multi.sub_materials], ["Red", "Textured"])
            textured = multi.sub_materials[1]
            self.assertEqual(os.path.basename(textured.maps["diffuse_map"].path), "checker.png")
            self.assertAlmostEqual(textured.maps["diffuse_map"].params["u_tiling"], 2.0, places=5)
            self.assertAlmostEqual(textured.maps["diffuse_map"].params["v_tiling"], 3.0, places=5)
            red = mf.scene.decode(nodes["Child"].material)
            self.assertEqual(red.name, "Red")
            self.assertAlmostEqual(red.params["glossiness"], 75.0, places=3)
            self.assertEqual(mf.scene.ref(nodes["Helper"].obj, 1).class_label(), "Dummy")

        # Re-import into an empty scene and compare.
        bpy.ops.wm.read_factory_settings(use_empty=True)
        addon_utils.enable("mx_io_max", default_set=True)
        self.assertEqual(bpy.ops.import_scene.mx_max(filepath=path, use_collection=False), {'FINISHED'})
        bpy.context.view_layer.update()
        p2, c2 = bpy.data.objects["Parent"], bpy.data.objects["Child"]
        self.assertIs(c2.parent, p2)
        for a, b in zip(p2.matrix_world, world_parent):
            for x, y in zip(a, b):
                self.assertAlmostEqual(x, y, places=4)
        for a, b in zip(c2.matrix_world, world_child):
            for x, y in zip(a, b):
                self.assertAlmostEqual(x, y, places=4)
        self.assertEqual(len(p2.data.polygons), 6)
        self.assertEqual([s.material.name for s in p2.material_slots], ["Red", "Textured"])
        self.assertEqual([p.material_index for p in p2.data.polygons], [0, 1, 0, 1, 0, 1])
        corners = sorted(tuple(round(v, 4) for v in p2.matrix_world @ vert.co) for vert in p2.data.vertices)
        expected = sorted(tuple(round(v, 4) for v in world_parent @ Vector(c)) for c in (
            (x, y, z) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)))
        self.assertEqual(corners, expected)
        self.assertAlmostEqual(c2.color[0], 1.0, places=2)

    def test_selection_only_and_units(self):
        a = mesh_object("A", 1.0, (1.0, 0.0, 0.0))
        b = mesh_object("B", 1.0, (0.0, 1.0, 0.0))
        for obj in bpy.context.view_layer.objects:
            obj.select_set(obj is a)
        path = self.path("selected.max")
        bpy.ops.export_scene.mx_max(filepath=path, use_selection=True, units='inches')
        import maxfile
        with maxfile.open(path) as mf:
            self.assertEqual([n.name for n in mf.nodes], ["A"])
            self.assertEqual(mf.units.unit, "inches")
            self.assertAlmostEqual(mf.nodes[0].transform.position[0], 1.0 / 0.0254, places=3)
        del b

    def test_smoothing_and_uvs_round_trip(self):
        bpy.ops.mesh.primitive_cylinder_add(vertices=8, radius=1.0, depth=2.0)
        cyl = bpy.context.active_object
        cyl.name = "Cyl"
        bpy.ops.object.shade_auto_smooth(angle=math.radians(60))     # Sides 45 degrees apart: smooth.
        bpy.ops.object.modifier_apply(modifier=cyl.modifiers[-1].name) if cyl.modifiers else None
        path = self.path("cyl.max")
        bpy.ops.export_scene.mx_max(filepath=path, units='meters')
        import maxfile
        with maxfile.open(path) as mf:
            mesh = mf.scene.decode(mf.nodes[0].object)
            self.assertEqual(len(mesh.faces), 10)
            caps = [g for f, g in zip(mesh.faces, mesh.smoothing_groups) if len(f) == 8]
            sides = [g for f, g in zip(mesh.faces, mesh.smoothing_groups) if len(f) == 4]
            self.assertEqual(len(set(sides)), 1)                # Sides share one group ...
            self.assertTrue(all(c & sides[0] == 0 for c in caps))   # ... that the caps don't have.
            self.assertEqual(len(mesh.map_channels[1].faces), 10)

    def test_physical_materials(self):
        obj = mesh_object("Metal")
        mat = new_material("Gold", (1.0, 0.7, 0.2), roughness=0.3)
        next(n for n in mat.node_tree.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled") \
            .inputs["Metallic"].default_value = 1.0
        obj.data.materials.append(mat)
        path = self.path("physical.max")
        bpy.ops.export_scene.mx_max(filepath=path, material_type='PHYSICAL')
        import maxfile
        with maxfile.open(path) as mf:
            data = mf.scene.decode(mf.nodes[0].material)
            self.assertEqual(data.class_name, "PhysicalMaterial")
            self.assertAlmostEqual(data.params["metalness"], 1.0, places=5)
            self.assertAlmostEqual(data.params["roughness"], 0.3, places=5)

    def test_menu_entry(self):
        from mx_io_max import export_max
        self.assertIn(export_max.menu_func_export, bpy.types.TOPBAR_MT_file_export._dyn_ui_initialize())


if __name__ == "__main__":
    _runner_util.main()
