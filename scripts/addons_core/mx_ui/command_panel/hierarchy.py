# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Hierarchy tab: Pivot (Max's pivot is Blender's object origin) and Link Info.

- Affect Pivot Only → the tool setting "Affect Only Origins" (``use_transform_data_origin``).
- Affect Object Only (move the object but not its pivot) has no Blender equivalent yet: shown disabled.
- Center to Object / Center to Pivot / Align to World / Reset → ``object.origin_set`` and
  ``object.transform_apply`` on the selection.
- Link Info locks → ``lock_location`` / ``lock_rotation`` / ``lock_scale``.
"""

import bpy
from bpy.props import EnumProperty
from bpy.types import Operator

from .. import utils

PIVOT_ACTIONS = (
    ('CENTER_TO_OBJECT', "Center to Object", "Move the pivot to the center of the object's bounding box"),
    ('CENTER_TO_PIVOT', "Center to Pivot", "Move the object so its bounding box is centered on the pivot"),
    ('ALIGN_TO_WORLD', "Align to World", "Align the pivot with the world axes, keeping the geometry in place"),
    ('RESET_PIVOT', "Reset Pivot", "Center the pivot on the object and align it with the world"),
    ('RESET_TRANSFORM', "Reset Transform", "Bake rotation and scale into the object, keeping it in place"),
    ('RESET_SCALE', "Reset Scale", "Bake the scale into the object, keeping it in place"),
)


def apply_pivot_action(context, objects, action):
    objects = [obj for obj in objects if obj.is_editable]
    if not objects:
        return
    override = utils.object_context_override(context, objects[0], objects)
    with context.temp_override(**override):
        if action in {'CENTER_TO_OBJECT', 'RESET_PIVOT'}:
            bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='BOUNDS')
        if action == 'CENTER_TO_PIVOT':
            bpy.ops.object.origin_set(type='GEOMETRY_ORIGIN', center='BOUNDS')
        if action in {'ALIGN_TO_WORLD', 'RESET_PIVOT'}:
            bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)
        if action == 'RESET_TRANSFORM':
            bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
        if action == 'RESET_SCALE':
            bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)


class OBJECT_OT_mx_pivot(Operator):
    """Adjust the pivot (object origin) of the selected objects"""
    bl_idname = "object.mx_pivot"
    bl_label = "Adjust Pivot"
    bl_options = {'REGISTER', 'UNDO'}

    action: EnumProperty(name="Action", items=PIVOT_ACTIONS)

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and bool(context.selected_editable_objects)

    @classmethod
    def description(cls, _context, properties):
        for key, _label, desc in PIVOT_ACTIONS:
            if key == properties.action:
                return desc
        return None

    def execute(self, context):
        try:
            apply_pivot_action(context, context.selected_editable_objects, self.action)
        except RuntimeError as ex:
            self.report({'ERROR'}, str(ex))
            return {'CANCELLED'}
        return {'FINISHED'}


def _action_button(layout, action, text=None):
    label = text or next(item[1] for item in PIVOT_ACTIONS if item[0] == action)
    layout.operator(OBJECT_OT_mx_pivot.bl_idname, text=label).action = action


def draw(layout, context):
    tool_settings = context.scene.tool_settings
    obj = context.active_object

    header, body = layout.panel("MXUI_hierarchy_adjust_pivot")
    header.label(text="Adjust Pivot")
    if body is not None:
        col = body.column(align=True)
        col.label(text="Move/Rotate/Scale:")
        col.prop(tool_settings, "use_transform_data_origin", text="Affect Pivot Only", toggle=True)
        row = col.row(align=True)
        row.active = False
        row.label(text="Affect Object Only: coming later")
        col.prop(tool_settings, "use_transform_skip_children", text="Don't Affect Children", toggle=True)

        col = body.column(align=True)
        col.label(text="Alignment:")
        _action_button(col, 'CENTER_TO_OBJECT')
        _action_button(col, 'CENTER_TO_PIVOT')
        _action_button(col, 'ALIGN_TO_WORLD')

        col = body.column(align=True)
        col.label(text="Pivot:")
        _action_button(col, 'RESET_PIVOT')

    header, body = layout.panel("MXUI_hierarchy_adjust_transform", default_closed=True)
    header.label(text="Adjust Transform")
    if body is not None:
        col = body.column(align=True)
        col.label(text="Reset:")
        _action_button(col, 'RESET_TRANSFORM', "Transform")
        _action_button(col, 'RESET_SCALE', "Scale")

    header, body = layout.panel("MXUI_hierarchy_link_info")
    header.label(text="Link Info")
    if body is None:
        return
    if obj is None:
        body.label(text="Select an object")
        return
    body.use_property_split = True
    body.use_property_decorate = False
    col = body.column()
    col.prop(obj, "parent", text="Parent")
    row = col.row(align=True)
    row.operator("object.select_hierarchy", text="Select Parent").direction = 'PARENT'
    row.operator("object.select_hierarchy", text="Select Children").direction = 'CHILD'
    col.separator()
    col.label(text="Locks:")
    col.prop(obj, "lock_location", text="Move")
    col.prop(obj, "lock_rotation", text="Rotate")
    col.prop(obj, "lock_scale", text="Scale")


classes = (
    OBJECT_OT_mx_pivot,
)
