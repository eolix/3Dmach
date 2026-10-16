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

Phase 2b core (see `ROADMAP.md`): container, chunk trees, gzip-compressed streams, class and DLL directories,
scene objects and references, nodes (name, parent, object offset, controller / object / material / layer
slots), hierarchy, and the static value of the common transform controllers. Geometry, materials, modifiers,
units and node flags (hidden, frozen, wire colour) are not decoded yet.

**Everything above the container follows `docs/format/overview.md`, which has not been checked against real
files yet.** Each assumption the code relies on is marked with a comment:

```sh
grep -rn "Unverified" maxfile/
```

Python 3.11 or newer, standard library only.

## API

```python
import maxfile

with maxfile.open("scene.max") as mf:          # a path, or bytes holding the file
    for entry in mf.streams:                    # container streams (DirEntry: path, size, ...)
        print(entry.path_str, entry.size)

    for cls in mf.class_directory.entries:      # ClassEntry: index, name, class_id, superclass_id, dll
        print(cls.index, cls.name, cls.class_id, cls.class_id.u64_str() if cls.class_id else None)

    for node in mf.nodes:                       # Node: name, parent, children, object_offset, transform, ...
        geometry = node.object                  # SceneObject (shared between instances) or None
        print(node.name, geometry.class_label() if geometry else None, node.transform)

    for usage in mf.unknown_classes():          # classes used in the scene that the registry doesn't know
        print(usage.entry.label(), usage.entry.class_id, usage.count)

    print(mf.warnings)                          # everything that was odd but not fatal
```

| Object | What it is |
|---|---|
| `maxfile.open(path)` → `MaxFile` | Context manager. Reads the container at once; directories and scene on first access. |
| `MaxFile.streams`, `.raw_stream(name)`, `.stream(name)` | Container streams; raw bytes; decompressed `ChunkStream` (cached, names case-insensitive). |
| `MaxFile.class_directory`, `.dll_directory` | `ClassDirectory` of `ClassEntry`, `DllDirectory` of `DllEntry`. |
| `MaxFile.scene` (`.objects`, `.nodes`) | `Scene`: `objects` by index, `nodes`, `roots`, `decode(obj)`, `warnings`, `undecoded`. |
| `MaxFile.class_usage()`, `.unknown_classes()` | `ClassUsage(entry, count, known, decoder)` per class, most used first. |
| `maxfile.chunks.Chunk` | `type`, `is_container`, `offset`, `size`, `children` (lazy), `data`, `find()`, `string()`, `u32s()`, `f32s()`, `error`. |
| `maxfile.classes.ClassID` | Two 32-bit words `a`, `b`; `str()` → `0x1BF8338D, 0x192F6098`, `.u64_str()` → `0x192F60981BF8338D`. |
| `maxfile.transform.Transform` | `position (x, y, z)`, `rotation (w, x, y, z)`, `scale`; `.matrix()` → 4×4 rows, column vectors. |
| `maxfile.registry` | Known class names (`known_class()`), decoders (`@decoder`, `find_decoder()`, `registered_decoders()`). |
| `maxfile.MaxFileError` | Base of every content error: `ContainerError`, `NotCompoundFileError`, `UnsupportedFormatError`, `StreamNotFoundError`, `ChunkError`, `DecodeError`. |

Errors: a file that can't be read at all (not a Compound File, broken container, no `Scene` stream) raises a
`MaxFileError` subclass from `maxfile.open()`. Anything less (a damaged chunk, an unknown class, a reference
out of range, a controller that can't be decoded) is kept as far as possible and reported in `warnings`.
`OSError` from the file system is passed through.

The data model and the reasons behind it are in `docs/decisions/0008-maxfile-api.md`.

## maxdump

```sh
python -m maxfile.dump scene.max                          # summary (or `maxdump` after pip install)
python -m maxfile.dump scene.max --chunks                 # chunk tree of every scene object
python -m maxfile.dump scene.max --chunks --object 12 --depth 2
python -m maxfile.dump scene.max --stream ClassDirectory3 # chunk tree of any stream
python -m maxfile.dump scene.max --json                   # any mode, as JSON
```

The summary lists the streams (stored and decompressed size, gzip), the class directory (both class-ID forms,
superclass, DLL, object count, registry name, decoder), the DLL directory, the node tree, classes the registry
doesn't know (with counts), objects without a decoder, and warnings. `docs/format/maxdump.md` explains the output
and how to use it to work out a new class.

## Adding a decoder

1. Investigate the class with `maxdump` on real files (`docs/format/maxdump.md`) and write down what you find
   in `docs/format/`.
2. Add a module in `maxfile/objects/` (one per class family) and register the function:

   ```python
   from ..errors import DecodeError
   from ..registry import decoder

   @decoder(0x2008, kind="controller.position", name="Bezier Position")
   def bezier_position(obj, ctx):
       """Position from the value chunk 0x2503."""
       chunk = obj.chunk.find(0x2503)
       if chunk is None:
           raise DecodeError("no 0x2503 chunk")
       return tuple(chunk.f32s()[:3])
   ```

   (A version of this example already exists in `objects/controllers.py`; registering a class twice raises.)
   `obj` is a `SceneObject`; `ctx.ref(obj, slot)`, `ctx.first_ref(obj)` and `ctx.decode(other)` follow
   references. Return plain data; raise `DecodeError` for data you don't understand.
3. Add the class to the known classes in `maxfile/registry.py` if it isn't there.
4. Add a unit test with a synthetic fixture (`tests/synth_max.py`) and a corpus case (`tests/corpus/`).

## Running the tests

```sh
cd pylibs/maxfile
python -m pip install -e ".[test]"   # or just: pip install pytest
python -m pytest
```

The unit tests build their fixtures in code: `tests/cfb_writer.py` writes Compound Files from the [MS-CFB]
spec, and `tests/synth_max.py` writes chunk streams that follow the layouts in `docs/format/overview.md`. They
test the parser against those documented assumptions only. `tests/test_corpus.py` runs the reader and
`maxdump` on every real file in the local corpus (`tests/corpus/README.md`) and is skipped when there is none.
