# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Primitive parameters stored on meshes (``Mesh.mx_primitive``), and writing generated geometry into meshes.

The parameters live on the mesh so that instances (objects sharing the mesh) share them. Changing a parameter
regenerates the mesh through the property's update callback; modifiers on the objects keep working on top.
"""

__all__ = (
    "MXPrimitiveSettings",
    "property_definitions",
    "suspended_updates",
    "settings_of",
    "get_parameters",
    "set_parameters",
    "rebuild",
    "write_mesh",
    "clear",
)

import contextlib

import bmesh
import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
)

from . import geometry
from .kinds import KINDS, ICONS

# Enumeration items. The numbers are stored in .blend files: never renumber, only append.
_KIND_NUMBERS = {kind: index + 1 for index, kind in enumerate(geometry.KIND_IDS)}
_KIND_DESCRIPTIONS = {kind: (name, description) for kind, name, description in KINDS}

KIND_ITEMS = [
    (kind, _KIND_DESCRIPTIONS[kind][0], _KIND_DESCRIPTIONS[kind][1], ICONS[kind], _KIND_NUMBERS[kind])
    for kind, _name, _description in KINDS
]
_KIND_ITEMS_WITH_NONE = [('NONE', "None", "Not a live primitive", 'NONE', 0)] + KIND_ITEMS

_ENUM_ITEMS = {
    "hemisphere_mode": [
        ('CHOP', "Chop", "Remove the vertices and faces below the cut (fewer faces)", 0),
        ('SQUASH', "Squash", "Keep all segments, squashed into the part that is left", 1),
    ],
    "base_type": [
        ('TETRA', "Tetra", "Build from a tetrahedron", 0),
        ('OCTA', "Octa", "Build from an octahedron", 1),
        ('ICOSA', "Icosa", "Build from an icosahedron", 2),
    ],
    "smooth_mode": [
        ('ALL', "All", "Smooth the whole surface", 0),
        ('SIDES', "Sides", "Smooth across segments: smooth bands running around the ring", 1),
        ('NONE', "None", "No smoothing: faceted", 2),
        ('SEGMENTS', "Segments", "Smooth each segment on its own: ring-shaped facets", 3),
    ],
}

_DISTANCE = {"subtype": 'DISTANCE', "unit": 'LENGTH'}
_ANGLE = {"subtype": 'ANGLE', "unit": 'ROTATION'}


def _int(name, description, minimum, soft_max=100):
    return (IntProperty, {"name": name, "description": description, "min": minimum, "soft_max": soft_max,
                          "max": 1000})


def _size(name, description, signed=False):
    keywords = {"name": name, "description": description, "soft_max": 1000.0, **_DISTANCE}
    if not signed:
        keywords["min"] = 0.0
    return (FloatProperty, keywords)


def _bool(name, description):
    return (BoolProperty, {"name": name, "description": description})


# Property definition per parameter name: (property function, keyword arguments). Each name is shared by all the
# kinds that have it; per-kind ranges and defaults come from `geometry` (values are clamped on rebuild).
_PARAMETER_DEFINITIONS = {
    "length": _size("Length", "Size along the local Y axis"),
    "width": _size("Width", "Size along the local X axis"),
    "depth": _size("Depth", "Size along the local Y axis"),
    "height": _size("Height", "Size along the local Z axis (negative: downwards)", signed=True),
    "radius": _size("Radius", "Radius"),
    "radius1": _size("Radius 1", "First radius"),
    "radius2": _size("Radius 2", "Second radius"),
    "length_segments": _int("Length Segments", "Number of divisions along the length", 1),
    "width_segments": _int("Width Segments", "Number of divisions along the width", 1),
    "depth_segments": _int("Depth Segments", "Number of divisions along the depth", 1),
    "height_segments": _int("Height Segments", "Number of divisions along the height", 1),
    "cap_segments": _int("Cap Segments", "Number of concentric divisions of the caps", 1),
    "sides": _int("Sides", "Number of sides around", 3),
    "segments": _int("Segments", "Number of segments", 1),
    "smooth": _bool("Smooth", "Smooth the curved surfaces"),
    "hemisphere": (FloatProperty, {"name": "Hemisphere", "description": "Part of the sphere cut off from the bottom",
                                   "min": 0.0, "max": 1.0, "subtype": 'FACTOR'}),
    "hemisphere_on": _bool("Hemisphere", "Only the upper half"),
    "slice_on": _bool("Slice On", "Keep only the part between Slice From and Slice To"),
    "slice_from": (FloatProperty, {"name": "Slice From", "description": "Angle where the kept part starts",
                                   **_ANGLE}),
    "slice_to": (FloatProperty, {"name": "Slice To", "description": "Angle where the kept part ends "
                                 "(counter-clockwise from Slice From)", **_ANGLE}),
    "base_to_pivot": _bool("Base To Pivot", "Put the pivot at the bottom instead of the centre"),
    "rotation": (FloatProperty, {"name": "Rotation", "description": "Rotation of the vertices around the cross-section",
                                 **_ANGLE}),
    "twist": (FloatProperty, {"name": "Twist", "description": "Twist of the cross-section, growing around the ring",
                              **_ANGLE}),
    "generate_uvs": _bool("Generate Mapping Coords", "Create UV coordinates"),
    "part_body": _bool("Body", "Include the body"),
    "part_handle": _bool("Handle", "Include the handle"),
    "part_spout": _bool("Spout", "Include the spout"),
    "part_lid": _bool("Lid", "Include the lid"),
}
for _name, _items in _ENUM_ITEMS.items():
    _PARAMETER_DEFINITIONS[_name] = (EnumProperty, {"name": _name.replace("_", " ").title(), "items": _items})
_PARAMETER_DEFINITIONS["base_type"][1]["name"] = "Geodesic Base Type"
_PARAMETER_DEFINITIONS["hemisphere_mode"][1]["name"] = "Hemisphere Mode"
_PARAMETER_DEFINITIONS["smooth_mode"][1]["name"] = "Smooth"

PARAMETER_NAMES = tuple(_PARAMETER_DEFINITIONS)


def property_definitions(update=None, options=None):
    """
    Annotations for all parameters (used by the property group and, without ``update``, by the add operator).
    Defaults are those of the first kind that has the parameter.
    """
    defaults = {}
    for params in geometry.PARAMETERS.values():
        for name, value in params.items():
            defaults.setdefault(name, value)
    result = {}
    for name, (function, keywords) in _PARAMETER_DEFINITIONS.items():
        keywords = dict(keywords, default=defaults[name])
        if update is not None:
            keywords["update"] = update
        if options is not None:
            keywords["options"] = options
        result[name] = function(**keywords)
    return result


# -----------------------------------------------------------------------------
# Updates

_suspended = 0


@contextlib.contextmanager
def suspended_updates():
    """Set several parameters without regenerating the mesh after each one."""
    global _suspended
    _suspended += 1
    try:
        yield
    finally:
        _suspended -= 1


def _on_parameter_update(self, _context):
    if _suspended:
        return
    mesh = self.id_data
    if isinstance(mesh, bpy.types.Mesh) and self.kind != 'NONE':
        rebuild(mesh)


MXPrimitiveSettings = type("MXPrimitiveSettings", (bpy.types.PropertyGroup,), {
    "__doc__": "Parameters of a Max-style live primitive",
    "__annotations__": {
        "kind": EnumProperty(
            name="Primitive",
            description="Kind of live primitive; None once converted to an editable mesh",
            items=_KIND_ITEMS_WITH_NONE,
            default='NONE',
        ),
        **property_definitions(update=_on_parameter_update),
    },
})


# -----------------------------------------------------------------------------
# Access

def settings_of(obj_or_mesh):
    """The primitive settings of an object's mesh (or of a mesh), or ``None`` if it isn't a live primitive."""
    mesh = obj_or_mesh
    if isinstance(obj_or_mesh, bpy.types.Object):
        mesh = obj_or_mesh.data if obj_or_mesh.type == 'MESH' else None
    if not isinstance(mesh, bpy.types.Mesh):
        return None
    settings = getattr(mesh, "mx_primitive", None)
    if settings is None or settings.kind == 'NONE':
        return None
    return settings


def _raw_parameters(settings, kind):
    return {name: getattr(settings, name) for name in geometry.PARAMETERS[kind]}


def get_parameters(mesh):
    """``(kind, parameters)`` of a live primitive mesh, or ``(None, {})``."""
    settings = settings_of(mesh)
    if settings is None:
        return None, {}
    return settings.kind, geometry.normalize_params(settings.kind, _raw_parameters(settings, settings.kind))


def set_parameters(mesh, kind, params=None):
    """
    Make ``mesh`` a live primitive of ``kind`` (if it isn't already) with the given parameters, and regenerate it.
    Parameters not given keep their current value, or get the kind's defaults when the kind changes.
    """
    settings = mesh.mx_primitive
    if settings.kind == kind:
        values = _raw_parameters(settings, kind)
    else:
        values = dict(geometry.PARAMETERS[kind])
    values.update(params or {})
    values = geometry.normalize_params(kind, values)
    with suspended_updates():
        settings.kind = kind
        for name, value in values.items():
            setattr(settings, name, value)
    rebuild(mesh)


def rebuild(mesh):
    """Regenerate a live primitive mesh from its parameters."""
    settings = mesh.mx_primitive
    kind = settings.kind
    if kind == 'NONE' or mesh.library is not None:
        return
    raw = _raw_parameters(settings, kind)
    values = geometry.normalize_params(kind, raw)
    clamped = {name: value for name, value in values.items() if value != raw[name]}
    if clamped:
        # Show the values that are actually used (e.g. a sphere has at least 4 segments).
        with suspended_updates():
            for name, value in clamped.items():
                setattr(settings, name, value)
    write_mesh(mesh, geometry.generate(kind, **values))


def clear(mesh):
    """Remove the primitive parameters from a mesh, keeping its geometry ("Convert to Editable Poly")."""
    with suspended_updates():
        mesh.property_unset("mx_primitive")
        # Unset leaves the default ('NONE') in place, but make sure in case the group was only partly stored.
        mesh.mx_primitive.kind = 'NONE'


# -----------------------------------------------------------------------------
# Writing meshes

def write_mesh(mesh, data):
    """Replace the geometry of ``mesh`` with a :class:`geometry.MeshData`. Works in edit mode too."""
    if mesh.is_editmode:
        temp = bpy.data.meshes.new("~mx_primitive")
        try:
            _fill_mesh(temp, data)
            bm = bmesh.from_edit_mesh(mesh)
            bm.clear()
            bm.from_mesh(temp)
            bmesh.update_edit_mesh(mesh, loop_triangles=True, destructive=True)
        finally:
            bpy.data.meshes.remove(temp)
        return
    _fill_mesh(mesh, data)


def _fill_mesh(mesh, data):
    mesh.clear_geometry()
    vertices = data.vertices
    faces = data.faces
    mesh.vertices.add(len(vertices))
    mesh.vertices.foreach_set("co", [c for v in vertices for c in v])
    loop_starts = []
    total = 0
    for face in faces:
        loop_starts.append(total)
        total += len(face)
    mesh.loops.add(total)
    mesh.loops.foreach_set("vertex_index", [i for face in faces for i in face])
    mesh.polygons.add(len(faces))
    mesh.polygons.foreach_set("loop_start", loop_starts)
    mesh.update(calc_edges=True)

    mesh.polygons.foreach_set("material_index", data.material_ids)

    flat = data.flat_faces()
    if any(flat):
        mesh.attributes.new("sharp_face", 'BOOLEAN', 'FACE').data.foreach_set("value", flat)
    sharp = set(data.sharp_edges())
    if sharp:
        edge_vertices = [0] * (2 * len(mesh.edges))
        mesh.edges.foreach_get("vertices", edge_vertices)
        flags = []
        for k in range(0, len(edge_vertices), 2):
            a, b = edge_vertices[k], edge_vertices[k + 1]
            flags.append(((a, b) if a < b else (b, a)) in sharp)
        mesh.attributes.new("sharp_edge", 'BOOLEAN', 'EDGE').data.foreach_set("value", flags)

    if data.uvs is not None:
        layer = mesh.uv_layers.new(name="UVMap")
        layer.uv.foreach_set("vector", [c for face_uvs in data.uvs for uv in face_uvs for c in uv])
    mesh.update()
