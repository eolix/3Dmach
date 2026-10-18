# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Shapes (superclass 0x40): splines as Bezier knots, for the importer to turn into curves.

Every decoder here returns a :class:`ShapeData` with at least one spline whenever the shape has any geometry:
explicit splines are read from the file (Line, SplineShape, the glyph cache of Text), parametric shapes are
generated from their parameters (Rectangle, Circle, NGon, Star, Donut, Angle).

Layouts, worked out on the local corpus (623 files; numbers are corpus objects):

**Spline** (a ``0x1010`` container; 2,173 of them in Line, SplineShape and Text objects, all with exactly these
children, in this order):

- ``0x2900`` u32 knot count.
- ``0x2904`` u32, 0 on every corpus spline (meaning unknown).
- ``0x290A`` one 52-byte record per knot (the size is 52 x count on all 2,173 splines)::

      u32 knot_type, u32 segment_type, f32 ?, f32[3] position, f32[3] in_handle, f32[3] out_handle, u32 aux

  Handles are absolute positions (not offsets), in object space. Evidence for the field order: a two-knot
  straight Line has its out handle 1/3 and its in handle 2/3 of the way along; the corner knots of converted
  rectangles have handles 1/3 of the way to their neighbours (as do 5,431 of 6,116 corner knots).
  ``knot_type``: 0 smooth (the handles of all 424 interior type-0 knots point along next-minus-previous knot:
  automatic tangents), 1 corner, 2 Bezier (handles colinear on 10,492 of 10,514 knots), 3 Bezier corner
  (independent handles); see :data:`KNOT_TYPES`.
  ``segment_type`` of the segment leaving the knot: 1 = line (all 580 such segments are straight), 0 = curve. The
  f32 is 1 / segment count on every one of the 21,515 corpus knots (a derived value, ignored). ``aux``: 0 on most
  knots, otherwise a multiple of 0x10000 up to 0x200000. Guess: the high 16 bits are the segment's 0-based
  material ID (:attr:`ShapeKnot.material_id`).
- ``0x290D`` u32 closed flag (1 on all 1,266 Text glyph splines, which are outlines).

**Bezier shape** (the container holding the splines): ``0x1010`` splines, then selection data (``0x1020`` /
``0x1030`` / ``0x1040``) and small values (``0x1050``-``0x2000``) that are not needed to build the curves.
SplineShape (0xA) holds it as its ``0x1010`` child, Line (0x1040) inside its ``0x2000`` container, Text inside
each glyph entry.

**Interpolation** (steps / optimize / adaptive). Parametric shapes and Text: an old ParamBlock in reference slot 2
with ids 0 steps, 1 optimize, 2 adaptive (values 0-7 / 0-1 / 0-1 in the corpus, defaults 6 / 1 / 0). Line and
SplineShape: chunks next to the Bezier shape, ``0x1060`` steps (0-80 in the corpus; the Bezier shape's own
``0x1050`` repeats it on 414 of 434 objects), ``0x10C0`` optimize, ``0x10D0`` adaptive (always 0 in the corpus).

**Rendering** settings: an old ParamBlock of 23 parameters in reference slot 0 of every shape class
(:data:`RENDERING_PARAMS`).

