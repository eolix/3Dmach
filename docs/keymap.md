# Max-Style keymap reference

The "Max-Style" keymap of the `mx_keymap` add-on (ROADMAP Phase 1a). On stock Blender 5.2: enable
"Max-Style Keymap" in Preferences > Add-ons, then click "Activate Max-Style Keymap" in its preferences, or pick
"Max-Style" in Preferences > Keymap. Activating it also sets Max-like navigation preferences (see the end of this
page) unless "Max-Like Navigation" is unchecked in the add-on preferences. Pick "Blender" in Preferences > Keymap to
go back. How it works: [`decisions/0005-keymap.md`](decisions/0005-keymap.md).

Keys apply in the 3D viewport, in object mode and in the edit modes, unless noted. Other editors keep Blender's
keys. On macOS, Ctrl is Cmd for the same keys as in Blender's own keymap.

## Navigation

| Max action | Key | In this app |
|---|---|---|
| Orbit | Alt + middle mouse drag | Orbits around the selection (navigation preferences) |
| Pan | Middle mouse drag | Pans |
| Zoom | Mouse wheel | Zooms towards the mouse position (navigation preferences) |
| Zoom | Ctrl + Alt + middle mouse drag | Zooms |
| Zoom in / out | `[` / `]` | Zooms one step |
| Zoom region | Ctrl + W | Drag a rectangle to zoom to |
| Zoom extents selected | Z | Frames the selection; frames everything when nothing is selected (object and edit mode) |
| Zoom extents | Ctrl + Alt + Z | Frames everything |
| Maximize viewport toggle | Alt + W | Maximizes the viewport under the mouse, or restores the layout (see notes) |

## Views

