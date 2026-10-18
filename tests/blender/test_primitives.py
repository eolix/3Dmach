# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Live primitives (``mx_primitives``): creation, live parameters, instances, undo, conversion, importer helper."""

import math
import os
import sys
import unittest

import addon_utils
import bpy
from mathutils import Euler, Matrix, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _runner_util

ADDON = "mx_primitives"


def enable(name):
    errors = []
    mod = addon_utils.enable(name, default_set=True, handle_error=lambda ex: errors.append(ex))
    if errors:
        raise errors[0]
    if mod is None:
        raise RuntimeError("add-on {!r} could not be enabled".format(name))
    return mod


def clear_scene():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    for mesh in list(bpy.data.meshes):
        bpy.data.meshes.remove(mesh)


def evaluated_vertex_count(obj):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    return len(obj.evaluated_get(depsgraph).data.vertices)


class PrimitiveTestCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.module = enable(ADDON)
        import mx_primitives
        cls.mx = mx_primitives
        cls.geometry = mx_primitives.geometry

    @classmethod
    def tearDownClass(cls):
        addon_utils.disable(ADDON, default_set=True)

    def setUp(self):
        if bpy.context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        clear_scene()
        bpy.context.scene.cursor.location = (0.0, 0.0, 0.0)

    def add(self, kind, **params):
        self.assertEqual(bpy.ops.mesh.mx_primitive_add(kind=kind, **params), {'FINISHED'})
        return bpy.context.view_layer.objects.active

    def assertMeshMatches(self, mesh, kind, **params):
        data = self.geometry.generate(kind, **params)
        self.assertEqual(len(mesh.vertices), len(data.vertices))
        self.assertEqual(len(mesh.polygons), len(data.faces))


class ApiTest(PrimitiveTestCase):

    def test_kinds(self):
        kinds = [kind for kind, _label, _description in self.mx.KINDS]
        self.assertEqual(sorted(kinds), sorted(self.geometry.KIND_IDS))
        icons = bpy.types.UILayout.bl_rna.functions["prop"].parameters["icon"].enum_items.keys()
        for kind in kinds:
            self.assertIn(self.mx.ICONS[kind], icons)

    def test_layout_covers_parameters(self):
        from mx_primitives import ui
        for kind in self.geometry.KIND_IDS:
            names = [entry[0] for entry in ui.LAYOUT[kind] if entry is not None]
            self.assertEqual(sorted(names), sorted(self.geometry.PARAMETERS[kind]), kind)
            self.assertEqual(len(names), len(set(names)), kind)

    def test_operator_has_every_parameter(self):
        # The add operator mirrors the stored parameters; its own properties must not shadow one of them.
        op_props = bpy.ops.mesh.mx_primitive_add.get_rna_type().properties
        settings_props = bpy.types.Mesh.bl_rna.properties["mx_primitive"].fixed_type.properties
        for params in self.geometry.PARAMETERS.values():
            for name in params:
                self.assertIn(name, op_props)
                self.assertEqual(op_props[name].type, settings_props[name].type, name)
                self.assertEqual(getattr(op_props[name], "subtype", None), getattr(settings_props[name], "subtype",
                                                                                   None), name)

    def test_draw_parameters(self):
        # No UI in background mode: draw into a stand-in layout that records the properties drawn.
        class FakeLayout:
            def __init__(self, log):
                self.log = log

            def column(self, **_kw):
                return self

            row = column

            def prop(self, data, name, **_kw):
                getattr(data, name)
                self.log.append(name)

            def label(self, **_kw):
                pass

            def separator(self, **_kw):
                pass

        for kind in self.geometry.KIND_IDS:
            with self.subTest(kind=kind):
                obj = self.mx.create_primitive_object(kind, kind, {})
                log = []
                self.assertTrue(self.mx.draw_parameters(FakeLayout(log), obj))
                self.assertEqual(sorted(log), sorted(self.geometry.PARAMETERS[kind]))
        bpy.ops.mesh.primitive_cube_add()
        self.assertFalse(self.mx.draw_parameters(FakeLayout([]), bpy.context.active_object))
        self.assertFalse(self.mx.draw_parameters(FakeLayout([]), None))

    def test_registered(self):
        self.assertTrue(hasattr(bpy.types.Mesh, "mx_primitive"))
        self.assertTrue(hasattr(bpy.types, "PROPERTIES_PT_mx_primitive"))
        self.assertTrue(hasattr(bpy.types, "VIEW3D_PT_mx_primitive"))
        self.assertTrue(hasattr(bpy.types, "VIEW3D_MT_mx_primitive_add"))