Parametric shapes keep their parameters in an old ParamBlock in reference slot 1 (Angle: a ParamBlock2 in slot
3) and cache no spline in the file; :func:`generate_rectangle` and friends rebuild them. Their placement was
checked against the object-space bounding box Max stores in the ModContext of a modifier on top of the shape
(derived object chunk ``0x2500`` / ``0x2511``: six f32, min then max): 58 Rectangles, 5 Circles, 10 Texts.
"""

__all__ = (
    "KNOT_TYPES",
    "SEGMENT_TYPES",
    "KAPPA",
    "RENDERING_PARAMS",
    "SHAPE_PARAMS",
    "ShapeKnot",
    "ShapeSpline",
    "ShapeRendering",
    "ShapeData",
    "read_spline",
    "read_bezier_shape",
    "generate_rectangle",
    "generate_circle",
    "generate_ngon",
    "generate_star",
    "generate_donut",
    "generate_angle",
    "layout_text",
)

import dataclasses
import math
import struct
from typing import Any

from ..errors import DecodeError
from ..registry import decoder

Vec3 = tuple[float, float, float]

SUPERCLASS_SHAPE = 0x40

# Chunks (see the module docstring).
CHUNK_SPLINE = 0x1010
CHUNK_KNOT_COUNT = 0x2900
CHUNK_KNOTS = 0x290A
CHUNK_CLOSED = 0x290D
CHUNK_LINE_BODY = 0x2000            # Line: container holding the Bezier shape and interpolation chunks.
CHUNK_SHAPE = 0x1010                # SplineShape / Line body: the Bezier shape.
CHUNK_STEPS = 0x1060
CHUNK_OPTIMIZE = 0x10C0
CHUNK_ADAPTIVE = 0x10D0             # Guess (by its place next to steps / optimize): never non-zero in the corpus.
# Text (all 228 corpus Text objects).
CHUNK_TEXT_FONT = 0x1005            # u32 byte length, UTF-16LE font name with NUL.
CHUNK_TEXT_STRING = 0x1015          # u32 byte length, UTF-16LE text with NUL (\r\n between lines).
CHUNK_TEXT_GLYPH = 0x1030           # One per distinct character, in order of first use.
CHUNK_TEXT_CHARS = 0x1035           # u32 count, then per character u32 code + u8 flags (3 = CR, 5 = LF, else 0).
CHUNK_GLYPH_CODE = 0x1000           # u32 character code.
CHUNK_GLYPH_ADVANCE = 0x1010        # f32 advance width in glyph units.
CHUNK_GLYPH_SHAPE = 0x1020          # Bezier shape in glyph units.

KNOT_RECORD = struct.Struct("<IIf9fI")      # 52 bytes.

KNOT_TYPES = {0: "smooth", 1: "corner", 2: "bezier", 3: "bezier_corner"}
SEGMENT_TYPES = {0: "curve", 1: "line"}

# Handle length of a quarter circle, as a fraction of the radius. Measured on circles converted to editable splines
# in the corpus (21.658056 / 39.250813 and 4.051059 / 7.341718 both give 0.5517862).
KAPPA = 0.5517862

# Glyph units: the shape of each glyph is stored with ascent + descent = 1000 units (Arial's cap height comes out
# at 641-644, its digit advance at 498 = 1139 / 2288 * 1000). Verified: glyph units x size / 1000 reproduce the
# ModContext bounding box of 9 Text objects (5 files, sizes 0.27-100, kerning 0-7.3).
GLYPH_UNITS = 1000.0

# Class IDs (all superclass 0x40, from the corpus class directories).
CLASS_LINE = 0x1040
CLASS_SPLINE_SHAPE = 0xA
CLASS_TEXT = 0x1993
CLASS_RECTANGLE = 0x1065
CLASS_CIRCLE = 0x1999
CLASS_NGON = 0x1050
CLASS_STAR = 0x1995
CLASS_DONUT = 0x1060
CLASS_ANGLE = 0x93257030

# Reference slots of parametric shapes (every corpus object of these classes: slots 0, 1, 2 are old ParamBlocks;
# Angle has slot 0 and 2 and a ParamBlock2 in slot 3).
SLOT_RENDERING = 0
SLOT_PARAMS = 1
SLOT_INTERPOLATION = 2
SLOT_ANGLE_PARAMS = 3

# Shape parameter blocks: class ID -> (kind, {param id: name}). Names after the Max-compatible UI.
SHAPE_PARAMS = {
    # Verified: id 0 is the extent along Y and id 1 along X (58 ModContext boxes); id 2 the corner radius (the
    # rounded rectangle converted in LightGallery_Max2018 has knots at width/2, length/2 - radius etc.).
    CLASS_RECTANGLE: ("RECTANGLE", {0: "length", 1: "width", 2: "corner_radius"}),
    # Verified: ModContext box = +-radius on 4 objects.
    CLASS_CIRCLE: ("CIRCLE", {0: "radius"}),
    # Guess (3 corpus objects, all 6 sides): id 1 sides (6), id 3 corner radius (0.0); ids 2 and 4 are 0 and 1 on
    # all of them, read as "circular" (off) and "inscribed" (on), the UI defaults.
    CLASS_NGON: ("NGON", {0: "radius", 1: "sides", 2: "circular", 3: "corner_radius", 4: "inscribed"}),
    # Guess for ids 3-5 (4 corpus objects): id 2 is the point count (6 and 12); id 3 is 0 or 8, read as the
    # distortion in degrees; ids 4, 5 are always 0.
    CLASS_STAR: ("STAR", {0: "radius1", 1: "radius2", 2: "points", 3: "distortion", 4: "fillet_radius1",
                          5: "fillet_radius2"}),
    CLASS_DONUT: ("DONUT", {0: "radius1", 1: "radius2"}),
    # Verified on 228 objects: slot 1 holds size (default-like 4-31), kerning (0-7.3) and leading.
    CLASS_TEXT: ("TEXT", {0: "size", 1: "kerning", 2: "leading"}),
    # Guess (14 objects in 3 files, all with the same values 6, 4, 0.5, False, 0, 0.5, 0): the Angle extended
    # spline's UI order.
    CLASS_ANGLE: ("ANGLE", {0: "length", 1: "width", 2: "thickness", 3: "sync_corner_fillets", 4: "corner_radius1",
                            5: "corner_radius2", 6: "edge_radii"}),
}

# The "Rendering" old ParamBlock (23 parameters, reference slot 0 of all 840 corpus shapes). Names and evidence:
# id 6 is on for shapes used directly by nodes with a changed thickness (e.g. 0.08-78.6); id 8 is on where the
# viewport values (ids 3-5) differ from the defaults; ids 1 / 4 hold the sides (3-36, default 12); id 21 is 40
# degrees (as radians) on 831 objects and 90 on 2. The others are guesses from the defaults and the UI order.
RENDERING_PARAMS = {
    0: "thickness",
    1: "sides",
    2: "angle",                     # Guess: degrees (values 0, 66.0, 66.1).
    3: "viewport_thickness",
    4: "viewport_sides",
    5: "viewport_angle",
    6: "renderable",                # "Enable In Renderer".
    7: "display_render_mesh",       # Guess: "Enable In Viewport".
    8: "use_viewport_settings",
    9: "generate_mapping_coords",   # Guess.
    10: "real_world_map_size",      # Guess (1 on all but 4 objects).
    11: "rectangular",              # Guess: on for the 8 objects whose rectangular values are non-default.
    12: "rectangular_width",        # Guess: default 2.0.
    13: "rectangular_length",       # Guess: default 6.0.
    14: "rectangular_angle",        # Guess: degrees.
    15: "rectangular_aspect_lock",  # Guess: always 0.
    16: "viewport_rectangular_width",
    17: "viewport_rectangular_length",
    18: "viewport_rectangular_angle",
    19: "viewport_rectangular_aspect_lock",
    20: "auto_smooth",              # Guess: it precedes the threshold.
    21: "auto_smooth_threshold",    # Radians.
    22: "unknown_22",               # Always 0.
}


@dataclasses.dataclass
class ShapeKnot:
    """One Bezier knot. Handles are absolute positions in object space."""
    position: Vec3
    in_handle: Vec3
    out_handle: Vec3
    knot_type: str = "corner"       # KNOT_TYPES value: "smooth", "corner", "bezier" or "bezier_corner".
    segment_type: str = "curve"     # Type of the segment leaving this knot: "curve" or "line".
    material_id: int = 0            # Guess: 0-based material ID of that segment (high 16 bits of the aux word).


@dataclasses.dataclass
class ShapeSpline:
    knots: list[ShapeKnot]
    closed: bool


@dataclasses.dataclass
class ShapeRendering:
    """The shape's "Rendering" settings. Distances in scene units, angles in radians."""
    renderable: bool
    display_render_mesh: bool
    use_viewport_settings: bool
    generate_mapping_coords: bool
    thickness: float
    sides: int
    angle: float
    viewport_thickness: float
    viewport_sides: int
    viewport_angle: float
    rectangular: bool = False
    rectangular_length: float = 6.0
    rectangular_width: float = 2.0
    rectangular_angle: float = 0.0
    auto_smooth: bool = False
    auto_smooth_threshold: float = math.radians(40.0)
    values: dict[str, Any] = dataclasses.field(default_factory=dict)   # Every parameter by RENDERING_PARAMS name.


