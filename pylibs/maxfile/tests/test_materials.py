# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Material, map, parameter-block and asset-metadata tests.

The fixtures (``synth_max``) encode the *documented, unverified* layouts of ``docs/format/overview.md`` §5 only:
name chunks per class, the u16-index parameter rule, the two VRayMtl indices it names, Arnold sockets, bitmap
path chunks and the asset metadata split rule.
"""

import random
import struct

import pytest

import maxfile
from maxfile.assets import parse_asset_metadata
from maxfile.objects.materials import MaterialData
from maxfile.objects.paramblock import read_param_block
from synth_max import NULL, SceneBuilder, cont, f32, leaf, param, refs_ordered, refs_sparse, text, u32

IDS = {
    "standard": (0x0002, 0),
    "multi": (0x0200, 0),
    "physical": (0x3D6B1CEC, 0xDEADC001),
    "vray": (0x37BF3F2F, 0x7034695C),
    "corona": (0x6912AB89, 0x87151720),
    "corona_legacy": (0x70BE6506, 0x448931DD),
    "arnold": (0x7E73161F, 0x62F74B4C),
    "raytrace": (0x27190FF4, 0x329B106E),
}


class Builder(SceneBuilder):
    def __init__(self):
        super().__init__()
        self.node_class = self.cls("Node", (1, 0), 1)
        self.c = {key: self.cls(key, cid, 0xC00) for key, cid in IDS.items()}
        self.block = self.cls("ParamBlock?", (0x7E57, 3), 0x82)
        self.bitmap = self.cls("Bitmaptexture?", (0x7E57, 4), 0xC10)
        self.socket = self.cls("ArnoldSocket?", (0x7E57, 5), 0x82)
        self.asset_ref = self.cls("AssetRef", (0x3333, 0), 0x99)

    def mat(self, key, *children):
        return self.obj(self.c[key], *children)

    def bitmap_direct(self, path):
        block = self.obj(self.block, cont(0x0005, leaf(0x1230, text(path))))
        return self.obj(self.bitmap, refs_ordered(block))


def _open(b, **kwargs):
    return maxfile.open(b.build(**kwargs))


# -----------------------------------------------------------------------------
# Names (§5.1)

@pytest.mark.parametrize("key,children,expected_class,name", [
    ("standard", (cont(0x4000, leaf(0x0001, text("Std")), leaf(0x0002, text("x"))),), "Standardmaterial", "Std"),
    ("physical", (cont(0x0100, leaf(0x4001, text("Phys"))),), "PhysicalMaterial", "Phys"),
    ("vray", (leaf(0x5431, text("Wood")),), "VRayMtl", "Wood"),
    ("corona", (leaf(0x0FA0, text("Glass")),), "CoronaPhysicalMtl", "Glass"),
    ("corona_legacy", (leaf(0x0FA0, text("Old")),), "CoronaMtl", "Old"),
    ("raytrace", (leaf(0x0100, text("Ray@Chrome")),), "Raytrace", "Chrome"),
    ("arnold", (leaf(0x0100, text("x@Skin")),), "ai_standard_surface", "Skin"),
])
def test_material_names(key, children, expected_class, name):
    b = Builder()
    m = b.mat(key, *children)
    with _open(b) as mf:
        mat = mf.scene.decode(mf.objects[m])
        assert isinstance(mat, MaterialData)
        assert mat.class_name == expected_class and mat.name == name and mat.index == m


def test_missing_names_are_none():
    b = Builder()
    m1 = b.mat("standard", leaf(0x4000, b"leaf"))
    m2 = b.mat("raytrace", leaf(0x0100, text("no at sign")))
    m3 = b.mat("vray")
    with _open(b) as mf:
        assert [mf.scene.decode(mf.objects[i]).name for i in (m1, m2, m3)] == [None, None, None]


# -----------------------------------------------------------------------------
# Parameters (§5.1)

def test_vray_documented_params():
    b = Builder()
    # The reader takes a colour from the last f32[3] and a float from the last f32 of the entry.
    block = b.obj(b.block, param(0x02, f32(9)), param(0x01, u32(0) + f32(0.1, 0.2, 0.3)),
                  param(0x06, u32(0) + f32(0.75)), refs_ordered(1, 1))
    m = b.mat("vray", leaf(0x5431, text("Wood")), refs_ordered(block))
    with _open(b) as mf:
        mat = mf.scene.decode(mf.objects[m])
        assert mat.params.keys() == {"diffuse", "reflection_glossiness"}
        assert mat.params["diffuse"] == pytest.approx((0.1, 0.2, 0.3))
        assert mat.params["reflection_glossiness"] == 0.75
        assert mat.param_blocks == [block]
        assert mf.warnings == []


def test_vray_missing_params_reported():
    b = Builder()
    m = b.mat("vray", refs_ordered(b.obj(b.block, param(0x06, f32(0.5)))))
    with _open(b) as mf:
        mat = mf.scene.decode(mf.objects[m])
        assert mat.params == {"reflection_glossiness": 0.5}
        assert any("parameter 0x01 (diffuse) not found" in w for w in mf.warnings)


def test_other_classes_have_no_guessed_params():
    b = Builder()
    m = b.mat("standard", refs_ordered(b.obj(b.block, param(0x01, f32(1, 2, 3)), param(0x06, f32(0.5)))))
    with _open(b) as mf:
        assert mf.scene.decode(mf.objects[m]).params == {}


def test_arnold_sockets():
    b = Builder()
    tex = b.bitmap_direct("C:\\maps\\skin.png")
    s1 = b.obj(b.socket, leaf(0x0001, text("base_color")), leaf(0x0003, f32(0.8, 0.5, 0.4)))
    s2 = b.obj(b.socket, leaf(0x0001, text("metalness")), leaf(0x0003, f32(1.0)))
    s3 = b.obj(b.socket, leaf(0x0001, text("opacity")), leaf(0x0003, f32(1, 1, 1, 1)))
    s4 = b.obj(b.socket, leaf(0x0001, text("base_color.shader")), refs_ordered(tex))
    s5 = b.obj(b.socket, leaf(0x0001, text("odd")), leaf(0x0003, b"\x01\x02"))
    s6 = b.obj(b.socket, leaf(0x0001, text("normal.shader")))
    m = b.mat("arnold", leaf(0x0100, text("x@Skin")), refs_ordered(s1, s2, s3, s4, s5, s6))
    with _open(b) as mf:
        mat = mf.scene.decode(mf.objects[m])
        assert mat.params["base_color"] == pytest.approx((0.8, 0.5, 0.4))
        assert mat.params["metalness"] == 1.0 and mat.params["opacity"] == (1.0, 1.0, 1.0)
        assert "odd" not in mat.params
        assert mat.maps["base_color_shader"].path == "C:\\maps\\skin.png"
        assert mat.maps["normal_shader"] is None
        assert any("socket 'odd' value not understood" in w for w in mf.warnings)


# -----------------------------------------------------------------------------
# Multi/Sub-Object (§5.3)

def test_multi_sub():
    b = Builder()
    a = b.mat("vray", leaf(0x5431, text("A")))
    c = b.mat("standard", cont(0x4000, leaf(0x0001, text("C"))))
    block = b.obj(b.block, param(0x01, f32(1)))
    multi = b.mat("multi", refs_sparse({0: block, 1: a, 3: c}))
    b.node(b.node_class, "N", refs=[NULL, NULL, NULL, multi])
    with _open(b) as mf:
        mat = mf.scene.decode(mf.objects[multi])
        assert mat.class_name == "Multimaterial"
        assert [s.name for s in mat.sub_materials] == ["A", "C"]
        assert mat.sub_ids is None
        assert any("sub-material IDs not decoded" in w for w in mf.warnings)


def test_multi_sub_cycle_and_empty():
    b = Builder()
    multi = b.placeholder()
    b.set_obj(multi, b.c["multi"], refs_ordered(multi))
    empty = b.mat("multi")
    with _open(b) as mf:
        mat = mf.scene.decode(mf.objects[multi])
        assert mat.sub_materials == [None]
        assert any("reference cycle" in w for w in mf.warnings)
        assert mf.scene.decode(mf.objects[empty]).sub_materials == []


# -----------------------------------------------------------------------------
# Maps and bitmap paths (§5.2)

def test_direct_bitmap_path():
    b = Builder()
    tex = b.bitmap_direct("D:\\tex\\wood.jpg")
    m = b.mat("vray", refs_ordered(b.obj(b.block, param(0x01, f32(1, 1, 1)), param(0x06, f32(1))), tex))
    with _open(b) as mf:
        mat = mf.scene.decode(mf.objects[m])
        (slot, tmap), = mat.unassigned_maps.items()
        assert slot == 1 and tmap.path == "D:\\tex\\wood.jpg" and tmap.path_source == "0x1230"
        assert tmap.class_name == "Bitmaptexture?" and tmap.index == tex
        assert mat.maps == {}


def _asset_stream(paths):
    # Synthetic stream following only what overview.md §5.2 says: headers and UTF-16 paths separated by zero runs.
    parts = []
    for i, path in enumerate(paths):
        parts.append(b"\x07\x00\x00\x00HDR" + bytes([0x41 + i]) + b"\x00\x00\x00")
        parts.append(path.encode("utf-16-le") + b"\x00\x00\x00\x00")
    return b"".join(parts)


def test_asset_metadata_parsing():
    entries = parse_asset_metadata(_asset_stream(["C:\\a\\one.png", "rel/two.tga", "three.exr"]))
    assert [e.path for e in entries] == ["C:\\a\\one.png", "rel/two.tga", "three.exr"]
    assert entries[0].header.endswith(b"HDRA") and entries[2].index == 2
    assert parse_asset_metadata(b"") == []
    assert parse_asset_metadata(b"\x00" * 100 + b"\xFF\xFE\x01") == []


def test_asset_index_bitmap():
    b = Builder()
    block = b.obj(b.block, leaf(0x1260, u32(1)))
    tex = b.obj(b.bitmap, refs_ordered(block))
    out_of_range = b.obj(b.bitmap, refs_ordered(b.obj(b.block, leaf(0x1260, u32(50)))))
    via_object = b.obj(b.bitmap, refs_ordered(b.obj(b.asset_ref)))
    m = b.mat("standard", refs_ordered(tex, out_of_range, via_object))
    # The asset stream is found by directory position (overview.md §1); here it is the only non-chunk stream.
    data = b.build(extra_streams={"ZAssets": _asset_stream(["first.png", "C:\\second.png"])})
    with maxfile.open(data) as mf:
        assert mf.asset_metadata.stream == "ZAssets"
        mat = mf.scene.decode(mf.objects[m])
        maps = mat.unassigned_maps
        assert maps[0].path == "C:\\second.png" and maps[0].asset_index == 1
        assert maps[0].path_source == "asset_metadata"
        assert maps[1].path is None and maps[1].asset_index == 50
        assert maps[2].path_source == "asset_object_0x3333" and maps[2].path is None
        text_ = "\n".join(mf.warnings)
        assert "asset index 50 not resolved" in text_ and "asset reference object" in text_


def test_no_asset_stream():
    b = Builder()
    tex = b.obj(b.bitmap, refs_ordered(b.obj(b.block, leaf(0x1260, u32(0)))))
    b.mat("standard", refs_ordered(tex))
    with _open(b) as mf:
        assert mf.asset_metadata.stream is None and mf.asset_metadata.entries == []
        assert any("no asset metadata stream" in w for w in mf.warnings)


# -----------------------------------------------------------------------------
# Generic parameter blocks (§5.1)

def test_param_block_guesses():
    b = Builder()
    block = b.obj(b.block, param(0x10, f32(1.5)), param(0x11, f32(0.1, 0.2, 0.3)),
                  param(0x12, f32(0.1, 0.2, 0.3, 1.0)), param(0x13, struct.pack("<i", -4)),
                  leaf(0x0001, b"\x01"), cont(0x0009, param(0x14, f32(1))), refs_ordered(0))
    with _open(b) as mf:
        data = read_param_block(mf.objects[block])
        assert data.object_index == block
        assert [e.param_id for e in data.entries] == [0x10, 0x11, 0x12, 0x13]
        assert data.get(0x10).as_float() == 1.5 and data.get(0x10).as_color() is None
        assert data.get(0x11).as_color() == pytest.approx((0.1, 0.2, 0.3))
        assert data.get(0x12).as_rgba_color() == pytest.approx((0.1, 0.2, 0.3))
        assert data.get(0x13).as_int() == -4
        assert data.get(0x99) is None
        assert mf.scene.param_block(mf.objects[block]).entries[0].raw == struct.pack("<H", 0x10) + f32(1.5)


# -----------------------------------------------------------------------------
# Corruption

def test_fuzzed_materials_never_crash():
    b = Builder()
    tex = b.bitmap_direct("C:\\x.png")
    block = b.obj(b.block, param(0x01, f32(1, 1, 1)), param(0x06, f32(1)), leaf(0x1260, u32(0)))
    vray = b.mat("vray", leaf(0x5431, text("V")), refs_ordered(block, tex))
    sock = b.obj(b.socket, leaf(0x0001, text("base_color")), leaf(0x0003, f32(1, 1, 1)))
    arnold = b.mat("arnold", leaf(0x0100, text("a@b")), refs_ordered(sock))
    multi = b.mat("multi", refs_ordered(vray, arnold))
    original = list(b.objects)
    rng = random.Random(11)
    for _ in range(300):
        b.objects = []
        for data in original:
            data = bytearray(data)
            for _ in range(rng.randint(0, 3)):
                data[rng.randrange(len(data))] = rng.getrandbits(8)
            b.objects.append(bytes(data))
        try:
            mf = maxfile.open(b.build(extra_streams={"ZAssets": bytes(rng.getrandbits(8) for _ in range(64))}))
        except maxfile.MaxFileError:
            continue
        for index in (vray, arnold, multi, tex):
            if index < len(mf.objects):
                mf.scene.decode(mf.objects[index])
        mf.warnings
