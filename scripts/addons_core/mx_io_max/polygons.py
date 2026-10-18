# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Editable Mesh triangles to the polygons Max shows.

An Editable Mesh stores triangles with per-edge visibility; a hidden edge is the diagonal of a polygon split into
triangles (``docs/format/overview.md`` §6.3: 2.84 million hidden edges, each shared by exactly two triangles that
both hide it). Triangles joined by hidden edges are merged back into one polygon when their outline is a single
simple loop; anything else (holes, non-manifold groups, very large groups) stays triangulated.

No Blender dependency. With NumPy (always there in Blender) the common case, two triangles sharing one hidden
edge, is merged vectorised; the rest goes through the general merge.
"""

__all__ = (
    "merge_triangles",
)

# Meshes with fewer triangles use the plain Python merge: it is faster than NumPy's per-call overhead there.
NUMPY_FROM = 5000


def merge_triangles(faces, visibility, channels=(), max_group=256):
    """
    Merge triangles along hidden edges.

    :arg faces: triangles ``(a, b, c)``.
    :arg visibility: per triangle, bits 0-2 = edge a-b, b-c, c-a visible.
    :arg channels: per map channel, its triangles (texture vertex indices, corner for corner with ``faces``).
    :return: ``(polygons, source triangle of each polygon, [polygons of each channel])``, or None when nothing
       was merged.
    """
    try:
        import numpy as np
    except ImportError:
        np = None
    if np is None or len(faces) < NUMPY_FROM:
        return _merge(faces, visibility, channels, max_group)
    return _merge_numpy(np, faces, visibility, channels, max_group)


def _merge_numpy(np, faces, visibility, channels, max_group):
    tris = np.asarray(faces, dtype=np.int64).reshape(-1, 3)
    vis = np.asarray(visibility, dtype=np.int64) & 7
    hidden = np.stack([((vis >> k) & 1) == 0 for k in range(3)], axis=1)       # (F, 3)
    hidden_count = hidden.sum(axis=1)
    hidden[hidden_count == 3] = False       # No visible edge: not merged (see _merge).
    hidden_count[hidden_count == 3] = 0
    if not hidden_count.any():
        return None
    count = len(tris)
    n = int(tris.max()) + 1
    tri_index, edge = np.nonzero(hidden)
    a = tris[tri_index, edge]
    b = tris[tri_index, (edge + 1) % 3]
    keys = np.minimum(a, b) * n + np.maximum(a, b)
    order = np.argsort(keys, kind='stable')
    keys, tri_index, edge = keys[order], tri_index[order], edge[order]
    # Pairs: a key hidden by exactly two triangles that hide nothing else, wound consistently.
    same_next = np.zeros(len(keys), dtype=bool)
    same_next[:-1] = keys[1:] == keys[:-1]
    first = np.nonzero(same_next)[0]
    second = first + 1
    ok = np.ones(len(first), dtype=bool)
    # Exactly two entries for the key.
    ok &= (second + 1 >= len(keys)) | (np.append(keys, -1)[np.minimum(second + 1, len(keys))] != keys[second])
    ok &= (first == 0) | (keys[np.maximum(first - 1, 0)] != keys[first])
    t1, k1, t2, k2 = tri_index[first], edge[first], tri_index[second], edge[second]
    ok &= (hidden_count[t1] == 1) & (hidden_count[t2] == 1) & (t1 != t2)
    p = tris[t1, (k1 + 1) % 3]
    ok &= tris[t2, k2] == p             # The partner runs the shared edge the other way.
    t1, k1, t2, k2 = t1[ok], k1[ok], t2[ok], k2[ok]
    corners_a = np.stack([(k1 + 1) % 3, (k1 + 2) % 3, k1], axis=1)
    quads = np.concatenate([tris[t1[:, None], corners_a], tris[t2, (k2 + 2) % 3][:, None]], axis=1)
    used = np.zeros(count, dtype=bool)
    used[t1] = True
    used[t2] = True
    polygons = quads.tolist()
    sources = t1.tolist()
    channel_polys = []
    channel_arrays = [np.asarray(chan, dtype=np.int64).reshape(-1, 3) for chan in channels]
    for chan in channel_arrays:
        channel_polys.append(np.concatenate([chan[t1[:, None], corners_a], chan[t2, (k2 + 2) % 3][:, None]],
                                            axis=1).tolist())
    rest = np.nonzero(~used)[0]
    if len(rest):
        rest_faces = tris[rest].tolist()
        rest_vis = vis[rest].tolist()
        rest_channels = [chan[rest].tolist() for chan in channel_arrays]
        merged = _merge(rest_faces, rest_vis, rest_channels, max_group) if hidden_count[rest].any() else None
        if merged is None:
            polygons.extend(rest_faces)
            sources.extend(rest.tolist())
            for out, chan in zip(channel_polys, rest_channels):
                out.extend(chan)
        else:
            more, more_sources, more_channels = merged
            polygons.extend(more)
            sources.extend(rest[more_sources].tolist())
            for out, chan in zip(channel_polys, more_channels):
                out.extend(chan)
    if not len(t1) and len(polygons) == count:
        return None
    return polygons, sources, channel_polys


def _merge(faces, visibility, channels=(), max_group=256):
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
        if vis & 7 == 7 or vis & 7 == 0:
            # All edges visible: a triangle of its own. None visible: meshes imported without edge visibility
            # (210,000 such triangles in Shadow-Study alone); merging them would only build huge groups.
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
