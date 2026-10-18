# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Editable Poly / Editable Spline commands of the Modify tab (``catalog.EDITABLE_POLY`` and
``catalog.EDITABLE_SPLINE``), run on Blender's edit-mode operators.

The command panel is not a 3D viewport, while many mesh operators need one (or behave differently without
one), so ``object.mx_edit_command`` runs them with a 3D viewport as context:

- 'EXEC' commands (Weld, Remove, Collapse, Make Planar, ...) run at once, in Edit Mode of the active object.
  They register as the last operator, so the viewport's Adjust Last Operation panel shows their settings
  (that is what Max's Settings buttons open).
- 'PICK' commands (Extrude, Chamfer, Cut, QuickSlice, ...) work like Max's toggle buttons: the button stays
  highlighted until you click in a viewport, which starts the interactive Blender operator there. Right-click,
  Esc or clicking the button again cancels.

Also here: Material IDs (``mesh.mx_material_id``), Auto Smooth (``mesh.mx_auto_smooth``) and NURMS
subdivision of the base object (``object.mx_nurms_toggle``).
"""

import time

import bmesh
import bpy
from bpy.props import EnumProperty, StringProperty
from bpy.types import Operator

from .. import utils
from . import catalog

# A Subdivision Surface modifier with this name is the base object's NURMS subdivision (Max's Editable Poly
# "Use NURMS Subdivision"): it is drawn in the Subdivision Surface rollout, not in the stack.
NURMS_NAME = "NURMS"


def nurms_modifier(obj):
    mod = getattr(obj, "modifiers", {}).get(NURMS_NAME) if obj is not None else None
    return mod if mod is not None and mod.type == 'SUBSURF' else None


def is_nurms_modifier(mod):
    return mod.name == NURMS_NAME and mod.type == 'SUBSURF'


# -----------------------------------------------------------------------------
# Running operators with a 3D viewport as context

def view3d_override(context, area=None, region=None):
    """Keyword arguments for `temp_override` with a 3D viewport (the given one, or the largest)."""
    window = getattr(context, "window", None)
    if window is None:
        return {}
    if area is None:
        areas = [a for a in window.screen.areas if a.type == 'VIEW_3D']
        if not areas:
            return {}
        area = max(areas, key=lambda a: a.width * a.height)
    if region is None:
        region = next((r for r in area.regions if r.type == 'WINDOW'), None)
    return {"window": window, "screen": window.screen, "area": area, "region": region}


def push_undo():
    """
    The ``undo`` argument for operators the command panel runs: with the interface, the operator pushes its
    own undo step and registers as the last operator (its Adjust Last Operation panel shows its settings).
    Not in background mode (scripts, tests), where there is no one to undo.
    """
    return not bpy.app.background


def operator_function(idname):
    category, _, name = idname.partition(".")
    return getattr(getattr(bpy.ops, category), name)


def _resolve(value, state):
    if isinstance(value, catalog.StateValue):
        return getattr(state, value.name)
    if isinstance(value, dict):
        return {key: _resolve(sub, state) for key, sub in value.items()}
    return value


class CommandError(Exception):
    pass


def ensure_mode(context, obj, button):
    """Enter Edit Mode of ``obj`` for an edit command (Max's buttons work from the object level too)."""
    if not button.edit:
        return
    if obj is None or obj.type != button.edit and not (button.edit == 'CURVE' and obj.type == 'FONT'):
        raise CommandError("{:s} needs an editable {:s}".format(
            button.label, "poly" if button.edit == 'MESH' else "spline"))
    if obj.mode != 'EDIT':
        with context.temp_override(**utils.object_context_override(context, obj)):
            bpy.ops.object.mode_set(mode='EDIT')


def run_command(context, button, execution='EXEC_DEFAULT', area=None, region=None):
    """Run a catalog edit command on the active object. Returns the operator's result set."""
    state = utils.get_state(context)
    ensure_mode(context, context.active_object, button)
    func = operator_function(button.operator)
    props = {name: _resolve(value, state) for name, value in button.props.items()}
    override = view3d_override(context, area, region)
    try:
        with context.temp_override(**override):
            return func(execution, push_undo(), **props)
    except RuntimeError as ex:
        raise CommandError(str(ex).replace("Error: ", "").strip()) from ex
    except TypeError as ex:
        # Context-dependent enum items, e.g. Target Weld's "merge at last" needs a last selected vertex.
        if "enum" not in str(ex):
            raise
        raise CommandError("{:s} is not possible with this selection".format(button.label)) from ex


def _region_under_mouse(window, event):
    for area in window.screen.areas:
        if area.type != 'VIEW_3D':
            continue
        for region in area.regions:
            if region.type != 'WINDOW':
                continue
            if region.x <= event.mouse_x < region.x + region.width and \
                    region.y <= event.mouse_y < region.y + region.height:
                return area, region
    return None, None


def tag_redraw_panels(context=None):
    context = context or bpy.context
    wm = context.window_manager
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type in {'PROPERTIES', 'VIEW_3D'}:
                area.tag_redraw()


class OBJECT_OT_mx_edit_command(Operator):
    """Editable Poly / Editable Spline command"""
    bl_idname = "object.mx_edit_command"
    bl_label = "Edit Command"
    bl_options = {'INTERNAL'}

    command: StringProperty(name="Command", options={'SKIP_SAVE'})

    # Last command cancelled by clicking outside a viewport: clicking its button again toggles it off.
    _last_cancel = ("", 0.0)

    @classmethod
    def description(cls, _context, properties):
        button = catalog.COMMANDS.get(properties.command)
        if button is None:
            return None
        if button.description:
            return button.description
        try:
            desc = operator_function(button.operator).get_rna_type().description
        except (AttributeError, KeyError):
            desc = ""
        return "{:s}: {:s}".format(button.label, desc) if desc else button.label

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type in {'MESH', 'CURVE', 'FONT'}

    def _button(self):
        button = catalog.COMMANDS.get(self.command)
        if button is None:
            self.report({'ERROR'}, "Unknown command {!r}".format(self.command))
        return button

    def execute(self, context):
        button = self._button()
        if button is None:
            return {'CANCELLED'}
        try:
            result = run_command(context, button)
        except CommandError as ex:
            self.report({'WARNING'}, str(ex))
            return {'CANCELLED'}
        return {'FINISHED'} if 'FINISHED' in result else {'CANCELLED'}

    def invoke(self, context, _event):
        button = self._button()
        if button is None:
            return {'CANCELLED'}
        if button.mode != 'PICK' or context.window is None:
            return self.execute(context)
        key, when = OBJECT_OT_mx_edit_command._last_cancel
        if key == button.key and time.monotonic() - when < 1.0:
            # The button was clicked while active: Max turns it off.
            OBJECT_OT_mx_edit_command._last_cancel = ("", 0.0)
            return {'CANCELLED'}
        try:
            ensure_mode(context, context.active_object, button)
        except CommandError as ex:
            self.report({'WARNING'}, str(ex))
            return {'CANCELLED'}
        state = utils.get_state(context)
        state.edit_command_active = button.key
        context.window_manager.modal_handler_add(self)
        context.window.cursor_modal_set('CROSSHAIR')
        context.workspace.status_text_set("{:s}: click in a viewport (right-click or Esc to cancel)".format(
            button.label))
        tag_redraw_panels(context)
        return {'RUNNING_MODAL'}

    def _finish(self, context):
        state = utils.get_state(context)
        if state is not None:
            state.edit_command_active = ""
        context.window.cursor_modal_restore()
        context.workspace.status_text_set(None)
        tag_redraw_panels(context)

    def modal(self, context, event):
        if event.type == 'ESC' or (event.type == 'RIGHTMOUSE' and event.value == 'PRESS'):
            self._finish(context)
            return {'CANCELLED'}
        if event.type != 'LEFTMOUSE' or event.value != 'PRESS':
            return {'PASS_THROUGH'}
        button = catalog.COMMANDS[self.command]
        self._finish(context)
        area, region = _region_under_mouse(context.window, event)
        if region is None:
            OBJECT_OT_mx_edit_command._last_cancel = (button.key, time.monotonic())
            return {'CANCELLED', 'PASS_THROUGH'}
        try:
            run_command(context, button, 'INVOKE_DEFAULT', area, region)
        except CommandError as ex:
            self.report({'WARNING'}, str(ex))
        return {'CANCELLED'}


# -----------------------------------------------------------------------------
# Polygon: Material IDs and Smoothing Groups

def _edit_bmesh(obj):
    return bmesh.from_edit_mesh(obj.data)


class MESH_OT_mx_material_id(Operator):
    """Set or select the Material ID (material slot) of polygons"""
    bl_idname = "mesh.mx_material_id"
    bl_label = "Material ID"
    bl_options = {'REGISTER', 'UNDO'}

    action: EnumProperty(
        name="Action",
        items=(
            ('SET', "Set ID", "Assign the Set ID to the selected polygons"),
            ('SELECT', "Select ID", "Select the polygons with the Select ID"),
        ),
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH' and obj.mode == 'EDIT'

    def execute(self, context):
        state = utils.get_state(context)
        obj = context.active_object
        bm = _edit_bmesh(obj)
        if self.action == 'SET':
            index = state.material_id - 1
            for face in bm.faces:
                if face.select:
                    face.material_index = index
            bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
            return {'FINISHED'}
        index = state.select_material_id - 1
        for face in bm.faces:
            if face.material_index == index:
                face.select_set(True)
            elif state.select_id_clear:
                face.select_set(False)
        bm.select_flush_mode()
        bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
        return {'FINISHED'}


class MESH_OT_mx_auto_smooth(Operator):
    """Smooth the selected polygons, keeping edges sharper than the threshold sharp"""
    bl_idname = "mesh.mx_auto_smooth"
    bl_label = "Auto Smooth"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH' and obj.mode == 'EDIT'

    def execute(self, context):
        state = utils.get_state(context)
        bpy.ops.mesh.faces_shade_smooth()
        bpy.ops.mesh.set_sharpness_by_angle(angle=state.auto_smooth_angle)
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Subdivision Surface rollout: NURMS

def toggle_nurms(obj):
    """Add or remove the base object's NURMS subdivision. Returns the modifier, or None when removed."""
    mod = nurms_modifier(obj)
    if mod is not None:
        obj.modifiers.remove(mod)
        return None
    mod = obj.modifiers.new(NURMS_NAME, 'SUBSURF')
    mod.levels = 1
    mod.render_levels = 1
    # Part of the base object: evaluated before the modifiers the user added.
    obj.modifiers.move(len(obj.modifiers) - 1, 0)
    return mod


class OBJECT_OT_mx_nurms_toggle(Operator):
    """Use NURMS Subdivision: smooth the base object with subdivision surfaces (Catmull-Clark)"""
    bl_idname = "object.mx_nurms_toggle"
    bl_label = "Use NURMS Subdivision"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH'

    def execute(self, context):
        toggle_nurms(context.active_object)
        return {'FINISHED'}


classes = (
    OBJECT_OT_mx_edit_command,
    MESH_OT_mx_material_id,
    MESH_OT_mx_auto_smooth,
    OBJECT_OT_mx_nurms_toggle,
)
