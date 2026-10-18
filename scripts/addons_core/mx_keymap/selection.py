# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Selection: select by name (H), lock selection (Space), and select-and-transform drags with transform tools."""

import fnmatch

import bpy
from bpy.props import BoolProperty, CollectionProperty, IntProperty, StringProperty
from bpy.types import Operator, PropertyGroup, UIList

# Active tool -> transform operator used when dragging on an object.
TRANSFORM_FOR_TOOL = {
    "builtin.move": "translate",
    "builtin.transform": "translate",
    "builtin.rotate": "rotate",
    "builtin.scale": "resize",
    "builtin.scale_cage": "resize",
}

_LOCK_PROP = "mx_keymap_selection_locked"


def _view3d_poll(context):
    return context.area is not None and context.area.type == 'VIEW_3D' and context.region_data is not None


# ------------------------------------------------------------------------------
# Lock selection

def is_selection_locked(context):
    return bool(getattr(context.window_manager, _LOCK_PROP, False))


def set_selection_locked(context, locked):
    setattr(context.window_manager, _LOCK_PROP, bool(locked))


def toggle_selection_lock(context):
    set_selection_locked(context, not is_selection_locked(context))
    return is_selection_locked(context)


def _tag_view3d_redraw(context):
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


class MX_KEYMAP_OT_selection_lock_toggle(Operator):
    """Lock the selection: clicking in the viewport no longer changes it, dragging transforms it"""
    bl_idname = "mx_keymap.selection_lock_toggle"
    bl_label = "Lock Selection Toggle"

    @classmethod
    def poll(cls, context):
        # Only in the 3D viewport: elsewhere the same key (Space) falls through to playing animation.
        return context.area is not None and context.area.type == 'VIEW_3D'

    def execute(self, context):
        locked = toggle_selection_lock(context)
        self.report({'INFO'}, "Selection locked" if locked else "Selection unlocked")
        _tag_view3d_redraw(context)
        return {'FINISHED'}


class MX_KEYMAP_OT_selection_lock_guard(Operator):
    """Swallows viewport clicks while the selection is locked (only runs when it is)"""
    bl_idname = "mx_keymap.selection_lock_guard"
    bl_label = "Selection Locked"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return is_selection_locked(context) and _view3d_poll(context)

    def invoke(self, _context, _event):
        # Cancelled still counts as handled: the selection items after this one don't run.
        return {'CANCELLED'}


def draw_lock_indicator(self, context):
    if is_selection_locked(context):
        self.layout.operator("mx_keymap.selection_lock_toggle", text="Selection Locked", icon='LOCKED', depress=True)


# ------------------------------------------------------------------------------
# Picking and dragging

def active_tool_id(context):
    tool = context.workspace.tools.from_space_view3d_mode(context.mode, create=False)
    return tool.idname if tool is not None else None


def press_location(context, event):
    """Where the drag started, in region coordinates."""
    region = context.region
    return (event.mouse_prev_press_x - region.x, event.mouse_prev_press_y - region.y)


def pick(location):
    """
    Make sure the element (object, or vertex/edge/face in edit mode) under ``location`` is selected.

    An unselected element becomes the only selected one; an already selected element keeps the current selection
    (so a drag moves the whole selection, like Max). Returns False when there is nothing under ``location``.
    """
    if 'FINISHED' in bpy.ops.view3d.select(location=location, select_passthrough=True):
        return True
    # Nothing changed: either nothing is there, or it is already selected. Find out by deselecting it ...
    if 'FINISHED' in bpy.ops.view3d.select(location=location, deselect=True):
        # ... and select it again.
        bpy.ops.view3d.select(location=location, extend=True)
        return True
    return False


def run_transform(kind):
    """Start the interactive transform ``kind`` ('translate', 'rotate' or 'resize'), confirmed on release."""
    return getattr(bpy.ops.transform, kind)('INVOKE_DEFAULT', release_confirm=True)


def has_any_selection(context):
    from .view import has_selection
    if context.mode == 'OBJECT':
        return bool(context.selected_objects)
    return has_selection(context)


