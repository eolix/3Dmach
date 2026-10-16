# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Importer building blocks that need Blender: the bulk mesh builder and the report text block."""

import os
import sys
import unittest

import addon_utils
import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _runner_util

CUBE_POSITIONS = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]
CUBE_FACES = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]


class MeshBuildTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        addon_utils.enable("mx_io_max", default_set=True)

    @classmethod
    def tearDownClass(cls):
        addon_utils.disable("mx_io_max", default_set=True)

    def test_cube(self):
        from mx_io_max import mesh_build, smoothing
        groups = [1, 2, 4, 4, 4, 4]
        sharp_edges, sharp_faces = smoothing.sharp_from_smoothing_groups(CUBE_FACES, groups)
        uvs = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)] * 6
        mesh = mesh_build.build_mesh(
            "cube", CUBE_POSITIONS, CUBE_FACES,
            uv_layers=[("UVMap", uvs)],
            material_indices=[0, 1, 2, 2, 2, 2],
            sharp_edges=sharp_edges,
            sharp_faces=sharp_faces,
        )
        self.assertEqual((len(mesh.vertices), len(mesh.edges), len(mesh.polygons)), (8, 12, 6))
        self.assertFalse(mesh.validate(verbose=True))
        self.assertEqual([p.material_index for p in mesh.polygons], [0, 1, 2, 2, 2, 2])
        self.assertEqual([tuple(p.vertices) for p in mesh.polygons], CUBE_FACES)
        sharp = mesh.attributes["sharp_edge"].data
        marked = {tuple(sorted(e.vertices)) for e, s in zip(mesh.edges, sharp) if s.value}
        self.assertEqual(marked, sharp_edges)
        self.assertEqual(len(marked), 8)
        self.assertNotIn("sharp_face", mesh.attributes)  # All faces smooth.
        self.assertEqual(tuple(mesh.uv_layers["UVMap"].data[2].uv), (1.0, 1.0))

    def test_flat_faces_and_bad_uvs(self):
        from mx_io_max import mesh_build
        mesh = mesh_build.build_mesh("flat", CUBE_POSITIONS, CUBE_FACES, sharp_faces=[True] * 6)
        self.assertTrue(all(v.value for v in mesh.attributes["sharp_face"].data))
        meshes_before = len(bpy.data.meshes)
        with self.assertRaises(ValueError):
            mesh_build.build_mesh("bad", CUBE_POSITIONS, CUBE_FACES, uv_layers=[("UVMap", [(0, 0)])])
        self.assertEqual(len(bpy.data.meshes), meshes_before)

    def test_report_text_block(self):
        from mx_common import report as mx_report
        report = mx_report.ImportReport(source="x.max")
        report.add_unsupported("material", "SomeMtl")
        text = mx_report.store_in_text(report)
        self.assertIn("material: SomeMtl x1", text.as_string())
        # Storing again replaces the contents.
        mx_report.store_in_text(mx_report.ImportReport(source="y.max"))
        self.assertNotIn("SomeMtl", text.as_string())


if __name__ == "__main__":
    _runner_util.main()
