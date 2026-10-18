# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Helpers for test files executed inside Blender by ``run_tests.py``."""

import os
import sys
import unittest


def project_addons():
    """Names of the project add-ons staged by ``run_tests.py``."""
    value = os.environ.get("MX_TEST_ADDONS", "")
    if not value:
        raise RuntimeError("MX_TEST_ADDONS is not set: run this test through tests/blender/run_tests.py")
    return value.split(",")


def main():
    """Run the ``unittest`` tests in ``__main__``, exiting non-zero on failure."""
    # Blender's own arguments are in `sys.argv`, don't let `unittest` parse them.
    result = unittest.main(module="__main__", argv=[sys.argv[0]], exit=False, verbosity=2).result
    if not result.wasSuccessful():
        sys.exit(1)
