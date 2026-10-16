# ROADMAP — PROJECT_NAME (working title)

> A free, open-source 3D application that looks, feels and behaves like 3ds Max, opens `.max` files, and renders their materials with Blender's renderers (Cycles / EEVEE). Built as a hard fork of Blender.

`PROJECT_NAME` is a placeholder. The final name must not contain or resemble any Autodesk trademark ("3ds Max", "Max", "Autodesk", etc.).

---

## 0. Instructions for the coding agent

Read this whole file before writing any code. Then:

1. **Work phase by phase, in order.** Phase 0 and Phase 1 come before any C++ work. Do not start Phase 3 without the maintainer's go-ahead.
2. **Prefer Python add-ons over C++.** Anything that can be done through Blender's Python API should be. C++ changes to the Blender core are reserved for Phase 3, and each one needs a short design note first (see §8).
3. **Small, reviewable changes.** One feature per branch / PR. Every PR updates the checklist in this file and adds or updates tests.
4. **Respect the hard constraints in §3.** If a task seems to require breaking one, stop and ask.
5. **Record decisions.** Any non-obvious choice goes in `docs/decisions/NNNN-title.md` (a few paragraphs: context, decision, consequences).
6. **You cannot run 3ds Max.** Test data must come from the maintainer or contributors (see §6). Never invent the contents of a `.max` file; if a format detail is uncertain, write a probe script that dumps the real data and reason from that.
7. **When stuck or when the spec is ambiguous, ask** rather than guess. Add the question to §10.

---

## 1. Vision

A 3ds Max user should be able to:

1. Launch the app and feel at home: Max navigation, hotkeys, quad menus, command panel, modifier stack.
2. Drag in a `.max` file and see their scene: geometry, hierarchy, cameras, lights, and materials that render close to the original in Cycles or EEVEE.
3. Keep modelling in a Max-style workflow (primitives with live parameters, Editable Poly, modifier stack) and save as `.blend`, or export to FBX / USD / OBJ.

## 2. Scope

### In scope (v1)

- Max-style UI, hotkeys, navigation and selection behaviour.
- `.max` **import**: geometry, transforms, hierarchy, instances, primitives, common modifiers, splines, cameras, lights, materials and textures.
- Material translation to Blender node trees (Principled BSDF based).
- Max-style modelling behaviour (Phase 3).

### Out of scope for now (non-goals)

- **Running native 3ds Max plugins** (`.dlm`, `.dlo`, `.dlr`, `.dlu`, `.dle`, `.dli`, `.gup`, `.dll`, …). Not planned.
- **Animation** import and Max's controller system. Revisit after v1.
- **Saving `.max` files.** Native save is `.blend`; interchange is FBX / USD / OBJ.
- **MAXScript** compatibility.
- **Staying in sync with upstream Blender.** The fork is allowed to diverge. Occasional deliberate merges of a newer Blender LTS are possible but not required.

## 3. Hard constraints

1. **Licence:** everything in this repo is GPL-compatible (the fork as a whole is GPL, matching Blender). Third-party code must be GPL-compatible and keep its copyright headers.
2. **No Autodesk assets:** do not copy icons, images, splash screens, UI artwork, names or logos. Draw original icons. Describe the project as "Max-compatible", never as "3ds Max".
3. **No Autodesk SDK code:** do not copy code or headers from the 3ds Max SDK. The `.max` reader is built from analysing real files (interoperability). If you want to use SDK documentation as a reference for something (e.g. class IDs, parameter meanings), flag it to the maintainer first.
4. **Clean behaviour, original implementation:** replicate *behaviour* (what a feature does, hotkeys, workflow), never copied implementation.
5. **Test files are never committed:** `.max` files and their reference exports stay in the gitignored `tests/corpus/local/` (or `$MX_CORPUS_DIR`). See `docs/decisions/0004-local-corpus.md`.

## 4. Architecture and repo layout

