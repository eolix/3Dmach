# Design: the full Max-style interface ("chrome")

- Status: Accepted (maintainer request, 2026-10-16: "all the sidebars, modifiers, tabs for objects, all exactly
  like Max. Even if not yet implemented, the buttons must all be there.")

The Max-style workspace reproduces the **layout and controls** of Max's default interface (Max 2017+ "Default"
workspace, dark UI). Every menu, toolbar button, tab, rollout and control is present in the same place. Where
the feature behind it exists in Blender or in our add-ons, the control uses it; otherwise it is a
**placeholder**: drawn normally, tooltip "not implemented yet", reports that when clicked
(`mx_ui.placeholder.placeholder()`, operator `mx_ui.placeholder`).

Rules (ROADMAP §3): replicate layout, names of commands and behaviour; **never** copy Max's icons, artwork or
strings beyond command names. Use Blender's built-in icons (closest match) or text. No Autodesk product names as
features (no "Arnold" menu, no "A360"); a menu named after a Max feature (e.g. "Civil View") stays a plain-text
placeholder menu.

All of it is switchable: add-on preference `use_max_chrome` (default on). When off, Blender's own headers come
back. Header overrides must call Blender's original `draw` when the preference is off or the area isn't a Max one.

## Screen map (top to bottom, left to right)

```
+----------------------------------------------------------------------------------------------------+
| Menu bar: File Edit Tools Group Views Create Modifiers Animation Graph Editors Rendering Civil View |
|           Customize Scripting Interactive Content Help                                             |
+----------------------------------------------------------------------------------------------------+
| Main toolbar (one row of buttons, see below)                                                        |
+---+-------------------+---------------------------------------------------+-------------------------+
| V | Scene Explorer    | Viewports (4, or 1 maximised)                     | Command panel           |
| i | menus: Select     |  label menus: [+] [Perspective] [Standard]        |  tabs: Create Modify    |
| e |  Display Edit     |   [Default Shading] top-left of each viewport     |  Hierarchy Motion       |
| w |  Customize        |  ViewCube top-right, world axis tripod            |  Display Utilities      |
| p | find field, icons |  bottom-left, grid                                |  (rest: see below)      |
| o | columns: Name     |                                                   |                         |
| r |  (Sorted Asc.),   |                                                   |                         |
| t |  Frozen           |                                                   |                         |
|   | left: filter bar  |                                                   |                         |
| t | bottom: explorer  |                                                   |                         |
| a |  selector         |                                                   |                         |
| b |  [Default] + sort |                                                   |                         |
|   |  by hierarchy /   |                                                   |                         |
|   |  by layer         |                                                   |                         |
+---+-------------------+---------------------------------------------------+-------------------------+
| Time slider:  < 0 / 100 >                                                                           |
| Track bar: frame ruler 0 ... 100                                                                     |
+----------------------------------------------------------------------------------------------------+
| MAXScript mini-listener | selection count / prompt | lock, abs/offset, X Y Z, Grid = | Add Time Tag |
| Auto Key, Set Key, [Selected], Key Filters | playback | frame field, time config | viewport nav ctrls |
+----------------------------------------------------------------------------------------------------+
```

## Inventory

### Menu bar
File, Edit, Tools, Group, Views, Create, Modifiers, Animation, Graph Editors, Rendering, Civil View,
Customize, Scripting, Interactive, Content, Help. Each with Max's items in Max's order (submenus included).
The modeling menus (File, Edit, Tools, Group, Views, Create, Modifiers, Rendering, Customize, Scripting, Help)
are complete; Animation, Graph Editors, Civil View, Interactive and Content only hold a few placeholder
entries (maintainer, 2026-10-16: the interface is classic modeling Max, no animation/paint/populate presets).
No "Sign In" and no workspace switcher: Blender's workspace tabs (and scene / view layer selectors) are hidden
while the chrome is on, the Max layout being the one workspace that matters.

Entries without a Blender feature are placeholders. The others map as follows (`chrome/menubar.py`, data
in `MENUS`):

