# .max format overview (from prior art)

This is what the existing GPL importer **`io_scene_max` 1.9.2** (Sebastian Sille / NRGSille, with
Jens M. Plonka and Philippe Lagadec; extensions.blender.org, archive SHA-256
`ae11b890…ef77b43`) reveals about the `.max` format. Line references are to `import_max.py` in that release.

**Nothing here has been checked against real files by this project yet.** It describes what that importer's
code *assumes*. Each assumption gets verified with `maxdump` (ROADMAP Phase 2b) on corpus files before a decoder
relies on it. Open points are collected in [To verify](#to-verify) at the end.

Conventions: all integers are little-endian. `u16`/`u32`/`u64` are unsigned, `f32` is an IEEE float.
Chunk type IDs are written as `0x0962`.

## 1. Container

A `.max` file is a **Compound File Binary** (OLE2 / "structured storage") file, as documented publicly by
Microsoft in [MS-CFB]. It starts with the signature `D0 CF 11 E0 A1 B1 1A E1`. The importer reads it with a
reduced copy of the `olefile` library (lines 35–560): header, FAT/DIFAT, mini-FAT, directory tree,
streams by name. It handles both 512-byte and 4096-byte sectors. Nothing in this layer is Max-specific, so our
reader can be written from the [MS-CFB] spec alone.

### Streams the importer reads

| Stream | Read as | Used for |
|---|---|---|
| `Scene` | chunk tree | All scene objects (§3). The core of the file. |
| `ClassDirectory3` (falls back to `ClassDirectory`) | chunk tree | Class table: maps a chunk's type ID to a class (§2.2). The fallback suggests older files use the un-numbered name. |
| `DllDirectory` | chunk tree | Plugin DLL table referenced by the class table (§2.3). |
| `ClassData` | chunk tree | Read but not used. |
| `Config` | chunk tree | Read but not used. Scene units may be stored here (unconfirmed). |
| `VideoPostQueue` | chunk tree | Read but not used. |
| *(asset metadata)* | special (§5.2) | Bitmap file paths in newer files. The importer doesn't look it up by name: it takes the directory entry with the highest index, capped at 11 (line 2253), which is fragile. |

## 2. Chunks

### 2.1 Chunk headers

Every stream except the asset metadata stream is a sequence of chunks (lines 714–754):

```
u16  type
u32  size          # size of the whole chunk, header included
                   # bit 31 set   -> container chunk: the payload is a sequence of child chunks
                   # bit 31 clear -> leaf chunk: the payload is raw bytes
                   # size == 0    -> extended header follows:
u64  size64        # (extended header only) same meaning, bit 63 = container flag; header is then 14 bytes
payload            # size - 6 (or size - 14) bytes
```

The meaning of a `type` depends on context: inside a scene object it is a property ID; for the direct children
of the top-level `Scene` container it is an index into the class directory (§3).

### 2.2 Compression

If a stream starts with the gzip magic `1F 8B`, the importer decompresses the whole stream with zlib in gzip mode
before parsing chunks (lines 722–729). It only does so when the next header bytes match one of three hard-coded
values, which look like specific gzip header fields (OS byte, flags). A more robust test would be "starts with
`1F 8B 08` and decompresses cleanly". The importer does not say which Max versions compress.

### 2.3 Class directory

`ClassDirectory3` is a list of container chunks, one per class used in the file. **A class's position in this
list is the type ID that scene objects of that class use** (line 846). Each entry contains (lines 650–663):

| Chunk | Layout | Meaning |
|---|---|---|
| `0x2060` | `u32 dll_index, u64 class_id, u32 superclass_id` | `dll_index` points into the DLL directory (out of range = built-in, presumably). |
| `0x2042` | UTF-16LE string | Class name. |

A Max class ID is a pair of 32-bit words; the importer reads the pair as one `u64` with the first word in the
low half. For example it lists Editable Mesh as `0x00000000E44F10B3` and Editable Poly as
`0x192F60981BF8338D`. Our class-ID registry should store the two words separately and print them in the same
form as `maxdump`, so contributors can match them up.

### 2.4 DLL directory

A list of entries with two UTF-16LE strings, chunk types `0x2037` and `0x2039` (lines 666–674). The code doesn't
say which is which (probably a description and a file name).

## 3. Scene stream and references

The `Scene` stream holds **one top-level container chunk**. Its direct children are every object in the scene
(nodes, geometry, controllers, materials, maps, parameter blocks, layers, …). For each child:

- its chunk `type` is an index into the class directory;
- its position in the list is its **object index**, which other objects use to refer to it (line 819).

References between objects (lines 906–927):

| Chunk | Layout | Meaning |
|---|---|---|
| `0x2034` | `u32[]` object indices | Ordered references: slot *i* = element *i*. |
| `0x2035` | `u32 (skipped)`, then `(u32 slot, u32 object_index)` pairs | Sparse references keyed by slot number. |

Out-of-range indices are treated as "no reference" (`0xFFFFFFFF` is presumably the explicit null). Because
references are by index, **instancing comes for free**: two nodes referencing the same geometry object index
share it. The importer ignores this and builds a separate mesh per node.

## 4. Nodes and transforms

A child of the scene is treated as a **node** when its class has class ID `0x1` and superclass ID `0x1`, or when
it has a parent chunk `0x0960` (line 2222).

Node chunks the importer uses:

| Chunk | Layout | Meaning |
|---|---|---|
| `0x0960` | `u32 parent_index, …` | Parent node's object index. |
| `0x0962` | UTF-16LE | Node name. |
| `0x096A` | `f32[3]` | Object offset position (pivot offset). |
| `0x096B` | `f32[4]` | Object offset rotation, quaternion. |
| `0x096C` | `f32[3+]` | Object offset scale (first three used). |

Node reference slots (line 1806): **0** = transform controller, **1** = object (geometry, possibly wrapped in a
modifier stack, §6), **3** = material, **6** = layer.

The importer applies the object offset to the mesh data and the controller transform to the object, relative to
the parent (lines 2194–2248). That matches Max's model: the node transform positions the pivot, and the object
offset places the geometry relative to the pivot.

### 4.1 Transform controllers

Only the static value of each controller is read; animation keys are ignored (fine for v1, see ROADMAP §2).

| Class ID | Name (per importer) | Value |
|---|---|---|
| `0x2005` | Position/Rotation/Scale | References `[position, rotation, scale]` controllers. |
| `0xFFEE238A118F7E02` | Position XYZ | Three float controllers. |
| `0x2008` | Bezier Position | `0x2503`: `f32[3]`. |
| `0x442312` | TCB Position | `0x2503`: `f32[3]`. |
| `0x4B4B1002` | Position List / Scale List | First reference used. |
| `0x2012` | Euler XYZ | Three float controllers (radians). |
| `0x442313` | TCB Rotation | `0x2504`: `f32[4]` quaternion. |
| `0x3A90416731381913` | Rotation Wire | First reference used. |
| `0x4B4B1003` | Rotation List | First reference used. |
| `0xFEEE238B118F7C01` | Scale XYZ | Three float controllers. |
| `0x2010` | Bezier Scale | `0x2501` or `0x2505`. |
| `0x442315` | TCB Zoom | `0x2501` or `0x2505`. |
| `0x2007` | Bezier Float | Child `0x7127` → `0x2501`: `f32`. |
| `0x71F11549498702E7` | Float Wire | First reference used. |
| `0x9154` | Biped slave control | Values from the biped sub-anim references. |

Quaternions (`0x2504`, `0x096B`) are reordered as `(w, x, y, z) = (q[3], q[2], q[1], q[0])` (lines 1751, 2210).
That ordering, and whether Max's rotation sign convention differs from Blender's, needs checking against
reference exports.

## 5. Materials and maps

The node's slot-3 reference is the material. The importer recognises these classes (lines 62–80, 1590–1655):

| Class ID | Material |
|---|---|
| `0x0002` | Standard |
| `0x0006` | "Legacy" (per importer) |
| `0x0200` | Multi/Sub-Object |
| `0xDEADC0013D6B1CEC` | Physical Material |
| `0x7034695C37BF3F2F` | VRayMtl |
| `0x11731B4B6066686A` | VRay2SidedMtl |
| `0x448931DD70BE6506` | CoronaMtl (legacy) |
| `0x871517206912AB89` | CoronaPhysicalMtl |
| `0x8425554E65486584` | CoronaLayeredMtl |
| `0x44CFDE95BEC41C73` / `0xCA41F54622C05DD6` | CoronaSkinMtl / CoronaHairMtl |
| `0x62F74B4C7E73161F` | Arnold Standard Surface |
| `0x329B106E27190FF4` | Raytrace |
| `0x4A16365470B05735` | Architectural |
| `0x0000000046EE536A` | Shellac |

### 5.1 Parameters

Most material parameters live in **parameter block** objects reached through the material's references.
The importer finds a parameter by scanning the block's child chunks for one whose payload starts with a `u16`
equal to the parameter index, then reads the value from the **end** of the payload: a colour is the last
`f32[3]`, an RGB(A) colour `f32[3]` at offset `len - 16`, a float the last `f32` (lines 1120–1223). Parameter
indices are hard-coded per material class (e.g. VRayMtl diffuse = `0x01`, reflection glossiness = `0x06`).

Arnold Standard Surface stores parameters differently: one referenced object per socket, with the socket name as
a UTF-16 string in child chunk `0x1` (`"base_color"`, `"metalness"`, `"base_color.shader"`, …) and the value in
child `0x3` (lines 1261–1335).

Where the material's **name** is stored differs per class: `0x4000` → first child (Standard), `0x5431` (VRayMtl),
`0x0FA0` (Corona), `0x100` → `0x4001` (Physical), or text after an `@` in chunk `0x100` (Raytrace, Arnold,
Architectural). A general rule hasn't been worked out yet.

The importer maps everything onto one Principled BSDF: diffuse, specular tint, roughness, metallic, IOR, alpha,
emission, and up to five image maps (base colour, roughness, specular, alpha, normal).

### 5.2 Bitmap paths

Two storage schemes, presumably from different Max versions (lines 1128–1175):

- **Direct:** the path is a UTF-16 string in chunk `0x1230` inside the bitmap's parameter object.
- **Asset metadata:** chunk `0x1260` (or a class `0x3333` object) holds an asset index; the path is looked up in
  the asset metadata stream. That stream isn't made of chunks: the importer splits it on `00 00 00` runs and
  pairs up headers with UTF-16 path strings (lines 608–631). This is the least understood part of the format.

The importer keeps only the file name and searches for it next to the `.max` file.

### 5.3 Multi/Sub-Object

Sub-materials are found through references (ordered or sparse). The importer appends each sub-material as a slot
and copies the per-face material IDs from the mesh straight into `material_index`. It doesn't map Max material
IDs to sub-material slots through the Multi/Sub-Object ID list, so scenes with gaps in their ID lists will be
assigned wrongly.

## 6. Geometry

### 6.1 Geometry classes

| Class ID | Object | Handling |
|---|---|---|
| `0x192F60981BF8338D` | Editable Poly | Mesh from chunk `0x08FE` (§6.2). |
| `0x000000005D21369A` | PolyMeshObject | Same as Editable Poly. |
| `0x00000000E44F10B3` | Editable Mesh | Mesh from chunk `0x08FE` (§6.3). |
| `0x10`, `0x11`, `0x12`, `0x16`, `0x19` | Primitives (`0x10` Box, `0x11` Sphere, `0x12` Cylinder per the importer) | If a `0x08FE` mesh is present, it is read like Editable Mesh (§6.3); otherwise rebuilt from parameters (§6.4). |
| `0x14`, `0x19` | Treated as Box | Parameters. |
| `0x20` | Torus | Parameters. |
| `0x00000000A86C23DD` | Cone | Parameters. |
| `0x77566F65081F1DFC` | Plane | Parameters. |
| `0x2032`, `0x2033` | Wrapper (the importer calls it "shell") | Imports the **last reference** only. Probably the modifier-stack holder ("derived object"): the base object is the last reference and the modifiers come before it. The importer never reads the modifiers. |
| `0x01BBAC5F7BC209AF` | Boolean | Imports each operand separately. |
| `0x0000000000876234` | Dummy | Empty. |
| `0x9125` | Biped object | Empty. |

Recognised but skipped: cameras (`0x1002`, target `0x1020`), lights (Omni `0x1011`, Free Direct `0x1013`,
VRayLight), splines (Line `0x1040`, Rectangle `0x1065`, Ellipse `0x1097`, Circle `0x1999`), Point helper, bones,
Particle View, CV surfaces and a few others (lines 82–100).

### 6.2 Editable Poly (`0x08FE` container)

| Chunk | Layout (per importer) | Meaning |
|---|---|---|
| `0x0100` | `u32 count`, then per vertex `u32 flags, f32[3]` | Vertices. |
| `0x011A` | `u32 count`, then per face: `u32 n, u32[n] vertex indices, u16 flags`, then optional fields by flag: `0x01` → `u16[2]`; `0x08` → `u16` **material ID**; `0x10` → `u32` (likely **smoothing groups**); `0x20` → `u32[2·(n−3)]` (likely triangulation of the polygon) | Polygons. |
| `0x0108` | `u32 count`, then per entry `u32 ?, u32 v1, u32 v2, u32 a, u32 b, u32 flags`; `b` can be `0xFFFFFFFF` | Probably edges (two vertices, two adjacent faces, `0xFFFFFFFF` on a border). The importer reads it as extra vertex indices but never uses the result. |
| `0x010A` | `u32 end`, then `u32` triples up to byte offset `end` | Triangles. Read, not used. |
| `0x0118` | container with `0x0110` (`u32 n, u32[n]`) and `0x0130` (`u16` material ID) | One face, alternative layout. |
| `0x0124` | `u32` | Map channel number (one per channel). |
| `0x0128` | `u32 count`, then `f32[3]` per map vertex | Map (UVW) vertices for that channel. |
| `0x012B` | per face `u32 n, u32[n]` | Map faces for that channel. |
| `0x0310` | per face `u32 n, u32[n]` | Polygons, alternative layout. |

Map channels are matched to coordinates and faces by order of appearance. Only U and V are used; the importer
doesn't distinguish UV channels (1+) from vertex colour (0) and illumination/alpha (−2, −1) channels.

### 6.3 Editable Mesh (`0x08FE` container)

| Chunk | Layout | Meaning |
|---|---|---|
| `0x0914` | `u32 count`, `f32[3]` each | Vertices. |
| `0x0912` | `u32 count`, per face `u32[3] vertices, u32 (likely smoothing groups), u16 flags, u16 material ID` | Triangles. |
| `0x0924` / `0x0959` | `u32` | Map channel number. |
| `0x0916` (class `0x19`) / `0x2394` (others) | `u32 count`, `f32[3]` each | Map vertices. |
| `0x0918` (class `0x19`) / `0x2396` (others) | `u32 count`, `u32[3]` per face | Map faces. |

Primitives that carry this cache are interesting for us: the cache **is Max's own topology** for those
parameters, which is exactly the ground truth our live primitives (ROADMAP Phase 1c/2c) need to match.

### 6.4 Primitive parameters

Primitive parameters are in a parameter block (first reference). The importer handles three encodings, which
suggests the layout changed between Max versions (lines 1967–2145):

1. Leaf chunk longer than 11 bytes: the value is the last `f32`.
2. Child chunk `0x100` holding the `f32`.
3. A fixed record `u16, u32, u16, u16, u8, f32, f32`, value in the last field.

Parameter order per the importer: Box = length, width, height; Sphere = radius; Cylinder = radius, height;
Torus = radius 1, radius 2; Cone = radius 1, radius 2, height; Plane = length, width. The importer then calls
Blender's own primitive operators, so segment counts and topology are Blender's, not Max's.

## 7. What `io_scene_max` doesn't cover

Relevant to our scope (ROADMAP §2):

- Modifier stacks: never read (wrapper objects reduced to their base object).
- Instances: every node gets its own mesh copy.
- Smoothing groups: read into a field and dropped.
- Multi/Sub-Object ID → slot mapping (§5.3).
- Splines, cameras, lights, environment.
- Scene units: none read; the user sets a scale factor by hand.
- Layers: the slot-6 reference is found but not used.
- Hidden/frozen state, wire colour.
- Material IDs, map channels and parameter indices are hard-coded per class with no version handling beyond the
  try/fallback chains above.
- No import report; errors are printed and swallowed (`except: pass` in several places).

## To verify

To check on real files with `maxdump` before relying on them. Each one should become a test.

1. Stream list per Max version; which streams are gzip-compressed and from which version.
2. Name and structure of the asset metadata stream (§5.2).
3. Chunk header rule for 64-bit sizes: which versions use it, and does it occur inside streams or only at the top?
4. Class directory: what `dll_index` holds for built-in classes; how the two class-ID words map onto the `u64`.
5. Node chunks `0x0960`–`0x096C`; remaining node chunks (hidden, frozen, wire colour, layer membership,
   render flags).
6. Quaternion component order and handedness (`0x096B`, `0x2504`), against a `reference.fbx`.
7. Editable Poly face flags: confirm `0x08` = material ID and `0x10` = smoothing groups; meaning of `0x01` and `0x20`.
8. Map channel numbering (vertex colour 0, UV 1+, alpha −2, illumination −1) in `0x0124`.
9. Whether `0x2032`/`0x2033` are the modifier stack holder, and how modifiers and their per-modifier data are
   stored.
10. Where scene units are stored (`Config`?).
11. Material ID base (0- or 1-based on disk) and the Multi/Sub-Object ID list.
12. A general rule for material and map names.
13. The meaning of class IDs `0x14`, `0x16`, `0x19`.

[MS-CFB]: https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-cfb/
