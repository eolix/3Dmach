# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Every project add-on enables and disables cleanly; the importer operator handles bad input."""

import os
import sys
import tempfile
import unittest

import addon_utils
import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _runner_util


def enable(name):
    errors = []
    mod = addon_utils.enable(name, default_set=True, handle_error=lambda ex: errors.append(ex))
    if errors:
        raise errors[0]
    if mod is None:
        raise RuntimeError("add-on {!r} could not be enabled".format(name))
    return mod


class AddonRegisterTest(unittest.TestCase):

    def test_enable_disable(self):
        for name in _runner_util.project_addons():
            with self.subTest(addon=name):
                enable(name)
                self.assertIn(name, bpy.context.preferences.addons)
                addon_utils.disable(name, default_set=True)
                self.assertNotIn(name, bpy.context.preferences.addons)

    def test_shared_modules_importable(self):
        import maxfile
        import mx_common
        self.assertTrue(maxfile.__version__)
        self.assertTrue(mx_common.__doc__)


class ImportOperatorTest(unittest.TestCase):

    def setUp(self):
        enable("mx_io_max")
        self.tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmpdir.cleanup()
        addon_utils.disable("mx_io_max", default_set=True)

    def test_registered(self):
        self.assertTrue(hasattr(bpy.types, "IMPORT_SCENE_OT_mx_max"))
        self.assertTrue(hasattr(bpy.types, "IO_FH_mx_max"))

    def test_rejects_non_max_file(self):
        path = os.path.join(self.tmpdir.name, "not_a_scene.max")
        with open(path, "wb") as fh:
            fh.write(b"definitely not a compound file")
        with self.assertRaisesRegex(RuntimeError, "Not a .max file"):
            bpy.ops.import_scene.mx_max(filepath=path)

    def test_missing_file(self):
        path = os.path.join(self.tmpdir.name, "missing.max")
        with self.assertRaisesRegex(RuntimeError, "Cannot read"):
            bpy.ops.import_scene.mx_max(filepath=path)

    def test_broken_container(self):
        # A Compound File signature followed by garbage: a clear error, nothing imported.
        from maxfile import container
        path = os.path.join(self.tmpdir.name, "container_only.max")
        with open(path, "wb") as fh:
            fh.write(container.CFB_SIGNATURE + b"\0" * 504)
        with self.assertRaisesRegex(RuntimeError, "Cannot import"):
            bpy.ops.import_scene.mx_max(filepath=path)

    def test_objects_unchanged_on_failure(self):
        before = set(bpy.data.objects)
        path = os.path.join(self.tmpdir.name, "not_a_scene.max")
        with open(path, "wb") as fh:
            fh.write(b"x")
        with self.assertRaises(RuntimeError):
            bpy.ops.import_scene.mx_max(filepath=path)
        self.assertEqual(before, set(bpy.data.objects))


if __name__ == "__main__":
    _runner_util.main()
