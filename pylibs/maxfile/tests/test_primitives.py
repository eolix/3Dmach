# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Primitive decoders (:mod:`maxfile.objects.primitives`): synthetic objects with ParamBlock2 and old ParamBlock
parameter blocks, plus corpus checks (skipped without the corpus) that compare the decoded sizes with the input
bounding boxes Max stores in modifier contexts.
"""

import importlib.util
import math
import os
import struct

import pytest

import maxfile
from corpus_files import all_files, corpus_file, full_corpus_enabled
from maxfile.objects.primitives import BUILDER_KINDS, PRIMITIVE_PARAMS, PRIMITIVES, PrimitiveData
from synth_max import PB2, SceneBuilder, cont, f32, leaf, pb2_block, pb2_param, refs_ordered, u32

BUILDER_GEOMETRY = os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts", "addons_core",
                                "mx_primitives", "geometry.py")


def old_pb(values):
    """Old ParamBlock (class 0x8) children: per parameter a 0x0002 container with 0x0003 (index) and a value
    chunk (0x0100 float, 0x0101 int)."""
    children = [leaf(0x0001, u32(len(values)))]
    for index, value in enumerate(values):
        body = leaf(0x0100, f32(value)) if isinstance(value, float) else leaf(0x0101, struct.pack("<i", value))
        children.append(cont(0x0002, leaf(0x0003, u32(index)), body))
    return children


class Builder(SceneBuilder):
    def __init__(self):
        super().__init__()
        self.pb2 = self.cls("ParamBlock2", *PB2)
        self.pb = self.cls("ParamBlock", (0x8, 0), 0x8)
        self.box = self.cls("Box", (0x10, 0), 0x10)
        self.sphere = self.cls("Sphere", (0x11, 0), 0x10)
        self.plane = self.cls("Plane", (0x081F1DFC, 0x77566F65), 0x10)
        self.bend = self.cls("Bend", (0x10, 0), 0x810)      # Same class ID as Box, other superclass.

    def primitive(self, cls, block_children, block_class=None):
        owner = self.placeholder()
        block = self.obj(self.pb2 if block_class is None else block_class, *block_children)
        self.set_obj(owner, cls, refs_ordered(block), leaf(0x204B, b"\x2e"))
        return owner


def _decode(data, index):
    with maxfile.open(data) as mf:
        return mf.scene.decode(mf.objects[index]), list(mf.scene.warnings)


def test_box_param_block2():
    b = Builder()
    box = b.primitive(b.box, pb2_block(
        0,
        pb2_param(0, "world", 30.0), pb2_param(1, "world", 20.0), pb2_param(2, "world", -5.0),
        pb2_param(3, "int", 4), pb2_param(4, "int", 2), pb2_param(5, "int", 1), pb2_param(6, "bool", True),
    ))
    prim, warnings = _decode(b.build(), box)
    assert isinstance(prim, PrimitiveData) and prim.kind == "BOX" and prim.encoding == "pb2"
    assert prim.params == {"length": 30.0, "width": 20.0, "height": -5.0, "width_segments": 4,
                           "length_segments": 2, "height_segments": 1, "generate_uvs": True}
    assert prim.cached_mesh is None and prim.extra_values == [] and prim.param_block == box + 1
    assert "length" not in prim.guessed and "generate_uvs" in prim.guessed
    assert warnings == []


def test_sphere_old_param_block_converts_types():
    b = Builder()
    sphere = b.primitive(b.sphere, old_pb([12.5, 24, 1, 0.5, 1, 0, 1, 0, 0.0, 0.0]), b.pb)
    prim, warnings = _decode(b.build(), sphere)
    assert prim.kind == "SPHERE" and prim.encoding == "pb"
    p = prim.params
    assert p["radius"] == 12.5 and p["segments"] == 24 and p["smooth"] is True and p["hemisphere"] == 0.5
    assert p["hemisphere_mode"] == "SQUASH" and p["slice_on"] is False and p["generate_uvs"] is True
    assert p["base_to_pivot"] is False and p["slice_from"] == 0.0
    assert warnings == []


def test_plane_render_multipliers_are_extra():
    b = Builder()
    plane = b.primitive(b.plane, pb2_block(
        0, pb2_param(0, "float", 10.0), pb2_param(1, "float", 40.0), pb2_param(2, "int", 8), pb2_param(3, "int", 2),
        pb2_param(4, "float", 2.0), pb2_param(5, "float", 3.0), pb2_param(6, "bool", False),
        pb2_param(9, "int", 77),
    ))
    prim, _ = _decode(b.build(), plane)
    assert prim.params == {"length": 10.0, "width": 40.0, "width_segments": 8, "length_segments": 2,
                           "generate_uvs": False}
    assert prim.extra_params == {"render_scale": 2.0, "render_density": 3.0}
    assert prim.unknown_params == {9: 77} and prim.extra_values == [77]


def test_unknown_enum_value_and_missing_block():
    b = Builder()
    sphere = b.primitive(b.sphere, pb2_block(0, pb2_param(0, "world", 1.0), pb2_param(4, "int", 7)))
    lonely = b.obj(b.box)
    data = b.build()
    prim, warnings = _decode(data, sphere)
    assert prim.params == {"radius": 1.0} and prim.extra_params == {"hemisphere_mode": 7}
    assert any("unknown value 7" in w for w in warnings)
    assert any("parameter 1 (segments) missing" in w for w in warnings)
    prim, warnings = _decode(data, lonely)
    assert prim.kind == "BOX" and prim.params == {} and prim.param_block is None
    assert any("no parameter block" in w for w in warnings)


def test_bend_is_not_a_box():
    """Class 0x10 is Box in superclass 0x10 and Bend in 0x810."""
    b = Builder()
    bend = b.obj(b.bend)
    value, _ = _decode(b.build(), bend)
    assert not isinstance(value, PrimitiveData)


def test_tables_cover_every_class_and_have_unique_ids():
    assert set(PRIMITIVES.values()) == set(PRIMITIVE_PARAMS)
    for kind, table in PRIMITIVE_PARAMS.items():
        ids = [entry[0] for entry in table]
        names = [entry[1] for entry in table]
        assert len(ids) == len(set(ids)) and len(names) == len(set(names)), kind


def _builder_module():
    if not os.path.isfile(BUILDER_GEOMETRY):
        pytest.skip("mx_primitives not in this checkout")
    spec = importlib.util.spec_from_file_location("mx_primitives_geometry", BUILDER_GEOMETRY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_params_are_accepted_by_the_live_primitive_builder():
    geometry = _builder_module()
    assert BUILDER_KINDS == set(PRIMITIVE_PARAMS) & set(geometry.PARAMETERS)
    for kind in BUILDER_KINDS:
        names = {name for _id, name, _conv, _verified, extra in PRIMITIVE_PARAMS[kind] if not extra}
        assert names <= set(geometry.PARAMETERS[kind]), (kind, names - set(geometry.PARAMETERS[kind]))
        for _id, name, conversion, _verified, extra in PRIMITIVE_PARAMS[kind]:
            if isinstance(conversion, dict):
                assert set(conversion.values()) <= set(geometry.ENUMS[name])


# -----------------------------------------------------------------------------
# Corpus

def _bottom_context_boxes(mf):
    """(primitive data, bottom modifier context bbox) for each derived object directly over a primitive."""
    scene = mf.scene
    for obj in scene.objects:
        if obj.class_index not in (0x2032, 0x2033):
            continue
        refs = sorted(obj.references.items())
        contexts = [c for c in obj.chunk.children if c.type == 0x2500]
        if len(refs) < 2 or not contexts:
            continue
        prim = scene.decode(scene.objects[refs[-1][1]])
        bbox = contexts[-1].find(0x2511)
        if isinstance(prim, PrimitiveData) and bbox is not None:
            box = struct.unpack_from("<6f", bbox.data)
            if box[3] >= box[0]:
                yield prim, box


def _ngon_extents(radius, sides):
    xs = [radius * math.cos(2 * math.pi * k / sides) for k in range(sides)]
    ys = [radius * math.sin(2 * math.pi * k / sides) for k in range(sides)]
    return max(xs) - min(xs), max(ys) - min(ys)


def _expected_extents(prim):
    p = prim.params
    if prim.kind in ("BOX", "CHAMFERBOX"):
        return p["width"], p["length"], abs(p["height"])
    if prim.kind == "PLANE":
        return p["width"], p["length"], 0.0
    if prim.kind == "CYLINDER":
        return (*_ngon_extents(p["radius"], p["sides"]), abs(p["height"]))
    if prim.kind == "CONE":
        return (*_ngon_extents(max(p["radius1"], p["radius2"]), p["sides"]), abs(p["height"]))
    return None


def _close(a, b):
    return abs(a - b) <= 1e-3 * max(1.0, abs(b))


@pytest.mark.parametrize("relpath, minimum", [
    ("Maps and Materials/maps/Organics/LavaFlowSlateShader/lavaFlowShader.max", 1),
    ("Particle Flow Elements Library/scenes/Water/Boat Wake Spray.max", 2),
    ("Scenes/Characters/Meshes/CreatureSkinned.max", 13),
    ("Scenes/Characters/Meshes/SheK_Character_Rig.max", 2),
])
def test_corpus_sizes_match_modifier_context_boxes(relpath, minimum):
    """Box / Plane / Cylinder / Cone extents rebuilt from the decoded parameters equal the bounding box of the
    bottom modifier's input."""
    checked = 0
    with maxfile.open(corpus_file(relpath)) as mf:
        for prim, box in _bottom_context_boxes(mf):
            expected = _expected_extents(prim)
            if expected is None:
                continue
            extents = [box[k + 3] - box[k] for k in range(3)]
            assert all(_close(e, x) for e, x in zip(extents, expected)), (prim, box)
            checked += 1
    assert checked >= minimum


