# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
The neutral scene model the writer takes: plain dataclasses, independent of Blender and of the file layout.

Conventions are those of :mod:`maxfile` (``docs/decisions/0008-maxfile-api.md``): vectors ``(x, y, z)``,
quaternions ``(w, x, y, z)`` (Blender's convention; the writer converts to the file's), lengths in scene units,
colours as 0-1 floats, wire colours as 0-255 ints, material IDs 1-based as Max shows them, percentages as Max's
UI numbers (0-100).
"""

__all__ = (
    "Scene", "Node", "Transform", "EditablePoly", "MapChannel", "Bitmap", "StandardMaterial", "PhysicalMaterial",
    "MultiSubMaterial", "UNITS",
)

import dataclasses

# System unit codes (overview.md §4.2; codes 2 and 6 assumed from the order).
UNITS = {"inches": 0, "feet": 1, "miles": 2, "millimeters": 3, "centimeters": 4, "meters": 5, "kilometers": 6}


@dataclasses.dataclass
class Transform:
    """Position / rotation / scale, relative to the parent node (Max's controller values)."""
    position: tuple = (0.0, 0.0, 0.0)
    rotation: tuple = (1.0, 0.0, 0.0, 0.0)     # (w, x, y, z)
    scale: tuple = (1.0, 1.0, 1.0)


@dataclasses.dataclass
class MapChannel:
    """One map channel: map vertices (u, v, w) and one map face per polygon, with the polygon's corner count."""
    vertices: list
    faces: list


@dataclasses.dataclass
class EditablePoly:
    """Polygon mesh written as an Editable Poly object."""
    positions: list                             # [(x, y, z)]
    polygons: list                              # [[vertex index, ...]] (3 or more corners, Max corner order)
    material_ids: list | None = None            # Per polygon, 1-based (Max's UI numbers); None: all 1.
    smoothing_groups: list | None = None        # Per polygon, a bit mask (bit 0 = group 1); None: none.
    map_channels: dict = dataclasses.field(default_factory=dict)    # {channel number: MapChannel}


@dataclasses.dataclass
class Bitmap:
    """A Bitmap texture map."""
    path: str
    name: str = ""
    u_offset: float = 0.0
    v_offset: float = 0.0
    u_tiling: float = 1.0
    v_tiling: float = 1.0
    w_angle: float = 0.0                        # Radians.
    map_channel: int = 1


@dataclasses.dataclass
class StandardMaterial:
    """A Standard material with the Blinn shader."""
    name: str
    diffuse: tuple = (150 / 255, 150 / 255, 150 / 255)    # Max's default grey (627 of 912 corpus Blinns)
    ambient: tuple | None = None                # None: locked to the diffuse colour, like Max's default.
    specular: tuple = (0.9, 0.9, 0.9)
    specular_level: float = 0.0                 # Percent.
    glossiness: float = 10.0                    # Percent.
    opacity: float = 100.0                      # Percent.
    self_illumination: float = 0.0              # Percent.
    two_sided: bool = False
    wire: bool = False
    diffuse_map: Bitmap | None = None
    specular_map: Bitmap | None = None
    specular_level_map: Bitmap | None = None
    glossiness_map: Bitmap | None = None
    opacity_map: Bitmap | None = None
    bump_map: Bitmap | None = None
    bump_amount: float = 30.0                   # Percent (Max's default 30).


@dataclasses.dataclass
class PhysicalMaterial:
    """A Physical Material (Max 2017 and later)."""
    name: str
    base_color: tuple = (0.5, 0.5, 0.5)
    base_weight: float = 1.0
    reflectivity: float = 1.0
    roughness: float = 0.0
    roughness_inverted: bool = False            # True: ``roughness`` is a glossiness.
    metalness: float = 0.0
    transparency: float = 0.0
    trans_ior: float = 1.52
    emission: float = 0.0
    emit_color: tuple = (1.0, 1.0, 1.0)
    thin_walled: bool = False
    base_color_map: Bitmap | None = None
    roughness_map: Bitmap | None = None
    metalness_map: Bitmap | None = None
    transparency_map: Bitmap | None = None
    emission_map: Bitmap | None = None
    bump_map: Bitmap | None = None
    bump_amount: float = 0.3
    cutout_map: Bitmap | None = None


@dataclasses.dataclass
class MultiSubMaterial:
    """A Multi/Sub-Object material: sub-material i is used by faces with material ID ``ids[i]`` (1-based)."""
    name: str
    materials: list                             # Sub-materials (None for an empty slot).
    ids: list | None = None                     # 1-based; None: 1, 2, 3, ...
    names: list | None = None                   # Slot names; None: empty.


@dataclasses.dataclass(eq=False)
class Node:
    """A scene node. ``mesh`` None makes a Dummy helper (e.g. a group parent)."""
    name: str
    parent: "Node | None" = None
    transform: Transform = dataclasses.field(default_factory=Transform)
    object_offset: Transform = dataclasses.field(default_factory=Transform)
    mesh: EditablePoly | None = None
    material: object = None                     # StandardMaterial, PhysicalMaterial or MultiSubMaterial.
    wire_color: tuple = (87, 224, 198)
    hidden: bool = False
    frozen: bool = False
    dummy_size: float = 10.0                    # Box size of a Dummy (nodes without a mesh), scene units.


@dataclasses.dataclass
class Scene:
    """The scene: nodes (parents before or after children, any order) and the system unit."""
    nodes: list = dataclasses.field(default_factory=list)
    unit: str = "inches"                        # A key of UNITS.
    unit_scale: float = 1.0                     # "1 unit = unit_scale <unit>"
    frame_rate: int = 30
    animation_end: int = 100                    # Frames.
    comment: str = ""

    def add(self, node: Node) -> Node:
        self.nodes.append(node)
        return node
