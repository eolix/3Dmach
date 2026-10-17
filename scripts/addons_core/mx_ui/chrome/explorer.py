# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
The Scene Explorer: Blender's Outliner dressed as Max's explorer.

    | Select  Display  Edit  Customize      |  menu row        (strip 'EXPLORER_MENUS')
    | [find........] (filter) (lock) (...)  |  find row        (strip 'EXPLORER_FIND')
    |F| Name (Sorted Ascending)    Frozen  |  Outliner header (column titles)
    |i| > Box001                      ...   |  Outliner (View Layer mode)
    |l|                                     |
    | [Default v]  (hierarchy) (layer)      |  footer          (strip 'EXPLORER_FOOTER')

The filter bar on the left (strip 'FILTER_BAR') toggles the Outliner's object filters. Max's "Frozen" column
is the Outliner's selectability column: in the Max Layout, toggling it freezes or unfreezes the object the
Max way (gray, flagged, see ``freeze.py``), through a message-bus subscription on ``Object.hide_select``.
Sort by Hierarchy / Sort by Layer switch the Outliner between objects with their children and collections.
"""

import bpy
from bpy.app.handlers import persistent
from bpy.props import EnumProperty, StringProperty
from bpy.types import Menu, Operator

from .. import freeze, utils
from ..placeholder import placeholder
from . import _areas

# (label, icon, Outliner filter property or None for a placeholder): Max's object type filters.
TYPE_FILTERS = (
    ("Display Geometry", 'MESH_CUBE', "use_filter_object_mesh"),
    ("Display Shapes", 'CURVE_BEZCURVE', "use_filter_object_others"),
    ("Display Lights", 'LIGHT', "use_filter_object_light"),
    ("Display Cameras", 'CAMERA_DATA', "use_filter_object_camera"),
    ("Display Helpers", 'EMPTY_AXIS', "use_filter_object_empty"),
    ("Display Space Warps", 'FORCE_FORCE', None),
    ("Display Groups/Assemblies", 'GROUP', None),
    ("Display Object XRefs", 'LINKED', None),
    ("Display Bones", 'BONE_DATA', "use_filter_object_armature"),
    ("Display Containers", 'PACKAGE', None),
)
TYPE_FILTER_PROPS = tuple(prop for _label, _icon, prop in TYPE_FILTERS if prop) + ("use_filter_object_grease_pencil",)


# -----------------------------------------------------------------------------
# Outliner state helpers (plain functions, tested headless)

def shows_frozen(space):
    return space.filter_state in {'ALL', 'VISIBLE'}


def shows_hidden(space):
    return space.filter_state == 'ALL'


def set_state_filters(space, frozen, hidden):
    """Map Max's Display Frozen / Display Hidden onto the Outliner's single object state filter."""
    if not frozen:
        space.filter_state = 'SELECTABLE'
    elif hidden:
        space.filter_state = 'ALL'
    else:
        space.filter_state = 'VISIBLE'


def set_type_filters(space, action):
    for prop in TYPE_FILTER_PROPS:
        value = getattr(space, prop)
        setattr(space, prop, {'ALL': True, 'NONE': False, 'INVERT': not value}[action])
    if action == 'ALL':
        set_state_filters(space, True, True)


def sort_mode(space):
    return 'LAYER' if space.use_filter_collection else 'HIERARCHY'


def set_sort_mode(space, mode):
    space.display_mode = 'VIEW_LAYER'
    space.use_filter_children = True
    space.use_filter_collection = mode == 'LAYER'


# -----------------------------------------------------------------------------
# Operators

def _explorer_area(context):
    screen = context.screen
    area = _areas.find_area(screen, 'EXPLORER')
    if area is None or area.type != 'OUTLINER':
        area = next((a for a in screen.areas if a.type == 'OUTLINER'), None) if screen else None
    return area


class _ExplorerOperator:
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return _areas.explorer_space(context) is not None

    def redraw(self, context):
        area = _explorer_area(context)
        if area is not None:
            area.tag_redraw()


class MXUI_OT_explorer_display(_ExplorerOperator, Operator):
    """Display all, no or the other object types in the Scene Explorer"""
    bl_idname = "mx_ui.explorer_display"
    bl_label = "Explorer Display Filter"

    action: EnumProperty(
        name="Action",
        items=(
            ('ALL', "Display All", "Show every object type"),
            ('NONE', "Display None", "Hide every object type"),
            ('INVERT', "Invert Display", "Swap shown and hidden object types"),
            ('FROZEN', "Display Frozen", "Show or hide frozen objects"),
            ('HIDDEN', "Display Hidden", "Show or hide hidden objects"),
        ),
    )

    @classmethod
    def description(cls, _context, properties):
        prop = cls.bl_rna.properties["action"]
        return next(item.description for item in prop.enum_items if item.identifier == properties.action)

    def execute(self, context):
        space = _areas.explorer_space(context)
        if self.action == 'FROZEN':
            set_state_filters(space, not shows_frozen(space), shows_hidden(space))
        elif self.action == 'HIDDEN':
            set_state_filters(space, True, not shows_hidden(space))
        else:
            set_type_filters(space, self.action)
        self.redraw(context)
        return {'FINISHED'}


class MXUI_OT_explorer_sort(_ExplorerOperator, Operator):
    """Sort the Scene Explorer by hierarchy (objects and their children) or by layer (collections)"""
    bl_idname = "mx_ui.explorer_sort"
    bl_label = "Explorer Sort"

    mode: EnumProperty(
        name="Sort",
        items=(
            ('HIERARCHY', "Sort by Hierarchy", "Objects with their children"),
            ('LAYER', "Sort by Layer", "Objects in their layers (collections)"),
        ),
    )

    def execute(self, context):
        set_sort_mode(_areas.explorer_space(context), self.mode)
        self.redraw(context)
        return {'FINISHED'}


# Outliner operators the explorer menus may run in the explorer's area.
OUTLINER_OPERATORS = {
    "outliner.expanded_toggle",
    "outliner.show_hierarchy",
    "outliner.show_one_level",
    "outliner.collection_new",
    "outliner.select_all",
}


class MXUI_OT_explorer_outliner_op(_ExplorerOperator, Operator):
    """Run an Outliner command in the Scene Explorer"""
    bl_idname = "mx_ui.explorer_outliner_op"
    bl_label = "Explorer Command"

    operator: StringProperty(name="Operator")
    open: bpy.props.BoolProperty(name="Open", default=True, options={'SKIP_SAVE'})

    def execute(self, context):
        if self.operator not in OUTLINER_OPERATORS:
            return {'CANCELLED'}
        area = _explorer_area(context)
        region = next((r for r in area.regions if r.type == 'WINDOW'), None)
        category, name = self.operator.split(".")
        op = getattr(getattr(bpy.ops, category), name)
        kwargs = {"open": self.open} if self.operator == "outliner.show_one_level" else {}
        with context.temp_override(area=area, region=region):
            if not op.poll():
                return {'CANCELLED'}
            return op(**kwargs)


class MXUI_OT_explorer_select(Operator):
    """Select in the scene from the Scene Explorer"""
    bl_idname = "mx_ui.explorer_select"
    bl_label = "Explorer Select"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    action: EnumProperty(
        name="Select",
        items=(
            ('SELECT', "Select All", "Select every object"),
            ('DESELECT', "Select None", "Deselect every object"),
            ('INVERT', "Select Invert", "Invert the selection"),
            ('CHILDREN', "Select Children", "Add the children of the selected objects to the selection"),
        ),
    )

    @classmethod
    def poll(cls, context):
        return context.view_layer is not None and context.mode == 'OBJECT'

    def execute(self, context):
        view_layer = context.view_layer
        objects = [obj for obj in view_layer.objects if obj.visible_get(view_layer=view_layer)
                   and not obj.hide_select]
        if self.action == 'CHILDREN':
            for obj in [o for o in objects if o.select_get(view_layer=view_layer)]:
                for child in obj.children_recursive:
                    if child in objects:
                        child.select_set(True, view_layer=view_layer)
            return {'FINISHED'}
        for obj in objects:
            selected = obj.select_get(view_layer=view_layer)
            obj.select_set({'SELECT': True, 'DESELECT': False, 'INVERT': not selected}[self.action],
                           view_layer=view_layer)
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Menus

class OUTLINER_MT_mx_explorer_select(Menu):
    bl_idname = "OUTLINER_MT_mx_explorer_select"
    bl_label = "Select"

    def draw(self, _context):
        layout = self.layout
        layout.operator(MXUI_OT_explorer_select.bl_idname, text="Select All").action = 'SELECT'
        layout.operator(MXUI_OT_explorer_select.bl_idname, text="Select None").action = 'DESELECT'
        layout.operator(MXUI_OT_explorer_select.bl_idname, text="Select Invert").action = 'INVERT'
        layout.separator()
        layout.operator(MXUI_OT_explorer_select.bl_idname, text="Select Children").action = 'CHILDREN'
        placeholder(layout, "Select Dependents")
        placeholder(layout, "Select Influences")
        layout.separator()
        space = _ExplorerSpace.get()
        if space is not None:
            layout.prop(space, "use_filter_case_sensitive", text="Find Case Sensitive")
            layout.prop(space, "use_filter_complete", text="Find Exact Match")
        placeholder(layout, "Find Using Wildcards")
        placeholder(layout, "Find Using Regular Expressions")
        placeholder(layout, "Search While Typing")


class OUTLINER_MT_mx_explorer_display(Menu):
    bl_idname = "OUTLINER_MT_mx_explorer_display"
    bl_label = "Display"

    def draw(self, _context):
        layout = self.layout
        space = _ExplorerSpace.get()
        if space is not None:
            layout.prop(space, "use_filter_children", text="Display Children")
            layout.prop(space, "use_filter_object_content", text="Display Object Contents")
        placeholder(layout, "Display Influences")
        placeholder(layout, "Display Dependents")
        layout.separator()
        draw_type_filters(layout, space, text=True)
        layout.separator()
        layout.operator(MXUI_OT_explorer_display.bl_idname, text="Display All").action = 'ALL'
        layout.operator(MXUI_OT_explorer_display.bl_idname, text="Display None").action = 'NONE'
        layout.operator(MXUI_OT_explorer_display.bl_idname, text="Invert Display").action = 'INVERT'


class OUTLINER_MT_mx_explorer_edit(Menu):
    bl_idname = "OUTLINER_MT_mx_explorer_edit"
    bl_label = "Edit"

    def draw(self, _context):
        layout = self.layout
        layout.operator("wm.call_panel", text="Rename").name = "TOPBAR_PT_name"
        layout.operator("object.delete", text="Delete").use_global = False
        layout.separator()
        layout.operator("object.hide_view_set", text="Hide").unselected = False
        layout.operator("object.hide_view_clear", text="Unhide All")
        layout.operator("object.mx_freeze_selected", text="Freeze")
        layout.operator("object.mx_unfreeze_all", text="Unfreeze All")
        layout.separator()
        props = layout.operator(MXUI_OT_explorer_outliner_op.bl_idname, text="Create New Layer")
        props.operator = "outliner.collection_new"
        layout.operator("object.move_to_collection", text="Add Selected to Layer...")
        layout.separator()
        props = layout.operator(MXUI_OT_explorer_outliner_op.bl_idname, text="Expand All")
        props.operator = "outliner.show_one_level"
        props.open = True
        props = layout.operator(MXUI_OT_explorer_outliner_op.bl_idname, text="Collapse All")
        props.operator = "outliner.show_one_level"
        props.open = False
        layout.separator()
        placeholder(layout, "Lock Cell Editing")


class OUTLINER_MT_mx_explorer_customize(Menu):
    bl_idname = "OUTLINER_MT_mx_explorer_customize"
    bl_label = "Customize"

    def draw(self, _context):
        layout = self.layout
        placeholder(layout, "Configure Columns...")
        placeholder(layout, "Toolbars")
        placeholder(layout, "Lock Toolbars")
        layout.separator()
        placeholder(layout, "Explorer Pane Configuration")
        placeholder(layout, "Open Scene Explorer...")
        placeholder(layout, "Save Scene Explorer As...")
        placeholder(layout, "Configure Default Explorer")


class OUTLINER_MT_mx_explorer_selector(Menu):
    bl_idname = "OUTLINER_MT_mx_explorer_selector"
    bl_label = "Scene Explorers"

    def draw(self, _context):
        layout = self.layout
        layout.operator(MXUI_OT_explorer_sort.bl_idname, text="Default", icon='OUTLINER').mode = 'HIERARCHY'
        layout.operator(MXUI_OT_explorer_sort.bl_idname, text="Layer Explorer",
                        icon='RENDERLAYERS').mode = 'LAYER'
        layout.separator()
        placeholder(layout, "New Scene Explorer", icon='ADD')
        placeholder(layout, "Manage Local Explorers...")


class _ExplorerSpace:
    """The explorer space for menus (their context is the strip they open from)."""

    @staticmethod
    def get():
        return _areas.explorer_space(bpy.context)


# -----------------------------------------------------------------------------
# Drawing

def draw_type_filters(layout, space, text=False):
    for label, icon, prop in TYPE_FILTERS:
        if prop is None or space is None:
            placeholder(layout, label if text else "", icon=icon, feature=label)
        else:
            layout.prop(space, prop, text=label if text else "", icon=icon, toggle=not text)
    if space is not None:
        layout.operator(MXUI_OT_explorer_display.bl_idname, text="Display Frozen" if text else "",
                        icon='FREEZE', depress=shows_frozen(space)).action = 'FROZEN'
        layout.operator(MXUI_OT_explorer_display.bl_idname, text="Display Hidden" if text else "",
                        icon='HIDE_ON', depress=shows_hidden(space)).action = 'HIDDEN'


def draw_menus(layout, _context):
    row = layout.row(align=True)
    row.emboss = 'PULLDOWN_MENU'
    row.menu(OUTLINER_MT_mx_explorer_select.bl_idname)
    row.menu(OUTLINER_MT_mx_explorer_display.bl_idname)
    row.menu(OUTLINER_MT_mx_explorer_edit.bl_idname)
    row.menu(OUTLINER_MT_mx_explorer_customize.bl_idname)


def draw_find(layout, context):
    space = _areas.explorer_space(context)
    if space is None:
        layout.label(text="No Scene Explorer")
        return
    layout.prop(space, "filter_text", text="", icon='VIEWZOOM', placeholder="Find")
    row = layout.row(align=True)
    row.menu(OUTLINER_MT_mx_explorer_display.bl_idname, text="", icon='FILTER')
    placeholder(row, "", icon='UNLOCKED', feature="Lock Cell Editing")
    row.prop(space, "use_filter_children", text="", icon='OUTLINER_OB_EMPTY')
    row.prop(space, "use_filter_object_content", text="", icon='MODIFIER')


def draw_footer(layout, context):
    space = _areas.explorer_space(context)
    row = layout.row(align=True)
    sub = row.row(align=True)
    sub.ui_units_x = 8.0
    sub.menu(OUTLINER_MT_mx_explorer_selector.bl_idname, text="Default", icon='OUTLINER')
    if space is None:
        return
    mode = sort_mode(space)
    row = layout.row(align=True)
    row.operator(MXUI_OT_explorer_sort.bl_idname, text="", icon='RENDERLAYERS',
                 depress=mode == 'LAYER').mode = 'LAYER'
    row.operator(MXUI_OT_explorer_sort.bl_idname, text="", icon='OUTLINER',
                 depress=mode == 'HIERARCHY').mode = 'HIERARCHY'


def draw_filter_bar(layout, context):
    space = _areas.explorer_space(context)
    col = layout.column(align=True)
    col.operator(MXUI_OT_explorer_select.bl_idname, text="", icon='CHECKBOX_HLT').action = 'SELECT'
    col.operator(MXUI_OT_explorer_select.bl_idname, text="", icon='CHECKBOX_DEHLT').action = 'DESELECT'
    col.operator(MXUI_OT_explorer_select.bl_idname, text="", icon='ARROW_LEFTRIGHT').action = 'INVERT'
    col.separator()
    col = layout.column(align=True)
    draw_type_filters(col, space)
    col.separator()
    col = layout.column(align=True)
    col.operator(MXUI_OT_explorer_display.bl_idname, text="", icon='PROP_ON').action = 'ALL'
    col.operator(MXUI_OT_explorer_display.bl_idname, text="", icon='PROP_OFF').action = 'NONE'
    col.operator(MXUI_OT_explorer_display.bl_idname, text="", icon='PROP_CON').action = 'INVERT'
    col.separator()
    col = layout.column(align=True)
    if space is not None:
        col.prop(space, "use_sync_select", text="", icon='UV_SYNC_SELECT')
    placeholder(col, "", icon='LOCKED', feature="Lock Cell Editing")


def draw_columns(layout, context):
    """The Outliner header as the explorer's column titles: Name (Sorted Ascending) ... Frozen."""
    space = context.space_data
    label = "Name (Sorted Ascending)" if space.use_sort_alpha else "Name"
    layout.prop(space, "use_sort_alpha", text=label, icon='SORT_ASC', emboss=False)
    layout.separator_spacer()
    row = layout.row(align=True)
    row.active = False
    row.label(text="Frozen")
    row.label(text="", icon='HIDE_OFF')