def test_corpus_cone_sides_from_polygon_extents():
    """A 9-sided cone has X extent r (1 + cos 20 deg) and Y extent 2 r sin 80 deg; with id 3 (4) as the sides
    neither would match."""
    with maxfile.open(corpus_file("Scenes/Characters/Meshes/SheK_Character_Rig.max")) as mf:
        cones = [(p, box) for p, box in _bottom_context_boxes(mf) if p.kind == "CONE"]
    assert cones
    prim, box = cones[0]
    assert prim.params["sides"] == 9 and prim.params["height_segments"] == 4
    r = max(prim.params["radius1"], prim.params["radius2"])
    assert _close(box[3] - box[0], r * (1 + math.cos(math.radians(20))))
    assert _close(box[4] - box[1], 2 * r * math.sin(math.radians(80)))


def test_corpus_box_width_segments_run_along_the_bend_axis():
    """CreatureSkinned's long thin Box (84.3 along X) is bent along X (Bend axis 0) and has 6 width segments."""
    with maxfile.open(corpus_file("Scenes/Characters/Meshes/CreatureSkinned.max")) as mf:
        scene = mf.scene
        found = False
        for obj in scene.objects:
            if obj.class_index != 0x2032:
                continue
            refs = sorted(obj.references.items())
            if len(refs) != 2:
                continue
            prim, mod = scene.decode(scene.objects[refs[1][1]]), scene.decode(scene.objects[refs[0][1]])
            if isinstance(prim, PrimitiveData) and prim.kind == "BOX" and type(mod).__name__ == "ModifierData":
                assert mod.class_name == "Bend" and mod.params["bend_axis"] == 0
                assert prim.params["width"] > 20 * prim.params["length"]
                assert prim.params["width_segments"] == 6 and prim.params["length_segments"] == 1
                found = True
        assert found


@pytest.mark.skipif(not full_corpus_enabled(), reason="set MX_FULL_CORPUS=1")
def test_full_corpus_primitives_decode():
    count = 0
    for path in all_files():
        with maxfile.open(path) as mf:
            for obj in mf.scene.objects:
                if obj.superclass_id == 0x10 and obj.class_id in PRIMITIVES:
                    prim = mf.scene.decode(obj)
                    assert isinstance(prim, PrimitiveData) and prim.param_block is not None, (path, obj.index)
                    count += 1
    assert count == 0 or count > 1000
