# SPDX-FileCopyrightText: 2026 3Dmach Authors
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
    "SceneUnits",
    "DecodeContext",
    "parse_scene",
    "read_units",
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

# Reference chunks (verified on the corpus, overview.md §3).
CHUNK_REFS_ORDERED = 0x2034     # u32[] object indices, slot i = element i
CHUNK_REFS_SPARSE = 0x2035      # u32 slot count, then (u32 slot, u32 object index) pairs
NULL_INDEX = 0xFFFFFFFF         # "No reference" (0x2034 lists it for empty slots).

# Node chunks (overview.md §4). Verified on 40,948 corpus nodes: every node has 0x0960, 0x0962 and the offset chunks.
CHUNK_NODE_PARENT = 0x0960      # u32 parent object index, u32 node flags (see Node.flags)
CHUNK_NODE_NAME = 0x0962        # UTF-16LE
CHUNK_NODE_OFFSET_POS = 0x096A  # f32[3]
CHUNK_NODE_OFFSET_ROT = 0x096B  # f32[4], file order (see transform.quat_from_max)
CHUNK_NODE_OFFSET_SCALE = 0x096C  # f32[3] scale, f32[4] scale-axis quaternion; first three used
CHUNK_NODE_WIRE_COLOR = 0x0974  # u8 r, g, b, 0 (the fourth byte is 0 on every corpus node)

# Node reference slots (verified: slot 0 holds a matrix3 controller on 40,947 of 40,948 nodes, slot 1 geometry /
# light / camera / shape / helper objects, slot 3 materials, slot 6 a layer).
SLOT_CONTROLLER = 0
SLOT_OBJECT = 1
SLOT_MATERIAL = 3
SLOT_LAYER = 6

# Verified: nodes have class ID 0x1 and superclass 0x1 (the scene root is class 0x2, superclass 0x1: "RootNode").
NODE_CLASS_ID = ClassID(0x1, 0x0)
NODE_SUPERCLASS_ID = 0x1
ROOT_NODE_CLASS_ID = ClassID(0x2, 0x0)

# Node flag bits in the second word of 0x0960. Guess, from the names of the nodes that carry them in the corpus:
NODE_FLAG_GROUP_HEAD = 1 << 6       # Set on the Dummy heading a group ("tower01", "block-2", ...).
NODE_FLAG_GROUP_MEMBER = 1 << 8     # Set on members of a group (and on nested group heads).
NODE_FLAG_TARGET = 1 << 14          # Set on every "<name>.Target" node of cameras and lights.

# Chunk types beyond the class directory that are classes of their own (see registry.DERIVED_OBJECT).
PSEUDO_CLASSES = {
    registry.DERIVED_OBJECT: "Derived Object",
    registry.DERIVED_OBJECT_WSM: "Derived Object (world space)",
}

# Decoders can follow references into other decoders; this bounds the nesting (Python recursion).
MAX_DECODE_DEPTH = 64

