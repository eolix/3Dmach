# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Synthetic ``.max``-like fixtures, built in code.

**These are not real .max files** and contain no bytes copied from any. They follow the layouts described in
``docs/format/overview.md``, most of which have been verified on the local corpus (see the overview); tests built
on them check that the parser implements those layouts. The corpus tests (``test_corpus.py``) check the layouts
themselves against real files.

Where the overview doesn't specify something (for example the chunk type of the Scene's top-level container), the
builders use arbitrary placeholder values that the parser must not depend on.
"""

import gzip
import struct

from cfb_writer import build_cfb

CLASS_ENTRY = 0x2040
DLL_HEADER = 0x21C0
DLL_ENTRY = 0x2038
# Placeholder chunk type for things overview.md doesn't specify; the parser must ignore it.
ANY_SCENE_TOP = 0x2000
NULL = 0xFFFFFFFF


def leaf(chunk_type, payload=b"", extended=False):
    """A leaf chunk (overview.md §2.1)."""
    if extended:
        return struct.pack("<HIQ", chunk_type, 0, len(payload) + 14) + payload
    return struct.pack("<HI", chunk_type, len(payload) + 6) + payload


def cont(chunk_type, *children, extended=False):
    """A container chunk (overview.md §2.1): bit 31 (bit 63 when extended) of the size is set."""
    payload = b"".join(children)
    if extended:
        return struct.pack("<HIQ", chunk_type, 0, (len(payload) + 14) | (1 << 63)) + payload
    return struct.pack("<HI", chunk_type, (len(payload) + 6) | 0x80000000) + payload


def text(s):
    return s.encode("utf-16-le")


def u32(*values):
    return struct.pack("<{:d}I".format(len(values)), *values)


def f32(*values):
    return struct.pack("<{:d}f".format(len(values)), *values)


def max_quat(w, x, y, z):
    """Encode (w, x, y, z) as files store it: x, y, z, w of the inverse rotation (overview.md §4.1)."""
    return f32(-x, -y, -z, w)


class SceneBuilder:
    """Collects classes, DLLs and scene objects and writes the streams."""

    def __init__(self):
        self.classes = []
        self.dlls = []
        self.objects = []

    def dll(self, *strings_by_type):
        """Add a DLL entry; arguments are (chunk_type, text) pairs (0x2037 file name, 0x2039 description).
        Returns its index."""
        self.dlls.append(cont(DLL_ENTRY, *(leaf(t, text(s)) for t, s in strings_by_type)))
        return len(self.dlls) - 1

    def cls(self, name, class_id, superclass_id, dll_index=NULL):
        """Add a class-directory entry (overview.md §2.3). ``class_id`` is (a, b). Returns the class index."""
        a, b = class_id
        self.classes.append(cont(
            CLASS_ENTRY,
            leaf(0x2060, u32(dll_index, a, b, superclass_id)),
            leaf(0x2042, text(name)),
        ))
        return len(self.classes) - 1

    def obj(self, class_index, *children):
        """Add a scene object; returns its object index."""
        self.objects.append(cont(class_index, *children))
        return len(self.objects) - 1

    def set_obj(self, index, class_index, *children):
        self.objects[index] = cont(class_index, *children)

    def placeholder(self):
        """Reserve an object index, to be filled with :meth:`set_obj` (for forward references)."""
        self.objects.append(None)
        return len(self.objects) - 1

    def node(self, node_class, name=None, parent=None, refs=None, offset_pos=None, offset_rot=None,
             offset_scale=None, extra=()):
        """Add a node object (overview.md §4). ``refs`` is a list of object indices (or NULL) per slot."""
        children = []
        if refs is not None:
            children.append(refs_ordered(*refs))
        if parent is not None:
            children.append(leaf(0x0960, u32(parent, 0)))
        if name is not None:
            children.append(leaf(0x0962, text(name)))
        if offset_pos is not None:
            children.append(leaf(0x096A, f32(*offset_pos)))
        if offset_rot is not None:
            children.append(leaf(0x096B, max_quat(*offset_rot)))
        if offset_scale is not None:
            children.append(leaf(0x096C, f32(*offset_scale, 0.0, 0.0, 0.0, 1.0)))
        children.extend(extra)
        return self.obj(node_class, *children)

    def streams(self, compress=()):
        """The stream dict for :func:`cfb_writer.build_cfb`; stream names in ``compress`` are gzipped."""
        assert None not in self.objects, "unfilled placeholder"
        streams = {
            "ClassDirectory3": b"".join(self.classes),
            "DllDirectory": leaf(DLL_HEADER, u32(0x4E200000)) + b"".join(self.dlls),
            "Scene": cont(ANY_SCENE_TOP, *self.objects),
        }
        for name in compress:
            streams[name] = gzip.compress(streams[name])
        return streams

    def build(self, version=3, compress=(), extra_streams=None):
        streams = self.streams(compress)
        streams.update(extra_streams or {})
        return build_cfb(streams, version=version)[0]


def refs_ordered(*indices):
    """Ordered references (overview.md §3): slot i = element i."""
    return leaf(0x2034, u32(*indices))


def refs_sparse(mapping, first=0):
    """Sparse references (overview.md §3): one skipped u32, then (slot, index) pairs."""
    values = [first]
    for slot, index in sorted(mapping.items()):
        values.extend((slot, index))
    return leaf(0x2035, u32(*values))


# -----------------------------------------------------------------------------
# Geometry (overview.md §6.2, §6.3). Material IDs are written 0-based, as stored on disk.

def poly_mesh(positions, faces, material_ids=None, smoothing=None, channels=None, extra=(), unknown_field=False):
    """An Editable Poly 0x08FE container. ``material_ids`` are 0-based disk values; ``channels`` maps
    channel number -> (map vertices, map faces). Like Max, the optional face fields are only written when they
    are non-zero, and the triangulation diagonals on faces with more than three corners."""
    verts = u32(len(positions)) + b"".join(u32(0) + f32(*p) for p in positions)
    face_data = [u32(len(faces))]
    for i, face in enumerate(faces):
        flags = 0
        tail = b""
        if unknown_field:
            flags |= 0x01
            tail += u32(1)
        if material_ids is not None and material_ids[i]:
            flags |= 0x08
            tail += struct.pack("<H", material_ids[i])
        if smoothing is not None and smoothing[i]:
            flags |= 0x10
            tail += u32(smoothing[i])
        if len(face) > 3:
            flags |= 0x20
            tail += b"".join(u32(0, k) for k in range(2, len(face) - 1))     # Fan diagonals.
        face_data.append(u32(len(face), *face) + struct.pack("<H", flags) + tail)
    children = [leaf(0x0100, verts), leaf(0x011A, b"".join(face_data)),
                leaf(0x0120, u32(max(channels or {0: None}) + 1))]
    for number, (map_verts, map_faces) in (channels or {}).items():
        children.append(leaf(0x0124, struct.pack("<i", number)))
        children.append(leaf(0x0128, u32(len(map_verts)) + b"".join(f32(*v) for v in map_verts)))
        children.append(leaf(0x012B, b"".join(u32(len(f), *f) for f in map_faces)))
    children.extend(extra)
    return cont(0x08FE, *children)


def tri_mesh(positions, faces, material_ids=None, smoothing=None, channels=None, edge_flags=None):
    """An Editable Mesh 0x08FE container (triangles). ``material_ids`` are 0-based disk values; ``edge_flags`` are
    the face flags (bits 0-2: edge visibility; default all visible)."""
    n = len(faces)
    material_ids = material_ids or [0] * n
    smoothing = smoothing or [0] * n
    edge_flags = edge_flags or [7] * n
    children = [
        leaf(0x0906, u32(0)),
        leaf(0x0914, u32(len(positions)) + b"".join(f32(*p) for p in positions)),
        leaf(0x0912, u32(n) + b"".join(u32(*f, smoothing[i]) + struct.pack("<HH", edge_flags[i], material_ids[i])
                                       for i, f in enumerate(faces))),
        leaf(0x0924, u32(0)),   # Not a channel number (it was read as one by the prior-art importer).
    ]
    for number, (map_verts, map_faces) in (channels or {}).items():
        children.append(leaf(0x0959, struct.pack("<i", number)))
        children.append(leaf(0x2398, u32(1)))
        children.append(leaf(0x2394, u32(len(map_verts)) + b"".join(f32(*v) for v in map_verts)))
        children.append(leaf(0x2396, u32(len(map_faces)) + b"".join(u32(*f) for f in map_faces)))
    return cont(0x08FE, *children)


# -----------------------------------------------------------------------------
# Parameter blocks (overview.md §5.1)

PB2 = ((0x82, 0), 0x82)         # ParamBlock2 class ID and superclass
PB2_TYPES = {"float": 0, "int": 1, "rgb": 2, "point3": 3, "bool": 4, "angle": 5, "percent": 6, "world": 7,
             "string": 8, "filename": 9, "material": 14, "texmap": 15, "node": 17, "reference": 18, "rgba": 23}
_PB2_FORMATS = {"float": "<f", "angle": "<f", "percent": "<f", "world": "<f", "int": "<i", "bool": "<I",
                "rgb": "<3f", "point3": "<3f", "rgba": "<4f"}


def _pb2_value(kind, value):
    if kind in ("string", "filename"):
        if value is None:
            return u32(0xFFFFFFFF)
        raw = value.encode("utf-8") + b"\0"
        return u32(len(raw)) + raw
    fmt = _PB2_FORMATS[kind]
    return struct.pack(fmt, *(value if isinstance(value, (tuple, list)) else (value,)))


def pb2_param(param_id, kind, value=None, animated=False, inline_ref=False, table=False):
    """One ParamBlock2 record (chunk 0x100E). References are slot-based unless ``inline_ref`` (then ``value`` is
    the object index or None); ``animated`` values have no inline value (a controller in the next free slot).
    ``table``: ``value`` is a list (for references, the items are slot-based or inline like single values)."""
    code = PB2_TYPES[kind] | (0x800 if table else 0)
    is_ref = kind in ("material", "texmap", "node", "reference")
    flags_a = 0x0100 if inline_ref else 0
    flags_b = 0x81 if is_ref else (0x92 if animated else 0x82)
    value_flags = 0x80 if animated else 0x40
    head = struct.pack("<HIHIHB", param_id, code, flags_a, flags_b, 0, 0 if table else value_flags)
    if table:
        items = []
        for item in value:
            if is_ref:
                items.append(b"\x40" + (u32(0xFFFFFFFF if item is None else item) if inline_ref else b""))
            elif item is None:      # Animated item.
                items.append(b"\x80")
            else:
                items.append(b"\x40" + _pb2_value(kind, item))
        return leaf(0x100E, head + u32(len(value)) + b"".join(items))
    if is_ref:
        return leaf(0x100E, head + (u32(0xFFFFFFFF if value is None else value) if inline_ref else b""))
    if animated:
        return leaf(0x100E, head)
    return leaf(0x100E, head + _pb2_value(kind, value))


def pb2_block(owner, *records, refs=None, old_records=False):
    """A ParamBlock2 object's children: the 0x0009 header, the records and the reference chunk. ``refs`` maps slot
    -> object index. ``old_records`` writes the record chunks as 0x000E (files from Max 2012 and older)."""
    header = leaf(0x0009, struct.pack("<IHIHI", 1, 0, 0x4E20, len(records), owner))
    if old_records:
        records = tuple(leaf(0x000E, r[6:]) for r in records)
    children = [header, *records]
    if refs:
        count = max(refs) + 1
        children.append(refs_sparse(refs, first=count))
    return children


def param(param_id, payload):
    """A parameter-block entry: a leaf whose payload starts with the u16 parameter index (overview.md §5.1).
    The chunk type is a placeholder; the documented rule doesn't depend on it."""
    return leaf(0x0001, struct.pack("<H", param_id) + payload)


def prim_leaf(value):
    """Primitive parameter, encoding 1 (overview.md §6.4): a leaf longer than 11 bytes, value = last f32."""
    return leaf(0x0002, b"\0" * 8 + f32(value))


def prim_holder(value):
    """Primitive parameter, encoding 2: a container with a 0x0100 child holding the f32."""
    return cont(0x0003, leaf(0x0100, f32(value)))


def prim_record(value):
    """Primitive parameter, encoding 3: u16, u32, u16, u16, u8, f32, f32 (value last)."""
    return leaf(0x0004, struct.pack("<HIHHBff", 1, 2, 3, 4, 5, 0.0, value))
