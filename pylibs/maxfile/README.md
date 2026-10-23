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

The reader and its decoders were checked against 623 real files (Autodesk's public sample files, Max 2008-2018;
see `docs/format/overview.md` for every layout and the evidence behind it): container, chunk trees, gzip, class and
DLL directories (registry keyed by class ID *and* superclass), derived objects, references, nodes (name, parent,
object offset, wire colour, flags), hierarchy and transforms (quaternion convention verified against the node
matrices the Skin modifier stores), system units, ParamBlock2 / ParamBlock with typed values.

Decoders: Editable Poly / Editable Mesh meshes (every corpus mesh), modifier stacks (order verified) and the
parameters of the common modifiers, primitives (parameters; no primitive caches a mesh), shapes, lights and
cameras, materials (Standard, Physical, Arnold Standard Surface, Multi/Sub-Object with its ID list, two-material
classes) and maps (Bitmap paths through the asset table, Checker, Noise, Mix, Normal Bump).

What could only be inferred is marked in the code:

```sh
grep -rn "Guess" maxfile/
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
| `Scene.resolve_geometry(node)` | `(base_object, [modifier objects, top of stack first])` through derived objects. |
| `Scene.param_block(obj)` | A ParamBlock2 / ParamBlock object as `ParamBlockData(params={id: Param})` (typed values, references, controllers), or None. |
| `MaxFile.asset_metadata` | `AssetMetadata`: the asset table (`FileAssetMetaData3` / `2`): ID, type, path, resolved path. |
| `MaxFile.units`, `.max_release` | `SceneUnits(unit, scale, code)` (`.metres` per scene unit); Max release x 1000. |
| `Node` | `name`, `parent`, `children`, `object_offset`, `transform`, `controller` / `object` / `material` / `layer`, `flags`, `wire_color`, `is_hidden` / `is_frozen` / `is_target` (guessed bits). |
| `maxfile.report` | `to_plain(value)` (JSON-ready copy of decoded data), `format_value(value)` (readable text). |
| `maxfile.MaxFileError` | Base of every content error: `ContainerError`, `NotCompoundFileError`, `UnsupportedFormatError`, `StreamNotFoundError`, `ChunkError`, `DecodeError`. |

Errors: a file that can't be read at all (not a Compound File, broken container, no `Scene` stream) raises a
`MaxFileError` subclass from `maxfile.open()`. Anything less (a damaged chunk, an unknown class, a reference
out of range, a controller that can't be decoded) is kept as far as possible and reported in `warnings`.
`OSError` from the file system is passed through.

The data model and the reasons behind it are in `docs/decisions/0008-maxfile-api.md`.

### Decoded data

`mf.scene.decode(obj)` runs the decoder registered for the object's class and returns one of these plain
dataclasses (or None, with the reason in `warnings`). The layouts are in `docs/format/overview.md`; values that
could only be inferred are listed per object (`guessed`) or marked `# Guess:` in the code.

