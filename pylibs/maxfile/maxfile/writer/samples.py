# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Write a ladder of test files for checking the experimental writer in Max::

    python -m maxfile.writer.samples OUT_DIR

Each file adds one thing to the previous ones, so the first file that fails to open (or opens wrong) points at
what the writer gets wrong. ``OUT_DIR/README.txt`` says what Max should show for each file and how to report.
"""

__all__ = ("SAMPLES", "write_samples", "main")

import argparse
import math
import os
import struct
import sys
import zlib

from . import (
    Bitmap, EditablePoly, MapChannel, MultiSubMaterial, Node, PhysicalMaterial, Scene, StandardMaterial, Transform,
    WriterOptions, write,
)

TEXTURE = "3dmach_checker.png"


def _quat_axis(axis, degrees):
    half = math.radians(degrees) / 2.0
    s = math.sin(half)
    return (math.cos(half), axis[0] * s, axis[1] * s, axis[2] * s)


def box(width=20.0, length=20.0, height=20.0, material_ids=None, uvs=True, smoothing=True):
    """A box like Max's Box primitive converted to Editable Poly: pivot at the bottom centre, 6 quads."""
    x, y = width / 2.0, length / 2.0
    positions = [(-x, -y, 0), (x, -y, 0), (-x, y, 0), (x, y, 0),
                 (-x, -y, height), (x, -y, height), (-x, y, height), (x, y, height)]
    polygons = [[0, 2, 3, 1], [4, 5, 7, 6], [0, 1, 5, 4], [1, 3, 7, 5], [3, 2, 6, 7], [2, 0, 4, 6]]
    channels = {}
    if uvs:
        channels[1] = MapChannel([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)],
                                 [[1, 2, 3, 0], [0, 1, 2, 3], [0, 1, 2, 3], [0, 1, 2, 3], [0, 1, 2, 3], [0, 1, 2, 3]])
    return EditablePoly(positions, polygons, material_ids=material_ids,
                        smoothing_groups=[2, 4, 8, 16, 32, 64] if smoothing else None, map_channels=channels)


def cylinder(radius=10.0, height=30.0, sides=12):
    """A cylinder with n-gon caps (tests polygons with many corners), smoothing groups and UVs."""
    positions = []
    for z in (0.0, height):
        for i in range(sides):
            a = 2.0 * math.pi * i / sides
            positions.append((radius * math.cos(a), radius * math.sin(a), z))
    polygons = [list(reversed(range(sides))), list(range(sides, 2 * sides))]
    for i in range(sides):
        j = (i + 1) % sides
        polygons.append([i, j, sides + j, sides + i])
    uv_verts = [(i / sides, v, 0.0) for v in (0.0, 1.0) for i in range(sides + 1)]
    cap_verts = [(0.5 + 0.5 * math.cos(2 * math.pi * i / sides), 0.5 + 0.5 * math.sin(2 * math.pi * i / sides), 0.0)
                 for i in range(sides)]
    base = len(uv_verts)
    uv_faces = [[base + k for k in reversed(range(sides))], [base + k for k in range(sides)]]
    for i in range(sides):
        uv_faces.append([i, i + 1, sides + 2 + i, sides + 1 + i])
    smoothing = [2, 4] + [1] * sides
    return EditablePoly(positions, polygons, smoothing_groups=smoothing,
                        map_channels={1: MapChannel(uv_verts + cap_verts, uv_faces)})


def checker_png(size=64, squares=8) -> bytes:
    """A small black and white checker PNG (written with zlib, no imaging library)."""
    rows = []
    cell = size // squares
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            v = 255 if ((x // cell) + (y // cell)) % 2 else 40
            row += bytes((v, v, v))
        rows.append(bytes(row))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b""))


# -----------------------------------------------------------------------------
# The ladder

def s01_empty():
    return Scene(), WriterOptions()


def s01b_empty_lean():
    return Scene(), WriterOptions(skeleton="lean")


def s02_box():
    scene = Scene()
    scene.add(Node("Box001", mesh=box(), wire_color=(225, 88, 199)))
    return scene, WriterOptions()


def s02b_triangle():
    scene = Scene()
    scene.add(Node("Triangle001", mesh=EditablePoly([(0, 0, 0), (20, 0, 0), (0, 20, 0)], [[0, 1, 2]])))
    return scene, WriterOptions()


