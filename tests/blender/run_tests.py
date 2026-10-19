#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Run every ``test_*.py`` in this directory inside headless Blender, one Blender process per file.

Usage::

    python3 tests/blender/run_tests.py --blender /path/to/blender [-k NAME] [--timeout SECONDS]

The ``BLENDER`` environment variable can be used instead of ``--blender``.

The project add-ons (``scripts/addons_core/mx_*``) and modules (``scripts/modules/mx_common``,
``pylibs/maxfile``) are copied from this source tree into a temporary directory passed as ``BLENDER_SYSTEM_SCRIPTS``,
so the tests run against the working tree on a stock Blender. ``--factory-startup`` and a temporary
``BLENDER_USER_RESOURCES`` keep the user's own Blender configuration out of the way.
(User script paths can't be used: ``--factory-startup`` leaves their ``modules`` off ``sys.path``.)

Each test file is run as::

    blender -b --factory-startup --python-exit-code 1 --python test_file.py

and must exit non-zero on failure (the test files use ``unittest`` via ``_runner_util.main()``).
``MX_CORPUS_DIR`` (the local corpus of real ``.max`` files, never committed) is passed through to the tests that
use it (``test_io_max_corpus.py``); ``--corpus DIR`` sets it.
This script exits non-zero when any test file fails.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.normpath(os.path.join(TESTS_DIR, "..", ".."))

# (source relative to `ROOT_DIR`, destination relative to the staged scripts directory).
STAGED_MODULES = (
    (os.path.join("scripts", "modules", "mx_common"), os.path.join("modules", "mx_common")),
    (os.path.join("pylibs", "maxfile", "maxfile"), os.path.join("modules", "maxfile")),
)


def stage_scripts(scripts_dir):
    """Copy the project's add-ons and modules into ``scripts_dir``. Returns the add-on names."""
    addons_src = os.path.join(ROOT_DIR, "scripts", "addons_core")
    addons = sorted(name for name in os.listdir(addons_src) if name.startswith("mx_"))
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    for name in addons:
        shutil.copytree(
            os.path.join(addons_src, name),
            os.path.join(scripts_dir, "addons", name),
            ignore=ignore,
        )
    for src, dst in STAGED_MODULES:
        shutil.copytree(os.path.join(ROOT_DIR, src), os.path.join(scripts_dir, dst), ignore=ignore)
    return addons


def find_tests(keyword):
    return sorted(
        os.path.join(TESTS_DIR, name)
        for name in os.listdir(TESTS_DIR)
        if name.startswith("test_") and name.endswith(".py") and (keyword is None or keyword in name)
    )


def run_test(blender, test_file, env, timeout):
    cmd = [blender, "-b", "--factory-startup", "--python-exit-code", "1", "--python", test_file]
    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd, env=env, timeout=timeout,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace",
        )
    except subprocess.TimeoutExpired as ex:
        output = ex.stdout or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        return False, output + "\nTimed out after {:d} seconds\n".format(timeout), time.monotonic() - start
    return proc.returncode == 0, proc.stdout, time.monotonic() - start


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--blender", default=os.environ.get("BLENDER"), help="Blender executable (default: $BLENDER)")
    parser.add_argument("-k", dest="keyword", default=None, help="Only run test files whose name contains this")
    parser.add_argument("--timeout", type=int, default=600, help="Timeout per test file, in seconds")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print Blender output for passing tests too")
    parser.add_argument("--corpus", default=os.environ.get("MX_CORPUS_DIR"),
                        help="Local corpus of .max files for the corpus tests (default: $MX_CORPUS_DIR)")
    args = parser.parse_args(argv)

    if not args.blender:
        parser.error("no Blender executable: pass --blender or set $BLENDER")

    tests = find_tests(args.keyword)
    if not tests:
        print("No tests found")
        return 1

    failed = []
    with tempfile.TemporaryDirectory(prefix="mx_blender_tests_") as tmp_dir:
        scripts_dir = os.path.join(tmp_dir, "scripts")
        addons = stage_scripts(scripts_dir)
        env = dict(os.environ)
        env["BLENDER_SYSTEM_SCRIPTS"] = scripts_dir
        # Isolate config, scripts and extensions from the user's own Blender setup.
        env["BLENDER_USER_RESOURCES"] = os.path.join(tmp_dir, "user")
        for var in ("BLENDER_USER_CONFIG", "BLENDER_USER_SCRIPTS", "BLENDER_USER_EXTENSIONS", "BLENDER_USER_DATAFILES"):
            env.pop(var, None)
        env["MX_TEST_ADDONS"] = ",".join(addons)
        env["MX_TEST_ROOT"] = ROOT_DIR
        if args.corpus:
            env["MX_CORPUS_DIR"] = os.path.abspath(args.corpus)

        for test_file in tests:
            name = os.path.basename(test_file)
            ok, output, elapsed = run_test(args.blender, test_file, env, args.timeout)
            print("{:s} {:s} ({:.1f}s)".format("PASS" if ok else "FAIL", name, elapsed), flush=True)
            if not ok or args.verbose:
                print(output)
            if not ok:
                failed.append(name)

    print("\n{:d} of {:d} test files passed".format(len(tests) - len(failed), len(tests)))
    for name in failed:
        print("  failed:", name)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
