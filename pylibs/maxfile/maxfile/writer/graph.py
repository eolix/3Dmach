# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
The object graph of the ``Scene`` stream, and its serialisation with the class and DLL directories.

Every scene object is a :class:`MaxObject`: a class (:class:`ClassDef`), reference slots pointing at other
objects, and body chunks. Indices are only known once the whole graph is ordered, so a body chunk may be a
callable ``f(index_of) -> bytes`` that is evaluated at the end (node parents, parameter block owners).

Order (as in real files, ``docs/design/max-writer.md``): depth-first from the scene object, an object's
references (slot order) before the object itself; objects can name *followers* that come right after them (the
root node is followed by the scene's nodes, parents first). Class indices are given in order of first use, DLL
indices likewise (the corpus files are ordered that way).
"""

__all__ = ("ClassDef", "MaxObject", "SceneGraph", "BUILTIN", "BUILTIN_ALT")

import dataclasses

from .chunks import cont, leaf, text, u32

# DLL index of classes built into the core (overview.md §2.3).
BUILTIN = 0xFFFFFFFF
BUILTIN_ALT = 0xFFFFFFFE
CHUNK_REFS_DENSE = 0x2034
CHUNK_REFS_SPARSE = 0x2035
# Corpus: every object with a reference chunk follows it with 0x204B holding the single byte 0x2E (all objects of
# the 2015 files that have a 0x2034 / 0x2035 chunk).
CHUNK_REFS_END = 0x204B
NULL = 0xFFFFFFFF


@dataclasses.dataclass(frozen=True)
class ClassDef:
    """A class as the class directory stores it."""
    name: str
    class_id: int                   # 64-bit form (a = low word, overview.md §2.3).
    superclass: int
    dll: tuple | None = None        # (file name, description), None for built-in classes.
    builtin_index: int = BUILTIN    # dll_index value for built-in classes.

    @property
    def key(self):
        return (self.class_id, self.superclass)


class MaxObject:
    """One scene object."""

    def __init__(self, cls: ClassDef, chunks=(), refs=None, num_refs=None, label=None):
        self.cls = cls
        self.chunks = list(chunks)
        self.refs = dict(refs or {})        # slot -> MaxObject (or None)
        self.num_refs = num_refs            # Number of reference slots (default: highest used slot + 1).
        self.followers = []                 # Objects written right after this one (e.g. nodes after the root).
        self.label = label or cls.name

    def ref(self, slot, obj):
        self.refs[slot] = obj
        return obj

    def slot_count(self):
        if self.num_refs is not None:
            return self.num_refs
        used = [s for s, o in self.refs.items() if o is not None]
        return max(used) + 1 if used else 0

    def __repr__(self):
        return "<MaxObject {:s}>".format(self.label)


def _ref_chunk(obj, index_of):
    """0x2034 (dense) or 0x2035 (sparse), whichever is smaller.

    Corpus rule: with n slots and k of them used, real files use the sparse form exactly when 4 + 8k < 4n (Nodes:
    16 slots, sparse; Position/Rotation/Scale: 3 of 3, dense; Block Control: 1 of 3, a tie, dense; Texmaps: 48
    slots, sparse). No chunk when the class has no slots.
    """
    n = obj.slot_count()
    if n == 0:
        return []
    used = sorted((s, index_of(o)) for s, o in obj.refs.items() if o is not None)
    if 4 + 8 * len(used) < 4 * n:
        values = [n]
        for slot, index in used:
            values.extend((slot, index))
        chunk = leaf(CHUNK_REFS_SPARSE, u32(*values))
    else:
        dense = [NULL] * n
        for slot, index in used:
            dense[slot] = index
        chunk = leaf(CHUNK_REFS_DENSE, u32(*dense))
    return [chunk, leaf(CHUNK_REFS_END, b"\x2E")]


class SceneGraph:
    """Orders the graph from its top object and writes the Scene, ClassDirectory3 and DllDirectory streams."""

    def __init__(self, top: MaxObject):
        self.top = top
        self.order = self._order(top)
        self.index = {id(o): i for i, o in enumerate(self.order)}
        self.classes = []
        self.class_index = {}
        self.dlls = []
        self.dll_index = {}
        for obj in self.order:
            key = obj.cls.key
            if key not in self.class_index:
                self.class_index[key] = len(self.classes)
                self.classes.append(obj.cls)
                if obj.cls.dll is not None and obj.cls.dll[0].lower() not in self.dll_index:
                    self.dll_index[obj.cls.dll[0].lower()] = len(self.dlls)
                    self.dlls.append(obj.cls.dll)

    @staticmethod
    def _order(top):
        order = []
        done = set()
        visiting = set()
        # Iterative post-order: (object, stage) frames.
        stack = [(top, 0)]
        while stack:
            obj, stage = stack.pop()
            key = id(obj)
            if stage == 0:
                if key in done:
                    continue
                if key in visiting:
                    raise ValueError("reference cycle through {!r}".format(obj))
                visiting.add(key)
                stack.append((obj, 1))
                for slot in sorted(obj.refs, reverse=True):
                    child = obj.refs[slot]
                    if child is not None and id(child) not in done:
                        stack.append((child, 0))
            else:
                visiting.discard(key)
                if key in done:
                    continue
                done.add(key)
                order.append(obj)
                for follower in reversed(obj.followers):
                    stack.append((follower, 0))
        return order

    def index_of(self, obj) -> int:
        if obj is None:
            return NULL
        return self.index[id(obj)]

    def objects_of(self, name):
        return [o for o in self.order if o.cls.name == name]

    def scene_stream(self, container_type) -> bytes:
        parts = []
        for obj in self.order:
            body = _ref_chunk(obj, self.index_of)
            for chunk in obj.chunks:
                body.append(chunk(self.index_of) if callable(chunk) else chunk)
            parts.append(cont(self.class_index[obj.cls.key], *body))
        return cont(container_type, *parts)

    def class_directory_stream(self) -> bytes:
        """``ClassDirectory3``: one 0x2040 entry per class (overview.md §2.3)."""
        parts = []
        for cls in self.classes:
            dll = self.dll_index[cls.dll[0].lower()] if cls.dll is not None else cls.builtin_index
            a, b = cls.class_id & 0xFFFFFFFF, cls.class_id >> 32
            parts.append(cont(0x2040, leaf(0x2060, u32(dll, a, b, cls.superclass)), leaf(0x2042, text(cls.name))))
        return b"".join(parts)

    def dll_directory_stream(self, header) -> bytes:
        """``DllDirectory``: the 0x21C0 version header, then one 0x2038 entry per DLL (overview.md §2.4)."""
        parts = [leaf(0x21C0, u32(header))]
        for file_name, description in self.dlls:
            parts.append(cont(0x2038, leaf(0x2039, text(description)), leaf(0x2037, text(file_name))))
        return b"".join(parts)
