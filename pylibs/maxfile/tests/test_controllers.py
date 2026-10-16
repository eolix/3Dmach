# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Transform controller decoding tests.

Class IDs and value chunks are the *documented, unverified* assumptions of ``docs/format/overview.md`` §4.1;
the fixtures (``synth_max``) encode them, so these tests check our decoders against the documentation only.
"""

import math

import pytest

import maxfile
from maxfile import transform
from synth_max import NULL, SceneBuilder, cont, f32, leaf, max_quat, refs_ordered

ID = {
    "prs": (0x2005, 0),
    "bezier_pos": (0x2008, 0),
    "tcb_pos": (0x442312, 0),
    "pos_xyz": (0x118F7E02, 0xFFEE238A),
    "pos_list": (0x4B4B1002, 0),
    "euler": (0x2012, 0),
    "tcb_rot": (0x442313, 0),
    "rot_wire": (0x31381913, 0x3A904167),
    "rot_list": (0x4B4B1003, 0),
    "scale_xyz": (0x118F7C01, 0xFEEE238B),
    "bezier_scale": (0x2010, 0),
    "tcb_zoom": (0x442315, 0),
    "bezier_float": (0x2007, 0),
    "float_wire": (0x498702E7, 0x71F11549),
    "biped": (0x9154, 0),
}


class Builder(SceneBuilder):
    def __init__(self):
        super().__init__()
        self.node_class = self.cls("Node", (1, 0), 1)
        self.c = {key: self.cls(key, cid, 0x9000) for key, cid in ID.items()}

    def ctrl(self, key, *children):
        return self.obj(self.c[key], *children)

    def float_ctrl(self, value):
        return self.ctrl("bezier_float", cont(0x7127, leaf(0x2501, f32(value))))

    def scene_node(self, controller, name="N"):
        return self.node(self.node_class, name, refs=[controller])


def _open(b):
    return maxfile.open(b.build())


def _approx(a, b):
    return all(math.isclose(x, y, abs_tol=1e-6) for x, y in zip(a, b)) and len(a) == len(b)


def test_prs_with_key_controllers():
    b = Builder()
    pos = b.ctrl("bezier_pos", leaf(0x2503, f32(1, 2, 3)))
    rot = b.ctrl("tcb_rot", leaf(0x2504, max_quat(0.5, 0.5, 0.5, 0.5)))
    scale = b.ctrl("bezier_scale", leaf(0x2501, f32(2, 3, 4)))
    prs = b.ctrl("prs", refs_ordered(pos, rot, scale))
    n = b.scene_node(prs)
    with _open(b) as mf:
        t = mf.scene.node(n).transform
        assert t.position == (1.0, 2.0, 3.0)
        assert t.rotation == (0.5, 0.5, 0.5, 0.5)
        assert t.scale == (2.0, 3.0, 4.0)
        assert mf.warnings == []


def test_quaternion_order_from_file():
    # Unverified (overview.md §4.1): file order q0..q3 maps to (w, x, y, z) = (q3, q2, q1, q0).
    b = Builder()
    rot = b.ctrl("tcb_rot", leaf(0x2504, f32(0.1, 0.2, 0.3, 0.4)))
    n = b.scene_node(b.ctrl("prs", refs_ordered(NULL, rot)))
    with _open(b) as mf:
        assert _approx(mf.scene.node(n).transform.rotation, (0.4, 0.3, 0.2, 0.1))


def test_xyz_controllers_and_euler():
    b = Builder()
    pos = b.ctrl("pos_xyz", refs_ordered(b.float_ctrl(1), b.float_ctrl(2), b.float_ctrl(3)))
    rot = b.ctrl("euler", refs_ordered(b.float_ctrl(0), b.float_ctrl(0), b.float_ctrl(math.pi / 2)))
    scale = b.ctrl("scale_xyz", refs_ordered(b.float_ctrl(1), b.float_ctrl(1), b.float_ctrl(5)))
    n = b.scene_node(b.ctrl("prs", refs_ordered(pos, rot, scale)))
    with _open(b) as mf:
        t = mf.scene.node(n).transform
        assert t.position == (1.0, 2.0, 3.0)
        assert _approx(t.rotation, (math.cos(math.pi / 4), 0, 0, math.sin(math.pi / 4)))
        assert t.scale == (1.0, 1.0, 5.0)
        m = t.matrix()
        # 90 degrees about Z, then scale, then translate: local X axis maps to world +Y.
        assert _approx([m[0][0], m[1][0], m[2][0]], [0, 1, 0])
        assert _approx([m[0][3], m[1][3], m[2][3]], [1, 2, 3])
        assert _approx([m[0][2], m[1][2], m[2][2]], [0, 0, 5])


def test_tcb_position_tcb_zoom_uniform():
    b = Builder()
    pos = b.ctrl("tcb_pos", leaf(0x2503, f32(-1, 0, 7)))
    scale = b.ctrl("tcb_zoom", leaf(0x2505, f32(3)))
    n = b.scene_node(b.ctrl("prs", refs_ordered(pos, NULL, scale)))
    with _open(b) as mf:
        t = mf.scene.node(n).transform
        assert t.position == (-1.0, 0.0, 7.0) and t.rotation is None and t.scale == (3.0, 3.0, 3.0)


def test_list_and_wire_use_first_reference():
    b = Builder()
    inner_pos = b.ctrl("bezier_pos", leaf(0x2503, f32(4, 5, 6)))
    other_pos = b.ctrl("bezier_pos", leaf(0x2503, f32(9, 9, 9)))
    pos_list = b.ctrl("pos_list", refs_ordered(inner_pos, other_pos))
    inner_rot = b.ctrl("tcb_rot", leaf(0x2504, max_quat(1, 0, 0, 0)))
    rot_list = b.ctrl("rot_list", refs_ordered(b.ctrl("rot_wire", refs_ordered(inner_rot))))
    n = b.scene_node(b.ctrl("prs", refs_ordered(pos_list, rot_list)))
    fw = b.ctrl("float_wire", refs_ordered(b.float_ctrl(2.5)))
    with _open(b) as mf:
        t = mf.scene.node(n).transform
        assert t.position == (4.0, 5.0, 6.0) and t.rotation == (1.0, 0.0, 0.0, 0.0)
        assert mf.scene.decode(mf.objects[fw]) == 2.5


def test_unknown_controller_is_reported():
    b = Builder()
    biped = b.ctrl("biped")
    n = b.scene_node(biped)
    unknown_class = b.cls("MysteryCtrl", (0xDEAD, 0xBEEF), 0x9000)
    m = b.scene_node(b.obj(unknown_class), "M")
    with _open(b) as mf:
        assert mf.scene.node(n).transform is None and mf.scene.node(m).transform is None
        assert mf.scene.undecoded == {"Biped slave control": 1, "MysteryCtrl": 1}
        assert any("transform controller Biped slave control not decoded" in w for w in mf.warnings)


def test_prs_with_undecodable_component():
    b = Builder()
    pos = b.ctrl("bezier_pos")      # No 0x2503 value chunk.
    rot = b.ctrl("biped")           # No decoder.
    # A position controller in the scale slot still gives a 3-vector, which is accepted.
    scale = b.ctrl("bezier_pos", leaf(0x2503, f32(1, 1, 1)))
    n = b.scene_node(b.ctrl("prs", refs_ordered(pos, rot, scale)))
    # A 3-vector in the rotation slot is rejected.
    bad_rot = b.ctrl("bezier_pos", leaf(0x2503, f32(1, 1, 1)))
    m = b.scene_node(b.ctrl("prs", refs_ordered(NULL, bad_rot)), "M")
    with _open(b) as mf:
        t = mf.scene.node(n).transform
        assert t.position is None and t.rotation is None and t.scale == (1.0, 1.0, 1.0)
        assert mf.scene.node(m).transform.rotation is None
        warnings = "\n".join(mf.warnings)
        assert "no position value chunk" in warnings
        assert "not a rotation value" in warnings


@pytest.mark.parametrize("children,match", [
    ((leaf(0x2503, f32(1, 2)),), "has 2 float"),
    ((), "no position value chunk"),
])
def test_bad_value_chunks(children, match):
    b = Builder()
    pos = b.ctrl("bezier_pos", *children)
    with _open(b) as mf:
        assert mf.scene.decode(mf.objects[pos]) is None
        assert any(match in w for w in mf.warnings)


def test_bezier_float_needs_holder():
    b = Builder()
    f = b.ctrl("bezier_float", leaf(0x2501, f32(1)))
    with _open(b) as mf:
        assert mf.scene.decode(mf.objects[f]) is None
        assert any("no 0x7127 chunk" in w for w in mf.warnings)


def test_xyz_missing_component():
    b = Builder()
    p = b.ctrl("pos_xyz", refs_ordered(b.float_ctrl(1), b.float_ctrl(2)))
    with _open(b) as mf:
        assert mf.scene.decode(mf.objects[p]) is None
        assert any("position Z controller in reference slot 2" in w for w in mf.warnings)


def test_reference_cycle_terminates():
    b = Builder()
    a = b.placeholder()
    c = b.ctrl("pos_list", refs_ordered(a))
    b.set_obj(a, b.c["rot_wire"], refs_ordered(c))
    n = b.scene_node(b.ctrl("prs", refs_ordered(c)))
    with _open(b) as mf:
        assert mf.scene.node(n).transform.position is None
        assert any("reference cycle" in w for w in mf.warnings)


def test_deep_reference_chain_is_bounded():
    b = Builder()
    current = b.ctrl("bezier_pos", leaf(0x2503, f32(1, 1, 1)))
    for _ in range(500):
        current = b.ctrl("pos_list", refs_ordered(current))
    with _open(b) as mf:
        assert mf.scene.decode(mf.objects[current]) is None
        assert any("nested more than" in w for w in mf.warnings)


def test_decode_is_cached():
    b = Builder()
    pos = b.ctrl("bezier_pos", leaf(0x2503, f32(1, 2, 3)))
    with _open(b) as mf:
        assert mf.scene.decode(mf.objects[pos]) is mf.scene.decode(mf.objects[pos])
        assert mf.scene.decode(None) is None


def test_world_matrix():
    b = Builder()
    p_ctrl = b.ctrl("prs", refs_ordered(b.ctrl("bezier_pos", leaf(0x2503, f32(10, 0, 0)))))
    c_ctrl = b.ctrl("prs", refs_ordered(b.ctrl("bezier_pos", leaf(0x2503, f32(0, 5, 0)))))
    parent = b.node(b.node_class, "P", refs=[p_ctrl])
    child = b.node(b.node_class, "C", parent=parent, refs=[c_ctrl])
    with _open(b) as mf:
        m = mf.scene.node(child).world_matrix()
        assert _approx([m[0][3], m[1][3], m[2][3]], [10, 5, 0])


def test_transform_helpers():
    assert transform.compose(None, None, None) == transform.IDENTITY
    assert transform.quat_to_matrix3((0, 0, 0, 0)) == ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    q = transform.euler_xyz_to_quat(math.pi / 2, 0, 0)
    assert _approx(q, (math.cos(math.pi / 4), math.sin(math.pi / 4), 0, 0))
    assert transform.matmul(transform.IDENTITY, transform.IDENTITY) == transform.IDENTITY
    assert transform.quat_from_max((1, 2, 3, 4)) == (4, 3, 2, 1)
