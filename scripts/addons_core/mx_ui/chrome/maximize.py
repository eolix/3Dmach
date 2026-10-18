# SPDX-FileCopyrightText: 2026 3Dmach Authors
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
    Work out the two edge moves that maximize viewport ``target`` (pure geometry, testable without Blender).

    The 2x2 block may have been split rows-first or columns-first, so an inner edge can be one straight line or
    two separate segments. Each move is made at a point inside the target's own extent, which always picks the
    edge (segment) bordering the target; the area beyond the other edge segment becomes a sliver anyway.

    :arg rects: ``(x, y, width, height)`` of the four viewports (window pixels, y up).
    :arg target: Index into ``rects`` of the viewport to maximize.
    :return: ``(vertical, horizontal)`` moves, each ``(x, y, delta, edge)``: a point on the edge, the distance to
       move it (positive = right/up) and the edge's coordinate before the move; or None when the rectangles
       aren't a 2x2 block.
    """
    if len(rects) != 4:
        return None
    left = min(r[0] for r in rects)
    right = max(r[0] + r[2] for r in rects)
    bottom = min(r[1] for r in rects)
    top = max(r[1] + r[3] for r in rects)
    tx, ty, tw, th = rects[target]
    in_right_column = tx > left
    in_top_row = ty > bottom
    if in_right_column == (tx + tw < right) or in_top_row == (ty + th < top):
        return None     # Not a corner of the block: not a 2x2 layout.
    mid_x, mid_y = tx + tw // 2, ty + th // 2
    # Vertical edge on the target's inner side, pushed to the block's far side.
    if in_right_column:
        vertical = (tx, mid_y, left - tx, tx)
    else:
        vertical = (tx + tw, mid_y, right - (tx + tw), tx + tw)
    if in_top_row:
        horizontal = (mid_x, ty, bottom - ty, ty)
    else:
        horizontal = (mid_x, ty + th, top - (ty + th), ty + th)
    return vertical, horizontal


def restore_plan(rect, original_edges, in_right_column, in_top_row):
    """
    Edge moves that put the maximized viewport's inner edges back where they were.

    :arg rect: The maximized viewport's current ``(x, y, width, height)``.
    :arg original_edges: ``(x, y)`` of its inner vertical and horizontal edges before maximizing.
    """
    x, y, w, h = rect
    mid_x, mid_y = x + w // 2, y + h // 2
    edge_x = x if in_right_column else x + w
    edge_y = y if in_top_row else y + h
    return (edge_x, mid_y, original_edges[0] - edge_x, edge_x), (mid_x, edge_y, original_edges[1] - edge_y, edge_y)


def viewport_areas(screen):
    return [a for a in screen.areas if a.type == 'VIEW_3D']


def _rect(area):
    return (area.x, area.y, area.width, area.height)


def _move(context, x, y, delta):
    """Move the screen edge at (x, y) by ``delta`` pixels (positive = right/up)."""
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
        stored = screen.get(SCREEN_KEY)
        if stored:
            index, edge_x, edge_y, right_column, top_row = (int(v) for v in stored)
            if index >= len(areas):
                del screen[SCREEN_KEY]
                return {'CANCELLED'}
            moves = restore_plan(_rect(areas[index]), (edge_x, edge_y), bool(right_column), bool(top_row))
            for (x, y, delta, _edge) in moves:
                _move(context, x, y, delta)
            for area in areas:
                area.spaces.active.show_region_header = True
            del screen[SCREEN_KEY]
            return {'FINISHED'}

        if context.area not in areas:
            return {'CANCELLED'}
        index = areas.index(context.area)
        rects = [_rect(a) for a in areas]
        moves = plan(rects, index)
        if moves is None:
            return {'CANCELLED'}
        (_vx, _vy, _dvx, edge_x), (_hx, _hy, _dhy, edge_y) = moves
        left = min(r[0] for r in rects)
        bottom = min(r[1] for r in rects)
        screen[SCREEN_KEY] = (index, edge_x, edge_y, int(rects[index][0] > left), int(rects[index][1] > bottom))
        # Hidden headers let the other viewports shrink below header size.
        for area in areas:
            if area != context.area:
                area.spaces.active.show_region_header = False
        for (x, y, delta, _edge) in moves:
            _move(context, x, y, delta)
        return {'FINISHED'}


def is_maximized(screen):
    return bool(screen and screen.get(SCREEN_KEY))


classes = (
    MXUI_OT_max_viewport_maximize,
)
