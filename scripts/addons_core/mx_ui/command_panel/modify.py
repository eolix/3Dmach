# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Modify tab: object name and wire colour, the Modifier List, the modifier stack and the parameters of the
selected stack entry.

The stack is drawn the Max way: the base object at the bottom and modifiers above it, last-applied on top
(Blender lists them in evaluation order, top to bottom). The selected entry is Blender's active modifier, or
the base object (remembered in ``state.stack_base_selected``).

For live primitives the base entry's parameters come from the ``mx_primitives`` add-on, called through
its module (``sys.modules["mx_primitives"]``), which offers:

- ``draw_parameters(layout, obj)`` (required): draws the primitive's parameters; returning ``False`` means
  "not a live primitive", and the base entry is drawn as a plain mesh;
- ``is_live_primitive(obj)`` (optional): checked first when present;
- ``primitive_label(obj)`` (optional): the base entry's name ("Box", "Sphere", ...);
- ``is_primitive_modifier(mod)`` (optional): modifiers that implement the primitive (e.g. a Geometry
  Nodes modifier), folded into the base entry instead of being listed.
"""

import bpy
from bpy.props import IntProperty
from bpy.types import Operator

from .. import utils
from .. import modifier_map
from ..quad_menu import SUBOBJECT_LEVELS

END_RESULT_KEY = "mx_end_result_hidden"

BASE_LABELS = {
    'MESH': "Editable Poly",
    'CURVE': "Editable Spline",
    'SURFACE': "NURBS Surface",
    'FONT': "Text",
    'META': "Metaball",
    'LIGHT': "Light",
    'CAMERA': "Camera",
    'EMPTY': "Dummy",
    'LATTICE': "Lattice",
    'ARMATURE': "Bones",
    'GREASEPENCIL': "Grease Pencil",
    'CURVES': "Hair Curves",
    'POINTCLOUD': "Point Cloud",
    'VOLUME': "Volume",
}


# -----------------------------------------------------------------------------
# Live primitives (optional `mx_primitives` add-on)

def _primitives():
    return utils.primitives_module()


def is_live_primitive(obj):
    mod = _primitives()
    if mod is None:
        return False
    check = getattr(mod, "is_live_primitive", None)
    if check is not None:
        try:
            return bool(check(obj))
        except Exception:
            return False
    return hasattr(mod, "draw_parameters")


def base_label(obj):
    mod = _primitives()
    if mod is not None and is_live_primitive(obj):
        label = getattr(mod, "primitive_label", None)
        if label is not None:
            try:
                text = label(obj)
                if text:
                    return text
            except Exception:
                pass
    return BASE_LABELS.get(obj.type, obj.type.title())


def stack_modifiers(obj):
    """The modifiers shown in the stack, in Blender (evaluation) order."""
    mod_prim = _primitives()
    hidden = getattr(mod_prim, "is_primitive_modifier", None) if mod_prim else None
    mods = []
    for mod in getattr(obj, "modifiers", ()):
        if hidden is not None:
            try:
                if hidden(mod):
                    continue
            except Exception:
                pass
        mods.append(mod)
    return mods


def base_selected(context, obj):
    state = utils.get_state(context)
    if state is not None and state.stack_base_selected == obj.name:
        return True
    return not any(mod.is_active for mod in stack_modifiers(obj))


def selected_modifier(context, obj):
    if base_selected(context, obj):
        return None
    for mod in stack_modifiers(obj):
        if mod.is_active:
            return mod
    return None


# -----------------------------------------------------------------------------
# Operators

class OBJECT_OT_mx_stack_select(Operator):
    """Select this modifier stack entry and show its parameters"""
    bl_idname = "object.mx_stack_select"
    bl_label = "Select Stack Entry"
    bl_options = {'INTERNAL'}

    index: IntProperty(name="Index", description="Modifier index, -1 for the base object", default=-1, min=-1)

    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def execute(self, context):
        obj = context.active_object
        state = utils.get_state(context)
        if self.index < 0:
            state.stack_base_selected = obj.name
        else:
            if self.index >= len(obj.modifiers):
                return {'CANCELLED'}
            obj.modifiers.active = obj.modifiers[self.index]
            state.stack_base_selected = ""
        return {'FINISHED'}


class OBJECT_OT_mx_stack_remove(Operator):
    """Remove the selected modifier from the stack"""
    bl_idname = "object.mx_stack_remove"
    bl_label = "Remove Modifier from the Stack"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and selected_modifier(context, obj) is not None

    def execute(self, context):
        obj = context.active_object
        mod = selected_modifier(context, obj)
        index = list(obj.modifiers).index(mod)
        obj.modifiers.remove(mod)
        if obj.modifiers:
            obj.modifiers.active = obj.modifiers[min(index, len(obj.modifiers) - 1)]
        return {'FINISHED'}


def collapse_stack(context, obj):
    """Apply every modifier (Max's Collapse All): the object becomes an Editable Poly with the result."""
    if obj.type not in {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META'}:
        raise ValueError("Only geometry can be collapsed")
    if obj.mode != 'OBJECT':
        with context.temp_override(**utils.object_context_override(context, obj)):
            bpy.ops.object.mode_set(mode='OBJECT')
    with context.temp_override(**utils.object_context_override(context, obj)):
        bpy.ops.object.convert(target='MESH')
    if END_RESULT_KEY in obj:
        del obj[END_RESULT_KEY]


class OBJECT_OT_mx_collapse_stack(Operator):
    """Collapse the modifier stack: apply all modifiers to the base object"""
    bl_idname = "object.mx_collapse_stack"
    bl_label = "Collapse All"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type in {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META'}

    def execute(self, context):
        try:
            collapse_stack(context, context.active_object)
        except (ValueError, RuntimeError) as ex:
            self.report({'ERROR'}, str(ex))
            return {'CANCELLED'}
        return {'FINISHED'}


def show_end_result(obj):
    return END_RESULT_KEY not in obj


def toggle_end_result(context, obj):
    """
    Max's "Show end result" switch. Off: the modifiers above the selected entry are hidden in the viewport
    (their names are stored on the object); on: they are shown again.
    """
    if not show_end_result(obj):
        names = set(obj[END_RESULT_KEY])
        for mod in obj.modifiers:
            if mod.name in names:
                mod.show_viewport = True
        del obj[END_RESULT_KEY]
        return
    mods = list(obj.modifiers)
    selected = selected_modifier(context, obj)
    start = 0 if selected is None else mods.index(selected) + 1
    hidden = []
    for mod in mods[start:]:
        if mod.show_viewport:
            mod.show_viewport = False
            hidden.append(mod.name)
    obj[END_RESULT_KEY] = hidden


class OBJECT_OT_mx_show_end_result(Operator):
    """Show the end result of the whole stack, or only the result up to the selected entry"""
    bl_idname = "object.mx_show_end_result"
    bl_label = "Show End Result"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and hasattr(obj, "modifiers")

    def execute(self, context):
        toggle_end_result(context, context.active_object)
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Drawing

def draw_stack(layout, context, obj):
    mods = stack_modifiers(obj)
    all_mods = list(obj.modifiers)
    base_sel = base_selected(context, obj)

    box = layout.box()
    col = box.column(align=True)
    for mod in reversed(mods):
        row = col.row(align=True)
        row.prop(mod, "show_viewport", text="", emboss=False)
        props = row.operator(OBJECT_OT_mx_stack_select.bl_idname, text=mod.name,
                             depress=mod.is_active and not base_sel, emboss=mod.is_active and not base_sel)
        props.index = all_mods.index(mod)
    row = col.row(align=True)
    row.label(text="", icon='OBJECT_DATA')
    props = row.operator(OBJECT_OT_mx_stack_select.bl_idname, text=base_label(obj), depress=base_sel,
                         emboss=base_sel)
    props.index = -1

    # Stack toolbar (below the stack, as in Max).
    row = layout.row(align=True)
    row.operator(OBJECT_OT_mx_show_end_result.bl_idname, text="", icon='MOD_SUBSURF',
                 depress=show_end_result(obj))
    row.operator(OBJECT_OT_mx_stack_remove.bl_idname, text="", icon='TRASH')
    row.separator()
    row.operator(OBJECT_OT_mx_collapse_stack.bl_idname, text="Collapse", icon='MOD_REMESH')


def draw_modifier_parameters(layout, mod):
    layout.use_property_split = True
    layout.use_property_decorate = False
    if mod.type == 'NODES':
        draw_node_group_inputs(layout, mod)
        return
    col = layout.column()
    for name in modifier_map.parameter_names(mod):
        col.prop(mod, name)


def draw_node_group_inputs(layout, mod):
    layout.prop(mod, "node_group")
    group = mod.node_group
    if group is None:
        return
    inputs = mod.properties.inputs
    for item in group.interface.items_tree:
        if item.item_type != 'SOCKET' or item.in_out != 'INPUT':
            continue
        input_ptr = getattr(inputs, item.identifier, None)
        if input_ptr is None or "value" not in input_ptr.bl_rna.properties:
            continue
        layout.prop(input_ptr, "value", text=item.name)


def draw_base_parameters(layout, context, obj):
    mod_prim = _primitives()
    if mod_prim is not None and is_live_primitive(obj):
        try:
            if mod_prim.draw_parameters(layout, obj) is not False:
                return
        except Exception as ex:
            layout.label(text="Primitive parameters failed: {:s}".format(str(ex)), icon='ERROR')
            return

    layout.use_property_split = True
    layout.use_property_decorate = False
    data = obj.data
    if obj.type == 'MESH':
        header, body = layout.panel("MXUI_modify_selection")
        header.label(text="Selection")
        if body is not None:
            row = body.row(align=True)
            row.scale_y = 1.3
            for level, label, icon in SUBOBJECT_LEVELS[1:]:
                row.operator("object.mx_ui_subobject_level", text="", icon=icon).level = level
            sub = body.row()
            sub.active = False
            sub.label(text="{:d} vertices, {:d} polygons".format(len(data.vertices), len(data.polygons)))
        header, body = layout.panel("MXUI_modify_subdivision_surface", default_closed=True)
        header.label(text="Subdivision Surface")
        if body is not None:
            body.operator(modifier_map.OBJECT_OT_mx_modifier_add.bl_idname,
                          text="Add TurboSmooth").kind = 'TURBOSMOOTH'
    elif obj.type in {'CURVE', 'FONT'}:
        header, body = layout.panel("MXUI_modify_rendering")
        header.label(text="Rendering")
        if body is not None:
            col = body.column()
            col.prop(data, "bevel_depth", text="Thickness")
            col.prop(data, "bevel_resolution", text="Sides")
            col.prop(data, "resolution_u", text="Interpolation Steps")
            if obj.type == 'CURVE':
                col.prop(data, "fill_mode")
            else:
                col.prop(data, "body", text="Text")
                col.prop(data, "size")
    elif obj.type == 'LIGHT':
        col = layout.column()
        col.prop(data, "type")
        col.prop(data, "color")
        col.prop(data, "energy")
        if data.type == 'SPOT':
            col.prop(data, "spot_size", text="Falloff/Field")
            col.prop(data, "spot_blend", text="Hotspot Blend")
        col.prop(data, "use_shadow", text="Shadows")
    elif obj.type == 'CAMERA':
        col = layout.column()
        col.prop(data, "type", text="Projection")
        if data.type == 'PERSP':
            col.prop(data, "lens")
            col.prop(data, "angle", text="FOV")
        else:
            col.prop(data, "ortho_scale")
        col.prop(data, "clip_start")
        col.prop(data, "clip_end")
    elif obj.type == 'EMPTY':
        col = layout.column()
        col.prop(obj, "empty_display_type", text="Display")
        col.prop(obj, "empty_display_size", text="Size")
    else:
        layout.label(text="No parameters")


def draw(layout, context):
    obj = context.active_object
    if obj is None:
        col = layout.column()
        col.active = False
        col.label(text="Select an object to modify")
        return

    row = layout.row(align=True)
    row.prop(obj, "name", text="")
    sub = row.row(align=True)
    sub.ui_units_x = 2.0
    sub.prop(obj, "color", text="")

    if not hasattr(obj, "modifiers"):
        draw_base_parameters(layout, context, obj)
        return

    layout.menu(modifier_map.OBJECT_MT_mx_modifier_list.bl_idname, text="Modifier List", icon='DOWNARROW_HLT')
    draw_stack(layout, context, obj)

    mod = selected_modifier(context, obj)
    header, body = layout.panel("MXUI_modify_parameters")
    header.label(text="Parameters" if mod is None else mod.name)
    if body is None:
        return
    if mod is None:
        draw_base_parameters(body, context, obj)
    else:
        draw_modifier_parameters(body, mod)


classes = (
    OBJECT_OT_mx_stack_select,
    OBJECT_OT_mx_stack_remove,
    OBJECT_OT_mx_collapse_stack,
    OBJECT_OT_mx_show_end_result,
)
