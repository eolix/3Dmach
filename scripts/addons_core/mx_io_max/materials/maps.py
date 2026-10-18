# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
``maxfile`` maps (``MapData``) to :mod:`model` texture maps.

Bitmap, Checker, Noise, Mix and Normal Bump come with named parameters from ``maxfile``. Falloff, Gradient, Mask
and Color Correction are read here from their parameter blocks by ID (the IDs and their evidence are listed
below and in ``docs/format/materials.md``); ``param_reader(map_data)`` supplies those blocks, so this module
has no dependency on Blender or on ``maxfile`` itself. Maps that have no conversion pass their first child map
through when they have one (reported as approximated), otherwise they are reported as unsupported.
"""

__all__ = (
    "MapConverter",
    "PARAM_TABLES",
)

import math

from . import model

# Importer-side parameter tables, (reference slot of the ParamBlock2, {param id: key}). Evidence: the corpus
# (82 Falloff, 83 Gradient, 94 Mask, 119 Color Correction maps): defaults and the classes of the maps referenced.
PARAM_TABLES = {
    # Falloff: colour 1 black / colour 2 white (59 / 56), amounts 100, map on flags, type 1 (53 of 82: Max's
    # default Perpendicular/Parallel), 12 IOR 1.6 (Max's default) on all.
    "Falloff": (0, {0: "color1", 1: "map1_amount", 2: "map1", 3: "map1_on", 4: "color2", 5: "map2_amount",
                    6: "map2", 7: "map2_on", 8: "falloff_type", 9: "direction", 12: "ior"}),
    # Gradient: colours black / 0.5 grey / white (Max's defaults), maps 3-5 with on flags 6-8, 9 colour 2
    # position (0.5 on 50), 10 type (0 linear, 1 radial).
    "Gradient": (1, {0: "color1", 1: "color2", 2: "color3", 3: "map1", 4: "map2", 5: "map3", 6: "map1_on",
                     7: "map2_on", 8: "map3_on", 9: "color2_pos", 10: "gradient_type"}),
    # Mask: 0 map, 1 mask, 2 / 3 on flags (all on), 4 invert (off on all).
    "Mask": (2, {0: "map", 1: "mask", 2: "map_on", 3: "mask_on", 4: "invert"}),
    # Color Correction: 0 colour, 1 map (71 Bitmaps), 7 hue shift (degrees), 8 saturation (percent, -100..100),
    # 12 brightness, 13 contrast (percent). Guess: 7-13 from the UI order and value ranges.
    "Color Correction": (0, {0: "color", 1: "map", 7: "hue_shift", 8: "saturation", 12: "brightness",
                             13: "contrast"}),
}

# Max Falloff types, in the order of its list.
FALLOFF_TYPES = {0: "TOWARDS_AWAY", 1: "PERPENDICULAR_PARALLEL", 2: "FRESNEL", 3: "SHADOW_LIGHT",
                 4: "DISTANCE_BLEND"}
NOISE_TYPES = {0: "REGULAR", 1: "FRACTAL", 2: "TURBULENCE"}
BITMAP_CLASSES = {"Bitmaptexture", "Bitmap", "VRayBitmap", "CoronaBitmap"}
# Maps that become their first child map when nothing better is possible.
PASS_THROUGH = {"Output", "RGB Tint", "RGB Multiply", "Composite", "composite", "Bump 2D", "Vertex Color"}


def _rgb(value, default=(0.0, 0.0, 0.0)):
    if isinstance(value, (tuple, list)) and len(value) >= 3:
        return tuple(float(c) for c in value[:3])
    return default


def _on(params, key):
    return params.get(key) is not False


class MapConverter:
    """
    Converts maps for one import, caching by map object so shared maps are converted once.

    :arg param_reader: ``f(map_data, slot) -> {param id: value} | None`` for maps converted from raw
       parameter blocks; None to skip them.
    :arg unsupported: ``f(class_name)`` called for maps that can't be converted.
    :arg note: ``f(text)`` called for approximations.
    """

    def __init__(self, param_reader=None, unsupported=None, note=None):
        self.param_reader = param_reader
        self.unsupported = unsupported or (lambda name: None)
        self.note = note or (lambda text: None)
        self._cache = {}
        self._active = set()

    def convert(self, tex):
        if tex is None:
            return None
        key = getattr(tex, "index", None)
        key = key if key is not None else id(tex)
        if key in self._cache:
            return self._cache[key]
        if key in self._active:
            return None     # A map that contains itself.
        self._active.add(key)
        try:
            result = self._convert(tex)
        finally:
            self._active.discard(key)
        self._cache[key] = result
        return result

    def _table(self, tex):
        entry = PARAM_TABLES.get(tex.class_name)
        if entry is None or self.param_reader is None:
            return None
        raw = self.param_reader(tex, entry[0])
        if raw is None:
            return None
        return {key: raw[pid] for pid, key in entry[1].items() if pid in raw}

    def _child(self, value):
        """A child map value: MapData -> converted map; object indices are resolved by the param reader."""
        if value is None:
            return None
        if hasattr(value, "class_name"):
            return self.convert(value)
        return None

    def _convert(self, tex):
        name = tex.class_name
        params = tex.params or {}
        if name in BITMAP_CLASSES:
            if not (tex.path or getattr(tex, "resolved_path", None)):
                return None
            mirror = (params.get("u_mirror", False), params.get("v_mirror", False))
            if any(mirror):
                self.note("Bitmap mirror tiling imported as plain tiling")
            return model.Bitmap(
                name=tex.name or "", path=tex.path or "",
                resolved_path=getattr(tex, "resolved_path", None),
                uv_channel=params.get("map_channel", 1),
                tiling=(params.get("u_tiling", 1.0), params.get("v_tiling", 1.0)),
                offset=(params.get("u_offset", 0.0), params.get("v_offset", 0.0)),
                rotation=params.get("w_angle", 0.0),
            )
        if name == "Checker":
            return model.Checker(
                name=tex.name or "",
                color1=_rgb(params.get("color1"), (0.0, 0.0, 0.0)),
                color2=_rgb(params.get("color2"), (1.0, 1.0, 1.0)),
                map1=self._child(params.get("map1")) if _on(params, "map1_on") else None,
                map2=self._child(params.get("map2")) if _on(params, "map2_on") else None,
                tiling=(params.get("u_tiling", 1.0), params.get("v_tiling", 1.0)),
                uv_channel=params.get("map_channel", 1),
            )
        if name == "Noise":
            return model.Noise(
                name=tex.name or "",
                color1=_rgb(params.get("color1"), (0.0, 0.0, 0.0)),
                color2=_rgb(params.get("color2"), (1.0, 1.0, 1.0)),
                map1=self._child(params.get("map1")) if _on(params, "map1_on") else None,
                map2=self._child(params.get("map2")) if _on(params, "map2_on") else None,
                size=params.get("size", 25.0),
                levels=params.get("levels", 3.0),
                kind=NOISE_TYPES.get(params.get("noise_type", 0), "REGULAR"),
            )
        if name == "Mix":
            amount = params.get("mix_amount", 0.0)
            amount = amount / 100.0 if amount > 1.0 else amount
            mask = self._child(params.get("mask")) if _on(params, "mask_on") else None
            if params.get("use_curve"):
                self.note("Mix map curve (upper / lower) not imported")
            return model.Mix(
                name=tex.name or "",
                a=(self._child(params.get("map1")) if _on(params, "map1_on") else None)
                or _rgb(params.get("color1"), (0.0, 0.0, 0.0)),
                b=(self._child(params.get("map2")) if _on(params, "map2_on") else None)
                or _rgb(params.get("color2"), (1.0, 1.0, 1.0)),
                amount=mask if mask is not None else amount,
            )
        if name == "Normal_Bump":
            normal = self._child(params.get("normal_map")) if params.get("map1on", True) is not False else None
            bump = self._child(params.get("bump_map")) if params.get("map2on", True) is not False else None
            if params.get("flip_red") or params.get("swap_rg"):
                self.note("Normal Bump red flip / channel swap not imported")
            if normal is None and bump is None:
                return None
            return model.NormalMap(
                name=tex.name or "", input=normal, strength=params.get("mult_spin", 1.0),
                flip_green=bool(params.get("flip_green", False)),
                bump=bump, bump_strength=params.get("bump_spin", 1.0),
            )
        table = self._table(tex)
        if table is not None:
            converted = self._from_table(tex, table)
            if converted is not None:
                return converted
        return self._fallback(tex)

    def _from_table(self, tex, p):
        name = tex.class_name
        maps = {s.index: s for s in (tex.sub_maps or []) if getattr(s, "index", None) is not None}

        def child(key, on_key=None):
            index = p.get(key)
            if index is None or (on_key and p.get(on_key) is False):
                return None
            sub = maps.get(index)
            return self.convert(sub) if sub is not None else None

        if name == "Falloff":
            kind = FALLOFF_TYPES.get(p.get("falloff_type", 1), "PERPENDICULAR_PARALLEL")
            near = child("map1", "map1_on") or _rgb(p.get("color1"), (0.0, 0.0, 0.0))
            far = child("map2", "map2_on") or _rgb(p.get("color2"), (1.0, 1.0, 1.0))
            if p.get("direction", 0) != 0:
                self.note("Falloff direction other than the viewing direction imported as the viewing direction")
            return model.Falloff(name=tex.name or "", near=near, far=far, kind=kind, ior=p.get("ior", 1.6))
        if name == "Gradient":
            colors = (_rgb(p.get("color1"), (0.0, 0.0, 0.0)), _rgb(p.get("color2"), (0.5, 0.5, 0.5)),
                      _rgb(p.get("color3"), (1.0, 1.0, 1.0)))
            if any(child("map{:d}".format(i), "map{:d}_on".format(i)) for i in (1, 2, 3)):
                self.note("Gradient colour maps not imported (colours used)")
            return model.Gradient(name=tex.name or "", colors=colors, position2=p.get("color2_pos", 0.5),
                                  kind="RADIAL" if p.get("gradient_type", 0) == 1 else "LINEAR",
                                  uv_channel=(tex.params or {}).get("map_channel", 1))
        if name == "Mask":
            source = child("map", "map_on")
            mask = child("mask", "mask_on")
            if source is None:
                return None
            if mask is None:
                return source
            if p.get("invert"):
                self.note("Inverted Mask map imported without inversion")
            return model.Mix(name=tex.name or "", a=(0.0, 0.0, 0.0), b=source, amount=mask)
        if name == "Color Correction":
            source = child("map") or _rgb(p.get("color"), (0.0, 0.0, 0.0))
            return model.ColorCorrection(
                name=tex.name or "", input=source, hue=p.get("hue_shift", 0.0),
                saturation=p.get("saturation", 0.0), brightness=p.get("brightness", 0.0),
                contrast=p.get("contrast", 0.0))
        return None

    def _fallback(self, tex):
        subs = [s for s in (tex.sub_maps or []) if s is not None]
        if subs and (tex.class_name in PASS_THROUGH or tex.class_name.startswith("ai_")):
            converted = self.convert(subs[0])
            if converted is not None:
                self.note("{:s} map approximated by its first input map".format(tex.class_name))
                return converted
        self.unsupported(tex.class_name)
        return None


def rotate_uv_center(tiling, offset, rotation):
    """
    Blender Mapping node (POINT) location for Max's UV placement: Max tiles and rotates around the map centre
    and shifts by the offset, ``uv' = R(-w) (S (uv - c - o)) + c``; Blender computes ``L + R (S uv)``.
    Returns ``(location xy, rotation z)``.
    """
    c, s = math.cos(-rotation), math.sin(-rotation)
    px, py = (0.5 + offset[0]) * tiling[0], (0.5 + offset[1]) * tiling[1]
    return (0.5 - (c * px - s * py), 0.5 - (s * px + c * py)), -rotation
