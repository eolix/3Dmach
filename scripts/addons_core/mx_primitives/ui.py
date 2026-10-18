# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Parameter rollout, panels (Properties editor modifier tab, 3D View sidebar) and the Add menu."""

__all__ = (
    "LAYOUT",
    "draw_parameters",
    "draw_parameter_list",
)

import bpy

from . import props
from .kinds import KINDS, ICONS, label

# The "Parameters" rollout per kind, in Max's order and with Max's names: (property, label) entries,
# None for a gap between groups, and (property, label, "EXPAND") for radio-button rows.
_SLICE = (("slice_on", "Slice On"), ("slice_from", "Slice From"), ("slice_to", "Slice To"))
_UVS = ("generate_uvs", "Generate Mapping Coords")

LAYOUT = {
    "BOX": (
        ("length", "Length"), ("width", "Width"), ("height", "Height"),
        ("length_segments", "Length Segs"), ("width_segments", "Width Segs"), ("height_segments", "Height Segs"),
        None, _UVS,
    ),
    "SPHERE": (
        ("radius", "Radius"), ("segments", "Segments"), ("smooth", "Smooth"),
        ("hemisphere", "Hemisphere"), ("hemisphere_mode", "", "EXPAND"),
        None, *_SLICE,
        None, ("base_to_pivot", "Base To Pivot"), _UVS,
    ),
    "GEOSPHERE": (
        ("radius", "Radius"), ("segments", "Segments"),
        ("base_type", "Geodesic Base Type", "EXPAND"),
        None, ("smooth", "Smooth"), ("hemisphere_on", "Hemisphere"), _UVS, ("base_to_pivot", "Base To Pivot"),
    ),
    "CYLINDER": (
        ("radius", "Radius"), ("height", "Height"),
        ("height_segments", "Height Segments"), ("cap_segments", "Cap Segments"), ("sides", "Sides"),
        ("smooth", "Smooth"),
        None, *_SLICE,
        None, _UVS,
    ),
    "TUBE": (
        ("radius1", "Radius 1"), ("radius2", "Radius 2"), ("height", "Height"),
        ("height_segments", "Height Segments"), ("cap_segments", "Cap Segments"), ("sides", "Sides"),
        ("smooth", "Smooth"),
        None, *_SLICE,
        None, _UVS,
    ),
    "CONE": (
        ("radius1", "Radius 1"), ("radius2", "Radius 2"), ("height", "Height"),
        ("height_segments", "Height Segments"), ("cap_segments", "Cap Segments"), ("sides", "Sides"),
        ("smooth", "Smooth"),
        None, *_SLICE,
        None, _UVS,
    ),
    "TORUS": (
        ("radius1", "Radius 1"), ("radius2", "Radius 2"), ("rotation", "Rotation"), ("twist", "Twist"),
        ("segments", "Segments"), ("sides", "Sides"),
        None, ("smooth_mode", "Smooth", "EXPAND"),
        None, *_SLICE,
        None, _UVS,
    ),
    "PYRAMID": (
        ("width", "Width"), ("depth", "Depth"), ("height", "Height"),
        ("width_segments", "Width Segs"), ("depth_segments", "Depth Segs"), ("height_segments", "Height Segs"),
        None, _UVS,
    ),
    "PLANE": (
        ("length", "Length"), ("width", "Width"),
        ("length_segments", "Length Segs"), ("width_segments", "Width Segs"),
        None, _UVS,
    ),
    "TEST_SHAPE": (
        ("radius", "Radius"), ("segments", "Segments"), ("smooth", "Smooth"),
        None, ("part_body", "Body"), ("part_handle", "Handle"), ("part_spout", "Spout"), ("part_lid", "Lid"),
        None, _UVS,
    ),
}

_SLICE_DEPENDENT = {"slice_from", "slice_to"}


def draw_parameter_list(layout, data, kind):
    """
    Draw the parameters of ``kind`` stored on ``data`` (a primitive's settings, or the add operator).
    The layout should use property split.
    """
    col = layout.column()
    for entry in LAYOUT[kind]:
        if entry is None:
            col.separator()
            continue
        name, text = entry[0], entry[1]
        row = col.row()
        if name in _SLICE_DEPENDENT:
            row.active = data.slice_on
        if name == "hemisphere_mode":
            row.active = data.hemisphere > 0.0
        if len(entry) > 2:
            row.prop(data, name, text=text, expand=True)
        else:
            row.prop(data, name, text=text)


def draw_parameters(layout, obj):
    """
    Draw the "Parameters" rollout of a live primitive, in Max's order and with Max's names.
    Returns ``False`` (drawing nothing) if ``obj`` isn't a live primitive.
    """
    settings = props.settings_of(obj) if obj is not None else None
    if settings is None:
        return False
    col = layout.column()
    col.use_property_split = True
    col.use_property_decorate = False
    if obj.mode == 'EDIT':
        col.label(text="Changing parameters replaces edits made in Edit Mode", icon='INFO')
    if obj.data.library is not None:
        col.enabled = False
    draw_parameter_list(col, settings, settings.kind)
    return True


def _draw_panel(panel, context):
    # `context.object` follows the Properties editor's pinning; in the 3D View it is the active object.
    obj = context.object
    settings = props.settings_of(obj)
    layout = panel.layout
    row = layout.row()
    row.label(text=label(settings.kind), icon=ICONS[settings.kind])
    users = obj.data.users
    if users > 1:
        row.label(text="{:d} instances".format(users))
    draw_parameters(layout, obj)
    layout.separator()
    layout.operator("object.mx_convert_to_editable_poly")


class _PrimitivePanel:
    bl_label = "Parameters"

    @classmethod
    def poll(cls, context):
        return props.settings_of(context.object) is not None

    def draw(self, context):
        _draw_panel(self, context)


class PROPERTIES_PT_mx_primitive(_PrimitivePanel, bpy.types.Panel):
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "modifier"
    bl_label = "Primitive Parameters"


class VIEW3D_PT_mx_primitive(_PrimitivePanel, bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Item"
    bl_label = "Primitive Parameters"


class VIEW3D_MT_mx_primitive_add(bpy.types.Menu):
    bl_idname = "VIEW3D_MT_mx_primitive_add"
    bl_label = "Max-Style Primitives"

    def draw(self, _context):
        layout = self.layout
        layout.operator_context = 'INVOKE_REGION_WIN'
        for kind, name, _description in KINDS:
            layout.operator("mesh.mx_primitive_add", text=name, icon=ICONS[kind]).kind = kind


def menu_func(self, _context):
    layout = self.layout
    layout.separator()
    layout.menu(VIEW3D_MT_mx_primitive_add.bl_idname, icon='MESH_CUBE')


classes = (
    PROPERTIES_PT_mx_primitive,
    VIEW3D_PT_mx_primitive,
    VIEW3D_MT_mx_primitive_add,
)