### 4.1 Base

- Fork Blender from the **latest LTS release at the time of forking** (check blender.org for the current LTS; record the exact version and commit in `docs/decisions/0001-base-version.md`).
- Build following Blender's official build docs for each target platform (Windows first — most Max users are on Windows — then Linux, then macOS).

### 4.2 Project code

All project-specific Python lives in bundled add-ons that ship enabled by default. Blender 4.2+ loads bundled add-ons from `scripts/addons_core/` (verified for 5.2).

```
scripts/addons_core/
  mx_keymap/          # Max hotkeys + navigation (Phase 1)
  mx_ui/              # quad menus, command panel, theme, startup layout (Phase 1)
  mx_io_max/          # .max importer, Blender side (Phase 2)
    __init__.py       # operator, menu entry, drag-and-drop handler
    build_scene.py    # turns parsed data into Blender objects
    materials/        # one module per Max material/map family
    modifiers/        # one module per Max modifier
    primitives/       # one module per Max primitive

scripts/modules/
  mx_common/          # shared helpers (units, axis, logging, report UI); a plain module, not an add-on

pylibs/maxfile/       # pure-Python .max parser, NO bpy dependency (not `libs/`: Blender's `lib/` holds precompiled deps)
  pyproject.toml
  maxfile/
    container.py      # OLE / Compound File reading
    chunks.py         # chunk tree parsing
    classes.py        # class directory, DLL directory, class-ID registry
    scene.py          # node tree, transforms, references
    objects/ ...      # decoders per object type
  tests/              # pytest, runs without Blender

tests/
  corpus/             # corpus tooling; the .max files themselves live in the gitignored corpus/local/ (see §6)
  blender/            # headless Blender tests (blender -b --python ...)

docs/
  decisions/          # architecture decision records
  format/             # what we've learned about the .max format
  outreach/           # drafts of messages for the maintainer to send
  CONTRIBUTING.md
```

See `docs/decisions/0002-repo-layout.md` for why this differs slightly from the first draft (`pylibs/`, `mx_common` location) and how `maxfile` reaches Blender.

**Key rule:** `pylibs/maxfile` parses `.max` files into plain Python data (dataclasses) and knows nothing about Blender. `mx_io_max` converts that data into Blender objects. This lets most of the importer be unit-tested with plain `pytest`, and lets the parser be reused by other projects.

The module name prefix `mx_` is a placeholder; rename when the project name is decided.

---

## 5. Phases

Status legend: `[ ]` not started · `[~]` in progress · `[x]` done

### Phase 0 — Foundations

Goal: a forked, buildable, testable repo that contributors can join.

- [x] Fork Blender at the chosen LTS; record version in `docs/decisions/0001-base-version.md`. *(Proposed 5.2 LTS, `v5.2.2`; branch `mx/main`. Waiting for confirmation and a hosted remote.)* *(Branch `mx/main` at `v5.2.2` on `eolix/3Dmach`.)*
- [ ] Confirm a clean build on Windows; document build steps in `docs/BUILDING.md`.
- [ ] Rename app branding to `PROJECT_NAME` (window title, splash text, about box). Keep Blender credit and licence notices intact.
- [x] Create the add-on and `pylibs/maxfile` skeletons from §4.2, with `pytest` wired up.
- [x] Headless test runner (`tests/blender/run_tests.py`): a script that runs every test in `tests/blender/` via `blender -b --factory-startup --python ...` and exits non-zero on failure.
- [~] CI (GitHub Actions or similar): build on at least one platform, run `pytest pylibs/maxfile` and `pytest tests/corpus`, run headless Blender tests. *(`.github/workflows/tests.yml` (pytest + headless tests on official 5.2.2) runs on every `mx/**` push; `build.yml` (full Linux x64 build) is manual and not yet verified.)*
- [~] `README.md`, `CONTRIBUTING.md` (how to build, how to add a modifier/material/primitive decoder, how to submit test files), issue templates ("unsupported .max feature", "bug", "test file submission"). *(First draft of `docs/CONTRIBUTING.md`; README waits on the project name, issue templates on the hosting choice.)*
- [x] Set up `tests/corpus/` with its manifest format (§6). *(Local-only corpus: `tests/corpus/README.md`, `tests/corpus/corpus.py`.)*

