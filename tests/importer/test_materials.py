# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Max material families to the neutral material model, and texture path resolution. Run: pytest tests/importer"""

import importlib
import importlib.util
import os
import sys

import pytest

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
MATERIALS_DIR = os.path.join(ROOT, "scripts", "addons_core", "mx_io_max", "materials")

# Import the `materials` sub-package on its own (the add-on package itself needs `bpy`).
_spec = importlib.util.spec_from_file_location(
    "mx_materials", os.path.join(MATERIALS_DIR, "__init__.py"), submodule_search_locations=[MATERIALS_DIR])
_pkg = importlib.util.module_from_spec(_spec)
sys.modules["mx_materials"] = _pkg
_spec.loader.exec_module(_pkg)
model = importlib.import_module("mx_materials.model")
convert = importlib.import_module("mx_materials.convert")
textures = importlib.import_module("mx_materials.textures")


class TestConvert:

    def test_unknown_class_is_placeholder(self):
        result = convert.convert("SomePluginMtl", {"name": "Wood", "diffuse": (0.5, 0.25, 0.1)})
        assert isinstance(result, model.Placeholder)
        assert result.name == "Wood"
        assert result.source_class == "SomePluginMtl"
        assert result.diffuse == (0.5, 0.25, 0.1)

    def test_physical(self):
        bitmap = model.Bitmap(path="C:\\maps\\wood.jpg")
        s = convert.convert("PhysicalMaterial", {
            "name": "Floor", "base_color": (1.0, 0.5, 0.0), "base_weight": 0.5,
            "roughness": 0.3, "roughness_inv": True, "metalness": 1.0, "trans_ior": 1.33,
            "base_color_map": bitmap,
        })
        assert s.name == "Floor"
        assert s.base_color.map is bitmap
        assert s.roughness.value == pytest.approx(0.7)
        assert s.metallic.value == 1.0
        assert s.ior == pytest.approx(1.33)

    def test_physical_weight_scales_color_without_map(self):
        s = convert.convert("PhysicalMaterial", {"base_color": (1.0, 0.5, 0.0), "base_weight": 0.5})
        assert s.base_color.value == pytest.approx((0.5, 0.25, 0.0))

    def test_vray_glossiness_and_reflection(self):
        s = convert.convert("VRayMtl", {
            "diffuse": (0.2, 0.2, 0.2), "reflection": (0.5, 0.5, 0.25), "reflection_glossiness": 0.8,
            "refraction_ior": 1.5,
        })
        assert s.roughness.value == pytest.approx(0.2)
        assert s.specular_ior_level == pytest.approx(0.25)
        assert s.specular_tint == pytest.approx((1.0, 1.0, 0.5))
        assert s.ior == pytest.approx(1.5)
        assert s.transmission.value == 0.0

    def test_vray_glass(self):
        s = convert.convert("VRayMtl", {"refraction": (1.0, 1.0, 1.0), "refraction_ior": 1.52,
                                        "reflection": (1.0, 1.0, 1.0)})
        assert s.transmission.value == pytest.approx(1.0)
        assert s.ior == pytest.approx(1.52)

    def test_vray_bump_becomes_bump(self):
        bump = model.Bitmap(path="bump.png")
        s = convert.convert("VRayMtl", {"texmap_bump": bump, "texmap_bump_multiplier": 0.5})
        assert isinstance(s.normal, model.Bump)
        assert s.normal.input is bump and s.normal.strength == 0.5

    def test_vray_normal_map_passes_through(self):
        normal = model.NormalMap(input=model.Bitmap(path="n.png"))
        assert convert.convert("VRayMtl", {"texmap_bump": normal}).normal is normal

    def test_standard(self):
        s = convert.convert("Standardmaterial", {"diffuse": (0.6, 0.6, 0.6), "glossiness": 40.0,
                                                 "specular_level": 50.0, "opacity": 50.0})
        assert s.roughness.value == pytest.approx(0.6)
        assert s.specular_ior_level == pytest.approx(0.25)
        assert s.alpha.value == pytest.approx(0.5)

    def test_corona_physical_metal(self):
        s = convert.convert("CoronaPhysicalMtl", {"base_color": (0.9, 0.6, 0.2), "metalness_mode": 1,
                                                  "base_roughness": 0.25})
        assert s.metallic.value == 1.0
        assert s.roughness.value == pytest.approx(0.25)

    def test_corona_legacy(self):
        s = convert.convert("CoronaMtl", {"color_diffuse": (1.0, 1.0, 1.0), "level_diffuse": 0.5,
                                          "level_reflect": 1.0, "reflect_glossiness": 0.9})
        assert s.base_color.value == pytest.approx((0.5, 0.5, 0.5))
        assert s.roughness.value == pytest.approx(0.1)

    def test_arnold(self):
        s = convert.convert("ai_standard_surface", {"base_color": (0.8, 0.1, 0.1), "metalness": 0.5,
                                                    "specular_roughness": 0.4, "emission": 2.0})
        assert s.metallic.value == 0.5
        assert s.roughness.value == pytest.approx(0.4)
        assert s.emission_strength == 2.0

    def test_map_toggle_off(self):
        s = convert.convert("PhysicalMaterial", {"base_color_map": model.Bitmap(path="a.png"),
                                                 "base_color_map_on": False})
        assert s.base_color.map is None


class TestTextures:

    def touch(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "wb").close()
        return path

    def test_existing_absolute(self, tmp_path):
        tex = self.touch(str(tmp_path / "a.png"))
        assert textures.TextureResolver(str(tmp_path / "s.max")).resolve(tex) == tex

    def test_windows_path_next_to_scene(self, tmp_path):
        self.touch(str(tmp_path / "proj" / "maps" / "Wood.JPG"))
        resolver = textures.TextureResolver(str(tmp_path / "proj" / "scene.max"))
        found = resolver.resolve("D:\\Clients\\Job\\maps\\wood.jpg")
        assert found == str(tmp_path / "proj" / "maps" / "Wood.JPG")
        assert resolver.missing == []

    def test_relative_path(self, tmp_path):
        self.touch(str(tmp_path / "proj" / "tex" / "sub" / "a.png"))
        resolver = textures.TextureResolver(str(tmp_path / "proj" / "scene.max"))
        assert resolver.resolve("tex\\sub\\a.png") == str(tmp_path / "proj" / "tex" / "sub" / "a.png")

    def test_search_dirs_and_missing(self, tmp_path):
        self.touch(str(tmp_path / "library" / "deep" / "brick.tif"))
        resolver = textures.TextureResolver(str(tmp_path / "proj" / "scene.max"),
                                            search_dirs=[str(tmp_path / "library")])
        assert resolver.resolve("C:\\maps\\BRICK.tif") == str(tmp_path / "library" / "deep" / "brick.tif")
        assert resolver.resolve("C:\\maps\\nothere.png") is None
        assert resolver.resolve("C:\\maps\\nothere.png") is None
        assert resolver.missing == ["C:\\maps\\nothere.png"]

    def test_empty(self, tmp_path):
        assert textures.TextureResolver(str(tmp_path / "s.max")).resolve("") is None
