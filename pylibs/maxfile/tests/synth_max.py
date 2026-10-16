# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Synthetic ``.max``-like fixtures, built in code.

**These are not real .max files.** They follow the layouts described in ``docs/format/overview.md``, which come
from the prior-art importer and have not been verified on real files. Tests built on them check that our parser
implements those *documented assumptions*; they say nothing about whether the assumptions are right. That is
what the corpus tests (``test_corpus.py``) are for.

Where the overview doesn't specify something (for example the chunk type of a class-directory entry or of the
Scene's top-level container), the builders use arbitrary placeholder values that the parser must not depend on.
"""

import gzip
import struct

from cfb_writer import build_cfb

# Placeholder chunk types for things overview.md doesn't specify; the parser must ignore them.
ANY_CLASS_ENTRY = 0x2040
ANY_DLL_ENTRY = 0x2038
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
    """Encode (w, x, y, z) in the documented file order: the reader maps (q3, q2, q1, q0) to (w, x, y, z)."""
    return f32(z, y, x, w)


class SceneBuilder:
    """Collects classes, DLLs and scene objects and writes the streams."""

    def __init__(self):
        self.classes = []
        self.dlls = []
        self.objects = []

    def dll(self, *strings_by_type):
        """Add a DLL entry; arguments are (chunk_type, text) pairs. Returns its index."""
        self.dlls.append(cont(ANY_DLL_ENTRY, *(leaf(t, text(s)) for t, s in strings_by_type)))
        return len(self.dlls) - 1

    def cls(self, name, class_id, superclass_id, dll_index=NULL):
        """Add a class-directory entry (overview.md §2.3). ``class_id`` is (a, b). Returns the class index."""
        a, b = class_id
        self.classes.append(cont(
            ANY_CLASS_ENTRY,
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
            "DllDirectory": b"".join(self.dlls),
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
