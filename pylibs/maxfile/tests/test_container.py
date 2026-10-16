# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

import pytest

from maxfile import container


def test_signature_recognised():
    assert container.has_cfb_signature(container.CFB_SIGNATURE + b"\0" * 504)


@pytest.mark.parametrize("data", [
    b"",
    container.CFB_SIGNATURE[:-1],
    b"PK\x03\x04" + b"\0" * 60,  # ZIP.
    b"BLENDER-v502",
])
def test_signature_rejected(data):
    assert not container.has_cfb_signature(data)


def test_is_compound_file(tmp_path):
    good = tmp_path / "good.bin"
    good.write_bytes(container.CFB_SIGNATURE + b"\0" * 504)
    bad = tmp_path / "bad.bin"
    bad.write_bytes(b"not a compound file")
    empty = tmp_path / "empty.bin"
    empty.write_bytes(b"")

    assert container.is_compound_file(good)
    assert container.is_compound_file(str(good))
    assert not container.is_compound_file(bad)
    assert not container.is_compound_file(empty)


def test_is_compound_file_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        container.is_compound_file(tmp_path / "missing.max")
