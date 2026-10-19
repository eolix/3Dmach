# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
UV coordinates from the Unwrap UVW and UVW Map modifiers, without Blender.

**Unwrap UVW** stores its result per node in the derived object's modifier context (``0x2500`` > ``0x2512``,
``docs/format/overview.md`` §6.6). Worked out on the 140 Unwrap UVW contexts of the corpus (all parse to the
exact chunk length):

- ``0x0860``: u32 count, then 24 bytes per texture vertex: f32 u, v, w, u32 0, u32 0xFFFFFFFF, u32 (flags).
- ``0x0870``: u32 face count, then per face: u32 degree, u32 texture vertex index per corner, three u32 (the
  first counts up on 95 of 140 contexts: Guess, the face's index or material; the others are flags), u32
  geometry vertex index per corner. On the 89 contexts directly above an Editable Poly / Mesh, the geometry
  indices equal the base mesh's faces corner for corner.
- ``0x0330``: u32 count, f32[3] per geometry vertex (the modifier's input positions).

**UVW Map** generates coordinates from a gizmo. The gizmo's object-space placement is the modifier context
matrix (``ModifierRef.context_tm``, object to context space) followed by the inverse of the gizmo controller's
transform. On the corpus a freshly fitted gizmo sits at the centre of the input's bounding box with length /
width / height equal to its extents, and its rotation controller holds a half turn about Z (all 190 maps with an
identity context): this module takes that half turn as the gizmo's rest orientation, so a default planar map
runs U along +X and V along +Y. The projection formulas follow Max's documented behaviour (Guess: the seam
position of cylindrical / spherical maps and the box sides' orientation are not verified against real files).
"""

__all__ = (
    "MAP_TYPES",
    "parse_unwrap",
    "uvw_map",
)

import math
import struct

CHUNK_UNWRAP_TVERTS = 0x0860
CHUNK_UNWRAP_FACES = 0x0870
CHUNK_UNWRAP_GEOMETRY = 0x0330

MAP_TYPES = {0: "PLANAR", 1: "CYLINDRICAL", 2: "SPHERICAL", 3: "SHRINK_WRAP", 4: "BOX", 5: "FACE", 6: "XYZ"}


def parse_unwrap(data_chunk):
    """
    ``(texture vertices [(u, v)], faces [(tv indices, geometry indices)])`` from an Unwrap UVW context chunk
    (``0x2512``), or None when it doesn't have the expected layout.
    """
    tv_chunk = data_chunk.find(CHUNK_UNWRAP_TVERTS)
    face_chunk = data_chunk.find(CHUNK_UNWRAP_FACES)
    if tv_chunk is None or face_chunk is None or tv_chunk.is_container or face_chunk.is_container:
        return None
    raw = bytes(tv_chunk.data)
    if len(raw) < 4:
        return None
    count = struct.unpack_from("<I", raw)[0]
    if len(raw) != 4 + 24 * count:
        return None
    tverts = [struct.unpack_from("<2f", raw, 4 + 24 * i) for i in range(count)]
    raw = bytes(face_chunk.data)
    try:
        nfaces = struct.unpack_from("<I", raw)[0]
        pos = 4
        faces = []
        for _ in range(nfaces):
            degree = struct.unpack_from("<I", raw, pos)[0]
            if degree < 3 or degree > 100000:
                return None
            pos += 4
            tv = struct.unpack_from("<{:d}I".format(degree), raw, pos)
            pos += 4 * degree + 12
            geo = struct.unpack_from("<{:d}I".format(degree), raw, pos)
            pos += 4 * degree
            if any(i >= count for i in tv):
                return None
            faces.append((tv, geo))
    except struct.error:
        return None
    if pos != len(raw):
        return None
    return tverts, faces


def _apply(m, p):
    """4x4 (rows, column vectors) times a point."""
    return (m[0][0] * p[0] + m[0][1] * p[1] + m[0][2] * p[2] + m[0][3],
            m[1][0] * p[0] + m[1][1] * p[1] + m[1][2] * p[2] + m[1][3],
            m[2][0] * p[0] + m[2][1] * p[1] + m[2][2] * p[2] + m[2][3])


def _apply_dir(m, v):
    return (m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
            m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
            m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2])


# Projection axis (the modifier's "alignment") -> the gizmo axes used as (u, v, w).
_ALIGN = {0: (1, 2, 0), 1: (0, 2, 1), 2: (0, 1, 2)}


def uvw_map(corners, face_sizes, face_normals, params, to_gizmo):
    """
    UVs for the corners of a mesh.

    :arg corners: corner positions in object space (scene units), face after face.
    :arg face_sizes: number of corners of each face.
    :arg face_normals: one object-space normal per face (box mapping and cylinder caps).
    :arg params: UVW Map parameters (``map_type``, ``length``, ``width``, ``height``, ``u_tile``, ...,
       ``axis``).
    :arg to_gizmo: 4x4 matrix (rows) from object space to gizmo space.
    :return: list of ``(u, v)``, one per corner, or None for map types without a conversion.
    """
    kind = MAP_TYPES.get(params.get("map_type", 0), "PLANAR")
    if kind in {"FACE", "XYZ"}:
        return None
    width = params.get("width", 1.0) or 1.0
    length = params.get("length", 1.0) or 1.0
    height = params.get("height", 1.0) or 1.0
    iu, iv, iw = _ALIGN.get(params.get("axis", 2), (0, 1, 2))

    def local(p):
        g = _apply(to_gizmo, p)
        g = (-g[0], -g[1], g[2])        # The gizmo's rest orientation is a half turn about Z (see above).
        return g[iu], g[iv], g[iw]

    def local_dir(n):
        g = _apply_dir(to_gizmo, n)
        g = (-g[0], -g[1], g[2])
        return g[iu], g[iv], g[iw]

    uvs = []
    start = 0
    for size, normal in zip(face_sizes, face_normals):
        pts = [local(p) for p in corners[start:start + size]]
        start += size
        if kind == "PLANAR":
            uvs.extend((x / width + 0.5, y / length + 0.5) for x, y, _z in pts)
        elif kind == "BOX":
            nx, ny, nz = local_dir(normal)
            ax, ay, az = abs(nx), abs(ny), abs(nz)
            if az >= ax and az >= ay:
                sign = 1.0 if nz >= 0.0 else -1.0
                uvs.extend((sign * x / width + 0.5, y / length + 0.5) for x, y, _z in pts)
            elif ax >= ay:
                sign = 1.0 if nx >= 0.0 else -1.0
                uvs.extend((sign * y / length + 0.5, z / height + 0.5) for _x, y, z in pts)
            else:
                sign = -1.0 if ny >= 0.0 else 1.0
                uvs.extend((sign * x / width + 0.5, z / height + 0.5) for x, _y, z in pts)
        elif kind == "CYLINDRICAL":
            nx, ny, nz = local_dir(normal)
            if params.get("cap") and abs(nz) > max(abs(nx), abs(ny)):
                uvs.extend((x / width + 0.5, y / length + 0.5) for x, y, _z in pts)
                continue
            us = [math.atan2(y, x) / (2.0 * math.pi) + 0.5 for x, y, _z in pts]
            _unwrap_seam(us)
            uvs.extend((u, z / height + 0.5) for u, (_x, _y, z) in zip(us, pts))
        else:   # SPHERICAL, SHRINK_WRAP (approximated as spherical).
            us = [math.atan2(y, x) / (2.0 * math.pi) + 0.5 for x, y, _z in pts]
            _unwrap_seam(us)
            uvs.extend((u, math.atan2(z, math.hypot(x, y)) / math.pi + 0.5) for u, (x, y, z) in zip(us, pts))
    tiles = (params.get("u_tile", 1.0), params.get("v_tile", 1.0))
    flips = (-1.0 if params.get("u_flip") else 1.0, -1.0 if params.get("v_flip") else 1.0)
    if tiles != (1.0, 1.0) or flips != (1.0, 1.0):
        uvs = [(u * tiles[0] * flips[0], v * tiles[1] * flips[1]) for u, v in uvs]
    return uvs


def _unwrap_seam(us):
    """Keep a face that crosses the cylinder / sphere seam on one side of it."""
    if max(us) - min(us) > 0.5:
        for i, u in enumerate(us):
            if u < 0.5:
                us[i] = u + 1.0
