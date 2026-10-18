# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Class directory, DLL directory and registry tests.

The directory layouts are the *documented, unverified* assumptions of ``docs/format/overview.md`` §2.3-2.4,
built synthetically by ``synth_max``.
"""

import pytest

import maxfile
from maxfile import registry
from maxfile.chunks import ChunkStream
from maxfile.classes import ClassID, parse_class_directory, parse_dll_directory
from synth_max import NULL, SceneBuilder, cont, leaf, text, u32


# -----------------------------------------------------------------------------
# ClassID

def test_class_id_forms():
    # The two forms of the Editable Poly ID in overview.md §2.3 / §6.1: the first word is the low half.
    cid = ClassID.from_u64(0x192F60981BF8338D)
    assert (cid.a, cid.b) == (0x1BF8338D, 0x192F6098)
    assert str(cid) == "0x1BF8338D, 0x192F6098"
    assert cid.u64_str() == "0x192F60981BF8338D"
    assert ClassID(0x2005) == ClassID(0x2005, 0) == ClassID.from_u64(0x2005)
    assert hash(ClassID(1, 2)) == hash(ClassID(1, 2))


def test_as_class_id():
    assert registry.as_class_id((1, 2)) == ClassID(1, 2)
    assert registry.as_class_id(0x0000000200000001) == ClassID(1, 2)
    assert registry.as_class_id(ClassID(3, 4)) == ClassID(3, 4)
    with pytest.raises(TypeError):
        registry.as_class_id("0x1")
    with pytest.raises(TypeError):
        registry.as_class_id(-1)


# -----------------------------------------------------------------------------
# Directories

def _class_stream(*entries):
    return ChunkStream(b"".join(entries), "ClassDirectory3")


def test_class_directory():
    b = SceneBuilder()
    dll = b.dll((0x2037, "Description"), (0x2039, "thing.dlo"))
    b.cls("Node", (1, 0), 1)
    b.cls("Thing", (0x11112222, 0x33334444), 0x10, dll)
    streams = b.streams()
    dlls = parse_dll_directory(ChunkStream(streams["DllDirectory"], "DllDirectory"))
    classes = parse_class_directory(ChunkStream(streams["ClassDirectory3"], "ClassDirectory3"), dlls)
    assert classes.warnings == [] and dlls.warnings == []
    assert len(classes) == 2
    node, thing = classes.entries
    assert node.index == 0 and node.name == "Node" and node.class_id == ClassID(1, 0)
    assert node.superclass_id == 1 and node.dll_index == NULL and node.dll is None
    assert thing.class_id == ClassID(0x11112222, 0x33334444) and thing.dll is dlls[0]
    assert dlls[0].strings == {0x2037: "Description", 0x2039: "thing.dlo"}
    assert classes.get(5) is None and classes.get(-1) is None


def test_class_directory_bad_entries():
    stream = _class_stream(
        leaf(0x2040, b"not a container"),
        cont(0x2040, leaf(0x2042, text("NoHeader"))),
        cont(0x2040, leaf(0x2060, u32(0, 1)), leaf(0x2042, text("ShortHeader"))),
        cont(0x2040, leaf(0x2060, u32(NULL, 5, 0, 7))),
    )
    classes = parse_class_directory(stream)
    leaf_entry, no_header, short, ok = classes.entries
    assert "leaf chunk" in leaf_entry.error
    assert no_header.name == "NoHeader" and "no 0x2060" in no_header.error
    assert short.class_id is None and "expected 16" in short.error
    assert ok.error is None and ok.class_id == ClassID(5) and ok.name is None
    assert ok.label() == "<0x00000005, 0x00000000>"
    assert len(classes.warnings) == 3


def test_missing_directories():
    assert parse_class_directory(None).entries == []
    assert parse_dll_directory(None).entries == []


def test_class_directory_fallback_name():
    # Unverified (overview.md §1): older files presumably name the stream "ClassDirectory".
    b = SceneBuilder()
    b.cls("Node", (1, 0), 1)
    streams = b.streams()
    streams["ClassDirectory"] = streams.pop("ClassDirectory3")
    from cfb_writer import build_cfb
    with maxfile.open(build_cfb(streams)[0]) as mf:
        assert mf.class_directory.stream_name == "ClassDirectory"
        assert mf.class_directory[0].name == "Node"


# -----------------------------------------------------------------------------
# Registry

def test_seeded_known_classes():
    poly = registry.known_class(0x192F60981BF8338D)
    assert poly.name == "Editable Poly" and poly.category == "geometry" and not poly.verified
    assert registry.known_class(ClassID(0x1BF8338D, 0x192F6098)) is poly
    assert registry.known_class((0x12345, 0x6789)) is None
    assert registry.known_class(None) is None
    # The node entry is registered for superclass 1 only.
    assert registry.known_class(0x1, 0x1).name == "Node"
    assert registry.known_class(0x1, 0x2) is None
    assert all(not k.verified for k in registry.known_classes())


def test_superclass_preference():
    cid = ClassID(0x7E570001, 0x7E570002)
    generic = registry.register_class(cid, "Generic test class", "test")
    specific = registry.register_class(cid, "Specific test class", "test", superclass_id=0x99)
    try:
        assert registry.known_class(cid) is generic
        assert registry.known_class(cid, 0x99) is specific
        assert registry.known_class(cid, 0x98) is generic
    finally:
        del registry._KNOWN[(cid, None)]
        del registry._KNOWN[(cid, 0x99)]


def test_decoder_registration():
    cid = ClassID(0x7E570003, 0x7E570004)

    @registry.decoder(cid, kind="test.thing", name="Test Thing")
    def decode_thing(obj, ctx):
        """Decode a test thing."""
        return 42

    try:
        info = registry.find_decoder(cid)
        assert info.function is decode_thing and info.kind == "test.thing" and info.module == __name__
        assert info.description == "Decode a test thing."
        assert info in registry.registered_decoders()
        with pytest.raises(ValueError, match="already has a decoder"):
            registry.decoder(cid, kind="test.other")(lambda obj, ctx: None)
    finally:
        del registry._DECODERS[(cid, None)]
    with pytest.raises(TypeError):
        registry.decoder(kind="x")


def test_registered_decoders_listing():
    decoders = registry.registered_decoders()
    kinds = {d.kind for d in decoders}
    assert {"controller.transform", "controller.position", "controller.rotation", "controller.scale",
            "controller.float"} <= kinds
    assert all(d.module.startswith("maxfile.objects.") for d in decoders)
    assert not any(d.verified for d in decoders)
    # Every decoder's class IDs are known classes, so the feature matrix can name them.
    for d in decoders:
        for cid in d.class_ids:
            assert registry.known_class(cid) is not None, cid