# Scene settings object (class 0x2222, superclass 0x100, stored name "Scene"; one per file) and its unit chunk:
# u32 system unit, f32 system unit scale ("1 unit = <scale> <unit>"). Verified on the corpus (623 files: codes 0, 1,
# 3, 4, 5 occur, the scale is always 1.0): architectural scenes come out at their real size with this table, e.g.
# an interior modelled as a 5.000 m room is 196.85 units in a file with code 0 (inches), a ~4.9 km bridge is
# 166,534 units in inches, a photo studio 6,263 units in millimetres, a Revit import of a building 149.6 units in
# feet. Some sample sets were saved with a unit that doesn't match their content (character sets that exist in a
# metre and a "-US" variant with identical geometry, motion-capture files with identical geometry saved in
# centimetres or metres), so the importer should let the user override it.
SCENE_SETTINGS_CLASS_ID = ClassID(0x2222, 0x0)
SCENE_SETTINGS_SUPERCLASS_ID = 0x100
CHUNK_SYSTEM_UNIT = 0x8520
# Codes 2 and 6 don't occur in the corpus; they are assumed from the order of the others.
SYSTEM_UNITS = {0: "inches", 1: "feet", 2: "miles", 3: "millimeters", 4: "centimeters", 5: "meters",
                6: "kilometers"}


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
    flags: int = 0
    """Raw node flags (second word of 0x0960); see :attr:`is_target`, :attr:`is_group_head`."""
    wire_color: tuple[int, int, int] | None = None
    """Wireframe colour, 0-255 per channel."""

    @property
    def is_target(self) -> bool:
        """The target node of a camera or light. Guess (NODE_FLAG_TARGET): verified only by node names."""
        return bool(self.flags & NODE_FLAG_TARGET)

    @property
    def is_group_head(self) -> bool:
        """The dummy heading a group. Guess (NODE_FLAG_GROUP_HEAD): verified only by node names."""
        return bool(self.flags & NODE_FLAG_GROUP_HEAD)

    @property
    def is_group_member(self) -> bool:
        """A member of a group. Guess (NODE_FLAG_GROUP_MEMBER)."""
        return bool(self.flags & NODE_FLAG_GROUP_MEMBER)

    def local_matrix(self) -> Matrix4:
        """The transform controller's matrix (identity when not decoded)."""
        return self.transform.matrix() if self.transform is not None else IDENTITY

    def world_matrix(self) -> Matrix4:
        """
        Product of :meth:`local_matrix` from the root down to this node.

        Unverified (overview.md §4): assumes controller values are relative to the parent node (no reference
        export in the corpus to check against).
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


@dataclasses.dataclass(frozen=True)
class SceneUnits:
    """The scene's system unit: one scene unit is ``scale`` ``unit`` (e.g. 1.0 "inches")."""
    unit: str | None        # "inches", "feet", "miles", "millimeters", "centimeters", "meters", "kilometers"
    scale: float
    code: int               # The stored unit code.

    @property
    def metres(self) -> float | None:
        """Length of one scene unit in metres, or None for an unknown unit code."""
        factors = {"inches": 0.0254, "feet": 0.3048, "miles": 1609.344, "millimeters": 0.001,
                   "centimeters": 0.01, "meters": 1.0, "kilometers": 1000.0}
        return self.scale * factors[self.unit] if self.unit in factors else None


