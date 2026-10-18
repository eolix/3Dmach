# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Import representative scenes of the local corpus (Autodesk's public sample files) and check what they become.

The corpus is never committed (``docs/decisions/0004-local-corpus.md``): set ``MX_CORPUS_DIR`` (run_tests.py
passes it through) to the directory holding ``autodesk_3ds_max_english_win_sample_files/`` (or the sample files
themselves); the tests are skipped without it. The expectations were checked on the imported scenes.
"""

import collections
import os
import sys
import time
import unittest

import addon_utils
import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _runner_util

SAMPLE_SET = "autodesk_3ds_max_english_win_sample_files"


def corpus_file(relpath):
    root = os.environ.get("MX_CORPUS_DIR")
    if not root:
        return None
    for base in (os.path.join(root, SAMPLE_SET), root):
        path = os.path.join(base, relpath)
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            return path
    return None


def count(items):
    return collections.Counter(items)


class Imported:
    """Summary of the scene after one import."""

    def __init__(self, path):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        addon_utils.enable("mx_io_max", default_set=True)
        start = time.monotonic()
        self.result = bpy.ops.import_scene.mx_max(filepath=path)
        self.seconds = time.monotonic() - start
        self.objects = list(bpy.data.objects)
        self.types = count(o.type for o in self.objects)
        self.meshes = [o for o in self.objects if o.type == 'MESH']
        self.modifiers = count(m.type for o in self.objects for m in getattr(o, "modifiers", ()))
        self.constraints = count(c.type for o in self.objects for c in o.constraints)
        self.lights = count(o.data.type for o in self.objects if o.type == 'LIGHT')
        self.hidden = sum(o.hide_get() for o in self.objects)
        self.frozen = sum(bool(o.get("mx_frozen")) for o in self.objects)
        self.shader_nodes = count(n.type for m in bpy.data.materials if m.node_tree for n in m.node_tree.nodes)
        world = bpy.context.scene.world
        self.world_nodes = count(n.type for n in world.node_tree.nodes) if world and world.node_tree else collections.Counter()
        self.report = bpy.data.texts["Import Report"].as_string()


class CorpusImportTest(unittest.TestCase):

    def scene(self, relpath):
        path = corpus_file(relpath)
        if path is None:
            self.skipTest("corpus file not available (set MX_CORPUS_DIR): " + relpath)
        imported = Imported(path)
        self.assertEqual(imported.result, {'FINISHED'})
        self.assertGreater(len(imported.objects), 0)
        print("{:s}: {:.1f} s, {:d} objects".format(relpath, imported.seconds, len(imported.objects)))
        return imported

    def test_meshsmooth_hammer(self):
        s = self.scene("Scenes/SubDivSurfaces/Meshsmooth-Hammer.max")
        self.assertEqual(len(s.meshes), 1)
        mesh = s.meshes[0]
        self.assertEqual(len(mesh.data.vertices), 56)
        # Editable Mesh triangles merged along hidden edges: the 54 quads Max's MeshSmooth subdivides.
        self.assertEqual(len(mesh.data.polygons), 54)
        smooth = mesh.modifiers["MeshSmooth"]
        self.assertEqual((smooth.type, smooth.levels), ('SUBSURF', 2))

    def test_living_room_targets_sun_sky(self):
        s = self.scene("Scenes/Rendering/living.room/living.room_ART.max")
        self.assertEqual(s.types['CAMERA'], 2)
        self.assertEqual(s.constraints['TRACK_TO'], 2)
        self.assertEqual(s.lights, count({'SUN': 1}))
        self.assertEqual(s.world_nodes['TEX_SKY'], 1)
        self.assertGreaterEqual(len(s.meshes), 58)
        self.assertIsNotNone(bpy.context.scene.camera)
        self.assertNotIn("object: Target", s.report)

    def test_arnold_studio_lights_and_frozen(self):
        s = self.scene("Scenes/Design Visualization/Studio_Scene/Arnold Studio.max")
        self.assertEqual(s.lights, count({'AREA': 3}))     # Arnold quad lights.
        self.assertEqual(s.frozen, 52)
        self.assertEqual(s.modifiers['SUBSURF'], 20)
        self.assertEqual(s.constraints['TRACK_TO'], 1)

    def test_lathe_as_screw(self):
        s = self.scene("Scenes/Design Visualization/Interior_scene/CGCookie 4_Day_ART.max")
        self.assertEqual(s.modifiers['SCREW'], 2)
        self.assertEqual(s.lights, count({'SUN': 1}))
        self.assertEqual(s.world_nodes['TEX_SKY'], 1)

    def test_text_extrude_and_hidden(self):
        s = self.scene("Particle Flow Elements Library/scenes/Logo/Cereal.max")
        self.assertEqual(len(s.meshes), 8)
        self.assertEqual(s.lights, count({'SPOT': 3}))
        self.assertEqual(s.constraints['TRACK_TO'], 4)
        self.assertEqual(s.hidden, 8)

    def test_biplane_shapes(self):
        s = self.scene("Scenes/TextureMapping/biplane.max")
        self.assertEqual(s.types['CURVE'], 7)
        self.assertEqual(s.modifiers['SCREW'], 2)
        self.assertEqual(s.modifiers['MIRROR'], 2)

    def test_symmetry(self):
        s = self.scene("Scenes/SymmetryModifier/BallSymmetry.max")
        self.assertEqual(s.modifiers['MIRROR'], 4)
        self.assertEqual(s.lights, count({'AREA': 1}))

    def test_tiger_tank_uvs(self):
        s = self.scene("Scenes/DirectXFeatures/TigerTank.max")
        self.assertEqual(len(s.meshes), 20)
        self.assertTrue(all(o.data.uv_layers for o in s.meshes))
        self.assertEqual(s.modifiers['MIRROR'], 1)

    def test_photometric_lights(self):
        s = self.scene("Scenes/Design Visualization/IES lights_ART.max")
        self.assertEqual(s.lights, count({'POINT': 8, 'SUN': 1}))
        self.assertEqual(s.constraints['TRACK_TO'], 7)
        self.assertEqual(len(s.meshes), 284)
        self.assertIn("IES", s.report)       # Web distributions are reported as approximated.

    def test_blend_materials(self):
        s = self.scene("Scenes/Rendering/Glass.Iris/Glass_Iris_ART.max")
        self.assertEqual(s.shader_nodes['MIX_SHADER'], 4)
        self.assertEqual(s.types['CURVE'], 6)
        self.assertEqual(s.hidden, 7)

    def test_skylight_world_and_lathes(self):
        s = self.scene("Scenes/CameraMap/wall.max")
        self.assertEqual(s.modifiers['SCREW'], 3)
        self.assertEqual(s.world_nodes['BACKGROUND'], 1)
        self.assertEqual(len(s.meshes), 102)

    def test_edit_spline_extrude_crowd(self):
        s = self.scene("Scenes/Crowd/MotionClips/ButterflyLandingBig.max")
        self.assertEqual(len(s.meshes), 1204)
        self.assertEqual(s.modifiers['SUBSURF'], 401)


if __name__ == "__main__":
    _runner_util.main()
