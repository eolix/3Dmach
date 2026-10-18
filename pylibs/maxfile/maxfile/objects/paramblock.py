# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Parameter blocks: where most objects (primitives, modifiers, materials, maps, lights, cameras) keep their
parameters. Two classes, both worked out on the local corpus (``docs/format/overview.md`` §5.1):

**ParamBlock2** (class 0x82, superclass 0x82; 190,760 objects in the corpus). Children:

- ``0x0009`` header, 16 bytes: ``u16 block_id, u16 ?, u32 ? (version-like), u16 parameter count, u32 owner``
  (the object index of the object the block belongs to).
- one record per parameter, chunk ``0x100E`` (``0x000E`` in files from Max 2012 and older)::

      u16 param_id, u32 type, u16 flags_a, u32 flags_b, u16 ?, u8 value_flags, value...

  ``value_flags & 0x40``: the value is stored inline; otherwise (0x80 alone) a controller animates it.
  ``flags_b & 0x01``: the parameter holds a reference (node, map, material, ...); ``flags_a & 0x0100``: that
  reference is stored inline as an object index (``0xFFFFFFFF`` = none) instead of in a reference slot.
  ``type & 0x800`` marks a table (``u32 count``, then per item ``u8 item_flags`` and the item's value).
- ``0x2034`` / ``0x2035`` references: the block's reference slots are handed out **in record order** to every
  parameter value that isn't stored inline (controllers of animated values, non-inline references, one slot per
  table item). This rule reproduces the slot count of 60,408 of the 60,410 corpus blocks whose records could all
  be sized, and the referenced classes match the parameter types (float -> float controller, texmap -> map, ...).

Types (codes from the files; the storage of each was checked on the corpus, the meaning from the values and the
class of what they reference): 0 float, 1 int, 2 RGB colour (3 floats), 3 point (3 floats), 4 bool (u32),
5 angle (float, radians), 6 percentage (float fraction: 0.1 = 10 %), 7 world-space distance (float), 8 string,
9 file name, 12 time (int), 13 radio button index (int), 14 material, 15 texture map, 16 one byte (meaning
unknown), 17 node, 18 any reference, 19 index (int), 20 matrix (52 bytes), 23 RGBA colour (4 floats). Strings are
``u32 length`` (0xFFFFFFFF = none) then that many bytes of 8-bit text including a terminating NUL. A length of
0xFFFFFFFE (1,754 file-name parameters in the corpus) means the value is an asset reference: the record ends there
and the next chunk of the block, a ``0x000F`` container, holds the asset's 16-byte ID in ``0x0002`` (the IDs the
``FileAssetMetaData3`` stream lists with their paths). Such values are :class:`AssetRef` objects. Records of a type
the reader can't size but without any value bytes (type 25, 194 records) are read as None.

**ParamBlock** (class 0x8, superclass 0x8; older plugins such as Bend or the Standard material's shader-less
parts). Children: ``0x0001`` u32 count, ``0x0005`` u16, then one ``0x0002`` container per parameter holding
``0x0003`` (u32 index) and one value chunk: ``0x0100`` float, ``0x0101`` int, ``0x0102`` point (3 floats),
``0x0103`` colour (3 floats), ``0x0104`` bool/int; ``0x0200``-``0x0204`` (empty) mark the same types driven by a
controller, which is the block's reference in the slot equal to the parameter index. ``0x0004`` (empty) appears
on animatable parameters.

