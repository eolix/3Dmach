# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Max viewports: the viewport label menus and the world axis tripod.

In the Max Layout the 3D viewport header is replaced by Max's label menus, drawn as plain text over the view
(the header region overlaps the view and its theme colour is made transparent while the chrome is on):

    [+]  [Perspective]  [Standard]  [Default Shading]

- ``[+]``: Maximize Viewport, Show Grids, ViewCube, SteeringWheels, xView, Viewport Clipping, Configure...
- ``[Perspective]``: the view (Cameras, Perspective, Orthographic, Top ... Right), Show Safe Frames ...
- ``[Standard]``: display quality (High Quality = Material Preview, Standard = Solid).
- ``[Default Shading]``: shading styles (Default Shading, Flat Color, Clay, Wireframe Override, Edged Faces,
  See-Through, Lighting and Shadows, Materials).

Blender's text info overlay and navigation gizmo are switched off in Max viewports (the ViewCube replaces the
gizmo, ``viewcube.py``), and a small world axis tripod is drawn in the bottom-left corner.
"""

import math

import bpy
import blf
import gpu
from bpy.props import EnumProperty, StringProperty
from bpy.types import Menu, Operator
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

from .. import utils
from ..placeholder import placeholder
from . import _areas, frame_state

# Transparent viewport headers while the chrome is on (alpha of the 3D viewport's theme header colour).
HEADER_ALPHA = 0.0
# Blender's default, used to restore when the stored value is lost (e.g. preferences saved while on).
DEFAULT_HEADER_ALPHA = 0.7019608


def is_max_viewport(context):
    space = getattr(context, "space_data", None)
    return space is not None and space.type == 'VIEW_3D' and _areas.max_context(context)


# -----------------------------------------------------------------------------
# Labels

AXIS_VIEWS = (
    ('TOP', "Top", Vector((0.0, 0.0, -1.0))),
    ('BOTTOM', "Bottom", Vector((0.0, 0.0, 1.0))),
    ('FRONT', "Front", Vector((0.0, 1.0, 0.0))),
    ('BACK', "Back", Vector((0.0, -1.0, 0.0))),
    ('LEFT', "Left", Vector((1.0, 0.0, 0.0))),
    ('RIGHT', "Right", Vector((-1.0, 0.0, 0.0))),
)


def axis_view(rv3d):
    """The axis view (``'TOP'`` ...) ``rv3d`` looks along, or None."""
    direction = rv3d.view_rotation @ Vector((0.0, 0.0, -1.0))
    for key, _label, axis in AXIS_VIEWS:
        if direction.dot(axis) > 0.9999:
            return key
    return None


def view_label(space, scene=None):
    rv3d = space.region_3d
    if rv3d is None:
        return "Perspective"
    if rv3d.view_perspective == 'CAMERA':
        camera = space.camera if space.use_local_camera and space.camera else (scene.camera if scene else None)
        return camera.name if camera is not None else "Camera"
    if rv3d.view_perspective == 'ORTHO':
        key = axis_view(rv3d) if rv3d.is_orthographic_side_view else None
        if key is not None:
            return next(label for k, label, _axis in AXIS_VIEWS if k == key)
        return "Orthographic"
    return "Perspective"


def quality_label(space):
    return "High Quality" if space.shading.type in {'MATERIAL', 'RENDERED'} else "Standard"


def shading_label(space):
    shading = space.shading
    if shading.type == 'WIREFRAME':
        label = "Wireframe Override"
    elif shading.type == 'SOLID' and shading.light == 'FLAT':
        label = "Flat Color"
    elif shading.type == 'SOLID' and shading.light == 'MATCAP':
        label = "Clay"
    else:
        label = "Default Shading"
    if space.overlay.show_wireframes and shading.type != 'WIREFRAME':
        label += " + Edged Faces"
    return label


# -----------------------------------------------------------------------------
# Shading styles (plain function, tested headless)

SHADING_STYLES = (
    ('DEFAULT', "Default Shading", "Shaded with lighting, in the object colours"),
    ('FLAT_COLOR', "Flat Color", "Object colours without lighting"),
    ('CLAY', "Clay", "Uniform clay material, no colours"),
    ('WIREFRAME', "Wireframe Override", "Wireframe only"),
    ('EDGED_FACES', "Edged Faces", "Toggle the wireframe drawn over shaded objects"),
    ('SEE_THROUGH', "See-Through", "Toggle drawing objects semi-transparent"),
    ('SHADOWS', "Shadows", "Toggle shadows"),
    ('AMBIENT_OCCLUSION', "Ambient Occlusion", "Toggle cavity shading"),
    ('MATERIALS', "Shaded Materials", "Show material colours instead of object colours"),
    ('OBJECT_COLORS', "Object Colors", "Show object (wire) colours"),
    ('HIGH_QUALITY', "High Quality", "Material preview"),
    ('STANDARD', "Standard", "Solid shading"),
    ('GRIDS', "Show Grids", "Toggle the home grid"),
    ('SAFE_FRAMES', "Show Safe Frames", "Toggle the camera's safe frames"),
)


def apply_shading(space, style, scene=None):
    shading = space.shading
    overlay = space.overlay
    if style in {'DEFAULT', 'FLAT_COLOR', 'CLAY'}:
        shading.type = 'SOLID'
        shading.light = {'DEFAULT': 'STUDIO', 'FLAT_COLOR': 'FLAT', 'CLAY': 'MATCAP'}[style]
        shading.color_type = 'SINGLE' if style == 'CLAY' else 'OBJECT'
    elif style == 'WIREFRAME':
        shading.type = 'WIREFRAME'
    elif style == 'EDGED_FACES':
        overlay.show_wireframes = not overlay.show_wireframes
        overlay.wireframe_threshold = 1.0
    elif style == 'SEE_THROUGH':
        if shading.type == 'WIREFRAME':
            shading.show_xray_wireframe = not shading.show_xray_wireframe
        else:
            shading.show_xray = not shading.show_xray
    elif style == 'SHADOWS':
        shading.show_shadows = not shading.show_shadows
    elif style == 'AMBIENT_OCCLUSION':
        shading.show_cavity = not shading.show_cavity
    elif style == 'MATERIALS':
        shading.color_type = 'MATERIAL'
    elif style == 'OBJECT_COLORS':
        shading.color_type = 'OBJECT'
    elif style == 'HIGH_QUALITY':
        shading.type = 'MATERIAL'
    elif style == 'STANDARD':
        shading.type = 'SOLID'
    elif style == 'GRIDS':
        show = not (overlay.show_floor or overlay.show_ortho_grid)
        overlay.show_floor = show
        overlay.show_ortho_grid = show
    elif style == 'SAFE_FRAMES':
        camera = scene.camera if scene is not None else None
        if camera is not None and camera.type == 'CAMERA':
            camera.data.show_safe_areas = not camera.data.show_safe_areas
            camera.data.show_passepartout = True


class MXUI_OT_viewport_shading(Operator):
    """Viewport display style"""
    bl_idname = "mx_ui.viewport_shading"
    bl_label = "Viewport Shading"
    bl_options = {'INTERNAL'}

    style: EnumProperty(name="Style", items=SHADING_STYLES)

    @classmethod
    def description(cls, _context, properties):
        return next(item[2] for item in SHADING_STYLES if item[0] == properties.style)

    @classmethod
    def poll(cls, context):
        return context.space_data is not None and context.space_data.type == 'VIEW_3D'

    def execute(self, context):
        apply_shading(context.space_data, self.style, context.scene)
        context.area.tag_redraw()
        return {'FINISHED'}


VIEWS = (
    ('PERSP', "Perspective", "Perspective view"),
    ('ORTHO', "Orthographic", "Orthographic view at the current angle"),
) + tuple((key, label, label + " view") for key, label, _axis in AXIS_VIEWS)


class MXUI_OT_viewport_view(Operator):
    """Change the viewport's view"""
    bl_idname = "mx_ui.viewport_view"
    bl_label = "Viewport View"
    bl_options = {'INTERNAL'}

    view: EnumProperty(name="View", items=VIEWS)

    @classmethod
    def description(cls, _context, properties):
        return next(item[2] for item in VIEWS if item[0] == properties.view)

    @classmethod
    def poll(cls, context):
        return context.space_data is not None and context.space_data.type == 'VIEW_3D'

    def execute(self, context):
        area = context.area
        region = next((r for r in area.regions if r.type == 'WINDOW'), None)
        rv3d = context.space_data.region_3d
        with context.temp_override(region=region):
            if self.view in {'PERSP', 'ORTHO'}:
                if hasattr(bpy.types, "MX_KEYMAP_OT_view_projection"):
                    bpy.ops.mx_keymap.view_projection(mode=self.view)
                else:
                    rv3d.view_perspective = self.view
            else:
                rv3d.view_perspective = 'ORTHO'
                bpy.ops.view3d.view_axis(type=self.view)
        area.tag_redraw()
        return {'FINISHED'}