@dataclasses.dataclass
class ShapeData:
    """A shape as Bezier splines plus its settings."""
    kind: str                       # "LINE", "SPLINE_SHAPE", "TEXT", "RECTANGLE", "CIRCLE", "NGON", "STAR", ...
    splines: list[ShapeSpline]
    source: str                     # "stored" (read from the file), "glyphs" (Text), or "generated".
    params: dict[str, Any] = dataclasses.field(default_factory=dict)
    steps: int | None = None        # Interpolation steps per segment.
    optimize: bool | None = None
    adaptive: bool | None = None
    rendering: ShapeRendering | None = None
    approximate: bool = False       # True when generated without a feature (fillets, NGon corner radius).
    animated: bool = False          # Line / SplineShape: some vertices are animated (only static values given).
    param_block: int | None = None  # Object index of the shape's parameter block.


# -----------------------------------------------------------------------------
# Reading stored splines.

def read_spline(chunk) -> ShapeSpline:
    """Read one spline container (``0x1010`` with ``0x2900`` / ``0x290A`` / ``0x290D``)."""
    count_chunk = chunk.find(CHUNK_KNOT_COUNT)
    knots_chunk = chunk.find(CHUNK_KNOTS)
    if count_chunk is None or knots_chunk is None or count_chunk.payload_size < 4:
        raise DecodeError("spline at 0x{:X} without knot count or knots".format(chunk.offset))
    count = struct.unpack_from("<I", count_chunk.data)[0]
    data = knots_chunk.data
    if len(data) != count * KNOT_RECORD.size:
        raise DecodeError("spline at 0x{:X}: {:d} knots but {:d} bytes of knot data".format(
            chunk.offset, count, len(data)))
    closed_chunk = chunk.find(CHUNK_CLOSED)
    closed = bool(struct.unpack_from("<I", closed_chunk.data)[0]) if (
        closed_chunk is not None and closed_chunk.payload_size >= 4) else False
    knots = []
    for i in range(count):
        ktype, stype, _u, *v, aux = KNOT_RECORD.unpack_from(data, i * KNOT_RECORD.size)
        if not all(math.isfinite(q) for q in v):
            raise DecodeError("spline at 0x{:X}: knot {:d} has non-finite coordinates".format(chunk.offset, i))
        knots.append(ShapeKnot(
            tuple(v[0:3]), tuple(v[3:6]), tuple(v[6:9]),
            KNOT_TYPES.get(ktype, "unknown:{:d}".format(ktype)),
            SEGMENT_TYPES.get(stype, "unknown:{:d}".format(stype)),
            aux >> 16,
        ))
    return ShapeSpline(knots, closed)


