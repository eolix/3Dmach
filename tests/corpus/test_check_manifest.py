# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Tests for check_manifest.py, plus a check of the real manifest. Run with: pytest tests/corpus"""

import os

import pytest

import check_manifest

GOOD_CASE = """
[[case]]
name = "editable_poly_box"
max_version = "2024"
renderer = "none"
features = ["geometry.editable_poly", "material.multi_sub_object"]
expected = "xfail"
license = "CC0-1.0"
contributor = "Jane Doe"
"""


def make_corpus(tmp_path, cases=GOOD_CASE, files=check_manifest.REQUIRED_FILES, case_dir="editable_poly_box"):
    manifest = tmp_path / "manifest.toml"
    manifest.write_text("schema_version = 1\n" + cases)
    if case_dir:
        (tmp_path / case_dir).mkdir()
        for name in files:
            (tmp_path / case_dir / name).write_bytes(b"")
    return manifest


def test_real_manifest_is_valid():
    manifest = os.path.join(os.path.dirname(os.path.abspath(__file__)), "manifest.toml")
    assert check_manifest.check_manifest(manifest) == []


def test_good_case(tmp_path):
    assert check_manifest.check_manifest(make_corpus(tmp_path)) == []


def test_optional_files_allowed(tmp_path):
    files = check_manifest.REQUIRED_FILES + check_manifest.OPTIONAL_FILES
    assert check_manifest.check_manifest(make_corpus(tmp_path, files=files)) == []


def test_missing_and_unexpected_files(tmp_path):
    files = ("scene.max", "LICENSE.txt", "notes.md", "stray.txt")
    problems = check_manifest.check_manifest(make_corpus(tmp_path, files=files))
    assert problems == [
        "case editable_poly_box: missing file editable_poly_box/reference.obj",
        "case editable_poly_box: unexpected file editable_poly_box/stray.txt",
    ]


def test_missing_directory(tmp_path):
    problems = check_manifest.check_manifest(make_corpus(tmp_path, case_dir=None))
    assert problems == ["case editable_poly_box: directory 'editable_poly_box' does not exist"]


def test_directory_without_entry(tmp_path):
    manifest = make_corpus(tmp_path)
    (tmp_path / "orphan_case").mkdir()
    (tmp_path / "__pycache__").mkdir()
    assert check_manifest.check_manifest(manifest) == ["directory 'orphan_case' has no [[case]] entry in the manifest"]


@pytest.mark.parametrize("old, new, expected", [
    ('license = "CC0-1.0"', 'license = "Proprietary"', "license 'Proprietary' is not in the redistributable list"),
    ('expected = "xfail"', 'expected = "maybe"', "expected must be one of pass, skip, xfail"),
    ('max_version = "2024"', "max_version = 2024", "max_version must be a quoted year-based version"),
    ('renderer = "none"', 'renderer = "V-Ray"', "renderer must be lower_snake_case"),
    ('"geometry.editable_poly"', '"EditablePoly"', "feature must be dotted lower_snake_case"),
    ('contributor = "Jane Doe"', 'contributor = " "', "contributor must be a non-empty string"),
    ('contributor = "Jane Doe"', '', "missing key 'contributor'"),
    ('contributor = "Jane Doe"', 'contributor = "Jane Doe"\ncolour = "red"', "unknown key 'colour'"),
])
def test_bad_values(tmp_path, old, new, expected):
    assert old in GOOD_CASE
    problems = check_manifest.check_manifest(make_corpus(tmp_path, cases=GOOD_CASE.replace(old, new)))
    assert len(problems) == 1
    assert problems[0].startswith("case editable_poly_box: " + expected)


def test_duplicate_name(tmp_path):
    problems = check_manifest.check_manifest(make_corpus(tmp_path, cases=GOOD_CASE * 2))
    assert problems == ["case editable_poly_box: duplicate name"]


def test_bad_schema_version_and_toml(tmp_path):
    manifest = tmp_path / "manifest.toml"
    manifest.write_text("schema_version = 2\n")
    assert check_manifest.check_manifest(manifest) == ["schema_version must be 1, got 2"]
    manifest.write_text("schema_version = \n")
    assert check_manifest.check_manifest(manifest)[0].startswith("cannot read manifest:")
