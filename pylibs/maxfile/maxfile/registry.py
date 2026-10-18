# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Class-ID registry: what we know about Max classes, and which decoder reads each one.

Two tables:

- **Known classes** (:func:`known_class`): (class ID, superclass ID) -> name and category. Seeded from the class
  directories of the local corpus: the names are the ones Max itself stores next to each class.
  :func:`category_of` classifies any class, known or not, by its superclass.
- **Decoders** (:func:`decoder`, :func:`find_decoder`): functions that turn a scene object of a class into plain
  data. They live one module per class family in :mod:`maxfile.objects` and register themselves with the
  :func:`decoder` decorator. :func:`registered_decoders` lists them (input for the generated supported-features
  matrix, ROADMAP Phase 4).

Class IDs are only unique within a superclass (verified: 0x2 is RootNode in superclass 0x1 and the Standard material
in superclass 0xC00; 0x10 is Box in 0x10 and Bend in 0x810), so both tables are keyed by (class ID, superclass ID).
A lookup prefers an entry registered for the exact superclass, then one registered without a superclass (used only
for the derived-object pseudo-classes, which have none).

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
    "SUPERCLASSES",
    "category_of",
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


# Superclass IDs and what they hold. Verified on the local corpus: every class directory entry's superclass against
# the class names stored next to it (e.g. 0x30 holds "Omni", "Target Spot", "Free Light", ...).
SUPERCLASSES = {
    0x0001: "node",                 # Node, RootNode
    0x0008: "paramblock",           # ParamBlock (old parameter blocks)
    0x0082: "paramblock2",          # ParamBlock2
    0x0010: "geometry",             # Editable Poly / Mesh, primitives, Bone, particle systems, ...
    0x0020: "camera",
    0x0030: "light",
    0x0040: "shape",                # Line, Rectangle, Circle, Text, SplineShape, ...
    0x0050: "helper",               # Dummy, Point, Grid, Tape, ...
    0x0060: "system",               # Biped, Daylight, ...
    0x0810: "modifier",             # Object-space modifiers.
    0x0820: "modifier.world_space",
    0x0830: "space_warp",
    0x0C00: "material",
    0x0C10: "texmap",
    0x1080: "material.texmaps",     # A Standard material's map list ("Texmaps").
    0x10B0: "shader",               # Standard material shaders: Blinn, Phong, Anisotropic, ...
    0x10F0: "layer",
    0x1160: "custom_attribute",
    0x9003: "controller.float",
    0x9005: "controller.point3",
    0x9008: "controller.matrix3",   # Position/Rotation/Scale, Look At, ...
    0x900B: "controller.position",
    0x900C: "controller.rotation",
    0x900D: "controller.scale",
}

# Classes that never appear in the class directory: scene objects whose chunk type is beyond the class directory use
# the chunk type itself as their class (verified: 2,952 objects of type 0x2032 and 67 of type 0x2033 in the corpus,
# all referenced from slot 1 of nodes or of other derived objects; no other such chunk types occur).
DERIVED_OBJECT = 0x2032
DERIVED_OBJECT_WSM = 0x2033

SOURCE_CORPUS = "class directories of the local corpus (623 files, Max 2008-2018)"


def category_of(superclass_id) -> str | None:
    """What a superclass holds (``"geometry"``, ``"light"``, ``"modifier"``, ...), or None when unknown."""
    return SUPERCLASSES.get(superclass_id)