def read_bezier_shape(chunk) -> list[ShapeSpline]:
    """The splines of a Bezier shape container (its ``0x1010`` children that hold knots)."""
    return [read_spline(c) for c in chunk.children
            if c.type == CHUNK_SPLINE and c.is_container and c.find(CHUNK_KNOTS) is not None]


# -----------------------------------------------------------------------------
# Generating parametric shapes. All lie in the XY plane, centred on the origin, counter-clockwise.

def _corner_polygon(points, closed=True) -> ShapeSpline:
    """Corner knots with handles 1/3 of the way to their neighbours (straight segments, as Max stores corners)."""
    n = len(points)
    knots = []
    for i, p in enumerate(points):
        prev = points[(i - 1) % n] if (closed or i > 0) else p
        nxt = points[(i + 1) % n] if (closed or i < n - 1) else p
        knots.append(ShapeKnot(
            p,
            tuple(p[k] + (prev[k] - p[k]) / 3.0 for k in range(3)),
            tuple(p[k] + (nxt[k] - p[k]) / 3.0 for k in range(3)),
            "corner", "curve"))
    return ShapeSpline(knots, closed)


def _tangent_knot(point, direction, length, knot_type) -> ShapeKnot:
    dx, dy = direction
    x, y = point
    return ShapeKnot((x, y, 0.0), (x - dx * length, y - dy * length, 0.0), (x + dx * length, y + dy * length, 0.0),
                     knot_type, "curve")


def generate_circle(radius: float, center=(0.0, 0.0)) -> ShapeSpline:
    """
    Four Bezier knots. Verified on circles converted to editable splines in the corpus: the first knot at
    (radius, 0), counter-clockwise, handles KAPPA x radius along the tangent, knot type Bezier.
    """
    cx, cy = center
    knots = []
    for i in range(4):
        a = i * math.pi / 2.0
        c, s = round(math.cos(a)), round(math.sin(a))
        knots.append(_tangent_knot((cx + radius * c, cy + radius * s), (-s, c), KAPPA * radius, "bezier"))
    return ShapeSpline(knots, True)


