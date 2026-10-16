# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Drawing helpers shared by the command panel tabs: Max-style rollouts and the `catalog` cells (buttons, two
per row with small gaps, placeholder buttons and checkboxes, property fields).
"""

from .. import utils
from ..placeholder import placeholder
from . import catalog

EDIT_COMMAND_OPERATOR = "object.mx_edit_command"


def rollout(layout, key, title, default_closed=False):
    """A Max rollout: a collapsible sub-panel with a title. Returns its body layout, or None when closed."""
    header, body = layout.panel("MXUI_" + key, default_closed=default_closed)
    header.label(text=title)
    if body is not None:
        body.use_property_split = False
        body.use_property_decorate = False
    return body


def resolve(value, state):
    """An operator property value from the catalog (`catalog.StateValue` read from the panel state)."""
    if isinstance(value, catalog.StateValue):
        return getattr(state, value.name)
    return value


def set_props(props, values, state):
    for name, value in values.items():
        if isinstance(value, dict):
            # Properties of a macro's sub-operator are filled in when the button runs, not when drawing.
            continue
        setattr(props, name, resolve(value, state))


def draw_button(layout, context, button, text=None, depress=False):
    """Draw a catalog button: an operator, an edit command, or a placeholder."""
    text = button.label if text is None else text
    if button.checkbox:
        return placeholder(layout, text, icon='CHECKBOX_DEHLT', feature=button.label, emboss=False)
    if not button.implemented:
        return placeholder(layout, text, icon=button.icon, feature=button.label)
    state = utils.get_state(context)
    if button.edit:
        active = state is not None and state.edit_command_active == button.key
        props = layout.operator(EDIT_COMMAND_OPERATOR, text=text, icon=button.icon, depress=depress or active)
        props.command = button.key
        return props
    props = layout.operator(button.operator, text=text, icon=button.icon, depress=depress)
    set_props(props, button.props, state)
    return props


def prop_owner(context, owner):
    obj = active_object(context)
    if owner == 'TOOL_SETTINGS':
        return context.scene.tool_settings
    if owner == 'STATE':
        return utils.get_state(context)
    if owner == 'PREFS':
        return utils.get_prefs(context)
    if owner == 'OBJECT':
        return obj
    if owner == 'DATA':
        return getattr(obj, "data", None)
    raise ValueError("Unknown property owner {!r}".format(owner))


def draw_prop(layout, context, cell):
    data = prop_owner(context, cell.owner)
    if data is None or cell.prop not in data.bl_rna.properties:
        row = layout.row()
        row.active = False
        row.label(text=cell.text)
        return
    layout.prop(data, cell.prop, text=cell.text, toggle=cell.toggle, expand=cell.expand, icon=cell.icon)


def draw_cell(layout, context, cell, specials):
    if cell is None:
        layout.label(text="")
    elif isinstance(cell, catalog.Button):
        if cell.settings is not None:
            sub = layout.row(align=True)
            draw_button(sub, context, cell)
            draw_button(sub, context, cell.settings, text="")
        else:
            draw_button(layout, context, cell)
    elif isinstance(cell, catalog.Prop):
        draw_prop(layout, context, cell)
    elif isinstance(cell, catalog.Label):
        layout.label(text=cell.text)
    elif isinstance(cell, catalog.Special):
        draw_special = specials.get(cell.name) if specials else None
        if draw_special is None:
            raise KeyError("No widget for {!r}".format(cell.name))
        draw_special(layout, context)
    else:
        raise TypeError(cell)


def draw_rows(layout, context, rows, specials=None):
    """Draw catalog rows: one cell full width, several cells side by side with small gaps (Max's layout)."""
    col = layout.column(align=False)
    for row in rows:
        if len(row) == 1:
            draw_cell(col, context, row[0], specials)
            continue
        sub = col.row(align=False)
        for cell in row:
            draw_cell(sub, context, cell, specials)
    return col


def draw_rollout(layout, context, data, specials=None):
    """Draw a `catalog.Rollout`."""
    body = rollout(layout, data.key.replace(".", "_"), data.title, data.default_closed)
    if body is not None:
        draw_rows(body, context, data.rows, specials)
    return body


def two_columns(layout):
    """A column for Max's buttons-in-two-columns blocks (Create tab, Utilities)."""
    return layout.grid_flow(row_major=True, columns=2, even_columns=True, even_rows=True, align=False)


_target_stack = []


class target:
    """Draw for ``obj`` instead of the active object (the Modify tab's pinned stack)."""

    def __init__(self, obj):
        self.obj = obj

    def __enter__(self):
        _target_stack.append(self.obj)
        return self.obj

    def __exit__(self, *_args):
        _target_stack.pop()


def active_object(context):
    if _target_stack:
        return _target_stack[-1]
    return getattr(context, "active_object", None)