class ExecTest(PrimitiveTestCase):

    def test_every_kind(self):
        bpy.context.scene.cursor.location = (1.0, 2.0, 3.0)
        for kind in self.geometry.KIND_IDS:
            with self.subTest(kind=kind):
                obj = self.add(kind)
                self.assertTrue(obj.select_get())
                self.assertEqual(self.mx.get_parameters(obj)[0], kind)
                self.assertEqual(obj.data.mx_primitive.kind, kind)
                self.assertMeshMatches(obj.data, kind)
                self.assertEqual(tuple(obj.location), (1.0, 2.0, 3.0))
                self.assertNotEqual(tuple(obj.color), (1.0, 1.0, 1.0, 1.0))
                self.assertEqual(len(bpy.context.selected_objects), 1)
                self.assertTrue(obj.name.endswith("001"), obj.name)
                if kind != "PLANE":
                    # Closed meshes: every edge shared by two faces.
                    counts = {}
                    for poly in obj.data.polygons:
                        for key in poly.edge_keys:
                            counts[key] = counts.get(key, 0) + 1
                    self.assertTrue(all(count == 2 for count in counts.values()), kind)

    def test_kind_defaults_differ(self):
        # Shared parameter names with per-kind defaults: a cone has 24 sides, a cylinder 18.
        cone = self.add("CONE")
        cylinder = self.add("CYLINDER")
        self.assertEqual(cone.data.mx_primitive.sides, 24)
        self.assertEqual(cylinder.data.mx_primitive.sides, 18)
        self.assertEqual(cylinder.data.mx_primitive.height_segments, 5)

    def test_parameters_and_location(self):
        obj = self.add("BOX", width=2.0, length=3.0, height=4.0, width_segments=2, location=(1.0, 0.0, 0.0),
                       object_rotation=(0.0, 0.0, math.pi / 2))
        self.assertAlmostEqual(obj.dimensions.x, 2.0, places=5)
        self.assertAlmostEqual(obj.dimensions.y, 3.0, places=5)
        self.assertAlmostEqual(obj.dimensions.z, 4.0, places=5)
        self.assertEqual(tuple(obj.location), (1.0, 0.0, 0.0))
        self.assertAlmostEqual(obj.rotation_euler.z, math.pi / 2, places=5)
        self.assertMeshMatches(obj.data, "BOX", width=2.0, length=3.0, height=4.0, width_segments=2)

    def test_box_attributes(self):
        obj = self.add("BOX")
        mesh = obj.data
        self.assertEqual(sorted({p.material_index for p in mesh.polygons}), [0, 1, 2, 3, 4, 5])
        sharp = mesh.attributes["sharp_edge"].data
        self.assertEqual(sum(1 for item in sharp if item.value), 12)
        self.assertIn("UVMap", mesh.uv_layers)
        self.assertEqual(len(mesh.uv_layers["UVMap"].uv), len(mesh.loops))

    def test_smooth_sphere(self):
        obj = self.add("SPHERE")
        mesh = obj.data
        self.assertTrue(all(p.use_smooth for p in mesh.polygons))
        self.assertEqual(len(mesh.vertices), 482)
        obj.data.mx_primitive.smooth = False
        self.assertFalse(any(p.use_smooth for p in mesh.polygons))

    def test_no_uvs(self):
        obj = self.add("CYLINDER", generate_uvs=False)
        self.assertEqual(len(obj.data.uv_layers), 0)

    def test_edit_mode_object_converted(self):
        obj = self.add("BOX")
        bpy.ops.object.mode_set(mode='EDIT')
        self.add("SPHERE")
        self.assertEqual(bpy.context.mode, 'OBJECT')


