# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Build Blender meshes from polygon data in bulk.

Everything goes through ``foreach_set`` on flat NumPy arrays (NumPy ships with Blender), and the per-corner work
(face sizes, smoothing groups to sharp edges, UV gathering) is vectorised, so importing scenes with millions of
polygons stays fast (ROADMAP Phase 2g performance target: 1M polygons in under 30 s).
"""

__all__ = (
    "MATERIAL_ID_ATTRIBUTE",
    "build_mesh",
    "corner_uvs",
    "face_material_ids",
    "sharp_from_groups",
)

import itertools

import bpy
import numpy as np

# Face attribute holding the Max material ID (1-based) of each face, for material slot assignment.
MATERIAL_ID_ATTRIBUTE = "mx_material_id"


def _face_arrays(faces):
    """``(sizes, starts, corner vertex indices)`` as int32 arrays."""
    count = len(faces)
    sizes = np.fromiter(map(len, faces), dtype=np.int32, count=count)
    total = int(sizes.sum())
    corners = np.fromiter(itertools.chain.from_iterable(faces), dtype=np.int32, count=total)
    starts = np.zeros(count, dtype=np.int32)
    if count > 1:
        np.cumsum(sizes[:-1], out=starts[1:])
    return sizes, starts, corners


def _edge_keys(corners, sizes, starts, vertex_count):
    """Per corner: the int64 key of the edge from this corner to the next one in its face."""
    face_of_corner = np.repeat(np.arange(len(sizes), dtype=np.int64), sizes)
    index = np.arange(len(corners), dtype=np.int64)
    last = starts[face_of_corner] + sizes[face_of_corner] - 1
    following = np.where(index == last, starts[face_of_corner], index + 1)
    a = corners.astype(np.int64)
    b = corners[following].astype(np.int64)
    return np.minimum(a, b) * vertex_count + np.maximum(a, b), face_of_corner


def sharp_from_groups(faces_or_arrays, groups, vertex_count):
    """
    Vectorised :func:`smoothing.sharp_from_smoothing_groups`: ``(sharp edge keys (sorted int64 array of
    min * vertex_count + max), sharp faces (bool array))``. An edge is sharp when a face using it shares no
    smoothing group with the first face (in face order) that uses it.
    """
    if isinstance(faces_or_arrays, tuple) and len(faces_or_arrays) == 3:
        sizes, starts, corners = faces_or_arrays
    else:
        sizes, starts, corners = _face_arrays(faces_or_arrays)
    g = np.asarray(groups, dtype=np.uint32)
    sharp_faces = g == 0
    if len(corners) == 0:
        return np.zeros(0, dtype=np.int64), sharp_faces
    keys, face_of_corner = _edge_keys(corners, sizes, starts, vertex_count)
    order = np.argsort(keys, kind='stable')
    ks = keys[order]
    gs = g[face_of_corner[order]]
    run_start = np.empty(len(ks), dtype=bool)
    run_start[0] = True
    run_start[1:] = ks[1:] != ks[:-1]
    first = np.maximum.accumulate(np.where(run_start, np.arange(len(ks)), 0))
    sharp = (~run_start) & ((gs & gs[first]) == 0)
    return np.unique(ks[sharp]), sharp_faces


def corner_uvs(map_vertices, map_faces, sizes):
    """
    Per-corner UVs (flat float32 array, u v u v ...) from a map channel, or None when its faces don't have the
    geometry's face sizes.
    """
    if len(map_faces) != len(sizes):
        return None
    msizes = np.fromiter(map(len, map_faces), dtype=np.int32, count=len(map_faces))
    if not np.array_equal(msizes, sizes):
        return None
    index = np.fromiter(itertools.chain.from_iterable(map_faces), dtype=np.int64, count=int(msizes.sum()))
    verts = np.asarray(map_vertices, dtype=np.float32)
    if verts.ndim != 2 or verts.shape[0] == 0 or (len(index) and index.max() >= verts.shape[0]):
        return None
    return np.ascontiguousarray(verts[index, :2]).reshape(-1)


def face_material_ids(mesh):
    """The faces' Max material IDs (int32 array), or None when the mesh has none."""
    attribute = mesh.attributes.get(MATERIAL_ID_ATTRIBUTE)
    if attribute is not None and attribute.domain == 'FACE' and len(attribute.data) == len(mesh.polygons):
        values = np.zeros(len(mesh.polygons), dtype=np.int32)
        attribute.data.foreach_get("value", values)
        return values
    legacy = mesh.get("mx_material_ids")
    if legacy is not None and len(legacy) == len(mesh.polygons):
        return np.asarray(list(legacy), dtype=np.int32)
    return None


