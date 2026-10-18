# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
``maxdump`` output for decoded data (geometry, primitives, modifier stacks, materials, ``--decode``), on a
synthetic file built to the layouts of ``docs/format/overview.md`` (verified on the local corpus).
"""

import io
import json

import pytest

from maxfile import dump, report
from synth_max import (PB2, NULL, SceneBuilder, cont, leaf, pb2_block, pb2_param, poly_mesh, refs_ordered, text,
                       u32)

CUBE = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]
QUADS = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]


@pytest.fixture(scope="module")
def max_path(tmp_path_factory):
    b = SceneBuilder()
    node = b.cls("Node", (1, 0), 1)
    poly = b.cls("Editable Poly", (0x1BF8338D, 0x192F6098), 0x10)
    box = b.cls("Box", (0x10, 0), 0x10)
    modifier = b.cls("TurboThing", (0x7E57, 1), 0x810)
    block = b.cls("ParamBlock2", *PB2)
    multi = b.cls("Multi/Sub-Object", (0x200, 0), 0xC00)
    bitmap = b.cls("Bitmap?", (0x7E57, 3), 0xC10)

    geo = b.obj(poly, poly_mesh(CUBE, QUADS, material_ids=[0, 1] * 3, channels={1: ([(0, 0, 0)] * 4,
                                                                                    [(0, 1, 2, 3)] * 6)}))
    mod = b.obj(modifier)
    stack = b.obj(0x2032, refs_ordered(mod, geo))                                       # [2]
    prim_block = b.obj(block, *pb2_block(4, pb2_param(0, "world", 10.0), pb2_param(1, "world", 20.0),
                                         pb2_param(2, "world", 30.0)))
    prim = b.obj(box, refs_ordered(prim_block))                                         # [4]
    tex_block = b.obj(block, cont(0x0005, leaf(0x1230, text("C:\\maps\\wood.png"))))
    tex = b.obj(bitmap, refs_ordered(tex_block))                                        # [6]
    b.obj(block, *pb2_block(9, pb2_param(1, "int", 3)))                                 # [7]
    b.obj(block)                                                                        # [8]
    mm = b.obj(multi, cont(0x4000, leaf(0x4001, text("Wood set")), leaf(0x4003, u32(0))),
               refs_ordered(7, tex))                                                    # [9]
    root = b.node(node, "Root")
    b.node(node, "Thing", parent=root, refs=[NULL, stack, NULL, mm])                    # [11]
    b.node(node, "Crate", parent=root, refs=[NULL, prim])
    path = tmp_path_factory.mktemp("dump_decoded") / "synthetic.max"
    path.write_bytes(b.build())
    return str(path)


def _run(*args):
    out = io.StringIO()
    status = dump.main(list(args), out=out)
    return status, out.getvalue()


def test_summary_sections(max_path):
    status, out = _run(max_path)
    assert status == 0, out
    assert "== Geometry (1) ==" in out
    assert "[0] Editable Poly  source=editable_poly vertices=8 faces=6 corners=24 channels=1 material_ids=1,2" in out
    assert "[4] Box  kind=BOX  length=10  width=20  height=30" in out and "encoding=pb2" in out
    assert "[2] Derived Object  base=[0] Editable Poly  modifiers=[1] TurboThing" in out
    assert '[9] Multi/Sub-Object "Wood set"' in out or "[9] Multimaterial" in out
    assert '[11] "Thing"  object=[2] Derived Object' in out and "geometry=[0] Editable Poly  modifiers=1" in out


def test_summary_json(max_path):
    status, out = _run(max_path, "--json")
    assert status == 0
    data = json.loads(out)
    assert data["geometry"][0]["mesh"]["faces"] == 6
    assert {k: data["primitives"][0]["params"][k] for k in ("length", "width", "height")} == {
        "length": 10.0, "width": 20.0, "height": 30.0}
    assert data["modifier_stacks"][0]["modifiers"][0]["index"] == 1
    assert data["materials"][0]["index"] == 9
    thing = next(n for n in data["nodes"] if n["name"] == "Thing")
    assert thing["geometry"]["index"] == 0 and [m["index"] for m in thing["modifiers"]] == [1]


def test_decode_object(max_path):
    status, out = _run(max_path, "--object", "9", "--decode")
    assert status == 0, out
    assert "== Object [9] Multi/Sub-Object" in out and "kind=material" in out
    assert "decoded:\nMaterialData" in out
    assert "references: 0=[7] ParamBlock2  1=[6] Bitmap?" in out
    assert "parameter block [7] (pb2 id=1, 1 parameters) in reference slot 0:\n  id=1 int=3" in out
    status, out = _run(max_path, "--object", "4", "--decode")
    assert "id=0 world=10" in out
    status, out = _run(max_path, "--object", "11", "--decode")
    assert 'node: name="Thing"' in out and "modifiers=[1] TurboThing" in out


def test_decode_object_json(max_path):
    status, out = _run(max_path, "--object", "0", "--decode", "--json")
    assert status == 0
    data = json.loads(out)
    assert data["value"]["type"] == "MeshData" and len(data["value"]["faces"]) == 6
    assert data["value"]["map_channels"]["1"]["faces"][0] == [0, 1, 2, 3]


def test_decode_errors(max_path, capsys):
    status, _ = _run(max_path, "--object", "500", "--decode")
    assert status == 1 and "out of range" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        _run(max_path, "--decode")


def test_report_helpers():
    assert report.to_plain({1: (1.0, float("nan")), "b": b"\x01\x02"}) == {"1": [1.0, "nan"], "b": "01 02"}
    text_ = report.format_value(list(range(20)), max_items=3)
    assert text_ == "[0, 1, 2, ... (20 total)]"