class LiveParameterTest(PrimitiveTestCase):

    def test_change_regenerates(self):
        obj = self.add("SPHERE")
        obj.data.mx_primitive.segments = 8
        self.assertMeshMatches(obj.data, "SPHERE", segments=8)
        obj.data.mx_primitive.hemisphere = 0.5
        self.assertMeshMatches(obj.data, "SPHERE", segments=8, hemisphere=0.5)
        self.assertAlmostEqual(min(v.co.z for v in obj.data.vertices), 0.0, places=5)

    def test_clamped_to_kind_limits(self):
        obj = self.add("SPHERE")
        obj.data.mx_primitive.segments = 2
        self.assertEqual(obj.data.mx_primitive.segments, 4)
        self.assertMeshMatches(obj.data, "SPHERE", segments=4)

    def test_every_parameter_regenerates(self):
        changes = {
            "BOX": {"length_segments": 3}, "SPHERE": {"slice_on": True, "slice_to": 2.0},
            "GEOSPHERE": {"base_type": 'OCTA'}, "CYLINDER": {"cap_segments": 3},
            "TUBE": {"sides": 7}, "CONE": {"radius2": 0.2}, "TORUS": {"smooth_mode": 'SIDES', "segments": 9},
            "PYRAMID": {"height_segments": 4}, "PLANE": {"width_segments": 7}, "TEST_SHAPE": {"part_lid": False},
        }
        for kind, params in changes.items():
            with self.subTest(kind=kind):
                obj = self.add(kind)
                for name, value in params.items():
                    setattr(obj.data.mx_primitive, name, value)
                self.assertMeshMatches(obj.data, kind, **params)

    def test_instances_share(self):
        obj = self.add("CYLINDER")
        instance = obj.copy()
        bpy.context.collection.objects.link(instance)
        self.assertIs(instance.data, obj.data)
        instance.data.mx_primitive.sides = 7
        self.assertEqual(obj.data.mx_primitive.sides, 7)
        self.assertMeshMatches(obj.data, "CYLINDER", sides=7)

    def test_modifier_on_top(self):
        obj = self.add("BOX")
        modifier = obj.modifiers.new("Subdivision", 'SUBSURF')
        modifier.levels = 1
        before = evaluated_vertex_count(obj)
        obj.data.mx_primitive.width_segments = 3
        bpy.context.view_layer.update()
        after = evaluated_vertex_count(obj)
        self.assertGreater(after, before)
        self.assertEqual(obj.modifiers[0].name, "Subdivision")

    def test_undo(self):
        obj = self.add("TORUS")
        name = obj.name
        bpy.ops.ed.undo_push(message="created")
        obj.data.mx_primitive.segments = 5
        bpy.ops.ed.undo_push(message="segments")
        self.assertMeshMatches(bpy.data.objects[name].data, "TORUS", segments=5)
        bpy.ops.ed.undo()
        mesh = bpy.data.objects[name].data
        self.assertEqual(mesh.mx_primitive.segments, 24)
        self.assertMeshMatches(mesh, "TORUS")
        bpy.ops.ed.redo()
        mesh = bpy.data.objects[name].data
        self.assertEqual(mesh.mx_primitive.segments, 5)
        self.assertMeshMatches(mesh, "TORUS", segments=5)
        # Still live after undo: a further change regenerates.
        mesh.mx_primitive.sides = 4
        self.assertMeshMatches(mesh, "TORUS", segments=5, sides=4)

    def test_edit_mode_rebuild(self):
        obj = self.add("BOX")
        bpy.ops.object.mode_set(mode='EDIT')
        obj.data.mx_primitive.height_segments = 3
        bpy.ops.object.mode_set(mode='OBJECT')
        self.assertMeshMatches(obj.data, "BOX", height_segments=3)
        self.assertEqual(len(obj.data.uv_layers), 1)


class ConvertTest(PrimitiveTestCase):

    def test_convert_to_editable_poly(self):
        obj = self.add("CONE")
        instance = obj.copy()
        bpy.context.collection.objects.link(instance)
        count = len(obj.data.vertices)
        self.assertTrue(bpy.types.VIEW3D_PT_mx_primitive.poll(bpy.context))
        self.assertEqual(bpy.ops.object.mx_convert_to_editable_poly(), {'FINISHED'})
        self.assertFalse(bpy.types.VIEW3D_PT_mx_primitive.poll(bpy.context))
        self.assertFalse(self.mx.is_live_primitive(obj))
        self.assertFalse(self.mx.is_live_primitive(instance))
        self.assertEqual(obj.data.mx_primitive.kind, 'NONE')
        self.assertEqual(len(obj.data.vertices), count)
        # Properties written afterwards don't touch the mesh any more.
        obj.data.mx_primitive.sides = 5
        self.assertEqual(len(obj.data.vertices), count)
        self.assertFalse(self.mx.draw_parameters(None, obj))

    def test_poll(self):
        bpy.ops.mesh.primitive_cube_add()
        self.assertFalse(bpy.ops.object.mx_convert_to_editable_poly.poll())

    def test_convert_undo(self):
        obj = self.add("PLANE")
        name = obj.name
        bpy.ops.ed.undo_push(message="created")
        bpy.ops.object.mx_convert_to_editable_poly()
        bpy.ops.ed.undo_push(message="converted")
        bpy.ops.ed.undo()
        self.assertTrue(self.mx.is_live_primitive(bpy.data.objects[name]))


