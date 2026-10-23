# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Editable Poly objects: the inverse of :func:`maxfile.objects.geometry` for ``0x08FE`` polygon meshes
(``docs/format/overview.md`` §6.2), plus the object-level chunks, parameter block and Master Point Controller
every Editable Poly of the 2015 corpus files has (299 objects).

Derived data written like Max does for a freshly built mesh (checked on the corpus):

- edges (0x010A): every polygon side once, created in polygon order, first-use direction (the edge list of 85 of
  299 corpus meshes is exactly this; the others were edited after building);
- vertex adjacency (0x0310): per vertex the incident edges, then the incident polygons, each list ascending
  (exactly reproduced on 131 of the 299 corpus meshes, all the unedited ones);
- triangulation diagonals (face flag 0x20) for polygons with more than three corners: a fan from corner 0.
"""

__all__ = ("editable_poly", "derive_edges", "vertex_adjacency")

import struct

from . import classes
from .chunks import cont, f32, i32, leaf, u32, u32_array, f32_array, u8
from .graph import MaxObject
from .pblock import FIRST_WORD, R, pb2


def derive_edges(polygons):
    """``[(v1, v2)]``: every polygon side once, in polygon order, direction of first use."""
    seen = set()
    edges = []
    for poly in polygons:
        n = len(poly)
        for j in range(n):
            a, b = poly[j], poly[(j + 1) % n]
            key = (a, b) if a < b else (b, a)
            if key not in seen:
                seen.add(key)
                edges.append((a, b))
    return edges


def vertex_adjacency(vertex_count, edges, polygons):
    """The 0x0310 payload values: per vertex ``n, edges..., m, polygons...`` (ascending)."""
    ve = [[] for _ in range(vertex_count)]
    vf = [[] for _ in range(vertex_count)]
    for i, (a, b) in enumerate(edges):
        ve[a].append(i)
        if b != a:
            ve[b].append(i)
    for i, poly in enumerate(polygons):
        for v in sorted(set(poly)):
            vf[v].append(i)
    out = []
    for v in range(vertex_count):
        out.append(len(ve[v]))
        out.extend(ve[v])
        out.append(len(vf[v]))
        out.extend(vf[v])
    return out


def _mesh_chunk(mesh):
    positions = mesh.positions
    polygons = [list(p) for p in mesh.polygons]
    for poly in polygons:
        if len(poly) < 3:
            raise ValueError("polygon with fewer than 3 corners: {!r}".format(poly))
    nv = len(positions)
    edges = derive_edges(polygons)
    mat_ids = mesh.material_ids
    smoothing = mesh.smoothing_groups

    verts = [u32(nv)]
    flat = []
    for p in positions:
        flat.extend(p)
    # Vertex flags: 0 on 127,026 of 146,163 corpus vertices.
    verts.append(b"".join(u32(0) + f32(x, y, z) for x, y, z in positions))

    edge_values = [len(edges)]
    for a, b in edges:
        edge_values.extend((0, a, b))      # Edge flags: 0 on 95,594 corpus edges (0x01000000 on 140,982; unknown).

    faces = [u32(len(polygons))]
    for i, poly in enumerate(polygons):
        n = len(poly)
        flags = 0
        tail = b""
        disk_id = (mat_ids[i] - 1) if mat_ids is not None else 0
        if disk_id:                         # Written only when non-zero (overview.md §6.2), 0-based on disk.
            flags |= 0x08
            tail += struct.pack("<H", disk_id & 0xFFFF)
        group = (smoothing[i] if smoothing is not None else 0) & 0xFFFFFFFF
        if group:
            flags |= 0x10
            tail += u32(group)
        if n > 3:
            flags |= 0x20
            tail += u32_array(v for k in range(1, n - 2) for v in (0, k + 1))     # Fan diagonals 0-2, 0-3, ...
        faces.append(u32(n) + u32_array(poly) + struct.pack("<H", flags) + tail)

    channels = sorted(mesh.map_channels.items())
    children = [
        # Corpus (299 Editable Polys of the 2015 files): 0x0150 = 0x00080003 (most common), 0x0140 = 0x40 (134),
        # 0x0130 = 0 (190).
        leaf(0x0150, u32(0x00080003)),
        leaf(0x0140, u32(0x40)),
        leaf(0x0130, u32(0)),
        leaf(0x0100, b"".join(verts)),
        leaf(0x010A, u32_array(edge_values)),
        leaf(0x011A, b"".join(faces)),
        leaf(0x0120, u32((max(c for c, _ in channels) + 1) if channels else 2)),     # 2 on all 193 sampled
    ]
    for number, channel in channels:
        if len(channel.faces) != len(polygons):
            raise ValueError("map channel {:d} has {:d} faces for {:d} polygons".format(
                number, len(channel.faces), len(polygons)))
        mverts = [u32(len(channel.vertices))]
        mflat = []
        for v in channel.vertices:
            mflat.extend((tuple(v) + (0.0, 0.0, 0.0))[:3])
        mverts.append(f32_array(mflat))
        mfaces = []
        for face, poly in zip(channel.faces, polygons):
            if len(face) != len(poly):
                raise ValueError("map face corner count differs from its polygon")
            mfaces.append(u32(len(face)) + u32_array(face))
        children += [leaf(0x0124, i32(number)), leaf(0x0128, b"".join(mverts)), leaf(0x012B, b"".join(mfaces))]
    children += [
        leaf(0x0310, u32_array(vertex_adjacency(nv, edges, polygons))),
        leaf(0x0320, u32(10)),              # 10 on 77 of 193 sampled (12: 46, 0: 70); meaning unknown.
    ]
    return cont(0x08FE, *children)


def editable_poly(mesh) -> MaxObject:
    obj = MaxObject(classes.EDITABLE_POLY, num_refs=2, label="Editable Poly")
    obj.ref(0, _edit_poly_params(obj))
    obj.ref(1, MaxObject(classes.MASTER_POINT_CONTROLLER, label="Master Point Controller"))
    obj.refs[1].chunks = [leaf(0x2535, u32(0))]             # 231 of 241 sampled: only 0x2535 = 0.
    forever = u32(0x80000000, 0x7FFFFFFF)
    obj.chunks = [
        # Corpus, all 193 sampled Editable Polys (2015): object-level chunks and their values.
        cont(0x4039, leaf(0x0000, u32(0)), leaf(0x0001, u32(0))),
        leaf(0x403A),
        leaf(0x4038, u32(0)),
        leaf(0x0900, forever * 5 + u32(0xFFFFFFFF)),        # Validity intervals.
        _mesh_chunk(mesh),
        cont(0x0906, *[leaf(t, v) for t, v in (
            (0x300D, u32(5)), (0x300E, u32(2)), (0x300F, u32(2)), (0x3014, u32(2)), (0x3015, u32(3)),
            (0x3010, f32(10.0)), (0x3017, f32(20.0)), (0x3012, f32(20.0)), (0x3013, u32(0)), (0x3016, u32(1)),
            (0x301C, u32(0)), (0x3019, u32(0)), (0x301A, u32(2)), (0x301D, u32(20000)), (0x301B, u32(0)),
            (0x301E, u32(1)))]),
        leaf(0x0908, u8(0)),
        leaf(0x090A, u8(1)),
        leaf(0x090C, u8(0)),
    ]
    return obj


def _edit_poly_params(owner):
    """The Editable Poly parameter block (block 0): the dominant records of the 97 sampled 2015 blocks."""
    from ._epoly_params import RECORDS, ROLLOUTS
    block = pb2(owner, FIRST_WORD["Editable Poly"], 0, [R(*r) for r in RECORDS], rollouts=ROLLOUTS,
                num_refs=1)
    return block
