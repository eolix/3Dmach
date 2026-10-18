# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Materials, texture maps and the asset metadata stream.

The synthetic fixtures follow the layouts worked out on the corpus (see ``maxfile/objects/materials.py``,
``maps.py`` and ``assets.py``); they are built in code, with made-up values. The corpus tests at the end check
facts of named sample files and skip without the corpus.
"""

import struct
import uuid

import pytest

import maxfile
from maxfile.assets import AssetMetadata, format_guid, parse_asset_metadata
from maxfile.objects.maps import MapData, object_name, read_map
from maxfile.objects.materials import MaterialData
from corpus_files import all_files, corpus_file, full_corpus_enabled, sample
from synth_max import NULL, SceneBuilder, cont, f32, leaf, pb2_block, pb2_param, refs_ordered, refs_sparse, text, u32

GUID_A = uuid.UUID("6c009b10-b7e1-4141-86b8-d9f72423860f")
GUID_B = uuid.UUID("0f0e0d0c-0b0a-0908-0706-050403020100")

CLASSES = {
    "standard": ((0x2, 0), 0xC00),
    "multi": ((0x200, 0), 0xC00),
    "physical": ((0x3D6B1CEC, 0xDEADC001), 0xC00),
    "arnold": ((0x7E73161F, 0x62F74B4C), 0xC00),
    "blend": ((0x250, 0), 0xC00),
    "blinn": ((0x38, 0), 0x10B0),
    "anisotropic": ((0x2857F460, 0), 0x10B0),
    "texmaps": ((0x1200, 0), 0x1080),
    "bitmap": ((0x240, 0), 0xC10),
    "checker": ((0x200, 0), 0xC10),
    "uvgen": ((0x100, 0), 0xC20),
    "pb2": ((0x82, 0), 0x82),
    "pb": ((0x8, 0), 0x8),
    "aiparam": ((0x38E67D6E, 0x3DE3000E), 0x200),
}


# -----------------------------------------------------------------------------
# Builders

def mtl_header(name):
    """The MtlBase header: name (0x4001) and flags (0x4003), in a 0x4000 container."""
    return cont(0x4000, leaf(0x4001, text(name)), leaf(0x4003, u32(0x200)))


def asset_string(s):
    return u32(len(s)) + text(s) + b"\0\0"


def asset_entry(guid, kind, path, resolved=""):
    data = guid.bytes_le + asset_string(kind) + asset_string(path)
    if resolved is not None:
        data += asset_string(resolved)
    return data


class Builder(SceneBuilder):
    def __init__(self):
        super().__init__()
        self.c = {key: self.cls(key, cid, sup) for key, (cid, sup) in CLASSES.items()}
        self.node_class = self.cls("Node", (1, 0), 1)

    def add(self, key, *children):
        return self.obj(self.c[key], *children)

    def pb2(self, *records, refs=None):
        return self.add("pb2", *pb2_block(0, *records, refs=refs))

    def old_pb(self, values):
        children = [leaf(0x0001, u32(len(values)))]
        for index, value in sorted(values.items()):
            body = leaf(0x0101, struct.pack("<i", value)) if isinstance(value, int) else leaf(0x0100, f32(value))
            children.append(cont(0x0002, leaf(0x0003, u32(index)), body))
        return self.add("pb", *children)

    def bitmap(self, name, guid=None, channel=1, tiling=(1.0, 1.0), offset=(0.0, 0.0)):
        uv_pb = self.old_pb({0: offset[0], 1: offset[1], 2: tiling[0], 3: tiling[1], 6: 0.5, 7: 1.0, 10: 1})
        uv = self.add("uvgen", refs_ordered(uv_pb), leaf(0x9002, u32(0x50000003)), leaf(0x9005, u32(0)),
                      leaf(0x900B, u32(channel)))
        records = [pb2_param(0, "float", 0.0)]
        extra = []
        if guid is not None:
            # File name parameter (type 9) holding an asset reference: length 0xFFFFFFFE, then the 0x000F container.
            head = struct.pack("<HIHIHB", 16, 9, 0, 0x82, 0, 0x40)
            records.append(leaf(0x100E, head + u32(0xFFFFFFFE)))
            extra.append(cont(0x000F, leaf(0x0002, guid.bytes_le)))
        else:
            records.append(pb2_param(16, "filename", None))
        block = pb2_block(0, *records)
        pb = self.add("pb2", *block, *extra)
        return self.add("bitmap", mtl_header(name), refs_ordered(uv, pb))

    def ai_param(self, name, ptype, value=b"", refs=None):
        children = [leaf(0x0001, text(name)), leaf(0x0002, u32(ptype)), leaf(0x0009, u32(1 if refs else 0)),
                    cont(0x0003, leaf(0x0004, u32(1)), leaf(0x0005, u32(NULL)), leaf(0x0006, value))]
        if refs:
            children.insert(0, refs_ordered(*refs))
        return self.add("aiparam", *children)

    def ai_group(self, name, members):
        return self.add("aiparam", refs_ordered(*members), leaf(0x0001, text(name)), leaf(0x0002, u32(21)),
                        cont(0x0003, leaf(0x0004, u32(len(members)))))


def _open(b, assets=None, stream="FileAssetMetaData3"):
    extra = {stream: assets} if assets is not None else None
    return maxfile.open(b.build(extra_streams=extra))


# -----------------------------------------------------------------------------
# Asset metadata

def test_asset_metadata_v3_and_lookup():
    data = (asset_entry(GUID_A, "Bitmap", "maps\\wood.jpg", "C:\\scenes\\maps\\wood.jpg")
            + asset_entry(GUID_B, "Photometric", "lamp.ies", ""))
    entries, warnings = parse_asset_metadata(data, 3)
    assert warnings == []
    assert [(e.kind, e.path, e.resolved_path) for e in entries] == [
        ("Bitmap", "maps\\wood.jpg", "C:\\scenes\\maps\\wood.jpg"), ("Photometric", "lamp.ies", None)]
    assert entries[0].guid == str(GUID_A) == format_guid(GUID_A.bytes_le)
    assets = AssetMetadata("FileAssetMetaData3", entries)
    assert assets.get(GUID_A.bytes_le).path == "maps\\wood.jpg"
    assert assets.get("{" + str(GUID_B).upper() + "}").kind == "Photometric"

    class Ref:      # Like maxfile.objects.paramblock.AssetRef.
        guid = str(GUID_A)
        raw = GUID_A.bytes_le
    assert assets.get(Ref()).index == 0
    assert assets.path(1) == "lamp.ies" and assets.path(2) is None


def test_asset_metadata_v2_and_damage():
    data = asset_entry(GUID_A, "Bitmap", "a.jpg", None) + asset_entry(GUID_B, "Bitmap", "b.png", None)
    entries, warnings = parse_asset_metadata(data, 2)
    assert [e.path for e in entries] == ["a.jpg", "b.png"] and warnings == []
    entries, warnings = parse_asset_metadata(data[:-5], 2)
    assert [e.path for e in entries] == ["a.jpg"] and len(warnings) == 1
    entries, warnings = parse_asset_metadata(data + b"\x01\x02", 2)
    assert len(entries) == 2 and "trailing" in warnings[0]


def test_asset_stream_found_by_name():
    b = Builder()
    b.add("standard", mtl_header("M"))
    data = asset_entry(GUID_A, "Bitmap", "x.tga", None)
    with _open(b, data, "FileAssetMetaData2") as mf:
        assert mf.asset_metadata.stream == "FileAssetMetaData2"
        assert mf.asset_metadata.entries[0].path == "x.tga"
    with _open(b) as mf:
        assert mf.asset_metadata.stream is None and mf.asset_metadata.entries == []


# -----------------------------------------------------------------------------
# Maps

def test_bitmap_path_and_placement():
    b = Builder()
    bmp = b.bitmap("Wood map", GUID_A, channel=2, tiling=(4.0, 2.0), offset=(0.25, 0.0))
    empty = b.bitmap("Empty")
    assets = asset_entry(GUID_A, "Bitmap", "maps\\wood.jpg", "D:\\p\\maps\\wood.jpg")
    with _open(b, assets) as mf:
        m = mf.scene.decode(mf.objects[bmp])
        assert isinstance(m, MapData)
        assert (m.class_name, m.name, m.source_class) == ("Bitmaptexture", "Wood map", "Bitmap")
        assert (m.path, m.resolved_path, m.path_source) == ("maps\\wood.jpg", "D:\\p\\maps\\wood.jpg", "asset:filename")
        assert m.asset_guid == str(GUID_A) and m.asset_index == 0
        p = m.params
        assert (p["map_channel"], p["u_tiling"], p["v_tiling"], p["u_offset"]) == (2, 4.0, 2.0, 0.25)
        assert p["w_angle"] == 0.5 and p["u_tile"] and p["v_tile"] and p["environment"] is False
        e = mf.scene.decode(mf.objects[empty])
        assert e.path is None and e.path_source is None


def test_bitmap_asset_missing_warns():
    b = Builder()
    bmp = b.bitmap("Lost", GUID_B)
    with _open(b, asset_entry(GUID_A, "Bitmap", "a.jpg")) as mf:
        m = mf.scene.decode(mf.objects[bmp])
        assert m.path is None and m.asset_guid == str(GUID_B)
        assert any("not in the asset metadata" in w for w in mf.warnings)


def test_checker_sub_maps():
    b = Builder()
    inner = b.bitmap("Inner", GUID_A)
    uv = b.add("uvgen", refs_ordered(b.old_pb({2: 3.0})))
    pb = b.pb2(pb2_param(1, "rgb", (1.0, 0.0, 0.0)), pb2_param(2, "rgb", (0.0, 0.0, 1.0)),
               pb2_param(3, "texmap", inner, inline_ref=True), pb2_param(4, "texmap", None, inline_ref=True))
    checker = b.add("checker", mtl_header("Check"), refs_ordered(uv, pb))
    with _open(b, asset_entry(GUID_A, "Bitmap", "in.png")) as mf:
        m = read_map(mf.objects[checker], mf.scene.context)
        assert m.class_name == "Checker" and m.params["color1"] == (1.0, 0.0, 0.0)
        assert m.params["map1"].path == "in.png" and "map2" not in m.params
        assert [s.index for s in m.sub_maps] == [inner] and m.params["u_tiling"] == 3.0


# -----------------------------------------------------------------------------
# Materials

def _standard(b, shader_key="blinn", maps=None, enabled=0, amounts=None):
    shader_pb = b.pb2(pb2_param(0, "rgb", (0.1, 0.1, 0.1)), pb2_param(1, "rgb", (0.8, 0.2, 0.1)),
                      pb2_param(2, "rgb", (0.9, 0.9, 0.9)), pb2_param(4, "bool", False),
                      pb2_param(6, "bool", False), pb2_param(7, "percent", 0.0),
                      pb2_param(9, "percent", 0.45), pb2_param(10, "percent", 0.3), pb2_param(11, "float", 0.1))
    shader = b.add(shader_key, refs_ordered(shader_pb))
    basics = b.pb2(pb2_param(0, "int", 1), pb2_param(1, "bool", False), pb2_param(2, "bool", True))
    extended = b.pb2(pb2_param(1, "percent", 0.5), pb2_param(2, "rgb", (0.5, 0.5, 0.5)), pb2_param(6, "float", 1.5))
    tex_children = [leaf(0x5003, u32(enabled))]
    for i, amount in (amounts or {}).items():
        tex_children.append(leaf(0x5100 + i, f32(amount)))
    if maps:
        tex_children.insert(0, refs_sparse({2 * i + 1: index for i, index in maps.items()}))
    texmaps = b.add("texmaps", *tex_children)
    return b.add("standard", mtl_header("Brick"), refs_ordered(NULL, texmaps, shader, basics, extended))


def test_standard_material():
    b = Builder()
    diffuse = b.bitmap("D", GUID_A)
    bump = b.bitmap("B", GUID_B)
    other = b.bitmap("O")
    mat = _standard(b, maps={1: diffuse, 8: bump, 20: other}, enabled=(1 << 1) | (1 << 20), amounts={8: 0.3})
    assets = asset_entry(GUID_A, "Bitmap", "brick.jpg") + asset_entry(GUID_B, "Bitmap", "brick_bump.jpg")
    with _open(b, assets) as mf:
        m = mf.scene.decode(mf.objects[mat])
        assert isinstance(m, MaterialData)
        assert (m.class_name, m.name, m.source_class) == ("Standardmaterial", "Brick", "Standard")
        p = m.params
        assert p["shader"] == "Blinn" and p["diffuse"] == pytest.approx((0.8, 0.2, 0.1))
        assert p["ambient"] == pytest.approx((0.1, 0.1, 0.1)) and p["specular"] == pytest.approx((0.9, 0.9, 0.9))
        assert p["specular_level"] == pytest.approx(45.0) and p["glossiness"] == pytest.approx(30.0)
        assert p["soften"] == pytest.approx(0.1) and p["self_illum_amount"] == 0.0
        assert p["opacity"] == pytest.approx(50.0) and p["ior"] == pytest.approx(1.5)
        assert p["two_sided"] is True and p["wire"] is False
        assert m.maps["diffuse_map"].path == "brick.jpg" and p["diffuse_map_on"] is True
        assert p["diffuse_map_amount"] == 1.0
        assert m.maps["bump_map"].path == "brick_bump.jpg" and p["bump_map_on"] is False
        assert p["bump_map_amount"] == pytest.approx(0.3)
        assert list(m.unassigned_maps) == [20] and m.sub_materials is None and m.sub_ids is None


def test_standard_shader_map_layout():
    b = Builder()
    bump = b.bitmap("B")
    mat = _standard(b, "anisotropic", maps={8: bump, 11: bump})
    with _open(b) as mf:
        m = mf.scene.decode(mf.objects[mat])
        assert m.params["shader"] == "Anisotropic"
        assert m.maps["bump_map"].index == bump and list(m.unassigned_maps) == [8]


def test_multi_sub_object():
    b = Builder()
    red = _standard(b)
    green = b.add("physical", cont(0x0100, leaf(0x4001, text("Green")), leaf(0x4003, u32(0x200))),
                  refs_ordered(b.pb2(pb2_param(2, "rgba", (0.0, 1.0, 0.0, 1.0)))))
    pb = b.pb2(pb2_param(0, "material", [None, None], table=True, inline_ref=True),
               pb2_param(1, "bool", [True, False], table=True),
               pb2_param(2, "string", ["", "grass"], table=True),
               pb2_param(3, "int", [0, 4], table=True))
    multi = b.add("multi", mtl_header("Ground"), refs_ordered(pb, red, green), leaf(0x4002, u32(2)))
    with _open(b) as mf:
        m = mf.scene.decode(mf.objects[multi])
        assert (m.class_name, m.name) == ("Multimaterial", "Ground")
        assert [s.name for s in m.sub_materials] == ["Brick", "Green"]
        assert m.sub_ids == [1, 5] and m.sub_names == [None, "grass"]
        assert m.params["sub_enabled"] == [True, False]
        assert m.sub_materials[1].params["base_color"] == (0.0, 1.0, 0.0)


def test_physical_material():
    b = Builder()
    bmp = b.bitmap("Color", GUID_A)
    pb = b.pb2(pb2_param(1, "float", 0.9), pb2_param(2, "rgba", (0.2, 0.3, 0.4, 1.0)),
               pb2_param(4, "float", 0.8), pb2_param(5, "bool", True), pb2_param(6, "float", 1.0),
               pb2_param(30, "float", 0.5), pb2_param(33, "float", 1.33), pb2_param(52, "float", 1500.0),
               pb2_param(101, "texmap", bmp, inline_ref=True), pb2_param(151, "bool", True),
               pb2_param(130, "texmap", None, inline_ref=True), pb2_param(230, "float", 0.3))
    mat = b.add("physical", cont(0x0100, leaf(0x4001, text("Chrome")), leaf(0x4003, u32(0x200))), refs_ordered(pb))
    with _open(b, asset_entry(GUID_A, "Bitmap", "c.png")) as mf:
        m = mf.scene.decode(mf.objects[mat])
        assert (m.class_name, m.name) == ("PhysicalMaterial", "Chrome")
        p = m.params
        assert p["base_color"] == pytest.approx((0.2, 0.3, 0.4)) and p["base_weight"] == pytest.approx(0.9)
        assert p["roughness"] == pytest.approx(0.8) and p["roughness_inv"] is True and p["metalness"] == 1.0
        assert p["transparency"] == 0.5 and p["trans_ior"] == pytest.approx(1.33)
        assert p["bump_map_amt"] == pytest.approx(0.3) and p["emit_luminance"] == 1500.0
        assert m.maps["base_color_map"].path == "c.png" and p["base_color_map_on"] is True
        assert "bump_map" not in m.maps


def test_arnold_standard_surface():
    b = Builder()
    bmp = b.bitmap("Tex")
    members = [
        b.ai_param("base", 0, f32(0.9)),
        b.ai_param("base_color", 2, f32(0.1, 0.2, 0.3)),
        b.ai_param("base_color.connected", 4, u32(1)),
        b.ai_param("base_color.shader", 15, u32(NULL), refs=[bmp]),
        b.ai_param("specular_IOR", 0, f32(1.6)),
        b.ai_param("thin_walled", 4, u32(0)),
    ]
    groups = [b.ai_group("results", []), b.ai_group("parameters", members), b.ai_group("connections", [])]
    pb = b.pb2(pb2_param(0, "reference", groups, table=True, inline_ref=True))
    mat = b.add("arnold", cont(0x0100, leaf(0x4001, text("Skin")), leaf(0x4003, u32(0x200))), refs_ordered(pb))
    with _open(b) as mf:
        m = mf.scene.decode(mf.objects[mat])
        assert (m.class_name, m.name) == ("ai_standard_surface", "Skin")
        p = m.params
        assert p["base"] == pytest.approx(0.9) and p["base_color"] == pytest.approx((0.1, 0.2, 0.3))
        assert p["specular_ior"] == pytest.approx(1.6) and p["thin_walled"] is False
        assert m.maps["base_color_shader"].index == bmp and p["base_color_shader_on"] is True
        assert "base_color_connected" not in p


def test_blend_components():
    b = Builder()
    first, second = _standard(b), _standard(b)
    mask = b.bitmap("Mask")
    pb = b.pb2(pb2_param(0, "percent", 0.25))
    blend = b.add("blend", mtl_header("Mixed"), refs_ordered(pb, first, second, mask))
    with _open(b) as mf:
        m = mf.scene.decode(mf.objects[blend])
        assert m.class_name == "Blend" and m.sub_materials is None
        assert [c.index for c in m.components] == [first, second]
        assert m.params["mix_amount"] == 0.25 and m.maps["mask_map"].index == mask


def test_object_name_rules():
    b = Builder()
    plain = b.add("standard", mtl_header("A"))
    newer = b.add("physical", cont(0x0100, leaf(0x4001, text("B")), leaf(0x4003, u32(0))))
    scripted = b.add("standard", leaf(0x4001, text("C")), leaf(0x4003, u32(0)))
    unnamed = b.add("standard", mtl_header(""))
    nothing = b.add("standard", cont(0x4000, leaf(0x4003, u32(0))))
    with _open(b) as mf:
        names = [object_name(mf.objects[i]) for i in (plain, newer, scripted, unnamed, nothing)]
        assert names == ["A", "B", "C", None, None]


# -----------------------------------------------------------------------------
# Corpus

def _materials(mf):
    return {o.index: mf.scene.decode(o) for o in mf.objects if o.superclass_id == 0xC00}


def test_corpus_palm_tree_standard_maps():
    """A Max 2008-era file (FileAssetMetaData2): Phong materials with diffuse / opacity / bump bitmaps."""
    path = corpus_file("Scenes/MarlinStudios/PalmTree002_Var02/PalmTree002_Var02.max")
    with maxfile.open(path) as mf:
        mats = {m.name: m for m in _materials(mf).values() if m is not None}
        frond = mats["FanFrond02"]
        assert frond.class_name == "Standardmaterial" and frond.params["shader"] == "Phong"
        assert frond.params["glossiness"] == pytest.approx(20.0)
        assert frond.maps["diffuse_map"].path == "PalmLeaf001_Diffuse.jpg"
        assert frond.maps["opacity_map"].path == "PalmLeaf001_Alpha.jpg"
        assert frond.maps["bump_map"].path == "PalmLeaf001_Bump.jpg"
        assert frond.maps["specular_map"].path == "PalmLeaf001_Specular.jpg"
        assert mats["Trunk"].maps["bump_map"].path == "PalmBark003_Bump.jpg"


def test_corpus_lava_standard_texmaps():
    """Texmaps object: enabled bits and amounts (bump present but switched off, amount 30)."""
    path = corpus_file("Maps and Materials/maps/Organics/LavaFlowSlateShader/lavaFlowShader.max")
    with maxfile.open(path) as mf:
        m = mf.scene.decode(mf.objects[115])
        assert m.name == "01 - Default" and m.maps["diffuse_map"].name == "ColorMask"
        assert m.params["bump_map_on"] is False and m.params["bump_map_amount"] == pytest.approx(0.3)
        assert m.params["self_illum_map_on"] is True and m.params["glossiness"] == pytest.approx(19.0)


def test_corpus_bitmap_asset_paths():
    """FileAssetMetaData3: the stored (relative) path and the absolute one it last resolved to."""
    path = corpus_file("Scenes/SubDivSurfaces/HSDS-Dolphin.max")
    with maxfile.open(path) as mf:
        m = mf.scene.decode(mf.objects[12])
        assert m.class_name == "Bitmaptexture" and m.path == "Scenes\\SubDivSurfaces\\Flipper.jpg"
        assert m.resolved_path.endswith("\\Scenes\\SubDivSurfaces\\Flipper.jpg")
        assert m.path_source == "asset:filename" and m.params["map_channel"] == 1


def test_corpus_multi_sub_arnold():
    path = corpus_file("Scenes/Lighting/Lighting-CB_Arnold_SSurface.max")
    with maxfile.open(path) as mf:
        multi = mf.scene.decode(mf.objects[849])
        assert (multi.class_name, multi.name) == ("Multimaterial", "Cornell Box")
        assert multi.sub_ids == [1, 2, 3, 4, 5, 6]
        assert multi.sub_names == [None, "bottom", "Left", "Right", None, None]
        assert [s.index for s in multi.sub_materials] == [346, 346, 597, 848, 346, 346]
        green = multi.sub_materials[2]
        assert green.class_name == "ai_standard_surface"
        assert green.params["base_color"] == pytest.approx((0.0784, 0.8, 0.0784), abs=1e-3)
        assert green.maps["normal_shader"].class_name == "Bump 2D"


def test_corpus_physical_material():
    path = corpus_file("Scenes/PolygonObject/gargoile.max")
    with maxfile.open(path) as mf:
        m = mf.scene.decode(mf.objects[62])
        assert (m.class_name, m.name) == ("PhysicalMaterial", "Standard_1")
        assert m.params["roughness"] == pytest.approx(0.1) and m.params["roughness_inv"] is True
        assert m.params["base_color"] == pytest.approx((0.588, 0.588, 0.588), abs=1e-3)


def _check_file(path):
    """Invariants for every material and map of one file."""
    with maxfile.open(path) as mf:
        ctx = mf.scene.context
        for obj in mf.objects:
            if obj.superclass_id == 0xC00:
                m = mf.scene.decode(obj)
                if m is None:
                    continue
                if m.class_name == "Multimaterial":
                    assert len(m.sub_ids) == len(m.sub_materials) == len(m.sub_names or m.sub_ids), path
                    assert len(set(m.sub_ids)) == len(m.sub_ids) and min(m.sub_ids or [1]) >= 1, path
            elif obj.superclass_id == 0xC10 and obj.class_label() == "Bitmap":
                m = read_map(obj, ctx)
                if m.asset_guid is not None:
                    assert m.path, (path, obj.index)
                assert m.params.get("map_channel", 1) >= 1


@pytest.mark.parametrize("path", sample(10) if all_files() else [None])
def test_corpus_sample_invariants(path):
    if path is None:
        pytest.skip("no corpus")
    _check_file(path)


def test_corpus_all_invariants():
    if not all_files():
        pytest.skip("no corpus")
    if not full_corpus_enabled():
        pytest.skip("set MX_FULL_CORPUS=1")
    for path in all_files():
        _check_file(path)
