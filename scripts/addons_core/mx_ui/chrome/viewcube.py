# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
The ViewCube: a clickable cube in the top-right corner of each Max viewport.

A Python gizmo (``MXUI_GT_viewcube``) draws the cube in region pixels with ``gpu`` and does its own picking
(``test_select``): each face is split in 3 x 3 cells, the middle cell picks the face, the border cells the
edges and corners they touch, so there are 26 targets, each a direction ``(x, y, z)`` with components in
{-1, 0, 1}. Clicking a face switches to that orthographic view (Top, Front, ...); clicking an edge or corner
turns the view to look from there, in perspective. Dragging the cube orbits the view;
the small house above it goes back to the home view. Original geometry and labels; Blender's navigation gizmo
is switched off in Max viewports.

The gizmo also records the viewport the mouse is over (Blender asks the gizmo on each mouse move), which the
status line's navigation controls act on.
"""

import math

import bpy
import blf
import gpu
from bpy.types import Gizmo, GizmoGroup, Operator
from gpu_extras.batch import batch_for_shader
from mathutils import Euler, Matrix, Vector

from . import _areas, frame_state, navigation

# Layout in region pixels at UI scale 1.
CUBE_SIZE = 30.0            # Half the cube's edge.
MARGIN_RIGHT = 62.0         # Distance of the cube centre from the right edge.
MARGIN_TOP = 78.0           # ... and from the top (below the label menus).
EDGE_FRACTION = 0.22        # Width of the edge / corner cells, as a fraction of the edge length.
HOME_PART = 100
_DRAG_THRESHOLD = 4

FACE_LABELS = {
    (0, 0, 1): "TOP",
    (0, 0, -1): "BOTTOM",
    (0, -1, 0): "FRONT",
    (0, 1, 0): "BACK",
    (-1, 0, 0): "LEFT",
    (1, 0, 0): "RIGHT",
}
FACE_VIEWS = {
    (0, 0, 1): 'TOP',
    (0, 0, -1): 'BOTTOM',
    (0, -1, 0): 'FRONT',
    (0, 1, 0): 'BACK',
    (-1, 0, 0): 'LEFT',
    (1, 0, 0): 'RIGHT',
}

# Same angle as the Max Layout's perspective view.
HOME_ROTATION = Euler((math.radians(65.0), 0.0, math.radians(-45.0))).to_quaternion()

_FACE_COLOR = (0.78, 0.78, 0.80, 0.92)
_FACE_SHADE = 0.13
_HIGHLIGHT = (0.45, 0.70, 1.0, 0.95)
_OUTLINE = (0.25, 0.25, 0.27, 1.0)
_TEXT = (0.18, 0.18, 0.20, 1.0)
_RING = (0.55, 0.55, 0.58, 0.8)


# -----------------------------------------------------------------------------
# Geometry (plain functions, tested headless)

def _face_axes(normal):
    """Two tangent axes of the face with ``normal``."""
    n = Vector(normal)
    t1 = Vector((0.0, 0.0, 1.0)) if abs(n.z) < 0.5 else Vector((1.0, 0.0, 0.0))
    t2 = n.cross(t1)
    t1 = t2.cross(n)
    return t1, t2


def cube_cells(view_rotation, center, size):
    """
    The visible cells of the cube as ``[(part, polygon, depth, face)]``, front-most last: ``part`` is the
    target direction (tuple of -1/0/1), ``polygon`` four 2D points in region pixels, ``face`` the face normal.
    """
    to_view = view_rotation.inverted().to_matrix()
    cx, cy = center
    bounds = (-1.0, -1.0 + 2.0 * EDGE_FRACTION, 1.0 - 2.0 * EDGE_FRACTION, 1.0)
    cells = []
    for normal in FACE_LABELS:
        n = Vector(normal)
        view_normal = to_view @ n
        if view_normal.z <= 1e-4:
            continue
        t1, t2 = _face_axes(normal)
        for i in range(3):
            for j in range(3):
                corners = []
                for a, b in ((bounds[i], bounds[j]), (bounds[i + 1], bounds[j]),
                             (bounds[i + 1], bounds[j + 1]), (bounds[i], bounds[j + 1])):
                    p = to_view @ ((n + t1 * a + t2 * b) * size)
                    corners.append((cx + p.x, cy + p.y))
                part = n + t1 * (i - 1) + t2 * (j - 1)
                part = tuple(int(round(c)) for c in part)
                depth = view_normal.z
                cells.append((part, corners, depth, normal))
    cells.sort(key=lambda cell: cell[2])
    return cells


def _point_in_polygon(point, polygon):
    x, y = point
    inside = False
    count = len(polygon)
    for k in range(count):
        x1, y1 = polygon[k]
        x2, y2 = polygon[(k + 1) % count]
        if (y1 > y) != (y2 > y):
            if x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                inside = not inside
    return inside


def pick_part(cells, point):
    for part, polygon, _depth, _face in reversed(cells):
        if _point_in_polygon(point, polygon):
            return part
    return None


def cube_center(region_width, region_height, scale=1.0):
    return region_width - MARGIN_RIGHT * scale, region_height - MARGIN_TOP * scale


def home_rect(center, size):
    cx, cy = center
    return cx - size * 1.9, cy + size * 1.0, size * 0.6


def rotation_for_part(part):
    """View rotation looking at the cube from ``part`` (its +Z axis points to ``part``)."""
    z = Vector(part).normalized()
    if abs(z.z) > 0.999:
        up = Vector((0.0, 1.0 if z.z > 0 else -1.0, 0.0))
    else:
        up = Vector((0.0, 0.0, 1.0))
    x = up.cross(z).normalized()
    y = z.cross(x)
    return Matrix((x, y, z)).transposed().to_quaternion()


# -----------------------------------------------------------------------------
# View changes

def set_view(area, rv3d, target):
    """
    Turn ``rv3d`` to the rotation ``target``. Faces go through ``view3d.view_axis``, which animates (smooth
    view); edges and corners are set directly: an animation from timers registered while the gizmo finishes
    didn't advance in the GUI check.
    """
    rv3d.view_rotation = target
    area.tag_redraw()


def apply_part(context, area, region, part):
    """Change the viewport for a click on ``part`` (a direction, or `HOME_PART`)."""
    rv3d = region.data
    if part == HOME_PART:
        rv3d.is_orthographic_side_view = False
        if rv3d.view_perspective != 'PERSP':
            rv3d.view_perspective = 'PERSP'
        set_view(area, rv3d, HOME_ROTATION)
        with context.temp_override(area=area, region=region):
            if bpy.ops.view3d.view_all.poll():
                bpy.ops.view3d.view_all(center=False)
        return
    view = FACE_VIEWS.get(tuple(part))
    if view is not None:
        with context.temp_override(area=area, region=region):
            bpy.ops.view3d.view_axis(type=view)
        return
    if rv3d.view_perspective == 'CAMERA':
        rv3d.view_perspective = 'PERSP'
    rv3d.is_orthographic_side_view = False
    if rv3d.view_perspective == 'ORTHO':
        # Leaving an axis view: Max shows edges and corners in perspective.
        rv3d.view_perspective = 'PERSP'
    set_view(area, rv3d, rotation_for_part(part))


class MXUI_OT_viewcube_home(Operator):
    """Go to the Home view (perspective, the whole scene in view)"""
    bl_idname = "mx_ui.viewcube_home"
    bl_label = "Home"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'VIEW_3D'

    def execute(self, context):
        region = next((r for r in context.area.regions if r.type == 'WINDOW'), None)
        if region is None:
            return {'CANCELLED'}
        apply_part(context, context.area, region, HOME_PART)
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Gizmo

def _shade(color, depth):
    k = 1.0 - _FACE_SHADE * (1.0 - depth)
    return (color[0] * k, color[1] * k, color[2] * k, color[3])


def _polygon_batch(shader, polygon):
    a, b, c, d = polygon
    return batch_for_shader(shader, 'TRIS', {"pos": [a, b, c, a, c, d]})


def _pixel_matrices(region):
    projection = Matrix.Identity(4)
    projection[0][0] = 2.0 / region.width
    projection[1][1] = 2.0 / region.height
    projection[0][3] = -1.0
    projection[1][3] = -1.0
    return projection


class MXUI_GT_viewcube(Gizmo):
    bl_idname = "MXUI_GT_viewcube"
    __slots__ = ("hover", "press", "dragged", "_start")

    def setup(self):
        self.hover = None
        self.press = None
        self.dragged = False

    def _layout(self, context):
        region = context.region
        scale = context.preferences.system.ui_scale or 1.0
        center = cube_center(region.width, region.height, scale)
        size = CUBE_SIZE * scale
        return center, size, scale

    def test_select(self, context, location):
        navigation.note_viewport(context.area)
        rv3d = context.region_data
        if rv3d is None:
            return -1
        center, size, _scale = self._layout(context)
        hx, hy, hs = home_rect(center, size)
        x, y = location
        if abs(x - hx) <= hs and abs(y - hy) <= hs:
            self.hover = HOME_PART
            return 0
        part = pick_part(cube_cells(rv3d.view_rotation, center, size), (x, y))
        self.hover = part
        return -1 if part is None else 0

    def draw(self, context):
        rv3d = context.region_data
        region = context.region
        if rv3d is None or region is None:
            return
        center, size, scale = self._layout(context)
        cells = cube_cells(rv3d.view_rotation, center, size)
        hover = self.hover if self.is_highlight else None
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        gpu.state.blend_set('ALPHA')
        gpu.state.depth_test_set('NONE')
        with gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
            gpu.matrix.load_identity()
            gpu.matrix.load_projection_matrix(_pixel_matrices(region))
            self._draw_ring(shader, rv3d, center, size)
            for part, polygon, depth, _face in cells:
                color = _HIGHLIGHT if hover is not None and part == hover else _shade(_FACE_COLOR, depth)
                shader.bind()
                shader.uniform_float("color", color)
                _polygon_batch(shader, polygon).draw(shader)
            self._draw_outline(shader, rv3d, center, size)
            self._draw_home(shader, center, size, hover == HOME_PART)
            self._draw_labels(rv3d, center, size, scale)
        gpu.state.blend_set('NONE')

    def _draw_ring(self, shader, rv3d, center, size):
        to_view = rv3d.view_rotation.inverted().to_matrix()
        points = []
        radius = size * 1.75
        for k in range(49):
            angle = 2.0 * math.pi * k / 48
            p = to_view @ Vector((math.cos(angle) * radius, math.sin(angle) * radius, -size))
            points.append((center[0] + p.x, center[1] + p.y))
        shader.bind()
        shader.uniform_float("color", _RING)
        batch_for_shader(shader, 'LINE_STRIP', {"pos": points}).draw(shader)

    def _draw_outline(self, shader, rv3d, center, size):
        to_view = rv3d.view_rotation.inverted().to_matrix()
        lines = []
        for normal in FACE_LABELS:
            n = Vector(normal)
            if (to_view @ n).z <= 1e-4:
                continue
            t1, t2 = _face_axes(normal)
            corners = [to_view @ ((n + t1 * a + t2 * b) * size) for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
            for k in range(4):
                p, q = corners[k], corners[(k + 1) % 4]
                lines += [(center[0] + p.x, center[1] + p.y), (center[0] + q.x, center[1] + q.y)]
        shader.bind()
        shader.uniform_float("color", _OUTLINE)
        batch_for_shader(shader, 'LINES', {"pos": lines}).draw(shader)

    def _draw_home(self, shader, center, size, highlight):
        hx, hy, hs = home_rect(center, size)
        s = hs * 0.8
        house = [(hx - s, hy - s), (hx + s, hy - s), (hx + s, hy + s * 0.2), (hx, hy + s), (hx - s, hy + s * 0.2)]
        shader.bind()
        shader.uniform_float("color", _HIGHLIGHT if highlight else _FACE_COLOR)
        tris = [house[0], house[1], house[2], house[0], house[2], house[4], house[4], house[2], house[3]]
        batch_for_shader(shader, 'TRIS', {"pos": tris}).draw(shader)
        shader.uniform_float("color", _OUTLINE)
        batch_for_shader(shader, 'LINE_LOOP', {"pos": house}).draw(shader)

    def _draw_labels(self, rv3d, center, size, scale):
        to_view = rv3d.view_rotation.inverted().to_matrix()
        font = 0
        blf.size(font, 8.5 * scale)
        blf.color(font, *_TEXT)
        for normal, text in FACE_LABELS.items():
            n = to_view @ Vector(normal)
            if n.z < 0.35:
                continue
            p = n * size
            width, height = blf.dimensions(font, text)
            blf.position(font, center[0] + p.x - width / 2.0, center[1] + p.y - height / 2.0, 0.0)
            blf.draw(font, text)

    def invoke(self, context, event):
        self.press = self.hover
        self.dragged = False
        self._start = (event.mouse_region_x, event.mouse_region_y)
        return {'RUNNING_MODAL'}

    def modal(self, context, event, _tweak):
        if event.type == 'MOUSEMOVE':
            dx = event.mouse_region_x - self._start[0]
            dy = event.mouse_region_y - self._start[1]
            if not self.dragged and math.hypot(dx, dy) > _DRAG_THRESHOLD:
                self.dragged = True
            if self.dragged:
                self._orbit(context, dx, dy)
                self._start = (event.mouse_region_x, event.mouse_region_y)
        return {'RUNNING_MODAL'}

    def _orbit(self, context, dx, dy):
        navigation.orbit_view(context.region_data, dx, dy, speed=0.012)
        context.area.tag_redraw()

    def exit(self, context, cancel):
        if cancel or self.dragged or self.press is None:
            return
        region = context.region
        apply_part(context, context.area, region, self.press)


class VIEW3D_GGT_mx_viewcube(GizmoGroup):
    bl_idname = "VIEW3D_GGT_mx_viewcube"
    bl_label = "ViewCube"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    bl_options = {'PERSISTENT'}

    @classmethod
    def poll(cls, context):
        if not _areas.max_context(context):
            return False
        space = context.space_data
        if space is None or not space.show_gizmo:
            return False
        state = frame_state.get(context)
        return state is None or state.show_viewcube

    def setup(self, _context):
        self.cube = self.gizmos.new(MXUI_GT_viewcube.bl_idname)
        self.cube.use_draw_modal = True


classes = (
    MXUI_OT_viewcube_home,
    MXUI_GT_viewcube,
    VIEW3D_GGT_mx_viewcube,
)
