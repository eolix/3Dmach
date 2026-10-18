# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Max-style groups, built from empties.

A Max group is a named head object with the grouped objects linked below it; transforming the head moves
the whole group. Here the head is an empty (display: cube, sized to the members' bounds) marked with the
custom property ``mx_group``, and the members are parented to it. Open/Close (selecting members vs. the
whole group) needs selection changes that are left for later.
"""

from mathutils import Vector

import bpy
from bpy.props import StringProperty
from bpy.types import Operator

from . import utils

GROUP_KEY = "mx_group"


def is_group(obj):
    return obj is not None and obj.type == 'EMPTY' and bool(obj.get(GROUP_KEY, False))


def _top_level(objects):
    selected = set(objects)
    result = []
    for obj in objects:
        parent = obj.parent
        while parent is not None and parent not in selected:
            parent = parent.parent
        if parent is None:
            result.append(obj)
    return result


def _world_bounds(objects):
    points = []
    for obj in objects:
        points.extend(obj.matrix_world @ Vector(corner) for corner in obj.bound_box)
    if not points:
        return Vector(), Vector()
    bb_min = Vector(min(p[i] for p in points) for i in range(3))
    bb_max = Vector(max(p[i] for p in points) for i in range(3))
    return bb_min, bb_max


def _set_parent_keep_transform(obj, parent):
    matrix = obj.matrix_world.copy()
    obj.parent = parent
    if parent is not None:
        obj.matrix_parent_inverse = parent.matrix_world.inverted()
    else:
        obj.matrix_parent_inverse.identity()
    obj.matrix_world = matrix


def make_group(context, objects, name=None):
    members = _top_level(objects)
    bb_min, bb_max = _world_bounds(members)
    head = bpy.data.objects.new(name or utils.max_style_name("Group"), None)
    head.empty_display_type = 'CUBE'
    head.empty_display_size = max(max((bb_max - bb_min) * 0.5), 0.01)
    head.location = (bb_min + bb_max) * 0.5
    head[GROUP_KEY] = True
    utils.link_to_scene(context, head)
    context.view_layer.update()
    for obj in members:
        _set_parent_keep_transform(obj, head)
    return head


def ungroup(group):
    for child in list(group.children):
        _set_parent_keep_transform(child, None)
    bpy.data.objects.remove(group)


class OBJECT_OT_mx_group(Operator):
    """Group the selected objects under a new group head"""
    bl_idname = "object.mx_group"
    bl_label = "Group"
    bl_options = {'REGISTER', 'UNDO'}

    name: StringProperty(name="Group Name")

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and bool(context.selected_editable_objects)

    def invoke(self, context, _event):
        self.name = utils.max_style_name("Group")
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        head = make_group(context, context.selected_editable_objects, self.name or None)
        utils.make_active(context, head)
        return {'FINISHED'}


class OBJECT_OT_mx_ungroup(Operator):
    """Dissolve the selected groups, keeping their members in place"""
    bl_idname = "object.mx_ungroup"
    bl_label = "Ungroup"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and any(is_group(obj) for obj in context.selected_objects)

    def execute(self, context):
        for obj in [obj for obj in context.selected_objects if is_group(obj)]:
            ungroup(obj)
        return {'FINISHED'}


class OBJECT_OT_mx_group_attach(Operator):
    """Attach the selected objects to the active group"""
    bl_idname = "object.mx_group_attach"
    bl_label = "Attach to Group"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and is_group(context.active_object)

    def execute(self, context):
        group = context.active_object
        for obj in _top_level([obj for obj in context.selected_editable_objects if obj != group]):
            _set_parent_keep_transform(obj, group)
        return {'FINISHED'}


class OBJECT_OT_mx_group_detach(Operator):
    """Detach the selected objects from their group"""
    bl_idname = "object.mx_group_detach"
    bl_label = "Detach from Group"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and any(is_group(obj.parent) for obj in context.selected_objects)

    def execute(self, context):
        for obj in context.selected_editable_objects:
            if is_group(obj.parent):
                _set_parent_keep_transform(obj, None)
        return {'FINISHED'}


classes = (
    OBJECT_OT_mx_group,
    OBJECT_OT_mx_ungroup,
    OBJECT_OT_mx_group_attach,
    OBJECT_OT_mx_group_detach,
)
