# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Modifier-stack wrappers (``docs/format/overview.md`` §6.1, classes 0x2032 / 0x2033).

The overview calls these "probably the modifier-stack holder" (a "derived object"): the base object is the
**last** reference and the modifiers come before it. Unverified ("To verify" #9), including:

- that every other reference is a modifier (some may be per-modifier context data);
- which end is the top of the stack. We assume the references run **from the top of the stack down to the
  base**, the order Max's modifier list is shown in, with the base last. :attr:`ModifierStack.modifiers` is in
  that order; :meth:`ModifierStack.bottom_up` gives the order to apply them.

Use :meth:`maxfile.scene.Scene.resolve_geometry` to get a node's base object and modifiers through any number
of wrappers.
"""

__all__ = (
    "ModifierRef",
    "ModifierStack",
)

import dataclasses

from ..registry import decoder


@dataclasses.dataclass
class ModifierRef:
    object_index: int
    class_name: str
    enabled: bool | None = None     # Not known from the file yet.


@dataclasses.dataclass
class ModifierStack:
    base: int | None                # Object index of the base object (the last reference).
    modifiers: list[ModifierRef]    # Top of the stack first (assumption, see the module docstring).

    def bottom_up(self) -> list[ModifierRef]:
        """The modifiers in the order they apply to the base object."""
        return list(reversed(self.modifiers))


@decoder(0x2032, 0x2033, kind="geometry.modifier_stack", name="Derived object (modifier stack)")
def derived_object(obj, ctx):
    """Base object (last reference) and modifiers (the other references)."""
    refs = ctx.refs(obj)
    if not refs:
        ctx.warn("object {:d} ({:s}): modifier stack without references".format(obj.index, obj.class_label()))
        return ModifierStack(None, [])
    # Unverified (overview.md §6.1): base = last reference, modifiers = the others, top of the stack first.
    *mods, (_slot, base) = refs
    return ModifierStack(base.index, [ModifierRef(o.index, o.class_label()) for _slot, o in mods])
