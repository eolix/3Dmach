# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Geometry of the Max-style primitives, with no Blender dependency.

``generate(kind, **params)`` returns a :class:`MeshData` for one of the kinds in :data:`PARAMETERS`.
The live-primitive add-on writes it into a Blender mesh; the ``.max`` importer uses it to rebuild primitives
from their stored parameters. This module must not import ``bpy`` or ``mathutils`` (a test enforces this).

Conventions, all following Max:

- Z is up. Box, Cylinder, Cone, Tube and Pyramid have their pivot at the centre of the base; Sphere, GeoSphere
  and Torus at their centre (unless "base to pivot"); Plane at its centre. Extended primitives: ChamferBox,
  ChamferCyl, Capsule, OilTank, Spindle, Gengon, L-Ext and C-Ext at the centre of the base, Prism at the corner
  where side 1 starts, Torus Knot and Hedra at their centre.
- Box and ChamferBox: width along X, length along Y, height along Z. Pyramid: width X, depth Y. Plane: width X,
  length Y. L-Ext / C-Ext: front (and back) length along X, side length along Y.
- Angles (slice, rotation, twist) are in radians. Ring vertices run counter-clockwise seen from +Z and start at
  +X (Cylinder, Cone and the extended primitives) or at +Y (Sphere, Tube, Torus), as in Max (:data:`RING_START`).
  With slice on, the part that is kept runs counter-clockwise from ``slice_from`` to ``slice_to``, measured from
  the ring start; equal angles give the whole object back.
- Faces are wound counter-clockwise seen from outside, so normals point outwards.
- ``material_ids`` are 0-based (Max shows ID + 1 in its UI).
- ``smoothing_groups`` are Max-style 32-bit masks: two faces sharing an edge are smoothed across it when their
  masks share a bit; 0 means a faceted face. :meth:`MeshData.sharp_edges` turns them into sharp edges.
- ``uvs`` are per face corner, following "Generate Mapping Coords" (``None`` when it is off).

