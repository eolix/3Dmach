# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Motion tab: the Parameters / Motion Paths buttons and their rollouts (``catalog.MOTION_*``).

Kept minimal for now (modeling comes first): PRS Parameters' Create Key / Delete Key insert and delete
Blender keyframes on the selection (keying sets Location, Rotation, Scaling); everything else is a
placeholder.
"""

from .. import utils
from . import catalog, widgets

MODE_ROLLOUTS = {
    'PARAMETERS': catalog.MOTION_PARAMETERS,
    'MOTION_PATHS': catalog.MOTION_PATHS,
}


def draw(layout, context):
    state = utils.get_state(context)
    row = layout.row(align=False)
    row.scale_y = 1.2
    row.prop(state, "motion_mode", expand=True)
    for data in MODE_ROLLOUTS[state.motion_mode]:
        widgets.draw_rollout(layout, context, data)