**Done when:** a new contributor can clone, build, run the tests and see them pass by following the docs.

### Phase 1 — The Max shell (Python only)

Goal: a Max user feels at home navigating and selecting, even before `.max` import exists. Everything here must also work as standalone add-ons on stock Blender, so people can try it early.

#### 1a. Keymap and navigation (`mx_keymap`)

Build a full custom keymap. Verify each binding against Max's defaults (ask the maintainer when unsure). Starting list:

| Action | Max default |
|---|---|
| Orbit | Alt + Middle mouse |
| Pan | Middle mouse drag |
| Zoom | Mouse wheel; Ctrl+Alt + Middle mouse |
| Zoom extents selected | Z |
| Maximise / restore viewport | Alt+W |
| Select / Move / Rotate / Scale | Q / W / E / R |
| Sub-object levels | 1–5 (vertex, edge, border, polygon, element); 6 = back to top level |
| Views | T top · B bottom · F front · L left · P perspective · U user (ortho) · C camera |
| Wireframe / shaded toggle | F3 |
| Edged faces toggle | F4 |
| Grid toggle | G |
| Select by name | H |
| Snap toggle / angle snap | S / A |
| Transform gizmo toggle | X |
| Isolate selection | Alt+Q |
| Lock selection | Space |
| Material editor | M |
| Render setup / quick render | F10 / Shift+Q (and F9 render last) |
| Clone | Shift + drag with transform tool → Clone Options dialog (Copy / Instance / Reference, number of copies) |
| Selection modifiers | Click = select; Ctrl+click = add; Alt+click = remove |
| Undo / redo | Ctrl+Z / Ctrl+Y |

- [~] Viewport navigation matches Max, including orbit around selection/sub-object. *(`mx_keymap`; orbit around selection, zoom to mouse. Needs a hands-on check.)*
- [x] Transform tools follow Max's persistent-tool model: W/E/R choose a tool that stays active, rather than Blender's modal G/R/S operation.
- [x] Sub-object hotkeys map onto Blender edit-mode select modes (border = boundary-loop selection, element = linked selection) as a Phase-1 approximation. *(Approximations listed in `docs/keymap.md`.)*
- [~] Shift+drag clone with an options dialog (Copy → duplicate, Instance → linked duplicate; Reference → treat as Instance for now and note it). *(Implemented; the drag-then-dialog flow still needs a hands-on check.)*
- [x] Keymap is a selectable preset and the default in the fork. *(Preset `Max-Style`; factory default in `blendfile.cc`. See `docs/keymap.md`, decision 0005.)*

#### 1b. UI (`mx_ui`)

- [~] **Quad menu** on right-click in the viewport, context-sensitive (object mode vs edit mode), with Max's four-quadrant layout (tools 1 / tools 2 / display / transform). Implement as a custom popup or pie-style menu. *(`VIEW3D_MT_mx_quad` (pie with four quadrant columns); opens like a Blender pie (doesn't stay open like Max's).)*
- [x] **Command panel** docked on the right with tabs: Create, Modify, Hierarchy, Display, Utilities. (Motion tab omitted until animation is in scope.) *(In the Properties editor's Tool tab (decision 0007). Blender's own tool panels still show below it.)*
  - Create: primitive buttons (Box, Sphere, Cylinder, Plane, Cone, Torus, Tube, Pyramid, GeoSphere, Teapot-equivalent → use an original test shape, not the Utah teapot data unless its licence is confirmed), splines, lights, cameras.
  - Modify: object name + colour swatch, modifier list dropdown, stack view, parameters of the selected stack entry.
  - Hierarchy: pivot editing (affect pivot only / affect object only / center to object / align to world).
  - Display: hide/freeze by selection, category, etc.
