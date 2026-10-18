# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
The quad menu: Max's right-click menu with four quadrants (tools 1, tools 2, display, transform).

It is a pie menu (``VIEW3D_MT_mx_quad``, opened with ``wm.call_menu_pie``). The two upper quadrants sit side by
side in the pie's North slot and the two lower ones in its South slot: Blender grows the North slot upwards and
the South slot downwards from the cursor, so the four boxed columns meet at the cursor without overlapping
(the diagonal slots are anchored at their top and overlap once the columns get long). The
contents are data (``QUADS``), selected by the current mode, so they can be checked by tests and extended
without touching the drawing code.

``mx_keymap`` binds right-click to it; for standalone use `prefs` can add an add-on keymap entry.
"""

import bpy
from bpy.props import EnumProperty
from bpy.types import Menu, Operator, Panel

from . import utils


class Op:
    """An operator item."""
    __slots__ = ("idname", "text", "icon", "props")

    def __init__(self, idname, text, icon='NONE', **props):
        self.idname = idname
        self.text = text
        self.icon = icon
        self.props = props


class Sub:
    """A submenu item."""
    __slots__ = ("menu", "text", "icon")

    def __init__(self, menu, text, icon='NONE'):
        self.menu = menu
        self.text = text
        self.icon = icon


SEP = None


def _tool(tool_id, text, icon):
    return Op("wm.tool_set_by_id", text, icon, name=tool_id)


# Sub-object levels (Editable Poly): Max hotkeys 1-5, 6 = back to the object.
SUBOBJECT_LEVELS = (
    ('TOP', "Top-level", 'OBJECT_DATAMODE'),
    ('VERTEX', "Vertex", 'VERTEXSEL'),
    ('EDGE', "Edge", 'EDGESEL'),
    ('BORDER', "Border", 'MOD_EDGESPLIT'),
    ('POLYGON', "Polygon", 'FACESEL'),
    ('ELEMENT', "Element", 'MESH_DATA'),
)

_SUBOBJECT_ITEMS = [Op("object.mx_ui_subobject_level", label, icon, level=level)
                    for level, label, icon in SUBOBJECT_LEVELS]

_TRANSFORM_OBJECT = [
    _tool("builtin.move", "Move", 'EMPTY_ARROWS'),
    _tool("builtin.rotate", "Rotate", 'ORIENTATION_GIMBAL'),
    _tool("builtin.scale", "Scale", 'OBJECT_ORIGIN'),
    SEP,
    _tool("builtin.select_box", "Select", 'RESTRICT_SELECT_OFF'),
    Op("object.select_grouped", "Select Similar", 'NONE', type='TYPE'),
    SEP,
    Op("object.mx_clone", "Clone", 'DUPLICATE'),
    Op("wm.call_panel", "Object Properties...", 'PROPERTIES', name="VIEW3D_PT_mx_object_properties",
       keep_open=True),
]

QUADS = {
    'OBJECT': {
        'NW': ("tools 1", [
            *_SUBOBJECT_ITEMS,
            SEP,
            Op("object.shade_smooth", "Shade Smooth", 'NONE'),
            Op("object.shade_flat", "Shade Flat", 'NONE'),
        ]),
        'NE': ("display", [
            Op("view3d.localview", "Isolate Selection", 'VIEW_ZOOM'),
            Op("object.mx_unfreeze_all", "Unfreeze All", 'NONE'),
            Op("object.mx_freeze_selected", "Freeze Selection", 'FREEZE'),
            SEP,
            Op("object.mx_unhide_by_name", "Unhide by Name", 'NONE'),
            Op("object.hide_view_clear", "Unhide All", 'NONE', select=False),
            Op("object.hide_view_set", "Hide Unselected", 'NONE', unselected=True),
            Op("object.hide_view_set", "Hide Selection", 'HIDE_ON', unselected=False),
        ]),
        'SW': ("tools 2", [
            Sub("VIEW3D_MT_mx_quad_convert", "Convert To:", 'NONE'),
            Op("object.mx_attach", "Attach", 'NONE'),
            SEP,
            Op("object.mx_new_layer_from_selection", "New Layer from Selection", 'COLLECTION_NEW'),
            Op("object.mx_add_to_current_layer", "Add to Current Layer", 'NONE'),
            SEP,
            Op("object.mx_group", "Group", 'GROUP'),
            Op("object.mx_ungroup", "Ungroup", 'NONE'),
            SEP,
            Op("transform.mirror", "Mirror", 'MOD_MIRROR'),
            Op("object.align", "Align", 'NONE'),
        ]),
        'SE': ("transform", _TRANSFORM_OBJECT),
    },
    'EDIT_MESH': {
        'NW': ("tools 1", [
            *_SUBOBJECT_ITEMS,
            SEP,
            Op("screen.repeat_last", "Repeat Last", 'RECOVER_LAST'),
            Op("mesh.bisect", "QuickSlice", 'NONE'),
            Op("mesh.loopcut_slide", "Swift Loop", 'NONE'),
            Op("mesh.knife_tool", "Cut", 'NONE'),
            SEP,
            Op("mesh.select_more", "Grow", 'NONE'),
            Op("mesh.select_less", "Shrink", 'NONE'),
            Op("mesh.select_edge_ring_multi", "Ring", 'NONE'),
            Op("mesh.select_edge_loop_multi", "Loop", 'NONE'),
        ]),
        'NE': ("display", [
            Op("view3d.localview", "Isolate Selection", 'VIEW_ZOOM'),
            Op("mesh.reveal", "Unhide All", 'NONE'),
            Op("mesh.hide", "Hide Unselected", 'NONE', unselected=True),
            Op("mesh.hide", "Hide Selection", 'HIDE_ON', unselected=False),
        ]),
        'SW': ("tools 2", [
            Op("mesh.edge_face_add", "Create", 'NONE'),
            Op("mesh.dissolve_mode", "Remove", 'NONE'),
            Op("view3d.edit_mesh_extrude_move_normal", "Extrude", 'NONE'),
            Op("mesh.bevel", "Chamfer", 'NONE', affect='EDGES'),
            Op("mesh.inset", "Inset", 'NONE'),
            Op("mesh.vert_connect_path", "Connect", 'NONE'),
            Op("mesh.subdivide_edgering", "Connect Edges", 'NONE'),
            Op("mesh.bridge_edge_loops", "Bridge", 'NONE'),
            SEP,
            Op("mesh.remove_doubles", "Weld", 'AUTOMERGE_OFF'),
            Op("mesh.merge", "Target Weld", 'NONE', type='LAST'),
            Op("mesh.merge", "Collapse", 'NONE', type='CENTER'),
            Op("mesh.fill_holes", "Cap", 'NONE'),
            Op("mesh.flip_normals", "Flip", 'NONE'),
            Op("mesh.face_make_planar", "Make Planar", 'NONE'),
            Op("mesh.subdivide", "Tessellate", 'NONE'),
            SEP,
            Op("object.mx_attach", "Attach", 'NONE'),
            Op("mesh.separate", "Detach", 'NONE', type='SELECTED'),
            Sub("VIEW3D_MT_mx_quad_convert_selection", "Convert Selection", 'NONE'),
        ]),
        'SE': ("transform", [
            _tool("builtin.move", "Move", 'EMPTY_ARROWS'),
            _tool("builtin.rotate", "Rotate", 'ORIENTATION_GIMBAL'),
            _tool("builtin.scale", "Scale", 'OBJECT_ORIGIN'),
            SEP,
            _tool("builtin.select_box", "Select", 'RESTRICT_SELECT_OFF'),
            Sub("VIEW3D_MT_edit_mesh_select_similar", "Select Similar", 'NONE'),
            SEP,
            Op("wm.call_panel", "Object Properties...", 'PROPERTIES', name="VIEW3D_PT_mx_object_properties",
               keep_open=True),
        ]),
    },
    # Any other mode: just the transform and display quadrants.
    'OTHER': {
        'NE': ("display", [
            Op("view3d.localview", "Isolate Selection", 'VIEW_ZOOM'),
        ]),
        'SE': ("transform", [
            _tool("builtin.move", "Move", 'EMPTY_ARROWS'),
            _tool("builtin.rotate", "Rotate", 'ORIENTATION_GIMBAL'),
            _tool("builtin.scale", "Scale", 'OBJECT_ORIGIN'),
            SEP,
            _tool("builtin.select_box", "Select", 'RESTRICT_SELECT_OFF'),
        ]),
    },
}

# Pie slot order is W, E, S, N, NW, NE, SW, SE: the first four stay empty.
PIE_SLOTS = ('W', 'E', 'S', 'N', 'NW', 'NE', 'SW', 'SE')
# Pie slot -> the quadrants drawn in it, left to right.
QUADRANT_ROWS = (('S', ('SW', 'SE')), ('N', ('NW', 'NE')))


def quads_for_mode(mode):
    return QUADS.get(mode) or QUADS['OTHER']


def _resolve_op(item):
    """Use the `mx_keymap` operators (same behaviour as the hotkeys) when that add-on is enabled."""
    if item.idname == "object.mx_clone":
        if utils.keymap_operator_available("MX_KEYMAP_OT_clone"):
            return Op("mx_keymap.clone", item.text, item.icon)
        return Op("object.duplicate_move", item.text, item.icon)
    return item


def draw_item(layout, item):
    if item is SEP:
        layout.separator()
    elif isinstance(item, Sub):
        layout.menu(item.menu, text=item.text, icon=item.icon)
    elif item.idname == "object.mx_ui_subobject_level":
        utils.subobject_operator(layout, item.props["level"], text=item.text, icon=item.icon)
    else:
        item = _resolve_op(item)
        props = layout.operator(item.idname, text=item.text, icon=item.icon)
        for key, value in item.props.items():
            setattr(props, key, value)


def draw_quadrant(layout, title, items):
    col = layout.column()
    box = col.box()
    inner = box.column(align=True)
    header = inner.row()
    header.active = False
    header.label(text=title)
    for item in items:
        draw_item(inner, item)


class VIEW3D_MT_mx_quad(Menu):
    bl_idname = "VIEW3D_MT_mx_quad"
    bl_label = "Quad Menu"

    def draw(self, context):
        pie = self.layout.menu_pie()
        quads = quads_for_mode(context.mode)
        # Pie items fill the slots in PIE_SLOTS order: W and E stay empty, then S and N get a row of two quadrants.
        pie.separator()
        pie.separator()
        for _slot, quadrants in QUADRANT_ROWS:
            split = pie.split(factor=0.5)
            for quadrant in quadrants:
                quad = quads.get(quadrant)
                if quad is None:
                    split.column()
                else:
                    draw_quadrant(split, *quad)


class VIEW3D_MT_mx_quad_convert(Menu):
    bl_idname = "VIEW3D_MT_mx_quad_convert"
    bl_label = "Convert To"

    def draw(self, context):
        layout = self.layout
        if utils.is_live_primitive(context.active_object):
            # Keeps the geometry and drops the primitive's parameters (operator of `mx_primitives`).
            layout.operator("object.mx_convert_to_editable_poly", text="Convert to Editable Poly")
            layout.operator("object.mx_convert_to_editable_poly", text="Convert to Editable Mesh")
        else:
            layout.operator("object.convert", text="Convert to Editable Poly").target = 'MESH'
            layout.operator("object.convert", text="Convert to Editable Mesh").target = 'MESH'
        layout.operator("object.convert", text="Convert to Editable Spline").target = 'CURVE'


class VIEW3D_MT_mx_quad_convert_selection(Menu):
    bl_idname = "VIEW3D_MT_mx_quad_convert_selection"
    bl_label = "Convert Selection"

    def draw(self, _context):
        layout = self.layout
        for select_type, text in (('VERT', "To Vertex"), ('EDGE', "To Edge"), ('FACE', "To Face")):
            props = layout.operator("mesh.select_mode", text=text)
            props.type = select_type
            props.use_expand = True


# -----------------------------------------------------------------------------
# Operators used by the quad menu

def set_subobject_level(context, obj, level):
    """Switch ``obj`` to a Max sub-object level, mapped onto Blender edit-mode select modes."""
    if level == 'TOP':
        if obj.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        return
    if obj.type != 'MESH':
        raise ValueError("Sub-object levels need a mesh object")
    if obj.mode != 'EDIT':
        bpy.ops.object.mode_set(mode='EDIT')
    if level == 'VERTEX':
        bpy.ops.mesh.select_mode(type='VERT')
    elif level == 'EDGE':
        bpy.ops.mesh.select_mode(type='EDGE')
    elif level == 'BORDER':
        # Phase 1 approximation: edge mode, selection reduced to the boundary loop of what is selected.
        bpy.ops.mesh.select_mode(type='EDGE')
        if obj.data.total_edge_sel:
            bpy.ops.mesh.region_to_loop()
    elif level == 'POLYGON':
        bpy.ops.mesh.select_mode(type='FACE')
    elif level == 'ELEMENT':
        # Phase 1 approximation: face mode, selection grown to whole connected elements.
        bpy.ops.mesh.select_mode(type='FACE')
        if obj.data.total_face_sel:
            bpy.ops.mesh.select_linked()


class OBJECT_OT_mx_ui_subobject_level(Operator):
    """Switch to a Max sub-object level (Vertex, Edge, Border, Polygon, Element) or back to the object.
    The quad menu and command panel use the Max-Style Keymap's fuller version when that add-on is enabled"""
    bl_idname = "object.mx_ui_subobject_level"
    bl_label = "Sub-Object Level"
    bl_options = {'REGISTER', 'UNDO'}

    level: EnumProperty(
        name="Level",
        items=[(level, label, "", icon, index) for index, (level, label, icon) in enumerate(SUBOBJECT_LEVELS)],
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH' and context.mode in {'OBJECT', 'EDIT_MESH'}

    def execute(self, context):
        try:
            set_subobject_level(context, context.active_object, self.level)
        except (ValueError, RuntimeError) as ex:
            self.report({'ERROR'}, str(ex))
            return {'CANCELLED'}
        return {'FINISHED'}


class OBJECT_OT_mx_attach(Operator):
    """Attach the other selected objects to the active one (join them into one object)"""
    bl_idname = "object.mx_attach"
    bl_label = "Attach"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type in {'MESH', 'CURVE'} and len(context.selected_objects) > 1

    def execute(self, context):
        obj = context.active_object
        was_edit = obj.mode == 'EDIT'
        if was_edit:
            bpy.ops.object.mode_set(mode='OBJECT')
        others = [o for o in context.selected_editable_objects if o != obj and o.type == obj.type]
        if others:
            with context.temp_override(**utils.object_context_override(context, obj, [obj, *others])):
                bpy.ops.object.join()
        if was_edit:
            bpy.ops.object.mode_set(mode='EDIT')
        return {'FINISHED'}


class VIEW3D_PT_mx_object_properties(Panel):
    """Max-style Object Properties, as a popup (quad menu > Object Properties...)"""
    bl_idname = "VIEW3D_PT_mx_object_properties"
    bl_label = "Object Properties"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'HEADER'
    bl_ui_units_x = 14

    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def draw(self, context):
        draw_object_properties(self.layout, context.active_object)


def draw_object_properties(layout, obj):
    from . import freeze
    layout.use_property_split = True
    layout.use_property_decorate = False

    box = layout.box()
    box.label(text="Object Information", icon='OBJECT_DATA')
    col = box.column()
    col.prop(obj, "name")
    col.prop(obj, "color", text="Wire Color")
    col.prop(obj, "dimensions")
    if obj.parent:
        col.prop(obj, "parent")

    box = layout.box()
    box.label(text="Interactivity", icon='RESTRICT_SELECT_OFF')
    col = box.column()
    col.prop(obj, "hide_viewport", text="Hide")
    row = col.row()
    row.enabled = False
    row.label(text="Frozen" if freeze.is_frozen(obj) else "Not frozen")

    box = layout.box()
    box.label(text="Display Properties", icon='SHADING_WIRE')
    col = box.column()
    col.prop(obj, "display_type", text="Display As")
    col.prop(obj, "show_wire", text="Edged Faces")
    col.prop(obj, "show_name")
    col.prop(obj, "show_in_front")

    box = layout.box()
    box.label(text="Rendering Control", icon='RESTRICT_RENDER_OFF')
    col = box.column()
    col.prop(obj, "hide_render", text="Hide in Renders")
    col.prop(obj, "visible_shadow", text="Cast Shadows")
    col.prop(obj, "visible_camera", text="Visible to Camera")


classes = (
    VIEW3D_MT_mx_quad_convert,
    VIEW3D_MT_mx_quad_convert_selection,
    VIEW3D_MT_mx_quad,
    OBJECT_OT_mx_ui_subobject_level,
    OBJECT_OT_mx_attach,
    VIEW3D_PT_mx_object_properties,
)