def generate_rectangle(length: float, width: float, corner_radius: float = 0.0) -> ShapeSpline:
    """
    Width along X, length along Y (verified, see SHAPE_PARAMS). Without a corner radius: four corner knots from
    (width/2, length/2) counter-clockwise (the knot order of rectangles converted to editable splines). With one:
    eight Bezier-corner knots from (width/2, length/2 - radius), handles KAPPA x radius along the outline (the
    converted rounded rectangle in LightGallery_Max2018, whose Rectangle has 60 x 216, radius 6).
    """
    w, h = width / 2.0, length / 2.0
    r = min(max(corner_radius, 0.0), w, h)
    if r <= 0.0:
        return _corner_polygon([(w, h, 0.0), (-w, h, 0.0), (-w, -h, 0.0), (w, -h, 0.0)])
    k = KAPPA * r
    spec = (
        ((w, h - r), (0, 1)), ((w - r, h), (-1, 0)),
        ((-w + r, h), (-1, 0)), ((-w, h - r), (0, -1)),
        ((-w, -h + r), (0, -1)), ((-w + r, -h), (1, 0)),
        ((w - r, -h), (1, 0)), ((w, -h + r), (0, 1)),
    )
    return ShapeSpline([_tangent_knot(p, d, k, "bezier_corner") for p, d in spec], True)


def generate_ngon(radius: float, sides: int, inscribed: bool = True, circular: bool = False) -> ShapeSpline:
    """
    A regular polygon. Guess: first vertex at angle 0, counter-clockwise; circumscribed puts the edge midpoints at
    ``radius``; circular uses Bezier knots with the usual 4/3 tan(pi / 2n) handle length.
    """
    sides = max(int(sides), 3)
    r = radius if inscribed else radius / math.cos(math.pi / sides)
    angles = [2.0 * math.pi * i / sides for i in range(sides)]
    if circular:
        k = r * 4.0 / 3.0 * math.tan(math.pi / (2.0 * sides))
        return ShapeSpline([_tangent_knot((r * math.cos(a), r * math.sin(a)), (-math.sin(a), math.cos(a)), k,
                                          "bezier") for a in angles], True)
    return _corner_polygon([(r * math.cos(a), r * math.sin(a), 0.0) for a in angles])


def generate_star(radius1: float, radius2: float, points: int, distortion: float = 0.0) -> ShapeSpline:
    """
    ``points`` knots at ``radius1`` alternating with knots at ``radius2`` half-way between them, turned by
    ``distortion`` degrees. Guess: the first ``radius1`` knot at angle pi / points (the only corpus Star with a
    modifier, 12 points at radius 8, has a ModContext box of +-8 cos 15 degrees, which rules out a knot on an axis).
    """
    points = max(int(points), 3)
    step = 2.0 * math.pi / points
    start = step / 2.0
    twist = math.radians(distortion)
    pts = []
    for i in range(points):
        a = start + i * step
        pts.append((radius1 * math.cos(a), radius1 * math.sin(a), 0.0))
        b = a + step / 2.0 + twist
        pts.append((radius2 * math.cos(b), radius2 * math.sin(b), 0.0))
    return _corner_polygon(pts)


def generate_donut(radius1: float, radius2: float) -> list[ShapeSpline]:
    """Two concentric circles (Guess: both counter-clockwise, radius1 first)."""
    return [generate_circle(radius1), generate_circle(radius2)]


def generate_angle(length: float, width: float, thickness: float) -> ShapeSpline:
    """
    Guess: an L section, width along X and length along Y, legs ``thickness`` thick, its bounding box centred on
    the origin; fillets and edge radii are not generated.
    """
    w, h = width / 2.0, length / 2.0
    t = min(max(thickness, 0.0), width, length)
    return _corner_polygon([(-w, -h, 0.0), (w, -h, 0.0), (w, -h + t, 0.0), (-w + t, -h + t, 0.0),
                            (-w + t, h, 0.0), (-w, h, 0.0)])


