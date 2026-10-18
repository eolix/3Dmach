# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Max lights, cameras and environment to neutral descriptions. Run with: pytest tests/importer"""

import importlib.util
import math
import os

import pytest

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
_spec = importlib.util.spec_from_file_location(
    "mx_io_max_lights", os.path.join(ROOT, "scripts", "addons_core", "mx_io_max", "lights.py"))
lights = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lights)


def test_kelvin():
    assert lights.kelvin_to_rgb(6600) == pytest.approx((1.0, 1.0, 1.0), abs=0.03)
    warm = lights.kelvin_to_rgb(3000)
    assert warm[0] == 1.0 and warm[2] < warm[1] < 1.0
    cold = lights.kelvin_to_rgb(12000)
    assert cold[2] == 1.0 and cold[0] < 1.0


def test_photometric_point_candela():
    desc = lights.light_from_params("Free_Light", {"intensity": 1500.0, "intensity_type": "candelas"})
    assert desc.kind == "POINT"
    assert desc.power == pytest.approx(1500.0 * 4.0 * math.pi / 683.0)


def test_photometric_lumens_rectangle():
    desc = lights.light_from_params("Target_Light", {
        "intensity": 683.0, "intensity_type": "lumens", "shape": "rectangle", "length": 2.0, "width": 1.0})
    assert desc.target
    assert (desc.kind, desc.shape, desc.size, desc.size_y) == ("AREA", "RECTANGLE", 2.0, 1.0)
    assert desc.power == pytest.approx(1.0)


def test_photometric_spot():
    desc = lights.light_from_params("Free_Light", {
        "distribution": "spotlight", "hotspot": 30.0, "falloff": 60.0, "intensity": 100.0})
    assert desc.kind == "SPOT"
    assert desc.spot_size == pytest.approx(math.radians(60.0))
    assert desc.spot_blend == pytest.approx(0.5)
    # Intensity in candela is the same along the axis whatever the cone: point-equivalent power.
    assert desc.power == pytest.approx(100.0 * 4.0 * math.pi / 683.0)


def test_kelvin_tints_photometric():
    desc = lights.light_from_params("Free_Light", {"use_kelvin": True, "kelvin": 3000.0})
    assert desc.color[2] < desc.color[0]


def test_standard_lights():
    omni = lights.light_from_params("Omnilight", {"multiplier": 0.5, "color": (1.0, 0.0, 0.0)})
    assert (omni.kind, omni.power, omni.color) == ("POINT", 500.0, (1.0, 0.0, 0.0))
    assert any("decay" in note for note in omni.notes)
    direct = lights.light_from_params("Directionallight", {})
    assert direct.kind == "SUN"


def test_vray_plane_sizes_are_half():
    desc = lights.light_from_params("VRayLight", {"type": "plane", "size0": 0.5, "size1": 0.25,
                                                  "multiplier": 2.0})
    assert (desc.size, desc.size_y) == (1.0, 0.5)
    assert desc.power == pytest.approx(2.0 * 0.5 * math.pi)
    assert lights.light_from_params("VRayLight", {"type": "dome"}) is None


def test_corona_and_unknown():
    sun = lights.light_from_params("CoronaSun", {"intensity": 1.0})
    assert sun.kind == "SUN"
    disk = lights.light_from_params("CoronaLight", {"shape": "disk", "width": 2.0, "intensity": 683.0,
                                                    "intensity_units": "lm"})
    assert (disk.kind, disk.shape, disk.power) == ("AREA", "DISK", pytest.approx(1.0))
    assert lights.light_from_params("SomeOtherLight", {}) is None


def test_cameras():
    cam = lights.camera_from_params("Targetcamera", {"fov": 45.0})
    assert cam.target
    assert cam.lens_mm == pytest.approx(36.0 / (2.0 * math.tan(math.radians(22.5))))
    phys = lights.camera_from_params("Physical", {"film_width_mm": 36.0, "focal_length_mm": 35.0,
                                                  "horizontal_shift": 10.0, "use_dof": True, "f_number": 2.8})
    assert phys.lens_mm == 35.0 and phys.shift_x == pytest.approx(0.1)
    assert phys.use_dof and phys.fstop == 2.8
    fov = lights.camera_from_params("Physical", {"specify_fov": True, "fov": 90.0})
    assert fov.lens_mm == pytest.approx(18.0)
    clipped = lights.camera_from_params("Freecamera", {"clip_on": True, "near_clip": 1.0, "far_clip": 50.0})
    assert (clipped.clip_start, clipped.clip_end) == (1.0, 50.0)


def test_world():
    world = lights.world_from_params({"background_color": (0.1, 0.2, 0.3), "environment_map": "C:\\hdri\\sky.hdr",
                                      "map_multiplier": 2.0})
    assert world.color == (0.1, 0.2, 0.3)
    assert world.environment_map == "C:\\hdri\\sky.hdr" and world.strength == 2.0
    assert lights.world_from_params({"environment_map": "x.hdr", "use_map": False}).environment_map is None
