# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
The ``Scene`` stream: the object list, references between objects, and scene nodes.

Model, from ``docs/format/overview.md`` §3 and §4 (unverified on real files):

- The stream holds one top-level container. Each of its children is one **object** (node, geometry, controller,
  material, ...). The child's chunk type is an index into the class directory; its position in the list is the
  object's **index**, which other objects use to refer to it.
- An object's **references** map slot numbers to object indices (chunks ``0x2034`` and ``0x2035``). Two nodes
  that reference the same object index share it: that is how instancing works.
- A **node** has a name, a parent, an object offset (pivot) and reference slots for its transform controller,
  object, material and layer.

Everything is plain data. Objects other than nodes are not decoded here; :meth:`Scene.decode` runs the decoder
registered for an object's class (:mod:`maxfile.registry`).
"""

__all__ = (
    "SCENE_STREAM",
    "SceneObject",
    "Node",
    "Scene",
    "DecodeContext",
    "parse_scene",
)

import collections
import dataclasses
import struct
from typing import Any

from . import registry
from .chunks import Chunk, ChunkStream, f32s, u32s
from .classes import ClassDirectory, ClassEntry, ClassID
from .errors import DecodeError, MaxFileError
from .transform import IDENTITY, Matrix4, Transform, matmul, quat_from_max

SCENE_STREAM = "Scene"

# Reference chunks (unverified, overview.md §3).
CHUNK_REFS_ORDERED = 0x2034     # u32[] object indices, slot i = element i
CHUNK_REFS_SPARSE = 0x2035      # u32 (unknown, skipped), then (u32 slot, u32 object index) pairs
NULL_INDEX = 0xFFFFFFFF         # Presumably the explicit "no reference" (overview.md §3).

# Node chunks (unverified, overview.md §4).
CHUNK_NODE_PARENT = 0x0960      # u32 parent object index, ...
CHUNK_NODE_NAME = 0x0962        # UTF-16LE
CHUNK_NODE_OFFSET_POS = 0x096A  # f32[3]
CHUNK_NODE_OFFSET_ROT = 0x096B  # f32[4], file order (see transform.quat_from_max)
CHUNK_NODE_OFFSET_SCALE = 0x096C  # f32[3+], first three used

# Node reference slots (unverified, overview.md §4).
SLOT_CONTROLLER = 0
SLOT_OBJECT = 1
SLOT_MATERIAL = 3
SLOT_LAYER = 6

# Unverified (overview.md §4): nodes have class ID 0x1 and superclass 0x1.
NODE_CLASS_ID = ClassID(0x1, 0x0)
NODE_SUPERCLASS_ID = 0x1

# Decoders can follow references into other decoders; this bounds the nesting (Python recursion).
MAX_DECODE_DEPTH = 64


@dataclasses.dataclass(eq=False)
class SceneObject:
    """One child of the ``Scene`` container."""
    index: int                          # Position in the object list.
    class_index: int                    # The chunk type: index into the class directory.
    cls: ClassEntry | None              # None when class_index is outside the class directory.
    chunk: Chunk = dataclasses.field(repr=False)
    references: dict[int, int] = dataclasses.field(default_factory=dict, repr=False)
    """Reference slot -> object index, for in-range, non-null references only."""

    @property
    def class_id(self) -> ClassID | None:
        return self.cls.class_id if self.cls is not None else None

    @property
    def superclass_id(self) -> int | None:
        return self.cls.superclass_id if self.cls is not None else None

    def class_label(self) -> str:
        """Our registry name for the class, else the name stored in the file, else ``#<class index>``."""
        known = registry.known_class(self.class_id, self.superclass_id)
        if known is not None:
            return known.name
        if self.cls is not None:
            return self.cls.label()
        return "#{:d}".format(self.class_index)


@dataclasses.dataclass(eq=False)
class Node:
    """A scene node. Object references point into :attr:`Scene.objects`."""
    index: int                          # Object index of the node itself.
    obj: SceneObject = dataclasses.field(repr=False)
    name: str | None = None
    parent_index: int | None = None     # Raw value of the parent chunk (may point at a non-node, e.g. the root).
    parent: "Node | None" = dataclasses.field(default=None, repr=False)
    children: list["Node"] = dataclasses.field(default_factory=list, repr=False)
    object_offset: Transform = dataclasses.field(default_factory=Transform)
    """Pivot offset: places the object's geometry relative to the node."""
    transform: Transform | None = None
    """Static value of the transform controller, relative to the parent (None when not decoded)."""
    controller: SceneObject | None = dataclasses.field(default=None, repr=False)
    object: SceneObject | None = dataclasses.field(default=None, repr=False)
    material: SceneObject | None = dataclasses.field(default=None, repr=False)
    layer: SceneObject | None = dataclasses.field(default=None, repr=False)

    def local_matrix(self) -> Matrix4:
        """The transform controller's matrix (identity when not decoded)."""
        return self.transform.matrix() if self.transform is not None else IDENTITY

    def world_matrix(self) -> Matrix4:
        """
        Product of :meth:`local_matrix` from the root down to this node.

        Unverified (overview.md §4): assumes controller values are relative to the parent node.
        """
        chain = []
        node = self
        while node is not None:     # Parent cycles are broken when the scene is built.
            chain.append(node)
            node = node.parent
        matrix = IDENTITY
        for node in reversed(chain):
            matrix = matmul(matrix, node.local_matrix())
        return matrix


