# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
The "Max Layout" workspace: Max's default window, built from Blender editors.

    +------------------------------------------------------------------+
    | main toolbar (strip)                                             |
    +--+--------------+-------------+-------------+--------------------+
    |  | menus  (strip)|            |             |                    |
    |  | find   (strip)|    Top      |   Front     |                    |
    |T |F| Scene      |             |             |   Command panel    |
    |a |i| Explorer   +-------------+-------------+                    |
    |b |l| (Outliner) |    Left     | Perspective |                    |
    |s |t|            |             |             |                    |
    |  | footer (strip)|            |             |                    |
    +--+--------------+-------------+-------------+--------------------+
    | time slider (Timeline header) / track bar (Timeline)             |
    +------------------------------------------------------------------+
    | status row 1 (strip)                                             |
    +------------------------------------------------------------------+
      status row 2: Blender's status bar

Strips are editors whose drawing the chrome replaces, found again through marks this module records on the
screen and workspace (``chrome/_areas.py``, ``docs/decisions/0009-max-chrome-frame.md``).

Building it uses screen operators, which only behave in a real window, so the code is split in two:

- ``configure_*`` functions set up one space (shading, view, grid, tabs). They work on any space and are
  tested headless.
- ``build_steps`` closes every area but one (``screen.area_close``) and ``split_steps`` splits it into the
  areas above. They are generators doing one screen operation per step, because the event loop has to
  refresh the screen in between (see `split_steps`); `start_build` runs them from a timer. The first splits
  are tested headless; closing areas and splitting new areas need a real window.