class MXUI_OT_viewport_camera(Operator):
    """View through this camera"""
    bl_idname = "mx_ui.viewport_camera"
    bl_label = "Camera View"
    bl_options = {'INTERNAL'}

    name: StringProperty(name="Camera")

    @classmethod
    def poll(cls, context):
        return context.space_data is not None and context.space_data.type == 'VIEW_3D'

    def execute(self, context):
        camera = context.scene.objects.get(self.name)
        if camera is None or camera.type != 'CAMERA':
            return {'CANCELLED'}
        context.scene.camera = camera
        context.space_data.region_3d.view_perspective = 'CAMERA'
        context.area.tag_redraw()
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Label menus

def _shading_op(layout, style, text=None, depress=None, icon='NONE'):
    label = text or next(item[1] for item in SHADING_STYLES if item[0] == style)
    if depress is None:
        layout.operator(MXUI_OT_viewport_shading.bl_idname, text=label, icon=icon).style = style
    else:
        layout.operator(MXUI_OT_viewport_shading.bl_idname, text=label,
                        icon='CHECKBOX_HLT' if depress else 'CHECKBOX_DEHLT').style = style


class VIEW3D_MT_mx_viewcube(Menu):
    bl_idname = "VIEW3D_MT_mx_viewcube"
    bl_label = "ViewCube"

    def draw(self, context):
        layout = self.layout
        state = frame_state.get(context)
        if state is not None:
            layout.prop(state, "show_viewcube", text="Show the ViewCube")
        layout.operator("mx_ui.viewcube_home", text="Home", icon='HOME')
        placeholder(layout, "Set Current View as Home")
        placeholder(layout, "Set Current View as Front")
        placeholder(layout, "Reset Front")
        placeholder(layout, "Configure...")