Values driven by a controller are given as the controller's static value when it can be decoded
(:mod:`maxfile.objects.controllers`), so callers can use :meth:`ParamBlockData.value` either way.
"""

__all__ = (
    "AssetRef",
    "Param",
    "ParamBlockData",
    "TYPE_NAMES",
    "read_param_block",
    "read_param_block2",
    "read_old_param_block",
)

import dataclasses
import struct
import uuid
from typing import Any

from ..errors import DecodeError
from ..registry import decoder

PB2_HEADER = 0x0009
PB2_RECORDS = (0x100E, 0x000E)
PB2_ASSET = 0x000F          # Container after a record whose string length is ASSET_STRING: 0x0002 = asset ID.
PB2_ASSET_ID = 0x0002
ASSET_STRING = 0xFFFFFFFE
PB_COUNT = 0x0001
PB_PARAM = 0x0002
PB_INDEX = 0x0003

TAB = 0x800
REF_FLAG = 0x01             # flags_b: the parameter holds a reference.
INLINE_REF = 0x0100         # flags_a: the reference is stored inline as an object index.
VALUE_INLINE = 0x40         # value_flags: the value follows the record header.
NULL = 0xFFFFFFFF

# Type code -> (name, struct format of an inline value or None for special handling).
TYPE_NAMES = {
    0: "float", 1: "int", 2: "rgb", 3: "point3", 4: "bool", 5: "angle", 6: "percent", 7: "world",
    8: "string", 9: "filename", 12: "time", 13: "radio", 14: "material", 15: "texmap", 16: "byte",
    17: "node", 18: "reference", 19: "index", 20: "matrix3", 23: "rgba",
}
_FORMATS = {
    0: "<f", 5: "<f", 6: "<f", 7: "<f",
    1: "<i", 12: "<i", 13: "<i", 19: "<i",
    4: "<I",
    2: "<3f", 3: "<3f", 23: "<4f",
    20: "<13f",
    16: "<B",
}

# Old ParamBlock value chunks: chunk type -> (name, format); +0x100 = the same type, driven by a controller.
_OLD_VALUES = {0x0100: ("float", "<f"), 0x0101: ("int", "<i"), 0x0102: ("point3", "<3f"),
               0x0103: ("rgb", "<3f"), 0x0104: ("int", "<i")}


@dataclasses.dataclass(frozen=True)
class AssetRef:
    """A file-name parameter stored as a reference into the file's asset table."""
    guid: str                       # Canonical text form, e.g. "2fd48fc1-c16d-4a1c-a89c-b37183364429".
    raw: bytes = dataclasses.field(default=b"", repr=False)    # The 16 bytes as stored.

    @classmethod
    def from_bytes(cls, data: bytes) -> "AssetRef":
        return cls(str(uuid.UUID(bytes_le=bytes(data[:16]))), bytes(data[:16]))


_PENDING_ASSET = object()   # Placeholder until the 0x000F chunk after the record is read.


@dataclasses.dataclass
class Param:
    """One parameter of a parameter block."""
    param_id: int
    type: int                       # Type code (see TYPE_NAMES); tables have 0x800 set.
    kind: str                       # TYPE_NAMES name, "table:<name>" for tables, "unknown:<code>" otherwise.
    value: Any = None
    """Inline value: float, int, bool, tuple of floats, str, or an object index for references (None = none);
    a list of those for tables. For animated values, the controller's static value when it could be read."""
    controller: int | None = None   # Object index of the controller animating the value.
    controllers: list | None = None  # Tables: per-item controller (or None).
    animated: bool = False          # Value comes from a controller.
    is_reference: bool = False      # The value is an object index (node, map, material, ...).
    raw: bytes = dataclasses.field(default=b"", repr=False)


@dataclasses.dataclass
class ParamBlockData:
    object_index: int | None
    kind: str                       # "pb2" or "pb".
    params: dict[int, Param]
    block_id: int | None = None
    owner: int | None = None        # Object index of the owner (ParamBlock2 header), None when not stored.
    problems: list[str] = dataclasses.field(default_factory=list)

    def get(self, param_id: int) -> Param | None:
        return self.params.get(param_id)

    def value(self, param_id: int, default=None):
        """The value of a parameter (static value for animated ones), or ``default``."""
        param = self.params.get(param_id)
        if param is None or param.value is None:
            return default
        return param.value

    @property
    def entries(self) -> list[Param]:
        """The parameters in parameter-ID order."""
        return [self.params[k] for k in sorted(self.params)]


def _string(data, pos):
    """``u32 length`` + bytes (with NUL). Returns ``(text or None, new_pos)``."""
    (n,) = struct.unpack_from("<I", data, pos)
    pos += 4
    if n == NULL:
        return None, pos
    if n == ASSET_STRING:
        return _PENDING_ASSET, pos
    raw = bytes(data[pos:pos + n])
    if len(raw) < n:
        raise DecodeError("string of {:d} bytes runs past the record".format(n))
    return raw.split(b"\0", 1)[0].decode("utf-8", errors="replace"), pos + n