class DecodeContext:
    """What a decoder gets besides the object: access to references and to other objects' decoded values."""

    def __init__(self, scene: "Scene"):
        self.scene = scene

    def ref(self, obj: SceneObject, slot: int) -> SceneObject | None:
        """The object in reference ``slot`` of ``obj``, or None."""
        return self.scene.ref(obj, slot)

    def first_ref(self, obj: SceneObject) -> SceneObject | None:
        """The object in the lowest-numbered reference slot of ``obj``, or None."""
        if not obj.references:
            return None
        return self.scene.objects[obj.references[min(obj.references)]]

    def decode(self, obj: SceneObject | None) -> Any:
        """Decoded value of another object (None when absent or not decodable)."""
        return self.scene.decode(obj)

    def warn(self, message: str):
        self.scene.warnings.append(message)


class Scene:
    """
    The parsed ``Scene`` stream.

    :attr:`objects` is the object list, :attr:`nodes` the scene nodes in object order and :attr:`roots` the nodes
    without a parent node. Problems are collected in :attr:`warnings`; nothing here raises on bad data.
    """

    def __init__(self, objects: list[SceneObject], warnings: list[str]):
        self.objects = objects
        self.warnings = warnings
        self.nodes: list[Node] = []
        self.roots: list[Node] = []
        self.undecoded: collections.Counter[str] = collections.Counter()
        """Class label -> number of objects :meth:`decode` was asked for that have no decoder."""
        self._decoded: dict[int, Any] = {}
        self._decoding: list[int] = []
        self._ctx = DecodeContext(self)
        self._node_by_index: dict[int, Node] = {}

    def ref(self, obj: SceneObject, slot: int) -> SceneObject | None:
        """The object in reference ``slot`` of ``obj``, or None."""
        index = obj.references.get(slot)
        return self.objects[index] if index is not None else None

    def node(self, index: int) -> Node | None:
        """The node with object index ``index``, or None when that object isn't a node."""
        return self._node_by_index.get(index)

    def class_counts(self) -> collections.Counter[int]:
        """Class index -> number of objects of that class."""
        return collections.Counter(obj.class_index for obj in self.objects)

    def decode(self, obj: SceneObject | None) -> Any:
        """
        Run the registered decoder for ``obj``'s class and return its result (cached).

        Returns None when ``obj`` is None, its class has no decoder (counted in :attr:`undecoded`) or decoding
        failed (reason added to :attr:`warnings`).
        """
        if obj is None:
            return None
        if obj.index in self._decoded:
            return self._decoded[obj.index]
        if obj.index in self._decoding:
            raise DecodeError("reference cycle through object {:d}".format(obj.index))
        if len(self._decoding) >= MAX_DECODE_DEPTH:
            raise DecodeError("references nested more than {:d} deep".format(MAX_DECODE_DEPTH))
        info = registry.find_decoder(obj.class_id, obj.superclass_id)
        if info is None:
            self.undecoded[obj.class_label()] += 1
            self._decoded[obj.index] = None
            return None
        self._decoding.append(obj.index)
        try:
            value = info.function(obj, self._ctx)
        except (MaxFileError, struct.error) as ex:
            self.warnings.append("object {:d} ({:s}): {:s}: {:s}".format(
                obj.index, obj.class_label(), info.name, str(ex)))
            value = None
        finally:
            self._decoding.pop()
        self._decoded[obj.index] = value
        return value


def _read_references(chunk: Chunk, count: int, problems: collections.Counter) -> dict[int, int]:
    refs = {}
    for child in chunk.children:
        if child.type == CHUNK_REFS_ORDERED:
            # Unverified (overview.md §3): u32 object indices, slot = position.
            if child.payload_size % 4:
                problems["reference chunk size not a multiple of 4"] += 1
            pairs = enumerate(u32s(child.data))
        elif child.type == CHUNK_REFS_SPARSE:
            # Unverified (overview.md §3): one skipped u32, then (slot, object index) pairs.
            if child.payload_size % 8 != 4:
                problems["sparse reference chunk size isn't 4 + 8n"] += 1
            values = u32s(child.data)[1:]
            pairs = zip(values[0::2], values[1::2])
        else:
            continue
        for slot, index in pairs:
            if index == NULL_INDEX:
                continue
            if index >= count:
                problems["reference to an object index outside the object list"] += 1
                continue
            refs[slot] = index
    return refs