| Max action | Key | In this app |
|---|---|---|
| Top view | T | Orthographic top view |
| Bottom view | B | Orthographic bottom view |
| Front view | F | Orthographic front view |
| Left view | L | Orthographic left view |
| Perspective view | P | Perspective at the current angle (from a camera view: at the camera's viewpoint) |
| User (orthographic) view | U | Orthographic at the current angle (from a camera view: at the camera's viewpoint) |
| Camera view | C | Views through the selected camera, otherwise the scene camera; warns when there is none |

## Tools and sub-object levels

| Max action | Key | In this app |
|---|---|---|
| Select object | Q | Selection tool. Pressing Q again cycles box, circle and lasso |
| Select and move | W | Move tool (stays active) |
| Select and rotate | E | Rotate tool (stays active) |
| Select and scale | R | Scale tool (stays active). Pressing R again cycles scale / scale cage |
| Vertex level | 1 | Edit mode, vertex selection |
| Edge level | 2 | Edit mode, edge selection |
| Border level | 3 | Edit mode, edge selection limited to open borders; the selection grows to whole border loops and a click selects a whole border loop |
| Polygon level | 4 | Edit mode, face selection |
| Element level | 5 | Edit mode, face selection; the selection grows to connected elements and a click selects a whole element |
| Top level | 6, or the active level's key again | Object mode |

The tools follow Max's persistent-tool model: the tool stays active until another one is chosen. With the Move,
Rotate or Scale tool active:

- dragging on an object (or vertex/edge/face in edit mode) selects it and transforms it; dragging on an object that
  is already selected transforms the whole selection;
- dragging on empty space draws a selection rectangle (Ctrl adds, Alt removes);
- dragging the gizmo transforms the selection along its axes or planes, as in Blender.

For non-mesh objects, 1-5 enter edit mode (and the same key or 6 leaves it).

## Display

| Max action | Key | In this app |
|---|---|---|
| Wireframe / shaded toggle | F3 | Toggles wireframe and the previous shading mode |
| Edged faces toggle | F4 | Toggles the wireframe overlay on shaded objects |
| Show home grid | G | Toggles the floor grid (and the grid of orthographic views) |
| Transform gizmo toggle | X | Shows or hides the active tool's gizmo |
| See-through | Alt + X | Toggles X-ray for the viewport (Max: for the selected objects only) |
| Isolate selection | Alt + Q | Toggles local view on the selection |

## Selection

| Max action | Key | In this app |
|---|---|---|
| Select | Click | Selects the object or element under the mouse; clicking empty space deselects all |
| Add to selection | Ctrl + click, Ctrl + drag | Adds |
| Remove from selection | Alt + click, Alt + drag | Removes |
| Select all / none / invert | Ctrl + A / Ctrl + D / Ctrl + I | Object, pose and edit modes |
| Select by name | H | "Select From Scene" dialog: searchable list (`*` and `?` wildcards), several objects can be checked. Object mode |
| Select parent / child | Page Up / Page Down | Objects and bones |
| Select edge loop | Double-click an edge | Ctrl + double-click adds the loop, Alt + double-click removes it |
| Lock selection toggle | Space | While locked, clicks in the viewport don't change the selection and dragging anywhere transforms the selection. "Selection Locked" shows in the viewport header |

## Cloning

| Max action | Key | In this app |
|---|---|---|
| Clone by dragging | Shift + drag with the Move, Rotate or Scale tool (on an object or on the gizmo) | The originals stay in place and an instance follows the mouse. On release the "Clone Options" dialog asks for Copy / Instance / Reference, Number of Copies and Name. Each further copy gets the drag applied once more (cumulative offset), like Max |
| Clone | Ctrl + V | "Clone Options" for a clone in place |

- **Copy** duplicates the object and its geometry (materials stay shared, as in Max).
- **Instance** shares the geometry with the original (Blender linked duplicate).
- **Reference** currently behaves like Instance; real Max references (shared base, own modifiers on top) need core
  work (ROADMAP Phase 3).
- New objects are named Max-style ("Box001" gives "Box002", "Box003", ...). The last copy ends up selected.
- In edit mode, Shift + drag duplicates the dragged elements inside the mesh ("Clone To Element"), without a dialog.

## Editing

| Max action | Key | In this app |
|---|---|---|
| Delete | Delete | Deletes the selected objects without confirmation. In mesh edit mode, deletes the selected vertices, edges or faces (by selection mode), no menu |
| Remove (edit poly) | Backspace | Dissolves the selected vertices / edges / faces |
| Quad menu | Right click | Opens the quad menu (`VIEW3D_MT_mx_quad`, from the `mx_ui` add-on) in object and mesh edit mode. Without `mx_ui` nothing opens; Blender's context menu stays on the Menu key |
| Undo / redo | Ctrl + Z / Ctrl + Y | Ctrl + Shift + Z also redoes, as in Blender |

## Rendering and editors

| Max action | Key | In this app |
|---|---|---|
| Material editor | M | Opens a Shader Editor in a new window; M again closes it |
| Render setup | F10 | Opens the Render properties in a new window; F10 again closes it. Anywhere in the app |
| Quick render | Shift + Q | Renders (through the viewport's camera). Anywhere |
| Render last | F9 | Renders again, same as Shift + Q. Anywhere |
| Play animation | `/` | Plays / stops animation (Space plays animation outside the 3D viewport) |

## Files

| Max action | Key | In this app |
|---|---|---|
| Open | Ctrl + O | Opens a `.max` scene into a fresh scene (or a `.blend` file). File > Import > .max merges instead |
| Save | Ctrl + S | Saves to the scene's `.max` file with the `.max` writer, plus a `<name>.max.3dmach.blend` backup that Open uses when it's newer; without the writer, saves the native scene |
| Save As | Ctrl + Shift + S | Same, under a new name; choose `.blend` for a native 3Dmach / Blender scene |

## Blender keys that are kept

Tab (edit mode), Ctrl + Tab (mode pie), N (sidebar), F1 (manual), F2 (rename), F11 / F12 (render view / render),
Ctrl + S / Ctrl + O / Ctrl + N (files), Ctrl + Space (maximize area), Shift + A (add menu), Shift + S (snap pie),
Shift + Z (wireframe), Alt + Z (X-ray), numpad views, Home (view all), Ctrl + C (copy objects), Alt + H (reveal),
Shift + H (hide unselected), K (knife), I (inset / insert keyframe), Shift + click (toggle selection) and every
key-map of the other editors.

## Blender keys that changed in the 3D viewport

| Blender | Was | Now |
|---|---|---|
| G / R / S | Move / rotate / scale immediately | W / E / R tools (or drag with them) |
| A, Alt + A, double A | Select all / none | Ctrl + A / Ctrl + D |
| X, Delete | Delete (with menu or confirmation) | Delete (no confirmation) |
| H | Hide | Use the quad menu (Shift + H and Alt + H are kept) |
| M | Move to collection / merge | Object and mesh menus |
| T | Toolbar toggle | View menu |
| Z | Shading pie | Header shading buttons (F3 / F4 / Shift + Z / Alt + Z) |
| B, C, W | Box / circle select, cycle select tools | Q |
| 1 / 2 / 3 (edit mode) | Vertex / edge / face mode | 1 / 2 / 4 (Shift and Ctrl variants are kept) |
| E, F, P, L, U (mesh edit) | Extrude, fill, separate, select linked, UV menu | Mesh menus and the quad menu (level 5 picks linked elements) |
| Alt + click, Shift + Alt + click | Edge loop / ring select | Double-click (Shift + Alt + click toggle is kept) |
| Ctrl + click | Shortest path / object pick | Add to selection |
| Alt + click (object mode) | Choose among overlapping objects | Remove from selection; Shift + Alt + click still lists them |
| Middle mouse | Orbit | Pan (Alt + middle mouse orbits) |
| Alt + middle mouse drag / click | Snap to axis views / center on mouse | Orbit |
| `/` | Local view | Alt + Q |
| `[` / `]` | Select parent / child | Zoom; Page Up / Page Down select parent / child |
| Ctrl + A (object mode) | Apply menu | Object > Apply |
| Ctrl + V | Paste objects | Clone; paste is Ctrl + Shift + V |
| Alt + Q | Transfer mode | Isolate |
| F3 | Menu search | Wireframe toggle; search stays on F3 in other editors and in Edit > Menu Search |
| F9 | Adjust last operation | Render; the panel in the viewport's bottom-left corner still adjusts the last operation |
| Space | Play animation | Lock selection (viewport only; `/` plays) |
| Shift while transforming | Precision | Nothing (Shift is for cloning) |

## Notes and differences from Max

- **Alt + W** maximizes a viewport when the layout uses separate viewports. In Blender's single-area quad view
  (Ctrl + Alt + Q) it leaves quad view keeping the view under the mouse; pressing it again rebuilds Blender's quad
  view with its default Front / Top / Right views.
- **S** turns snapping on for moves, **A** for rotations (Blender's snapping with "Affect" Move / Rotate). Angle
  snapping uses the rotation increment (5 degrees by default) and needs the "Increment" snap target, which is the
  default.
- **Sub-object levels** are a Phase-1 approximation: Blender keeps one selection per mesh, not one per level, and
  switching levels converts it.
- **Undo after a Shift-drag clone** takes two steps: the first removes the copies made by the dialog and shows the
  instance created during the drag, the second removes that.
- **Emulate 3 Button Mouse** with Alt (Preferences > Input) makes Alt + click / drag act as the middle mouse button,
  so Alt can't remove from the selection with that option on.
- **Navigation preferences** set on activation: orbit around selection, zoom to mouse position, auto perspective
  off (orbiting an orthographic view keeps it orthographic, like Max's "Orthographic" user view), turntable orbit.
  "Restore Previous Navigation Preferences" in the add-on preferences puts back the values from before the first
  activation.
