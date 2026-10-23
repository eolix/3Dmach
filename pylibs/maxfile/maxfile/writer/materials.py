# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Materials and maps: Standard (Blinn), Multi/Sub-Object, Bitmap with its Placement (UVGen) and Output, and the
Physical Material; the inverse of :mod:`maxfile.objects.materials` / :mod:`maxfile.objects.maps`
(``docs/format/overview.md`` §7).

Parameter heads and the defaults of parameters the model doesn't set are the dominant values of the corpus
(Standard: 915 sampled materials of the 2015 files; Bitmap: all 175 of them; Multi/Sub-Object: all 57; Physical
Material: 106 sampled materials of the 2018 files, the class doesn't exist in 2015). Counts are given as
"n/N" = this head and value in n of N sampled blocks.
"""

__all__ = ("MaterialWriter", "STANDARD_MAP_SLOTS")

import os
import uuid

from . import classes
from .chunks import cont, f32, leaf, text, u32, u8
from .graph import MaxObject
from .pblock import OLD_FLOAT, OLD_INT, R, Table, old_pb, pb2
from .model import Bitmap, MultiSubMaterial, PhysicalMaterial, StandardMaterial

# Standard material map slots with the Blinn shader (overview.md §7), and their scripting names.
STANDARD_MAP_SLOTS = {
    "ambient": 0, "diffuse": 1, "specular": 2, "specularLevel": 3, "glossiness": 4, "selfIllum": 5,
    "opacity": 6, "filter": 7, "bump": 8, "reflection": 9, "refraction": 10, "displacement": 11,
}
_SLOT_OF_FIELD = {
    "diffuse_map": 1, "specular_map": 2, "specular_level_map": 3, "glossiness_map": 4, "opacity_map": 6,
    "bump_map": 8,
}
# Corpus: Bitmap file formats by extension (the 0x1240 names of all 242 Bitmaps with a file in the 2015 files).
_FORMAT_NAMES = {
    ".tga": "Targa Image File", ".tif": "TIF Image File", ".tiff": "TIF Image File", ".jpg": "JPEG File",
    ".jpeg": "JPEG File", ".bmp": "BMP Image File", ".png": "PNG Image File", ".dds": "DDS Image File",
}


def mtl_header(name, flags=0x200, container=0x4000):
    """The MtlBase header container 0x4000 (overview.md §7): name, flags, 0x4020, 0x4030.

    Corpus: 0x4003 = 0x200 on 759 of 915 Standards and 140 of 175 Bitmaps; 0x4020 = 0 and 0x4030 =
    (0, 0, 0, 1.0) on all of them.
    """
    return cont(container, leaf(0x4001, text(name or "")), leaf(0x4003, u32(flags)), leaf(0x4020, u32(0)),
                leaf(0x4030, u32(0, 0, 0) + f32(1.0)))


class MaterialWriter:
    """Builds material objects, sharing one object per model material, and collects the bitmap assets."""

    def __init__(self, guid_seed="3dmach"):
        self._built = {}            # id(model object) -> MaxObject
        self._keep = []             # The model objects, so their ids stay unique while building.
        self._map_count = 0
        self.assets = []            # [(guid bytes, path)] for FileAssetMetaData3, in order of first use.
        self._asset_of_path = {}
        self._guid_seed = guid_seed

    # -------------------------------------------------------------------------

    def build(self, material):
        if material is None:
            return None
        key = id(material)
        if key not in self._built:
            if isinstance(material, StandardMaterial):
                obj = self.standard(material)
            elif isinstance(material, MultiSubMaterial):
                obj = self.multi_sub(material)
            elif isinstance(material, PhysicalMaterial):
                obj = self.physical(material)
            else:
                raise TypeError("not a material: {!r}".format(material))
            self._built[key] = obj
            self._keep.append(material)
        return self._built[key]

    def asset_guid(self, path):
        """A stable asset ID per path (a name-based UUID, so writing the same scene twice gives the same file)."""
        if path not in self._asset_of_path:
            guid = uuid.uuid5(uuid.NAMESPACE_URL, "{:s}:{:s}".format(self._guid_seed, path)).bytes_le
            self._asset_of_path[path] = guid
            self.assets.append((guid, path))
        return self._asset_of_path[path]

    # -------------------------------------------------------------------------
    # Standard

    def standard(self, m: StandardMaterial) -> MaxObject:
        obj = MaxObject(classes.STANDARD, num_refs=9, label="Standard " + m.name)
        maps = {}
        for field, slot in _SLOT_OF_FIELD.items():
            bitmap = getattr(m, field)
            if bitmap is not None:
                maps[slot] = self.bitmap(bitmap)
        amounts = {8: m.bump_amount / 100.0}

        texmaps = MaxObject(classes.TEXMAPS, num_refs=48)
        mask = 0
        for slot, map_obj in maps.items():
            texmaps.ref(2 * slot + 1, map_obj)
            mask |= 1 << slot
        # Corpus: 0x5003 enable mask (0 on 734 of 915), 0x5108 bump amount (0.3 on 887 of 901), 0x510C-0x510F = 0
        # on 672 of 915 (the amounts of slots 12-15, unused by Blinn).
        texmaps.chunks = [leaf(0x5003, u32(mask)), leaf(0x5108, f32(amounts[8]))]
        texmaps.chunks += [leaf(0x510C + i, f32(0.0)) for i in range(4)]

        shader = self.blinn(m)
        obj.ref(1, texmaps)
        obj.ref(2, shader)
        obj.ref(3, pb2(obj, 9, 0, [
            R(0x00, 1, 0x0000, 0x82, 0, 0x40, 1),               # shader index: 1 = Blinn (877/915)
            R(0x01, 4, 0x0000, 0x82, 0, 0x40, int(m.wire)),     # wire (914/915: 0)
            R(0x02, 4, 0x0000, 0x82, 0, 0x40, int(m.two_sided)),
            R(0x03, 4, 0x0000, 0x82, 0, 0x40, 0),               # face map (881/915)
            R(0x04, 4, 0x0000, 0x82, 0, 0x40, 0),               # faceted (915/915)
            R(0x05, 8, 0x0000, 0x80, 0, 0x40, None),            # shader name: none (903/915)
        ], rollouts=(1,)))
        obj.ref(4, pb2(obj, 9, 1, [
            R(0x00, 1, 0x0000, 0x92, 0, 0x40, 0),               # 915/915
            R(0x01, 6, 0x0001, 0x92, 0, 0xC0, m.opacity / 100.0),
            R(0x02, 2, 0x0001, 0x82, 0, 0xC0, (0.5, 0.5, 0.5)),  # filter colour (865/915)
            R(0x03, 15, 0x2900, 0x1081, 0, 0x40, None),         # 915/915
            R(0x04, 1, 0x0000, 0x92, 0, 0x40, 0),               # opacity type (915/915)
            R(0x05, 6, 0x0001, 0x92, 0, 0xC0, 0.0),             # falloff amount (914/915)
            R(0x06, 0, 0x0001, 0x92, 0, 0xC0, 1.5),             # index of refraction (914/915)
            R(0x07, 0, 0x0001, 0x92, 0, 0xC0, 1.0),             # wire size (914/915)
            R(0x08, 1, 0x0000, 0x92, 0, 0x40, 0),               # 915/915
            R(0x09, 4, 0x0000, 0x82, 0, 0x40, 0),               # 915/915
            R(0x0A, 0, 0x0001, 0x92, 0, 0xC0, 0.0),             # 915/915
            R(0x0B, 0, 0x0001, 0x92, 0, 0xC0, 3.0),             # reflection dimming (909/915)
        ]))
        obj.ref(5, pb2(obj, 9, 2, [                             # Supersampling; record order as in all 915.
            R(0x00, 1, 0x0000, 0x82, 0, 0x40, 3),
            R(0x01, 0, 0x0001, 0x92, 0, 0xC0, 0.5),
            R(0x02, 4, 0x0001, 0x82, 0, 0xC0, 0),               # 914/915
            R(0x04, 0, 0x0000, 0x92, 0, 0x40, 0.1),
            R(0x03, 4, 0x0000, 0x82, 0, 0x40, 1),
            R(0x06, 4, 0x0000, 0x82, 0, 0x40, 1),
            R(0x05, 4, 0x0000, 0x82, 0, 0x40, 1),
            R(0x07, 8, 0x0000, 0x80, 0, 0x40, None),            # 906/915
            R(0x08, 0, 0x0000, 0x92, 0, 0x40, 0.0),
            R(0x09, 0, 0x0000, 0x92, 0, 0x40, 0.0),
            R(0x0A, 4, 0x0000, 0x82, 0, 0x40, 1),               # 914/915
        ]))
        # Map table (overview.md §7): enables, maps (inline indices), amounts. Dominant amounts: 1.0, bump 0.3,
        # slots 12-15 0.0 (561/915).
        enables = [1 if i in maps else 0 for i in range(24)]
        table_maps = [maps.get(i) for i in range(24)]
        table_amounts = [amounts.get(i, 0.0 if 12 <= i <= 15 else 1.0) for i in range(24)]
        names = sorted((name + suffix, pid, index) for name, index in STANDARD_MAP_SLOTS.items()
                       for suffix, pid in (("Map", 1), ("MapAmount", 2), ("MapEnable", 0)))
        obj.ref(6, pb2(obj, 9, 3, [
            R(0x00, 0x804, 0x0000, 0x82, 0, 0x00, Table(enables)),
            R(0x01, 0x80F, 0x0100, 0x81, 0, 0x00, Table(table_maps)),
            R(0x02, 0x806, 0x0000, 0x92, 0, 0x00, Table(table_amounts)),
            R(0x03, 4, 0x0000, 0x82, 0, 0x40, 1),               # 911/915
        ], names=names))
        obj.ref(7, pb2(obj, 9, 4, []))                          # Dynamics: no records in all 915.
        obj.ref(8, sampler())
        # Corpus: 0x5300 = 13 and 0x5600 > 0x0322 = 0 on all 915 Standards.
        obj.chunks = [mtl_header(m.name), leaf(0x5300, u32(13)), cont(0x5600, leaf(0x0322, u32(0)))]
        return obj

    @staticmethod
    def blinn(m: StandardMaterial) -> MaxObject:
        obj = MaxObject(classes.BLINN, num_refs=1)
        ambient = m.ambient if m.ambient is not None else m.diffuse
        obj.ref(0, pb2(obj, 6, 0, [                             # Blinn block: all 912 sampled shaders.
            R(0x00, 2, 0x0001, 0x82, 0, 0xC0, tuple(ambient)),
            R(0x01, 2, 0x0001, 0x82, 0, 0xC0, tuple(m.diffuse)),
            R(0x02, 2, 0x0001, 0x82, 0, 0xC0, tuple(m.specular)),
            R(0x03, 4, 0x0000, 0x82, 0, 0x40, 1),               # ad texture lock (912/912)
            R(0x04, 4, 0x0000, 0x82, 0, 0x40, int(m.ambient is None)),   # ambient-diffuse lock (on: 804/912)
            R(0x05, 4, 0x0000, 0x82, 0, 0x40, 0),               # diffuse-specular lock (911/912)
            R(0x06, 4, 0x0000, 0x82, 0, 0x40, 0),               # use self-illumination colour (904/912)
            R(0x07, 6, 0x0001, 0x92, 0, 0xC0, m.self_illumination / 100.0),
            R(0x08, 2, 0x0001, 0x82, 0, 0xC0, (0.0, 0.0, 0.0)),  # self-illumination colour (906/912)
            R(0x09, 6, 0x0001, 0x92, 0, 0xC0, m.specular_level / 100.0),
            R(0x0A, 6, 0x0001, 0x92, 0, 0xC0, m.glossiness / 100.0),
            R(0x0B, 0, 0x0001, 0x92, 0, 0xC0, 0.1),             # soften (905/912)
        ], rollouts=(1,)))
        # Corpus: 0x5300 = 2 and 0x5020 > 0x0322 = 0 on all 912 Blinn shaders.
        obj.chunks = [leaf(0x5300, u32(2)), cont(0x5020, leaf(0x0322, u32(0)))]
        return obj

    # -------------------------------------------------------------------------
    # Multi/Sub-Object

    def multi_sub(self, m: MultiSubMaterial) -> MaxObject:
        subs = [self.build(sub) for sub in m.materials]
        count = len(subs)
        ids = list(m.ids) if m.ids is not None else list(range(1, count + 1))
        names = list(m.names) if m.names is not None else [""] * count
        obj = MaxObject(classes.MULTI_SUB, num_refs=count + 1, label="Multi/Sub " + m.name)
        # Corpus: all 57 Multi/Sub-Objects of the 2015 files have these four tables; IDs are stored 0-based
        # (overview.md §7), slot names are empty strings, and 0x1005 names item 0 of table 0 "material1".
        obj.ref(0, pb2(obj, 15, 0, [
            R(0x00, 0x80E, 0x1300, 0x881, 0, 0x00, Table(subs)),
            R(0x01, 0x804, 0x1000, 0x82, 0, 0x00, Table([1] * count)),
            R(0x02, 0x808, 0x1000, 0x80, 0, 0x00, Table(names)),
            R(0x03, 0x801, 0x1000, 0x80, 0, 0x00, Table([i - 1 for i in ids])),
        ], rollouts=(1,), names=[("material1", 0, 0)]))
        for i, sub in enumerate(subs):
            obj.ref(i + 1, sub)
        # Corpus: 0x4005 (empty) then 0x4002 = count, after the header, on all 57.
        obj.chunks = [mtl_header(m.name), leaf(0x4005), leaf(0x4002, u32(count))]
        return obj

    # -------------------------------------------------------------------------
    # Bitmap

    def bitmap(self, b: Bitmap) -> MaxObject:
        key = ("bitmap", id(b))
        if key in self._built:
            return self._built[key]
        guid = self.asset_guid(b.path)
        obj = MaxObject(classes.BITMAP, num_refs=4, label="Bitmap " + b.path)
        ext = os.path.splitext(b.path)[1].lower()
        info = [leaf(0x1201, bitmap_info()), cont(0x1260, leaf(0x0002, guid))]
        if ext in _FORMAT_NAMES:
            info.append(leaf(0x1240, text(_FORMAT_NAMES[ext])))
        main = pb2(obj, 9, 0, [                                 # All 175 Bitmaps of the 2015 files.
            R(0x00, 0, 0x0001, 0x92, 0, 0xC0, 0.0),             # clip u
            R(0x01, 0, 0x0001, 0x92, 0, 0xC0, 0.0),             # clip v
            R(0x02, 0, 0x0001, 0x92, 0, 0xC0, 1.0),             # clip w
            R(0x03, 0, 0x0001, 0x92, 0, 0xC0, 1.0),             # clip h
            R(0x04, 0, 0x0001, 0x92, 0, 0xC0, 1.0),             # jitter
            R(0x05, 4, 0x0000, 0x82, 0, 0x40, 0),
            R(0x06, 4, 0x0000, 0x82, 0, 0x40, 0),
            R(0x07, 1, 0x0000, 0x92, 0, 0x40, 0),
            R(0x08, 1, 0x0000, 0x92, 0, 0x40, 0),
            R(0x09, 1, 0x0000, 0x92, 0, 0x40, 0),               # 173/175
            R(0x0A, 1, 0x0000, 0x92, 0, 0x40, 0),               # 174/175
            R(0x0B, 1, 0x0000, 0x92, 0, 0x40, 2),               # 98/175 (filtering?)
            R(0x0C, 4, 0x0000, 0x82, 0, 0x40, 1),
            R(0x0D, 16, 0x0000, 0x80, 0, 0x40, 1, after=[cont(0x0003, *info)]),   # 172/175
            R(0x0E, 18, 0x0300, 0x881, 0, 0x40, None),          # 166/175
            R(0x0F, 18, 0x0300, 0x881, 0, 0x40, None),          # 166/175
            # File name as an asset reference: length 0xFFFFFFFE, then 0x000F > 0x0002 = asset ID (overview §5.1).
            R(0x10, 9, 0x0002, 0x80, 2, 0x40, raw=u32(0xFFFFFFFE), after=[cont(0x000F, leaf(0x0002, guid))]),
        ], rollouts=(1,))
        timing = pb2(obj, 9, 1, [                               # Time block, all 175.
            R(0x00, 12, 0x0000, 0x92, 0, 0x40, 0),              # start frame
            R(0x01, 0, 0x0000, 0x92, 0, 0x40, 1.0),             # playback rate
            R(0x02, 1, 0x0000, 0x92, 0, 0x40, 0),               # end condition
            R(0x03, 4, 0x0000, 0x82, 0, 0x40, 0),
        ])
        obj.ref(0, placement(b))
        obj.ref(1, main)
        obj.ref(2, output())
        obj.ref(3, timing)
        self._map_count += 1
        obj.chunks = [mtl_header(b.name or "Map #{:d}".format(self._map_count))]
        self._built[key] = obj
        self._keep.append(b)
        return obj

    # -------------------------------------------------------------------------
    # Physical Material (Max 2017+)

    def physical(self, m: PhysicalMaterial) -> MaxObject:
        from .physical import physical_material
        maps = {}
        for field in ("base_color_map", "roughness_map", "metalness_map", "transparency_map", "emission_map",
                      "bump_map", "cutout_map"):
            bitmap = getattr(m, field)
            if bitmap is not None:
                maps[field] = self.bitmap(bitmap)
        return physical_material(m, maps)


def sampler() -> MaxObject:
    """The "Max 2.5 Star" sampler of a Standard material (all 915 sampled: old ParamBlock version 2)."""
    obj = MaxObject(classes.MAX25_STAR, num_refs=1)
    obj.ref(0, old_pb(2, [(OLD_FLOAT, 0.5, False), (0x0104, 0, False), (0x0104, 1, False)]))     # 879/915
    obj.chunks = [leaf(0x0200, u32(2)), cont(0x39BF, leaf(0x0100, text("Max 2.5 Star")))]
    return obj


def placement(b: Bitmap) -> MaxObject:
    """The Bitmap's coordinates object ("Placement", UVGen), overview.md §7."""
    obj = MaxObject(classes.PLACEMENT, num_refs=1)
    obj.ref(0, old_pb(6, [                                      # 13 parameters, version 6 (all 246 UVGens).
        (OLD_FLOAT, b.u_offset), (OLD_FLOAT, b.v_offset), (OLD_FLOAT, b.u_tiling), (OLD_FLOAT, b.v_tiling),
        (OLD_FLOAT, 0.0), (OLD_FLOAT, 0.0), (OLD_FLOAT, b.w_angle),
        (OLD_FLOAT, 1.0),                                       # blur (231/246)
        (OLD_FLOAT, 1.0), (OLD_FLOAT, 1.0), (OLD_INT, 1), (OLD_FLOAT, 0.0),     # noise
        (OLD_FLOAT, 0.0),                                       # blur offset (245/246)
    ]))
    # Corpus (246 UVGens): 0x9002 tiling flags 0x50000003 (161; bits 0/1 = U/V tile), 0x9003 0, 0x9009 mapping 4
    # (231), 0x9005 0 (219), 0x9006 0, 0x900B map channel.
    obj.chunks = [leaf(0x9002, u32(0x50000003)), leaf(0x9003, u32(0)), leaf(0x9009, u32(4)),
                  leaf(0x9005, u32(0)), leaf(0x9006, u32(0)), leaf(0x900B, u32(b.map_channel))]
    return obj


def output() -> MaxObject:
    """The Bitmap's Output object: old ParamBlock version 3 with 4 values (359 of 361), slots 1-2 empty."""
    obj = MaxObject(classes.OUTPUT, num_refs=3)
    obj.ref(0, old_pb(3, [(OLD_FLOAT, 1.0), (OLD_FLOAT, 0.0), (OLD_FLOAT, 1.0), (OLD_FLOAT, 1.0)]))
    obj.chunks = [leaf(0x0002, u32(0))]                         # 361/361
    return obj


def bitmap_info(width=320, height=240) -> bytes:
    """The 70-byte bitmap-info settings (0x1201) of a Bitmap's file.

    Fields not decoded; written as the most common record of the 2015 files with the given size (u16 width,
    u16 height, f32 aspect 1.0, f32 gamma 2.2, then the rest of the record 55 times out of 242).
    """
    return (struct_u16(width, height) + f32(1.0, 2.2) + u32(0, 0, 0, 6) + struct_u16(320, 200) + bytes(10)
            + struct_u16(0x7FFF, 0, 0x7FFF, 1) + bytes(6) + f32(1.0) + u32(4, 0) + struct_u16(0))


def struct_u16(*values):
    import struct
    return struct.pack("<{:d}H".format(len(values)), *values)


_ = u8  # Re-exported helpers used by sibling modules.
