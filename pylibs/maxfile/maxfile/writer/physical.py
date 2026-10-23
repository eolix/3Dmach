# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Physical Material (class 0xDEADC0013D6B1CEC / 0xC00), written with the layout of the 2018 corpus files.

**Experimental, Max 2017 and later only.** The class appeared in Max 2017, so no 2015 file has one; a 2015-format
file holding one is something Max never wrote itself. Max 2015 / 2016 show the material as a missing plug-in.
The material's references 1 and 2 (two "Ray Engine" objects of the raytracer plug-in in all 106 sampled
materials) are left empty.

Parameters set from the model (overview.md §7): 1 base_weight, 2 base_color (RGBA), 3 reflectivity, 4 roughness,
5 roughness_inv, 6 metalness, 30 transparency, 33 trans_ior, 37 thin_walled, 50 emission, 51 emit_color, 230
bump_map_amt; maps 101 base colour, 104 roughness, 105 metalness, 109 transparency, 116 emission, 130 bump, 133
cutout. Everything else keeps the dominant corpus value (``_physical_params``).
"""

__all__ = ("physical_material",)

import struct

from . import classes
from ._physical_params import DESC_VERSION, RECORDS, ROLLOUTS, VERSION_WORD
from .chunks import leaf, u32
from .graph import MaxObject
from .materials import mtl_header
from .pblock import R, pb2

_MAP_IDS = {"base_color_map": 101, "roughness_map": 104, "metalness_map": 105, "transparency_map": 109,
            "emission_map": 116, "bump_map": 130, "cutout_map": 133}


def _values(m):
    return {
        0x01: m.base_weight,
        0x02: tuple(m.base_color[:3]) + (1.0,),
        0x03: m.reflectivity,
        0x04: m.roughness,
        0x05: int(m.roughness_inverted),
        0x06: m.metalness,
        0x1E: m.transparency,
        0x21: m.trans_ior,
        0x25: int(m.thin_walled),
        0x32: m.emission,
        0x33: tuple(m.emit_color[:3]) + (1.0,),
        0xE6: m.bump_amount,
    }


def physical_material(m, maps) -> MaxObject:
    """``maps``: model field name -> Bitmap object."""
    obj = MaxObject(classes.PHYSICAL_MATERIAL, num_refs=3, label="Physical " + m.name)
    values = _values(m)
    records = []
    slot_maps = {}
    slot = 0
    positions = []
    for position, rec in enumerate(RECORDS):
        r = R(*rec)
        if r.id in values:
            r.value = values[r.id]
        if r.type == 15 and r.flags_a == 0 and r.raw == b"":
            # A map held in a reference slot (slots handed out in record order, overview.md §5.1).
            for field, map_id in _MAP_IDS.items():
                if map_id == r.id and field in maps:
                    slot_maps[slot] = maps[field]
            slot += 1
        if 101 <= r.id <= 133 or 251 <= r.id <= 270:
            # 0x0012: (record position, 0, map index) for every map record but the first of each table (all 106).
            positions.append((position, r.id - (100 if r.id < 250 else 250)))
        records.append(r)
    table = u32(len(positions)) + b"".join(struct.pack("<IHH", p, 0, k) for p, k in positions)
    block = pb2(obj, DESC_VERSION, 0, records, rollouts=ROLLOUTS, refs=slot_maps, num_refs=slot,
                version_word=VERSION_WORD, extra_chunks=[leaf(0x0012, table)])
    obj.ref(0, block)
    # The MtlBase header of this class is container 0x0100 (overview.md §7), not 0x4000.
    obj.chunks = [mtl_header(m.name, container=0x0100)]
    return obj