``screen.mx_max_layout`` duplicates the current workspace and builds the layout once the window has switched
to the copy (workspace changes are also applied by the event loop). To rebuild it, delete the workspace and
run the operator again. With the add-on preference "Use Max Layout for New Files", a persistent ``load_post``
handler runs it for new unsaved files.
"""

import math

import bpy
from bpy.app.handlers import persistent
from bpy.types import Operator
from mathutils import Euler

from . import utils
from .chrome import _areas

WORKSPACE_NAME = _areas.WORKSPACE_NAME

# Widths as fractions of the window width (Max's default proportions).
EXPLORER_WIDTH = 0.21        # Scene Explorer with its filter bar.
COMMAND_PANEL_WIDTH = 0.16
# Height of the Timeline (time slider header and track bar), pixels at UI scale 1.
TIMELINE_HEIGHT = 80.0
# Split factors giving the smallest area Blender allows: a header-high or 29 pixel wide strip.
_STRIP_LOW = 0.001
_STRIP_HIGH = 0.999
# A split of a new area waits this many steps for the event loop to compute the area's size.
_SPLIT_ATTEMPTS = 50

# role → (view axis or None for perspective, shading type).
VIEWPORTS = {
    'TOP': ('TOP', 'WIREFRAME'),
    'FRONT': ('FRONT', 'WIREFRAME'),
    'LEFT': ('LEFT', 'WIREFRAME'),
    'PERSPECTIVE': (None, 'SOLID'),
}

# View rotations (as `RegionView3D.view_rotation`) of the orthographic views, Max's Left = Blender's Left.
_AXIS_ROTATIONS = {
    'TOP': Euler((0.0, 0.0, 0.0)),
    'FRONT': Euler((math.radians(90.0), 0.0, 0.0)),
    'LEFT': Euler((math.radians(90.0), 0.0, math.radians(-90.0))),
}
# Looking from the front left, above, like Max's default Perspective view.
_PERSPECTIVE_ROTATION = Euler((math.radians(65.0), 0.0, math.radians(-45.0)))
_VIEW_DISTANCE = 18.0


# -----------------------------------------------------------------------------
# Space configuration (no screen changes, testable headless)

def configure_view3d(space, role):
    """Set up a 3D viewport space as one of the four Max viewports."""
    axis, shading_type = VIEWPORTS[role]
    shading = space.shading
    shading.type = shading_type
    # Max draws objects in their object (wire) colour.
    shading.color_type = 'OBJECT'
    shading.wireframe_color_type = 'OBJECT'
    shading.light = 'STUDIO'
    shading.show_xray_wireframe = False

    overlay = space.overlay
    overlay.show_floor = True
    overlay.show_ortho_grid = True
    overlay.show_axis_x = True
    overlay.show_axis_y = True
    overlay.show_axis_z = False
    overlay.grid_scale = 1.0
    overlay.grid_subdivisions = 10

    space.show_region_header = True
    space.show_region_toolbar = False
    space.show_region_tool_header = False
    space.show_region_ui = False
    # Max chrome: label menus instead of the text overlay, the ViewCube instead of the navigation gizmo.
    from .chrome import viewport
    viewport.configure_chrome_view3d(space, utils.use_max_chrome())

    rv3d = space.region_3d
    rv3d.view_location = (0.0, 0.0, 0.0)
    rv3d.view_distance = _VIEW_DISTANCE
    if axis is None:
        rv3d.view_perspective = 'PERSP'
        rv3d.view_rotation = _PERSPECTIVE_ROTATION.to_quaternion()
        space.lens = 45.0
    else:
        rv3d.view_rotation = _AXIS_ROTATIONS[axis].to_quaternion()
        rv3d.view_perspective = 'ORTHO'
        # Snaps the view to the axis view, so the viewport shows "Top"/"Front"/... and its grid.
        rv3d.is_orthographic_side_view = True


def configure_outliner(space):
    """The Scene Explorer: View Layer mode with the selectable (freeze) column visible."""
    from .chrome import explorer
    explorer.configure_explorer(space)


def configure_timeline(area):
    from .chrome import timeslider
    timeslider.configure_timeline(area)


def configure_command_panel(space):
    from .command_panel import setup_command_panel_space
    setup_command_panel_space(space)
    space.outliner_sync = 'NEVER'


# -----------------------------------------------------------------------------
# Screen building (screen operators)

def _split(window, screen, area, direction, factor):
    """Split ``area``; returns the new area (screen operators append it to ``screen.areas``)."""
    before = set(screen.areas)
    with bpy.context.temp_override(window=window, screen=screen, area=area):
        result = bpy.ops.screen.area_split(direction=direction, factor=factor)
    if 'FINISHED' not in result:
        raise RuntimeError("Could not split the {:s} area".format(area.type))
    new_areas = [a for a in screen.areas if a not in before]
    if len(new_areas) != 1:
        raise RuntimeError("Unexpected result of an area split")
    return new_areas[0]


def _split_when_ready(window, screen, area, direction, factor):
    """
    Generator splitting ``area`` (``factor`` is a number or a function of the area), retrying on the next steps
    while Blender refuses because the area's size isn't known yet. Returns the new area.
    """
    for attempt in range(_SPLIT_ATTEMPTS):
        try:
            return _split(window, screen, area, direction, factor(area) if callable(factor) else factor)
        except RuntimeError:
            if attempt == _SPLIT_ATTEMPTS - 1:
                raise
            yield


def _ui_scale():
    return bpy.context.preferences.system.ui_scale or 1.0


def split_steps(window, screen, area):
    """
    Generator splitting ``area`` into the Max Layout's areas, yielding after each split; its return value
    (``StopIteration.value``) is ``{role: area}`` with the roles 'STATUS_ROW', 'TIMELINE', 'MAIN_TOOLBAR', 'TAB_BAR',
    'EXPLORER', 'EXPLORER_MENUS', 'EXPLORER_FIND', 'EXPLORER_FOOTER', 'FILTER_BAR', 'COMMAND_PANEL' and the
    `VIEWPORTS` keys.

    ``area_split`` puts the new area on the left/bottom for factors <= 0.5, on the right/top otherwise, and
    never makes an area smaller than its header (height) or 29 pixels (width): strips use the extreme factors.
    It also refuses to split an area whose size (``winx``/``winy``) is not known yet, which is the case for an
    area created by a split until the screen has been refreshed by the event loop: the caller must let the
    event loop run between steps (see `start_build`); splits of new areas are retried on the next steps.
    The original area is split first (it can be split repeatedly without a refresh).
    """
    width = max(window.width, 1)
    area.type = 'VIEW_3D'

    def timeline_factor(a):
        return min(TIMELINE_HEIGHT * _ui_scale() / max(a.height, 1), 0.5)

    def explorer_factor(a):
        return min(EXPLORER_WIDTH * width / max(a.width, 1), 0.5)

    def command_panel_factor(a):
        return max(1.0 - COMMAND_PANEL_WIDTH * width / max(a.width, 1), 0.5)

    status_row = yield from _split_when_ready(window, screen, area, 'HORIZONTAL', _STRIP_LOW)
    status_row.type = _areas.STRIP_TYPES['STATUS_ROW']
    yield
    timeline = yield from _split_when_ready(window, screen, area, 'HORIZONTAL', timeline_factor)
    timeline.type = 'DOPESHEET_EDITOR'
    yield
    toolbar = yield from _split_when_ready(window, screen, area, 'HORIZONTAL', _STRIP_HIGH)
    toolbar.type = _areas.STRIP_TYPES['MAIN_TOOLBAR']
    yield
    tab_bar = yield from _split_when_ready(window, screen, area, 'VERTICAL', _STRIP_LOW)
    tab_bar.type = _areas.STRIP_TYPES['TAB_BAR']
    yield
    explorer = yield from _split_when_ready(window, screen, area, 'VERTICAL', explorer_factor)
    explorer.type = 'OUTLINER'
    yield
    command_panel = yield from _split_when_ready(window, screen, area, 'VERTICAL', command_panel_factor)
    command_panel.type = 'PROPERTIES'
    yield
    bottom = yield from _split_when_ready(window, screen, area, 'HORIZONTAL', 0.5)
    yield
    top_left = yield from _split_when_ready(window, screen, area, 'VERTICAL', 0.5)
    yield
    # From here on, areas created by the splits above are split.
    bottom_left = yield from _split_when_ready(window, screen, bottom, 'VERTICAL', 0.5)
    yield
    menus = yield from _split_when_ready(window, screen, explorer, 'HORIZONTAL', _STRIP_HIGH)
    menus.type = _areas.STRIP_TYPES['EXPLORER_MENUS']
    yield
    find = yield from _split_when_ready(window, screen, explorer, 'HORIZONTAL', _STRIP_HIGH)
    find.type = _areas.STRIP_TYPES['EXPLORER_FIND']
    yield
    footer = yield from _split_when_ready(window, screen, explorer, 'HORIZONTAL', _STRIP_LOW)
    footer.type = _areas.STRIP_TYPES['EXPLORER_FOOTER']
    yield
    filter_bar = yield from _split_when_ready(window, screen, explorer, 'VERTICAL', _STRIP_LOW)
    filter_bar.type = _areas.STRIP_TYPES['FILTER_BAR']
    return {
        'STATUS_ROW': status_row,
        'TIMELINE': timeline,
        'MAIN_TOOLBAR': toolbar,
        'TAB_BAR': tab_bar,
        'EXPLORER': explorer,
        'EXPLORER_MENUS': menus,
        'EXPLORER_FIND': find,
        'EXPLORER_FOOTER': footer,
        'FILTER_BAR': filter_bar,
        'COMMAND_PANEL': command_panel,
        'TOP': top_left,
        'FRONT': area,
        'LEFT': bottom_left,
        'PERSPECTIVE': bottom,
    }


def _toggle_navigation_bar(window, screen, area):
    # The navigation bar has no RNA property; toggle the region (it is visible in a new editor).
    if bpy.app.background:
        return
    with bpy.context.temp_override(window=window, screen=screen, area=area):
        bpy.ops.screen.region_toggle(region_type='NAVIGATION_BAR')


def configure_areas(window, screen, roles):
    """Set up the editors of a split screen (``roles`` as returned by `split_steps`) and record the roles."""
    for role in VIEWPORTS:
        area = roles[role]
        area.type = 'VIEW_3D'
        configure_view3d(area.spaces.active, role)
    roles['EXPLORER'].type = 'OUTLINER'
    configure_outliner(roles['EXPLORER'].spaces.active)
    panel_area = roles['COMMAND_PANEL']
    space = panel_area.spaces.active
    configure_command_panel(space)
    space.show_region_header = False
    _toggle_navigation_bar(window, screen, panel_area)
    if 'TIMELINE' in roles:
        configure_timeline(roles['TIMELINE'])
    for kind in _areas.STRIP_TYPES:
        area = roles.get(kind)
        if area is None:
            continue
        _areas.setup_strip(area, kind)
        if area.type == 'PROPERTIES':
            _toggle_navigation_bar(window, screen, area)
    screen.show_statusbar = True
    _areas.mark_areas(screen, roles)
    if window.screen == screen and window.workspace is not None:
        _areas.mark_workspace(window.workspace)


def build_steps(window, screen):
    """
    Generator turning ``screen`` (shown in ``window``) into the Max Layout, one screen operation per step:
    close every area but the largest, split it, configure the editors.
    """
    keep = max(screen.areas, key=lambda a: a.width * a.height)
    for _attempt in range(len(screen.areas) * 2):
        others = [a for a in screen.areas if a != keep]
        if not others:
            break
        with bpy.context.temp_override(window=window, screen=screen, area=others[0]):
            bpy.ops.screen.area_close()
        yield
    roles = yield from split_steps(window, screen, keep)
    yield
    configure_areas(window, screen, roles)
    yield
    zoom_extents_all(window, screen, roles)
    return roles


def zoom_extents_all(window, screen, roles):
    """Frame the whole scene in every viewport, as Max's viewports do on a new layout."""
    if bpy.app.background:
        return
    if window.screen != screen or screen.is_temporary:
        # E.g. a viewport was maximised (Alt+W) while the layout was being built: leave the views alone.
        return
    for role in VIEWPORTS:
        area = roles[role]
        region = next((r for r in area.regions if r.type == 'WINDOW'), None)
        if region is None:
            continue
        with bpy.context.temp_override(window=window, screen=screen, area=area, region=region):
            if bpy.ops.view3d.view_all.poll():
                bpy.ops.view3d.view_all(center=False)


