# 0008: The maxfile public data model

- Status: Proposed (waiting for maintainer review)
- Date: 2026-10-16

## Context

ROADMAP Phase 2b builds `pylibs/maxfile`, the pure-Python `.max` reader that `mx_io_max` and `maxdump` sit on.
Its API will be used by every decoder and by the Blender-side builder, so its shape is worth fixing early. The
constraints:

- No Blender types (ROADMAP §4.2): the output must be plain Python data that `pytest` can check.
- Almost nothing about the format is verified yet (`docs/format/overview.md`). The API has to make it easy to
  look at raw data when an assumption turns out wrong, and must not hide unknown data.
- Files can be hundreds of MB, and corrupt or unexpected files must give a clear message, never a crash or hang.
- Decoders are the main contribution path (ROADMAP §7); adding one should touch one module and nothing else.

## Decision

**Layers, each usable on its own:**

1. `maxfile.container.CompoundFile`: the [MS-CFB] container (streams by case-insensitive name or path). Knows
   nothing about `.max`.
2. `maxfile.chunks`: `ChunkStream` (one stream, decompressed) and `Chunk` (`type`, `is_container`, `offset`,
   `size`, lazily parsed `children`, payload `data`, `error`). Offsets are into the decompressed stream.
3. `maxfile.classes`: `ClassID`, `ClassDirectory` / `ClassEntry`, `DllDirectory` / `DllEntry`.
4. `maxfile.scene`: `Scene` with `SceneObject`s (index, class, raw chunk, references) and `Node`s.
5. `maxfile.open(path) -> MaxFile` ties them together: `streams`, `stream()`, `class_directory`,
   `dll_directory`, `scene`, `objects`, `nodes`, `warnings`, `class_usage()`, `unknown_classes()`.

**Objects are referred to by index, and keep their raw chunks.** A `SceneObject` is its position in the
`Scene` list plus its chunk tree; references are `slot -> object index`. Nodes resolve the slots they know
(`controller`, `object`, `material`, `layer`) to the shared `SceneObject`, so two nodes that instance the same
geometry point at the same object. Keeping the chunk on every object means a decoder, `maxdump` and a bug
report can always get back to the bytes.

**Decoding is separate from parsing, and registered per class.** `maxfile.registry` holds known class names
(seeded from overview.md, all marked unverified) and decoders added with `@decoder(class_id, kind=...)` in
modules under `maxfile/objects/`. `Scene.decode(obj)` runs the decoder for `obj`'s class, caches the result,
guards against reference cycles and deep nesting, and turns `DecodeError` into a warning. Only the transform
controllers are decoded eagerly (to fill `Node.transform`); everything else is decoded when the importer asks.
`registered_decoders()` is the input for the generated supported-features matrix. Lookups take an optional
superclass ID, because class IDs may only be unique within a superclass.

**Errors versus warnings.** A file that can't be read at all raises a `MaxFileError` subclass from
`maxfile.open()` (not a Compound File, broken container, no `Scene` stream). Everything else is kept as far as
possible and reported: a bad chunk header stops parsing of that one level and is recorded in `Chunk.error`;
unknown classes, out-of-range references, parent cycles and undecodable objects become entries in `warnings`
(aggregated with counts where they repeat) or `None` values. The importer can then always build what it
understood and list the rest in its report (ROADMAP §2g).

**Laziness and bounded work.** The container reads only header, FAT and directory up front; files opened by
path are memory-mapped. Chunk children are parsed one level at a time on first access and never recursively;
tree walks are iterative. Every chain and tree walk is linear and cycle-checked.

