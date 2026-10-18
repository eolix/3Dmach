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
  and Torus at their centre (unless "base to pivot"); Plane at its centre.
- Box: width along X, length along Y, height along Z. Pyramid: width X, depth Y. Plane: width X, length Y.
- Angles (slice, rotation, twist) are in radians. Ring vertices start at +X and run counter-clockwise seen
  from +Z. With slice on, the part that is kept runs counter-clockwise from ``slice_from`` to ``slice_to``;
  equal angles give the whole object back.
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
}

KIND_IDS = tuple(PARAMETERS)

# Allowed values of the enumeration parameters.
ENUMS = {
    "hemisphere_mode": ("CHOP", "SQUASH"),
    "base_type": ("TETRA", "OCTA", "ICOSA"),
    "smooth_mode": ("ALL", "SIDES", "NONE", "SEGMENTS"),
}

# (minimum, maximum) per parameter; ``None`` means unbounded. Kind-specific entries override the generic ones.
_GENERIC_LIMITS = {
    "length": (0.0, None), "width": (0.0, None), "depth": (0.0, None), "height": (None, None),
    "radius": (0.0, None), "radius1": (0.0, None), "radius2": (0.0, None),
    "length_segments": (1, 1000), "width_segments": (1, 1000), "depth_segments": (1, 200),
    "height_segments": (1, 200), "cap_segments": (1, 100), "sides": (3, 200), "segments": (3, 200),
    "hemisphere": (0.0, 1.0),
}
_KIND_LIMITS = {
    ("SPHERE", "segments"): (4, 200),
    ("GEOSPHERE", "segments"): (1, 200),
    ("TEST_SHAPE", "segments"): (1, 64),
    ("BOX", "height_segments"): (1, 1000),
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


def _ring(builder, radius, z, angles, closed):
    """Vertices of a ring around Z. A ring of radius 0 is a single vertex, repeated."""
    count = len(angles) - 1 if closed else len(angles)
    if radius == 0.0:
        return [builder.vert(0.0, 0.0, z)] * count
    return [builder.vert(radius * math.cos(a), radius * math.sin(a), z) for a in angles[:count]]


def _cyclic_group(index, count, closed):
    """Smoothing group for item ``index`` of ``count`` neighbours so that adjacent items never share a group."""
    if closed and count % 2 == 1 and index == count - 1:
        return 4
    return 1 if index % 2 == 0 else 2


def _cap_uvs(angles, fraction, mirror):
    """Planar UVs of a ring of relative radius ``fraction`` on a disc cap, mirrored for bottom caps."""
    sign = -1.0 if mirror else 1.0
    return [(0.5 + sign * 0.5 * fraction * math.cos(a), 0.5 + 0.5 * fraction * math.sin(a)) for a in angles]


# -----------------------------------------------------------------------------
# Box

# Material IDs (0-based) and smoothing groups per side. Max gives each side of a box its own material ID and
# smoothing group; which number goes to which side is unverified (see the decision record).
BOX_SIDES = {
    #          material, smoothing group
    "BOTTOM": (1, 1 << 1),
    "TOP": (0, 1 << 2),
    "FRONT": (4, 1 << 3),   # -Y
    "RIGHT": (2, 1 << 4),   # +X
    "BACK": (5, 1 << 5),    # +Y
    "LEFT": (3, 1 << 6),    # -X
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

    # Faces: bottom, top, front, right, back, left.
    grid("BOTTOM", lambda a, c: (ws - a, c, 0), uv_grid(ws, ls))
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

    # Vertices: top pole, rings from the top down, then the bottom pole (or the centre of the hemisphere's base).
    top = b.vert(0.0, 0.0, r + z_offset)
    rings = []
    for theta in thetas:
        rho = r * math.sin(theta)
        rings.append(_ring(b, rho, r * math.cos(theta) + z_offset, angles, closed))
    count = len(rings[0])
    bottom = b.vert(0.0, 0.0, bottom_z + z_offset)

    us = [k / n for k in range(n + 1)]

    def uv_row(theta):
        return [(u, 1.0 - theta / math.pi) for u in us]

    group = 1 if smooth else 0
    # Faces: bands from the top down.
    prev, prev_theta = [top] * count, 0.0
    for ring, theta in zip(rings, thetas):
        b.strip(ring, prev, uv_row(theta), uv_row(prev_theta), n, group, 0)
        prev, prev_theta = ring, theta
    if cut:
        # Base of the hemisphere: a fan around a centre vertex.
        b.strip([bottom] * count, prev, _cap_uvs(angles, 0.0, True), _cap_uvs(angles, 1.0, True), n, 2, 0)
    else:
        b.strip([bottom] * count, prev, uv_row(math.pi), uv_row(prev_theta), n, group, 0)

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

    def cap_radius(i):
        return inner_r + (outer_r - inner_r) * i / cs

    # Vertices: outer wall rings upwards, inner wall rings upwards, then the rings inside the bottom and top caps.
    outer = [_ring(b, outer_r, h * j / hs, angles, closed) for j in range(hs + 1)]
    inner = [_ring(b, inner_r, h * j / hs, angles, closed) for j in range(hs + 1)]
    bottom = [inner[0]] + [_ring(b, cap_radius(i), 0.0, angles, closed) for i in range(1, cs)] + [outer[0]]
    top = [inner[hs]] + [_ring(b, cap_radius(i), h, angles, closed) for i in range(1, cs)] + [outer[hs]]
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
        b.strip(bottom[i], bottom[i + 1], _cap_uvs(angles, cap_fraction(i), True),
                _cap_uvs(angles, cap_fraction(i + 1), True), n, 4, TUBE_MATERIALS["BOTTOM"])
    for i in range(cs, 0, -1):
        b.strip(top[i], top[i - 1], _cap_uvs(angles, cap_fraction(i), False),
                _cap_uvs(angles, cap_fraction(i - 1), False), n, 8, TUBE_MATERIALS["TOP"])

    if not closed:
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

    # Vertices: one ring (cross-section) per segment, counter-clockwise around Z; in each ring the vertices start
    # on the outside of the torus (+ rotation, + the twist so far) and run upwards around the tube.
    rings = []
    for i in range(ring_count):
        phi = angles[i]
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
}
