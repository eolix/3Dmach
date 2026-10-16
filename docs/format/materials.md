# Material translation

How the importer turns Max materials into Blender materials (`scripts/addons_core/mx_io_max/materials/`).
The goal is a render in Cycles that is recognisably the same material, and an acceptable one in EEVEE; exact
matches aren't possible because each renderer has its own BRDF.

Pipeline: `maxfile` decodes a material's parameters (by Max parameter name) → `convert.py` maps them onto a
renderer-neutral `model.Surface` → `nodes.py` builds a Principled BSDF node tree.

## Mappings

| Max material | Principled BSDF | Notes |
|---|---|---|
| **Physical Material** | base colour × base weight; roughness (inverted when "Inv" is on); metalness; IOR; reflectivity → specular level; transparency → transmission; coating → coat; emission × luminance / 1500 → emission strength; cutout map → alpha; bump map → bump | Closest match: both are modern PBR models. |
| **Standard (Legacy)** | diffuse; glossiness → roughness (1 − g/100); specular level → specular level; opacity → alpha; self-illumination → emission; bump | Blinn/Phong highlights only approximate microfacet roughness. |
| **VRayMtl** | diffuse; reflection glossiness → roughness (1 − g; or used directly with "use roughness"); reflection colour brightness → specular level, its hue → specular tint; metalness; refraction → transmission; refraction/reflection IOR (with IOR lock); fog colour → transmission tint; coat; sheen; self-illumination; bump/normal | Without Fresnel, reflection is constant at all angles: approximated with a stronger specular layer. |
| **CoronaPhysicalMtl** | base colour × level; roughness (or glossiness mode); metalness mode; IOR; refraction amount; thin mode; clearcoat; sheen; SSS amount; self-illumination; opacity; bump | |
| **CoronaMtl** (legacy) | diffuse × level; reflection level → specular level; reflection glossiness → roughness; Fresnel IOR; refraction level → transmission; self-illumination; opacity; bump | |
| **Arnold Standard Surface** | near one-to-one: Principled v2 follows the same model | |
| **Multi/Sub-Object** | one material slot per sub-material actually used; faces assigned by material ID | IDs not in the list wrap by `(id − 1) mod count` (to verify). |
| **Blend** | Mix Shader of the two materials, mask or amount as factor | Nested blends are simplified and reported. |
| Anything else | flat placeholder named after the class, with its diffuse colour if readable (magenta otherwise) | Listed in the import report. |

## Maps

| Max map | Blender nodes |
|---|---|
| Bitmap | Image Texture + UV Map (channel) + Mapping (tiling, offset, rotation); colour space sRGB for colour inputs, Non-Color for scalars and normals |
| Checker | Checker Texture (scale 2: Max has 2×2 squares per tile) |
| Noise | Noise Texture mixing colour 1 and 2; size → scale; fractal/turbulence → detail |
| Gradient | Gradient Texture + Color Ramp (Max's 3 colours, middle position) |
| Mix | Mix (colour) with amount or mask |
| Falloff | Layer Weight (perpendicular/parallel, towards/away) or Fresnel (IOR) driving a mix |
| Color Correction | Hue/Saturation + Bright/Contrast (+ Gamma) |
| Normal Bump / VRayNormalMap / CoronaNormal | Normal Map (optional green flip) + Bump for the extra bump input |
| Bump (material bump slot) | Bump node; strength = amount |

A map "amount" below 100 % mixes the map with the parameter's constant value.

Map channel 1 is the UV layer `UVMap`; channel *n* is `UVChannel_n`.

## Textures

Texture paths are resolved by `materials/textures.py`: the stored path if it exists here; then, for relative
paths, relative to the `.max` file; then the file name (case-insensitive) next to the `.max` file or in its
`maps`, `textures`, `tex`, `images` or `sourceimages` sub-folder; then anywhere below the folder chosen in the
import options. Textures still not found are listed in the import report, and the material keeps an empty
image node so it can be fixed by hand.

Each (file, colour space) pair is loaded once per import. Images already in the Blender file are never reused
or modified.
