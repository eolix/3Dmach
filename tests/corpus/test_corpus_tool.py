# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Tests for corpus.py. Run with: pytest tests/corpus"""

import corpus


def touch(path, data=b""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def by_name(cases):
    return {case.name: case for case in cases}


def test_missing_corpus(tmp_path):
    assert corpus.load_corpus(tmp_path / "nothing") == ([], [])


def test_discovery_and_references(tmp_path):
    touch(tmp_path / "box" / "scene.max")
    touch(tmp_path / "box" / "reference.obj")
    touch(tmp_path / "box" / "maps" / "wood.png")
    touch(tmp_path / "many" / "a.max")
    touch(tmp_path / "many" / "a.obj")
    touch(tmp_path / "many" / "b.MAX")
    touch(tmp_path / "many" / "reference.obj")  # Ambiguous with two .max files: not used.
    touch(tmp_path / "top.max")

    cases, problems = corpus.load_corpus(tmp_path)
    assert problems == []
    cases = by_name(cases)
    assert sorted(cases) == ["box/scene.max", "many/a.max", "many/b.MAX", "top.max"]
    assert cases["box/scene.max"].reference_obj == str(tmp_path / "box" / "reference.obj")
    assert cases["many/a.max"].reference_obj == str(tmp_path / "many" / "a.obj")
    assert cases["many/b.MAX"].reference_obj is None
    assert cases["top.max"].expected == "pass"


def test_manifest_metadata(tmp_path):
    touch(tmp_path / "vray" / "room.max")
    touch(tmp_path / "exports" / "room_collapsed.obj")
    (tmp_path / "manifest.toml").write_text(
        'schema_version = 2\n'
        '[[case]]\n'
        'file = "vray/room.max"\n'
        'expected = "xfail"\n'
        'max_version = "2023"\n'
        'renderer = "vray"\n'
        'features = ["material.vray_mtl", "geometry.editable_poly"]\n'
        'reference_obj = "exports/room_collapsed.obj"\n'
    )
    cases, problems = corpus.load_corpus(tmp_path)
    assert problems == []
    (case,) = cases
    assert case.expected == "xfail"
    assert case.max_version == "2023"
    assert case.features == ("material.vray_mtl", "geometry.editable_poly")
    assert case.reference_obj == str(tmp_path / "exports" / "room_collapsed.obj")


def test_manifest_problems(tmp_path):
    touch(tmp_path / "a.max")
    (tmp_path / "manifest.toml").write_text(
        'schema_version = 2\n'
        '[[case]]\nfile = "missing.max"\n'
        '[[case]]\nfile = "a.max"\nexpected = "maybe"\ncolour = "red"\nfeatures = ["Bad"]\n'
    )
    cases, problems = corpus.load_corpus(tmp_path)
    assert len(cases) == 1 and cases[0].expected == "pass"
    assert problems == [
        "manifest.toml: case missing.max: no such .max file in the corpus",
        "manifest.toml: case a.max: unknown key 'colour'",
        "manifest.toml: case a.max: expected must be one of pass, xfail, skip, got 'maybe'",
        "manifest.toml: case a.max: features must be a list of dotted lower_snake_case names "
        "(e.g. \"geometry.editable_poly\")",
    ]


def test_bad_schema_and_toml(tmp_path):
    touch(tmp_path / "a.max")
    (tmp_path / "manifest.toml").write_text("schema_version = 1\n")
    assert corpus.load_corpus(tmp_path)[1] == ["manifest.toml: schema_version must be 2, got 1"]
    (tmp_path / "manifest.toml").write_text("schema_version = \n")
    assert corpus.load_corpus(tmp_path)[1][0].startswith("manifest.toml: cannot read:")


def test_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("MX_CORPUS_DIR", str(tmp_path))
    assert corpus.corpus_dir() == str(tmp_path)
    monkeypatch.delenv("MX_CORPUS_DIR")
    assert corpus.corpus_dir() == corpus.DEFAULT_DIR
