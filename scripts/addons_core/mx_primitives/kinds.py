# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Primitive kinds as shown in the UI (no Blender dependency)."""

__all__ = ("KINDS", "ICONS", "label")

# (kind, label, description), in the order of the Max-style Create panel (two buttons per row). The stored
# enumeration numbers come from the order of ``geometry.PARAMETERS``, not from this list.
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
    # Extended primitives, in the order of the Max-style Create panel.
    ("HEDRA", "Hedra", "Polyhedra of the tetrahedron, cube / octahedron and dodecahedron / icosahedron families"),
    ("TORUS_KNOT", "Torus Knot", "Tube swept along a (p, q) torus knot or a warped circle"),
    ("CHAMFERBOX", "ChamferBox", "Box with rounded (filleted) edges"),
    ("CHAMFERCYL", "ChamferCyl", "Cylinder with rounded (filleted) cap edges"),
    ("OILTANK", "OilTank", "Cylinder with convex caps"),
    ("CAPSULE", "Capsule", "Cylinder with hemispherical caps"),
    ("SPINDLE", "Spindle", "Cylinder with conical caps"),
    ("L_EXT", "L-Ext", "Extruded L shape"),
    ("GENGON", "Gengon", "Extruded regular polygon with optionally filleted side edges"),
    ("C_EXT", "C-Ext", "Extruded C shape"),
    ("PRISM", "Prism", "Prism with a triangular base of three side lengths"),
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
    "HEDRA": 'MESH_ICOSPHERE',
    "TORUS_KNOT": 'SURFACE_NTORUS',
    "CHAMFERBOX": 'MOD_BEVEL',
    "CHAMFERCYL": 'MESH_CYLINDER',
    "OILTANK": 'META_CAPSULE',
    "CAPSULE": 'MESH_CAPSULE',
    "SPINDLE": 'MESH_CONE',
    "L_EXT": 'MOD_SOLIDIFY',
    "GENGON": 'MESH_CIRCLE',
    "C_EXT": 'MOD_SOLIDIFY',
    "PRISM": 'TRIA_UP',
}

_LABELS = {kind: name for kind, name, _description in KINDS}


def label(kind):
    return _LABELS.get(kind, kind)
