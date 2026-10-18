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
| **Multi/Sub-Object** | one material slot per sub-material actually used; faces assigned by material ID (`maxfile` gives the IDs 1-based: they are stored 0-based) | IDs not in the list wrap by `(id − 1) mod count` (to verify). A Multi/Sub inside another material uses its first sub-material (reported). |
| **Blend** | Mix Shader of its two component materials, the mask map (when enabled) or the mix amount as factor | Nested blends are simplified and reported. |
| **Double Sided**, **Top/Bottom**, **Shellac**, other materials made of materials | their first component (front, top, base) | Reported. |
| Anything else | flat placeholder named after the class, with its diffuse colour if readable (magenta otherwise) | Listed in the import report. |

## Maps

| Max map | Blender nodes |
|---|---|
| Bitmap | Image Texture + UV Map (channel) + Mapping (tiling, offset, W angle about the map centre, like Max); colour space sRGB for colour inputs, Non-Color for scalars and normals. The stored path is resolved first, then the path Max last resolved the asset to (asset metadata) |
| Checker | Checker Texture (scale 2: Max has 2×2 squares per tile), colours or maps 1 / 2, tiling |
| Noise | Noise Texture in object coordinates mixing colour (or map) 1 and 2; size (scene units) → scale per metre; fractal / turbulence → detail |
| Gradient | Gradient Texture + Color Ramp (Max's 3 colours, colour 2 position, linear / radial) |
| Mix | Mix (colour) of colour or map 1 and 2, mask map or mix amount |
| Mask | Mix from black to the map with the mask as factor |
| Falloff | Layer Weight (perpendicular/parallel, towards/away) or Fresnel (IOR) driving a mix of colour or map 1 and 2 |
| Color Correction | Hue/Saturation + Bright/Contrast (+ Gamma) of its map or colour |
| Normal Bump / VRayNormalMap / CoronaNormal | Normal Map (strength, optional green flip) + Bump for the extra bump input |
| Bump (material bump slot) | Bump node; strength = amount |
| Output, RGB Tint, RGB Multiply, Composite, Bump 2D, Vertex Color | their first input map (reported as approximated) |
| Anything else | not converted: the parameter keeps its constant value (reported) |

`maxfile` names the parameters of Bitmap, Checker, Noise, Mix and Normal Bump. Falloff, Gradient, Mask and Color
Correction are read by the importer from their ParamBlock2 by ID (`materials/maps.py`); evidence from the corpus:

| Map (block ref) | IDs | Evidence |
|---|---|---|
| Falloff (0; 82 maps) | 0 colour 1, 1 / 5 map amounts, 2 map 1, 3 map 1 on, 4 colour 2, 6 map 2, 7 map 2 on, 8 type (0 towards/away, 1 perpendicular/parallel, 2 Fresnel, 3 shadow/light, 4 distance blend), 9 direction, 12 IOR | colour 1 black on 59 and colour 2 white on 56 (Max's defaults); type 1 on 53 (the default); IOR 1.6 on all (the default) |
| Gradient (1; 83) | 0-2 colours 1-3, 3-5 maps, 6-8 map on, 9 colour 2 position, 10 type (0 linear, 1 radial) | black / 0.5 grey / white defaults; position 0.5 on 50 |
| Mask (2; 94) | 0 map, 1 mask, 2 / 3 on, 4 invert | the referenced classes; invert off on all |
| Color Correction (0; 119) | 0 colour, 1 map (71 Bitmaps), 7 hue shift, 8 saturation, 12 brightness, 13 contrast | Guess for 7-13: UI order and value ranges (saturation -100..100) |

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
