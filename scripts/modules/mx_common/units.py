# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Length units used by Max scenes, and conversion to Blender's metres.

A Max scene has a *system unit* (inches by default in US installs, often centimetres or metres) and a
*system unit scale* (1 unit = N system units). One scene unit in metres is ``scale * METRES_PER_UNIT[unit]``.
No Blender dependency.
"""

__all__ = (
    "METRES_PER_UNIT",
    "scene_unit_in_metres",
)

METRES_PER_UNIT = {
    "inches": 0.0254,
    "feet": 0.3048,
    "miles": 1609.344,
    "millimeters": 0.001,
    "centimeters": 0.01,
    "meters": 1.0,
    "kilometers": 1000.0,
}


def scene_unit_in_metres(unit="inches", scale=1.0):
    """Length of one Max scene unit in metres. ``unit`` is a key of :data:`METRES_PER_UNIT`."""
    try:
        factor = METRES_PER_UNIT[unit]
    except KeyError:
        raise ValueError("unknown unit {!r}, expected one of: {:s}".format(unit, ", ".join(METRES_PER_UNIT)))
    if not scale > 0.0:
        raise ValueError("unit scale must be positive, got {!r}".format(scale))
    return scale * factor
