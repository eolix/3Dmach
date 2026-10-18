# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Decoders for individual object classes, one module per class family (controllers, Editable Poly, primitives,
splines, ...).

Each module registers its decoders with :func:`maxfile.registry.decoder`. Modules here are imported on first use
of the registry's decoder lookup (:func:`maxfile.registry.load_decoders`), so adding a module is enough to make
its decoders available; nothing needs to be listed by hand.
"""

__all__ = (
    "import_all",
)

import importlib
import pkgutil


def import_all():
    """Import every decoder module in this package."""
    for info in pkgutil.iter_modules(__path__):
        importlib.import_module(__name__ + "." + info.name)
