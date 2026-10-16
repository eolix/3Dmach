# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Layers (Max's Layer / Scene Explorer) mapped onto collections.

In Max an object is on exactly one layer and new objects go to the current layer. Collections allow more,
so these operators keep to the Max model: moving objects to a layer unlinks them from their other
collections. The current layer is the active collection of the view layer. The explorer itself is an
Outliner in View Layer mode (see `layout`).
"""

import bpy
from bpy.props import StringProperty
from bpy.types import Operator

from . import utils


def next_layer_name(existing):
    return utils.max_style_name("Layer", existing)


def move_to_collection(objects, collection):
    for obj in objects:
        if collection not in obj.users_collection:
            collection.objects.link(obj)
        for other in list(obj.users_collection):
            if other != collection:
                other.objects.unlink(obj)


def new_layer_from_objects(scene, objects, name=None, make_current=True, view_layer=None):
    """Create a collection under the scene collection and move ``objects`` into it."""
    name = name or next_layer_name(bpy.data.collections.keys())
    collection = bpy.data.collections.new(name)
    scene.collection.children.link(collection)
    move_to_collection(objects, collection)
    if make_current and view_layer is not None:
        layer_collection = _find_layer_collection(view_layer.layer_collection, collection)
        if layer_collection is not None:
            view_layer.active_layer_collection = layer_collection
    return collection


def _find_layer_collection(layer_collection, collection):
    if layer_collection.collection == collection:
        return layer_collection
    for child in layer_collection.children:
        found = _find_layer_collection(child, collection)
        if found is not None:
            return found
    return None


class OBJECT_OT_mx_new_layer_from_selection(Operator):
    """Create a new layer (collection), move the selected objects to it and make it the current layer"""
    bl_idname = "object.mx_new_layer_from_selection"
    bl_label = "New Layer from Selection"
    bl_options = {'REGISTER', 'UNDO'}

    name: StringProperty(name="Name", description="Name of the new layer (empty for an automatic name)")

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and bool(context.selected_objects)

    def execute(self, context):
        collection = new_layer_from_objects(
            context.scene, context.selected_objects, self.name or None, view_layer=context.view_layer)
        self.report({'INFO'}, "Created layer {:s}".format(collection.name))
        return {'FINISHED'}


class OBJECT_OT_mx_add_to_current_layer(Operator):
    """Move the selected objects to the current layer (the active collection)"""
    bl_idname = "object.mx_add_to_current_layer"
    bl_label = "Add Selection to Current Layer"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and bool(context.selected_objects)

    def execute(self, context):
        collection = context.view_layer.active_layer_collection.collection
        if collection.library or collection.override_library:
            self.report({'ERROR'}, "The current layer is not editable")
            return {'CANCELLED'}
        move_to_collection(context.selected_objects, collection)
        return {'FINISHED'}


classes = (
    OBJECT_OT_mx_new_layer_from_selection,
    OBJECT_OT_mx_add_to_current_layer,
)
