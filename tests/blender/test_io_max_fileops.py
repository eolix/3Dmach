# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""File > Open / Save / Save As defaulting to .max, and the .blend flow under Import / Export."""

import os
import sys
import tempfile
import time
import unittest

import addon_utils
import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _runner_util


class FileOpsTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        addon_utils.enable("mx_io_max", default_set=True)
        cls.tmp = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        addon_utils.enable("mx_io_max", default_set=True)

    def path(self, name):
        return os.path.join(self.tmp.name, name)

    def test_registered(self):
        for name in ("WM_OT_mx_open", "WM_OT_mx_open_browse", "WM_OT_mx_save", "WM_OT_mx_save_as"):
            self.assertTrue(hasattr(bpy.types, name), name)

    def test_save_as_blend(self):
        path = self.path("scene.blend")
        self.assertEqual(bpy.ops.wm.mx_save_as(filepath=path), {'FINISHED'})
        self.assertTrue(os.path.isfile(path))
        self.assertEqual(os.path.normpath(bpy.data.filepath), os.path.normpath(path))
        # Save then writes the same native file.
        before = os.path.getmtime(path)
        time.sleep(1.1)
        self.assertEqual(bpy.ops.wm.mx_save(), {'FINISHED'})
        self.assertGreater(os.path.getmtime(path), before)

    def test_save_as_max_without_writer(self):
        from mx_io_max import file_ops
        if file_ops.writer_available():
            self.skipTest("the .max writer is installed")
        with self.assertRaisesRegex(RuntimeError, "isn't available yet"):
            bpy.ops.wm.mx_save_as(filepath=self.path("scene.max"))

    def test_save_as_max_with_writer(self):
        from mx_io_max import file_ops
        if not file_ops.writer_available():
            self.skipTest("the .max writer is not installed")
        bpy.ops.wm.read_homefile(use_empty=True)
        bpy.ops.mesh.primitive_cube_add()
        path = self.path("cube.max")
        self.assertEqual(bpy.ops.wm.mx_save_as(filepath=path), {'FINISHED'})
        self.assertTrue(os.path.isfile(path))
        self.assertTrue(os.path.isfile(file_ops.backup_path(path)))
        self.assertEqual(bpy.context.scene[file_ops.MAX_PATH_KEY], path)
        # The written .max reads back with the cube in it.
        import maxfile
        with maxfile.open(path) as mf:
            self.assertEqual([n.name for n in mf.nodes if n.name], ["Cube"])
        # Save writes the same .max again.
        before = os.path.getmtime(path)
        time.sleep(1.1)
        self.assertEqual(bpy.ops.wm.mx_save(), {'FINISHED'})
        self.assertGreater(os.path.getmtime(path), before)

    def test_open_uses_newer_backup(self):
        from mx_io_max import file_ops
        max_path = self.path("room.max")
        with open(max_path, "wb") as fh:
            fh.write(b"not used: the backup is newer")
        bpy.ops.wm.read_homefile(use_empty=True)
        bpy.data.objects.new("Marker", None)
        bpy.context.scene.collection.objects.link(bpy.data.objects["Marker"])
        bpy.ops.wm.save_as_mainfile(filepath=file_ops.backup_path(max_path))
        bpy.ops.wm.read_homefile(use_empty=True)
        self.assertNotIn("Marker", bpy.data.objects)
        self.assertEqual(file_ops.open_file(max_path), {'FINISHED'})
        self.assertIn("Marker", bpy.data.objects)
        self.assertTrue(bpy.data.filepath.endswith(file_ops.BACKUP_SUFFIX))

    def test_open_blend(self):
        from mx_io_max import file_ops
        path = self.path("plain.blend")
        bpy.ops.wm.read_homefile(use_empty=True)
        bpy.ops.wm.save_as_mainfile(filepath=path)
        bpy.ops.wm.read_homefile(use_empty=True)
        self.assertEqual(file_ops.open_file(path), {'FINISHED'})
        self.assertEqual(os.path.normpath(bpy.data.filepath), os.path.normpath(path))

    def test_blend_entries_in_import_export_menus(self):
        from mx_io_max import file_ops
        self.assertIn(file_ops.menu_func_import_blend, bpy.types.TOPBAR_MT_file_import._dyn_ui_initialize())
        self.assertIn(file_ops.menu_func_export_blend, bpy.types.TOPBAR_MT_file_export._dyn_ui_initialize())


if __name__ == "__main__":
    _runner_util.main()
