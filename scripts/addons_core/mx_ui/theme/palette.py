# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
The "Max-Style Dark" palette, as changes to Blender's default theme.

It is an original palette inspired by the look of Max's dark interface (no assets or values copied):
a lighter, neutral mid-dark gray for editors and widgets, a calmer blue accent, viewports in solid gray with
darker grid lines, and red sub-object selection (selected vertices, edges and faces) with blue vertices.

Two steps, applied to a theme that has just been reset to Blender's defaults:

1. `lift_gray`: every near-neutral UI colour gets a little lighter (outside the 3D viewport's object and
   edit-mode colours, which step 2 sets), so every editor stays coherent without listing each colour.
2. `OVERRIDES`: explicit values, by RNA path relative to the theme.

``build_theme.py`` turns the result into ``mx_dark.xml``.
"""

# How much lighter neutral grays become: v' = v + LIFT * (1 - v).
LIFT = 0.10
# Colours whose channels differ by less than this count as neutral gray.
NEUTRAL_TOLERANCE = 0.04

# Blender's default accent blue, and the accent that replaces it.
DEFAULT_ACCENT = (0.278, 0.447, 0.702)
ACCENT = (0.290, 0.525, 0.780)
ACCENT_TOLERANCE = 0.02

# Paths (prefixes, relative to the theme) whose colours are left to `OVERRIDES` or kept as they are.
LIFT_EXCLUDE = (
    "bone_color_sets",
    "collection_color",
    "strip_color",
    "common.anim",
    "common.curves",
)
# 3D viewport colours that are lifted (the space colours); the rest of `view_3d` is not.
VIEW3D_LIFT_PREFIX = "view_3d.space"

OVERRIDES = {
    # Viewport background and grid.
    "view_3d.space.gradients.background_type": 'SINGLE_COLOR',
    "view_3d.space.gradients.high_gradient": (0.278, 0.278, 0.278),
    "view_3d.space.gradients.gradient": (0.212, 0.212, 0.212),
    "view_3d.grid": (0.176, 0.176, 0.176, 0.65),
    "view_3d.grid_major": (0.137, 0.137, 0.137, 0.9),
    "view_3d.grid_axis_brightness": 0.55,
    "view_3d.view_overlay": (0.86, 0.86, 0.86),

    # Objects: selection is white, as in Max.
    "view_3d.object_selected": (0.86, 0.86, 0.86),
    "view_3d.object_active": (1.0, 1.0, 1.0),
    "view_3d.wire": (0.05, 0.05, 0.05),
    "view_3d.wire_edit": (0.05, 0.05, 0.05),
    "view_3d.camera": (0.35, 0.55, 0.85),
    "view_3d.empty": (0.25, 0.65, 0.3),
    "view_3d.light": (0.95, 0.85, 0.35, 0.35),
    "view_3d.transform": (1.0, 1.0, 1.0),

    # Sub-object selection: blue vertices, red selection.
    "view_3d.vertex": (0.12, 0.28, 0.95),
    "view_3d.vertex_select": (1.0, 0.12, 0.10),
    "view_3d.vertex_size": 4,
    "view_3d.edge_select": (1.0, 0.18, 0.14),
    "view_3d.edge_mode_select": (1.0, 0.30, 0.22),
    "view_3d.face": (1.0, 1.0, 1.0, 0.03),
    "view_3d.face_select": (1.0, 0.12, 0.10, 0.22),
    "view_3d.face_mode_select": (1.0, 0.20, 0.15, 0.30),
    "view_3d.editmesh_active": (1.0, 1.0, 1.0, 0.35),
    "view_3d.facedot_size": 4,

    # Widgets: a little contrast between fields and buttons, as Max's flat dark controls.
    "user_interface.wcol_regular.inner": (0.380, 0.380, 0.380, 1.0),
    "user_interface.wcol_tool.inner": (0.380, 0.380, 0.380, 1.0),
    "user_interface.wcol_text.inner": (0.165, 0.165, 0.165, 1.0),
    "user_interface.wcol_num.inner": (0.200, 0.200, 0.200, 1.0),
    "user_interface.wcol_numslider.inner": (0.200, 0.200, 0.200, 1.0),
    "user_interface.wcol_tab.inner_sel": (0.302, 0.302, 0.302, 1.0),
    "user_interface.panel_header": (0.330, 0.330, 0.330, 1.0),
    "user_interface.panel_back": (0.300, 0.300, 0.300, 1.0),
    "user_interface.editor_border": (0.120, 0.120, 0.120),
    "user_interface.widget_text_cursor": (0.55, 0.75, 1.0),
}


def is_neutral(color):
    rgb = color[:3]
    return max(rgb) - min(rgb) < NEUTRAL_TOLERANCE


def lift_gray(color):
    """Lighten a neutral gray, keeping alpha."""
    rgb = tuple(v + LIFT * (1.0 - v) for v in color[:3])
    return rgb + tuple(color[3:])


def is_default_accent(color):
    return all(abs(a - b) < ACCENT_TOLERANCE for a, b in zip(color[:3], DEFAULT_ACCENT))


def adjust_color(path, color):
    """The palette's version of the default ``color`` at ``path`` (before `OVERRIDES`)."""
    if path.startswith(LIFT_EXCLUDE):
        return color
    if path.startswith("view_3d.") and not path.startswith(VIEW3D_LIFT_PREFIX):
        return color
    if is_default_accent(color):
        return ACCENT + tuple(color[3:])
    if is_neutral(color):
        return lift_gray(color)
    return color
