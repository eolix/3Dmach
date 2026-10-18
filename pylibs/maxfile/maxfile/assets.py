# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
The asset metadata stream: bitmap file paths in newer files (``docs/format/overview.md`` §5.2).

This is the least understood part of the format. The overview only says that the stream isn't a chunk tree,
that the prior-art importer finds it by directory position rather than by name, and that it splits the data on
runs of zero bytes and pairs "headers" with UTF-16 path strings. This module does that, **best effort**, and
keeps the raw pieces so the stream can be studied with ``maxdump``. Nothing here should be relied on before it is
checked on real files.
"""

__all__ = (
    "AssetEntry",
    "AssetMetadata",
    "find_asset_stream",
    "parse_asset_metadata",
    "read_asset_metadata",
)

import dataclasses
import re

from .errors import MaxFileError

# Streams known to be chunk trees, never the asset metadata (overview.md §1).
_CHUNK_STREAMS = {"SCENE", "CLASSDIRECTORY3", "CLASSDIRECTORY", "DLLDIRECTORY", "CLASSDATA", "CONFIG",
                  "VIDEOPOSTQUEUE"}
# Unverified (overview.md §1): the importer takes the directory entry with the highest index, capped at 11.
_MAX_ENTRY_ID = 11
# Unverified (overview.md §5.2): the stream is split on runs of zero bytes. "00 00 00": the end of a UTF-16
# string (high byte of the last character plus a 16-bit terminator) is the shortest run that separates fields.
_SPLIT = re.compile(b"\x00{3,}")


@dataclasses.dataclass(slots=True)
class AssetEntry:
    """A path string found in the stream, with the bytes before it ("header", meaning unknown)."""
    index: int          # Position among the paths found. Whether asset indices count this way is a guess.
    header: bytes
    path: str
    offset: int         # Offset of the path in the stream.


@dataclasses.dataclass(slots=True)
class AssetMetadata:
    stream: str | None          # Name of the stream read, None when none was found.
    entries: list[AssetEntry]
    warnings: list[str] = dataclasses.field(default_factory=list)

    def path(self, asset_index: int) -> str | None:
        """The path at ``asset_index`` (guess: indices count the paths in stream order), or None."""
        if 0 <= asset_index < len(self.entries):
            return self.entries[asset_index].path
        return None


def _as_path(segment: bytes) -> str | None:
    """``segment`` as UTF-16LE text when it plausibly is a file path, else None."""
    for start in (0, 1):    # The zero run may have eaten the high byte of a character before the string.
        data = segment[start:]
        if len(data) % 2:
            data += b"\0"
        if len(data) < 6:
            continue
        try:
            text = data.decode("utf-16-le").rstrip("\0")
        except UnicodeDecodeError:
            continue
        if not text.isprintable() or "\0" in text:
            continue
        ascii_count = sum(1 for c in text if " " <= c <= "~")
        if ascii_count * 2 < len(text):
            continue
        if any(sep in text for sep in ("\\", "/")) or re.search(r"\.[A-Za-z0-9]{2,5}$", text):
            return text
    return None


def parse_asset_metadata(data: bytes) -> list[AssetEntry]:
    """Split the stream as described in overview.md §5.2 and pair each path with the segment before it."""
    entries = []
    previous = b""
    pos = 0
    for match in list(_SPLIT.finditer(data)) + [None]:
        end = match.start() if match is not None else len(data)
        segment = data[pos:end]
        if segment:
            path = _as_path(segment)
            if path is not None:
                entries.append(AssetEntry(len(entries), previous, path, pos))
                previous = b""
            else:
                previous = segment
        if match is not None:
            pos = match.end()
    return entries


def find_asset_stream(container):
    """
    The asset metadata stream candidate, or None.

    Like the prior-art importer, the directory entry with the highest index up to ``_MAX_ENTRY_ID``; unlike it,
    streams known to be chunk trees are skipped (our own guard, also unverified).
    """
    candidates = [e for e in container.streams()
                  if e.id <= _MAX_ENTRY_ID and e.path_str.upper() not in _CHUNK_STREAMS]
    return max(candidates, key=lambda e: e.id) if candidates else None


def read_asset_metadata(container) -> AssetMetadata:
    """Find and parse the asset metadata stream of a :class:`~maxfile.container.CompoundFile`."""
    entry = find_asset_stream(container)
    if entry is None:
        return AssetMetadata(None, [], ["no asset metadata stream candidate"])
    try:
        data = container.read_stream(entry.path)
    except MaxFileError as ex:
        return AssetMetadata(entry.path_str, [], ["asset metadata stream {!r}: {:s}".format(entry.path_str, str(ex))])
    return AssetMetadata(entry.path_str, parse_asset_metadata(data))