def _type_name(code):
    base = code & ~TAB
    name = TYPE_NAMES.get(base, "unknown:{:d}".format(base))
    return "table:" + name if code & TAB else name


def _read_value(base, data, pos, is_ref, inline_ref):
    """One value of type ``base`` at ``pos``. Returns ``(value, new_pos, uses_slot)``."""
    if is_ref:
        if inline_ref:
            (index,) = struct.unpack_from("<I", data, pos)
            return (None if index == NULL else index), pos + 4, False
        return None, pos, True
    if base in (8, 9):
        text, pos = _string(data, pos)
        return text, pos, False
    fmt = _FORMATS.get(base)
    if fmt is None:
        if pos >= len(data):
            return None, pos, False     # Nothing stored (type 25 records, for example).
        raise DecodeError("unknown parameter type {:d}".format(base))
    size = struct.calcsize(fmt)
    values = struct.unpack_from(fmt, data, pos)
    if base == 4:
        value = bool(values[0])
    elif len(values) == 1:
        value = values[0]
    elif base == 20:
        value = values[1:]      # Guess: a leading flags word, then the 4x3 rows.
    else:
        value = tuple(values)
    return value, pos + size, False


def _record(data):
    """Parse one ParamBlock2 record. Returns ``(Param, slot_requests)`` where each request is ``(param, item)``."""
    if len(data) < 15:
        raise DecodeError("parameter record of {:d} bytes".format(len(data)))
    pid, code, flags_a, flags_b, _unknown, value_flags = struct.unpack_from("<HIHIHB", data)
    base = code & ~TAB
    is_ref = bool(flags_b & REF_FLAG)
    inline_ref = bool(flags_a & INLINE_REF)
    param = Param(pid, code, _type_name(code), is_reference=is_ref, raw=bytes(data))
    requests = []
    pos = 15
    if code & TAB:
        (count,) = struct.unpack_from("<I", data, pos)
        pos += 4
        values = []
        param.controllers = []
        for item in range(count):
            if pos >= len(data):
                raise DecodeError("table parameter {:d}: {:d} of {:d} items".format(pid, item, count))
            item_flags = data[pos]
            pos += 1
            if not is_ref and not item_flags & VALUE_INLINE:
                values.append(None)
                requests.append((param, item))
                param.animated = True
            else:
                value, pos, uses_slot = _read_value(base, data, pos, is_ref, inline_ref)
                values.append(value)
                if uses_slot:
                    requests.append((param, item))
            param.controllers.append(None)
        param.value = values
    elif is_ref:
        value, pos, uses_slot = _read_value(base, data, pos, True, inline_ref)
        if inline_ref and len(data) == 15:
            value = None        # Inline reference without data: none.
        param.value = value
        if uses_slot:
            requests.append((param, None))
    elif value_flags & VALUE_INLINE:
        param.value, pos, _ = _read_value(base, data, pos, False, False)
    else:
        param.animated = True
        requests.append((param, None))
    return param, requests


def _has_pending(param):
    values = param.value if isinstance(param.value, list) else [param.value]
    return any(v is _PENDING_ASSET for v in values)


def _set_pending(param, value):
    if isinstance(param.value, list):
        param.value = [value if v is _PENDING_ASSET else v for v in param.value]
    else:
        param.value = value


def _static(ctx, index):
    """The static value of the controller at ``index`` (None when unknown)."""
    if ctx is None or index is None:
        return None
    value = ctx.decode(ctx.scene.objects[index])
    if isinstance(value, (int, float)) or (isinstance(value, tuple) and all(isinstance(v, float) for v in value)):
        return value
    return None


