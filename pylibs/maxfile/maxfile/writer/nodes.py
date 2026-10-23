# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Scene nodes and Dummy helpers, the inverse of :mod:`maxfile.scene` (``docs/format/overview.md`` §4).

A node carries the chunks every corpus node has, in the order of the 2015 files; the ones the reader decodes are
written from the model, the others with the value the Editable Poly nodes of the 2015 files have most often
(344 nodes; "n/344" below).
"""

__all__ = ("node_object", "dummy_object", "NODE_FLAG_FROZEN", "NODE_FLAG_HIDDEN")

from . import classes
from .chunks import cont, f32, leaf, text, u32, u8
from .controllers import max_quaternion, prs
from .graph import MaxObject

# Reference slots (verified, overview.md §4).
SLOT_CONTROLLER, SLOT_OBJECT, SLOT_MATERIAL, SLOT_LAYER = 0, 1, 3, 6
NODE_REF_SLOTS = 16             # Corpus: the sparse reference chunk of all 14,680 nodes declares 16 slots.

# Node flag bits (second word of 0x0960); guesses of overview.md §4 (the reader's NODE_FLAG_*).
NODE_FLAG_FROZEN = 1 << 9
NODE_FLAG_HIDDEN = 1 << 20
BASE_NODE_FLAGS = 0x1000        # 256/344.


def node_object(node, handle, parent_obj, object_obj, material_obj, layer_obj) -> MaxObject:
    """The node object for model ``node``; ``handle`` is its node handle (1, 2, ...)."""
    t = node.transform
    controller = prs(t.position, t.rotation, t.scale)
    obj = MaxObject(classes.NODE, num_refs=NODE_REF_SLOTS, label="Node " + node.name)
    obj.ref(SLOT_CONTROLLER, controller)
    obj.ref(SLOT_OBJECT, object_obj)
    obj.ref(SLOT_MATERIAL, material_obj)
    obj.ref(SLOT_LAYER, layer_obj)
    flags = BASE_NODE_FLAGS
    if node.hidden:
        flags |= NODE_FLAG_HIDDEN
    if node.frozen:
        flags |= NODE_FLAG_FROZEN
    off = node.object_offset
    r, g, b = (max(0, min(255, int(c))) for c in node.wire_color)
    obj.chunks = [
        leaf(0x09CE, u32(700)),                                 # 14,680/14,680
        lambda index_of: leaf(0x0960, u32(index_of(parent_obj), flags)),
        leaf(0x0962, text(node.name)),
        leaf(0x09BA),                                           # User properties: empty (4,846/5,113)
        leaf(0x0963, u32(0x10, 0x10)),                          # 338/344
        leaf(0x096A, f32(*off.position)),
        leaf(0x096B, f32(*max_quaternion(off.rotation))),
        leaf(0x096C, f32(*off.scale, 0.0, 0.0, 0.0, 1.0)),
        leaf(0x0974, u8(r, g, b, 0)),
        leaf(0x099C, u32(0x0F00D600)),                          # 295/344
        leaf(0x0A28, u32(0, 0)),                                # 14,680/14,680
        leaf(0x0978),                                           # 474/882 sampled
        leaf(0x0A32, u32(handle)),                              # Node handle: 1, 2, 3, ... in file order
        leaf(0x0ABE, u32(0)),
        leaf(0x0AC3, u32(1)),
        # Display settings record (21 bytes), the most common one (1,841/5,113).
        cont(0x0AD2, leaf(0x0006, bytes((0, 0, 1, 0, 0, 1)) + f32(36.0) + bytes((0, 1, 1, 1, 1, 0, 0)) + f32(1.0))),
        cont(0x0B22, leaf(0x0100, u32(0)), leaf(0x0101, u8(1)), leaf(0x0102, u8(1)), leaf(0x0103, f32(2.0)),
             leaf(0x0104, f32(20.0)), leaf(0x0105, bytes((6, 0))), leaf(0x0106, u8(1)), leaf(0x0107, u32(0)),
             leaf(0x0108, u8(0)), leaf(0x0109, u8(0))),         # All 5,113 sampled (0x0104 = 20.0 in 5,051)
        cont(0x0ADC, leaf(0x0001, bytes((0, 0))), leaf(0x0002, u8(1))),
        cont(0x0AF0, leaf(0x0001, u32(0)), leaf(0x0002, u32(1)), leaf(0x0003, u32(3)), leaf(0x0004, u32(2)),
             leaf(0x0005, u32(0)), leaf(0x0006, u32(0x7149F2CA, 0x7149F2CA, 0xF149F2CA, 0xF149F2CA)),
             leaf(0x0007, u32(0)), leaf(0x0008, u32(0))),       # 0x0002: 1 on 2,908 of 5,113; the rest all
        cont(0x0B0E, cont(0x0001, *[leaf(t, v) for t, v in (
            (0x0002, u32(0)), (0x0020, b""), (0x0018, u32(0xFFFFFFFF)), (0x0005, u32(0)), (0x0006, u32(0)),
            (0x0007, u32(3)), (0x0008, u32(1)), (0x001F, u32(0)), (0x0009, u32(1)), (0x000A, f32(10.0)),
            (0x000B, u32(1)), (0x000C, u32(0)), (0x000D, u32(0)), (0x0012, u32(1)), (0x0013, f32(1.0, 0.0, 0.0)),
            (0x0014, f32(-10.0)), (0x0015, f32(10.0)), (0x0016, u32(0)), (0x0017, u32(0)), (0x001A, u32(0)),
            (0x001B, u32(4)), (0x001C, u32(1)), (0x001D, u32(1)), (0x001E, u32(1)))])),     # All 5,113 sampled
        leaf(0x0B4A, u8(0)),                                    # 5,107/5,113
        cont(0x0B54, cont(0x0001, leaf(0x0002, u32(0)))),
        cont(0x0B5E, cont(0x0001, leaf(0x0005, u32(2)))),       # 839/882
        leaf(0x0B68, u32(0)),
    ]
    return obj


def dummy_object(size) -> MaxObject:
    """A Dummy helper (class 0x876234 / 0x50) whose box is ``size`` wide, centred on the pivot."""
    obj = MaxObject(classes.DUMMY, label="Dummy")
    h = size / 2.0
    # Corpus (198 Dummies of the 2015 files): 0x09EC = 0, 0x09ED = the box (min xyz, max xyz), 0x09EE = 12 bytes
    # (0.0549, 1.0, 0.0078 in 104 of 198; not decoded).
    obj.chunks = [leaf(0x09EC, u32(0)), leaf(0x09ED, f32(-h, -h, -h, h, h, h)),
                  leaf(0x09EE, bytes.fromhex("e2e0603d0000803f8180003c"))]
    return obj
