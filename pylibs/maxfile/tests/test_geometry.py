# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Mesh and modifier-stack decoder tests.

The synthetic fixtures (``synth_max``) follow the layouts of ``docs/format/overview.md`` §6, verified on the local
corpus; the corpus tests at the end check those layouts on real files and skip without the corpus.
"""

import collections
import math
import random
import struct

import pytest

import maxfile
from corpus_files import corpus_file, full_corpus_enabled, sample
from maxfile.objects.geometry import MATERIAL_ID_DISK_OFFSET, MeshData
from maxfile.objects.modifiers import ModifierStack
from synth_max import NULL, SceneBuilder, cont, f32, leaf, poly_mesh, refs_ordered, tri_mesh, u32

CUBE = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]
QUADS = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
DERIVED = 0x2032        # Chunk type of derived objects: a class of its own, not in the class directory.
DERIVED_WSM = 0x2033


class Builder(SceneBuilder):
    def __init__(self):
        super().__init__()
        self.node_class = self.cls("Node", (1, 0), 1)
        self.poly = self.cls("Editable Poly", (0x1BF8338D, 0x192F6098), 0x10)
        self.polymesh = self.cls("PolyMeshObject", (0x5D21369A, 0), 0x10)
        self.mesh = self.cls("Editable Mesh", (0xE44F10B3, 0), 0x10)
        self.modifier = self.cls("SomeModifier", (0x7E57, 0x0001), 0x810)


def _decode(b, index):
    mf = maxfile.open(b.build())
    return mf, mf.scene.decode(mf.objects[index])


# -----------------------------------------------------------------------------
# Editable Poly (§6.2)

def test_editable_poly():
    b = Builder()
    uvs = [(u, v, 0) for u in (0, 1) for v in (0, 1)]
    map_faces = [(0, 1, 3, 2)] * 6
    obj = b.obj(b.poly, poly_mesh(CUBE, QUADS, material_ids=[0, 0, 1, 1, 2, 2], smoothing=[1, 1, 1, 0, 2, 2],
                                  channels={1: (uvs, map_faces), 0: ([(1, 1, 1)], [(0, 0, 0, 0)] * 6)}))
    mf, mesh = _decode(b, obj)
    assert isinstance(mesh, MeshData) and mesh.source == "editable_poly"
    assert mesh.positions == [tuple(map(float, p)) for p in CUBE]
    assert mesh.faces == QUADS
    # Disk IDs are 0-based (verified); MeshData has Max's 1-based IDs.
    assert MATERIAL_ID_DISK_OFFSET == 1
    assert mesh.material_ids == [1, 1, 2, 2, 3, 3]
    assert mesh.smoothing_groups == [1, 1, 1, 0, 2, 2]
    assert sorted(mesh.map_channels) == [0, 1]
    assert mesh.map_channels[1].faces == map_faces and len(mesh.map_channels[1].vertices) == 4
    assert mesh.edge_visibility is None
    assert mesh.warnings == [] and mf.warnings == []
    assert mesh.stats()["corners"] == 24
    assert mesh.bounds() == ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))


def test_poly_defaults_without_optional_fields():
    b = Builder()
    obj = b.obj(b.polymesh, poly_mesh(CUBE, [(0, 1, 2), (4, 5, 6)]))
    _, mesh = _decode(b, obj)
    assert mesh.material_ids == [MATERIAL_ID_DISK_OFFSET] * 2 and mesh.smoothing_groups == [0, 0]
    assert mesh.map_channels == {}


def test_poly_optional_fields_are_skipped():
    # Flag 0x01 (u32, meaning unknown) and 0x20 (diagonals, 2 * (n - 3) u32) carry data we skip; the next face
    # must still line up.
    b = Builder()
    faces = [(0, 1, 2, 3, 4), (4, 5, 6), (0, 1, 2, 3)]
    obj = b.obj(b.poly, poly_mesh(CUBE, faces, material_ids=[4, 0, 2], smoothing=[0, 3, 0], unknown_field=True))
    _, mesh = _decode(b, obj)
    assert mesh.faces == faces and mesh.material_ids == [5, 1, 3] and mesh.smoothing_groups == [0, 3, 0]
    assert mesh.warnings == []


def test_poly_unknown_face_flags_reported():
    face = u32(3, 0, 1, 2) + struct.pack("<H", 0x40)
    b = Builder()
    obj = b.obj(b.poly, cont(0x08FE, leaf(0x0100, u32(3) + b"".join(u32(0) + f32(*p) for p in CUBE[:3])),
                             leaf(0x011A, u32(1) + face)))
    mf, mesh = _decode(b, obj)
    assert mesh.faces == [(0, 1, 2)]
    assert any("unknown face flag bits 0x0040" in w for w in mf.warnings)


def test_bad_face_indices_are_dropped_with_their_data():
    b = Builder()
    faces = [(0, 1, 2), (0, 1, 99), (2, 3), (4, 5, 6)]
    obj = b.obj(b.poly, poly_mesh(CUBE, faces, material_ids=[0, 1, 2, 3], smoothing=[1, 2, 4, 8],
                                  channels={1: ([(0, 0, 0)] * 3, [(0, 1, 2), (0, 1, 2), (0, 1, 2, 1), (0, 1, 2)])}))
    mf, mesh = _decode(b, obj)
    assert mesh.faces == [(0, 1, 2), (4, 5, 6)]
    assert mesh.material_ids == [1, 4] and mesh.smoothing_groups == [1, 8]
    # A dropped face's map face doesn't have to match it (the corpus has 0-corner faces with quad map faces).
    assert mesh.map_channels[1].faces == [(0, 1, 2), (0, 1, 2)]
    assert any("2 face(s) dropped" in w for w in mf.warnings)


def test_bad_map_channels_are_dropped():
    b = Builder()
    obj = b.obj(b.poly, poly_mesh(CUBE, QUADS[:2], channels={
        1: ([(0, 0, 0)], [(0, 0, 0, 0)]),                       # One map face for two faces.
        2: ([(0, 0, 0)], [(0, 0, 0), (0, 0, 0, 0)]),            # Corner count differs.
        3: ([(0, 0, 0)], [(0, 0, 0, 5), (0, 0, 0, 0)]),         # Map vertex out of range.
        4: ([(0, 0, 0)], [(0, 0, 0, 0), (0, 0, 0, 0)]),         # Fine.
    }))
    mf, mesh = _decode(b, obj)
    assert sorted(mesh.map_channels) == [4]
    text = "\n".join(mf.warnings)
    assert "map channel 1 dropped" in text and "map channel 2 dropped" in text and "map channel 3 dropped" in text


def test_map_channel_without_data():
    b = Builder()
    extra = (leaf(0x0124, struct.pack("<i", 7)),)   # A channel number without vertices / faces.
    obj = b.obj(b.poly, poly_mesh(CUBE, QUADS[:1], channels={1: ([(0, 0, 0)], [(0, 0, 0, 0)])}, extra=extra))
    mf, mesh = _decode(b, obj)
    assert sorted(mesh.map_channels) == [1]
    orphan = b.obj(b.poly, cont(0x08FE, leaf(0x0100, u32(0)), leaf(0x011A, u32(0)),
                                leaf(0x0128, u32(1) + f32(0, 0, 0))))
    mf, mesh = _decode(b, orphan)
    assert mesh.map_channels == {} and any("before any channel number" in w for w in mf.warnings)


def test_counts_larger_than_data():
    b = Builder()
    verts = leaf(0x0100, u32(1000) + u32(0) + f32(1, 2, 3))
    faces = leaf(0x011A, u32(50) + u32(3, 0, 0, 0) + struct.pack("<H", 0) + u32(0xFFFFFFF0))
    obj = b.obj(b.poly, cont(0x08FE, verts, faces))
    mf, mesh = _decode(b, obj)
    assert mesh.positions == [(1.0, 2.0, 3.0)]
    assert mesh.faces == [(0, 0, 0)]
    text = "\n".join(mf.warnings)
    assert "claims 1000 entries, only 1 fit" in text and "data ends inside face 1 of 50" in text


def test_missing_mesh_container():
    b = Builder()
    obj = b.obj(b.poly, leaf(0x1234, b"x"))
    mf, mesh = _decode(b, obj)
    assert mesh is None and any("no 0x08FE mesh container" in w for w in mf.warnings)


# -----------------------------------------------------------------------------
# Editable Mesh (§6.3)

def test_editable_mesh():
    b = Builder()
    tris = [(0, 1, 2), (0, 2, 3)]
    obj = b.obj(b.mesh, tri_mesh(CUBE[:4], tris, material_ids=[0, 4], smoothing=[3, 0], edge_flags=[0x43, 0x46],
                                 channels={1: ([(0, 0, 0), (1, 0, 0), (1, 1, 0)], [(0, 1, 2), (0, 2, 1)]),
                                           -2: ([(1, 1, 1)], [(0, 0, 0)] * 2)}))
    mf, mesh = _decode(b, obj)
    assert mesh.source == "editable_mesh" and mesh.faces == tris
    assert mesh.material_ids == [1, 5] and mesh.smoothing_groups == [3, 0]
    assert sorted(mesh.map_channels) == [-2, 1]
    assert mesh.map_channels[1].faces == [(0, 1, 2), (0, 2, 1)]
    # Bits 0-2 of the face flags: edges a-b, b-c, c-a visible. The shared edge 0-2 is hidden on both sides.
    assert mesh.edge_visibility == [0x3, 0x6]
    assert mf.warnings == []


def test_editable_mesh_truncated():
    b = Builder()
    obj = b.obj(b.mesh, cont(0x08FE, leaf(0x0914, u32(2) + f32(1, 2, 3)), leaf(0x0912, u32(1) + b"\x01")))
    mf, mesh = _decode(b, obj)
    assert mesh.positions == [(1.0, 2.0, 3.0)] and mesh.faces == []
    assert any("claims 2 entries, only 1 fit" in w for w in mf.warnings)


# -----------------------------------------------------------------------------
# Modifier stacks (§6.5)

def _context(bbox=((0, 0, 0), (1, 1, 1)), flags=0x00040100):
    tm = f32(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0) + u32(6)
    return cont(0x2500, leaf(0x2510, tm), leaf(0x2511, f32(*bbox[0], *bbox[1])), leaf(0x2513, u32(flags)))


def test_modifier_stack_and_resolve_geometry():
    b = Builder()
    base = b.obj(b.poly, poly_mesh(CUBE, QUADS))
    mod_top = b.obj(b.modifier)
    mod_bottom = b.obj(b.modifier)
    inner = b.obj(DERIVED, refs_ordered(mod_bottom, base), _context())
    outer_mod = b.obj(b.modifier)
    outer = b.obj(DERIVED_WSM, refs_ordered(outer_mod, mod_top, inner),
                  _context(((0, 0, 0), (2, 2, 2)), 0x00040000), _context())
    node = b.node(b.node_class, "N", refs=[NULL, outer])
    mf = maxfile.open(b.build())
    stack = mf.scene.decode(mf.objects[outer])
    assert isinstance(stack, ModifierStack) and stack.base == inner
    assert [m.object_index for m in stack.modifiers] == [outer_mod, mod_top]
    assert [m.object_index for m in stack.bottom_up()] == [mod_top, outer_mod]
    top = stack.modifiers[0]
    assert top.class_name == "SomeModifier" and top.enabled is None
    assert top.context_bbox == ((0.0, 0.0, 0.0), (2.0, 2.0, 2.0)) and top.context_flags == 0x00040000
    assert top.context_tm == ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (0.0, 0.0, 0.0))
    base_obj, mods = mf.scene.resolve_geometry(mf.scene.node(node))
    assert base_obj.index == base
    assert [m.index for m in mods] == [outer_mod, mod_top, mod_bottom]
    assert mf.objects[outer].class_label() == "Derived Object (world space)"
    assert mf.warnings == []


def test_resolve_geometry_edge_cases():
    b = Builder()
    empty = b.obj(DERIVED)
    a = b.placeholder()
    c = b.obj(DERIVED, refs_ordered(a))
    b.set_obj(a, DERIVED, refs_ordered(c))
    plain = b.obj(b.mesh, tri_mesh(CUBE[:3], [(0, 1, 2)]))
    n_empty = b.node(b.node_class, "Empty", refs=[NULL, empty])
    n_cycle = b.node(b.node_class, "Cycle", refs=[NULL, c])
    n_plain = b.node(b.node_class, "Plain", refs=[NULL, plain])
    n_none = b.node(b.node_class, "None")
    mf = maxfile.open(b.build())
    scene = mf.scene
    assert scene.resolve_geometry(scene.node(n_empty)) == (None, [])
    assert scene.resolve_geometry(scene.node(n_cycle))[0] is None
    assert scene.resolve_geometry(scene.node(n_plain)) == (mf.objects[plain], [])
    assert scene.resolve_geometry(scene.node(n_none)) == (None, [])
    assert any("form a cycle" in w for w in mf.warnings)
    assert any("modifier stack without references" in w for w in mf.warnings)


# -----------------------------------------------------------------------------
# Corruption

def test_fuzzed_geometry_never_crashes():
    b = Builder()
    uv = ([(0, 0, 0)] * 4, [(0, 1, 2, 3)] * 6)
    poly = b.obj(b.poly, poly_mesh(CUBE, QUADS, material_ids=[1] * 6, smoothing=[1] * 6, channels={1: uv}))
    tri_uv = ([(0, 0, 0)] * 3, [(0, 1, 2)] * 2)
    mesh = b.obj(b.mesh, tri_mesh(CUBE[:4], [(0, 1, 2), (0, 2, 3)], channels={1: tri_uv}))
    stack = b.obj(DERIVED, refs_ordered(b.obj(b.modifier), poly), _context())
    b.node(b.node_class, "N", refs=[NULL, stack])
    targets = [poly, mesh, stack]
    original = list(b.objects)
    rng = random.Random(7)
    for _ in range(300):
        objects = []
        for data in original:
            data = bytearray(data)
            for _ in range(rng.randint(0, 3)):
                data[rng.randrange(len(data))] = rng.getrandbits(8)
            objects.append(bytes(data))
        b.objects = objects
        try:
            mf = maxfile.open(b.build())
        except maxfile.MaxFileError:
            continue
        for index in targets:
            if index < len(mf.objects):
                mf.scene.decode(mf.objects[index])
        for node in mf.nodes:
            mf.scene.resolve_geometry(node)


# -----------------------------------------------------------------------------
# Real files (skipped without the corpus)

HAMMER = "Scenes/SubDivSurfaces/Meshsmooth-Hammer.max"


def test_corpus_meshsmooth_hammer():
    with maxfile.open(corpus_file(HAMMER)) as mf:
        (node,) = mf.nodes
        assert node.name == "Box06"
        base, modifiers = mf.scene.resolve_geometry(node)
        assert base.class_label() == "Editable Mesh"
        assert [m.class_label() for m in modifiers] == ["MeshSmooth"]
        mesh = mf.scene.decode(base)
        assert (len(mesh.positions), len(mesh.faces)) == (56, 108)
        # Converted from a Box: the six sides keep the IDs 1-6 Max gives a box (0-5 on disk).
        assert sorted(set(mesh.material_ids)) == [1, 2, 3, 4, 5, 6]
        assert mesh.warnings == [] and not any("Editable Mesh" in w for w in mf.warnings)
        # Every hidden edge is a quad diagonal shared by two triangles.
        assert _hidden_edges_paired(mesh)


def test_corpus_editable_poly_with_three_channels():
    path = corpus_file("Scenes/BoxModeling/PrimerFrame_Box_modeling.max")
    with maxfile.open(path) as mf:
        meshes = [mf.scene.decode(o) for o in mf.objects if o.class_label() == "Editable Poly"]
        assert meshes and all(isinstance(m, MeshData) and not m.warnings for m in meshes)
        assert any(sorted(m.map_channels) == [-1, 0, 1] for m in meshes)


def test_corpus_derived_object_order():
    # Modifiers that turn a shape into a mesh sit directly above the shape base: the base is the last reference and
    # the references run from the top of the stack down.
    with maxfile.open(corpus_file("Scenes/CameraMap/wall.max")) as mf:
        stacks = [mf.scene.decode(o) for o in mf.objects if o.class_index == DERIVED]
        found = 0
        for stack in stacks:
            base = mf.objects[stack.base]
            names = [m.class_name for m in stack.modifiers]
            if base.superclass_id == 0x40 and names:
                assert names[-1] in ("Extrude", "Lathe", "Edit Spline", "Sweep", "Normalize Spl."), names
                found += 1
                # The bottom modifier's input is the flat shape when it's an Extrude.
                if names[-1] == "Extrude":
                    lo, hi = stack.modifiers[-1].context_bbox
                    assert abs(hi[2] - lo[2]) < 1e-3
        assert found


def _hidden_edges_paired(mesh):
    edges = collections.Counter()
    hidden = collections.Counter()
    for face, vis in zip(mesh.faces, mesh.edge_visibility):
        for i in range(3):
            key = tuple(sorted((face[i], face[(i + 1) % 3])))
            edges[key] += 1
            if not vis >> i & 1:
                hidden[key] += 1
    return all(count == 2 and edges[key] == 2 for key, count in hidden.items())


def _check_meshes(path):
    """Mesh facts that hold for every Editable Poly / Mesh of the corpus."""
    problems = collections.Counter()
    with maxfile.open(path) as mf:
        for obj in mf.objects:
            if obj.superclass_id != 0x10:
                continue
            if obj.class_label() not in ("Editable Poly", "Editable Mesh", "PolyMeshObject"):
                continue
            mesh = mf.scene.decode(obj)
            assert isinstance(mesh, MeshData), (path, obj.index)
            nverts = len(mesh.positions)
            assert all(all(0 <= v < nverts for v in face) and len(face) >= 3 for face in mesh.faces)
            assert all(math.isfinite(c) for p in mesh.positions for c in p)
            assert len(mesh.material_ids) == len(mesh.smoothing_groups) == len(mesh.faces)
            assert all(1 <= m <= 0x10000 for m in mesh.material_ids)
            for channel in mesh.map_channels.values():
                assert len(channel.faces) == len(mesh.faces)
            for message in mesh.warnings:
                problems[message.split(":")[0]] += 1
    return problems


@pytest.mark.parametrize("path", sample(12) or [None])
def test_corpus_meshes_sample(path):
    if path is None:
        pytest.skip("no corpus")
    problems = _check_meshes(path)
    # The only mesh problem in the whole corpus: a few faces without corners (one file).
    assert set(problems) <= {"map channel 1 dropped", "2 face(s) dropped", "4 face(s) dropped",
                             "6 face(s) dropped"}, problems


def test_corpus_meshes_all():
    if not full_corpus_enabled():
        pytest.skip("set MX_FULL_CORPUS=1 for the whole-corpus mesh check")
    from corpus_files import all_files
    files = all_files()
    if not files:
        pytest.skip("no corpus")
    total = collections.Counter()
    for path in files:
        total.update(_check_meshes(path))
    assert sum(total.values()) <= 13, total
