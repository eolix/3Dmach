# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""The test-file ladder for the maintainer (``python -m maxfile.writer.samples OUT_DIR``) reads back cleanly."""

import io
import os
import zlib

import maxfile
from maxfile import dump
from maxfile.writer import samples

EXPECTED_NODES = {"01_empty.max": 0, "01b_empty_lean.max": 0, "02_box.max": 1, "02b_triangle.max": 1,
                  "03_hierarchy.max": 9, "04_materials.max": 4, "04b_physical.max": 2, "05_units_cm.max": 2,
                  "06_many_objects.max": 100}


def test_samples_ladder(tmp_path):
    names = samples.write_samples(str(tmp_path))
    assert names == list(EXPECTED_NODES)
    readme = (tmp_path / "README.txt").read_text(encoding="utf-8")
    for name in names:
        assert name in readme
        with maxfile.open(str(tmp_path / name)) as mf:
            assert mf.warnings == []
            assert len(mf.nodes) == EXPECTED_NODES[name]
            for node in mf.nodes:
                base, _ = mf.scene.resolve_geometry(node)
                if node.name.startswith("Dummy"):
                    assert base.class_label() == "Dummy"
                else:
                    assert mf.scene.decode(base).warnings == []
                if node.material is not None:
                    assert mf.scene.decode(node.material) is not None
        # maxdump reads every sample without trouble (summary and chunk trees).
        for args in ([], ["--chunks"]):
            out = io.StringIO()
            assert dump.main([str(tmp_path / name)] + args, out=out) == 0
            assert "Warnings (0)" in out.getvalue() or "--chunks" in args
    with maxfile.open(str(tmp_path / "05_units_cm.max")) as mf:
        assert mf.units.unit == "centimeters"
    with maxfile.open(str(tmp_path / "03_hierarchy.max")) as mf:
        by_name = {n.name: n for n in mf.nodes}
        assert by_name["Grandchild_Rot90X"].parent.parent is by_name["Parent_Rot45Z"]
        assert by_name["Hidden_Box"].is_hidden and by_name["Frozen_Box"].is_frozen


def test_checker_png_is_valid():
    data = samples.checker_png(16, 4)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    # IDAT decompresses to 16 rows of filter byte + 16 RGB pixels.
    start = data.index(b"IDAT") + 4
    length = int.from_bytes(data[start - 8:start - 4], "big")
    assert len(zlib.decompress(data[start:start + length])) == 16 * (1 + 16 * 3)


def test_samples_cli(tmp_path, capsys):
    assert samples.main([str(tmp_path / "out")]) == 0
    assert os.path.isfile(tmp_path / "out" / "02_box.max")
    assert "README" in capsys.readouterr().out
