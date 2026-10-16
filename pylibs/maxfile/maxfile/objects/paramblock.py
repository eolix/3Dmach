# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Generic parameter blocks (``docs/format/overview.md`` §5.1, §6.4).

The overview describes how the prior-art importer finds a parameter: it scans the block's child chunks for one
whose payload **starts with a u16 equal to the parameter index**, and reads the value from the **end** of the
payload (a colour is the last ``f32[3]``, an RGB(A) colour the ``f32[3]`` at ``len - 16``, a float the last
``f32``). The class IDs of parameter-block objects are not documented, so this is a structural reader: it is
applied to whatever object a caller says is a parameter block, and every value it gives is a *guess* that the
caller picks from by the type it expects.
"""

__all__ = (
    "ParamEntry",
    "ParamBlockData",
    "read_param_block",
)

import dataclasses
import struct

_REFERENCE_CHUNKS = (0x2034, 0x2035)    # Reference lists, never parameters.


@dataclasses.dataclass
class ParamEntry:
    """One leaf chunk of a parameter block."""
    param_id: int               # The payload's first u16 (unverified meaning: the parameter index).
    chunk_type: int
    raw: bytes                  # The whole payload, id included.
    guessed: dict               # "float", "int", "color", "rgba_color": readings of the payload's end.

    def as_float(self) -> float | None:
        return self.guessed.get("float")

    def as_int(self) -> int | None:
        return self.guessed.get("int")

    def as_color(self) -> tuple | None:
        return self.guessed.get("color")

    def as_rgba_color(self) -> tuple | None:
        return self.guessed.get("rgba_color")


@dataclasses.dataclass
class ParamBlockData:
    object_index: int | None
    entries: list[ParamEntry]

    def get(self, param_id: int) -> ParamEntry | None:
        """The first entry with ``param_id``, or None."""
        for entry in self.entries:
            if entry.param_id == param_id:
                return entry
        return None


def _guesses(data: bytes) -> dict:
    # Unverified (overview.md §5.1): values are read from the end of the payload, after the u16 id.
    guesses = {}
    size = len(data)
    if size >= 6:
        guesses["float"] = struct.unpack_from("<f", data, size - 4)[0]
        guesses["int"] = struct.unpack_from("<i", data, size - 4)[0]
    if size >= 14:
        guesses["color"] = struct.unpack_from("<3f", data, size - 12)
    if size >= 18:
        guesses["rgba_color"] = struct.unpack_from("<3f", data, size - 16)
    return guesses


def read_param_block(obj_or_chunk) -> ParamBlockData:
    """Read a :class:`~maxfile.scene.SceneObject` (or a bare chunk) as a parameter block."""
    chunk = getattr(obj_or_chunk, "chunk", obj_or_chunk)
    index = getattr(obj_or_chunk, "index", None)
    entries = []
    for child in chunk.children:
        if child.is_container or child.type in _REFERENCE_CHUNKS or child.payload_size < 2:
            continue
        data = child.data
        entries.append(ParamEntry(struct.unpack_from("<H", data, 0)[0], child.type, data, _guesses(data)))
    return ParamBlockData(index, entries)