class ImporterHelperTest(PrimitiveTestCase):

    def test_create_primitive_object(self):
        collection = bpy.data.collections.new("Imported")
        bpy.context.scene.collection.children.link(collection)
        obj = self.mx.create_primitive_object("Box001", "BOX", {"length": 2.0, "height_segments": 2},
                                              collection=collection)
        self.assertEqual(obj.name, "Box001")
        self.assertIn(obj.name, collection.objects)
        self.assertFalse(obj.select_get())
        kind, params = self.mx.get_parameters(obj)
        self.assertEqual(kind, "BOX")
        self.assertAlmostEqual(params["length"], 2.0)
        self.assertEqual(params["height_segments"], 2)
        self.assertMeshMatches(obj.data, "BOX", length=2.0, height_segments=2)

        instance = self.mx.create_primitive_object("Box002", "BOX", {"length": 2.0, "height_segments": 2},
                                                   collection=collection, mesh=obj.data)
        self.assertIs(instance.data, obj.data)
        self.assertEqual(len(bpy.data.meshes), 1)

    def test_shared_mesh_reconfigured(self):
        mesh = bpy.data.meshes.new("plain")
        obj = self.mx.create_primitive_object("Tube001", "TUBE", {"sides": 5}, mesh=mesh)
        self.assertIs(obj.data, mesh)
        self.assertMeshMatches(mesh, "TUBE", sides=5)
        self.assertIn(obj.name, bpy.context.collection.objects)

    def test_errors(self):
        with self.assertRaises(ValueError):
            self.mx.create_primitive_object("x", "TEAPOT", {})
        with self.assertRaises(TypeError):
            self.mx.create_primitive_object("x", "BOX", {"radius": 1.0})

    def test_disable_keeps_meshes(self):
        obj = self.mx.create_primitive_object("Sphere001", "SPHERE", {"segments": 6})
        count = len(obj.data.vertices)
        addon_utils.disable(ADDON, default_set=True)
        try:
            self.assertFalse(hasattr(bpy.types.Mesh, "mx_primitive"))
            self.assertEqual(len(obj.data.vertices), count)
        finally:
            enable(ADDON)
        import mx_primitives
        self.assertTrue(mx_primitives.is_live_primitive(obj))
        self.assertEqual(obj.data.mx_primitive.segments, 6)


class CreationMathTest(PrimitiveTestCase):

    def plane_for(self, euler, axis_aligned=True):
        from mx_primitives import creation
        view = Euler(euler).to_quaternion().to_matrix()
        return creation.construction_plane([tuple(row) for row in view], axis_aligned)

    def test_view_planes(self):
        # Blender's axis views as view rotations (Euler angles of the view), and the plane normal Max uses.
        cases = {
            "TOP": ((0.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
            "BOTTOM": ((math.pi, 0.0, 0.0), (0.0, 0.0, -1.0)),
            "FRONT": ((math.pi / 2, 0.0, 0.0), (0.0, -1.0, 0.0)),
            "BACK": ((math.pi / 2, 0.0, math.pi), (0.0, 1.0, 0.0)),
            "RIGHT": ((math.pi / 2, 0.0, math.pi / 2), (1.0, 0.0, 0.0)),
            "LEFT": ((math.pi / 2, 0.0, -math.pi / 2), (-1.0, 0.0, 0.0)),
        }
        for name, (euler, normal) in cases.items():
            with self.subTest(view=name):
                plane = self.plane_for(euler)
                self.assertTrue((Vector(plane.normal) - Vector(normal)).length < 1e-6, plane)
                self.assertAlmostEqual(Matrix(plane.matrix()).determinant(), 1.0, places=6)
        # Perspective: always the ground plane.
        self.assertEqual(self.plane_for((1.0, 0.2, 0.3), axis_aligned=False).normal, (0.0, 0.0, 1.0))

    def test_session_drives_object(self):
        from mx_primitives import creation
        plane = self.plane_for((math.pi / 2, 0.0, 0.0))
        session = creation.CreationSession("CYLINDER", plane)
        session.press(creation.ray_plane((0.0, -10.0, 0.0), (0.0, 1.0, 0.0), plane))
        session.update((1.0, -10.0, 0.0), (0.0, 1.0, 0.0))
        self.assertEqual(session.advance(), "CONTINUE")
        # Height towards the viewer (-Y): look along +X at the line through (1, 0, 0) going -Y.
        session.update((-10.0, -2.0, 0.0), (1.0, 0.0, 0.0))
        self.assertEqual(session.advance(), "FINISHED")
        obj = self.mx.create_primitive_object("Cylinder001", "CYLINDER", session.params)
        obj.matrix_world = Matrix.Translation(session.location) @ Matrix(plane.matrix()).to_4x4()
        bpy.context.view_layer.update()
        world = [obj.matrix_world @ v.co for v in obj.data.vertices]
        self.assertAlmostEqual(min(v.y for v in world), -2.0, places=5)
        self.assertAlmostEqual(max(v.y for v in world), 0.0, places=5)
        self.assertAlmostEqual(max(v.x for v in world), 1.0, places=5)


if __name__ == "__main__":
    _runner_util.main()
