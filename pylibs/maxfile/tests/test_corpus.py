# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Run the reader, every decoder and ``maxdump`` on real ``.max`` files of the local corpus (``tests/corpus/``).

The corpus is never committed (see ``docs/decisions/0004-local-corpus.md``); without one, the tests are skipped.
By default a sample of files spread over the corpus is checked (a few seconds); set ``MX_FULL_CORPUS=1`` to check
every file (several minutes for the 623 sample files).
"""

import io
import os
import sys

import pytest

import maxfile
from maxfile import dump

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests", "corpus"))
import corpus  # noqa: E402

CASES, PROBLEMS = corpus.load_corpus()
FULL = os.environ.get("MX_FULL_CORPUS", "") not in ("", "0")
SAMPLE_SIZE = 8


def _selected():
    cases = sorted(CASES, key=lambda c: c.name)
    if FULL or len(cases) <= SAMPLE_SIZE:
        return cases
    # Spread over the sorted list, smallest file of each slice (keeps the default run fast).
    step = len(cases) / SAMPLE_SIZE
    chosen = []
    for i in range(SAMPLE_SIZE):
        part = cases[int(i * step):int((i + 1) * step)]
        chosen.append(min(part, key=lambda c: os.path.getsize(c.path)))
    return chosen


def _params():
    if not CASES:
        return [pytest.param(None, marks=pytest.mark.skip(reason="no .max files in " + corpus.corpus_dir()))]
    params = []
    for case in _selected():
        marks = []
        if case.expected == "skip":
            marks.append(pytest.mark.skip(reason="manifest: expected = skip"))
        elif case.expected == "xfail":
            marks.append(pytest.mark.xfail(reason="manifest: expected = xfail"))
        params.append(pytest.param(case, marks=marks, id=case.name))
    return params


@pytest.mark.parametrize("case", _params())
def test_corpus_file(case):
    with maxfile.open(case.path) as mf:
        assert mf.class_directory.entries, "empty class directory"
        assert mf.objects, "no scene objects"
        mf.class_usage()
        for node in mf.nodes:
            node.world_matrix()
            base, modifiers = mf.scene.resolve_geometry(node)
            for obj in [base, node.material, *modifiers]:
                mf.scene.decode(obj)
        for obj in mf.objects:
            mf.scene.param_block(obj)
        data = dump.summary(mf)
        assert data["objects"] == len(mf.objects)
        # Print what was found, so `pytest -s` shows it next to the result.
        print("\n{:s}: {:d} objects, {:d} nodes, {:d} unknown classes, {:d} warnings".format(
            case.name, len(mf.objects), len(mf.nodes), len(mf.unknown_classes()), len(mf.warnings)))
    for args in ([case.path], [case.path, "--json"], [case.path, "--chunks", "--depth", "2"]):
        assert dump.main(args, out=io.StringIO()) == 0, args


def test_corpus_manifest_is_valid():
    assert PROBLEMS == []
