# Contributing to 3Dmach

3Dmach is a fork of Blender that aims to look, feel and behave like a Max-style 3D application and to
open `.max` files. [`ROADMAP.md`](../ROADMAP.md) has the plan, the hard constraints (§3) and the current status.
Please read §3 before contributing: no Autodesk assets, no code or headers from the Max SDK, and `.max` test
files are never committed.

## Where things live

| Path | What |
|---|---|
| `scripts/addons_core/mx_keymap/` | Max-style hotkeys and navigation |
| `scripts/addons_core/mx_ui/` | Quad menus, command panel, theme, startup layout |
| `scripts/addons_core/mx_io_max/` | `.max` importer, Blender side |
| `scripts/addons_core/mx_primitives/` | Max-style live primitives; `geometry.py` is bpy-free |
| `scripts/modules/mx_common/` | Helpers shared by the add-ons |
| `pylibs/maxfile/` | `.max` parser, pure Python, no Blender dependency |
| `tests/blender/` | Tests that run inside headless Blender |
| `tests/corpus/` | Corpus tooling; your `.max` test files go in the gitignored `tests/corpus/local/` |
| `docs/decisions/` | Architecture decision records |
| `docs/format/` | What we know about the `.max` format |

Everything else is Blender.

## Building

Not documented yet (ROADMAP Phase 0, `docs/BUILDING.md`). Until then, follow Blender's
[build instructions](https://developer.blender.org/docs/handbook/building_blender/). The Python add-ons and the
parser can be developed and tested against an official Blender 5.2 release without building anything.

## Running the tests

Parser tests (plain Python 3.11+, no Blender needed):

```sh
python3 -m pip install pytest
cd pylibs/maxfile && python3 -m pytest
```

Primitive geometry and creation-math tests (plain Python, no Blender needed):

```sh
python3 -m pytest tests/primitives
```

Corpus tooling tests, and a listing of your local corpus:

```sh
python3 -m pytest tests/corpus
python3 tests/corpus/corpus.py
```

Tests inside Blender (a stock Blender 5.2 or a fork build):

```sh
python3 tests/blender/run_tests.py --blender /path/to/blender
```

The runner copies the add-ons and modules from your working tree into a temporary directory and runs each
`tests/blender/test_*.py` with `blender -b --factory-startup`. It does not touch your own Blender configuration.
Use `-k NAME` to run only matching test files and `-v` to see Blender's output for passing tests.

A Blender test file uses `unittest` and ends with:

```python
if __name__ == "__main__":
    _runner_util.main()
```

## Code style

- Follow Blender's Python style: `autopep8` settings from the root `pyproject.toml` (120 columns).
- Every source file starts with an SPDX header:

  ```python
  # SPDX-FileCopyrightText: 2026 3Dmach Authors
  #
  # SPDX-License-Identifier: GPL-2.0-or-later
  ```

  Code adapted from elsewhere keeps its original copyright lines and licence (it must be GPL-compatible).
- `pylibs/maxfile` must never import `bpy`, `mathutils` or other Blender modules; a test enforces this.
  The same goes for `mx_primitives/geometry.py` and `mx_primitives/creation.py`.

## Changes

- One feature per branch (`mx/<topic>`, based on `mx/main`) and per pull request.
- Every pull request updates the checklist in `ROADMAP.md` and adds or updates tests.
- Record non-obvious choices in `docs/decisions/NNNN-title.md` (copy `0000-template.md`).
- C++ changes to Blender itself need a design note in `docs/design/` and maintainer approval first (ROADMAP §8).

## Adding support for a Max class

To be written with the first decoder (ROADMAP Phase 2b/§7): one decoder module, one registry entry,
tests, checked against a local corpus case.

## Test files

See [`tests/corpus/README.md`](../tests/corpus/README.md).
