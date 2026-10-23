# Design note: an experimental .max writer

- Status: **Experimental, waiting for the maintainer's tests in Max**
- Date: 2026-10-23
- Code: `pylibs/maxfile/maxfile/writer/` (pure Python), `scripts/addons_core/mx_io_max/export_max.py` (Blender side)

## Goal

File > Save in 3Dmach should be able to write a `.max` file that Max opens. The first version is
**modelling-first**: nodes with hierarchy and transforms, Editable Poly geometry (material IDs, smoothing groups,
UVs), Standard / Physical / Multi/Sub-Object materials with bitmaps, units. Everything is generated from code:
the layouts are the inverse of what `maxfile` reads (`docs/format/overview.md`), and where a field's meaning is
unknown the writer emits the value that dominates in real files of the targeted version, with its corpus frequency
noted next to the constant (`maxfile/writer/` marks them `# Corpus:`). No bytes are copied from corpus files and no
SDK material is used (ROADMAP §3).

## Non-goals (for now)

Animation (keys), modifier stacks (the Blender exporter bakes modifiers into the Editable Poly), cameras, lights,
shapes / splines, helpers, groups, layers other than "0", custom attributes, render settings beyond the defaults,
viewport layouts, scripted plug-in data, thumbnails, Editable Mesh. These are reported as "not written" by the
exporter.

## Which Max version to write

Every corpus file (623) is a Compound File **version 4** (4096-byte sectors) whose root entry has the CLSID
`{1CDD8C7B-81C0-45A0-9FED-04143144CC1E}` (all 623). The release in the DLL directory header splits the corpus
into 2008 (3 files), 2010 (60), 2012 (30), **2015 (305)**, 2017 (60), 2018 (74 + 91).

The writer targets **Max 2015** (release 16900):

- Max opens files of older releases, so a 2015 file opens in every release from 2015 on (11+ years of
  releases). Older targets would add only very old releases while the evidence for them is thin (2008: 3 files,
  2010: 60, 2012: 30) and they use the pre-Unicode records (8-bit strings, `0x000E` parameter records).
- 2015 is the best-documented release in the corpus: 305 files with a uniform layout (one stream list for all of
  them, one top-level Scene container type, one Scene-object reference layout).
- 2015 files are never compressed (0 of 305), which keeps the writer simple; files from 2017/2018 are mostly
  gzipped.

Version stamps written (all from the 2015 corpus files):

| Where | Value | Corpus |
|---|---|---|
| DLL directory header `0x21C0` | `0x4204019B` (release 16900, build 0x019B) | 76 of 305 (most common of 9 builds; the high word is 16900 in all 305) |
| `SaveConfigData` `0x2170` / `0x2173` | same value / 16900 | 305 of 305 (`0x2170` = the DLL header in all) |
| `SaveConfigData` `0x2172` / `0x2174` / `0x2171` | `0x0409` / 65001 / 0 | 305 of 305 |
| Scene stream top container type | `0x2020` | 305 of 305 (2008: `0x200F`, 2010: `0x2013`, 2012: `0x2014`, 2017: `0x2022`, 2018: `0x2023`) |
| ParamBlock2 header version word | `0x42042B08` | most common in 2015 (`0x42042B0A` in the rest) |
| Summary information | "3ds Max Version: 16.90", "Saved As Version: 16.90" | the strings real 2015 files carry |

## Streams

Probe over the corpus (`tests/corpus/survey.py`-style; 2015 files):

