# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Texture maps (``docs/format/overview.md`` §5.2).

The overview documents no class IDs for maps and no map parameters, only where a **bitmap's file path** is
stored, in two schemes (unverified):

- *direct*: a UTF-16 string in chunk ``0x1230`` inside the bitmap's parameter object;
- *asset metadata*: chunk ``0x1260`` (or a class ``0x3333`` object) holds an asset index, and the path is looked
  up in the asset metadata stream (:mod:`maxfile.assets`).

So maps are read structurally: :func:`read_map` turns any object into a :class:`MapData` (class name and path),
and :func:`is_map_like` says whether an object carries one of those path chunks. Materials use both for the
objects they reference. ``params`` and ``sub_maps`` stay empty until real files show their layout.
"""

__all__ = (
    "MapData",
    "ASSET_REF_CLASS",
    "is_map_like",
    "read_map",
)

import dataclasses
import struct

from ..chunks import walk
from ..classes import ClassID

CHUNK_BITMAP_PATH = 0x1230      # UTF-16 path (direct scheme)
CHUNK_ASSET_INDEX = 0x1260      # Asset index (asset metadata scheme); layout not documented
ASSET_REF_CLASS = ClassID(0x3333)
# How deep below an object to look for the path chunks (they sit inside parameter entries).
_SEARCH_DEPTH = 3


@dataclasses.dataclass
class MapData:
    """A texture map. Only ``class_name`` and, for bitmaps, ``path`` are filled so far."""
    class_name: str
    name: str | None                # Not documented for maps yet: always None.
    params: dict
    path: str | None
    sub_maps: list                  # Not documented yet: always empty.
    index: int | None = None        # Object index of the map.
    path_source: str | None = None  # "0x1230", "asset_metadata" (guessed lookup) or "asset_object_0x3333".
    asset_index: int | None = None


def _find(chunk, types):
    for _depth, child in walk([chunk], _SEARCH_DEPTH):
        if child.type in types:
            return child
    return None


def _candidates(obj, ctx):
    # Unverified (overview.md §5.2): the path is "inside the bitmap's parameter object", which we take to be one
    # of the map's direct references; the map's own chunks are searched last.
    return [o for _slot, o in ctx.refs(obj)] + [obj]


def is_map_like(obj, ctx) -> bool:
    """True when ``obj`` or one of its direct references carries a bitmap path or asset index chunk."""
    key = ("map_like", obj.index)
    if key not in ctx.cache:
        found = False
        for candidate in _candidates(obj, ctx):
            if candidate.class_id == ASSET_REF_CLASS or _find(
                    candidate.chunk, (CHUNK_BITMAP_PATH, CHUNK_ASSET_INDEX)):
                found = True
                break
        ctx.cache[key] = found
    return ctx.cache[key]


def read_map(obj, ctx) -> MapData:
    """Read ``obj`` as a map (cached per scene)."""
    key = ("map", obj.index)
    if key in ctx.cache:
        return ctx.cache[key]
    result = MapData(obj.class_label(), None, {}, None, [], index=obj.index)
    ctx.cache[key] = result
    candidates = _candidates(obj, ctx)
    for candidate in candidates:
        chunk = _find(candidate.chunk, (CHUNK_BITMAP_PATH,))
        if chunk is not None and not chunk.is_container:
            result.path = chunk.string()
            result.path_source = "0x1230"
            return result
    for candidate in candidates:
        chunk = _find(candidate.chunk, (CHUNK_ASSET_INDEX,))
        if chunk is not None and not chunk.is_container:
            result.path_source = "asset_metadata"
            # Guess: the layout of 0x1260 isn't documented; we read its first u32 as the asset index.
            if chunk.payload_size >= 4:
                result.asset_index = struct.unpack_from("<I", chunk.data, 0)[0]
                assets = ctx.asset_metadata()
                if assets is not None:
                    # Guess: the asset index counts the paths in the asset metadata stream in order.
                    result.path = assets.path(result.asset_index)
            if result.path is None:
                ctx.warn("object {:d} ({:s}): asset index {!s} not resolved to a path".format(
                    obj.index, result.class_name, result.asset_index))
            return result
    for candidate in candidates:
        if candidate.class_id == ASSET_REF_CLASS:
            # Unverified (overview.md §5.2): a class 0x3333 object holds the asset index; where is not known.
            result.path_source = "asset_object_0x3333"
            ctx.warn("object {:d} ({:s}): asset reference object [{:d}] not decoded (layout unknown)".format(
                obj.index, result.class_name, candidate.index))
            return result
    return result