class MX_KEYMAP_OT_select_drag(Operator):
    """Drag on an object to select and transform it with the active Move, Rotate or Scale tool"""
    bl_idname = "mx_keymap.select_drag"
    bl_label = "Select and Transform"
    bl_options = {'INTERNAL', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _view3d_poll(context)

    def invoke(self, context, event):
        kind = TRANSFORM_FOR_TOOL.get(active_tool_id(context))
        if kind is None:
            # Other tools: let the drag do what it does in Blender.
            return {'PASS_THROUGH'}
        if is_selection_locked(context):
            # Locked: drag anywhere to transform the selection.
            if not has_any_selection(context):
                return {'CANCELLED'}
        elif not pick(press_location(context, event)):
            # Empty space: the selection rectangle (next key-map item) takes the drag.
            return {'PASS_THROUGH'}
        run_transform(kind)
        return {'FINISHED'}


class MX_KEYMAP_OT_select_pick(Operator):
    """Select under the mouse (respects the selection lock)"""
    bl_idname = "mx_keymap.select_pick"
    bl_label = "Select"
    bl_options = {'INTERNAL'}

    deselect_all: BoolProperty(name="Deselect On Nothing", options={'SKIP_SAVE'})
    select_passthrough: BoolProperty(name="Only Select Unselected", options={'SKIP_SAVE'})
    extend: BoolProperty(name="Extend", options={'SKIP_SAVE'})
    deselect: BoolProperty(name="Deselect", options={'SKIP_SAVE'})
    toggle: BoolProperty(name="Toggle", options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return _view3d_poll(context)

    def invoke(self, context, _event):
        if is_selection_locked(context):
            # Not handled, so a drag can still start (and transform the locked selection).
            return {'PASS_THROUGH'}
        props = {
            name: True for name in ("deselect_all", "select_passthrough", "extend", "deselect", "toggle")
            if getattr(self, name)
        }
        return bpy.ops.view3d.select('INVOKE_DEFAULT', **props)


# ------------------------------------------------------------------------------
# Select by name

def filter_names(names, pattern):
    """Names matching ``pattern``: case-insensitive, ``*`` and ``?`` wildcards, otherwise a substring match."""
    if not pattern:
        return list(names)
    pattern = pattern.lower()
    if not any(c in pattern for c in "*?["):
        pattern = "*" + pattern + "*"
    return [name for name in names if fnmatch.fnmatchcase(name.lower(), pattern)]


def selectable_objects(view_layer):
    return [ob for ob in view_layer.objects if ob.visible_get(view_layer=view_layer) and not ob.hide_select]


def select_objects_by_name(view_layer, names, *, extend=False):
    """Select the objects called ``names`` (deselecting the others unless ``extend``). Returns them."""
    wanted = set(names)
    selected = []
    for ob in view_layer.objects:
        if ob.name in wanted and ob.visible_get(view_layer=view_layer) and not ob.hide_select:
            ob.select_set(True, view_layer=view_layer)
            selected.append(ob)
        elif not extend:
            ob.select_set(False, view_layer=view_layer)
    active = view_layer.objects.active
    if selected and (active is None or active not in selected):
        # Keep Max's dialog order: the first listed object becomes active.
        view_layer.objects.active = min(selected, key=lambda ob: ob.name.lower())
    return selected


class MX_KEYMAP_PG_name_item(PropertyGroup):
    name: StringProperty()
    select: BoolProperty(name="Select")
    icon: StringProperty()


def _all_update(self, _context):
    for item in self.mx_keymap_select_by_name_items:
        item.select = self.mx_keymap_select_by_name_all


class MX_KEYMAP_UL_select_by_name(UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        row = layout.row(align=True)
        row.prop(item, "select", text="")
        row.label(text=item.name, icon=item.icon or 'OBJECT_DATA')

    def filter_items(self, _context, data, propname):
        items = getattr(data, propname)
        names = [item.name for item in items]
        visible = set(filter_names(names, self.filter_name))
        flags = [self.bitflag_filter_item if item.name in visible else 0 for item in items]
        if self.use_filter_invert:
            flags = [0 if flag else self.bitflag_filter_item for flag in flags]
        order = []
        if self.use_filter_sort_alpha:
            order = bpy.types.UI_UL_list.sort_items_by_name(items, "name")
        if self.use_filter_sort_reverse and order:
            order.reverse()
        return flags, order


_TYPE_ICONS = {
    'MESH': 'OUTLINER_OB_MESH', 'CURVE': 'OUTLINER_OB_CURVE', 'SURFACE': 'OUTLINER_OB_SURFACE',
    'META': 'OUTLINER_OB_META', 'FONT': 'OUTLINER_OB_FONT', 'ARMATURE': 'OUTLINER_OB_ARMATURE',
    'LATTICE': 'OUTLINER_OB_LATTICE', 'EMPTY': 'OUTLINER_OB_EMPTY', 'CAMERA': 'OUTLINER_OB_CAMERA',
    'LIGHT': 'OUTLINER_OB_LIGHT', 'SPEAKER': 'OUTLINER_OB_SPEAKER', 'LIGHT_PROBE': 'OUTLINER_OB_LIGHTPROBE',
    'CURVES': 'OUTLINER_OB_CURVES', 'POINTCLOUD': 'OUTLINER_OB_POINTCLOUD', 'VOLUME': 'OUTLINER_OB_VOLUME',
    'GREASEPENCIL': 'OUTLINER_OB_GREASEPENCIL',
}


def fill_name_list(context):
    """Fill the dialog's list from the view layer, with the current selection checked."""
    wm = context.window_manager
    items = wm.mx_keymap_select_by_name_items
    items.clear()
    for ob in sorted(selectable_objects(context.view_layer), key=lambda ob: ob.name.lower()):
        item = items.add()
        item.name = ob.name
        item.select = ob.select_get()
        item.icon = _TYPE_ICONS.get(ob.type, 'OBJECT_DATA')
    wm.mx_keymap_select_by_name_index = 0


class MX_KEYMAP_OT_select_by_name(Operator):
    """Select objects from a searchable list of names"""
    bl_idname = "mx_keymap.select_by_name"
    bl_label = "Select From Scene"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and context.view_layer is not None

    def invoke(self, context, _event):
        fill_name_list(context)
        return context.window_manager.invoke_props_dialog(self, width=360, confirm_text="Select")

    def draw(self, context):
        wm = context.window_manager
        layout = self.layout
        layout.template_list(
            "MX_KEYMAP_UL_select_by_name", "", wm, "mx_keymap_select_by_name_items",
            wm, "mx_keymap_select_by_name_index", rows=14,
        )
        layout.prop(wm, "mx_keymap_select_by_name_all", text="All")

    def execute(self, context):
        wm = context.window_manager
        names = [item.name for item in wm.mx_keymap_select_by_name_items if item.select]
        select_objects_by_name(context.view_layer, names)
        wm.mx_keymap_select_by_name_items.clear()
        return {'FINISHED'}

    def cancel(self, context):
        context.window_manager.mx_keymap_select_by_name_items.clear()


classes = (
    MX_KEYMAP_OT_selection_lock_toggle,
    MX_KEYMAP_OT_selection_lock_guard,
    MX_KEYMAP_OT_select_drag,
    MX_KEYMAP_OT_select_pick,
    MX_KEYMAP_PG_name_item,
    MX_KEYMAP_UL_select_by_name,
    MX_KEYMAP_OT_select_by_name,
)


def register_props():
    wm = bpy.types.WindowManager
    wm.mx_keymap_selection_locked = BoolProperty(
        name="Lock Selection", description="Clicking in the viewport doesn't change the selection",
        options={'SKIP_SAVE'})
    wm.mx_keymap_select_by_name_items = CollectionProperty(type=MX_KEYMAP_PG_name_item, options={'SKIP_SAVE'})
    wm.mx_keymap_select_by_name_index = IntProperty(options={'SKIP_SAVE'})
    wm.mx_keymap_select_by_name_all = BoolProperty(
        name="All", description="Check or uncheck every object in the list", update=_all_update,
        options={'SKIP_SAVE'})
    bpy.types.VIEW3D_HT_header.append(draw_lock_indicator)


def unregister_props():
    bpy.types.VIEW3D_HT_header.remove(draw_lock_indicator)
    wm = bpy.types.WindowManager
    del wm.mx_keymap_select_by_name_all
    del wm.mx_keymap_select_by_name_index
    del wm.mx_keymap_select_by_name_items
    del wm.mx_keymap_selection_locked
