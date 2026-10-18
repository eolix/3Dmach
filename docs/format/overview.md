# .max format overview

What `maxfile` knows about the `.max` format, and how each fact was established.

**Status.** Everything below was checked on the local corpus: Autodesk's public sample files, 623 non-empty
`.max` files saved by Max 2008 to 2018 (release numbers 10000 to 20000 in the DLL directory header, §2.4), with
20.3 million chunks in their Scene streams. "Verified" means the rule holds on every corpus file it applies to
(the counts say how many), or, for meanings, that it was checked against independent data in the files: geometry,
names, the matrices the Skin modifier stores, the input bounding boxes stored for each modifier, and so on. What
could only be inferred is marked **Guess**, and the code marks it `# Guess:`. Facts that are not about real files
come from the GPL importer `io_scene_max` 1.9.2 (Sebastian Sille et al.), which was the starting point; where it
was wrong this document says so. No Autodesk SDK documentation was used.

Conventions: all integers are little-endian. `u16`/`u32`/`u64` are unsigned, `f32` is an IEEE float. Chunk type
IDs are written as `0x0962`. Object indices are written `[12]`. Corpus file paths are relative to the sample set's
root.

Tools: `maxdump` (see [maxdump.md](maxdump.md)) shows all of this for one file; `tests/corpus/survey.py` runs the
reader over the whole corpus (about 1 minute); the corpus tests in `pylibs/maxfile/tests/` (skipped without the
corpus) turn the facts below into assertions.

## 1. Container and streams

A `.max` file is a Compound File Binary (OLE2) file [MS-CFB]. The streams, with the number of corpus files that
have them:

| Stream | Files | Content |
|---|---|---|
| `Scene` | 623 | The scene: one container holding every object (§3). |
| `ClassDirectory3` | 623 | Class table (§2.3). No corpus file uses the older name `ClassDirectory`. |
| `DllDirectory` | 623 | Plugin table (§2.4). |
| `Config` | 623 | Settings (viewports, grid, render, gamma, ...). The system unit is *not* here (§4.3). |
| `ClassData`, `VideoPostQueue` | 623 | Chunk trees, not read. |
| `ScriptedCustAttribDefs` | 620 | Chunk tree, not read. |
| `SaveConfigData` | 560 | `0x2170` = the DLL directory header value, `0x2173` = release x 1000. |
| `FileAssetMetaData3` | 530 | Asset table (bitmap paths, §7). |
| `FileAssetMetaData2` | 90 | Older asset table (§7). |
| `MetaData` | 2 | Not read. |
| `\x05SummaryInformation`, `\x05DocumentSummaryInformation` | 623 | Standard property sets (thumbnail, "3ds Max Version: 16.90", scene totals, object / material / plug-in lists as text). Not read. |

## 2. Chunks

### 2.1 Chunk headers (verified)

```
u16  type
u32  size          # whole chunk, header included; bit 31 set -> container (payload = child chunks)
u64  size64        # only when size == 0: the real size, bit 63 = container flag (header is then 14 bytes)
payload
```

All chunk streams of all 623 files parse with this rule without one error. The 64-bit form occurs inside
streams (39,751 chunks in 240 files), not only at the top. The meaning of a type depends on its parent.

### 2.2 Compression (verified)

A compressed stream is one gzip member (`1F 8B 08`, deflate). In practice compression is a per-file choice: 192
files compress every chunk stream (all Max 2008 files, and 189 of the 225 files from Max 2017-2018), the others
none.

### 2.3 Class directory (verified)

`ClassDirectory3` is a list of `0x2040` containers, one per class; a class's position is the type ID of the scene
objects of that class (§3). Each entry:

| Chunk | Layout | Meaning |
|---|---|---|
| `0x2060` | `u32 dll_index, u32 class_id_a, u32 class_id_b, u32 superclass_id` | `dll_index` counts the DLL directory's entries (§2.4); `0xFFFFFFFF`, and for a few classes `0xFFFFFFFE`, mean "built in". |
| `0x2042` | UTF-16LE | The class name, as Max shows it ("Editable Poly", "Target Spot", "Physical Material", ...). |

A class ID is the pair (a, b); the 64-bit form used in this document puts `a` in the low half (Editable Poly is
stored as a = `0x1BF8338D`, b = `0x192F6098`: `0x192F60981BF8338D`).

**Class IDs are only unique within a superclass**: `0x2` is RootNode (superclass `0x1`) and the Standard material
(`0xC00`); `0x10` is Box (`0x10`) and Bend (`0x810`); `0x200` is Multi/Sub-Object (`0xC00`) and Checker (`0xC10`).
The registry (`maxfile/registry.py`) is therefore keyed by (class ID, superclass), and seeded from the names the
corpus's class directories store. The superclasses, with the classes they hold in the corpus:

| Superclass | Holds | Superclass | Holds |
|---|---|---|---|
| `0x0001` | Node, RootNode | `0x0C00` | materials |
| `0x0008` | ParamBlock | `0x0C10` | texture maps |
| `0x0082` | ParamBlock2 | `0x1080` | a Standard material's map list ("Texmaps") |
| `0x0010` | geometry (Editable Poly / Mesh, primitives, Bone, Biped, particle systems, Target) | `0x10B0` | Standard material shaders (Blinn, Phong, ...) |
| `0x0020` | cameras | `0x10F0` | layers |
| `0x0030` | lights | `0x1160` | custom attributes |
| `0x0040` | shapes | `0x9003` | float controllers |
| `0x0050` | helpers (Dummy, Point, Grid, Tape, particle operators) | `0x9005` | point3 / colour controllers |
| `0x0060` | systems (Biped, Daylight) | `0x9008` | transform controllers (PRS, Look At) |
| `0x0810` | modifiers | `0x900B` / `0x900C` / `0x900D` | position / rotation / scale controllers |
| `0x0820` | world-space modifiers | `0x0830` | space warps |

### 2.4 DLL directory (verified)

A `0x21C0` leaf, then one `0x2038` container per plugin DLL. `dll_index` in the class directory counts the
`0x2038` entries only (the prior-art importer counted the header too and was off by one: it labelled the Blinn
shader as coming from `viewportmanager.gup` instead of `mtl.dlt`).

| Chunk | Layout | Meaning |
|---|---|---|
| `0x21C0` | `u32` | Low word: a build number (?); high word: the Max release x 1000 (20000 = Max 2018, 19000 = Max 2017, 16900 = 2015, 14000 = 2012, 12900 = 2010, 10000 = 2008), matching "3ds Max Version: 16.90" in the summary information. `MaxFile.max_release`. |
| `0x2037` | UTF-16LE | File name, e.g. `mtl.dlt`. |
| `0x2039` | UTF-16LE | Description, e.g. "Standard Materials and Textures (Autodesk)". |

## 3. Scene stream and references (verified)

The `Scene` stream holds one top-level container (all 623 files). Its children are the scene's objects; an
object's position is its **object index**, and its chunk type is its class index into the class directory.

**Derived objects.** Two chunk types beyond the class directory occur: `0x2032` (2,952 objects) and `0x2033` (67).
They are classes of their own, the derived objects that carry modifier stacks (§6.5); `maxfile` gives them pseudo
class entries ("Derived Object", "Derived Object (world space)") so that they are ordinary objects. No other
chunk type outside the class directory occurs.

**References.** An object refers to others by object index:

| Chunk | Layout |
|---|---|
| `0x2034` | `u32[]`: slot *i* = element *i*; `0xFFFFFFFF` = empty slot. |
| `0x2035` | `u32` slot count, then `(u32 slot, u32 object index)` pairs (payload 4 + 8n in all 17,097 sampled). |

Two nodes that reference the same object index share it (instancing; 5,248 node references go to only 2,952
derived objects).

## 4. Nodes

Nodes are exactly the objects of class `0x1` / superclass `0x1` (40,948 in the corpus). The scene root is the one
object of class `0x2` / superclass `0x1` ("RootNode"); top-level nodes name it as their parent.

| Chunk | Layout | Meaning |
|---|---|---|
| `0x0960` | `u32 parent, u32 flags` | Parent's object index (the root for top-level nodes); node flags (below). |
| `0x0962` | UTF-16LE | Node name. |
| `0x096A` | `f32[3]` | Object offset position (pivot offset). |
| `0x096B` | `f32[4]` | Object offset rotation, quaternion stored like controller rotations (§4.1). |
| `0x096C` | `f32[3]`, `f32[4]` | Object offset scale, then a scale-axis quaternion (only the scale is used). |
| `0x0974` | `u8 r, g, b, 0` | Wireframe colour (the fourth byte is 0 on every node). |
| `0x0963`, `0x09CE`, `0x099C`, `0x0A28`, `0x0A32`, `0x0ABE`, `0x0AC3`, `0x0AD2`, `0x0B22`, `0x0ADC`, `0x0AF0`, `0x0B0E`, `0x0B4A`, `0x0B54`, `0x0B5E`, `0x0B68` | | Present on every node; not decoded (render / display properties, by their contents). |

Reference slots (verified by the superclass of what they point at, on all nodes): **0** transform controller
(superclass `0x9008`, all but one node), **1** object (geometry, light, camera, shape, helper, derived object),
**3** material, **5** visibility track (float controller, rare), **6** layer (Base Layer and others).

**Node flags** (second word of `0x0960`). Guesses, from the names and roles of the nodes carrying each bit:
bit 6 group head (the Dummies heading groups such as "tower01"), bit 8 group member, bit 9 frozen (weak: context
buildings "existing01"... and site lines in architectural scenes, rig bones), bit 14 target (every
"*.Target" node), bit 20 hidden (particle-shape sources, collision helpers, biped nubs and footsteps, proxy boxes of
rigs, the "ceiling" of interiors rendered from inside). `Node.flags`, `is_hidden`, `is_frozen`, `is_target`,
`is_group_head`, `is_group_member`. Bits 10-12 are set on most nodes.

### 4.1 Transform controllers (verified)

Each controller stores its value at the time of saving, whether or not it has keys:

| Class (superclass) | Value |
|---|---|
| Position/Rotation/Scale `0x2005` (`0x9008`) | References 0, 1, 2 = position, rotation, scale controllers. |
| Bezier Position `0x2008`, TCB Position `0x442312` (`0x900B`) | `0x2503`: `f32[3]`. |
| Position XYZ `0xFFEE238A118F7E02` (`0x900B`) | References 0, 1, 2 = X, Y, Z float controllers. |
| TCB Rotation `0x442313` (`0x900C`) | `0x2504`: `f32[4]` quaternion (below). |
| Euler XYZ `0x2012` (`0x900C`) | References 0, 1, 2 = X, Y, Z float controllers, radians. |
| Bezier Scale `0x2010`, TCB Scale `0x442315` (`0x900D`) | `0x2505`: `f32[3]` scale, `f32[4]` scale-axis quaternion. |
| ScaleXYZ `0xFEEE238B118F7C01` (`0x900D`) | References 0, 1, 2 = float controllers. |
| Bezier Float `0x2007`, Linear Float `0x2001` (`0x9003`) | `0x2501`: `f32` (7,287 of 222,296 Bezier Floats nest it in a `0x7127` container). |
| Bezier Point3 `0x200A`, Bezier Color `0x2011` (`0x9005`) | `0x2501`: `f32[3]`. |
| Position / Rotation / Scale / Float / Point3 List `0x4B4B1002` / `1003` / `1004` / `1000` / `1001` | Sub-controllers as references. Simplification: the first one's value. |