def layout_text(chars, glyphs, size, kerning=0.0, leading=0.0) -> list[ShapeSpline]:
    """
    Place cached glyph outlines. ``chars`` is the character codes in order, ``glyphs`` maps a code to
    ``(advance, [ShapeSpline in glyph units])``.

    Verified on 9 single-line Texts (ModContext boxes): glyphs scaled by size / 1000, each advanced by its advance
    plus ``kerning``, the baseline at y = 0, and the whole text centred on x = 0 by its knot bounding box. Guess:
    a CR (or a lone LF) starts a new line ``size + leading`` lower, lines aligned left. CR and LF draw nothing
    (their cached glyph is the font's missing-glyph box); other codes below 32 do have real glyphs (two corpus
    Texts show "0" and "1" through a cached glyph stored under code 0x13).
    """
    scale = size / GLYPH_UNITS
    out = []
    x = y = 0.0
    prev = None
    for code in chars:
        if code == 13 or (code == 10 and prev != 13):
            x, y = 0.0, y - (size + leading)
        elif code != 10 and code in glyphs:
            advance, splines = glyphs[code]
            for spline in splines:
                out.append(_transform_spline(spline, scale, x, y))
            x += advance * scale + kerning
        prev = code
    xs = [k.position[0] for s in out for k in s.knots]
    if xs:
        shift = -(min(xs) + max(xs)) / 2.0
        out = [_transform_spline(s, 1.0, shift, 0.0) for s in out]
    return out


def _transform_spline(spline, scale, dx, dy) -> ShapeSpline:
    def tr(p):
        return (p[0] * scale + dx, p[1] * scale + dy, p[2] * scale)
    return ShapeSpline([dataclasses.replace(k, position=tr(k.position), in_handle=tr(k.in_handle),
                                            out_handle=tr(k.out_handle)) for k in spline.knots], spline.closed)


# -----------------------------------------------------------------------------
# Settings.

def _u32(chunk, child_type):
    child = chunk.find(child_type)
    if child is None or child.is_container or child.payload_size < 4:
        return None
    return struct.unpack_from("<I", child.data)[0]


def _block(obj, ctx, slot):
    ref = ctx.ref(obj, slot)
    return ctx.scene.param_block(ref) if ref is not None else None


def read_rendering(block) -> ShapeRendering | None:
    """The "Rendering" settings from the 23-parameter block (None for anything else)."""
    if block is None or len(block.params) != len(RENDERING_PARAMS):
        return None
    values = {name: block.value(pid) for pid, name in RENDERING_PARAMS.items()}

    def f(name, default=0.0):
        v = values.get(name)
        return float(v) if isinstance(v, (int, float)) else default

    def i(name, default=0):
        v = values.get(name)
        return int(v) if isinstance(v, (int, float)) else default

    return ShapeRendering(
        renderable=bool(i("renderable")),
        display_render_mesh=bool(i("display_render_mesh")),
        use_viewport_settings=bool(i("use_viewport_settings")),
        generate_mapping_coords=bool(i("generate_mapping_coords")),
        thickness=f("thickness", 1.0),
        sides=i("sides", 12),
        angle=math.radians(f("angle")),
        viewport_thickness=f("viewport_thickness", 1.0),
        viewport_sides=i("viewport_sides", 12),
        viewport_angle=math.radians(f("viewport_angle")),
        rectangular=bool(i("rectangular")),
        rectangular_length=f("rectangular_length", 6.0),
        rectangular_width=f("rectangular_width", 2.0),
        rectangular_angle=math.radians(f("rectangular_angle")),
        auto_smooth=bool(i("auto_smooth")),
        auto_smooth_threshold=f("auto_smooth_threshold", math.radians(40.0)),
        values=values,
    )


def _interpolation_from_block(shape, block):
    if block is None:
        return
    steps, optimize, adaptive = block.value(0), block.value(1), block.value(2)
    shape.steps = int(steps) if isinstance(steps, (int, float)) else None
    shape.optimize = bool(optimize) if optimize is not None else None
    shape.adaptive = bool(adaptive) if adaptive is not None else None


def _named_params(block, names) -> dict[str, Any]:
    if block is None:
        return {}
    return {name: block.value(pid) for pid, name in names.items() if block.value(pid) is not None}


def _common(obj, ctx, kind, source):
    shape = ShapeData(kind, [], source)
    shape.rendering = read_rendering(_block(obj, ctx, SLOT_RENDERING))
    return shape


