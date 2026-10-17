# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Hierarchy tab: the Pivot / IK / Link Info buttons and their rollouts (``catalog.HIERARCHY_*``).
Max's pivot is Blender's object origin.

- Affect Pivot Only → the tool setting "Affect Only Origins" (``use_transform_data_origin``).
- Affect Object Only switches the alignment buttons (Center to Pivot, ...) like Max; moving the object without
  its pivot with the transform tools has no Blender equivalent yet.
- Center to Object / Center to Pivot / Align to World / Reset → ``object.origin_set`` and
  ``object.transform_apply`` on the selection.
- Don't Affect Children → "Affect Only Parents" (``use_transform_skip_children``).
- Link Info locks → ``lock_location`` / ``lock_rotation`` / ``lock_scale``.
- IK, Working Pivot, Skin Pose and Inherit are placeholders.
"""

import bpy
from bpy.props import EnumProperty
from bpy.types import Operator

from .. import utils
from ..placeholder import placeholder
from . import catalog, widgets

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


def _special_pivot_alignment(layout, context):
    """Max relabels the alignment buttons for Affect Object Only."""
    state = utils.get_state(context)
    col = layout.column(align=False)
    if state.affect_object_only:
        _action_button(col, 'CENTER_TO_PIVOT')
        placeholder(col, "Align to Pivot")
        placeholder(col, "Align to World", feature="Align to World (Affect Object Only)")
    else:
        _action_button(col, 'CENTER_TO_OBJECT')
        placeholder(col, "Align to Object")
        _action_button(col, 'ALIGN_TO_WORLD')


def _special_locks(layout, context):
    obj = context.active_object
    for label, prop in (("Move:", "lock_location"), ("Rotate:", "lock_rotation"), ("Scale:", "lock_scale")):
        row = layout.row(align=False)
        row.label(text=label)
        for index, axis in enumerate("XYZ"):
            if obj is None:
                placeholder(row, axis, icon='CHECKBOX_DEHLT', feature="Lock " + axis, emboss=False)
            else:
                row.prop(obj, prop, index=index, text=axis)


SPECIALS = {
    "PIVOT_ALIGNMENT": _special_pivot_alignment,
    "LOCKS": _special_locks,
}

MODE_ROLLOUTS = {
    'PIVOT': catalog.HIERARCHY_PIVOT,
    'IK': catalog.HIERARCHY_IK,
    'LINK_INFO': catalog.HIERARCHY_LINK_INFO,
}


def draw(layout, context):
    state = utils.get_state(context)
    row = layout.row(align=False)
    row.scale_y = 1.2
    row.prop(state, "hierarchy_mode", expand=True)
    for data in MODE_ROLLOUTS[state.hierarchy_mode]:
        widgets.draw_rollout(layout, context, data, SPECIALS)


classes = (
    OBJECT_OT_mx_pivot,
)
