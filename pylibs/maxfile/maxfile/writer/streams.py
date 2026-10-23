# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
The streams beside ``Scene`` / ``ClassDirectory3`` / ``DllDirectory``: ``Config``, ``VideoPostQueue``,
``SaveConfigData``, ``FileAssetMetaData3`` and the two property-set streams ([MS-OLEPS]).

Values are the dominant ones of the 305 files saved by Max 2015 ("n/305"); see ``docs/design/max-writer.md``.

[MS-OLEPS]: https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-oleps/
"""

__all__ = ("config_stream", "video_post_queue_stream", "save_config_stream", "asset_metadata_stream",
           "summary_information_stream", "document_summary_information_stream")

import struct
import uuid

from .chunks import cont, f32, leaf, u32


def config_stream(frame_rate=30, animation_end_frame=100, ticks_per_second=4800) -> bytes:
    """
    A minimal ``Config`` stream: the top-level records holding plain scalar settings, in the order of the corpus.

    Left out (Max keeps its defaults): viewport layouts (0x2080), plug-in configuration (0x21A0), scene explorer
    and editor window states (0x20A0, 0x20A5, 0x20A6, 0x2190, 0x2130, 0x2180).
    """
    ticks_per_frame = ticks_per_second // frame_rate
    return b"".join([
        leaf(0x2090, u32(0)),                                               # 274/305
        cont(0x20E0,                                                        # Grid settings (?)
             leaf(0x0100, f32(10.0) + u32(10, 1)),                          # 296/305
             leaf(0x0400, u32(7, 1)),                                       # 299/305
             leaf(0x0200, f32(5.0, 10.0) + u32(3, 1, 2, 3, 4, 0, 0, 0)),    # 201/305
             leaf(0x0300)),
        cont(0x20B0,                                                        # Time configuration
             leaf(0x0010, u32(frame_rate)),                                 # Frame rate: 30 on 286/305
             leaf(0x0020, u32(0)),
             leaf(0x0030, u32(1)),                                          # 207/305
             leaf(0x0040, u32(1)),                                          # 304/305
             leaf(0x0050, u32(0)),                                          # Animation start (ticks), 292/305
             leaf(0x0060, u32(animation_end_frame * ticks_per_frame)),      # Animation end (ticks): 16000 most often
             leaf(0x0070, u32(0)),
             cont(0x0100, leaf(0x0090, u32(0))),
             leaf(0x0110, u32(0)),
             leaf(0x0120, u32(1))),
        cont(0x20D0,                                                        # Render output range / size (?)
             leaf(0x0005, u32(1, 1, 0, 0, 0)),                              # 302/305
             leaf(0x0001, u32(0)),
             leaf(0x0002, u32(4640)),                                       # 298/305
             leaf(0x0003, u32(0)),
             leaf(0x0004, u32(4640)),                                       # 298/305
             leaf(0x0010, u32(640)),
             leaf(0x0020, u32(480)),
             leaf(0x0030, f32(1.0)),
             leaf(0x0031, u32(0))),
        cont(0x2160,                                                        # Gamma (off, 2.2, 2.2: 246/305)
             leaf(0x0100, u32(0) + f32(2.2, 2.2)),
             leaf(0x0200, u32(1, 1)),
             leaf(0x0300, u32(0, 0, 1, 0, 15, 0, 0)),
             leaf(0x0400, u32(16)),
             leaf(0x0500, u32(20))),
        cont(0x2007, leaf(0x0010, u32(0, 0x11E))),                          # 254/305
        cont(0x2008,                                                        # 305/305 (construction plane ?)
             leaf(0x0010, f32(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0) + u32(7)),
             leaf(0x0020, f32(20.0)),
             leaf(0x0030, u32(1))),
    ])


def video_post_queue_stream() -> bytes:
    """An empty Video Post queue: 0x0050 = 1, 0x0060 > (0x0010: 24 bytes, 0x0020) (294/305)."""
    return leaf(0x0050, u32(1)) + cont(0x0060, leaf(0x0010, u32(7, 1, 0, 0, 0x1220, 0)), leaf(0x0020))


def save_config_stream(dll_header, release) -> bytes:
    """``SaveConfigData`` (overview.md §1): version, release, LCID 0x0409, code page 65001, 0 (all 305)."""
    return b"".join([
        leaf(0x2170, u32(dll_header)),
        leaf(0x2173, u32(release)),
        leaf(0x2172, struct.pack("<H", 0x0409)),
        leaf(0x2174, u32(65001)),
        leaf(0x2171, struct.pack("<H", 0)),
    ])


def _string(value):
    raw = value.encode("utf-16-le")
    return u32(len(value)) + raw + b"\0\0"


def asset_metadata_stream(assets) -> bytes:
    """``FileAssetMetaData3``: per asset the 16-byte ID, the type, the path and the resolved path (overview §7)."""
    parts = []
    for guid, path in assets:
        parts.append(bytes(guid) + _string("Bitmap") + _string(path) + _string(path))
    return b"".join(parts)


# -----------------------------------------------------------------------------
# Property sets ([MS-OLEPS])

FMTID_SUMMARY = uuid.UUID("f29f85e0-4ff9-1068-ab91-08002b27b3d9")
FMTID_DOC_SUMMARY = uuid.UUID("d5cdd502-2e9c-101b-9397-08002b2cf9ae")
VT_I2, VT_I4, VT_LPSTR, VT_UI4, VT_VARIANT, VT_VECTOR = 0x02, 0x03, 0x1E, 0x13, 0x0C, 0x1000
CODEPAGE_UTF8 = 65001
# Corpus: the property sets of the 2015 files carry the OS version word 0x00020206 and locale 0x0409.
_OS_VERSION = 0x00020206
_LOCALE = 0x0409


def _pad4(data):
    return data + b"\0" * (-len(data) % 4)


def _lpstr(value):
    raw = value.encode("utf-8") + b"\0"
    return _pad4(u32(len(raw)) + raw)


def _typed(vt, payload):
    return struct.pack("<HH", vt, 0) + payload


def _property_set(fmtid, properties):
    """A property-set stream with one section; ``properties`` = [(property id, typed value bytes)]."""
    count = len(properties)
    offset = 8 + 8 * count
    table = []
    values = []
    for pid, value in properties:
        table.append(struct.pack("<II", pid, offset))
        values.append(value)
        offset += len(value)
    section = u32(offset, count) + b"".join(table) + b"".join(values)
    header = struct.pack("<HHI16sI", 0xFFFE, 0, _OS_VERSION, b"\0" * 16, 1) + fmtid.bytes_le + u32(48)
    return header + section


def _common():
    return [(1, _typed(VT_I2, struct.pack("<hxx", CODEPAGE_UTF8 - 65536))),
            (0x80000000, _typed(VT_UI4, u32(_LOCALE)))]


def summary_information_stream(comments="") -> bytes:
    """``\\x05SummaryInformation``: code page, locale, comments (no thumbnail)."""
    props = _common()
    if comments:
        props.append((6, _typed(VT_LPSTR, _lpstr(comments))))
    return _property_set(FMTID_SUMMARY, props)


def document_summary_information_stream(groups) -> bytes:
    """``\\x05DocumentSummaryInformation``: the heading pairs and document parts Max shows in its file properties
    (``groups`` = [(heading, [strings])], e.g. ("General", ["3ds Max Version: 16.90", ...]))."""
    pairs = []
    parts = []
    for heading, strings in groups:
        pairs.append(_typed(VT_LPSTR, _lpstr(heading)))
        pairs.append(_typed(VT_I4, struct.pack("<i", len(strings))))
        parts.extend(strings)
    heading_pairs = _typed(VT_VECTOR | VT_VARIANT, u32(len(pairs)) + b"".join(pairs))
    doc_parts = _typed(VT_VECTOR | VT_LPSTR, u32(len(parts)) + b"".join(_lpstr(s) for s in parts))
    return _property_set(FMTID_DOC_SUMMARY, _common() + [(12, heading_pairs), (13, doc_parts)])
