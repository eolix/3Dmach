# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Top bar additions: Max-style Create, Modifiers and Group menus, and a compact main toolbar
(undo/redo, selection and transform tools, reference coordinate system, pivot, snaps, mirror, align,
material editor, render).
"""

import bpy
from bpy.types import Menu, Operator

from . import utils
from . import modifier_map
from .command_panel import create


class TOPBAR_MT_mx_create(Menu):
    bl_idname = "TOPBAR_MT_mx_create"
    bl_label = "Create"

    def draw(self, _context):
        layout = self.layout
        if utils.primitives_operator_available():
            layout.label(text="Standard Primitives", icon='MESH_CUBE')
            for kind, label in create.PRIMITIVES:
                layout.operator(utils.PRIMITIVE_OPERATOR_IDNAME, text=label).kind = kind
        else:
            layout.label(text="Standard Primitives need Max-Style Primitives", icon='INFO')
        layout.separator()
        layout.menu(TOPBAR_MT_mx_create_shapes.bl_idname, icon='CURVE_BEZCURVE')
        layout.menu(TOPBAR_MT_mx_create_lights.bl_idname, icon='LIGHT')
        layout.menu(TOPBAR_MT_mx_create_cameras.bl_idname, icon='CAMERA_DATA')
        layout.menu(TOPBAR_MT_mx_create_helpers.bl_idname, icon='EMPTY_AXIS')


class TOPBAR_MT_mx_create_shapes(Menu):
    bl_idname = "TOPBAR_MT_mx_create_shapes"
    bl_label = "Shapes"

    def draw(self, _context):
        for kind, label in create.SHAPES:
            self.layout.operator(create.CURVE_OT_mx_shape_add.bl_idname, text=label).kind = kind


class _CreateObjectsMenu:
    groups = ()

    def draw(self, _context):
        layout = self.layout
        for group in self.groups:
            for kind, label, _base, item_group, available in create.OBJECTS:
                if item_group == group and available:
                    layout.operator(create.OBJECT_OT_mx_create.bl_idname, text=label).kind = kind


class TOPBAR_MT_mx_create_lights(_CreateObjectsMenu, Menu):
    bl_idname = "TOPBAR_MT_mx_create_lights"
    bl_label = "Lights"
    groups = create.CATEGORY_GROUPS['LIGHTS']


class TOPBAR_MT_mx_create_cameras(_CreateObjectsMenu, Menu):
    bl_idname = "TOPBAR_MT_mx_create_cameras"
    bl_label = "Cameras"
    groups = create.CATEGORY_GROUPS['CAMERAS']


class TOPBAR_MT_mx_create_helpers(_CreateObjectsMenu, Menu):
    bl_idname = "TOPBAR_MT_mx_create_helpers"
    bl_label = "Helpers"
    groups = create.CATEGORY_GROUPS['HELPERS']


class TOPBAR_MT_mx_modifiers(Menu):
    bl_idname = "TOPBAR_MT_mx_modifiers"
    bl_label = "Modifiers"

    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        obj_type = obj.type if obj else None
        for cat_id, cat_label in modifier_map.CATEGORIES:
            entries = [entry for entry in modifier_map.MODIFIERS
                       if entry.category == cat_id and entry.available and obj_type in entry.object_types]
            if not entries:
                continue
            layout.label(text=cat_label)
            for entry in entries:
                layout.operator(modifier_map.OBJECT_OT_mx_modifier_add.bl_idname, text=entry.label).kind = entry.key
            layout.separator()
        layout.operator("object.mx_collapse", text="Collapse Stack")


class TOPBAR_MT_mx_group(Menu):
    bl_idname = "TOPBAR_MT_mx_group"
    bl_label = "Group"

    def draw(self, _context):
        layout = self.layout
        layout.operator("object.mx_group", text="Group...")
        layout.operator("object.mx_ungroup")
        layout.separator()
        layout.operator("object.mx_group_attach", text="Attach")
        layout.operator("object.mx_group_detach", text="Detach")


class SCREEN_OT_mx_material_editor(Operator):
    """Open the material (shader node) editor in a new window"""
    bl_idname = "screen.mx_material_editor"
    bl_label = "Material Editor"

    @classmethod
    def poll(cls, context):
        return context.window is not None and not bpy.app.background

    def execute(self, context):
        before = set(context.window_manager.windows)
        bpy.ops.wm.window_new()
        for window in context.window_manager.windows:
            if window not in before:
                area = window.screen.areas[0]
                area.ui_type = 'ShaderNodeTree'
                break
        return {'FINISHED'}


def draw_top_menus(self, context):
    prefs = utils.get_prefs(context)
    if prefs is None or not prefs.show_top_menus:
        return
    layout = self.layout
    layout.menu(TOPBAR_MT_mx_group.bl_idname)
    layout.menu(TOPBAR_MT_mx_create.bl_idname)
    layout.menu(TOPBAR_MT_mx_modifiers.bl_idname)


_TOOLS = (
    ("builtin.select_box", "RESTRICT_SELECT_OFF", "Select Object"),
    ("builtin.move", "EMPTY_ARROWS", "Select and Move"),
    ("builtin.rotate", "ORIENTATION_GIMBAL", "Select and Rotate"),
    ("builtin.scale", "OBJECT_ORIGIN", "Select and Scale"),
)


def draw_main_toolbar(self, context):
    prefs = utils.get_prefs(context)
    region = context.region
    if prefs is None or not prefs.show_main_toolbar or (region is not None and region.alignment != 'RIGHT'):
        return
    layout = self.layout
    scene = context.scene
    tool_settings = scene.tool_settings

    row = layout.row(align=True)
    row.operator("ed.undo", text="", icon='LOOP_BACK')
    row.operator("ed.redo", text="", icon='LOOP_FORWARDS')

    row = layout.row(align=True)
    for tool_id, icon, _label in _TOOLS:
        row.operator("wm.tool_set_by_id", text="", icon=icon).name = tool_id
    if utils.keymap_operator_available("MX_KEYMAP_OT_select_by_name"):
        row.operator("mx_keymap.select_by_name", text="", icon='VIEWZOOM')

    row = layout.row(align=True)
    row.ui_units_x = 4.5
    row.prop(scene.transform_orientation_slots[0], "type", text="")
    layout.prop(tool_settings, "transform_pivot_point", text="", icon_only=True)

    row = layout.row(align=True)
    row.prop(tool_settings, "use_snap", text="")
    row.popover(panel="VIEW3D_PT_snapping", text="")

    row = layout.row(align=True)
    row.operator("transform.mirror", text="", icon='MOD_MIRROR')
    row.operator("object.align", text="", icon='ALIGN_CENTER')

    row = layout.row(align=True)
    if utils.keymap_operator_available("MX_KEYMAP_OT_open_editor"):
        row.operator("mx_keymap.open_editor", text="", icon='MATERIAL').editor = 'MATERIAL'
        row.operator("mx_keymap.open_editor", text="", icon='PREFERENCES').editor = 'RENDER'
    else:
        row.operator(SCREEN_OT_mx_material_editor.bl_idname, text="", icon='MATERIAL')
    row.operator("render.render", text="", icon='RENDER_STILL')


classes = (
    TOPBAR_MT_mx_create_shapes,
    TOPBAR_MT_mx_create_lights,
    TOPBAR_MT_mx_create_cameras,
    TOPBAR_MT_mx_create_helpers,
    TOPBAR_MT_mx_create,
    TOPBAR_MT_mx_modifiers,
    TOPBAR_MT_mx_group,
    SCREEN_OT_mx_material_editor,
)


def register():
    bpy.types.TOPBAR_MT_editor_menus.append(draw_top_menus)
    bpy.types.TOPBAR_HT_upper_bar.append(draw_main_toolbar)


def unregister():
    bpy.types.TOPBAR_HT_upper_bar.remove(draw_main_toolbar)
    bpy.types.TOPBAR_MT_editor_menus.remove(draw_top_menus)
