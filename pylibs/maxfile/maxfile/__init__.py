# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Reader for .max scene files.

This package must never import Blender modules (`bpy`, `mathutils`, `bmesh`, ...).
It turns a file into plain Python data; `mx_io_max` turns that data into Blender objects.
"""

__version__ = "0.0.1"
