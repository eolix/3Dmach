# Modifier stacks

How the importer converts Max modifier stacks (`scripts/addons_core/mx_io_max/modifiers/convert.py`, shapes in
`shapes.py`). Each supported modifier becomes a Blender modifier named like the Max modifier (its stack name when
the user renamed it), in the same order, so the stack stays editable. Class names are matched after replacing
spaces by underscores, so the names stored in the file ("UVW Map", "Turn to Poly") find their converter.

The stack is imported up to the first modifier that would change the shape but can't be converted; it is listed
in the import report. Modifiers that don't change the shape (selection and attribute modifiers) are left out
without stopping the stack. "Collapse stack on import" applies everything instead. Approximations are listed in
the report once per kind, with the objects they apply to.

Each converter gets the modifier's context from the derived object (`maxfile` `ModifierRef`): the context matrix,
the input bounding box, the per-node data chunk (`0x2500` > `0x2512`) and the gizmo (the modifier's
Position/Rotation/Scale controller). A gizmo in object space is `inverse(context matrix) @ gizmo transform`;
when it isn't at the object origin it becomes an empty parented to the object (Symmetry / Mirror mirror object,
Simple Deform origin, Screw axis object).

| Max modifier | Blender | Differences |
|---|---|---|
| TurboSmooth, MeshSmooth, OpenSubdiv | Subdivision Surface (iterations, render iterations when set) | MeshSmooth classic / quad output imported as Catmull-Clark |
| Shell | Solidify (inner + outer amount → thickness and offset, even thickness) | No segments |
| Symmetry | Mirror with bisect (slice along mirror), flip (kept side), weld threshold, gizmo as mirror object | |
| Mirror | Mirror (copy on) or a "Mirror XYZ" node group scaling by −1 and flipping faces (copy off); offset and gizmo as mirror object | Mirror without copy about a moved gizmo uses the object origin |
| Chamfer | Bevel on edges above the minimum angle | Max Chamfer has many more options |
| Bend / Twist / Taper | Simple Deform (angle / amount, axis); gizmo and centre as the origin object; limits (lower / upper, relative to the centre) as Simple Deform limits, fractions of the input bounding box along the axis | Bend direction, Twist bias and Taper curve not applied |
| Noise | Displace with a Clouds texture in local coordinates; a single-axis strength displaces along that axis | Several strength axes: one strength along the normals |
| Push | Displace along normals | |
| Relax | Smooth | |
| Optimize, ProOptimizer | Decimate (planar dissolve with the face threshold) | |
| Lattice | Wireframe | |
| Normal (flip) | Geometry Nodes "Flip Normals" | |
| Turn to Poly / Mesh / Patch | nothing needed | |
| UVW Map | UVs generated on import into the channel's UV map (planar, box, cylindrical with cap, spherical; shrink wrap as spherical), gizmo, length / width / height, tiles and flips | Not live; face / XYZ mapping not converted; skipped above modifiers that change the topology |
| Unwrap UVW | The UVs it stores per node (`0x2512`: `0x0860` texture vertices, `0x0870` faces), applied when they fit the mesh corner for corner | Skipped above modifiers that change the topology (e.g. on top of MeshSmooth) |
| Mesh Select, Poly Select, Vol. Select, Attribute Holder, Arnold Properties, MapScaler | left out, the stack goes on | Modifiers above a selection apply to the whole object |
| Edit Poly, Edit Mesh | not converted: they store their edits, not their result | The stack is imported up to them and reported |
| FFD, Skin, Wave, … | not yet | Reported; the stack stops there |

## UVW Map gizmo

On the corpus, a freshly fitted UVW Map gizmo sits at the centre of the input's bounding box with length, width
and height equal to its extents (all 190 maps with an identity context matrix), and the gizmo's rotation
controller holds a half turn about Z. The importer takes that half turn as the gizmo's rest orientation, so a
default planar map runs U along +X and V along +Y. The alignment (`axis`) picks the projection plane: Z → (X, Y),
Y → (X, Z), X → (Y, Z), with V along `length`. Guess: the seam of cylindrical / spherical maps and the
orientation of the box sides are taken from Max's documented behaviour, not verified against stored UVs.

## Shapes at the bottom of a stack

Shape modifiers sit directly above a shape base (`docs/format/overview.md` §6.5).

| Max | Blender | Notes |
|---|---|---|
| Edit Spline | its stored result (`0x2512` > `0x1000` > `0x1040`, a Bezier shape read by `maxfile.objects.shapes.read_bezier_shape`: 34 of 34 corpus contexts) replaces the splines below | |
| Extrude | a mesh built on import: amount along the shape's Z, segments, start / end caps (with holes, nesting by even-odd), material IDs 1 start cap / 2 end cap / 3 sides, sides smooth with sharp edges at corner knots | Not live (the modifiers above it are) |
| Lathe | the profile as a wire mesh with a Screw modifier (degrees, segments, weld core, normals calculated) around the Lathe axis: the gizmo's local Z through the gizmo origin | Caps of partial revolutions not generated |
| Sweep, Bevel, CrossSection, Surface, … | not yet: the shape is imported as a curve and the modifier reported | |
| (no modifier) | a Bezier curve (see below) | |

Extrude parameters (old ParamBlock, reference 0; 135 corpus objects): 0 amount, 1 segments (1 on 126), 2 / 3 cap
start / end, 4 cap type (0 morph), 5 output (1 mesh), 6 generate mapping coordinates, 7 generate material IDs, 8 use
shape IDs, 9 smooth. Ids 0-3 from values and defaults; 4-9 guessed from Max's UI order and defaults.

Lathe parameters (old ParamBlock, reference 1; reference 0 is the axis gizmo; 51 corpus objects): 0 degrees (360
on all), 1 segments (8-36), 2 / 3 cap start / end, 4 cap type, 6 output (1 mesh on 46). The axis direction is not a
parameter: it is the gizmo rotation (a quarter turn about X on the 48 lathes made with the default Y direction puts
the gizmo's Z on the shape's Y; a quarter turn about Y on one made with X), and the gizmo sits at the profile's
minimum X and middle Y (Max's default "Align Min"). Guess: 5 weld core.

Curves: knots and their absolute handles as stored; smooth and Bezier knots get aligned handles, corner and Bezier
corner knots free handles; the interpolation steps + 1 are the resolution. A shape with "Enable In Renderer" or
"Enable In Viewport" gets a round bevel of the rendering thickness (sides / 4 − 1 as the bevel resolution; the
rectangular section is approximated by a round one). Text shapes arrive as their glyph outlines.

## Editable Mesh triangles

Editable Mesh objects store triangles with per-edge visibility; the hidden edges are the diagonals of the
polygons Max shows. Under a subdivision modifier (MeshSmooth / TurboSmooth subdivide those polygons), and for
meshes up to 20,000 faces, the hidden edges are dissolved so the Blender mesh has Max's polygons.
