# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Shift-drag cloning with the Move / Rotate / Scale tools, and the "Clone Options" dialog.

While dragging, a temporary instance of the selection follows the mouse (the originals stay in place, as in Max).
When the drag ends the dialog asks for the clone type and the number of copies; each further copy gets the drag's
transform applied once more (cumulative offset, like Max). Cancelling removes the temporary instances.
"""

import re

import bpy
from bpy.props import EnumProperty, IntProperty, StringProperty
from bpy.types import Operator
from mathutils import Matrix

from . import selection

CLONE_TYPES = (
    ('COPY', "Copy", "Independent copy: the object and its geometry are duplicated"),
    ('INSTANCE', "Instance", "Instance: shares its geometry (object data) with the original, editing one edits all"),
    ('REFERENCE', "Reference",
     "Reference: for now the same as Instance (shared geometry). Max-style references, with a shared base and "
     "their own modifiers on top, are not supported yet"),
)

# The drag waiting for the dialog: {"sources": [names], "previews": [names], "before": {name: Matrix},
# "deltas": {name: Matrix}}.
_pending = {}


# ------------------------------------------------------------------------------
# Plain functions (testable without a window)

_NUMBERED = re.compile(r"^(.*?)(\d+)$")


def next_clone_names(name, count, existing):
    """
    ``count`` new unique names after ``name``, Max-style: "Box001" -> "Box002", "Box003"; "Box" -> "Box001".

    A Blender-style ".001" suffix is incremented the same way ("Cube.001" -> "Cube.002").
    """
    existing = set(existing)
    match = _NUMBERED.match(name)
    if match:
        base, digits = match.group(1), match.group(2)
        number, width = int(digits), len(digits)
    else:
        base, number, width = name, 0, 3
    names = []
    while len(names) < count:
        number += 1
        candidate = "{:s}{:0{:d}d}".format(base, number, width)
        if candidate not in existing:
            names.append(candidate)
            existing.add(candidate)
    return names


def first_clone_names(first, count, existing):
    """Names for ``count`` clones whose first one the user named ``first`` (used as-is when free)."""
    existing = set(existing)
    if first and first not in existing:
        return [first] + next_clone_names(first, count - 1, existing | {first})
    return next_clone_names(first, count, existing)


def _duplicate(src, mode):
    new = src.copy()
    if mode == 'COPY' and src.data is not None:
        new.data = src.data.copy()
    return new


def make_clones(sources, *, mode='COPY', count=1, delta=None, before=None, first_name=None, collection=None):
    """
    Clone ``sources`` (objects) ``count`` times.

    :arg mode: 'COPY' (own data), 'INSTANCE' or 'REFERENCE' (shared data; reference is an instance for now).
    :arg delta: world-space transform between consecutive copies: a Matrix for all objects, or a dict
       ``{name: Matrix}`` per object. Copy ``i`` (1-based) gets ``delta ** i`` applied to its original.
    :arg before: optional ``{name: Matrix}`` world matrices of the originals (defaults to their current ones).
    :arg first_name: name of the first clone when cloning a single object (Max's dialog name field).
    :arg collection: where to link clones of objects that are in no collection.
    :return: a list (one per copy) of lists of new objects, in the order of ``sources``.
    """
    sources = list(sources)
    source_set = set(sources)
    if before is None:
        before = {src.name: src.matrix_world.copy() for src in sources}
    identity = Matrix.Identity(4)

    def delta_of(src):
        if delta is None:
            return identity
        if isinstance(delta, dict):
            return delta.get(src.name, identity)
        return delta

    existing = set(bpy.data.objects.keys())
    if first_name and len(sources) == 1:
        names = {sources[0].name: first_clone_names(first_name, count, existing)}
    else:
        names = {}
        for src in sources:
            names[src.name] = next_clone_names(src.name, count, existing)
            existing.update(names[src.name])

    copies = []
    current = {src.name: before[src.name].copy() for src in sources}
    for i in range(count):
        mapping = {}
        for src in sources:
            new = _duplicate(src, mode)
            new.name = names[src.name][i]
            colls = src.users_collection or ((collection,) if collection is not None else ())
            for coll in colls:
                coll.objects.link(new)
            mapping[src] = new
        for src, new in mapping.items():
            if src.parent in source_set:
                # Children follow their cloned parent; `matrix_parent_inverse` and the local transform are copied.
                new.parent = mapping[src.parent]
            else:
                current[src.name] = delta_of(src) @ current[src.name]
                new.matrix_world = current[src.name]
        copies.append([mapping[src] for src in sources])
    return copies


def remove_objects(names):
    for name in names:
        ob = bpy.data.objects.get(name)
        if ob is not None:
            bpy.data.objects.remove(ob)


def select_only(context, objects, active=None):
    view_layer = context.view_layer
    wanted = set(objects)
    for ob in view_layer.objects:
        ob.select_set(ob in wanted)
    if active is not None:
        view_layer.objects.active = active
    elif objects:
        view_layer.objects.active = objects[-1]


def begin_pending(context, sources):
    """Create temporary instances of ``sources`` for the drag and select them. Records the pending clone."""
    active = context.view_layer.objects.active
    before = {src.name: src.matrix_world.copy() for src in sources}
    previews = make_clones(sources, mode='INSTANCE', count=1, collection=context.collection)[0]
    _pending.clear()
    _pending.update({
        "sources": [src.name for src in sources],
        "previews": [ob.name for ob in previews],
        "before": before,
        "deltas": {},
        "active": active.name if active is not None and active in sources else None,
        "in_place": False,
    })
    preview_active = previews[sources.index(active)] if active in sources else None
    select_only(context, previews, active=preview_active)
    return previews


def begin_in_place(context, sources):
    """Record a pending clone of ``sources`` at their current place (Max's Edit > Clone, Ctrl+V)."""
    active = context.view_layer.objects.active
    _pending.clear()
    _pending.update({
        "sources": [src.name for src in sources],
        "previews": [],
        "before": {src.name: src.matrix_world.copy() for src in sources},
        "deltas": {},
        "active": active.name if active is not None and active in sources else None,
        "in_place": True,
    })


def end_drag(context):
    """
    The drag finished: measure it from the temporary instances.

    Returns True when the drag moved something (the dialog should open). Otherwise the drag was cancelled and
    the pending clone is dropped.
    """
    if not _pending:
        return False
    deltas = {}
    moved = False
    for src_name, preview_name in zip(_pending["sources"], _pending["previews"]):
        preview = bpy.data.objects.get(preview_name)
        if preview is None:
            continue
        before = _pending["before"][src_name]
        delta = preview.matrix_world @ before.inverted_safe()
        deltas[src_name] = delta
        if not _matrix_is_identity(delta):
            moved = True
    _pending["deltas"] = deltas
    if not moved:
        cancel_pending(context)
    return moved


def _matrix_is_identity(matrix, eps=1e-6):
    identity = Matrix.Identity(4)
    return all(abs(matrix[i][j] - identity[i][j]) <= eps for i in range(4) for j in range(4))


def finish_pending(context, *, mode, count, first_name=None):
    """Create the clones for the pending drag. Returns the list of copies (see :func:`make_clones`)."""
    if not _pending:
        return []
    remove_objects(_pending["previews"])
    sources = [bpy.data.objects[name] for name in _pending["sources"] if name in bpy.data.objects]
    copies = make_clones(
        sources, mode=mode, count=count, delta=_pending["deltas"], before=_pending["before"],
        first_name=first_name, collection=context.collection,
    )
    active_name = _pending.get("active")
    _pending.clear()
    if copies:
        last = copies[-1]
        active = None
        if active_name is not None:
            active = last[[src.name for src in sources].index(active_name)]
        select_only(context, last, active=active)
    return copies


def cancel_pending(context):
    """Drop the pending clone: remove the temporary instances and select the originals again."""
    if not _pending:
        return
    remove_objects(_pending["previews"])
    sources = [bpy.data.objects[name] for name in _pending["sources"] if name in bpy.data.objects]
    active = bpy.data.objects.get(_pending.get("active") or "")
    _pending.clear()
    select_only(context, sources, active=active)


def pending():
    return dict(_pending)


# ------------------------------------------------------------------------------
# Operators

def _transform_running(window):
    """A transform (or a gizmo running its own modal tweak) is in progress in ``window``."""
    return any(
        op.bl_idname.startswith("TRANSFORM_OT_") or op.bl_idname == "GIZMOGROUP_OT_gizmo_tweak"
        for op in window.modal_operators
    )


class _CloneDragBase:
    """Waits (modal, passing every event through) for the transform started in ``invoke`` to finish."""

    _timer = None

    def _start_wait(self, context):
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.05, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type != 'TIMER' or _transform_running(context.window):
            return {'PASS_THROUGH'}
        context.window_manager.event_timer_remove(self._timer)
        if end_drag(context):
            bpy.ops.mx_keymap.clone_options('INVOKE_DEFAULT')
        return {'FINISHED'}

    def cancel(self, context):
        if self._timer is not None:
            context.window_manager.event_timer_remove(self._timer)
        cancel_pending(context)


class MX_KEYMAP_OT_clone_drag(_CloneDragBase, Operator):
    """Shift-drag with the Move, Rotate or Scale tool to clone"""
    bl_idname = "mx_keymap.clone_drag"
    bl_label = "Clone Drag"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return (
            context.area is not None and context.area.type == 'VIEW_3D' and
            context.mode in {'OBJECT', 'EDIT_MESH'}
        )

    def invoke(self, context, event):
        kind = selection.TRANSFORM_FOR_TOOL.get(selection.active_tool_id(context))
        if kind is None:
            return {'PASS_THROUGH'}
        if not selection.is_selection_locked(context):
            if not selection.pick(selection.press_location(context, event)):
                return {'PASS_THROUGH'}
        if context.mode == 'EDIT_MESH':
            # Max's "Clone To Element": duplicate the selected elements inside the mesh, no dialog.
            if not selection.has_any_selection(context):
                return {'CANCELLED'}
            bpy.ops.mesh.duplicate()
            selection.run_transform(kind)
            return {'FINISHED'}
        sources = list(context.selected_objects)
        if not sources:
            return {'CANCELLED'}
        begin_pending(context, sources)
        selection.run_transform(kind)
        return self._start_wait(context)


class MX_KEYMAP_OT_clone_gizmo_drag(_CloneDragBase, Operator):
    """Shift-drag the transform gizmo to clone"""
    bl_idname = "mx_keymap.clone_gizmo_drag"
    bl_label = "Clone Gizmo Drag"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return (
            context.area is not None and context.area.type == 'VIEW_3D' and context.mode == 'OBJECT' and
            selection.active_tool_id(context) in selection.TRANSFORM_FOR_TOOL and bool(context.selected_objects)
        )

    def invoke(self, context, _event):
        sources = list(context.selected_objects)
        begin_pending(context, sources)
        # Run the highlighted gizmo (normally an axis or plane of the transform gizmo) on the instances.
        result = bpy.ops.gizmogroup.gizmo_tweak('INVOKE_DEFAULT')
        if 'CANCELLED' in result:
            cancel_pending(context)
            # Let the gizmo handle the drag as usual.
            return {'PASS_THROUGH'}
        if not _transform_running(context.window):
            # Some other gizmo (e.g. a navigation button) ran an operator of its own: nothing to clone.
            cancel_pending(context)
            return {'FINISHED'}
        return self._start_wait(context)


class MX_KEYMAP_OT_clone_options(Operator):
    """Clone the dragged objects"""
    bl_idname = "mx_keymap.clone_options"
    bl_label = "Clone Options"
    # No 'REGISTER': like Max's dialog it can't be adjusted afterwards (the drag it measured is gone).
    bl_options = {'UNDO', 'INTERNAL'}

    clone_type: EnumProperty(name="Object", items=CLONE_TYPES, default='COPY')
    count: IntProperty(name="Number of Copies", min=1, soft_max=100, max=10000, default=1)
    name: StringProperty(name="Name", options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, _context):
        return bool(_pending)

    def invoke(self, context, _event):
        sources = _pending["sources"]
        if len(sources) == 1:
            self.name = next_clone_names(sources[0], 1, bpy.data.objects.keys())[0]
        return context.window_manager.invoke_props_dialog(self, width=300, title="Clone Options")

    def draw(self, _context):
        layout = self.layout
        layout.use_property_split = False
        col = layout.column()
        col.label(text="Object")
        col.row().prop(self, "clone_type", expand=True)
        if not _pending.get("in_place"):
            col.prop(self, "count")
        row = col.row()
        row.enabled = len(_pending.get("sources", ())) == 1
        row.prop(self, "name")

    def execute(self, context):
        count = 1 if _pending.get("in_place") else self.count
        copies = finish_pending(context, mode=self.clone_type, count=count, first_name=self.name or None)
        if not copies:
            return {'CANCELLED'}
        return {'FINISHED'}

    def cancel(self, context):
        cancel_pending(context)


class MX_KEYMAP_OT_clone(Operator):
    """Clone the selected objects in place"""
    bl_idname = "mx_keymap.clone"
    bl_label = "Clone"

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and bool(context.selected_objects)

    def invoke(self, context, _event):
        begin_in_place(context, list(context.selected_objects))
        bpy.ops.mx_keymap.clone_options('INVOKE_DEFAULT')
        return {'FINISHED'}


classes = (
    MX_KEYMAP_OT_clone,
    MX_KEYMAP_OT_clone_drag,
    MX_KEYMAP_OT_clone_gizmo_drag,
    MX_KEYMAP_OT_clone_options,
)