def build_mesh(
        name,
        positions,
        faces,
        *,
        uv_layers=(),
        material_indices=None,
        sharp_edges=None,
        sharp_faces=None,
        edges=(),
        smoothing_groups=None,
        material_ids=None,
):
    """
    Create a mesh datablock.

    :arg positions: Sequence (or ``(n, 3)`` array) of vertex positions.
    :arg faces: Sequence of polygons, each a sequence of vertex indices (3 or more).
    :arg uv_layers: Sequence of ``(name, uvs)``: ``uvs`` holds one ``(u, v)`` per face corner in face order, or
       is a flat array ``u v u v ...``.
    :arg material_indices: One material slot index per face, or None.
    :arg sharp_edges: Iterable of ``(v1, v2)`` vertex pairs to mark sharp, or None.
    :arg sharp_faces: One bool per face (True = flat shaded), or None to shade every face smooth.
    :arg edges: Loose edges as ``(v1, v2)`` pairs (for wire meshes such as Lathe profiles).
    :arg smoothing_groups: One Max smoothing-group mask per face: sharp edges and faces are computed from them
       (vectorised) and added to ``sharp_edges`` / ``sharp_faces``.
    :arg material_ids: One Max material ID per face, stored in the :data:`MATERIAL_ID_ATTRIBUTE` attribute.
    :return: The new ``bpy.types.Mesh``.
    """
    sizes, starts, corners = _face_arrays(faces)
    corner_count = len(corners)
    flat_uvs = []
    for layer_name, uvs in uv_layers:
        flat = np.asarray(uvs, dtype=np.float32).reshape(-1)
        if len(flat) != corner_count * 2:
            raise ValueError("UV layer {!r} has {:d} corners, the mesh has {:d}".format(
                layer_name, len(flat) // 2, corner_count))
        flat_uvs.append((layer_name, flat))

    co = np.asarray(positions, dtype=np.float32).reshape(-1)
    vertex_count = len(co) // 3
    mesh = bpy.data.meshes.new(name)
    mesh.vertices.add(vertex_count)
    mesh.vertices.foreach_set("co", co)
    mesh.loops.add(corner_count)
    mesh.loops.foreach_set("vertex_index", corners)
    mesh.polygons.add(len(sizes))
    mesh.polygons.foreach_set("loop_start", starts)
    if edges:
        mesh.edges.add(len(edges))
        mesh.edges.foreach_set("vertices", np.asarray(edges, dtype=np.int32).reshape(-1))

    for layer_name, flat in flat_uvs:
        layer = mesh.uv_layers.new(name=layer_name, do_init=False)
        layer.data.foreach_set("uv", flat)

    if material_indices is not None:
        mesh.polygons.foreach_set("material_index", np.asarray(material_indices, dtype=np.int32))
    if material_ids is not None:
        attribute = mesh.attributes.new(MATERIAL_ID_ATTRIBUTE, 'INT', 'FACE')
        attribute.data.foreach_set("value", np.asarray(material_ids, dtype=np.int32))

    mesh.update(calc_edges=True)

    sharp_keys = None
    flat_faces = None
    if smoothing_groups is not None and len(smoothing_groups) == len(sizes):
        sharp_keys, flat_faces = sharp_from_groups((sizes, starts, corners), smoothing_groups, vertex_count)
    if sharp_faces is not None:
        given = np.asarray(sharp_faces, dtype=bool)
        flat_faces = given if flat_faces is None else (flat_faces | given)
    if sharp_edges:
        pairs = np.asarray([tuple(e) for e in sharp_edges], dtype=np.int64).reshape(-1, 2)
        extra = np.minimum(pairs[:, 0], pairs[:, 1]) * vertex_count + np.maximum(pairs[:, 0], pairs[:, 1])
        sharp_keys = extra if sharp_keys is None else np.union1d(sharp_keys, extra)

    mesh.shade_smooth()
    if flat_faces is not None and flat_faces.any():
        attribute = mesh.attributes.get("sharp_face") or mesh.attributes.new("sharp_face", 'BOOLEAN', 'FACE')
        attribute.data.foreach_set("value", flat_faces)
    if sharp_keys is not None and len(sharp_keys):
        edge_verts = np.zeros(len(mesh.edges) * 2, dtype=np.int32)
        mesh.edges.foreach_get("vertices", edge_verts)
        edge_verts = edge_verts.reshape(-1, 2).astype(np.int64)
        keys = np.minimum(edge_verts[:, 0], edge_verts[:, 1]) * vertex_count + np.maximum(
            edge_verts[:, 0], edge_verts[:, 1])
        attribute = mesh.attributes.get("sharp_edge") or mesh.attributes.new("sharp_edge", 'BOOLEAN', 'EDGE')
        attribute.data.foreach_set("value", np.isin(keys, sharp_keys))
    return mesh