class VIEW3D_MT_mx_viewport_plus(Menu):
    bl_idname = "VIEW3D_MT_mx_viewport_plus"
    bl_label = "[+]"

    def draw(self, context):
        layout = self.layout
        layout.operator_context = 'INVOKE_REGION_WIN'
        space = context.space_data
        layout.operator("mx_ui.viewport_maximize_toggle", text="Maximize Viewport", icon='FULLSCREEN_ENTER')
        placeholder(layout, "Active Viewport")
        placeholder(layout, "Disable Viewport")
        layout.separator()
        overlay = space.overlay
        _shading_op(layout, 'GRIDS', depress=overlay.show_floor or overlay.show_ortho_grid)
        state = frame_state.get(context)
        if state is not None:
            layout.prop(state, "show_world_axis", text="Display World Axis")
        layout.menu(VIEW3D_MT_mx_viewcube.bl_idname)
        placeholder(layout, "SteeringWheels")
        placeholder(layout, "xView")
        layout.separator()
        placeholder(layout, "Create Preview")
        layout.separator()
        placeholder(layout, "Viewport Clipping")
        placeholder(layout, "2D Pan Zoom Mode")
        layout.separator()
        layout.operator("wm.call_panel", text="Configure Viewports...").name = "VIEW3D_PT_overlay"


