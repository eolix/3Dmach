# Investigating a .max file with maxdump

`maxdump` prints what `maxfile` sees in a `.max` file. It is the main tool for checking the assumptions in
[overview.md](overview.md) on real files and for working out classes we don't support yet.

```sh
cd pylibs/maxfile
python -m maxfile.dump path/to/scene.max            # or `maxdump` after `pip install -e .`
```

`maxdump` only reads the file. Its output contains whatever is in the scene (object names, texture paths,
plugin names), so check it before pasting it into a public issue.

## Reading the output

The examples below are output for a **synthetic** test file built to the layouts in overview.md (like the
fixtures in `pylibs/maxfile/tests/synth_max.py`), not for a real `.max` file.

Conventions, everywhere: `[12]` is scene object 12 (its position in the `Scene` object list), `#5` is class
directory entry 5, `0x0962` is a chunk type, and details are `key=value`. That makes the output easy to `grep`.

### Summary (default)

```
== Streams (3) ==
        STORED          SIZE  GZIP  CHUNKS  NAME
           308           308  -          7  ClassDirectory3
            66            66  -          1  DllDirectory
           160           268  gzip       1  Scene
```

One line per stream: size in the container, size after decompression, whether it was gzip-compressed, and how
many top-level chunks it parses into. `(not a clean chunk stream: ...)` means the stream isn't a chunk tree, or
our header rule is wrong for it; the asset metadata stream (overview §5.2) is expected to show this.

```
== Class directory: ClassDirectory3 (7 classes) ==
  #1    class=0x00002005, 0x00000000 (0x0000000000002005)  super=0x09008003  dll=0xFFFFFFFF(none)  objects=1  name="PRS"  known="Position/Rotation/Scale"  decoder="Position/Rotation/Scale"
  #6    class=0x00001234, 0x00005678 (0x0000567800001234)  super=0x00000010  dll=#0  objects=1  name="Weird"  known=-
```

`class=` is the class ID as two words (the order they are stored in), then the single 64-bit form used in
overview.md. `dll=` is the DLL directory entry, or `0x...(none)` when the index is outside the DLL directory
(built-in classes, presumably). `objects=` counts scene objects of the class. `name=` is the name stored in the
file; `known=` is the name in our registry (`maxfile/registry.py`), and `decoder=` appears when we can decode it.

```
== Nodes (3 of 9 objects, 1 roots) ==
  [6] "Root"
    [7] "Box001"  object=[4] Box  controller=[3] Position/Rotation/Scale  pos=(1, 2, 3)  scale=(2, 2, 2)  offset_pos=(0, 0, 1)
      [8] "Box002"  object=[4] Box
```

The node tree, indented by depth. `transform=?` means the transform controller couldn't be decoded (see the
warnings). `offset_pos=` / `offset_rot_wxyz=` / `offset_scale=` are the object offset (pivot).

Node lines also show `geometry=` when the node's object is a modifier-stack wrapper (the base object found
through it) and `modifiers=` with the number of modifiers.

Then come the **decoded** sections (all from the unverified layouts of overview.md §5-6):

```
== Geometry (2) ==
  [0] Editable Poly  source=editable_poly vertices=8 faces=6 corners=24 channels=1 material_ids=1,2 smoothing=yes
== Primitives (1) ==
  [5] Box  kind=BOX  length=10  width=20  height=30  encoding=0x0100+leaf+record  cached_mesh=(vertices=3 ...)
== Modifier stacks (1, modifiers listed top of stack first) ==
  [3] Derived object? (io_scene_max: "shell")  base=[0] Editable Poly  modifiers=[2] Mod
== Materials used by nodes (3 rows) ==
  [12] Multimaterial (no name)  sub_materials=2  sub_ids=None
    [9] VRayMtl "Wood"  diffuse=(0.5, 0.25, 0.125)  reflection_glossiness=0.8  slot1=[7] Bitmap? path="C:\\maps\\wood.png"
```

`material_ids=` lists the distinct face material IDs (1-based, see `MATERIAL_ID_DISK_OFFSET`). `problems=N`
counts what the mesh decoder had to drop. `encoding=` says which of the three primitive parameter encodings of
overview §6.4 were found; `extra_values=` are values beyond the parameters the overview names. Material maps
show up as `slotN=` (a referenced bitmap whose parameter is unknown) or under a parameter key.

The remaining sections list **classes not in the registry** with their object counts (candidates for new
registry entries and decoders), classes that were **asked for but have no decoder**, and **warnings**.

### One object, decoded

```sh
maxdump scene.max --object 9 --decode           # text
maxdump scene.max --object 9 --decode --json    # the full dataclass as JSON
```

Prints the object's references, its node data if it is a node, the value its decoder returns (lists cut after a
few items in text mode, complete in JSON), and two generic readings that work for any class:

