# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Shape decoding tests (:mod:`maxfile.objects.shapes`).

The synthetic fixtures follow the layouts worked out on the local corpus (see the module docstring); the corpus
tests at the end check those layouts against real files and skip without the corpus.
"""

import math
import struct

import pytest

import maxfile
from maxfile.objects import shapes
from synth_max import SceneBuilder, cont, f32, leaf, refs_ordered, refs_sparse, text, u32

import corpus_files

SHAPE = 0x40
ID = {
    "line": (0x1040, 0),
    "spline_shape": (0xA, 0),
    "text": (0x1993, 0),
    "rectangle": (0x1065, 0),
    "circle": (0x1999, 0),
    "ngon": (0x1050, 0),
    "star": (0x1995, 0),
    "donut": (0x1060, 0),
}
RENDER_DEFAULTS = [1.0, 12, 0.0, 1.0, 12, 0.0, 0, 0, 0, 0, 1, 0, 2.0, 6.0, 0.0, 0, 2.0, 6.0, 0.0, 0, 0,
                   math.radians(40.0), 0]


class Builder(SceneBuilder):
    def __init__(self):
        super().__init__()
        self.c = {key: self.cls(key, cid, SHAPE) for key, cid in ID.items()}
        self.pb_class = self.cls("ParamBlock", (0x8, 0), 0x8)

    def old_pb(self, *values):
        """An old ParamBlock: floats as 0x0100 chunks, ints as 0x0101."""
        params = []
        for index, value in enumerate(values):
            chunk = leaf(0x0100, f32(value)) if isinstance(value, float) else leaf(0x0101, struct.pack("<i", value))
            params.append(cont(0x0002, leaf(0x0003, u32(index)), chunk))
        return self.obj(self.pb_class, leaf(0x0001, u32(len(values))), *params)

    def rendering(self, **changes):
        values = list(RENDER_DEFAULTS)
        names = {v: k for k, v in shapes.RENDERING_PARAMS.items()}
        for name, value in changes.items():
            values[names[name]] = value
        return self.old_pb(*values)

    def parametric(self, key, *values, steps=6, optimize=1, adaptive=0):
        render = self.rendering()
        params = self.old_pb(*values)
        interp = self.old_pb(steps, optimize, adaptive)
        return self.obj(self.c[key], refs_ordered(render, params, interp))


def knot(position, in_handle=None, out_handle=None, knot_type=1, segment_type=0, aux=0, u=1.0):
    in_handle = in_handle or position
    out_handle = out_handle or position
    return struct.pack("<IIf9fI", knot_type, segment_type, u, *position, *in_handle, *out_handle, aux)


def spline(knots, closed=False, count=None):
    return cont(0x1010,
                leaf(0x2900, u32(len(knots) if count is None else count)),
                leaf(0x2904, u32(0)),
                leaf(0x290A, b"".join(knots)),
                leaf(0x290D, u32(int(closed))))


def bezier_shape(*splines):
    """A Bezier shape container: splines plus a selection container the reader must skip."""
    return cont(0x1010, *splines, cont(0x1020, leaf(0x1000, u32(1))), leaf(0x1050, u32(6)))


def shape_body(shape, steps=6, optimize=1, adaptive=0):
    return [leaf(0x2000, u32(1)), shape, leaf(0x1060, u32(steps)), leaf(0x10C0, u32(optimize)),
            leaf(0x10D0, u32(adaptive))]


def _open(b):
    return maxfile.open(b.build())


def _close(a, b, tol=1e-5):
    return len(a) == len(b) and all(math.isclose(x, y, abs_tol=tol) for x, y in zip(a, b))


# -----------------------------------------------------------------------------
# Stored splines.

def test_line_two_knots():
    b = Builder()
    render = b.rendering(renderable=1, thickness=2.5, sides=8)
    line = b.obj(b.c["line"], refs_ordered(render, 0xFFFFFFFF), cont(0x2000, *shape_body(bezier_shape(spline([
        knot((0, 0, 0), out_handle=(1, 0, 0)),
        knot((3, 0, 0), in_handle=(2, 0, 0), knot_type=2),
    ])), steps=12, optimize=0)))
    with _open(b) as mf:
        d = mf.scene.decode(mf.objects[line])
    assert isinstance(d, shapes.ShapeData)
    assert (d.kind, d.source, d.steps, d.optimize, d.adaptive) == ("LINE", "stored", 12, False, False)
    assert len(d.splines) == 1 and not d.splines[0].closed
    k0, k1 = d.splines[0].knots
    assert k0.position == (0, 0, 0) and k0.out_handle == (1, 0, 0) and k0.knot_type == "corner"
    assert k1.in_handle == (2, 0, 0) and k1.knot_type == "bezier" and k1.segment_type == "curve"
    assert d.rendering.renderable and d.rendering.thickness == 2.5 and d.rendering.sides == 8
    assert math.isclose(d.rendering.auto_smooth_threshold, math.radians(40.0), rel_tol=1e-6)
    assert not d.animated


def test_spline_shape_splines_types_and_animation():
    b = Builder()
    render = b.rendering()
    square = [knot((x, y, 0), knot_type=t, segment_type=1, aux=0x20000)
              for (x, y), t in zip(((1, 1), (-1, 1), (-1, -1), (1, -1)), (0, 1, 2, 3))]
    obj = b.obj(b.c["spline_shape"], refs_sparse({0: render, 1: render, 4: render}),
                *shape_body(bezier_shape(spline(square, closed=True), spline([knot((5, 5, 5))]))))
    with _open(b) as mf:
        d = mf.scene.decode(mf.objects[obj])
    assert d.kind == "SPLINE_SHAPE" and len(d.splines) == 2
    sq, single = d.splines
    assert sq.closed and [k.knot_type for k in sq.knots] == ["smooth", "corner", "bezier", "bezier_corner"]
    assert all(k.segment_type == "line" and k.material_id == 2 for k in sq.knots)
    assert len(single.knots) == 1 and single.knots[0].position == (5, 5, 5)
    assert d.animated          # Reference slots beyond the vertex controller.


@pytest.mark.parametrize("knots,count,match", [
    ([knot((0, 0, 0))], 2, "2 knots but 52 bytes"),
    ([knot((float("nan"), 0, 0))], None, "non-finite"),
])
def test_bad_spline(knots, count, match):
    b = Builder()
    obj = b.obj(b.c["spline_shape"], *shape_body(bezier_shape(spline(knots, count=count))))
    with _open(b) as mf:
        assert mf.scene.decode(mf.objects[obj]) is None
        assert any(match in w for w in mf.warnings)


def test_line_without_shape():
    b = Builder()
    obj = b.obj(b.c["line"], leaf(0x2000, u32(1)))
    with _open(b) as mf:
        assert mf.scene.decode(mf.objects[obj]) is None
        assert any("no spline data" in w for w in mf.warnings)


# -----------------------------------------------------------------------------
# Parametric shapes.

def _bbox(splines):
    pts = [k.position for s in splines for k in s.knots]
    return tuple(min(p[i] for p in pts) for i in range(3)) + tuple(max(p[i] for p in pts) for i in range(3))


def test_rectangle_plain_and_rounded():
    b = Builder()
    plain = b.parametric("rectangle", 10.0, 4.0, 0.0)
    rounded = b.parametric("rectangle", 10.0, 4.0, 1.0)
    with _open(b) as mf:
        p = mf.scene.decode(mf.objects[plain])
        r = mf.scene.decode(mf.objects[rounded])
    assert p.params == {"length": 10.0, "width": 4.0, "corner_radius": 0.0}
    assert (p.kind, p.source, p.steps, p.optimize, p.adaptive) == ("RECTANGLE", "generated", 6, True, False)
    assert len(p.splines[0].knots) == 4 and p.splines[0].closed
    assert _close(_bbox(p.splines), (-2, -5, 0, 2, 5, 0))     # Width along X, length along Y.
    k0 = p.splines[0].knots[0]
    assert _close(k0.position, (2, 5, 0)) and _close(k0.out_handle, (2 - 4 / 3, 5, 0))
    assert len(r.splines[0].knots) == 8
    assert _close(_bbox(r.splines), (-2, -5, 0, 2, 5, 0))
    k0 = r.splines[0].knots[0]
    assert _close(k0.position, (2, 4, 0)) and _close(k0.out_handle, (2, 4 + shapes.KAPPA, 0))
    assert k0.knot_type == "bezier_corner"


def test_circle_ngon_star_donut():
    b = Builder()
    circle = b.parametric("circle", 3.0)
    ngon = b.parametric("ngon", 2.0, 5, 0, 0.0, 1)
    star = b.parametric("star", 4.0, 2.0, 6, 0.0, 0.0, 0.0)
    donut = b.parametric("donut", 3.0, 1.0)
    with _open(b) as mf:
        c, n, s, d = (mf.scene.decode(mf.objects[i]) for i in (circle, ngon, star, donut))
    knots = c.splines[0].knots
    assert len(knots) == 4 and all(k.knot_type == "bezier" for k in knots)
    assert _close(knots[0].position, (3, 0, 0)) and _close(knots[0].out_handle, (3, 3 * shapes.KAPPA, 0))
    assert _close(knots[1].position, (0, 3, 0))                         # Counter-clockwise.
    assert n.params["sides"] == 5 and len(n.splines[0].knots) == 5
    assert all(math.isclose(math.hypot(*k.position[:2]), 2.0) for k in n.splines[0].knots)
    radii = [math.hypot(*k.position[:2]) for k in s.splines[0].knots]
    assert len(radii) == 12 and _close(radii[0::2], [4.0] * 6) and _close(radii[1::2], [2.0] * 6)
    assert [len(sp.knots) for sp in d.splines] == [4, 4]
    assert _close(_bbox(d.splines[1:]), (-1, -1, 0, 1, 1, 0))


def test_parametric_without_parameters():
    b = Builder()
    obj = b.obj(b.c["circle"], refs_ordered(b.rendering()))
    with _open(b) as mf:
        assert mf.scene.decode(mf.objects[obj]) is None
        assert any("no parameter block in slot 1" in w for w in mf.warnings)


# -----------------------------------------------------------------------------
# Text.

def _utf16(s):
    raw = text(s + "\0")
    return u32(len(raw)) + raw


def _glyph_shape(*splines):
    return cont(0x1020, *splines)


def test_text_layout():
    b = Builder()
    box = spline([knot((0, 0, 0)), knot((500, 0, 0)), knot((500, 700, 0)), knot((0, 700, 0))], closed=True)
    chars = "AA\r\nA"
    entries = u32(len(chars)) + b"".join(u32(ord(c)) + bytes([{13: 3, 10: 5}.get(ord(c), 0)]) for c in chars)
    obj = b.obj(
        b.c["text"],
        refs_ordered(b.rendering(), b.old_pb(10.0, 1.0, 2.0), b.old_pb(6, 1, 0)),
        leaf(0x1005, _utf16("Arial")),
        leaf(0x1015, _utf16(chars)),
        cont(0x1030, leaf(0x1000, u32(ord("A"))), leaf(0x1010, f32(600.0)), _glyph_shape(box)),
        cont(0x1030, leaf(0x1000, u32(13)), leaf(0x1010, f32(600.0)), _glyph_shape(box)),
        cont(0x1030, leaf(0x1000, u32(10)), leaf(0x1010, f32(600.0)), _glyph_shape(box)),
        leaf(0x1035, entries),
    )
    with _open(b) as mf:
        d = mf.scene.decode(mf.objects[obj])
    assert d.kind == "TEXT" and d.source == "glyphs"
    assert d.params == {"size": 10.0, "kerning": 1.0, "leading": 2.0, "text": chars, "font": "Arial"}
    assert len(d.splines) == 3                  # CR and LF draw nothing.
    # Line 1: glyphs at x = 0 and 6 + 1 (advance x size / 1000 + kerning), 5 wide; centred on x = 0.
    # Line 2 starts size + leading = 12 lower.
    assert _close(_bbox(d.splines), (-6, -12, 0, 6, 7, 0))
    assert _close(_bbox(d.splines[:1]), (-6, 0, 0, -1, 7, 0))


# -----------------------------------------------------------------------------
# Corpus.

def _base_by_name(mf, name):
    for node in mf.scene.nodes:
        if node.name == name:
            return mf.scene.resolve_geometry(node)[0], node
    raise AssertionError("no node " + name)


def _mod_context_box(derived):
    """The object-space box of the bottom modifier's ModContext (0x2500 / 0x2511) of a derived object."""
    contexts = [c for c in derived.chunk.children if c.type == 0x2500]
    return contexts[-1].find(0x2511).f32s()


