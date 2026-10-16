# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Display tab: display colour, hide by category, hide, freeze, display properties and layers.

Hide by Category and the display colour apply to every 3D viewport (Max's settings are global, Blender's
are per viewport). Display properties apply to all selected objects, toggled from the active one.
"""

from bpy.props import EnumProperty
from bpy.types import Operator

from .. import utils
from .. import freeze
from ..state import HIDE_CATEGORIES

SEE_THROUGH_ALPHA = 0.4

DISPLAY_TOGGLES = (
    ('BOX', "Display as Box", "Draw the selected objects as their bounding box"),
    ('SEE_THROUGH', "See-Through", "Draw the selected objects semi-transparent (object colour alpha)"),
    ('EDGES', "Edged Faces", "Draw the wireframe on top of the selected objects' shaded surfaces"),
    ('NAME', "Show Name", "Show the names of the selected objects in the viewport"),
    ('IN_FRONT', "Always on Top", "Draw the selected objects in front of everything else"),
)


def display_toggle_state(obj, prop):
    if prop == 'BOX':
        return obj.display_type == 'BOUNDS'
    if prop == 'SEE_THROUGH':
        return obj.color[3] < 1.0
    if prop == 'EDGES':
        return obj.show_wire
    if prop == 'NAME':
        return obj.show_name
    if prop == 'IN_FRONT':
        return obj.show_in_front
    raise ValueError(prop)


def set_display_toggle(obj, prop, value):
    if prop == 'BOX':
        obj.display_type = 'BOUNDS' if value else 'TEXTURED'
    elif prop == 'SEE_THROUGH':
        color = list(obj.color)
        color[3] = SEE_THROUGH_ALPHA if value else 1.0
        obj.color = color
    elif prop == 'EDGES':
        obj.show_wire = value
    elif prop == 'NAME':
        obj.show_name = value
    elif prop == 'IN_FRONT':
        obj.show_in_front = value


class OBJECT_OT_mx_display_toggle(Operator):
    """Toggle a display property on the selected objects"""
    bl_idname = "object.mx_display_toggle"
    bl_label = "Toggle Display Property"
    bl_options = {'REGISTER', 'UNDO'}

    property: EnumProperty(name="Property", items=DISPLAY_TOGGLES)

    @classmethod
    def poll(cls, context):
        return context.active_object is not None or bool(context.selected_objects)

    @classmethod
    def description(cls, _context, properties):
        for key, _label, desc in DISPLAY_TOGGLES:
            if key == properties.property:
                return desc
        return None

    def execute(self, context):
        objects = list(context.selected_objects)
        reference = context.active_object if context.active_object in objects else (objects[0] if objects else None)
        if reference is None:
            return {'CANCELLED'}
        value = not display_toggle_state(reference, self.property)
        for obj in objects:
            set_display_toggle(obj, self.property, value)
        return {'FINISHED'}


def draw(layout, context):
    state = utils.get_state(context)
    obj = context.active_object

    header, body = layout.panel("MXUI_display_color", default_closed=True)
    header.label(text="Display Color")
    if body is not None:
        body.use_property_split = True
        body.use_property_decorate = False
        body.prop(state, "wire_display_color")
        body.prop(state, "shaded_display_color")

    header, body = layout.panel("MXUI_display_hide_by_category", default_closed=True)
    header.label(text="Hide by Category")
    if body is not None:
        col = body.column(align=True)
        for prop, _label, _kinds in HIDE_CATEGORIES:
            col.prop(state, prop)

    header, body = layout.panel("MXUI_display_hide")
    header.label(text="Hide")
    if body is not None:
        col = body.column(align=True)
        col.operator("object.hide_view_set", text="Hide Selected").unselected = False
        col.operator("object.hide_view_set", text="Hide Unselected").unselected = True
        col.operator(freeze.OBJECT_OT_mx_unhide_by_name.bl_idname, text="Unhide by Name")
        col.operator("object.hide_view_clear", text="Unhide All").select = False

    header, body = layout.panel("MXUI_display_freeze")
    header.label(text="Freeze")
    if body is not None:
        col = body.column(align=True)
        col.operator(freeze.OBJECT_OT_mx_freeze_selected.bl_idname, text="Freeze Selected")
        col.operator(freeze.OBJECT_OT_mx_freeze_unselected.bl_idname, text="Freeze Unselected")
        col.operator(freeze.OBJECT_OT_mx_unfreeze_by_name.bl_idname, text="Unfreeze by Name")
        col.operator(freeze.OBJECT_OT_mx_unfreeze_all.bl_idname, text="Unfreeze All")

    header, body = layout.panel("MXUI_display_properties", default_closed=True)
    header.label(text="Display Properties")
    if body is not None:
        col = body.column(align=True)
        for key, label, _desc in DISPLAY_TOGGLES:
            depress = obj is not None and display_toggle_state(obj, key)
            col.operator(OBJECT_OT_mx_display_toggle.bl_idname, text=label, depress=depress).property = key
        col.separator()
        col.prop(state, "backface_cull", toggle=True)

    header, body = layout.panel("MXUI_display_layers", default_closed=True)
    header.label(text="Layers")
    if body is not None:
        layer_collection = context.view_layer.active_layer_collection
        row = body.row()
        row.label(text="Current:", icon='OUTLINER_COLLECTION')
        row.label(text=layer_collection.name)
        col = body.column(align=True)
        col.operator("object.mx_new_layer_from_selection", icon='COLLECTION_NEW')
        col.operator("object.mx_add_to_current_layer")


classes = (
    OBJECT_OT_mx_display_toggle,
)
