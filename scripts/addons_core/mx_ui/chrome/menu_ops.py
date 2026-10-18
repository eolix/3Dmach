# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Operators behind the menu bar and the main toolbar.

Both are drawn in the top bar (or in a header-only strip), where there is no 3D viewport in the context, so
viewport commands go through :class:`MXUI_OT_viewport_call`, which runs an operator in the "active" viewport
(see :func:`target_view3d`). Editors Max opens as dialogs (Curve Editor, MAXScript Listener, Environment, ...)
open as new windows with :class:`MXUI_OT_open_editor_window`.
"""

import json

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ImportHelper
from mathutils import Matrix, Vector

from .. import utils


# -----------------------------------------------------------------------------
# Helpers

def operator_type_name(idname):
    """``"object.mx_group"`` → ``"OBJECT_OT_mx_group"``."""
    category, _, name = idname.partition(".")
    return "{:s}_OT_{:s}".format(category.upper(), name)


def has_operator(idname):
    """
    Whether an operator is available. Blender's own operators are assumed to be (the tests check every name
    drawn); our add-ons' operators (``mx_`` names, from add-ons that may be disabled) are looked up.
    """
    category, _, name = idname.partition(".")
    if category.startswith("mx_") or name.startswith("mx_"):
        return hasattr(bpy.types, operator_type_name(idname))
    return True


def operator_enum_values(idname, prop_name):
    """Identifiers of an enum property of an operator (empty when the operator is not available)."""
    if not has_operator(idname):
        return frozenset()
    category, _, name = idname.partition(".")
    try:
        prop = getattr(getattr(bpy.ops, category), name).get_rna_type().properties[prop_name]
    except (AttributeError, KeyError):
        return frozenset()
    return frozenset(item.identifier for item in prop.enum_items)


def view3d_areas(window):
    screen = window.screen if window else None
    return [area for area in (screen.areas if screen else ()) if area.type == 'VIEW_3D']


def _window_region(area):
    return next((region for region in area.regions if region.type == 'WINDOW'), None)


def target_view3d(context, perspective=False):
    """
    The 3D viewport commands from the menu bar act on: the context's viewport when there is one, else the
    largest one (Max's four views are the same size; the Perspective view wins a tie, or with ``perspective``).
    Returns ``(window, area, region)`` or None.
    """
    window = context.window
    area = context.area
    if area is not None and area.type == 'VIEW_3D':
        region = _window_region(area)
        if region is not None:
            return window, area, region
    best = None
    best_key = None
    for area in view3d_areas(window):
        region = _window_region(area)
        if region is None:
            continue
        rv3d = area.spaces.active.region_3d
        is_persp = rv3d is not None and rv3d.view_perspective == 'PERSP'
        key = (is_persp, area.width * area.height) if perspective else (area.width * area.height, is_persp)
        if best_key is None or key > best_key:
            best, best_key = (window, area, region), key
    return best


def _op_function(idname):
    category, _, name = idname.partition(".")
    return getattr(getattr(bpy.ops, category), name)


# -----------------------------------------------------------------------------
# Running viewport operators from outside a viewport

class MXUI_OT_viewport_call(Operator):
    bl_idname = "mx_ui.viewport_call"
    bl_label = "Viewport Command"
    bl_options = {'INTERNAL'}

    operator: StringProperty(name="Operator", options={'SKIP_SAVE'})
    properties: StringProperty(name="Properties", description="Operator properties as JSON", options={'SKIP_SAVE'})
    all_viewports: BoolProperty(name="All Viewports", options={'SKIP_SAVE'})
    invoke_operator: BoolProperty(name="Invoke", options={'SKIP_SAVE'})
    perspective: BoolProperty(name="Prefer Perspective", options={'SKIP_SAVE'})

    @classmethod
    def description(cls, _context, properties):
        try:
            return _op_function(properties.operator).get_rna_type().description
        except (AttributeError, KeyError, ValueError):
            return None

    @classmethod
    def poll(cls, context):
        return context.window is not None and bool(view3d_areas(context.window))

    def execute(self, context):
        try:
            func = _op_function(self.operator)
            kwargs = json.loads(self.properties) if self.properties else {}
        except (AttributeError, ValueError) as ex:
            self.report({'ERROR'}, "Invalid viewport command: {!s}".format(ex))
            return {'CANCELLED'}
        if self.all_viewports:
            window = context.window
            targets = [(window, area, _window_region(area)) for area in view3d_areas(window)]
        else:
            targets = [target_view3d(context, perspective=self.perspective)]
        targets = [target for target in targets if target is not None and target[2] is not None]
        if not targets:
            self.report({'WARNING'}, "No 3D viewport")
            return {'CANCELLED'}
        result = {'CANCELLED'}
        mode = 'INVOKE_DEFAULT' if self.invoke_operator else 'EXEC_DEFAULT'
        for window, area, region in targets:
            with context.temp_override(window=window, area=area, region=region):
                try:
                    if 'FINISHED' in func(mode, **kwargs):
                        result = {'FINISHED'}
                except RuntimeError as ex:
                    self.report({'WARNING'}, str(ex).strip())
        return result


def viewport_call(layout, idname, text, icon='NONE', all_viewports=False, invoke=False, perspective=False,
                  depress=False, **props):
    """Draw a button running ``idname`` in the active 3D viewport (or in all of them)."""
    op = layout.operator(MXUI_OT_viewport_call.bl_idname, text=text, icon=icon, depress=depress)
    op.operator = idname
    op.properties = json.dumps(props) if props else ""
    op.all_viewports = all_viewports
    op.invoke_operator = invoke
    op.perspective = perspective
    return op


class MXUI_OT_viewport_toggle(Operator):
    """Toggle a display option in every viewport"""
    bl_idname = "mx_ui.viewport_toggle"
    bl_label = "Toggle Viewport Option"
    bl_options = {'INTERNAL'}

    path: StringProperty(name="Path", description="Property path relative to the 3D viewport space",
                         options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return context.window is not None and bool(view3d_areas(context.window))

    def execute(self, context):
        spaces = [area.spaces.active for area in view3d_areas(context.window)]
        try:
            value = not viewport_option(spaces[0], self.path)
            for space in spaces:
                owner, _, name = self.path.rpartition(".")
                setattr(space.path_resolve(owner) if owner else space, name, value)
        except (AttributeError, ValueError, TypeError) as ex:
            self.report({'ERROR'}, str(ex))
            return {'CANCELLED'}
        for area in view3d_areas(context.window):
            area.tag_redraw()
        return {'FINISHED'}


def viewport_option(space, path):
    return bool(space.path_resolve(path))


def viewport_toggle(layout, context, path, text):
    """A menu entry toggling ``path`` in every viewport, with a check box showing the current state."""
    window = getattr(context, "window", None)
    areas = view3d_areas(window) if window else ()
    state = False
    if areas:
        try:
            state = viewport_option(areas[0].spaces.active, path)
        except ValueError:
            pass
    op = layout.operator(MXUI_OT_viewport_toggle.bl_idname, text=text,
                         icon='CHECKBOX_HLT' if state else 'CHECKBOX_DEHLT')
    op.path = path
    return op


class MXUI_OT_set_tool(Operator):
    """Make this the active tool of the 3D viewport"""
    bl_idname = "mx_ui.set_tool"
    bl_label = "Set Tool"
    bl_options = {'INTERNAL'}

    # Menus use this instead of `wm.tool_set_by_id`, which Blender draws indented in menus (as a tool button).
    name: StringProperty(name="Tool", options={'SKIP_SAVE'})

    def execute(self, _context):
        return bpy.ops.wm.tool_set_by_id(name=self.name, space_type='VIEW_3D')


class MXUI_OT_redraw_views(Operator):
    """Redraw all viewports"""
    bl_idname = "mx_ui.redraw_views"
    bl_label = "Redraw All Views"

    def execute(self, context):
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()
        return {'FINISHED'}


class MXUI_OT_isolate_selection(Operator):
    """Show only the selection in every viewport (local view), or end the isolation"""
    bl_idname = "mx_ui.isolate_selection"
    bl_label = "Isolate Selection"

    end: BoolProperty(name="End Isolate", options={'SKIP_SAVE'})

    @classmethod
    def description(cls, _context, properties):
        if properties.end:
            return "Show all objects again in the isolated viewports"
        return "Show only the selected objects in every viewport and zoom to them"

    @classmethod
    def poll(cls, context):
        return context.window is not None and bool(view3d_areas(context.window))

    def execute(self, context):
        changed = False
        for area in view3d_areas(context.window):
            space = area.spaces.active
            if bool(space.local_view) != self.end:
                continue
            region = _window_region(area)
            with context.temp_override(window=context.window, area=area, region=region):
                try:
                    if 'FINISHED' in bpy.ops.view3d.localview(frame_selected=not self.end):
                        changed = True
                except RuntimeError as ex:
                    self.report({'WARNING'}, str(ex).strip())
                    return {'CANCELLED'}
        return {'FINISHED'} if changed else {'CANCELLED'}


class MXUI_OT_active_shade(Operator):
    """Render interactively in the active viewport (toggles rendered shading)"""
    bl_idname = "mx_ui.active_shade"
    bl_label = "ActiveShade"

    @classmethod
    def poll(cls, context):
        return context.window is not None and bool(view3d_areas(context.window))

    def execute(self, context):
        target = target_view3d(context, perspective=True)
        if target is None:
            return {'CANCELLED'}
        shading = target[1].spaces.active.shading
        shading.type = 'SOLID' if shading.type == 'RENDERED' else 'RENDERED'
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Editor windows

# Editor kind → (label, description, Area.ui_type, Properties editor tab or None).
EDITOR_WINDOWS = {
    'MATERIAL': ("Material Editor", "Shader editor in a new window", 'ShaderNodeTree', None),
    'COMPOSITOR': ("Effects", "Compositor in a new window", 'CompositorNodeTree', None),
    'CURVE_EDITOR': ("Curve Editor", "Graph editor (animation curves) in a new window", 'FCURVES', None),
    'DOPE_SHEET': ("Dope Sheet", "Dope sheet in a new window", 'DOPESHEET', None),
    'EXPLORER': ("Scene Explorer", "Outliner in a new window", 'OUTLINER', None),
    'SCRIPT_EDITOR': ("Script Editor", "Text editor in a new window", 'TEXT_EDITOR', None),
    'LISTENER': ("Python Listener", "Interactive Python console in a new window", 'CONSOLE', None),
    'MESSAGES': ("Messages", "Reports and the operator log in a new window", 'INFO', None),
    'IMAGE': ("Image Viewer", "Image editor in a new window", 'IMAGE_EDITOR', None),
    'VIDEO_POST': ("Video Post", "Video sequencer in a new window", 'SEQUENCE_EDITOR', None),
    'RENDER_SETUP': ("Render Setup", "Render properties in a new window", 'PROPERTIES', 'RENDER'),
    'OUTPUT': ("Output Setup", "Output properties in a new window", 'PROPERTIES', 'OUTPUT'),
    'ENVIRONMENT': ("Environment", "World properties in a new window", 'PROPERTIES', 'WORLD'),
    'SPREADSHEET': ("Spreadsheet", "Spreadsheet of the active object's data in a new window", 'SPREADSHEET', None),
}


def _largest_area(screen):
    areas = [area for area in screen.areas if area.type not in {'TOPBAR', 'STATUSBAR'}]
    return max(areas, key=lambda area: area.width * area.height, default=None)


class MXUI_OT_open_editor_window(Operator):
    bl_idname = "mx_ui.open_editor_window"
    bl_label = "Open Editor Window"

    editor: EnumProperty(
        name="Editor",
        items=[(key, label, description) for key, (label, description, _ui, _tab) in EDITOR_WINDOWS.items()],
    )
    new_text: BoolProperty(name="New Script", description="Start a new text in the editor", options={'SKIP_SAVE'})

    @classmethod
    def description(cls, _context, properties):
        return EDITOR_WINDOWS[properties.editor][1]

    @classmethod
    def poll(cls, context):
        return context.window is not None and context.screen is not None and not context.screen.is_temporary

    def execute(self, context):
        _label, _description, ui_type, tab = EDITOR_WINDOWS[self.editor]
        window = context.window
        area = _largest_area(window.screen)
        if area is None:
            return {'CANCELLED'}
        before = {w.as_pointer() for w in context.window_manager.windows}
        with context.temp_override(window=window, area=area, region=_window_region(area)):
            if 'FINISHED' not in bpy.ops.screen.area_dupli('INVOKE_DEFAULT'):
                return {'CANCELLED'}
        new = [w for w in context.window_manager.windows if w.as_pointer() not in before]
        if not new:
            return {'CANCELLED'}
        area = new[0].screen.areas[0]
        area.ui_type = ui_type
        space = area.spaces.active
        if tab is not None:
            try:
                space.context = tab
            except TypeError:
                pass
        if self.new_text and space.type == 'TEXT_EDITOR':
            space.text = bpy.data.texts.new("Script.py")
        return {'FINISHED'}


def open_editor(layout, editor, text, icon='NONE', new_text=False, depress=False):
    """
    A button opening an editor window. The material editor and render setup use `mx_keymap.open_editor`
    when that add-on is enabled (so the button toggles the same window as the M and F10 keys).
    """
    keymap_editor = {'MATERIAL': 'MATERIAL', 'RENDER_SETUP': 'RENDER'}.get(editor)
    if keymap_editor and utils.keymap_operator_available("MX_KEYMAP_OT_open_editor"):
        op = layout.operator("mx_keymap.open_editor", text=text, icon=icon, depress=depress)
        op.editor = keymap_editor
        return op
    op = layout.operator(MXUI_OT_open_editor_window.bl_idname, text=text, icon=icon, depress=depress)
    op.editor = editor
    if new_text:
        op.new_text = True
    return op


# -----------------------------------------------------------------------------
# Scripting

class MXUI_OT_run_script(Operator, ImportHelper):
    """Run a Python script file"""
    bl_idname = "mx_ui.run_script"
    bl_label = "Run Script"

    filename_ext = ".py"
    filter_glob: StringProperty(default="*.py", options={'HIDDEN'})

    def execute(self, _context):
        return bpy.ops.script.python_file_run(filepath=self.filepath)


# -----------------------------------------------------------------------------
# Mirror

MIRROR_AXES = (
    ('X', "X", "", (0,)),
    ('Y', "Y", "", (1,)),
    ('Z', "Z", "", (2,)),
    ('XY', "XY", "", (0, 1)),
    ('YZ', "YZ", "", (1, 2)),
    ('ZX', "ZX", "", (2, 0)),
)
_MIRROR_AXIS_INDICES = {key: axes for key, _label, _description, axes in MIRROR_AXES}


def mirror_matrix(center, axis, offset=0.0):
    """World-space matrix mirroring about ``center`` along ``axis`` ('X', 'XY', ...), then moving by ``offset``."""
    indices = _MIRROR_AXIS_INDICES[axis]
    scale = Matrix.Identity(4)
    shift = Vector((0.0, 0.0, 0.0))
    for index in indices:
        scale[index][index] = -1.0
        shift[index] = offset
    center = Vector(center)
    return Matrix.Translation(center + shift) @ scale @ Matrix.Translation(-center)


def _top_level(objects):
    chosen = set(objects)
    result = []
    for obj in objects:
        parent = obj.parent
        while parent is not None and parent not in chosen:
            parent = parent.parent
        if parent is None:
            result.append(obj)
    return result


def selection_center(objects):
    """Centre of the world-space bounding box of ``objects`` (Max's selection centre)."""
    points = []
    for obj in objects:
        if obj.bound_box and obj.type not in {'EMPTY', 'LIGHT', 'CAMERA'}:
            points.extend(obj.matrix_world @ Vector(corner) for corner in obj.bound_box)
        else:
            points.append(obj.matrix_world.translation.copy())
    if not points:
        return Vector((0.0, 0.0, 0.0))
    low = Vector(tuple(min(p[i] for p in points) for i in range(3)))
    high = Vector(tuple(max(p[i] for p in points) for i in range(3)))
    return (low + high) / 2.0


def _clone(context, obj, instance):
    new = obj.copy()
    if obj.data is not None and not instance:
        new.data = obj.data.copy()
    base = utils._NAME_NUMBER_RE.match(obj.name)
    new.name = utils.max_style_name(base.group(1) if base else obj.name)
    collections = obj.users_collection or (context.scene.collection,)
    for collection in collections:
        collection.objects.link(new)
    return new


def mirror_objects(context, objects, axis, offset=0.0, clone='NONE'):
    """Mirror ``objects`` about their selection centre. Returns the mirrored objects (the clones, if any)."""
    objects = _top_level(list(objects))
    matrix = mirror_matrix(selection_center(objects), axis, offset)
    if clone != 'NONE':
        objects = [_clone(context, obj, clone == 'INSTANCE') for obj in objects]
    for obj in objects:
        obj.matrix_world = matrix @ obj.matrix_world
    return objects


class OBJECT_OT_mx_mirror(Operator):
    """Mirror the selection about its centre, optionally as a copy or instance (Max's Mirror dialog)"""
    bl_idname = "object.mx_mirror"
    bl_label = "Mirror"
    bl_options = {'REGISTER', 'UNDO'}

    axis: EnumProperty(name="Mirror Axis", items=[item[:3] for item in MIRROR_AXES], default='X')
    offset: FloatProperty(name="Offset", subtype='DISTANCE', unit='LENGTH')
    clone: EnumProperty(
        name="Clone Selection",
        items=(
            ('NONE', "No Clone", "Mirror the selected objects themselves"),
            ('COPY', "Copy", "Mirror copies of the selected objects"),
            ('INSTANCE', "Instance", "Mirror instances (shared data) of the selected objects"),
        ),
        default='NONE',
    )

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and bool(utils.selected_objects(context))

    def invoke(self, context, _event):
        return context.window_manager.invoke_props_dialog(self, width=260)

    def draw(self, _context):
        layout = self.layout
        box = layout.box()
        box.label(text="Mirror Axis")
        box.row().prop(self, "axis", expand=True)
        box.prop(self, "offset")
        box = layout.box()
        box.label(text="Clone Selection")
        box.row().prop(self, "clone", expand=True)

    def execute(self, context):
        result = mirror_objects(context, utils.selected_objects(context), self.axis, self.offset, self.clone)
        if self.clone != 'NONE':
            for obj in utils.selected_objects(context):
                obj.select_set(False)
            for obj in result:
                obj.select_set(True)
            context.view_layer.objects.active = result[0]
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Cameras

# Blender's viewport lens is relative to a 72 mm wide sensor, cameras default to 36 mm.
_VIEW_LENS_FACTOR = 0.5


class OBJECT_OT_mx_camera_from_view(Operator):
    """Create a camera matching the active perspective viewport and look through it"""
    bl_idname = "object.mx_camera_from_view"
    bl_label = "Create Camera From View"
    bl_options = {'REGISTER', 'UNDO'}

    physical: BoolProperty(name="Physical Camera", options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and context.window is not None and bool(view3d_areas(context.window))

    def execute(self, context):
        target = target_view3d(context, perspective=True)
        if target is None:
            return {'CANCELLED'}
        space = target[1].spaces.active
        rv3d = space.region_3d
        if rv3d.view_perspective == 'CAMERA':
            self.report({'INFO'}, "The viewport already shows a camera")
            return {'CANCELLED'}
        cam = bpy.data.cameras.new("Camera")
        if rv3d.view_perspective == 'ORTHO':
            cam.type = 'ORTHO'
            cam.ortho_scale = rv3d.view_distance * 72.0 / space.lens
        else:
            cam.lens = space.lens * _VIEW_LENS_FACTOR
        cam.clip_start = space.clip_start
        cam.clip_end = space.clip_end
        obj = bpy.data.objects.new(utils.max_style_name("PhysCamera" if self.physical else "Camera"), cam)
        obj.matrix_world = rv3d.view_matrix.inverted()
        utils.link_to_scene(context, obj)
        utils.make_active(context, obj)
        if context.scene.camera is None:
            context.scene.camera = obj
        with context.temp_override(window=target[0], area=target[1], region=target[2]):
            bpy.ops.view3d.object_as_camera()
        return {'FINISHED'}


classes = (
    MXUI_OT_viewport_call,
    MXUI_OT_viewport_toggle,
    MXUI_OT_set_tool,
    MXUI_OT_redraw_views,
    MXUI_OT_isolate_selection,
    MXUI_OT_active_shade,
    MXUI_OT_open_editor_window,
    MXUI_OT_run_script,
    OBJECT_OT_mx_mirror,
    OBJECT_OT_mx_camera_from_view,
)
