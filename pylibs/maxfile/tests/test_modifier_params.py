# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Modifier parameter decoders (:mod:`maxfile.objects.modifier_params`): synthetic modifiers built to the layouts
found on the corpus, plus corpus checks (skipped without the corpus).
"""

import struct

import pytest

import maxfile
from corpus_files import all_files, corpus_file, full_corpus_enabled
from maxfile.objects.modifier_params import CLASS_IDS, MODIFIER_PARAMS, ModifierData
from synth_max import PB2, SceneBuilder, cont, f32, leaf, pb2_block, pb2_param, refs_ordered, text, u32


def old_pb(values):
    """Old ParamBlock children: 0x0002 container per parameter with 0x0003 (index) and a value chunk
    (0x0100 float, 0x0101 int, 0x0103 colour / 3 floats)."""
    children = [leaf(0x0001, u32(len(values)))]
    for index, value in enumerate(values):
        if isinstance(value, tuple):
            body = leaf(0x0103, f32(*value))
        elif isinstance(value, float):
            body = leaf(0x0100, f32(value))
        else:
            body = leaf(0x0101, struct.pack("<i", value))
        children.append(cont(0x0002, leaf(0x0003, u32(index)), body))
    return children


def state(name="", *markers):
    """The 0x39BF container: 0x0100 display name (UTF-16) and empty marker leaves."""
    return cont(0x39BF, leaf(0x0100, text(name)), *(leaf(m) for m in markers))


def split(cid):
    return cid & 0xFFFFFFFF, cid >> 32


class Builder(SceneBuilder):
    def __init__(self):
        super().__init__()
        self.pb2 = self.cls("ParamBlock2", *PB2)
        self.pb = self.cls("ParamBlock", (0x8, 0), 0x8)
        self.prs = self.cls("Position/Rotation/Scale", (0x2005, 0), 0x9008)
        self.mods = {name: self.cls(name, split(cid), 0x810) for name, cid in CLASS_IDS.items()}

    def modifier(self, name, block_class, block_children, slot, extra=(), gizmo_slot=None):
        refs = [0xFFFFFFFF] * (slot + 1)
        if gizmo_slot is not None:
            refs[gizmo_slot] = self.obj(self.prs)
        owner = self.placeholder()
        refs[slot] = self.obj(block_class, *block_children)
        self.set_obj(owner, self.mods[name], refs_ordered(*refs), leaf(0x204B, b"\x2e"), *extra)
        return owner


def _decode(data, index):
    with maxfile.open(data) as mf:
        return mf.scene.decode(mf.objects[index]), list(mf.scene.warnings)


def test_turbosmooth_params_name_and_markers():
    b = Builder()
    mod = b.modifier("TurboSmooth", b.pb2, pb2_block(
        0, pb2_param(0, "int", 1), pb2_param(1, "bool", True), pb2_param(2, "int", 2), pb2_param(4, "bool", True),
        pb2_param(30, "float", 7.0)), 0, extra=[state("Smooth body", 0x0110, 0x0120)])
    data, warnings = _decode(b.build(), mod)
    assert isinstance(data, ModifierData) and data.class_name == "TurboSmooth"
    assert data.params == {"iterations": 1, "use_render_iterations": True, "render_iterations": 2,
                           "smooth_result": True}
    assert data.name == "Smooth body" and data.state_flags == (0x0110, 0x0120) and data.enabled is None
    assert data.unknown_params == {30: 7.0} and data.guessed == ["smooth_result"]
    assert warnings == []


def test_bend_block_in_slot_2_with_gizmo():
    b = Builder()
    mod = b.modifier("Bend", b.pb2, pb2_block(
        0, pb2_param(0, "float", 90.0), pb2_param(1, "float", 0.0), pb2_param(2, "int", 2),
        pb2_param(3, "bool", False), pb2_param(4, "float", -1.5), pb2_param(5, "float", 2.5)), 2,
        extra=[state()], gizmo_slot=0)
    data, _ = _decode(b.build(), mod)
    assert data.params == {"bend_angle": 90.0, "bend_direction": 0.0, "bend_axis": 2, "limit_effect": False,
                           "lower_limit": -1.5, "upper_limit": 2.5}
    assert data.gizmo == mod - 1 and data.name is None and data.state_flags == ()


def test_uvw_map_old_param_block_in_slot_1():
    b = Builder()
    values = [4, 1.0, 2.0, 1.0, 0, 1, 0, 0, 0, 10.0, 20.0, 30.0, 2, 3, 0, 0]
    mod = b.modifier("UVW Map", b.pb, old_pb(values), 1, extra=[state("UVW Mapping")], gizmo_slot=0)
    data, _ = _decode(b.build(), mod)
    p = data.params
    assert p["map_type"] == 4 and p["v_tile"] == 2.0 and p["v_flip"] is True and p["u_flip"] is False
    assert (p["length"], p["width"], p["height"]) == (10.0, 20.0, 30.0) and p["axis"] == 2 and p["channel"] == 3
    assert data.name == "UVW Mapping" and set(data.unknown_params) == {8, 14, 15}


def test_noise_strength_is_a_vector():
    b = Builder()
    mod = b.modifier("Noise", b.pb, old_pb([0, 100.0, 1, 0.2, 6.0, 0, 0.25, 0, (1.0, 2.0, 3.0)]), 2,
                     gizmo_slot=0)
    data, _ = _decode(b.build(), mod)
    assert data.params["strength"] == (1.0, 2.0, 3.0) and data.params["fractal"] is True
    assert data.params["scale"] == 100.0 and data.params["iterations"] == 6.0


def test_unwrap_channel_and_edit_poly_state_wrapper():
    b = Builder()
    unwrap = b.modifier("Unwrap UVW", b.pb2, pb2_block(0, pb2_param(4, "bool", True)), 95,
                        extra=[state(), leaf(0x0190, u32(2))])
    edit = b.modifier("Edit Poly", b.pb2, pb2_block(0, pb2_param(0, "int", 0)), 0,
                      extra=[cont(0x0080, state("Edit Poly", 0x0110))])
    data = b.build()
    value, _ = _decode(data, unwrap)
    assert value.params == {"channel": 2} and "channel" in value.guessed and value.notes
    value, _ = _decode(data, edit)
    assert value.params == {} and value.name == "Edit Poly" and value.state_flags == (0x0110,)


def test_animated_without_static_value_is_unresolved():
    b = Builder()
    mod = b.modifier("Push", b.pb2, pb2_block(0, pb2_param(0, "float", animated=True)), 0)
    data, warnings = _decode(b.build(), mod)
    assert data.params == {} and data.unresolved == ["push_value"] and warnings == []


def test_tables():
    assert set(CLASS_IDS) <= set(MODIFIER_PARAMS)
    for name, (_slot, _gizmo, table) in MODIFIER_PARAMS.items():
        ids = [entry[0] for entry in table]
        assert len(ids) == len(set(ids)), name


# -----------------------------------------------------------------------------
# Corpus

def _stack_objects(mf, obj):
    refs = sorted(obj.references.items())
    return [mf.scene.objects[i] for _slot, i in refs]


def _context_boxes(obj):
    out = []
    for context in obj.chunk.children:
        if context.type == 0x2500:
            box = context.find(0x2511)
            out.append(struct.unpack_from("<6f", box.data) if box is not None else None)
    return out


def test_corpus_meshsmooth_iterations():
    with maxfile.open(corpus_file("Scenes/SubDivSurfaces/Meshsmooth-Hammer.max")) as mf:
        smooth = [mf.scene.decode(o) for o in mf.objects if o.class_label() == "MeshSmooth"]
    assert len(smooth) == 1 and smooth[0].params["iterations"] == 2
    assert smooth[0].params["use_render_iterations"] is False


def test_corpus_meshsmooth_iterations_from_vertex_counts():
    """FishAnim: Unwrap UVW above the MeshSmooth stores 706 positions; the base mesh has 46 vertices forming 44
    quads with 88 edges: one NURMS iteration gives 46 + 88 + 44 = 178 vertices (352 edges, 176 quads), the second
    178 + 352 + 176 = 706. The MeshSmooth says 2 iterations."""
    with maxfile.open(corpus_file("Scenes/SubDivSurfaces/Meshsmooth-FishAnim .max")) as mf:
        stacks = [o for o in mf.objects if o.class_index == 0x2032
                  and [m.class_label() for m in _stack_objects(mf, o)][:5] == [
                      "Wave", "Mesh Select", "Unwrap UVW", "UVW Map", "MeshSmooth"]]
        assert len(stacks) == 1
        mods = _stack_objects(mf, stacks[0])
        assert mf.scene.decode(mods[4]).params["iterations"] == 2
        unwrap_context = [c for c in stacks[0].chunk.children if c.type == 0x2500][2]
        positions = unwrap_context.find(0x2512).find(0x0330)
        assert struct.unpack_from("<I", positions.data)[0] == 706


def test_corpus_symmetry_flip_keeps_the_negative_side():
    """TigerTank: the Symmetry's input spans X -61.65..49.2, the next modifier's input -61.65..61.65: the -X half
    was kept and mirrored. Its flip parameter is on and its axis is 0 (X)."""
    with maxfile.open(corpus_file("Scenes/DirectXFeatures/TigerTank.max")) as mf:
        for obj in mf.objects:
            if obj.class_index != 0x2032:
                continue
            mods = _stack_objects(mf, obj)[:-1]
            names = [m.class_label() for m in mods]
            if "Symmetry" not in names:
                continue
            i = names.index("Symmetry")
            sym = mf.scene.decode(mods[i])
            boxes = _context_boxes(obj)
            before, after = boxes[i], boxes[i - 1]
            assert sym.params["axis"] == 0 and sym.params["flip"] is True
            assert after[0] == pytest.approx(before[0]) and after[3] == pytest.approx(-before[0], rel=1e-4)
            assert before[3] < after[3]
            return
    pytest.fail("no Symmetry stack")


def test_corpus_bend_axis_z_on_a_tall_cone():
    with maxfile.open(corpus_file("Scenes/Atmospherics/Fire-FireEffect.max")) as mf:
        bends = [mf.scene.decode(o) for o in mf.objects if o.class_label() == "Bend"]
    assert bends and all(b.params["bend_axis"] == 2 for b in bends if "bend_axis" in b.params)


@pytest.mark.skipif(not full_corpus_enabled(), reason="set MX_FULL_CORPUS=1")
def test_full_corpus_modifiers_decode():
    ids = {cid for cid in CLASS_IDS.values()}
    count = 0
    for path in all_files():
        with maxfile.open(path) as mf:
            for obj in mf.objects:
                if obj.superclass_id != 0x810 or obj.class_id is None:
                    continue
                if (obj.class_id.a | (obj.class_id.b << 32)) in ids:
                    data = mf.scene.decode(obj)
                    assert isinstance(data, ModifierData), (path, obj.index)
                    count += 1
    assert count == 0 or count > 2000