| Stream | 2015 files | Written as |
|---|---|---|
| `Scene` | 305 | The scene (below). |
| `ClassDirectory3`, `DllDirectory` | 305 | Built from the classes the scene uses, in order of first use (as real files). |
| `Config` | 305 | Minimal: the top-level chunks with scalar settings (animation range, time, gamma, grid); viewport layouts (`0x2080`) and plug-in configuration (`0x21A0`) are left out so Max uses its defaults. **Risk.** |
| `ClassData` | 305 | Empty (it holds per-plug-in class data). **Risk.** |
| `VideoPostQueue` | 303 | The dominant 52-byte queue (empty queue). |
| `ScriptedCustAttribDefs` | 305 | Empty (it defines the scripted custom attributes we don't write). **Risk.** |
| `SaveConfigData` | 305 | Version stamps (above). |
| `FileAssetMetaData3` | 305 (often empty) | Asset table: one `Bitmap` entry per bitmap file (`docs/format/overview.md` §7). |
| `\x05SummaryInformation`, `\x05DocumentSummaryInformation` | 305 | Property sets [MS-OLEPS] with the code page, the version strings, scene totals and object / material / plug-in lists. No thumbnail. |

## The Scene stream

One top-level container (type `0x2020`) holding the objects; each object's chunk type is its class index, its
position its object index. Objects are written **children first** (an object's references have lower indices),
which is the order real files have; nodes follow the root node, parents before children.

### Scene-level objects

The last object of every file is the scene object (class `0x2222` / superclass `0x100`), which references the
scene-level objects. In all 305 files of 2015 its references are:

| Slot | Class | Written |
|---|---|---|
| 0 | Material Editor (`0xC80` / `0x100`) | With 24 default Standard materials in its slots ("01 - Default" ...), like a fresh scene. |
| 1 | MtlBaseLib (`0x3333` / `0x100`) | Referencing the scene materials. |
| 2 | Default Sound (`0x1` / `0xD00`) | 243 of 305 (the others: ProSound). |
| 3 | RootNode (`0x2` / `0x1`) | |
| 4 | RenderEnvironment (`0xEE448B23` / `0x1010`) | With its renderers (Default Scanline Renderer + Area filter), render element managers, background / tint / ambient colour controllers. |
| 5 | NamedSelSetList | Empty. |
| 6 | TVNode (track view root) | With the entries every 2015 file has: Video Post, Global Tracks (Float / Point3 / Position / Rotation / Scale / Block Control lists), Reaction Manager, Parameter Collector, SME, Scene Effects. Plug-in entries (Biped, Raytrace globals, ...) are left out; plug-ins recreate them. |
| 7 | Grid Reference | |
| 8 | RenderEffects | Empty. |
| 9 | Shadow Map (`0x100` / `0x10D0`) | The default shadow generator with its parameter block. |
| 10 | Layer Manager | With layer "0" (Base Layer). |
| 11 | TrackSetList | Empty. |
| 12 | PersistentIsolationData | With its two node sets. |

The custom attributes real files hang on the scene (scene properties, anchors, viewport managers on materials)
are not written.

### Nodes and transforms

Nodes (class `0x1` / `0x1`) carry the chunks every corpus node has (`0x0960` parent + flags, `0x0962` name,
`0x096A`-`0x096C` object offset, `0x0974` wire colour, and the display / render chunks with their dominant
values), references 0 transform controller, 1 object, 3 material, 6 layer. Transforms use a Position/Rotation/Scale
controller with **Bezier Position**, **TCB Rotation** and **Bezier Scale** sub-controllers, whose value chunks
(`0x2503`, `0x2504`, `0x2505`) are the verified ones; the quaternion is written as `x, y, z, w` of the inverse
rotation (`docs/format/overview.md` §4.1). Hidden / frozen are the guessed flag bits 20 / 9.

### Editable Poly

`0x08FE` holds vertices (`0x0100`), edges (`0x010A`, derived from the polygons in the order Max lists them: first
use, in face order), polygons (`0x011A`: material ID 0-based, smoothing groups, triangulation diagonals for
polygons with more than three corners), map channels (`0x0120`, `0x0124`/`0x0128`/`0x012B`), and the
vertex adjacency `0x0310` (per vertex: the incident edges, then the incident faces, ascending; worked out on
corpus boxes). The object has the Editable Poly parameter block (reference 0, dominant values) and a Master Point
Controller (reference 1).

### Materials

- **Standard** (`0x2` / `0xC00`): Texmaps (ref 1), Blinn shader with its block (ref 2), five ParamBlock2 (refs
  3-7, block IDs 0-4, layouts and defaults from the corpus), sampler "Max 2.5 Star" (ref 8). Diffuse, specular,
  glossiness, specular level, opacity and the diffuse / bump / opacity / specular maps are set from the model.
- **Physical Material** (`0xDEADC0013D6B1CEC` / `0xC00`): ParamBlock2 0 with the parameters of overview §7.
- **Multi/Sub-Object** (`0x200` / `0xC00`): ParamBlock2 0 (tables of materials, enables, names, 0-based IDs),
  references i+1 = sub-materials, `0x4002` = count.
- **Bitmap** (`0x240` / `0xC10`): Placement (UVGen), ParamBlock2 with the file name as an asset reference
  (`0xFFFFFFFE` + `0x000F`/`0x0002` GUID), Output, time block; the GUID and path go into `FileAssetMetaData3`.

## Risks

1. **Max may require data we leave out** (viewport configuration, plug-in class data, custom attributes, render
   settings blobs). Max's loaders are chunk loops that skip unknown chunks and keep defaults for missing ones, but
   a missing *reference* (an object a class expects) can crash. Mitigation: every object we write has the full
   reference layout real files have; the sample ladder starts with an empty scene so failures can be bisected.
2. **Parameter blocks** carry a descriptor version and per-parameter type / flag words; a mismatch may make Max
   drop the block or refuse the file. Mitigation: heads are emitted exactly as the dominant corpus records.
3. **Editable Poly** has cached data (`0x0310`, edges, flags) Max may check for consistency. Mitigation: derived
   from the polygons the way the corpus boxes show; a crash here would show up at step 02 of the ladder.
4. **Version checks**: Max may read the version from several places (DLL header, SaveConfigData, Scene container
   type, summary information). All are written consistently for 2015.
5. Unknown flag bits (node flags, display chunks) use the dominant values, so objects may come up with odd
   display settings rather than fail.

## Test plan

- **Round trip** (pytest, no corpus): model -> write -> `maxfile.open` -> decoded data equals the model (nodes,
  hierarchy, transforms including the quaternion convention, geometry, material IDs, smoothing groups, UVs,
  materials, bitmaps, units).
- **Structure against the corpus** (pytest, skipped without corpus): the written file's streams, root CLSID,
  version stamps, Scene container type, scene-object references, class / DLL entries and node / material chunk
  layouts match real 2015 files.
- **Blender**: export, re-import with `import_scene.mx_max`, compare objects / transforms / geometry / materials.
- **Max (maintainer)**: `python -m maxfile.writer.samples OUT_DIR` writes a ladder of files (empty scene, one
  box, hierarchy, materials, units, many objects) with a README saying what Max should show for each. The
  maintainer reports per file: opens / doesn't open (message) / what looks wrong. Failures early in the ladder
  point at the scene-level skeleton, later ones at the object they introduce.
