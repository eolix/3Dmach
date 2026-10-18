# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
``maxdump`` smoke tests, on a synthetic file that follows the *documented, unverified* layouts of
``docs/format/overview.md`` (see ``synth_max``).
"""

import io
import json
import os
import subprocess
import sys

import pytest

from maxfile import dump
from synth_max import NULL, SceneBuilder, cont, f32, leaf, refs_ordered, text


@pytest.fixture(scope="module")
def max_path(tmp_path_factory):
    b = SceneBuilder()
    dll = b.dll((0x2037, "Test objects"), (0x2039, "test.dlo"))
    node = b.cls("Node", (1, 0), 1)
    prs = b.cls("PRS", (0x2005, 0), 0x9008003)
    bez = b.cls("BezPos", (0x2008, 0), 0x900B)
    box = b.cls("Box", (0x10, 0), 0x10, dll)
    weird = b.cls("WeirdPlugin", (0xABCD, 0x1234), 0x10, dll)
    pos = b.obj(bez, leaf(0x2503, f32(1, 2, 3)))
    ctrl = b.obj(prs, refs_ordered(pos))
    geo = b.obj(box, leaf(0x0100, f32(10.0, 20.0)), leaf(0x0101, b"\x01\x02\x03"))
    for _ in range(2):
        b.obj(weird, cont(0x0001, leaf(0x0002, text("deep"))))
    root = b.node(node, "Root")
    b.node(node, "Box001", parent=root, refs=[ctrl, geo], offset_pos=(0, 0, 1))
    b.node(node, "Box002", parent=root, refs=[NULL, geo])
    path = tmp_path_factory.mktemp("dump") / "synthetic.max"
    path.write_bytes(b.build(compress=("Scene",)))
    return str(path)


def _run(*args):
    out = io.StringIO()
    status = dump.main(list(args), out=out)
    return status, out.getvalue()


def test_summary(max_path):
    status, text_out = _run(max_path)
    assert status == 0
    assert "Compound File v3" in text_out
    assert "gzip" in text_out and "Scene" in text_out
    assert '#3    class=0x00000010, 0x00000000 (0x0000000000000010)' in text_out
    assert 'name="WeirdPlugin"' in text_out
    assert '[5] "Root"' in text_out
    assert '    [6] "Box001"  object=[2] Box  controller=[1] Position/Rotation/Scale  pos=(1, 2, 3)' in text_out
    assert "offset_pos=(0, 0, 1)" in text_out
    assert 'objects=2      #4    class=0x0000ABCD, 0x00001234 (0x000012340000ABCD)' in text_out
    assert '0x2037="Test objects"' in text_out


def test_summary_json(max_path):
    status, out = _run(max_path, "--json")
    assert status == 0
    data = json.loads(out)
    assert {s["path"] for s in data["streams"]} == {"ClassDirectory3", "DllDirectory", "Scene"}
    assert [n["name"] for n in data["nodes"]] == ["Root", "Box001", "Box002"]
    assert data["nodes"][1]["transform"]["position"] == [1.0, 2.0, 3.0]
    assert data["unknown_classes"][0]["name"] == "WeirdPlugin"
    assert data["unknown_classes"][0]["objects"] == 2
    assert data["class_directory"]["classes"][1]["decoder"] == "Position/Rotation/Scale"


def test_chunks(max_path):
    status, out = _run(max_path, "--chunks")
    assert status == 0
    assert "[2] 0x0003 cont" in out and "#3 Box" in out
    assert "0x0100 leaf size=14" in out and "f32=10 20" in out
    assert '0x0002 leaf size=14 @0x' in out and '"deep"' in out
    assert '#0 Node "Box001"' in out


def test_chunks_one_object_with_depth(max_path):
    status, out = _run(max_path, "--object", "3", "--depth", "1")
    assert status == 0
    lines = out.splitlines()[1:]
    assert lines[0].startswith("  [3] 0x0004 cont")
    assert "children=not shown" in lines[1]
    assert len(lines) == 2


def test_chunks_json(max_path):
    status, out = _run(max_path, "--chunks", "--object", "2", "--json")
    assert status == 0
    data = json.loads(out)
    assert data["stream"] == "Scene" and data["compressed"]
    first, *rest = data["chunks"]
    assert first["object"] == 2 and first["class"] == "Box" and first["depth"] == 0
    assert rest[1]["hex"] == "01 02 03"


def test_stream(max_path):
    status, out = _run(max_path, "--stream", "dlldirectory")
    assert status == 0
    assert "== Stream DllDirectory" in out
    assert '0x2039 leaf' in out and '"test.dlo"' in out


def test_errors(max_path, tmp_path, capsys):
    status, _ = _run(max_path, "--object", "999")
    assert status == 1 and "out of range" in capsys.readouterr().err
    status, _ = _run(max_path, "--stream", "Nope")
    assert status == 1 and "no stream named" in capsys.readouterr().err
    bad = tmp_path / "bad.max"
    bad.write_bytes(b"not a max file" * 100)
    status, _ = _run(str(bad))
    assert status == 1 and "not a Compound File" in capsys.readouterr().err
    status, _ = _run(str(tmp_path / "missing.max"))
    assert status == 1
    with pytest.raises(SystemExit):
        _run(max_path, "--stream", "Scene", "--object", "1")


def test_module_entry_point(max_path):
    result = subprocess.run(
        [sys.executable, "-m", "maxfile.dump", max_path, "--depth", "0", "--chunks"],
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(dump.__file__))),
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "[0] 0x0002 cont" in result.stdout
