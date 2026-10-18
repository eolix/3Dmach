# 3Dmach

A free, open-source, Max-compatible 3D application: Max-style navigation, quad menus, command panel and
modelling workflow; opens `.max` files and renders their materials with Blender's renderers (Cycles / EEVEE). Built as a fork of
[Blender](https://www.blender.org) 5.2 LTS. Not affiliated with or endorsed by Autodesk.

**Status: early development.** See [`ROADMAP.md`](../ROADMAP.md) for the plan and progress.

What it adds on top of Blender (as bundled add-ons, which also run on a stock Blender 5.2):

| Add-on | What |
|---|---|
| `mx_keymap` | Max-style hotkeys and viewport navigation |
| `mx_ui` | Quad menus, command panel, Max-style layout and theme |
| `mx_primitives` | Live primitives with editable parameters and click-drag creation |
| `mx_io_max` | `.max` scene import (in progress), built on the pure-Python [`maxfile`](../pylibs/maxfile) reader |

## Getting started

- Building: [`docs/BUILDING.md`](../docs/BUILDING.md)
- Contributing and running the tests: [`docs/CONTRIBUTING.md`](../docs/CONTRIBUTING.md)
- What we know about the `.max` format: [`docs/format/`](../docs/format/)

## Licence

GPL, like Blender: the fork as a whole is licensed under the GNU General Public License, version 3; individual
files may carry a different but compatible licence. Blender is a trademark of the Blender Foundation; "Max" and
"3ds Max" are trademarks of Autodesk, used here only to describe compatibility.
