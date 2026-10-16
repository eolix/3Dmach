# Test corpus

Real `.max` files used to check the importer (ROADMAP §6).

**`.max` files are never committed.** Put them in `tests/corpus/local/` (gitignored), or anywhere else and point
`MX_CORPUS_DIR` at that directory. Every `*.max` file below the corpus root is a test case; tests that need the
corpus are skipped when it's empty.

## Layout

Any layout works. Textures can sit next to the scenes. For example:

```
tests/corpus/local/
  manifest.toml              # optional metadata, see below
  editable_poly_box/
    scene.max
    reference.obj            # optional: exported from Max with the modifier stack collapsed
    reference.fbx            # optional: hierarchy / transforms / cameras ground truth
    notes.md                 # optional: Max version, renderer, what to look for
  archviz/
    living_room.max
    living_room.obj          # `<name>.obj` next to `<name>.max` is picked up as its reference
    maps/...
```

A reference export is found automatically as `<name>.obj` / `<name>.fbx` next to `<name>.max`, or as
`reference.obj` / `reference.fbx` when the directory holds only one `.max` file.

## Manifest (optional)

`manifest.toml` in the corpus root adds metadata. All keys except `file` are optional.

```toml
schema_version = 2

[[case]]
file = "archviz/living_room.max"     # relative to the corpus root
expected = "xfail"                    # "pass" (default), "xfail" (known to fail) or "skip"
max_version = "2023"
renderer = "vray"
features = ["geometry.editable_poly", "material.multi_sub_object", "material.vray_mtl"]
reference_obj = "exports/living_room_collapsed.obj"   # when not found automatically
notes = "Big interior, lots of instances"
```

Feature names are dotted `lower_snake_case`, starting with the area: `geometry.*`, `modifier.*`, `material.*`,
`map.*`, `camera.*`, `light.*`, `scene.*`.

List the corpus and check the manifest:

```sh
python3 tests/corpus/corpus.py
```

## Making a test scene in Max

1. Keep it small: one feature per scene where possible. Real project files are welcome too.
2. Export `reference.obj` (or `<name>.obj`) with the modifier stacks collapsed: that is the geometry ground truth.
3. Optionally export `reference.fbx` and write a few lines in `notes.md` (Max version, renderer, units setup).
