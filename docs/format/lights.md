# Lights, cameras and environment

How the importer converts Max lights and cameras (`scripts/addons_core/mx_io_max/lights.py`).

## Light intensity

Blender's light power is in watts; Blender treats 1 W as 683 lm (the luminous efficacy at 555 nm).

| Max light | Blender | Intensity |
|---|---|---|
| Photometric, uniform spherical | Point | cd × 4π / 683 W; lm / 683; lux × d² × 4π / 683 (the "lux at" distance d is stored in scene units: converted to metres) |
| Photometric, uniform diffuse | Point | as above with a π solid angle |
| Photometric, spotlight | Spot (cone = falloff, blend from hotspot/falloff) | point-equivalent power, so the on-axis intensity matches |
| Photometric, web (IES) | Point | imported as uniform, reported |
| Photometric shapes: rectangle, disc | Area (rectangle, disk) | |
| Photometric shapes: sphere, cylinder, line | Point with radius | reported |
| Colour by Kelvin | Black-body RGB × filter colour | |
| Omni / Spot (standard) | Point / Spot | multiplier × 1000 W (no physical unit) |
| Directional (standard) | Sun | multiplier × 4 |
| VRayLight plane / disc | Area (V-Ray stores half sizes: doubled) | default units: multiplier × area × π; luminous power lm / 683; radiant power W |
| VRayLight sphere | Point with radius | |
| VRayLight dome, Skylight | World (Skylight: sky colour × multiplier) | The Skylight's map is not imported |
| Arnold Light point / spot | Point / Spot (cone angle) | 4π × intensity × unit² W, Arnold exposure as the light's exposure (intensity × 2^exposure taken as W/sr per scene unit) |
| Arnold Light quad / disk | Area rectangle (quad X / Y) / disk | π × intensity × unit² W (normalised area light) |
| Arnold Light distant | Sun | intensity W/m², exposure as the light's exposure |
| Arnold Light skydome | World | colour × intensity × 2^exposure |
| Arnold Light cylinder / mesh / photometric | Point | reported |
| Sun Positioner | Sun lamp (strength 4, 0.526° angle) shining along the decoded sun direction, plus a Sky Texture with the sun's elevation and rotation | The north direction's sense is a guess |
| Standard light far attenuation | EEVEE custom distance | Cycles ignores it |
| VRaySun / CoronaSun | Sun | multiplier × 4, tuned to look right at exposure 0 |
| CoronaLight sphere / rectangle / disk | Point / Area | default units W/(sr·m²) × area × π; lm; cd |

Standard Max lights without decay don't fall off with distance, which Blender lights can't reproduce; the
import report says so.

## Cameras

| Max | Blender |
|---|---|
| Physical camera | lens = focal length × zoom (or from FOV when "Specify FOV" is on); sensor = film width; lens shift in % of frame width; depth of field and f-number |
| Target / Free camera | lens from FOV (horizontal by default, vertical or diagonal as stored); orthographic projection; clipping planes when "Clip Manually" is on |
| Target (Look At controller) | Track To constraint (−Z to the target, +Y up) to the target node's object, plus a Transformation constraint adding the Look At roll; any node with a Look At controller gets them |

The first camera becomes the scene camera when the scene has none. A Physical camera's exposure value sets the
scene exposure (Blender exposure = log2(0.18 × (683 / π) / 0.125) − EV ≈ 8.29 − EV, middle-grey calibration) only
for scenes lit by photometric lights without a sun system, where both are in physical units. Cameras without
manual clipping clip at 0.1 and 10,000 scene units.

The target nodes ("Target" helper objects) and Dummy / Point helpers import as empties.

## Environment

The background colour and environment map become the World: a Background node with the colour, or an
Environment Texture with the map and its multiplier. A sun/sky system gives a Sky Texture with the sun's
elevation and rotation.
