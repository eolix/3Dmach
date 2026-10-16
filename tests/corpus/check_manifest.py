#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Validate ``tests/corpus/manifest.toml`` against the case directories next to it.

Usage::

    python3 tests/corpus/check_manifest.py [path/to/manifest.toml]

Prints one line per problem and exits non-zero when there are any.
"""

import os
import re
import sys
import tomllib

SCHEMA_VERSION = 1

# Licences that allow redistributing the test files (SPDX identifiers).
ALLOWED_LICENSES = {"CC0-1.0", "CC-BY-4.0", "CC-BY-SA-4.0", "GPL-2.0-or-later", "GPL-3.0-or-later"}

EXPECTED_STATUS = {"pass", "xfail", "skip"}

REQUIRED_FILES = ("scene.max", "reference.obj", "LICENSE.txt", "notes.md")
OPTIONAL_FILES = ("reference.fbx", "reference.png")

REQUIRED_KEYS = {"name", "max_version", "renderer", "features", "expected", "license", "contributor"}
OPTIONAL_KEYS = {"notes"}

NAME_RE = re.compile(r"^[a-z0-9]+(_[a-z0-9]+)*$")
FEATURE_RE = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)+$")
MAX_VERSION_RE = re.compile(r"^[0-9]{4}(\.[0-9]+)*$")


def check_case(case, corpus_dir):
    """Return a list of problems with one ``[[case]]`` table."""
    problems = []
    keys = set(case)
    for key in sorted(REQUIRED_KEYS - keys):
        problems.append("missing key {!r}".format(key))
    for key in sorted(keys - REQUIRED_KEYS - OPTIONAL_KEYS):
        problems.append("unknown key {!r}".format(key))

    name = case.get("name")
    if not isinstance(name, str) or not NAME_RE.match(name):
        problems.append("name must be lower_snake_case, got {!r}".format(name))
        name = None

    max_version = case.get("max_version")
    if "max_version" in case and not (isinstance(max_version, str) and MAX_VERSION_RE.match(max_version)):
        problems.append(
            "max_version must be a quoted year-based version such as \"2024\", got {!r}".format(max_version))

    renderer = case.get("renderer")
    if "renderer" in case and not (isinstance(renderer, str) and NAME_RE.match(renderer)):
        problems.append("renderer must be lower_snake_case (e.g. \"none\", \"vray\"), got {!r}".format(renderer))

    features = case.get("features")
    if "features" in case:
        if not isinstance(features, list) or not features:
            problems.append("features must be a non-empty list")
        else:
            for feature in features:
                if not (isinstance(feature, str) and FEATURE_RE.match(feature)):
                    problems.append("feature must be dotted lower_snake_case (e.g. \"geometry.editable_poly\"), "
                                    "got {!r}".format(feature))

    expected = case.get("expected")
    if "expected" in case and expected not in EXPECTED_STATUS:
        problems.append("expected must be one of {:s}, got {!r}".format(", ".join(sorted(EXPECTED_STATUS)), expected))

    license_id = case.get("license")
    if "license" in case and license_id not in ALLOWED_LICENSES:
        problems.append("license {!r} is not in the redistributable list: {:s}".format(
            license_id, ", ".join(sorted(ALLOWED_LICENSES))))

    for key in ("contributor", "notes"):
        if key in case and not (isinstance(case[key], str) and case[key].strip()):
            problems.append("{:s} must be a non-empty string".format(key))

    if name is not None:
        case_dir = os.path.join(corpus_dir, name)
        if not os.path.isdir(case_dir):
            problems.append("directory {!r} does not exist".format(name))
        else:
            for filename in REQUIRED_FILES:
                if not os.path.isfile(os.path.join(case_dir, filename)):
                    problems.append("missing file {:s}/{:s}".format(name, filename))
            known = set(REQUIRED_FILES) | set(OPTIONAL_FILES)
            for filename in sorted(os.listdir(case_dir)):
                if filename not in known:
                    problems.append("unexpected file {:s}/{:s}".format(name, filename))
    return problems


def check_manifest(manifest_path):
    """Return a list of problems with the manifest at ``manifest_path`` and its case directories."""
    corpus_dir = os.path.dirname(os.path.abspath(manifest_path))
    try:
        with open(manifest_path, "rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as ex:
        return ["cannot read manifest: {:s}".format(str(ex))]

    problems = []
    if data.get("schema_version") != SCHEMA_VERSION:
        problems.append("schema_version must be {:d}, got {!r}".format(SCHEMA_VERSION, data.get("schema_version")))
    for key in sorted(set(data) - {"schema_version", "case"}):
        problems.append("unknown top-level key {!r}".format(key))

    cases = data.get("case", [])
    if not isinstance(cases, list):
        return problems + ["'case' must be an array of tables ([[case]])"]

    seen = set()
    for index, case in enumerate(cases):
        label = case.get("name") if isinstance(case.get("name"), str) else "#{:d}".format(index + 1)
        if label in seen:
            problems.append("case {:s}: duplicate name".format(label))
        seen.add(label)
        problems.extend("case {:s}: {:s}".format(label, problem) for problem in check_case(case, corpus_dir))

    # Every case directory needs a manifest entry, so files can't be added without a licence record.
    for entry in sorted(os.listdir(corpus_dir)):
        if os.path.isdir(os.path.join(corpus_dir, entry)) and not entry.startswith((".", "_")) and entry not in seen:
            problems.append("directory {!r} has no [[case]] entry in the manifest".format(entry))
    return problems


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    manifest_path = argv[0] if argv else os.path.join(os.path.dirname(os.path.abspath(__file__)), "manifest.toml")
    problems = check_manifest(manifest_path)
    for problem in problems:
        print(problem)
    if not problems:
        print("OK:", manifest_path)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
