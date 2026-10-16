# Test corpus

Real `.max` files with reference exports, used to check the importer (ROADMAP §6).

Only commit files you made yourself, or files whose licence allows redistribution (ROADMAP §3.5).

## Layout

```
tests/corpus/
  manifest.toml          # one [[case]] entry per case directory
  <case_name>/
    scene.max            # required: the source file
    reference.obj        # required: exported from Max with the modifier stack collapsed (geometry ground truth)
    LICENSE.txt          # required: redistribution licence for the files in this directory
    notes.md             # required: Max version, renderer, what the case tests, anything unusual
    reference.fbx        # optional: hierarchy / transforms / cameras ground truth
    reference.png        # optional: render from Max, for visual comparison
```

No other files are allowed in a case directory.

## Manifest

```toml
schema_version = 1

[[case]]
name = "editable_poly_box"        # lower_snake_case, same as the directory name
max_version = "2024"              # the Max version that saved scene.max (a quoted string)
renderer = "none"                 # renderer the scene was set up for: "none", "scanline", "arnold", "vray", "corona", ...
features = ["geometry.editable_poly", "material.multi_sub_object"]  # what the case exercises, dotted names
expected = "xfail"                # "pass", "xfail" (known to fail, tracked) or "skip"
license = "CC0-1.0"               # SPDX id, must match LICENSE.txt
contributor = "Jane Doe"          # who made or supplied the files
notes = "Optional short note"     # optional
```

Accepted licences: `CC0-1.0`, `CC-BY-4.0`, `CC-BY-SA-4.0`, `GPL-2.0-or-later`, `GPL-3.0-or-later`.
Ask before using another one.

Feature names are dotted `lower_snake_case`, starting with the area: `geometry.*`, `modifier.*`, `material.*`,
`map.*`, `camera.*`, `light.*`, `scene.*`. Use an existing name when one fits.

Check the manifest before committing:

```sh
python3 tests/corpus/check_manifest.py
```

`pytest tests/corpus` runs the same check plus the checker's own tests.

## Making a case in Max

1. Keep it small: one feature per case where possible.
2. Save the scene as `scene.max`.
3. Export `reference.obj` with the modifier stacks collapsed (geometry ground truth).
4. Optionally export `reference.fbx` and render `reference.png`.
5. Write `notes.md` (Max version, renderer, units setup, what to look for) and `LICENSE.txt`.
6. Add a `[[case]]` entry to `manifest.toml`.
