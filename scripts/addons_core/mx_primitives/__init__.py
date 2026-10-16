# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Max-style primitives with live parameters (ROADMAP Phase 1c).

Parameters are stored on the mesh (``Mesh.mx_primitive``) and changing one regenerates the mesh, so modifiers on
top keep working and instances share the primitive. "Convert to Editable Poly" removes the parameters and keeps
the mesh. With the add-on disabled, meshes stay as they were last generated. See
``docs/decisions/0006-live-primitives.md``.

Module-level API, for other add-ons and the ``.max`` importer:

- :data:`KINDS`: ordered ``(kind, label, description)`` list; :data:`ICONS`: Blender icon per kind.
- :func:`draw_parameters`: draw the "Parameters" rollout of a live primitive.
- :func:`create_primitive_object`: create a live primitive object without operators.
- :func:`is_live_primitive`, :func:`get_parameters`, :func:`set_parameters`.
- :mod:`.geometry`: the bpy-free mesh generators, ``geometry.generate(kind, **params)``.
"""

bl_info = {
    "name": "Max-Style Primitives",
    "author": "PROJECT_NAME Authors",
    "version": (0, 1, 0),
    "blender": (5, 2, 0),
    "location": "3D Viewport > Add > Mesh > Max-Style Primitives; Properties > Modifiers; Sidebar > Item",
    "description": "Primitives with live parameters and click-drag creation in a Max-style workflow",
    "warning": "Early development",
    "category": "Add Mesh",
}

if "bpy" in locals():
    import importlib
    for _module in (geometry, creation, kinds, props, ui, ops):  # noqa: F821
        importlib.reload(_module)
    del _module

import bpy

from . import (
    geometry,
    creation,
    kinds,
    props,
    ui,
    ops,
)

__all__ = (
    "KINDS",
    "ICONS",
    "draw_parameters",
    "create_primitive_object",
    "is_live_primitive",
    "get_parameters",
    "set_parameters",
    "geometry",
)

KINDS = kinds.KINDS
ICONS = kinds.ICONS


def draw_parameters(layout, obj):
    """
    Draw the "Parameters" rollout (Max's order and names) of a live primitive ``obj`` into ``layout``.
    Returns ``False`` without drawing anything if ``obj`` isn't a live primitive.
    """
    return ui.draw_parameters(layout, obj)


def create_primitive_object(name, kind, params, collection=None, mesh=None):
    """
    Create an object holding a live primitive, using ``bpy.data`` only (no operators).

    ``params`` are those of ``geometry.PARAMETERS[kind]`` (missing ones get defaults). Pass the ``mesh`` of an
    earlier call to make an instance sharing the primitive. The object is linked to ``collection`` (default: the
    context's collection), at the origin, unselected.
    """
    return ops.create_primitive_object(name, kind, params, collection=collection, mesh=mesh)


def is_live_primitive(obj_or_mesh):
    """Whether an object (or mesh) is a live primitive."""
    return props.settings_of(obj_or_mesh) is not None


def get_parameters(obj_or_mesh):
    """``(kind, parameters)`` of a live primitive, or ``(None, {})``."""
    mesh = obj_or_mesh.data if isinstance(obj_or_mesh, bpy.types.Object) else obj_or_mesh
    if not isinstance(mesh, bpy.types.Mesh):
        return None, {}
    return props.get_parameters(mesh)


def set_parameters(obj_or_mesh, kind, params):
    """Set parameters of a live primitive (turning a plain mesh into one) and regenerate it."""
    mesh = obj_or_mesh.data if isinstance(obj_or_mesh, bpy.types.Object) else obj_or_mesh
    props.set_parameters(mesh, kind, params)


_classes = (
    props.MXPrimitiveSettings,
    ops.MESH_OT_mx_primitive_add,
    ops.OBJECT_OT_mx_convert_to_editable_poly,
    *ui.classes,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Mesh.mx_primitive = bpy.props.PointerProperty(type=props.MXPrimitiveSettings)
    bpy.types.VIEW3D_MT_mesh_add.append(ui.menu_func)


def unregister():
    bpy.types.VIEW3D_MT_mesh_add.remove(ui.menu_func)
    # The stored parameters stay in the file (as plain ID properties) and come back when re-enabled.
    del bpy.types.Mesh.mx_primitive
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