def _is_node(obj: SceneObject) -> bool:
    # Unverified (overview.md §4): class ID 0x1 with superclass 0x1, or a parent chunk.
    if obj.class_id == NODE_CLASS_ID and obj.superclass_id == NODE_SUPERCLASS_ID:
        return True
    return obj.chunk.find(CHUNK_NODE_PARENT) is not None


def _read_node(obj: SceneObject, scene: Scene, problems: collections.Counter) -> Node:
    node = Node(obj.index, obj)
    chunk = obj.chunk
    name = chunk.find(CHUNK_NODE_NAME)
    if name is not None:
        node.name = name.string()
    parent = chunk.find(CHUNK_NODE_PARENT)
    if parent is not None:
        if parent.payload_size >= 4:
            node.parent_index = u32s(parent.data, 1)[0]
        else:
            problems["node parent chunk shorter than 4 bytes"] += 1

    def floats(chunk_type, count):
        found = chunk.find(chunk_type)
        if found is None:
            return None
        values = f32s(found.data)
        if len(values) < count:
            problems["node chunk 0x{:04X} shorter than {:d} floats".format(chunk_type, count)] += 1
            return None
        return values[:count]

    rotation = floats(CHUNK_NODE_OFFSET_ROT, 4)
    node.object_offset = Transform(
        position=floats(CHUNK_NODE_OFFSET_POS, 3),
        rotation=quat_from_max(rotation) if rotation is not None else None,
        scale=floats(CHUNK_NODE_OFFSET_SCALE, 3),
    )
    node.controller = scene.ref(obj, SLOT_CONTROLLER)
    node.object = scene.ref(obj, SLOT_OBJECT)
    node.material = scene.ref(obj, SLOT_MATERIAL)
    node.layer = scene.ref(obj, SLOT_LAYER)
    return node


def _link_hierarchy(scene: Scene, problems: collections.Counter):
    for node in scene.nodes:
        if node.parent_index is not None and node.parent_index != node.index:
            node.parent = scene.node(node.parent_index)
        elif node.parent_index == node.index:
            problems["node is its own parent"] += 1
    # Break parent cycles: walk up from each node, marking visited nodes; O(number of nodes) overall.
    state = {}  # node index -> 1 while on the current path, 2 when known to reach a root
    for start in scene.nodes:
        path = []
        node = start
        while node is not None and node.index not in state:
            state[node.index] = 1
            path.append(node)
            node = node.parent
        if node is not None and state[node.index] == 1:
            # ``node`` is on the current path: cut the link that closes the loop.
            problems["parent links form a cycle (link removed)"] += 1
            path[-1].parent = None
        for item in path:
            state[item.index] = 2
    for node in scene.nodes:
        if node.parent is not None:
            node.parent.children.append(node)
        else:
            scene.roots.append(node)


def parse_scene(stream: ChunkStream | None, classes: ClassDirectory) -> Scene:
    """Build the :class:`Scene` from the ``Scene`` chunk stream and the class directory."""
    warnings = []
    problems = collections.Counter()
    if stream is None:
        return Scene([], ["no {:s} stream".format(SCENE_STREAM)])
    warnings.extend(stream.warnings)
    if stream.error:
        warnings.append("{:s}: {:s}".format(stream.name, stream.error))
    # Unverified (overview.md §3): one top-level container holding all objects.
    containers = [c for c in stream.chunks if c.is_container]
    if len(stream.chunks) != 1:
        warnings.append("{:s}: {:d} top-level chunks (expected 1); using the first container".format(
            stream.name, len(stream.chunks)))
    if not containers:
        warnings.append("{:s}: no top-level container, no objects read".format(stream.name))
        return Scene([], warnings)
    top = containers[0]

    children = top.children
    if top.error:
        warnings.append("{:s}: object list: {:s}".format(stream.name, top.error))
    objects = []
    for index, chunk in enumerate(children):
        cls = classes.get(chunk.type)
        if cls is None:
            problems["object class index outside the class directory"] += 1
        objects.append(SceneObject(index, chunk.type, cls, chunk))
    for obj in objects:
        obj.references = _read_references(obj.chunk, len(objects), problems)
        if obj.chunk.error:
            problems["object chunk tree damaged (see maxdump --chunks)"] += 1

    scene = Scene(objects, warnings)
    for obj in objects:
        if _is_node(obj):
            node = _read_node(obj, scene, problems)
            scene.nodes.append(node)
            scene._node_by_index[obj.index] = node
    _link_hierarchy(scene, problems)

    undecoded_controllers = collections.Counter()
    for node in scene.nodes:
        if node.controller is None:
            continue
        value = scene.decode(node.controller)
        if isinstance(value, Transform):
            node.transform = value
        else:
            undecoded_controllers[node.controller.class_label()] += 1
    for label, count in sorted(undecoded_controllers.items()):
        warnings.append("{:d} node(s): transform controller {:s} not decoded".format(count, label))
    for message, count in sorted(problems.items()):
        warnings.append("{:s}: {:s} ({:d}x)".format(stream.name, message, count))
    return scene
