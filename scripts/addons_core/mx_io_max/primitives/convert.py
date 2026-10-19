# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Decoded primitive parameters (``maxfile`` ``PrimitiveData``) to the parameters of the live-primitive builder
(``mx_primitives.geometry``).

- Lengths are converted from scene units to metres, so a live primitive edited later keeps real-world sizes.
- Kinds the installed builder doesn't have yet are rebuilt as the nearest kind it has (Chamfer Box as a Box, ...)
  and reported as approximated.
- Parameters the builder doesn't accept are dropped (and listed in the note).

No Blender dependency: ``available`` is the builder's ``geometry.PARAMETERS`` table.
"""

__all__ = (
    "builder_params",
    "is_length",
)

# Max kind -> the builder's name for the same primitive.
KIND_ALIASES = {
    "TEAPOT": "TEST_SHAPE",
}

# Max kind -> (stand-in kind, parameter renames) when the builder lacks the kind.
FALLBACKS = {
    "CHAMFERBOX": ("BOX", {}),
    "CHAMFERCYL": ("CYLINDER", {}),
    "CAPSULE": ("CYLINDER", {}),
    "TORUS_KNOT": ("TORUS", {"cross_section_radius": "radius2", "radius": "radius1"}),
}

# Parameter names holding distances contain one of these words (angles, counts, fractions and flags don't).
LENGTH_WORDS = ("length", "width", "height", "depth", "radius", "fillet", "thickness", "size")


def is_length(name):
    return any(word in name for word in LENGTH_WORDS)


def builder_params(kind, params, available, unit_scale=1.0):
    """
    ``(builder kind or None, parameters, notes)`` for a decoded primitive.

    :arg kind: ``PrimitiveData.kind``.
    :arg params: ``PrimitiveData.params`` (Max units: scene units, radians).
    :arg available: the builder's ``geometry.PARAMETERS`` (kind -> default parameters).
    :arg unit_scale: metres per scene unit; lengths are multiplied by it (1.0 keeps scene units).
    """
    notes = []
    target = KIND_ALIASES.get(kind, kind)
    renames = {}
    if target not in available:
        fallback = FALLBACKS.get(kind)
        if fallback is None or fallback[0] not in available:
            return None, {}, ["no live primitive for {:s}".format(kind)]
        target, renames = fallback
        notes.append("{:s} rebuilt as a {:s} (approximation)".format(kind, target.title()))
    accepted = available[target]
    out = {}
    dropped = []
    for name, value in params.items():
        name = renames.get(name, name)
        if name not in accepted:
            dropped.append(name)
            continue
        default = accepted[name]
        if isinstance(default, float) and not isinstance(default, bool) and is_length(name):
            value = float(value) * unit_scale
        out[name] = value
    if dropped and target == KIND_ALIASES.get(kind, kind):
        notes.append("{:s} parameters not rebuilt: {:s}".format(kind, ", ".join(sorted(dropped))))
    return target, out, notes
