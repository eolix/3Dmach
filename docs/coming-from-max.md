# Coming from Max

A short guide for Max users. 3Dmach is Blender underneath, with a Max-style layer on top: the keys,
menus and panels you know, mapped onto Blender's tools. When something here differs from Max, the
reference pages say how: [`keymap.md`](keymap.md), [`format/modifiers.md`](format/modifiers.md),
[`format/materials.md`](format/materials.md).

## The screen

New files open in the **Max Layout** workspace:

- **Scene Explorer** (left): Blender's Outliner. Layers are Blender *collections*; "New Layer from Selection"
  is in the quad menu and the Display panel.
- **Four viewports**: Top, Front, Left (wireframe) and Perspective (shaded). Alt+W maximises the viewport under
  the mouse, as in Max. Each viewport has Blender's header with its view, select, add and object menus.
- **Command panel** (right): Create, Modify, Hierarchy, Display and Utilities tabs.
- **Top bar**: Max-style Group, Create and Modifiers menus, and a compact main toolbar (select and transform
  tools, snaps, Select by Name, Material Editor, Render Setup, Render).

You can get back to Blender's own workspaces from the tabs along the top ("Layout", "Modeling", ...).
`screen.mx_max_layout` (or the button in the `mx_ui` add-on preferences) rebuilds the Max layout at any time.

## Moving around

| Do | Keys |
|---|---|
| Orbit (around the selection) | Alt + middle mouse |
| Pan | Middle mouse |
| Zoom | Wheel, or Ctrl+Alt + middle mouse |
| Zoom extents selected | Z |
| Top / Bottom / Front / Left / Perspective / User / Camera | T / B / F / L / P / U / C |
| Wireframe ↔ shaded / edged faces | F3 / F4 |

## Selecting and transforming

- Q / W / E / R pick the Select, Move, Rotate and Scale tools, and they **stay active** like in Max (Blender's
  G/R/S quick transforms are off in the viewport). Drag an object to select and move it in one go.
- Ctrl+click adds to the selection, Alt+click removes. H opens Select by Name. Space locks the selection.
- **Shift+drag** with a transform tool clones: the Clone Options dialog offers Copy, Instance (shared data) and
  Reference (an instance for now), and a number of copies.
- **Right-click** opens the quad menu: tools 1 and 2 on the left, display and transform on the right.

## Creating and modifying

- **Create > Geometry > Standard Primitives**: Box, Sphere, GeoSphere, Cylinder, Tube, Cone, Torus, Pyramid,
  Plane and a test shape. Click-drag the base in a viewport, move the mouse for the height, click to finish
  (right-click cancels). Parameters stay editable in the Modify tab until you convert the object.
- **Modify**: the name and wire-colour swatch, the **Modifier List** (Max names such as TurboSmooth, Shell,
  Symmetry, Bend, FFD), and the stack with the base object at the bottom. Click an entry to edit its
  parameters; the icon next to it turns it on or off; Collapse applies the stack.
- **Convert To: Editable Poly** (quad menu) turns a live primitive into a plain mesh.
- **Sub-object levels**: 1 vertex, 2 edge, 3 border, 4 polygon, 5 element (Blender's edit mode; border and
  element select boundary loops and linked geometry). 6, or the same number again, goes back to object level.

Blender's modifier stack is shown the Max way round (top of the list = top of the stack). Editing
sub-objects *between* modifiers, like an Edit Poly modifier in the middle of a stack, isn't available yet.

## Hierarchy, display, units

- **Hierarchy > Pivot**: Affect Pivot Only edits the object origin; Center to Object, Align to World and Reset
  are there too.
- **Display**: hide and unhide (by selection, by name, by category), **Freeze** (frozen objects turn gray and
  can't be selected), display as box, see-through, backface culling.
- **Utilities > Units Setup**: display units and the system unit scale, as in Max.
- **Utilities > Reset XForm**: applies the object transform.

## Opening .max files

File > Import > .max Scene, or drag a `.max` file into a viewport. The importer brings in the node hierarchy,
transforms, Editable Poly/Mesh geometry with material IDs, smoothing groups and UVs, instances (shared data),
primitives, modifier stacks (as editable Blender modifiers), materials and textures. Whatever it can't convert
yet becomes an empty or a placeholder, and the **Import Report** text block (Scripting workspace, or any Text
Editor) lists it. Please attach that report, and `maxdump` output, when reporting a file that doesn't import
well.

Scene units aren't read from the file yet: pick them in the import options if the scale looks wrong. Save your
work as `.blend`, or export to FBX, USD or OBJ (File > Export). Saving back to `.max` isn't supported.

## Materials and rendering

- M opens the material editor (Blender's Shader Editor); F10 opens render setup; Shift+Q renders.
- Imported Physical, Standard, V-Ray, Corona and Arnold materials become Principled BSDF node trees, which
  render in both Cycles and EEVEE. Textures are looked for where the scene says, next to the `.max` file, and
  in the folder you choose when importing.

## Getting back to plain Blender

Every Max-style piece is an add-on (Preferences > Add-ons: `mx_keymap`, `mx_ui`, `mx_primitives`,
`mx_io_max`), and the keymap can be switched back to "Blender" in Preferences > Keymap.
