# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Operators: add a live primitive (at the 3D cursor or interactively, Max-style) and convert it to a plain mesh."""

__all__ = (
    "MESH_OT_mx_primitive_add",
    "OBJECT_OT_mx_convert_to_editable_poly",
    "create_primitive_object",
    "random_wire_color",
    "next_object_name",
)

import colorsys
import random

import bpy
from bpy.props import (
    EnumProperty,
    FloatVectorProperty,
)
from bpy_extras import view3d_utils
from mathutils import Matrix, Vector

from . import creation, geometry, props, ui
from .kinds import KINDS, label

_DESCRIPTIONS = {kind: description for kind, _name, description in KINDS}


def create_primitive_object(name, kind, params, collection=None, mesh=None):
    """
    Create an object holding a live primitive, without operators (for importers and scripts).

    :arg name: name of the new object (and of a new mesh).
    :arg kind: one of ``geometry.KIND_IDS``.
    :arg params: parameters for :func:`geometry.generate`; missing ones get the kind's defaults.
    :arg collection: collection to link the object into; the context's collection by default.
    :arg mesh: an existing mesh to use, so instances share one primitive. If it is already a live primitive of
       ``kind`` with these parameters it is used as it is; otherwise it is turned into one.
    :return: the new object, at the origin, not selected.
    """
    if kind not in geometry.PARAMETERS:
        raise ValueError("unknown primitive kind {!r}".format(kind))
    wanted = geometry.normalize_params(kind, params)
    if mesh is None:
        mesh = bpy.data.meshes.new(name)
        props.set_parameters(mesh, kind, wanted)
    else:
        current_kind, current = props.get_parameters(mesh)
        if current_kind != kind or not _same_parameters(current, wanted):
            props.set_parameters(mesh, kind, wanted)
    obj = bpy.data.objects.new(name, mesh)
    if collection is None:
        collection = bpy.context.collection or bpy.context.scene.collection
    collection.objects.link(obj)
    return obj


def _same_parameters(a, b):
    # Stored floats are single precision.
    for name, value in b.items():
        other = a.get(name)
        if isinstance(value, float):
            if other is None or abs(other - value) > 1e-6 * max(1.0, abs(value)):
                return False
        elif other != value:
            return False
    return True


def random_wire_color(rng=random):
    """A random, fairly saturated object colour (RGBA), like the wire colours Max gives new objects."""
    r, g, b = colorsys.hsv_to_rgb(rng.random(), rng.uniform(0.45, 0.9), rng.uniform(0.55, 0.95))
    return (r, g, b, 1.0)


def next_object_name(base):
    """Max-style numbered name: ``Box001``, ``Box002``, ..."""
    names = bpy.data.objects
    number = 1
    while "{:s}{:03d}".format(base, number) in names:
        number += 1
    return "{:s}{:03d}".format(base, number)


def _ensure_object_mode(context):
    if context.mode != 'OBJECT' and context.active_object is not None:
        bpy.ops.object.mode_set(mode='OBJECT')


def _view3d_regions(screen):
    """``(area, region)`` for every main region of the 3D viewports in ``screen`` (quad views have several)."""
    result = []
    if screen is None:
        return result
    for area in screen.areas:
        if area.type != 'VIEW_3D':
            continue
        for region in area.regions:
            if region.type == 'WINDOW' and region.width > 1 and region.height > 1:
                result.append((area, region))
    return result


def _region_under_mouse(context, event):
    for area, region in _view3d_regions(context.window.screen if context.window else None):
        if region.x <= event.mouse_x < region.x + region.width and region.y <= event.mouse_y < region.y + region.height:
            return area, region
    return None, None