def read_param_block2(obj, ctx=None) -> ParamBlockData:
    """Read a ParamBlock2 object (``obj`` a SceneObject; ``ctx`` to resolve controllers, optional)."""
    chunk = obj.chunk
    block = ParamBlockData(getattr(obj, "index", None), "pb2", {})
    header = chunk.find(PB2_HEADER)
    if header is not None and header.payload_size >= 16:
        block.block_id = struct.unpack_from("<H", header.data, 0)[0]
        block.owner = struct.unpack_from("<I", header.data, 12)[0]
    requests = []
    pending = None      # A parameter whose asset ID follows in the next chunk.
    for child in chunk.children:
        if pending is not None:
            if child.type == PB2_ASSET and child.is_container:
                found = child.find(PB2_ASSET_ID)
                if found is not None and found.payload_size >= 16:
                    _set_pending(pending, AssetRef.from_bytes(found.data))
                    pending = None
                    continue
            block.problems.append("parameter {:d}: asset reference without its 0x000F chunk".format(
                pending.param_id))
            _set_pending(pending, None)
            pending = None
        if child.type not in PB2_RECORDS or child.is_container:
            continue
        try:
            param, wanted = _record(child.data)
        except (DecodeError, struct.error) as ex:
            block.problems.append("record at 0x{:X}: {:s}".format(child.offset, str(ex)))
            # Slot numbering after an unreadable record is unknown: stop assigning references.
            requests = None
            continue
        block.params.setdefault(param.param_id, param)
        if _has_pending(param):
            pending = param
        if requests is not None:
            requests.extend(wanted)
    if pending is not None:
        block.problems.append("parameter {:d}: asset reference without its 0x000F chunk".format(pending.param_id))
        _set_pending(pending, None)
    refs = getattr(obj, "references", {})
    if requests is None:
        if refs:
            block.problems.append("references not assigned to parameters (a record could not be read)")
        return block
    for slot, (param, item) in enumerate(requests):
        index = refs.get(slot)
        if param.is_reference:
            # A reference-holding parameter: the slot's object is the value.
            if item is None:
                param.value = index
            else:
                param.value[item] = index
        else:
            if item is None:
                param.controller = index
                value = _static(ctx, index)
                if value is not None:
                    param.value = value
            else:
                param.controllers[item] = index
                value = _static(ctx, index)
                if value is not None:
                    param.value[item] = value
    return block


def read_old_param_block(obj, ctx=None) -> ParamBlockData:
    """Read an old-style ParamBlock object (class 0x8)."""
    block = ParamBlockData(getattr(obj, "index", None), "pb", {})
    refs = getattr(obj, "references", {})
    for child in obj.chunk.children:
        if child.type != PB_PARAM or not child.is_container:
            continue
        index_chunk = child.find(PB_INDEX)
        if index_chunk is None or index_chunk.payload_size < 4:
            block.problems.append("parameter at 0x{:X} without index".format(child.offset))
            continue
        index = struct.unpack_from("<I", index_chunk.data)[0]
        for value_chunk in child.children:
            spec = _OLD_VALUES.get(value_chunk.type)
            animated = False
            if spec is None:
                spec = _OLD_VALUES.get(value_chunk.type - 0x100)
                animated = spec is not None
            if spec is None:
                continue
            name, fmt = spec
            param = Param(index, value_chunk.type, name, raw=value_chunk.data)
            if animated:
                param.animated = True
                param.controller = refs.get(index)
                param.value = _static(ctx, param.controller)
            elif value_chunk.payload_size >= struct.calcsize(fmt):
                values = struct.unpack_from(fmt, value_chunk.data)
                param.value = values[0] if len(values) == 1 else tuple(values)
            block.params[index] = param
            break
    return block


def read_param_block(obj, ctx=None) -> ParamBlockData | None:
    """``obj`` read as whichever parameter block class it is, or None when it is neither."""
    if obj is None or obj.class_id is None:
        return None
    if (obj.class_id.a, obj.class_id.b, obj.superclass_id) == (0x82, 0, 0x82):
        return read_param_block2(obj, ctx)
    if (obj.class_id.a, obj.class_id.b, obj.superclass_id) == (0x8, 0, 0x8):
        return read_old_param_block(obj, ctx)
    return None


@decoder(0x82, kind="paramblock", name="ParamBlock2", superclass_id=0x82, verified=True)
def param_block2(obj, ctx):
    """Typed parameters by parameter ID, references and controllers resolved."""
    return read_param_block2(obj, ctx)


@decoder(0x8, kind="paramblock", name="ParamBlock", superclass_id=0x8, verified=True)
def old_param_block(obj, ctx):
    """Typed parameters by index (old parameter blocks)."""
    return read_old_param_block(obj, ctx)
