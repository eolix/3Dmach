# maxfile

Pure-Python reader for `.max` scene files. It parses a file into plain Python
data (dataclasses) and has **no dependency on Blender** (`bpy`, `mathutils`, …),
so it can be unit-tested with plain `pytest` and reused by other projects.
The Blender side of the importer lives in `scripts/addons_core/mx_io_max`.

The reader is built from analysing real files (interoperability); see
`docs/format/` for what is known about the format.

Much of the starting knowledge comes from the GPL importer `io_scene_max` by Sebastian Sille,
Jens M. Plonka and Philippe Lagadec, used as a reference (see `docs/decisions/0003-io-scene-max-rewrite.md`).
The Compound File container is read according to Microsoft's public [MS-CFB] specification.

[MS-CFB]: https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-cfb/

## Status

Skeleton only: the container module recognises the Compound File signature.
See `ROADMAP.md` (Phase 2b) for the plan.

## Running the tests

```sh
cd pylibs/maxfile
python -m pip install -e ".[test]"   # or just: pip install pytest
python -m pytest
```
