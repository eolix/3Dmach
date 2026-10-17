# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Modify tab: object name and wire colour, the Modifier List, the modifier stack with Max's stack toolbar
(Pin Stack, Show End Result, Make Unique, Remove Modifier, Configure Modifier Sets) and the rollouts of the
selected stack entry.

The stack is drawn the Max way: the base object at the bottom and modifiers above it, last-applied on top
(Blender lists them in evaluation order, top to bottom). The selected entry is Blender's active modifier, or
the base object (remembered in ``state.stack_base_selected``). Under a mesh's "Editable Poly" entry, the
sub-object levels (Vertex, Edge, Border, Polygon, Element) switch Edit Mode like Max's.

Base entry rollouts:

- live primitives (``mx_primitives``): its "Parameters" rollout (``draw_parameters``);
- other meshes, "Editable Poly": Max's Editable Poly rollouts for the current sub-object level
  (``catalog.EDITABLE_POLY``), run on Blender's mesh operators (``edit_commands``);
- curves, "Editable Spline": ``catalog.EDITABLE_SPLINE``; lights, cameras, helpers, text: their parameters.

For live primitives the ``mx_primitives`` module is used through ``sys.modules["mx_primitives"]``:
``is_live_primitive(obj)``, ``get_parameters(obj)``, ``KINDS``, ``draw_parameters(layout, obj)`` and,
should a later version provide them, ``primitive_label(obj)`` and ``is_primitive_modifier(mod)``.