def test_corpus_spline_shape_primer_frame():
    path = corpus_files.corpus_file("Scenes/BoxModeling/PrimerFrame_Box_modeling.max")
    with maxfile.open(path) as mf:
        base, _node = _base_by_name(mf, "PrimerFrame.com")
        d = mf.scene.decode(base)
    assert d.kind == "SPLINE_SHAPE" and len(d.splines) == 43
    assert all(s.closed and s.knots for s in d.splines)
    assert len(d.splines[0].knots) == 14
    for s in d.splines:
        for k in s.knots:
            assert all(math.isfinite(v) for v in k.position + k.in_handle + k.out_handle)
            assert math.dist(k.position, k.in_handle) < 100 and math.dist(k.position, k.out_handle) < 100


def test_corpus_line_and_circle():
    path = corpus_files.corpus_file("Scenes/BoneAdjustment/octopus07.max")
    with maxfile.open(path) as mf:
        line = mf.scene.decode(_base_by_name(mf, "Line01")[0])
        circle = mf.scene.decode(_base_by_name(mf, "Circle01")[0])
    (s,) = line.splines
    assert line.kind == "LINE" and len(s.knots) == 2 and not s.closed and line.steps == 6
    a, b = s.knots
    # A straight two-knot line: handles at 1/3 and 2/3.
    third = tuple(a.position[i] + (b.position[i] - a.position[i]) / 3 for i in range(3))
    assert _close(a.out_handle, third, 1e-3)
    assert circle.kind == "CIRCLE" and len(circle.splines[0].knots) == 4
    radius = circle.params["radius"]
    assert all(math.isclose(math.hypot(*k.position[:2]), radius, rel_tol=1e-6) for k in circle.splines[0].knots)


