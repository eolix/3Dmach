# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
The classes the writer emits, as the class directory of real Max 2015 files stores them.

Interoperability data learnt from the corpus (``docs/design/max-writer.md``): for each class the name, class ID
(64-bit form, overview.md §2.3), superclass and plug-in DLL (file name and description, as the 2015 files'
DLL directories give them; file names are lower case in all 2015 files). Every entry below is the only value the
2015 corpus files have for that class name (the counts are objects of the class in those files).
"""

from .graph import BUILTIN, ClassDef

_MTL = ("mtl.dlt", "Standard Materials and Textures (Autodesk)")
_MTLGEN = ("mtlgen.dlt", "Default Materials and Textures (Autodesk)")
_CTRL = ("ctrl.dlc", "Standard Controllers (Autodesk)")
_REND = ("rend.dlr", "Default Scanline Renderer (Autodesk)")

# Scene level.
SCENE = ClassDef("Scene", 0x2222, 0x100)                                            # 305 objects
MATERIAL_EDITOR = ClassDef("Material Editor", 0xC80, 0x100)                         # 305
MTL_BASE_LIB = ClassDef("MtlBaseLib", 0x3333, 0x100)                                # 305
DEFAULT_SOUND = ClassDef("Default Sound", 0x1, 0xD00)                               # 243
ROOT_NODE = ClassDef("RootNode", 0x2, 0x1)                                          # 305
RENDER_ENVIRONMENT = ClassDef("RenderEnvironment", 0xEE448B23, 0x1010)              # 305
SCANLINE_RENDERER = ClassDef("Default Scanline Renderer", 0x1, 0xF00, _REND)        # 1,175
AREA_FILTER = ClassDef("Area", 0x77912301, 0x10A0, ("kernel.dlk", "Standard Pre-Filter Kernels (Autodesk)"))  # 1,166
RENDER_ELEMENT_MGR = ClassDef("RenderElementMgr", 0x0654654646576167, 0x200)        # 610
NAMED_SEL_SET_LIST = ClassDef("NamedSelSetList", 0x8D52, 0x100)                     # 305
TV_NODE = ClassDef("TVNode", 0x90F2EE718D73B8AA, 0x200)                             # 3,519
REACTION_MANAGER = ClassDef("Reaction Manager", 0x087906D7294A389C, 0x100,
                            ("reactor.dlc", "Change Reaction Controller (Autodesk)"))  # 305
SCENE_EFFECT_LOADER = ClassDef("Scene Effect Loader", 0xF4044794368D1139, 0x9003,
                               ("sceneeffectloader.dlu", "Scene Effect Manager (Autodesk)"))  # 304
GRID_REFERENCE = ClassDef("Grid Reference", 0x1, 0xFFFFFE00)                        # 305
RENDER_EFFECTS = ClassDef("RenderEffects", 0x17356912, 0x1090)                      # 305
SHADOW_MAP = ClassDef("Shadow Map", 0x100, 0x10D0, _REND)                           # 513
LAYER_MANAGER = ClassDef("Layer Manager", 0x51FF028E0D7374FC, 0x200)                # 305
BASE_LAYER = ClassDef("Base Layer", 0x1DBA1DF07E9858FE, 0x10F0)                     # 331
TRACK_SET_LIST = ClassDef("TrackSetList", 0x2CF03595, 0x100)                        # 305
PERSISTENT_ISOLATION_DATA = ClassDef("PersistentIsolationData", 0x1D74772F7DCD1692, 0x200)  # 305
PERSISTENT_NODE_SET = ClassDef("PersistentNodeSet", 0x54F83FAE66812BA4, 0x200)      # 610

# Global tracks (list controllers in the track view's "Global Tracks").
FLOAT_LIST = ClassDef("Float List", 0x4B4B1000, 0x9003, _CTRL)                      # 316
POINT3_LIST = ClassDef("Point3 List", 0x4B4B1001, 0x9005, _CTRL)                    # 305
POSITION_LIST = ClassDef("Position List", 0x4B4B1002, 0x900B, _CTRL)                # 3,132
ROTATION_LIST = ClassDef("Rotation List", 0x4B4B1003, 0x900C, _CTRL)                # 3,172
SCALE_LIST = ClassDef("Scale List", 0x4B4B1004, 0x900D, _CTRL)                      # 2,924
BLOCK_CONTROL = ClassDef("Block Control", 0x4B4B1015, 0x9011, _CTRL)                # 305

# Parameter blocks and controllers.
PARAM_BLOCK = ClassDef("ParamBlock", 0x8, 0x8)                                      # 11,630
PARAM_BLOCK2 = ClassDef("ParamBlock2", 0x82, 0x82)                                  # 83,808
BEZIER_FLOAT = ClassDef("Bezier Float", 0x2007, 0x9003)                             # 86,259
BEZIER_COLOR = ClassDef("Bezier Color", 0x2011, 0x9005)                             # 1,286
PRS = ClassDef("Position/Rotation/Scale", 0x2005, 0x9008)                           # 11,824
BEZIER_POSITION = ClassDef("Bezier Position", 0x2008, 0x900B)                       # 681
TCB_ROTATION = ClassDef("TCB Rotation", 0x442313, 0x900C)                           # 578
BEZIER_SCALE = ClassDef("Bezier Scale", 0x2010, 0x900D)                             # 10,685

# Nodes and geometry.
NODE = ClassDef("Node", 0x1, 0x1)                                                   # 14,680
EDITABLE_POLY = ClassDef("Editable Poly", 0x192F60981BF8338D, 0x10,
                         ("epoly.dlo", "Editable Poly Object (Autodesk)"))         # 299
DUMMY = ClassDef("Dummy", 0x876234, 0x50)                                          # 198
MASTER_POINT_CONTROLLER = ClassDef("Master Point Controller", 0x0D9C20FF, 0x9010)   # 2,313

# Materials and maps.
STANDARD = ClassDef("Standard", 0x2, 0xC00, _MTL)                                   # 7,753
TEXMAPS = ClassDef("Texmaps", 0x1200, 0x1080, _MTL)                                 # 7,753
BLINN = ClassDef("Blinn", 0x38, 0x10B0, _MTL)                                       # 7,656
MAX25_STAR = ClassDef("Max 2.5 Star", 0x25773211, 0x1110, ("samplers.dlh", "Standard Samplers (Autodesk)"))  # 7,809
MULTI_SUB = ClassDef("Multi/Sub-Object", 0x200, 0xC00, _MTL)                        # 57
BITMAP = ClassDef("Bitmap", 0x240, 0xC10, _MTL)                                     # 248
PLACEMENT = ClassDef("Placement", 0x100, 0xC20, _MTLGEN)                            # 480 (UVGen)
OUTPUT = ClassDef("Output", 0x100, 0xC40, _MTLGEN)                                  # 624
# Physical Material appeared in Max 2017: the entry is the one of the 2017 / 2018 corpus files (2,119 objects).
PHYSICAL_MATERIAL = ClassDef("Physical Material", 0xDEADC0013D6B1CEC, 0xC00,
                             ("physicalmaterial.dlt", "Physical Material"))  # 806 objects in 2018 files

__all__ = [name for name, value in dict(globals()).items() if isinstance(value, ClassDef)] + ["BUILTIN"]