class MESH_OT_mx_primitive_add(bpy.types.Operator):
    """Create a Max-style primitive with live parameters"""

    bl_idname = "mesh.mx_primitive_add"
    bl_label = "Add Max-Style Primitive"
    bl_options = {'REGISTER', 'UNDO'}

    # The primitive parameters, shared with `Mesh.mx_primitive` (without update callbacks).
    __annotations__ = {
        "kind": EnumProperty(name="Kind", items=props.KIND_ITEMS, default='BOX'),
        **props.property_definitions(options={'SKIP_SAVE'}),
        "location": FloatVectorProperty(
            name="Location", subtype='TRANSLATION', unit='LENGTH', options={'SKIP_SAVE'},
            description="Location of the new object (default: the 3D cursor)",
        ),
        # Not "rotation": that is the Torus parameter.
        "object_rotation": FloatVectorProperty(
            name="Rotation", subtype='EULER', unit='ROTATION', options={'SKIP_SAVE'},
            description="Rotation of the new object",
        ),
    }

    @classmethod
    def description(cls, _context, properties):
        return _DESCRIPTIONS.get(properties.kind, cls.__doc__)

    # -------------------------------------------------------------------------
    # Parameters

    def _effective_params(self):
        defaults = geometry.PARAMETERS[self.kind]
        params = {
            name: getattr(self, name) if self.properties.is_property_set(name) else default
            for name, default in defaults.items()
        }
        return geometry.normalize_params(self.kind, params)

    def _store(self, params, location, rotation):
        # Keep the values actually used, so the redo panel shows them and repeats this exact object.
        for name, value in params.items():
            setattr(self, name, value)
        self.location = location
        self.object_rotation = rotation

    def draw(self, _context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.label(text=label(self.kind), icon=props.ICONS[self.kind])
        ui.draw_parameter_list(layout, self, self.kind)
        layout.separator()
        layout.prop(self, "location")
        layout.prop(self, "object_rotation")

    def _create(self, context, params, location, rotation):
        obj = create_primitive_object(
            next_object_name(label(self.kind).replace(" ", "")), self.kind, params,
            collection=context.view_layer.active_layer_collection.collection,
        )
        obj.location = location
        obj.rotation_euler = rotation
        obj.color = random_wire_color()
        for other in context.selected_objects:
            other.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        return obj

    # -------------------------------------------------------------------------
    # Non-interactive

    def execute(self, context):
        _ensure_object_mode(context)
        params = self._effective_params()
        location = (Vector(self.location) if self.properties.is_property_set("location")
                    else context.scene.cursor.location.copy())
        rotation = (tuple(self.object_rotation) if self.properties.is_property_set("object_rotation")
                    else (0.0, 0.0, 0.0))
        self._store(params, location, rotation)
        self._create(context, params, location, rotation)
        return {'FINISHED'}

    # -------------------------------------------------------------------------
    # Interactive creation

    def invoke(self, context, _event):
        if context.window is None or not _view3d_regions(context.window.screen):
            return self.execute(context)
        _ensure_object_mode(context)
        self._base_params = self._effective_params()
        self._session = None
        self._object = None
        self._region = None
        self._area = None
        self._step_start_y = 0
        self._world_per_pixel = 0.0
        self._previous_selection = []
        self._previous_active = None
        context.window_manager.modal_handler_add(self)
        context.window.cursor_modal_set('CROSSHAIR')
        self._set_status(context)
        return {'RUNNING_MODAL'}

    _NAVIGATION = {
        'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'WHEELINMOUSE', 'WHEELOUTMOUSE',
        'TRACKPADPAN', 'TRACKPADZOOM', 'MOUSEROTATE', 'MOUSESMARTZOOM',
    }

    def modal(self, context, event):
        try:
            return self._modal(context, event)
        except Exception:
            self._end(context, cancel=True)
            raise

    def _modal(self, context, event):
        kind, value = event.type, event.value
        if kind == 'ESC' or (kind == 'RIGHTMOUSE' and value == 'PRESS'):
            return self._end(context, cancel=True)
        if kind in self._NAVIGATION or kind.startswith('NDOF') or kind.startswith('NUMPAD'):
            return {'PASS_THROUGH'}

        if self._session is None:
            # Waiting for the first press in a viewport; anything else goes to the rest of the interface.
            if kind == 'LEFTMOUSE' and value == 'PRESS':
                area, region = _region_under_mouse(context, event)
                if region is None:
                    return self._end(context, cancel=True) | {'PASS_THROUGH'}
                self._begin(context, event, area, region)
                return {'RUNNING_MODAL'}
            return {'PASS_THROUGH'}

        if kind in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE', 'LEFT_CTRL', 'RIGHT_CTRL'}:
            self._update(event)
            return {'RUNNING_MODAL'}
        if kind == 'LEFTMOUSE':
            first_step = self._session.step == 0
            if (first_step and value == 'RELEASE') or (not first_step and value == 'PRESS'):
                self._update(event)
                return self._advance(context, event)
        return {'RUNNING_MODAL'}

    def _ray(self, event):
        region, rv3d = self._region, self._region.data
        coord = (event.mouse_x - region.x, event.mouse_y - region.y)
        origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
        direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
        return tuple(origin), tuple(direction)

    def _snap_step(self, context, area):
        tool_settings = context.scene.tool_settings
        if not tool_settings.use_snap or not ({'INCREMENT', 'GRID'} & set(tool_settings.snap_elements)):
            return 0.0
        overlay = area.spaces.active.overlay
        return overlay.grid_scale_unit or overlay.grid_scale

    def _begin(self, context, event, area, region):
        rv3d = region.data
        plane = creation.construction_plane(
            [tuple(row) for row in rv3d.view_rotation.to_matrix()],
            rv3d.is_orthographic_side_view and not rv3d.is_perspective,
        )
        self._area, self._region = area, region
        origin, direction = self._ray(event)
        hit = creation.ray_plane(origin, direction, plane)
        if hit is None:
            return
        session = creation.CreationSession(self.kind, plane, self._snap_step(context, area))
        session.press(hit)
        self._previous_selection = list(context.selected_objects)
        self._previous_active = context.view_layer.objects.active
        rotation = Matrix(plane.matrix()).to_euler()
        self._object = self._create(context, {**self._base_params, **session.params}, session.location, rotation)
        self._session = session
        self._start_step(event)
        self._set_status(context)

    def _start_step(self, event):
        # Screen-space fallback for the height when looking straight down its axis (e.g. a box in the top view).
        self._step_start_y = event.mouse_y
        region, rv3d = self._region, self._region.data
        anchor = Vector(self._session.location)
        coord = view3d_utils.location_3d_to_region_2d(region, rv3d, anchor)
        if coord is None:
            self._world_per_pixel = 0.0
            return
        a = view3d_utils.region_2d_to_location_3d(region, rv3d, coord, anchor)
        b = view3d_utils.region_2d_to_location_3d(region, rv3d, coord + Vector((0.0, 1.0)), anchor)
        self._world_per_pixel = (b - a).length

    def _update(self, event):
        session = self._session
        origin, direction = self._ray(event)
        fallback = (event.mouse_y - self._step_start_y) * self._world_per_pixel
        session.update(origin, direction, square=event.ctrl, fallback_height=fallback)
        props.set_parameters(self._object.data, self.kind, session.params)
        self._object.location = session.location

    def _advance(self, context, event):
        result = self._session.advance()
        if result == "INVALID":
            # A click without a drag creates nothing; wait for the next drag.
            self._discard(context)
            self._set_status(context)
            return {'RUNNING_MODAL'}
        if result == "CONTINUE":
            self._start_step(event)
            self._set_status(context)
            return {'RUNNING_MODAL'}
        obj = self._object
        _kind, params = props.get_parameters(obj.data)
        self._store(params, obj.location.copy(), tuple(obj.rotation_euler))
        self._object = None
        self._session = None
        return self._end(context, cancel=False)

    def _discard(self, context):
        obj = self._object
        if obj is not None:
            mesh = obj.data
            bpy.data.objects.remove(obj)
            if mesh.users == 0:
                bpy.data.meshes.remove(mesh)
            for other in self._previous_selection:
                try:
                    other.select_set(True)
                except ReferenceError:
                    pass
            context.view_layer.objects.active = self._previous_active
        self._object = None
        self._session = None

    def _end(self, context, cancel):
        if cancel:
            self._discard(context)
        context.window.cursor_modal_restore()
        context.workspace.status_text_set(None)
        return {'CANCELLED'} if cancel else {'FINISHED'}

    _STEP_HINTS = {
        "RECT": "Drag to draw the base (Ctrl: square)",
        "RADIUS": "Drag from the centre to set the radius",
        "HEIGHT": "Move to set the height, click to finish",
        "RADIUS2": "Move to set radius 2, click to finish",
    }

    def _set_status(self, context):
        if self._session is None:
            step = creation.STEPS[self.kind][0]
            hint = self._STEP_HINTS[step]
            text = "{:s}: {:s} in a viewport. Right-click or Esc: cancel".format(label(self.kind), hint)
        else:
            step = self._session.step_name
            hint = self._STEP_HINTS[step]
            if step != "RECT" and self._session.step < len(self._session.steps) - 1:
                hint = hint.replace(", click to finish", ", click to continue")
            text = "{:s}: {:s}. Right-click or Esc: cancel".format(label(self.kind), hint)
        context.workspace.status_text_set(text)


class OBJECT_OT_mx_convert_to_editable_poly(bpy.types.Operator):
    """Convert live primitives to plain editable meshes, removing their parameters (instances share them)"""

    bl_idname = "object.mx_convert_to_editable_poly"
    bl_label = "Convert to Editable Poly"
    bl_options = {'REGISTER', 'UNDO'}

    @staticmethod
    def _targets(context):
        objects = list(context.selected_objects)
        if context.active_object is not None and context.active_object not in objects:
            objects.append(context.active_object)
        return [obj for obj in objects if props.settings_of(obj) is not None]

    @classmethod
    def poll(cls, context):
        return bool(cls._targets(context))

    def execute(self, context):
        meshes = {obj.data for obj in self._targets(context)}
        for mesh in meshes:
            props.clear(mesh)
        self.report({'INFO'}, "Converted {:d} primitive(s) to editable meshes".format(len(meshes)))
        return {'FINISHED'}