def test_corpus_rectangles_match_converted_spline():
    """The Rectangle "Shade" (60 x 216, radius 6) and the converted copy "Window Mullion" have the same knots."""
    path = corpus_files.corpus_file("Scenes/Rendering/LightGallery_Max2018_ART.max")
    with maxfile.open(path) as mf:
        rect = mf.scene.decode(_base_by_name(mf, "Shade")[0])
        converted = mf.scene.decode(_base_by_name(mf, "Window Mullion")[0])
        floor_base, floor_node = _base_by_name(mf, "Floor")
        floor = mf.scene.decode(floor_base)
        box = _mod_context_box(floor_node.object)
    assert rect.params == {"length": 60.0, "width": 216.0, "corner_radius": 6.0}
    for got, want in zip(rect.splines[0].knots, converted.splines[0].knots, strict=True):
        for field in ("position", "in_handle", "out_handle"):
            assert _close(getattr(got, field), getattr(want, field), 1e-3)
    assert len(floor.splines[0].knots) == 4
    assert _close(_bbox(floor.splines), box, 1e-3)


def test_corpus_text_matches_mod_context():
    path = corpus_files.corpus_file("Particle Flow Elements Library/scenes/Logo/Logo 01.max")
    with maxfile.open(path) as mf:
        base, node = _base_by_name(mf, "Text01")
        d = mf.scene.decode(base)
        box = _mod_context_box(node.object)
    assert d.params["text"] == "Logo" and d.params["font"] == "Arial" and len(d.splines) == 7
    assert _close(_bbox(d.splines), box, 1e-2)


def test_corpus_sample_decodes():
    """Every shape in a sample of files decodes to splines with knots and finite coordinates."""
    files = corpus_files.all_files() if corpus_files.full_corpus_enabled() else corpus_files.sample(25)
    if not files:
        pytest.skip("no corpus")
    seen = 0
    for path in files:
        with maxfile.open(path) as mf:
            for obj in mf.scene.objects:
                if obj.superclass_id != SHAPE or obj.class_id.a not in {a for a, _ in ID.values()} | {0x93257030}:
                    continue
                d = mf.scene.decode(obj)
                assert isinstance(d, shapes.ShapeData), (path, obj.index)
                seen += 1
                for s in d.splines:
                    assert s.knots
                    for k in s.knots:
                        assert all(math.isfinite(v) for v in k.position + k.in_handle + k.out_handle)
    assert seen or not corpus_files.full_corpus_enabled()
