# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Experimental ``.max`` writer (pure Python, no Blender).

Takes a neutral scene model (:mod:`maxfile.writer.model`) and writes a Compound File laid out like the files Max
2015 saves; see ``docs/design/max-writer.md`` for what is written and why::

    from maxfile.writer import Scene, Node, EditablePoly, StandardMaterial, write

    scene = Scene(unit="centimeters")
    scene.add(Node("Box001", mesh=EditablePoly(positions, polygons), material=StandardMaterial("Red")))
    write(scene, "box.max")

Every byte is generated from code: layouts are the inverse of what :mod:`maxfile` reads, values the reader
doesn't decode are the dominant ones of the corpus files of the targeted version.
"""

__all__ = (
    "write", "to_bytes", "WriterOptions", "Scene", "Node", "Transform", "EditablePoly", "MapChannel", "Bitmap",
    "StandardMaterial", "PhysicalMaterial", "MultiSubMaterial", "TARGET_RELEASE", "DLL_HEADER",
)

import dataclasses

from . import classes
from .cfb import write_compound_file
from .chunks import leaf, u32
from .graph import SceneGraph
from .materials import MaterialWriter
from .model import (
    Bitmap, EditablePoly, MapChannel, MultiSubMaterial, Node, PhysicalMaterial, Scene, StandardMaterial, Transform,
)
from .nodes import dummy_object, node_object
from .poly import editable_poly
from .skeleton import build_skeleton
from . import streams

# Max 2015 (docs/design/max-writer.md): release 16900, build 411 (the most common build of the 2015 corpus files,
# 76 of 305; "Build: 17.0.411.0" in their summary information).
TARGET_RELEASE = 16900
DLL_HEADER = (TARGET_RELEASE << 16) | 411
SCENE_CONTAINER_TYPE = 0x2020       # The Scene stream's top container in all 305 files of 2015.
VERSION_TEXT = "16.90"
BUILD_TEXT = "17.0.411.0"


@dataclasses.dataclass
class WriterOptions:
    """``skeleton``: ``"full"`` (like a fresh Max scene) or ``"lean"`` (diagnostic, see :mod:`.skeleton`)."""
    skeleton: str = "full"
    comments: str = "Written by 3Dmach (experimental .max writer)"


def _ordered_nodes(scene):
    """Nodes with parents before children (pre-order), keeping the model's order among siblings."""
    in_scene = {id(n) for n in scene.nodes}
    children = {}
    roots = []
    for node in scene.nodes:
        parent = node.parent if node.parent is not None and id(node.parent) in in_scene else None
        if parent is None:
            roots.append(node)
        else:
            children.setdefault(id(parent), []).append(node)
    order = []
    stack = list(reversed(roots))
    seen = set()
    while stack:
        node = stack.pop()
        if id(node) in seen:
            raise ValueError("node hierarchy has a cycle at {!r}".format(node.name))
        seen.add(id(node))
        order.append(node)
        stack.extend(reversed(children.get(id(node), [])))
    if len(order) != len(scene.nodes):
        raise ValueError("node hierarchy has a cycle")
    return order


def _build(scene: Scene, options: WriterOptions):
    materials = MaterialWriter()
    nodes = _ordered_nodes(scene)
    skel = build_skeleton(scene, materials, options.skeleton, next_handle=len(nodes) + 1)
    node_objs = {}
    geometry = {}
    scene_materials = []
    for handle, node in enumerate(nodes, start=1):
        if node.mesh is not None:
            key = id(node.mesh)
            if key not in geometry:         # Nodes sharing a mesh share the object (instances).
                geometry[key] = editable_poly(node.mesh)
            obj = geometry[key]
        else:
            obj = dummy_object(node.dummy_size)
        material = materials.build(node.material)
        if material is not None and all(m is not material for m in scene_materials):
            scene_materials.append(material)
        parent = node_objs[id(node.parent)] if id(node.parent) in node_objs else skel.root
        node_obj = node_object(node, handle, parent, obj, material, skel.layer)
        node_objs[id(node)] = node_obj
        skel.root.followers.append(node_obj)
    # MtlBaseLib: the scene's materials (dense references; 0x4110 = their count).
    lib = skel.mtl_lib
    lib.num_refs = len(scene_materials)
    for i, m in enumerate(scene_materials):
        lib.ref(i, m)
    lib.chunks = [leaf(0x4110, u32(len(scene_materials)))]
    graph = SceneGraph(skel.scene)
    return graph, materials, nodes


def _document_parts(scene, graph, materials, nodes):
    verts = sum(len(n.mesh.positions) for n in nodes if n.mesh is not None)
    faces = sum(sum(len(p) - 2 for p in n.mesh.polygons) for n in nodes if n.mesh is not None)
    geometry = sum(1 for n in nodes if n.mesh is not None)
    helpers = len(nodes) - geometry
    names = []

    def collect(material):
        if material is None:
            return
        if material.name not in names:
            names.append(material.name)
        for sub in getattr(material, "materials", None) or ():
            collect(sub)

    for node in nodes:
        collect(node.material)
    return [
        ("General", ["3ds Max Version: " + VERSION_TEXT, "Uncompressed", "Build: " + BUILD_TEXT,
                     "Saved As Version: " + VERSION_TEXT]),
        ("Mesh Totals", ["Vertices: {:d}".format(verts), "Faces: {:d}".format(faces)]),
        ("Scene Totals", ["Objects: {:d}".format(geometry), "Shapes: 0", "Lights: 0", "Cameras: 0",
                          "Helpers: {:d}".format(helpers), "Space Warps: 0", "Total: {:d}".format(len(nodes))]),
        ("External Dependencies", [path for _guid, path in materials.assets]),
        ("Objects", [n.name for n in nodes]),
        ("Materials", names),
        ("Used Plug-Ins", [dll[0] for dll in graph.dlls]),
    ]


def to_bytes(scene: Scene, options: WriterOptions | None = None) -> bytes:
    """The ``.max`` file for ``scene``, as bytes."""
    options = options or WriterOptions()
    graph, materials, nodes = _build(scene, options)
    scene_stream = graph.scene_stream(SCENE_CONTAINER_TYPE)
    ordered = [
        ("SaveConfigData", streams.save_config_stream(DLL_HEADER, TARGET_RELEASE)),
        ("Scene", scene_stream),
        ("ScriptedCustAttribDefs", b""),
        ("DllDirectory", graph.dll_directory_stream(DLL_HEADER)),
        ("ClassDirectory3", graph.class_directory_stream()),
        ("ClassData", b""),
        ("Config", streams.config_stream(scene.frame_rate, scene.animation_end)),
        ("VideoPostQueue", streams.video_post_queue_stream()),
        ("\x05SummaryInformation", streams.summary_information_stream(scene.comment or options.comments)),
        ("\x05DocumentSummaryInformation",
         streams.document_summary_information_stream(_document_parts(scene, graph, materials, nodes))),
        ("FileAssetMetaData3", streams.asset_metadata_stream(materials.assets)),
    ]
    return write_compound_file(ordered)


def write(scene: Scene, path, options: WriterOptions | None = None):
    """Write ``scene`` to ``path``."""
    data = to_bytes(scene, options)
    with open(path, "wb") as fh:
        fh.write(data)
    return len(data)
