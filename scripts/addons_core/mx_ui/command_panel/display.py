# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Display tab: Display Color, Hide by Category, Hide, Freeze, Display Properties and Link Display
(``catalog.DISPLAY``).

Hide by Category and the display colour apply to every 3D viewport (Max's settings are global, Blender's
are per viewport). Display properties apply to all selected objects, toggled from the active one.
"""

from bpy.props import EnumProperty
from bpy.types import Operator

from .. import utils
from ..placeholder import placeholder
from ..state import HIDE_CATEGORIES
from . import catalog, widgets

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


def _check(value):
    return 'CHECKBOX_HLT' if value else 'CHECKBOX_DEHLT'


def _placeholder_check(layout, text):
    placeholder(layout, text, icon='CHECKBOX_DEHLT', emboss=False)


def _special_display_color(layout, context):
    state = utils.get_state(context)
    layout.label(text="Wireframe:")
    row = layout.row()
    row.prop_enum(state, "wire_display_color", 'OBJECT', text="Object Color")
    placeholder(row, "Material Color", feature="Wireframe in Material Color")
    layout.label(text="Shaded:")
    row = layout.row()
    row.prop_enum(state, "shaded_display_color", 'OBJECT', text="Object Color")
    row.prop_enum(state, "shaded_display_color", 'MATERIAL', text="Material Color")


# Max's Hide by Category list: state properties, or None for categories without a Blender equivalent.
_HIDE_BY_CATEGORY = (
    ("hide_geometry", "Geometry"),
    ("hide_shapes", "Shapes"),
    ("hide_lights", "Lights"),
    ("hide_cameras", "Cameras"),
    ("hide_helpers", "Helpers"),
    (None, "Space Warps"),
    (None, "Particle Systems"),
    ("hide_bones", "Bone Objects"),
)
assert {prop for prop, _label in _HIDE_BY_CATEGORY if prop} == {prop for prop, *_rest in HIDE_CATEGORIES}


def _special_hide_by_category(layout, context):
    state = utils.get_state(context)
    col = layout.column(align=True)
    for prop, label in _HIDE_BY_CATEGORY:
        if prop is None:
            _placeholder_check(col, label)
        else:
            col.prop(state, prop, text=label)


def _special_display_properties(layout, context):
    state = utils.get_state(context)
    prefs = utils.get_prefs(context)
    obj = context.active_object
    col = layout.column(align=True)

    def toggle(key, label):
        on = obj is not None and display_toggle_state(obj, key)
        col.operator(OBJECT_OT_mx_display_toggle.bl_idname, text=label, icon=_check(on),
                     emboss=False).property = key

    toggle('BOX', "Display as Box")
    col.prop(state, "backface_cull")
    _placeholder_check(col, "Edges Only")
    _placeholder_check(col, "Vertex Ticks")
    _placeholder_check(col, "Trajectory")
    toggle('SEE_THROUGH', "See-Through")
    _placeholder_check(col, "Ignore Extents")
    if prefs is not None:
        col.prop(prefs, "frozen_in_gray", text="Show Frozen in Gray")
    else:
        _placeholder_check(col, "Show Frozen in Gray")
    _placeholder_check(col, "Never Degrade")
    row = col.row()
    _placeholder_check(row, "Vertex Colors")
    placeholder(row, "Shaded", feature="Vertex Colors Shaded")


SPECIALS = {
    "DISPLAY_COLOR": _special_display_color,
    "HIDE_BY_CATEGORY": _special_hide_by_category,
    "DISPLAY_PROPERTIES": _special_display_properties,
}


def draw(layout, context):
    for data in catalog.DISPLAY:
        widgets.draw_rollout(layout, context, data, SPECIALS)


classes = (
    OBJECT_OT_mx_display_toggle,
)
