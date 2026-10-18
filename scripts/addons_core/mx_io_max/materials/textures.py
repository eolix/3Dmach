# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Find the texture files a ``.max`` scene refers to (ROADMAP Phase 2e).

Scenes usually store absolute Windows paths from the machine they were made on. Resolution order:

1. the path as stored, if it exists here;
2. the stored path relative to the ``.max`` file's folder (for relative paths), then the file name next to the
   ``.max`` file or in its ``maps``/``textures`` sub-folders;
3. the file name anywhere below the user's search folders (case-insensitive, like Windows);
4. otherwise it is reported missing.

No Blender dependency.
"""

__all__ = (
    "TextureResolver",
)

import ntpath
import os

COMMON_SUBDIRS = ("", "maps", "Maps", "textures", "Textures", "tex", "images", "sourceimages")


def _split_stored(path):
    """File name and relative-path parts of a stored path, whichever separator style it uses."""
    path = path.strip().strip('"')
    if "\\" in path or ntpath.splitdrive(path)[0]:
        drive, rest = ntpath.splitdrive(path)
        parts = [p for p in rest.replace("/", "\\").split("\\") if p]
        return parts, bool(drive) or rest.startswith(("\\", "/"))
    parts = [p for p in path.split("/") if p]
    return parts, path.startswith("/")


class TextureResolver:
    """Resolves stored texture paths, caching directory scans. One instance per import."""

    def __init__(self, max_path, search_dirs=(), recursive=True):
        self.base_dir = os.path.dirname(os.path.abspath(max_path)) if max_path else os.getcwd()
        self.search_dirs = [d for d in search_dirs if d and os.path.isdir(d)]
        self.recursive = recursive
        self._index = None          # lower-case file name -> first path found in the search dirs.
        self._cache = {}
        self.missing = []

    def _search_index(self):
        if self._index is None:
            self._index = {}
            for root in self.search_dirs:
                if self.recursive:
                    for dirpath, dirnames, filenames in os.walk(root):
                        dirnames.sort()
                        for name in sorted(filenames):
                            self._index.setdefault(name.lower(), os.path.join(dirpath, name))
                else:
                    for name in sorted(os.listdir(root)):
                        self._index.setdefault(name.lower(), os.path.join(root, name))
        return self._index

    @staticmethod
    def _find_case_insensitive(directory, name):
        exact = os.path.join(directory, name)
        if os.path.isfile(exact):
            return exact
        if not os.path.isdir(directory):
            return None
        lower = name.lower()
        for entry in os.listdir(directory):
            if entry.lower() == lower and os.path.isfile(os.path.join(directory, entry)):
                return os.path.join(directory, entry)
        return None

    def resolve(self, stored_path):
        """Return a usable local path for ``stored_path``, or None (and remember it as missing)."""
        if not stored_path:
            return None
        if stored_path in self._cache:
            return self._cache[stored_path]
        result = self._resolve(stored_path)
        self._cache[stored_path] = result
        if result is None and stored_path not in self.missing:
            self.missing.append(stored_path)
        return result

    def _resolve(self, stored_path):
        if os.path.isfile(stored_path):
            return stored_path
        parts, is_absolute = _split_stored(stored_path)
        if not parts:
            return None
        name = parts[-1]
        if not is_absolute:
            candidate = os.path.join(self.base_dir, *parts)
            if os.path.isfile(candidate):
                return candidate
        for subdir in COMMON_SUBDIRS:
            found = self._find_case_insensitive(os.path.join(self.base_dir, subdir), name)
            if found:
                return found
        return self._search_index().get(name.lower())
