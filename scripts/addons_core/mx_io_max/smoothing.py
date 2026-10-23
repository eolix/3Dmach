# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Max smoothing groups to Blender sharp edges and flat faces.

In Max every face carries a 32-bit smoothing-group mask. Normals are averaged across an edge only when the two
faces sharing it have at least one smoothing group in common; a face with no smoothing group is faceted.
Blender (4.1+) expresses the same thing with the ``sharp_edge`` and ``sharp_face`` boolean attributes.

This module has no Blender dependency so it can be tested with plain pytest.
"""

__all__ = (
    "sharp_from_smoothing_groups",
    "smoothing_groups_from_sharp",
)

GROUP_COUNT = 32


def sharp_from_smoothing_groups(faces, groups):
    """
    Compute Blender sharpness from Max smoothing groups.

    :arg faces: Polygons as sequences of vertex indices.
    :arg groups: One smoothing-group bit mask per polygon.
    :return: ``(sharp_edges, sharp_faces)``: a set of sorted ``(v1, v2)`` vertex pairs for edges that must be
       sharp, and a list with one bool per polygon (True for faces without any smoothing group).
    """
    if len(faces) != len(groups):
        raise ValueError("faces and groups differ in length ({:d} != {:d})".format(len(faces), len(groups)))

    sharp_faces = [group == 0 for group in groups]
    # Edge -> smoothing mask of the first face seen with it, or None once it is known to be sharp/handled.
    first_mask = {}
    sharp_edges = set()
    for face, group in zip(faces, groups):
        count = len(face)
        for i in range(count):
            a, b = face[i], face[(i + 1) % count]
            edge = (a, b) if a < b else (b, a)
            if edge not in first_mask:
                first_mask[edge] = group
            elif (first_mask[edge] & group) == 0:
                sharp_edges.add(edge)
            # Edges shared by more than two faces (non-manifold) are sharp if any pair shares no group,
            # which the check above handles for each later face against the first one.
    return sharp_edges, sharp_faces


def smoothing_groups_from_sharp(faces, sharp_edges=(), sharp_faces=None):
    """
    Max smoothing groups that reproduce Blender sharpness (the inverse of :func:`sharp_from_smoothing_groups`).

    Faces joined by smooth edges form a region and share one group; regions meeting at a sharp edge get
    different groups (greedy colouring with the 32 groups Max has). Flat faces get no group. A sharp edge
    inside one region (the region connects around it) can't be expressed with smoothing groups and comes out
    smooth; so do sharp edges between regions when more than 32 groups would be needed around one region.

    :arg faces: Polygons as sequences of vertex indices.
    :arg sharp_edges: ``(v1, v2)`` vertex pairs of sharp edges (any order).
    :arg sharp_faces: One bool per polygon (True = flat shaded), or None.
    :return: One smoothing-group mask per polygon.
    """
    count = len(faces)
    flat = list(sharp_faces) if sharp_faces is not None else [False] * count
    if len(flat) != count:
        raise ValueError("faces and sharp_faces differ in length ({:d} != {:d})".format(count, len(flat)))
    sharp = {(a, b) if a < b else (b, a) for a, b in sharp_edges}
    parent = list(range(count))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    edge_faces = {}
    for index, face in enumerate(faces):
        n = len(face)
        for i in range(n):
            a, b = face[i], face[(i + 1) % n]
            edge_faces.setdefault((a, b) if a < b else (b, a), []).append(index)
    for edge, users in edge_faces.items():
        if edge in sharp:
            continue
        smooth = [f for f in users if not flat[f]]
        for other in smooth[1:]:
            ra, rb = find(smooth[0]), find(other)
            if ra != rb:
                parent[rb] = ra
    neighbours = {}
    for edge, users in edge_faces.items():
        roots = {find(f) for f in users if not flat[f]}
        if len(roots) > 1:
            for r in roots:
                neighbours.setdefault(r, set()).update(roots - {r})
    colour = {}
    for index in range(count):
        if flat[index]:
            continue
        root = find(index)
        if root in colour:
            continue
        used = {colour[n] for n in neighbours.get(root, ()) if n in colour}
        free = [c for c in range(GROUP_COUNT) if c not in used]
        colour[root] = free[0] if free else len(colour) % GROUP_COUNT
    return [0 if flat[i] else 1 << colour[find(i)] for i in range(count)]
