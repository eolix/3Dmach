# Design note: sub-object editing inside the modifier stack (Edit Poly modifier)

- Status: **Draft, waiting for maintainer approval** (ROADMAP §8, Phase 3 item 1–2)
- Date: 2026-10-16

## The Max behaviour (user's point of view)

In Max, an object's modifier stack can contain **Edit Poly** modifiers anywhere: below a TurboSmooth, above a
Bend, etc. Selecting the Edit Poly entry in the stack lets you select vertices/edges/polygons (levels 1–5) and
move, extrude, bevel or delete them, while the modifiers *above* stay live (with "Show end result" you see
the smoothed result while you edit the cage). The edits are stored in the modifier, not baked into the base
object; you can turn the modifier off, move it in the stack, or delete it to undo all of its edits.

Two related behaviours:

- **Sub-object selection travels up the stack.** A selection made at one level (in an Edit Poly or a Poly
  Select modifier) is what the modifiers above it act on, e.g. a Shell or a Bend only on the selected faces.
- **Selections persist.** Leaving and re-entering a sub-object level brings the same selection back.

## What Blender has today

- Edit mode always edits the **original** mesh, i.e. the bottom of the stack. Modifiers can show on the cage
  ("On Cage", "Edit Mode") but nothing can be edited *between* modifiers.
- Selection is stored per mesh (`.select_vert` etc. attributes), so it does persist across mode switches, but
  only on the original mesh, and modifiers don't take "the current selection" as input. Vertex groups and
  Geometry Nodes named attributes can play that role explicitly.
- Geometry Nodes can apply edits procedurally, but there are no interactive tools that write into a node
  modifier's stored data.

So the Phase 1 approximation (sub-object levels = Blender edit mode select modes) only covers the case where
the Edit Poly is at the bottom of the stack, which is the common case after "Collapse".

## Options

1. **Python-only "Edit Poly" emulation (no C++).** An "Edit Poly" stack entry is a marker modifier
   (Geometry Nodes group carrying a stored mesh delta). Entering it: evaluate the stack up to that point, put
   the result into a temporary edit mesh, edit in normal edit mode, then on exit store the difference
   (topology changes as a full mesh snapshot, pure deformations as offsets) back in the modifier.
   - Pros: no core changes, works on stock Blender.
   - Cons: edits are snapshots, not re-applied operations, so changing a modifier *below* invalidates them
     (Max re-applies recorded operations where it can). Heavy on large meshes. Fragile with undo.
2. **Core: a new "Edit Mesh" modifier type (C++).** A modifier that stores a mesh (or an edit
   journal) and an "edit here" flag. Edit mode, when that modifier is active, edits a BMesh built from the
   evaluated input of the modifier instead of the original mesh; on exit the result is stored in the
   modifier. Depsgraph evaluation then uses the stored result (or replays the journal) at that point.
   - Affected code: `source/blender/modifiers/` (new modifier), `blenkernel` mesh evaluation
     (`BKE_mesh_wrapper`, `mesh_runtime`, cage computation in `DerivedMesh`/`mesh_data_update`),
     `editors/mesh` + `editors/object/object_edit.cc` (entering edit mode on a modifier), `bmesh` conversion,
     undo (`editmesh_undo.cc`), RNA/DNA for the new modifier, and the modifier UI panel.
   - Risks: deep in core evaluation; every edit-mode tool assumes the edit mesh is the original; snapping,
     undo and selection syncing all need care; long-term divergence from upstream.
3. **Core, narrower: selection-aware modifiers (C++ light).** Keep editing at the bottom of the stack, but
   (a) store the sub-object selection as attributes that survive evaluation (they already partly do) and
   (b) add a "Use Stack Selection" option to the main modifiers (Shell/Solidify, Bevel/Chamfer, Subdivision,
   Simple Deform, Displace...) to limit them to selected elements, like Max's selection flowing up. Could also
   be done with Geometry Nodes versions of those modifiers, so mostly Python.

## Proposal

- **Now (Python, Phase 1/2):** Option 3 via Geometry Nodes: a "Poly Select" stack entry (named-attribute
  selection), and Max-named node-group modifiers that respect it. Plus the Option 1 emulation for an Edit Poly
  that is *not* at the bottom, clearly labelled as a snapshot. This covers most day-to-day Max workflows and
  needs no fork-specific C++.
- **Later (C++, needs approval):** Option 2, scoped to meshes, after the importer and Phase 1 shell are
  stable, with a prototype branch first to measure how invasive it is.

## Testing

- Headless tests: stack evaluation with a Poly Select + selection-aware modifiers gives the expected
  geometry; the Edit Poly emulation round-trips (enter, move a vertex, exit, toggle the modifier off/on).
- Corpus: `.max` files with Edit Poly modifiers in the middle of the stack, compared against
  `reference.obj` (collapsed).
- GUI check: enter/exit sub-object levels from the command panel stack view.

## Questions for the maintainer

1. Is the Python-first plan acceptable, with the C++ modifier as a later, separate approval?
2. How important is "edits survive changes to modifiers below" (true operation replay)? It decides between a
   snapshot store and an edit journal.