# -----------------------------------------------------------------------------
# Workspace and operator

_BUILD_STEP_INTERVAL = 0.02
_WAIT_ATTEMPTS = 50


def _activate(window, workspace):
    if window.workspace != workspace:
        window.workspace = workspace


def _find_window(pointer):
    wm = bpy.context.window_manager
    return next((w for w in wm.windows if w.as_pointer() == pointer), None)


def start_build(window, workspace):
    """
    Build the Max Layout in ``workspace`` from timers: wait for ``window`` to show the workspace (workspace
    changes are applied by the event loop), then run `build_steps`, letting the event loop refresh the screen
    between steps.
    """
    window_pointer = window.as_pointer()
    workspace_name = workspace.name
    state = {"steps": None, "wait": _WAIT_ATTEMPTS}

    def tick():
        window = _find_window(window_pointer)
        workspace = bpy.data.workspaces.get(workspace_name)
        if window is None or workspace is None:
            return None
        if state["steps"] is None:
            if window.workspace != workspace:
                state["wait"] -= 1
                return _BUILD_STEP_INTERVAL if state["wait"] > 0 else None
            state["steps"] = build_steps(window, window.screen)
        try:
            next(state["steps"])
        except StopIteration:
            return None
        except (RuntimeError, ReferenceError, TypeError) as ex:
            # TypeError: e.g. a context override refused because the window shows a temporary screen.
            print("Max Layout: could not build the layout:", ex)
            return None
        return _BUILD_STEP_INTERVAL

    bpy.app.timers.register(tick, first_interval=0.0)


