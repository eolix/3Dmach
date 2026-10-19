# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Per-node state from the Max node: wire colour, hidden, frozen, targets and helper objects.

The hidden / frozen node flags are partly guessed by ``maxfile`` (``Node.is_hidden`` / ``Node.is_frozen``, see
``docs/format/overview.md`` §4), so the importer counts what it applied in the report.

Frozen objects follow the ``mx_ui`` freeze semantics (unselectable, drawn gray, the original colour kept in
``mx_frozen_color``) whether or not that add-on is enabled, so they can be unfrozen later with its Unfreeze.
"""

__all__ = (
    "HELPER_CLASSES",
    "apply_frozen",
    "apply_hidden",
    "srgb_to_linear",
    "wire_color",
)

# Max helper classes imported as empties (display type, size in scene units): they have nothing to convert, so
# they are counted as helpers instead of unsupported objects.
HELPER_CLASSES = {
    "Target": ('CUBE', 2.0),
    "Dummy": ('CUBE', 5.0),
    "Point": ('PLAIN_AXES', 5.0),
    "Grid": ('PLAIN_AXES', 5.0),
}

# Same keys and colour as ``mx_ui.freeze`` (kept in sync by tests/blender/test_io_max_import.py).
FROZEN_KEY = "mx_frozen"
COLOR_KEY = "mx_frozen_color"
FROZEN_GRAY = (0.45, 0.45, 0.45, 1.0)


def srgb_to_linear(c):
    """One sRGB-encoded channel (0..1) to linear."""
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def wire_color(rgb8):
    """Max wire colour (0-255 per channel, as displayed) to a linear RGBA ``Object.color``."""
    if rgb8 is None or len(rgb8) < 3:
        return None
    return (*(srgb_to_linear(min(max(v, 0), 255) / 255.0) for v in rgb8[:3]), 1.0)


def apply_hidden(obj):
    """Hide ``obj`` in the viewports and renders, as Max does for hidden nodes."""
    obj.hide_set(True)
    obj.hide_render = True


def apply_frozen(obj):
    """Freeze ``obj`` like ``mx_ui``'s Freeze Selection (gray, unselectable)."""
    try:
        from mx_ui import freeze
    except ImportError:
        freeze = None
    if freeze is not None and hasattr(freeze, "freeze_objects"):
        freeze.freeze_objects([obj])
        return
    obj[FROZEN_KEY] = True
    obj[COLOR_KEY] = list(obj.color)
    obj.color = FROZEN_GRAY
    obj.hide_select = True
