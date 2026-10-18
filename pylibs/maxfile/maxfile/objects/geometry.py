# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Mesh geometry: Editable Poly, PolyMeshObject and Editable Mesh (``docs/format/overview.md`` §6.2-6.3).

The layouts below were checked on every mesh of the local corpus (4,566 Editable Poly / PolyMeshObject meshes with
2,037,565 polygons, 5,694 Editable Mesh meshes with 4,382,904 triangles): all chunks are consumed exactly, no face
uses a vertex index out of range, and every map channel has one map face per face with the same corner count and
in-range map vertex indices (except 13 Editable Poly channels in one file, which the reader drops). The decoders
still never trust a count or an index: counts are capped to the data actually present, and faces that use
out-of-range vertices are dropped (with a warning), together with their material ID, smoothing group and map faces.
"""

__all__ = (
    "MATERIAL_ID_DISK_OFFSET",
    "MapChannel",
    "MeshData",
    "read_poly_mesh",
    "read_tri_mesh",
)

import dataclasses
import struct

from ..chunks import i32s
from ..errors import DecodeError
from ..registry import decoder

# Material IDs on disk are 0-based; Max shows them 1-based. Verified: in Editable Poly faces the material field is
# only written when it is non-zero (1,007,416 faces have it, never with the value 0; the other 1,030,149 faces are
# ID 0), and an Editable Mesh converted from a Box (Scenes/SubDivSurfaces/Meshsmooth-Hammer.max) has IDs 0-5 for
# the box's six sides, which Max numbers 1-6.
MATERIAL_ID_DISK_OFFSET = 1

CHUNK_MESH = 0x08FE             # Container holding the mesh in Editable Poly / Mesh objects.

# Editable Poly (verified).
POLY_VERTICES = 0x0100          # u32 count, then per vertex: u32 flags, f32[3]
POLY_EDGES = 0x010A             # u32 count, then per edge: u32 flags, u32 v1, u32 v2
POLY_FACES = 0x011A             # u32 count, then per face: u32 n, u32[n], u16 flags, optional fields by flag
POLY_MAP_COUNT = 0x0120         # u32: number of map channels (highest channel + 1)
POLY_MAP_CHANNEL = 0x0124       # i32 channel number; the next 0x0128 / 0x012B belong to it
POLY_MAP_VERTICES = 0x0128      # u32 count, f32[3] each
POLY_MAP_FACES = 0x012B         # per face: u32 n, u32[n] map vertex indices (no count)
# Optional per-face fields in 0x011A, in this order (verified: these sizes consume every face chunk exactly).
FACE_FLAG_UNKNOWN = 0x01        # u32, meaning unknown (values 1, 2, 4, 5 and large ones)
FACE_FLAG_MATERIAL = 0x08       # u16 material ID, 0-based; only present when non-zero
FACE_FLAG_SMOOTHING = 0x10      # u32 smoothing groups; only present when non-zero
# u32[2 * (n - 3)]: the polygon's triangulation diagonals (corner indices < n); present exactly on faces with more
# than three corners.
FACE_FLAG_DIAGONALS = 0x20
_KNOWN_FACE_FLAGS = FACE_FLAG_UNKNOWN | FACE_FLAG_MATERIAL | FACE_FLAG_SMOOTHING | FACE_FLAG_DIAGONALS

# Editable Mesh (verified).
MESH_VERTICES = 0x0914          # u32 count, f32[3] each
MESH_FACES = 0x0912             # u32 count, per face: u32[3] vertices, u32 smoothing, u16 flags, u16 material ID
MESH_MAP_CHANNEL = 0x0959       # i32 channel number; the next 0x2394 / 0x2396 belong to it
MESH_MAP_VERTICES = 0x2394      # u32 count, f32[3] each
MESH_MAP_FACES = 0x2396         # u32 count, u32[3] each
# Face flags bits 0-2: edge a-b, b-c, c-a visible (unset = a hidden diagonal of a polygon split into triangles).
TRI_EDGE_VISIBILITY_MASK = 0x07
# Kept for older callers; not chunk types of their own in real files.
MESH_MAP_VERTICES_0x19 = MESH_MAP_VERTICES
MESH_MAP_FACES_0x19 = MESH_MAP_FACES

_U32 = struct.Struct("<I")
_U16 = struct.Struct("<H")
_VEC3 = struct.Struct("<3f")
_POLY_VERTEX = struct.Struct("<I3f")
_MESH_FACE = struct.Struct("<3IIHH")
_TRI = struct.Struct("<3I")


@dataclasses.dataclass
class MapChannel:
    """One map channel: its own vertices, and one face per geometry face with the same number of corners."""
    vertices: list[tuple[float, float, float]]
    faces: list[tuple[int, ...]]


@dataclasses.dataclass
class MeshData:
    """
    A polygon mesh as stored by Max.

    ``faces`` are polygons as vertex-index tuples in Max's corner order. ``material_ids`` are 1-based (the IDs Max
    shows, see :data:`MATERIAL_ID_DISK_OFFSET`), ``smoothing_groups`` are 32-bit masks (0 = none). ``map_channels``
    is keyed by the channel number as stored: 0 vertex colour, 1+ texture channels, -1 / -2 illumination / alpha
    (the corpus has channels -2 to 3; numbering is Max's documented convention, the meaning of 0 / -1 / -2 isn't
    checked against files).
    """
    positions: list[tuple[float, float, float]]
    faces: list[tuple[int, ...]]
    material_ids: list[int]
    smoothing_groups: list[int]
    map_channels: dict[int, MapChannel]
    source: str                 # "editable_poly" or "editable_mesh".
    warnings: list[str] = dataclasses.field(default_factory=list)
    edge_visibility: list[int] | None = None
    """Triangle meshes only: per face, bits 0-2 = edge a-b, b-c, c-a visible. Hidden edges are the diagonals of
    the polygons Max shows (e.g. a box side is two triangles sharing one hidden edge)."""

    def stats(self) -> dict:
        """Counts for reports: vertices, faces, corners, channel numbers, distinct material IDs."""
        return {
            "vertices": len(self.positions),
            "faces": len(self.faces),
            "corners": sum(len(f) for f in self.faces),
            "channels": sorted(self.map_channels),
            "material_ids": sorted(set(self.material_ids)),
            "smoothing": any(self.smoothing_groups),
        }

    def bounds(self):
        """``((min x, y, z), (max x, y, z))`` of the vertex positions, or None for an empty mesh."""
        if not self.positions:
            return None
        xs, ys, zs = zip(*self.positions)
        return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


# -----------------------------------------------------------------------------
# Low-level readers. Each returns what it could read and appends problems to ``warnings``.

def _counted_records(chunk, record: struct.Struct, what, warnings):
    """``u32 count`` followed by fixed-size records."""
    data = chunk.data
    if len(data) < 4:
        warnings.append("{:s} chunk 0x{:04X} has no count".format(what, chunk.type))
        return []
    (count,) = _U32.unpack_from(data, 0)
    available = (len(data) - 4) // record.size
    if count > available:
        warnings.append("{:s} chunk 0x{:04X} claims {:d} entries, only {:d} fit".format(
            what, chunk.type, count, available))
        count = available
    return list(record.iter_unpack(data[4:4 + count * record.size]))


def _polygons(data, offset, count, what, warnings):
    """``count`` (None = until the end) polygons stored as ``u32 n, u32[n]``; returns ``(faces, end_offset)``."""
    faces = []
    size = len(data)
    while (count is None and offset < size) or (count is not None and len(faces) < count):
        if offset + 4 > size:
            warnings.append("{:s}: data ends after {:d} face(s)".format(what, len(faces)))
            break
        (n,) = _U32.unpack_from(data, offset)
        if offset + 4 + 4 * n > size:
            warnings.append("{:s}: face {:d} claims {:d} corners, past the end of the data".format(
                what, len(faces), n))
            break
        faces.append(struct.unpack_from("<{:d}I".format(n), data, offset + 4))
        offset += 4 + 4 * n
    return faces, offset


def _vec3s(chunk, what, warnings):
    return [tuple(v) for v in _counted_records(chunk, _VEC3, what, warnings)]


def _channel_number(chunk, warnings):
    values = i32s(chunk.data)
    if not values:
        warnings.append("map channel chunk 0x{:04X} is empty".format(chunk.type))
        return None
    return values[0]


def _channels(mesh_chunk, number_type, vertex_type, face_type, read_faces, warnings):
    """Map channels: each channel-number chunk is followed by its vertex and face chunks (verified order)."""
    found = []      # [number, vertices, faces]
    for child in mesh_chunk.children:
        if child.type == number_type:
            found.append([_channel_number(child, warnings), None, None])
        elif child.type in (vertex_type, face_type):
            if not found:
                warnings.append("map chunk 0x{:04X} before any channel number; dropped".format(child.type))
                continue
            slot = 1 if child.type == vertex_type else 2
            if found[-1][slot] is not None:
                warnings.append("map channel {!s}: second 0x{:04X} chunk dropped".format(found[-1][0], child.type))
                continue
            found[-1][slot] = _vec3s(child, "map vertex", warnings) if slot == 1 else read_faces(child)
    channels = {}
    for number, verts, faces in found:
        if number is None:
            continue
        if verts is None or faces is None:
            if verts is not None or faces is not None:
                warnings.append("map channel {:d} has vertices or faces missing; dropped".format(number))
            continue
        if number in channels:
            warnings.append("map channel {:d} appears twice; the second is dropped".format(number))
            continue
        channels[number] = MapChannel(verts, faces)
    return channels


# -----------------------------------------------------------------------------
# Editable Poly (§6.2)

def _poly_faces(chunk, warnings):
    data = chunk.data
    faces, material_ids, smoothing = [], [], []
    if len(data) < 4:
        warnings.append("face chunk 0x011A has no count")
        return faces, material_ids, smoothing
    (count,) = _U32.unpack_from(data, 0)
    offset = 4
    unknown_flags = 0
    size = len(data)
    while len(faces) < count:
        try:
            (n,) = _U32.unpack_from(data, offset)
            if offset + 4 + 4 * n + 2 > size:
                raise struct.error("face past the end")
            verts = struct.unpack_from("<{:d}I".format(n), data, offset + 4)
            offset += 4 + 4 * n
            (flags,) = _U16.unpack_from(data, offset)
            offset += 2
            unknown_flags |= flags & ~_KNOWN_FACE_FLAGS
            material = 0
            group = 0
            if flags & FACE_FLAG_UNKNOWN:
                offset += 4
            if flags & FACE_FLAG_MATERIAL:
                (material,) = _U16.unpack_from(data, offset)
                offset += 2
            if flags & FACE_FLAG_SMOOTHING:
                (group,) = _U32.unpack_from(data, offset)
                offset += 4
            if flags & FACE_FLAG_DIAGONALS:
                offset += 8 * max(n - 3, 0)
            if offset > size:
                raise struct.error("face fields past the end")
        except struct.error:
            warnings.append("face chunk 0x011A: data ends inside face {:d} of {:d}".format(len(faces), count))
            break
        faces.append(verts)
        material_ids.append(material + MATERIAL_ID_DISK_OFFSET)
        smoothing.append(group)
    if unknown_flags:
        warnings.append("face chunk 0x011A: unknown face flag bits 0x{:04X} (assumed to carry no data)".format(
            unknown_flags))
    if offset != size and len(faces) == count:
        warnings.append("face chunk 0x011A: {:d} byte(s) left after the last face".format(size - offset))
    return faces, material_ids, smoothing


def read_poly_mesh(mesh_chunk, source="editable_poly") -> MeshData:
    """Read an Editable Poly ``0x08FE`` container (overview.md §6.2)."""
    warnings = []
    positions = []
    vertices = mesh_chunk.find(POLY_VERTICES)
    if vertices is None:
        warnings.append("no 0x0100 vertex chunk")
    else:
        positions = [(x, y, z) for _flags, x, y, z in _counted_records(vertices, _POLY_VERTEX, "vertex", warnings)]
    face_chunk = mesh_chunk.find(POLY_FACES)
    if face_chunk is None:
        warnings.append("no 0x011A face chunk")
        faces, material_ids, smoothing = [], [], []
    else:
        faces, material_ids, smoothing = _poly_faces(face_chunk, warnings)
    channels = _channels(mesh_chunk, POLY_MAP_CHANNEL, POLY_MAP_VERTICES, POLY_MAP_FACES,
                         lambda c: _polygons(c.data, 0, None, "map face chunk 0x012B", warnings)[0], warnings)
    mesh = MeshData(positions, faces, material_ids, smoothing, channels, source, warnings)
    _validate(mesh)
    return mesh


# -----------------------------------------------------------------------------
# Editable Mesh (§6.3)

def read_tri_mesh(mesh_chunk, source="editable_mesh", map_vertex_type=MESH_MAP_VERTICES,
                  map_face_type=MESH_MAP_FACES) -> MeshData:
    """Read an Editable Mesh ``0x08FE`` container (overview.md §6.3)."""
    warnings = []
    vertices = mesh_chunk.find(MESH_VERTICES)
    positions = _vec3s(vertices, "vertex", warnings) if vertices is not None else []
    if vertices is None:
        warnings.append("no 0x0914 vertex chunk")
    faces, material_ids, smoothing, visibility = [], [], [], []
    face_chunk = mesh_chunk.find(MESH_FACES)
    if face_chunk is None:
        warnings.append("no 0x0912 face chunk")
    else:
        for a, b, c, group, flags, material in _counted_records(face_chunk, _MESH_FACE, "face", warnings):
            faces.append((a, b, c))
            smoothing.append(group)
            material_ids.append(material + MATERIAL_ID_DISK_OFFSET)
            visibility.append(flags & TRI_EDGE_VISIBILITY_MASK)
    channels = _channels(mesh_chunk, MESH_MAP_CHANNEL, map_vertex_type, map_face_type,
                         lambda c: [tuple(f) for f in _counted_records(c, _TRI, "map face", warnings)], warnings)
    mesh = MeshData(positions, faces, material_ids, smoothing, channels, source, warnings, visibility)
    _validate(mesh)
    return mesh


# -----------------------------------------------------------------------------
# Validation

def _validate(mesh):
    """Drop faces with bad vertex indices, and channels that don't line up with the faces."""
    nverts = len(mesh.positions)
    keep = [len(f) >= 3 and all(0 <= v < nverts for v in f) for f in mesh.faces]
    dropped = keep.count(False)

    for number, channel in list(mesh.map_channels.items()):
        problem = None
        if len(channel.faces) != len(mesh.faces):
            problem = "{:d} faces, the mesh has {:d}".format(len(channel.faces), len(mesh.faces))
        else:
            nmap = len(channel.vertices)
            for i, (face, map_face) in enumerate(zip(mesh.faces, channel.faces)):
                if not keep[i]:
                    continue    # Dropped below anyway (the corpus has a few 0-corner faces with map faces).
                if len(face) != len(map_face):
                    problem = "face {:d} has {:d} corners, the mesh face {:d}".format(i, len(map_face), len(face))
                    break
                if keep[i] and not all(0 <= v < nmap for v in map_face):
                    problem = "face {:d} uses a map vertex out of range".format(i)
                    break
        if problem:
            mesh.warnings.append("map channel {:d} dropped: {:s}".format(number, problem))
            del mesh.map_channels[number]

    if dropped:
        mesh.warnings.append("{:d} face(s) dropped: fewer than 3 corners or vertex index out of range".format(dropped))
        mesh.faces = [f for f, k in zip(mesh.faces, keep) if k]
        mesh.material_ids = [m for m, k in zip(mesh.material_ids, keep) if k]
        mesh.smoothing_groups = [s for s, k in zip(mesh.smoothing_groups, keep) if k]
        if mesh.edge_visibility is not None:
            mesh.edge_visibility = [e for e, k in zip(mesh.edge_visibility, keep) if k]
        for channel in mesh.map_channels.values():
            channel.faces = [f for f, k in zip(channel.faces, keep) if k]


def _report(obj, ctx, mesh):
    for message in mesh.warnings:
        ctx.warn("object {:d} ({:s}): {:s}".format(obj.index, obj.class_label(), message))


def _mesh_chunk(obj):
    chunk = obj.chunk.find(CHUNK_MESH)
    if chunk is None or not chunk.is_container:
        raise DecodeError("no 0x{:04X} mesh container".format(CHUNK_MESH))
    return chunk


@decoder(0x192F60981BF8338D, 0x000000005D21369A, kind="geometry.mesh", name="Editable Poly / PolyMeshObject",
         superclass_id=0x10, verified=True)
def editable_poly(obj, ctx):
    """Polygon mesh from the 0x08FE container (Editable Poly layout)."""
    mesh = read_poly_mesh(_mesh_chunk(obj), "editable_poly")
    _report(obj, ctx, mesh)
    return mesh


@decoder(0x00000000E44F10B3, kind="geometry.mesh", name="Editable Mesh", superclass_id=0x10, verified=True)
def editable_mesh(obj, ctx):
    """Triangle mesh from the 0x08FE container (Editable Mesh layout)."""
    mesh = read_tri_mesh(_mesh_chunk(obj), "editable_mesh")
    _report(obj, ctx, mesh)
    return mesh
