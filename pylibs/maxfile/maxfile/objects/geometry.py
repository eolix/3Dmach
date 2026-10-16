# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Mesh geometry: Editable Poly, PolyMeshObject and Editable Mesh (``docs/format/overview.md`` §6.1-6.3).

All chunk layouts here come from the overview and are unverified on real files. The decoders never trust a
count or an index: counts are capped to the data actually present, and faces that use out-of-range vertices are
dropped (with a warning), together with their material ID, smoothing group and map faces.
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

# Unverified (overview.md §6.2, §6.3, "To verify" #11): material IDs on disk are assumed to be 0-based, so this is
# added to get the 1-based IDs Max shows in its UI. If real files store them 1-based, set this to 0.
MATERIAL_ID_DISK_OFFSET = 1

CHUNK_MESH = 0x08FE             # Container holding the mesh, in Editable Poly / Mesh and primitive caches.

# Editable Poly. Unverified (overview.md §6.2).
POLY_VERTICES = 0x0100          # u32 count, then per vertex: u32 flags, f32[3]
POLY_FACES = 0x011A             # u32 count, then per face: u32 n, u32[n], u16 flags, optional fields by flag
POLY_FACE_ALT = 0x0118          # container per face: 0x0110 (u32 n, u32[n]) and 0x0130 (u16 material ID)
POLY_FACE_ALT_VERTS = 0x0110
POLY_FACE_ALT_MATID = 0x0130
POLY_FACES_ALT = 0x0310         # per face: u32 n, u32[n]
POLY_MAP_CHANNEL = 0x0124       # i32 channel number
POLY_MAP_VERTICES = 0x0128      # u32 count, f32[3] each
POLY_MAP_FACES = 0x012B         # per face: u32 n, u32[n]
# Optional per-face fields in 0x011A, in this order. Unverified (overview.md §6.2, "To verify" #7): order and meaning.
FACE_FLAG_UNKNOWN_2U16 = 0x01   # u16[2], meaning unknown
FACE_FLAG_MATERIAL = 0x08       # u16 material ID
FACE_FLAG_SMOOTHING = 0x10      # u32, likely smoothing groups
FACE_FLAG_TRIANGULATION = 0x20  # u32[2 * (n - 3)], likely the polygon's triangulation
_KNOWN_FACE_FLAGS = FACE_FLAG_UNKNOWN_2U16 | FACE_FLAG_MATERIAL | FACE_FLAG_SMOOTHING | FACE_FLAG_TRIANGULATION

