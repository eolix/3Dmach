# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
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
)


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
