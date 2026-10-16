# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Max's time slider and track bar: the Timeline in the Max Layout.

- The Timeline's header becomes the time slider, ``< [ 0 / 100 ] >``: a track the width of the editor with a
  thumb showing the current and last frame; clicking or dragging anywhere on it scrubs.
- Its main region is the track bar (Blender's timeline: frame ruler and keys of the selection).

Applies to Timelines in the Max Layout workspace with the chrome on; ``DOPESHEET_HT_header.draw`` falls back
to Blender's elsewhere. (Row 1 of the status line is a strip under the Timeline: Blender never shows the
Timeline's footer.)
"""

import bpy
from bpy.types import Operator

from . import _areas

# Thumb width and arrow buttons, in UI units.
THUMB_WIDTH = 4.5
ARROW_WIDTH = 1.0
# Horizontal padding of header layouts (pixels at UI scale 1).
_HEADER_PAD = 8.0


def is_max_timeline(context):
    space = getattr(context, "space_data", None)
    return (space is not None and space.type == 'DOPESHEET_EDITOR' and space.mode == 'TIMELINE'
            and _areas.max_context(context))


def frame_fraction(scene):
    start, end = scene.frame_start, scene.frame_end
    if end <= start:
        return 0.0
    return min(max((scene.frame_current - start) / (end - start), 0.0), 1.0)


def slider_text(scene):
    return "{:d} / {:d}".format(scene.frame_current, scene.frame_end)


def _track_geometry(region_width, ui_scale):
    """``(track start, track width, thumb width)`` in region pixels."""
    unit = 20.0 * ui_scale
    pad = _HEADER_PAD * ui_scale
    start = pad + ARROW_WIDTH * unit
    width = max(region_width - 2.0 * start, 1.0)
    thumb = min(THUMB_WIDTH * unit, width)
    return start, width, thumb


def frame_at(scene, x, region_width, ui_scale):
    """The frame for a click at region x-coordinate ``x``, the thumb's centre following the mouse."""
    start, width, thumb = _track_geometry(region_width, ui_scale)
    travel = max(width - thumb, 1.0)
    fraction = min(max((x - start - thumb / 2.0) / travel, 0.0), 1.0)
    return int(round(scene.frame_start + fraction * (scene.frame_end - scene.frame_start)))


class SCREEN_OT_mx_time_slider(Operator):
    """Drag to change the current frame"""
    bl_idname = "screen.mx_time_slider"
    bl_label = "Time Slider"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return context.scene is not None and context.region is not None

    def _set(self, context, event):
        scene = context.scene
        ui_scale = context.preferences.system.ui_scale or 1.0
        x = event.mouse_x - self._region_x
        frame = frame_at(scene, x, self._region_width, ui_scale)
        if frame != scene.frame_current:
            scene.frame_set(frame)

    def invoke(self, context, event):
        self._region_x = context.region.x
        self._region_width = context.region.width
        self._set(context, event)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'MOUSEMOVE':
            self._set(context, event)
        elif event.type in {'LEFTMOUSE', 'RIGHTMOUSE', 'ESC'} and event.value == 'RELEASE':
            return {'FINISHED'}
        return {'RUNNING_MODAL'}


def draw_time_slider(layout, context):
    scene = context.scene
    region = context.region
    ui_scale = context.preferences.system.ui_scale or 1.0
    unit = 20.0 * ui_scale
    region_width = region.width if region is not None else 800
    _start, width, thumb = _track_geometry(region_width, ui_scale)
    before = frame_fraction(scene) * (width - thumb)
    after = width - thumb - before

    # Header layouts don't stretch: every part gets its width in UI units.
    row = layout.row(align=True)
    sub = row.row(align=True)
    sub.ui_units_x = ARROW_WIDTH
    sub.operator("screen.frame_offset", text="", icon='TRIA_LEFT').delta = -1
    for part, text in ((before, None), (thumb, slider_text(scene)), (after, None)):
        units = part / unit
        if units < 0.05:
            continue
        sub = row.row(align=True)
        sub.ui_units_x = units
        if text is None:
            sub.emboss = 'NONE'
        sub.operator(SCREEN_OT_mx_time_slider.bl_idname, text=text or " ")
    sub = row.row(align=True)
    sub.ui_units_x = ARROW_WIDTH
    sub.operator("screen.frame_offset", text="", icon='TRIA_RIGHT').delta = 1


def configure_timeline(area):
    """Set up a Timeline as Max's time slider and track bar (no screen operators)."""
    area.type = 'DOPESHEET_EDITOR'
    area.ui_type = 'TIMELINE'
    space = area.spaces.active
    space.show_region_header = True
    space.show_region_channels = False
    space.show_region_ui = False
    space.show_seconds = False
    space.show_markers = True
    space.show_locked_time = False


def _draw_header(self, context):
    if not is_max_timeline(context):
        return False
    draw_time_slider(self.layout, context)
    return True


_overrides = []

classes = (
    SCREEN_OT_mx_time_slider,
)


def register():
    _overrides.append((bpy.types.DOPESHEET_HT_header,
                       _areas.override_draw(bpy.types.DOPESHEET_HT_header, _draw_header)))


def unregister():
    for cls, override in reversed(_overrides):
        _areas.restore_draw(cls, override)
    _overrides.clear()
