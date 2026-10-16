# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Wire colours: new objects get a random object colour (Max hands out a random wire colour per object),
or the name and colour set in the Create tab's Name and Color rollout.

New objects are detected in a ``depsgraph_update_post`` handler. To stay cheap it only looks at the
objects in ``depsgraph.updates`` and compares their ``session_uid`` with the set of objects already seen;
the set is rebuilt after loading a file and after undo/redo, so objects coming back from undo or from a
loaded file are never recoloured. Only objects still having Blender's default white colour are touched,
so duplicates keep the colour of their original.
"""

import bpy
from bpy.app.handlers import persistent
from bpy.types import Operator

from . import utils

DEFAULT_COLOR = (1.0, 1.0, 1.0, 1.0)

_known_objects = None


def _all_object_uids():
    return {obj.session_uid for obj in bpy.data.objects}


def reset_known_objects():
    global _known_objects
    try:
        _known_objects = _all_object_uids()
    except AttributeError:  # `bpy.data` is restricted while add-ons register at startup.
        _known_objects = None


def _is_default_color(obj):
    return all(abs(a - b) < 1e-6 for a, b in zip(obj.color, DEFAULT_COLOR))


def assign_new_object(context, obj, rng=None):
    """Apply the Name and Color rollout (or a random colour) to a newly created object."""
    import random
    rng = rng or random
    state = utils.get_state(context)
    prefs = utils.get_prefs(context)
    if state is not None and state.next_name:
        obj.name = state.next_name
        state.next_name = ""
    chosen = state is not None and state.next_color_initialized
    if not _is_default_color(obj) and not (chosen and utils.is_live_primitive(obj)):
        return
    use_random = prefs is None or prefs.random_wire_colors
    if state is not None and state.next_color_initialized:
        obj.color = state.next_color
    elif use_random:
        obj.color = utils.random_wire_color(rng)
    else:
        return
    if state is not None and use_random:
        # Max picks the next random colour as soon as an object has been created.
        state.next_color = utils.random_wire_color(rng)


def init_next_color(context=None):
    """Show a random colour in the Name and Color swatch (when random wire colours are on)."""
    context = context or bpy.context
    state = utils.get_state(context)
    prefs = utils.get_prefs(context)
    if state is not None and not state.next_color_initialized and (prefs is None or prefs.random_wire_colors):
        state.next_color = utils.random_wire_color()


def new_objects_in(depsgraph):
    """Original objects in ``depsgraph.updates`` that weren't seen before (and remember them)."""
    global _known_objects
    if _known_objects is None:
        _known_objects = _all_object_uids()
        return []
    found = []
    for update in depsgraph.updates:
        id_eval = update.id
        if not isinstance(id_eval, bpy.types.Object):
            continue
        obj = id_eval.original
        uid = obj.session_uid
        if uid in _known_objects:
            continue
        _known_objects.add(uid)
        found.append(obj)
    return found


@persistent
def _on_depsgraph_update(_scene, depsgraph):
    if not depsgraph.id_type_updated('OBJECT'):
        return
    context = bpy.context
    for obj in new_objects_in(depsgraph):
        if obj.is_editable:
            assign_new_object(context, obj)


@persistent
def _on_reset(*_args):
    reset_known_objects()


class OBJECT_OT_mx_random_wire_color(Operator):
    """Give each selected object a random object (wire) colour"""
    bl_idname = "object.mx_random_wire_color"
    bl_label = "Assign Random Wire Colors"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(context.selected_objects)

    def execute(self, context):
        from . import freeze
        for obj in context.selected_objects:
            if not freeze.is_frozen(obj):
                obj.color = utils.random_wire_color()
        return {'FINISHED'}


classes = (
    OBJECT_OT_mx_random_wire_color,
)

_handlers = (
    (bpy.app.handlers.depsgraph_update_post, _on_depsgraph_update),
    (bpy.app.handlers.load_post, _on_reset),
    (bpy.app.handlers.undo_post, _on_reset),
    (bpy.app.handlers.redo_post, _on_reset),
)


def register():
    for handlers, func in _handlers:
        if func not in handlers:
            handlers.append(func)
    reset_known_objects()
    bpy.app.timers.register(_deferred_init, first_interval=0.0)


def _deferred_init():
    if _known_objects is None:
        reset_known_objects()
    init_next_color()


def unregister():
    global _known_objects
    for handlers, func in _handlers:
        if func in handlers:
            handlers.remove(func)
    _known_objects = None
