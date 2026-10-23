# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Round trip of the experimental writer: model -> ``maxfile.writer`` -> ``maxfile.open`` -> decoded data equals the
model. No corpus needed (``test_writer_corpus.py`` compares the written structure with real files).
"""

import math
import struct

import pytest

import maxfile
from maxfile import container
from maxfile.objects.geometry import MeshData
from maxfile.writer import (
    Bitmap, EditablePoly, MapChannel, MultiSubMaterial, Node, PhysicalMaterial, Scene, StandardMaterial, Transform,
    WriterOptions, to_bytes, write,
)
from maxfile.writer import cfb, poly

STREAMS = {"\x05DocumentSummaryInformation", "\x05SummaryInformation", "ClassData", "ClassDirectory3", "Config",
           "DllDirectory", "FileAssetMetaData3", "SaveConfigData", "Scene", "ScriptedCustAttribDefs",
           "VideoPostQueue"}


def box_mesh(size=10.0, **kwargs):
    h = size / 2.0
    pos = [(-h, -h, 0), (h, -h, 0), (-h, h, 0), (h, h, 0), (-h, -h, size), (h, -h, size), (-h, h, size), (h, h, size)]
    polys = [[0, 2, 3, 1], [4, 5, 7, 6], [0, 1, 5, 4], [1, 3, 7, 5], [3, 2, 6, 7], [2, 0, 4, 6]]
    return EditablePoly(pos, polys, **kwargs)


def open_bytes(data):
    return maxfile.open(data)


def quat_equal(a, b, eps=1e-5):
    dot = abs(sum(x * y for x, y in zip(a, b)))
    return abs(dot - 1.0) < eps


# -----------------------------------------------------------------------------
# Container

def test_cfb_round_trip_small_and_large_streams():
    payloads = [("Small", b"abc"), ("Empty", b""), ("Exact", b"x" * 4096), ("Big", bytes(range(256)) * 100),
                ("Storage/Inner", b"inner"), ("Mini2", b"y" * 4095), ("Huge", b"z" * (5 * 1024 * 1024 + 7))]
    data = cfb.write_compound_file(payloads)
    cf = container.CompoundFile(data)
    assert cf.version == 4 and cf.sector_size == 4096
    assert not cf.warnings
    for name, payload in payloads:
        assert cf.read_stream(name) == payload


def test_cfb_root_clsid_and_tree_colours():
    data = cfb.write_compound_file([("S{:02d}".format(i), b"d") for i in range(11)])
    # Root entry (directory sector 0 of this layout, entry 0): CLSID at offset 80.
    header = struct.unpack_from("<8s16sHHHHH6sIIIIIIIII", data, 0)
    first_dir = header[10]
    root = data[(first_dir + 1) * 4096:(first_dir + 1) * 4096 + 128]
    assert root[80:96] == cfb.MAX_ROOT_CLSID.bytes_le
    # Red-black rules on the root storage's children: every path to a leaf has the same black count, no red node
    # has a red child.
    entries = []
    for i in range(12):
        e = data[(first_dir + 1) * 4096 + 128 * i:(first_dir + 1) * 4096 + 128 * (i + 1)]
        _name, _nl, _t, color, left, right, child = struct.unpack_from("<64sHBBIII", e)
        entries.append((color, left, right, child))

    def black_heights(eid, parent_red=False):
        if eid == cfb.NOSTREAM:
            return {0}
        color, left, right, _ = entries[eid]
        red = color == 0
        assert not (red and parent_red)
        heights = black_heights(left, red) | black_heights(right, red)
        return {h + (0 if red else 1) for h in heights}

    assert len(black_heights(entries[0][3])) == 1


# -----------------------------------------------------------------------------
# File structure

def test_empty_scene_structure():
    data = to_bytes(Scene())
    with open_bytes(data) as mf:
        assert {e.path_str for e in mf.streams} == STREAMS
        assert mf.container.version == 4
        assert mf.max_release == 16900
        assert mf.dll_directory.header == 0x4204019B
        assert mf.warnings == []
        assert mf.nodes == []
        objs = mf.scene.objects
        top = objs[-1]
        assert top.class_label() == "Scene"
        assert [objs[i].class_label() for _, i in sorted(top.references.items())] == [
            "Material Editor", "MtlBaseLib", "Default Sound", "RootNode", "RenderEnvironment", "NamedSelSetList",
            "TVNode", "Grid Reference", "RenderEffects", "Shadow Map", "Layer Manager", "TrackSetList",
            "PersistentIsolationData"]
        assert mf.stream("Scene").chunks[0].type == 0x2020
        # Children before parents: every reference points to a lower index.
        for obj in objs:
            assert all(index < obj.index for index in obj.references.values())
        # The 24 default sample-slot materials.
        names = [mf.scene.decode(o).name for o in objs if o.class_label() == "Standard"]
        assert names == ["{:02d} - Default".format(i) for i in range(1, 25)]
        save = {c.type: c.data for c in mf.stream("SaveConfigData").chunks}
        assert struct.unpack("<I", save[0x2170])[0] == 0x4204019B and struct.unpack("<I", save[0x2173])[0] == 16900


def test_lean_skeleton():
    data = to_bytes(Scene(), WriterOptions(skeleton="lean"))
    with open_bytes(data) as mf:
        assert mf.warnings == []
        assert not [o for o in mf.scene.objects if o.class_label() == "Standard"]
        top = mf.scene.objects[-1]
        assert len(top.references) == 13


def test_deterministic(tmp_path):
    scene = Scene(nodes=[Node("Box001", mesh=box_mesh(), material=StandardMaterial(
        "M", diffuse_map=Bitmap("C:\\maps\\a.jpg")))])
    a = to_bytes(scene)
    path = tmp_path / "x.max"
    write(scene, path)
    assert a == path.read_bytes()
    assert a == to_bytes(scene)


# -----------------------------------------------------------------------------
# Nodes and transforms

def test_hierarchy_and_transforms():
    scene = Scene()
    angle = math.radians(30)
    rot = (math.cos(angle / 2), 0.0, 0.0, math.sin(angle / 2))      # 30 degrees about Z
    q2 = (0.5, 0.5, -0.5, 0.5)
    parent = scene.add(Node("Parent", mesh=box_mesh(), transform=Transform((10, 20, 30), rot, (1, 2, 3)),
                            wire_color=(255, 0, 128)))
    child = scene.add(Node("Child", parent=parent, mesh=box_mesh(5), transform=Transform((0, 0, 40), q2)))
    scene.add(Node("Grandchild", parent=child, mesh=None, hidden=True, frozen=True))
    with open_bytes(to_bytes(scene)) as mf:
        assert mf.warnings == []
        by_name = {n.name: n for n in mf.nodes}
        p, c, g = by_name["Parent"], by_name["Child"], by_name["Grandchild"]
        assert p.parent is None and c.parent is p and g.parent is c
        assert p.transform.position == pytest.approx((10, 20, 30))
        assert quat_equal(p.transform.rotation, rot)
        assert p.transform.scale == pytest.approx((1, 2, 3))
        assert quat_equal(c.transform.rotation, q2)
        assert p.wire_color == (255, 0, 128)
        assert g.is_hidden and g.is_frozen and not p.is_hidden and not p.is_frozen
        assert g.object.class_label() == "Dummy"
        # World matrix composes parent @ T @ R @ S (overview.md §4.1).
        world = c.world_matrix()
        assert world[2][3] == pytest.approx(30 + 3 * 40)


def test_quaternion_convention_matches_reader():
    # The file stores x, y, z, w of the inverse rotation; reading it back gives the model's rotation.
    for q in [(1, 0, 0, 0), (0.7071068, 0.7071068, 0, 0), (0.5, -0.5, 0.5, 0.5), (0.0, 0.0, 1.0, 0.0)]:
        scene = Scene(nodes=[Node("N", mesh=box_mesh(), transform=Transform(rotation=q))])
        with open_bytes(to_bytes(scene)) as mf:
            assert quat_equal(mf.nodes[0].transform.rotation, q)


def test_object_offset():
    off = Transform((1, 2, 3), (0.7071068, 0, 0.7071068, 0), (2, 2, 2))
    scene = Scene(nodes=[Node("N", mesh=box_mesh(), object_offset=off)])
    with open_bytes(to_bytes(scene)) as mf:
        o = mf.nodes[0].object_offset
        assert o.position == pytest.approx((1, 2, 3))
        assert quat_equal(o.rotation, off.rotation)
        assert o.scale == pytest.approx((2, 2, 2))


@pytest.mark.parametrize("unit, code", [("inches", 0), ("feet", 1), ("millimeters", 3), ("centimeters", 4),
                                        ("meters", 5)])
def test_units(unit, code):
    with open_bytes(to_bytes(Scene(unit=unit))) as mf:
        assert mf.units.code == code and mf.units.unit == unit and mf.units.scale == 1.0


def test_bad_unit():
    with pytest.raises(ValueError):
        to_bytes(Scene(unit="cubits"))


# -----------------------------------------------------------------------------
# Geometry

def test_geometry_round_trip():
    positions = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0.5, 2, 0), (2, 0.5, 0), (2, 2, 1)]
    polygons = [[0, 1, 2, 3], [3, 2, 4], [1, 5, 6, 4, 2]]
    uv = MapChannel([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0.5, 0.5, 0)],
                    [[0, 1, 2, 3], [3, 2, 4], [0, 1, 2, 3, 4]])
    second = MapChannel([(0.25, 0.75, 0)], [[0, 0, 0, 0], [0, 0, 0], [0, 0, 0, 0, 0]])
    mesh = EditablePoly(positions, polygons, material_ids=[1, 3, 7], smoothing_groups=[1, 0, 0x80000001],
                        map_channels={1: uv, 2: second})
    with open_bytes(to_bytes(Scene(nodes=[Node("Poly", mesh=mesh)]))) as mf:
        data = mf.scene.decode(mf.nodes[0].object)
        assert isinstance(data, MeshData) and data.warnings == []
        assert data.positions == pytest.approx(positions)
        assert [list(f) for f in data.faces] == polygons
        assert data.material_ids == [1, 3, 7]
        assert data.smoothing_groups == [1, 0, 0x80000001]
        assert sorted(data.map_channels) == [1, 2]
        assert [list(f) for f in data.map_channels[1].faces] == uv.faces
        assert data.map_channels[1].vertices == pytest.approx(uv.vertices)
        assert data.map_channels[2].vertices == pytest.approx(second.vertices)


def test_default_material_ids_and_no_smoothing():
    with open_bytes(to_bytes(Scene(nodes=[Node("Box", mesh=box_mesh())]))) as mf:
        data = mf.scene.decode(mf.nodes[0].object)
        assert data.material_ids == [1] * 6
        assert data.smoothing_groups == [0] * 6


def test_instances_share_the_object():
    mesh = box_mesh()
    scene = Scene(nodes=[Node("A", mesh=mesh), Node("B", mesh=mesh), Node("C", mesh=box_mesh())])
    with open_bytes(to_bytes(scene)) as mf:
        a, b, c = mf.nodes
        assert a.object is b.object and a.object is not c.object


def test_derived_edges_and_adjacency_of_a_box():
    box = box_mesh()
    edges = poly.derive_edges(box.polygons)
    assert len(edges) == 12
    assert edges[:4] == [(0, 2), (2, 3), (3, 1), (1, 0)]
    adj = poly.vertex_adjacency(8, edges, box.polygons)
    # Vertex 0: edges 0, 3, 9 and faces 0, 2, 5 (the layout of the corpus boxes).
    assert adj[:8] == [3, 0, 3, 9, 3, 0, 2, 5]
    assert len(adj) == 8 * 8


def test_polygon_validation():
    with pytest.raises(ValueError):
        to_bytes(Scene(nodes=[Node("Bad", mesh=EditablePoly([(0, 0, 0), (1, 0, 0)], [[0, 1]]))]))
    uv = MapChannel([(0, 0, 0)], [[0, 0, 0]])
    with pytest.raises(ValueError):
        to_bytes(Scene(nodes=[Node("Bad", mesh=box_mesh(map_channels={1: uv}))]))


def test_hierarchy_cycle_is_rejected():
    a = Node("A")
    b = Node("B", parent=a)
    a.parent = b
    with pytest.raises(ValueError):
        to_bytes(Scene(nodes=[a, b]))


# -----------------------------------------------------------------------------
# Materials

def test_standard_material_round_trip():
    mat = StandardMaterial("Bricks", diffuse=(0.8, 0.4, 0.2), specular=(1, 1, 1), specular_level=50,
                           glossiness=35, opacity=75, two_sided=True,
                           diffuse_map=Bitmap("C:\\maps\\bricks.jpg", u_tiling=2, v_tiling=3, u_offset=0.25),
                           bump_map=Bitmap("C:\\maps\\bricks_bump.png"), bump_amount=60,
                           opacity_map=Bitmap("maps/alpha.tga"))
    with open_bytes(to_bytes(Scene(nodes=[Node("Wall", mesh=box_mesh(), material=mat)]))) as mf:
        assert mf.warnings == []
        data = mf.scene.decode(mf.nodes[0].material)
        assert data.class_name == "Standardmaterial" and data.name == "Bricks"
        p = data.params
        assert p["diffuse"] == pytest.approx((0.8, 0.4, 0.2))
        assert p["specular"] == pytest.approx((1, 1, 1))
        assert p["specular_level"] == pytest.approx(50)
        assert p["glossiness"] == pytest.approx(35)
        assert p["opacity"] == pytest.approx(75)
        assert p["two_sided"] is True
        assert p["shader"] == "Blinn"
        maps = data.maps
        assert maps["diffuse_map"].path == "C:\\maps\\bricks.jpg"
        assert maps["diffuse_map"].params["u_tiling"] == pytest.approx(2)
        assert maps["diffuse_map"].params["v_tiling"] == pytest.approx(3)
        assert maps["diffuse_map"].params["u_offset"] == pytest.approx(0.25)
        assert maps["bump_map"].path == "C:\\maps\\bricks_bump.png"
        assert p["bump_map_amount"] == pytest.approx(0.6)        # Map amounts are read as stored: fractions.
        assert maps["opacity_map"].path == "maps/alpha.tga"
        assets = mf.asset_metadata
        assert sorted(e.path for e in assets.entries) == ["C:\\maps\\bricks.jpg", "C:\\maps\\bricks_bump.png",
                                                          "maps/alpha.tga"]
        assert all(e.kind == "Bitmap" and e.resolved_path == e.path for e in assets.entries)
        assert not assets.warnings


def test_shared_bitmap_is_one_object_and_one_asset():
    tex = Bitmap("C:\\t\\wood.jpg")
    a = StandardMaterial("A", diffuse_map=tex)
    b = StandardMaterial("B", diffuse_map=tex)
    scene = Scene(nodes=[Node("1", mesh=box_mesh(), material=a), Node("2", mesh=box_mesh(), material=b)])
    with open_bytes(to_bytes(scene)) as mf:
        bitmaps = [o for o in mf.scene.objects if o.class_label() == "Bitmap"]
        assert len(bitmaps) == 1
        assert len(mf.asset_metadata.entries) == 1


def test_multi_sub_material_round_trip():
    red = StandardMaterial("Red", diffuse=(1, 0, 0))
    blue = StandardMaterial("Blue", diffuse=(0, 0, 1))
    multi = MultiSubMaterial("Multi", [red, blue], ids=[1, 5], names=["front", "back"])
    with open_bytes(to_bytes(Scene(nodes=[Node("Box", mesh=box_mesh(material_ids=[1, 5] * 3), material=multi)]))) \
            as mf:
        data = mf.scene.decode(mf.nodes[0].material)
        assert data.class_name == "Multimaterial" and data.name == "Multi"
        assert data.sub_ids == [1, 5]
        assert data.sub_names == ["front", "back"]
        subs = data.sub_materials
        assert [s.name for s in subs] == ["Red", "Blue"]
        assert subs[1].params["diffuse"] == pytest.approx((0, 0, 1))
        lib = [o for o in mf.scene.objects if o.class_label() == "MtlBaseLib"][0]
        assert len(lib.references) == 1


def test_physical_material_round_trip():
    mat = PhysicalMaterial("Metal", base_color=(0.9, 0.8, 0.1), roughness=0.25, metalness=1.0, transparency=0.5,
                           base_color_map=Bitmap("C:\\t\\albedo.png"), roughness_map=Bitmap("C:\\t\\rough.png"),
                           bump_map=Bitmap("C:\\t\\normal.png"), cutout_map=Bitmap("C:\\t\\mask.png"))
    with open_bytes(to_bytes(Scene(nodes=[Node("Ball", mesh=box_mesh(), material=mat)]))) as mf:
        assert mf.warnings == []
        data = mf.scene.decode(mf.nodes[0].material)
        assert data.class_name == "PhysicalMaterial" and data.name == "Metal"
        assert data.params["base_color"] == pytest.approx((0.9, 0.8, 0.1))
        assert data.params["roughness"] == pytest.approx(0.25)
        assert data.params["metalness"] == pytest.approx(1.0)
        assert data.params["transparency"] == pytest.approx(0.5)
        assert {k: v.path for k, v in data.maps.items()} == {
            "base_color_map": "C:\\t\\albedo.png", "roughness_map": "C:\\t\\rough.png",
            "bump_map": "C:\\t\\normal.png", "cutout_map": "C:\\t\\mask.png"}


def test_summary_information_lists_the_scene():
    scene = Scene(nodes=[Node("Box001", mesh=box_mesh(), material=StandardMaterial("Mat A"))])
    with open_bytes(to_bytes(scene)) as mf:
        raw = mf.raw_stream("\x05DocumentSummaryInformation")
    text = raw.decode("latin-1")
    for expected in ("3ds Max Version: 16.90", "Saved As Version: 16.90", "Vertices: 8", "Faces: 12", "Box001",
                     "Mat A", "epoly.dlo"):
        assert expected in text
