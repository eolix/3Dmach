# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Build Blender meshes from polygon data in bulk.

Uses ``foreach_set`` on flat arrays rather than ``from_pydata`` or per-element access, so importing scenes with
millions of polygons stays fast (ROADMAP Phase 2g performance target).
"""

__all__ = (
    "build_mesh",
)

import array

import bpy


def build_mesh(
        name,
        positions,
        faces,
        *,
        uv_layers=(),
        material_indices=None,
        sharp_edges=None,
        sharp_faces=None,
):
    """
    Create a mesh datablock.

    :arg positions: Sequence of ``(x, y, z)`` vertex positions.
    :arg faces: Sequence of polygons, each a sequence of vertex indices (3 or more).
    :arg uv_layers: Sequence of ``(name, uvs)`` where ``uvs`` holds one ``(u, v)`` per face corner, in face order.
    :arg material_indices: One material slot index per face, or None.
    :arg sharp_edges: Iterable of ``(v1, v2)`` vertex pairs to mark sharp, or None.
    :arg sharp_faces: One bool per face (True = flat shaded), or None to shade every face smooth.
    :return: The new ``bpy.types.Mesh``.
    """
    corner_count = sum(len(face) for face in faces)
    for layer_name, uvs in uv_layers:
        if len(uvs) != corner_count:
            raise ValueError("UV layer {!r} has {:d} corners, the mesh has {:d}".format(
                layer_name, len(uvs), corner_count))

    mesh = bpy.data.meshes.new(name)

    mesh.vertices.add(len(positions))
    mesh.vertices.foreach_set("co", array.array("f", (c for co in positions for c in co)))

    loop_starts = array.array("i")
    corner_verts = array.array("i")
    for face in faces:
        loop_starts.append(len(corner_verts))
        corner_verts.extend(face)
    mesh.loops.add(len(corner_verts))
    mesh.loops.foreach_set("vertex_index", corner_verts)
    mesh.polygons.add(len(faces))
    mesh.polygons.foreach_set("loop_start", loop_starts)

    for layer_name, uvs in uv_layers:
        layer = mesh.uv_layers.new(name=layer_name, do_init=False)
        layer.data.foreach_set("uv", array.array("f", (c for uv in uvs for c in uv)))

    if material_indices is not None:
        mesh.polygons.foreach_set("material_index", array.array("i", material_indices))

    mesh.update(calc_edges=True)

    if sharp_faces is None:
        sharp_faces = [False] * len(faces)
    mesh.shade_smooth()
    if any(sharp_faces):
        attribute = mesh.attributes.get("sharp_face") or mesh.attributes.new("sharp_face", 'BOOLEAN', 'FACE')
        attribute.data.foreach_set("value", [bool(v) for v in sharp_faces])

    if sharp_edges:
        sharp = {tuple(sorted(edge)) for edge in sharp_edges}
        edge_verts = array.array("i", [0]) * (len(mesh.edges) * 2)
        mesh.edges.foreach_get("vertices", edge_verts)
        values = [
            (min(edge_verts[i], edge_verts[i + 1]), max(edge_verts[i], edge_verts[i + 1])) in sharp
            for i in range(0, len(edge_verts), 2)
        ]
        attribute = mesh.attributes.get("sharp_edge") or mesh.attributes.new("sharp_edge", 'BOOLEAN', 'EDGE')
        attribute.data.foreach_set("value", values)

    return mesh
