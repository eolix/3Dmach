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

Max primitives don't cache meshes in the corpus (`docs/format/overview.md` §6.4), but two other sources check the
topology: objects that were primitives and were converted to Editable Poly / Mesh (their vertex and face order
is Max's generator order, as long as they weren't edited), and the input bounding boxes that modifier contexts
store for the primitive below them (odd segment counts tell where rings start). Each generator creates vertices
and faces in one commented order so it can be adjusted. Verified on the corpus:

- **Ring start.** Spheres, Tubes and Tori start their rings at **+Y** (`geometry.RING_START`): 11 Spheres with 14,
  18 and 19 segments, Tubes with 18 and 87 sides and a 41-segment Torus have the context boxes of +Y rings and not
  of +X ones; converted Spheres have their first ring vertex on +Y. Cylinders (32) and Cones (79) start at +X, as
  do converted Cylinders and a converted Capsule. Slice angles are counted from the ring start (unverified).
- **Sphere layout** (a 10-segment Sphere converted to Editable Poly, exact match): top pole, rings from the top
  down counter-clockwise from +Y, bottom pole; faces: top fan `(pole, r[k], r[k+1])`, bands
  `(upper[k], lower[k], lower[k+1], upper[k+1])`, bottom fan `(pole, r[k+1], r[k])`; one smoothing group.
- **Box layout** (converted 1x1x1 and 1x5x1 Boxes): vertices bottom grid then top grid, rows along +Y, each along
  +X; faces bottom `(0, 2, 3, 1)`, top `(4, 5, 7, 6)`, front, right, back, left; Max's 1-based material IDs top 1,
  bottom 2, left 3, right 4, front 5, back 6 and smoothing groups 2, 3, 4, 5, 6, 7 (bottom to left, masks
  2 to 64).
- **Capsule layout** (an 8-sided Capsule converted to Editable Mesh, exact match of all 66 vertices): top pole,
  rings from the top counter-clockwise from +X, `sides // 2` bands per hemisphere, the cylinder's height segments,
  bottom pole; faces like the Sphere's but the bottom fan as `(r[k], pole, r[k+1])`; all faces material ID 1,
  smoothing group 3.
- **OilTank** (a converted 14-sided OilTank, deformed, so only the structure): pole first, 4 bands per cap
  (we use `max(2, ceil(sides / 4))`), caps in smoothing group 3 and the cylinder in group 4, all material ID 1.
- Counts known from Max: default Sphere 482 vertices / 960 triangles; default GeoSphere 162 vertices / 320 faces.
- A converted Cylinder shows Editable Poly caps as n-gons without a centre vertex (as we build them).