def read_units(scene: "Scene") -> SceneUnits | None:
    """The system unit stored in the scene settings object, or None when the file has none."""
    for obj in scene.objects:
        if obj.class_id == SCENE_SETTINGS_CLASS_ID and obj.superclass_id == SCENE_SETTINGS_SUPERCLASS_ID:
            chunk = obj.chunk.find(CHUNK_SYSTEM_UNIT)
            if chunk is None or chunk.payload_size < 8:
                return None
            code, scale = struct.unpack_from("<If", chunk.data)
            return SceneUnits(SYSTEM_UNITS.get(code), scale, code)
    return None


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

    def refs(self, obj: SceneObject) -> list[tuple[int, SceneObject]]:
        """All ``(slot, object)`` references of ``obj``, in slot order."""
        return [(slot, self.scene.objects[index]) for slot, index in sorted(obj.references.items())]

    def decode(self, obj: SceneObject | None) -> Any:
        """
        Decoded value of another object (None when absent or not decodable).

        A reference cycle or too deep nesting is reported in the warnings and gives None, so a decoder can treat
        every referenced object the same way.
        """
        try:
            return self.scene.decode(obj)
        except DecodeError as ex:
            self.warn("object {:d}: {:s}".format(obj.index, str(ex)))
            return None

    def warn(self, message: str):
        self.scene.warnings.append(message)

    @property
    def cache(self) -> dict:
        """Per-scene storage for helpers that aren't registered decoders (keyed by the helper)."""
        return self.scene.cache

    def asset_metadata(self):
        """The file's asset metadata (:class:`maxfile.assets.AssetMetadata`), or None when not available."""
        return self.scene.asset_metadata()


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
        self.cache: dict = {}
        """Storage for decoding helpers (see :attr:`DecodeContext.cache`)."""
        self._asset_loader = None   # Set by MaxFile: a callable returning the asset metadata.

    def asset_metadata(self):
        """The file's asset metadata (:class:`maxfile.assets.AssetMetadata`), or None when not available."""
        return self._asset_loader() if self._asset_loader is not None else None

    @property
    def context(self) -> DecodeContext:
        """A decode context, for calling helpers such as :func:`maxfile.objects.maps.read_map` directly."""
        return self._ctx

    def resolve_geometry(self, node: Node) -> tuple[SceneObject | None, list[SceneObject]]:
        """
        The base object of ``node`` and its modifiers, through any modifier-stack wrappers.

        Returns ``(base, modifiers)``; ``modifiers`` lists the modifier objects from the top of the stack down
        (verified order, see :mod:`maxfile.objects.modifiers`). ``base`` is None when the node has no object or
        the wrappers don't lead to one.
        """
        from .objects.modifiers import ModifierStack
        obj = node.object
        modifiers = []
        seen = set()
        while obj is not None:
            if obj.index in seen:
                self.warnings.append("node {:d}: modifier-stack wrappers form a cycle at object {:d}".format(
                    node.index, obj.index))
                return None, modifiers
            seen.add(obj.index)
            value = self.decode(obj)
            if not isinstance(value, ModifierStack):
                return obj, modifiers
            # Outer wrappers sit above inner ones, so their modifiers come first.
            modifiers.extend(self.objects[m.object_index] for m in value.modifiers)
            obj = self.objects[value.base] if value.base is not None else None
        return None, modifiers

    def param_block(self, obj: SceneObject | None):
        """
        ``obj`` read as a parameter block (:class:`maxfile.objects.paramblock.ParamBlockData`), or None when it is
        not a ParamBlock / ParamBlock2.
        """
        from .objects.paramblock import ParamBlockData
        value = self.decode(obj) if obj is not None else None
        return value if isinstance(value, ParamBlockData) else None

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
            # Verified: u32 object indices, slot = position.
            if child.payload_size % 4:
                problems["reference chunk size not a multiple of 4"] += 1
            pairs = enumerate(u32s(child.data))
        elif child.type == CHUNK_REFS_SPARSE:
            # Verified: u32 slot count, then (slot, object index) pairs (payload 4 + 8n in all 17,097 sampled).
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
    # Verified: class ID 0x1 with superclass 0x1.
    return obj.class_id == NODE_CLASS_ID and obj.superclass_id == NODE_SUPERCLASS_ID


def _read_node(obj: SceneObject, scene: Scene, problems: collections.Counter) -> Node:
    node = Node(obj.index, obj)
    chunk = obj.chunk
    name = chunk.find(CHUNK_NODE_NAME)
    if name is not None:
        node.name = name.string()
    parent = chunk.find(CHUNK_NODE_PARENT)
    if parent is not None:
        if parent.payload_size >= 8:
            node.parent_index, node.flags = u32s(parent.data, 2)
        elif parent.payload_size >= 4:
            node.parent_index = u32s(parent.data, 1)[0]
        else:
            problems["node parent chunk shorter than 4 bytes"] += 1
    wire = chunk.find(CHUNK_NODE_WIRE_COLOR)
    if wire is not None and wire.payload_size >= 3:
        node.wire_color = tuple(wire.data[:3])

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
    # Verified: one top-level container holding all objects.
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
    pseudo = {}
    for index, chunk in enumerate(children):
        cls = classes.get(chunk.type)
        if cls is None and chunk.type in PSEUDO_CLASSES:
            # Verified: these chunk types are classes of their own, never in the class directory.
            if chunk.type not in pseudo:
                pseudo[chunk.type] = ClassEntry(chunk.type, PSEUDO_CLASSES[chunk.type], ClassID(chunk.type), None,
                                                None)
            cls = pseudo[chunk.type]
        elif cls is None:
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