def create_workspace(context, window):
    """Duplicate the window's workspace as the (not yet built) Max Layout workspace."""
    before = set(bpy.data.workspaces)
    with context.temp_override(window=window):
        bpy.ops.workspace.duplicate()
    new = [ws for ws in bpy.data.workspaces if ws not in before]
    if len(new) != 1:
        raise RuntimeError("Could not create the {:s} workspace".format(WORKSPACE_NAME))
    workspace = new[0]
    workspace.name = WORKSPACE_NAME
    workspace.object_mode = 'OBJECT'
    _areas.mark_workspace(workspace)
    return workspace


class SCREEN_OT_mx_max_layout(Operator):
    """Switch to the Max Layout workspace (four viewports, command panel, scene explorer), creating it if needed"""
    bl_idname = "screen.mx_max_layout"
    bl_label = "Max Layout"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return context.window is not None

    def execute(self, context):
        window = context.window
        workspace = bpy.data.workspaces.get(WORKSPACE_NAME)
        if workspace is not None:
            _activate(window, workspace)
            return {'FINISHED'}

        try:
            workspace = create_workspace(context, window)
        except RuntimeError as ex:
            self.report({'ERROR'}, str(ex))
            return {'CANCELLED'}
        _activate(window, workspace)
        if not bpy.app.background:
            start_build(window, workspace)
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# New files

def _apply_to_new_file():
    wm = bpy.context.window_manager
    if not wm or not wm.windows:
        return None
    window = wm.windows[0]
    with bpy.context.temp_override(window=window):
        bpy.ops.screen.mx_max_layout()
    return None


@persistent
def _on_load_post(*_args):
    prefs = utils.get_prefs()
    if prefs is None or not prefs.use_max_layout_for_new_files:
        return
    if bpy.app.background or bpy.data.filepath:
        return
    bpy.app.timers.register(_apply_to_new_file, first_interval=0.0)


classes = (
    SCREEN_OT_mx_max_layout,
)


def register():
    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)


def unregister():
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
