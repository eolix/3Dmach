# 0009: The Max window frame (strips, explorer, viewport labels, ViewCube, time slider, status line)

- Status: Proposed
- Date: 2026-10-16

## Context

`docs/design/max-ui-chrome.md` asks for Max's default window, every bar in the same place: a main toolbar
under the menu bar, the viewport layout tab bar and the Scene Explorer (with its filter bar) on the left, four
viewports with label menus, a ViewCube and a world axis tripod, the command panel on the right, the time
slider and track bar, and Max's two-row status line with the transform type-in, the animation controls and
the viewport navigation controls. (The ribbon was dropped on 2026-10-16: the maintainer wants the classic
modeling interface, without the animation / paint / populate presets.)

Python can't add editor types, can't size regions, and can't store data on areas. It can override the `draw`
of header classes, add panels to regions that draw panels, add gizmos and draw handlers, and change screens
with screen operators (which need event-loop ticks in between, see 0007).

## Decision

**Strips are rarely used editors, marked on the screen.** Horizontal strips (main toolbar; the explorer's
menu, find and footer rows; row 1 of the status line) are **Info editors** shrunk to their header
(`screen.area_split` never makes an area smaller than its header, so an extreme split factor gives a
header-high area). `INFO_HT_header.draw` is
overridden: in a marked area it draws the strip, elsewhere Blender's Info header. Vertical strips (viewport
layout tab bar, explorer filter bar) are narrow **Properties editors** (29 px, Blender's minimum area width)
without header and navigation bar, showing the **Collection tab pinned to the scene collection**: every
Blender collection panel polls `context.collection != context.scene.collection`, so the editor draws nothing
but our header-less panel `MXUI_PT_strip`, whose poll checks the mark. A strip that is not marked is an
ordinary editor.

**The mark** is an ID property on the screen: `screen["mx_chrome_areas"]` maps each role of the layout
(strips, explorer, viewports, timeline, command panel) to the area's index in `screen.areas`, its editor type
and its rectangle as fractions of the screen. Areas are saved in order, so the index survives save and load.
Each role is resolved to the area of the recorded type with the closest rectangle (the recorded index counting
as closer), within a limit, so the marks survive window resizes and most layout edits (splitting or closing
other areas); the result is cached per screen until an area moves or changes type. Data can't be written
while drawing, so marks are only written by the layout builder.

**Plain Max editors are recognised by workspace.** The Max Layout workspace carries
`workspace["mx_max_layout"]` (the name "Max Layout" is accepted for layouts built before the mark). Every 3D
viewport, Timeline and status bar shown with that workspace gets the Max drawing; the Outliner does when it
is the recorded explorer (or no explorer is recorded). This also covers the temporary screen of a maximised
viewport (Alt+W, `screen.screen_full_area`): the maximised viewport keeps its labels, the status bar its Max
row with the Maximize Viewport Toggle to come back. All of it only while `use_max_chrome` is on; the
overrides fall back to Blender's draw otherwise.

**Header overrides keep other add-ons' functions.** `_areas.override_draw` replaces only the class's own
`draw` in the list `Header.append` maintains (`_dyn_ui_initialize`), so functions appended by other add-ons
(e.g. `mx_keymap`'s selection-lock indicator in the 3D viewport header) keep running; unregistering puts the
original back. Overridden: `INFO_HT_header`, `OUTLINER_HT_header`, `VIEW3D_HT_header`, `DOPESHEET_HT_header`,
`STATUSBAR_HT_header`.

**Building**: the builder of 0007 (one screen operation per timer step) gains the strips. It splits the
original area first (it can be split repeatedly without a refresh) into status row, timeline, main toolbar, tab bar,
explorer column, command panel and the viewport grid, then splits the new areas (bottom viewports, explorer
rows, filter bar), retrying a split on the next steps while Blender doesn't know the new area's size yet.
Then it configures the editors and records the marks.

**Explorer**: the Outliner in View Layer mode. Its header becomes the column titles (Name (Sorted Ascending)
/ Frozen), Max's Frozen column is the Outliner's selectability column; in the Max Layout a message-bus
subscription on `Object.hide_select` turns toggling it into Freeze / Unfreeze (gray colour and flag, 0007).
The filter bar toggles the Outliner's object type filters; Display Frozen / Hidden map onto its single state
filter (`ALL` / `VISIBLE` / `SELECTABLE`). Sort by Hierarchy / by Layer switch collections off / on.

**Viewport labels** are the 3D viewport header redrawn as four text menus. The header overlaps the view
(region overlap, Blender's default) and the 3D viewport's theme header colour is made fully transparent while
the chrome is on (restored when it is switched off or the add-on disabled; Blender's default alpha is used if
the original was lost because preferences were saved meanwhile). The text info overlay and the navigation
gizmo are switched off in Max viewports.

**ViewCube**: a Python gizmo drawing in region pixels with `gpu`/`blf` and picking itself in `test_select`
(26 targets: faces, edges, corners, plus a home button); faces call `view3d.view_axis` (smooth view), edges
and corners animate the view rotation from a timer; dragging orbits. Its `test_select`, called by Blender on
every mouse move over a viewport, also records which viewport the mouse is over: the status line's navigation
controls act on that viewport.

**Bottom**: the Timeline's header is the time slider (a track drawn with proportional splits, scrubbed by a
modal operator mapping the mouse to frames), its main region the track bar. Row 1 of the status line is a
horizontal strip under it (Blender never shows the Timeline's footer); Blender's status bar draws row 2.
The navigation controls are modes as in Max (Zoom, Zoom All, Field of View: own drag handling; Pan, Orbit,
Zoom Region: Blender's operators started in the viewport clicked; right click ends the mode).

## Consequences

- Strips are real editors: they can be resized, closed or changed by the user like any area, and an Info or
  Properties editor the user opens elsewhere stays an ordinary editor.
- Fidelity limits: strips are header-high (26 px at scale 1), narrower than Max's toolbar; Max's two status
  rows are two different regions; the tab bar and filter bar are at least 29 px wide; the explorer's column
  titles don't follow the Outliner's column widths exactly.
- The transparent header is a theme change, so Blender workspaces also get transparent 3D viewport headers
  while the chrome is on.
- C changes that would make this cleaner (later, need approval): an area flag or name to mark strips, a
  Properties context without panels, header-less custom regions, region sizes from Python.
