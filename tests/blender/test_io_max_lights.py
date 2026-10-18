# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Light, camera and world descriptions to Blender data."""

import math
import os
import sys
import unittest

import addon_utils
import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _runner_util


class LightsCamerasTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        addon_utils.enable("mx_io_max", default_set=True)

    @classmethod
    def tearDownClass(cls):
        addon_utils.disable("mx_io_max", default_set=True)

    def test_lights(self):
        from mx_io_max import lights
        coll = bpy.context.scene.collection
        spot = lights.create_light(lights.light_from_params(
            "Targetspot", {"name": "Key", "hotspot": 20.0, "falloff": 40.0, "multiplier": 2.0}), coll)
        self.assertEqual(spot.data.type, 'SPOT')
        self.assertAlmostEqual(spot.data.spot_size, math.radians(40.0), places=5)
        self.assertEqual(spot.data.energy, 2000.0)
        area = lights.create_light(lights.light_from_params(
            "VRayLight", {"type": "plane", "size0": 50.0, "size1": 25.0}), coll, scene_scale=0.01)
        self.assertEqual((area.data.shape, round(area.data.size, 4), round(area.data.size_y, 4)),
                         ('RECTANGLE', 1.0, 0.5))
        off = lights.create_light(lights.light_from_params("Omnilight", {"on": False}), coll)
        self.assertTrue(off.hide_render)

    def test_camera_with_target(self):
        from mx_io_max import lights
        coll = bpy.context.scene.collection
        cam = lights.create_camera(lights.camera_from_params("Targetcamera", {"name": "Cam01", "fov": 60.0}), coll)
        self.assertEqual(cam.data.sensor_fit, 'HORIZONTAL')
        self.assertAlmostEqual(math.degrees(cam.data.angle_x), 60.0, places=3)
        target = bpy.data.objects.new("Cam01.Target", None)
        coll.objects.link(target)
        target.location = (0.0, 10.0, 0.0)
        lights.add_target_constraint(cam, target)
        bpy.context.view_layer.update()
        # Looking down -Z towards +Y: the camera's -Z axis points along +Y.
        forward = cam.matrix_world.to_3x3() @ __import__("mathutils").Vector((0.0, 0.0, -1.0))
        self.assertAlmostEqual(forward.y, 1.0, places=4)

    def test_world(self):
        from mx_io_max import lights
        scene = bpy.context.scene
        world = lights.setup_world(scene, lights.world_from_params({"background_color": (0.2, 0.3, 0.4)}))
        bg = next(n for n in world.node_tree.nodes if n.type == 'BACKGROUND')
        self.assertAlmostEqual(bg.inputs["Color"].default_value[2], 0.4, places=5)
        sky = lights.setup_world(scene, lights.WorldDesc(sky=True, sun_direction=(0.0, 0.70710678, 0.70710678)))
        tex = next(n for n in sky.node_tree.nodes if n.type == 'TEX_SKY')
        self.assertAlmostEqual(math.degrees(tex.sun_elevation), 45.0, places=3)


if __name__ == "__main__":
    _runner_util.main()