def _seed():
    # Names are the ones Max stores in the class directory. Every entry was checked on the corpus: stored under this
    # class ID, superclass and name. Integers are in the 64-bit form (first word in the low half).
    seed = (
        (0x1, 0x1, "Node", "node"),
        (0x2, 0x1, "RootNode", "node"),
        (0x82, 0x82, "ParamBlock2", "paramblock2"),
        (0x8, 0x8, "ParamBlock", "paramblock"),
        # Transform and value controllers.
        (0x2005, 0x9008, "Position/Rotation/Scale", "controller.matrix3"),
        (0x2006, 0x9008, "Look At", "controller.matrix3"),
        (0x9154, 0x9008, "BipSlave Control", "controller.matrix3"),
        (0xFFEE238A118F7E02, 0x900B, "Position XYZ", "controller.position"),
        (0x2008, 0x900B, "Bezier Position", "controller.position"),
        (0x442312, 0x900B, "TCB Position", "controller.position"),
        (0x4B4B1002, 0x900B, "Position List", "controller.position"),
        (0x2012, 0x900C, "Euler XYZ", "controller.rotation"),
        (0x442313, 0x900C, "TCB Rotation", "controller.rotation"),
        (0x4B4B1003, 0x900C, "Rotation List", "controller.rotation"),
        (0x3A90416731381913, 0x900C, "Rotation Wire", "controller.rotation"),
        (0xFEEE238B118F7C01, 0x900D, "ScaleXYZ", "controller.scale"),
        (0x2010, 0x900D, "Bezier Scale", "controller.scale"),
        (0x442315, 0x900D, "TCB Scale", "controller.scale"),
        (0x4B4B1004, 0x900D, "Scale List", "controller.scale"),
        (0x2007, 0x9003, "Bezier Float", "controller.float"),
        (0x2001, 0x9003, "Linear Float", "controller.float"),
        (0x4B4B1000, 0x9003, "Float List", "controller.float"),
        (0x71F11549498702E7, 0x9003, "Float Wire", "controller.float"),
        (0x938F3E43984B8D27, 0x9003, "On/Off", "controller.float"),
        (0x200A, 0x9005, "Bezier Point3", "controller.point3"),
        (0x2011, 0x9005, "Bezier Color", "controller.point3"),
        (0x4B4B1001, 0x9005, "Point3 List", "controller.point3"),
        # Geometry.
        (0x192F60981BF8338D, 0x10, "Editable Poly", "geometry"),
        (0x5D21369A, 0x10, "PolyMeshObject", "geometry"),
        (0xE44F10B3, 0x10, "Editable Mesh", "geometry"),
        (0x9, 0x10, "MeshObject", "geometry"),
        (0x1030, 0x10, "Editable Patch", "geometry"),
        (0x10, 0x10, "Box", "geometry"),
        (0x11, 0x10, "Sphere", "geometry"),
        (0x12, 0x10, "Cylinder", "geometry"),
        (0x20, 0x10, "Torus", "geometry"),
        (0xA86C23DD, 0x10, "Cone", "geometry"),
        (0x77566F65081F1DFC, 0x10, "Plane", "geometry"),
        (0x7F9E00000000, 0x10, "GeoSphere", "geometry"),
        (0xACAD26D9ACAD13D3, 0x10, "Teapot", "geometry"),
        (0x7B21, 0x10, "Tube", "geometry"),
        (0x720, 0x10, "Torus Knot", "geometry"),
        (0x48EA0F971AD73F40, 0x10, "ChamferBox", "geometry"),
        (0x21A446A17B9A546E, 0x10, "ChamferCyl", "geometry"),
        (0x79C939A96D3D77AC, 0x10, "Capsule", "geometry"),
        (0x7AF0200D33B1284D, 0x10, "C-Ext", "geometry"),
        (0x11634EB86C3600A5, 0x10, "TextPlus", "geometry"),
        (0x10B0, 0x10, "Loft", "geometry"),
        (0x1C596B1A51DB4F2F, 0x10, "Boolean", "geometry"),
        (0x2257F99331CEA620, 0x10, "ProBoolean", "geometry"),
        (0x2ECCA84028BF6E8D, 0x10, "Bone", "geometry"),
        (0x9125, 0x10, "Biped Object", "geometry"),
        (0x1020, 0x10, "Target", "geometry"),           # The object of camera / light target nodes.
        (0x1EB3430074F93B02, 0x10, "ParticleGroup", "geometry"),
        (0x50320C9A, 0x10, "PF Source", "geometry"),
        # Cameras.
        (0x1001, 0x20, "Free", "camera"),
        (0x1002, 0x20, "Target", "camera"),
        (0x28E8008D46697218, 0x20, "Physical", "camera"),
        # Lights.
        (0x1011, 0x30, "Omni", "light"),
        (0x1012, 0x30, "Target Spot", "light"),
        (0x1014, 0x30, "Free Spot", "light"),
        (0x1013, 0x30, "Free Direct", "light"),
        (0x1015, 0x30, "Target Direct", "light"),
        (0x522E47057BF61478, 0x30, "Skylight", "light"),
        (0x0B025CF032375FCC, 0x30, "Free Light", "light"),
        (0x72CD4259658D4F97, 0x30, "Target Light", "light"),
        (0xCA131D056705F00D, 0x30, "Arnold Light", "light"),
        (0x105A1A4736507D92, 0x30, "Free Rectangle", "light"),
        (0x70AE52F271794F9D, 0x30, "Target Rectangle", "light"),
        (0x0C4F430E5BCC6D42, 0x30, "Free Disc", "light"),
        (0x201758B338732348, 0x30, "Target Disc", "light"),
        (0x1ABB6B327CA93582, 0x30, "Free Sphere", "light"),
        (0x0A327AAF46F634E3, 0x30, "Free Cylinder", "light"),
        (0x716F5B2527FE329C, 0x30, "Sun Positioner", "light"),
        (0x25E2112471503BBB, 0x30, "mr Sun", "light"),
        (0x799B5B5626EE3350, 0x30, "mr Sky", "light"),
        # Shapes.
        (0x1040, 0x40, "Line", "shape"),
        (0xA, 0x40, "SplineShape", "shape"),
        (0x1065, 0x40, "Rectangle", "shape"),
        (0x1999, 0x40, "Circle", "shape"),
        (0x1993, 0x40, "Text", "shape"),
        (0x1995, 0x40, "Star", "shape"),
        (0x1050, 0x40, "NGon", "shape"),
        (0x1060, 0x40, "Donut", "shape"),
        (0x93257030, 0x40, "Angle", "shape"),
        # Helpers.
        (0x876234, 0x50, "Dummy", "helper"),
        (0x2013, 0x50, "Point", "helper"),
        (0x2010, 0x50, "Grid", "helper"),
        (0x2011, 0x50, "Tape", "helper"),
        # Modifiers.
        (0xF72B1, 0x810, "UVW Map", "modifier"),
        (0x10, 0x810, "Bend", "modifier"),
        (0x20, 0x810, "Taper", "modifier"),
        (0x90, 0x810, "Twist", "modifier"),
        (0x73D8FF93, 0x810, "Mesh Select", "modifier"),
        (0x50, 0x810, "Edit Mesh", "modifier"),
        (0x7F9E00000032, 0x810, "MeshSmooth", "modifier"),
        (0x491D29A70D727B3E, 0x810, "TurboSmooth", "modifier"),
        (0x9ABC45FC73CCF34A, 0x810, "OpenSubdiv", "modifier"),
        (0x156660095C723, 0x810, "Skin", "modifier"),
        (0xA0, 0x810, "Extrude", "modifier"),
        (0xB0, 0x810, "Lathe", "modifier"),
        (0x72BA4E1F02DF2E3A, 0x810, "Unwrap UVW", "modifier"),
        (0xF997B124, 0x810, "Noise", "modifier"),
        (0x311815057CE5206B, 0x810, "Poly Select", "modifier"),
        (0x25215824, 0x810, "XForm", "modifier"),
        (0x60, 0x810, "Edit Spline", "modifier"),
        (0x71A075B779AA6E1D, 0x810, "Edit Poly", "modifier"),
        (0x67AD0ADF0618372D, 0x810, "Push", "modifier"),
        (0x0BE41A6E2D7E702B, 0x810, "Symmetry", "modifier"),
        (0x6D84E8D03B9B1A16, 0x810, "Shell", "modifier"),
        (0x38BB548C332C9510, 0x810, "Chamfer", "modifier"),
        (0x511BBE75EF92AA7C, 0x810, "Mirror", "modifier"),
        (0x7F9E00000064, 0x810, "Relax", "modifier"),
        (0xC4D31, 0x810, "Optimize", "modifier"),
        (0xF8614, 0x810, "Normal", "modifier"),
        (0xF8613, 0x810, "Smooth", "modifier"),
        (0x2ED9401C148132A1, 0x810, "Lattice", "modifier"),
        (0x1F88220F25EBC866, 0x810, "Sweep", "modifier"),
        (0xA5CBA2A317BB6854, 0x810, "Morpher", "modifier"),
        (0xC4D32, 0x810, "Displace", "modifier"),
        (0x82D7FE748AB36CC5, 0x810, "FFD(box)", "modifier"),
        (0x2CD10BD921325596, 0x810, "FFD 3x3x3", "modifier"),
        (0x60397CA15C5B50F7, 0x810, "Turn to Mesh", "modifier"),
        # Materials.
        (0x2, 0xC00, "Standard", "material"),
        (0x200, 0xC00, "Multi/Sub-Object", "material"),
        (0xDEADC0013D6B1CEC, 0xC00, "Physical Material", "material"),
        (0x62F74B4C7E73161F, 0xC00, "Standard Surface", "material"),      # Arnold
        (0x4A16365470B05735, 0xC00, "Arch & Design", "material"),
        (0x329B106E27190FF4, 0xC00, "Raytrace", "material"),
        (0x250, 0xC00, "Blend", "material"),
        (0x210, 0xC00, "Double Sided", "material"),
        (0x100, 0xC00, "Top/Bottom", "material"),
        (0x13640AF661DC0CD7, 0xC00, "Composite", "material"),
        (0x260, 0xC00, "Matte/Shadow", "material"),
        (0x691E303713D11BBE, 0xC00, "Architectural", "material"),
        (0x46EE536A, 0xC00, "Shellac", "material"),
        (0x4D3960A501A8169A, 0xC00, "Ink 'n Paint", "material"),
        (0x213DAAF81ED415E4, 0xC00, "Autodesk Material", "material"),
        (0x7A10ACA56926BA21, 0xC00, "mental ray", "material"),
        (0x6CFF42F72914493D, 0xC00, "Advanced Lighting Override", "material"),
        (0xA964C1587E73161F, 0xC00, "Standard Hair", "material"),
        (0xC25EA83B7773160F, 0xC00, "ProMaterials: Plastic/Vinyl", "material"),
        (0xB9544C137773160F, 0xC00, "ProMaterials: Metal", "material"),
        (0xA5605F307773160F, 0xC00, "ProMaterials: Generic", "material"),
        (0xB96170207773160F, 0xC00, "ProMaterials: Metallic Paint", "material"),
        (0x4D4EB17C7773160F, 0xC00, "ProMaterials: Solid Glass", "material"),
        (0xBB0E4F267773160F, 0xC00, "ProMaterials: Mirror", "material"),
        (0x572151887E73161F, 0xC00, "Atmospheric Volume", "material"),
        (0x72928E198CCDF7BC, 0xC00, "Map to Material", "material"),
        (0xAB3C62177773160F, 0xC00, "Subsurface Scattering Fast Material", "material"),
        (0x6133DAF20ED995E4, 0xC00, "DirectX Shader", "material"),
        # Texture maps.
        (0x290, 0xC10, "RGB Multiply", "texmap"),
        (0x218, 0xC10, "Dent", "texmap"),
        (0x0A845E7C, 0xC10, "Smoke", "texmap"),
        (0x284441BC00000000, 0xC10, "Raytrace", "texmap"),
        (0x240, 0xC10, "Bitmap", "texmap"),
        (0x234, 0xC10, "Noise", "texmap"),
        (0x200, 0xC10, "Checker", "texmap"),
        (0x270, 0xC10, "Gradient", "texmap"),
        (0x43383A511DEC5B86, 0xC10, "Gradient Ramp", "texmap"),
        (0x6EC3730C, 0xC10, "Falloff", "texmap"),
        (0x220, 0xC10, "Mask", "texmap"),
        (0x230, 0xC10, "Mix", "texmap"),
        (0x280, 0xC10, "Composite", "texmap"),
        (0x2D0, 0xC10, "Color Correction", "texmap"),
        (0x63F6A014243E22C6, 0xC10, "Normal Bump", "texmap"),
        (0xB65F556E7E73161F, 0xC10, "Bump 2D", "texmap"),
        (0x111940BBC90017A5, 0xC10, "Cellular", "texmap"),
        (0x69664CDC64035FB9, 0xC10, "Tiles", "texmap"),
        (0x273DEEF87ED417E4, 0xC10, "Autodesk Map", "texmap"),
        # Standard material parts.
        (0x1200, 0x1080, "Texmaps", "material.texmaps"),
        (0x38, 0x10B0, "Blinn", "shader"),
        (0x37, 0x10B0, "Phong", "shader"),
        (0x39, 0x10B0, "Metal", "shader"),
        (0x2857F460, 0x10B0, "Anisotropic", "shader"),
        (0x2857F421, 0x10B0, "Oren-Nayar-Blinn", "shader"),
        (0x2857F450, 0x10B0, "Strauss", "shader"),
        (0x2857F470, 0x10B0, "Multi-Layer", "shader"),
        (0x2857F480, 0x10B0, "Translucent Shader", "shader"),
        (0x1DBA1DF07E9858FE, 0x10F0, "Base Layer", "layer"),
    )
    for class_id, superclass_id, name, category in seed:
        register_class(class_id, name, category, superclass_id, source=SOURCE_CORPUS, verified=True)
    # Not in any class directory, see DERIVED_OBJECT. Registered without a superclass.
    register_class(DERIVED_OBJECT, "Derived Object", "geometry.derived", None, source=SOURCE_CORPUS, verified=True)
    register_class(DERIVED_OBJECT_WSM, "Derived Object (world space)", "geometry.derived", None,
                   source=SOURCE_CORPUS, verified=True)


_seed()
