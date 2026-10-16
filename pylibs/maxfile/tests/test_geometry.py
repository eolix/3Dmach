# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Geometry, primitive and modifier-stack decoder tests.

The fixtures (``synth_max``) encode the *documented, unverified* layouts of ``docs/format/overview.md`` §6; these
tests check the decoders against that documentation only.
"""

import random
import struct

import pytest

import maxfile
from maxfile.objects.geometry import MATERIAL_ID_DISK_OFFSET, MeshData
from maxfile.objects.modifiers import ModifierStack
from maxfile.objects.primitives import PrimitiveData
from synth_max import (
    NULL,
    SceneBuilder,
    cont,
    f32,
    leaf,
    poly_mesh,
    prim_holder,
    prim_leaf,
    prim_record,
    refs_ordered,
    tri_mesh,
    u32,
)

CUBE = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]
QUADS = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]


class Builder(SceneBuilder):
    def __init__(self):
        super().__init__()
        self.node_class = self.cls("Node", (1, 0), 1)
        self.poly = self.cls("Editable Poly", (0x1BF8338D, 0x192F6098), 0x10)
        self.polymesh = self.cls("PolyMeshObject", (0x5D21369A, 0), 0x10)
        self.mesh = self.cls("Editable Mesh", (0xE44F10B3, 0), 0x10)
        self.box = self.cls("Box", (0x10, 0), 0x10)
        self.sphere = self.cls("Sphere", (0x11, 0), 0x10)
        self.prim19 = self.cls("Prim19", (0x19, 0), 0x10)
        self.torus = self.cls("Torus", (0x20, 0), 0x10)
        self.cone = self.cls("Cone", (0xA86C23DD, 0), 0x10)
        self.plane = self.cls("Plane", (0x081F1DFC, 0x77566F65), 0x10)
        self.derived = self.cls("Derived", (0x2032, 0), 0x0B)
        self.derived2 = self.cls("Derived2", (0x2033, 0), 0x0B)
        self.modifier = self.cls("SomeModifier", (0x7E57, 0x0001), 0x810)
        self.block = self.cls("SomeParamBlock", (0x7E57, 0x0002), 0x82)


def _decode(b, index):
    mf = maxfile.open(b.build())
    return mf, mf.scene.decode(mf.objects[index])


# -----------------------------------------------------------------------------
# Editable Poly (§6.2)

def test_editable_poly():
    b = Builder()
    uvs = [(u, v, 0) for u in (0, 1) for v in (0, 1)]
    map_faces = [(0, 1, 3, 2)] * 6
    obj = b.obj(b.poly, poly_mesh(CUBE, QUADS, material_ids=[0, 0, 1, 1, 2, 2], smoothing=[1] * 6,
                                  channels={1: (uvs, map_faces), 0: ([(1, 1, 1)], [(0, 0, 0, 0)] * 6)}))
    mf, mesh = _decode(b, obj)
    assert isinstance(mesh, MeshData) and mesh.source == "editable_poly"
    assert mesh.positions == [tuple(map(float, p)) for p in CUBE]
    assert mesh.faces == QUADS
    # Disk IDs 0, 1, 2 are Max UI IDs 1, 2, 3 under the documented-but-unverified 0-based assumption.
    assert MATERIAL_ID_DISK_OFFSET == 1
    assert mesh.material_ids == [1, 1, 2, 2, 3, 3]
    assert mesh.smoothing_groups == [1] * 6
    assert sorted(mesh.map_channels) == [0, 1]
    assert mesh.map_channels[1].faces == map_faces and len(mesh.map_channels[1].vertices) == 4
    assert mesh.warnings == [] and mf.warnings == []
    assert mesh.stats()["corners"] == 24


def test_poly_defaults_without_optional_fields():
    b = Builder()
    obj = b.obj(b.polymesh, poly_mesh(CUBE, QUADS[:2]))
    _, mesh = _decode(b, obj)
    assert mesh.material_ids == [MATERIAL_ID_DISK_OFFSET] * 2 and mesh.smoothing_groups == [0, 0]
    assert mesh.map_channels == {}


def test_poly_optional_fields_are_skipped():
    # Flags 0x01 (u16[2]) and 0x20 (u32[2 * (n - 3)]) carry data we skip; the next face must still line up.
    faces = []
    for face, flags in (((0, 1, 2, 3, 4), 0x01 | 0x20 | 0x08), ((4, 5, 6), 0x08)):
        tail = b""
        if flags & 0x01:
            tail += struct.pack("<HH", 9, 9)
        tail += struct.pack("<H", 4)
        if flags & 0x20:
            tail += u32(*([7] * 2 * (len(face) - 3)))
        faces.append(u32(len(face), *face) + struct.pack("<H", flags) + tail)
    mesh_chunk = cont(0x08FE, leaf(0x0100, u32(8) + b"".join(u32(0) + f32(*p) for p in CUBE)),
                      leaf(0x011A, u32(2) + b"".join(faces)))
    b = Builder()
    obj = b.obj(b.poly, mesh_chunk)
    _, mesh = _decode(b, obj)
    assert mesh.faces == [(0, 1, 2, 3, 4), (4, 5, 6)] and mesh.material_ids == [5, 5]


def test_poly_unknown_face_flags_reported():
    face = u32(3, 0, 1, 2) + struct.pack("<H", 0x40)
    b = Builder()
    obj = b.obj(b.poly, cont(0x08FE, leaf(0x0100, u32(3) + b"".join(u32(0) + f32(*p) for p in CUBE[:3])),
                             leaf(0x011A, u32(1) + face)))
    mf, mesh = _decode(b, obj)
    assert mesh.faces == [(0, 1, 2)]
    assert any("unknown face flag bits 0x0040" in w for w in mf.warnings)


def test_poly_alternative_face_layouts():
    verts = leaf(0x0100, u32(8) + b"".join(u32(0) + f32(*p) for p in CUBE))
    b = Builder()
    alt_0310 = b.obj(b.poly, cont(0x08FE, verts, leaf(0x0310, b"".join(u32(4, *f) for f in QUADS))))
    alt_0118 = b.obj(b.poly, cont(0x08FE, verts, *(
        cont(0x0118, leaf(0x0110, u32(4, *f)), leaf(0x0130, struct.pack("<H", i))) for i, f in enumerate(QUADS))))
    mf = maxfile.open(b.build())
    m1 = mf.scene.decode(mf.objects[alt_0310])
    m2 = mf.scene.decode(mf.objects[alt_0118])
    assert m1.faces == QUADS and m2.faces == QUADS
    assert m2.material_ids == [1, 2, 3, 4, 5, 6]


def test_bad_face_indices_are_dropped_with_their_data():
    b = Builder()
    faces = [(0, 1, 2), (0, 1, 99), (2, 3), (4, 5, 6)]
    obj = b.obj(b.poly, poly_mesh(CUBE, faces, material_ids=[0, 1, 2, 3], smoothing=[1, 2, 4, 8],
                                  channels={1: ([(0, 0, 0)] * 3, [(0, 1, 2), (0, 1, 2), (0, 1), (0, 1, 2)])}))
    mf, mesh = _decode(b, obj)
    assert mesh.faces == [(0, 1, 2), (4, 5, 6)]
    assert mesh.material_ids == [1, 4] and mesh.smoothing_groups == [1, 8]
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


def test_map_data_out_of_step():
    b = Builder()
    extra = (leaf(0x0124, struct.pack("<i", 7)),)   # A channel number without vertices / faces.
    obj = b.obj(b.poly, poly_mesh(CUBE, QUADS[:1], channels={1: ([(0, 0, 0)], [(0, 0, 0, 0)])}, extra=extra))
    mf, mesh = _decode(b, obj)
    assert sorted(mesh.map_channels) == [1]
    assert any("out of step" in w for w in mf.warnings)


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
    obj = b.obj(b.mesh, tri_mesh(CUBE[:4], tris, material_ids=[0, 4], smoothing=[3, 0],
                                 channels={1: ([(0, 0, 0), (1, 0, 0), (1, 1, 0)], [(0, 1, 2), (0, 2, 1)])}))
    mf, mesh = _decode(b, obj)
    assert mesh.source == "editable_mesh" and mesh.faces == tris
    assert mesh.material_ids == [1, 5] and mesh.smoothing_groups == [3, 0]
    assert mesh.map_channels[1].faces == [(0, 1, 2), (0, 2, 1)]
    assert mf.warnings == []


def test_editable_mesh_truncated():
    b = Builder()
    obj = b.obj(b.mesh, cont(0x08FE, leaf(0x0914, u32(2) + f32(1, 2, 3)), leaf(0x0912, u32(1) + b"\x01")))
    mf, mesh = _decode(b, obj)
    assert mesh.positions == [(1.0, 2.0, 3.0)] and mesh.faces == []
    assert any("claims 2 entries, only 1 fit" in w for w in mf.warnings)


# -----------------------------------------------------------------------------
# Primitives (§6.1, §6.4)

@pytest.mark.parametrize("encode", [prim_leaf, prim_holder, prim_record])
def test_box_parameters(encode):
    b = Builder()
    block = b.obj(b.block, encode(10.0), encode(20.0), encode(30.0))
    box = b.obj(b.box, refs_ordered(block))
    mf, prim = _decode(b, box)
    assert isinstance(prim, PrimitiveData) and prim.kind == "BOX"
    assert prim.params == {"length": 10.0, "width": 20.0, "height": 30.0}
    assert prim.encoding == {"prim_leaf": "leaf", "prim_holder": "0x0100", "prim_record": "record"}[
        encode.__name__]
    assert prim.cached_mesh is None and prim.extra_values == [] and prim.param_block == block
    assert mf.warnings == []


@pytest.mark.parametrize("attr,kind,names", [
    ("sphere", "SPHERE", ("radius",)),
    ("torus", "TORUS", ("radius1", "radius2")),
    ("cone", "CONE", ("radius1", "radius2", "height")),
    ("plane", "PLANE", ("length", "width")),
])
def test_primitive_kinds(attr, kind, names):
    b = Builder()
    block = b.obj(b.block, *(prim_leaf(float(i + 1)) for i in range(len(names))))
    obj = b.obj(getattr(b, attr), refs_ordered(block))
    _, prim = _decode(b, obj)
    assert prim.kind == kind and prim.params == {n: float(i + 1) for i, n in enumerate(names)}


def test_primitive_extra_and_missing_values():
    b = Builder()
    block = b.obj(b.block, prim_leaf(1), leaf(0x0009, b"short"), prim_leaf(2), prim_leaf(3), prim_leaf(4),
                  refs_ordered(0))  # Short leaves and reference chunks are not parameters.
    box = b.obj(b.box, refs_ordered(block))
    few = b.obj(b.cone, refs_ordered(b.obj(b.block, prim_leaf(5))))
    no_block = b.obj(b.sphere)
    mf = maxfile.open(b.build())
    prim = mf.scene.decode(mf.objects[box])
    assert prim.params == {"length": 1.0, "width": 2.0, "height": 3.0} and prim.extra_values == [4.0]
    assert mf.scene.decode(mf.objects[few]).params == {"radius1": 5.0}
    assert mf.scene.decode(mf.objects[no_block]).params == {}
    text = "\n".join(mf.warnings)
    assert "1 undocumented parameter value(s)" in text and "1 of 3 documented parameters" in text
    assert "no parameter block reference" in text


def test_primitive_cached_mesh():
    b = Builder()
    block = b.obj(b.block, prim_leaf(1), prim_leaf(1), prim_leaf(1))
    tris = [(0, 1, 2)]
    box = b.obj(b.box, refs_ordered(block), tri_mesh(CUBE[:3], tris, channels={1: ([(0, 0, 0)], [(0, 0, 0)])}))
    p19 = b.obj(b.prim19, refs_ordered(block),
                tri_mesh(CUBE[:3], tris, channels={1: ([(0, 0, 0)], [(0, 0, 0)])}, class_0x19=True))
    # The documented class-0x19 map chunks are 0x0916 / 0x0918; under a Box they aren't read.
    box_with_19_chunks = b.obj(b.box, refs_ordered(block),
                               tri_mesh(CUBE[:3], tris, channels={1: ([(0, 0, 0)], [(0, 0, 0)])}, class_0x19=True))
    mf = maxfile.open(b.build())
    for index, channels in ((box, [1]), (p19, [1]), (box_with_19_chunks, [])):
        prim = mf.scene.decode(mf.objects[index])
        assert prim.cached_mesh.source == "primitive_cache" and prim.cached_mesh.faces == tris
        assert sorted(prim.cached_mesh.map_channels) == channels
    # The torus has no documented cache: a 0x08FE chunk is ignored.
    torus = Builder()
    torus_block = torus.obj(torus.block, prim_leaf(1), prim_leaf(2))
    t = torus.obj(torus.torus, refs_ordered(torus_block), tri_mesh(CUBE[:3], tris))
    _, prim = _decode(torus, t)
    assert prim.cached_mesh is None


# -----------------------------------------------------------------------------
# Modifier stacks (§6.1)

def test_modifier_stack_and_resolve_geometry():
    b = Builder()
    base = b.obj(b.poly, poly_mesh(CUBE, QUADS))
    mod_top = b.obj(b.modifier)
    mod_bottom = b.obj(b.modifier)
    inner = b.obj(b.derived, refs_ordered(mod_bottom, base))
    outer_mod = b.obj(b.modifier)
    outer = b.obj(b.derived2, refs_ordered(outer_mod, mod_top, inner))
    node = b.node(b.node_class, "N", refs=[NULL, outer])
    mf = maxfile.open(b.build())
    stack = mf.scene.decode(mf.objects[outer])
    assert isinstance(stack, ModifierStack) and stack.base == inner
    assert [m.object_index for m in stack.modifiers] == [outer_mod, mod_top]
    assert [m.object_index for m in stack.bottom_up()] == [mod_top, outer_mod]
    assert stack.modifiers[0].class_name == "SomeModifier" and stack.modifiers[0].enabled is None
    base_obj, mods = mf.scene.resolve_geometry(mf.scene.node(node))
    assert base_obj.index == base
    assert [m.index for m in mods] == [outer_mod, mod_top, mod_bottom]


def test_resolve_geometry_edge_cases():
    b = Builder()
    empty = b.obj(b.derived)
    a = b.placeholder()
    c = b.obj(b.derived, refs_ordered(a))
    b.set_obj(a, b.derived, refs_ordered(c))
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
    poly = b.obj(b.poly, poly_mesh(CUBE, QUADS, material_ids=[0] * 6, smoothing=[1] * 6, channels={1: uv}))
    tri_uv = ([(0, 0, 0)] * 3, [(0, 1, 2)] * 2)
    mesh = b.obj(b.mesh, tri_mesh(CUBE[:4], [(0, 1, 2), (0, 2, 3)], channels={1: tri_uv}))
    block = b.obj(b.block, prim_leaf(1), prim_holder(2), prim_record(3))
    box = b.obj(b.box, refs_ordered(block), tri_mesh(CUBE[:3], [(0, 1, 2)]))
    stack = b.obj(b.derived, refs_ordered(b.obj(b.modifier), poly))
    b.node(b.node_class, "N", refs=[NULL, stack])
    targets = [poly, mesh, box, stack]
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