_areas.DRAWERS.update({
    'EXPLORER_MENUS': draw_menus,
    'EXPLORER_FIND': draw_find,
    'EXPLORER_FOOTER': draw_footer,
    'FILTER_BAR': draw_filter_bar,
})


def is_explorer(context):
    """An Outliner drawn as the Scene Explorer: the explorer of the Max Layout (or any Outliner in it)."""
    area = getattr(context, "area", None)
    if area is None or area.type != 'OUTLINER' or not _areas.max_context(context):
        return False
    role = _areas.area_role(context.screen, area)
    return role in {'EXPLORER', None}


def _draw_outliner_header(self, context):
    if not is_explorer(context):
        return False
    draw_columns(self.layout, context)
    return True


def configure_explorer(space):
    """The Scene Explorer: View Layer mode sorted by hierarchy, the selectability column as "Frozen"."""
    set_sort_mode(space, 'HIERARCHY')
    space.show_restrict_column_select = True
    space.show_restrict_column_hide = True
    space.show_restrict_column_viewport = False
    space.show_restrict_column_render = False
    space.show_restrict_column_enable = False
    space.use_sort_alpha = True
    space.use_sync_select = True


# -----------------------------------------------------------------------------
# Frozen column: toggling selectability in the Max Layout freezes / unfreezes

