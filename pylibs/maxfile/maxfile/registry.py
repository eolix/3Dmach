# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Class-ID registry: what we know about Max classes, and which decoder reads each one.

Two tables:

- **Known classes** (:func:`known_class`): class ID -> human name and category. Seeded from the class IDs listed
  in ``docs/format/overview.md``, which come from the prior-art importer ``io_scene_max`` and are **unverified**.
  The file's own class directory also stores a name for every class; the registry name is what *we* call it.
- **Decoders** (:func:`decoder`, :func:`find_decoder`): functions that turn a scene object of a class into plain
  data. They live one module per class family in :mod:`maxfile.objects` and register themselves with the
  :func:`decoder` decorator. :func:`registered_decoders` lists them (input for the generated supported-features
  matrix, ROADMAP Phase 4).

Max class IDs may only be unique within a superclass, so both tables accept an optional superclass ID. A lookup
prefers an entry registered for the exact superclass, then one registered without a superclass.

A decoder is called as ``function(obj, ctx)`` where ``obj`` is a :class:`maxfile.scene.SceneObject` and ``ctx``
a :class:`maxfile.scene.DecodeContext` (to follow references and decode other objects). It returns plain data,
or raises :class:`maxfile.errors.DecodeError` when the object's data doesn't match what it expects.
"""

__all__ = (
    "KnownClass",
    "DecoderInfo",
    "as_class_id",
    "register_class",
    "known_class",
    "known_classes",
    "decoder",
    "find_decoder",
    "registered_decoders",
)

import dataclasses
from collections.abc import Callable

from .classes import ClassID

# Where the seed entries come from.
SOURCE_OVERVIEW = "io_scene_max 1.9.2, via docs/format/overview.md"


def as_class_id(value) -> ClassID:
    """Accept a :class:`ClassID`, an ``(a, b)`` pair, or an int in the 64-bit form (``a`` in the low half)."""
    if isinstance(value, ClassID):
        return value
    if isinstance(value, tuple) and len(value) == 2:
        return ClassID(int(value[0]), int(value[1]))
    if isinstance(value, int) and 0 <= value < (1 << 64):
        return ClassID.from_u64(value)
    raise TypeError("not a class ID: {!r}".format(value))


@dataclasses.dataclass(frozen=True, slots=True)
class KnownClass:
    """A class we have a name for."""
    class_id: ClassID
    name: str
    category: str                   # "node", "controller", "material", "geometry", "camera", "light", ...
    superclass_id: int | None = None
    source: str = SOURCE_OVERVIEW
    verified: bool = False          # True once checked against real files.


@dataclasses.dataclass(frozen=True, slots=True)
class DecoderInfo:
    """A registered decoder."""
    class_ids: tuple[ClassID, ...]
    name: str                       # What the decoder reads, e.g. "Bezier Position".
    kind: str                       # What it returns, dotted, e.g. "controller.position".
    function: Callable = dataclasses.field(repr=False)
    module: str = ""
    superclass_id: int | None = None
    verified: bool = False          # True once the layout it relies on is checked against real files.
    description: str = ""


# (ClassID, superclass or None) -> entry.
_KNOWN: dict[tuple[ClassID, int | None], KnownClass] = {}
_DECODERS: dict[tuple[ClassID, int | None], DecoderInfo] = {}
_decoders_loaded = False


def register_class(class_id, name: str, category: str, superclass_id: int | None = None,
                   source: str = SOURCE_OVERVIEW, verified: bool = False) -> KnownClass:
    """Add or replace a known class."""
    entry = KnownClass(as_class_id(class_id), name, category, superclass_id, source, verified)
    _KNOWN[(entry.class_id, superclass_id)] = entry
    return entry


def _lookup(table, class_id, superclass_id):
    if class_id is None:
        return None
    class_id = as_class_id(class_id)
    if superclass_id is not None:
        found = table.get((class_id, superclass_id))
        if found is not None:
            return found
    return table.get((class_id, None))


def known_class(class_id, superclass_id: int | None = None) -> KnownClass | None:
    """The known class for ``class_id`` (and ``superclass_id`` when given), or None."""
    return _lookup(_KNOWN, class_id, superclass_id)


def known_classes() -> list[KnownClass]:
    """All known classes, sorted by category then name."""
    return sorted(_KNOWN.values(), key=lambda k: (k.category, k.name, k.class_id))


def decoder(*class_ids, kind: str, name: str | None = None, superclass_id: int | None = None,
            verified: bool = False):
    """
    Decorator registering ``function(obj, ctx)`` as the decoder for one or more class IDs.

    Example::

        @decoder(0x2008, kind="controller.position", name="Bezier Position")
        def bezier_position(obj, ctx):
            ...
    """
    if not class_ids:
        raise TypeError("decoder() needs at least one class ID")
    ids = tuple(as_class_id(c) for c in class_ids)

    def register(function):
        info = DecoderInfo(
            class_ids=ids,
            name=name or function.__name__,
            kind=kind,
            function=function,
            module=function.__module__,
            superclass_id=superclass_id,
            verified=verified,
            description=(function.__doc__ or "").strip().split("\n")[0],
        )
        for class_id in ids:
            key = (class_id, superclass_id)
            existing = _DECODERS.get(key)
            if existing is not None and existing.function is not function:
                raise ValueError("class {:s} already has a decoder ({:s}.{:s})".format(
                    str(class_id), existing.module, existing.function.__name__))
            _DECODERS[key] = info
        return function
    return register


def load_decoders():
    """Import every module in :mod:`maxfile.objects` so their decoders are registered (idempotent)."""
    global _decoders_loaded
    if not _decoders_loaded:
        _decoders_loaded = True
        from . import objects
        objects.import_all()


def find_decoder(class_id, superclass_id: int | None = None) -> DecoderInfo | None:
    """The decoder for a class, or None."""
    load_decoders()
    return _lookup(_DECODERS, class_id, superclass_id)


def registered_decoders() -> list[DecoderInfo]:
    """Every registered decoder once, sorted by kind then name."""
    load_decoders()
    unique = {id(info): info for info in _DECODERS.values()}
    return sorted(unique.values(), key=lambda d: (d.kind, d.name))


def _seed():
    # Everything below is unverified (overview.md §4, §4.1, §5, §6.1): names and categories as the prior-art
    # importer uses them. Integers are in the 64-bit form of overview.md (first word in the low half).
    seed = (
        # §4 nodes. The node test also requires superclass 0x1.
        (0x1, "Node", "node", 0x1),
        # §4.1 transform controllers.
        (0x2005, "Position/Rotation/Scale", "controller", None),
        (0xFFEE238A118F7E02, "Position XYZ", "controller", None),
        (0x2008, "Bezier Position", "controller", None),
        (0x442312, "TCB Position", "controller", None),
        (0x4B4B1002, "Position List / Scale List", "controller", None),
        (0x2012, "Euler XYZ", "controller", None),
        (0x442313, "TCB Rotation", "controller", None),
        (0x3A90416731381913, "Rotation Wire", "controller", None),
        (0x4B4B1003, "Rotation List", "controller", None),
        (0xFEEE238B118F7C01, "Scale XYZ", "controller", None),
        (0x2010, "Bezier Scale", "controller", None),
        (0x442315, "TCB Zoom", "controller", None),
        (0x2007, "Bezier Float", "controller", None),
        (0x71F11549498702E7, "Float Wire", "controller", None),
        (0x9154, "Biped slave control", "controller", None),
        # §5 materials.
        (0x0002, "Standard", "material", None),
        (0x0006, "Legacy (per io_scene_max)", "material", None),
        (0x0200, "Multi/Sub-Object", "material", None),
        (0xDEADC0013D6B1CEC, "Physical Material", "material", None),
        (0x7034695C37BF3F2F, "VRayMtl", "material", None),
        (0x11731B4B6066686A, "VRay2SidedMtl", "material", None),
        (0x448931DD70BE6506, "CoronaMtl (legacy)", "material", None),
        (0x871517206912AB89, "CoronaPhysicalMtl", "material", None),
        (0x8425554E65486584, "CoronaLayeredMtl", "material", None),
        (0x44CFDE95BEC41C73, "CoronaSkinMtl", "material", None),
        (0xCA41F54622C05DD6, "CoronaHairMtl", "material", None),
        (0x62F74B4C7E73161F, "Arnold Standard Surface", "material", None),
        (0x329B106E27190FF4, "Raytrace", "material", None),
        (0x4A16365470B05735, "Architectural", "material", None),
        (0x0000000046EE536A, "Shellac", "material", None),
        # §6.1 geometry and other objects.
        (0x192F60981BF8338D, "Editable Poly", "geometry", None),
        (0x000000005D21369A, "PolyMeshObject", "geometry", None),
        (0x00000000E44F10B3, "Editable Mesh", "geometry", None),
        (0x10, "Box", "geometry", None),
        (0x11, "Sphere", "geometry", None),
        (0x12, "Cylinder", "geometry", None),
        (0x14, "Primitive 0x14 (read as Box by io_scene_max)", "geometry", None),
        (0x16, "Primitive 0x16 (meaning unknown)", "geometry", None),
        (0x19, "Primitive 0x19 (read as Box by io_scene_max)", "geometry", None),
        (0x20, "Torus", "geometry", None),
        (0x00000000A86C23DD, "Cone", "geometry", None),
        (0x77566F65081F1DFC, "Plane", "geometry", None),
        (0x2032, "Derived object? (io_scene_max: \"shell\")", "geometry", None),
        (0x2033, "Derived object? (io_scene_max: \"shell\")", "geometry", None),
        (0x01BBAC5F7BC209AF, "Boolean", "geometry", None),
        (0x0000000000876234, "Dummy", "helper", None),
        (0x9125, "Biped object", "helper", None),
        (0x1002, "Camera", "camera", None),
        (0x1020, "Camera (target?)", "camera", None),
        (0x1011, "Omni light", "light", None),
        (0x1013, "Free Direct light", "light", None),
        (0x1040, "Line", "shape", None),
        (0x1065, "Rectangle", "shape", None),
        (0x1097, "Ellipse", "shape", None),
        (0x1999, "Circle", "shape", None),
    )
    for class_id, name, category, superclass_id in seed:
        register_class(class_id, name, category, superclass_id)


_seed()
