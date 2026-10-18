# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Editable Mesh triangles to the polygons Max shows.

An Editable Mesh stores triangles with per-edge visibility; a hidden edge is the diagonal of a polygon split into
triangles (``docs/format/overview.md`` §6.3: 2.84 million hidden edges, each shared by exactly two triangles that
both hide it). Triangles joined by hidden edges are merged back into one polygon when their outline is a single
simple loop; anything else (holes, non-manifold groups, very large groups) stays triangulated.

No Blender dependency.
"""

__all__ = (
    "merge_triangles",
)


def merge_triangles(faces, visibility, channels=(), max_group=256):
    """
    Merge triangles along hidden edges.

    :arg faces: triangles ``(a, b, c)``.
    :arg visibility: per triangle, bits 0-2 = edge a-b, b-c, c-a visible.
    :arg channels: per map channel, its triangles (texture vertex indices, corner for corner with ``faces``).
    :return: ``(polygons, source triangle of each polygon, [polygons of each channel])``, or None when nothing
       was merged.
    """
    count = len(faces)
    parent = list(range(count))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    owner = {}
    merged_any = False
    for t in range(count):
        vis = visibility[t]
        if vis & 7 == 7:
            continue
        a, b, c = faces[t]
        for k, (u, v) in enumerate(((a, b), (b, c), (c, a))):
            if vis & (1 << k):
                continue
            key = (u, v) if u < v else (v, u)
            other = owner.pop(key, None)
            if other is None:
                owner[key] = t
            else:
                ra, rb = find(other), find(t)
                if ra != rb:
                    parent[rb] = ra
                    merged_any = True
    if not merged_any:
        return None

    groups = {}
    for t in range(count):
        root = find(t)
        if root != t or parent[t] != t:
            groups.setdefault(root, []).append(t)
    for root in list(groups):
        groups[root].append(root)

    polygons, sources = [], []
    channel_polys = [[] for _ in channels]
    done = set()
    for t in range(count):
        if t in done:
            continue
        root = find(t)
        members = groups.get(root)
        if members is None or len(members) < 2 or len(members) > max_group:
            done.add(t)
            polygons.append(tuple(faces[t]))
            sources.append(t)
            for out, chan in zip(channel_polys, channels):
                out.append(tuple(chan[t]))
            continue
        done.update(members)
        loop = _outline(faces, members)
        if loop is None:
            for m in sorted(members):
                polygons.append(tuple(faces[m]))
                sources.append(m)
                for out, chan in zip(channel_polys, channels):
                    out.append(tuple(chan[m]))
            continue
        polygons.append(tuple(v for v, _tri, _corner in loop))
        sources.append(min(members))
        for out, chan in zip(channel_polys, channels):
            out.append(tuple(chan[tri][corner] for _v, tri, corner in loop))
    return polygons, sources, channel_polys


def _outline(faces, members):
    """The group's boundary as ``[(vertex, triangle, corner)]`` in winding order, or None if it isn't one loop."""
    directed = set()
    for m in members:
        a, b, c = faces[m]
        directed.update(((a, b), (b, c), (c, a)))
    following = {}
    for m in members:
        tri = faces[m]
        for k in range(3):
            u, v = tri[k], tri[(k + 1) % 3]
            if (v, u) in directed:
                continue        # Interior edge.
            if u in following:
                return None     # The outline touches itself.
            following[u] = (v, m, k)
    if len(following) < 3:
        return None
    start = next(iter(following))
    loop = []
    vertex = start
    for _ in range(len(following)):
        v, m, k = following[vertex]
        loop.append((vertex, m, k))
        vertex = v
        if vertex == start:
            break
    if vertex != start or len(loop) != len(following):
        return None
    return loop