- **File**: New > New All (empty scene), New from Template (Blender's templates); Reset (startup file); Open,
  Open Recent, Save, Save As, Save Copy As; View Image File (image editor window); Import > Import... (the .max
  importer, `import_scene.mx_max`), Merge (Append), Other Formats (Blender's importers); Export > Export...
  (Blender's exporters); Reference > XRef Objects/Scene (Link), Asset Tracking (external data); Exit.
  "Share View" and "Send To" (product names / online services) are left out.
- **Edit**: Undo, Redo, Delete (objects, or sub-objects in edit mode), Clone (`mx_keymap.clone`), Move /
  Rotate / Scale (tools), Select All / None / Invert / Similar / Instances, Select By > Color / Name
  (`mx_keymap.select_by_name`) / Layer, Selection Region (select tools, Window / Crossing state), Object
  Properties. Hold and Fetch are placeholders.
- **Tools**: Scene / Layer Explorer (Outliner window), Isolate Selection / End Isolate (local view in every
  viewport), Mirror (`object.mx_mirror`: axis, offset, No Clone / Copy / Instance), Align > Align / Quick
  Align, Rename Objects (batch rename), Grab Viewport (viewport render), Grids and Snaps > Grid and Snap
  Settings / Show Home Grid.
- **Group**: Group, Ungroup, Attach, Detach (`mx_ui.groups`); Open / Close / Explode and Assembly are
  placeholders.
- **Views**: Redraw All Views, Set Active Viewport (Perspective, Orthographic, Front ... Right, Camera; the
  `mx_keymap` view operators), Create Standard / Physical Camera From View (`object.mx_camera_from_view`),
  xView > Show Statistics, Show Transform Gizmo, Expert Mode (full-screen viewport without panels).
- **Create**: submenus mirroring the Command panel categories: Standard / Extended Primitives
  (`mesh.mx_primitive_add`, an entry becomes real as soon as the operator has that kind), Compound > Boolean,
  NURBS > CV Surface / CV Curve, Shapes (`curve.mx_shape_add`), Lights / Cameras / Helpers
  (`object.mx_create`), Systems > Bones; AEC, Particles, Patch Grids, Dynamics, SpaceWarps are placeholders.
- **Modifiers**: Max's categories (Selection, Patch/Spline Editing, Mesh Editing, Conversion, Animation, ...,
  Free Form Deformers, Parametric Deformers, Surface, ...), each entry looked up in `modifier_map` by name
  (`object.mx_modifier_add`); every Modifier List entry is reachable.
- **Rendering**: Render, Render Setup (render properties window), Rendered Frame Window, Exposure Control,
  Environment (world properties), Effects (compositor), Material Editor > Compact / Slate (shader editor
  window), Video Post (sequencer), View Image File, Print Size Assistant (output properties), Render Message
  Window (Info editor).
- **Customize**: Customize User Interface, Hotkey Editor, Configure Paths, Plug-in Manager, Preferences
  (Blender preferences at the matching section), Revert to Startup Layout (`screen.mx_max_layout`), Units
  Setup (`scene.mx_units_setup`).
- **Scripting**: New Script / Open Script (text editor window), Run Script (runs a .py file), MAXScript
  Listener (Python console window), Macro Recorder (Info editor: the operator log), Scripting Reference.
- **Help**: Welcome Screen (splash), Help (manual), Hotkey Map, Search Commands, Scripting Help, About.

Viewport commands run in the "active" viewport: the context's viewport, else the largest one (the Perspective
view wins a tie). Editors that Max opens as dialogs open as new windows.

### Main toolbar
Undo, Redo | Select and Link, Unlink Selection, Bind to Space Warp | Selection Filter dropdown (All, Geometry,
Shapes, Lights, Cameras, Helpers, Warps, Combos, Bone, IK Chain Object, Point, CAT Bone) | Select Object, Select
by Name, Selection Region flyout (Rectangular, Circular, Fence, Lasso, Paint), Window/Crossing | Select and Move,
Select and Rotate, Select and Scale flyout (Uniform, Non-uniform, Squash), Select and Place flyout (Place,
Rotate) | Reference Coordinate System dropdown (View, Screen, World, Parent, Local, Gimbal, Grid, Working, Local
Aligned, Pick) | Pivot flyout (Use Pivot Point Center, Use Selection Center, Use Transform Coordinate Center) |
Select and Manipulate | Keyboard Shortcut Override Toggle | Snaps Toggle flyout (2D, 2.5D, 3D), Angle Snap,
Percent Snap, Spinner Snap | Edit Named Selection Sets, Named Selection Sets dropdown ("Create Selection Set") |
Mirror, Align flyout (Align, Quick Align, Normal Align, Place Highlight, Align Camera, Align to View) | Toggle
Scene Explorer, Toggle Layer Explorer, Toggle Ribbon | Curve Editor, Schematic View, Material Editor flyout
(Compact, Slate) | Render Setup, Rendered Frame Window, Render flyout (Render Production, Render Iterative,
ActiveShade).

`chrome.main_toolbar.draw_main_toolbar(layout, context)` draws it into any header; the frame hosts it in a
header-only strip. Flyouts are `operator_menu_hold` buttons: click runs the variant shown, press and hold lists
the others; the variant shown is the active one (tool, pivot) or the last one picked. Active tools and enabled
snaps are drawn pressed. Mapping:

- Undo (hold: undo history), Redo; Select and Link / Unlink: parent to the active object / clear parent, both
  keeping transforms.
- Selection Filter and Window/Crossing: session state on `WindowManager.mx_ui` (`selection_filter`,
  `select_crossing`), for the selection operators to use.
- Select Object: the select tool of the current region (Rectangular → Box, Lasso → Lasso, Paint → Circle;
  Circular and Fence are placeholders); Select by Name: `mx_keymap.select_by_name`.
- Move, Rotate, Scale (Uniform and Non-uniform → Blender's Scale tool; Squash placeholder).
- Reference Coordinate System: `mx_ui.ref_coord_sys`, read from and written to the scene's transform
  orientation: View and Screen → View, World → Global, Parent, Local, Gimbal, Working → 3D Cursor, Local
  Aligned → Normal; a custom orientation shows as Pick; Grid and Pick can't be chosen yet.
- Pivot: Pivot Point Center → Individual Origins, Selection Center → Bounding Box Center, Transform
  Coordinate Center → 3D Cursor.
- Snaps (3D), Angle Snap, Percent Snap: independent toggles over Blender's snapping switch and its Move /
  Rotate / Scale "affect" options (`mx_ui.snap_toggle`); 2D / 2.5D and Spinner Snap are placeholders.
- Mirror: `object.mx_mirror`; Align: Align Objects (to the active object), Quick Align (selection to active).
- Curve Editor: Graph editor window; Material Editor: shader editor window (`mx_keymap.open_editor`); Render
  Setup: render properties window; Rendered Frame Window: render result; Render Production / Iterative:
  render; ActiveShade: toggles rendered shading in the active viewport.
- Placeholders: Bind to Space Warp, Select and Place, Select and Manipulate, Keyboard Shortcut Override,
  named selection sets, Normal Align and the other align variants, the explorer and ribbon toggles, Schematic
  View.

### Ribbon
Not built (maintainer, 2026-10-16: no Modeling/Freeform/Selection/Object Paint/Populate presets). The main
toolbar's Toggle Ribbon button is a placeholder.

### Scene Explorer (left)
Menus Select, Display, Edit, Customize; Find field; header icons (hierarchy/layer view, lock, filters). Columns
Name (Sorted Ascending) and Frozen. Vertical filter bar on its left: Select All, Select None, Select Invert,
Display Geometry, Shapes, Lights, Cameras, Helpers, Space Warps, Groups/Assemblies, Object XRefs, Bones,
Containers, Frozen, Hidden, Display All, Display None, Invert Display, Sync Selection, Lock Cell Editing.
Bottom: explorer selector dropdown ("Default") and Sort by Hierarchy / Sort by Layer buttons.

### Viewport layout tab bar (far left)
Vertical strip with layout presets (4 views, 1 view, 2/3 splits) and the add-tab arrow at the bottom.

### Viewports
Label menus top-left: `[+]` (Maximize Viewport, Active Viewport, Disable Viewport, Show Grids, ViewCube,
SteeringWheels, xView, Viewport Clipping, 2D Pan Zoom Mode, Safe Frames, Viewport Configuration...),
`[Perspective]` (Cameras, Lights, Perspective, Orthographic, Top, Bottom, Front, Back, Left, Right, Extended
Viewports, Show Safe Frames, Viewport Clipping, Undo/Redo View Change), `[Standard]` (High Quality, Standard,
Performance, DX Mode), `[Default Shading]` (Default Shading, Facets, Flat Color, Hidden Line, Clay, Wireframe
Override, Edged Faces, Bounding Box, Stylized, Lighting and Shadows, Materials...). ViewCube top-right (click a
face/edge/corner to change the view, home icon), world axis tripod bottom-left. Blender's header text overlay is
hidden in Max viewports.

### Command panel (right)
Tabs: Create, Modify, Hierarchy, **Motion**, Display, Utilities (icon row).

- **Create**: category icons Geometry, Shapes, Lights, Cameras, Helpers, Space Warps, Systems; per category a
  sub-category dropdown and an "Object Type" rollout (AutoGrid checkbox + buttons, two per row), then "Name and
  Color".
  - Geometry: Standard Primitives (Box, Cone, Sphere, GeoSphere, Cylinder, Tube, Torus, Pyramid, Teapot, Plane,
    TextPlus), Extended Primitives (Hedra, Torus Knot, ChamferBox, ChamferCyl, OilTank, Capsule, Spindle, L-Ext,
    Gengon, C-Ext, RingWave, Hose, Prism), Compound Objects (Morph, Scatter, Conform, Connect, BlobMesh,
    ShapeMerge, Terrain, Loft, Mesher, ProBoolean, ProCutter, Boolean), Particle Systems, Patch Grids, NURBS
    Surfaces, Doors, Windows, AEC Extended, Stairs, Point Cloud Objects, Dynamics Objects, Body Objects.
  - Shapes: Splines (Line, Rectangle, Circle, Ellipse, Arc, Donut, NGon, Star, Text, Helix, Egg, Section,
    Freehand), NURBS Curves, Compound Shapes, Extended Splines.
  - Lights: Photometric (Target Light, Free Light, Sun Positioner), Standard (Target Spot, Free Spot, Target
    Direct, Free Direct, Omni, Skylight).
  - Cameras: Standard (Physical, Target, Free).
  - Helpers: Standard (Dummy, Container, Crowd, Delegate, ExposeTm, Grid, Point, Point Cloud, Protractor, Tape),
    Atmospheric Apparatus, Camera Match, Manipulators, Particle Flow.
  - Space Warps: Forces, Deflectors, Geometric/Deformable, Modifier-Based.
  - Systems: Standard (Bones, Ring Array, Biped, Sunlight, Daylight).
- **Modify**: name + colour swatch, Modifier List, stack view, stack buttons (Pin Stack, Show End Result, Make
  Unique, Remove Modifier, Configure Modifier Sets), parameter rollouts of the selected entry.
- **Hierarchy**: Pivot / IK / Link Info buttons; Pivot: Move/Rotate/Scale (Affect Pivot Only, Affect Object
  Only, Affect Hierarchy Only), Alignment (Center to Object, Align to Object, Align to World), Pivot (Reset
  Pivot), Working Pivot, Adjust Transform, Skin Pose.
- **Motion**: Parameters / Motion Paths buttons; Assign Controller, PRS Parameters, Key Info.
- **Display**: Display Color, Hide by Category, Hide, Freeze, Display Properties, Link Display rollouts.
- **Utilities**: Utilities rollout (More..., Sets, Perspective Match, Collapse, Color Clipboard, Measure, Motion
  Capture, Reset XForm, MAXScript, Flight Studio, Configure Button Sets).

### Bottom
Time slider (`< 0 / 100 >`), track bar (frame ruler). MAXScript mini-listener (Python here: one-line input that
runs Python, and the last result), status line: selection count ("None Selected"), prompt line ("Click and drag
to select and move objects"), Isolate toggle, Selection Lock toggle, Absolute/Offset toggle, X/Y/Z fields (active
object position), Grid = value, Adaptive Degradation, Add Time Tag. Animation controls: Auto Key, Set Key,
[Selected] dropdown, Key Filters..., default tangents, Go to Start, Previous Frame, Play, Next Frame, Go to End,
Key Mode, current frame, Time Configuration. Viewport navigation controls: Zoom, Zoom All, Zoom Extents (flyout),
Zoom Extents All (flyout), Field of View / Zoom Region, Pan View, Orbit (flyout), Maximize Viewport Toggle.

## Building it in Blender (Python only)

- **Menu bar**: `TOPBAR_MT_editor_menus.draw` replaced while `use_max_chrome` is on; the workspace tabs (and the
  scene / view layer selectors) in the top bar are hidden (`TOPBAR_HT_upper_bar.draw_left/draw_right`).
- **Toolbar strip** (main toolbar): editors shrunk to their header (an area can be as short as its
  header), whose header draw is overridden only for areas that the Max layout marked as strips.
- **Vertical strips** (explorer filter bar, viewport layout tab bar): narrow editors whose main region draws a
  column of icon buttons.
- **Viewport labels**: the 3D viewport header becomes the label menus, drawn transparently over the viewport
  (region overlap), in Max viewports only.
- **ViewCube**: a Python gizmo group with a clickable cube.
- **Time slider / track bar**: a Timeline editor with its header redrawn as the time slider.
- **Status bar**: `STATUSBAR_HT_header.draw` replaced with the Max status line and controls.

C changes that would improve fidelity (later, need approval): hide Blender's built-in tool panels under the
command panel; area-level flags to mark strips instead of geometry tests; a real two-row status bar.