class VIEW3D_MT_mx_viewport_cameras(Menu):
    bl_idname = "VIEW3D_MT_mx_viewport_cameras"
    bl_label = "Cameras"

    def draw(self, context):
        layout = self.layout
        cameras = [obj for obj in context.scene.objects if obj.type == 'CAMERA']
        if not cameras:
            layout.label(text="No Cameras")
        for camera in cameras:
            layout.operator(MXUI_OT_viewport_camera.bl_idname, text=camera.name, icon='CAMERA_DATA').name = camera.name


class VIEW3D_MT_mx_viewport_view(Menu):
    bl_idname = "VIEW3D_MT_mx_viewport_view"
    bl_label = "View"

    def draw(self, context):
        layout = self.layout
        layout.operator_context = 'INVOKE_REGION_WIN'
        layout.menu(VIEW3D_MT_mx_viewport_cameras.bl_idname)
        placeholder(layout, "Lights")
        layout.separator()
        for key, label, _desc in VIEWS:
            layout.operator(MXUI_OT_viewport_view.bl_idname, text=label).view = key
            if key == 'ORTHO':
                layout.separator()
        layout.separator()
        placeholder(layout, "Extended Viewports")
        layout.separator()
        camera = context.scene.camera
        safe = camera is not None and camera.type == 'CAMERA' and camera.data.show_safe_areas
        _shading_op(layout, 'SAFE_FRAMES', depress=safe)
        placeholder(layout, "Viewport Clipping")
        layout.separator()
        placeholder(layout, "Undo View Change")
        placeholder(layout, "Redo View Change")


class VIEW3D_MT_mx_viewport_quality(Menu):
    bl_idname = "VIEW3D_MT_mx_viewport_quality"
    bl_label = "Quality"

    def draw(self, context):
        layout = self.layout
        quality = quality_label(context.space_data)
        layout.operator(MXUI_OT_viewport_shading.bl_idname, text="High Quality",
                        icon='RADIOBUT_ON' if quality == "High Quality" else 'RADIOBUT_OFF').style = 'HIGH_QUALITY'
        layout.operator(MXUI_OT_viewport_shading.bl_idname, text="Standard",
                        icon='RADIOBUT_ON' if quality == "Standard" else 'RADIOBUT_OFF').style = 'STANDARD'
        placeholder(layout, "Performance", icon='RADIOBUT_OFF')
        placeholder(layout, "DX Mode", icon='RADIOBUT_OFF')
        layout.separator()
        placeholder(layout, "Display Selected")
        placeholder(layout, "Viewport Background")
        layout.separator()
        layout.operator("wm.call_panel", text="Per-View Preference...").name = "VIEW3D_PT_shading"


class VIEW3D_MT_mx_viewport_lighting(Menu):
    bl_idname = "VIEW3D_MT_mx_viewport_lighting"
    bl_label = "Lighting and Shadows"

    def draw(self, context):
        layout = self.layout
        shading = context.space_data.shading
        _shading_op(layout, 'SHADOWS', depress=shading.show_shadows)
        _shading_op(layout, 'AMBIENT_OCCLUSION', depress=shading.show_cavity)
        layout.separator()
        placeholder(layout, "Illuminate with Scene Lights")
        placeholder(layout, "Illuminate with Default Lights")


class VIEW3D_MT_mx_viewport_materials(Menu):
    bl_idname = "VIEW3D_MT_mx_viewport_materials"
    bl_label = "Materials"

    def draw(self, context):
        layout = self.layout
        color_type = context.space_data.shading.color_type
        layout.operator(MXUI_OT_viewport_shading.bl_idname, text="Shaded Materials",
                        icon='RADIOBUT_ON' if color_type == 'MATERIAL' else 'RADIOBUT_OFF').style = 'MATERIALS'
        layout.operator(MXUI_OT_viewport_shading.bl_idname, text="Object Colors",
                        icon='RADIOBUT_ON' if color_type == 'OBJECT' else 'RADIOBUT_OFF').style = 'OBJECT_COLORS'
        placeholder(layout, "Realistic Materials with Maps", icon='RADIOBUT_OFF')


