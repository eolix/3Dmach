#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Find the local ``.max`` test corpus and its optional metadata.

The corpus lives in ``tests/corpus/local/`` (gitignored, never committed) or in the directory named by the
``MX_CORPUS_DIR`` environment variable. Every ``*.max`` file below it is a test case. An optional
``manifest.toml`` in the corpus root adds metadata per file; see ``tests/corpus/README.md``.

Usage::

    python3 tests/corpus/corpus.py [CORPUS_DIR]

Lists the cases and any manifest problems; exits non-zero when there are problems.
"""

__all__ = (
    "Case",
    "corpus_dir",
    "load_corpus",
)

import dataclasses
import os
import re
import sys
import tomllib

SCHEMA_VERSION = 2
MANIFEST_NAME = "manifest.toml"
EXPECTED_STATUS = ("pass", "xfail", "skip")
CASE_KEYS = {"file", "max_version", "renderer", "features", "expected", "reference_obj", "reference_fbx", "notes"}
FEATURE_RE = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)+$")

DEFAULT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "local")


@dataclasses.dataclass
class Case:
    """One ``.max`` file in the corpus."""
    path: str                       # Absolute path to the .max file.
    name: str                       # Path relative to the corpus root, with forward slashes.
    expected: str = "pass"          # "pass", "xfail" or "skip".
    max_version: str | None = None
    renderer: str | None = None
    features: tuple[str, ...] = ()
    reference_obj: str | None = None  # Absolute path, when a reference export exists.
    reference_fbx: str | None = None
    notes: str | None = None


def corpus_dir():
    """The corpus root: ``$MX_CORPUS_DIR`` or ``tests/corpus/local``."""
    return os.environ.get("MX_CORPUS_DIR") or DEFAULT_DIR


def _find_reference(max_path, ext, max_files_in_dir):
    """``<stem>.<ext>`` next to the file, or ``reference.<ext>`` when the directory holds a single .max file."""
    directory, filename = os.path.split(max_path)
    candidates = [os.path.splitext(filename)[0] + ext]
    if max_files_in_dir == 1:
        candidates.append("reference" + ext)
    for candidate in candidates:
        path = os.path.join(directory, candidate)
        if os.path.isfile(path):
            return path
    return None


def _check_entry(entry):
    problems = []
    for key in sorted(set(entry) - CASE_KEYS):
        problems.append("unknown key {!r}".format(key))
    if not isinstance(entry.get("file"), str):
        problems.append("missing or non-string 'file'")
    if entry.get("expected", "pass") not in EXPECTED_STATUS:
        problems.append("expected must be one of {:s}, got {!r}".format(", ".join(EXPECTED_STATUS), entry["expected"]))
    for key in ("max_version", "renderer", "reference_obj", "reference_fbx", "notes"):
        if key in entry and not isinstance(entry[key], str):
            problems.append("{:s} must be a string".format(key))
    features = entry.get("features", [])
    if not isinstance(features, list) or not all(isinstance(f, str) and FEATURE_RE.match(f) for f in features):
        problems.append("features must be a list of dotted lower_snake_case names (e.g. \"geometry.editable_poly\")")
    return problems


def load_corpus(root=None):
    """
    Return ``(cases, problems)`` for the corpus at ``root`` (default: :func:`corpus_dir`).

    A missing corpus directory gives no cases and no problems.
    """
    root = os.path.abspath(root or corpus_dir())
    if not os.path.isdir(root):
        return [], []

    max_files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        max_files.extend(os.path.join(dirpath, f) for f in sorted(filenames) if f.lower().endswith(".max"))
    per_dir = {}
    for path in max_files:
        per_dir[os.path.dirname(path)] = per_dir.get(os.path.dirname(path), 0) + 1

    cases = {}
    for path in max_files:
        name = os.path.relpath(path, root).replace(os.sep, "/")
        count = per_dir[os.path.dirname(path)]
        cases[name] = Case(
            path=path,
            name=name,
            reference_obj=_find_reference(path, ".obj", count),
            reference_fbx=_find_reference(path, ".fbx", count),
        )

    problems = []
    manifest_path = os.path.join(root, MANIFEST_NAME)
    if os.path.isfile(manifest_path):
        try:
            with open(manifest_path, "rb") as fh:
                data = tomllib.load(fh)
        except (OSError, tomllib.TOMLDecodeError) as ex:
            return list(cases.values()), ["{:s}: cannot read: {:s}".format(MANIFEST_NAME, str(ex))]
        if data.get("schema_version") != SCHEMA_VERSION:
            problems.append("{:s}: schema_version must be {:d}, got {!r}".format(
                MANIFEST_NAME, SCHEMA_VERSION, data.get("schema_version")))
        entries = data.get("case", [])
        if not isinstance(entries, list):
            entries = []
            problems.append("{:s}: 'case' must be an array of tables ([[case]])".format(MANIFEST_NAME))
        for index, entry in enumerate(entries):
            label = entry.get("file") if isinstance(entry.get("file"), str) else "#{:d}".format(index + 1)
            entry_problems = _check_entry(entry)
            case = cases.get(label)
            if not entry_problems and case is None:
                entry_problems.append("no such .max file in the corpus")
            if entry_problems:
                problems.extend("{:s}: case {:s}: {:s}".format(MANIFEST_NAME, label, p) for p in entry_problems)
                continue
            case.expected = entry.get("expected", "pass")
            case.max_version = entry.get("max_version")
            case.renderer = entry.get("renderer")
            case.features = tuple(entry.get("features", ()))
            case.notes = entry.get("notes")
            for key in ("reference_obj", "reference_fbx"):
                if key in entry:
                    ref = os.path.join(root, entry[key])
                    if os.path.isfile(ref):
                        setattr(case, key, ref)
                    else:
                        problems.append("{:s}: case {:s}: {:s} {!r} does not exist".format(
                            MANIFEST_NAME, label, key, entry[key]))
    return list(cases.values()), problems


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    root = argv[0] if argv else corpus_dir()
    cases, problems = load_corpus(root)
    if not os.path.isdir(root):
        print("No corpus directory at", root)
    for case in cases:
        refs = ", ".join(k for k in ("reference_obj", "reference_fbx") if getattr(case, k)) or "no references"
        print("{:s}  [{:s}; {:s}]".format(case.name, case.expected, refs))
    for problem in problems:
        print("PROBLEM:", problem)
    print("{:d} case(s), {:d} problem(s)".format(len(cases), len(problems)))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
