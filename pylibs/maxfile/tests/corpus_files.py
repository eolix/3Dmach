# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Helpers for tests that check facts about specific real files of the local corpus.

The corpus is never committed (``docs/decisions/0004-local-corpus.md``): these tests skip when it is absent. They
name files of Autodesk's public sample-file set by their path below the corpus root, e.g.
``corpus_file("Scenes/SubDivSurfaces/Meshsmooth-Hammer.max")``; the set may sit directly in the corpus root or in
one sub-directory of it (as ``autodesk_3ds_max_english_win_sample_files/``).
"""

import functools
import os
import sys

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests", "corpus"))
import corpus  # noqa: E402

SAMPLE_SET = "autodesk_3ds_max_english_win_sample_files"


@functools.lru_cache(maxsize=None)
def _roots():
    root = corpus.corpus_dir()
    return [r for r in (os.path.join(root, SAMPLE_SET), root) if os.path.isdir(r)]


def find(relpath):
    """The absolute path of a corpus file, or None."""
    for root in _roots():
        path = os.path.join(root, relpath)
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            return path
    return None


def corpus_file(relpath):
    """The absolute path of a corpus file; skips the calling test when it isn't there."""
    path = find(relpath)
    if path is None:
        pytest.skip("corpus file not available: " + relpath)
    return path


@functools.lru_cache(maxsize=None)
def all_files():
    """Every non-empty .max file of the corpus, sorted (empty when there is no corpus)."""
    found = set()
    for root in _roots()[-1:]:
        for directory, _dirs, names in os.walk(root):
            for name in names:
                path = os.path.join(directory, name)
                if name.lower().endswith(".max") and os.path.getsize(path) > 0:
                    found.add(path)
    return sorted(found)


def sample(count):
    """``count`` corpus files spread evenly over the sorted list (all of them when there are fewer)."""
    files = all_files()
    if len(files) <= count:
        return list(files)
    step = len(files) / count
    return [files[int(i * step)] for i in range(count)]


def full_corpus_enabled():
    """True when the slow whole-corpus tests are asked for (``MX_FULL_CORPUS=1``)."""
    return os.environ.get("MX_FULL_CORPUS", "") not in ("", "0")