class VIEW3D_MT_mx_viewport_shading(Menu):
    bl_idname = "VIEW3D_MT_mx_viewport_shading"
    bl_label = "Shading"

    def draw(self, context):
        layout = self.layout
        space = context.space_data
        current = shading_label(space).split(" + ")[0]
        for style, label in (('DEFAULT', "Default Shading"), ('FACETS', "Facets"), ('FLAT_COLOR', "Flat Color"),
                             ('HIDDEN_LINE', "Hidden Line"), ('CLAY', "Clay"), ('WIREFRAME', "Wireframe Override")):
            icon = 'RADIOBUT_ON' if current == label else 'RADIOBUT_OFF'
            if style in {'FACETS', 'HIDDEN_LINE'}:
                placeholder(layout, label, icon=icon)
            else:
                layout.operator(MXUI_OT_viewport_shading.bl_idname, text=label, icon=icon).style = style
        layout.separator()
        _shading_op(layout, 'EDGED_FACES', depress=space.overlay.show_wireframes)
        placeholder(layout, "Bounding Box")
        xray = space.shading.show_xray_wireframe if space.shading.type == 'WIREFRAME' else space.shading.show_xray
        _shading_op(layout, 'SEE_THROUGH', depress=xray)
        layout.separator()
        placeholder(layout, "Stylized")
        layout.menu(VIEW3D_MT_mx_viewport_lighting.bl_idname)
        layout.menu(VIEW3D_MT_mx_viewport_materials.bl_idname)
        layout.separator()
        layout.operator("wm.call_panel", text="Per-View Preference...").name = "VIEW3D_PT_shading"


def draw_labels(layout, context):
    space = context.space_data
    row = layout.row(align=True)
    row.emboss = 'NONE'
    row.menu(VIEW3D_MT_mx_viewport_plus.bl_idname, text="[+]")
    row.menu(VIEW3D_MT_mx_viewport_view.bl_idname, text="[{:s}]".format(view_label(space, context.scene)))
    row.menu(VIEW3D_MT_mx_viewport_quality.bl_idname, text="[{:s}]".format(quality_label(space)))
    row.menu(VIEW3D_MT_mx_viewport_shading.bl_idname, text="[{:s}]".format(shading_label(space)))
    layout.separator_spacer()


def _draw_header(self, context):
    if not is_max_viewport(context):
        return False
    draw_labels(self.layout, context)
    return True


# -----------------------------------------------------------------------------
# World axis tripod

TRIPOD_ORIGIN = (36.0, 36.0)
TRIPOD_LENGTH = 24.0
_AXIS_COLORS = (
    (0.90, 0.25, 0.25, 1.0),
    (0.35, 0.80, 0.30, 1.0),
    (0.30, 0.50, 1.00, 1.0),
)


def tripod_lines(rv3d, origin=TRIPOD_ORIGIN, length=TRIPOD_LENGTH, scale=1.0):
    """``[(axis letter, colour, start, end)]`` in region pixels, back-most axis first."""
    rotation = rv3d.view_rotation.inverted().to_matrix()
    ox, oy = origin[0] * scale, origin[1] * scale
    lines = []
    for index, letter in enumerate("xyz"):
        axis = Vector((0.0, 0.0, 0.0))
        axis[index] = 1.0
        view = rotation @ axis
        end = (ox + view.x * length * scale, oy + view.y * length * scale)
        lines.append((view.z, letter, _AXIS_COLORS[index], (ox, oy), end))
    lines.sort(key=lambda item: item[0])
    return [line[1:] for line in lines]


_draw_handle = None


