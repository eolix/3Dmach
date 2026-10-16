# 0006: Live primitives as mesh parameters plus Python regeneration

- Status: Proposed
- Date: 2026-10-16

## Context

ROADMAP Phase 1c asks for Max-style primitives that keep their parameters (length, segments, slice, ...) after
creation, editable in the Modify panel until the user converts them to Editable Poly, and created by click-drag
in the viewport. Phase 2c will rebuild primitives found in `.max` files as the same live primitives, so the
geometry has to be reproducible from the stored parameters, ideally with Max's topology. The roadmap names two
options: Geometry Nodes groups, or a property group plus regeneration.

## Decision

**Parameters on the mesh, geometry regenerated in Python.**

- The parameters are a `PropertyGroup` on the **Mesh** datablock, `Mesh.mx_primitive` (`kind` plus every
  parameter, one property per name shared by the kinds that use it). Objects that share the mesh (instances,
  Alt+D duplicates, imported Max instances) share the primitive, as in Max.
- Each property's `update` callback regenerates the mesh. Generated data: vertices, polygons (quads and n-gons
  where Max shows them in Editable Poly), per-corner UVs ("Generate Mapping Coords"), material indices, and
  smoothing written as `sharp_face` / `sharp_edge` attributes. Modifiers on the objects evaluate on top and keep
  working. Undo is Blender's normal memfile undo: the mesh and its parameters are restored together.
- "Convert to Editable Poly" (`object.mx_convert_to_editable_poly`) unsets the property group and keeps the mesh.
  It converts every object sharing the mesh, and it does not collapse modifiers (Max's Convert To does both
  steps in one; collapsing can follow later as an option).
- With the add-on disabled the meshes are ordinary meshes; the parameters stay in the file as ID properties and
  become live again when it is re-enabled.
- The generators live in `mx_primitives/geometry.py`, which does not import `bpy`: `generate(kind, **params)`
  returns a `MeshData` (vertices, faces, uvs, Max smoothing-group masks, 0-based material IDs). The importer uses
  it directly and through `mx_primitives.create_primitive_object()`; plain `pytest` tests it.
  Material IDs and smoothing groups are kept in Max's terms (IDs per face, 32-bit groups) and converted to Blender
  terms only when written, so `.max` data and generated data use the same representation.
- Interactive creation is a modal operator (`mesh.mx_primitive_add`, INVOKE). The plane and drag math are in the
  bpy-free `mx_primitives/creation.py` (`construction_plane`, `CreationSession`), tested without a viewport.

### Why not Geometry Nodes

- Topology control: matching Max's vertex and face order (needed to apply Max's stored UVs, Edit Poly data or
  vertex selections on top of a rebuilt primitive) is straightforward in Python and awkward in a node tree.
- One implementation serves the add-on, the importer and the tests. A node group cannot be run by `pytest`, and
  the importer would still need Python to read the result.
- Parameters on a node modifier sit on the object, so instances would not share them, and the "base object"
  would look like a modifier in the stack rather than the object itself.
- Cost: Python regeneration is slower for very dense primitives (hundreds of thousands of faces), and updates
  happen on the main thread. Fine for typical segment counts; ROADMAP Phase 3 keeps "native live primitives" as
  the fallback if it proves too slow.

### Parameters and conventions

- Max conventions: Z up; Box, Cylinder, Cone, Tube and Pyramid have their pivot at the base centre; Sphere,
  GeoSphere and Torus at the centre (unless Base To Pivot); Plane at the centre. Box length runs along Y, width
  along X, height along Z; Pyramid width X, depth Y; Plane length Y, width X.
- Angles are radians in the API (degrees in the UI, as Blender always does).
- Defaults for non-interactive creation are Max's segment counts (Box 1/1/1, Sphere 32, GeoSphere 4 icosa,
  Cylinder 5/1/18, Tube 5/1/18, Cone 5/1/24, Torus 24/12, Plane 4/4) with metre-scale sizes.
- Values are clamped per kind (e.g. a sphere has at least 4 segments) and the clamped value is written back so the
  UI shows what is used.
- Enumeration values are stored as numbers in `.blend` files: never renumber them, only append.
- The Max teapot is replaced by an original **Test Shape**: a lathed pot body and lid, a swept handle and a tapering
  swept spout, all closed shells with material IDs 0–3, with proportions made up for this project. It shares no
  data with the Utah teapot.

### Topology: what follows Max and what is unverified