Keys, when present, are in `0x2520`-`0x2528` (`0x2525` Bezier Float, `0x2526` Bezier Position / Point3, `0x2522`
TCB Rotation, `0x2528` Bezier Scale). Not read (animation is out of scope).

**Quaternions** are stored as `x, y, z, w` of the **inverse** rotation: in Blender's convention `(w, x, y, z) =
(q3, -q0, -q1, -q2)`. Verified against independent data: the Skin modifier keeps the matrix (4x3 floats, no
quaternion) of the node it deforms (§6.5). Composing node matrices as `parent @ T @ R @ S` with this quaternion
mapping reproduces 71 of those 75 matrices in the corpus, among them every one with a non-trivial rotation (the
other 4 nodes moved after skinning); 30 of them only match with the object offset applied (`node @ offset`), which
also verifies the offset composition. The prior-art mapping `(q3, q2, q1, q0)` fails on 10. **Euler XYZ** angles
are radians with the same sign as Blender's (negating them breaks 22 of the matches); the rotation order isn't
discriminated by these scenes (fixed axes X, then Y, then Z is assumed).

### 4.2 Scene settings and units (verified)

The scene settings object is the one object of class `0x2222` / superclass `0x100` (stored name "Scene", one per
file). Its `0x8520` chunk is the system unit: `u32 unit, f32 scale` ("1 unit = scale units"). Codes in the corpus:
0 inches (507 files), 1 feet (1), 3 millimetres (6), 4 centimetres (35), 5 metres (74); the scale is 1.0 in every
file. Codes 2 and 6 (miles, kilometres) are assumed from the order. Evidence: with this table architectural scenes
come out at their real size: an interior modelled as a 5.000 m room is 196.85 units in a file with code 0, a
~4.9 km bridge 166,534 units in inches, a photo studio 6,263 units in millimetres, a Revit import of a building
149.6 units in feet. Caveat: some sample sets were saved with a unit that doesn't match their content (character
sets in a metre and a "-US" version with identical geometry; motion-capture files with identical geometry saved in
centimetres or metres), so the importer keeps a units override. `MaxFile.units` -> `SceneUnits(unit, scale, code)`.

The same object holds `0x8510` = 4800 (ticks per second, presumably) and `0x8500` / `0x8530` (u32 2).

## 5. Parameter blocks (verified)

Most objects keep their parameters in parameter block objects they reference (usually in low reference slots).
`Scene.param_block(obj)` reads either kind into `ParamBlockData(params={id: Param})`.

### 5.1 ParamBlock2 (class `0x82` / superclass `0x82`, 190,760 objects)

| Chunk | Layout |
|---|---|
| `0x0009` | 16 bytes: `u16` (?), `u16`, `u32` (version-like), `u16` parameter count, `u32` owner (object index of the object the block belongs to). |
| `0x100E` (`0x000E` in files from Max 2012 and older) | One per parameter: `u16 id, u32 type, u16 flags_a, u32 flags_b, u16 ?, u8 value_flags`, value. |
| `0x2034` / `0x2035` | The block's references. |

- `value_flags & 0x40`: the value follows inline. Without it (`0x80`) a controller animates the value.
- `flags_b & 0x01`: the parameter holds a reference (node, map, material, ...); `flags_a & 0x0100`: the reference
  is inline, as an object index (`0xFFFFFFFF` = none), instead of in a reference slot.
- `type & 0x800`: a table: `u32 count`, then per item `u8 item_flags` and the item's value (inline value, inline
  index, or nothing when it is in a slot / animated).
- **Reference slots** are handed out in record order to every value that isn't inline: a controller for each
  animated value, one slot per non-inline reference, one per table item of a reference table or animated item. This
  reproduces the slot count of the `0x2035` chunk for 60,408 of the 60,410 sampled blocks whose records could all
  be sized, and the referenced classes match the types (float params -> float controllers, texmaps -> maps, nodes
  -> nodes, ...).

Types, established from the values and from what references point at: 0 float, 1 int, 2 RGB colour (3 floats),
3 point (3 floats), 4 bool (u32), 5 angle (radians), 6 percentage (fraction: a 10 % glossiness is 0.1), 7
world-space distance, 8 string, 9 file name, 12 time, 13 radio-button index, 14 material, 15 texture map, 16 one
byte (unknown), 17 node, 18 any reference, 19 index, 20 matrix (52 bytes: a word, then 4x3 floats; guess), 23 RGBA
colour (4 floats). Strings are `u32` byte length (`0xFFFFFFFF` = none) and the text with a terminating NUL:
UTF-16LE in `0x100E` records (18,145 values), 8-bit in `0x000E` records (881). A length of `0xFFFFFFFE` (1,754
file-name values) means an asset reference: the record ends there and the block's next chunk, a `0x000F`
container, holds the 16-byte asset ID in `0x0002` (looked up in the asset table, §7). Records of a type the reader
can't size but without value bytes (type 25, 194 records) read as None. Parameter **names** are not stored; the tables in §6-§9 give the IDs worked out per class.

### 5.2 ParamBlock (class `0x8` / superclass `0x8`, 28,131 objects)

`0x0001` u32 count, `0x0005` u16, then one `0x0002` container per parameter: `0x0003` u32 index, optionally
`0x0004` (empty, on animatable parameters), and one value chunk: `0x0100` float, `0x0101` int, `0x0102` point (3
floats), `0x0103` colour (3 floats), `0x0104` bool / int; `0x0200`-`0x0204` (empty) mark the same types driven by a
controller, which is the block's reference in the slot equal to the parameter index.

## 6. Geometry

### 6.1 Classes

Geometry objects (superclass `0x10`) in the corpus, by object count: Biped Object 6,159, Editable Mesh 5,694,
Editable Poly 4,455, Bone 2,114, ParticleGroup 852, CATBone 558, Target 364 (camera / light targets), Plane 327,
Box 322, Cylinder 316, Sphere 291, PF Source 216, PolyMeshObject 111, GeoSphere 88, Teapot 62, ChamferBox 36,
Tube 29, Cone 22, Torus 18, Loft 17, Editable Patch 15, ChamferCyl 13, ... Only Editable Poly, PolyMeshObject,
Editable Mesh, MeshObject and Editable Patch store a mesh (`0x08FE`); primitives store only parameters (§6.4).

### 6.2 Editable Poly / PolyMeshObject (`0x08FE` container, verified)

Verified on all 4,566 meshes (2,037,565 polygons): every chunk is consumed exactly, no index is out of range.

| Chunk | Layout | Meaning |
|---|---|---|
| `0x0100` | `u32 count`, per vertex `u32 flags, f32[3]` | Vertices. |
| `0x010A` | `u32 count`, per edge `u32 flags, u32 v1, u32 v2` | Edges. |
| `0x011A` | `u32 count`, per face `u32 n, u32[n] vertices, u16 flags`, then by flag: `0x01` `u32` (meaning unknown), `0x08` `u16` material ID, `0x10` `u32` smoothing groups, `0x20` `u32[2(n-3)]` triangulation diagonals | Polygons. |
| `0x0120` | `u32` | Number of map channels (highest channel + 1). |
| `0x0124` | `i32` | Map channel number; the following `0x0128` and `0x012B` belong to it. Channels -2 to 3 occur. |
| `0x0128` | `u32 count`, `f32[3]` each | Map vertices. |
| `0x012B` | per face `u32 n, u32[n]` (no count) | Map faces: one per polygon, same corner count (all channels but 13 in one file). |
| `0x0150`, `0x0140`, `0x0130`, `0x0310`, `0x0320`, `0x0200`, `0x0210` | | Not decoded (`0x0310` is not a face list). |

The optional face fields are written only when non-zero: 1,007,416 faces carry a material ID, never 0, the other
1,030,149 have none; smoothing likewise; the diagonals exactly on faces with more than three corners. **Material
IDs are 0-based on disk** (Max shows them 1-based): absent = 0 = Max's ID 1; also, an Editable Mesh converted from a
Box (`Scenes/SubDivSurfaces/Meshsmooth-Hammer.max`) has IDs 0-5 for the six sides Max numbers 1-6. `MeshData` holds
the 1-based IDs. 58 faces in the corpus have fewer than three corners (one file); the reader drops them.

### 6.3 Editable Mesh (`0x08FE` container, verified)

Verified on all 5,694 meshes (4,382,904 triangles), same checks as above.

| Chunk | Layout | Meaning |
|---|---|---|
| `0x0914` | `u32 count`, `f32[3]` each | Vertices. |
| `0x0912` | `u32 count`, per face `u32[3] vertices, u32 smoothing, u16 flags, u16 material ID` | Triangles. Flags bits 0-2: edge a-b, b-c, c-a visible. |
| `0x0959` | `i32` | Map channel number (-1, 0, 1, 2 occur); the following `0x2398`, `0x2394`, `0x2396` belong to it. |
| `0x2398` | `u32` | Usually 1 (meaning unknown). |
| `0x2394` | `u32 count`, `f32[3]` each | Map vertices. |
| `0x2396` | `u32 count`, `u32[3]` each | Map faces, one per triangle (all 4,486 channels). |
| `0x0906`, `0x0908`, `0x0924`, `0x0928`, `0x092A`, `0x092C`-`0x092E`, `0x0952`, `0x23A0` | | Not decoded. `0x0924` is **not** the map channel (the prior-art importer read it as one). |

Edge visibility: 2.84 million hidden edges are shared by exactly two triangles that both hide them: they are the
diagonals of the polygons Max shows (a box side is two triangles with one hidden edge). `MeshData.edge_visibility`
lets the importer rebuild those polygons.

Overall the meshes are clean: 3,493 non-manifold edges among 11.2 million, 7,791 unused vertices.

### 6.4 Primitives

#### Evidence used: modifier-context bounding boxes

A derived object (chunk type 0x2032 / 0x2033) holds one `0x2500` container per modifier, in the order of its
modifier references (top of the stack first). `0x2500/0x2511` is 6 floats: the bounding box (min xyz, max xyz) of
the modifier's input, in object space, as it was when the modifier was added (it is not refreshed later: instanced
modifiers keep the box of the first object, animated objects show the box at the time of adding). For the bottom
modifier that is the bounding box of the base object, which gives an independent measure of a primitive's size;
the context box of the modifier above a given modifier shows that modifier's output.

#### Primitives (superclass 0x10)

No primitive in the corpus caches a mesh: the 1,533 primitive objects only have `0x0100` (Box: 1 byte 0/1;
Cylinder / Cone: u32 0; Sphere / Tube / Torus: empty; meaning unknown, possibly real-world map size),
`0x2034`/`0x2035`, `0x204B`, `0x2150` (AppData) and once `0x21B0`. `cached_mesh` is therefore always None on the
corpus (the decoder still reads a `0x08FE` container with the Editable Mesh layout if one ever appears).

Parameters live in the parameter block in **reference slot 0** (all 1,533): a ParamBlock2 or, in older files /
objects, an old ParamBlock (class 0x8). The old block's parameter indices equal the ParamBlock2 IDs (same types in
the same order; the bounding-box checks pass on both). Angles are radians in both (old Tube slices +-1.0472).

Names follow the live-primitive builder (`mx_primitives.geometry.PARAMETERS`); `params` holds only names the
builder accepts for its kinds, other named values go to `extra_params`.

V = verified, G = guess (UI order / defaults only). Counts are corpus objects.

| Class (ID) | kind | Parameter IDs |
|---|---|---|
| Box 0x10 (322) | BOX | 0 length (Y) V, 1 width (X) V, 2 height (Z, may be negative) V, 3 width_segments (X) V, 4 length_segments (Y) V, 5 height_segments G, 6 generate_uvs G |
| Sphere 0x11 (291) | SPHERE | 0 radius V, 1 segments V, 2 smooth G, 3 hemisphere (fraction) V, 4 hemisphere_mode (0 CHOP / 1 SQUASH) G, 5 slice_on G, 6 generate_uvs G (not base-to-pivot: set on spheres whose box starts at -r), 7 base_to_pivot G (never set), 8 slice_from G, 9 slice_to G |
| Cylinder 0x12 (316) | CYLINDER | 0 radius V, 1 height V, 2 height_segments G (Edit Poly count 108 = 18 x 6), 3 cap_segments G, 4 sides V, 5 smooth G, 6-8 slice on/from/to G, 9 generate_uvs G |
| Cone 0xA86C23DD (22) | CONE | 0 radius1 V, 1 radius2 V, 2 height V, 3 height_segments G, 4 cap_segments G, 5 sides V, 6 smooth G, 7-9 slice G, 10 generate_uvs G |
| Tube 0x7B21 (29) | TUBE | 0 radius1 V, 1 radius2 V, 2 height V, 3 **sides** V, 4 cap_segments G, 5 height_segments G, 6 smooth G, 7-9 slice G, 10 generate_uvs G |
| Torus 0x20 (18) | TORUS | 0 radius1 V, 1 radius2 V, 2 rotation G, 3 twist G, 4 segments V, 5 sides V, 6 smooth_mode (2 = ALL, others unknown) G, 7-9 slice G, 10 generate_uvs G |
| Plane 0x77566F65081F1DFC (327) | PLANE | 0 length (Y) V, 1 width (X) V, 2 width_segments V, 3 length_segments V, 4 render_scale G (extra), 5 render_density G (extra), 6 generate_uvs G |
| GeoSphere 0x00007F9E00000000 (88) | GEOSPHERE | 0 radius V, 1 segments G, 2 base_type (2 = ICOSA on all; 0 TETRA / 1 OCTA guessed) G, 3 hemisphere_on G, 4 smooth G, 5 base_to_pivot G, 6 generate_uvs G |
| Teapot 0xACAD26D9ACAD13D3 (62) | TEAPOT | 0 radius V (box 3.217 r x 2 r x 1.575 r), 1 segments G, 2 smooth G, 3 unknown int (-1 on all), 4-7 part_body / part_handle / part_spout / part_lid G, 8 generate_uvs G |
| ChamferBox 0x48EA0F971AD73F40 (36) | CHAMFERBOX | 0 length V, 1 width V, 2 height V, 3 fillet G, 4 width_segments G, 5 length_segments G, 6 height_segments G, 7 fillet_segments G, 8 smooth G, 9 generate_uvs G |
| ChamferCyl 0x21A446A17B9A546E (13) | CHAMFERCYL | 0 radius V, 1 height V, 2 fillet G, 3 height_segments G, 4 fillet_segments G, 5 sides V, 6 cap_segments G, 7 smooth G, 8-10 slice G, 11 generate_uvs G |
| Capsule 0x79C939A96D3D77AC (7) | CAPSULE | 0 radius V, 1 height (overall, caps included) V, 2 height_type G, 3 sides G, 4 height_segments G, 5 smooth G, 6-8 slice G, 9 generate_uvs G |
| Torus Knot 0x720 (2) | TORUS_KNOT | 0 radius G, 1 cross_section_radius G, 4 segments G, 5 sides G, 7 p G, 8 q G (defaults 120 / 12 / 2 / 3) |

How the V entries were established:

- Box: context box X extent = id 1, Y = id 0, Z = |id 2| on 100 of 106 boxes under a modifier (the rest are
  stale / animated boxes). Plane: 92 of 92. ChamferBox 18 of 20, ChamferCyl 9 of 9, Capsule 7 of 7.
- Sides: the X / Y extents of an n-sided polygon (first vertex on +X) identify n. Cylinder id 4 (46 of 48; id 2
  matches 11 only where both are equal), Cone id 5 (10 and 9 sides; id 3 = 18 / 4 does not fit), Tube id 3 (87, 24
  and 18 sides), ChamferCyl id 5, Torus id 5 (Z extent 2 r2 sin 60 for 6 sides).
- Segments along X: Bend modifiers bend along the axis with the segments. CreatureSkinned's Box (84.3 along X,
  3.96 along Y) has id 3 = 6, id 4 = 1 and is bent with axis 0 = X; four Planes (Boat Wake Spray, evermotion 09,
  Viewport-Dragon) have their larger count in id 2 and are bent along X. Bend axis 0 = X is itself established by
  tall Cylinders / Cones (long in Z) being bent with axis 2.
- Edit Poly vertex counts above primitives agree (Box 3x3x3: 56, 1x1x1: 8, 3x3x1: 32).
- Rebuilding the decoded primitives with `mx_primitives.geometry.generate` reproduces the context boxes of 98 of
  106 Boxes, 65 of 92 Planes (the rest have context boxes offset by a moved gizmo), 44 of 48 Cylinders, 36 of 48
  Spheres, 3 Tubes, 6 of 19 Cones (13 share one stale instanced context).

### 6.5 Modifier stacks (derived objects, verified)

A derived object (`0x2032`, or `0x2033` for 67 objects whose stack has world-space modifiers) carries a modifier
stack. Verified on all 3,019 of them:

- references (`0x2034`, contiguous slots): the modifiers, **top of the stack first**, and the base object last.
  Evidence: modifiers that turn a shape into a mesh (Extrude, Lathe, Sweep) always sit directly above a shape base
  and below every mesh modifier (`UVW Map, Extrude, Edit Spline, <Line>`); Skin is above Morpher; and the input
  bounding boxes below grow from the bottom up (a Star under Extrude is flat).
- the base may itself be a derived object (nested stacks: instanced modifiers); its modifiers sit below the outer
  ones.
- one `0x2500` container per modifier, in the same order: `0x2510` (the modifier context matrix, 4 rows of 3
  floats, then a u32), `0x2511` (bounding box of the modifier's input, min then max), optionally `0x2512` (the
  modifier's data for this object: Skin keeps its node's matrix here, `0x2512/0x0010/0x03E8`), and `0x2513` (u32).

`Scene.resolve_geometry(node)` -> `(base object, modifiers top first)`; `ModifierStack.modifiers` carry the context
matrix, input box and flags.

### 6.6 Modifier parameters

Modifier object layout:

- One parameter block per class in a fixed reference slot (slot 0 for most; 1 for UVW Map and Mirror, whose slot 0
  is the gizmo's Position/Rotation/Scale controller; 2 for Bend, Taper, Twist and Noise (slot 0 gizmo PRS, slot 1
  gizmo centre position); 95 for Unwrap UVW). Bend's block is a ParamBlock2 with plain float angles in degrees;
  Taper, Twist, Noise, UVW Map, Mirror, Push, Relax, Optimize, Lattice, Normal use old ParamBlocks.
- `0x39BF` container (inside `0x0080` for Edit Poly): `0x0100` = the name shown in the stack (UTF-16, empty
  unless renamed: "UVW Mapping", "MSmth-RFore..."), plus optional empty markers `0x0110` (~110 objects), `0x0120`
  (~50, nearly only TurboSmooth / MeshSmooth) and `0x0130` (once).

**Enabled flag: not established.** The three markers are the best candidates for Max's three states (Off, Off in
Viewport, Off in Renderer), but the files don't say which is which: the context boxes don't help (they are not
refreshed, so "output = input" doesn't separate flagged modifiers: 18 of 22 `0x0110` modifiers change the box,
172 of 884 unflagged ones don't), and the parameter combinations are ambiguous (MeshSmooth with 0 viewport / 2
render iterations carries `0x0110`; Maxine's TurboSmooths with render iterations 2 carry both `0x0110` and
`0x0120`). `ModifierData.enabled` stays None; `state_flags` lists the markers raw. The derived object's
`0x2500/0x2513` u32 (0x00040100 on 2,695 contexts, 0x00040000 on 586, 0x00040140 on 123, 0x00040040 on 7,
0x00040020 once) does not correlate with the markers either (both values occur with and without them).

Parameter IDs (V verified, G guess):

| Modifier (class ID) | slot | Parameters |
|---|---|---|
| TurboSmooth 0x491D29A70D727B3E (98) | 0 | 0 iterations V, 1 use_render_iterations V, 2 render_iterations V (id 1 True <=> id 2 > 0), 3 isoline_display G, 4 smooth_result G (True on all), 5 separate_by_materials G, 6 separate_by_smoothing_groups G, 7 update_mode G, 8 explicit_normals G |
| OpenSubdiv 0x9ABC45FC73CCF34A (8) | 0 | 0 iterations V, 1 use_render_iterations G, 2 render_iterations G (same pattern as TurboSmooth) |
| MeshSmooth 0x00007F9E00000032 (144) | 0 | 4 iterations V, 13 use_render_iterations V, 14 render_iterations V, 0 strength G, 1 relax G, 2 smoothness G, 9 subdivision_method G (2 on 126), 12 use_render_smoothness G, 16 render_smoothness G |
| Shell 0x6D84E8D03B9B1A16 (15) | 0 | 0 inner_amount G, 1 outer_amount G (partly: Maxine's shells grow outwards by ~id 1), 12 segments G, 14 auto_smooth_edge G, 15 auto_smooth_angle G (45.0) |
| Symmetry 0x0BE41A6E2D7E702B (20) | 0 (gizmo 1) | 0 axis V, 1 slice_along_mirror G, 2 weld_seam G, 3 threshold V (0.1 default), 4 flip V |
| Mirror 0x511BBE75EF92AA7C (3) | 1 (gizmo 0) | 0 mirror_axis G, 1 copy G, 2 offset G |
| Chamfer 0x38BB548C332C9510 (12) | 0 | 0 amount G, 1 segments G, 2 tension G, 12 min_angle (degrees) G |
| Bend 0x10 (533) | 2 (gizmo 0) | 0 bend_angle (deg) V, 1 bend_direction (deg) G, 2 bend_axis V (0 X, 1 Y, 2 Z), 3 limit_effect G, 4 lower_limit V (always <= 0), 5 upper_limit V (always >= 0) |
| Twist 0x90 (7) | 2 | 0 angle (deg) V, 1 bias G, 2 axis G, 3 limit_effect G, 4 lower_limit G, 5 upper_limit G |
| Taper 0x20 (56) | 2 | 0 amount G, 1 curve G, 2 primary_axis V (2 on tall cylinders), 3 effect_axis G, 4 symmetry G, 5 limit_effect G, 6 lower_limit G, 7 upper_limit G |
| Noise 0xF997B124 (102) | 2 | 0 seed G, 1 scale V (100 default), 2 fractal G, 3 roughness G, 4 iterations V (6.0), 5 animate_noise G, 6 frequency V (0.25), 7 phase G (always animated), 8 strength (3 floats) V |
| Push 0x67AD0ADF0618372D (27) | 0 | 0 push_value V (only parameter) |
| Relax 0x00007F9E00000064 (6) | 0 | 0 relax_value V, 1 iterations V, 2 keep_boundary_points_fixed G, 3 save_outer_corners G |
| Optimize 0xC4D31 (3) | 0 | 2 face_threshold (rad) G, 3 edge_threshold (rad) G, 4 bias G |
| Lattice 0x2ED9401C148132A1 (6) | 0 | 0 geometry_type G, 1 strut_radius G, 2 strut_segments G, 3 strut_sides G, 7 joint_radius G |
| Normal 0xF8614 (13) | 0 | 0 unify G, 1 flip G (1 on all) |
| UVW Map 0xF72B1 (913) | 1 (gizmo 0) | 0 map_type G (4 box 535, 0 planar 342, ...), 1-3 u/v/w_tile G, 4-6 u/v/w_flip G, 7 cap G (set only on cylindrical), 9 length G, 10 width G, 11 height V (= Z extent on 430+), 12 axis G, 13 channel V (1 on 892) |
| Unwrap UVW 0x72BA4E1F02DF2E3A (112) | 95 | chunk 0x0190 u32 channel G (1 on 111). The ParamBlock2 holds display settings only. |
| Edit Poly 0x71A075B779AA6E1D (29) | 0 (PRS 1, Master Point Controller 2) | ~110 parameters (all display / operation defaults); not named |
| Turn to Mesh 0x60397CA15C5B50F7 (2) | 0 | not named |

Evidence for the V entries:

- MeshSmooth iterations: Meshsmooth-FishAnim's MeshSmooth sits on a 46-vertex / 88-triangle Editable Mesh (44
  quads, 88 polygon edges). The Unwrap UVW above it stores 706 geometry positions and 704 faces: 46+88+44 = 178
  vertices after one NURMS iteration (352 edges, 176 quads), 178+352+176 = 706 after two; id 4 = 2.
  Meshsmooth-Hammer's MeshSmooth: id 4 = 2.
- Render iterations: TurboSmooth id 1 True on 56 objects, all with id 2 > 0; MeshSmooth id 13 True on 63, all with
  id 14 > 0.
- Symmetry flip: in 5 stacks the next modifier's context box shows the kept side: flip True kept -X (TigerTank,
  08022 shots 000 / 003, 4 stacks), flip False kept +X (08022 shot 003 #2764). Axis 0 = X: only the X extent
  changes.
- Bend axis / limits: see above; id 4 is never positive, id 5 never negative.
- Noise / Relax / Push / UVW Map channel: defaults and the only value of the right type.

#### What the editing modifiers store

- **Edit Poly** stores edits, not its result: per node in the derived object's context `0x2500/0x2512`, a list of
  operations (`0x0230` u32 operation type, `0x0234` selection, `0x0238` with `0x12C3` u32 vertex count, `0x12C4`
  one f32[3] offset per input vertex, `0x12C5` UTF-16 node name). E.g. a 3x3x3 Box: 56 offsets per operation.
- **Unwrap UVW** stores its result per node in `0x2500/0x2512`: `0x0860` u32 count + 24-byte texture vertices
  (3 floats first), `0x0870` u32 face count + face records, `0x0330` u32 count + f32[3] geometry positions. The
  modifier object only holds UI settings.
- **Mesh Select** contexts hold bit arrays sized by the input's vertex / face / edge counts (706 / 1408 / 4224 in
  FishAnim), which is another way to read vertex counts through a stack.

#### Remaining questions

- Modifier on / off markers (see above).
- Primitive generate-mapping / real-world-map-size: which of the last bool and the object's own `0x0100` chunk is
  which.
- Sphere / Torus ring start angle: Max's first longitude is at +Y for 18- and 19-segment spheres and a 41-segment
  torus (their context boxes are the builder's with X and Y swapped).

## 7. Materials and maps

Worked out on the local corpus (623 files, Max 2008-2018). Code: `maxfile/objects/materials.py`,
`maxfile/objects/maps.py`, `maxfile/assets.py`. Counts are corpus objects. Unless a row says **Guess**, the
meaning is backed by the evidence given (defaults, value ranges, names of materials and bitmap files, classes of
referenced maps). Parameter names are the scripting names the importer's converters use.

### Names (all material and map classes)

The "MtlBase header" is a container whose first child is `0x4001` (UTF-16 name) followed by `0x4003` (flags),
`0x4020`, `0x4030`, and in newer files `0x4220`/`0x4230`/`0x4210`/`0x4200` (the `0x4200` leaf is the material
editor's preview thumbnail: RGB pixels). The container type depends on the class:

| Container | Classes (examples) |
|---|---|
| `0x4000` | Standard (15,299), Multi/Sub-Object, Blend, Double Sided, Raytrace, Bitmap (1,779), Noise, Checker, Mix, ... |
| `0x0100` | Physical Material (2,119), Arnold Standard Surface (837), Arch & Design, ProMaterials, Arnold maps |
| `0x1000` | Composite map |
| `0x1100` | Autodesk Material |
| none: `0x4001` + `0x4003` directly in the object | scripted materials (e.g. "CGCookie \| X-Ray") |

An empty `0x4001` (6-byte chunk) means "no name". 70 of the 81 material/map classes always have a name this way.

### Asset table (`FileAssetMetaData3` / `FileAssetMetaData2` streams)

Found by stream name. 530 files have version 3 (Max 2010+), 90 version 2 (Max 2008-2009), 3 have neither
(animation clips without materials), none has both. Not a chunk tree: a plain sequence of entries:

```
u8[16]  asset ID: a Windows GUID in binary layout (u32, u16, u16 little-endian, 8 bytes)
string  type: "Bitmap" (761 + 451), "Animation" (224), "RenderOutput" (9), "Photometric" (5), "Sound", "VideoPost", "Other"
string  path as picked by the user (absolute, or relative to the project folder)
string  (version 3 only) absolute path it last resolved to; empty in 150 of 1,000 entries, equal to the first in 181
string  = u32 character count, UTF-16LE characters, u16 NUL
```

Verified: this layout consumes all bytes of all 620 streams (1,000 + 453 entries). Example (HSDS-Dolphin.max):
`Bitmap`, `Scenes\SubDivSurfaces\Flipper.jpg`, `P:\Projects\Sample Files\Scenes\SubDivSurfaces\Flipper.jpg`.

### Bitmap (class 0x240, superclass 0xC10; 1,779 in 330 files)

References: 0 `Placement` (UVGen, class 0x100 / superclass 0xC20), 1 ParamBlock2 (17 parameters, same layout in
all 1,779), 2 `Output` (0xC40), 3 ParamBlock2 of time settings (start frame, playback rate, end condition, sync).

The path is never stored as a string in the corpus; it goes through the asset table:

- parameter 16, type 9 (file name): string length `0xFFFFFFFE`, record ends, and the next chunk of the block is a
  container `0x000F` whose `0x0002` holds the 16-byte asset ID (1,740 Bitmaps). Length `0xFFFFFFFF` = no file (39).
- parameter 13 (type 16) is followed by the bitmap-info container `0x0003`: `0x1201` (settings), `0x1260` /
  `0x0002` (asset ID again), `0x1240` (image format name, "JPEG File"), sometimes `0x1220`, `0x1250`. Gives the
  file for 13 Bitmaps whose parameter 16 is empty; equal to parameter 16 in 1,739 of 1,740.

Result: 1,753 Bitmaps resolve to a non-empty path (1,740 via parameter 16, 13 via the bitmap info); 26 have no
asset ID at all (empty Bitmap slots). The prior-art "path string in chunk 0x1230" scheme is not in the corpus
(kept as an unverified fallback for older files).

Other Bitmap ParamBlock2 parameters (not used by the importer): 0-4 floats (0, 0, 1, 1, 1: **Guess** crop
u/v/w/h and jitter), 5-6 bools, 7-11 ints, 12 bool, 14-15 references.

#### UVGen ("Placement", class 0x100, superclass 0xC20; 2,154)

Old ParamBlock in reference 0 (13 parameters in all Bitmaps):

| id | key | evidence |
|---|---|---|
| 0, 1 | `u_offset`, `v_offset` | default 0; 0.15, -0.14, ... |
| 2, 3 | `u_tiling`, `v_tiling` | default 1; 2, 3, 10, -1 (flipped), 0.0254 / 0.3077 (real-world sizes) |
| 4, 5, 6 | `u_angle`, `v_angle`, `w_angle` (radians) | only 6 varies: 1.5708, 3.1416, 0.7854 |
| 7 | `blur` | 1.0 default, 0.01 (the minimum) in 373 |
| 8, 9, 10, 11 | `noise_amount`, `noise_size`, `noise_levels` (int), `noise_phase` | 1, 1, 1, 0 except in the two Bitmaps with noise on (13.6, 0.581, 3, 0.35) |
| 12 | `blur_offset` | **Guess**: 0 in 1,776 |

Leaf chunks of the UVGen object:

| chunk | key | evidence |
|---|---|---|
| `0x900B` | `map_channel` | 1 in 1,770; 2 in 9, all on objects whose stack has UVW Map modifiers (base meshes only have channel 1) |
| `0x9002` | `u_tile` (bit 0), `v_tile` (bit 1) | 0x...03 in 1,766; 0 for decal-like maps. **Guess**: bit 2/3 = U/V mirror (0x...06 with tiling 1 x 7). High bits (0x50000000, 0x08000000 set in Max 2017+ files and on all "real-world size" tilings) not understood. |
| `0x9005` | `environment` | 1 in the 33 Bitmaps referenced by RenderEnvironment or a Raytrace material's environment slot |
| `0x9009` | `mapping` (raw) | 4 for texture maps, 1 for most environment maps; **Guess** = mapping type |

Noise etc. use `Placement` 0xC30 (XYZ, old ParamBlock) - not decoded.

#### Other maps (parameters in a ParamBlock2)

| Class | block | parameters |
|---|---|---|
| Checker 0x200 (130) | ref 1 | 0 soften, 1 color1, 2 color2, 3 map1, 4 map2, 5 map1_on, 6 map2_on, 7 coordinates ref |
| Noise 0x234 (386) | ref 1 | 0 color1, 1 color2, 2 map1, 3 map2, 4/5 map on, 6 size (25 default), 7 phase, 8 levels (3 default), 9 threshold_low (0), 10 threshold_high (1), 11 noise_type (**Guess**: 0 regular, 1 fractal, 2 turbulence) |
| Mix 0x230 (59) | ref 0 | 0 mix_amount (percent), 1 lower (0.3), 2 upper (0.7), 3 use_curve, 4 color1, 5 color2, 6 map1, 7 map2, 8 mask, 9-11 enables |
| Normal Bump 0x63F6A014243E22C6 (65) | ref 0 | 0 mult_spin (1.0), 1 bump_spin (1.0), 2 normal_map (51 Bitmaps), 3 bump_map, 4/5 enables, 6 method (**Guess**, always 0), 7-9 flip red / flip green / swap (**Guess**: UI order) |
| Bump 2D, Arnold noise, ... | ref 0 | Arnold parameter objects (below) |

`MapData.class_name`: `Bitmaptexture` for Bitmap (what the importer expects), `Checker`, `Noise`, `Mix`,
`Normal_Bump`; other classes keep the file's class name.

### Standard material (class 0x2, superclass 0xC00; 15,299 in 622 files)

References: 1 `Texmaps` (0x1200 / 0x1080), 2 shader (superclass 0x10B0), 3-7 ParamBlock2s, 8 sampler
("Max 2.5 Star" / "Adaptive Halton"). Most corpus Standards are the 24 untouched material-editor slots per file.

Shader classes (0x10B0): Blinn 0x38 (14,799), Phong 0x37 (302), Metal 0x39 (23), Anisotropic 0x2857F460 (140),
Oren-Nayar-Blinn 0x2857F421 (26), Strauss 0x2857F450, Multi-Layer 0x2857F470, Translucent Shader 0x2857F480.
ParamBlock2 3 parameter 0 is the shader index, matching the class in all 1,130 materials used in scenes:
0 Anisotropic, 1 Blinn, 2 Metal, 3 Multi-Layer, 4 Oren-Nayar-Blinn, 5 Phong, 6 Strauss, 7 Translucent.

**Blinn / Phong / Metal shader block** (shader reference 0; percents stored as fractions, the importer gets percent
numbers):

| id | key | evidence |
|---|---|---|
| 0 | `ambient` | 0.588 grey default; equal to 1 in 11,878 of 12,289 blocks with the lock (4) on, different in 2,695 of 2,835 with it off; often black / 0.1 grey |
| 1 | `diffuse` | 0.588 grey default; carries the varied colours |
| 2 | `specular` | 0.9 grey default (616 of 773 used Blinns) |
| 3 | `ad_texture_lock` | **Guess**: on in 771 of 773 |
| 4 | `ambient_diffuse_lock` | see 0 |
| 5 | `diffuse_specular_lock` | on in 9 blocks, all with specular == diffuse |
| 6 | `use_self_illum_color` | colour 8 is non-black in 134 blocks with 6 on and 5 with it off |
| 7 | `self_illum_amount` (%) | > 0 only in particle materials ("SparksShader", "FireFlies", "Snow") |
| 8 | `self_illum_color` | |
| 9 | `specular_level` (%) | 0 default; 5, 100 common |
| 10 | `glossiness` (%) | 10 default (265 of 773) |
| 11 | `soften` | 0.1 in 760 of 773 |

Other shaders: ids 0-2 ambient / diffuse / specular follow the same pattern for Anisotropic, Oren-Nayar-Blinn,
Translucent; Multi-Layer 0/1 and Strauss 0 (= colour) are **Guesses**.

**ParamBlock2 3** (basics): 0 shader index, 1 `wire` (on in "wire", "body wire", "grid", "Edges"), 2 `two_sided`
(on in "Leaf", "Flag", "teeth01"), 3 `face_map` (on in particle materials), 4 `faceted` (**Guess**), 5 shader name
(string).
**ParamBlock2 4** (extended): 1 `opacity` (100 % default; 0 in smoke / dust / fire particle materials with opacity
maps), 2 `filter_color` (0.5 grey), 6 `ior` (1.5); **Guesses**: 4 opacity type, 5 falloff amount, 7 wire size,
9-11 reflection dimming (11 = 3.0 default).
**ParamBlock2 5**: supersampling (not read). **ParamBlock2 7**: 1.0, 0, 0 (**Guess**: dynamics bounce / static /
sliding friction).
**ParamBlock2 6**: a 24-entry map table (0 enables, 1 maps, 2 amounts, 3 bool). Stale in 61 materials (empty or
other maps than the Texmaps object; amounts 100.0 in 1,556 materials from older files), so only a fallback.

**Texmaps object** (authoritative): reference 2i+1 = map of slot i, 2i = animated amount controller; chunk
`0x5003` = bit mask of enabled slots (equal to the table's enables in 15,238 materials, and the plausible one in
the 61 others); chunk `0x5100 + i` = amount of slot i as a fraction, absent = 1.0 (the table says 1.0 for all 927
present maps without the chunk). The bump amount default is 0.3 (13,946 materials).

Slots (key = name + `_map`, with `_map_amount` and `_map_on` in `params`):

| Shader | slots |
|---|---|
| Blinn / Phong / Metal | 0 ambient, 1 diffuse, 2 specular, 3 specular_level, 4 glossiness, 5 self_illum, 6 opacity, 7 filter, 8 bump, 9 reflection, 10 refraction, 11 displacement |
| Anisotropic | 1 diffuse, 11 bump, 12 reflection, 13 refraction, 14 displacement |
| Oren-Nayar-Blinn | 1 diffuse, 10 bump, 11 reflection, 12 refraction, 13 displacement |
| Multi-Layer | 1 diffuse, 17 bump, 18 reflection, 19 refraction, 20 displacement |
| Strauss, Translucent | **Guess**: 0 (Strauss) / 1 (Translucent) diffuse only |

Evidence: Blinn/Phong slot 1 "_Diffuse" files and 120 Checkers; 2 "_specular"; 3 "specular.jpg" and 4 "gloss.jpg"
(troll_cleric29); 5 "emissive.jpg" and Falloff maps; 6 "_Alpha" files and Mask maps; 8 "_Bump" files and Normal
Bump maps; 9 Raytrace, Flat Mirror, "cubemap"; 10 Raytrace. Anisotropic 11 "_bmp" files; Oren-Nayar-Blinn 13
"bodydisplace.jpg"; Multi-Layer 17 a bump-like bitmap, 18 Reflect/Refract. Refraction/displacement slots of
Anisotropic and Multi-Layer and reflection/refraction of Oren-Nayar-Blinn follow the pattern (**Guess**).

### Physical Material (0xDEADC0013D6B1CEC; 2,119 in 109 files)

References: 0 ParamBlock2 (115 parameters in all), 1-2 "Ray Engine". RGBA colours (alpha dropped by the reader).

| id | key | id | key |
|---|---|---|---|
| 0 | material_mode (int) | 30 | transparency |
| 1 | base_weight | 31 | trans_color |
| 2 | base_color | 32 | trans_depth |
| 3 | reflectivity | 33 | trans_ior |
| 4 | roughness | 34-36 | **Guess** trans_roughness_lock, trans_roughness, trans_roughness_inv |
| 5 | roughness_inv | 37 | thin_walled |
| 6 | metalness | 40-44 | scattering, sss_color, sss_depth (10), sss_scale (1), sss_scatter_color (1, 0.5, 0.25) |
| 10 | refl_color | 50, 51, 52, 54 | emission, emit_color, emit_luminance (1500), emit_kelvin (6500) |
| 11 | diff_roughness | 60-66 | coating, coat_color, coat_roughness, coat_roughness_inv, coat_affect_color, coat_affect_roughness, coat_ior |
| 12-15 | brdf_mode, brdf_low (0.05), brdf_high (1.0), brdf_curve (5.0) | 230-232 | bump_map_amt (0.3), clearcoat_bump_map_amt (0.3), displacement_map_amt |
| 20-23 | **Guess** anisotropy, anisoangle, aniso_mode, aniso_channel | | |

Evidence from names: metalness 1.0 in "Metal", "chrome", "Wheels", "Metal - Steel, Polished"; transparency 1.0 in
"Solid Glass"/"Glass", 0.85 in "Windows_Glass"; trans_ior 1.33 in "water"; thin_walled on in window glass;
roughness 0.6 with inv off in "Wall Paint", "Laminate - Linen,Matte", 1.0 / 0.9 with inv on (glossiness) in
"Chrome metal", "Metal - Steel, Polished", "Mirror"; emission 1.0 in "Template Plankton shader"; a Standard
converted to Physical ("Standard_1", glossiness 10) has roughness 0.1 with inv on.

Maps: 100-120 = `base_weight_map, base_color_map, reflectivity_map, refl_color_map, roughness_map, metalness_map,
diff_rough_map, anisotropy_map, aniso_angle_map, transparency_map, trans_color_map, trans_rough_map,
trans_ior_map, scattering_map, sss_color_map, sss_scale_map, emission_map, emit_color_map, coat_map,
coat_color_map, coat_rough_map`, enabled flags 150-170 (a map is never present with its flag off). Evidence: 101
holds 319 Bitmaps, 104 Tiles/Falloff, 110/114 Color Correction, 117 "emissive.jpg". 130 `bump_map` (Bitmap,
Noise, Smoke, Tiles), 131 `coat_bump_map`, 132 `displacement_map` (Noise masks on petals), 133 `cutout_map` (a Mix
on "feather"); flags 180-183. 131-133: **Guess** from order. 250-270: a second map table; when set (62 times) always
the same as 100-120: ignored.

### Arnold Standard Surface (0x62F74B4C7E73161F; 837 in 34 files) and other Arnold classes

Reference 0 is a ParamBlock2 whose parameter 0 is a table of three `aiPBParameter` objects (class
0x3DE3000E38E67D6E, superclass 0x200; 177,824 in 41 files) - groups named "results", "parameters",
"connections". "parameters" and "connections" reference parallel parameter objects with identical values and
maps in all 837 materials; the reader uses "parameters". One object per parameter:

```
0x0001  name (UTF-16): "base_color", "base_color.connected", "base_color.shader", "specular_IOR", ...
0x0002  u32 type: 0 float, 1 int, 2 RGB, 3 vector, 4 bool (u32), 15 shader, 21 group, 23 RGBA
0x0009  u32 (1 when a shader is connected, 0x67 = child count in groups)
0x0003  container: 0x0004 u32 1, 0x0005 u32 0xFFFFFFFF (always), 0x0006 value
```

A shader parameter's map is the object's reference 0 (650 connected shaders: Bitmap in `base_color.shader`
(344), `bump_map.shader`, Bump 2D in `normal.shader` (112), Complex IOR in `specular_color.shader`, ...). Groups
reference their members (also listed in `0x0006`). The same structure is used by Bump 2D, Complex IOR, Standard
Hair, noise, composite and other Arnold classes. Keys: name lower-cased, "." -> "_": `specular_IOR` ->
`specular_ior`, `base_color.shader` -> map key `base_color_shader`, `.connected` -> `<key>_shader_on`.

### Multi/Sub-Object (0x200 / 0xC00; 320 in 202 files)

References: 0 ParamBlock2, i+1 = sub-material i; chunk `0x4002` = count (equal to the tables' length in all 320).
ParamBlock2: 0 table:material (empty/stale in 131 materials: the references are authoritative), 1 table:bool
(enabled), 2 table:string (slot names), 3 table:int (material IDs).

IDs are 0-based on disk (287 lists start at 0, 32 at 8; all unique). Checked against meshes: of 1,064 meshes
using a Multi/Sub-Object material, the stored (0-based) face IDs are all in the stored list for 1,029; with 1
added for only 647 - never the other way round. `sub_ids` = stored + 1 (the UI's IDs, matching `MeshData`'s
1-based face IDs). The 35 meshes with IDs outside the list rely on Max's wrap rule.

### Two-material classes

| Class | references | ParamBlock2 0 |
|---|---|---|
| Blend 0x250 (42) | 1, 2 materials, 3 mask map | 0 mix_amount (percent), 1 lower, 2 upper, 3 use_curve, 4 int, 5/6 the materials, 7 mask, 8-10 enables (**Guess**) |
| Double Sided 0x210 (4) | 1 front, 2 back | 0/1 materials, 2/3 enables, 4 translucency |
| Top/Bottom 0x100 (5) | 1 top, 2 bottom | 0/1 materials, 2/3 enables, 4 blend, 5 position, 6 coordinates |
| Shellac 0x46EE536A (3) | 1 base, 2 shellac | 0/1 materials, 2 shellac colour blend (percent) |

### ParamBlock2 strings

Strings in `0x100E` records (Max 2013+) are UTF-16LE with a byte length (18,145 corpus values), in `0x000E`
records 8-bit (881); the parameter block reader (§5.1) decodes both.

### Not decoded (names and directly referenced maps only)

Arch & Design (246), Raytrace (67, old ParamBlock + "Texmaps RaytraceMtl"), Ink 'n Paint (44), Autodesk Material
(39), Composite material (9), Matte/Shadow (9), mental ray, ProMaterials, Architectural, Standard Hair, DirectX
Shader, Advanced Lighting Override.

## 8. Lights and cameras

Decoder: `maxfile/objects/lights.py` (`LightData`, `CameraData`). Established on the local corpus: 502 lights and
252 cameras (754 objects in 249 files, 832 nodes); **all 754 decode**. Parameter names are the lower_snake_case
names the importer (`mx_io_max.lights.light_from_params` / `camera_from_params`) reads; units are left as in the
file (scene units, degrees, mm) unless stated. Every parameter-block value is also kept in `raw`
(`"slot.param_id" -> value`), and the object's switch / marker chunks in `flags` (chunk type -> u16, None for
empty markers), so unnamed parameters can be studied without re-reading the file.

### Classes

| Superclass | Class ID | Name in file | `class_name` | Objects / files | Parameters |
|---|---|---|---|---|---|
| 0x30 | 0x1011 | Omni | `Omnilight` | 149 / 87 | old ParamBlock, 15 |
| 0x30 | 0x1012 | Target Spot | `Targetspot` | 172 / 92 | old ParamBlock, 18 |
| 0x30 | 0x1014 | Free Spot | `Freespot` | 4 / 3 | old ParamBlock, 19 |
| 0x30 | 0x1013 | Free Direct | `Directionallight` | 4 / 3 | old ParamBlock, 19 |
| 0x30 | 0x1015 | Target Direct | `TargetDirectionallight` | 14 / 12 | old ParamBlock, 18 |
| 0x30 | 0x0B025CF032375FCC | Free Light | `Free_Light`, shape point | 60 / 7 | 5 ParamBlock2 |
| 0x30 | 0x72CD4259658D4F97 | Target Light | `Target_Light`, shape point | 3 / 1 | 5 ParamBlock2 |
| 0x30 | 0x105A1A4736507D92 | Free Rectangle | `Free_Light`, shape rectangle | 16 / 8 | 5 ParamBlock2 |
| 0x30 | 0x70AE52F271794F9D | Target Rectangle | `Target_Light`, shape rectangle | 4 / 3 | 5 ParamBlock2 |
| 0x30 | 0x0C4F430E5BCC6D42 | Free Disc | `Free_Light`, shape disc | 1 / 1 | 5 ParamBlock2 |
| 0x30 | 0x201758B338732348 | Target Disc | `Target_Light`, shape disc | 6 / 4 | 5 ParamBlock2 |
| 0x30 | 0x1ABB6B327CA93582 | Free Sphere | `Free_Light`, shape sphere | 4 / 2 | 5 ParamBlock2 |
| 0x30 | 0x0A327AAF46F634E3 | Free Cylinder | `Free_Light`, shape cylinder | 1 / 1 | 5 ParamBlock2 |
| 0x30 | 0xCA131D056705F00D | Arnold Light | `Arnold_Light` | 25 / 10 | ParamBlock2, ~58 |
| 0x30 | 0x522E47057BF61478 | Skylight | `Skylight` | 6 / 6 | ParamBlock2, 10 |
| 0x30 | 0x716F5B2527FE329C | Sun Positioner | `Sun_Positioner` | 21 / 21 | ParamBlock2, 26 |
| 0x30 | 0x25E2112471503BBB | mr Sun | `mr_Sun` (raw only) | 6 / 2 | ParamBlock2, 17 |
| 0x30 | 0x799B5B5626EE3350 | mr Sky | `mr_Sky` (raw only) | 6 / 2 | ParamBlock2, 24 |
| 0x20 | 0x1001 | Free | `Freecamera` | 73 / 58 | old ParamBlock, 9 |
| 0x20 | 0x1002 | Target | `Targetcamera` | 112 / 99 | old ParamBlock, 9 |
| 0x20 | 0x28E8008D46697218 | Physical | `Physical` | 67 / 46 | ParamBlock2, 53 |

The photometric shape classes are given the importer's `Free_Light` / `Target_Light` with a `shape` parameter
(`source_class` keeps the file's name). The shape follows from the class: verified by the emitter outline in chunk
0x0858 of the light (three f32 per point): a single point at the origin on all 63 Free / Target Light, the four
corners of the rectangle on all 20 rectangles (empty on discs, spheres, cylinders). Target Sphere / Cylinder and the
line lights don't occur in the corpus (class IDs unknown).

### Targets

A light or camera with a target has a **Look At** transform controller (class 0x2006, superclass 0x9008) with
references 0 = target node, 1 = position controller, 2 = roll (float controller), 3 = scale controller. Verified:
all 393 Look At light / camera nodes point at a node whose object is "Target" (0x1020, superclass 0x10) and whose
node flags have bit 14 set, which supports the `Node.is_target` guess: 407 nodes have bit 14, all with a "Target"
object; 399 of them are aimed at by a Look At (393 by lights / cameras, 5 by helpers, 1 by a node without object),
the other 8 are orphans. No light / camera node with another transform controller has a target. Look At is also
used by 11 helper / geometry / empty nodes aiming at nodes without bit 14 (9 Dummies, 2 "Target" objects).

`target_node` = object index of the target node of the first node instancing the light / camera (instanced lights
can have different targets; a warning says so, and `target_node_of(scene, node)` gives each node's).
`target_distance` of targeted objects is measured between the node and its target (`target_distance_of`): the
Look At node's position comes from its position controller, since Look At itself isn't decoded. Verified: equals
the stored target distance of 47 of 48 targeted Physical cameras (the 48th is animated) and 3 of 4 targeted Arnold
lights; Target cameras don't keep their stored value up to date (0 on 77 of 112).

### Standard lights (Omni, spots, directs)

References: 0 old ParamBlock (below), 2 projector map (one Target Spot with a Gradient Ramp; guess), 3 shadow
generator (`shadow_generator`: Shadow Map 320, Ray Traced Shadows 17, Area Shadows 3, Adv. Ray Traced 3), 4 a
second old ParamBlock (5 values: 1/0, 1000/0, 0, 10000/0, 10000/0; meaning unknown), 5 sometimes a second Shadow Map.

| Omni | Spot / Direct | Name | Type | Evidence |
|---|---|---|---|---|
| 0 | 0 | `color` | point3 | white on 53/149 Omni, 113/172 Target Spots; Bezier Color when animated |
| 1 | 1 | `multiplier` | float | 1.0 on 62 Omni, 82 Target Spots |
| 2 | 2 | `contrast` | float | Guess: 0-100, default 0 |
| 3 | 3 | `soften_diffuse_edge` | float | Guess: 0-100, 50 or 0 |
| - | 4, 5 | `hotspot`, `falloff` | float | 43 / 45 on 147 / 144 of 172 Target Spots, hotspot <= falloff on all 194 spots / directs. Spots: full cone angle in **degrees** (max 100). Directs: beam radius in scene units (values up to 908) |
| - | 6 | `aspect` | float | Guess: always 1.0 |
| 4, 5 | 7, 8 | `near_atten_start`, `near_atten_end` | float | defaults 0 / 40; edited on 12 of 13 lights with "use near" set, on 29 of 330 without |
| 6, 7 | 9, 10 | `far_atten_start`, `far_atten_end` | float | defaults 80 / 200; edited on 30 of 30 lights with "use far" set, on 22 of 313 without |
| 8 | 11 | `decay_start` | float | default 40; edited on all 11 lights with a decay type, on 15 of 332 without |
| 9 | 12 | `shadow_color` | point3 | Guess: black on all but 4 |
| 13 | 16 | `shadow_density` | float | Guess: 1.0 on 328 of 343, 0.25-2 |
| - | 18 (free only) | `target_distance` | float | Guess: default 240 (like the photometric lights'); 8 lights |
| 10-12, 14 | 13-15, 17 | - | int, float, float, int | unknown (0/1, 1.0, 1.0, 0) |

Switches: `u16` leaf chunks of the light object, 1 = on.

| Chunk | Name | Evidence |
|---|---|---|
| 0x2580 | `on` | 145/149 Omni, 170/172 Target Spots; off on both Omni of Lighting-Vertex.max (lighting baked into vertex colours) |
| 0x2570 | `cast_shadows` | Guess (pattern only): set on the Cornell box's "Main Light", clear on its fill lights; 115/172 spots, 23/149 Omni |
| 0x2561 | `use_near_atten` | see the attenuation values above |
| 0x2562 | `use_far_atten` | see the attenuation values above |
| 0x25D0 | `decay_type` | present only on the 11 lights whose decay start was edited; 1 = `"inverse"`, 2 = `"inverse_square"` (Guess: order of the UI list); absent = `"none"` |
| 0x25B0 (empty) | `affect_diffuse` = False | Guess: on two "luz brillo" ("highlight light") Omni |
| 0x25B1 (empty) | `affect_specular` = False | Guess: on 20 fill lights ("Omni - Fill01", ...) and the Cornell box's coloured fills |
| 0x2560, 0x2571 (0/1/0xFFFF), 0x2572, 0x2573 (spots / directs, always 1), 0x2590, 0x25A0, 0x2700, 0x2575 (empty) | - | unknown; in `flags` |

Container 0x2800 (children 0x03E9, 0x03EC u32, 0x03EA) is on every standard light: probably the include / exclude
list (not decoded).

### Photometric lights

References: 0 main ParamBlock2, 1 shadow parameters, 2 spotlight cone, 3 photometric web, 4 shadow generator,
5 shape / target distance.

| Slot.ID | Name | Type | Evidence |
|---|---|---|---|
| 0.1 | `distribution` | int | 0 `"uniform_spherical"`: 54 of 60 Free Light, all spheres / cylinders; 2 `"uniform_diffuse"`: 15 of 20 rectangles and the lights named "*Area*"; 1 `"spotlight"`: the two lights with an edited cone (75 / 178) and the disc spots of LightGallery; 3 `"web"`: the "...-ies-..." / "wallwash" / floor lights of IES lights_ART.max, which reference a web file |
| 0.2 | `on` | bool | Guess: always true |
| 0.3 | `cast_shadows` | bool | Guess: false on one light |
| 0.5 | `rgb` | rgb | filter colour; white on 92 of 95 |
| 0.6 | `intensity` | float | 1500 on 69 of 95 (Max's default 1500 cd) |
| 0.8, 0.10 | `kelvin`, `use_kelvin` | float, bool | kelvin 3600 by default; 6500 / 2800 / 5000 exactly on the 7 lights with use_kelvin |
| 0.13 | `lux_at_distance` | float | 1 m in **scene units** by default (39.37008 / 100 / 3.28084 / 1000 in inch / cm / foot / mm scenes); edited only on lights with lux units |
| 0.14 | `intensity_type` | int | 1 `"candelas"` on 84 (the default unit); 2 `"lux"` on the 11 lights whose "at distance" was edited; 0 `"lumens"` (Guess: the remaining unit) |
| 0.16 | - | float | 1500, or the web file's intensity on web lights (8100, 7728) |
| 0.18, 0.19 | `use_dimmer`, `dimmer` | bool, float (percent) | Guess |
| 0.23, 0.24 | - | world | 80 / 200: far attenuation start / end like the standard lights (not named) |
| 2.0, 2.1 | `hotspot`, `falloff` | float | full cone angles in degrees; defaults 30 / 60 |
| 3.0 | `web_file` / `web_file_asset` | filename | stored as an **asset reference**: the record's value is 0xFFFFFFFE and is followed by a 0x000F container whose 0x0002 child is a 16-byte GUID; `web_file_asset` is that GUID as hex. The GUID is found in the `FileAssetMetaData3` stream followed by `u32` length + UTF-16 strings: type ("Photometric"), relative path, absolute path (checked on IES lights_ART.max: `...\photometric\30.IES`). Only given for web distributions |
| 3.1-3.3 | `web_rotate_x/y/z` | float | Guess: degrees (0 but one 90) |
| 5.7 | `target_distance` | float | free lights; default 240. Targeted lights: measured instead (5.7 is stale: 240 on 13 of 13) |
| 5.12, 5.11 | `length`, `width` | world | rectangles; verified on all 20 against the outline in 0x0858: 5.12 is the extent along local **X**, 5.11 along local Y (e.g. 66.33 x 5.906 with corners at x = +-33.165, y = +-2.953). `length` = X so the importer's Blender `size` (X) is right |
| 5.13 | `radius` | world | discs and spheres: the only size edited on them (defaults 5.5 / 2) |
| 5.11 | `length` (cylinder) | world | Guess (one cylinder with default sizes) |

Slot 1 (shadow parameters, 9 values: bool, 100, 100, density 1.0, bool, colour black, bool, bool, shadow map) is kept
in `raw` only.

### Arnold Light

| ID | Name | Evidence |
|---|---|---|
| 18 | `type` | 6 `"skydome"` on the two "*Skydome" lights; 2 `"spot"` on the three targeted lights with an edited cone and the light converted from a photometric spotlight; 3 `"quad"` on "ArnoldLightQuad-001" and the four "ArnoldPortal*"; 8 `"mesh"` on the four lights referencing a mesh node; 5 `"cylinder"` on the light converted from a photometric cylinder. Guess for 0 point, 1 distant, 4 disk, 7 photometric |
| 1, 2 | `targeted`, `target_distance` | targeted exactly on the 4 Look At nodes; distance matches 3 of 4 (the 4th converted from a photometric light keeps 240) |
| 33, 34 | `quad_x`, `quad_y` | equal the X / Y extents of the photometric rectangles they were converted from (ART Studio / Arnold Studio) |
| 52 | `spot_cone_angle` | degrees; default 60, edited on spots only |
| 48 | `mesh_node` | node reference of mesh lights |
| 0, 4, 7, 8, 10, 11, 12 | `on`, `color`, `use_kelvin`, `kelvin`, `intensity`, `exposure`, `cast_shadows` | Guess from defaults (intensity 1, exposure 8 on quads, kelvin 6500 / 3600 / 4200 with use_kelvin on the edited ones) |

The importer has no Arnold conversion yet; Arnold's own convention is radiance = `color * intensity * 2^exposure`.

### Skylight, Sun Positioner, mr Sun / Sky

Skylight (Guess names from defaults): 0 `color` (0.95, 0.95, 1), 2 `sky_map` (texmap reference), 3 `on`, 4
`rays_per_sample` (20), 10 `multiplier` (1 / 1.5); 11 = 0.005 (ray bias?), 7 int 0/1 (sky colour source?).

Sun Positioner, verified: 16 / 17 are the Julian day and second of the day (2457925 / 43200 = 21 June 2017,
12:00) and agree with `year` 8, `month` 7, `day` 6, `hour` 4, `minute` 5 on all 21; `latitude` 12 / `longitude` 13 /
`time_zone` 9 = 37.795 / -122.394 / -8 (San Francisco, the default location); `azimuth` 18 / `altitude` 19 =
128.71 / 69.17 degrees, the sun's position there at 12:00 daylight-saving time (`daylight_saving` 10); IES
lights_ART.max: Chicago 21:30, altitude -9.8 (after sunset). Guess: `north_direction` 14 (degrees),
`compass_radius` 1, `sun_distance` 2 (world). `sun_direction` (unit vector towards the sun) assumes north = +Y
turned counter-clockwise by `north_direction` (sense unverified).

mr Sun / mr Sky: parameters in `raw` only.

### Cameras

Free / Target camera, old ParamBlock (slot 0):

| ID | Name | Evidence |
|---|---|---|
| 0 | `fov` | radians in the file, **given in degrees**; 0.7854 (45 degrees, the default) on 93 of 112 Target and 45 of 73 Free cameras |
| 1 | `target_distance` | Free cameras: default 160 (18 of 73). Target cameras: measured from the target instead |
| 2, 3 | `near_clip`, `far_clip` | defaults 1 / 1000 (scaled by unit rescaling: 0.3937 / 393.7) |
| 4, 5 | `near_env_range`, `far_env_range` | defaults 0 / 1000 |
| 6 | `multipass_effect` | Guess: 1 on 10 of the 14 cameras whose effect is Motion Blur, 0 on all 171 with Depth of Field |
| 8 | `fov_type` | Guess: always 0 = `"horizontal"` |

Slot 2: the multi-pass effect (`effect`: Depth of Field 171, Motion Blur 14); slot 1 sometimes an old ParamBlock
(int 1, float 2.0). Marker chunks: 0x2682 on all 112 Target cameras and no Free camera; 0x2684 (8), 0x2686 (1),
0x2688 (4), 0x268A (4), 0x268C (7) are probably the orthographic / clip-manually / show cone / horizon / ranges
check boxes but couldn't be told apart (0x268A is on both cameras with edited environment ranges; 0x268C on the
"FaceHUD" and "hand controls" cameras); `orthographic` and `clip_on` are therefore **not** given.

Physical camera, ParamBlock2 (slot 0):

| ID | Name | Evidence |
|---|---|---|
| 0 | `targeted` | true exactly on the 48 Look At nodes |
| 8 | `target_distance` | equals the measured distance on 47 / 48 (measured value used) |
| 4 | `film_width_mm` | 36 on 66 of 67 |
| 5 | `focal_length_mm` | default 40 |
| 6 | `f_number` | default 8; 1.0 on the two DOF_* sample cameras |
| 47, 48, 49 | `clip_on`, `near_clip`, `far_clip` | clip_on set exactly on the 5 cameras whose near / far differ from the defaults |
| 50, 51 | `near_env_range`, `far_env_range` | defaults 0 / 1000 |
| 7 | `zoom_factor` | Guess: always 1 |
| 9, 10 | `focus_distance` | Guess: 9 = custom focus distance (5 m by default), used when 10 = 1 (one camera, with an edited value); otherwise `focus_distance` = target distance |
| 11 | `use_dof` | Guess: the two DOF_* cameras and the Underwater one |
| 1, 20 | `specify_fov`, `fov` | Guess: specify_fov on 4 cameras imported from other applications ("Views: ...", "3D View: ..."); fov in degrees |
| 18 | `motion_blur` | Guess (MotionBlur-DragonFlying_Arnold.max) |
| 15, 24, 27 | `shutter_duration`, `exposure_value`, `white_balance_kelvin` | Guess: 0.5 frames, EV 6 / 14.75 / 10, 6500 K defaults |

## 9. Shapes

Module: `maxfile/objects/shapes.py`. Every decoder returns `ShapeData` (kind, `splines` of `ShapeKnot`s, source
`"stored"` / `"glyphs"` / `"generated"`, `params`, `steps` / `optimize` / `adaptive`, `rendering`,
`approximate`, `animated`, `param_block`). Knots and handles are absolute object-space positions in scene units.

Corpus: 840 shape objects. The 9 decoded classes cover 837 of them; all 837 decode without a warning, and all but
one (an empty SplineShape in HeadHudAnible.max) have at least one spline. Not decoded: CV Curve
(0x12A822FB76A11646), LinkLeaf, PolymorphicGeom (one object each).

| Class | Class ID | Objects / files | Splines from | Verified |
|---|---|---|---|---|
| Line | 0x1040 | 303 / 65 | stored (`0x2000` > `0x1010`) | yes |
| Text | 0x1993 | 228 / 38 | glyph cache, laid out | yes (single-line layout) |
| SplineShape (editable spline) | 0xA | 131 / 24 | stored (`0x1010`) | yes |
| Rectangle | 0x1065 | 93 / 10 | generated | yes |
| Circle | 0x1999 | 60 / 16 | generated | yes |
| Angle (extended spline) | 0x93257030 | 14 / 3 | generated (L section) | no |
| Star | 0x1995 | 4 / 3 | generated | partly |
| NGon | 0x1050 | 3 / 2 | generated | no |
| Donut | 0x1060 | 1 / 1 | generated | no |

All registered for superclass 0x40; the registry already knows all nine classes.

### Spline (`0x1010` container)

Children, in this order on all 2,173 corpus splines (409 in Lines, 498 in SplineShapes, 1,266 in Text glyphs):

| Chunk | Content |
|---|---|
| `0x2900` | u32 knot count |
| `0x2904` | u32, 0 on every spline (unknown) |
| `0x290A` | 52 bytes per knot (size = 52 x count on all 2,173) |
| `0x290D` | u32 closed flag (1 on all 1,266 glyph outlines; 151 / 258 Lines closed / open) |

Knot record (21,515 knots):

```
u32 knot_type, u32 segment_type, f32 u, f32[3] position, f32[3] in_handle, f32[3] out_handle, u32 aux
```

- Field order: a straight two-knot Line has its out handle at 1/3 and the next knot's in handle at 2/3; corner
  knots of converted rectangles have handles 1/3 of the way to the neighbours.
- `knot_type`: 0 smooth (the handle direction of all 424 interior type-0 knots is parallel to next - previous
  knot: automatic tangents), 1 corner (5,431 of 6,116 have their in handle 1/3 of the way to the previous knot), 2 Bezier
  (handles colinear on 10,492 of 10,514 knots with two non-zero handles), 3 Bezier corner (independent handles).
- `segment_type` of the segment leaving the knot: 1 = line (all 580 such segments are straight, handles at
  1/3 / 2/3), 0 = curve. Lines (class 0x1040) only use 0.
- `u` is 1 / (number of segments) on all 21,515 knots: derived, ignored.
- `aux`: 0 on most knots; otherwise multiples of 0x10000 up to 0x200000 (233 knots). Guess: high 16 bits =
  0-based material ID of the segment (a Line with values 0, 1, 2 in wall.max carries a Multi/Sub-Object
  material). Exposed as `ShapeKnot.material_id`.

### Bezier shape (container of splines)

`0x1010` spline containers, then `0x1020` / `0x1030` / `0x1040` (selection bit arrays: `0x1000` count, `0x1010`
> `0x2700` u32 bit count + bits; guess), `0x1050` (repeats the steps on 414 of 434 Line/SplineShape objects,
0xFFFFFFFF on 20), `0x1060`, `0x1070`, `0x1080`, `0x1090`, `0x1100` (empty), `0x2000` (24 bytes). Only the
splines are read.

- SplineShape: the object's own `0x1010` child.
- Line: inside the object's `0x2000` container.
- Text: inside each glyph entry (`0x1030` > `0x1020`).
- Also seen in Edit Spline modifier data (derived object `0x2500` > `0x2512` > `0x1000` > `0x1040`), not decoded
  here.

Line / SplineShape object chunks around the Bezier shape (Line: inside `0x2000`; SplineShape: top level):
`0x7FC2` > `0x0010` (u32 4), `0x2000` (u32 1), `0x1001` (28 bytes, an empty box), `0x10A0`, the Bezier shape,
`0x1060` **steps** (0-80; 240 Lines at the default 6), `0x1090`, `0x10B0`, `0x10C0` **optimize** (300 of 303
Lines on), `0x10D0` **adaptive** (guess from its position: 0 on all objects), `0x1080` (f32 0.1).
SplineShapes may add `0x21B0` (25 objects). References: slot 0 rendering ParamBlock, slot 1 "Master Point
Controller"; 5 objects animate vertices (Bezier Point3 controllers in slots 3, 6, 9, ...): `ShapeData.animated`,
only the static knots are given.

### Parameter blocks of parametric shapes

Rectangle, Circle, NGon, Star, Donut, Text: old ParamBlocks in slots 0 (rendering), 1 (shape), 2
(interpolation). Angle: slots 0 and 2 the same, slot 1 empty, shape parameters in a ParamBlock2 (block id 30) in
slot 3. None of these cache a spline.

Interpolation block (slot 2, all 403 objects): id 0 `steps` (int, 0-7 seen), 1 `optimize` (int 0/1), 2
`adaptive` (int 0/1). Verified by values (defaults 6 / 1 / 0, Circles with adaptive on and optimize off).

| Class | id: name (type) | Evidence |
|---|---|---|
| Rectangle | 0 `length` (float, along Y), 1 `width` (float, along X), 2 `corner_radius` | ModContext box matches on 74 derived objects; the converted copy of a 60 x 216 r 6 rectangle |
| Circle | 0 `radius` | ModContext box = +-radius on 5 objects |
| NGon | 0 `radius`, 1 `sides` (int), 2 `circular` (int), 3 `corner_radius`, 4 `inscribed` (int) | guess for 2 and 4 (0 and 1 on all 3 objects) |
| Star | 0 `radius1`, 1 `radius2`, 2 `points` (int), 3 `distortion` (degrees, guess), 4 `fillet_radius1`, 5 `fillet_radius2` | 4 objects; 3-5 guessed |
| Donut | 0 `radius1`, 1 `radius2` | 1 object |
| Text | 0 `size`, 1 `kerning`, 2 `leading` | layout matches ModContext boxes (below) |
| Angle (pb2) | 0 `length`, 1 `width`, 2 `thickness`, 3 `sync_corner_fillets` (bool), 4 `corner_radius1`, 5 `corner_radius2`, 6 `edge_radii` | guess (14 objects, identical values) |

### Generated splines

All in the XY plane, centred on the origin, counter-clockwise.

- Circle: 4 Bezier knots from (r, 0), handles `KAPPA` r along the tangent, `KAPPA = 0.5517862` — measured on
  circles converted to editable splines (`21.658056 / 39.250813`, `4.051059 / 7.341718`), which also give the
  start knot, direction and knot type.
- Rectangle: 4 corner knots from (w/2, l/2), handles at 1/3; with a corner radius 8 Bezier-corner knots from
  (w/2, l/2 - r), all handles `KAPPA` r along the outline. Verified knot for knot (positions and handles) against
  the converted copy of the "Shade" rectangle in LightGallery_Max2018_ART.max.
- Star: 2 x points corner knots, radius1 at angle pi / points + 2 pi k / points, radius2 half-way between, turned
  by the distortion. Guess; the one usable ModContext box (12 points, radius 8: box +-8 cos 15 degrees) rules out
  a point on an axis. Fillets are not generated (`approximate`).
- NGon: corner knots from angle 0 (guess); circumscribed scales the radius by 1 / cos(pi / n); circular uses
  Bezier knots; the corner radius is not generated (`approximate`).
- Donut: two circles (guess: both counter-clockwise).
- Angle: an L section (guess); fillets / edge radii not generated (`approximate` on all 14).

### Text

| Chunk | Content |
|---|---|
| `0x1005` | font name: u32 byte length, UTF-16LE with NUL ("Arial" on 220 objects) |
| `0x1015` | text: same encoding, lines separated by `\r\n` |
| `0x1030` | one glyph entry per distinct character, in order of first use (all 228 objects): `0x1000` u32 code, `0x1010` f32 advance, `0x1020` Bezier shape (outline, closed splines) |
| `0x1035` | u32 count, then per character u32 code + u8 flags (3 on CR, 5 on LF, else 0); equals the string on 226 objects, the other two use code 0x13 whose glyph is a real digit |
| `0x2020` | empty; `0x1080` u32 (0, or 1 on 3 objects: unknown, maybe style); `0x2010` u32 2 |

Glyph units: ascent + descent = 1000 (Arial's digits advance 498 = 1139 / 2288 x 1000, cap height 641-644).
Layout (`layout_text`), verified on 12 Text objects whose bottom modifier's ModContext box matches exactly (sizes
0.27-100, kerning 0-7.3, 5 files): scale = size / 1000, each glyph advanced by advance x scale + kerning,
baseline at y = 0, the whole text centred on x = 0 by its knot bounding box (not shifted in y). Guess: CR (or
a lone LF) starts a new line `size + leading` lower, left-aligned; CR / LF glyphs (the missing-glyph box) are
not drawn.

### Rendering block (slot 0 of every shape, old ParamBlock, 23 parameters)

| id | name | type | evidence |
|---|---|---|---|
| 0 | thickness | float | changed together with id 6 on directly rendered shapes |
| 1 | sides | int | 3-36, default 12 |
| 2 | angle | float, degrees (guess) | values 0, 66.0 |
| 3-5 | viewport thickness / sides / angle | | changed when id 8 is on |
| 6 | renderable ("enable in renderer") | int | on for shapes used directly by nodes with changed thickness |
| 7 | display_render_mesh ("enable in viewport") | int | guess |
| 8 | use_viewport_settings | int | see 3-5 |
| 9 | generate_mapping_coords | int | guess |
| 10 | real_world_map_size | int | guess (1 on all but 4) |
| 11 | rectangular | int | guess: on for the 8 objects with non-default rectangular values |
| 12 / 13 / 14 / 15 | rectangular width (2.0) / length (6.0) / angle / aspect lock | | guess from defaults |
| 16-19 | the same for the viewport | | guess |
| 20 | auto_smooth | int | guess (precedes the threshold) |
| 21 | auto_smooth_threshold | float, radians | 40 degrees on 831 objects |
| 22 | unknown | int | always 0 |

`ShapeRendering` converts angles to radians; `values` holds every parameter by name.

### ModContext bounding box (used for verification)

A derived object's `0x2500` container per modifier holds `0x2510` (a 13-float matrix + u32) and `0x2511` (six f32:
min xyz, max xyz). The bottom modifier's box is the object-space box of the shape when the modifier was applied.
It is shared between objects when a modifier instance is (Cereal.max: 7 shapes, one box), and covers only the
selection when sub-objects were selected (single points, or 1e30 for an empty selection), so it can't be used
blindly.

## 10. Open questions

- Node flags: hidden / frozen / group bits are inferred from node roles only; a pair of files differing in one state
  would settle them. Render / display properties in the other node chunks are not decoded.
- Euler XYZ rotation order (only single-axis rotations were discriminating).
- Animation (keys in `0x2520`-`0x2528`) is out of scope.
- Parameter IDs are per class and worked out one class at a time; classes not listed above keep their parameters
  in `ParamBlockData` without names.
- The meaning of several always-present chunks (Editable Poly `0x0150`-`0x0130`, `0x0310`, Editable Mesh `0x23A0`,
  ParamBlock2 header words, modifier context `0x2513`).
- Files older than Max 2008 (no corpus files): the class directory may be called `ClassDirectory`, and other layouts
  may differ.

[MS-CFB]: https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-cfb/
