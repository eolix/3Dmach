# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Max shapes (``maxfile`` ``ShapeData``) to Blender curves, and the shape-to-mesh modifiers at the bottom of a
stack (Extrude, Lathe).

- A shape on its own becomes a Bezier curve object: knots and their absolute in / out handles as stored, knot
  types as handle types (smooth / Bezier -> aligned, corners -> free), the interpolation steps as the curve
  resolution, and the "Rendering" thickness as a round bevel when the shape is renderable.
- **Extrude** builds the extruded mesh here (amount along the shape's local Z, segments, start / end caps with
  holes, Max's material IDs 1 / 2 / 3 for start cap / end cap / sides, sharp edges at corner knots), so the
  modifiers above it work on a mesh.
- **Lathe** becomes the profile as a polyline mesh with a Screw modifier around the Lathe axis (the gizmo's
  local Z: degrees, segments, weld core), which keeps it editable.

Parameter IDs of Extrude and Lathe (old ParamBlocks), from the corpus (135 Extrude, 51 Lathe):

- Extrude, slot 0: 0 amount (scene units), 1 segments (1 on 126), 2 / 3 cap start / end (on on 133), 4 cap type
  (0 morph on 134), 5 output (1 mesh on all), 6 generate mapping coords, 7 generate material IDs (on on 134),
  8 use shape IDs (off on all), 9 smooth (on on all). Guess: 4-9 from Max's UI order and defaults.
- Lathe, slot 1 (slot 0 is the axis gizmo's Position/Rotation/Scale): 0 degrees (360 on all), 1 segments (8-36),
  2 / 3 cap start / end, 4 cap type, 6 output (1 mesh on 46 of 51). The axis direction is not a parameter: it is
  the gizmo's rotation (a quarter turn about X on the 48 lathes made with the default Y direction puts the
  gizmo's Z on the shape's Y; a quarter turn about Y for one made with X), and the gizmo sits at the profile's
  minimum X and middle Y (Max's default "Align Min"). Guess: 5 weld core.

No ``bpy`` in the geometry functions (``polyline``, ``extrude_mesh``); ``bpy`` / ``mathutils`` are imported
where curves and meshes are made.
"""

__all__ = (
    "EXTRUDE_PARAMS",
    "LATHE_PARAMS",
    "extrude_mesh",
    "polyline",
    "shape_bounds",
)

import math

EXTRUDE_PARAMS = {0: "amount", 1: "segments", 2: "cap_start", 3: "cap_end", 4: "cap_type", 5: "output",
                  6: "generate_mapping_coords", 7: "generate_material_ids", 8: "use_shape_ids", 9: "smooth"}
EXTRUDE_SLOT = 0
LATHE_PARAMS = {0: "degrees", 1: "segments", 2: "cap_start", 3: "cap_end", 4: "cap_type", 5: "weld_core",
                6: "output"}
LATHE_SLOT = 1
LATHE_GIZMO_SLOT = 0

CORNER_KNOTS = {"corner", "bezier_corner"}
SMOOTH_KNOTS = {"smooth", "bezier"}


def _bezier(p0, p1, p2, p3, t):
    s = 1.0 - t
    a, b, c, d = s * s * s, 3.0 * s * s * t, 3.0 * s * t * t, t * t * t
    return tuple(a * p0[i] + b * p1[i] + c * p2[i] + d * p3[i] for i in range(3))


def _straight(p0, p1, p2, p3, eps=1e-6):
    """Whether a Bezier segment is a straight line (handles on the chord)."""
    dx = [p3[i] - p0[i] for i in range(3)]
    length = math.sqrt(sum(c * c for c in dx))
    if length < eps:
        return True
    for p in (p1, p2):
        v = [p[i] - p0[i] for i in range(3)]
        cross = (v[1] * dx[2] - v[2] * dx[1], v[2] * dx[0] - v[0] * dx[2], v[0] * dx[1] - v[1] * dx[0])
        if math.sqrt(sum(c * c for c in cross)) / length > eps * max(1.0, length):
            return False
    return True


def polyline(spline, steps=6):
    """
    The spline as points: each knot, plus ``steps`` points inside every curved segment (straight segments get
    none, like Max's optimised interpolation). Returns ``(points, knot_index_of_point)``; the closing segment of
    a closed spline is included, its end point (the first knot) is not repeated.
    """
    knots = spline.knots
    n = len(knots)
    points, owners = [], []
    if n == 0:
        return points, owners
    count = n if spline.closed else n - 1
    for i in range(n):
        points.append(tuple(knots[i].position))
        owners.append(i)
        if i >= count:
            break
        a, b = knots[i], knots[(i + 1) % n]
        p0, p1, p2, p3 = a.position, a.out_handle, b.in_handle, b.position
        if a.segment_type == "line" or _straight(p0, p1, p2, p3):
            continue
        for k in range(1, steps + 1):
            points.append(_bezier(p0, p1, p2, p3, k / (steps + 1.0)))
            owners.append(None)
    return points, owners


def _signed_area(points):
    area = 0.0
    for i, (x0, y0, _z0) in enumerate(points):
        x1, y1, _z1 = points[(i + 1) % len(points)]
        area += x0 * y1 - x1 * y0
    return area * 0.5


def _inside(point, polygon):
    x, y = point[0], point[1]
    inside = False
    n = len(polygon)
    for i in range(n):
        x0, y0 = polygon[i][0], polygon[i][1]
        x1, y1 = polygon[(i - 1) % n][0], polygon[(i - 1) % n][1]
        if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
            inside = not inside
    return inside


def shape_bounds(splines):
    pts = [k.position for s in splines for k in s.knots]
    if not pts:
        return None
    return (tuple(min(p[i] for p in pts) for i in range(3)), tuple(max(p[i] for p in pts) for i in range(3)))


def extrude_mesh(splines, amount, segments=1, cap_start=True, cap_end=True, steps=6, tessellate=None):
    """
    The mesh of Max's Extrude.

    :arg splines: ``ShapeSpline`` list.
    :arg tessellate: ``f(list of point loops) -> triangles`` (``mathutils.geometry.tessellate_polygon``), for
       the caps; None leaves the caps out.
    :return: ``(positions, faces, material_ids (1-based), smoothing_groups, sharp_edges)``.
    """
    segments = max(int(segments), 1)
    positions, faces, mat_ids, groups = [], [], [], []
    sharp = set()
    loops = []      # (point list, closed, owners, knot types)
    for spline in splines:
        pts, owners = polyline(spline, steps)
        if len(pts) < 2:
            continue
        loops.append((pts, spline.closed and len(pts) >= 3, owners, [k.knot_type for k in spline.knots]))
    # Orientation: outlines counter-clockwise, holes clockwise (nesting depth by point in polygon), so the sides
    # face outwards; a negative amount turns everything over.
    closed = [loop for loop in loops if loop[1]]
    for index, loop in enumerate(loops):
        pts = loop[0]
        if not loop[1]:
            continue
        depth = sum(1 for other in closed if other is not loop and _inside(pts[0], other[0]))
        want_ccw = depth % 2 == 0
        if (_signed_area(pts) > 0.0) != want_ccw:
            loops[index] = (list(reversed(pts)), loop[1], list(reversed(loop[2])), loop[3])
    flip = amount < 0.0
    rings = []
    for pts, is_closed, owners, knot_types in loops:
        base = len(positions)
        n = len(pts)
        for layer in range(segments + 1):
            dz = amount * layer / segments
            positions.extend((x, y, z + dz) for x, y, z in pts)
        count = n if is_closed else n - 1
        for layer in range(segments):
            lo, hi = base + layer * n, base + (layer + 1) * n
            for i in range(count):
                j = (i + 1) % n
                quad = (lo + i, lo + j, hi + j, hi + i)
                faces.append(tuple(reversed(quad)) if flip else quad)
                mat_ids.append(3)
                groups.append(1)
        for i, owner in enumerate(owners):
            if owner is not None and owner < len(knot_types) and knot_types[owner] in CORNER_KNOTS:
                for layer in range(segments):
                    a, b = base + layer * n + i, base + (layer + 1) * n + i
                    sharp.add((a, b) if a < b else (b, a))
        rings.append((base, n, is_closed))
    if tessellate is not None and closed and (cap_start or cap_end):
        outline = [(base, n) for base, n, is_closed in rings if is_closed]
        polys = [[positions[base + i] for i in range(n)] for base, n in outline]
        flat = [(base, i) for base, n in outline for i in range(n)]
        sizes = dict(outline)
        try:
            triangles = tessellate([[(p[0], p[1], 0.0) for p in poly] for poly in polys])
        except (ValueError, TypeError):
            triangles = []
        for cap, layer, normal_up in ((cap_start, 0, False), (cap_end, segments, True)):
            if not cap:
                continue
            for tri in triangles:
                verts = []
                for t in tri:
                    base, i = flat[t]
                    verts.append(base + layer * sizes[base] + i)
                pa, pb, pc = (positions[v] for v in verts)
                nz = (pb[0] - pa[0]) * (pc[1] - pa[1]) - (pb[1] - pa[1]) * (pc[0] - pa[0])
                up = (nz > 0.0) != flip
                if up != normal_up:
                    verts.reverse()
                faces.append(tuple(verts))
                mat_ids.append(2 if normal_up else 1)
                groups.append(0)
    return positions, faces, mat_ids, groups, sharp