Nothing here was checked against Max-generated meshes yet: the vertex and face order can only be verified once
corpus files with cached primitive meshes exist (`docs/format/overview.md` §6.3). Each generator creates
vertices and faces in one commented order so it can be adjusted. Counts that are known from Max are tested
(default Sphere: 482 vertices, 960 triangles; default GeoSphere: 162 vertices, 320 faces).

| Kind | Generated | Unsure about |
|---|---|---|
| Box | Grid per side; 6 material IDs and 6 smoothing groups. | Which ID goes to which side (we use top 1, bottom 2, right 3, left 4, front 5, back 6 in Max's 1-based numbers); vertex order. |
| Sphere | `segments` around, `segments // 2` bands, triangle fans at the poles. Hemisphere cuts from the bottom (0.5 = equator) and closes with a fan around a centre vertex; Chop drops rings, Squash keeps them. Slice faces are one n-gon each (meridian + axis). | Odd segment counts; how Max closes the hemisphere and slice faces (centre vertices? extra axis vertices?); ring start angle. |
| GeoSphere | Each base face subdivided `segments`² times and projected (class I geodesic), a vertex at the top pole. Hemisphere keeps the upper half (clipping faces that cross the equator for odd counts and Tetra) and closes it with one n-gon. | Max's exact vertex spacing on the sphere, base orientation, whether Max's hemisphere is closed. UVs are a spherical projection; on faces across the seam U runs past 1. |
| Cylinder / Cone | Rings per height segment; 1 cap segment = one n-gon cap, more = quad rings around a triangle fan. Radius 0 collapses a cap to an apex. Slice faces are grids (cap segments × height segments) with vertices on the axis. Material IDs: top 1, bottom 2, sides 3, slice 4. | Material ID numbers; whether the 1-segment cap has a hidden centre vertex in Max; slice cap layout. |
| Tube | Outer and inner walls, annular caps with cap segments, slice grids. IDs: top 1, bottom 2, outer 3, inner 4, slice 5. | Material IDs. |
| Torus | `segments` rings of `sides` vertices; rotation offsets and twist turns the cross-section (the twist shows a seam unless it is a multiple of 360°); slice ends closed by n-gons. Smooth All / Sides (bands around the ring) / None / Segments (ring facets). | Ring start angle; how Max closes slice ends; whether the twist seam is handled differently. |
| Pyramid | Base grid; four sides with rows per height segment, triangle fans at the apex; base and each side smoothed separately. | Material IDs (all 0 here). |
| Plane | Grid, one-sided. Render multipliers (scale, density) are not implemented. | — |

The kept part of a slice runs counter-clockwise from Slice From to Slice To; equal angles give the whole object,
as in Max. The direction is from memory of Max's behaviour and needs a check against a real file.

### Interactive creation

INVOKE starts a modal operator that waits for a click-drag in any 3D viewport region (quad views included),
regardless of where it was invoked from. The construction plane is the ground plane in perspective and user views
and in the top view; in axis-aligned orthographic views (bottom, front, back, left, right) it is the plane through
the origin facing the viewer, and the object is created in that plane's orientation, so its height points at the
viewer, as in Max. Steps:

| Kind | Steps |
|---|---|
| Box, Pyramid | Drag base corner to corner (Ctrl: square), move for height, click. |
| Plane | Drag corner to corner. |
| Sphere, GeoSphere, Test Shape | Drag from the centre. |
| Cylinder | Drag radius, move for height, click. |
| Cone | Drag radius 1, move for height, click, move for radius 2, click. |
| Tube | Drag radius 1, move for radius 2, click, move for height, click. |
| Torus | Drag radius 1, move for radius 2, click. |

The height follows the point on the vertical line through the release point that is closest to the mouse ray;
when the view looks straight down that line (a box in the top view) the vertical mouse movement is used instead.
Grid snapping applies when snapping is on with Increment or Grid. A click without a drag creates nothing.
Right-click or Esc cancels the object being created. Navigation events pass through. Unlike Max, creation stops
after one object (Max stays in creation mode until right-click); a persistent mode can come with the command panel.

## Consequences

- The `.max` importer can rebuild primitives with `create_primitive_object()` and share meshes between instances.
  When a primitive carries a cached mesh, comparing it with `generate()` is the way to fix our topology
  (see the table above), and a corpus test should do that automatically.
- Editing a live primitive in Edit Mode works, but the next parameter change replaces the edits (the panel says
  so). Max avoids this by requiring a conversion or an Edit Poly modifier first.
- Python regeneration may be too slow for extreme segment counts; revisit if that matters in practice.
- Parameter names are part of the file format now (they are stored as ID properties); renaming one needs a
  versioning step.
