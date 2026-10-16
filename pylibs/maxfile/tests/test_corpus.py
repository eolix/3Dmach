# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Run the reader and ``maxdump`` on every real ``.max`` file in the local corpus (``tests/corpus/``).

This is where the unverified assumptions of ``docs/format/overview.md`` meet real files. The corpus is never
committed (see ``docs/decisions/0004-local-corpus.md``); without one, the test is skipped.
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


def _params():
    if not CASES:
        return [pytest.param(None, marks=pytest.mark.skip(reason="no .max files in " + corpus.corpus_dir()))]
    params = []
    for case in CASES:
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
        data = dump.summary(mf)
        assert data["objects"] == len(mf.objects)
        # Print what was found, so `pytest -s` shows it next to the result.
        print("\n{:s}: {:d} objects, {:d} nodes, {:d} unknown classes, {:d} warnings".format(
            case.name, len(mf.objects), len(mf.nodes), len(mf.unknown_classes()), len(mf.warnings)))
    for args in ([case.path], [case.path, "--json"], [case.path, "--chunks", "--depth", "2"]):
        assert dump.main(args, out=io.StringIO()) == 0, args


def test_corpus_manifest_is_valid():
    assert PROBLEMS == []
