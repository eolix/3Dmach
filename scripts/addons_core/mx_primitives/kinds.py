# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Primitive kinds as shown in the UI (no Blender dependency)."""

__all__ = ("KINDS", "ICONS", "label")

# (kind, label, description), in the order of the Max-style Create panel (two buttons per row).
KINDS = [
    ("BOX", "Box", "Box with length, width and height segments"),
    ("CONE", "Cone", "Cone or truncated cone, with optional slice"),
    ("SPHERE", "Sphere", "Sphere made of segments around and from pole to pole, with hemisphere and slice"),
    ("GEOSPHERE", "GeoSphere", "Geodesic sphere built from a tetrahedron, octahedron or icosahedron"),
    ("CYLINDER", "Cylinder", "Cylinder with height and cap segments, with optional slice"),
    ("TUBE", "Tube", "Hollow cylinder with two radii"),
    ("TORUS", "Torus", "Ring with a round cross-section, rotation and twist"),
    ("PYRAMID", "Pyramid", "Pyramid with a rectangular base"),
    ("TEST_SHAPE", "Test Shape", "Original procedural test object: a pot with lid, handle and spout"),
    ("PLANE", "Plane", "Flat grid"),
]

# Generic Blender icons per kind.
ICONS = {
    "BOX": 'MESH_CUBE',
    "CONE": 'MESH_CONE',
    "SPHERE": 'MESH_UVSPHERE',
    "GEOSPHERE": 'MESH_ICOSPHERE',
    "CYLINDER": 'MESH_CYLINDER',
    "TUBE": 'MESH_CIRCLE',
    "TORUS": 'MESH_TORUS',
    "PYRAMID": 'TRIA_UP',
    "TEST_SHAPE": 'MESH_MONKEY',
    "PLANE": 'MESH_PLANE',
}

_LABELS = {kind: name for kind, name, _description in KINDS}


def label(kind):
    return _LABELS.get(kind, kind)
