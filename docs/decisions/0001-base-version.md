# 0001: Base the fork on Blender 5.2 LTS

- Status: Accepted
- Date: 2026-10-16

## Context

ROADMAP §4.1 asks for the fork to start from the latest Blender LTS release at the time of forking.
On 2026-10-16 the Blender releases were:

| Version | Kind | Notes |
|---|---|---|
| 4.5 | LTS | Older LTS, Python 3.11. |
| 5.2 | LTS | Latest LTS. `BLENDER_VERSION_SUFFIX` is `LTS` in `BKE_blender_version.h`. |
| 5.3 | Release branch (`blender-v5.3-release`) | Not LTS. |
| 5.4 | `main`, alpha | Not LTS, unstable. |

The newest 5.2 tag is `v5.2.2`.

## Decision

Fork from tag **`v5.2.2`**, commit **`d13f752e3b9c4f8c261cda552b1021f8bcc0382c`** (tagged 2026-09-14).

Branches in this repository:

- `mx/main`: the fork's trunk, created at `v5.2.2`.
- `mx/<topic>`: one branch per feature / PR, based on `mx/main` (ROADMAP §0.3).
- Upstream `main` and the `blender-v*-release` branches are left untouched, so upstream fixes can still be fetched.

## Consequences

- Blender's bundled Python is **3.13**. Project Python code must run on 3.13; `pylibs/maxfile` also supports
  3.11+ so contributors can run its tests with a system Python.
- Bundled add-ons load from `scripts/addons_core/` (checked against `scripts/modules/addon_utils.py` in 5.2).
- LTS versions get bug-fix releases for two years. Fixes from `blender-v5.2-release` (5.2.3, …) can be merged
  into `mx/main` when wanted; that is optional (ROADMAP §2 non-goals).
- Blender 5.2 has precompiled libraries for Linux x64, macOS arm64, Windows x64 and Windows arm64, but not
  Linux arm64. Linux builds (and CI) should use x64 machines.
