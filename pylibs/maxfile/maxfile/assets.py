# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
The asset metadata stream: the external files a scene uses (bitmaps, IES files, animation files, ...).

Bitmaps don't store their file path themselves: their ``filename`` parameter holds an **asset ID** (a GUID, see
:mod:`maxfile.objects.maps`) and the path is looked up here. The table is a stream of its own, found **by name**:

- ``FileAssetMetaData3`` (530 corpus files, Max 2010-2018) and ``FileAssetMetaData2`` (90 files, Max 2008-2009);
  3 corpus files (animation clips without materials) have neither. No file has both.
- The stream is a plain sequence of entries, not a chunk tree::

      u8[16]  asset ID (a Windows GUID in its binary layout: u32, u16, u16, u8[8])
      string  asset type ("Bitmap", "Animation", "Photometric", "RenderOutput", "Sound", "VideoPost", "Other")
      string  file path as the user picked it (absolute, or relative to the project folder)
      string  (``FileAssetMetaData3`` only) the absolute path it last resolved to, often empty or the same

  where ``string`` = ``u32 character count`` + that many UTF-16LE characters + a 16-bit NUL terminator.

Verified on the whole corpus: this layout consumes every byte of all 620 streams (1,000 entries in version 3
streams, 453 in version 2), every entry's terminators are where the counts say, and 1,753 of the 1,779 corpus
Bitmaps find their asset ID here (the other 26 have no file loaded). The type strings and the meaning of the two
version-3 paths come from the values (e.g. ``Scenes\\SubDivSurfaces\\Flipper.jpg`` and
``P:\\Projects\\Sample Files\\Scenes\\SubDivSurfaces\\Flipper.jpg``).
"""

__all__ = (
    "ASSET_STREAMS",
    "AssetEntry",
    "AssetMetadata",
    "format_guid",
    "find_asset_stream",
    "parse_asset_metadata",
    "read_asset_metadata",
)

import dataclasses
import struct
import uuid

from .errors import MaxFileError

# Stream name -> number of strings per entry (verified, see the module docstring).
ASSET_STREAMS = {"FileAssetMetaData3": 3, "FileAssetMetaData2": 2}
GUID_SIZE = 16


def format_guid(raw: bytes) -> str:
    """
    An asset ID as text: ``6c009b10-b7e1-4141-86b8-d9f72423860f`` for the stored bytes ``10 9B 00 6C E1 B7 41 41
    86 B8 ...`` (a Windows GUID: u32, u16, u16 little-endian, then 8 bytes; the same form as
    :class:`maxfile.objects.paramblock.AssetRef`).
    """
    return str(uuid.UUID(bytes_le=bytes(raw[:GUID_SIZE])))


def _guid_key(guid) -> str:
    """Normalise an asset ID given as raw bytes, an ``AssetRef`` (``.raw``/``.guid``) or text (any case, braces)."""
    raw = getattr(guid, "raw", None)
    if raw:
        return format_guid(raw)
    if isinstance(guid, (bytes, bytearray, memoryview)):
        return format_guid(guid)
    text = getattr(guid, "guid", guid)
    return str(text).strip("{}").lower()


@dataclasses.dataclass(slots=True)
class AssetEntry:
    """One asset: its ID, type and path(s)."""
    index: int                      # Position in the stream.
    guid: str                       # format_guid() of the asset ID.
    kind: str                       # "Bitmap", "Animation", "Photometric", ...
    path: str                       # The path as stored (absolute, or relative to the project folder).
    resolved_path: str | None       # FileAssetMetaData3 only: the absolute path it last resolved to (None if empty).
    offset: int                     # Byte offset of the entry in the stream.


@dataclasses.dataclass(slots=True)
class AssetMetadata:
    stream: str | None              # Name of the stream read, None when the file has none.
    entries: list[AssetEntry]
    warnings: list[str] = dataclasses.field(default_factory=list)
    _by_guid: dict = dataclasses.field(default_factory=dict, repr=False)

    def __post_init__(self):
        for entry in self.entries:
            self._by_guid.setdefault(entry.guid, entry)

    def get(self, guid) -> AssetEntry | None:
        """The entry for an asset ID (raw 16 bytes, a paramblock ``AssetRef`` or GUID text), or None."""
        return self._by_guid.get(_guid_key(guid))

    def path(self, asset_index: int) -> str | None:
        """The path of the entry at position ``asset_index`` in the stream, or None."""
        if 0 <= asset_index < len(self.entries):
            return self.entries[asset_index].path
        return None


def _string(data, pos):
    if pos + 4 > len(data):
        raise MaxFileError("string length at offset {:d} runs past the end".format(pos))
    (count,) = struct.unpack_from("<I", data, pos)
    pos += 4
    end = pos + 2 * count
    if end + 2 > len(data):
        raise MaxFileError("string of {:d} characters at offset {:d} runs past the end".format(count, pos))
    if data[end:end + 2] != b"\0\0":
        raise MaxFileError("string at offset {:d} has no terminator".format(pos))
    return bytes(data[pos:end]).decode("utf-16-le", errors="replace"), end + 2


def parse_asset_metadata(data: bytes, strings: int = 3) -> tuple[list[AssetEntry], list[str]]:
    """
    Read the entries of an asset metadata stream (``strings`` = 3 for ``FileAssetMetaData3``, 2 for version 2).

    Returns ``(entries, warnings)``; reading stops at the first entry that doesn't fit, keeping the ones before.
    """
    entries, warnings = [], []
    pos = 0
    while pos < len(data):
        start = pos
        if pos + GUID_SIZE > len(data):
            warnings.append("asset metadata: {:d} trailing bytes at offset {:d}".format(len(data) - pos, pos))
            break
        guid = format_guid(data[pos:pos + GUID_SIZE])
        pos += GUID_SIZE
        try:
            values = []
            for _ in range(strings):
                text, pos = _string(data, pos)
                values.append(text)
        except MaxFileError as ex:
            warnings.append("asset metadata entry {:d}: {:s}".format(len(entries), str(ex)))
            break
        resolved = values[2] if strings >= 3 and values[2] else None
        entries.append(AssetEntry(len(entries), guid, values[0], values[1], resolved, start))
    return entries, warnings


def find_asset_stream(container):
    """The directory entry of the asset metadata stream (``FileAssetMetaData3`` or ``2``), or None."""
    for name in ASSET_STREAMS:
        entry = container.find(name)
        if entry is not None:
            return entry
    return None


def read_asset_metadata(container) -> AssetMetadata:
    """Find and parse the asset metadata stream of a :class:`~maxfile.container.CompoundFile`."""
    entry = find_asset_stream(container)
    if entry is None:
        return AssetMetadata(None, [])
    name = entry.path_str
    try:
        data = container.read_stream(entry.path)
    except MaxFileError as ex:
        return AssetMetadata(name, [], ["asset metadata stream {!r}: {:s}".format(name, str(ex))])
    strings = next((n for key, n in ASSET_STREAMS.items() if key.upper() == entry.name.upper()), 3)
    entries, warnings = parse_asset_metadata(data, strings)
    return AssetMetadata(name, entries, warnings)
