# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
The writer's output has the shape of real files saved by Max 2015 (the release it targets): same streams, root
CLSID, version stamps, Scene container, scene-level objects, class / DLL entries, node / Editable Poly / material
layouts. Compared with a few 2015 files of the local corpus; skipped without the corpus.
"""

import struct

import pytest

import maxfile
from maxfile.writer import Bitmap, EditablePoly, MapChannel, MultiSubMaterial, Node, Scene, StandardMaterial, to_bytes
from maxfile.writer import poly

from corpus_files import corpus_file

# 2015 files (release 16900) of the sample set, chosen for their content.
EMPTYISH = "Scenes/Raytrace/AdvancedExamples/A01depth.max"            # 3 GeoSpheres, Standard + Raytrace
BITMAP = "Scenes/Raytrace/AdvancedExamples/C02Blrof.max"              # a Bitmap on a Standard
EPOLY = "Particle Flow Examples/Box2/PFlow_mP_Tutorial_SinglePaperTutorial_Start.max"     # an Editable Poly
MULTI = "Scenes/CacheForceVehicles/NH tractor.max"                    # Multi/Sub-Object, Bitmaps
# Chunks real objects may carry that the writer leaves out on purpose (AppData, custom attributes, optional
# markers).
OPTIONAL = {0x2150, 0x21B0, 0x9500, 0x0975, 0x0976, 0x0977, 0x0978, 0x0AFA, 0x0A8C, 0x09C4, 0x09D8, 0x09E2}
# Per class, chunks that only part of the 2015 files have (counts in docs/design/max-writer.md / the writer).
OPTIONAL_BY_CLASS = {
    "Layer Manager": {0x1800},                      # 48/305
    "Default Scanline Renderer": {0x0074, 0x0075},  # 1,034/1,175
    "Texmaps": {0x510C, 0x510D, 0x510E, 0x510F},    # 672/915
}


def _written():
    box = EditablePoly(
        [(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0), (0, 0, 1), (1, 0, 1), (0, 1, 1), (1, 1, 1)],
        [[0, 2, 3, 1], [4, 5, 7, 6], [0, 1, 5, 4], [1, 3, 7, 5], [3, 2, 6, 7], [2, 0, 4, 6]],
        material_ids=[1, 2, 1, 2, 1, 2], smoothing_groups=[1, 2, 4, 8, 16, 32],
        map_channels={1: MapChannel([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [[0, 1, 2, 3]] * 6)})
    std = StandardMaterial("Bricks", diffuse_map=Bitmap("C:\\maps\\bricks.jpg"))
    multi = MultiSubMaterial("Multi", [std, StandardMaterial("Plain")])
    return to_bytes(Scene(nodes=[Node("Box001", mesh=box, material=multi)]))


@pytest.fixture(scope="module")
def ours():
    with maxfile.open(_written()) as mf:
        yield mf


def _real(relpath):
    return maxfile.open(corpus_file(relpath))


def _first(mf, label):
    for obj in mf.scene.objects:
        if obj.class_label() == label:
            return obj
    raise AssertionError("no {:s} object".format(label))


def _types(chunk, skip=OPTIONAL):
    return [c.type for c in chunk.children if c.type not in skip]


def _heads(pb_obj):
    """(id, type, flags_a, flags_b, extra, value flags) of each ParamBlock2 record, in order."""
    return [struct.unpack_from("<HIHIHB", c.data) for c in pb_obj.chunk.children if c.type == 0x100E]


def _pb2_header(pb_obj):
    return struct.unpack_from("<IHIHI", pb_obj.chunk.find(0x0009).data)


def test_corpus_container_and_streams(ours):
    with _real(EMPTYISH) as real:
        assert real.max_release == ours.max_release == 16900
        assert {e.path_str for e in real.streams} == {e.path_str for e in ours.streams}
        assert real.container.version == ours.container.version == 4
        assert real.stream("Scene").chunks[0].type == ours.stream("Scene").chunks[0].type
        save_real = [c.type for c in real.stream("SaveConfigData").chunks]
        assert save_real == [c.type for c in ours.stream("SaveConfigData").chunks]
        for top in ours.stream("Config").chunks:
            assert top.type in [c.type for c in real.stream("Config").chunks]
        assert [c.type for c in real.stream("VideoPostQueue").chunks] == \
            [c.type for c in ours.stream("VideoPostQueue").chunks]


def _root_clsid(blob):
    first_dir = struct.unpack_from("<I", blob, 48)[0]
    entry = (first_dir + 1) * 4096
    return blob[entry + 80:entry + 96]


def test_corpus_root_clsid():
    with open(corpus_file(EMPTYISH), "rb") as fh:
        real = fh.read()
    assert _root_clsid(real) == _root_clsid(_written())


def _ref_labels(mf, obj):
    return [mf.scene.objects[i].class_label() for _, i in sorted(obj.references.items())]


def test_corpus_scene_object(ours):
    with _real(EMPTYISH) as real:
        r, o = real.scene.objects[-1], ours.scene.objects[-1]
        assert _ref_labels(real, r) == _ref_labels(ours, o)
        assert _types(r.chunk) == _types(o.chunk)


@pytest.mark.parametrize("label", ["Material Editor", "MtlBaseLib", "Default Sound", "RootNode", "RenderEnvironment",
                                   "NamedSelSetList", "Grid Reference", "RenderEffects", "Layer Manager",
                                   "Base Layer", "TrackSetList", "PersistentIsolationData", "PersistentNodeSet",
                                   "Default Scanline Renderer", "RenderElementMgr", "Shadow Map", "Max 2.5 Star",
                                   "Texmaps", "Blinn", "Standard", "Position/Rotation/Scale", "Bezier Position",
                                   "TCB Rotation", "Bezier Scale", "Scene Effect Loader"])
def test_corpus_object_layouts(ours, label):
    """Chunk types (top level, in order) of the scene-level objects, controllers and materials."""
    with _real(EMPTYISH) as real, _real(BITMAP) as real2:
        try:
            r = _first(real, label)
        except AssertionError:
            r = _first(real2, label)
        skip = OPTIONAL | OPTIONAL_BY_CLASS.get(label, set())
        assert _types(r.chunk, skip) == _types(_first(ours, label).chunk, skip)


def test_corpus_class_and_dll_entries(ours):
    """Every class the writer emits has the class ID, superclass and DLL (file, description) of the real files."""
    real_entries = {}
    for relpath in (EMPTYISH, BITMAP, EPOLY, MULTI):
        with _real(relpath) as real:
            for e in real.class_directory.entries:
                dll = (e.dll.file_name, e.dll.description) if e.dll else e.dll_index
                real_entries.setdefault(e.name, (e.class_id, e.superclass_id, dll))
    checked = 0
    for e in ours.class_directory.entries:
        if e.name not in real_entries:
            continue
        dll = (e.dll.file_name, e.dll.description) if e.dll else e.dll_index
        assert (e.class_id, e.superclass_id, dll) == real_entries[e.name], e.name
        checked += 1
    assert checked >= 40


def test_corpus_node_and_editable_poly_layout(ours):
    with _real(EPOLY) as real:
        node = next(n for n in real.nodes if n.object is not None and n.object.class_label() == "Editable Poly")
        ours_node = ours.nodes[0]
        assert _types(node.obj.chunk) == _types(ours_node.obj.chunk)
        for sub in (0x0AD2, 0x0B22, 0x0ADC, 0x0AF0, 0x0B54, 0x0B5E):
            assert _types(node.obj.chunk.find(sub)) == _types(ours_node.obj.chunk.find(sub))
        real_poly, our_poly = node.object, ours_node.object
        assert _types(real_poly.chunk) == _types(our_poly.chunk)
        assert _types(real_poly.chunk.find(0x08FE)) == _types(our_poly.chunk.find(0x08FE))
        assert _types(real_poly.chunk.find(0x0906)) == _types(our_poly.chunk.find(0x0906))
        real_pb = real.scene.ref(real_poly, 0)
        our_pb = ours.scene.ref(our_poly, 0)
        assert [h[:2] for h in _heads(real_pb)] == [h[:2] for h in _heads(our_pb)]


def test_corpus_standard_material_blocks(ours):
    """Record heads of the Standard material's blocks, its Blinn block and the sampler's old block."""
    with _real(EMPTYISH) as real:
        r = _first(real, "Standard")
        o = next(obj for obj in ours.scene.objects if obj.class_label() == "Standard"
                 and ours.scene.decode(obj).name == "Bricks")
        for slot in (3, 4, 5, 6, 7):
            rb, ob = real.scene.ref(r, slot), ours.scene.ref(o, slot)
            assert _heads(rb) == _heads(ob), slot
            assert _pb2_header(rb)[1] == _pb2_header(ob)[1]         # Block ID.
            assert _types(rb.chunk) == _types(ob.chunk)
        rs, os_ = real.scene.ref(r, 2), ours.scene.ref(o, 2)
        assert _heads(real.scene.ref(rs, 0)) == _heads(ours.scene.ref(os_, 0))


def test_corpus_bitmap_layout(ours):
    with _real(BITMAP) as real:
        r, o = _first(real, "Bitmap"), _first(ours, "Bitmap")
        assert _types(r.chunk) == _types(o.chunk)
        for slot in (1, 3):
            rb, ob = real.scene.ref(r, slot), ours.scene.ref(o, slot)
            assert _heads(rb) == _heads(ob)
            assert _types(rb.chunk) == _types(ob.chunk)
            info_r, info_o = rb.chunk.find(0x0003), ob.chunk.find(0x0003)
            if info_r is not None:
                assert _types(info_r) == _types(info_o)
        for slot in (0, 2):
            assert _types(real.scene.ref(r, slot).chunk) == _types(ours.scene.ref(o, slot).chunk)


def test_corpus_multi_sub_layout(ours):
    with _real(MULTI) as real:
        r, o = _first(real, "Multi/Sub-Object"), _first(ours, "Multi/Sub-Object")
        assert _types(r.chunk) == _types(o.chunk)
        rb, ob = real.scene.ref(r, 0), ours.scene.ref(o, 0)
        assert [h[:4] for h in _heads(rb)] == [h[:4] for h in _heads(ob)]
        assert _types(rb.chunk) == _types(ob.chunk)


def _poly_topology(obj):
    m = obj.chunk.find(0x08FE)
    data = m.find(0x0100).data
    nv = struct.unpack_from("<I", data)[0]
    data = m.find(0x010A).data
    edges = [tuple(struct.unpack_from("<III", data, 4 + 12 * i)[1:]) for i in range(struct.unpack_from("<I", data)[0])]
    data = m.find(0x011A).data
    faces, p = [], 4
    for _ in range(struct.unpack_from("<I", data)[0]):
        k = struct.unpack_from("<I", data, p)[0]
        faces.append(list(struct.unpack_from("<{:d}I".format(k), data, p + 4)))
        p += 4 + 4 * k
        flags = struct.unpack_from("<H", data, p)[0]
        p += 2 + (4 if flags & 1 else 0) + (2 if flags & 8 else 0) + (4 if flags & 0x10 else 0) + \
            (8 * (k - 3) if flags & 0x20 else 0)
    stored = list(struct.unpack_from("<{:d}I".format(m.find(0x0310).payload_size // 4), m.find(0x0310).data))
    return nv, edges, faces, stored


def test_corpus_poly_adjacency_rule():
    """On corpus meshes whose edge list is the face-order one, 0x0310 is exactly what the writer derives."""
    matched = 0
    for relpath in (EPOLY, "Particle Flow Elements Library/scenes/Earth/Leaves_one car.max"):
        with _real(relpath) as real:
            for obj in real.scene.objects:
                if obj.class_label() != "Editable Poly":
                    continue
                nv, edges, faces, stored = _poly_topology(obj)
                if edges != poly.derive_edges(faces):
                    continue
                assert stored == poly.vertex_adjacency(nv, edges, faces)
                matched += 1
    assert matched >= 1
