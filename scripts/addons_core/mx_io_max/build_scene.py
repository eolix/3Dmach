# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Turn data parsed by ``maxfile`` into Blender objects.

Object, material, modifier and primitive conversion live in the ``materials``,
``modifiers`` and ``primitives`` sub-packages (one module per Max class family).
"""

__all__ = (
    "import_file",
)


def import_file(operator, context, filepath):
    """Import one ``.max`` file, reporting problems through ``operator``. Returns an operator result set."""
    from maxfile import container

    try:
        is_cfb = container.is_compound_file(filepath)
    except OSError as ex:
        operator.report({'ERROR'}, "Cannot read {!r}: {:s}".format(filepath, ex.strerror or str(ex)))
        return {'CANCELLED'}

    if not is_cfb:
        operator.report({'ERROR'}, "Not a .max file (no Compound File signature): {!r}".format(filepath))
        return {'CANCELLED'}

    operator.report({'WARNING'}, "Importing .max scenes is not implemented yet: {!r}".format(filepath))
    return {'CANCELLED'}