_owner = object()
_selectable = {}


def _snapshot():
    _selectable.clear()
    try:
        objects = list(bpy.data.objects)
    except AttributeError:  # Restricted data while add-ons register at startup.
        return
    for obj in objects:
        _selectable[obj.session_uid] = obj.hide_select


def sync_frozen(objects=None, gray=None):
    """
    Freeze objects whose selectability was turned off (and unfreeze the reverse) since the last call.
    Returns ``(frozen, unfrozen)``.
    """
    if gray is None:
        prefs = utils.get_prefs()
        gray = prefs.frozen_in_gray if prefs else True
    frozen, unfrozen = [], []
    for obj in (bpy.data.objects if objects is None else objects):
        before = _selectable.get(obj.session_uid)
        now = obj.hide_select
        _selectable[obj.session_uid] = now
        if before is None or before == now:
            continue
        if now and not freeze.is_frozen(obj):
            frozen += freeze.freeze_objects([obj], gray=gray)
        elif not now and freeze.is_frozen(obj):
            unfrozen += freeze.unfreeze_objects([obj])
    return frozen, unfrozen


def _on_hide_select():
    context = bpy.context
    window = getattr(context, "window", None)
    if window is None or not _areas.max_window(context, window):
        _snapshot()
        return
    sync_frozen()


def subscribe():
    bpy.msgbus.clear_by_owner(_owner)
    _snapshot()
    bpy.msgbus.subscribe_rna(key=(bpy.types.Object, "hide_select"), owner=_owner, args=(),
                             notify=_on_hide_select)


@persistent
def _on_load_post(*_args):
    subscribe()


_override = None

classes = (
    MXUI_OT_explorer_display,
    MXUI_OT_explorer_sort,
    MXUI_OT_explorer_outliner_op,
    MXUI_OT_explorer_select,
    OUTLINER_MT_mx_explorer_select,
    OUTLINER_MT_mx_explorer_display,
    OUTLINER_MT_mx_explorer_edit,
    OUTLINER_MT_mx_explorer_customize,
    OUTLINER_MT_mx_explorer_selector,
)


def register():
    global _override
    _override = _areas.override_draw(bpy.types.OUTLINER_HT_header, _draw_outliner_header)
    subscribe()
    bpy.app.handlers.load_post.append(_on_load_post)


def unregister():
    global _override
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
    bpy.msgbus.clear_by_owner(_owner)
    if _override is not None:
        _areas.restore_draw(bpy.types.OUTLINER_HT_header, _override)
        _override = None