# -----------------------------------------------------------------------------
# Decoders.

def _stored_shape(obj, ctx, kind, body):
    shape = _common(obj, ctx, kind, "stored")
    if body is None:
        raise DecodeError("object {:d} ({:s}): no spline data".format(obj.index, obj.class_label()))
    bezier = body.find(CHUNK_SHAPE)
    if bezier is None or not bezier.is_container:
        raise DecodeError("object {:d} ({:s}): no Bezier shape".format(obj.index, obj.class_label()))
    shape.splines = read_bezier_shape(bezier)
    steps = _u32(body, CHUNK_STEPS)
    optimize = _u32(body, CHUNK_OPTIMIZE)
    adaptive = _u32(body, CHUNK_ADAPTIVE)
    shape.steps = steps
    shape.optimize = bool(optimize) if optimize is not None else None
    shape.adaptive = bool(adaptive) if adaptive is not None else None
    # Slot 1 is the vertex controller ("Master Point Controller"); vertex animation adds point controllers in
    # further slots (found on 5 corpus objects).
    shape.animated = any(slot > 1 for slot in obj.references)
    for i, spline in enumerate(shape.splines):
        if not spline.knots:
            ctx.warn("object {:d} ({:s}): spline {:d} has no knots".format(obj.index, obj.class_label(), i))
    return shape


@decoder(CLASS_LINE, kind="shape", name="Line", superclass_id=SUPERCLASS_SHAPE, verified=True)
def line(obj, ctx):
    """Line: stored Bezier splines (inside the object's 0x2000 container)."""
    body = obj.chunk.find(CHUNK_LINE_BODY)
    if body is not None and not body.is_container:
        body = None
    return _stored_shape(obj, ctx, "LINE", body)


@decoder(CLASS_SPLINE_SHAPE, kind="shape", name="Editable Spline", superclass_id=SUPERCLASS_SHAPE, verified=True)
def spline_shape(obj, ctx):
    """SplineShape (editable spline): stored Bezier splines."""
    return _stored_shape(obj, ctx, "SPLINE_SHAPE", obj.chunk)


def _text_string(chunk):
    if chunk is None or chunk.payload_size < 4:
        return None
    n = struct.unpack_from("<I", chunk.data)[0]
    raw = chunk.data[4:4 + n]
    return bytes(raw).decode("utf-16-le", errors="replace").rstrip("\0")


@decoder(CLASS_TEXT, kind="shape", name="Text", superclass_id=SUPERCLASS_SHAPE, verified=True)
def text_shape(obj, ctx):
    """Text: string, font, size; outlines from the file's glyph cache."""
    shape = _common(obj, ctx, "TEXT", "glyphs")
    block = _block(obj, ctx, SLOT_PARAMS)
    shape.param_block = block.object_index if block is not None else None
    shape.params = _named_params(block, SHAPE_PARAMS[CLASS_TEXT][1])
    _interpolation_from_block(shape, _block(obj, ctx, SLOT_INTERPOLATION))
    chunk = obj.chunk
    shape.params["text"] = _text_string(chunk.find(CHUNK_TEXT_STRING))
    shape.params["font"] = _text_string(chunk.find(CHUNK_TEXT_FONT))
    glyphs = {}
    for g in chunk.find_all(CHUNK_TEXT_GLYPH):
        code = _u32(g, CHUNK_GLYPH_CODE)
        advance = g.find(CHUNK_GLYPH_ADVANCE)
        outline = g.find(CHUNK_GLYPH_SHAPE)
        if code is None or advance is None or advance.payload_size < 4:
            ctx.warn("object {:d} (Text): glyph entry without code or advance".format(obj.index))
            continue
        splines = read_bezier_shape(outline) if outline is not None and outline.is_container else []
        glyphs[code] = (struct.unpack_from("<f", advance.data)[0], splines)
    chars_chunk = chunk.find(CHUNK_TEXT_CHARS)
    if chars_chunk is not None and chars_chunk.payload_size >= 4:
        count = struct.unpack_from("<I", chars_chunk.data)[0]
        if chars_chunk.payload_size < 4 + 5 * count:
            raise DecodeError("object {:d} (Text): character list too short".format(obj.index))
        chars = [struct.unpack_from("<I", chars_chunk.data, 4 + 5 * i)[0] for i in range(count)]
    else:
        chars = [ord(c) for c in shape.params["text"] or ""]
    missing = sorted({c for c in chars if c not in (10, 13) and c not in glyphs})
    if missing:
        ctx.warn("object {:d} (Text): no cached glyph for {:d} character(s)".format(obj.index, len(missing)))
    size = shape.params.get("size", 100.0)
    shape.splines = layout_text(chars, glyphs, size, shape.params.get("kerning", 0.0),
                                shape.params.get("leading", 0.0))
    return shape


