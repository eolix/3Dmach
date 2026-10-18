# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
``mx_ui`` command panel, complete Max layout: the catalog (every tab, category, sub-category, rollout and
button; each one implemented by an existing operator or a placeholder), drawing every tab / category /
sub-category / sub-object level with the recording layout of ``test_ui.py`` (which validates operator,
property and icon names against RNA), creating every implemented object type, the Editable Poly commands and
the Modify stack toolbar.
"""

import faulthandler
import os
import sys
import types
import unittest
faulthandler.enable()

import addon_utils
import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _runner_util
from test_ui import (
    LayoutError,
    _operator_rna,
    _ICONS,
    add_cube,
    add_curve,
    clear_scene,
    enable,
    fake_context,
    new_layout,
)

ADDON = "mx_ui"
SIBLINGS = ("mx_keymap", "mx_primitives")
_enabled = []


def setUpModule():
    enable(ADDON)
    _enabled.append(ADDON)
    for name in SIBLINGS:
        if name in _runner_util.project_addons():
            enable(name)
            _enabled.append(name)


def tearDownModule():
    for name in reversed(_enabled):
        addon_utils.disable(name, default_set=True)


def mx_ui():
    return sys.modules[ADDON]


def catalog():
    from mx_ui.command_panel import catalog as mod
    return mod


def state():
    return bpy.context.window_manager.mx_ui


def have_siblings():
    return all(name in _enabled for name in SIBLINGS)


def all_rollout_buttons():
    cat = catalog()
    for rollout in cat.ALL_ROLLOUTS:
        for button in cat.iter_buttons(rollout.rows):
            yield rollout, button


def placeholder_features(layout):
    return [c for c in layout.calls("operator") if c[1]["operator"] == "mx_ui.placeholder"]


def object_mode():
    obj = bpy.context.view_layer.objects.active
    if obj is not None and obj.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')


# -----------------------------------------------------------------------------
# Catalog

class CatalogTest(unittest.TestCase):

    def test_create_categories_match_state(self):
        cat = catalog()
        self.assertEqual([c.key for c in cat.CREATE], [c[0] for c in mx_ui().state.CREATE_CATEGORIES])
        self.assertEqual([t[0] for t in mx_ui().state.COMMAND_TABS],
                         ['CREATE', 'MODIFY', 'HIERARCHY', 'MOTION', 'DISPLAY', 'UTILITIES'])

    def test_max_subcategories_present(self):
        subs = {c.key: [s.label for s in c.subcategories] for c in catalog().CREATE}
        for category, labels in {
            'GEOMETRY': ["Standard Primitives", "Extended Primitives", "Compound Objects", "Particle Systems",
                         "Patch Grids", "NURBS Surfaces", "Doors", "Windows", "AEC Extended", "Stairs",
                         "Point Cloud Objects", "Dynamics Objects", "Body Objects"],
            'SHAPES': ["Splines", "NURBS Curves", "Compound Shapes", "Extended Splines"],
            'LIGHTS': ["Photometric", "Standard"],
            'CAMERAS': ["Standard"],
            'HELPERS': ["Standard", "Atmospheric Apparatus", "Camera Match", "Manipulators", "Particle Flow"],
            'SPACE_WARPS': ["Forces", "Deflectors", "Geometric/Deformable", "Modifier-Based"],
            'SYSTEMS': ["Standard"],
        }.items():
            with self.subTest(category=category):
                for label in labels:
                    self.assertIn(label, subs[category])
        standard = next(s for s in catalog().CREATE[0].subcategories if s.label == "Standard Primitives")
        self.assertEqual([b.label for b in standard.buttons],
                         ["Box", "Cone", "Sphere", "GeoSphere", "Cylinder", "Tube", "Torus", "Pyramid", "Teapot",
                          "Plane", "TextPlus"])
        extended = next(s for s in catalog().CREATE[0].subcategories if s.label == "Extended Primitives")
        self.assertEqual(len(extended.buttons), 13)
        self.assertEqual([b.label for b in extended.buttons if not b.implemented], ["RingWave", "Hose"])
        splines = next(s for s in catalog().CREATE[1].subcategories if s.label == "Splines")
        self.assertEqual([b.label for b in splines.buttons][-3:], ["Egg", "Section", "Freehand"])

    def test_teapot_is_an_original_stand_in(self):
        teapot = catalog().CREATE_BY_KEY["GEOMETRY.STANDARD.TEAPOT"]
        self.assertEqual(teapot.props["kind"], 'TEST_SHAPE')
        self.assertIn("original", teapot.description)
        self.assertIn("not the Utah teapot", teapot.description)

    def test_keys_unique(self):
        cat = catalog()
        create_keys = [b.key for c in cat.CREATE for s in c.subcategories for b in s.buttons]
        self.assertEqual(len(create_keys), len(set(create_keys)))
        self.assertTrue(all(create_keys))
        keys = [b.key for _rollout, b in all_rollout_buttons()]
        self.assertEqual(len(keys), len(set(keys)))
        rollout_keys = [r.key for r in cat.ALL_ROLLOUTS]
        self.assertEqual(len(rollout_keys), len(set(rollout_keys)))

    def check_button(self, button):
        """Implemented: the operator exists and takes these properties. Otherwise: a placeholder."""
        self.assertNotIn("3ds", button.label.lower())
        self.assertNotIn("autodesk", (button.label + button.description).lower())
        self.assertNotIn("arnold", (button.label + button.description).lower())
        if button.icon != 'NONE':
            self.assertIn(button.icon, _ICONS)
        if not button.implemented:
            return False
        if button.requires and button.requires not in _enabled:
            return True
        rna = _operator_rna(button.operator)
        for name, value in button.props.items():
            self.assertIn(name, rna.properties, "{:s}: {:s}".format(button.operator, name))
            prop = rna.properties[name]
            if prop.type == 'ENUM' and not prop.is_enum_flag and isinstance(value, str):
                self.assertIn(value, {item.identifier for item in prop.enum_items})
            if isinstance(value, dict):
                sub_rna = _operator_rna(".".join(name.lower().split("_ot_")))
                for sub_name in value:
                    self.assertIn(sub_name, sub_rna.properties)
        return True

    def test_every_create_button_is_real_or_placeholder(self):
        real = 0
        for key, button in catalog().CREATE_BY_KEY.items():
            with self.subTest(key=key):
                real += self.check_button(button)
        self.assertGreater(real, 40)

    def test_every_rollout_button_is_real_or_placeholder(self):
        real = 0
        for rollout, button in all_rollout_buttons():
            with self.subTest(rollout=rollout.key, button=button.label):
                real += self.check_button(button)
                if button.edit:
                    self.assertIn(button.key, catalog().COMMANDS)
                    self.assertIn(button.mode, {'EXEC', 'PICK'})
        self.assertGreater(real, 60)

    def test_utilities(self):
        cat = catalog()
        self.assertEqual([b.label for b in cat.UTILITIES],
                         ["Perspective Match", "Collapse", "Color Clipboard", "Measure", "Motion Capture",
                          "Reset XForm", "MAXScript", "Flight Studio"])

    def test_editable_poly_rollouts(self):
        titles = [r.title for r in catalog().EDITABLE_POLY]
        for title in ("Selection", "Soft Selection", "Edit Geometry", "Edit Vertices", "Edit Edges", "Edit Borders",
                      "Edit Polygons", "Edit Elements", "Polygon: Material IDs", "Polygon: Smoothing Groups",
                      "Subdivision Surface", "Subdivision Displacement", "Paint Deformation"):
            self.assertIn(title, titles)
        commands = catalog().COMMANDS
        for key, operator in (("EDIT_VERTICES.EXTRUDE", "mesh.extrude_vertices_move"),
                              ("EDIT_EDGES.CHAMFER", "mesh.bevel"),
                              ("EDIT_POLYGONS.EXTRUDE", "mesh.extrude_region_move"),
                              ("EDIT_VERTICES.WELD", "mesh.remove_doubles"), ("EDIT_GEOMETRY.CUT", "mesh.knife_tool"),
                              ("EDIT_GEOMETRY.QUICKSLICE", "mesh.bisect"), ("EDIT_GEOMETRY.MSMOOTH", "mesh.subdivide"),
                              ("EDIT_GEOMETRY.RELAX", "mesh.vertices_smooth"),
                              ("EDIT_GEOMETRY.DETACH", "mesh.separate"), ("SELECTION.GROW", "mesh.select_more"),
                              ("SELECTION.RING", "mesh.select_edge_ring_multi")):
            self.assertEqual(commands["EPOLY." + key].operator, operator)
        self.assertEqual(commands["EPOLY.EDIT_EDGES.CHAMFER"].mode, 'PICK')

    def test_modifier_list_sets(self):
        mm = mx_ui().modifier_map
        labels = [label for _id, label in mm.CATEGORIES]
        for label in ("Selection Modifiers", "Patch/Spline Editing", "Mesh Editing", "Animation", "UV Coordinates",
                      "Cache Tools", "Subdivision Surfaces", "Free Form Deformations", "Parametric Deformers",
                      "Surface", "Conversion"):
            self.assertIn(label, labels)
        names = {entry.label for entry in mm.MODIFIERS}
        for name in ("Edit Poly", "TurboSmooth", "Bend", "FFD 2x2x2", "UVW Map", "Unwrap UVW", "Shell", "Symmetry",
                     "Skin", "Morpher", "Point Cache", "Path Deform", "Extrude", "Lathe", "Sweep"):
            self.assertIn(name, names)
        self.assertGreater(len(mm.MODIFIERS), 100)


# -----------------------------------------------------------------------------
# Drawing

class DrawTest(unittest.TestCase):

    def setUp(self):
        clear_scene()

    def tearDown(self):
        object_mode()
        clear_scene()
        s = state()
        s.command_tab = 'CREATE'
        s.create_category = 'GEOMETRY'
        s.create_active = ""
        s.utility_active = ""
        s.pin_object = ""

    def draw(self, **overrides):
        from mx_ui import command_panel
        layout = new_layout()
        command_panel.draw_command_panel(layout, fake_context(**overrides))
        self.assertTrue(layout.calls())
        return layout

    def test_tab_row_is_icons_only(self):
        layout = self.draw()
        tab_prop = [c for c in layout.calls("prop") if c[1]["property"] == "command_tab"][0]
        self.assertTrue(tab_prop[1]["icon_only"])

    def test_every_create_subcategory(self):
        from mx_ui.command_panel import create
        s = state()
        s.command_tab = 'CREATE'
        for cat in catalog().CREATE:
            s.create_category = cat.key
            for sub in cat.subcategories:
                setattr(s, create.subcategory_prop(cat.key), sub.key)
                with self.subTest(category=cat.key, sub=sub.label):
                    layout = self.draw()
                    texts = [c[1].get("text") for c in layout.calls("operator")]
                    for button in sub.buttons:
                        self.assertIn(button.label, texts)
                    entries = [c for c in layout.calls("operator") if c[1]["operator"] == "object.mx_create_type"]
                    self.assertEqual(len(entries), sum(b.implemented for b in sub.buttons))
                    self.assertIn("AutoGrid", texts)
                    labels = [c[1].get("text") for c in layout.calls("label")]
                    self.assertIn("Object Type", labels)
                    self.assertIn("Name and Color", labels)

    def test_create_highlight_and_parameters(self):
        if not have_siblings():
            self.skipTest("mx_primitives is needed")
        s = state()
        s.command_tab = 'CREATE'
        self.assertEqual(bpy.ops.object.mx_create_type(entry="GEOMETRY.STANDARD.BOX"), {'FINISHED'})
        box = bpy.context.view_layer.objects.active
        self.assertEqual(s.create_active, "GEOMETRY.STANDARD.BOX")
        self.assertEqual(s.create_object, box.name)
        layout = self.draw(active_object=box, object=box)
        box_button = [c for c in layout.calls("operator")
                      if c[1]["operator"] == "object.mx_create_type" and c[1]["text"] == "Box"][0]
        self.assertTrue(box_button[1]["depress"])
        labels = [c[1].get("text") for c in layout.calls("label")]
        self.assertIn("Parameters", labels)
        self.assertIn("Creation Method", labels)
        self.assertTrue(any(c[1].get("property") == "length" for c in layout.calls("prop")))
        # Another object selected: the button is no longer highlighted.
        other = add_cube("Other")
        layout = self.draw(active_object=other, object=other)
        box_button = [c for c in layout.calls("operator")
                      if c[1]["operator"] == "object.mx_create_type" and c[1]["text"] == "Box"][0]
        self.assertFalse(box_button[1]["depress"])

    def modify_draw(self, obj):
        state().command_tab = 'MODIFY'
        return self.draw(active_object=obj, object=obj, selected_objects=[obj])

    def test_modify_editable_poly_every_level(self):
        cube = add_cube()
        layout = self.modify_draw(cube)
        labels = [c[1].get("text") for c in layout.calls("label")]
        for title in ("Selection", "Soft Selection", "Edit Geometry", "Subdivision Surface",
                      "Subdivision Displacement", "Paint Deformation"):
            self.assertIn(title, labels)
        self.assertNotIn("Edit Vertices", labels)
        self.assertIn("Whole Object Selected", labels)
        ops = [c[1]["operator"] for c in layout.calls("operator")]
        self.assertIn("object.mx_edit_command", ops)
        self.assertIn("object.mx_pin_stack", ops)
        self.assertIn("object.mx_make_unique", ops)
        self.assertIn("object.mx_stack_remove", ops)
        self.assertIn("object.mx_show_end_result", ops)
        self.assertIn("OBJECT_MT_mx_modifier_sets", [c[1]["menu"] for c in layout.calls("menu")])

        bpy.ops.object.mode_set(mode='EDIT')
        tool_settings = bpy.context.scene.tool_settings
        expected = {1: "Edit Vertices", 2: "Edit Edges", 3: "Edit Borders", 4: "Edit Polygons", 5: "Edit Elements"}
        for level, title in expected.items():
            if level in {3, 5} and "mx_keymap" not in _enabled:
                continue
            mode = {1: (True, False, False), 2: (False, True, False), 3: (False, True, False),
                    4: (False, False, True), 5: (False, False, True)}[level]
            tool_settings.mesh_select_mode = mode
            if "mx_keymap" in _enabled:
                bpy.context.window_manager.mx_keymap_subobject_level = level
            with self.subTest(level=level):
                layout = self.modify_draw(cube)
                labels = [c[1].get("text") for c in layout.calls("label")]
                self.assertIn(title, labels)
                for other in set(expected.values()) - {title}:
                    self.assertNotIn(other, labels)
                if level >= 4:
                    self.assertIn("Polygon: Material IDs", labels)
                    self.assertIn("Polygon: Smoothing Groups", labels)
                # Sub-object level buttons (Selection rollout and stack), the current one pressed.
                if "mx_keymap" in _enabled:
                    level_ops = [c[1] for c in layout.calls("operator")
                                 if c[1]["operator"] == "mx_keymap.subobject_level"]
                    self.assertTrue(any(c["depress"] for c in level_ops))
        object_mode()

    def test_modify_other_entries(self):
        objects = [add_curve()]
        from mx_ui.command_panel import create
        ctx = bpy.context
        for kind in ("OMNI", "TARGET_SPOT", "PHYSICAL_CAMERA", "DUMMY"):
            objects.append(create.create_object(ctx, kind))
        objects.append(create.create_shape(ctx, 'TEXT'))
        if have_siblings():
            bpy.ops.mesh.mx_primitive_add(kind='TEST_SHAPE')
            objects.append(bpy.context.view_layer.objects.active)
        for obj in objects:
            with self.subTest(obj=obj.name):
                layout = self.modify_draw(obj)
                labels = [c[1].get("text") for c in layout.calls("label")]
                if obj.type == 'CURVE':
                    self.assertIn("Geometry", labels)
                    self.assertIn("Rendering", labels)
                else:
                    self.assertIn("Parameters", labels)
        # Editable Spline at sub-object level.
        curve = objects[0]
        bpy.context.view_layer.objects.active = curve
        bpy.ops.object.mode_set(mode='EDIT')
        self.modify_draw(curve)
        object_mode()

    def test_modify_modifier_entry_and_nurms(self):
        cube = add_cube()
        mm = mx_ui().modifier_map
        mm.add_modifier(bpy.context, cube, "BEND")
        bpy.ops.object.mx_nurms_toggle()
        from mx_ui.command_panel import modify
        self.assertEqual([m.name for m in modify.stack_modifiers(cube)], ["Bend"])
        self.assertEqual(cube.modifiers[0].name, "NURMS")
        layout = self.modify_draw(cube)
        stack = [c[1]["text"] for c in layout.calls("operator") if c[1]["operator"] == "object.mx_stack_select"]
        self.assertEqual(stack, ["Bend", "Editable Poly"])
        bpy.ops.object.mx_stack_select(index=-1)
        layout = self.modify_draw(cube)
        self.assertTrue(any(c[1].get("property") == "levels" for c in layout.calls("prop")))

    def test_hierarchy_motion_display_utilities(self):
        cube = add_cube()
        s = state()
        for tab, prop, values in (('HIERARCHY', "hierarchy_mode", ('PIVOT', 'IK', 'LINK_INFO')),
                                  ('MOTION', "motion_mode", ('PARAMETERS', 'MOTION_PATHS'))):
            s.command_tab = tab
            for value in values:
                setattr(s, prop, value)
                with self.subTest(tab=tab, mode=value):
                    self.draw(active_object=cube, object=cube)
                    self.draw(active_object=None, object=None, selected_objects=[])
        s.hierarchy_mode = 'PIVOT'
        s.command_tab = 'HIERARCHY'
        s.affect_object_only = True
        texts = [c[1].get("text") for c in self.draw(active_object=cube).calls("operator")]
        self.assertIn("Center to Pivot", texts)
        s.affect_object_only = False
        texts = [c[1].get("text") for c in self.draw(active_object=cube).calls("operator")]
        self.assertIn("Center to Object", texts)

        s.command_tab = 'DISPLAY'
        layout = self.draw(active_object=cube, object=cube)
        labels = [c[1].get("text") for c in layout.calls("label")]
        for title in ("Display Color", "Hide by Category", "Hide", "Freeze", "Display Properties", "Link Display"):
            self.assertIn(title, labels)

        s.command_tab = 'UTILITIES'
        for utility in ("", "COLLAPSE", "MEASURE", "RESET_XFORM"):
            s.utility_active = utility
            with self.subTest(utility=utility):
                layout = self.draw(active_object=cube, object=cube)
                texts = [c[1].get("text") for c in layout.calls("operator")]
                for label in ("Perspective Match", "Collapse", "Measure", "Reset XForm", "MAXScript"):
                    self.assertIn(label, texts)
                if utility:
                    self.assertIn("Close", texts)

    def test_menus(self):
        cube = add_cube()
        for name in ("OBJECT_MT_mx_modifier_list", "OBJECT_MT_mx_modifier_sets", "OBJECT_MT_mx_more_utilities"):
            with self.subTest(menu=name):
                menu = types.SimpleNamespace(layout=new_layout())
                getattr(bpy.types, name).draw(menu, fake_context(active_object=cube, object=cube))
                self.assertTrue(menu.layout.calls())
        from mx_ui.command_panel import modify
        holder = types.SimpleNamespace(layout=new_layout())
        op = types.SimpleNamespace(bl_rna=bpy.types.OBJECT_OT_mx_stack_select.bl_rna)
        modify.draw_stack_context_menu(holder, types.SimpleNamespace(button_operator=op))
        self.assertIn("object.mx_collapse_stack", [c[1]["operator"] for c in holder.layout.calls("operator")])

    def test_blender_tool_panels_hidden_in_command_panel(self):
        from mx_ui import command_panel
        panels = list(command_panel.blender_tool_panels())
        self.assertIn(bpy.types.VIEW3D_PT_active_tool_duplicate, panels)
        space = types.SimpleNamespace(type='PROPERTIES', **{
            name: name == "show_properties_tool" for name in command_panel.PROPERTIES_TABS})
        self.assertTrue(command_panel.is_command_panel_space(space))
        ctx = types.SimpleNamespace(space_data=space, area=types.SimpleNamespace(type='PROPERTIES'))
        self.assertFalse(bpy.types.VIEW3D_PT_active_tool_duplicate.poll(ctx))
        # Panels without a poll of their own (registered again with one).
        options = bpy.types.VIEW3D_PT_tools_object_options
        self.assertIn(options, panels)
        self.assertFalse(options.poll(ctx))
        # An ordinary Properties editor keeps Blender's panels.
        setattr(space, next(n for n in command_panel.PROPERTIES_TABS if n != "show_properties_tool"), True)
        self.assertTrue(bpy.types.VIEW3D_PT_active_tool_duplicate.poll(ctx))
        self.assertTrue(options.poll(ctx))
        # Restored when the add-on is disabled, and hidden again when enabled.
        command_panel._restore_blender_tool_panels()
        self.assertFalse(hasattr(options, "poll"))
        self.assertTrue(options.is_registered)
        command_panel._hide_blender_tool_panels()
        self.assertTrue(hasattr(options, "poll"))
        self.assertTrue(bpy.types.VIEW3D_PT_tools_object_options_transform.is_registered)

    def test_layout_errors_are_caught(self):
        # The recording layout rejects unknown operators: makes sure the checks above mean something.
        with self.assertRaises(LayoutError):
            new_layout().operator("object.mx_no_such_operator")


# -----------------------------------------------------------------------------
# Behaviour

class CreateTest(unittest.TestCase):

    def setUp(self):
        clear_scene()

    def tearDown(self):
        object_mode()
        clear_scene()
        state().create_active = ""

    def test_every_implemented_create_button(self):
        cat = catalog()
        count = 0
        for key, button in cat.CREATE_BY_KEY.items():
            if not button.implemented or (button.requires and button.requires not in _enabled):
                continue
            clear_scene()
            if button.needs_selection:
                add_cube()
            before = len(bpy.data.objects)
            with self.subTest(key=key):
                self.assertEqual(bpy.ops.object.mx_create_type(entry=key), {'FINISHED'})
                count += 1
                if button.needs_selection:
                    self.assertTrue(bpy.context.view_layer.objects.active.modifiers)
                elif button.props.get("kind") != 'SKYLIGHT':
                    self.assertGreater(len(bpy.data.objects), before)
                self.assertEqual(state().create_active, key)
        self.assertGreater(count, 30)

    def test_placeholder_and_invoke(self):
        self.assertEqual(bpy.ops.object.mx_create_type(entry="GEOMETRY.EXTENDED.RINGWAVE"), {'CANCELLED'})
        with self.assertRaises(RuntimeError):
            bpy.ops.object.mx_create_type(entry="NO.SUCH")
        # From Edit Mode: creation goes back to object level first, like Max.
        cube = add_cube()
        bpy.ops.object.mode_set(mode='EDIT')
        self.assertEqual(bpy.ops.object.mx_create_type('INVOKE_DEFAULT', entry="LIGHTS.STANDARD.OMNI"),
                         {'FINISHED'})
        self.assertEqual(cube.mode, 'OBJECT')
        self.assertEqual(bpy.context.view_layer.objects.active.type, 'LIGHT')

    def test_extended_splines(self):
        from mx_ui.command_panel import create
        for kind in ('EGG', 'WRECTANGLE', 'CHANNEL', 'ANGLE', 'TEE', 'WIDE_FLANGE'):
            with self.subTest(kind=kind):
                obj = create.create_shape(bpy.context, kind)
                self.assertTrue(obj.data.splines)
                self.assertTrue(obj.data.splines[0].use_cyclic_u)
        self.assertEqual(len(bpy.data.objects["WRectangle001"].data.splines), 2)
        self.assertIn("WideFlange001", bpy.data.objects)


class EditCommandTest(unittest.TestCase):

    def setUp(self):
        clear_scene()
        from mx_ui.command_panel import edit_commands
        self.ec = edit_commands
        self.cube = add_cube()

    def tearDown(self):
        object_mode()
        clear_scene()

    def edit_all(self, obj=None):
        obj = obj or self.cube
        bpy.context.view_layer.objects.active = obj
        if obj.mode != 'EDIT':
            bpy.ops.object.mode_set(mode='EDIT')
        if obj.type == 'MESH':
            bpy.ops.mesh.select_all(action='SELECT')
        else:
            bpy.ops.curve.select_all(action='SELECT')

    def command(self, rollout_key, label):
        return catalog().COMMANDS["{:s}.{:s}".format(rollout_key, label)]

    def run_command(self, key):
        return bpy.ops.object.mx_edit_command(command=key)

    def test_every_command_reaches_its_operator(self):
        """Each command runs (or its operator's poll refuses the context), never a property/argument error."""
        curve = add_curve()
        for key, button in catalog().COMMANDS.items():
            object_mode()
            obj = curve if button.edit == 'CURVE' else self.cube
            if obj.name not in bpy.data.objects:
                continue
            with self.subTest(key=key):
                self.edit_all(obj)
                try:
                    result = self.ec.run_command(bpy.context, button)
                except self.ec.CommandError:
                    continue
                self.assertIsInstance(result, set)

    def test_mesh_commands(self):
        mesh = self.cube.data
        self.edit_all()
        self.assertEqual(self.run_command("EPOLY.EDIT_EDGES.INSERT_VERTEX"), {'FINISHED'})
        self.cube.update_from_editmode()
        self.assertGreater(len(mesh.vertices), 8)
        bpy.ops.mesh.select_all(action='SELECT')
        self.assertEqual(self.run_command("EPOLY.EDIT_GEOMETRY.MSMOOTH"), {'FINISHED'})
        bpy.ops.mesh.select_all(action='SELECT')
        self.assertEqual(self.run_command("EPOLY.EDIT_GEOMETRY.COLLAPSE"), {'FINISHED'})
        self.cube.update_from_editmode()
        self.assertEqual(len(mesh.vertices), 1)

    def test_weld_uses_threshold(self):
        state().weld_threshold = 5.0
        self.edit_all()
        self.assertEqual(self.run_command("EPOLY.EDIT_VERTICES.WELD"), {'FINISHED'})
        self.cube.update_from_editmode()
        self.assertEqual(len(self.cube.data.vertices), 1)
        state().weld_threshold = 0.001

    def test_chamfer_settings_and_detach(self):
        self.edit_all()
        self.assertEqual(self.run_command("EPOLY.EDIT_EDGES.CHAMFER.SETTINGS"), {'FINISHED'})
        self.cube.update_from_editmode()
        self.assertGreater(len(self.cube.data.vertices), 8)
        bpy.ops.mesh.select_all(action='SELECT')
        self.assertEqual(self.run_command("EPOLY.EDIT_GEOMETRY.DETACH"), {'FINISHED'})
        self.assertEqual(len([o for o in bpy.data.objects if o.type == 'MESH']), 2)

    def test_from_object_level_enters_edit_mode(self):
        self.assertEqual(self.cube.mode, 'OBJECT')
        self.assertEqual(self.run_command("EPOLY.SELECTION.GROW"), {'FINISHED'})
        self.assertEqual(self.cube.mode, 'EDIT')

    def test_material_ids_and_auto_smooth(self):
        self.edit_all()
        state().material_id = 3
        self.assertEqual(self.run_command("EPOLY.MATERIAL_IDS.SET"), {'FINISHED'})
        self.cube.update_from_editmode()
        self.assertEqual({p.material_index for p in self.cube.data.polygons}, {2})
        bpy.ops.mesh.select_all(action='DESELECT')
        state().select_material_id = 3
        self.assertEqual(self.run_command("EPOLY.MATERIAL_IDS.SELECT"), {'FINISHED'})
        self.assertEqual(self.cube.data.total_face_sel, 6)
        self.assertEqual(self.run_command("EPOLY.SMOOTHING_GROUPS.AUTO_SMOOTH"), {'FINISHED'})
        self.cube.update_from_editmode()
        self.assertTrue(all(p.use_smooth for p in self.cube.data.polygons))

    def test_curve_commands(self):
        curve = add_curve()
        self.edit_all(curve)
        self.assertEqual(self.run_command("ESPLINE.GEOMETRY.REFINE"), {'FINISHED'})
        curve.update_from_editmode()
        self.assertGreater(len(curve.data.splines[0].points), 3)
        self.assertEqual(self.run_command("ESPLINE.GEOMETRY.CLOSE"), {'FINISHED'})
        curve.update_from_editmode()
        self.assertTrue(curve.data.splines[0].use_cyclic_u)

    def test_wrong_object_type(self):
        light = bpy.data.objects.new("Light", bpy.data.lights.new("Light", 'POINT'))
        bpy.context.scene.collection.objects.link(light)
        bpy.context.view_layer.objects.active = light
        with self.assertRaises(self.ec.CommandError):
            self.ec.run_command(bpy.context, self.command("EPOLY.EDIT_VERTICES", "REMOVE"))

    def test_pick_commands_without_window_run_directly(self):
        self.edit_all()
        self.assertEqual(bpy.ops.object.mx_edit_command('INVOKE_DEFAULT', command="EPOLY.EDIT_POLYGONS.INSET"),
                         {'FINISHED'})


class StackToolbarTest(unittest.TestCase):

    def setUp(self):
        clear_scene()
        from mx_ui.command_panel import modify
        self.modify = modify
        self.cube = add_cube()
        self.mm = mx_ui().modifier_map
        self.mm.add_modifier(bpy.context, self.cube, "BEND")
        self.mm.add_modifier(bpy.context, self.cube, "TURBOSMOOTH")

    def tearDown(self):
        state().pin_object = ""
        clear_scene()

    def test_pin_stack(self):
        self.assertEqual(bpy.ops.object.mx_pin_stack(), {'FINISHED'})
        other = add_cube("Other")
        self.assertIs(self.modify.target_object(bpy.context), self.cube)
        bpy.ops.object.mx_stack_select(index=0)
        self.assertEqual(self.modify.selected_modifier(bpy.context, self.cube).name, "Bend")
        self.assertEqual(bpy.ops.object.mx_stack_remove(), {'FINISHED'})
        self.assertEqual([m.name for m in self.cube.modifiers], ["TurboSmooth"])
        self.assertEqual(bpy.ops.object.mx_pin_stack(), {'FINISHED'})
        self.assertIs(self.modify.target_object(bpy.context), other)

    def test_make_unique(self):
        instance = self.cube.copy()
        bpy.context.scene.collection.objects.link(instance)
        self.assertIs(instance.data, self.cube.data)
        self.assertEqual(bpy.ops.object.mx_make_unique(), {'FINISHED'})
        self.assertIsNot(instance.data, self.cube.data)
        self.assertEqual(bpy.ops.object.mx_make_unique.poll(), False)

    def test_show_end_result_and_remove(self):
        bpy.ops.object.mx_stack_select(index=0)
        self.assertEqual(bpy.ops.object.mx_show_end_result(), {'FINISHED'})
        self.assertEqual([m.show_viewport for m in self.cube.modifiers], [True, False])
        self.assertEqual(bpy.ops.object.mx_show_end_result(), {'FINISHED'})
        self.assertEqual(bpy.ops.object.mx_stack_remove(), {'FINISHED'})
        self.assertEqual([m.name for m in self.cube.modifiers], ["TurboSmooth"])

    def test_nurms_toggle(self):
        self.assertEqual(bpy.ops.object.mx_nurms_toggle(), {'FINISHED'})
        self.assertEqual(self.cube.modifiers[0].name, "NURMS")
        self.assertEqual(bpy.ops.object.mx_nurms_toggle(), {'FINISHED'})
        self.assertNotIn("NURMS", self.cube.modifiers)

    def test_configure_sets_placeholder(self):
        self.assertEqual(bpy.ops.mx_ui.placeholder(feature="Configure Modifier Sets"), {'FINISHED'})


class OtherTabsTest(unittest.TestCase):

    def setUp(self):
        clear_scene()
        self.cube = add_cube()

    def tearDown(self):
        state().utility_active = ""
        clear_scene()

    def test_create_key(self):
        if not bpy.ops.anim.keyframe_insert_by_name.poll():
            self.skipTest("keyframe insertion needs the interface")
        bpy.context.scene.frame_set(5)
        self.assertEqual(bpy.ops.anim.keyframe_insert_by_name(type="Location"), {'FINISHED'})
        self.assertIsNotNone(self.cube.animation_data)
        self.assertEqual(bpy.ops.anim.keyframe_delete_by_name(type="Location"), {'FINISHED'})
        bpy.context.scene.frame_set(1)

    def test_utility_open_close(self):
        self.assertEqual(bpy.ops.wm.mx_utility(utility="MEASURE"), {'FINISHED'})
        self.assertEqual(state().utility_active, "MEASURE")
        self.assertEqual(bpy.ops.wm.mx_utility(utility="MEASURE"), {'FINISHED'})
        self.assertEqual(state().utility_active, "")

    def test_pivot_buttons(self):
        for v in self.cube.data.vertices:
            v.co.x += 3.0
        self.assertEqual(bpy.ops.object.mx_pivot(action='CENTER_TO_OBJECT'), {'FINISHED'})
        self.assertAlmostEqual(self.cube.location.x, 3.0, places=4)


if __name__ == "__main__":
    # Debugging aid: MX_TEST_ONLY=EditCommandTest,DrawTest runs only these test classes.
    if os.environ.get("MX_TEST_ONLY"):
        _only = os.environ["MX_TEST_ONLY"].split(",")
        for _name, _value in list(globals().items()):
            if isinstance(_value, type) and issubclass(_value, unittest.TestCase) and _name not in _only:
                del globals()[_name]
    _runner_util.main()
