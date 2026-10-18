# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Material model to Principled BSDF node trees."""

import os
import sys
import tempfile
import unittest

import addon_utils
import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _runner_util


def linked_from(socket):
    """The node feeding ``socket``, or None."""
    return socket.links[0].from_node if socket.is_linked else None


class MaterialBuildTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        addon_utils.enable("mx_io_max", default_set=True)
        cls.tmp = tempfile.TemporaryDirectory()
        image = bpy.data.images.new("wood", 4, 4)
        cls.wood = os.path.join(cls.tmp.name, "maps", "wood.png")
        os.makedirs(os.path.dirname(cls.wood))
        image.filepath_raw = cls.wood
        image.file_format = 'PNG'
        image.save()
        bpy.data.images.remove(image)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()
        addon_utils.disable("mx_io_max", default_set=True)

    def builder(self):
        from mx_common.report import ImportReport
        from mx_io_max.materials import nodes, textures
        self.report = ImportReport()
        resolver = textures.TextureResolver(os.path.join(self.tmp.name, "scene.max"))
        return nodes.MaterialBuilder(resolver, self.report)

    def bsdf(self, mat):
        out = next(n for n in mat.node_tree.nodes if n.type == 'OUTPUT_MATERIAL')
        return linked_from(out.inputs["Surface"])

    def test_vray_with_bitmap_and_bump(self):
        from mx_io_max.materials import convert, model
        surface = convert.convert("VRayMtl", {
            "name": "Oak",
            "diffuse": (0.5, 0.3, 0.1),
            "texmap_diffuse": model.Bitmap(path="C:\\Proj\\maps\\wood.png", tiling=(2.0, 2.0)),
            "reflection": (0.6, 0.6, 0.6), "reflection_glossiness": 0.7,
            "texmap_bump": model.Bitmap(path="C:\\Proj\\maps\\missing_bump.png"), "texmap_bump_multiplier": 0.4,
        })
        mat = self.builder().build(surface)
        bsdf = self.bsdf(mat)
        self.assertEqual(bsdf.type, 'BSDF_PRINCIPLED')
        tex = linked_from(bsdf.inputs["Base Color"])
        self.assertEqual(tex.type, 'TEX_IMAGE')
        self.assertEqual(os.path.normpath(bpy.path.abspath(tex.image.filepath)), os.path.normpath(self.wood))
        self.assertFalse(tex.image.colorspace_settings.is_data)
        mapping = linked_from(tex.inputs["Vector"])
        self.assertEqual(mapping.type, 'MAPPING')
        self.assertEqual(tuple(mapping.inputs["Scale"].default_value), (2.0, 2.0, 1.0))
        self.assertAlmostEqual(bsdf.inputs["Roughness"].default_value, 0.3, places=5)
        # The bump map is missing: a bump node with an empty image texture, and it is reported.
        self.assertEqual(linked_from(bsdf.inputs["Normal"]).type, 'BUMP')
        self.assertEqual(self.report.missing_textures, ["C:\\Proj\\maps\\missing_bump.png"])
        self.assertEqual(mat["mx_source_class"], "VRayMtl")

    def test_normal_map_is_non_color(self):
        from mx_io_max.materials import model
        surface = model.Surface(normal=model.NormalMap(input=model.Bitmap(path="wood.png"), flip_green=True))
        mat = self.builder().build(surface)
        nmap = linked_from(self.bsdf(mat).inputs["Normal"])
        self.assertEqual(nmap.type, 'NORMAL_MAP')
        combine = linked_from(nmap.inputs["Color"])
        self.assertEqual(combine.type, 'COMBINE_COLOR')
        tex = next(n for n in mat.node_tree.nodes if n.type == 'TEX_IMAGE')
        self.assertTrue(tex.image.colorspace_settings.is_data)

    def test_procedural_maps(self):
        from mx_io_max.materials import model
        surface = model.Surface(
            base_color=model.Input((0.5, 0.5, 0.5), model.Mix(
                a=model.Checker(color1=(1, 0, 0), color2=(0, 0, 1)),
                b=model.Noise(),
                amount=model.Falloff(kind="FRESNEL"),
            )),
            roughness=model.Input(0.5, model.ColorCorrection(input=model.Gradient(), brightness=10.0, gamma=2.2),
                                  map_amount=0.5),
        )
        mat = self.builder().build(surface)
        bsdf = self.bsdf(mat)
        self.assertEqual(linked_from(bsdf.inputs["Base Color"]).type, 'MIX')
        types = {n.type for n in mat.node_tree.nodes}
        for expected in ('TEX_CHECKER', 'TEX_NOISE', 'FRESNEL', 'HUE_SAT', 'BRIGHTCONTRAST', 'GAMMA', 'VALTORGB'):
            self.assertIn(expected, types)
        # Map amount 0.5 inserts a mix between the constant and the map.
        rough_mix = linked_from(bsdf.inputs["Roughness"])
        self.assertEqual(rough_mix.type, 'MIX')
        self.assertAlmostEqual(rough_mix.inputs["Factor"].default_value, 0.5)

    def test_blend_and_placeholder(self):
        from mx_io_max.materials import convert, model
        builder = self.builder()
        blend = model.Blend(name="Mixed", a=model.Surface(), b=convert.convert("CoronaMtl", {}), amount=0.25)
        mat = builder.build(blend)
        mix = self.bsdf(mat)
        self.assertEqual(mix.type, 'MIX_SHADER')
        self.assertAlmostEqual(mix.inputs["Fac"].default_value, 0.25)
        ph = builder.build(convert.convert("WeirdMtl", {"diffuse": (0.1, 0.2, 0.3)}))
        self.assertTrue(ph["mx_placeholder"])
        self.assertAlmostEqual(ph.diffuse_color[2], 0.3, places=5)
        self.assertEqual(dict(self.report.unsupported), {("material", "WeirdMtl"): 1})

    def test_transparency_render_method(self):
        from mx_io_max.materials import convert
        mat = self.builder().build(convert.convert("Standardmaterial", {"opacity": 40.0}))
        self.assertEqual(mat.surface_render_method, 'DITHERED')
        self.assertAlmostEqual(self.bsdf(mat).inputs["Alpha"].default_value, 0.4, places=5)

    def test_images_shared(self):
        from mx_io_max.materials import model
        builder = self.builder()
        a = builder.build(model.Surface(base_color=model.Input((1, 1, 1), model.Bitmap(path="X:\\wood.png"))))
        b = builder.build(model.Surface(base_color=model.Input((1, 1, 1), model.Bitmap(path="X:\\wood.png"))))
        img_a = next(n for n in a.node_tree.nodes if n.type == 'TEX_IMAGE').image
        img_b = next(n for n in b.node_tree.nodes if n.type == 'TEX_IMAGE').image
        self.assertIs(img_a, img_b)

    def test_same_file_as_color_and_data(self):
        from mx_io_max.materials import model
        surface = model.Surface(
            base_color=model.Input((1, 1, 1), model.Bitmap(path="wood.png")),
            normal=model.Bump(input=model.Bitmap(path="wood.png"), strength=0.5),
        )
        mat = self.builder().build(surface)
        images = {n.image for n in mat.node_tree.nodes if n.type == 'TEX_IMAGE'}
        self.assertEqual(sorted(i.colorspace_settings.is_data for i in images), [False, True])


if __name__ == "__main__":
    _runner_util.main()
