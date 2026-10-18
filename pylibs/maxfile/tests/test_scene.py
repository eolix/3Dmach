# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Scene stream tests: object list, references, nodes, hierarchy, and maxfile.open().

The fixtures follow the *documented, unverified* layouts of ``docs/format/overview.md`` §3-4 (built by
``synth_max``); they test our parser against those assumptions, not the assumptions themselves.
"""

import random
import struct

import pytest

import maxfile
from cfb_writer import build_cfb
from maxfile.classes import ClassID
from synth_max import NULL, SceneBuilder, cont, f32, leaf, refs_ordered, refs_sparse, text, u32


def _basic():
    b = SceneBuilder()
    c = {
        "node": b.cls("Node", (1, 0), 1),
        "box": b.cls("Box", (0x10, 0), 0x10),
        "mat": b.cls("Standard", (0x2, 0), 0xC00),
        "layer": b.cls("Layer", (0x7E57, 0x7E57), 0x7E5),
    }
    return b, c


def test_object_list_and_classes():
    b, c = _basic()
    box = b.obj(c["box"], leaf(0x1234, b"\x01"))
    weird = b.obj(99)   # Class index outside the directory.
    with maxfile.open(b.build()) as mf:
        objects = mf.objects
        assert [o.index for o in objects] == [box, weird]
        assert objects[box].cls.name == "Box" and objects[box].class_id == ClassID(0x10)
        assert objects[box].class_label() == "Box"
        assert objects[weird].cls is None and objects[weird].class_label() == "#99"
        assert any("outside the class directory" in w for w in mf.warnings)
        assert mf.scene.class_counts()[c["box"]] == 1


def test_references_ordered_and_sparse():
    b, c = _basic()
    targets = [b.obj(c["box"]) for _ in range(4)]
    ordered = b.obj(c["box"], refs_ordered(targets[0], NULL, targets[2]))
    sparse = b.obj(c["box"], refs_sparse({0: targets[1], 5: targets[3], 7: NULL}))
    out_of_range = b.obj(c["box"], refs_ordered(targets[0], 5000))
    with maxfile.open(b.build()) as mf:
        objs = mf.objects
        assert objs[ordered].references == {0: targets[0], 2: targets[2]}
        assert objs[sparse].references == {0: targets[1], 5: targets[3]}
        assert objs[out_of_range].references == {0: targets[0]}
        assert mf.scene.ref(objs[sparse], 5) is objs[targets[3]]
        assert mf.scene.ref(objs[sparse], 1) is None
        assert any("outside the object list" in w for w in mf.warnings)


def test_malformed_reference_chunks():
    b, c = _basic()
    t = b.obj(c["box"])
    odd = b.obj(c["box"], leaf(0x2034, u32(t) + b"\x01"))
    short_sparse = b.obj(c["box"], leaf(0x2035, u32(0, 0)))
    with maxfile.open(b.build()) as mf:
        assert mf.objects[odd].references == {0: t}
        assert mf.objects[short_sparse].references == {}
        assert any("multiple of 4" in w for w in mf.warnings)
        assert any("4 + 8n" in w for w in mf.warnings)


def test_nodes_and_hierarchy():
    b, c = _basic()
    mat = b.obj(c["mat"])
    layer = b.obj(c["layer"])
    geo = b.obj(c["box"])
    root = b.node(c["node"], "Root")
    parent = b.node(c["node"], "Parent", parent=root, refs=[NULL, geo, NULL, mat, NULL, NULL, layer],
                    offset_pos=(1, 2, 3), offset_rot=(1, 0, 0, 0), offset_scale=(2, 2, 2))
    child_a = b.node(c["node"], "ChildA", parent=parent, refs=[NULL, geo])
    child_b = b.node(c["node"], "ChildB", parent=parent)
    with maxfile.open(b.build()) as mf:
        scene = mf.scene
        assert [n.name for n in mf.nodes] == ["Root", "Parent", "ChildA", "ChildB"]
        assert [n.name for n in scene.roots] == ["Root"]
        p = scene.node(parent)
        assert p.parent is scene.node(root) and p.parent_index == root
        assert [n.index for n in p.children] == [child_a, child_b]
        assert p.object is mf.objects[geo] and p.material is mf.objects[mat] and p.layer is mf.objects[layer]
        assert p.controller is None and p.transform is None
        # Instancing: two nodes reference the same object index.
        assert scene.node(child_a).object is p.object
        assert p.object_offset.position == (1.0, 2.0, 3.0)
        assert p.object_offset.rotation == (1.0, 0.0, 0.0, 0.0)
        assert p.object_offset.scale == (2.0, 2.0, 2.0)
        assert scene.node(child_b).object_offset.is_empty()
        assert scene.node(geo) is None
        assert mf.warnings == []


def test_node_needs_node_class():
    # Verified (overview.md §4): nodes are exactly the objects of class 0x1 / superclass 0x1; a parent chunk alone
    # doesn't make one.
    b, c = _basic()
    other = b.cls("SomethingElse", (0x7777, 0), 0x1)
    root = b.node(c["node"], "Root")
    n = b.obj(other, leaf(0x0960, u32(root)), leaf(0x0962, text("ByParent")))
    with maxfile.open(b.build()) as mf:
        assert mf.scene.node(n) is None and mf.scene.node(root) is not None


def test_node_flags_and_wire_color():
    b, c = _basic()
    n = b.obj(c["node"], leaf(0x0960, u32(NULL, (1 << 14) | (1 << 8))), leaf(0x0962, text("Spot01.Target")),
              leaf(0x0974, bytes((88, 177, 27, 0))))
    with maxfile.open(b.build()) as mf:
        node = mf.scene.node(n)
        assert node.is_target and node.is_group_member and not node.is_group_head
        assert node.wire_color == (88, 177, 27)


def test_derived_object_pseudo_class():
    # Verified: chunk types 0x2032 / 0x2033 beyond the class directory are classes of their own.
    b, c = _basic()
    d = b.obj(0x2032)
    with maxfile.open(b.build()) as mf:
        obj = mf.objects[d]
        assert obj.cls is not None and obj.class_label() == "Derived Object"
        assert not any("outside the class directory" in w for w in mf.warnings)


def test_node_class_requires_superclass():
    b, _ = _basic()
    fake = b.cls("FakeNode", (1, 0), 2)
    obj = b.obj(fake, leaf(0x0962, text("X")))
    with maxfile.open(b.build()) as mf:
        assert mf.scene.node(obj) is None


def test_parent_not_a_node_or_out_of_range():
    b, c = _basic()
    geo = b.obj(c["box"])
    a = b.node(c["node"], "A", parent=geo)
    z = b.node(c["node"], "Z", parent=123456)
    with maxfile.open(b.build()) as mf:
        scene = mf.scene
        assert scene.node(a).parent is None and scene.node(a).parent_index == geo
        assert scene.node(z).parent is None and scene.node(z).parent_index == 123456
        assert len(scene.roots) == 2


def test_parent_cycles_are_broken():
    b, c = _basic()
    # 0 -> 1 -> 2 -> 0, and 3 -> 3.
    for i, parent in enumerate([1, 2, 0, 3]):
        b.node(c["node"], "N{:d}".format(i), parent=parent)
    with maxfile.open(b.build()) as mf:
        scene = mf.scene
        for node in scene.nodes:
            seen = set()
            while node is not None:
                assert node.index not in seen
                seen.add(node.index)
                node = node.parent
        assert len(scene.roots) == 2
        assert any("form a cycle" in w for w in mf.warnings)
        assert any("own parent" in w for w in mf.warnings)
        for node in scene.nodes:
            node.world_matrix()     # Terminates.


def test_short_node_chunks():
    b, c = _basic()
    n = b.obj(c["node"], leaf(0x0960, b"\x01"), leaf(0x096A, f32(1.0)), leaf(0x0962, text("Short")))
    with maxfile.open(b.build()) as mf:
        node = mf.scene.node(n)
        assert node.parent_index is None and node.object_offset.position is None
        assert any("shorter than 4 bytes" in w for w in mf.warnings)
        assert any("0x096A shorter than 3 floats" in w for w in mf.warnings)


def test_damaged_object_chunk_is_reported():
    b, c = _basic()
    good = b.node(c["node"], "Good")
    b.objects.append(leaf(c["node"]))  # A leaf object: no children at all.
    # A container whose second child claims 0xFFFF0000 bytes.
    payload = leaf(0x0962, text("Broken")) + b"\x01\x00\x00\x00\xFF\x7F"
    b.objects.append(struct.pack("<HI", c["node"], (len(payload) + 6) | 0x80000000) + payload)
    with maxfile.open(b.build()) as mf:
        assert mf.scene.node(good).name == "Good"
        assert len(mf.objects) == 3
        assert any("chunk tree damaged" in w for w in mf.warnings)


def test_scene_top_level_variants():
    b, c = _basic()
    streams = b.streams()
    streams["Scene"] = leaf(0x0001, b"abc")
    with maxfile.open(build_cfb(streams)[0]) as mf:
        assert mf.objects == [] and any("no top-level container" in w for w in mf.warnings)
    streams["Scene"] = cont(0x2000) + cont(0x2001)
    with maxfile.open(build_cfb(streams)[0]) as mf:
        assert any("2 top-level chunks" in w for w in mf.warnings)


def test_compressed_scene():
    b, c = _basic()
    b.node(c["node"], "Zipped")
    with maxfile.open(b.build(compress=("Scene", "ClassDirectory3"))) as mf:
        assert mf.stream("Scene").compressed
        assert mf.nodes[0].name == "Zipped"
        assert mf.class_directory[c["node"]].name == "Node"


@pytest.mark.parametrize("version", [3, 4])
def test_open_path_and_stream_api(tmp_path, version):
    b, c = _basic()
    b.node(c["node"], "Box001")
    path = tmp_path / "scene.max"
    path.write_bytes(b.build(version=version, extra_streams={"Config": leaf(0x0001, b"cfg")}))
    with maxfile.open(path) as mf:
        assert mf.path == str(path)
        assert {e.path_str for e in mf.streams} == {"ClassDirectory3", "DllDirectory", "Scene", "Config"}
        assert mf.stream("config").chunks[0].data == b"cfg"
        assert mf.stream("Config") is mf.stream("CONFIG")
        assert mf.raw_stream("Config") == leaf(0x0001, b"cfg")
        with pytest.raises(maxfile.StreamNotFoundError):
            mf.stream("Nope")
        assert mf.nodes[0].name == "Box001"


def test_not_a_max_file():
    data, _ = build_cfb({"WordDocument": b"x" * 100})
    with pytest.raises(maxfile.MaxFileError, match="not a .max scene"):
        maxfile.open(data)
    with pytest.raises(maxfile.NotCompoundFileError):
        maxfile.open(b"hello" * 200)


def test_missing_directories_are_warnings():
    data, _ = build_cfb({"Scene": cont(0x2000, cont(0, leaf(0x0962, text("Orphan"))))})
    with maxfile.open(data) as mf:
        assert mf.objects[0].cls is None
        assert any("no class directory" in w for w in mf.warnings)
        assert any("no DllDirectory" in w for w in mf.warnings)


def test_unknown_classes_and_usage():
    b, c = _basic()
    weird = b.cls("WeirdPlugin", (0xABCD, 0x1234), 0x10)
    for _ in range(3):
        b.obj(weird)
    b.obj(c["box"])
    with maxfile.open(b.build()) as mf:
        unknown = mf.unknown_classes()
        names = [u.entry.name for u in unknown]
        assert names[0] == "WeirdPlugin" and unknown[0].count == 3
        assert "Box" not in names
        # "Layer" is unknown to the registry but unused, so it isn't listed.
        assert "Layer" not in names
        usage = {u.entry.name: u for u in mf.class_usage()}
        assert usage["Box"].known.name == "Box" and usage["Box"].count == 1


def test_fuzzed_scene_never_crashes():
    """Corrupt chunk data in the streams gives warnings or MaxFileError, never another exception."""
    b, c = _basic()
    geo = b.obj(c["box"], leaf(0x1234, b"\x01\x02\x03"))
    root = b.node(c["node"], "Root")
    for i in range(10):
        b.node(c["node"], "N{:d}".format(i), parent=root, refs=[NULL, geo], offset_pos=(i, 0, 0))
    streams = b.streams()
    rng = random.Random(99)
    for _ in range(300):
        mutated = {}
        for name, data in streams.items():
            data = bytearray(data)
            for _ in range(rng.randint(0, 4)):
                if data:
                    data[rng.randrange(len(data))] = rng.getrandbits(8)
            mutated[name] = bytes(data)
        try:
            with maxfile.open(build_cfb(mutated)[0]) as mf:
                mf.warnings
                mf.class_usage()
                for node in mf.nodes:
                    node.world_matrix()
        except maxfile.MaxFileError:
            pass