def _draw_tripod():
    context = bpy.context
    if not is_max_viewport(context):
        return
    state = frame_state.get(context)
    if state is not None and not state.show_world_axis:
        return
    rv3d = context.region_data
    region = context.region
    if rv3d is None or region is None:
        return
    scale = context.preferences.system.ui_scale or 1.0
    shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    font = 0
    blf.size(font, 11.0 * scale)
    for letter, color, start, end in tripod_lines(rv3d, scale=scale):
        batch = batch_for_shader(shader, 'LINES', {"pos": [start, end]})
        shader.bind()
        shader.uniform_float("viewportSize", (region.width, region.height))
        shader.uniform_float("lineWidth", 2.0 * scale)
        shader.uniform_float("color", color)
        batch.draw(shader)
        dx, dy = end[0] - start[0], end[1] - start[1]
        norm = math.hypot(dx, dy) or 1.0
        blf.color(font, *color)
        offset = 5.0 * scale / norm
        blf.position(font, end[0] + dx * offset - 3.0 * scale, end[1] + dy * offset - 4.0 * scale, 0.0)
        blf.draw(font, letter)
    gpu.state.blend_set('NONE')


# -----------------------------------------------------------------------------
# Chrome on / off

_saved = {"header_alpha": None}


def _theme_header():
    return bpy.context.preferences.themes[0].view_3d.space.header


def set_transparent_headers(enabled):
    try:
        color = _theme_header()
    except (AttributeError, IndexError):
        return
    if enabled:
        if abs(color[3] - HEADER_ALPHA) > 1e-4:
            _saved["header_alpha"] = color[3]
            color[3] = HEADER_ALPHA
    else:
        if abs(color[3] - HEADER_ALPHA) <= 1e-4:
            alpha = _saved["header_alpha"]
            color[3] = alpha if alpha is not None else DEFAULT_HEADER_ALPHA
        _saved["header_alpha"] = None


def configure_chrome_view3d(space, enabled):
    """Settings of a Max viewport that depend on the chrome: text overlay and navigation gizmo."""
    space.overlay.show_text = not enabled
    space.show_gizmo_navigate = not enabled


def chrome_toggled(enabled):
    set_transparent_headers(enabled)
    for workspace in bpy.data.workspaces:
        if not _areas.is_max_workspace(workspace):
            continue
        for screen in workspace.screens:
            for area in screen.areas:
                if area.type == 'VIEW_3D':
                    configure_chrome_view3d(area.spaces.active, enabled)


def _apply_after_register():
    if utils.use_max_chrome():
        set_transparent_headers(True)
    return None


_override = None

classes = (
    MXUI_OT_viewport_shading,
    MXUI_OT_viewport_view,
    MXUI_OT_viewport_camera,
    VIEW3D_MT_mx_viewcube,
    VIEW3D_MT_mx_viewport_plus,
    VIEW3D_MT_mx_viewport_cameras,
    VIEW3D_MT_mx_viewport_view,
    VIEW3D_MT_mx_viewport_quality,
    VIEW3D_MT_mx_viewport_lighting,
    VIEW3D_MT_mx_viewport_materials,
    VIEW3D_MT_mx_viewport_shading,
)


def register():
    global _override, _draw_handle
    _override = _areas.override_draw(bpy.types.VIEW3D_HT_header, _draw_header)
    if not bpy.app.background:
        _draw_handle = bpy.types.SpaceView3D.draw_handler_add(_draw_tripod, (), 'WINDOW', 'POST_PIXEL')
    # The add-on's preferences exist only once it is registered.
    bpy.app.timers.register(_apply_after_register, first_interval=0.0)


def unregister():
    global _override, _draw_handle
    if bpy.app.timers.is_registered(_apply_after_register):
        bpy.app.timers.unregister(_apply_after_register)
    set_transparent_headers(False)
    if _draw_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_draw_handle, 'WINDOW')
        _draw_handle = None
    if _override is not None:
        _areas.restore_draw(bpy.types.VIEW3D_HT_header, _override)
        _override = None
