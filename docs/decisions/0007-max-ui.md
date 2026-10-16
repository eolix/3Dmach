# 0007: Max-style interface shell (`mx_ui`)

- Status: Proposed
- Date: 2026-10-16

## Context

ROADMAP Phase 1b asks for Max's interface on top of Blender, in Python only, working as a standalone add-on on
stock Blender 5.2 and as the fork's default: a quad menu, a command panel (Create / Modify / Hierarchy /
Display / Utilities), Freeze, a scene explorer, a theme, a four-viewport startup layout and a units dialog.
Blender's Python API sets the limits: there is no API for new editor types, new Properties editor tabs or
custom popup shapes, and screen layouts can only be changed through screen operators.

## Decision

**Command panel container: the Properties editor's Tool tab.** Max's command panel is one column for the whole
window, not one per viewport, so a 3D viewport sidebar (repeated in each of the four viewports) is the wrong
container. The Properties editor is a full-height editor, and its Tool tab draws the 3D viewport's sidebar
panels of category "Tool". The command panel is therefore one panel registered as `VIEW_3D` / `UI` /
`bl_category = "Tool"` with `HIDE_HEADER`; header-less panels are sorted before the others, so it sits at the
top of the tab. Its poll shows it only in Properties editors (optionally also in the viewport sidebar). Its
own tab row is an expanded enum (icons and text, icons only when narrow); rollouts are `layout.panel()`
sub-panels. In the Max Layout, the Properties editor is set up as a dedicated command panel: every other tab
hidden (`show_properties_*`), header hidden, navigation bar toggled off. Blender's own Tool-category panels
(Active Tool, Options, Workspace) still draw below the command panel; hiding them needs a small core change
(a dedicated context, or a flag on the editor), which can come with the fork. A preference restricts the
command panel to such dedicated editors instead of every Properties editor's Tool tab.

**Quad menu: a pie menu using only the diagonal slots.** `VIEW3D_MT_mx_quad` is a `Menu` drawn with
`layout.menu_pie()`; the four axis slots are left empty and each diagonal slot holds a boxed column titled
"tools 1", "display", "tools 2" or "transform", which gives Max's four quadrants around the cursor without a
custom popup. The contents are data (`quad_menu.QUADS`, per mode: object mode, mesh edit mode, other modes),
which tests check against the operator registry. `mx_keymap` binds right-click to it; for standalone use the
add-on can add the binding to the add-on keymap (preference, "Automatic" = only when the Max-Style keymap is
not active). Items use the `mx_keymap` operators when that add-on is enabled (sub-object levels, Clone) and
`object.mx_convert_to_editable_poly` from `mx_primitives` for live primitives.

**Modify tab.** The stack is drawn the Max way, base object at the bottom and the last modifier on top; the
selected entry is Blender's active modifier, or the base object. The Modifier List is a data table
(`modifier_map.MODIFIERS`) of Max names mapped onto Blender modifiers with Max-like defaults, plus setup
functions where a modifier is not enough (FFD creates a fitted lattice parented to the object, Noise a 3D
Clouds texture, Normal a small Geometry Nodes group flipping faces, Smooth Blender's "Smooth by Angle").
Entries without an equivalent are listed but report that they are not available yet (UVW Map, Unwrap UVW,
Slice, Cap Holes, ...). Parameters are drawn from a per-type property list, with a generic fallback; a live
primitive's base entry is drawn by `mx_primitives.draw_parameters()`. The same table can serve the `.max`
importer's modifier mapping (ROADMAP 2d).

**Freeze: `hide_select` + gray colour + a flag.** A frozen object gets `hide_select = True`, its object colour
replaced by gray (the original kept in the custom property `mx_frozen_color`) and the custom property
`mx_frozen`. Unfreeze only touches flagged objects, so objects made unselectable otherwise are left alone.
Everything is saved in the .blend and still works without the add-on. Gray display relies on the Max Layout's
viewports using object colours (`shading.color_type = 'OBJECT'`, also for wireframes), which is also how Max
shows wire colours; new objects get a random colour from a cheap `depsgraph_update_post` handler that only
looks at updated objects it has not seen before (by `session_uid`) and still having the default white.

**Layout: a workspace built with screen operators, step by step.** `screen.mx_max_layout` duplicates the
current workspace as "Max Layout", closes all areas but the largest and splits it into explorer (Outliner in
View Layer mode, selectability column visible) / Top / Front / Left / Perspective / command panel. Two Blender
behaviours shape the code: workspace changes are applied by the event loop, and `screen.area_split` refuses
to split an area whose size has not been computed yet, which is the case for a freshly split area until the
screen is refreshed. So the build is a generator doing one screen operation per step, run from a timer that
lets the event loop run in between. Viewport setup (`configure_*`) is separate from screen changes and is
tested headless, as are the first splits. A persistent `load_post` handler applies the layout to new unsaved
files (preference, default on; never in background mode). In the fork, the workspace can later be saved
into the startup file instead.

**Theme: generated XML preset.** `theme/palette.py` describes an original dark-gray palette as changes to
Blender's default theme (neutral grays lifted a little, a calmer accent blue, explicit viewport and edit-mode
colours: gray background with darker grid, white selection, blue vertices and red sub-object selection).
`theme/build_theme.py` writes the complete preset `mx_dark.xml`. It is applied only on request (preference
button or `preferences.mx_apply_theme`), or installed as a user theme preset.

**Units Setup** is an operator dialog mapping Max's display units (Metric / US Standard / Generic) and system
unit ("1 Unit = N <unit>") to `scene.unit_settings` (`system`, `length_unit`, `scale_length`), through plain
functions shared by the dialog and the tests. Unit lengths come from `mx_common.units`.

## Consequences

- Everything works on stock Blender; the fork can later improve two things in C: a Properties context
  without Blender's Tool panels, and a startup file containing the Max Layout.
- The command panel also shows in the Tool tab of ordinary Properties editors (by default), which makes it
  discoverable in standard layouts but adds it above Blender's tool settings.
- The pie-menu quad keeps Blender's pie behaviour (click-drag and release selects); Max's quads open on
  press and stay open. Revisit if users find it unnatural.
- Building the layout depends on screen operators behaving the same in future Blender versions; only part of
  it can be tested headless, so it needs a GUI check after Blender updates.
- Max features without Blender equivalents are visible but disabled or reported (Affect Object Only,
  UVW Map, group Open/Close, Grid and Tape helpers), so they are easy to find when implemented.
