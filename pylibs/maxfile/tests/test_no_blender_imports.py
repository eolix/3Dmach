# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""The parser must stay usable without Blender: importing it must not pull in Blender modules."""

import os
import pkgutil
import subprocess
import sys

import maxfile

BLENDER_MODULES = ("bpy", "mathutils", "bmesh", "gpu", "bl_math", "_bpy")


def test_no_blender_imports():
    # Run in a fresh interpreter so modules imported by other tests (or pytest plugins) don't interfere.
    names = [name for _, name, _ in pkgutil.walk_packages(maxfile.__path__, prefix="maxfile.")]
    code = (
        "import importlib, sys\n"
        "for name in {names!r}: importlib.import_module(name)\n"
        "bad = sorted(m for m in sys.modules if m.split('.')[0] in {blender!r})\n"
        "print(','.join(bad))\n"
    ).format(names=["maxfile"] + names, blender=BLENDER_MODULES)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=os.path.dirname(maxfile.__path__[0]), capture_output=True, text=True, check=True,
    )
    assert result.stdout.strip() == "", "Blender modules imported: " + result.stdout
