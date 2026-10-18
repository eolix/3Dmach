# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Tests for the Blender-independent importer helpers. Run with: pytest tests/importer"""

import importlib.util
import os
import sys

import pytest

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts", "modules"))

from mx_common import report as mx_report  # noqa: E402
from mx_common import units  # noqa: E402


def load_addon_module(name):
    # The add-on package imports `bpy` in `__init__`, so load its pure modules by path.
    path = os.path.join(ROOT, "scripts", "addons_core", "mx_io_max", name + ".py")
    spec = importlib.util.spec_from_file_location("mx_io_max_" + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


smoothing = load_addon_module("smoothing")
material_ids = load_addon_module("material_ids")

# A cube: bottom 0-3, top 4-7. Faces: bottom, top, then four sides.
CUBE = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]


class TestSmoothing:

    def test_all_one_group_is_smooth(self):
        edges, faces = smoothing.sharp_from_smoothing_groups(CUBE, [1] * 6)
        assert edges == set()
        assert faces == [False] * 6

    def test_box_style_groups(self):
        # Max's Box gives each side its own group: every edge between sides is sharp.
        edges, faces = smoothing.sharp_from_smoothing_groups(CUBE, [1 << i for i in range(6)])
        assert len(edges) == 12
        assert faces == [False] * 6

    def test_shared_bit_smooths(self):
        # Sides share bit 2; caps have their own groups: only the 8 cap edges are sharp.
        groups = [1, 2, 4, 4 | 8, 4, 4]
        edges, _ = smoothing.sharp_from_smoothing_groups(CUBE, groups)
        assert edges == {(0, 3), (2, 3), (1, 2), (0, 1), (4, 5), (5, 6), (6, 7), (4, 7)}

    def test_no_group_is_faceted(self):
        edges, faces = smoothing.sharp_from_smoothing_groups(CUBE, [0, 1, 1, 1, 1, 1])
        assert faces == [True, False, False, False, False, False]
        # Edges of the ungrouped face against grouped neighbours are sharp too.
        assert edges == {(0, 3), (2, 3), (1, 2), (0, 1)}

    def test_length_mismatch(self):
        with pytest.raises(ValueError):
            smoothing.sharp_from_smoothing_groups(CUBE, [1])


class TestMaterialIds:

    def test_single_material(self):
        assert material_ids.slots_for_faces([1, 2, 3], None) == ([0], [0, 0, 0])

    def test_exact_ids(self):
        slots, faces = material_ids.slots_for_faces([1, 2, 2, 1], [1, 2])
        assert slots == [0, 1]
        assert faces == [0, 1, 1, 0]

    def test_unused_sub_materials_get_no_slot(self):
        slots, faces = material_ids.slots_for_faces([3, 3, 1], [1, 2, 3])
        assert slots == [0, None, 1]
        assert faces == [1, 1, 0]

    def test_sparse_ids(self):
        slots, faces = material_ids.slots_for_faces([5, 10], [5, None, 10])
        assert slots == [0, None, 1]
        assert faces == [0, 1]

    def test_wrap_when_id_missing(self):
        # Two sub-materials, face ID 3 wraps to position (3 - 1) % 2 = 0, ID 4 to position 1.
        slots, faces = material_ids.slots_for_faces([3, 4], [1, 2])
        assert faces == [0, 1]

    def test_empty_multi_sub(self):
        assert material_ids.slots_for_faces([1, 1], []) == ([], [0, 0])


class TestUnits:

    def test_values(self):
        assert units.scene_unit_in_metres("inches") == pytest.approx(0.0254)
        assert units.scene_unit_in_metres("centimeters", 1.0) == pytest.approx(0.01)
        assert units.scene_unit_in_metres("millimeters", 10.0) == pytest.approx(0.01)

    def test_errors(self):
        with pytest.raises(ValueError):
            units.scene_unit_in_metres("cubits")
        with pytest.raises(ValueError):
            units.scene_unit_in_metres("meters", 0.0)


class TestReport:

    def test_clean(self):
        report = mx_report.ImportReport(source="a.max")
        report.add_imported("objects", 3)
        assert report.is_clean
        assert report.summary() == "Imported 3 objects"
        assert "File: a.max" in report.to_text()

    def test_issues(self):
        report = mx_report.ImportReport()
        report.add_imported("objects", 2)
        report.add_imported("materials")
        report.add_unsupported("modifier", "Edit Poly")
        report.add_unsupported("modifier", "Edit Poly")
        report.add_missing_texture("C:/maps/wood.jpg")
        report.add_missing_texture("C:/maps/wood.jpg")
        report.warn("Units not found, assuming inches")
        assert not report.is_clean
        assert report.summary() == "Imported 1 materials, 2 objects; 4 issue(s), see the import report"
        text = report.to_text()
        assert "modifier: Edit Poly x2" in text
        assert text.count("C:/maps/wood.jpg") == 1
        assert "Units not found" in text
