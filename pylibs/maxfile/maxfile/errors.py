# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Exceptions raised by :mod:`maxfile`.

Every error caused by the *contents* of a file is a :class:`MaxFileError`, so callers (the importer, ``maxdump``)
can catch one type and show its message. ``OSError`` from opening or reading the file is passed through unchanged.
"""

__all__ = (
    "MaxFileError",
    "ContainerError",
    "NotCompoundFileError",
    "UnsupportedFormatError",
    "StreamNotFoundError",
    "ChunkError",
    "DecodeError",
)


class MaxFileError(Exception):
    """Base class: the file is corrupt, unsupported, or doesn't contain what was asked for."""


class ContainerError(MaxFileError):
    """The Compound File container is corrupt (bad header, broken sector chain, broken directory, ...)."""


class NotCompoundFileError(ContainerError):
    """The file doesn't start with the Compound File signature, so it is not a ``.max`` scene."""


class UnsupportedFormatError(ContainerError):
    """The container is well-formed but uses a variant this reader doesn't handle (e.g. an unknown version)."""


class StreamNotFoundError(MaxFileError, LookupError):
    """No stream with the requested name exists in the container."""


class ChunkError(MaxFileError):
    """A chunk header is invalid (size too small, or larger than the space left in its parent)."""


class DecodeError(MaxFileError):
    """An object decoder found data it can't interpret (wrong size, missing chunk, ...)."""
