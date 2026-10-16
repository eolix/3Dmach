# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Placeholder buttons for Max features that aren't implemented yet.

The Max-style interface shows every button and menu entry Max has, so the layout is familiar, even where the
feature behind it doesn't exist yet. Those draw through :func:`placeholder`: the button looks normal, its
tooltip says it isn't implemented, and clicking it reports that in the status bar.
"""

__all__ = (
    "placeholder",
)

import bpy
from bpy.props import StringProperty
from bpy.types import Operator


class MXUI_OT_placeholder(Operator):
    bl_idname = "mx_ui.placeholder"
    bl_label = "Not Implemented Yet"
    bl_options = {'INTERNAL'}

    feature: StringProperty(name="Feature", options={'SKIP_SAVE'})

    @classmethod
    def description(cls, _context, properties):
        return "{:s}: not implemented yet".format(properties.feature or "This feature")

    def execute(self, _context):
        self.report({'INFO'}, "{:s} is not implemented yet".format(self.feature or "This feature"))
        return {'FINISHED'}


def placeholder(layout, text, icon='NONE', feature=None, **kwargs):
    """Draw a button for a Max feature that isn't implemented. ``text=""`` gives an icon-only button."""
    props = layout.operator(MXUI_OT_placeholder.bl_idname, text=text, icon=icon, **kwargs)
    props.feature = feature or text
    return props


classes = (
    MXUI_OT_placeholder,
)
