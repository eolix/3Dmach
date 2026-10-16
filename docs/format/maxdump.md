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

The remaining sections list **classes not in the registry** with their object counts (candidates for new
registry entries and decoders), classes that were **asked for but have no decoder**, and **warnings**.

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
