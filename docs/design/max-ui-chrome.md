# Design: the full Max-style interface ("chrome")

- Status: Accepted (maintainer request, 2026-10-16: "all the sidebars, modifiers, tabs for objects, all exactly
  like Max. Even if not yet implemented, the buttons must all be there.")
- Scope (maintainer, 2026-10-16): the classic **modeling** interface. No ribbon and no workspace presets for
  animation, object paint, freeform or populate. The animation controls at the bottom are simple buttons
  (real where Blender has them); the effort goes into modeling: viewport labels, ViewCube, Scene Explorer,
  transform type-in and viewport navigation controls.

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
|           Customize Scripting Interactive Content Help            [Sign In]  Workspaces: [Default]  |
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
Right side: "Sign In" (placeholder), "Workspaces:" dropdown (Blender workspaces; "Default" = the Max layout).

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

### Ribbon
Dropped (see Scope): the Max Layout has no ribbon strip.

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

- **Menu bar**: `TOPBAR_MT_editor_menus.draw` replaced while `use_max_chrome` is on; the workspace tabs in the
  top bar are hidden in favour of the "Workspaces:" dropdown.
- **Toolbar strips** (main toolbar; Scene Explorer menu, find and footer rows; status row 1): Info editors
  shrunk to their header (an area can be as short as its header), whose header draw is overridden only for
  areas that the Max layout marked as strips (`screen["mx_chrome_areas"]`, see
  `docs/decisions/0009-max-chrome-frame.md`).
- **Vertical strips** (explorer filter bar, viewport layout tab bar): narrow Properties editors showing the
  Collection tab pinned to the scene collection (Blender draws no panels there), with one header-less panel
  drawing a column of icon buttons.
- **Viewport labels**: the 3D viewport header becomes the label menus, drawn transparently over the viewport
  (region overlap), in Max viewports only.
- **ViewCube**: a Python gizmo group with a clickable cube.
- **Time slider / track bar**: a Timeline editor with its header redrawn as the time slider, its main region
  as the track bar. Row 1 of the status line is a toolbar strip under it.
- **Status bar**: `STATUSBAR_HT_header.draw` replaced with row 2 of the Max status line and controls.

C changes that would improve fidelity (later, need approval): hide Blender's built-in tool panels under the
command panel; area-level flags to mark strips instead of geometry tests; a real two-row status bar.
