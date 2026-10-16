# 0003: Rewrite the importer, using io_scene_max as a reference

- Status: Proposed (waiting for maintainer review)
- Date: 2026-10-16

## Context

ROADMAP Phase 2a asks whether to refactor the existing GPL importer `io_scene_max` (1.9.2, by Sebastian Sille,
with Jens M. Plonka and Philippe Lagadec) into our `maxfile` / `mx_io_max` split, or to rewrite it using it as a
reference. What it knows about the format is summarised in `docs/format/overview.md`.

What we found reading it:

- **Parsing and Blender are interleaved.** Material and mesh decoding call `bpy` and `mathutils` directly, and
  parse state lives in module globals (`SCENE_LIST`, `CLS_DIR3_LIST`, …). Splitting it means touching nearly
  every function.
- **Its design doesn't fit our goals.** It builds one mesh per node (no instancing), reduces modifier stacks to
  the base object, rebuilds primitives with Blender's operators, and swallows errors (`except: pass`). We need
  shared data blocks, live modifier stacks, Max-exact primitive topology and an import report.
- **The container code is a trimmed copy of `olefile`** (BSD-2-Clause, Philippe Lagadec). Container reading is
  fully specified by Microsoft's public [MS-CFB] document, so we can write a small, tested reader without
  carrying derived code.
- **The licence is unclear:** source headers say GPL-2.0-or-later, the extension manifest says GPL-3.0-or-later.
  Either is compatible with the fork, but copying code would make us depend on the answer.
- **The useful part is the knowledge:** chunk IDs, class IDs, which reference slot holds what, mesh chunk layouts,
  parameter indices per material. That is information about the file format.

## Decision

Rewrite. `maxfile` and `mx_io_max` are written fresh to our architecture (pure-Python parser into dataclasses,
Blender-side builder, decoder registry, import report). `io_scene_max` is used as a **reference** for format
knowledge, which is then verified against real corpus files before a decoder depends on it (ROADMAP §0.6).

- The container reader is written from [MS-CFB].
- Format facts taken from `io_scene_max` are credited in `docs/format/` and in the `maxfile` README.
- If we do adapt a piece of its code (for example a tricky decoder), that file keeps the original copyright
  lines and licence header, and we settle the GPL-2.0/3.0 question with the author first.
- The outreach message to the author (drafted in `docs/outreach/io_scene_max-author.md`) proposes sharing
  findings both ways, so fixes and format knowledge can flow back to `io_scene_max`.

## Consequences

- More work up front than refactoring, but no large untested code base to untangle, and the parser can be
  unit-tested from day one.
- Until our importer catches up, `io_scene_max` imports some things we don't (materials, primitives). It stays
  useful as a comparison point when debugging; it is a separate extension and is not bundled.
- Format knowledge has to be re-verified on real files, which needs the test corpus (ROADMAP §6, §10).

[MS-CFB]: https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-cfb/
