# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Max-style Units Setup dialog, mapped onto ``scene.unit_settings``.

Max separates the *display* unit (how lengths are shown: Metric, US Standard or Generic) from the
*system* unit (what one internal unit is: "1 Unit = 1.0 Centimeters"). Blender has the same two ideas:

======================  =====================================================
Max                     Blender
======================  =====================================================
Display: Metric         ``system = 'METRIC'``, ``length_unit`` = mm/cm/m/km
Display: US Standard    ``system = 'IMPERIAL'``, ``length_unit`` = feet/inches/...
Display: Generic Units  ``system = 'NONE'``
1 Unit = N <unit>       ``scale_length = N * <unit in meters>``
======================  =====================================================

The mapping functions are plain Python so they can be tested without a dialog.
"""

from bpy.props import EnumProperty, FloatProperty
from bpy.types import Operator

from mx_common.units import METRES_PER_UNIT

# System units (Max's "1 Unit = N <unit>"), with their length in meters (shared with the importer).
SYSTEM_UNITS = tuple(
    (name.upper(), name.title(), METRES_PER_UNIT[name])
    for name in ("inches", "feet", "miles", "millimeters", "centimeters", "meters", "kilometers")
)
METERS_PER_UNIT = {key: meters for key, _label, meters in SYSTEM_UNITS}

DISPLAY_TYPES = (
    ('METRIC', "Metric", "Show lengths in metric units"),
    ('US', "US Standard", "Show lengths in feet and inches"),
    ('GENERIC', "Generic Units", "Show plain numbers without units"),
)

METRIC_UNITS = (
    ('MILLIMETERS', "Millimeters", ""),
    ('CENTIMETERS', "Centimeters", ""),
    ('METERS', "Meters", ""),
    ('KILOMETERS', "Kilometers", ""),
)

# Max's US Standard choices → Blender imperial length units.
US_UNITS = (
    ('FEET_INCHES', "Feet w/ Decimal Inches", "", 'ADAPTIVE'),
    ('FEET', "Decimal Feet", "", 'FEET'),
    ('INCHES', "Decimal Inches", "", 'INCHES'),
    ('MILES', "Miles", "", 'MILES'),
)
US_TO_BLENDER = {key: blender for key, _label, _desc, blender in US_UNITS}
BLENDER_TO_US = {blender: key for key, blender in US_TO_BLENDER.items()}


def apply_units(unit_settings, display, metric_unit='METERS', us_unit='FEET_INCHES',
                system_value=1.0, system_unit='METERS'):
    """Write a Units Setup choice to Blender's ``UnitSettings``."""
    if system_value <= 0.0:
        raise ValueError("The system unit scale must be positive")
    if display == 'METRIC':
        unit_settings.system = 'METRIC'
        unit_settings.length_unit = metric_unit
    elif display == 'US':
        unit_settings.system = 'IMPERIAL'
        unit_settings.length_unit = US_TO_BLENDER[us_unit]
    elif display == 'GENERIC':
        unit_settings.system = 'NONE'
    else:
        raise ValueError("Unknown display unit type {!r}".format(display))
    unit_settings.scale_length = system_value * METERS_PER_UNIT[system_unit]


def read_units(unit_settings):
    """Express ``UnitSettings`` as Units Setup values (the inverse of `apply_units`)."""
    values = {"display": 'GENERIC', "metric_unit": 'METERS', "us_unit": 'FEET_INCHES'}
    if unit_settings.system == 'METRIC':
        values["display"] = 'METRIC'
        if unit_settings.length_unit in {key for key, _label, _desc in METRIC_UNITS}:
            values["metric_unit"] = unit_settings.length_unit
    elif unit_settings.system == 'IMPERIAL':
        values["display"] = 'US'
        values["us_unit"] = BLENDER_TO_US.get(unit_settings.length_unit, 'FEET_INCHES')

    # Pick the system unit that makes "1 Unit = N" a round number, preferring N == 1.
    scale = unit_settings.scale_length
    values["system_unit"], values["system_value"] = 'METERS', scale
    for key, _label, meters in SYSTEM_UNITS:
        if abs(scale / meters - 1.0) < 1e-6:
            values["system_unit"], values["system_value"] = key, 1.0
            break
    return values


class SCENE_OT_mx_units_setup(Operator):
    """Choose how lengths are displayed and what one scene unit is (Max-style Units Setup)"""
    bl_idname = "scene.mx_units_setup"
    bl_label = "Units Setup"
    bl_options = {'REGISTER', 'UNDO'}

    display: EnumProperty(name="Display Unit Scale", items=DISPLAY_TYPES, default='METRIC')
    metric_unit: EnumProperty(name="Metric", items=METRIC_UNITS, default='METERS')
    us_unit: EnumProperty(name="US Standard", items=[item[:3] for item in US_UNITS], default='FEET_INCHES')
    system_value: FloatProperty(
        name="1 Unit",
        description="Size of one scene unit",
        default=1.0,
        min=1e-6,
        soft_max=1000.0,
        precision=4,
    )
    system_unit: EnumProperty(
        name="System Unit",
        items=[(key, label, "") for key, label, _meters in SYSTEM_UNITS],
        default='METERS',
    )

    def invoke(self, context, _event):
        for key, value in read_units(context.scene.unit_settings).items():
            setattr(self, key, value)
        return context.window_manager.invoke_props_dialog(self, width=320)

    def draw(self, _context):
        layout = self.layout
        box = layout.box()
        box.label(text="Display Unit Scale")
        col = box.column()
        col.prop(self, "display", expand=True)
        sub = col.row()
        sub.enabled = self.display == 'METRIC'
        sub.prop(self, "metric_unit", text="")
        sub = col.row()
        sub.enabled = self.display == 'US'
        sub.prop(self, "us_unit", text="")

        box = layout.box()
        box.label(text="System Unit Setup")
        row = box.row(align=True)
        row.prop(self, "system_value")
        row.prop(self, "system_unit", text="")

    def execute(self, context):
        try:
            apply_units(context.scene.unit_settings, self.display, self.metric_unit, self.us_unit,
                        self.system_value, self.system_unit)
        except ValueError as ex:
            self.report({'ERROR'}, str(ex))
            return {'CANCELLED'}
        return {'FINISHED'}


classes = (
    SCENE_OT_mx_units_setup,
)