- **as a parameter block**: every leaf whose payload starts with a u16, with that u16 as `id=` and the payload's
  end read as `float=`, `int=`, `color=` and `rgba_color=` (overview §5.1's rule). Only one of these readings is
  right for a given entry, and which one is for you to work out;
- **as a map**, when the object or one of its references holds a bitmap path (`0x1230`) or asset index
  (`0x1260`, overview §5.2).

### Chunk trees

```sh
maxdump scene.max --chunks                     # every scene object
maxdump scene.max --chunks --object 4          # one object
maxdump scene.max --chunks --object 4 --depth 1
maxdump scene.max --stream ClassDirectory3     # any stream (names are case-insensitive)
maxdump scene.max --stream Config --preview 64 # longer hex previews
```

```
$ maxdump synthetic.max --object 7
== Stream Scene: 268 bytes (gzip, 160 bytes stored), 1 top-level chunk(s) ==
  [7] 0x0000 cont size=70 @0x000092  #0 Node "Box001"  children=4
    0x2034 leaf size=14 @0x000098  03 00 00 00 04 00 00 00  u32=3 4 f32=4.2039e-45 5.60519e-45
    0x0960 leaf size=14 @0x0000A6  06 00 00 00 00 00 00 00  u32=6 0 f32=8.40779e-45 0
    0x0962 leaf size=18 @0x0000B4  "Box001"
    0x096A leaf size=18 @0x0000C6  00 00 00 00 00 00 00 00 00 00 80 3F  u32=0 0 0x3F800000 f32=0 0 1
```

Each line: chunk type, `cont` (container) or `leaf`, total size including the header, offset in the
decompressed stream, and for leaves a preview: text when the payload looks like UTF-16 text, otherwise hex, plus
the payload read as `u32` (hex from 0x10000 up) and `f32` values when it is 4 to 16 bytes long. `hdr=14` marks an extended (64-bit
size) header. `!! error:` marks a chunk header that doesn't fit, which means the data is damaged or our chunk
rule (overview §2.1) doesn't hold there.

`--json` writes the same rows as a flat list (`depth`, `type`, `container`, `offset`, `size`, `text` / `hex` /
`u32` / `f32`), which is easier to process with `jq` or Python.

## Working out a new class

1. **Find it.** In the summary, look under *Classes not in the registry*. Note the class ID (both forms), the
   superclass, the stored name and the DLL.
2. **Find its objects.** `maxdump scene.max --chunks --depth 0 | grep ' #5 '` lists every object of class `#5`.
3. **Look at one.** `maxdump scene.max --chunks --object 23`. Leaf payloads that are counts followed by arrays,
   UTF-16 names and small float groups usually stand out in the `u32=` / `f32=` previews.
4. **Change one thing.** The fastest way to learn what a chunk means is two files that differ in a single
   parameter (save, change the radius, save again). Offsets shift between files, so compare JSON without them:

   ```sh
   for f in a b; do
       maxdump $f.max --chunks --object 23 --json \
           | python -c "import json,sys; [print(r['depth'], r['type'], r.get('text') or r.get('hex')) for r in json.load(sys.stdin)['chunks']]" > $f.txt
   done
   diff a.txt b.txt
   ```

   Object indices can also change between saves; find the object again by name or class.
5. **Follow references.** `0x2034` lists object indices by slot, `0x2035` lists `(slot, index)` pairs after one
   leading value (overview §3). Dump the referenced objects the same way. For a node, slot 1 is its object,
   3 its material, 0 its transform controller.
6. **Write it down** in `docs/format/` (layout, which Max versions, which files), with the evidence.
7. **Implement it**: a registry entry and a decoder module in `pylibs/maxfile/maxfile/objects/`, a unit test
   with a synthetic fixture, and a corpus case (see `pylibs/maxfile/README.md` and `tests/corpus/README.md`).

For parameters, `--decode` on the material or primitive's parameter-block objects (listed as `param_blocks` /
`param_block` in the decoded value) is usually the quickest start: change one spinner in Max, save, and see which
`id=` entry changed and which reading (`float`, `color`, ...) matches the new value.

## Checking the overview's assumptions

The code marks every format assumption it relies on with `# Unverified (overview.md §N)`; list them with
`grep -rn Unverified pylibs/maxfile/maxfile`. The corpus test (`pytest pylibs/maxfile/tests/test_corpus.py -s`)
prints object, node and unknown-class counts and the number of warnings for every corpus file, and
`maxdump` shows the details. Things to look for first:

- **Streams section:** stream names per Max version, which streams are gzipped, and whether every chunk stream
  parses cleanly (overview "To verify" #1, #3).
- **Class directory:** whether names and class IDs look plausible (#4). A wrong word order shows up as
  well-known IDs (e.g. Editable Poly) not being matched by the registry.
- **Nodes:** whether node names, parents and positions match what Max shows (#5); compare rotations against a
  `reference.fbx` (#6).
- **Warnings:** references out of range or damaged chunk trees suggest that one of the rules in overview §2-3
  doesn't hold for that file.
- **Geometry:** vertex and face counts against `reference.obj`; faces dropped or map channels "dropped" /
  "out of step" mean the mesh layout of overview §6.2-6.3 is off for that file (#7, #8). Material IDs one too
  high or low mean `MATERIAL_ID_DISK_OFFSET` is wrong (#11).
- **Modifier stacks:** whether `modifiers=` lists the modifiers in the order Max shows them, top first (#9).
- **Materials:** whether names, VRayMtl diffuse / glossiness, and bitmap paths match the scene (#2, #12).

### Probes still needed

Nothing in overview.md documents these, so `maxfile` doesn't read them yet. Small scenes that differ in just one
of them would let us find the chunks with the "change one thing" method above:

- node **hidden** / **frozen** state, **wire colour**, renderable / visibility flags, layer membership details;
- **scene units** (probably in `Config`, overview "To verify" #10);
- the **Multi/Sub-Object ID list** and the parameter indices of every material class except the two VRayMtl ones;
- **modifier** parameters and enabled state;
- the layout of the asset index in `0x1260` and in class `0x3333` objects, and the asset metadata stream's name.