def _parametric(obj, ctx, class_id):
    kind, names = SHAPE_PARAMS[class_id]
    shape = _common(obj, ctx, kind, "generated")
    slot = SLOT_ANGLE_PARAMS if class_id == CLASS_ANGLE else SLOT_PARAMS
    block = _block(obj, ctx, slot)
    if block is None:
        raise DecodeError("object {:d} ({:s}): no parameter block in slot {:d}".format(
            obj.index, obj.class_label(), slot))
    shape.param_block = block.object_index
    shape.params = _named_params(block, names)
    _interpolation_from_block(shape, _block(obj, ctx, SLOT_INTERPOLATION))
    return shape


def _num(params, name, default=0.0):
    v = params.get(name, default)
    return float(v) if isinstance(v, (int, float)) else default


@decoder(CLASS_RECTANGLE, kind="shape", name="Rectangle", superclass_id=SUPERCLASS_SHAPE, verified=True)
def rectangle(obj, ctx):
    """Rectangle: length, width, corner radius; generated knots."""
    shape = _parametric(obj, ctx, CLASS_RECTANGLE)
    p = shape.params
    shape.splines = [generate_rectangle(_num(p, "length"), _num(p, "width"), _num(p, "corner_radius"))]
    return shape


@decoder(CLASS_CIRCLE, kind="shape", name="Circle", superclass_id=SUPERCLASS_SHAPE, verified=True)
def circle(obj, ctx):
    """Circle: radius; generated knots."""
    shape = _parametric(obj, ctx, CLASS_CIRCLE)
    shape.splines = [generate_circle(_num(shape.params, "radius"))]
    return shape


@decoder(CLASS_NGON, kind="shape", name="NGon", superclass_id=SUPERCLASS_SHAPE)
def ngon(obj, ctx):
    """NGon: radius, sides, corner radius; generated knots (Guess: vertex placement)."""
    shape = _parametric(obj, ctx, CLASS_NGON)
    p = shape.params
    shape.splines = [generate_ngon(_num(p, "radius"), int(_num(p, "sides", 6)), bool(p.get("inscribed", 1)),
                                   bool(p.get("circular", 0)))]
    shape.approximate = _num(p, "corner_radius") > 0.0
    return shape


@decoder(CLASS_STAR, kind="shape", name="Star", superclass_id=SUPERCLASS_SHAPE)
def star(obj, ctx):
    """Star: two radii, points, distortion; generated knots (Guess: orientation, fillets not generated)."""
    shape = _parametric(obj, ctx, CLASS_STAR)
    p = shape.params
    shape.splines = [generate_star(_num(p, "radius1"), _num(p, "radius2"), int(_num(p, "points", 6)),
                                   _num(p, "distortion"))]
    shape.approximate = _num(p, "fillet_radius1") > 0.0 or _num(p, "fillet_radius2") > 0.0
    return shape


@decoder(CLASS_DONUT, kind="shape", name="Donut", superclass_id=SUPERCLASS_SHAPE)
def donut(obj, ctx):
    """Donut: two concentric circles."""
    shape = _parametric(obj, ctx, CLASS_DONUT)
    shape.splines = generate_donut(_num(shape.params, "radius1"), _num(shape.params, "radius2"))
    return shape


@decoder(CLASS_ANGLE, kind="shape", name="Angle", superclass_id=SUPERCLASS_SHAPE)
def angle(obj, ctx):
    """Angle (extended spline): an L section; generated knots (Guess, fillets not generated)."""
    shape = _parametric(obj, ctx, CLASS_ANGLE)
    p = shape.params
    shape.splines = [generate_angle(_num(p, "length"), _num(p, "width"), _num(p, "thickness"))]
    shape.approximate = any(_num(p, n) > 0.0 for n in ("corner_radius1", "corner_radius2", "edge_radii"))
    return shape
