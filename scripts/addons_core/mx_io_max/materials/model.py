# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Renderer-neutral description of a material, between Max's material classes and Blender node trees.

Converters (one module per Max material family) turn decoded Max parameters into a :class:`Surface`;
``nodes.py`` turns a :class:`Surface` into a Principled BSDF node tree. Keeping this middle layer plain data
(no ``bpy``) lets the Max-to-PBR mapping be unit-tested with pytest.

Every input is either a constant or an :class:`Input` combining a constant with a texture map.
"""

__all__ = (
    "Bitmap",
    "Blend",
    "Bump",
    "Checker",
    "ColorCorrection",
    "Falloff",
    "Gradient",
    "Input",
    "Mix",
    "MultiSub",
    "Noise",
    "NormalMap",
    "Placeholder",
    "Surface",
    "TextureMap",
    "luminance",
)

import dataclasses


def luminance(color):
    """Rec. 709 luminance of an RGB triple (how a colour reflect/refract amount becomes a scalar)."""
    r, g, b = color[:3]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


# Texture maps.


@dataclasses.dataclass
class TextureMap:
    """Base class: every map has an optional output amount (Max's map "amount" spinner) applied by the user."""
    name: str = ""


@dataclasses.dataclass
class Bitmap(TextureMap):
    path: str = ""                      # As stored in the .max file (often an absolute Windows path).
    uv_channel: int = 1                 # Max map channel (1 = first UV set).
    tiling: tuple = (1.0, 1.0)
    offset: tuple = (0.0, 0.0)
    rotation: float = 0.0               # Radians, around W.
    # Max's "Real-World Map Size": tiling is in scene units rather than repeats.
    real_world_size: tuple | None = None
    # None = automatic (sRGB for colour inputs, non-colour for scalar inputs and normals).
    srgb: bool | None = None
    use_alpha: bool = False             # Output the alpha channel instead of RGB (e.g. cutout from a PNG).
    invert: bool = False


@dataclasses.dataclass
class Checker(TextureMap):
    color1: tuple = (0.0, 0.0, 0.0)
    color2: tuple = (1.0, 1.0, 1.0)
    map1: TextureMap | None = None
    map2: TextureMap | None = None
    tiling: tuple = (1.0, 1.0)
    uv_channel: int = 1


@dataclasses.dataclass
class Noise(TextureMap):
    color1: tuple = (0.0, 0.0, 0.0)
    color2: tuple = (1.0, 1.0, 1.0)
    size: float = 25.0                  # Max noise size, in scene units.
    levels: float = 3.0
    kind: str = "REGULAR"               # "REGULAR", "FRACTAL", "TURBULENCE".


@dataclasses.dataclass
class Gradient(TextureMap):
    colors: tuple = ((0.0, 0.0, 0.0), (0.5, 0.5, 0.5), (1.0, 1.0, 1.0))   # Max Gradient: 3 colours.
    position2: float = 0.5
    kind: str = "LINEAR"                # "LINEAR" or "RADIAL".
    uv_channel: int = 1


@dataclasses.dataclass
class Mix(TextureMap):
    a: "TextureMap | tuple | None" = None
    b: "TextureMap | tuple | None" = None
    amount: "float | TextureMap" = 0.5  # 0 = all a, 1 = all b; a map acts as the mask.


@dataclasses.dataclass
class Falloff(TextureMap):
    near: "TextureMap | tuple" = (0.0, 0.0, 0.0)
    far: "TextureMap | tuple" = (1.0, 1.0, 1.0)
    kind: str = "PERPENDICULAR_PARALLEL"    # Or "FRESNEL", "TOWARDS_AWAY", "SHADOW_LIGHT", "DISTANCE_BLEND".
    ior: float = 1.6                    # For "FRESNEL".


@dataclasses.dataclass
class ColorCorrection(TextureMap):
    input: "TextureMap | tuple | None" = None
    hue: float = 0.0                    # Degrees, -180..180.
    saturation: float = 0.0             # Percent, -100..100.
    brightness: float = 0.0             # Percent, -100..100.
    contrast: float = 0.0               # Percent, -100..100.
    gamma: float = 1.0


@dataclasses.dataclass
class NormalMap(TextureMap):
    """Normal Bump / VRayNormalMap / CoronaNormal: tangent-space normal map plus optional extra bump."""
    input: TextureMap | None = None
    strength: float = 1.0
    flip_green: bool = False
    bump: "TextureMap | None" = None
    bump_strength: float = 1.0


@dataclasses.dataclass
class Bump(TextureMap):
    input: TextureMap | None = None
    strength: float = 1.0               # Max bump amount as a fraction (Standard's 30 -> 0.3).


@dataclasses.dataclass
class Input:
    """A material input: a constant, optionally replaced/modulated by a map."""
    value: "float | tuple" = 0.0
    map: TextureMap | None = None
    # Max map amount: 1 = the map replaces the value, 0.5 = halfway between value and map.
    map_amount: float = 1.0

    @property
    def has_map(self):
        return self.map is not None and self.map_amount > 0.0


# Materials.


@dataclasses.dataclass
class Surface:
    """A single physically based surface; field names follow Blender's Principled BSDF."""
    name: str = "Material"
    base_color: Input = dataclasses.field(default_factory=lambda: Input((0.8, 0.8, 0.8)))
    metallic: Input = dataclasses.field(default_factory=lambda: Input(0.0))
    roughness: Input = dataclasses.field(default_factory=lambda: Input(0.5))
    ior: float = 1.5
    specular_ior_level: float = 0.5     # Principled default; 0 removes the specular layer.
    specular_tint: tuple = (1.0, 1.0, 1.0)
    transmission: Input = dataclasses.field(default_factory=lambda: Input(0.0))
    transmission_color: tuple | None = None     # Tints transmission through base colour in Principled.
    alpha: Input = dataclasses.field(default_factory=lambda: Input(1.0))
    emission_color: Input = dataclasses.field(default_factory=lambda: Input((0.0, 0.0, 0.0)))
    emission_strength: float = 0.0
    coat_weight: float = 0.0
    coat_roughness: float = 0.03
    coat_ior: float = 1.5
    sheen_weight: float = 0.0
    sheen_tint: tuple = (1.0, 1.0, 1.0)
    subsurface_weight: float = 0.0
    subsurface_radius: tuple = (1.0, 0.2, 0.1)
    anisotropic: float = 0.0
    normal: TextureMap | None = None    # NormalMap or Bump.
    thin_walled: bool = False
    double_sided: bool = True
    # Diffuse-only viewport colour, used for Blender's solid view and the Max "show shaded material" look.
    viewport_color: tuple | None = None
    source_class: str = ""              # Max class name, for the import report and node-tree labels.


@dataclasses.dataclass
class MultiSub:
    """Multi/Sub-Object: sub-materials by material ID. ``ids[i]`` is the material ID of ``materials[i]``."""
    name: str = "Multi/Sub"
    ids: list = dataclasses.field(default_factory=list)
    materials: list = dataclasses.field(default_factory=list)   # Surface | Blend | Placeholder | None.


@dataclasses.dataclass
class Blend:
    """Blend / layered material: ``b`` over ``a`` by ``amount`` (a float or a mask map)."""
    name: str = "Blend"
    a: "Surface | Blend | None" = None
    b: "Surface | Blend | None" = None
    amount: "float | TextureMap" = 0.5
    source_class: str = ""


@dataclasses.dataclass
class Placeholder:
    """An unsupported material: imported as a flat material named after the class, and reported."""
    name: str = "Material"
    source_class: str = "Unknown"
    diffuse: tuple | None = None
