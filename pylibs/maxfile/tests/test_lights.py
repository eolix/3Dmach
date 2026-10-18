# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Light and camera decoding tests (``maxfile.objects.lights``).

Synthetic fixtures follow the layouts established on the local corpus (``docs/format/lights.md``); the corpus tests
check facts about named sample files and skip without the corpus.
"""

import importlib.util
import math
import os
import struct

import pytest

import maxfile
from maxfile.objects.lights import CameraData, LightData, target_distance_of, target_node_of
from synth_max import NULL, SceneBuilder, cont, f32, leaf, refs_ordered, u32
from corpus_files import all_files, corpus_file, full_corpus_enabled, sample

ID = {   # key: (class ID (a, b), superclass)
    "node": ((1, 0), 1),
    "pb": ((0x8, 0), 0x8),
    "pb2": ((0x82, 0), 0x82),
    "omni": ((0x1011, 0), 0x30),
    "tspot": ((0x1012, 0), 0x30),
    "fdirect": ((0x1013, 0), 0x30),
    "free_light": ((0x32375FCC, 0x0B025CF0), 0x30),
    "target_rect": ((0x71794F9D, 0x70AE52F2), 0x30),
    "free_disc": ((0x5BCC6D42, 0x0C4F430E), 0x30),
    "arnold": ((0x6705F00D, 0xCA131D05), 0x30),
    "sun": ((0x27FE329C, 0x716F5B25), 0x30),
    "free_cam": ((0x1001, 0), 0x20),
    "target_cam": ((0x1002, 0), 0x20),
    "physical": ((0x46697218, 0x28E8008D), 0x20),
    "target_obj": ((0x1020, 0), 0x10),
    "shadow_map": ((0x100, 0), 0x10D0),
    "prs": ((0x2005, 0), 0x9008),
    "look_at": ((0x2006, 0), 0x9008),
    "bezier_pos": ((0x2008, 0), 0x900B),
    "bezier_float": ((0x2007, 0), 0x9003),
}
TARGET_FLAG = 1 << 14


class Builder(SceneBuilder):
    def __init__(self):
        super().__init__()
        self.c = {key: self.cls(key, cid, sup) for key, (cid, sup) in ID.items()}

    def add(self, key, *children):
        return self.obj(self.c[key], *children)

    # Old ParamBlock: 0x0002 container per parameter (0x0003 index + value chunk); animated: 0x0200+ marker.
    def old_pb(self, values, refs=None):
        children = [leaf(0x0001, u32(len(values)))]
        for index, value in sorted(values.items()):
            if value is None:       # Animated: controller in the reference slot equal to the index.
                body = leaf(0x0200)
            elif isinstance(value, tuple):
                body = leaf(0x0102, f32(*value))
            elif isinstance(value, int):
                body = leaf(0x0101, struct.pack("<i", value))
            else:
                body = leaf(0x0100, f32(value))
            children.append(cont(0x0002, leaf(0x0003, u32(index)), body))
        if refs:
            children.insert(0, refs_ordered(*refs))
        return self.add("pb", *children)

    # ParamBlock2: header + one 0x100E record per parameter (inline values).
    def pb2(self, records, extra=()):
        body = [leaf(0x0009, struct.pack("<HHIHI", 0, 0, 0, len(records), 0))]
        for pid, code, payload in records:
            body.append(leaf(0x100E, struct.pack("<HIHIHB", pid, code, 0, 0, 0, 0x40) + payload))
        body.extend(extra)
        return self.add("pb2", *body)

    def flags(self, mapping):
        out = []
        for chunk_type, value in mapping.items():
            out.append(leaf(chunk_type) if value is None else leaf(chunk_type, struct.pack("<H", value)))
        return out

    def pos_ctrl(self, xyz):
        return self.add("bezier_pos", leaf(0x2503, f32(*xyz)))

    def scene_node(self, name, obj, controller, flags=0):
        extra = (leaf(0x0960, u32(NULL, flags)),) if flags else ()
        return self.node(self.c["node"], name, refs=[controller, obj], extra=extra)

    def targeted(self, name, obj, position, target_position):
        """A node with a Look At controller aiming at a target node; returns (node, target node)."""
        target_obj = self.add("target_obj")
        target_ctrl = self.add("prs", refs_ordered(self.pos_ctrl(target_position)))
        target = self.scene_node(name + ".Target", target_obj, target_ctrl, flags=TARGET_FLAG)
        look_at = self.add("look_at", refs_ordered(target, self.pos_ctrl(position)))
        return self.scene_node(name, obj, look_at), target


def F(value):
    return struct.pack("<f", value)


def INT(value):
    return struct.pack("<i", value)


def B(value):
    return struct.pack("<I", int(value))


def RGB(*value):
    return f32(*value)


def _open(b):
    return maxfile.open(b.build())


def _decode(mf, index):
    return mf.scene.decode(mf.objects[index])


# -----------------------------------------------------------------------------
# Standard lights.

def test_omni():
    b = Builder()
    pb = b.old_pb({0: (1.0, 0.5, 0.25), 1: 2.0, 2: 0.0, 3: 50.0, 4: 0.0, 5: 40.0, 6: 80.0, 7: 200.0, 8: 33.0,
                   9: (0.0, 0.0, 0.0), 13: 1.0})
    shadow = b.add("shadow_map")
    omni = b.add("omni", refs_ordered(pb, NULL, NULL, shadow),
                 *b.flags({0x2580: 1, 0x2570: 0, 0x2561: 0, 0x2562: 1, 0x25D0: 2, 0x25B1: None}))
    node = b.scene_node("Omni01", omni, b.add("prs", refs_ordered(b.pos_ctrl((0, 0, 10)))))
    with _open(b) as mf:
        light = _decode(mf, omni)
        assert isinstance(light, LightData)
        assert light.class_name == "Omnilight" and light.source_class == "Omni"
        p = light.params
        assert p["color"] == (1.0, 0.5, 0.25) and p["multiplier"] == 2.0
        assert p["on"] is True and p["cast_shadows"] is False
        assert p["use_near_atten"] is False and p["use_far_atten"] is True
        assert p["decay_type"] == "inverse_square" and p["decay_start"] == 33.0
        assert p["affect_diffuse"] is True and p["affect_specular"] is False
        assert "hotspot" not in p and "target_distance" not in p
        assert light.shadow_generator == "shadow_map"
        assert light.nodes == [node] and light.target_node is None
        assert light.raw["0.1"] == 2.0


def test_target_spot_and_target_link():
    b = Builder()
    pb = b.old_pb({0: (1.0, 1.0, 1.0), 1: 1.0, 4: 30.0, 5: 50.0})
    spot = b.add("tspot", refs_ordered(pb), *b.flags({0x2580: 0, 0x2570: 1}))
    node, target = b.targeted("Spot01", spot, (0.0, 0.0, 10.0), (3.0, 4.0, 10.0))
    with _open(b) as mf:
        light = _decode(mf, spot)
        assert light.class_name == "Targetspot"
        assert light.params["hotspot"] == 30.0 and light.params["falloff"] == 50.0   # Degrees, as stored.
        assert light.params["on"] is False and light.params["cast_shadows"] is True
        assert light.params["decay_type"] == "none"
        assert light.target_node == target
        assert math.isclose(light.params["target_distance"], 5.0, rel_tol=1e-6)
        scene_node = mf.scene.node(node)
        assert target_node_of(mf.scene, scene_node).name == "Spot01.Target"
        assert mf.scene.node(target).is_target
        assert math.isclose(target_distance_of(mf.scene, scene_node), 5.0, rel_tol=1e-6)
        assert target_node_of(mf.scene, mf.scene.node(target)) is None


def test_animated_parameters():
    b = Builder()
    controller = b.add("bezier_float", leaf(0x2501, f32(0.75)))
    unreadable = b.add("bezier_float")          # No value chunk.
    pb = b.old_pb({0: (1.0, 1.0, 1.0), 1: None, 5: None}, refs=[NULL, controller, NULL, NULL, NULL, unreadable])
    omni = b.add("omni", refs_ordered(pb))
    with _open(b) as mf:
        light = _decode(mf, omni)
        assert light.params["multiplier"] == 0.75
        assert "near_atten_end" not in light.params
        assert set(light.animated) == {"multiplier", "near_atten_end"}


def test_free_direct_target_distance_kept():
    b = Builder()
    pb = b.old_pb({0: (1.0, 1.0, 1.0), 4: 100.0, 5: 120.0, 18: 240.0})
    direct = b.add("fdirect", refs_ordered(pb))
    with _open(b) as mf:
        light = _decode(mf, direct)
        assert light.class_name == "Directionallight"
        assert light.params["hotspot"] == 100.0 and light.params["target_distance"] == 240.0


def test_missing_param_block():
    b = Builder()
    omni = b.add("omni")
    with _open(b) as mf:
        assert _decode(mf, omni) is None
        assert any("no parameter block" in w for w in mf.scene.warnings)


# -----------------------------------------------------------------------------
# Photometric lights.

def _photometric_blocks(b, distribution=0, units=1, sizes=(48.0, 24.0, 5.5), web=None):
    main = b.pb2([(1, 1, INT(distribution)), (2, 4, B(True)), (3, 4, B(False)), (5, 2, RGB(1.0, 0.9, 0.8)),
                  (6, 0, F(800.0)), (8, 0, F(5000.0)), (10, 4, B(True)), (13, 0, F(39.37)), (14, 1, INT(units)),
                  (18, 4, B(False)), (19, 0, F(100.0))])
    spot = b.pb2([(0, 0, F(30.0)), (1, 0, F(60.0))])
    web_block = web if web is not None else b.pb2([(1, 0, F(0.0)), (2, 0, F(0.0)), (3, 0, F(0.0))])
    shape = b.pb2([(7, 0, F(240.0)), (11, 7, F(sizes[0])), (12, 7, F(sizes[1])), (13, 7, F(sizes[2]))])
    return [main, b.pb2([]), spot, web_block, b.add("shadow_map"), shape]


def test_photometric_rectangle_target():
    b = Builder()
    rect = b.add("target_rect", refs_ordered(*_photometric_blocks(b, distribution=2, units=2,
                                                                  sizes=(10.0, 20.0, 5.5))))
    node, target = b.targeted("Rect01", rect, (0.0, 0.0, 0.0), (0.0, 0.0, -7.0))
    with _open(b) as mf:
        light = _decode(mf, rect)
        p = light.params
        assert light.class_name == "Target_Light" and light.source_class == "Target Rectangle"
        assert p["shape"] == "rectangle" and p["distribution"] == "uniform_diffuse"
        assert p["intensity"] == 800.0 and p["intensity_type"] == "lux"
        assert p["on"] is True and p["cast_shadows"] is False
        assert p["use_kelvin"] is True and p["kelvin"] == 5000.0
        assert math.isclose(p["rgb"][1], 0.9, rel_tol=1e-6)
        # Parameter 12 is the extent along local X (the importer's length), 11 along Y.
        assert p["length"] == 20.0 and p["width"] == 10.0 and "radius" not in p
        assert math.isclose(p["target_distance"], 7.0, rel_tol=1e-6)      # From the target, not parameter 7.
        assert light.target_node == target
        assert "web_file_asset" not in p


def test_photometric_disc_and_web_asset():
    b = Builder()
    guid = bytes(range(16))
    # A file name stored by asset reference: value 0xFFFFFFFE, then a 0x000F container holding the GUID.
    web = b.add("pb2", leaf(0x0009, struct.pack("<HHIHI", 0, 0, 0, 1, 0)),
                leaf(0x100E, struct.pack("<HIHIHB", 0, 9, 0, 0, 0, 0x40) + u32(0xFFFFFFFE)),
                cont(0x000F, leaf(0x0002, guid)))
    disc = b.add("free_disc", refs_ordered(*_photometric_blocks(b, distribution=3, sizes=(48.0, 24.0, 12.5),
                                                                web=web)))
    with _open(b) as mf:
        light = _decode(mf, disc)
        p = light.params
        assert light.class_name == "Free_Light"
        assert p["shape"] == "disc" and p["radius"] == 12.5 and "length" not in p
        assert p["distribution"] == "web" and p["web_file_asset"] == guid.hex()
        assert p["target_distance"] == 240.0 and light.target_node is None


def test_photometric_point_spotlight():
    b = Builder()
    point = b.add("free_light", refs_ordered(*_photometric_blocks(b, distribution=1, units=0)))
    with _open(b) as mf:
        p = _decode(mf, point).params
        assert p["shape"] == "point" and p["distribution"] == "spotlight" and p["intensity_type"] == "lumens"
        assert (p["hotspot"], p["falloff"]) == (30.0, 60.0)
        assert not {"length", "width", "radius"} & set(p)


# -----------------------------------------------------------------------------
# Arnold, sun.

def test_arnold_light():
    b = Builder()
    pb = b.pb2([(0, 4, B(True)), (1, 4, B(False)), (2, 0, F(24.0)), (4, 2, RGB(1, 1, 1)), (10, 0, F(2.0)),
                (11, 0, F(8.0)), (18, 1, INT(3)), (33, 0, F(10.0)), (34, 0, F(20.0))])
    light = b.add("arnold", refs_ordered(pb))
    with _open(b) as mf:
        data = _decode(mf, light)
        assert data.class_name == "Arnold_Light"
        assert data.params["type"] == "quad" and data.params["intensity"] == 2.0 and data.params["exposure"] == 8.0
        assert (data.params["quad_x"], data.params["quad_y"]) == (10.0, 20.0)


def test_sun_positioner_direction():
    b = Builder()
    pb = b.pb2([(14, 0, F(0.0)), (18, 0, F(90.0)), (19, 0, F(30.0)), (12, 0, F(37.795)), (13, 0, F(-122.394))])
    sun = b.add("sun", refs_ordered(pb))
    with _open(b) as mf:
        p = _decode(mf, sun).params
        x, y, z = p["sun_direction"]
        # Azimuth 90 (east = +X with north = +Y), altitude 30 degrees.
        assert math.isclose(x, math.cos(math.radians(30)), abs_tol=1e-6)
        assert math.isclose(y, 0.0, abs_tol=1e-6) and math.isclose(z, 0.5, abs_tol=1e-6)


# -----------------------------------------------------------------------------
# Cameras.

def test_free_camera():
    b = Builder()
    pb = b.old_pb({0: math.radians(60.0), 1: 160.0, 2: 1.0, 3: 1000.0, 4: 0.0, 5: 1000.0, 6: 0, 7: 0, 8: 0})
    cam = b.add("free_cam", refs_ordered(pb))
    with _open(b) as mf:
        data = _decode(mf, cam)
        assert isinstance(data, CameraData) and data.class_name == "Freecamera"
        assert math.isclose(data.params["fov"], 60.0, rel_tol=1e-5)
        assert data.params["fov_type"] == "horizontal"
        assert data.params["target_distance"] == 160.0
        assert (data.params["near_clip"], data.params["far_clip"]) == (1.0, 1000.0)


def test_target_camera_distance_from_target():
    b = Builder()
    pb = b.old_pb({0: math.radians(45.0), 1: 0.0})      # Target cameras don't keep parameter 1 up to date.
    cam = b.add("target_cam", refs_ordered(pb), leaf(0x2682))
    node, target = b.targeted("Camera01", cam, (0.0, -100.0, 0.0), (0.0, 0.0, 0.0))
    with _open(b) as mf:
        data = _decode(mf, cam)
        assert data.class_name == "Targetcamera" and data.target_node == target
        assert math.isclose(data.params["target_distance"], 100.0, rel_tol=1e-6)
        assert data.flags == {0x2682: None}


@pytest.mark.parametrize("custom_focus", [False, True])
def test_physical_camera(custom_focus):
    b = Builder()
    pb = b.pb2([(0, 4, B(True)), (1, 4, B(False)), (4, 0, F(36.0)), (5, 0, F(50.0)), (6, 0, F(2.8)),
                (7, 0, F(1.0)), (8, 7, F(10.0)), (9, 7, F(3.0)), (10, 1, INT(int(custom_focus))), (11, 4, B(True)),
                (20, 0, F(45.0)), (47, 4, B(True)), (48, 7, F(0.5)), (49, 7, F(80.0))])
    cam = b.add("physical", refs_ordered(pb))
    node, target = b.targeted("PhysCamera001", cam, (0.0, 0.0, 0.0), (10.0, 0.0, 0.0))
    with _open(b) as mf:
        p = _decode(mf, cam).params
        assert p["targeted"] is True and p["film_width_mm"] == 36.0 and p["focal_length_mm"] == 50.0
        assert math.isclose(p["f_number"], 2.8, rel_tol=1e-6) and p["use_dof"] is True
        assert (p["clip_on"], p["near_clip"], p["far_clip"]) == (True, 0.5, 80.0)
        assert math.isclose(p["target_distance"], 10.0, rel_tol=1e-6)
        assert p["focus_distance"] == (3.0 if custom_focus else p["target_distance"])


# -----------------------------------------------------------------------------
# The importer's conversion accepts the decoded parameters (no Blender needed for the *_from_params functions).

def _importer_lights():
    path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts", "addons_core", "mx_io_max",
                        "lights.py")
    if not os.path.isfile(path):
        pytest.skip("importer module not found")
    spec = importlib.util.spec_from_file_location("mx_io_max_lights_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_importer_accepts_decoded_params():
    lights = _importer_lights()
    b = Builder()
    spot = b.add("tspot", refs_ordered(b.old_pb({0: (1.0, 1.0, 1.0), 1: 1.0, 4: 30.0, 5: 50.0})),
                 *b.flags({0x2580: 1, 0x2570: 1}))
    rect = b.add("target_rect", refs_ordered(*_photometric_blocks(b, distribution=2, sizes=(10.0, 20.0, 5.5))))
    cam = b.add("physical", refs_ordered(b.pb2([(4, 0, F(36.0)), (5, 0, F(50.0)), (7, 0, F(1.0))])))
    with _open(b) as mf:
        spot_data, rect_data, cam_data = (_decode(mf, i) for i in (spot, rect, cam))
    desc = lights.light_from_params(spot_data.class_name, spot_data.params)
    assert desc.kind == "SPOT" and math.isclose(desc.spot_size, math.radians(50.0))
    desc = lights.light_from_params(rect_data.class_name, rect_data.params)
    assert desc.kind == "AREA" and desc.shape == "RECTANGLE" and (desc.size, desc.size_y) == (20.0, 10.0)
    assert desc.target
    desc = lights.camera_from_params(cam_data.class_name, cam_data.params)
    assert math.isclose(desc.lens_mm, 50.0)


# -----------------------------------------------------------------------------
# Corpus.

def _lights_and_cameras(path):
    """[(node name, decoded)] for every light / camera node of a corpus file, and the scene."""
    out = []
    with maxfile.open(path) as mf:
        scene = mf.scene
        for node in scene.nodes:
            obj = node.object
            if obj is not None and obj.superclass_id in (0x20, 0x30):
                out.append((node, scene.decode(obj)))
        names = {node.index: node.name for node in scene.nodes}
    return out, names


def _class_counts(found):
    counts = {}
    for _node, data in found:
        counts[data.class_name] = counts.get(data.class_name, 0) + 1
    return counts


def test_corpus_cornell_box():
    found, names = _lights_and_cameras(corpus_file("Scenes/Lighting/Lighting-Cornel Box_Scanline.max"))
    assert _class_counts(found) == {"Omnilight": 3, "Targetspot": 1, "Targetcamera": 1}
    by_name = {node.name: data for node, data in found}
    main = by_name["Main Light"].params
    assert main["multiplier"] == 2.0 and main["cast_shadows"] and main["decay_type"] == "inverse"
    assert not by_name["Blue Light"].params["affect_specular"]
    spot = by_name["Caustic Spot Light"]
    assert (spot.params["hotspot"], spot.params["falloff"]) == (60.0, 62.0)
    assert names[spot.target_node] == "Caustic Spot Light.Target"
    camera = by_name["Camera01"]
    assert names[camera.target_node] == "Camera01.Target"
    assert math.isclose(camera.params["fov"], 45.0, rel_tol=1e-5)
    assert 239.0 < camera.params["target_distance"] < 240.0


def test_corpus_lights_off():
    found, _names = _lights_and_cameras(corpus_file("Scenes/Lighting/Lighting-Vertex.max"))
    omni = [data for _node, data in found if data.class_name == "Omnilight"]
    assert len(omni) == 2 and not any(data.params["on"] for data in omni)


def test_corpus_photometric_web_and_sun():
    found, names = _lights_and_cameras(corpus_file("Scenes/Design Visualization/IES lights_ART.max"))
    assert _class_counts(found) == {"Free_Light": 2, "Target_Light": 6, "Physical": 2, "Sun_Positioner": 1}
    web = [data for _node, data in found if data.params.get("distribution") == "web"]
    assert len(web) == 7 and all(len(data.params["web_file_asset"]) == 32 for data in web)
    targets = {names[data.target_node] for _node, data in found if data.class_name == "Target_Light"}
    assert "Photometric-wallwash02.Target" in targets
    sun = next(data for _node, data in found if data.class_name == "Sun_Positioner").params
    assert (sun["year"], sun["month"], sun["day"], sun["hour"], sun["minute"]) == (2017, 6, 21, 21, 30)
    assert sun["altitude"] < 0.0         # 21:30 in Chicago (41.87 N): the sun has set.


def test_corpus_physical_camera_dof():
    found, names = _lights_and_cameras(corpus_file("Scenes/CameraEffects/DOF/DOF_ART.max"))
    (node, camera), = found
    p = camera.params
    assert camera.class_name == "Physical" and p["targeted"] and names[camera.target_node] == node.name + ".Target"
    assert p["f_number"] == 1.0 and p["use_dof"] and p["film_width_mm"] == 36.0
    assert math.isclose(p["target_distance"], camera.raw["0.8"], rel_tol=1e-4)    # Stored = measured.


def test_corpus_light_gallery():
    found, _names = _lights_and_cameras(corpus_file("Scenes/Rendering/LightGallery_Max2018_ART.max"))
    shapes = sorted(data.params["shape"] for _node, data in found if data.class_name == "Free_Light")
    assert shapes == ["cylinder"] + ["disc"] * 6
    found, _names = _lights_and_cameras(corpus_file("Scenes/Rendering/LightGallery_Max2018_Arnold.max"))
    types = sorted(data.params["type"] for _node, data in found if data.class_name == "Arnold_Light")
    assert types == ["cylinder"] + ["spot"] * 6


def _check_file(path):
    """Every light / camera node decodes; its target (if any) is a target node with a "Target" object."""
    count = 0
    with maxfile.open(path) as mf:
        scene = mf.scene
        for node in scene.nodes:
            obj = node.object
            if obj is None or obj.superclass_id not in (0x20, 0x30):
                continue
            data = scene.decode(obj)
            assert isinstance(data, (LightData, CameraData)), (path, node.name)
            target = target_node_of(scene, node)
            if target is not None:
                assert target.is_target and target.object.class_label() == "Target", (path, node.name)
            count += 1
    return count


def test_corpus_sample_decodes():
    files = sample(30)
    if not files:
        pytest.skip("no corpus")
    assert sum(_check_file(path) for path in files) > 0


@pytest.mark.skipif(not full_corpus_enabled(), reason="set MX_FULL_CORPUS=1")
def test_corpus_all_decode():
    total = sum(_check_file(path) for path in all_files())
    assert total >= 830     # Light / camera nodes (754 objects, some instanced).