def s03_hierarchy():
    scene = Scene()
    parent = scene.add(Node("Parent_Rot45Z", mesh=box(), transform=Transform((0, 0, 0), _quat_axis((0, 0, 1), 45))))
    child = scene.add(Node("Child_Up40_Scale_1_1_2", parent=parent, mesh=box(10, 10, 10),
                           transform=Transform((0, 0, 40), (1, 0, 0, 0), (1, 1, 2)), wire_color=(255, 0, 0)))
    scene.add(Node("Grandchild_Rot90X", parent=child, mesh=box(5, 5, 5),
                   transform=Transform((15, 0, 0), _quat_axis((1, 0, 0), 90)), wire_color=(0, 0, 255)))
    group = scene.add(Node("Dummy_Group", mesh=None, transform=Transform((60, 0, 0)), dummy_size=20))
    scene.add(Node("InGroup_A", parent=group, mesh=box(8, 8, 8), transform=Transform((0, -10, 0))))
    scene.add(Node("InGroup_B", parent=group, mesh=box(8, 8, 8), transform=Transform((0, 10, 0))))
    scene.add(Node("Hidden_Box", mesh=box(), transform=Transform((-60, 0, 0)), hidden=True))
    scene.add(Node("Frozen_Box", mesh=box(), transform=Transform((-60, 40, 0)), frozen=True))
    scene.add(Node("Offset_Pivot", mesh=box(), transform=Transform((0, 60, 0)),
                   object_offset=Transform((10, 0, 0))))
    return scene, WriterOptions()


def s04_materials():
    scene = Scene()
    red = StandardMaterial("Red_Glossy", diffuse=(0.8, 0.05, 0.05), specular_level=60, glossiness=40)
    textured = StandardMaterial("Checker_Bitmap", diffuse_map=Bitmap(TEXTURE, u_tiling=2, v_tiling=2))
    see_through = StandardMaterial("Half_Transparent_TwoSided", diffuse=(0.1, 0.4, 0.9), opacity=50,
                                   two_sided=True)
    multi = MultiSubMaterial("Multi_RGB", [StandardMaterial("Sub_Red", diffuse=(1, 0, 0)),
                                           StandardMaterial("Sub_Green", diffuse=(0, 1, 0)),
                                           StandardMaterial("Sub_Blue", diffuse=(0, 0, 1))],
                             names=["red", "green", "blue"])
    scene.add(Node("Box_Red", mesh=box(), material=red, transform=Transform((-60, 0, 0))))
    scene.add(Node("Box_Checker", mesh=box(), material=textured, transform=Transform((-20, 0, 0))))
    scene.add(Node("Box_Transparent", mesh=box(), material=see_through, transform=Transform((20, 0, 0))))
    scene.add(Node("Box_MultiSub", mesh=box(material_ids=[1, 2, 3, 1, 2, 3]), material=multi,
                   transform=Transform((60, 0, 0))))
    return scene, WriterOptions()


def s04b_physical():
    scene = Scene()
    gold = PhysicalMaterial("Physical_Gold", base_color=(1.0, 0.77, 0.34), metalness=1.0, roughness=0.3)
    textured = PhysicalMaterial("Physical_Checker", base_color_map=Bitmap(TEXTURE), roughness=0.6)
    scene.add(Node("Box_Gold", mesh=box(), material=gold, transform=Transform((-20, 0, 0))))
    scene.add(Node("Box_PhysicalChecker", mesh=box(), material=textured, transform=Transform((20, 0, 0))))
    return scene, WriterOptions()


def s05_units_cm():
    scene = Scene(unit="centimeters")
    scene.add(Node("Box_100cm", mesh=box(100, 100, 100)))
    scene.add(Node("Cylinder_r25_h150", mesh=cylinder(25, 150, 16), transform=Transform((150, 0, 0))))
    return scene, WriterOptions()


def s06_many_objects():
    scene = Scene()
    for i in range(10):
        for j in range(10):
            n = i * 10 + j
            mesh = box(8, 8, 4 + n % 7 * 3) if n % 3 else cylinder(4, 4 + n % 5 * 4, 6 + n % 9)
            scene.add(Node("Obj_{:02d}".format(n), mesh=mesh, transform=Transform((i * 15.0, j * 15.0, 0)),
                           wire_color=((n * 37) % 256, (n * 91) % 256, (n * 53) % 256)))
    return scene, WriterOptions()


