# Building 3Dmach

3Dmach builds exactly like Blender 5.2 LTS, so Blender's
[build instructions](https://developer.blender.org/docs/handbook/building_blender/) apply. This page lists the
steps and the differences. The project's Python add-ons and the `maxfile` parser need no build: you can develop
and test them against an official Blender 5.2 release (see `docs/CONTRIBUTING.md`).

Status: the steps follow Blender's documented process; a full fork build has not yet been verified on every
platform. The `Build (Linux x64)` GitHub workflow (`.github/workflows/build.yml`, run manually) does the Linux steps.

## Windows (x64)

1. Install [Visual Studio 2022](https://visualstudio.microsoft.com/) Community with the "Desktop development with
   C++" workload, [Git for Windows](https://git-scm.com/) (with Git LFS) and [CMake](https://cmake.org/) 3.10+.
2. Clone and fetch Blender's precompiled libraries (about 6 GB):

   ```bat
   git clone git@github.com:eolix/3Dmach.git
   cd 3Dmach
   git switch mx/main
   make update
   ```

   `make update` also fetches Blender's Git LFS files (icons, startup file, …) from projects.blender.org, since
   this repository stores only their pointers.
3. Build: `make` (or `make ninja` with Ninja installed). The result is in `..\build_windows_x64_vc17_Release\bin\Release\`.

## Linux (x64)

```sh
sudo apt install build-essential git git-lfs cmake ninja-build libx11-dev libxxf86vm-dev libxcursor-dev \
    libxi-dev libxrandr-dev libxinerama-dev libegl-dev libwayland-dev wayland-protocols libxkbcommon-dev \
    libdbus-1-dev linux-libc-dev
git clone git@github.com:eolix/3Dmach.git && cd 3Dmach && git switch mx/main
make update
make ninja
../build_linux/bin/blender
```

Linux arm64 is not supported by Blender 5.2's precompiled libraries.

## macOS (Apple Silicon)

Install Xcode command line tools, CMake and Git LFS (e.g. with Homebrew), then `make update && make`.

## If it doesn't start

`bin/blender` needs the runtime folder next to it: `bin/5.2/` with `datafiles/` (fonts, icons, colour
management), `python/` (Python's standard library) and `scripts/` (including the 3Dmach add-ons and `maxfile`).
The build's **install step** creates it. `make` / `make ninja` always run it; building with `ninja` or
`cmake --build` directly in the build folder does not. Symptoms of a missing or partial `5.2/` folder:
`'fonts' data path not found`, `Font data directory "fonts/" could not be detected!`,
`Fatal Python error: Failed to import encodings module`, followed by a GLX/EGL assertion on exit.

Fix: run the install step, then start Blender from the build folder:

```sh
cmake --build ../build_linux --target install     # or: make ninja  (from the source folder)
ls ../build_linux/bin/5.2                         # datafiles  python  scripts
../build_linux/bin/blender
```

If `bin/5.2/python` is still missing, the precompiled libraries weren't fetched: run `make update` first
(it downloads `lib/linux_x64`), then build again.

On laptops with two GPUs, start it on the dedicated one with `switcherooctl launch ../build_linux/bin/blender`
(or, for NVIDIA, `__NV_PRIME_RENDER_OFFLOAD=1 __GLX_VENDOR_LIBRARY_NAME=nvidia ../build_linux/bin/blender`).

## What the fork changes in the build

- `source/creator/CMakeLists.txt` installs `pylibs/maxfile/maxfile` into `scripts/modules/` (see
  `docs/decisions/0002-repo-layout.md`).
- `source/blender/blenkernel/intern/blendfile.cc` enables the `mx_*` add-ons in the factory preferences.

## After building

Run the headless tests against your build:

```sh
python3 tests/blender/run_tests.py --blender /path/to/build/bin/blender
```
