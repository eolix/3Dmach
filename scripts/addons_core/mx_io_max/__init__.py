# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Blender side of the .max importer: the import operator, its menu entry and the drag-and-drop handler.

Parsing lives in the Blender-independent ``maxfile`` library (``pylibs/maxfile``);
``build_scene`` turns its output into Blender data.
"""

bl_info = {
    "name": "Import .max Scenes",
    "author": "PROJECT_NAME Authors",
    "version": (0, 0, 1),
    "blender": (5, 2, 0),
    "location": "File > Import > .max Scene",
    "description": "Import scenes from .max files (Max-compatible importer)",
    "warning": "Early development: scenes are not imported yet",
    "category": "Import-Export",
}

if "bpy" in locals():
    import importlib
    if "build_scene" in locals():
        importlib.reload(build_scene)

import os

import bpy
from bpy.props import (
    CollectionProperty,
    StringProperty,
)
from bpy_extras.io_utils import (
    ImportHelper,
    poll_file_object_drop,
)

from . import build_scene


class IMPORT_SCENE_OT_mx_max(bpy.types.Operator, ImportHelper):
    """Import a .max scene"""
    bl_idname = "import_scene.mx_max"
    bl_label = "Import .max"
    bl_options = {'UNDO'}

    directory: StringProperty(
        subtype='DIR_PATH',
        options={'HIDDEN', 'SKIP_PRESET'},
    )
    files: CollectionProperty(
        name="File Path",
        type=bpy.types.OperatorFileListElement,
        options={'HIDDEN', 'SKIP_PRESET'},
    )

    filename_ext = ".max"
    filter_glob: StringProperty(default="*.max", options={'HIDDEN'})

    def execute(self, context):
        if self.files:
            paths = [os.path.join(self.directory, file.name) for file in self.files]
        else:
            paths = [self.filepath]

        ret = {'CANCELLED'}
        for path in paths:
            if build_scene.import_file(self, context, path) == {'FINISHED'}:
                ret = {'FINISHED'}
        return ret

    def invoke(self, context, event):
        return self.invoke_popup(context)


class IO_FH_mx_max(bpy.types.FileHandler):
    bl_idname = "IO_FH_mx_max"
    bl_label = ".max Scene"
    bl_import_operator = "import_scene.mx_max"
    bl_file_extensions = ".max"

    @classmethod
    def poll_drop(cls, context):
        return poll_file_object_drop(context)


def menu_func_import(self, _context):
    self.layout.operator(IMPORT_SCENE_OT_mx_max.bl_idname, text=".max Scene (.max)")


classes = (
    IMPORT_SCENE_OT_mx_max,
    IO_FH_mx_max,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