- [x] **Freeze** (Max concept) → make objects unselectable and greyed out.
- [x] **Layer / Scene Explorer** panel mapped onto collections.
- [x] **Theme**: original dark-grey theme inspired by Max's palette. No copied assets. *(Applied on request (`preferences.mx_apply_theme`).)*
- [~] **Startup file**: four-viewport layout (Top, Front, Left, Perspective), command panel on the right, time slider hidden (animation out of scope), Max-like grid. *(`screen.mx_max_layout` + applied to new files; checked in GUI screenshots. Viewports should zoom extents after building.)*
- [x] **Units**: Max-style units setup dialog (display units + system unit scale) mapped to Blender scene units.

#### 1c. Live primitives (Python first pass)

- [x] Max-style primitives that keep editable parameters (length, width, height, segments, etc.) after creation, shown in the Modify tab, until the user converts them to Editable Poly. First pass: implement with Geometry Nodes groups or a parameter property group plus regeneration; record the choice in a decision record. *(`mx_primitives`, decision 0006. Topology not yet checked against Max's own meshes.)*
- [x] Interactive creation by click-drag in the viewport (base, then height), as in Max. *(Checked in the GUI with simulated mouse events.)*

**Done when:** a Max user can navigate, select, create primitives, apply modifiers and transform objects using only Max habits, in the fork and as add-ons on stock Blender.

### Phase 2 — `.max` import

Goal: open real-world `.max` files with correct geometry, structure and materials that render convincingly in Cycles/EEVEE.

#### 2a. Prior art (do this first)

- [x] Study the existing GPL importer **"Import Autodesk MAX (.max)"** (`io_scene_max`, by Sebastian Sille / NRGSille, with Philippe Lagadec and Jens M. Plonka). It's on extensions.blender.org and in the Blender repos on projects.blender.org, licensed GPL-2.0-or-later. *(Studied 1.9.2 from extensions.blender.org. Its source headers say GPL-2.0-or-later, its manifest GPL-3.0-or-later; see §10.)*
- [x] Write `docs/format/overview.md` summarising what it reveals about the format: container, streams, chunk structure, class directory, how meshes and materials are stored, compression, version differences.
- [x] Decide: refactor it into the `libs/maxfile` / `mx_io_max` split, or rewrite using it as reference. Either way, keep attribution and licence headers. Record in a decision record. *(Proposed: rewrite, using it as a reference. See `docs/decisions/0003-io-scene-max-rewrite.md`.)*
- [~] Contact the original author about collaborating or upstreaming fixes (maintainer will do this; the agent drafts the message). *(Draft in `docs/outreach/io_scene_max-author.md`.)*

#### 2b. Container and scene graph (`pylibs/maxfile`)

- [x] Read the Compound File (OLE) container and list its streams.
- [x] Parse chunk trees; handle compressed streams where present.
- [x] Parse the class directory and DLL directory; build a registry mapping class IDs → names → decoder modules.
- [~] Parse scene nodes: name, parent, transform (node TM, object offset / pivot), visibility, hidden/frozen state, wire colour, layer. *(Name, parent, transform, object offset; visibility/hidden/frozen/wire colour/layer not decoded yet (need real files).)*
- [x] Resolve references so instances share one data block.
- [ ] Read scene units and convert to metres. Max and Blender are both Z-up; verify axis handling against reference exports.
- [x] `maxdump` CLI: `python -m maxfile.dump file.max` prints the scene tree, class list and any unknown classes. This is the main tool for contributors adding support for new classes. *(`docs/format/maxdump.md`.)*

#### 2c. Geometry

Priority order (most common in real files first):

- [~] Editable Poly, including material IDs per face, smoothing groups, UV channels, vertex colours. *(Decoded per the documented layouts; not yet verified on real files. Vertex colours not imported.)*
- [~] Editable Mesh. *(Same: unverified on real files.)*
- [~] Standard primitives → rebuilt as **live** primitives from Phase 1c (Box, Sphere, Cylinder, Plane, Cone, Torus, Tube, Pyramid, GeoSphere). *(Max's cached mesh is used when present; otherwise rebuilt live from the decoded parameters (segment counts not decoded yet).)*
- [ ] Extended primitives (ChamferBox, ChamferCyl, …).
- [ ] Splines: Line, Rectangle, Circle, Arc, Text → Blender curves, including renderable-spline thickness.
- [ ] Groups → empties/collections with matching hierarchy.
- [x] Smoothing groups → sharp edges / custom normals. Pick the approach that matches Max shading most closely and document it. *(Sharp edges + flat faces (`mx_io_max/smoothing.py`).)*

#### 2d. Modifier stack

Each supported Max modifier becomes an equivalent Blender modifier (or Geometry Nodes group) in the same stack order, so the result stays editable. Where behaviour differs, prefer a faithful Geometry Nodes implementation over a loose built-in equivalent, and document the difference.

| Max modifier | First mapping |
|---|---|
| TurboSmooth / OpenSubdiv / MeshSmooth | Subdivision Surface |
| Shell | Solidify |
| Symmetry | Mirror (+ bisect) |
| Chamfer | Bevel |
| Bend / Twist / Taper | Simple Deform |
| FFD (2×2×2, 3×3×3, 4×4×4, Box) | Lattice |
| Noise | Displace + noise texture |
| UVW Map (planar, cylindrical, spherical, box) | Generate UVs to match Max's projection (custom, likely Geometry Nodes) |
| Unwrap UVW | Read stored UVs |
| Smooth | Smooth by angle |
| Normal | Flip normals |
| Extrude / Lathe / Sweep (on splines) | Curve → mesh via Geometry Nodes |
| Edit Poly | Bake if the file stores the result; otherwise import base object and report |

- [x] **Unsupported modifiers never block import.** Import the stack up to that point, add a placeholder, and list it in the import report. *(`docs/format/modifiers.md`.)*
- [x] Option: "Collapse stack on import" (bake everything) vs "Keep stack live" (default).

#### 2e. Materials and textures (`mx_io_max/materials`)

Translate to Principled BSDF node trees that render close to the original in Cycles and acceptably in EEVEE.

- [~] **Multi/Sub-Object** → Blender material slots assigned by face material ID. Highest priority: almost every real scene uses it. *(Slots by material ID; the ID list itself isn't decoded yet.)*
- [~] Physical Material. *(Converter done; parameter decoding needs real files.)*
- [~] Standard (Legacy). *(Converter done; parameter decoding needs real files.)*
- [~] VRayMtl. *(Converter done; only diffuse and reflection glossiness decoded so far.)*
- [~] Corona Physical Material / Corona Legacy Material. *(Converter done; parameter decoding needs real files.)*
- [~] Arnold Standard Surface. *(Converter done; sockets decoded per the documented layout.)*
- [~] Blend / layered materials → Mix Shader. *(Node builder done; decoding not yet.)*
- [~] Maps: Bitmap (path, tiling, offset, rotation, real-world scale, gamma), Falloff, Mix, Color Correction, Noise, Checker, Gradient, Normal Bump / VRayNormalMap / CoronaNormal, Bump. *(Node builders for all listed maps; only bitmap paths are decoded so far.)*
- [x] Texture path resolution: absolute path → relative to `.max` → a user-chosen search folder → report missing. *(`materials/textures.py`.)*
- [x] Unknown materials → a placeholder material with the original diffuse colour if readable, named after the original class, and listed in the import report.

#### 2f. Cameras and lights

- [~] Physical Camera, Target/Free Camera (FOV, sensor, target → Track To constraint). *(Conversion done (`lights.py`, `docs/format/lights.md`); camera decoding needs real files.)*
- [~] Photometric lights, V-Ray lights, Corona lights, Sun/Sky → Blender light types with approximate intensity conversion; document the formulas. *(Conversion done; light decoding needs real files.)*
- [~] Environment / background colour and HDRI map → World. *(Conversion done; decoding needs real files.)*

#### 2g. User experience

- [x] File → Import → `.max`, plus drag-and-drop into the viewport.
- [x] **Import report** panel after each import: objects, materials, modifiers imported; unsupported classes with counts; missing textures. Exportable as text, so users can attach it to bug reports. *(Text block "Import Report" + status-bar summary.)*
- [x] Graceful failure: a corrupt or unsupported-version file gives a clear message, never a crash. *(Fuzzed: corrupt files raise `MaxFileError`, reported to the user.)*
- [ ] Performance target: a 1-million-polygon scene imports in under 30 s on a mid-range machine (adjust after measuring).

**Done when:** at least 80% of the test corpus (§6) imports with correct geometry (within tolerance of reference exports) and recognisable materials, and every unsupported feature is reported rather than silently dropped.

### Phase 3 — Max-native behaviour (C++ core changes)

Requires maintainer approval per item and a design note (§8) before any code. Candidates, in rough priority order:

- [ ] **Editable Poly as a stack-aware object type**: sub-object editing that can sit in the modifier stack (Max's Edit Poly modifier), with sub-object selection passing up the stack. *(Design note: `docs/design/edit-poly-in-stack.md` (waiting for approval).)*
- [ ] **Persistent sub-object selection** that survives mode switches and is visible to modifiers above it.
- [ ] **Native live primitives** (replace the Phase 1c Python version if it proves too slow or fragile).
- [ ] **Max transform behaviour**: reference coordinate systems (View, Screen, World, Parent, Local, Gimbal, Grid, Pick), pivot modes (pivot point center / selection center / transform coordinate center), constrained axes via gizmo planes.
- [ ] **Max-faithful modifiers** where Blender's equivalents differ noticeably (Chamfer vs Bevel, Shell vs Solidify, Symmetry vs Mirror).
- [ ] **Clone "Reference"** semantics: shared base object, independent modifiers on top.
- [ ] **Max-style material editor** (Slate-like node editor UX built on Blender shader nodes).

### Phase 4 — First public release (v0.1)

- [ ] Installers / portable builds for Windows (then Linux, macOS).
- [ ] Original icon set and splash screen.
- [ ] User docs: "Coming from 3ds Max" quick guide, keymap reference card, supported-features matrix for `.max` import (generated automatically from the decoder registry).
- [ ] Website / repo landing page with clear pitch and contribution guide.

### Later (post-v1, not now)

- Animation import (keyframes, basic controllers) and Motion panel.
- Additional plugin object decoders (scatter tools, parametric architecture objects).
- MAXScript subset.

---

## 6. Test corpus

Most `.max` work depends on real files. The agent cannot create them, so this is a maintainer/contributor task, and the agent's job is to make using them easy.

The files are **never committed**. Every `*.max` file under the gitignored `tests/corpus/local/` (or `$MX_CORPUS_DIR`) is a test case; tests that need the corpus skip when it is empty. Each case can have reference exports next to it (`<name>.obj` / `reference.obj`: geometry with the stack collapsed; `<name>.fbx` / `reference.fbx`: hierarchy, transforms, cameras). An optional `manifest.toml` adds Max version, renderer, features exercised and expected pass/fail status. Details in `tests/corpus/README.md`.

Automated checks per case:

- Geometry: vertex/face counts and bounding boxes match `reference.obj` within tolerance; per-object comparison where names match.
- Hierarchy and transforms: compare against `reference.fbx`.
- Materials: correct slot count and assignment per face; texture paths resolved.
- Visual (optional, non-blocking): render in Cycles at low samples and compute an image difference against `reference.png`; store results as CI artifacts.

Coverage to aim for: one small case per feature (one modifier, one material type, …), plus a handful of realistic full scenes (archviz interior, product shot, game asset), across several Max versions.

## 7. Contribution model

- Each unsupported Max class becomes an issue labelled `decoder` with: class name, class ID, `maxdump` output, and a test file. These are the main "good first issues".
- Adding support for a class = one decoder module + one registry entry + one corpus case + tests. `CONTRIBUTING.md` must walk through this with a worked example.
- The supported-features matrix in the docs is generated from the registry, so it never goes stale.

## 8. Design notes for core changes

Before any C++ change (Phase 3), write `docs/design/<feature>.md` covering: the Max behaviour being replicated (described in words, from the user's point of view), the Blender code areas affected, the proposed approach, risks, and how it will be tested. Wait for maintainer approval.

## 9. Definition of done for v0.1

1. Builds and installs on Windows.
2. Max keymap, quad menus, command panel and four-viewport startup layout are the defaults.
3. Live primitives with interactive creation.
4. `.max` import meets the Phase 2 "done when" bar on the test corpus.
5. Imported scenes render in Cycles with recognisable materials.
6. Import report clearly lists anything unsupported.
7. Docs: building, contributing, "coming from Max" guide, feature matrix.

## 10. Open questions for the maintainer

- [ ] Project name (no Autodesk trademarks). *Repository is `3Dmach`: use that as the app name?*
- [x] Base Blender LTS version. *Accepted: 5.2 LTS (`v5.2.2`), see `docs/decisions/0001-base-version.md`.*
- [ ] Which renderers' materials matter most first (V-Ray, Corona, Arnold, Physical)?
- [ ] Who can produce test files and reference exports from 3ds Max, and which Max versions?
- [ ] Target platforms and order (proposed: Windows → Linux → macOS).
- [x] Repo hosting and CI provider. *(GitHub `eolix/3Dmach`, GitHub Actions.)* (Note: Blender 5.2 has no precompiled Linux arm64 libraries, so Linux CI should run on x64.)
- [x] Layout changes in `docs/decisions/0002-repo-layout.md` (`pylibs/maxfile`, `mx_common` in `scripts/modules/`): OK? *(Yes.)*
- [x] Should `.max` and other binary corpus files go through Git LFS? *(No: they are not committed at all, see `docs/decisions/0004-local-corpus.md`.)*
- [ ] Rewrite rather than refactor `io_scene_max` *(done that way)* (`docs/decisions/0003-io-scene-max-rewrite.md`): OK?
- [ ] First corpus files: `docs/format/overview.md` ends with 13 format points to verify on real files. Even three or four tiny scenes (a box, an Editable Poly with two material IDs, a Multi/Sub-Object material, a parented hierarchy) saved from two different Max versions would cover most of them.
- [ ] Licence of the prior-art importer: `io_scene_max` 1.9.2's source headers say GPL-2.0-or-later, its extension manifest says GPL-3.0-or-later. Either is compatible, but if we copy code from it we should know which applies (ask the author when contacting them, §2a).

---

## 11. First tasks for the agent (start here)

1. Phase 0: create the repo skeleton from §4.2 **without** the Blender fork first (add-ons + `libs/maxfile` + tests), so Phase 1 and 2 work can start while the fork build is being set up.
2. Phase 2a: study the existing `io_scene_max` importer and write `docs/format/overview.md`.
3. Phase 2b: implement `maxfile.container` + the `maxdump` CLI, tested against any `.max` files the maintainer provides.
4. Phase 1a: the `mx_keymap` add-on, testable on stock Blender.
5. Then fork Blender and wire the add-ons in as bundled, enabled-by-default add-ons.

After each task: update the checklists above, list any new open questions in §10, and stop for review.