| Class(es) | Returns | Contents |
|---|---|---|
| Editable Poly, PolyMeshObject, Editable Mesh | `objects.geometry.MeshData` | `positions`, `faces` (polygons, Max corner order), `material_ids` (1-based), `smoothing_groups`, `map_channels` (`{channel: MapChannel(vertices, faces)}`), `edge_visibility` (triangle meshes), `source`, `warnings`. |
| Box, Sphere, Cylinder, Cone, Tube, Torus, Plane, GeoSphere, Teapot, ChamferBox, ChamferCyl, Capsule, ... | `objects.primitives.PrimitiveData` | `kind`, `params` (names the live-primitive builder accepts), `extra_params`, `guessed`, `cached_mesh` (always None in the corpus), `encoding` (`"pb2"` / `"pb"`), `param_block`. |
| Derived objects (0x2032 / 0x2033) | `objects.modifiers.ModifierStack` | `base`, `modifiers` (`ModifierRef`, top of stack first, with the context matrix and input box). |
| Common modifiers | `objects.modifier_params.ModifierData` | `class_name`, `params` (the converters' names), `name`, `gizmo`, `guessed`, `enabled` (None: not established). |
| Shapes | `objects.shapes.ShapeData` | `kind`, `splines` (`ShapeSpline(knots, closed)`, Bezier knots with absolute handles), `params`, interpolation, `rendering`. |
| Lights, cameras | `objects.lights.LightData`, `CameraData` | `class_name` (importer names: `Omnilight`, `Targetspot`, `Free_Light`, `Targetcamera`, `Physical`, ...), `params`, `target_node`, `raw`. |
| Materials | `objects.materials.MaterialData` | `class_name` (`Standardmaterial`, `PhysicalMaterial`, `ai_standard_surface`, `Multimaterial`, ...), `name`, `params` / `maps` (the converters' keys), `sub_materials`, `sub_ids` (1-based), `sub_names`, `components`. |
| Maps | `objects.maps.MapData` | `class_name` (`Bitmaptexture`, ...), `name`, `params`, `path`, `resolved_path`, `asset_guid`, `sub_maps`. |
| Transform controllers | tuples / `Transform` | See `objects/controllers.py`. |

Maps have no documented class IDs, so they are read structurally: `objects.maps.read_map(obj, ctx)` gives a
`MapData(class_name, name, params, path, sub_maps, path_source, asset_index)` for any object, and materials use
it for the bitmap-like objects they reference. `objects.paramblock.read_param_block(obj)` gives
`ParamBlockData(entries=[ParamEntry(param_id, chunk_type, raw, guessed)])` with float / int / colour readings of
each entry's payload end.

Material IDs: the disk value plus `objects.geometry.MATERIAL_ID_DISK_OFFSET` (1: stored 0-based, verified).

## maxdump

```sh
python -m maxfile.dump scene.max                          # summary (or `maxdump` after pip install)
python -m maxfile.dump scene.max --chunks                 # chunk tree of every scene object
python -m maxfile.dump scene.max --chunks --object 12 --depth 2
python -m maxfile.dump scene.max --stream ClassDirectory3 # chunk tree of any stream
python -m maxfile.dump scene.max --object 12 --decode     # what the decoders make of object 12
python -m maxfile.dump scene.max --json                   # any mode, as JSON
```

The summary lists the streams (stored and decompressed size, gzip), the class directory (both class-ID forms,
superclass, DLL, object count, registry name, decoder), the DLL directory, the node tree (with resolved geometry
and modifier counts), decoded geometry (vertex / face / channel counts), primitive parameters, modifier stacks,
the material tree with bitmap paths, classes the registry doesn't know (with counts), objects without a decoder,
and warnings. `--decode` prints an object's decoded dataclass, plus generic parameter-block and map readings. `docs/format/maxdump.md` explains the output
and how to use it to work out a new class.

## Writer (experimental)

`maxfile.writer` writes `.max` files laid out like the ones Max 2015 saves, from a neutral scene model (nodes with
transforms, Editable Poly meshes with material IDs / smoothing groups / map channels, Standard, Multi/Sub-Object and
Physical materials with Bitmaps, the system unit). Everything is generated from code; values the reader doesn't
decode are the dominant ones of the corpus files. Design, constants and risks: `docs/design/max-writer.md`.

```python
from maxfile.writer import EditablePoly, Node, Scene, StandardMaterial, Transform, write

scene = Scene(unit="centimeters")
box = EditablePoly(positions, polygons, material_ids=None, smoothing_groups=None, map_channels={})
scene.add(Node("Box001", mesh=box, transform=Transform(position=(0, 0, 10)),
               material=StandardMaterial("Red", diffuse=(0.8, 0.1, 0.1))))
write(scene, "box.max")
```

```sh
python -m maxfile.writer.samples OUT_DIR    # the test-file ladder for checking the writer in Max, with a README
```

It has not been checked in Max yet: the files open in `maxfile` / `maxdump` and have the structure of real 2015
files (`tests/test_writer*.py`), which doesn't prove that Max accepts them.

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
spec, and `tests/synth_max.py` writes chunk streams that follow the layouts in `docs/format/overview.md` (no
bytes from real files). Tests named `test_corpus_*` check facts about real files of the local corpus
(`tests/corpus/README.md`; set `MX_CORPUS_DIR`) and are skipped when there is none: by default on a sample of files
(seconds); `MX_FULL_CORPUS=1` runs them, and `tests/test_corpus.py` (reader, decoders and `maxdump`), on every
file (several minutes).
