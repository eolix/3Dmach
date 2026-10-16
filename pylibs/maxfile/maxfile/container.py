# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Compound File Binary (OLE2) container access.

`.max` files are stored in the Compound File Binary format, which Microsoft documents
publicly as [MS-CFB]. This module will read that container and expose its streams
(Phase 2b). For now it only recognises the file signature.
"""

__all__ = (
    "CFB_SIGNATURE",
    "has_cfb_signature",
    "is_compound_file",
)

import os

# First 8 bytes of every Compound File ([MS-CFB] section 2.2, "Header Signature").
CFB_SIGNATURE = b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1"


def has_cfb_signature(data: bytes) -> bool:
    """Return True when ``data`` starts with the Compound File signature."""
    return data[:len(CFB_SIGNATURE)] == CFB_SIGNATURE


def is_compound_file(path: str | os.PathLike) -> bool:
    """
    Return True when the file at ``path`` starts with the Compound File signature.

    This is a cheap sniff, not a validation: a True result does not mean the file is a
    readable ``.max`` scene. Raises ``OSError`` when the file cannot be read.
    """
    with open(path, "rb") as fh:
        return has_cfb_signature(fh.read(len(CFB_SIGNATURE)))
