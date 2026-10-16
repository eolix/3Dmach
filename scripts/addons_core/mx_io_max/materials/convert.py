# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Max material families to :class:`model.Surface`.

Each converter takes a dict of decoded parameters named after the material's own parameter names (the names
shown in Max's UI and scripting, lower_snake_case), with texture maps already converted to ``model`` maps under
``<param>_map`` keys, and returns a :class:`model.Surface`. Missing parameters fall back to the class defaults
documented for that material. The mappings approximate each renderer's BRDF with Blender's Principled BSDF;
where the approximation is coarse it says so.

No Blender dependency.
"""

__all__ = (
    "CONVERTERS",
    "convert",
)

import math

from . import model
from .model import Input


def _input(params, key, default, map_key=None, amount_key=None):
    """An :class:`Input` from ``params[key]`` and an optional ``params[key + "_map"]``."""
    map_key = map_key or key + "_map"
    tex = params.get(map_key)
    amount = params.get(amount_key, 1.0) if amount_key else 1.0
    if params.get(map_key + "_on") is False:
        tex = None
    return Input(params.get(key, default), tex, amount)


def _scaled_color(color, weight):
    return tuple(min(max(c * weight, 0.0), 1.0) for c in color[:3])


def _normal(params, normal_key="bump_map", amount_key="bump_map_amount", default_amount=1.0):
    tex = params.get(normal_key)
    if tex is None or params.get(normal_key + "_on") is False:
        return None
    if isinstance(tex, (model.NormalMap, model.Bump)):
        return tex
    return model.Bump(input=tex, strength=params.get(amount_key, default_amount))


def gloss_to_roughness(glossiness):
    """V-Ray / Corona style glossiness (1 = mirror) to Principled roughness. Linear: both are perceptual."""
    return min(max(1.0 - glossiness, 0.0), 1.0)


def physical_material(params):
    """Physical Material (the Max 2017+ default PBR material)."""
    s = model.Surface(name=params.get("name", "Material"), source_class="PhysicalMaterial")
    weight = params.get("base_weight", 1.0)
    s.base_color = _input(params, "base_color", (0.5, 0.5, 0.5))
    if not s.base_color.has_map:
        s.base_color.value = _scaled_color(s.base_color.value, weight)
    s.roughness = _input(params, "roughness", 0.0)
    if params.get("roughness_inv", False):  # "Inv" checkbox: the value is glossiness.
        s.roughness.value = 1.0 - s.roughness.value
    s.metallic = _input(params, "metalness", 0.0)
    s.ior = params.get("trans_ior", 1.52)
    s.specular_ior_level = 0.5 * params.get("reflectivity", 1.0)
    s.specular_tint = tuple(params.get("refl_color", (1.0, 1.0, 1.0)))
    s.transmission = _input(params, "transparency", 0.0)
    s.transmission_color = params.get("trans_color")
    s.thin_walled = params.get("thin_walled", False)
    s.subsurface_weight = params.get("scattering", 0.0)
    s.coat_weight = params.get("coating", 0.0)
    s.coat_roughness = params.get("coat_roughness", 0.0)
    s.coat_ior = params.get("coat_ior", 1.5)
    if params.get("emission", 0.0) > 0.0:
        s.emission_color = _input(params, "emit_color", (1.0, 1.0, 1.0))
        # Luminance in cd/m² (nits) -> Blender emission strength: 1.0 is roughly "white at exposure 0";
        # Max's default 1500 nits is a typical lamp surface. Coarse, see docs/format/materials.md.
        s.emission_strength = params.get("emission", 1.0) * params.get("emit_luminance", 1500.0) / 1500.0
    cutout = params.get("cutout_map")
    if cutout is not None:
        s.alpha = Input(1.0, cutout)
    s.normal = _normal(params, "bump_map", "bump_map_amt", 0.3)
    s.viewport_color = s.base_color.value if isinstance(s.base_color.value, tuple) else None
    return s


def standard_material(params):
    """Standard (Legacy) material with Blinn/Phong shading."""
    s = model.Surface(name=params.get("name", "Material"), source_class="Standardmaterial")
    s.base_color = _input(params, "diffuse", (0.5, 0.5, 0.5), "diffuse_map", "diffuse_map_amount")
    level = params.get("specular_level", 0.0) / 100.0        # 0..999 %, usually 0..100.
    glossiness = params.get("glossiness", 10.0) / 100.0      # 0..100.
    # Blinn/Phong highlights don't map exactly onto a microfacet roughness; linear is a coarse but predictable match.
    s.roughness = Input(gloss_to_roughness(glossiness), params.get("glossiness_map"))
    s.specular_ior_level = min(level, 2.0) * 0.5
    s.specular_tint = tuple(params.get("specular", (1.0, 1.0, 1.0)))
    opacity = params.get("opacity", 100.0) / 100.0
    s.alpha = Input(opacity, params.get("opacity_map"), params.get("opacity_map_amount", 1.0))
    self_illum = params.get("self_illum_amount", 0.0) / 100.0
    if params.get("use_self_illum_color"):
        s.emission_color = Input(tuple(params.get("self_illum_color", (0.0, 0.0, 0.0))))
        s.emission_strength = 1.0
    elif self_illum > 0.0:
        s.emission_color = Input(s.base_color.value, s.base_color.map)
        s.emission_strength = self_illum
    s.normal = _normal(params, "bump_map", "bump_map_amount", 0.3)
    s.viewport_color = tuple(s.base_color.value)
    return s


def vray_material(params):
    """VRayMtl."""
    s = model.Surface(name=params.get("name", "Material"), source_class="VRayMtl")
    s.base_color = _input(params, "diffuse", (0.5, 0.5, 0.5), "texmap_diffuse", "texmap_diffuse_multiplier")
    reflection = tuple(params.get("reflection", (0.0, 0.0, 0.0)))
    s.roughness = Input(gloss_to_roughness(params.get("reflection_glossiness", 1.0)),
                        params.get("texmap_reflectionglossiness"))
    if params.get("brdf_useroughness", False):
        s.roughness.value = 1.0 - s.roughness.value  # The value is already roughness.
    s.metallic = _input(params, "reflection_metalness", 0.0, "texmap_metalness")
    # The reflection colour scales the (Fresnel) reflection: its brightness sets the specular level,
    # its hue the specular tint. Principled's level 0.5 = the physically correct amount for the IOR.
    refl_max = max(reflection)
    s.specular_ior_level = 0.5 * min(refl_max, 1.0)
    if refl_max > 0.0:
        s.specular_tint = tuple(c / refl_max for c in reflection)
    if params.get("reflection_lockior", True):
        s.ior = params.get("refraction_ior", 1.6)
    else:
        s.ior = params.get("reflection_ior", 1.6)
    if not params.get("reflection_fresnel", True):
        # Without Fresnel, reflection is constant at all angles: a stronger specular layer is the closest match.
        s.specular_ior_level = min(refl_max, 1.0)
    refraction = tuple(params.get("refraction", (0.0, 0.0, 0.0)))
    s.transmission = Input(model.luminance(refraction), params.get("texmap_refraction"))
    if s.transmission.value > 0.0:
        s.ior = params.get("refraction_ior", 1.6)
        fog = params.get("refraction_fogcolor")
        s.transmission_color = tuple(fog) if fog else None
    opacity = params.get("texmap_opacity")
    if opacity is not None:
        s.alpha = Input(1.0, opacity)
    if params.get("coat_amount", 0.0) > 0.0:
        s.coat_weight = params["coat_amount"]
        s.coat_roughness = gloss_to_roughness(params.get("coat_glossiness", 1.0))
        s.coat_ior = params.get("coat_ior", 1.6)
    if params.get("sheen_amount", 0.0) > 0.0:
        s.sheen_weight = params["sheen_amount"]
        s.sheen_tint = tuple(params.get("sheen_color", (1.0, 1.0, 1.0)))
    s.emission_color = _input(params, "selfillumination", (0.0, 0.0, 0.0), "texmap_self_illumination")
    s.emission_strength = params.get("selfillumination_multiplier", 1.0) if (
        s.emission_color.has_map or model.luminance(s.emission_color.value) > 0.0) else 0.0
    s.normal = _normal(params, "texmap_bump", "texmap_bump_multiplier", 0.3)
    s.viewport_color = tuple(s.base_color.value)
    return s


def corona_physical_material(params):
    """CoronaPhysicalMtl."""
    s = model.Surface(name=params.get("name", "Material"), source_class="CoronaPhysicalMtl")
    s.base_color = _input(params, "base_color", (0.8, 0.8, 0.8), "base_texmap")
    if not s.base_color.has_map:
        s.base_color.value = _scaled_color(s.base_color.value, params.get("base_level", 1.0))
    s.roughness = Input(params.get("base_roughness", 0.0), params.get("base_roughness_texmap"))
    if params.get("roughness_mode", 0) == 1:  # Glossiness mode.
        s.roughness.value = 1.0 - s.roughness.value
    s.metallic = Input(1.0 if params.get("metalness_mode", 0) == 1 else 0.0, params.get("metalness_texmap"))
    s.ior = params.get("base_ior", 1.52)
    s.transmission = Input(params.get("refraction_amount", 0.0), params.get("refraction_amount_texmap"))
    s.thin_walled = params.get("use_thin_mode", False)
    s.coat_weight = params.get("clearcoat_amount", 0.0)
    s.coat_roughness = params.get("clearcoat_roughness", 0.0)
    s.coat_ior = params.get("clearcoat_ior", 1.5)
    s.sheen_weight = params.get("sheen_amount", 0.0)
    s.subsurface_weight = params.get("sss_amount", 0.0)
    if params.get("self_illumination_level", 0.0) > 0.0:
        s.emission_color = _input(params, "self_illumination_color", (1.0, 1.0, 1.0),
                                  "self_illumination_texmap")
        s.emission_strength = params["self_illumination_level"]
    opacity = params.get("opacity_texmap")
    if opacity is not None or params.get("opacity_level", 1.0) < 1.0:
        s.alpha = Input(params.get("opacity_level", 1.0), opacity)
    s.normal = _normal(params, "base_bump_texmap", "base_bump_mapping_amount", 1.0)
    s.viewport_color = tuple(s.base_color.value)
    return s


def corona_legacy_material(params):
    """CoronaMtl (legacy Corona material)."""
    s = model.Surface(name=params.get("name", "Material"), source_class="CoronaMtl")
    s.base_color = _input(params, "color_diffuse", (0.5, 0.5, 0.5), "texmap_diffuse")
    if not s.base_color.has_map:
        s.base_color.value = _scaled_color(s.base_color.value, params.get("level_diffuse", 1.0))
    refl = params.get("level_reflect", 0.0)
    s.specular_ior_level = 0.5 * min(refl, 1.0)
    s.roughness = Input(gloss_to_roughness(params.get("reflect_glossiness", 1.0)),
                        params.get("texmap_reflect_glossiness"))
    s.ior = params.get("fresnel_ior", 1.52)
    refract = params.get("level_refract", 0.0)
    s.transmission = Input(refract, params.get("texmap_refract"))
    if refract > 0.0:
        s.ior = params.get("ior", 1.52)
    if params.get("level_self_illum", 0.0) > 0.0:
        s.emission_color = _input(params, "color_self_illum", (1.0, 1.0, 1.0), "texmap_self_illum")
        s.emission_strength = params["level_self_illum"]
    opacity = params.get("texmap_opacity")
    if opacity is not None or params.get("level_opacity", 1.0) < 1.0:
        s.alpha = Input(params.get("level_opacity", 1.0), opacity)
    s.normal = _normal(params, "texmap_bump", "mapamount_bump", 1.0)
    s.viewport_color = tuple(s.base_color.value)
    return s


def arnold_standard_surface(params):
    """Arnold Standard Surface: its parameters are the model Principled v2 follows, so mostly one-to-one."""
    s = model.Surface(name=params.get("name", "Material"), source_class="ai_standard_surface")
    s.base_color = _input(params, "base_color", (0.8, 0.8, 0.8), "base_color_shader")
    if not s.base_color.has_map:
        s.base_color.value = _scaled_color(s.base_color.value, params.get("base", 1.0))
    s.metallic = _input(params, "metalness", 0.0, "metalness_shader")
    s.roughness = _input(params, "specular_roughness", 0.2, "specular_roughness_shader")
    s.specular_ior_level = 0.5 * params.get("specular", 1.0)
    s.specular_tint = tuple(params.get("specular_color", (1.0, 1.0, 1.0)))
    s.ior = params.get("specular_ior", 1.5)
    s.transmission = _input(params, "transmission", 0.0, "transmission_shader")
    s.transmission_color = params.get("transmission_color")
    s.subsurface_weight = params.get("subsurface", 0.0)
    s.coat_weight = params.get("coat", 0.0)
    s.coat_roughness = params.get("coat_roughness", 0.1)
    s.coat_ior = params.get("coat_ior", 1.5)
    s.sheen_weight = params.get("sheen", 0.0)
    s.sheen_tint = tuple(params.get("sheen_color", (1.0, 1.0, 1.0)))
    s.anisotropic = params.get("specular_anisotropy", 0.0)
    s.emission_color = _input(params, "emission_color", (1.0, 1.0, 1.0), "emission_color_shader")
    s.emission_strength = params.get("emission", 0.0)
    opacity = params.get("opacity", (1.0, 1.0, 1.0))
    s.alpha = Input(model.luminance(opacity) if isinstance(opacity, tuple) else opacity, params.get("opacity_shader"))
    s.thin_walled = params.get("thin_walled", False)
    s.normal = params.get("normal_shader")
    s.viewport_color = tuple(s.base_color.value)
    return s


def placeholder(class_name, params):
    diffuse = None
    for key in ("diffuse", "base_color", "color_diffuse", "diffuse_color"):
        value = params.get(key)
        if isinstance(value, tuple) and len(value) >= 3:
            diffuse = tuple(value[:3])
            break
    return model.Placeholder(name=params.get("name", class_name), source_class=class_name, diffuse=diffuse)


CONVERTERS = {
    "PhysicalMaterial": physical_material,
    "Standardmaterial": standard_material,
    "VRayMtl": vray_material,
    "CoronaPhysicalMtl": corona_physical_material,
    "CoronaMtl": corona_legacy_material,
    "ai_standard_surface": arnold_standard_surface,
}


def convert(class_name, params):
    """Convert one material; unknown classes give a :class:`model.Placeholder`."""
    converter = CONVERTERS.get(class_name)
    if converter is None:
        return placeholder(class_name, params)
    surface = converter(params)
    if not math.isfinite(surface.ior) or surface.ior < 1.0:
        surface.ior = 1.5
    return surface
