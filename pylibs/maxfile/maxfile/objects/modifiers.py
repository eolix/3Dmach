# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Derived objects: a modifier stack on top of a base object (``docs/format/overview.md`` §6.1, §6.5).

Scene objects whose chunk type is 0x2032 (or 0x2033) are derived objects; these chunk types are not in the class
directory (see :data:`maxfile.registry.DERIVED_OBJECT`). Verified on all 3,019 derived objects of the local corpus:

- the references (``0x2034``, contiguous slots) are the modifiers, **top of the stack first**, and the base object
  last. Evidence: modifiers that turn a shape into a mesh (Extrude, Lathe, Sweep, Edit Spline) always sit directly
  above a shape base and below every mesh modifier (e.g. ``UVW Map, Extrude, Edit Spline, <Line>``), Skin is above
  Morpher, and the per-modifier input bounding boxes below grow from the bottom up (a flat Star has z = 0 under
  Extrude, the extruded height above it);
- the base may itself be a derived object (nested stacks; their modifiers sit below the outer ones);
- there is one ``0x2500`` container per modifier, in the same order, holding the modifier's context: ``0x2510``
  (a 4x3 matrix as four rows of three floats, then a u32), ``0x2511`` (the bounding box of the modifier's input,
  min then max), optionally ``0x2512`` (the modifier's per-object data) and ``0x2513`` (u32 flags).

Use :meth:`maxfile.scene.Scene.resolve_geometry` to get a node's base object and modifiers through any number
of derived objects.
"""

__all__ = (
    "ModifierRef",
    "ModifierStack",
)

import dataclasses
import struct

from ..registry import DERIVED_OBJECT, DERIVED_OBJECT_WSM, decoder

CHUNK_MOD_CONTEXT = 0x2500
CHUNK_CONTEXT_TM = 0x2510       # f32[12] rows (x axis, y axis, z axis, translation), u32
CHUNK_CONTEXT_BOX = 0x2511      # f32[6] min, max
CHUNK_CONTEXT_FLAGS = 0x2513    # u32, meaning not known


@dataclasses.dataclass
class ModifierRef:
    object_index: int
    class_name: str
    enabled: bool | None = None     # Not known from the derived object; modifier decoders may know it.
    context_tm: tuple | None = None
    """The modifier context matrix: four rows (x axis, y axis, z axis, translation) of three floats. Guess: the
    transform from the object to the modifier's gizmo space (identity for most modifiers)."""
    context_bbox: tuple | None = None
    """Bounding box of the modifier's input, ``((min x, y, z), (max x, y, z))``, in object space (verified on
    stacks over flat shapes: the bottom modifier's box is flat)."""
    context_flags: int | None = None    # Raw u32 of 0x2513.


@dataclasses.dataclass
class ModifierStack:
    base: int | None                # Object index of the base object (the last reference).
    modifiers: list[ModifierRef]    # Top of the stack first (verified, see the module docstring).

    def bottom_up(self) -> list[ModifierRef]:
        """The modifiers in the order they apply to the base object."""
        return list(reversed(self.modifiers))


def _context(chunk, ref):
    tm = chunk.find(CHUNK_CONTEXT_TM)
    if tm is not None and tm.payload_size >= 48:
        values = struct.unpack_from("<12f", tm.data)
        ref.context_tm = tuple(tuple(values[i:i + 3]) for i in range(0, 12, 3))
    box = chunk.find(CHUNK_CONTEXT_BOX)
    if box is not None and box.payload_size >= 24:
        values = struct.unpack_from("<6f", box.data)
        ref.context_bbox = (values[:3], values[3:])
    flags = chunk.find(CHUNK_CONTEXT_FLAGS)
    if flags is not None and flags.payload_size >= 4:
        ref.context_flags = struct.unpack_from("<I", flags.data)[0]


@decoder(DERIVED_OBJECT, DERIVED_OBJECT_WSM, kind="geometry.modifier_stack", name="Derived Object (modifier stack)",
         verified=True)
def derived_object(obj, ctx):
    """Base object (last reference) and modifiers (the other references, top of the stack first)."""
    refs = ctx.refs(obj)
    if not refs:
        ctx.warn("object {:d} ({:s}): modifier stack without references".format(obj.index, obj.class_label()))
        return ModifierStack(None, [])
    *mods, (_slot, base) = refs
    modifiers = [ModifierRef(o.index, o.class_label()) for _slot, o in mods]
    contexts = obj.chunk.find_all(CHUNK_MOD_CONTEXT)
    if len(contexts) == len(modifiers):
        for ref, chunk in zip(modifiers, contexts):
            if chunk.is_container:
                _context(chunk, ref)
    else:
        ctx.warn("object {:d} ({:s}): {:d} modifier context(s) for {:d} modifier(s)".format(
            obj.index, obj.class_label(), len(contexts), len(modifiers)))
    return ModifierStack(base.index, modifiers)