Vertex and face order: each generator creates vertices and faces in one fixed, commented order, so that the order
can be changed to Max's once real files with cached meshes are available (``docs/format/overview.md`` §6.3).
Topology details that could not be checked against Max are listed in ``docs/decisions/0006-live-primitives.md``.
"""

__all__ = (
    "KIND_IDS",
    "PARAMETERS",
    "ENUMS",
    "LIMITS",
    "MeshData",
    "normalize_params",
    "generate",
)

import math

TAU = 2.0 * math.pi

# Kinds and their parameters with defaults, in the order of Max's "Parameters" rollout.
# Sizes are in Blender units (metres); the defaults are only used for creation without interaction.
_SLICE = {"slice_on": False, "slice_from": 0.0, "slice_to": 0.0}

PARAMETERS = {
    "BOX": {
        "length": 1.0, "width": 1.0, "height": 1.0,
        "length_segments": 1, "width_segments": 1, "height_segments": 1,
        "generate_uvs": True,
    },
    "SPHERE": {
        "radius": 0.5, "segments": 32, "smooth": True, "hemisphere": 0.0, "hemisphere_mode": "CHOP",
        **_SLICE, "base_to_pivot": False, "generate_uvs": True,
    },
    "GEOSPHERE": {
        "radius": 0.5, "segments": 4, "base_type": "ICOSA", "smooth": True, "hemisphere_on": False,
        "base_to_pivot": False, "generate_uvs": True,
    },
    "CYLINDER": {
        "radius": 0.5, "height": 1.0, "height_segments": 5, "cap_segments": 1, "sides": 18, "smooth": True,
        **_SLICE, "generate_uvs": True,
    },
    "TUBE": {
        "radius1": 0.5, "radius2": 0.4, "height": 1.0, "height_segments": 5, "cap_segments": 1, "sides": 18,
        "smooth": True, **_SLICE, "generate_uvs": True,
    },
    "CONE": {
        "radius1": 0.5, "radius2": 0.0, "height": 1.0, "height_segments": 5, "cap_segments": 1, "sides": 24,
        "smooth": True, **_SLICE, "generate_uvs": True,
    },
    "TORUS": {
        "radius1": 0.5, "radius2": 0.15, "rotation": 0.0, "twist": 0.0, "segments": 24, "sides": 12,
        "smooth_mode": "ALL", **_SLICE, "generate_uvs": True,
    },
    "PYRAMID": {
        "width": 1.0, "depth": 1.0, "height": 1.0,
        "width_segments": 1, "depth_segments": 1, "height_segments": 1,
        "generate_uvs": True,
    },
    "PLANE": {
        "length": 1.0, "width": 1.0, "length_segments": 4, "width_segments": 4,
        "generate_uvs": True,
    },
    "TEST_SHAPE": {
        "radius": 0.5, "segments": 4, "smooth": True,
        "part_body": True, "part_handle": True, "part_spout": True, "part_lid": True,
        "generate_uvs": True,
    },
    # Extended primitives. Appended: the order of this table numbers the kinds stored in files.
    "CHAMFERBOX": {
        "length": 1.0, "width": 1.0, "height": 1.0, "fillet": 0.1,
        "length_segments": 1, "width_segments": 1, "height_segments": 1, "fillet_segments": 3,
        "smooth": True, "generate_uvs": True,
    },
    "CHAMFERCYL": {
        "radius": 0.5, "height": 1.0, "fillet": 0.1, "height_segments": 1, "fillet_segments": 1, "sides": 12,
        "cap_segments": 1, "smooth": True, **_SLICE, "generate_uvs": True,
    },
    "CAPSULE": {
        "radius": 0.5, "height": 2.0, "height_type": "OVERALL", "sides": 12, "height_segments": 1, "smooth": True,
        **_SLICE, "generate_uvs": True,
    },
    "OILTANK": {
        "radius": 0.5, "height": 2.0, "cap_height": 0.25, "height_type": "OVERALL", "blend": 0.0, "sides": 12,
        "height_segments": 1, "smooth": True, **_SLICE, "generate_uvs": True,
    },
    "SPINDLE": {
        "radius": 0.5, "height": 2.0, "cap_height": 0.5, "height_type": "OVERALL", "blend": 0.0, "sides": 24,
        "cap_segments": 1, "height_segments": 1, "smooth": True, **_SLICE, "generate_uvs": True,
    },
    "GENGON": {
        "sides": 5, "radius": 0.5, "fillet": 0.0, "height": 1.0,
        "side_segments": 1, "height_segments": 1, "fillet_segments": 1, "smooth": True, "generate_uvs": True,
    },
    "PRISM": {
        "side1_length": 1.0, "side2_length": 1.0, "side3_length": 1.0, "height": 1.0,
        "side1_segments": 1, "side2_segments": 1, "side3_segments": 1, "height_segments": 1, "generate_uvs": True,
    },
    "L_EXT": {
        "side_length": 1.0, "front_length": 1.0, "side_width": 0.25, "front_width": 0.25, "height": 1.0,
        "side_segments": 1, "front_segments": 1, "width_segments": 1, "height_segments": 1, "generate_uvs": True,
    },
    "C_EXT": {
        "back_length": 1.0, "side_length": 1.0, "front_length": 1.0,
        "back_width": 0.25, "side_width": 0.25, "front_width": 0.25, "height": 1.0,
        "back_segments": 1, "side_segments": 1, "front_segments": 1, "width_segments": 1, "height_segments": 1,
        "generate_uvs": True,
    },
    "TORUS_KNOT": {
        "base_curve": "KNOT", "radius": 0.5, "segments": 120, "p": 2.0, "q": 3.0,
        "warp_count": 0.0, "warp_height": 0.0,
        "cross_section_radius": 0.1, "sides": 12, "eccentricity": 1.0, "twist": 0.0,
        "lumps": 0.0, "lump_height": 0.0, "lump_offset": 0.0,
        "smooth_mode": "ALL", "generate_uvs": True,
    },
    "HEDRA": {
        "family": "TETRA", "family_p": 0.0, "family_q": 0.0,
        "axis_scale_p": 100.0, "axis_scale_q": 100.0, "axis_scale_r": 100.0,
        "vertex_mode": "BASIC", "radius": 0.5, "generate_uvs": True,
    },
}

KIND_IDS = tuple(PARAMETERS)

# Allowed values of the enumeration parameters.
ENUMS = {
    "hemisphere_mode": ("CHOP", "SQUASH"),
    "base_type": ("TETRA", "OCTA", "ICOSA"),
    "smooth_mode": ("ALL", "SIDES", "NONE", "SEGMENTS"),
    "height_type": ("OVERALL", "CENTERS"),
    "base_curve": ("KNOT", "CIRCLE"),
    "family": ("TETRA", "CUBE_OCTA", "DODEC_ICOS", "STAR1", "STAR2"),
    "vertex_mode": ("BASIC", "CENTER", "CENTER_SIDES"),
}

# (minimum, maximum) per parameter; ``None`` means unbounded. Kind-specific entries override the generic ones.
_GENERIC_LIMITS = {
    "length": (0.0, None), "width": (0.0, None), "depth": (0.0, None), "height": (None, None),
    "radius": (0.0, None), "radius1": (0.0, None), "radius2": (0.0, None),
    "length_segments": (1, 1000), "width_segments": (1, 1000), "depth_segments": (1, 200),
    "height_segments": (1, 200), "cap_segments": (1, 100), "sides": (3, 200), "segments": (3, 200),
    "hemisphere": (0.0, 1.0),
    "fillet": (0.0, None), "fillet_segments": (1, 100), "cap_height": (0.0, None), "blend": (0.0, None),
    "side_segments": (1, 200), "side1_length": (0.0, None), "side2_length": (0.0, None), "side3_length": (0.0, None),
    "side1_segments": (1, 200), "side2_segments": (1, 200), "side3_segments": (1, 200),
    "back_length": (None, None), "side_length": (None, None), "front_length": (None, None),
    "back_width": (0.0, None), "side_width": (0.0, None), "front_width": (0.0, None),
    "back_segments": (1, 200), "front_segments": (1, 200),
    "p": (1.0, 100.0), "q": (1.0, 100.0), "warp_count": (0.0, 100.0), "warp_height": (-0.95, 10.0),
    "cross_section_radius": (0.0, None), "eccentricity": (0.01, 100.0), "lumps": (0.0, 100.0),
    "lump_height": (-0.95, 10.0),
    "family_p": (0.0, 1.0), "family_q": (0.0, 1.0),
    "axis_scale_p": (0.0, 1000.0), "axis_scale_q": (0.0, 1000.0), "axis_scale_r": (0.0, 1000.0),
}
_KIND_LIMITS = {
    ("SPHERE", "segments"): (4, 200),
    ("GEOSPHERE", "segments"): (1, 200),
    ("TEST_SHAPE", "segments"): (1, 64),
    ("BOX", "height_segments"): (1, 1000),
    ("CHAMFERBOX", "height_segments"): (1, 1000),
    ("TORUS_KNOT", "segments"): (3, 1000),
}
LIMITS = {
    kind: {
        name: _KIND_LIMITS.get((kind, name), _GENERIC_LIMITS.get(name, (None, None)))
        for name in params
    }
    for kind, params in PARAMETERS.items()
}


class MeshData:
    """
    Polygon mesh produced by :func:`generate`.

    :ivar vertices: list of ``(x, y, z)``.
    :ivar faces: list of tuples of vertex indices (triangles, quads or n-gons).
    :ivar uvs: ``None``, or per face a tuple of ``(u, v)``, one per face corner.
    :ivar smoothing_groups: per face, a Max smoothing-group mask (0 = faceted).
    :ivar material_ids: per face, a 0-based material ID.
    """

    __slots__ = ("vertices", "faces", "uvs", "smoothing_groups", "material_ids")

    def __init__(self, vertices, faces, uvs, smoothing_groups, material_ids):
        self.vertices = vertices
        self.faces = faces
        self.uvs = uvs
        self.smoothing_groups = smoothing_groups
        self.material_ids = material_ids

    def __repr__(self):
        return "<MeshData {:d} vertices, {:d} faces>".format(len(self.vertices), len(self.faces))

    def edge_faces(self):
        """Map each edge ``(a, b)`` with ``a < b`` to the list of faces using it."""
        result = {}
        for index, face in enumerate(self.faces):
            n = len(face)
            for k in range(n):
                a, b = face[k], face[(k + 1) % n]
                result.setdefault((a, b) if a < b else (b, a), []).append(index)
        return result

    def sharp_edges(self):
        """Edges between faces that share no smoothing group, sorted. Open borders are not included."""
        groups = self.smoothing_groups
        sharp = []
        for edge, faces in self.edge_faces().items():
            if len(faces) < 2:
                continue
            if any(groups[a] & groups[b] == 0 for i, a in enumerate(faces) for b in faces[i + 1:]):
                sharp.append(edge)
        sharp.sort()
        return sharp

    def flat_faces(self):
        """Per face, whether it is faceted (smoothing group 0)."""
        return [group == 0 for group in self.smoothing_groups]


# -----------------------------------------------------------------------------
# Parameters

def normalize_params(kind, params):
    """
    Return the full parameter dictionary for ``kind``: missing parameters get their defaults, values are converted
    to the parameter's type and clamped to :data:`LIMITS`. Raises ``ValueError`` for an unknown kind or enumeration
    value and ``TypeError`` for an unknown parameter name.
    """
    try:
        defaults = PARAMETERS[kind]
    except KeyError:
        raise ValueError("unknown primitive kind {!r}".format(kind)) from None
    unknown = set(params) - set(defaults)
    if unknown:
        raise TypeError("{:s} has no parameter(s) {:s}".format(kind, ", ".join(sorted(unknown))))
    result = {}
    limits = LIMITS[kind]
    for name, default in defaults.items():
        value = params.get(name, default)
        if isinstance(default, bool):
            value = bool(value)
        elif isinstance(default, int):
            value = int(round(value))
        elif isinstance(default, float):
            value = float(value)
        else:
            value = str(value)
            if value not in ENUMS[name]:
                raise ValueError("{:s}: {!r} is not one of {!r}".format(name, value, ENUMS[name]))
        if not isinstance(default, (bool, str)):
            lo, hi = limits[name]
            if lo is not None and value < lo:
                value = type(default)(lo)
            if hi is not None and value > hi:
                value = type(default)(hi)
        result[name] = value
    return result


def generate(kind, **params):
    """Build the mesh of a primitive. See :data:`PARAMETERS` for the kinds, parameters and defaults."""
    params = normalize_params(kind, params)
    generate_uvs = params.pop("generate_uvs")
    builder = _GENERATORS[kind](**params)
    return builder.result(generate_uvs)


# -----------------------------------------------------------------------------
# Building blocks

class _Builder:
    __slots__ = ("vertices", "faces", "uvs", "groups", "materials", "flip")

    def __init__(self):
        self.vertices = []
        self.faces = []
        self.uvs = []
        self.groups = []
        self.materials = []
        # Reverse every face at the end (negative sizes mirror the shape).
        self.flip = False

    def vert(self, x, y, z):
        self.vertices.append((x, y, z))
        return len(self.vertices) - 1

    def face(self, indices, uvs, group=0, material=0):
        """
        Add a face. Consecutive repeated vertices (poles, collapsed rings) are merged, averaging their UVs,
        and a face left with fewer than 3 vertices is dropped.
        """
        merged = []
        merged_uvs = []
        for index, uv in zip(indices, uvs):
            if merged and merged[-1] == index:
                merged_uvs[-1].append(uv)
            else:
                merged.append(index)
                merged_uvs.append([uv])
        if len(merged) > 1 and merged[0] == merged[-1]:
            merged.pop()
            merged_uvs[0].extend(merged_uvs.pop())
        if len(merged) < 3:
            return
        self.faces.append(tuple(merged))
        self.uvs.append(tuple(
            (sum(uv[0] for uv in group_uvs) / len(group_uvs), sum(uv[1] for uv in group_uvs) / len(group_uvs))
            for group_uvs in merged_uvs
        ))
        self.groups.append(group)
        self.materials.append(material)

    def strip(self, row_a, row_b, uv_a, uv_b, count, group=0, material=0):
        """
        Add ``count`` quads between two rows of vertices. Rows shorter than ``count + 1`` wrap around (closed rings).
        The quads are wound ``a[k], a[k + 1], b[k + 1], b[k]``: with ``a`` running counter-clockwise around +Z and
        ``b`` above ``a``, they face outwards. ``uv_a`` and ``uv_b`` have ``count + 1`` entries.
        """
        na = len(row_a)
        nb = len(row_b)
        for k in range(count):
            self.face(
                (row_a[k % na], row_a[(k + 1) % na], row_b[(k + 1) % nb], row_b[k % nb]),
                (uv_a[k], uv_a[k + 1], uv_b[k + 1], uv_b[k]),
                group, material,
            )

    def result(self, generate_uvs):
        faces = self.faces
        uvs = self.uvs
        if self.flip:
            faces = [face[::-1] for face in faces]
            uvs = [uv[::-1] for uv in uvs]
        return MeshData(
            vertices=self.vertices,
            faces=faces,
            uvs=uvs if generate_uvs else None,
            smoothing_groups=self.groups,
            material_ids=self.materials,
        )


def _band(b, upper, lower, uv_upper, uv_lower, count, group=0, material=0, pole_first=False):
    """
    ``count`` quads between two rings running counter-clockwise around +Z, ``lower`` below ``upper`` (Max's sphere
    and capsule layout): ``upper[k], lower[k], lower[k + 1], upper[k + 1]``, facing outwards. A pole (a repeated
    vertex) gives triangles; ``pole_first`` starts each face at ``lower[k]`` instead (Max's bottom fans).
    """
    nu, nl = len(upper), len(lower)
    for k in range(count):
        indices = [upper[k % nu], lower[k % nl], lower[(k + 1) % nl], upper[(k + 1) % nu]]
        uvs = [uv_upper[k], uv_lower[k], uv_lower[k + 1], uv_upper[k + 1]]
        if pole_first:
            indices = indices[1:] + indices[:1]
            uvs = uvs[1:] + uvs[:1]
        b.face(indices, uvs, group, material)


def _arc(count, slice_on, slice_from, slice_to):
    """
    Angles of ``count`` segments around Z: returns ``(angles, closed)`` with ``count + 1`` angles.
    For a closed ring the last angle repeats the first one (+2π) and is only used for UVs.
    """
    if slice_on:
        arc = (slice_to - slice_from) % TAU
        if 1e-6 < arc < TAU - 1e-6:
            return [slice_from + arc * k / count for k in range(count + 1)], False
    return [TAU * k / count for k in range(count + 1)], True


def _ring(builder, radius, z, angles, closed, start=0.0):
    """
    Vertices of a ring around Z at ``angles`` counted from ``start`` (an angle from +X). A ring of radius 0 is a
    single vertex, repeated.
    """
    count = len(angles) - 1 if closed else len(angles)
    if radius == 0.0:
        return [builder.vert(0.0, 0.0, z)] * count
    return [builder.vert(radius * math.cos(a + start), radius * math.sin(a + start), z) for a in angles[:count]]


def _cyclic_group(index, count, closed):
    """Smoothing group for item ``index`` of ``count`` neighbours so that adjacent items never share a group."""
    if closed and count % 2 == 1 and index == count - 1:
        return 4
    return 1 if index % 2 == 0 else 2


def _cap_uvs(angles, fraction, mirror, start=0.0):
    """Planar UVs of a ring of relative radius ``fraction`` on a disc cap, mirrored for bottom caps."""
    sign = -1.0 if mirror else 1.0
    return [(0.5 + sign * 0.5 * fraction * math.cos(a + start), 0.5 + 0.5 * fraction * math.sin(a + start))
            for a in angles]


# Angle from +X of the first vertex of each ring (the other kinds start at +X). Verified on the corpus: spheres,
# tubes and tori under modifiers have the input bounding boxes of rings starting at +Y (11 spheres with 14, 18 and
# 19 segments, tubes with 18 and 87 sides, a torus with 41 segments), cylinders and cones those of rings starting
# at +X (32 and 79 objects); spheres converted to Editable Poly / Mesh have their first ring vertex on +Y, and a
# converted Capsule and Cylinders on +X.
RING_START = {"SPHERE": math.pi / 2, "TUBE": math.pi / 2, "TORUS": math.pi / 2}


# -----------------------------------------------------------------------------
# Box

# Material IDs (0-based) and smoothing groups per side, as on Boxes converted to Editable Poly / Mesh in the corpus
# (Max's 1-based IDs: top 1, bottom 2, left 3, right 4, front 5, back 6).
BOX_SIDES = {
    #          material, smoothing group
    "BOTTOM": (1, 1 << 1),
    "TOP": (0, 1 << 2),
    "FRONT": (4, 1 << 3),   # -Y
    "RIGHT": (3, 1 << 4),   # +X
    "BACK": (5, 1 << 5),    # +Y
    "LEFT": (2, 1 << 6),    # -X
}


def _box(length, width, height, length_segments, width_segments, height_segments):
    b = _Builder()
    ws, ls, hs = width_segments, length_segments, height_segments
    b.flip = (length < 0.0) ^ (width < 0.0) ^ (height < 0.0)

    def x(i):
        return width * (i / ws - 0.5)

    def y(j):
        return length * (j / ls - 0.5)

    def z(k):
        return height * k / hs

    # Vertices: bottom grid, then the side rings between bottom and top, then the top grid;
    # grids row by row along +Y, each row along +X.
    lattice = {}
    for k in [0] + list(range(1, hs)) + [hs]:
        on_cap = k in (0, hs)
        for j in range(ls + 1):
            for i in range(ws + 1):
                if on_cap or i in (0, ws) or j in (0, ls):
                    lattice[i, j, k] = b.vert(x(i), y(j), z(k))

    def grid(side, corners, uv):
        # `corners(a, b)` gives the lattice key of grid point (a, b); faces wind (a, b) -> (a + 1, b).
        material, group = BOX_SIDES[side]
        na, nb = len(uv) - 1, len(uv[0]) - 1
        for bi in range(nb):
            for ai in range(na):
                keys = ((ai, bi), (ai + 1, bi), (ai + 1, bi + 1), (ai, bi + 1))
                b.face([lattice[corners(*key)] for key in keys], [uv[ka][kb] for ka, kb in keys], group, material)

    def uv_grid(na, nb, mirror=False):
        return [[((na - a) / na if mirror else a / na, bb / nb) for bb in range(nb + 1)] for a in range(na + 1)]

    # Faces: bottom, top, front, right, back, left (Max's order). Corners as on converted Max boxes: bottom quads
    # start at their (-X, -Y) corner and run along +Y first; the others start at their lower left corner seen from
    # outside.
    grid("BOTTOM", lambda a, c: (c, a, 0), [[(1.0 - c / ws, a / ls) for c in range(ws + 1)] for a in range(ls + 1)])
    grid("TOP", lambda a, c: (a, c, hs), uv_grid(ws, ls))
    grid("FRONT", lambda a, c: (a, 0, c), uv_grid(ws, hs))
    grid("RIGHT", lambda a, c: (ws, a, c), uv_grid(ls, hs))
    grid("BACK", lambda a, c: (ws - a, ls, c), uv_grid(ws, hs))
    grid("LEFT", lambda a, c: (0, ls - a, c), uv_grid(ls, hs))
    return b


# -----------------------------------------------------------------------------
# Plane

def _plane(length, width, length_segments, width_segments):
    b = _Builder()
    ws, ls = width_segments, length_segments
    b.flip = (length < 0.0) ^ (width < 0.0)
    # Vertices row by row along +Y, each row along +X.
    rows = [[b.vert(width * (i / ws - 0.5), length * (j / ls - 0.5), 0.0) for i in range(ws + 1)]
            for j in range(ls + 1)]
    for j in range(ls):
        b.strip(rows[j], rows[j + 1],
                [(i / ws, j / ls) for i in range(ws + 1)], [(i / ws, (j + 1) / ls) for i in range(ws + 1)],
                ws, 1, 0)
    return b


# -----------------------------------------------------------------------------
# Sphere

def _sphere(radius, segments, smooth, hemisphere, hemisphere_mode, slice_on, slice_from, slice_to, base_to_pivot):
    b = _Builder()
    r = radius
    n = segments
    # Max: `segments` around, half as many bands from pole to pole (a 32-segment sphere has 482 vertices).
    # Unverified for odd segment counts.
    rows = max(2, n // 2)
    angles, closed = _arc(n, slice_on, slice_from, slice_to)

    hemisphere = min(hemisphere, 0.999)
    cut = hemisphere > 0.0
    if cut:
        # Hemisphere removes that fraction of the height from the bottom: 0.5 cuts at the equator.
        theta_cut = math.acos(1.0 - 2.0 * hemisphere)
        if hemisphere_mode == "SQUASH":
            thetas = [theta_cut * k / rows for k in range(1, rows + 1)]
        else:
            thetas = [math.pi * k / rows for k in range(1, rows) if math.pi * k / rows < theta_cut - 1e-9]
            thetas.append(theta_cut)
        bottom_z = r * math.cos(theta_cut)
    else:
        thetas = [math.pi * k / rows for k in range(1, rows)]
        bottom_z = -r
    z_offset = -bottom_z if base_to_pivot else 0.0

    # Vertices (as on spheres converted in Max): top pole, rings from the top down starting at +Y, then the bottom
    # pole (or the centre of the hemisphere's base).
    start = RING_START["SPHERE"]
    top = b.vert(0.0, 0.0, r + z_offset)
    rings = []
    for theta in thetas:
        rho = r * math.sin(theta)
        rings.append(_ring(b, rho, r * math.cos(theta) + z_offset, angles, closed, start))
    count = len(rings[0])
    bottom = b.vert(0.0, 0.0, bottom_z + z_offset)

    us = [k / n for k in range(n + 1)]

    def uv_row(theta):
        return [(u, 1.0 - theta / math.pi) for u in us]

    group = 1 if smooth else 0
    # Faces, as in Max: the top fan (pole, ring[k], ring[k + 1]), then bands from the top down, each quad
    # (upper[k], lower[k], lower[k + 1], upper[k + 1]), then the bottom fan (pole, ring[k + 1], ring[k]).
    prev, prev_theta = [top] * count, 0.0
    for ring, theta in zip(rings, thetas):
        _band(b, prev, ring, uv_row(prev_theta), uv_row(theta), n, group, 0)
        prev, prev_theta = ring, theta
    if cut:
        # Base of the hemisphere: a fan around a centre vertex.
        _band(b, prev, [bottom] * count, _cap_uvs(angles, 1.0, True, start), _cap_uvs(angles, 0.0, True, start),
              n, 2, 0, pole_first=True)
    else:
        _band(b, prev, [bottom] * count, uv_row(prev_theta), uv_row(math.pi), n, group, 0, pole_first=True)

    if not closed:
        # Slice faces: one n-gon per side, the half disc between the meridian and the axis.
        def meridian(e):
            return [top] + [ring[e] for ring in rings] + [bottom]

        def meridian_uvs(mirror):
            points = [(0.0, 1.0)] + [(math.sin(t), math.cos(t)) for t in thetas] + [(0.0, bottom_z / r if r else -1)]
            return [((1.0 - rho) if mirror else rho, 0.5 + 0.5 * zz) for rho, zz in points]

        b.face(meridian(0)[::-1], meridian_uvs(False)[::-1], 4, 0)
        b.face(meridian(count - 1), meridian_uvs(True), 8, 0)
    return b


# -----------------------------------------------------------------------------
# GeoSphere

def _normalize(v):
    length = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    return (v[0] / length, v[1] / length, v[2] / length)


def _base_polyhedron(base_type):
    """Unit base solid with a vertex at the top pole, faces wound outwards."""
    if base_type == "TETRA":
        rho = math.sqrt(8.0) / 3.0
        verts = [(0.0, 0.0, 1.0)] + [
            (rho * math.cos(TAU * k / 3), rho * math.sin(TAU * k / 3), -1.0 / 3.0) for k in range(3)]
        faces = [(0, 1, 2), (0, 2, 3), (0, 3, 1), (1, 3, 2)]
    elif base_type == "OCTA":
        verts = [(0.0, 0.0, 1.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (-1.0, 0.0, 0.0), (0.0, -1.0, 0.0),
                 (0.0, 0.0, -1.0)]
        faces = [(0, 1 + k, 1 + (k + 1) % 4) for k in range(4)] + [(5, 1 + (k + 1) % 4, 1 + k) for k in range(4)]
    else:
        z = 1.0 / math.sqrt(5.0)
        rho = 2.0 / math.sqrt(5.0)
        verts = [(0.0, 0.0, 1.0)]
        verts += [(rho * math.cos(TAU * k / 5), rho * math.sin(TAU * k / 5), z) for k in range(5)]
        verts += [(rho * math.cos(TAU * (k + 0.5) / 5), rho * math.sin(TAU * (k + 0.5) / 5), -z) for k in range(5)]
        verts.append((0.0, 0.0, -1.0))
        faces = []
        for k in range(5):
            u0, u1 = 1 + k, 1 + (k + 1) % 5
            l0, l1 = 6 + k, 6 + (k + 1) % 5
            faces += [(0, u0, u1), (u0, l0, u1), (u1, l0, l1), (11, l1, l0)]
    # Wind every face outwards.
    oriented = []
    for face in faces:
        a, b, c = (verts[i] for i in face)
        ab = [b[i] - a[i] for i in range(3)]
        ac = [c[i] - a[i] for i in range(3)]
        normal = (ab[1] * ac[2] - ab[2] * ac[1], ab[2] * ac[0] - ab[0] * ac[2], ab[0] * ac[1] - ab[1] * ac[0])
        centre = [sum(p[i] for p in (a, b, c)) for i in range(3)]
        oriented.append(face if sum(normal[i] * centre[i] for i in range(3)) > 0.0 else face[::-1])
    return verts, oriented


def _spherical_uvs(points):
    """Spherical-projection UVs of a face's unit-sphere points, keeping faces across the seam continuous."""
    us = []
    for x, y, z in points:
        us.append(None if x * x + y * y < 1e-12 else (math.atan2(y, x) / TAU) % 1.0)
    known = [u for u in us if u is not None]
    if known and max(known) - min(known) > 0.5:
        us = [None if u is None else (u + 1.0 if u < 0.5 else u) for u in us]
        known = [u for u in us if u is not None]
    pole_u = sum(known) / len(known) if known else 0.5
    return [(pole_u if u is None else u, 0.5 + math.asin(max(-1.0, min(1.0, z))) / math.pi)
            for u, (x, y, z) in zip(us, points)]


def _geosphere(radius, segments, base_type, smooth, hemisphere_on, base_to_pivot):
    b = _Builder()
    f = segments
    base_verts, base_faces = _base_polyhedron(base_type)

    # Subdivide each base triangle into f * f triangles and project onto the sphere. Vertices are created in
    # order of first use, face by face, and shared through their (rounded) position.
    points = []
    index_of = {}

    def point(a, bb, c, i, j):
        p = _normalize([a[k] + (bb[k] - a[k]) * i / f + (c[k] - a[k]) * j / f for k in range(3)])
        key = tuple(round(v, 9) for v in p)
        index = index_of.get(key)
        if index is None:
            index = index_of[key] = len(points)
            points.append(p)
        return index

    tris = []
    for face in base_faces:
        a, bb, c = (base_verts[i] for i in face)
        grid = {(i, j): point(a, bb, c, i, j) for j in range(f + 1) for i in range(f + 1 - j)}
        for j in range(f):
            for i in range(f - j):
                tris.append((grid[i, j], grid[i + 1, j], grid[i, j + 1]))
                if i + j + 1 < f:
                    tris.append((grid[i + 1, j], grid[i + 1, j + 1], grid[i, j + 1]))

    if hemisphere_on:
        # Keep the part above the equator. With an even segment count on the octa and icosa bases the equator runs
        # along edges; otherwise the faces crossing it are clipped, with new vertices on the equator.
        # The base is closed by one n-gon.
        tris = _clip_above_equator(points, tris)

    # Renumber the vertices that are used, in order of first use.
    remap = {}
    for tri in tris:
        for i in tri:
            if i not in remap:
                remap[i] = b.vert(*(radius * v for v in points[i]))
    z_offset = radius if (base_to_pivot and not hemisphere_on) else 0.0
    if z_offset:
        b.vertices = [(x, y, z + z_offset) for x, y, z in b.vertices]
    group = 1 if smooth else 0
    for tri in tris:
        b.face([remap[i] for i in tri], _spherical_uvs([points[i] for i in tri]), group, 0)

    if hemisphere_on:
        # The border of the dome, chained into a loop; the base runs the other way round.
        loop = _border_loop(b.faces)
        if loop:
            cap = loop[::-1]
            uvs = [(0.5 - 0.5 * b.vertices[i][0] / radius if radius else 0.5,
                    0.5 + 0.5 * b.vertices[i][1] / radius if radius else 0.5) for i in cap]
            b.face(cap, uvs, 2, 0)
    return b


def _clip_above_equator(points, faces, eps=1e-6):
    """Clip unit-sphere polygons to z >= 0, adding the crossing points (on the equator) to ``points``."""
    for i, p in enumerate(points):
        if abs(p[2]) < eps:
            points[i] = _normalize((p[0], p[1], 0.0))
    crossing = {}

    def cross(a, b):
        key = (a, b) if a < b else (b, a)
        index = crossing.get(key)
        if index is None:
            pa, pb = points[a], points[b]
            t = pa[2] / (pa[2] - pb[2])
            index = crossing[key] = len(points)
            points.append(_normalize((pa[0] + (pb[0] - pa[0]) * t, pa[1] + (pb[1] - pa[1]) * t, 0.0)))
        return index

    result = []
    for face in faces:
        if not any(points[i][2] > 0.0 for i in face):
            continue
        clipped = []
        n = len(face)
        for k in range(n):
            a, b = face[k], face[(k + 1) % n]
            za, zb = points[a][2], points[b][2]
            if za >= 0.0:
                clipped.append(a)
            if (za > 0.0 and zb < 0.0) or (za < 0.0 and zb > 0.0):
                clipped.append(cross(a, b))
        result.append(tuple(clipped))
    return result


def _edge_set(faces):
    return {(face[k], face[(k + 1) % len(face)]) for face in faces for k in range(len(face))}


def _border_loop(faces):
    """The single border loop of an open mesh, in face winding order (empty if there is none)."""
    directed = _edge_set(faces)
    nxt = {a: b for a, b in directed if (b, a) not in directed}
    if not nxt:
        return []
    start = min(nxt)
    loop = [start]
    while True:
        following = nxt[loop[-1]]
        if following == start:
            return loop
        loop.append(following)
        if len(loop) > len(nxt):
            raise RuntimeError("border is not a single loop")


# -----------------------------------------------------------------------------
# Cylinder and Cone

# Material IDs (0-based). Unverified against Max, see the decision record.
CAP_MATERIALS = {"TOP": 0, "BOTTOM": 1, "SIDES": 2, "SLICE": 3}
TUBE_MATERIALS = {"TOP": 0, "BOTTOM": 1, "OUTER": 2, "INNER": 3, "SLICE": 4}


def _cylinder(radius, height, height_segments, cap_segments, sides, smooth, slice_on, slice_from, slice_to):
    return _cone(radius, radius, height, height_segments, cap_segments, sides, smooth, slice_on, slice_from, slice_to)


def _cone(radius1, radius2, height, height_segments, cap_segments, sides, smooth, slice_on, slice_from, slice_to):
    b = _Builder()
    b.flip = height < 0.0
    r1, r2, h = radius1, radius2, height
    hs, cs, n = height_segments, cap_segments, sides
    angles, closed = _arc(n, slice_on, slice_from, slice_to)
    # A single cap segment is one n-gon (no centre vertex) unless the slice needs the centre; more cap segments
    # give rings of quads around a fan of triangles.
    centred = cs > 1 or not closed

    def radius_at(j):
        return r1 + (r2 - r1) * j / hs

    # Vertices: bottom centre, bottom cap rings outwards, side rings upwards, top cap rings inwards, top centre.
    if r1 == 0.0:
        bottom = [_ring(b, 0.0, 0.0, angles, closed)] * (cs + 1)
    else:
        bottom = [_ring(b, 0.0, 0.0, angles, closed) if centred else None]
        bottom += [_ring(b, r1 * i / cs, 0.0, angles, closed) for i in range(1, cs + 1)]
    sides_rings = [bottom[cs]] + [_ring(b, radius_at(j), h * j / hs, angles, closed) for j in range(1, hs)]
    if r2 == 0.0:
        top = [_ring(b, 0.0, h, angles, closed)] * (cs + 1)
    else:
        top = [None] * (cs + 1)
        for i in range(cs, 0, -1):
            top[i] = _ring(b, r2 * i / cs, h, angles, closed)
        top[0] = _ring(b, 0.0, h, angles, closed) if centred else None
    sides_rings.append(top[cs])
    count = len(sides_rings[0])

    side_group = 1 if smooth else 0
    us = [k / n for k in range(n + 1)]

    # Faces: bottom cap, sides, top cap, slice faces.
    if r1 != 0.0:
        if centred:
            for i in range(cs):
                b.strip(bottom[i], bottom[i + 1], _cap_uvs(angles, i / cs, True), _cap_uvs(angles, (i + 1) / cs, True),
                        n, 2, CAP_MATERIALS["BOTTOM"])
        else:
            b.face(bottom[1][::-1], _cap_uvs(angles[:count], 1.0, True)[::-1], 2, CAP_MATERIALS["BOTTOM"])
    for j in range(hs):
        b.strip(sides_rings[j], sides_rings[j + 1], [(u, j / hs) for u in us], [(u, (j + 1) / hs) for u in us],
                n, side_group, CAP_MATERIALS["SIDES"])
    if r2 != 0.0:
        if centred:
            for i in range(cs, 0, -1):
                b.strip(top[i], top[i - 1], _cap_uvs(angles, i / cs, False), _cap_uvs(angles, (i - 1) / cs, False),
                        n, 4, CAP_MATERIALS["TOP"])
        else:
            b.face(top[1], _cap_uvs(angles[:count], 1.0, False), 4, CAP_MATERIALS["TOP"])

    if not closed:
        # Slice faces: a grid of cap segments (from the axis out) by height segments, with its own vertices
        # on the axis (shared by both faces) and inside the face.
        axis = [bottom[0][0]] + [b.vert(0.0, 0.0, h * j / hs) for j in range(1, hs)] + [top[0][0]]
        for end, e in ((0, 0), (1, count - 1)):
            a = angles[e]
            ca, sa = math.cos(a), math.sin(a)
            grid = {}
            for j in range(hs + 1):
                for i in range(cs + 1):
                    if j == 0:
                        grid[i, j] = bottom[i][e]
                    elif j == hs:
                        grid[i, j] = top[i][e]
                    elif i == cs:
                        grid[i, j] = sides_rings[j][e]
                    elif i == 0:
                        grid[i, j] = axis[j]
                    else:
                        rho = radius_at(j) * i / cs
                        grid[i, j] = b.vert(rho * ca, rho * sa, h * j / hs)
            _slice_grid(b, grid, cs, hs, end, 8 << end, CAP_MATERIALS["SLICE"])
    return b


def _slice_grid(b, grid, ni, nj, end, group, material):
    """Faces of a slice grid ``grid[i, j]`` (i outwards from the axis, j upwards); ``end`` 0 faces clockwise."""
    for j in range(nj):
        for i in range(ni):
            keys = ((i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1))
            uvs = [((ni - ki) / ni if end else ki / ni, kj / nj) for ki, kj in keys]
            indices = [grid[key] for key in keys]
            if end:
                indices.reverse()
                uvs.reverse()
            b.face(indices, uvs, group, material)


# -----------------------------------------------------------------------------
# Tube

def _tube(radius1, radius2, height, height_segments, cap_segments, sides, smooth, slice_on, slice_from, slice_to):
    b = _Builder()
    b.flip = height < 0.0
    outer_r, inner_r = max(radius1, radius2), min(radius1, radius2)
    h, hs, cs, n = height, height_segments, cap_segments, sides
    angles, closed = _arc(n, slice_on, slice_from, slice_to)
    start = RING_START["TUBE"]

    def cap_radius(i):
        return inner_r + (outer_r - inner_r) * i / cs

    # Vertices (rings start at +Y, as in Max): outer wall rings upwards, inner wall rings upwards, then the rings
    # inside the bottom and top caps.
    outer = [_ring(b, outer_r, h * j / hs, angles, closed, start) for j in range(hs + 1)]
    inner = [_ring(b, inner_r, h * j / hs, angles, closed, start) for j in range(hs + 1)]
    bottom = [inner[0]] + [_ring(b, cap_radius(i), 0.0, angles, closed, start) for i in range(1, cs)] + [outer[0]]
    top = [inner[hs]] + [_ring(b, cap_radius(i), h, angles, closed, start) for i in range(1, cs)] + [outer[hs]]
    count = len(outer[0])

    wall_groups = (1, 2) if smooth else (0, 0)
    us = [k / n for k in range(n + 1)]
    fraction = inner_r / outer_r if outer_r else 0.0

    def cap_fraction(i):
        return fraction + (1.0 - fraction) * i / cs

    # Faces: outer wall, inner wall, bottom cap, top cap, slice faces.
    for j in range(hs):
        b.strip(outer[j], outer[j + 1], [(u, j / hs) for u in us], [(u, (j + 1) / hs) for u in us],
                n, wall_groups[0], TUBE_MATERIALS["OUTER"])
    for j in range(hs):
        b.strip(inner[j + 1], inner[j], [(u, (j + 1) / hs) for u in us], [(u, j / hs) for u in us],
                n, wall_groups[1], TUBE_MATERIALS["INNER"])
    for i in range(cs):
        b.strip(bottom[i], bottom[i + 1], _cap_uvs(angles, cap_fraction(i), True, start),
                _cap_uvs(angles, cap_fraction(i + 1), True, start), n, 4, TUBE_MATERIALS["BOTTOM"])
    for i in range(cs, 0, -1):
        b.strip(top[i], top[i - 1], _cap_uvs(angles, cap_fraction(i), False, start),
                _cap_uvs(angles, cap_fraction(i - 1), False, start), n, 8, TUBE_MATERIALS["TOP"])

    if not closed:
        for end, e in ((0, 0), (1, count - 1)):
            a = angles[e] + start
            ca, sa = math.cos(a), math.sin(a)
            grid = {}
            for j in range(hs + 1):
                for i in range(cs + 1):
                    if j == 0:
                        grid[i, j] = bottom[i][e]
                    elif j == hs:
                        grid[i, j] = top[i][e]
                    elif i == 0:
                        grid[i, j] = inner[j][e]
                    elif i == cs:
                        grid[i, j] = outer[j][e]
                    else:
                        rho = cap_radius(i)
                        grid[i, j] = b.vert(rho * ca, rho * sa, h * j / hs)
            _slice_grid(b, grid, cs, hs, end, 16 << end, TUBE_MATERIALS["SLICE"])
    return b


# -----------------------------------------------------------------------------
# Torus

def _torus(radius1, radius2, rotation, twist, segments, sides, smooth_mode, slice_on, slice_from, slice_to):
    b = _Builder()
    big, small = radius1, radius2
    m, n = segments, sides
    angles, closed = _arc(m, slice_on, slice_from, slice_to)
    ring_count = m if closed else m + 1

    # Vertices: one ring (cross-section) per segment, counter-clockwise around Z from +Y as in Max; in each ring
    # the vertices start on the outside of the torus (+ rotation, + the twist so far) and run upwards around the
    # tube.
    rings = []
    for i in range(ring_count):
        phi = angles[i] + RING_START["TORUS"]
        cp, sp = math.cos(phi), math.sin(phi)
        offset = rotation + twist * i / m
        ring = []
        for j in range(n):
            psi = TAU * j / n + offset
            rho = big + small * math.cos(psi)
            ring.append(b.vert(rho * cp, rho * sp, small * math.sin(psi)))
        rings.append(ring)

    def group(i, j):
        if smooth_mode == "ALL":
            return 1
        if smooth_mode == "SIDES":
            # Smooth across segments, sharp between sides: bands running around the torus.
            return _cyclic_group(j, n, True)
        if smooth_mode == "SEGMENTS":
            # Smooth around each segment, sharp between segments: rings.
            return _cyclic_group(i, m, closed)
        return 0

    # Faces: segment by segment, side by side.
    for i in range(m):
        ra, rb = rings[i], rings[(i + 1) % ring_count]
        for j in range(n):
            j1 = (j + 1) % n
            b.face((ra[j], rb[j], rb[j1], ra[j1]),
                   ((i / m, j / n), ((i + 1) / m, j / n), ((i + 1) / m, (j + 1) / n), (i / m, (j + 1) / n)),
                   group(i, j), 0)
    if not closed:
        # Slice ends closed by one n-gon each.
        uvs = [(0.5 + 0.5 * math.cos(TAU * j / n + rotation), 0.5 + 0.5 * math.sin(TAU * j / n + rotation))
               for j in range(n)]
        b.face(rings[0], uvs, 8, 0)
        b.face(rings[-1][::-1], [(1.0 - u, v) for u, v in uvs][::-1], 16, 0)
    return b


# -----------------------------------------------------------------------------
# Pyramid

def _pyramid(width, depth, height, width_segments, depth_segments, height_segments):
    b = _Builder()
    w, d, h = width, depth, height
    ws, ds, hs = width_segments, depth_segments, height_segments
    b.flip = (w < 0.0) ^ (d < 0.0) ^ (h < 0.0)

    # Vertices: base grid (rows along +Y, each along +X), side rings upwards, apex.
    base = [[b.vert(w * (i / ws - 0.5), d * (j / ds - 0.5), 0.0) for i in range(ws + 1)] for j in range(ds + 1)]
    # The base outline counter-clockwise from the front left corner: (grid i, grid j, side, position on side).
    outline = (
        [(i, 0, 0, i) for i in range(ws)]
        + [(ws, j, 1, j) for j in range(ds)]
        + [(ws - i, ds, 2, i) for i in range(ws)]
        + [(0, ds - j, 3, j) for j in range(ds)]
    )
    side_segments = (ws, ds, ws, ds)
    rings = [[base[j][i] for i, j, _side, _pos in outline]]
    for k in range(1, hs):
        s = 1.0 - k / hs
        rings.append([b.vert(w * (i / ws - 0.5) * s, d * (j / ds - 0.5) * s, h * k / hs) for i, j, _s, _p in outline])
    rings.append([b.vert(0.0, 0.0, h)] * len(outline))

    # Faces: base, then the front, right, back and left sides from the bottom up.
    for j in range(ds):
        for i in range(ws):
            b.face((base[j][i], base[j + 1][i], base[j + 1][i + 1], base[j][i + 1]),
                   ((1 - i / ws, j / ds), (1 - i / ws, (j + 1) / ds),
                    (1 - (i + 1) / ws, (j + 1) / ds), (1 - (i + 1) / ws, j / ds)),
                   1, 0)
    count = len(outline)
    for side in range(4):
        segs = side_segments[side]
        for k in range(hs):
            for p, (_i, _j, s, pos) in enumerate(outline):
                if s != side:
                    continue
                q = (p + 1) % count
                # U along the side, narrowing towards the apex like the side itself.
                s0, s1 = 1.0 - k / hs, 1.0 - (k + 1) / hs
                t0, t1 = pos / segs - 0.5, (pos + 1) / segs - 0.5
                b.face((rings[k][p], rings[k][q], rings[k + 1][q], rings[k + 1][p]),
                       ((0.5 + t0 * s0, k / hs), (0.5 + t1 * s0, k / hs),
                        (0.5 + t1 * s1, (k + 1) / hs), (0.5 + t0 * s1, (k + 1) / hs)),
                       2 << side, 0)
    return b


# -----------------------------------------------------------------------------
# Test shape: an original procedural object, standing in for Max's teapot (whose data has an unclear licence).
# A lathed pot body with a separate lathed lid, plus a swept handle and a tapering swept spout; all four parts
# are closed shells, given material IDs 0-3. The proportions are made up for this project.

# Profiles in the (radius, height) half-plane, for a unit radius, from the axis at the bottom round to the axis at
# the top. Each span is a straight line (2 points) or a cubic Bezier (4 points); spans with the same smoothing run
# number are smoothed together.
_BODY_PROFILE = (
    (0, ((0.0, 0.0), (0.70, 0.0))),
    (1, ((0.70, 0.0), (0.92, 0.0), (1.02, 0.22), (1.00, 0.45))),
    (1, ((1.00, 0.45), (0.98, 0.72), (0.70, 0.86), (0.62, 1.00))),
    (2, ((0.62, 1.00), (0.68, 1.06))),
    (3, ((0.68, 1.06), (0.0, 1.06))),
)
_LID_PROFILE = (
    (0, ((0.0, 1.00), (0.60, 1.00))),
    (1, ((0.60, 1.00), (0.64, 1.09))),
    (2, ((0.64, 1.09), (0.58, 1.22), (0.24, 1.28), (0.12, 1.30))),
    (3, ((0.12, 1.30), (0.10, 1.35), (0.18, 1.38), (0.17, 1.42))),
    (3, ((0.17, 1.42), (0.16, 1.46), (0.08, 1.48), (0.0, 1.48))),
)
# Sweep paths in the XZ plane: Bezier control points (x, z), start and end tube radius.
_HANDLE_PATH = (((-0.62, 0.82), (-1.40, 0.97), (-1.62, 0.25), (-0.85, 0.25)), 0.075, 0.075)
_SPOUT_PATH = (((0.75, 0.30), (1.30, 0.32), (1.25, 0.85), (1.62, 1.02)), 0.16, 0.06)


def _bezier(points, t):
    if len(points) == 2:
        (x0, y0), (x1, y1) = points
        return (x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = points
    s = 1.0 - t
    a, bb, c, d = s * s * s, 3.0 * s * s * t, 3.0 * s * t * t, t * t * t
    return (a * x0 + bb * x1 + c * x2 + d * x3, a * y0 + bb * y1 + c * y2 + d * y3)


def _lathe(b, profile, scale, sides, steps, smooth, material):
    angles = [TAU * k / sides for k in range(sides + 1)]
    points = [profile[0][1][0]]
    runs = []
    for run, span in profile:
        span_steps = 1 if len(span) == 2 else steps
        for k in range(1, span_steps + 1):
            points.append(_bezier(span, k / span_steps))
            runs.append(run)
    lengths = [0.0]
    for (r0, z0), (r1, z1) in zip(points, points[1:]):
        lengths.append(lengths[-1] + math.hypot(r1 - r0, z1 - z0))
    rings = [_ring(b, r * scale, z * scale, angles, True) for r, z in points]
    us = [k / sides for k in range(sides + 1)]
    for p in range(len(points) - 1):
        group = (1 << (runs[p] % 3)) if smooth else 0
        b.strip(rings[p], rings[p + 1], [(u, lengths[p] / lengths[-1]) for u in us],
                [(u, lengths[p + 1] / lengths[-1]) for u in us], sides, group, material)


def _sweep(b, path, scale, steps, sides, smooth, material):
    control, radius_start, radius_end = path
    rings = []
    for k in range(steps + 1):
        t = k / steps
        x, z = _bezier(control, t)
        # Tangent from a small central difference, then the frame: binormal +Y, normal = binormal x tangent.
        xa, za = _bezier(control, max(0.0, t - 1e-4))
        xb, zb = _bezier(control, min(1.0, t + 1e-4))
        tx, tz = xb - xa, zb - za
        length = math.hypot(tx, tz)
        tx, tz = tx / length, tz / length
        nx, nz = tz, -tx
        rho = radius_start + (radius_end - radius_start) * t
        ring = []
        for j in range(sides):
            psi = TAU * j / sides
            c, s = math.cos(psi) * rho, math.sin(psi) * rho
            ring.append(b.vert((x + c * nx) * scale, s * scale, (z + c * nz) * scale))
        rings.append(ring)
    us = [j / sides for j in range(sides + 1)]
    for k in range(steps):
        b.strip(rings[k], rings[k + 1], [(u, k / steps) for u in us], [(u, (k + 1) / steps) for u in us],
                sides, 1 if smooth else 0, material)
    cap = [(0.5 + 0.5 * math.cos(TAU * j / sides), 0.5 + 0.5 * math.sin(TAU * j / sides)) for j in range(sides)]
    b.face(rings[0][::-1], cap[::-1], 2, material)
    b.face(rings[-1], cap, 4, material)


def _test_shape(radius, segments, smooth, part_body, part_handle, part_spout, part_lid):
    b = _Builder()
    s = segments
    # Parts in order body, handle, spout, lid; material IDs 0, 1, 2, 3.
    if part_body:
        _lathe(b, _BODY_PROFILE, radius, 8 * s, 2 * s, smooth, 0)
    if part_handle:
        _sweep(b, _HANDLE_PATH, radius, 4 * s, max(6, 3 * s), smooth, 1)
    if part_spout:
        _sweep(b, _SPOUT_PATH, radius, 4 * s, max(6, 3 * s), smooth, 2)
    if part_lid:
        _lathe(b, _LID_PROFILE, radius, 8 * s, 2 * s, smooth, 3)
    return b


# =============================================================================
# Extended primitives
#
# Max's parameter sets and creation conventions. Their topology could only be checked where the corpus has converted
# objects (Capsule, see below); the rest follows the standard primitives' conventions and is listed as unverified in
# docs/decisions/0006-live-primitives.md.

def _newell(points):
    nx = ny = nz = 0.0
    for i, (x0, y0, z0) in enumerate(points):
        x1, y1, z1 = points[(i + 1) % len(points)]
        nx += (y0 - y1) * (z0 + z1)
        ny += (z0 - z1) * (x0 + x1)
        nz += (x0 - x1) * (y0 + y1)
    return (nx, ny, nz)


def _face_outward(b, indices, uvs, group, material, outward):
    """Add a face wound so that its normal points along ``outward``."""
    normal = _newell([b.vertices[i] for i in indices])
    if normal[0] * outward[0] + normal[1] * outward[1] + normal[2] * outward[2] < 0.0:
        indices = indices[::-1]
        uvs = uvs[::-1]
    b.face(indices, uvs, group, material)


def _compact(b):
    """Drop vertices no face uses (shapes assembled from patches sharing vertices by position)."""
    used = sorted({i for face in b.faces for i in face})
    if len(used) == len(b.vertices):
        return
    remap = {old: new for new, old in enumerate(used)}
    b.vertices = [b.vertices[i] for i in used]
    b.faces = [tuple(remap[i] for i in face) for face in b.faces]


class _Welder:
    """Vertices shared by position, for shapes assembled from patches."""

    __slots__ = ("b", "unit", "index")

    def __init__(self, b, size):
        self.b = b
        self.unit = max(abs(size), 1e-12) * 1e-9
        self.index = {}

    def __call__(self, x, y, z):
        key = (round(x / self.unit), round(y / self.unit), round(z / self.unit))
        index = self.index.get(key)
        if index is None:
            index = self.index[key] = self.b.vert(x, y, z)
        return index


def _mirror_z(b):
    """Mirror a shape built upwards to grow downwards (negative heights)."""
    b.vertices = [(x, y, -z) for x, y, z in b.vertices]
    b.flip = not b.flip


# -----------------------------------------------------------------------------
# Surfaces of revolution: ChamferCyl, Capsule, OilTank, Spindle

def _profile_add(nodes, r, z, span):
    """Append profile node ``(r, z)`` whose band to the next node has attributes ``span``; repeated nodes merge."""
    if abs(r) < 1e-12:
        r = 0.0
    if nodes and abs(nodes[-1][0] - r) < 1e-12 and abs(nodes[-1][1] - z) < 1e-12:
        nodes[-1] = (min(nodes[-1][0], r), nodes[-1][1], span)
    else:
        nodes.append((r, z, span))


def _revolve(b, nodes, sides, slice_on, slice_from, slice_to, slice_material, ngon_caps=False, start=0.0):
    """
    Revolve a profile around Z, in Max's capsule layout (verified on a converted Capsule): the top pole, rings from
    the top down, the bottom pole; the top fan ``(pole, ring[k], ring[k + 1])``, bands of quads
    ``(upper[k], lower[k], lower[k + 1], upper[k + 1])``, the bottom fan ``(ring[k], pole, ring[k + 1])``.

    ``nodes``: ``(r, z, (smoothing group, material))`` from the top down; ``r == 0`` is a pole on the axis. The
    attributes are those of the band to the next node. ``ngon_caps``: a flat end band from the axis is one n-gon
    without a pole vertex (Max's one-segment caps), unless sliced. With slice on, each cut is one polygon closed
    along the axis (the profile has to start and end on the axis).
    """
    angles, closed = _arc(sides, slice_on, slice_from, slice_to)
    count = sides if closed else sides + 1
    last = len(nodes) - 1
    flat_top = ngon_caps and closed and last >= 2 and nodes[0][0] == 0.0 and nodes[1][1] == nodes[0][1]
    flat_bottom = ngon_caps and closed and last >= 2 and nodes[last][0] == 0.0 and nodes[last - 1][1] == nodes[last][1]

    lengths = [0.0]
    for (r0, z0, _s), (r1, z1, _t) in zip(nodes, nodes[1:]):
        lengths.append(lengths[-1] + math.hypot(r1 - r0, z1 - z0))
    total = lengths[-1] or 1.0
    us = [k / sides for k in range(sides + 1)]

    def uv_row(i):
        v = 1.0 - lengths[i] / total
        return [(u, v) for u in us]

    rings = []
    for i, (r, z, _span) in enumerate(nodes):
        if (i == 0 and flat_top) or (i == last and flat_bottom):
            rings.append(None)
        else:
            rings.append(_ring(b, r, z, angles, closed, start))

    for i in range(last):
        group, material = nodes[i][2]
        if rings[i] is None:
            b.face(rings[i + 1], _cap_uvs(angles[:count], 1.0, False, start), group, material)
        elif rings[i + 1] is None:
            b.face(rings[i][::-1], _cap_uvs(angles[:count], 1.0, True, start)[::-1], group, material)
        else:
            _band(b, rings[i], rings[i + 1], uv_row(i), uv_row(i + 1), sides, group, material)

    if not closed:
        r_max = max(r for r, _z, _s in nodes) or 1.0
        z_lo = min(z for _r, z, _s in nodes)
        z_span = (max(z for _r, z, _s in nodes) - z_lo) or 1.0
        for end, e in ((0, 0), (1, count - 1)):
            a = angles[e] + start
            outward = (math.sin(a), -math.cos(a), 0.0) if end == 0 else (-math.sin(a), math.cos(a), 0.0)
            uvs = [((1.0 - r / r_max) if end else r / r_max, (z - z_lo) / z_span) for r, z, _s in nodes]
            _face_outward(b, [ring[e] for ring in rings], uvs, 8 << end, slice_material, outward)


def _chamfer_cyl(radius, height, fillet, height_segments, fillet_segments, sides, cap_segments, smooth,
                 slice_on, slice_from, slice_to):
    b = _Builder()
    r, h = radius, abs(height)
    f = min(fillet, r, h * 0.5)
    hs, fs, cs = height_segments, fillet_segments, cap_segments
    group = 1 if smooth else 0
    top, sides_attr, bottom = (group, CAP_MATERIALS["TOP"]), (group, CAP_MATERIALS["SIDES"]), \
        (group, CAP_MATERIALS["BOTTOM"])
    # Profile from the top centre: top cap rings, top fillet, side, bottom fillet, bottom cap rings.
    nodes = []
    _profile_add(nodes, 0.0, h, top)
    for i in range(1, cs + 1):
        _profile_add(nodes, (r - f) * i / cs, h, top if i < cs else sides_attr)
    for k in range(1, fs + 1):
        angle = 0.5 * math.pi * (1.0 - k / fs)
        _profile_add(nodes, r - f + f * math.cos(angle), h - f + f * math.sin(angle), sides_attr)
    for j in range(1, hs + 1):
        _profile_add(nodes, r, h - f - (h - 2.0 * f) * j / hs, sides_attr)
    for k in range(1, fs + 1):
        angle = -0.5 * math.pi * k / fs
        _profile_add(nodes, r - f + f * math.cos(angle), f + f * math.sin(angle), sides_attr if k < fs else bottom)
    for i in range(cs - 1, -1, -1):
        _profile_add(nodes, (r - f) * i / cs, 0.0, bottom)
    _revolve(b, nodes, sides, slice_on, slice_from, slice_to, CAP_MATERIALS["SLICE"], ngon_caps=cs == 1)
    if height < 0.0:
        _mirror_z(b)
    return b


def _tank(b, radius, height, cap_height, height_type, blend, sides, cap_segments, height_segments, cap_shape,
          groups, slice_on, slice_from, slice_to):
    """
    A cylinder with two caps (Capsule, OilTank, Spindle), pivot at the bottom. ``cap_shape`` 'DOME' (a squashed
    hemisphere of height ``cap_height``) or 'CONE'. ``height_type`` 'OVERALL' measures the whole object, 'CENTERS'
    the cylinder between the caps. ``blend`` > 0 bevels the edge between a cap and the cylinder.
    ``groups``: smoothing groups (cap, cylinder).
    """
    r, h = radius, abs(height)
    ch = min(cap_height, r) if cap_shape == "DOME" else cap_height
    if height_type == "OVERALL":
        overall = max(h, 2.0 * ch)
        body = overall - 2.0 * ch
    else:
        body = h
        overall = body + 2.0 * ch
    cap_group, body_group = groups
    cap_attr, body_attr, blend_attr = (cap_group, 0), (body_group, 0), (cap_group | body_group, 0)
    # A bevel cuts `blend` off the cylinder and about as much off the cap.
    body_cut = min(blend, body * 0.5)
    if cap_shape == "DOME":
        end = 0.5 * math.pi - (min(0.45 * math.pi, blend / ch) if ch > 0.0 else 0.0)

        def cap_point(t):
            angle = end * t
            return r * math.sin(angle), ch * (1.0 - math.cos(angle))
    else:
        cone = math.hypot(r, ch)
        end = 1.0 - (min(0.9, blend / cone) if cone > 0.0 else 0.0)

        def cap_point(t):
            return r * end * t, ch * end * t

    cut = blend > 0.0
    nodes = []
    _profile_add(nodes, 0.0, overall, cap_attr)
    for k in range(1, cap_segments + 1):
        rho, depth = cap_point(k / cap_segments)
        _profile_add(nodes, rho, overall - depth, blend_attr if (cut and k == cap_segments) else cap_attr)
    top_z, bottom_z = overall - ch - body_cut, ch + body_cut
    for j in range(height_segments + 1):
        last = j == height_segments
        _profile_add(nodes, r, top_z - (top_z - bottom_z) * j / height_segments,
                     (blend_attr if cut else cap_attr) if last else body_attr)
    for k in range(cap_segments, -1, -1):
        rho, depth = cap_point(k / cap_segments)
        _profile_add(nodes, rho, depth, cap_attr)
    _revolve(b, nodes, sides, slice_on, slice_from, slice_to, 1)
    if height < 0.0:
        _mirror_z(b)
    return b


def _capsule(radius, height, height_type, sides, height_segments, smooth, slice_on, slice_from, slice_to):
    # A converted 8-sided Capsule has 4 bands per hemisphere and all faces in smoothing group 3 (mask 4).
    group = 4 if smooth else 0
    return _tank(_Builder(), radius, height, radius, height_type, 0.0, sides, max(1, sides // 2), height_segments,
                 "DOME", (group, group), slice_on, slice_from, slice_to)


def _oil_tank(radius, height, cap_height, height_type, blend, sides, height_segments, smooth,
              slice_on, slice_from, slice_to):
    # A converted 14-sided OilTank has 4 bands per cap, the caps in smoothing group 3, the cylinder in group 4.
    groups = (4, 8) if smooth else (0, 0)
    return _tank(_Builder(), radius, height, cap_height, height_type, blend, sides, max(2, (sides + 3) // 4),
                 height_segments, "DOME", groups, slice_on, slice_from, slice_to)


def _spindle(radius, height, cap_height, height_type, blend, sides, cap_segments, height_segments, smooth,
             slice_on, slice_from, slice_to):
    groups = (4, 8) if smooth else (0, 0)
    return _tank(_Builder(), radius, height, cap_height, height_type, blend, sides, cap_segments, height_segments,
                 "CONE", groups, slice_on, slice_from, slice_to)


# -----------------------------------------------------------------------------
# Extrusions: Gengon, Prism, L-Ext, C-Ext

def _extrude(b, points, loop, caps, walls, height, height_segments, top=(4, 0), bottom=(2, 1)):
    """
    A solid extruded along +Z from a planar region: ``points`` (x, y), the outline ``loop`` (indices into
    ``points``, counter-clockwise), the cap polygons ``caps`` (index lists, counter-clockwise) and ``walls[m]``, the
    (smoothing group, material) of the wall over loop edge ``loop[m] -> loop[m + 1]``. ``top`` and ``bottom``: the
    caps' (smoothing group, material). As the Box: the bottom layer, the rings in between, the top layer; faces
    bottom, top, then the walls row by row.
    """
    h, hs = height, height_segments
    b.flip ^= h < 0.0
    bottom_layer = [b.vert(x, y, 0.0) for x, y in points]
    middle = [[b.vert(points[i][0], points[i][1], h * k / hs) for i in loop] for k in range(1, hs)]
    top_layer = [b.vert(x, y, h) for x, y in points]
    rings = [[bottom_layer[i] for i in loop]] + middle + [[top_layer[i] for i in loop]]

    xs, ys = [p[0] for p in points], [p[1] for p in points]
    x0, y0 = min(xs), min(ys)
    dx, dy = (max(xs) - x0) or 1.0, (max(ys) - y0) or 1.0
    for cap in caps:
        uvs = [(1.0 - (points[i][0] - x0) / dx, (points[i][1] - y0) / dy) for i in cap]
        b.face([bottom_layer[i] for i in cap][::-1], uvs[::-1], bottom[0], bottom[1])
    for cap in caps:
        b.face([top_layer[i] for i in cap], [((points[i][0] - x0) / dx, (points[i][1] - y0) / dy) for i in cap],
               top[0], top[1])
    n = len(loop)
    lengths = [0.0]
    for m in range(n):
        (xa, ya), (xb, yb) = points[loop[m]], points[loop[(m + 1) % n]]
        lengths.append(lengths[-1] + math.hypot(xb - xa, yb - ya))
    us = [length / (lengths[-1] or 1.0) for length in lengths]
    for k in range(hs):
        lower, upper = rings[k], rings[k + 1]
        for m in range(n):
            m1 = (m + 1) % n
            group, material = walls[m]
            b.face((lower[m], lower[m1], upper[m1], upper[m]),
                   ((us[m], k / hs), (us[m + 1], k / hs), (us[m + 1], (k + 1) / hs), (us[m], (k + 1) / hs)),
                   group, material)
    return b


def _straight_sides(points, loop):
    """Index of the straight side each loop edge belongs to (consecutive collinear edges share one)."""
    n = len(loop)
    directions = []
    for m in range(n):
        (xa, ya), (xb, yb) = points[loop[m]], points[loop[(m + 1) % n]]
        directions.append(math.atan2(yb - ya, xb - xa))
    # The outlines used here start at a corner.
    sides = [0] * n
    for m in range(1, n):
        turn = abs((directions[m] - directions[m - 1] + math.pi) % TAU - math.pi)
        sides[m] = sides[m - 1] + (1 if turn > 1e-6 else 0)
    return sides


def _gengon(sides, radius, fillet, height, side_segments, height_segments, fillet_segments, smooth):
    b = _Builder()
    n, big = sides, radius
    half = math.pi / n
    # The largest fillet turns the polygon into its inscribed circle.
    f = min(fillet, big * math.cos(half))
    centre = big - f / math.cos(half) if f > 0.0 else big

    def corner(i, k):
        theta = TAU * i / n
        if f <= 0.0:
            return (big * math.cos(theta), big * math.sin(theta))
        phi = theta - half + 2.0 * half * k / fillet_segments
        return (centre * math.cos(theta) + f * math.cos(phi), centre * math.sin(theta) + f * math.sin(phi))

    # Outline from the first corner (on +X), counter-clockwise: each corner's fillet, then the side to the next one.
    group = 1 if smooth else 0
    points, walls = [], []
    for i in range(n):
        if f > 0.0:
            for k in range(fillet_segments):
                points.append(corner(i, k))
                walls.append((group, CAP_MATERIALS["SIDES"]))
        end = corner(i, fillet_segments)
        nxt = corner((i + 1) % n, 0)
        for s in range(side_segments):
            t = s / side_segments
            points.append((end[0] + (nxt[0] - end[0]) * t, end[1] + (nxt[1] - end[1]) * t))
            walls.append((group, CAP_MATERIALS["SIDES"]))
    # The largest fillet leaves no flat sides: drop the repeated points.
    kept = [m for m in range(len(points))
            if math.hypot(points[m][0] - points[m - 1][0], points[m][1] - points[m - 1][1]) > 1e-9 * max(big, 1e-9)]
    if len(kept) < 3:
        # Radius 0 (while creating interactively).
        return b
    points = [points[m] for m in kept]
    walls = [walls[m] for m in kept]
    loop = list(range(len(points)))
    return _extrude(b, points, loop, [loop], walls, height, height_segments,
                    top=(4, CAP_MATERIALS["TOP"]), bottom=(2, CAP_MATERIALS["BOTTOM"]))


def _prism_triangle(a, b, c):
    """
    Corners of a triangle with sides ``a`` (along +X from the origin), ``b`` and ``c``. A side 3 that doesn't fit is
    clamped to a thin triangle.
    """
    a, b = max(a, 1e-9), max(b, 1e-9)
    margin = 0.01 * min(a, b)
    c = min(max(c, abs(a - b) + margin), a + b - margin)
    x = (a * a + c * c - b * b) / (2.0 * a)
    y = math.sqrt(max(c * c - x * x, 0.0))
    return (0.0, 0.0), (a, 0.0), (x, y)


def _prism(side1_length, side2_length, side3_length, height, side1_segments, side2_segments, side3_segments,
           height_segments):
    b = _Builder()
    corners = _prism_triangle(side1_length, side2_length, side3_length)
    # Outline counter-clockwise from the pivot corner: side 1 along +X, side 2 to the apex, side 3 back.
    points, walls = [], []
    for side, segments in enumerate((side1_segments, side2_segments, side3_segments)):
        (xa, ya), (xb, yb) = corners[side], corners[(side + 1) % 3]
        for s in range(segments):
            t = s / segments
            points.append((xa + (xb - xa) * t, ya + (yb - ya) * t))
            walls.append((8 << side, 2 + side))
    loop = list(range(len(points)))
    return _extrude(b, points, loop, [loop], walls, height, height_segments, top=(4, 0), bottom=(2, 1))


def _grid_region(rects):
    """
    A planar quad mesh from rectangles ``(x0, y0, x1, y1, segments along x, segments along y)`` sharing edges:
    ``(points, quads, outline)``, the outline counter-clockwise from its corner nearest the region's (-X, -Y) corner.
    """
    points, quads, index = [], [], {}
    size = max(max(abs(v) for rect in rects for v in rect[:4]), 1e-9)

    def point(x, y):
        key = (round(x / size * 1e9), round(y / size * 1e9))
        if key not in index:
            index[key] = len(points)
            points.append((x, y))
        return index[key]

    for x0, y0, x1, y1, nx, ny in rects:
        if x1 - x0 <= 1e-12 * size or y1 - y0 <= 1e-12 * size:
            continue
        grid = [[point(x0 + (x1 - x0) * i / nx, y0 + (y1 - y0) * j / ny) for i in range(nx + 1)]
                for j in range(ny + 1)]
        for j in range(ny):
            for i in range(nx):
                quads.append((grid[j][i], grid[j][i + 1], grid[j + 1][i + 1], grid[j + 1][i]))
    if not quads:
        # Nothing left (zero sizes while creating interactively).
        return points, quads, []
    # The rectangles share whole edges with the same segment counts, so there are no T-junctions.
    loop = _border_loop(quads)
    xmin = min(p[0] for p in points)
    ymin = min(p[1] for p in points)
    first = min(range(len(loop)), key=lambda m: (points[loop[m]][0] - xmin) ** 2 + (points[loop[m]][1] - ymin) ** 2)
    return points, quads, loop[first:] + loop[:first]


def _extrusion_walls(points, loop):
    """Per outline edge: (smoothing group, material) of its straight side: each side flat, IDs from 2 on."""
    sides = _straight_sides(points, loop)
    return [(8 << (side % 24), 2 + side) for side in sides]


def _mirrored(points, sx, sy):
    return [(x * sx, y * sy) for x, y in points]


def _l_ext(side_length, front_length, side_width, front_width, height, side_segments, front_segments,
           width_segments, height_segments):
    b = _Builder()
    # Pivot at the centre of the bounding rectangle; the front leg runs along X at -Y, the side leg along Y at -X.
    # Negative lengths mirror the shape.
    sl, fl = abs(side_length), abs(front_length)
    sw, fw = min(side_width, fl), min(front_width, sl)
    x0, y0 = -fl * 0.5, -sl * 0.5
    ws = width_segments
    points, quads, loop = _grid_region([
        (x0, y0, x0 + sw, y0 + fw, ws, ws),
        (x0 + sw, y0, x0 + fl, y0 + fw, front_segments, ws),
        (x0, y0 + fw, x0 + sw, y0 + sl, ws, side_segments),
    ])
    if not quads:
        return b
    sx, sy = (-1.0 if front_length < 0.0 else 1.0), (-1.0 if side_length < 0.0 else 1.0)
    if sx * sy < 0.0:
        b.flip = True
    walls = _extrusion_walls(points, loop)
    return _extrude(b, _mirrored(points, sx, sy), loop, quads, walls, height, height_segments)


def _c_ext(back_length, side_length, front_length, back_width, side_width, front_width, height, back_segments,
           side_segments, front_segments, width_segments, height_segments):
    b = _Builder()
    # Pivot at the centre of the bounding rectangle; the side leg runs along Y at -X, the front leg along X at -Y,
    # the back leg along X at +Y: the opening faces +X. Negative lengths mirror the shape.
    bl, sl, fl = abs(back_length), abs(side_length), abs(front_length)
    sw = min(side_width, bl, fl)
    fw = min(front_width, sl)
    bw = min(back_width, sl - fw)
    wide = max(bl, fl)
    x0, y0 = -wide * 0.5, -sl * 0.5
    ws = width_segments
    points, quads, loop = _grid_region([
        (x0, y0, x0 + sw, y0 + fw, ws, ws),
        (x0 + sw, y0, x0 + fl, y0 + fw, front_segments, ws),
        (x0, y0 + fw, x0 + sw, y0 + sl - bw, ws, side_segments),
        (x0, y0 + sl - bw, x0 + sw, y0 + sl, ws, ws),
        (x0 + sw, y0 + sl - bw, x0 + bl, y0 + sl, back_segments, ws),
    ])
    if not quads:
        return b
    sy = -1.0 if side_length < 0.0 else 1.0
    if sy < 0.0:
        b.flip = True
    walls = _extrusion_walls(points, loop)
    return _extrude(b, _mirrored(points, 1.0, sy), loop, quads, walls, height, height_segments)


# -----------------------------------------------------------------------------
# ChamferBox

CHAMFERBOX_FILLET_MATERIAL = 6


def _chamfer_box(length, width, height, fillet, length_segments, width_segments, height_segments, fillet_segments,
                 smooth):
    """
    A box with rounded edges: flat sides (the Box's material IDs and order), edge fillets of ``fillet_segments``
    around and the box's segments along, and corner patches made of rows of quads ending in a triangle. Points are
    the inner box (shrunk by the fillet) plus the fillet radius in some direction; patches share vertices by
    position.
    """
    b = _Builder()
    w, l, h = abs(width), abs(length), abs(height)
    f = max(0.0, min(fillet, w * 0.5, l * 0.5, h * 0.5))
    n = fillet_segments
    inner = ((-w * 0.5 + f, w * 0.5 - f), (-l * 0.5 + f, l * 0.5 - f), (f, h - f))
    full = ((-w * 0.5, w * 0.5), (-l * 0.5, l * 0.5), (0.0, h))
    segments = (width_segments, length_segments, height_segments)
    weld = _Welder(b, max(w, l, h))
    # Negative sizes mirror the shape; faces are wound outwards in the mirrored positions.
    signs = (-1.0 if width < 0.0 else 1.0, -1.0 if length < 0.0 else 1.0, -1.0 if height < 0.0 else 1.0)
    group = 1 if smooth else 0

    def vertex(centre, direction):
        p = [(centre[a] + f * direction[a]) * signs[a] for a in range(3)]
        return weld(*p)

    def uv(centre, direction, axis):
        p = [centre[a] + f * direction[a] for a in range(3)]
        u_axis, v_axis = [a for a in range(3) if a != axis]
        return tuple((p[a] - full[a][0]) / ((full[a][1] - full[a][0]) or 1.0) for a in (u_axis, v_axis))

    def quad(cells, axis, material):
        # cells: four (centre, direction); wound outwards, smoothing and material as given.
        indices = [vertex(c, d) for c, d in cells]
        uvs = [uv(c, d, axis) for c, d in cells]
        outward = [sum(d[a] for _c, d in cells) * signs[a] for a in range(3)]
        _face_outward(b, indices, uvs, group, material, outward)

    def station(axis, k, count):
        lo, hi = inner[axis]
        return lo + (hi - lo) * k / count

    # Flat sides, in the Box's order: bottom, top, front, right, back, left.
    for side, axis, sign in (("BOTTOM", 2, -1.0), ("TOP", 2, 1.0), ("FRONT", 1, -1.0), ("RIGHT", 0, 1.0),
                             ("BACK", 1, 1.0), ("LEFT", 0, -1.0)):
        ua, va = [a for a in range(3) if a != axis]
        direction = tuple(sign if a == axis else 0.0 for a in range(3))
        fixed = inner[axis][1] if sign > 0.0 else inner[axis][0]
        for j in range(segments[va]):
            for i in range(segments[ua]):
                cells = []
                for di, dj in ((0, 0), (1, 0), (1, 1), (0, 1)):
                    centre = [0.0, 0.0, 0.0]
                    centre[axis] = fixed
                    centre[ua] = station(ua, i + di, segments[ua])
                    centre[va] = station(va, j + dj, segments[va])
                    cells.append((centre, direction))
                quad(cells, axis, BOX_SIDES[side][0])

    # Edge fillets: along each axis, at the four combinations of signs of the other two.
    for along in (0, 1, 2):
        a1, a2 = [a for a in range(3) if a != along]
        for s1 in (-1.0, 1.0):
            for s2 in (-1.0, 1.0):
                for m in range(segments[along]):
                    for k in range(n):
                        cells = []
                        for dm, dk in ((0, 0), (1, 0), (1, 1), (0, 1)):
                            angle = 0.5 * math.pi * (k + dk) / n
                            centre = [0.0, 0.0, 0.0]
                            centre[along] = station(along, m + dm, segments[along])
                            centre[a1] = inner[a1][1] if s1 > 0.0 else inner[a1][0]
                            centre[a2] = inner[a2][1] if s2 > 0.0 else inner[a2][0]
                            direction = [0.0, 0.0, 0.0]
                            direction[a1] = s1 * math.cos(angle)
                            direction[a2] = s2 * math.sin(angle)
                            cells.append((centre, direction))
                        quad(cells, a1, CHAMFERBOX_FILLET_MATERIAL)

    # Corners: the octant between three fillets, rows of quads closed by a triangle.
    for sx in (-1.0, 1.0):
        for sy in (-1.0, 1.0):
            for sz in (-1.0, 1.0):
                centre = (inner[0][1] if sx > 0.0 else inner[0][0], inner[1][1] if sy > 0.0 else inner[1][0],
                          inner[2][1] if sz > 0.0 else inner[2][0])

                def direction(i, j):
                    k = n - i - j
                    d = (sx * math.sin(0.5 * math.pi * i / n), sy * math.sin(0.5 * math.pi * j / n),
                         sz * math.sin(0.5 * math.pi * k / n))
                    length = math.sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2])
                    return tuple(c / length for c in d)

                for j in range(n):
                    for i in range(n - j):
                        if i < n - j - 1:
                            keys = ((i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1))
                        else:
                            keys = ((i, j), (i + 1, j), (i, j + 1))
                        cells = [(centre, direction(ki, kj)) for ki, kj in keys]
                        indices = [vertex(c, d) for c, d in cells]
                        uvs = [uv(c, d, 2) for c, d in cells]
                        outward = (sx * signs[0], sy * signs[1], sz * signs[2])
                        _face_outward(b, indices, uvs, group, CHAMFERBOX_FILLET_MATERIAL, outward)
    _compact(b)
    return b


# -----------------------------------------------------------------------------
# Torus Knot

def _knot_point(t, base_curve, radius, p, q, warp_count, warp_height):
    """Point of the base curve at parameter ``t`` in [0, 2 pi)."""
    warp = 1.0 + warp_height * math.sin(warp_count * t)
    if base_curve == "CIRCLE":
        rho = radius * warp
        return (rho * math.cos(t), rho * math.sin(t), 0.0)
    # (p, q) torus knot: p turns around Z, q turns around the core circle; the overall radius is `radius`.
    rho = radius * warp * (2.0 + math.cos(q * t)) / 3.0
    return (rho * math.cos(p * t), rho * math.sin(p * t), -radius * math.sin(q * t) / 3.0)


def _torus_knot(base_curve, radius, segments, p, q, warp_count, warp_height, cross_section_radius, sides,
                eccentricity, twist, lumps, lump_height, lump_offset, smooth_mode):
    b = _Builder()
    m, n = segments, sides
    curve = [_knot_point(TAU * i / m, base_curve, radius, p, q, warp_count, warp_height) for i in range(m)]

    def sub(u, v):
        return (u[0] - v[0], u[1] - v[1], u[2] - v[2])

    def cross(u, v):
        return (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])

    def dot(u, v):
        return u[0] * v[0] + u[1] * v[1] + u[2] * v[2]

    def unit(u):
        length = math.sqrt(dot(u, u))
        return (u[0] / length, u[1] / length, u[2] / length) if length > 1e-12 else (0.0, 0.0, 1.0)

    tangents = [unit(sub(curve[(i + 1) % m], curve[i - 1])) for i in range(m)]
    # Rotation-minimising frames, starting with the normal pointing away from Z (the outside, as on the Torus);
    # the angle left over after going round is spread along the knot so that the tube closes.
    first = curve[0]
    normal = (first[0], first[1], 0.0)
    normal = unit(sub(normal, tuple(c * dot(normal, tangents[0]) for c in tangents[0])))
    normals = [normal]
    for i in range(1, m + 1):
        t = tangents[i % m]
        prev = normals[-1]
        normals.append(unit(sub(prev, tuple(c * dot(prev, t) for c in t))))
    end = normals.pop()
    error = math.atan2(dot(cross(normals[0], end), tangents[0]), dot(normals[0], end))

    rings = []
    for i in range(m):
        t, nrm = tangents[i], normals[i]
        binormal = cross(nrm, t)
        param = TAU * i / m
        # The end frame at angle psi is the start frame at psi - error.
        offset = (twist + error) * i / m
        bump = 0.5 - 0.5 * math.cos(lumps * param + lump_offset)
        rc = cross_section_radius * (1.0 + lump_height * bump)
        ring = []
        for j in range(n):
            psi = TAU * j / n + offset
            c, s = rc * math.cos(psi), rc * eccentricity * math.sin(psi)
            point = curve[i]
            ring.append(b.vert(point[0] + c * nrm[0] + s * binormal[0], point[1] + c * nrm[1] + s * binormal[1],
                               point[2] + c * nrm[2] + s * binormal[2]))
        rings.append(ring)

    def group(i, j):
        if smooth_mode == "ALL":
            return 1
        if smooth_mode == "SIDES":
            return _cyclic_group(j, n, True)
        if smooth_mode == "SEGMENTS":
            return _cyclic_group(i, m, True)
        return 0

    for i in range(m):
        ra, rb = rings[i], rings[(i + 1) % m]
        for j in range(n):
            j1 = (j + 1) % n
            b.face((ra[j], rb[j], rb[j1], ra[j1]),
                   ((i / m, j / n), ((i + 1) / m, j / n), ((i + 1) / m, (j + 1) / n), (i / m, (j + 1) / n)),
                   group(i, j), 0)
    return b


# -----------------------------------------------------------------------------
# Hedra

def _dual(verts, faces):
    """Dual of a convex polyhedron centred on the origin: face centres as vertices, a face around each vertex."""
    centres = [_normalize([sum(verts[i][k] for i in face) / len(face) for k in range(3)]) for face in faces]
    dual_faces = []
    for v in range(len(verts)):
        around = [f for f, face in enumerate(faces) if v in face]
        dual_faces.append(_sorted_around(verts[v], around, centres))
    return [_normalize(v) for v in centres], dual_faces


def _sorted_around(axis, items, points):
    """``items`` (indices into ``points``) sorted counter-clockwise around ``axis`` seen from outside."""
    axis = _normalize(axis)
    helper = (1.0, 0.0, 0.0) if abs(axis[0]) < 0.9 else (0.0, 1.0, 0.0)
    u = _normalize((helper[1] * axis[2] - helper[2] * axis[1], helper[2] * axis[0] - helper[0] * axis[2],
                    helper[0] * axis[1] - helper[1] * axis[0]))
    w = (axis[1] * u[2] - axis[2] * u[1], axis[2] * u[0] - axis[0] * u[2], axis[0] * u[1] - axis[1] * u[0])

    def angle(i):
        p = points[i]
        return math.atan2(sum(p[k] * w[k] for k in range(3)), sum(p[k] * u[k] for k in range(3)))

    return sorted(items, key=angle)


def _hedra_base(family):
    if family == "TETRA":
        return _base_polyhedron("TETRA")
    if family == "CUBE_OCTA":
        return _base_polyhedron("OCTA")
    if family == "STAR2":
        return _dual(*_base_polyhedron("ICOSA"))
    return _base_polyhedron("ICOSA")


# How far a star family raises the centres of its base faces (relative to their distance from the centre).
_STAR_RAISE = {"STAR1": 2.0, "STAR2": 2.4}


def _hedra(family, family_p, family_q, axis_scale_p, axis_scale_q, axis_scale_r, vertex_mode, radius):
    """
    Polyhedra in the symmetry of a base solid (Wythoff construction): every triangle (vertex, edge midpoint, face
    centre) of the base solid's barycentric subdivision gets the point ``r * vertex + q * edge + p * face``
    (``r = 1 - p - q``). The faces are the points around each base face ("P" faces), each base vertex ("Q" faces)
    and each base edge ("R" faces); faces that collapse are dropped. P = Q = 0 gives the base solid, P = 1 its dual,
    Q = 1 the solid with vertices at its edge midpoints. Material IDs: P faces 0, Q faces 1, R faces 2. The star
    families raise the centres of the base faces. Axis scaling moves the centres of the P, Q and R faces
    (percent); faces then become fans around their centre, as do all faces with the Center vertex modes.
    """
    b = _Builder()
    p, q = family_p, family_q
    if p + q > 1.0:
        p, q = p / (p + q), q / (p + q)
    r = 1.0 - p - q
    verts, faces = _hedra_base(family)
    centres = [_normalize([sum(verts[i][k] for i in face) / len(face) for k in range(3)]) for face in faces]

    # Fundamental triangles: (vertex, edge (sorted pair), face).
    triangles = []
    for f, face in enumerate(faces):
        for k in range(len(face)):
            a, c = face[k], face[(k + 1) % len(face)]
            edge = (min(a, c), max(a, c))
            triangles.append((a, edge, f))
            triangles.append((c, edge, f))
    edge_dirs = {}
    for _v, edge, _f in triangles:
        if edge not in edge_dirs:
            edge_dirs[edge] = _normalize([verts[edge[0]][k] + verts[edge[1]][k] for k in range(3)])
    points = []
    for v, edge, f in triangles:
        e = edge_dirs[edge]
        points.append(tuple(r * verts[v][k] + q * e[k] + p * centres[f][k] for k in range(3)))
    scale = radius / max(math.sqrt(sum(c * c for c in pt)) for pt in points)
    weld = _Welder(b, radius)
    corner = [weld(*(c * scale for c in pt)) for pt in points]

    groups = {}
    for t, (v, edge, f) in enumerate(triangles):
        groups.setdefault(("P", f), []).append(t)
        groups.setdefault(("Q", v), []).append(t)
        groups.setdefault(("R", edge), []).append(t)
    axes = {"P": lambda key: centres[key], "Q": lambda key: verts[key], "R": lambda key: edge_dirs[key]}
    scales = {"P": axis_scale_p / 100.0, "Q": axis_scale_q / 100.0, "R": axis_scale_r / 100.0}
    raise_p = _STAR_RAISE.get(family, 1.0)
    materials = {"P": 0, "Q": 1, "R": 2}

    polygons = []
    for (kind, key), members in groups.items():
        axis = axes[kind](key)
        ordered = _sorted_around(axis, members, points)
        polygon = []
        for t in ordered:
            if not polygon or corner[t] != polygon[-1]:
                polygon.append(corner[t])
        if len(polygon) > 1 and polygon[0] == polygon[-1]:
            polygon.pop()
        if len(polygon) >= 3:
            polygons.append((kind, polygon))

    for kind, polygon in polygons:
        material = materials[kind]
        pts = [b.vertices[i] for i in polygon]
        centroid = [sum(pt[k] for pt in pts) / len(pts) for k in range(3)]
        push = scales[kind] * (raise_p if kind == "P" else 1.0)
        fan = vertex_mode != "BASIC" or abs(push - 1.0) > 1e-9
        if not fan:
            b.face(polygon, _spherical_uvs([_normalize(pt) for pt in pts]), 0, material)
            continue
        centre = weld(*(c * push for c in centroid))
        if vertex_mode == "CENTER_SIDES":
            mids = []
            for k in range(len(polygon)):
                pa, pb = b.vertices[polygon[k]], b.vertices[polygon[(k + 1) % len(polygon)]]
                mids.append(weld(*((pa[c] + pb[c]) * 0.5 for c in range(3))))
            for k in range(len(polygon)):
                face = (polygon[k], mids[k], centre, mids[k - 1])
                b.face(face, _spherical_uvs([_normalize(b.vertices[i]) for i in face]), 0, material)
        else:
            for k in range(len(polygon)):
                face = (polygon[k], polygon[(k + 1) % len(polygon)], centre)
                b.face(face, _spherical_uvs([_normalize(b.vertices[i]) for i in face]), 0, material)
    _compact(b)
    return b


_GENERATORS = {
    "BOX": _box,
    "SPHERE": _sphere,
    "GEOSPHERE": _geosphere,
    "CYLINDER": _cylinder,
    "TUBE": _tube,
    "CONE": _cone,
    "TORUS": _torus,
    "PYRAMID": _pyramid,
    "PLANE": _plane,
    "TEST_SHAPE": _test_shape,
    "CHAMFERBOX": _chamfer_box,
    "CHAMFERCYL": _chamfer_cyl,
    "CAPSULE": _capsule,
    "OILTANK": _oil_tank,
    "SPINDLE": _spindle,
    "GENGON": _gengon,
    "PRISM": _prism,
    "L_EXT": _l_ext,
    "C_EXT": _c_ext,
    "TORUS_KNOT": _torus_knot,
    "HEDRA": _hedra,
}
