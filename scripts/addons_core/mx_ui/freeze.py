# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Freeze (a Max concept) and the hide/unhide-by-name helpers.

A frozen object stays visible but can't be selected and draws in gray. Blender has no such state, so it is
built from three pieces:

- ``Object.hide_select`` makes the object unselectable (in viewports and the outliner);
- the object colour is replaced by gray, and the original is kept in the custom property ``mx_frozen_color``
  (objects draw in their object colour in the Max Layout, ``shading.color_type = 'OBJECT'``);
- the custom property ``mx_frozen`` marks the object as frozen, so Unfreeze knows what to restore and objects
  made unselectable by other means are left alone.

All three are saved in the .blend, so a frozen object stays frozen after reloading, also without this add-on.
"""

import bpy
from bpy.props import EnumProperty
from bpy.types import Operator

from . import utils

FROZEN_KEY = "mx_frozen"
COLOR_KEY = "mx_frozen_color"
FROZEN_GRAY = (0.45, 0.45, 0.45, 1.0)


def is_frozen(obj):
    return bool(obj.get(FROZEN_KEY, False))


def freeze_objects(objects, gray=True):
    """Freeze ``objects``. Returns the objects that were frozen (already frozen ones are skipped)."""
    frozen = []
    for obj in objects:
        if is_frozen(obj) or not obj.is_editable:
            continue
        obj[FROZEN_KEY] = True
        if gray:
            obj[COLOR_KEY] = list(obj.color)
            obj.color = FROZEN_GRAY
        obj.select_set(False)
        obj.hide_select = True
        frozen.append(obj)
    return frozen


def unfreeze_objects(objects):
    """Unfreeze ``objects``, restoring their colour. Returns the objects that were unfrozen."""
    unfrozen = []
    for obj in objects:
        if not is_frozen(obj) or not obj.is_editable:
            continue
        color = obj.get(COLOR_KEY)
        if color is not None:
            obj.color = tuple(color)
            del obj[COLOR_KEY]
        del obj[FROZEN_KEY]
        obj.hide_select = False
        unfrozen.append(obj)
    return unfrozen


def frozen_objects(scene):
    return [obj for obj in scene.objects if is_frozen(obj)]


def hidden_objects(context):
    view_layer = context.view_layer
    return [obj for obj in view_layer.objects if obj.hide_get(view_layer=view_layer)]


def _gray(context):
    prefs = utils.get_prefs(context)
    return prefs.frozen_in_gray if prefs else True


# -----------------------------------------------------------------------------
# Operators

class OBJECT_OT_mx_freeze_selected(Operator):
    """Freeze the selected objects: they stay visible but can't be selected"""
    bl_idname = "object.mx_freeze_selected"
    bl_label = "Freeze Selection"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and bool(context.selected_objects)

    def execute(self, context):
        frozen = freeze_objects(context.selected_objects, gray=_gray(context))
        self.report({'INFO'}, "Froze {:d} object(s)".format(len(frozen)))
        return {'FINISHED'}


class OBJECT_OT_mx_freeze_unselected(Operator):
    """Freeze every visible object that is not selected"""
    bl_idname = "object.mx_freeze_unselected"
    bl_label = "Freeze Unselected"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def execute(self, context):
        targets = [obj for obj in context.visible_objects if not obj.select_get()]
        frozen = freeze_objects(targets, gray=_gray(context))
        self.report({'INFO'}, "Froze {:d} object(s)".format(len(frozen)))
        return {'FINISHED'}


class OBJECT_OT_mx_unfreeze_all(Operator):
    """Unfreeze every frozen object in the scene"""
    bl_idname = "object.mx_unfreeze_all"
    bl_label = "Unfreeze All"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def execute(self, context):
        unfrozen = unfreeze_objects(frozen_objects(context.scene))
        self.report({'INFO'}, "Unfroze {:d} object(s)".format(len(unfrozen)))
        return {'FINISHED'}


# Dynamic enum items must stay referenced from Python while Blender uses them.
_enum_cache = {}


def _frozen_items(_self, context):
    items = [(obj.name, obj.name, "") for obj in frozen_objects(context.scene)]
    _enum_cache["frozen"] = items = items or [("", "(no frozen objects)", "")]
    return items


class OBJECT_OT_mx_unfreeze_by_name(Operator):
    """Pick a frozen object by name and unfreeze it"""
    bl_idname = "object.mx_unfreeze_by_name"
    bl_label = "Unfreeze by Name"
    bl_options = {'REGISTER', 'UNDO'}
    bl_property = "name"

    name: EnumProperty(name="Object", items=_frozen_items)

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def invoke(self, context, _event):
        context.window_manager.invoke_search_popup(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        obj = context.scene.objects.get(self.name)
        if obj is None:
            return {'CANCELLED'}
        unfreeze_objects([obj])
        return {'FINISHED'}


def _hidden_items(_self, context):
    items = [(obj.name, obj.name, "") for obj in hidden_objects(context)]
    _enum_cache["hidden"] = items = items or [("", "(no hidden objects)", "")]
    return items


class OBJECT_OT_mx_unhide_by_name(Operator):
    """Pick a hidden object by name and unhide it"""
    bl_idname = "object.mx_unhide_by_name"
    bl_label = "Unhide by Name"
    bl_options = {'REGISTER', 'UNDO'}
    bl_property = "name"

    name: EnumProperty(name="Object", items=_hidden_items)

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def invoke(self, context, _event):
        context.window_manager.invoke_search_popup(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        obj = context.view_layer.objects.get(self.name)
        if obj is None:
            return {'CANCELLED'}
        obj.hide_set(False)
        obj.hide_viewport = False
        return {'FINISHED'}


classes = (
    OBJECT_OT_mx_freeze_selected,
    OBJECT_OT_mx_freeze_unselected,
    OBJECT_OT_mx_unfreeze_all,
    OBJECT_OT_mx_unfreeze_by_name,
    OBJECT_OT_mx_unhide_by_name,
)
