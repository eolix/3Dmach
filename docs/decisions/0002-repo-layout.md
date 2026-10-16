# 0002: Repository layout adjustments

- Status: Proposed (waiting for maintainer review)
- Date: 2026-10-16

## Context

ROADMAP §4.2 sketches where project code lives. Putting that layout into the Blender source tree
raised three issues:

1. Blender already has a top-level **`lib/`** directory. It holds the precompiled dependencies
   (`lib/linux_x64`, `lib/windows_x64`, …) as git submodules managed by `make update`, and the build system
   refers to it. A sibling `libs/` directory is easy to confuse with it, in tab completion and in tooling.
2. **`mx_common`** holds helpers shared by the other add-ons; it is not an add-on itself. Anything in
   `scripts/addons_core/` is treated as an add-on: it needs a `bl_info`, shows up in Preferences > Add-ons
   and can be disabled by the user, which would break the add-ons that depend on it.
3. The importer add-on must be able to `import maxfile`, both in the fork and when the add-ons are tried on a
   stock Blender (ROADMAP Phase 1).

## Decision

- The parser lives in **`pylibs/maxfile/`** instead of `libs/maxfile/`. It is an ordinary Python project
  (`pyproject.toml`, tests in `pylibs/maxfile/tests/`), installable with `pip`, with no Blender dependency.
- `mx_common` is a plain module in **`scripts/modules/mx_common/`**. Blender puts `scripts/modules` on
  `sys.path` in every session, and installs the whole `scripts/` directory, so nothing else is needed in the fork.
- How `maxfile` reaches Blender:
  - **Fork:** an install rule will copy `pylibs/maxfile/maxfile/` to `scripts/modules/maxfile/` in the
    installed Blender (ROADMAP §11 task 5, a small change to `source/creator/CMakeLists.txt`).
  - **Tests:** `tests/blender/run_tests.py` copies the add-ons, `mx_common` and `maxfile` into a temporary
    directory passed as `BLENDER_SYSTEM_SCRIPTS`, so the tests run against the working tree on any
    Blender build, including stock 5.2.
  - **Stock Blender, as standalone add-ons:** decided when the add-ons are first packaged (Phase 1). The likely
    route is packaging each add-on as an extension (`blender_manifest.toml`) with `maxfile` and `mx_common`
    vendored into it or shipped as a wheel (extensions support bundled wheels).
- The add-ons use the `bl_info` format, which is what `scripts/addons_core/` expects. Extension manifests are
  added when packaging.
- Everything else follows §4.2. `docs/` sits next to Blender's own `doc/` (API docs, man page); that is only
  cosmetic, so it stays as specified.

## Consequences

- ROADMAP §4.2 is updated to match.
- One extra build rule in the fork (copying `maxfile` into the installed scripts).
- If the project is renamed, the `mx_` prefix appears in: `scripts/addons_core/mx_*`, `scripts/modules/mx_common`,
  operator and class names (`import_scene.mx_max`, `IMPORT_SCENE_OT_mx_max`, `IO_FH_mx_max`) and
  `tests/blender/run_tests.py` (which stages every `mx_*` add-on).
