# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Utilities tab: the Utilities rollout (More..., Sets, Configure Button Sets and the utility buttons, in Max's
order, ``catalog.UTILITIES``). Clicking an implemented utility (Collapse, Measure, Reset XForm) opens its
rollout below, like Max; the others are placeholders.
"""

import bmesh
import bpy
from bpy.props import StringProperty
from bpy.types import Menu, Operator

from .. import utils
from ..placeholder import placeholder
from . import catalog, widgets
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


class WM_OT_mx_utility(Operator):
    """Open this utility's rollout below (click again to close it)"""
    bl_idname = "wm.mx_utility"
    bl_label = "Utility"
    bl_options = {'INTERNAL'}

    utility: StringProperty(name="Utility", options={'SKIP_SAVE'})

    def execute(self, context):
        state = utils.get_state(context)
        state.utility_active = "" if state.utility_active == self.utility else self.utility
        return {'FINISHED'}


def draw_utility_button(layout, context, button):
    state = utils.get_state(context)
    if not button.key:
        placeholder(layout, button.label)
        return
    props = layout.operator(WM_OT_mx_utility.bl_idname, text=button.label,
                            depress=state.utility_active == button.key)
    props.utility = button.key


class OBJECT_MT_mx_more_utilities(Menu):
    """More utilities"""
    bl_idname = "OBJECT_MT_mx_more_utilities"
    bl_label = "Utilities"

    def draw(self, context):
        for button in catalog.MORE_UTILITIES:
            draw_utility_button(self.layout, context, button)


def _close_button(layout):
    layout.operator(WM_OT_mx_utility.bl_idname, text="Close").utility = ""


def draw_collapse(layout, context):
    selected = len(utils.selected_objects(context))
    layout.label(text="Selected Objects: {:d}".format(selected))
    layout.label(text="Output Type:")
    col = layout.column(align=True)
    placeholder(col, "Modifier Stack Result", icon='RADIOBUT_ON', emboss=False,
                feature="Output type choice (always Modifier Stack Result)")
    placeholder(col, "Mesh", icon='RADIOBUT_OFF', emboss=False)
    layout.operator(OBJECT_OT_mx_collapse.bl_idname, text="Collapse Selected")


def draw_measure(layout, context):
    state = utils.get_state(context)
    obj = context.active_object
    if obj is None:
        layout.label(text="Select an object")
        return
    col = layout.column()
    col.use_property_split = True
    col.use_property_decorate = False
    col.label(text=obj.name, icon='OBJECT_DATA')
    col.operator(OBJECT_OT_mx_measure.bl_idname)
    if state.measure_object == obj.name:
        col.prop(state, "measure_area")
        col.prop(state, "measure_volume")
    else:
        sub = col.row()
        sub.active = False
        sub.label(text="Press Measure for area and volume")
    placeholder(col, "Center of Mass")
    col.prop(obj, "dimensions")


def draw_reset_xform(layout, _context):
    layout.operator(OBJECT_OT_mx_reset_xform.bl_idname, text="Reset Selected")


UTILITY_ROLLOUTS = {
    'COLLAPSE': ("Collapse", draw_collapse),
    'MEASURE': ("Measure", draw_measure),
    'RESET_XFORM': ("Reset XForm", draw_reset_xform),
}
assert {button.key for button in catalog.UTILITIES if button.key} == set(UTILITY_ROLLOUTS)


def draw(layout, context):
    state = utils.get_state(context)
    body = widgets.rollout(layout, "utilities", "Utilities")
    if body is not None:
        row = body.row(align=False)
        row.menu(OBJECT_MT_mx_more_utilities.bl_idname, text="More...")
        placeholder(row, "Sets")
        placeholder(row, "", icon='PREFERENCES', feature="Configure Button Sets")
        col = body.column(align=False)
        for button in catalog.UTILITIES:
            draw_utility_button(col, context, button)

    entry = UTILITY_ROLLOUTS.get(state.utility_active)
    if entry is None:
        return
    title, draw_function = entry
    body = widgets.rollout(layout, "utility_" + state.utility_active.lower(), title)
    if body is not None:
        draw_function(body, context)
        _close_button(body)


classes = (
    OBJECT_OT_mx_reset_xform,
    OBJECT_OT_mx_collapse,
    OBJECT_OT_mx_measure,
    WM_OT_mx_utility,
    OBJECT_MT_mx_more_utilities,
)