# Editable Mesh. Unverified (overview.md §6.3).
MESH_VERTICES = 0x0914          # u32 count, f32[3] each
MESH_FACES = 0x0912             # u32 count, per face: u32[3] vertices, u32 smoothing, u16 flags, u16 material ID
MESH_MAP_CHANNEL = (0x0924, 0x0959)  # i32 channel number
MESH_MAP_VERTICES = 0x2394      # u32 count, f32[3] each (class 0x19 uses 0x0916)
MESH_MAP_FACES = 0x2396         # u32 count, u32[3] each (class 0x19 uses 0x0918)
MESH_MAP_VERTICES_0x19 = 0x0916
MESH_MAP_FACES_0x19 = 0x0918

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

    ``faces`` are polygons as vertex-index tuples in Max's corner order. ``material_ids`` are 1-based (see
    :data:`MATERIAL_ID_DISK_OFFSET`), ``smoothing_groups`` are 32-bit masks (0 = none stored). ``map_channels``
    is keyed by the channel number as stored: 0 vertex colour, 1+ UV channels, -1 / -2 illumination / alpha
    (Max's convention; unverified in files, "To verify" #8).
    """
    positions: list[tuple[float, float, float]]
    faces: list[tuple[int, ...]]
    material_ids: list[int]
    smoothing_groups: list[int]
    map_channels: dict[int, MapChannel]
    source: str                 # "editable_poly", "editable_mesh" or "primitive_cache".
    warnings: list[str] = dataclasses.field(default_factory=list)

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


# -----------------------------------------------------------------------------
# Editable Poly (§6.2)

def _poly_faces_011a(chunk, warnings):
    data = chunk.data
    faces, material_ids, smoothing = [], [], []
    if len(data) < 4:
        warnings.append("face chunk 0x011A has no count")
        return faces, material_ids, smoothing
    (count,) = _U32.unpack_from(data, 0)
    offset = 4
    unknown_flags = 0
    size = len(data)
    # Unverified (overview.md §6.2): u32 n, u32[n] vertices, u16 flags, then the optional fields in flag order.
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
            if flags & FACE_FLAG_UNKNOWN_2U16:
                offset += 4
            if flags & FACE_FLAG_MATERIAL:
                (material,) = _U16.unpack_from(data, offset)
                offset += 2
            if flags & FACE_FLAG_SMOOTHING:
                (group,) = _U32.unpack_from(data, offset)
                offset += 4
            if flags & FACE_FLAG_TRIANGULATION:
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
    return faces, material_ids, smoothing


def _poly_faces_0118(chunks, warnings):
    faces, material_ids = [], []
    for chunk in chunks:
        verts = chunk.find(POLY_FACE_ALT_VERTS)
        if verts is None:
            warnings.append("face chunk 0x0118 without 0x0110 vertices; skipped")
            continue
        found, _ = _polygons(verts.data, 0, 1, "face chunk 0x0110", warnings)
        if not found:
            continue
        faces.append(found[0])
        mat = chunk.find(POLY_FACE_ALT_MATID)
        material = _U16.unpack_from(mat.data, 0)[0] if mat is not None and mat.payload_size >= 2 else 0
        material_ids.append(material + MATERIAL_ID_DISK_OFFSET)
    return faces, material_ids, [0] * len(faces)


def read_poly_mesh(mesh_chunk, source="editable_poly") -> MeshData:
    """Read an Editable Poly ``0x08FE`` container (overview.md §6.2)."""
    warnings = []
    positions = []
    vertices = mesh_chunk.find(POLY_VERTICES)
    if vertices is None:
        warnings.append("no 0x0100 vertex chunk")
    else:
        positions = [(x, y, z) for _flags, x, y, z in _counted_records(vertices, _POLY_VERTEX, "vertex", warnings)]

    # Unverified (overview.md §6.2): 0x011A is the main face layout; 0x0310 and 0x0118 are alternatives.
    face_chunk = mesh_chunk.find(POLY_FACES)
    if face_chunk is not None:
        faces, material_ids, smoothing = _poly_faces_011a(face_chunk, warnings)
    elif mesh_chunk.find(POLY_FACES_ALT) is not None:
        faces, _ = _polygons(mesh_chunk.find(POLY_FACES_ALT).data, 0, None, "face chunk 0x0310", warnings)
        material_ids = [MATERIAL_ID_DISK_OFFSET] * len(faces)
        smoothing = [0] * len(faces)
    else:
        faces, material_ids, smoothing = _poly_faces_0118(mesh_chunk.find_all(POLY_FACE_ALT), warnings)
        if not faces:
            warnings.append("no face chunk (0x011A, 0x0310 or 0x0118)")

    # Unverified (overview.md §6.2): channels are matched to their vertices and faces by order of appearance.
    numbers = [_channel_number(c, warnings) for c in mesh_chunk.find_all(POLY_MAP_CHANNEL)]
    map_verts = [_vec3s(c, "map vertex", warnings) for c in mesh_chunk.find_all(POLY_MAP_VERTICES)]
    map_faces = [_polygons(c.data, 0, None, "map face chunk 0x012B", warnings)[0]
                 for c in mesh_chunk.find_all(POLY_MAP_FACES)]
    mesh = MeshData(positions, faces, material_ids, smoothing, {}, source, warnings)
    _attach_channels(mesh, numbers, map_verts, map_faces)
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
    faces, material_ids, smoothing = [], [], []
    face_chunk = mesh_chunk.find(MESH_FACES)
    if face_chunk is None:
        warnings.append("no 0x0912 face chunk")
    else:
        # Unverified (overview.md §6.3): u32[3] vertices, u32 smoothing groups, u16 flags, u16 material ID.
        for a, b, c, group, _flags, material in _counted_records(face_chunk, _MESH_FACE, "face", warnings):
            faces.append((a, b, c))
            smoothing.append(group)
            material_ids.append(material + MATERIAL_ID_DISK_OFFSET)

    numbers = [_channel_number(c, warnings) for c in mesh_chunk.children if c.type in MESH_MAP_CHANNEL]
    map_verts = [_vec3s(c, "map vertex", warnings) for c in mesh_chunk.find_all(map_vertex_type)]
    map_faces = [[tuple(f) for f in _counted_records(c, _TRI, "map face", warnings)]
                 for c in mesh_chunk.find_all(map_face_type)]
    mesh = MeshData(positions, faces, material_ids, smoothing, {}, source, warnings)
    _attach_channels(mesh, numbers, map_verts, map_faces)
    _validate(mesh)
    return mesh


# -----------------------------------------------------------------------------
# Channels and validation

def _attach_channels(mesh, numbers, map_verts, map_faces):
    count = max(len(numbers), len(map_verts), len(map_faces))
    if not (len(numbers) == len(map_verts) == len(map_faces)):
        mesh.warnings.append(
            "map data out of step: {:d} channel number(s), {:d} vertex and {:d} face block(s); unmatched blocks "
            "dropped".format(len(numbers), len(map_verts), len(map_faces)))
    for i in range(count):
        if i >= len(numbers) or i >= len(map_verts) or i >= len(map_faces) or numbers[i] is None:
            continue
        number = numbers[i]
        if number in mesh.map_channels:
            mesh.warnings.append("map channel {:d} appears twice; the second is dropped".format(number))
            continue
        mesh.map_channels[number] = MapChannel(map_verts[i], map_faces[i])


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


@decoder(0x192F60981BF8338D, 0x000000005D21369A, kind="geometry.mesh", name="Editable Poly / PolyMeshObject")
def editable_poly(obj, ctx):
    """Polygon mesh from the 0x08FE container (Editable Poly layout)."""
    mesh = read_poly_mesh(_mesh_chunk(obj), "editable_poly")
    _report(obj, ctx, mesh)
    return mesh


@decoder(0x00000000E44F10B3, kind="geometry.mesh", name="Editable Mesh")
def editable_mesh(obj, ctx):
    """Triangle mesh from the 0x08FE container (Editable Mesh layout)."""
    mesh = read_tri_mesh(_mesh_chunk(obj), "editable_mesh")
    _report(obj, ctx, mesh)
    return mesh