| Kind | Generated | Unsure about |
|---|---|---|
| Box | Grid per side; 6 material IDs and 6 smoothing groups, as above. | Face order inside the bottom grid for more than one width segment. |
| Sphere | `segments` around, `segments // 2` bands, triangle fans at the poles. Hemisphere cuts from the bottom (0.5 = equator) and closes with a fan around a centre vertex; Chop drops rings, Squash keeps them. Slice faces are one n-gon each (meridian + axis). | Odd segment counts; how Max closes the hemisphere and slice faces (centre vertices? extra axis vertices?). |
| GeoSphere | Each base face subdivided `segments`² times and projected (class I geodesic), a vertex at the top pole. Hemisphere keeps the upper half (clipping faces that cross the equator for odd counts and Tetra) and closes it with one n-gon. | Max's exact vertex spacing on the sphere, base orientation, whether Max's hemisphere is closed. UVs are a spherical projection; on faces across the seam U runs past 1. |
| Cylinder / Cone | Rings per height segment; 1 cap segment = one n-gon cap, more = quad rings around a triangle fan. Radius 0 collapses a cap to an apex. Slice faces are grids (cap segments × height segments) with vertices on the axis. Material IDs: top 1, bottom 2, sides 3, slice 4. | Material ID numbers; slice cap layout; the corpus has Cones with a negative Radius 2 (Max accepts it, we clamp to 0). |
| Tube | Outer and inner walls, annular caps with cap segments, slice grids. IDs: top 1, bottom 2, outer 3, inner 4, slice 5. | Material IDs. |
| Torus | `segments` rings of `sides` vertices; rotation offsets and twist turns the cross-section (the twist shows a seam unless it is a multiple of 360°); slice ends closed by n-gons. Smooth All / Sides (bands around the ring) / None / Segments (ring facets). | How Max closes slice ends; whether the twist seam is handled differently. |
| Pyramid | Base grid; four sides with rows per height segment, triangle fans at the apex; base and each side smoothed separately. | Material IDs (all 0 here). |
| Plane | Grid, one-sided. Render multipliers (scale, density) are not implemented. | — |
| ChamferBox | Flat sides as the Box (same IDs), edge fillets of `fillet_segments` × the box's segments, each corner an octant made of rows of quads closed by a triangle (1 fillet segment: the classic 24-vertex, 26-face chamfered cube). Points are the box shrunk by the fillet plus the fillet radius, so all fillet vertices are on the rounding. Fillets material ID 7; Smooth puts everything in one group. Fillet clamped to half the smallest size. | Vertex and face order; corner layout; fillet material ID; Max's default fillet segments (we use 3). |
| ChamferCyl | Surface of revolution: cap rings (1 cap segment = n-gon), fillet arcs, side rings. IDs as the Cylinder (fillets with the sides). Fillet clamped to the radius and half the height. | Vertex order (we use the Capsule's top-down layout), IDs, slice faces (one polygon each). |
| Capsule | Verified layout (above). Overall: the height includes the caps (verified: context boxes of 7 corpus capsules) and is at least the diameter; Centers: the height of the cylinder. | Bands per hemisphere for other side counts (`sides // 2` from one 8-sided object). |
| OilTank | Caps are squashed hemispheres of Cap Height (≤ radius); Blend bevels the cap / cylinder edge with one band smoothed into both. | Cap shape (sphere segment or ellipse; the converted one was deformed); bands per cap; Blend's shape and segments. |
| Spindle | Cone caps with Cap Segments; Blend as OilTank. | All of the layout. |
| Gengon | Extruded regular polygon (first corner on +X), fillets of `fillet_segments` on the vertical edges (the largest fillet gives the inscribed circle), side segments; n-gon caps. IDs top 1, bottom 2, sides 3. | Corner start, IDs, smoothing. |
| Prism | Triangle with sides 1-3 (side 1 along +X from the pivot corner, the apex at +Y), side segments, n-gon caps; IDs top 1, bottom 2, sides 3-5. An impossible side 3 is clamped to a thin triangle. | Pivot position, IDs. |
| L-Ext / C-Ext | Quad-gridded caps (corner squares × width segments, legs × their segments), walls per straight side with IDs 3, 4, ...; pivot at the centre of the bounding rectangle; L: front leg along X at -Y, side leg along Y at -X; C opens towards +X. Negative lengths mirror (the corpus has a C-Ext with a negative Side Length). | Pivot, orientation, cap subdivision, IDs. |
| Torus Knot | (P, Q) torus knot `((2 + cos qt) cos pt, (2 + cos qt) sin pt, -sin qt) * radius / 3` or a circle; Warp modulates the radius; the cross-section (eccentricity, twist, lumps) follows rotation-minimising frames corrected to close. Smooth as the Torus. | Max's exact knot formula and radius definition, frame orientation, lump shape. Mapping offset / tiling are not implemented. |
| Hedra | Wythoff construction on the base solid (tetrahedron, octahedron, icosahedron; Star2 the dodecahedron): P = Q = 0 the base, P = 1 its dual, Q = 1 the rectified solid; faces around base faces / vertices / edges are the P / Q / R faces (IDs 1, 2, 3). Axis scaling and the Center modes make faces fans around a (pushed) centre; the stars raise the base faces' centres. | Which Max family member P / Q give, which solid is the base, the stars' exact shape. |
| RingWave, Hose | Not implemented (placeholders in the command panel). | — |

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
| ChamferBox | Drag the base, move for height, click, move up or down for the fillet, click. |
| ChamferCyl, Gengon | Drag radius, move for height, click, move for the fillet, click. |
| Capsule | Drag radius, move for height, click. |
| OilTank, Spindle | Drag radius, move for height, click, move for the cap height, click. |
| L-Ext, C-Ext | Drag the bounding rectangle, move for height, click, move for the leg widths, click. |
| Prism | Drag a rectangle holding an isosceles triangle (side 1 along X from the first corner), move for height, click. |
| Torus Knot | Drag radius, move for the cross-section radius, click. |
| Hedra | Drag radius. |

The height follows the point on the vertical line through the release point that is closest to the mouse ray;
when the view looks straight down that line (a box in the top view) the vertical mouse movement is used instead.
The fillet, cap height and width steps use the distance moved along that line since the previous click (or the
vertical mouse movement). Grid snapping applies when snapping is on with Increment or Grid. A click without a drag creates nothing.
Right-click or Esc cancels the object being created. Navigation events pass through. Unlike Max, creation stops
after one object (Max stays in creation mode until right-click); a persistent mode can come with the command panel.

## Consequences

- The `.max` importer can rebuild primitives with `create_primitive_object()` and share meshes between instances.
  When a primitive carries a cached mesh, comparing it with `generate()` is the way to fix our topology
  (see the table above), and a corpus test should do that automatically.
- Editing a live primitive in Edit Mode works, but the next parameter change replaces the edits (the panel says
  so). Max avoids this by requiring a conversion or an Edit Poly modifier first.
- Python regeneration may be too slow for extreme segment counts; revisit if that matters in practice.
- The `.max` decoder (`maxfile.objects.primitives`) hands ChamferBox, ChamferCyl, Capsule and Torus Knot
  parameters to the builder under the same names. Most of their IDs are UI-order guesses (only sizes and sides are
  verified by context boxes); OilTank (1 corpus object) and C-Ext (688 objects, none under a modifier) have no
  decoder entries yet, and Gengon, Spindle, Prism, L-Ext and Hedra no corpus objects. Their IDs need converted or
  modified objects of known parameters.
- Parameter names are part of the file format now (they are stored as ID properties); renaming one needs a
  versioning step.
