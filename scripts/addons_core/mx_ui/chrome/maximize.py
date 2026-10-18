# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Max's "Maximize Viewport Toggle" (Alt+W) inside the Max Layout.

Max enlarges the active viewport to the whole viewport block and keeps everything else on screen (menus,
toolbar, Scene Explorer, command panel, time slider). Blender's "maximize area" instead hides every other
editor. In the Max Layout we therefore move the 2x2 viewport block's inner edges to its far sides, which
shrinks the other three viewports to slivers (their headers are hidden meanwhile), and move them back to
restore. The edge positions are kept on the screen, so the toggle survives saving the file.
"""

import bpy
from bpy.types import Operator

from . import _areas

SCREEN_KEY = "mx_viewport_maximized"


def plan(rects, target):
    """
    Work out the edge moves that maximize viewport ``target`` (pure geometry, testable without Blender).

    :arg rects: ``(x, y, width, height)`` of the four viewports (window pixels).
    :arg target: Index into ``rects`` of the viewport to maximize.
    :return: ``(vertical, horizontal)`` moves, each ``(x, y, delta, start)``: a point on the inner edge, the
       distance to move it (positive = right/up) and the edge's current coordinate; or None when the rectangles
       aren't a 2x2 block.
    """
    if len(rects) != 4:
        return None
    left = min(r[0] for r in rects)
    right = max(r[0] + r[2] for r in rects)
    bottom = min(r[1] for r in rects)
    top = max(r[1] + r[3] for r in rects)
    columns = sorted({r[0] for r in rects})
    rows = sorted({r[1] for r in rects})
    if len(columns) != 2 or len(rows) != 2:
        return None
    edge_x, edge_y = columns[1], rows[1]
    tx, ty = rects[target][0], rects[target][1]
    # Push each inner edge away from the target: to the far left when the target is in the right column, etc.
    dx = (left - edge_x) if tx == edge_x else (right - edge_x)
    dy = (bottom - edge_y) if ty == edge_y else (top - edge_y)
    mid_x, mid_y = (left + right) // 2, (bottom + top) // 2
    return (edge_x, mid_y, dx, edge_x), (mid_x, edge_y, dy, edge_y)


def restore_plan(rects, original):
    """Edge moves putting the inner edges back at ``original`` = (edge_x fraction, edge_y fraction)."""
    if len(rects) != 4:
        return None
    left = min(r[0] for r in rects)
    right = max(r[0] + r[2] for r in rects)
    bottom = min(r[1] for r in rects)
    top = max(r[1] + r[3] for r in rects)
    columns = sorted({r[0] for r in rects})
    rows = sorted({r[1] for r in rects})
    if len(columns) != 2 or len(rows) != 2:
        return None
    edge_x, edge_y = columns[1], rows[1]
    want_x = round(left + original[0] * (right - left))
    want_y = round(bottom + original[1] * (top - bottom))
    mid_x, mid_y = (left + right) // 2, (bottom + top) // 2
    return (edge_x, mid_y, want_x - edge_x, edge_x), (mid_x, edge_y, want_y - edge_y, edge_y)


def viewport_areas(screen):
    return [a for a in screen.areas if a.type == 'VIEW_3D']


def _rect(area):
    return (area.x, area.y, area.width, area.height)


def _move(context, x, y, delta):
    if delta == 0:
        return
    with context.temp_override(window=context.window, screen=context.screen):
        bpy.ops.screen.area_move(x=int(x), y=int(y), delta=int(delta))


class MXUI_OT_max_viewport_maximize(Operator):
    """Maximize the viewport under the mouse within the viewport block, or restore the four viewports"""
    bl_idname = "mx_ui.max_viewport_maximize"
    bl_label = "Maximize Viewport Toggle"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        screen = context.screen
        return (context.window is not None and screen is not None and not screen.is_temporary
                and _areas.max_context(context) and len(viewport_areas(screen)) == 4)

    def execute(self, context):
        screen = context.screen
        areas = viewport_areas(screen)
        rects = [_rect(a) for a in areas]
        stored = screen.get(SCREEN_KEY)
        if stored:
            moves = restore_plan(rects, tuple(stored))
            if moves is None:
                return {'CANCELLED'}
            for (x, y, delta, _start) in moves:
                _move(context, x, y, delta)
            for area in areas:
                area.spaces.active.show_region_header = True
            del screen[SCREEN_KEY]
            return {'FINISHED'}

        target = context.area if context.area in areas else None
        if target is None:
            return {'CANCELLED'}
        index = areas.index(target)
        moves = plan(rects, index)
        if moves is None:
            return {'CANCELLED'}
        left = min(r[0] for r in rects)
        right = max(r[0] + r[2] for r in rects)
        bottom = min(r[1] for r in rects)
        top = max(r[1] + r[3] for r in rects)
        (vx, _vy, _dvx, _sx), (_hx, hy, _dhy, _sy) = moves
        screen[SCREEN_KEY] = ((vx - left) / max(right - left, 1), (hy - bottom) / max(top - bottom, 1))
        for (x, y, delta, _start) in moves:
            _move(context, x, y, delta)
        for area in areas:
            if area != target:
                area.spaces.active.show_region_header = False
        return {'FINISHED'}


def is_maximized(screen):
    return bool(screen and screen.get(SCREEN_KEY))


classes = (
    MXUI_OT_max_viewport_maximize,
)
