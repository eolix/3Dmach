# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Utilities tab: Reset XForm, Collapse, Measure, Units Setup, Assign Random Wire Colors."""

import bmesh
import bpy
from bpy.types import Operator

from .. import utils
from .modify import collapse_stack


def reset_xform(context, objects):
    """Max's Reset XForm: bake rotation and scale into the geometry, keeping the objects in place."""
    objects = [obj for obj in objects if obj.is_editable and obj.type in {'MESH', 'CURVE', 'SURFACE', 'FONT'}]
    if not objects:
        return
    with context.temp_override(**utils.object_context_override(context, objects[0], objects)):
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)


def measure(context, obj):
    """Surface area and volume of ``obj``'s evaluated mesh, in scene units (world space)."""
    depsgraph = context.evaluated_depsgraph_get()
    obj_eval = obj.evaluated_get(depsgraph)
    mesh = obj_eval.to_mesh()
    try:
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bm.transform(obj.matrix_world)
        area = sum(face.calc_area() for face in bm.faces)
        volume = abs(bm.calc_volume(signed=True))
        bm.free()
    finally:
        obj_eval.to_mesh_clear()
    return area, volume


class OBJECT_OT_mx_reset_xform(Operator):
    """Reset XForm: bake rotation and scale into the selected objects' geometry"""
    bl_idname = "object.mx_reset_xform"
    bl_label = "Reset XForm"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and bool(context.selected_editable_objects)

    def execute(self, context):
        try:
            reset_xform(context, context.selected_editable_objects)
        except RuntimeError as ex:
            self.report({'ERROR'}, str(ex))
            return {'CANCELLED'}
        return {'FINISHED'}


class OBJECT_OT_mx_collapse(Operator):
    """Collapse the selected objects: apply their modifier stacks"""
    bl_idname = "object.mx_collapse"
    bl_label = "Collapse"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and bool(context.selected_editable_objects)

    def execute(self, context):
        for obj in list(context.selected_editable_objects):
            if obj.type in {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META'}:
                collapse_stack(context, obj)
        return {'FINISHED'}


class OBJECT_OT_mx_measure(Operator):
    """Measure the surface area and volume of the active object"""
    bl_idname = "object.mx_measure"
    bl_label = "Measure"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type in {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META'}

    def execute(self, context):
        obj = context.active_object
        state = utils.get_state(context)
        state.measure_area, state.measure_volume = measure(context, obj)
        state.measure_object = obj.name
        return {'FINISHED'}


def draw(layout, context):
    state = utils.get_state(context)
    obj = context.active_object

    header, body = layout.panel("MXUI_utilities")
    header.label(text="Utilities")
    if body is not None:
        grid = body.grid_flow(row_major=True, columns=2, even_columns=True, align=True)
        grid.operator(OBJECT_OT_mx_reset_xform.bl_idname)
        grid.operator(OBJECT_OT_mx_collapse.bl_idname)
        grid.operator(OBJECT_OT_mx_measure.bl_idname)
        grid.operator("scene.mx_units_setup", text="Units Setup...")
        grid.operator("object.mx_random_wire_color", text="Random Colors")
        grid.operator("object.mx_unfreeze_all")

    header, body = layout.panel("MXUI_utilities_measure")
    header.label(text="Measure")
    if body is None:
        return
    if obj is None:
        body.label(text="Select an object")
        return
    body.use_property_split = True
    body.use_property_decorate = False
    col = body.column()
    col.label(text=obj.name, icon='OBJECT_DATA')
    col.prop(obj, "dimensions")
    if state.measure_object == obj.name:
        col.prop(state, "measure_area")
        col.prop(state, "measure_volume")
    else:
        sub = col.row()
        sub.active = False
        sub.label(text="Press Measure for area and volume")


classes = (
    OBJECT_OT_mx_reset_xform,
    OBJECT_OT_mx_collapse,
    OBJECT_OT_mx_measure,
)
