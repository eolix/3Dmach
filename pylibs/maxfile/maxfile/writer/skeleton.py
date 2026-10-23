# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
The scene-level objects every ``.max`` file has: the scene object (class 0x2222) and the 13 objects it references
(``docs/design/max-writer.md``, "Scene-level objects").

Contents are the dominant values of the 305 files saved by Max 2015 ("n/305" = files with that value). Two
levels are available (:class:`maxfile.writer.WriterOptions`):

- ``"full"`` (default): like a scene saved from a fresh Max session: 24 default Standard materials in the
  Material Editor, the render environment with its renderers and render settings, the track view root with the
  entries every 2015 file has (Video Post, Global Tracks with their list controllers, Reaction Manager,
  Parameter Collector, Scene Effects, SME).
- ``"lean"``: the same 13 objects with as little inside as the corpus shows to be optional (no Material Editor
  slots, no track view entries, no render settings): a diagnostic variant for the maintainer's tests in Max.
"""

__all__ = ("build_skeleton", "Skeleton")

import struct

from . import classes
from .chunks import cont, f32, leaf, text, u32, u8
from .controllers import bezier_color, bezier_float
from .graph import MaxObject
from .materials import MaterialWriter
from .model import StandardMaterial
from .pblock import OLD_FLOAT, OLD_INT, R, old_pb, pb2

TICKS_PER_SECOND = 4800


class Skeleton:
    """The scene object and the scene-level objects the rest of the writer hooks into."""

    def __init__(self, scene_obj, root_node, layer, mtl_lib):
        self.scene = scene_obj
        self.root = root_node
        self.layer = layer
        self.mtl_lib = mtl_lib


def _obj(cls, chunks=(), refs=None, num_refs=None):
    return MaxObject(cls, chunks=chunks, refs=refs, num_refs=num_refs)


def build_skeleton(model_scene, materials: MaterialWriter, level="full", next_handle=1) -> Skeleton:
    full = level == "full"

    # Slot 0: Material Editor. Corpus: 26 slots (0 empty, 1-24 the sample-slot materials, 25 empty in 128/305);
    # 0x9010 = 6, 4 (the slot grid), 0x9030 = 24 zero words (135/305), 0x09C0 = 0 (226/305), 0x90B0 = 2, 0x09D0 = 0.
    medit = _obj(classes.MATERIAL_EDITOR, num_refs=26)
    if full:
        for i in range(24):
            medit.ref(i + 1, materials.build(StandardMaterial("{:02d} - Default".format(i + 1))))
    medit.chunks = [leaf(0x9010, u32(6, 4)), leaf(0x9030, u32(*([0] * 24))), leaf(0x09C0, u32(0)),
                    leaf(0x90B0, u32(2)), leaf(0x09D0, u32(0))]

    # Slot 1: MtlBaseLib: the scene's materials (filled by the writer). 0x4110 = count.
    mtl_lib = _obj(classes.MTL_BASE_LIB)

    # Slot 2: Default Sound (243/305; values on all 243).
    sound = _obj(classes.DEFAULT_SOUND, chunks=[
        leaf(0x5000, u32(60)), leaf(0x5001, u32(4)), leaf(0x5003, u32(0)), leaf(0x5004, u32(0)), leaf(0x5010),
        leaf(0x5005, u32(0x80000000)), leaf(0x5009, u32(0x80000000))])

    # Slot 3: RootNode: 16 reference slots, none used (279/305); 0x0120 user data empty (60/305; the others hold
    # physics-engine node properties).
    root = _obj(classes.ROOT_NODE, num_refs=16, chunks=[leaf(0x0120)])

    # Slot 4: RenderEnvironment.
    render_env = _render_environment(full)

    # Slot 5: NamedSelSetList: no named selection sets (280/305).
    named_sets = _obj(classes.NAMED_SEL_SET_LIST, chunks=[leaf(0x0100, u32(0))])

    # Slot 6: track view root.
    tv_root = _track_view(full)

    # Slot 7: Grid Reference (2 slots, none used, all 305).
    grid = _obj(classes.GRID_REFERENCE, num_refs=2)

    # Slot 8: RenderEffects, no effects (269/305): 0x1100 = 0, 0x1110 = 1.
    effects = _obj(classes.RENDER_EFFECTS, chunks=[leaf(0x1100, u32(0)), leaf(0x1110, u32(1))])

    # Slot 9: the default shadow generator, Shadow Map (243/305) with its old ParamBlock (version 2, 5 values: map
    # size 512 (362/456), bias 4.0 (453/456), sample range 1.0 (368/456), 0, and a non-animatable 0).
    shadow = _obj(classes.SHADOW_MAP, num_refs=1)
    shadow.ref(0, old_pb(2, [(OLD_INT, 512), (OLD_FLOAT, 4.0), (OLD_FLOAT, 1.0), (OLD_INT, 0),
                             (0x0104, 0, False)]))

    # Slot 10: Layer Manager with layer "0".
    layer = _base_layer()
    layers = _obj(classes.LAYER_MANAGER, num_refs=1, refs={0: layer}, chunks=[
        leaf(0x1500, u32(1)),                   # Layer count (297/305 have one layer).
        leaf(0x1600, u32(0)),                   # Current layer (303/305).
        leaf(0x1700, "0".encode("utf-8")),      # Current layer name (303/305), 8-bit text.
    ])

    # Slot 11: TrackSetList, empty (all 305).
    track_sets = _obj(classes.TRACK_SET_LIST, chunks=[leaf(0x0100, u32(0))])

    # Slot 12: PersistentIsolationData with its two node sets (all 305).
    isolation = _isolation_data()

    scene = _obj(classes.SCENE, num_refs=13)
    for slot, target in enumerate((medit, mtl_lib, sound, root, render_env, named_sets, tv_root, grid, effects,
                                   shadow, layers, track_sets, isolation)):
        scene.ref(slot, target)
    unit_code, unit_scale = model_scene_unit(model_scene)
    scene.chunks = [
        leaf(0x8500, u32(2)),                   # 305/305
        leaf(0x8530, u32(2)),                   # 305/305
        leaf(0x8510, u32(TICKS_PER_SECOND)),    # 305/305
        leaf(0x8520, u32(unit_code) + f32(unit_scale)),     # System unit (overview.md §4.2)
        leaf(0x9000, u32(next_handle)),         # Next node handle (nodes are numbered 1, 2, ...).
        leaf(0x9600, u32(0)),                   # 305/305
        leaf(0x9700),                           # 305/305
        cont(0x9800, leaf(0x0001, u32(0))),     # 305/305
    ]
    return Skeleton(scene, root, layer, mtl_lib)


def model_scene_unit(model_scene):
    from .model import UNITS
    if model_scene.unit not in UNITS:
        raise ValueError("unknown unit {!r} (one of {:s})".format(model_scene.unit, ", ".join(UNITS)))
    return UNITS[model_scene.unit], float(model_scene.unit_scale)


def _base_layer():
    # Layer "0" (all 331 Base Layers of the 2015 files have these chunks; values: the most common).
    return _obj(classes.BASE_LAYER, chunks=[
        leaf(0x1000, u32(1)),                   # 331/331
        leaf(0x1010, "0".encode("utf-8")),      # Name, 8-bit text (305/331).
        leaf(0x1030, u8(0xFF, 0xFF, 0xFF, 0)),  # Layer colour (white: the most common, 30/331).
        leaf(0x1020, u32(0x00800000)),          # 160/321 sampled
        leaf(0x1040, u32(0)),
        leaf(0x1050, u32(0x0B00D600)),          # 261/321
        leaf(0x1060, f32(1.0, 1.0) + u8(1)),
        cont(0x1070, leaf(0x0006, bytes((0, 0, 1, 0, 0, 1)) + f32(39.3700787) + bytes((0, 1, 1, 1, 1, 0, 0))
                          + f32(1.0))),
        leaf(0x1080, u32(0)),
        leaf(0x1090, u8(0)),
    ])


def _isolation_data():
    sets = [_obj(classes.PERSISTENT_NODE_SET, chunks=[cont(0x001A, leaf(0x001B, u32(0)))]) for _ in range(2)]
    view = [leaf(0x03E8, bytes(48)), leaf(0x03F2, u32(0))]          # 300/305 (zero matrix), 0
    record = cont(0x0001,
                  leaf(0x0002, u8(0)),
                  cont(0x0003, *view),
                  cont(0x0010, cont(0x9001, *view), leaf(0x9002, bytes(12)), leaf(0x9003, u32(0)),
                       leaf(0x9004, u32(1)), leaf(0x9005, u32(0)), leaf(0x9006, u32(0)), leaf(0x9007, u32(0)),
                       leaf(0x9008, u32(0)), leaf(0x9014, u32(0)), leaf(0x9015, u32(0)), leaf(0x9016, u32(0)),
                       leaf(0x9017, u32(0))),
                  leaf(0x0004, u32(0)), leaf(0x0005, u32(0xFFFFFFFF)), leaf(0x0006, u32(17)))
    return _obj(classes.PERSISTENT_ISOLATION_DATA, num_refs=2, refs={0: sets[0], 1: sets[1]}, chunks=[record])


# -----------------------------------------------------------------------------
# Render environment

def _scanline_renderer():
    # Default Scanline Renderer with an Area filter (1,028 of 1,175: these chunks in this order and values).
    area = _obj(classes.AREA_FILTER, chunks=[cont(0x39BF, leaf(0x0100))])
    return _obj(classes.SCANLINE_RENDERER, num_refs=1, refs={0: area}, chunks=[
        leaf(0x0002), leaf(0x0020), leaf(0x0072), leaf(0x1000, u32(1)), leaf(0x0007, f32(1.0)),
        leaf(0x0008, f32(1.0)), leaf(0x0009, u32(10)), leaf(0x000A, u32(10)), leaf(0x000B, f32(0.5)),
        leaf(0x0030, f32(0.5)), leaf(0x000D, u32(1)), leaf(0x0060, f32(1.5)),
        leaf(0x0077, u32(0x25773211, 0)),       # The sampler's class ID (Max 2.5 Star), 1,102/1,175.
        leaf(0x0074), leaf(0x0075), leaf(0x0071, f32(0.5)), leaf(0x0076, f32(0.1)), leaf(0x0080, u32(0)),
    ])


def _render_element_manager(flag):
    # All 610: one manager with 0x1240 = 0, one with 1 (in every file).
    return _obj(classes.RENDER_ELEMENT_MGR, chunks=[
        leaf(0x1200, u8(1)), leaf(0x1210, u32(0)), leaf(0x1240, u32(flag)), leaf(0x1220, u32(0)),
        leaf(0x1230, u32(100, 55, 37, 90, 500)), leaf(0x1240, u32(flag)), leaf(0x1250, u8(1)), leaf(0x1260, u8(0))])


def _render_settings(kind):
    """One render-settings record (0x2000 production, 0x2100 material editor (?), 0x2300 ActiveShade (?)).

    All values are the dominant ones of the 305 files; output 640 x 480.
    """
    sizes = u32(640)
    out_info = cont(0x0400, leaf(0x1201, _render_bitmap_info()), leaf(0x1260))
    out_info2 = cont(0x0410, leaf(0x1201, _render_bitmap_info()), leaf(0x1260))
    other = cont(0x05C0, leaf(0x1200, u8(1)), leaf(0x1210, u32(0)), leaf(0x1240, u32(0 if kind == 0x2000 else 1)),
                 leaf(0x1220, u32(0)), leaf(0x1230, u32(100, 55, 37, 90, 500)),
                 leaf(0x1240, u32(0 if kind == 0x2000 else 1)), leaf(0x1250, u8(1)), leaf(0x1260, u8(0)))
    flags = u32(0x0510 if kind == 0x2000 else 0x050F)       # 0x0180: 185/305 (0x2000), 300/305 and 305/305 (others)
    active_shade = kind == 0x2300                           # No 0x05C0 there, 0x0330 / 0x0338 = 0 (201/305).
    return cont(kind,
                leaf(0x0100, u32(0x0501)), leaf(0x0110, u32(0)), leaf(0x0120, u32(16000)), leaf(0x0130, u32(1)),
                leaf(0x0135, u32(0)), leaf(0x0140, u32(1)), leaf(0x0150, u32(0)), leaf(0x0160, u32(0)),
                leaf(0x0170, u32(0)), leaf(0x0180, flags), leaf(0x0610, u32(0)), leaf(0x0620, u32(0)),
                leaf(0x0680), leaf(0x0640, u32(0)), leaf(0x0650, u32(0)), leaf(0x0690), leaf(0x0670, u32(0)),
                leaf(0x0199, u32(0x2803)), leaf(0x0190, sizes), leaf(0x0200, u32(480)), leaf(0x0210, f32(1.0)),
                leaf(0x0440, f32(36.0)), leaf(0x0500, u32(640)), leaf(0x0510, u32(480)), leaf(0x0520, f32(1.0)),
                leaf(0x0530, f32(36.0)), leaf(0x0220, u32(0)), leaf(0x0240, u32(0)), leaf(0x0290, u32(0)),
                leaf(0x0310, u32(0)), leaf(0x0320, u32(0)), leaf(0x0330, u32(0 if active_shade else 1)),
                leaf(0x0338, u32(0 if active_shade else 1)),
                leaf(0x05B0, u32(1)), leaf(0x05D0, u8(1)), leaf(0x05E0, u8(0)), leaf(0x0340, text("1,3,5-12")),
                out_info, out_info2, *([] if active_shade else [other]),
                leaf(0x0601, u32(0, 0, 1, 0, 1) + bytes(780)))     # 800 bytes; 87/305 exactly this pattern.


def _render_bitmap_info():
    # The output bitmap-info record of the render settings (195/305): 640 x 480, aspect 1.0, gamma 1.0.
    return (struct.pack("<HH", 640, 480) + f32(1.0, 1.0) + bytes(16) + struct.pack("<HH", 320, 200) + bytes(10)
            + struct.pack("<HHHH", 0x7FFF, 0, 0x7FFF, 1) + bytes(6) + f32(1.0) + u32(20, 0) + bytes(2))


def _render_environment(full):
    renderers = [_scanline_renderer() for _ in range(4)]
    env = _obj(classes.RENDER_ENVIRONMENT, num_refs=16)
    # References (237/305 have exactly these 10): 0, 1, 2, 12 renderers; 3, 4 render element managers; 6, 7, 8
    # background, tint (?) and ambient (?) colours; 9 a float (tint level ?).
    env.ref(0, renderers[0])
    env.ref(1, renderers[1])
    env.ref(2, renderers[2])
    env.ref(3, _render_element_manager(0))
    env.ref(4, _render_element_manager(1))
    env.ref(6, bezier_color((0.0, 0.0, 0.0)))      # 235/304
    env.ref(7, bezier_color((0.0, 0.0, 0.0)))      # 265/304
    env.ref(8, bezier_color((1.0, 1.0, 1.0)))      # 304/304
    env.ref(9, bezier_float(1.0))                  # 304/304
    env.ref(12, renderers[3])
    chunks = [leaf(0x0100, u32(0)), leaf(0x2000, u32(12)), leaf(0x0120, u32(0))]
    if full:
        chunks.append(cont(0x0110, _render_settings(0x2000), _render_settings(0x2100), _render_settings(0x2300),
                           leaf(0x2400, u32(0)), leaf(0x2500, u8(1))))
    chunks.append(leaf(0x6010, u32(0) + f32(2.2, 2.2)))   # Gamma: off, 2.2, 2.2 (246/305)
    env.chunks = chunks
    return env


# -----------------------------------------------------------------------------
# Track view

def _tv_node(entries=(), markers=()):
    """A track view node: ``entries`` are (name, 8-byte ID, flag, object) in order; slot i = entry i."""
    node = _obj(classes.TV_NODE, num_refs=len(entries))
    chunks = [leaf(m) for m in markers]
    for slot, (name, ident, flag, target) in enumerate(entries):
        node.ref(slot, target)
        chunks += [leaf(0x0110, text(name)), leaf(0x0120, ident), leaf(0x0130, u32(flag))]
    node.chunks = chunks
    return node


def _class_ident(a, b=0):
    return struct.pack("<II", a, b)


def _list_controller(cls, desc_version):
    # A list controller without entries: slots 0-1 empty, 2 = its weights block (304/305 for Float List).
    lst = _obj(cls, num_refs=3, chunks=[leaf(0x1010, u32(0)), leaf(0x1020, u32(0)), leaf(0x2535, u32(0))])
    lst.ref(2, pb2(lst, desc_version, 0, [
        R(0x00, 0x800, 0x1089, 0x92, 0, 0x80, raw=u32(0)),      # weights: an empty float table
        R(0x01, 4, 0x0000, 0x82, 0, 0x40, 0),                   # average: off
    ], rollouts=(1,)))
    return lst


def _track_view(full):
    if not full:
        return _tv_node(markers=(0x0140,))
    # Global tracks. The weights blocks' first header word differs between files; these are the values of the 18
    # files that share one set (Float 0x68 ... Block Control 0x6E, Scene Effect Loader 0x71).
    global_tracks = _tv_node([
        ("Float", _class_ident(0x4B4B1000), 1, _list_controller(classes.FLOAT_LIST, 0x68)),
        ("Point3", _class_ident(0x4B4B1001), 1, _list_controller(classes.POINT3_LIST, 0x69)),
        ("Position", _class_ident(0x4B4B1002), 1, _list_controller(classes.POSITION_LIST, 0x6B)),
        ("Rotation", _class_ident(0x4B4B1003), 1, _list_controller(classes.ROTATION_LIST, 0x6C)),
        ("Scale", _class_ident(0x4B4B1004), 1, _list_controller(classes.SCALE_LIST, 0x6D)),
        ("Block Control", _class_ident(0x4B4B1015), 1, _list_controller(classes.BLOCK_CONTROL, 0x6E)),
    ])
    loader = _obj(classes.SCENE_EFFECT_LOADER, num_refs=1,
                  chunks=[leaf(0x0400, u32(0)), leaf(0x0410, u32(0)), leaf(0x0420, u32(0))])     # 304/304
    loader.ref(0, pb2(loader, 0x71, 0, [
        R(0x00, 0x80E, 0x1000, 0x81, 0, 0x00, raw=u32(0)),      # three empty reference tables (304/304)
        R(0x01, 0x80E, 0x1000, 0x81, 0, 0x00, raw=u32(0)),
        R(0x02, 0x80E, 0x1000, 0x81, 0, 0x00, raw=u32(0)),
    ], rollouts=(1,)))
    scene_effects = _tv_node([("Scene Effect Loader", _class_ident(0x368D1139, 0xF4044794), 1, loader)])
    # Root entries present in all 305 (304 for Scene Effects) files, IDs as stored (the class IDs of the
    # objects they hold where there is one). Flag 0 for track view nodes, 1 for other objects.
    return _tv_node([
        ("Video Post", bytes.fromhex("308d2b4811852cb7"), 0, _tv_node()),
        ("Global Tracks", bytes.fromhex("2a9f7eb270d3fa73"), 0, global_tracks),
        ("Reaction Manager", _class_ident(0x294A389C, 0x087906D7), 1, _obj(classes.REACTION_MANAGER)),
        ("Parameter Collector", bytes.fromhex("4d5baa397e15c174"), 0, _tv_node(markers=(0x0140, 0x0150))),
        ("Scene Effects", _class_ident(0x368D1139, 0xF4044794), 0, scene_effects),
        ("SME", b"\xFF" * 8, 0, _tv_node()),
    ], markers=(0x0140,))
