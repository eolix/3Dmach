# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Sub-object levels (keys 1-6) mapped onto Blender's edit mode.

Phase-1 approximation (ROADMAP 1a):

====== ========= ================================================================
Level  Max       Blender
====== ========= ================================================================
1      Vertex    Edit mode, vertex select mode
2      Edge      Edit mode, edge select mode
3      Border    Edit mode, edge select mode; the selection is limited to open
                 boundary edges, grown to whole boundary loops, and clicks pick
                 whole boundary loops
4      Polygon   Edit mode, face select mode
5      Element   Edit mode, face select mode; the selection grows to connected
                 elements and clicks pick whole elements
6      (top)     Object mode
====== ========= ================================================================

Pressing the key of the active level again goes back to object level, like Max.
Unlike Max, Blender keeps one selection per mesh rather than one per level, and switching levels converts it.
"""

import bmesh
import bpy
from bpy.props import BoolProperty, IntProperty
from bpy.types import Operator

LEVEL_NAMES = {
    0: "Object",
    1: "Vertex",
    2: "Edge",
    3: "Border",
    4: "Polygon",
    5: "Element",
}
TOP_LEVEL = 6

_SELECT_MODE = {1: 'VERT', 2: 'EDGE', 3: 'EDGE', 4: 'FACE', 5: 'FACE'}

# Object types with an edit mode (levels 1-5 just enter edit mode for the non-mesh ones).
EDIT_TYPES = {'MESH', 'CURVE', 'SURFACE', 'META', 'FONT', 'LATTICE', 'ARMATURE', 'CURVES', 'POINTCLOUD',
              'GREASEPENCIL'}

_PROP = "mx_keymap_subobject_level"


def stored_level(context):
    return getattr(context.window_manager, _PROP, 0)


def _store_level(context, level):
    setattr(context.window_manager, _PROP, level)


def current_level(context):
    """The active sub-object level, 0 at object level."""
    obj = context.active_object
    if obj is None or context.mode == 'OBJECT' or context.edit_object is None:
        return 0
    stored = stored_level(context)
    if context.mode != 'EDIT_MESH':
        return stored if 1 <= stored <= 5 else 1
    vert, edge, face = context.tool_settings.mesh_select_mode
    flags = {'VERT': vert, 'EDGE': edge, 'FACE': face}
    if stored in _SELECT_MODE and flags[_SELECT_MODE[stored]]:
        # The select mode still matches the stored level (it can also be changed from the header).
        return stored
    if vert:
        return 1
    if edge:
        return 2
    return 4


def select_boundary_loops(bm):
    """Keep only selected open-boundary edges, grown to whole boundary loops. Returns the number selected."""
    seeds = [e for e in bm.edges if e.select and e.is_boundary]
    for e in bm.edges:
        e.select_set(False)
    for f in bm.faces:
        f.select_set(False)
    seen = set()
    stack = list(seeds)
    while stack:
        e = stack.pop()
        if e in seen:
            continue
        seen.add(e)
        for v in e.verts:
            for other in v.link_edges:
                if other.is_boundary and other not in seen:
                    stack.append(other)
    for e in seen:
        e.select_set(True)
    bm.select_flush_mode()
    return len(seen)


def _edit_meshes(context):
    return [ob for ob in (context.objects_in_mode or ()) if ob.type == 'MESH']


def _mesh_level_setup(context, level):
    bpy.ops.mesh.select_mode(use_extend=False, use_expand=False, type=_SELECT_MODE[level])
    if level == 3:
        for ob in _edit_meshes(context):
            bm = bmesh.from_edit_mesh(ob.data)
            select_boundary_loops(bm)
            bmesh.update_edit_mesh(ob.data, loop_triangles=False, destructive=False)
    elif level == 5:
        if any(ob.data.total_face_sel for ob in _edit_meshes(context)):
            bpy.ops.mesh.select_linked(delimit=set())


def set_subobject_level(context, level):
    """
    Switch to sub-object ``level`` (1-5), or back to object level (6, or the active level again).

    Returns the new level (0 for object level), or None if the active object has no sub-object levels.
    """
    obj = context.active_object
    if level == TOP_LEVEL or (level == current_level(context) and level != 0):
        if obj is not None and context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        _store_level(context, 0)
        return 0
    if obj is None or obj.type not in EDIT_TYPES:
        return None
    if context.edit_object is None:
        bpy.ops.object.mode_set(mode='EDIT')
    if obj.type == 'MESH':
        _mesh_level_setup(context, level)
    _store_level(context, level)
    return level


class MX_KEYMAP_OT_subobject_level(Operator):
    """Switch sub-object level (1 vertex, 2 edge, 3 border, 4 polygon, 5 element, 6 object level)"""
    bl_idname = "mx_keymap.subobject_level"
    bl_label = "Sub-Object Level"
    bl_options = {'REGISTER', 'UNDO'}

    level: IntProperty(name="Level", min=1, max=6, default=1)

    @classmethod
    def poll(cls, context):
        return context.view_layer is not None and context.active_object is not None

    def execute(self, context):
        result = set_subobject_level(context, self.level)
        if result is None:
            self.report({'INFO'}, "The active object has no sub-object levels")
            return {'CANCELLED'}
        return {'FINISHED'}


def _poll_level(context, level):
    return (
        context.mode == 'EDIT_MESH' and context.area is not None and context.area.type == 'VIEW_3D' and
        current_level(context) == level
    )


def _selected_edges(ob):
    bm = bmesh.from_edit_mesh(ob.data)
    bm.edges.index_update()
    return {e.index for e in bm.edges if e.select}


class MX_KEYMAP_OT_select_border_pick(Operator):
    """Select the whole boundary loop under the mouse (border sub-object level)"""
    bl_idname = "mx_keymap.select_border_pick"
    bl_label = "Select Border"
    bl_options = {'REGISTER', 'UNDO'}

    extend: BoolProperty(name="Extend", options={'SKIP_SAVE'})
    deselect: BoolProperty(name="Deselect", options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return _poll_level(context, 3)

    def invoke(self, context, _event):
        before = {ob.name: _selected_edges(ob) for ob in _edit_meshes(context)}
        result = bpy.ops.mesh.loop_select(
            'INVOKE_DEFAULT', extend=self.extend, deselect=self.deselect, toggle=False, ring=False)
        if 'CANCELLED' in result and not (self.extend or self.deselect):
            bpy.ops.mesh.select_all(action='DESELECT')
            return {'FINISHED'}
        if not self.deselect:
            # Interior edge loops aren't borders: only keep newly selected open edges.
            for ob in _edit_meshes(context):
                bm = bmesh.from_edit_mesh(ob.data)
                bm.edges.index_update()
                old = before.get(ob.name, set())
                for e in bm.edges:
                    if e.select and e.index not in old and not e.is_boundary:
                        e.select_set(False)
                bm.select_flush_mode()
                bmesh.update_edit_mesh(ob.data, loop_triangles=False, destructive=False)
        return {'FINISHED'}


class MX_KEYMAP_OT_select_element_pick(Operator):
    """Select the whole connected element under the mouse (element sub-object level)"""
    bl_idname = "mx_keymap.select_element_pick"
    bl_label = "Select Element"
    bl_options = {'REGISTER', 'UNDO'}

    extend: BoolProperty(name="Extend", options={'SKIP_SAVE'})
    deselect: BoolProperty(name="Deselect", options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return _poll_level(context, 5)

    def invoke(self, context, _event):
        if not (self.extend or self.deselect):
            bpy.ops.mesh.select_all(action='DESELECT')
        bpy.ops.mesh.select_linked_pick('INVOKE_DEFAULT', deselect=self.deselect, delimit=set())
        return {'FINISHED'}


classes = (
    MX_KEYMAP_OT_subobject_level,
    MX_KEYMAP_OT_select_border_pick,
    MX_KEYMAP_OT_select_element_pick,
)


def register_props():
    bpy.types.WindowManager.mx_keymap_subobject_level = IntProperty(
        name="Sub-Object Level", min=0, max=5, options={'SKIP_SAVE'})


def unregister_props():
    del bpy.types.WindowManager.mx_keymap_subobject_level