Collapse first calls ``object.mx_convert_to_editable_poly`` on live primitives.
"""

import bpy
from bpy.props import IntProperty
from bpy.types import Menu, Operator

from .. import utils
from .. import modifier_map
from ..placeholder import placeholder
from ..quad_menu import SUBOBJECT_LEVELS
from . import catalog, widgets
from .edit_commands import is_nurms_modifier, nurms_modifier

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

# Editable Spline sub-object levels: (keymap level, label, icon).
SPLINE_LEVELS = (
    ('VERTEX', "Vertex", 'VERTEXSEL'),
    ('EDGE', "Segment", 'EDGESEL'),
    ('BORDER', "Spline", 'CURVE_BEZCURVE'),
)


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
        try:
            if label is not None:
                return label(obj) or "Primitive"
            kind, _params = mod.get_parameters(obj)
            if kind == 'TEST_SHAPE':
                return "Teapot"
            return dict((k, name) for k, name, _desc in mod.KINDS).get(kind, "Primitive")
        except Exception:
            return "Primitive"
    return BASE_LABELS.get(obj.type, obj.type.title())


def stack_modifiers(obj):
    """The modifiers shown in the stack, in Blender (evaluation) order."""
    mod_prim = _primitives()
    hidden = getattr(mod_prim, "is_primitive_modifier", None) if mod_prim else None
    mods = []
    for mod in getattr(obj, "modifiers", ()):
        if is_nurms_modifier(mod):
            # Part of the base object (Subdivision Surface rollout), like Max's NURMS.
            continue
        if hidden is not None:
            try:
                if hidden(mod):
                    continue
            except Exception:
                pass
        mods.append(mod)
    return mods


def target_object(context):
    """The object the Modify tab shows: the pinned one (Pin Stack), else the active object."""
    state = utils.get_state(context)
    if state is not None and state.pin_object:
        obj = bpy.data.objects.get(state.pin_object)
        if obj is not None:
            return obj
    return context.active_object


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


def subobject_level(context, obj):
    """The Max sub-object level of ``obj`` (0 = object level; 1-5 Vertex, Edge, Border, Polygon, Element)."""
    if obj is None or obj.mode != 'EDIT':
        return 0
    stored = utils.keymap_subobject_level(context)
    if obj.type != 'MESH':
        return stored if stored in {1, 2, 3} else 1
    vert, edge, face = context.scene.tool_settings.mesh_select_mode
    if stored == 3 and edge:
        return 3
    if stored == 5 and face:
        return 5
    if vert:
        return 1
    return 2 if edge else 4


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
        return target_object(context) is not None

    def execute(self, context):
        obj = target_object(context)
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
    """Remove Modifier from the Stack: delete the selected modifier"""
    bl_idname = "object.mx_stack_remove"
    bl_label = "Remove Modifier from the Stack"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = target_object(context)
        return obj is not None and selected_modifier(context, obj) is not None

    def execute(self, context):
        obj = target_object(context)
        mod = selected_modifier(context, obj)
        index = list(obj.modifiers).index(mod)
        obj.modifiers.remove(mod)
        mods = stack_modifiers(obj)
        if mods:
            obj.modifiers.active = mods[min(index, len(mods) - 1)]
        return {'FINISHED'}


def collapse_stack(context, obj):
    """Apply every modifier (Max's Collapse All): the object becomes an Editable Poly with the result."""
    if obj.type not in {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META'}:
        raise ValueError("Only geometry can be collapsed")
    override = utils.object_context_override(context, obj)
    if obj.mode != 'OBJECT':
        with context.temp_override(**override):
            bpy.ops.object.mode_set(mode='OBJECT')
    with context.temp_override(**override):
        if utils.is_live_primitive(obj):
            # Otherwise the primitive's parameters would later regenerate the mesh over the collapsed result.
            bpy.ops.object.mx_convert_to_editable_poly()
        bpy.ops.object.convert(target='MESH')
    if END_RESULT_KEY in obj:
        del obj[END_RESULT_KEY]


class OBJECT_OT_mx_collapse_stack(Operator):
    """Collapse All: apply all modifiers to the base object"""
    bl_idname = "object.mx_collapse_stack"
    bl_label = "Collapse All"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = target_object(context)
        return obj is not None and obj.type in {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META'}

    def execute(self, context):
        try:
            collapse_stack(context, target_object(context))
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
        if mod.show_viewport and not is_nurms_modifier(mod):
            mod.show_viewport = False
            hidden.append(mod.name)
    obj[END_RESULT_KEY] = hidden


class OBJECT_OT_mx_show_end_result(Operator):
    """Show End Result: show the result of the whole stack, or only up to the selected entry"""
    bl_idname = "object.mx_show_end_result"
    bl_label = "Show End Result"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = target_object(context)
        return obj is not None and hasattr(obj, "modifiers")

    def execute(self, context):
        toggle_end_result(context, target_object(context))
        return {'FINISHED'}


class OBJECT_OT_mx_pin_stack(Operator):
    """Pin Stack: keep showing this object's stack while other objects are selected"""
    bl_idname = "object.mx_pin_stack"
    bl_label = "Pin Stack"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return target_object(context) is not None

    def execute(self, context):
        state = utils.get_state(context)
        if state.pin_object:
            state.pin_object = ""
        else:
            state.pin_object = target_object(context).name
        return {'FINISHED'}


def is_instanced(obj):
    data = getattr(obj, "data", None)
    return data is not None and data.users > 1


def make_unique(obj):
    """Max's Make Unique: give ``obj`` its own copy of shared (instanced) data."""
    if is_instanced(obj):
        obj.data = obj.data.copy()


class OBJECT_OT_mx_make_unique(Operator):
    """Make Unique: turn an instance into an independent copy of its data"""
    bl_idname = "object.mx_make_unique"
    bl_label = "Make Unique"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = target_object(context)
        return obj is not None and is_instanced(obj)

    def execute(self, context):
        make_unique(target_object(context))
        return {'FINISHED'}


class OBJECT_MT_mx_modifier_sets(Menu):
    """Configure Modifier Sets"""
    bl_idname = "OBJECT_MT_mx_modifier_sets"
    bl_label = "Configure Modifier Sets"

    def draw(self, _context):
        layout = self.layout
        placeholder(layout, "Configure Modifier Sets")
        placeholder(layout, "Show Buttons")
        placeholder(layout, "Show All Sets in List")
        layout.separator()
        for _cat_id, cat_label in modifier_map.CATEGORIES:
            placeholder(layout, cat_label, feature="Modifier set " + cat_label)


def draw_stack_context_menu(self, context):
    """Max's stack right-click entries, added to Blender's button menu for stack entries."""
    op = getattr(context, "button_operator", None)
    if op is None or op.bl_rna.identifier != "OBJECT_OT_mx_stack_select":
        return
    layout = self.layout
    layout.separator()
    layout.operator(OBJECT_OT_mx_collapse_stack.bl_idname)
    layout.operator(OBJECT_OT_mx_make_unique.bl_idname)
    layout.operator(OBJECT_OT_mx_stack_remove.bl_idname, text="Delete")


# -----------------------------------------------------------------------------
# Drawing: stack

def _draw_sublevels(col, context, obj):
    current = subobject_level(context, obj)
    levels = SUBOBJECT_LEVELS[1:] if obj.type == 'MESH' else SPLINE_LEVELS
    for level, label, _icon in levels:
        row = col.row(align=True)
        row.label(text="", icon='BLANK1')
        row.label(text="", icon='BLANK1')
        number = utils.SUBOBJECT_LEVEL_NUMBERS[level]
        # Like Max's stack: plain text entries, the current level highlighted.
        draw_level_button(row, obj, level, text=label, depress=current == number, emboss=current == number)


def draw_level_button(layout, obj, level, text="", icon='NONE', depress=False, emboss=True):
    """A sub-object level button (through `mx_keymap` when enabled; else meshes: our fallback, curves: Edit Mode)."""
    if utils.keymap_operator_available(utils.KEYMAP_SUBOBJECT_OPERATOR):
        props = layout.operator("mx_keymap.subobject_level", text=text, icon=icon, depress=depress, emboss=emboss)
        props.level = utils.SUBOBJECT_LEVEL_NUMBERS[level]
    elif obj.type == 'MESH':
        props = layout.operator("object.mx_ui_subobject_level", text=text, icon=icon, depress=depress, emboss=emboss)
        props.level = level
    else:
        props = layout.operator("object.mode_set", text=text, icon=icon, depress=depress, emboss=emboss)
        props.mode = 'EDIT'
    return props


def draw_stack(layout, context, obj):
    state = utils.get_state(context)
    mods = stack_modifiers(obj)
    all_mods = list(obj.modifiers)
    base_sel = base_selected(context, obj)

    box = layout.box()
    col = box.column(align=True)
    for mod in reversed(mods):
        row = col.row(align=True)
        row.prop(mod, "show_viewport", text="", emboss=False)
        selected = mod.is_active and not base_sel
        props = row.operator(OBJECT_OT_mx_stack_select.bl_idname, text=mod.name, depress=selected, emboss=selected)
        props.index = all_mods.index(mod)
    row = col.row(align=True)
    has_levels = obj.type in {'MESH', 'CURVE'} and not is_live_primitive(obj)
    if has_levels:
        row.prop(state, "stack_expanded", text="", emboss=False,
                 icon='TRIA_DOWN' if state.stack_expanded else 'TRIA_RIGHT')
    else:
        row.label(text="", icon='BLANK1')
    props = row.operator(OBJECT_OT_mx_stack_select.bl_idname, text=base_label(obj), depress=base_sel,
                         emboss=base_sel)
    props.index = -1
    if has_levels and state.stack_expanded:
        _draw_sublevels(col, context, obj)

    # Stack toolbar (below the stack, as in Max).
    row = layout.row(align=True)
    row.operator(OBJECT_OT_mx_pin_stack.bl_idname, text="", depress=bool(state.pin_object),
                 icon='PINNED' if state.pin_object else 'UNPINNED')
    row.operator(OBJECT_OT_mx_show_end_result.bl_idname, text="", icon='MODIFIER_ON',
                 depress=show_end_result(obj))
    row.operator(OBJECT_OT_mx_make_unique.bl_idname, text="", icon='UNLINKED')
    row.operator(OBJECT_OT_mx_stack_remove.bl_idname, text="", icon='TRASH')
    row.menu(OBJECT_MT_mx_modifier_sets.bl_idname, text="", icon='PREFERENCES')


# -----------------------------------------------------------------------------
# Drawing: parameters

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


def draw_object_parameters(layout, context, obj):
    """The parameters of a primitive, light, camera, helper or text. Returns False when there are none."""
    mod_prim = _primitives()
    if mod_prim is not None and is_live_primitive(obj):
        try:
            if mod_prim.draw_parameters(layout, obj) is not False:
                return True
        except Exception as ex:
            layout.label(text="Primitive parameters failed: {:s}".format(str(ex)), icon='ERROR')
            return True
    data = obj.data
    col = layout.column()
    col.use_property_split = True
    col.use_property_decorate = False
    if obj.type == 'LIGHT':
        col.prop(data, "type")
        col.prop(data, "color")
        col.prop(data, "energy")
        if data.type == 'SPOT':
            col.prop(data, "spot_size", text="Falloff/Field")
            col.prop(data, "spot_blend", text="Hotspot Blend")
        col.prop(data, "use_shadow", text="Shadows")
    elif obj.type == 'CAMERA':
        col.prop(data, "type", text="Projection")
        if data.type == 'PERSP':
            col.prop(data, "lens")
            col.prop(data, "angle", text="FOV")
        else:
            col.prop(data, "ortho_scale")
        col.prop(data, "clip_start")
        col.prop(data, "clip_end")
    elif obj.type == 'EMPTY':
        col.prop(obj, "empty_display_type", text="Display")
        col.prop(obj, "empty_display_size", text="Size")
    elif obj.type == 'FONT':
        col.prop(data, "body", text="Text")
        col.prop(data, "size")
        col.prop(data, "extrude")
        col.prop(data, "bevel_depth", text="Thickness")
    elif obj.type == 'CURVE':
        col.prop(data, "bevel_depth", text="Thickness")
        col.prop(data, "resolution_u", text="Steps")
    else:
        return False
    return True


def _special_subobject_levels(layout, context):
    obj = widgets.active_object(context)
    row = layout.row(align=True)
    row.scale_y = 1.4
    current = subobject_level(context, obj)
    for level, _label, icon in SUBOBJECT_LEVELS[1:]:
        number = utils.SUBOBJECT_LEVEL_NUMBERS[level]
        draw_level_button(row, obj, level, icon=icon, depress=current == number)


def _special_spline_levels(layout, context):
    obj = widgets.active_object(context)
    row = layout.row(align=True)
    row.scale_y = 1.4
    current = subobject_level(context, obj)
    for level, _label, icon in SPLINE_LEVELS:
        number = utils.SUBOBJECT_LEVEL_NUMBERS[level]
        draw_level_button(row, obj, level, icon=icon, depress=current == number)


_LEVEL_COUNTS = {
    1: ("total_vert_sel", "Vertices"),
    2: ("total_edge_sel", "Edges"),
    3: ("total_edge_sel", "Edges"),
    4: ("total_face_sel", "Polygons"),
    5: ("total_face_sel", "Polygons"),
}


def _special_selection_info(layout, context):
    obj = widgets.active_object(context)
    level = subobject_level(context, obj)
    row = layout.row()
    row.alignment = 'CENTER'
    row.active = False
    if level == 0 or obj.type != 'MESH':
        row.label(text="Whole Object Selected")
        return
    attr, noun = _LEVEL_COUNTS[level]
    count = getattr(obj.data, attr, 0)
    row.label(text="{:d} {:s} Selected".format(count, noun))


def _special_smoothing_groups(layout, _context):
    grid = layout.grid_flow(row_major=True, columns=8, even_columns=True, even_rows=True, align=True)
    for number in range(1, 33):
        placeholder(grid, str(number), feature="Smoothing group {:d}".format(number))


def _nurms_prop(layout, context, prop):
    mod = nurms_modifier(widgets.active_object(context))
    row = layout.row()
    if mod is None:
        row.active = False
        row.label(text="Iterations: 1 (NURMS off)")
        return
    row.prop(mod, prop, text="Iterations")


def _special_nurms_levels(layout, context):
    _nurms_prop(layout, context, "levels")


def _special_nurms_render_levels(layout, context):
    _nurms_prop(layout, context, "render_levels")


SPECIALS = {
    "SUBOBJECT_LEVELS": _special_subobject_levels,
    "SPLINE_LEVELS": _special_spline_levels,
    "SELECTION_INFO": _special_selection_info,
    "SMOOTHING_GROUPS": _special_smoothing_groups,
    "NURMS_LEVELS": _special_nurms_levels,
    "NURMS_RENDER_LEVELS": _special_nurms_render_levels,
}


def draw_editable_rollouts(layout, context, obj, rollouts):
    """Max's Editable Poly / Editable Spline rollouts for the current sub-object level."""
    level = subobject_level(context, obj)
    with widgets.target(obj):
        for data in rollouts:
            if data.levels and level not in data.levels:
                continue
            widgets.draw_rollout(layout, context, data, SPECIALS)


def draw_base_parameters(layout, context, obj):
    """The rollouts of the base stack entry."""
    if obj.type in {'MESH', 'CURVE'} and not is_live_primitive(obj):
        if obj != context.active_object:
            col = layout.column()
            col.active = False
            col.label(text="Pinned: select {:s} to edit it".format(obj.name), icon='PINNED')
            return
        rollouts = catalog.EDITABLE_POLY if obj.type == 'MESH' else catalog.EDITABLE_SPLINE
        draw_editable_rollouts(layout, context, obj, rollouts)
        return
    body = widgets.rollout(layout, "modify_parameters", "Parameters")
    if body is not None and not draw_object_parameters(body, context, obj):
        body.label(text="No parameters")


def draw(layout, context):
    obj = target_object(context)
    if obj is None:
        col = layout.column()
        col.active = False
        col.label(text="Select an object to modify")
        return

    row = layout.row(align=True)
    row.prop(obj, "name", text="")
    sub = row.row(align=True)
    sub.ui_units_x = 1.5
    sub.prop(obj, "color", text="")

    if not hasattr(obj, "modifiers"):
        draw_base_parameters(layout, context, obj)
        return

    layout.menu(modifier_map.OBJECT_MT_mx_modifier_list.bl_idname, text="Modifier List")
    draw_stack(layout, context, obj)

    mod = selected_modifier(context, obj)
    if mod is None:
        draw_base_parameters(layout, context, obj)
        return
    body = widgets.rollout(layout, "modify_modifier_parameters", "Parameters")
    if body is not None:
        draw_modifier_parameters(body, mod)


classes = (
    OBJECT_OT_mx_stack_select,
    OBJECT_OT_mx_stack_remove,
    OBJECT_OT_mx_collapse_stack,
    OBJECT_OT_mx_show_end_result,
    OBJECT_OT_mx_pin_stack,
    OBJECT_OT_mx_make_unique,
    OBJECT_MT_mx_modifier_sets,
)


def register():
    bpy.types.UI_MT_button_context_menu.append(draw_stack_context_menu)


def unregister():
    bpy.types.UI_MT_button_context_menu.remove(draw_stack_context_menu)
