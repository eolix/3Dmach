# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Blender side of the .max importer: the import operator, its menu entry and the drag-and-drop handler.

Parsing lives in the Blender-independent ``maxfile`` library (``pylibs/maxfile``);
``build_scene`` turns its output into Blender data.
"""

bl_info = {
    "name": "Import .max Scenes",
    "author": "3Dmach Authors",
    "version": (0, 0, 1),
    "blender": (5, 2, 0),
    "location": "File > Import > .max Scene",
    "description": "Import scenes from .max files (Max-compatible importer)",
    "warning": "Early development: geometry decoding still in progress",
    "category": "Import-Export",
}

if "bpy" in locals():
    import importlib
    if "build_scene" in locals():
        importlib.reload(build_scene)
    if "file_ops" in locals():
        importlib.reload(file_ops)

import os

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    StringProperty,
)
from bpy_extras.io_utils import (
    ImportHelper,
    poll_file_object_drop,
)

from . import build_scene
from . import file_ops


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

    units: EnumProperty(
        name="Scene Units",
        description="Units the scene was built in",
        items=build_scene.UNIT_CHOICES,
        default='AUTO',
    )
    global_scale: FloatProperty(
        name="Scale",
        description="Extra scale factor applied on import",
        min=1e-6, max=1e6, soft_min=0.001, soft_max=1000.0,
        default=1.0,
    )
    use_collection: BoolProperty(
        name="New Collection",
        description="Put the imported scene in a new collection named after the file",
        default=True,
    )
    keep_modifier_stack: BoolProperty(
        name="Keep Stack Live",
        description="Import modifier stacks as editable modifiers (off: collapse the stack on import)",
        default=True,
    )
    import_materials: BoolProperty(name="Materials", default=True)
    import_lights: BoolProperty(name="Lights", default=True)
    import_cameras: BoolProperty(name="Cameras", default=True)
    texture_search_dir: StringProperty(
        name="Texture Folder",
        description="Extra folder to search (with sub-folders) for textures that aren't where the scene says",
        subtype='DIR_PATH',
        default="",
    )

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, "units")
        layout.prop(self, "global_scale")
        layout.prop(self, "use_collection")
        layout.prop(self, "keep_modifier_stack")
        col = layout.column(heading="Include")
        col.prop(self, "import_materials")
        col.prop(self, "import_lights")
        col.prop(self, "import_cameras")
        layout.prop(self, "texture_search_dir")

    def settings(self):
        return build_scene.ImportSettings(
            units=self.units,
            global_scale=self.global_scale,
            use_collection=self.use_collection,
            keep_modifier_stack=self.keep_modifier_stack,
            import_materials=self.import_materials,
            import_lights=self.import_lights,
            import_cameras=self.import_cameras,
            texture_search_dirs=(bpy.path.abspath(self.texture_search_dir),) if self.texture_search_dir else (),
        )

    def execute(self, context):
        if self.files:
            paths = [os.path.join(self.directory, file.name) for file in self.files]
        else:
            paths = [self.filepath]

        ret = {'CANCELLED'}
        settings = self.settings()
        for path in paths:
            if build_scene.import_file(self, context, path, settings) == {'FINISHED'}:
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
    *file_ops.classes,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)
    file_ops.register()


def unregister():
    file_ops.unregister()
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
