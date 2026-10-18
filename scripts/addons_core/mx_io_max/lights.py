# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Max lights, cameras and environment to Blender (ROADMAP Phase 2f).

The ``*_from_params`` functions take decoded parameters (named after each class's own parameters,
lower_snake_case) and return plain descriptions; ``create_*`` functions build Blender data from those.
Only the ``create_*`` functions use ``bpy`` (imported lazily), so the conversions can be tested with pytest.

Intensity conversion follows the photometric definitions, with Blender's convention that 1 W of light power
corresponds to 683 lm (the luminous efficacy at 555 nm). Classes whose units are renderer-specific
("default/image" multipliers) are approximated so a default light gives a similar exposure; see
``docs/format/lights.md``.
"""

__all__ = (
    "CameraDesc",
    "LightDesc",
    "WorldDesc",
    "camera_from_params",
    "create_camera",
    "create_light",
    "kelvin_to_rgb",
    "light_from_params",
    "setup_world",
    "world_from_light",
    "world_from_params",
)

import dataclasses
import math

LUMENS_PER_WATT = 683.0
# Max's standard (non-physical) lights have no physical unit; a multiplier of 1 is mapped to this power.
STANDARD_LIGHT_WATTS = 1000.0
# V-Ray / Corona sun with multiplier 1 is a physically bright sun; this gives a similar look at exposure 0.
SUN_STRENGTH_PER_MULTIPLIER = 4.0
# Angular diameter of the sun (degrees), for sun lamps made from sun systems.
SUN_ANGLE = 0.526
# Free / Target camera clipping when "Clip Manually" is off (Max then clips nothing): near and far, scene units.
AUTO_CLIP = (0.1, 1.0e4)


# Class names as reported by `maxfile`'s class registry (Max's scripting names).
PHOTOMETRIC = {"Free_Light", "Target_Light", "Free_Point", "Target_Point", "Free_Linear", "Target_Linear",
               "Free_Area", "Target_Area"}
STANDARD_OMNI = {"Omnilight"}
STANDARD_SPOT = {"Targetspot", "Freespot"}
STANDARD_DIRECT = {"TargetDirectionallight", "Directionallight"}
# Lights in physical units, for which the Physical camera's exposure value is meaningful.
PHYSICAL_CLASSES = PHOTOMETRIC | {"Sun_Positioner"}


@dataclasses.dataclass
class LightDesc:
    name: str = "Light"
    kind: str = "POINT"                 # Blender light type: POINT, SPOT, SUN, AREA.
    color: tuple = (1.0, 1.0, 1.0)
    power: float = 1000.0               # Watts for POINT/SPOT/AREA, W/m² for SUN.
    radius: float = 0.0                 # POINT/SPOT soft size, in scene units.
    shape: str = "SQUARE"               # AREA: SQUARE, RECTANGLE, DISK, ELLIPSE.
    size: float = 1.0                   # AREA: size (x).
    size_y: float = 1.0                 # AREA: size (y) for RECTANGLE/ELLIPSE.
    spot_size: float = math.radians(45.0)   # SPOT: full cone angle (Max falloff).
    spot_blend: float = 0.15            # SPOT: from Max hotspot/falloff.
    cast_shadow: bool = True
    enabled: bool = True
    source_class: str = ""
    target: bool = False                # Has a Max target node (needs a Track To constraint).
    exposure: float = 0.0               # Blender light exposure (stops): power is multiplied by 2^exposure.
    cutoff_distance: float | None = None    # Scene units: EEVEE custom distance (Max far attenuation end).
    sun_angle: float | None = None      # SUN: angular diameter, degrees.
    direction: tuple | None = None      # World vector the light shines along (sun systems), else from the node.
    notes: list = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class CameraDesc:
    name: str = "Camera"
    lens_mm: float = 43.456             # Max default: 45° horizontal FOV on a 36 mm film.
    sensor_mm: float = 36.0
    sensor_fit: str = "HORIZONTAL"
    ortho: bool = False
    ortho_scale: float = 10.0
    clip_start: float = AUTO_CLIP[0]
    clip_end: float = AUTO_CLIP[1]
    shift_x: float = 0.0
    shift_y: float = 0.0
    use_dof: bool = False
    focus_distance: float = 10.0
    fstop: float = 8.0
    target: bool = False
    exposure_value: float | None = None     # Physical camera EV (exposure control), when stored.
    source_class: str = ""


@dataclasses.dataclass
class WorldDesc:
    color: tuple = (0.0, 0.0, 0.0)      # Max's default background is black.
    strength: float = 1.0
    environment_map: str | None = None  # Equirectangular image path, as stored.
    sky: bool = False                   # Physical sky (from a sun/sky system).
    sun_direction: tuple | None = None  # Unit vector towards the sun, for the sky texture.
    sun_disc: bool = False              # Draw the sun in the sky (off when a sun lamp lights the scene).
    source_class: str = ""
    notes: list = dataclasses.field(default_factory=list)


def kelvin_to_rgb(kelvin):
    """Approximate linear RGB of a black body at ``kelvin``, normalised to max 1 (1000 K–40000 K)."""
    t = min(max(kelvin, 1000.0), 40000.0) / 100.0
    # Curve fit of the CIE black-body locus in sRGB (Tanner Helland), then decoded to linear.
    if t <= 66.0:
        r = 255.0
        g = 99.4708025861 * math.log(t) - 161.1195681661
        b = 0.0 if t <= 19.0 else 138.5177312231 * math.log(t - 10.0) - 305.0447927307
    else:
        r = 329.698727446 * ((t - 60.0) ** -0.1332047592)
        g = 288.1221695283 * ((t - 60.0) ** -0.0755148492)
        b = 255.0

    def linear(c):
        c = min(max(c, 0.0), 255.0) / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    rgb = (linear(r), linear(g), linear(b))
    peak = max(rgb)
    return tuple(c / peak for c in rgb)


def _light_color(params):
    color = tuple(params.get("rgb", params.get("color", (1.0, 1.0, 1.0))))[:3]
    if params.get("use_kelvin", False) or params.get("color_mode") == "kelvin":
        kelvin = kelvin_to_rgb(params.get("kelvin", 6500.0))
        color = tuple(a * b for a, b in zip(color, kelvin))
    return color


def _spot_angles(params, desc):
    hotspot = math.radians(params.get("hotspot", params.get("hotspot_beam", 43.0)))
    falloff = math.radians(params.get("falloff", params.get("falloff_field", 45.0)))
    falloff = max(falloff, hotspot, 1e-4)
    desc.spot_size = min(falloff, math.pi)
    desc.spot_blend = min(max(1.0 - hotspot / falloff, 0.0), 1.0)


def photometric_power_watts(params, solid_angle, unit_scale=1.0):
    """
    Luminous intensity/flux/illuminance of a photometric light to Blender watts. ``unit_scale`` (metres per scene
    unit) converts the "lux at" distance, which ``maxfile`` gives in scene units (``lux_at_distance``).
    """
    units = params.get("intensity_type", "candelas")
    intensity = params.get("intensity", 1500.0)
    dimmer = params.get("dimmer", 100.0) / 100.0 if params.get("use_dimmer", False) else 1.0
    if units == "lumens":
        lumens = intensity
    elif units == "lux":
        # Illuminance at a distance from an isotropic source: E = I / d², I = flux / solid angle.
        if "lux_at_distance" in params:
            distance = params["lux_at_distance"] * unit_scale
        else:
            distance = params.get("lux_distance", 1.0)      # Already in metres.
        lumens = intensity * distance * distance * solid_angle
    else:  # candelas
        lumens = intensity * solid_angle
    return lumens * dimmer / LUMENS_PER_WATT


def light_from_params(class_name, params, unit_scale=1.0):
    """
    Describe a Max light. Returns None for classes we don't know (the caller reports them) and for lights that
    only light the World (see :func:`world_from_light`).

    ``unit_scale`` is the length of a scene unit in metres: intensities defined per scene unit (Arnold, V-Ray /
    Corona default units) and the photometric "lux at" distance are converted with it.
    """
    desc = LightDesc(name=params.get("name", class_name), source_class=class_name)
    desc.enabled = params.get("on", params.get("enabled", True))
    desc.cast_shadow = params.get("cast_shadows", params.get("shadows_on", True))
    desc.target = class_name.startswith("Target") or params.get("target", False)

    if class_name in PHOTOMETRIC:
        desc.color = _light_color(params)
        distribution = params.get("distribution", "uniform_spherical")
        shape = params.get("shape", "point")
        if distribution == "spotlight":
            desc.kind = "SPOT"
            _spot_angles(params, desc)
            half = desc.spot_size / 2.0
            solid_angle = 2.0 * math.pi * (1.0 - math.cos(half))
            # Blender spots emit like a point light clipped to the cone: give them the point-equivalent power.
            desc.power = photometric_power_watts(params, solid_angle, unit_scale) * (4.0 * math.pi / solid_angle)
        elif distribution == "web":
            desc.kind = "POINT"
            desc.power = photometric_power_watts(params, 4.0 * math.pi, unit_scale)
            desc.notes.append("Photometric web (IES) distribution imported as uniform")
        else:
            solid_angle = math.pi if distribution == "uniform_diffuse" else 4.0 * math.pi
            desc.power = photometric_power_watts(params, solid_angle, unit_scale)
            desc.kind = "POINT"
        if shape in {"rectangle", "disc"} and distribution != "spotlight":
            desc.kind = "AREA"
            desc.shape = "RECTANGLE" if shape == "rectangle" else "DISK"
            desc.size = params.get("length", params.get("radius", 0.5) * 2.0)
            desc.size_y = params.get("width", desc.size)
        elif shape in {"sphere", "cylinder", "line"}:
            desc.radius = params.get("radius", params.get("length", 0.1) / 2.0)
            if shape != "sphere":
                desc.notes.append("Photometric {:s} shape approximated with a point light".format(shape))
        return desc

    if class_name in STANDARD_OMNI | STANDARD_SPOT | STANDARD_DIRECT:
        desc.color = tuple(params.get("color", (1.0, 1.0, 1.0)))[:3]
        multiplier = params.get("multiplier", 1.0)
        if class_name in STANDARD_SPOT:
            desc.kind = "SPOT"
            _spot_angles(params, desc)
            desc.power = multiplier * STANDARD_LIGHT_WATTS
        elif class_name in STANDARD_DIRECT:
            desc.kind = "SUN"
            desc.power = multiplier * SUN_STRENGTH_PER_MULTIPLIER
            desc.notes.append("Directional light (parallel beam) imported as a sun lamp")
        else:
            desc.power = multiplier * STANDARD_LIGHT_WATTS
        if params.get("decay_type", "none") == "none" and desc.kind != "SUN":
            desc.notes.append("Standard light without decay: Blender lights always fall off with distance")
        if params.get("use_far_atten") and params.get("far_atten_end", 0.0) > 0.0 and desc.kind != "SUN":
            desc.cutoff_distance = params["far_atten_end"]
            desc.notes.append("Far attenuation imported as the EEVEE custom distance (Cycles ignores it)")
        return desc

    if class_name == "Arnold_Light":
        return _arnold_light(params, desc, unit_scale)

    if class_name == "Sun_Positioner":
        desc.kind = "SUN"
        desc.power = SUN_STRENGTH_PER_MULTIPLIER
        desc.sun_angle = SUN_ANGLE
        towards_sun = params.get("sun_direction")
        if towards_sun is not None:
            desc.direction = tuple(-c for c in towards_sun)
        else:
            desc.notes.append("Sun Positioner without a sun direction: the sun shines straight down")
            desc.direction = (0.0, 0.0, -1.0)
        desc.notes.append("Sun Positioner imported as a sun lamp (strength {:g}) and a sky texture".format(
            desc.power))
        return desc

    if class_name == "VRayLight":
        desc.color = _light_color(params)
        multiplier = params.get("multiplier", 30.0)
        light_type = params.get("type", "plane")
        units = params.get("normalizeColor", params.get("units", "default"))
        if light_type in {"plane", "disc"}:
            desc.kind = "AREA"
            # V-Ray stores half-length/half-width (radius for discs).
            half_l = params.get("size0", 0.5)
            half_w = params.get("size1", half_l)
            desc.shape = "RECTANGLE" if light_type == "plane" else "DISK"
            desc.size = half_l * 2.0
            desc.size_y = half_w * 2.0
            area = desc.size * desc.size_y if light_type == "plane" else math.pi * half_l * half_l
        elif light_type == "sphere":
            desc.kind = "POINT"
            desc.radius = params.get("size0", 0.5)
            area = 4.0 * math.pi * desc.radius * desc.radius
        elif light_type == "dome":
            return None  # World lighting, handled by world_from_params.
        else:
            desc.kind = "POINT"
            area = 1.0
            desc.notes.append("VRayLight type {!r} approximated with a point light".format(light_type))
        if units in {"radiant", "radiant_power", 3}:
            desc.power = multiplier
        elif units in {"luminous", "luminous_power", 1}:
            desc.power = multiplier / LUMENS_PER_WATT
        else:
            # "Default (image)" / radiance: multiplier is surface brightness, power grows with area (m²).
            desc.power = multiplier * area * unit_scale * unit_scale * math.pi
        if params.get("invisible", False):
            desc.notes.append("Invisible VRayLight: set the light's camera ray visibility off")
        return desc

    if class_name in {"CoronaLight", "CoronaSun", "VRaySun"}:
        desc.color = _light_color(params)
        if class_name in {"CoronaSun", "VRaySun"}:
            desc.kind = "SUN"
            desc.power = params.get("intensity", params.get("intensity_multiplier", 1.0)) * \
                SUN_STRENGTH_PER_MULTIPLIER
            return desc
        shape = params.get("shape", "sphere")
        intensity = params.get("intensity", 1.0)
        if shape == "rectangle":
            desc.kind, desc.shape = "AREA", "RECTANGLE"
            desc.size, desc.size_y = params.get("width", 1.0), params.get("height", 1.0)
            area = desc.size * desc.size_y
        elif shape == "disk":
            desc.kind, desc.shape = "AREA", "DISK"
            desc.size = desc.size_y = params.get("width", 1.0)
            area = math.pi * (desc.size / 2.0) ** 2
        else:
            desc.kind = "POINT"
            desc.radius = params.get("width", 1.0) / 2.0
            area = 4.0 * math.pi * desc.radius ** 2
        units = params.get("intensity_units", "default")
        if units == "lm":
            desc.power = intensity / LUMENS_PER_WATT
        elif units == "cd":
            desc.power = intensity * 4.0 * math.pi / LUMENS_PER_WATT
        else:  # Corona default units: W/(sr m²).
            desc.power = intensity * area * unit_scale * unit_scale * math.pi
        return desc

    return None


# Arnold light type -> Blender light type (and area shape).
ARNOLD_KINDS = {
    "point": ("POINT", None), "spot": ("SPOT", None), "distant": ("SUN", None),
    "quad": ("AREA", "RECTANGLE"), "disk": ("AREA", "DISK"), "cylinder": ("POINT", None),
    "photometric": ("POINT", None), "mesh": ("POINT", None),
}


def _arnold_light(params, desc, unit_scale):
    """
    Arnold Light. Arnold intensities are unitless (per scene unit): ``intensity x 2^exposure`` is taken as the
    radiant intensity (W/sr) of point and spot lights, the radiance of normalised area lights times their area
    (so the power doesn't depend on the size), the irradiance (W/m²) of distant lights. The exposure is kept as
    the Blender light's exposure.
    """
    light_type = params.get("type", "point")
    if light_type == "skydome":
        return None     # World lighting: world_from_light.
    desc.color = _light_color(params)
    desc.exposure = params.get("exposure", 0.0)
    intensity = params.get("intensity", 1.0)
    kind, shape = ARNOLD_KINDS.get(light_type, ("POINT", None))
    desc.kind = kind
    if kind == "SUN":
        desc.power = intensity
        desc.sun_angle = SUN_ANGLE
    elif kind == "AREA":
        desc.shape = shape
        if shape == "RECTANGLE":
            desc.size = params.get("quad_x", 1.0)
            desc.size_y = params.get("quad_y", desc.size)
        else:
            desc.size = desc.size_y = 2.0 * params.get("radius", 0.5)
        desc.power = math.pi * intensity * unit_scale * unit_scale
    else:
        desc.power = 4.0 * math.pi * intensity * unit_scale * unit_scale
        if kind == "SPOT":
            cone = math.radians(params.get("spot_cone_angle", 60.0))
            desc.spot_size = min(max(cone, 1e-3), math.pi)
            desc.spot_blend = 0.0
    if light_type in {"cylinder", "photometric", "mesh"}:
        desc.notes.append("Arnold {:s} light approximated with a point light".format(light_type))
    elif light_type not in ARNOLD_KINDS:
        desc.notes.append("Arnold light type {:s} imported as a point light".format(light_type))
    desc.notes.append("Arnold light intensity converted as intensity x 2^exposure per scene unit (approximation)")
    return desc


def world_from_light(class_name, params):
    """A :class:`WorldDesc` for lights that light the whole scene (Skylight, Arnold skydome, sun systems)."""
    if class_name == "Skylight":
        desc = WorldDesc(color=tuple(params.get("color", (0.95, 0.95, 1.0)))[:3],
                         strength=params.get("multiplier", 1.0), source_class=class_name)
        if params.get("sky_map") is not None:
            desc.notes.append("Skylight map not imported: the sky colour is used")
        return desc
    if class_name == "Arnold_Light" and params.get("type") == "skydome":
        strength = params.get("intensity", 1.0) * 2.0 ** params.get("exposure", 0.0)
        return WorldDesc(color=_light_color(params), strength=strength, source_class="Arnold skydome")
    if class_name == "Sun_Positioner":
        return WorldDesc(color=(0.05, 0.08, 0.12), sky=True, sun_direction=params.get("sun_direction"),
                         source_class=class_name)
    if class_name == "VRayLight" and params.get("type") == "dome":
        return WorldDesc(color=_light_color(params), strength=params.get("multiplier", 1.0),
                         source_class="VRayLight dome")
    return None


def exposure_from_ev(ev):
    """
    Blender exposure (stops) for a Max exposure value (EV at ISO 100), calibrated on middle grey: a scene of
    average luminance 0.125 x 2^EV cd/m² (the reflected-light meter constant 12.5) renders at 0.18. Blender's
    photometric scale (683 lm/W, a white diffuse surface at 1 W/m² renders at 1.0) puts 1.0 at 683 / pi cd/m².
    """
    return math.log2(0.18 * (LUMENS_PER_WATT / math.pi) / 0.125) - ev


def camera_from_params(class_name, params):
    """Describe a Max camera (Physical, Target, Free; V-Ray/Corona cameras use the same names)."""
    desc = CameraDesc(name=params.get("name", class_name), source_class=class_name)
    desc.target = class_name.startswith("Target") or params.get("targeted", False)
    if "film_width_mm" in params or class_name == "Physical":
        desc.sensor_mm = params.get("film_width_mm", 36.0)
        if params.get("specify_fov", False) and "fov" in params:
            desc.lens_mm = desc.sensor_mm / (2.0 * math.tan(math.radians(params["fov"]) / 2.0))
        else:
            desc.lens_mm = params.get("focal_length_mm", 40.0) * params.get("zoom_factor", 1.0)
        # Max lens shift is in percent of the frame width.
        desc.shift_x = params.get("horizontal_shift", 0.0) / 100.0
        desc.shift_y = params.get("vertical_shift", 0.0) / 100.0
        desc.use_dof = params.get("use_dof", False)
        desc.fstop = params.get("f_number", 8.0)
        desc.focus_distance = params.get("focus_distance", params.get("target_distance", 10.0))
    else:
        fov = math.radians(params.get("fov", 45.0))
        axis = params.get("fov_type", "horizontal")
        desc.sensor_fit = {"horizontal": "HORIZONTAL", "vertical": "VERTICAL"}.get(axis, "AUTO")
        desc.lens_mm = desc.sensor_mm / (2.0 * math.tan(fov / 2.0))
        desc.focus_distance = params.get("target_distance", desc.focus_distance)
    if params.get("exposure_value") is not None:
        desc.exposure_value = params["exposure_value"]
    desc.ortho = params.get("orthographic", False) or params.get("orthoProjection", False)
    if desc.ortho:
        fov = 2.0 * math.atan(desc.sensor_mm / (2.0 * desc.lens_mm))
        desc.ortho_scale = 2.0 * desc.focus_distance * math.tan(fov / 2.0)
    if params.get("clip_on", params.get("clip_manually", False)):
        desc.clip_start = params.get("near_clip", params.get("clip_near", desc.clip_start))
        desc.clip_end = params.get("far_clip", params.get("clip_far", desc.clip_end))
    return desc


def world_from_params(params):
    """Environment settings: ``background_color``, ``environment_map`` (path), ``use_map``, and optional sky."""
    desc = WorldDesc(color=tuple(params.get("background_color", (0.0, 0.0, 0.0)))[:3])
    if params.get("use_map", True) and params.get("environment_map"):
        desc.environment_map = params["environment_map"]
        desc.strength = params.get("map_multiplier", 1.0)
    if params.get("sky", False):
        desc.sky = True
        desc.sun_direction = params.get("sun_direction")
    return desc


# Blender side.


def create_light(desc, collection, scene_scale=1.0):
    """Create a light object; ``scene_scale`` converts sizes from scene units to metres."""
    import bpy
    light = bpy.data.lights.new(desc.name, desc.kind)
    light.color = desc.color
    light.energy = desc.power
    light.use_shadow = desc.cast_shadow
    if desc.kind in {"POINT", "SPOT"}:
        light.shadow_soft_size = desc.radius * scene_scale
    if desc.kind == "SPOT":
        light.spot_size = desc.spot_size
        light.spot_blend = desc.spot_blend
    if desc.kind == "AREA":
        light.shape = desc.shape
        light.size = desc.size * scene_scale
        light.size_y = desc.size_y * scene_scale
    if desc.exposure:
        light.exposure = desc.exposure
    if desc.cutoff_distance:
        light.use_custom_distance = True
        light.cutoff_distance = desc.cutoff_distance * scene_scale
    if desc.kind == "SUN" and desc.sun_angle is not None:
        light.angle = math.radians(desc.sun_angle)
    light["mx_source_class"] = desc.source_class
    obj = bpy.data.objects.new(desc.name, light)
    obj.hide_viewport = obj.hide_render = not desc.enabled
    collection.objects.link(obj)
    return obj


def create_camera(desc, collection, scene_scale=1.0):
    import bpy
    cam = bpy.data.cameras.new(desc.name)
    cam.type = 'ORTHO' if desc.ortho else 'PERSP'
    cam.lens = desc.lens_mm
    cam.sensor_width = desc.sensor_mm
    cam.sensor_fit = desc.sensor_fit
    cam.ortho_scale = desc.ortho_scale * scene_scale
    cam.clip_start = desc.clip_start * scene_scale
    cam.clip_end = desc.clip_end * scene_scale
    cam.shift_x = desc.shift_x
    cam.shift_y = desc.shift_y
    cam.dof.use_dof = desc.use_dof
    cam.dof.focus_distance = desc.focus_distance * scene_scale
    cam.dof.aperture_fstop = desc.fstop
    cam["mx_source_class"] = desc.source_class
    obj = bpy.data.objects.new(desc.name, cam)
    collection.objects.link(obj)
    return obj


def add_target_constraint(obj, target, roll=0.0):
    """
    Point ``obj`` (local -Z, +Y up as near world +Z as possible) at ``target`` like a Max Look At controller.

    ``roll`` (radians, about the viewing axis) is added by a Transformation constraint mapping a zero range of the
    target's location to a constant rotation about local Z, after the Track To.
    """
    con = obj.constraints.new('TRACK_TO')
    con.name = "Target"
    con.target = target
    con.track_axis = 'TRACK_NEGATIVE_Z'
    con.up_axis = 'UP_Y'
    if roll:
        tc = obj.constraints.new('TRANSFORM')
        tc.name = "Roll"
        tc.target = target
        tc.map_from = 'LOCATION'
        tc.map_to = 'ROTATION'
        tc.from_min_x = tc.from_max_x = 0.0
        tc.to_min_z_rot = tc.to_max_z_rot = roll
        tc.mix_mode_rot = 'AFTER'
        tc.owner_space = tc.target_space = 'WORLD'
    return con


def setup_world(scene, desc, image_loader=None):
    """Configure ``scene.world`` from a WorldDesc. ``image_loader(path) -> Image | None`` loads maps."""
    import bpy
    world = scene.world or bpy.data.worlds.new("World")
    scene.world = world
    if world.node_tree is None:
        world.use_nodes = True
    tree = world.node_tree
    for node in list(tree.nodes):
        tree.nodes.remove(node)
    out = tree.nodes.new("ShaderNodeOutputWorld")
    out.location = (300.0, 0.0)
    bg = tree.nodes.new("ShaderNodeBackground")
    bg.inputs["Strength"].default_value = desc.strength
    bg.inputs["Color"].default_value = (*desc.color, 1.0)
    tree.links.new(bg.outputs["Background"], out.inputs["Surface"])
    world.color = desc.color
    if desc.environment_map and image_loader is not None:
        image = image_loader(desc.environment_map)
        if image is not None:
            env = tree.nodes.new("ShaderNodeTexEnvironment")
            env.location = (-300.0, 0.0)
            env.image = image
            tree.links.new(env.outputs["Color"], bg.inputs["Color"])
    elif desc.sky:
        sky = tree.nodes.new("ShaderNodeTexSky")
        sky.location = (-300.0, 0.0)
        if desc.sun_direction:
            x, y, z = desc.sun_direction
            sky.sun_elevation = math.asin(max(-1.0, min(1.0, z)))
            sky.sun_rotation = math.atan2(x, y)
        if hasattr(sky, "sun_disc"):
            sky.sun_disc = desc.sun_disc
        tree.links.new(sky.outputs["Color"], bg.inputs["Color"])
    return world
