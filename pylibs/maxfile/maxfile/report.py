# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Turn decoded data (dataclasses, tuples, bytes, ...) into JSON-compatible values or readable text.

Used by ``maxdump --decode``; also handy for import reports and bug reports.
"""

__all__ = (
    "to_plain",
    "format_value",
)

import dataclasses
import math

# Decoded data nests a few levels (material -> sub-material -> map); this only guards against surprises.
_MAX_DEPTH = 100


def to_plain(value, _depth=0):
    """
    A JSON-compatible copy of ``value``: dataclasses become dicts (with a ``"type"`` key), tuples lists, dict keys
    strings, bytes hex strings and non-finite floats strings.
    """
    if _depth > _MAX_DEPTH:
        return "..."
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        out = {"type": type(value).__name__}
        for field in dataclasses.fields(value):
            out[field.name] = to_plain(getattr(value, field.name), _depth + 1)
        return out
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex(" ")
    if isinstance(value, dict):
        return {str(k): to_plain(v, _depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_plain(v, _depth + 1) for v in value]
    return value


def _scalar(value) -> str:
    if isinstance(value, float):
        return "{:.6g}".format(value)
    if isinstance(value, (bytes, bytearray)):
        text = bytes(value[:32]).hex(" ")
        return text + (" ..." if len(value) > 32 else "") + " ({:d} bytes)".format(len(value))
    if isinstance(value, tuple) and all(isinstance(v, (int, float)) for v in value):
        return "(" + ", ".join(_scalar(v) for v in value) + ")"
    if isinstance(value, str):
        return repr(value)
    return str(value)


def _is_scalar(value) -> bool:
    return not (dataclasses.is_dataclass(value) or isinstance(value, (list, dict))) and not (
        isinstance(value, tuple) and not all(isinstance(v, (int, float)) for v in value))


def format_value(value, max_items=8) -> str:
    """Indented text for ``value``; lists longer than ``max_items`` are cut, with the total shown."""
    lines = []

    def emit(label, item, indent, depth):
        pad = "  " * indent
        if depth > _MAX_DEPTH:
            lines.append(pad + label + "...")
            return
        if _is_scalar(item):
            lines.append(pad + label + _scalar(item))
        elif dataclasses.is_dataclass(item):
            lines.append(pad + label + type(item).__name__)
            for field in dataclasses.fields(item):
                emit(field.name + ": ", getattr(item, field.name), indent + 1, depth + 1)
        elif isinstance(item, dict):
            lines.append(pad + label + "{{{:d} item(s)}}".format(len(item)) if item else pad + label + "{}")
            for i, (k, v) in enumerate(item.items()):
                if i >= max_items:
                    lines.append(pad + "  ... ({:d} total)".format(len(item)))
                    break
                emit("{!s}: ".format(k), v, indent + 1, depth + 1)
        else:
            items = list(item)
            if all(_is_scalar(v) for v in items):
                shown = ", ".join(_scalar(v) for v in items[:max_items])
                more = ", ... ({:d} total)".format(len(items)) if len(items) > max_items else ""
                lines.append(pad + label + "[" + shown + more + "]")
                return
            lines.append(pad + label + "[{:d} item(s)]".format(len(items)))
            for i, v in enumerate(items[:max_items]):
                emit("[{:d}] ".format(i), v, indent + 1, depth + 1)
            if len(items) > max_items:
                lines.append(pad + "  ... ({:d} total)".format(len(items)))

    emit("", value, 0, 0)
    return "\n".join(lines)
