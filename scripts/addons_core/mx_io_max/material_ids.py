# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Map Max face material IDs onto Blender material slots.

A Multi/Sub-Object material holds a list of sub-materials, each with an explicit material ID. A face uses the
sub-material whose ID equals the face's material ID. When no sub-material has that ID, Max wraps the face ID
around the number of sub-materials (``id mod count`` picks the sub-material by position). This wrap rule is
the documented user-facing behaviour; check it against real files (``docs/format/overview.md``, To verify #11).

Face material IDs here are the 1-based IDs shown in Max's UI. If the file stores them 0-based, the decoder
adds 1 before calling this module.

This module has no Blender dependency so it can be tested with plain pytest.
"""

__all__ = (
    "slots_for_faces",
)


def slots_for_faces(face_ids, sub_ids):
    """
    Assign each face a material slot.

    :arg face_ids: 1-based material ID per face.
    :arg sub_ids: Material ID of each sub-material, in sub-material order, or ``None`` for an empty
       sub-material entry. Pass ``None`` (not a list) for an object with a single, non Multi/Sub material.
    :return: ``(slot_of_sub, face_slots)``: the slot index used for each sub-material position (or ``None`` when
       no face uses it), and the slot index per face. Only sub-materials actually used by faces get a slot,
       in order of first use by sub-material position, so the slot list stays compact.
    """
    if sub_ids is None:
        return [0], [0] * len(face_ids)
    count = len(sub_ids)
    if count == 0:
        return [], [0] * len(face_ids)

    position_of_id = {}
    for position, sub_id in enumerate(sub_ids):
        if sub_id is not None and sub_id not in position_of_id:
            position_of_id[sub_id] = position

    face_positions = []
    for face_id in face_ids:
        position = position_of_id.get(face_id)
        if position is None:
            position = (face_id - 1) % count
        face_positions.append(position)

    used = sorted(set(face_positions))
    slot_of_sub = [None] * count
    for slot, position in enumerate(used):
        slot_of_sub[position] = slot
    return slot_of_sub, [slot_of_sub[position] for position in face_positions]
