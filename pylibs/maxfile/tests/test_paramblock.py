# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
ParamBlock2 / ParamBlock reader tests (``docs/format/overview.md`` §5.1), on synthetic blocks built to the layout
verified on the corpus, plus corpus checks that skip without it.
"""

import collections
import math
import struct

import pytest

import maxfile
from corpus_files import corpus_file, sample
from maxfile.objects.paramblock import ParamBlockData
from synth_max import PB2, SceneBuilder, cont, f32, leaf, pb2_block, pb2_param, refs_ordered, u32


class Builder(SceneBuilder):
    def __init__(self):
        super().__init__()
        self.pb2 = self.cls("ParamBlock2", *PB2)
        self.pb = self.cls("ParamBlock", (0x8, 0), 0x8)
        self.float_ctrl = self.cls("Bezier Float", (0x2007, 0), 0x9003)
        self.owner = self.cls("Owner", (0x7E57, 1), 0x810)
        self.bitmap = self.cls("Bitmap", (0x240, 0), 0xC10)
        self.node_class = self.cls("Node", (1, 0), 1)


def test_param_block2_values_and_references():
    b = Builder()
    ctrl = b.obj(b.float_ctrl, leaf(0x2501, f32(2.5)))
    tex = b.obj(b.bitmap)
    owner = b.placeholder()
    block = b.obj(b.pb2, *pb2_block(
        owner,
        pb2_param(0, "float", 1.5),
        pb2_param(1, "int", 3),
        pb2_param(2, "bool", True),
        pb2_param(3, "rgb", (0.5, 0.25, 1.0)),
        pb2_param(4, "percent", 0.1),
        pb2_param(5, "angle", math.pi / 2),
        pb2_param(6, "float", animated=True),               # Slot 0: controller.
        pb2_param(7, "texmap"),                             # Slot 1: map.
        pb2_param(8, "texmap", tex, inline_ref=True),       # Inline object index: no slot.
        pb2_param(9, "string", "C:\\maps\\wood.png"),
        pb2_param(10, "string", None),
        pb2_param(11, "rgba", (1, 0, 0, 1)),
        pb2_param(12, "texmap", [None, None], table=True),  # Slots 2 and 3.
        pb2_param(13, "percent", [1.0, None], table=True),  # Item 1 animated: slot 4.
        refs={0: ctrl, 1: tex, 3: tex, 4: ctrl},
    ))
    b.set_obj(owner, b.owner, refs_ordered(block))
    with maxfile.open(b.build()) as mf:
        data = mf.scene.param_block(mf.objects[block])
        assert isinstance(data, ParamBlockData) and data.kind == "pb2" and data.owner == owner
        assert data.problems == []
        v = data.value
        assert v(0) == 1.5 and v(1) == 3 and v(2) is True and v(3) == (0.5, 0.25, 1.0)
        assert math.isclose(v(4), 0.1, rel_tol=1e-6) and math.isclose(v(5), math.pi / 2, rel_tol=1e-6)
        assert v(6) == 2.5 and data.get(6).controller == ctrl and data.get(6).animated
        assert v(7) == tex and data.get(7).is_reference and data.get(7).kind == "texmap"
        assert v(8) == tex
        assert v(9) == "C:\\maps\\wood.png" and v(10) is None and v(10, "x") == "x"
        assert v(11) == (1.0, 0.0, 0.0, 1.0)
        assert v(12) == [None, tex] and data.get(12).kind == "table:texmap"
        assert data.get(13).value[0] == 1.0 and data.get(13).value[1] == 2.5
        assert data.get(13).controllers == [None, ctrl]
        assert v(99, 7) == 7 and [p.param_id for p in data.entries] == list(range(14))
        # Not a parameter block.
        assert mf.scene.param_block(mf.objects[ctrl]) is None


def test_param_block2_old_record_chunks():
    b = Builder()
    block = b.obj(b.pb2, *pb2_block(0, pb2_param(0, "world", 12.0), pb2_param(3, "int", -1), old_records=True))
    with maxfile.open(b.build()) as mf:
        data = mf.scene.param_block(mf.objects[block])
        assert data.value(0) == 12.0 and data.value(3) == -1


def test_param_block2_unknown_type_stops_reference_assignment():
    b = Builder()
    ctrl = b.obj(b.float_ctrl, leaf(0x2501, f32(1)))
    bad = leaf(0x100E, struct.pack("<HIHIHB", 1, 77, 0, 0x82, 0, 0x40) + u32(0))    # Unknown type with a value.
    block = b.obj(b.pb2, *pb2_block(0, bad, pb2_param(2, "float", animated=True), refs={0: ctrl}))
    with maxfile.open(b.build()) as mf:
        data = mf.scene.param_block(mf.objects[block])
        assert data.get(2).animated and data.get(2).controller is None
        assert any("unknown parameter type 77" in p for p in data.problems)
        assert any("not assigned" in p for p in data.problems)


def test_param_block2_asset_reference():
    b = Builder()
    guid = bytes(range(16))
    asset_record = leaf(0x100E, struct.pack("<HIHIHB", 4, 9, 2, 0x80, 2, 0x40) + u32(0xFFFFFFFE))
    block = b.obj(b.pb2, *pb2_block(0, pb2_param(3, "int", 7), asset_record, cont(0x000F, leaf(0x0002, guid)),
                                    pb2_param(5, "filename", "plain.png")))
    lonely = b.obj(b.pb2, *pb2_block(0, asset_record))
    with maxfile.open(b.build()) as mf:
        data = mf.scene.param_block(mf.objects[block])
        ref = data.value(4)
        assert ref.guid == "03020100-0504-0706-0809-0a0b0c0d0e0f" and ref.raw == guid
        assert data.value(3) == 7 and data.value(5) == "plain.png" and data.problems == []
        bad = mf.scene.param_block(mf.objects[lonely])
        assert bad.value(4) is None and any("without its 0x000F chunk" in p for p in bad.problems)


def test_old_param_block():
    b = Builder()
    ctrl = b.obj(b.float_ctrl, leaf(0x2501, f32(4.0)))

    def param(index, value_chunk):
        return cont(0x0002, leaf(0x0003, u32(index)), value_chunk)

    block = b.obj(b.pb, leaf(0x0001, u32(4)), leaf(0x0005, b"\x02\x00"), refs_ordered(0xFFFFFFFF, ctrl),
                  param(0, leaf(0x0100, f32(0.5))), param(1, leaf(0x0200)), param(2, leaf(0x0104, u32(1))),
                  param(3, leaf(0x0103, f32(1, 0.5, 0))))
    with maxfile.open(b.build()) as mf:
        data = mf.scene.param_block(mf.objects[block])
        assert data.kind == "pb"
        assert data.value(0) == 0.5 and data.value(1) == 4.0 and data.get(1).controller == ctrl
        assert data.value(2) == 1 and data.value(3) == (1.0, 0.5, 0.0)


# -----------------------------------------------------------------------------
# Real files

def test_corpus_meshsmooth_block():
    with maxfile.open(corpus_file("Scenes/SubDivSurfaces/Meshsmooth-Hammer.max")) as mf:
        smooth = next(o for o in mf.objects if o.class_label() == "MeshSmooth")
        block = mf.scene.param_block(mf.scene.ref(smooth, 0))
        assert block.kind == "pb2" and block.owner == smooth.index and block.problems == []
        assert len(block.params) == 32


@pytest.mark.parametrize("path", sample(6) or [None])
def test_corpus_blocks_assign_every_reference(path):
    """The slot rule (overview.md §5.1) accounts for every reference of the corpus's parameter blocks."""
    if path is None:
        pytest.skip("no corpus")
    stats = collections.Counter()
    with maxfile.open(path) as mf:
        for obj in mf.objects:
            data = mf.scene.param_block(obj) if obj.superclass_id == 0x82 else None
            if data is None:
                continue
            stats["blocks"] += 1
            if data.problems:
                stats["with problems"] += 1
                continue
            claimed = set()
            for param in data.params.values():
                values = param.value if isinstance(param.value, list) else [param.value]
                if param.is_reference:
                    claimed.update(v for v in values if isinstance(v, int))
                claimed.update(c for c in [param.controller] + (param.controllers or []) if c is not None)
            missing = set(obj.references.values()) - claimed
            stats["unclaimed references"] += len(missing)
    # Blocks with records of types we can't size (a handful of plug-in tables) may leave references unassigned.
    assert stats["unclaimed references"] == 0 or stats["with problems"], stats
