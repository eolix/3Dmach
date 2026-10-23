# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Max-style File > Open / Save / Save As, with .max as the default format.

- **Open** (Ctrl+O) opens a ``.max`` file into a fresh scene, like Max's Open (File > Import > .max still merges
  into the current scene, like Max's Merge). ``.blend`` files open as before.
- **Save** (Ctrl+S) / **Save As** (Ctrl+Shift+S) write ``.max`` through the ``.max`` writer
  (operator ``export_scene.mx_max``) when it is available. The writer is experimental, so every ``.max`` save also
  writes the full scene next to it as ``<name>.max.3dmach.blend``; Open uses that backup when it is newer than the
  ``.max`` file, so nothing is lost when reopening in 3Dmach. Without the writer, Save writes the native scene.

Blender's own ``.blend`` open/save stay available under File > Import / Export ("Blender Scene").
"""

__all__ = (
    "classes",
)

import os

import bpy
from bpy.props import BoolProperty, StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ExportHelper, ImportHelper

# Scene property holding the .max file the scene was opened from / last saved to.
MAX_PATH_KEY = "mx_max_filepath"
BACKUP_SUFFIX = ".3dmach.blend"


def backup_path(max_path):
    """The native scene saved alongside a .max file."""
    return max_path + BACKUP_SUFFIX


def writer_available():
    return hasattr(bpy.types, "EXPORT_SCENE_OT_mx_max")


def current_max_path(context):
    scene = context.scene
    path = scene.get(MAX_PATH_KEY, "") if scene else ""
    return path if isinstance(path, str) else ""


def _is_max(path):
    return path.lower().endswith(".max")


def _open_max_deferred(filepath):
    """After ``read_homefile`` the operator's context is gone: import from a timer once the new file is up."""
    def run():
        window = bpy.context.window_manager.windows[0] if bpy.context.window_manager.windows else None
        override = {"window": window} if window else {}
        with bpy.context.temp_override(**override):
            try:
                bpy.ops.import_scene.mx_max(filepath=filepath, use_collection=False)
            except RuntimeError as ex:
                print("3Dmach: could not open {!r}: {}".format(filepath, ex))
                return None
            bpy.context.scene[MAX_PATH_KEY] = filepath
        return None
    bpy.app.timers.register(run, first_interval=0.01)


def open_file(filepath):
    """Open ``filepath`` (.max or .blend) replacing the current scene. Returns an operator result set."""
    if not _is_max(filepath):
        return bpy.ops.wm.open_mainfile(filepath=filepath)
    backup = backup_path(filepath)
    if os.path.isfile(backup) and os.path.getmtime(backup) >= os.path.getmtime(filepath):
        # Saved by 3Dmach: its full scene is next to it, reopen that instead (lossless).
        return bpy.ops.wm.open_mainfile(filepath=backup)
    result = bpy.ops.wm.read_homefile(use_empty=True)
    if 'FINISHED' in result:
        _open_max_deferred(filepath)
    return result


class WM_OT_mx_open(Operator):
    """Open a .max scene (or a .blend file), replacing the current scene"""
    bl_idname = "wm.mx_open"
    bl_label = "Open"

    def invoke(self, context, event):
        if bpy.data.is_dirty:
            return context.window_manager.invoke_confirm(
                self, event, title="Open", message="The current scene has unsaved changes that will be lost.",
                confirm_text="Open Anyway")
        return self.execute(context)

    def execute(self, _context):
        return bpy.ops.wm.mx_open_browse('INVOKE_DEFAULT')


class WM_OT_mx_open_browse(Operator, ImportHelper):
    """Open a .max scene (or a .blend file), replacing the current scene"""
    bl_idname = "wm.mx_open_browse"
    bl_label = "Open"
    bl_options = {'INTERNAL'}

    filename_ext = ".max"
    filter_glob: StringProperty(default="*.max;*.blend", options={'HIDDEN'})

    def execute(self, context):
        if not os.path.isfile(self.filepath):
            self.report({'ERROR'}, "File not found: {:s}".format(self.filepath))
            return {'CANCELLED'}
        return open_file(self.filepath)


def _save_max(operator, context, filepath):
    """Write ``filepath`` with the .max writer plus the native backup next to it."""
    result = bpy.ops.export_scene.mx_max(filepath=filepath)
    if 'FINISHED' not in result:
        operator.report({'ERROR'}, "Could not write {:s}".format(os.path.basename(filepath)))
        return {'CANCELLED'}
    context.scene[MAX_PATH_KEY] = filepath
    # The backup is the real save: it keeps everything the .max writer can't express yet.
    bpy.ops.wm.save_as_mainfile(filepath=backup_path(filepath), check_existing=False)
    operator.report({'INFO'}, "Saved {:s}".format(os.path.basename(filepath)))
    return {'FINISHED'}


class WM_OT_mx_save(Operator):
    """Save the scene: to its .max file when the .max writer is available, otherwise as a 3Dmach scene"""
    bl_idname = "wm.mx_save"
    bl_label = "Save"

    def execute(self, context):
        max_path = current_max_path(context)
        if writer_available() and max_path:
            return _save_max(self, context, max_path)
        if bpy.data.filepath and not bpy.data.filepath.endswith(BACKUP_SUFFIX):
            return bpy.ops.wm.save_mainfile()
        return bpy.ops.wm.mx_save_as('INVOKE_DEFAULT')


class WM_OT_mx_save_as(Operator, ExportHelper):
    """Save the scene under a new name: .max (with the .max writer) or a 3Dmach / Blender scene (.blend)"""
    bl_idname = "wm.mx_save_as"
    bl_label = "Save As"

    filename_ext = ".max"
    filter_glob: StringProperty(default="*.max;*.blend", options={'HIDDEN'})
    check_extension: BoolProperty(default=False, options={'HIDDEN'})

    def invoke(self, context, event):
        if not writer_available():
            self.filename_ext = ".blend"
        max_path = current_max_path(context)
        if max_path:
            stem = os.path.splitext(max_path)[0]
            self.filepath = stem + self.filename_ext
        elif bpy.data.filepath:
            self.filepath = os.path.splitext(bpy.data.filepath)[0] + self.filename_ext
        else:
            self.filepath = "untitled" + self.filename_ext
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        path = self.filepath
        if not os.path.splitext(path)[1]:
            path += ".max" if writer_available() else ".blend"
        if _is_max(path):
            if not writer_available():
                self.report({'ERROR'}, "Saving .max files isn't available yet: save as .blend")
                return {'CANCELLED'}
            return _save_max(self, context, path)
        if MAX_PATH_KEY in context.scene:
            del context.scene[MAX_PATH_KEY]     # Now a native scene: Save writes this .blend.
        return bpy.ops.wm.save_as_mainfile(filepath=path)


def menu_func_import_blend(self, _context):
    self.layout.operator("wm.open_mainfile", text="Blender Scene (.blend)")
    self.layout.operator("wm.append", text="Merge from Blender Scene (.blend)")


def menu_func_export_blend(self, _context):
    self.layout.operator("wm.save_as_mainfile", text="Blender Scene (.blend)").copy = True


classes = (
    WM_OT_mx_open,
    WM_OT_mx_open_browse,
    WM_OT_mx_save,
    WM_OT_mx_save_as,
)


def register():
    bpy.types.TOPBAR_MT_file_import.prepend(menu_func_import_blend)
    bpy.types.TOPBAR_MT_file_export.prepend(menu_func_export_blend)


def unregister():
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export_blend)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import_blend)