**Plain value conventions.** Vectors are `(x, y, z)`, quaternions `(w, x, y, z)`, matrices 4×4 tuples of rows
for column vectors (Blender's convention, so `mathutils.Matrix(m)` works directly), held in
`maxfile.transform.Transform`. `ClassID` keeps the two 32-bit words as stored and prints both the two-word form
and the 64-bit form used in overview.md.

**Unverified assumptions are marked in code** with `# Unverified (overview.md §N)` so they can be found and
checked when corpus files arrive.

### Decoded object data

Decoders return dataclasses defined next to them in `maxfile/objects/`, built from plain values (numbers,
tuples, lists, dicts, strings) and **object indices, never `SceneObject`s**, so they serialise directly
(`maxfile.report.to_plain`, `maxdump --decode --json`) and can be compared in tests.

- **`MeshData`** (`geometry.py`): `positions`, `faces` as polygons in Max corner order, per-face `material_ids`
  and `smoothing_groups`, and `map_channels: {channel: MapChannel(vertices, faces)}` with one map face per
  geometry face and the same corner count. This is the shape the importer needs for bulk mesh building and
  per-corner UVs; triangle meshes (Editable Mesh, primitive caches) use the same type. Material IDs are
  converted to Max's 1-based UI numbering at one place, `MATERIAL_ID_DISK_OFFSET`, because the disk base is
  unknown (overview "To verify" #11) and every consumer (Multi/Sub-Object slot mapping) thinks in UI IDs.
  The decoder validates instead of trusting: counts are capped to the data present, faces with out-of-range
  vertices are dropped together with their per-face data, and map channels that don't line up are dropped,
  each with a warning (also kept in `MeshData.warnings`).
- **`PrimitiveData`** (`primitives.py`): `kind`, `params` restricted to the names the overview gives, and the
  cached Max mesh when present. Values the overview doesn't name go to `extra_values` instead of being named by
  guesswork, so the importer never builds a primitive from a misread parameter.
- **`ModifierStack`** (`modifiers.py`): base object index plus `ModifierRef`s, top of the stack first.
  `Scene.resolve_geometry(node)` follows nested wrappers and returns `(base, modifiers)`; it is the one place
  that encodes the stack-order assumption.
- **`MaterialData` / `MapData`** (`materials.py`, `maps.py`): `class_name` uses the names the importer's
  converters dispatch on (`scripts/addons_core/mx_io_max/materials/convert.py`), and `params` / `maps` use their
  keys, so the Blender side needs no translation table. Only parameters the overview documents are filled; the
  rest of a material's references are kept as `param_blocks` (indices) and `unassigned_maps` (by slot) for
  investigation. `sub_ids` is None, not a guessed `1..n`, because the ID list isn't documented; the importer
  can pass `[None] * len(sub_materials)` to `mx_io_max.material_ids.slots_for_faces`, which then applies Max's
  wrap-around rule (face ID modulo sub-material count).
- **Structural readers** for things without documented class IDs: `read_param_block` (generic parameter
  blocks, values offered as several guesses) and `read_map` (bitmap paths). They are plain functions rather than
  registered decoders because there is no class ID to register them under.

## Consequences

- Decoders and the importer work on stable, Blender-free types; tests build synthetic fixtures for them.
- When an assumption proves wrong, the fix is usually local (one marked line in `chunks`, `classes` or
  `scene`), and `maxdump` still shows the raw data in the meantime.
- Indices instead of object pointers in `references` mean consumers do one lookup (`scene.ref(obj, slot)`), but
  the data has no reference cycles and serialises trivially (`maxdump --json`).
- Keeping raw chunks costs memory proportional to the number of chunks touched; payload bytes are only copied
  when read. If very large files need it, chunk objects could later be replaced by offset arrays without
  changing the `SceneObject` / `Node` API.
- Field names in `DllEntry` are still keyed by chunk type (`0x2037`, `0x2039`) and `Node` has no flags (hidden,
  frozen, wire colour) yet; both will change once real files show what the chunks mean. Until a first release,
  the API may change without deprecation.
- Most material parameters stay empty until real files show their indices; converters fall back to class
  defaults. Fields added later (map parameters, sub-maps, modifier parameters) extend the same dataclasses.

[MS-CFB]: https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-cfb/