SAMPLES = [
    ("01_empty.max", s01_empty,
     "An empty scene. Max should open it without errors or warnings (except possibly a units / gamma mismatch "
     "dialog). The scene is empty; the Material Editor shows 24 default materials \"01 - Default\" ...; the "
     "system unit is inches."),
    ("01b_empty_lean.max", s01b_empty_lean,
     "Diagnostic: the same empty scene with a minimal skeleton (no Material Editor materials, no track view "
     "entries, no render settings). Only interesting when 01 fails: tells whether the full skeleton is the "
     "problem."),
    ("02_box.max", s02_box,
     "One Editable Poly box \"Box001\", 20 x 20 x 20 units, pivot at the bottom centre, standing on the grid at "
     "the origin, pink wire colour. 8 vertices, 12 edges, 6 polygons; each side has its own smoothing group "
     "(2, 4, 8, 16, 32, 64: flat-shaded sides); UVW channel 1: each side mapped 0-1."),
    ("02b_triangle.max", s02b_triangle,
     "Diagnostic: one Editable Poly triangle \"Triangle001\" (corners (0,0,0), (20,0,0), (0,20,0)), no UVs, no "
     "smoothing. Only interesting when 02 fails."),
    ("03_hierarchy.max", s03_hierarchy,
     "Hierarchy and transforms. \"Parent_Rot45Z\" (box at the origin, rotated 45 degrees about Z) has child "
     "\"Child_Up40_Scale_1_1_2\" (red, 40 units above its parent, scaled 2x in its local Z, so 10 x 10 x 20) whose "
     "child \"Grandchild_Rot90X\" (blue, 15 units along the child's X, rotated 90 degrees about X). "
     "\"Dummy_Group\" is a Dummy helper (20-unit box) at (60, 0, 0) with two small boxes \"InGroup_A\" / "
     "\"InGroup_B\" 10 units either side of it in Y. \"Hidden_Box\" at (-60, 0, 0) is hidden (Unhide All shows "
     "it), \"Frozen_Box\" at (-60, 40, 0) is frozen. \"Offset_Pivot\": node at (0, 60, 0), its geometry shifted "
     "10 units along X from the pivot (the box is centred at x = 10; Hierarchy > Affect Pivot Only shows the pivot "
     "10 units left of the box centre). Please check Select by Name (hierarchy) and the Move / Rotate / Scale "
     "type-ins of each node."),
    ("04_materials.max", s04_materials,
     "Materials (Standard, Blinn). \"Box_Red\": red, glossy (specular level 60, glossiness 40). \"Box_Checker\": "
     "diffuse map Bitmap \"3dmach_checker.png\" (written next to the .max file; tiling 2 x 2; a black / white "
     "checker in the viewport with Show Shaded Material on). \"Box_Transparent\": blue, opacity 50, 2-sided. "
     "\"Box_MultiSub\": Multi/Sub-Object \"Multi_RGB\" with 3 sub-materials (IDs 1, 2, 3 = red, green, blue); "
     "opposite sides have the same colour. The asset tracker should list the PNG."),
    ("04b_physical.max", s04b_physical,
     "Max 2017 and later only: Physical Materials. \"Box_Gold\" gold metal (metalness 1, roughness 0.3), "
     "\"Box_PhysicalChecker\" with the checker PNG as base colour map. Max 2015 / 2016 report a missing plug-in."),
    ("05_units_cm.max", s05_units_cm,
     "System unit centimetres (Customize > Units Setup > System Unit Setup should show 1 unit = 1.0 Centimeters). "
     "\"Box_100cm\": a 100 x 100 x 100 cm box (1 m cube). \"Cylinder_r25_h150\": a 16-sided cylinder with "
     "16-sided polygon caps, radius 25 cm, height 150 cm, 150 cm along X; smooth sides, flat caps, UVs."),
    ("06_many_objects.max", s06_many_objects,
     "100 objects \"Obj_00\" ... \"Obj_99\" on a 10 x 10 grid (15 units apart), boxes of various heights and "
     "cylinders with 6 to 14 sides, each with its own wire colour."),
]

README_HEAD = """Test files from the experimental .max writer of 3Dmach
=========================================================

These files were written by `python -m maxfile.writer.samples` (pylibs/maxfile/maxfile/writer). They imitate
files saved by Max 2015, so any Max from 2015 on should open them (04b needs 2017 or later).

Please open each file in Max (File > Open; for a second check also File > Merge) in order, and report per file:

  NN_name.max: opens / doesn't open (exact message) / crashes
               what looks wrong (geometry, positions, rotations, hierarchy, materials, maps, units, names)
               anything Max printed in the MAXScript Listener or a "missing DLL" / "file errors" dialog
  Also useful: does File > Save then reopen work; which Max version you used.

When a file fails, the earlier ones narrow it down: 01 is only the scene skeleton, 02 adds one Editable Poly
node, 03 hierarchy / transforms / helpers, 04 materials and bitmaps, 05 units and n-gons, 06 many objects. The
"b" files are diagnostics for when the file before them fails.

Files
-----
"""


def write_samples(out_dir, verbose=False):
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, TEXTURE), "wb") as fh:
        fh.write(checker_png())
    lines = [README_HEAD]
    for name, builder, text in SAMPLES:
        scene, options = builder()
        size = write(scene, os.path.join(out_dir, name), options)
        if verbose:
            print("{:<24} {:>9,d} bytes".format(name, size))
        lines.append("{:s}\n{:s}\n".format(name, _wrap(text)))
    with open(os.path.join(out_dir, "README.txt"), "w", encoding="utf-8", newline="\r\n") as fh:
        fh.write("\n".join(lines))
    return [name for name, _, _ in SAMPLES]


def _wrap(text, width=100, indent="    "):
    words = text.split()
    lines, line = [], indent
    for word in words:
        if len(line) + len(word) + 1 > width and line.strip():
            lines.append(line.rstrip())
            line = indent
        line += word + " "
    lines.append(line.rstrip())
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m maxfile.writer.samples",
                                     description="Write the ladder of .max test files and a README.")
    parser.add_argument("out_dir")
    args = parser.parse_args(argv)
    write_samples(args.out_dir, verbose=True)
    print("README:", os.path.join(args.out_dir, "README.txt"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
