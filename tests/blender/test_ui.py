# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
``mx_ui``: registration, freeze, Modifier List mapping, units, theme, layout configuration, and smoke tests
of every draw function with a recording layout that checks property, operator, menu and icon names against
Blender's RNA.
"""

import math
import os
import sys
import types
import unittest
import xml.dom.minidom

import addon_utils
import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _runner_util

ADDON = "mx_ui"


def enable(name):
    errors = []
    mod = addon_utils.enable(name, default_set=True, handle_error=lambda ex: errors.append(ex))
    if errors:
        raise errors[0]
    if mod is None:
        raise RuntimeError("add-on {!r} could not be enabled".format(name))
    return mod


def setUpModule():
    enable(ADDON)


def tearDownModule():
    addon_utils.disable(ADDON, default_set=True)


def mx_ui():
    return sys.modules[ADDON]


# -----------------------------------------------------------------------------
# Recording layout

_UILAYOUT = bpy.types.UILayout.bl_rna
_LAYOUT_ATTRS = {prop.identifier for prop in _UILAYOUT.properties}
_ICONS = {item.identifier for item in _UILAYOUT.functions["label"].parameters["icon"].enum_items}
_SUBLAYOUTS = {"row", "column", "box", "split", "grid_flow", "column_flow", "menu_pie"}
_PROP_FUNCS = {"prop", "prop_menu_enum", "prop_enum", "props_enum", "prop_search", "prop_with_popover",
               "prop_with_menu", "prop_tabs_enum", "prop_decorator"}
_OPERATOR_FUNCS = {"operator", "operator_menu_enum", "operator_enum", "operator_menu_hold"}


class LayoutError(AssertionError):
    pass


def _operator_rna(idname):
    category, _, name = idname.partition(".")
    try:
        return getattr(getattr(bpy.ops, category), name).get_rna_type()
    except (AttributeError, KeyError) as ex:
        raise LayoutError("unknown operator {!r}".format(idname)) from ex


def _check_prop(data, prop_name, where):
    if data is None:
        raise LayoutError("{:s}: data is None for {!r}".format(where, prop_name))
    if prop_name.startswith('["'):
        return None
    props = data.bl_rna.properties
    if prop_name not in props:
        raise LayoutError("{:s}: {:s} has no property {!r}".format(where, data.bl_rna.identifier, prop_name))
    return props[prop_name]


class OperatorProps:
    """Stands in for the operator properties returned by ``layout.operator()``."""

    def __init__(self, idname, rna):
        object.__setattr__(self, "_idname", idname)
        object.__setattr__(self, "_rna", rna)

    def __setattr__(self, name, value):
        props = self._rna.properties
        if name not in props:
            raise LayoutError("operator {!r} has no property {!r}".format(self._idname, name))
        prop = props[name]
        if prop.type == 'ENUM' and not prop.is_enum_flag and prop.enum_items:
            values = {item.identifier for item in prop.enum_items}
            if value not in values:
                raise LayoutError("operator {!r}: {!r} is not a valid {:s}".format(self._idname, value, name))
        object.__setattr__(self, name, value)


class RecordingLayout:
    """A fake `UILayout` that records calls and validates them against Blender's RNA."""

    def __init__(self, log):
        object.__setattr__(self, "_log", log)

    def __setattr__(self, name, value):
        if name not in _LAYOUT_ATTRS:
            raise LayoutError("UILayout has no attribute {!r}".format(name))
        object.__setattr__(self, name, value)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        func = _UILAYOUT.functions.get(name)
        if func is None:
            raise LayoutError("UILayout has no function {!r}".format(name))
        param_names = [p.identifier for p in func.parameters if not p.is_output]

        def call(*args, **kwargs):
            if len(args) > len(param_names):
                raise LayoutError("too many arguments for {:s}".format(name))
            bound = dict(zip(param_names, args))
            for key, value in kwargs.items():
                if key not in param_names:
                    raise LayoutError("UILayout.{:s}() has no parameter {!r}".format(name, key))
                bound[key] = value
            return self._record(name, bound)
        return call

    def _record(self, name, bound):
        self._log.append((name, bound))
        icon = bound.get("icon")
        if icon is not None and icon not in _ICONS:
            raise LayoutError("unknown icon {!r} in {:s}()".format(icon, name))
        if name in _SUBLAYOUTS:
            return RecordingLayout(self._log)
        if name == "panel":
            return RecordingLayout(self._log), RecordingLayout(self._log)
        if name in _PROP_FUNCS:
            prop = _check_prop(bound.get("data"), bound.get("property"), name)
            if name == "prop_enum" and prop is not None:
                values = {item.identifier for item in prop.enum_items}
                if bound["value"] not in values:
                    raise LayoutError("{!r} is not a valid value of {!r}".format(bound["value"], bound["property"]))
            if name == "prop_search":
                _check_prop(bound.get("search_data"), bound.get("search_property"), name)
            return None
        if name in _OPERATOR_FUNCS:
            idname = bound["operator"]
            rna = _operator_rna(idname)
            if name in {"operator_menu_enum", "operator_enum"} and bound["property"] not in rna.properties:
                raise LayoutError("operator {!r} has no property {!r}".format(idname, bound["property"]))
            return OperatorProps(idname, rna)
        if name == "menu":
            if not hasattr(bpy.types, bound["menu"]):
                raise LayoutError("unknown menu {!r}".format(bound["menu"]))
        if name == "popover":
            if not hasattr(bpy.types, bound["panel"]):
                raise LayoutError("unknown panel {!r}".format(bound["panel"]))
        return None

    def calls(self, name=None):
        return [c for c in self._log if name is None or c[0] == name]


def new_layout():
    return RecordingLayout([])


def fake_context(**overrides):
    ctx = bpy.context
    values = {
        "scene": ctx.scene,
        "view_layer": ctx.view_layer,
        "window_manager": ctx.window_manager,
        "preferences": ctx.preferences,
        "active_object": ctx.view_layer.objects.active,
        "object": ctx.view_layer.objects.active,
        "selected_objects": [o for o in ctx.view_layer.objects if o.select_get()],
        "collection": ctx.collection,
        "mode": ctx.mode,
        "region": types.SimpleNamespace(width=320, alignment='RIGHT'),
        "space_data": None,
        "window": ctx.window,
        "screen": ctx.screen,
    }
    values.update(overrides)
    values.setdefault("selected_editable_objects", values["selected_objects"])
    values.setdefault("visible_objects", list(ctx.view_layer.objects))
    return types.SimpleNamespace(**values)


# -----------------------------------------------------------------------------
# Scene helpers

def clear_scene():
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    for collection in list(bpy.data.collections):
        bpy.data.collections.remove(collection)
    bpy.context.view_layer.update()


def add_cube(name="Cube", size=2.0):
    import bmesh
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=size)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    view_layer = bpy.context.view_layer
    for other in view_layer.objects:
        if other is not None:
            other.select_set(False)
    obj.select_set(True)
    view_layer.objects.active = obj
    return obj


def add_curve(name="Curve"):
    curve = bpy.data.curves.new(name, 'CURVE')
    spline = curve.splines.new('POLY')
    spline.points.add(2)
    for i, point in enumerate(spline.points):
        point.co = (i, 0.0, 0.0, 1.0)
    obj = bpy.data.objects.new(name, curve)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    return obj


# -----------------------------------------------------------------------------
# Tests

class RegistrationTest(unittest.TestCase):

    def test_types_registered(self):
        for name in (
            "VIEW3D_MT_mx_quad",
            "VIEW3D_MT_mx_quad_convert",
            "VIEW3D_PT_mx_command_panel",
            "VIEW3D_PT_mx_object_properties",
            "OBJECT_MT_mx_modifier_list",
            "TOPBAR_MT_mx_create",
            "TOPBAR_MT_mx_modifiers",
            "TOPBAR_MT_mx_group",
        ):
            with self.subTest(name=name):
                self.assertTrue(hasattr(bpy.types, name), name)

    def test_operators_registered(self):
        for idname in (
            "object.mx_freeze_selected", "object.mx_unfreeze_all", "object.mx_unfreeze_by_name",
            "object.mx_unhide_by_name", "object.mx_modifier_add", "object.mx_stack_select",
            "object.mx_collapse_stack", "object.mx_create", "curve.mx_shape_add", "object.mx_pivot",
            "object.mx_reset_xform", "object.mx_measure", "scene.mx_units_setup", "screen.mx_max_layout",
            "preferences.mx_apply_theme", "object.mx_ui_subobject_level", "object.mx_new_layer_from_selection",
            "object.mx_group", "object.mx_ungroup",
        ):
            with self.subTest(idname=idname):
                _operator_rna(idname)

    def test_quad_menu_is_pie_with_diagonal_quadrants(self):
        self.assertEqual(bpy.types.VIEW3D_MT_mx_quad.bl_idname, "VIEW3D_MT_mx_quad")
        quad_menu = mx_ui().quad_menu
        for mode, quads in quad_menu.QUADS.items():
            with self.subTest(mode=mode):
                self.assertTrue(set(quads) <= {'NW', 'NE', 'SW', 'SE'})
        # Upper quadrants go in the North slot (grows up), lower ones in the South slot (grows down).
        self.assertEqual(quad_menu.PIE_SLOTS[2:4], ('S', 'N'))
        self.assertEqual(dict(quad_menu.QUADRANT_ROWS), {'S': ('SW', 'SE'), 'N': ('NW', 'NE')})

    def test_state_and_prefs(self):
        state = bpy.context.window_manager.mx_ui
        self.assertEqual(state.command_tab, 'CREATE')
        prefs = bpy.context.preferences.addons[ADDON].preferences
        self.assertTrue(prefs.use_max_layout_for_new_files)
        self.assertTrue(prefs.random_wire_colors)


class DrawTest(unittest.TestCase):
    """Every draw function, with a recording layout that validates names against RNA."""

    def setUp(self):
        clear_scene()
        self.state = bpy.context.window_manager.mx_ui

    def tearDown(self):
        clear_scene()
        self.state.command_tab = 'CREATE'
        self.state.create_category = 'GEOMETRY'

    def draw_panel(self, **context_overrides):
        from mx_ui import command_panel
        layout = new_layout()
        command_panel.draw_command_panel(layout, fake_context(**context_overrides))
        return layout

    def test_all_tabs_and_categories(self):
        cube = add_cube()
        for key in ("TURBOSMOOTH", "BEND", "NOISE", "SYMMETRY", "CHAMFER", "OPTIMIZE", "SHELL", "NORMAL"):
            mx_ui().modifier_map.add_modifier(bpy.context, cube, key)
        for tab, *_rest in mx_ui().state.COMMAND_TABS:
            self.state.command_tab = tab
            if tab == 'CREATE':
                for category, *_rest2 in mx_ui().state.CREATE_CATEGORIES:
                    self.state.create_category = category
                    with self.subTest(tab=tab, category=category):
                        self.assertTrue(self.draw_panel().calls())
            else:
                with self.subTest(tab=tab):
                    self.assertTrue(self.draw_panel().calls())

    def test_tab_row_icons_only(self):
        # Max's tab row shows icons only, whatever the width.
        for width in (150, 600):
            layout = self.draw_panel(region=types.SimpleNamespace(width=width, alignment='RIGHT'))
            tab_prop = [c for c in layout.calls("prop") if c[1]["property"] == "command_tab"][0]
            self.assertTrue(tab_prop[1]["icon_only"])

    def test_modify_stack_for_each_entry_type(self):
        from mx_ui.command_panel import modify
        cube = add_cube()
        mm = mx_ui().modifier_map
        self.state.command_tab = 'MODIFY'
        for entry in mm.MODIFIERS:
            if not entry.available or entry.blender_type == "" and entry.setup == "setup_edit_mode":
                continue
            if 'MESH' not in entry.object_types:
                continue
            mod = mm.add_modifier(bpy.context, cube, entry.key)
            with self.subTest(modifier=entry.key):
                layout = new_layout()
                modify.draw(layout, fake_context(active_object=cube, object=cube))
                if mod is not None:
                    texts = [c[1].get("text") for c in layout.calls("operator")]
                    self.assertIn(mod.name, texts)

    def test_stack_order_is_reversed(self):
        from mx_ui.command_panel import modify
        cube = add_cube()
        mm = mx_ui().modifier_map
        mm.add_modifier(bpy.context, cube, "BEND")
        mm.add_modifier(bpy.context, cube, "TURBOSMOOTH")
        layout = new_layout()
        modify.draw_stack(layout, fake_context(active_object=cube), cube)
        texts = [c[1]["text"] for c in layout.calls("operator") if c[1]["operator"] == "object.mx_stack_select"]
        self.assertEqual(texts, ["TurboSmooth", "Bend", "Editable Poly"])

    def test_modify_other_object_types(self):
        from mx_ui.command_panel import modify, create
        ctx = bpy.context
        objects = [add_curve()]
        for kind in ("OMNI", "FREE_SPOT", "FREE_CAMERA", "DUMMY"):
            objects.append(create.create_object(ctx, kind))
        for kind in ("TEXT", "RECTANGLE"):
            objects.append(create.create_shape(ctx, kind))
        for obj in objects:
            with self.subTest(obj=obj.name):
                modify.draw(new_layout(), fake_context(active_object=obj, object=obj))

    def test_no_active_object(self):
        for tab, *_rest in mx_ui().state.COMMAND_TABS:
            self.state.command_tab = tab
            with self.subTest(tab=tab):
                self.draw_panel(active_object=None, object=None, selected_objects=[])

    def test_primitives_missing_draws_disabled_buttons(self):
        from mx_ui.command_panel import create
        if mx_ui().utils.primitives_operator_available():
            self.skipTest("mx_primitives is enabled")
        layout = new_layout()
        create.draw(layout, fake_context())
        texts = [c[1].get("text") for c in layout.calls("operator")]
        self.assertIn("Box", texts)
        labels = [c[1].get("text") for c in layout.calls("label")]
        self.assertTrue(any("Primitives add-on" in (text or "") for text in labels))

    def test_quad_menu_draw(self):
        quad_menu = mx_ui().quad_menu
        add_cube()
        for mode in ('OBJECT', 'EDIT_MESH', 'SCULPT'):
            with self.subTest(mode=mode):
                menu = types.SimpleNamespace(layout=new_layout())
                quad_menu.VIEW3D_MT_mx_quad.draw(menu, fake_context(mode=mode))
                calls = menu.layout.calls()
                self.assertEqual(len(menu.layout.calls("menu_pie")), 1)
                self.assertTrue(menu.layout.calls("operator"))
                # W and E empty, then the South and North slots each split into two quadrants.
                self.assertEqual([c[0] for c in calls[1:4]], ["separator", "separator", "split"])
                self.assertEqual(len(menu.layout.calls("split")), 2)
                self.assertEqual(len(menu.layout.calls("box")), len(quad_menu.quads_for_mode(mode)))

    def test_quad_items_valid(self):
        quad_menu = mx_ui().quad_menu
        for mode, quads in quad_menu.QUADS.items():
            for slot, (_title, items) in quads.items():
                for item in items:
                    with self.subTest(mode=mode, slot=slot, item=getattr(item, "text", None)):
                        quad_menu.draw_item(new_layout(), item)

    def test_menus(self):
        cube = add_cube()
        for name in ("OBJECT_MT_mx_modifier_list", "TOPBAR_MT_mx_create", "TOPBAR_MT_mx_create_shapes",
                     "TOPBAR_MT_mx_create_lights", "TOPBAR_MT_mx_create_cameras", "TOPBAR_MT_mx_create_helpers",
                     "TOPBAR_MT_mx_modifiers", "TOPBAR_MT_mx_group", "VIEW3D_MT_mx_quad_convert",
                     "VIEW3D_MT_mx_quad_convert_selection"):
            with self.subTest(menu=name):
                cls = getattr(bpy.types, name)
                menu = types.SimpleNamespace(layout=new_layout(), groups=getattr(cls, "groups", ()))
                cls.draw(menu, fake_context(active_object=cube, object=cube))
                self.assertTrue(menu.layout.calls())

    def test_object_properties(self):
        # The menu bar and main toolbar are tested in `test_ui_menus.py`.
        cube = add_cube()
        mx_ui().quad_menu.draw_object_properties(new_layout(), cube)

    def test_preferences_and_units_dialog(self):
        prefs = bpy.context.preferences.addons[ADDON].preferences

        class Proxy:
            """Forwards to ``real`` but draws into a recording layout."""

            def __init__(self, real):
                self.layout = new_layout()
                self._real = real

            def __getattr__(self, name):
                return getattr(self._real, name)

        type(prefs).draw(Proxy(prefs), fake_context())

        op_rna = bpy.ops.scene.mx_units_setup.get_rna_type()
        op = types.SimpleNamespace(layout=new_layout(), bl_rna=op_rna, display='METRIC', metric_unit='METERS',
                                   us_unit='FEET', system_value=1.0, system_unit='METERS')
        mx_ui().units.SCENE_OT_mx_units_setup.draw(op, bpy.context)
        drawn = {c[1]["property"] for c in op.layout.calls("prop")}
        self.assertEqual(drawn, {"display", "metric_unit", "us_unit", "system_value", "system_unit"})


class FreezeTest(unittest.TestCase):

    def setUp(self):
        clear_scene()
        self.freeze = mx_ui().freeze

    def test_freeze_and_unfreeze_restore_color(self):
        cube = add_cube()
        cube.color = (0.2, 0.4, 0.6, 1.0)
        self.assertEqual(self.freeze.freeze_objects([cube]), [cube])
        self.assertTrue(self.freeze.is_frozen(cube))
        self.assertTrue(cube.hide_select)
        self.assertFalse(cube.select_get())
        self.assertAlmostEqual(cube.color[0], self.freeze.FROZEN_GRAY[0], places=5)
        # Freezing twice keeps the original colour.
        self.assertEqual(self.freeze.freeze_objects([cube]), [])
        self.assertEqual(self.freeze.unfreeze_objects([cube]), [cube])
        self.assertFalse(self.freeze.is_frozen(cube))
        self.assertFalse(cube.hide_select)
        self.assertAlmostEqual(cube.color[1], 0.4, places=5)
        self.assertNotIn(self.freeze.COLOR_KEY, cube)

    def test_unfreeze_leaves_unselectable_objects_alone(self):
        cube = add_cube()
        cube.hide_select = True
        self.assertEqual(self.freeze.unfreeze_objects([cube]), [])
        self.assertTrue(cube.hide_select)

    def test_operators(self):
        a = add_cube("A")
        b = add_cube("B")
        a.select_set(True)
        b.select_set(False)
        self.assertEqual(bpy.ops.object.mx_freeze_selected(), {'FINISHED'})
        self.assertTrue(self.freeze.is_frozen(a))
        self.assertFalse(self.freeze.is_frozen(b))
        self.assertEqual(bpy.ops.object.mx_freeze_unselected(), {'FINISHED'})
        self.assertTrue(self.freeze.is_frozen(b))
        self.assertEqual(bpy.ops.object.mx_unfreeze_by_name(name="B"), {'FINISHED'})
        self.assertFalse(self.freeze.is_frozen(b))
        self.assertEqual(bpy.ops.object.mx_unfreeze_all(), {'FINISHED'})
        self.assertFalse(self.freeze.is_frozen(a))

    def test_frozen_gray_preference(self):
        prefs = bpy.context.preferences.addons[ADDON].preferences
        cube = add_cube()
        cube.color = (0.1, 0.9, 0.1, 1.0)
        prefs.frozen_in_gray = False
        try:
            bpy.ops.object.mx_freeze_selected()
        finally:
            prefs.frozen_in_gray = True
        self.assertAlmostEqual(cube.color[1], 0.9, places=5)
        bpy.ops.object.mx_unfreeze_all()
        self.assertAlmostEqual(cube.color[1], 0.9, places=5)

    def test_unhide_by_name(self):
        cube = add_cube()
        cube.hide_set(True)
        self.assertEqual(bpy.ops.object.mx_unhide_by_name(name=cube.name), {'FINISHED'})
        self.assertFalse(cube.hide_get())


class WireColorTest(unittest.TestCase):

    def setUp(self):
        clear_scene()
        self.wirecolor = mx_ui().wirecolor
        self.wirecolor.reset_known_objects()
        self.state = bpy.context.window_manager.mx_ui

    def new_object(self, name):
        obj = bpy.data.objects.new(name, bpy.data.meshes.new(name))
        bpy.context.scene.collection.objects.link(obj)
        bpy.context.view_layer.update()
        return obj

    def test_new_objects_get_a_color(self):
        obj = self.new_object("Fresh")
        self.assertNotEqual(tuple(obj.color), (1.0, 1.0, 1.0, 1.0))

    def test_name_and_color_rollout(self):
        self.state.next_name = "Hero"
        self.state.next_color = (0.25, 0.5, 0.75, 1.0)
        obj = self.new_object("Unnamed")
        self.assertEqual(obj.name, "Hero")
        self.assertAlmostEqual(obj.color[2], 0.75, places=5)
        self.assertEqual(self.state.next_name, "")

    def test_existing_and_colored_objects_untouched(self):
        cube = add_cube()
        self.wirecolor.reset_known_objects()
        cube.location.x = 1.0
        bpy.context.view_layer.update()
        self.assertEqual(tuple(cube.color), (1.0, 1.0, 1.0, 1.0))
        obj = bpy.data.objects.new("Colored", bpy.data.meshes.new("Colored"))
        obj.color = (0.0, 1.0, 0.0, 1.0)
        bpy.context.scene.collection.objects.link(obj)
        bpy.context.view_layer.update()
        self.assertEqual(tuple(obj.color), (0.0, 1.0, 0.0, 1.0))

    def test_preference_off(self):
        prefs = bpy.context.preferences.addons[ADDON].preferences
        self.state.next_color_initialized = False
        prefs.random_wire_colors = False
        try:
            obj = self.new_object("Plain")
        finally:
            prefs.random_wire_colors = True
        self.assertEqual(tuple(obj.color), (1.0, 1.0, 1.0, 1.0))


class ModifierMapTest(unittest.TestCase):

    def setUp(self):
        clear_scene()
        self.mm = mx_ui().modifier_map

    def test_table_consistent(self):
        keys = [entry.key for entry in self.mm.MODIFIERS]
        self.assertEqual(len(keys), len(set(keys)))
        categories = {cat for cat, _label in self.mm.CATEGORIES}
        modifier_types = {item.identifier for item in bpy.types.Modifier.bl_rna.properties["type"].enum_items}
        for entry in self.mm.MODIFIERS:
            with self.subTest(entry=entry.key):
                self.assertIn(entry.category, categories)
                self.assertNotIn("3ds", entry.label.lower())
                if entry.blender_type:
                    self.assertIn(entry.blender_type, modifier_types)
                if entry.setup:
                    self.assertTrue(callable(getattr(self.mm, entry.setup)))

    def test_every_entry_applies(self):
        for entry in self.mm.MODIFIERS:
            clear_scene()
            obj = add_curve() if 'MESH' not in entry.object_types else add_cube()
            with self.subTest(entry=entry.key):
                if not entry.available:
                    with self.assertRaises(self.mm.ModifierNotAvailable):
                        self.mm.add_modifier(bpy.context, obj, entry.key)
                    continue
                mod = self.mm.add_modifier(bpy.context, obj, entry.key)
                if entry.blender_type or entry.key == "SMOOTH":
                    self.assertIsNotNone(mod)
                    self.assertEqual(mod.name, entry.label)
                    if entry.blender_type:
                        self.assertEqual(mod.type, entry.blender_type)
                    for attr, value in entry.settings.items():
                        got = getattr(mod, attr)
                        if isinstance(value, float):
                            self.assertAlmostEqual(got, value, places=5)
                        elif isinstance(value, tuple):
                            self.assertEqual(tuple(got), value)
                        else:
                            self.assertEqual(got, value)
                    self.assertTrue(self.mm.parameter_names(mod))
                if obj.mode != 'OBJECT':
                    bpy.ops.object.mode_set(mode='OBJECT')

    def test_specific_mappings(self):
        cube = add_cube()
        mod = self.mm.add_modifier(bpy.context, cube, "TURBOSMOOTH")
        self.assertEqual((mod.type, mod.levels), ('SUBSURF', 1))
        mod = self.mm.add_modifier(bpy.context, cube, "SYMMETRY")
        self.assertEqual(tuple(mod.use_bisect_axis), (True, False, False))
        mod = self.mm.add_modifier(bpy.context, cube, "TWIST")
        self.assertEqual((mod.type, mod.deform_method), ('SIMPLE_DEFORM', 'TWIST'))
        mod = self.mm.add_modifier(bpy.context, cube, "NOISE")
        self.assertEqual(mod.type, 'DISPLACE')
        self.assertIsNotNone(mod.texture)
        self.assertEqual(mod.texture.type, 'CLOUDS')
        mod = self.mm.add_modifier(bpy.context, cube, "FFD_3")
        lattice = mod.object
        self.assertEqual(lattice.type, 'LATTICE')
        self.assertEqual((lattice.data.points_u, lattice.data.points_v, lattice.data.points_w), (3, 3, 3))
        self.assertEqual(lattice.parent, cube)
        self.assertAlmostEqual(lattice.scale.x, 2.0, places=4)
        mod = self.mm.add_modifier(bpy.context, cube, "NORMAL")
        self.assertEqual(mod.node_group.name, self.mm.FLIP_NORMALS_GROUP)
        mod = self.mm.add_modifier(bpy.context, cube, "SMOOTH")
        self.assertEqual(mod.type, 'NODES')
        self.assertEqual(mod.name, "Smooth")
        # The flip-normals group really flips: the evaluated cube's normals point inward.
        cube.modifiers.clear()
        self.mm.add_modifier(bpy.context, cube, "NORMAL")
        depsgraph = bpy.context.evaluated_depsgraph_get()
        mesh = cube.evaluated_get(depsgraph).to_mesh()
        face = mesh.polygons[0]
        self.assertLess(face.normal.dot(face.center), 0.0)
        cube.evaluated_get(depsgraph).to_mesh_clear()

    def test_edit_poly_enters_edit_mode(self):
        cube = add_cube()
        self.assertIsNone(self.mm.add_modifier(bpy.context, cube, "EDIT_POLY"))
        self.assertEqual(cube.mode, 'EDIT')
        bpy.ops.object.mode_set(mode='OBJECT')

    def test_wrong_object_type(self):
        curve = add_curve()
        with self.assertRaises(ValueError):
            self.mm.add_modifier(bpy.context, curve, "SHELL")

    def test_operator(self):
        add_cube()
        self.assertEqual(bpy.ops.object.mx_modifier_add(kind='SHELL'), {'FINISHED'})
        self.assertEqual(bpy.context.object.modifiers[-1].type, 'SOLIDIFY')
        self.assertEqual(bpy.ops.object.mx_modifier_add(kind='UVW_MAP'), {'CANCELLED'})


class StackTest(unittest.TestCase):

    def setUp(self):
        clear_scene()
        self.mm = mx_ui().modifier_map
        from mx_ui.command_panel import modify
        self.modify = modify
        self.cube = add_cube()
        self.mm.add_modifier(bpy.context, self.cube, "BEND")
        self.mm.add_modifier(bpy.context, self.cube, "TURBOSMOOTH")
        self.mm.add_modifier(bpy.context, self.cube, "SHELL")

    def test_select_entries(self):
        bpy.ops.object.mx_stack_select(index=0)
        self.assertEqual(self.modify.selected_modifier(bpy.context, self.cube).name, "Bend")
        bpy.ops.object.mx_stack_select(index=-1)
        self.assertIsNone(self.modify.selected_modifier(bpy.context, self.cube))

    def test_remove(self):
        bpy.ops.object.mx_stack_select(index=1)
        self.assertEqual(bpy.ops.object.mx_stack_remove(), {'FINISHED'})
        self.assertEqual([m.name for m in self.cube.modifiers], ["Bend", "Shell"])

    def test_show_end_result(self):
        bpy.ops.object.mx_stack_select(index=0)
        bpy.ops.object.mx_show_end_result()
        self.assertEqual([m.show_viewport for m in self.cube.modifiers], [True, False, False])
        bpy.ops.object.mx_show_end_result()
        self.assertEqual([m.show_viewport for m in self.cube.modifiers], [True, True, True])

    def test_collapse(self):
        verts_before = len(self.cube.data.vertices)
        self.assertEqual(bpy.ops.object.mx_collapse_stack(), {'FINISHED'})
        self.assertEqual(len(self.cube.modifiers), 0)
        self.assertGreater(len(self.cube.data.vertices), verts_before)


class UnitsTest(unittest.TestCase):

    def setUp(self):
        self.units = mx_ui().units
        self.settings = bpy.context.scene.unit_settings
        self.saved = (self.settings.system, self.settings.length_unit, self.settings.scale_length)

    def tearDown(self):
        self.settings.system = self.saved[0]
        self.settings.length_unit = self.saved[1]
        self.settings.scale_length = self.saved[2]

    def test_metric_centimeters(self):
        self.units.apply_units(self.settings, 'METRIC', metric_unit='CENTIMETERS',
                               system_value=1.0, system_unit='CENTIMETERS')
        self.assertEqual(self.settings.system, 'METRIC')
        self.assertEqual(self.settings.length_unit, 'CENTIMETERS')
        self.assertAlmostEqual(self.settings.scale_length, 0.01)
        values = self.units.read_units(self.settings)
        self.assertEqual((values["display"], values["metric_unit"], values["system_unit"]),
                         ('METRIC', 'CENTIMETERS', 'CENTIMETERS'))
        self.assertAlmostEqual(values["system_value"], 1.0)

    def test_us_standard_inches(self):
        self.units.apply_units(self.settings, 'US', us_unit='FEET_INCHES', system_value=1.0, system_unit='INCHES')
        self.assertEqual((self.settings.system, self.settings.length_unit), ('IMPERIAL', 'ADAPTIVE'))
        self.assertAlmostEqual(self.settings.scale_length, 0.0254)
        values = self.units.read_units(self.settings)
        self.assertEqual((values["display"], values["us_unit"], values["system_unit"]),
                         ('US', 'FEET_INCHES', 'INCHES'))

    def test_generic_and_odd_scale(self):
        self.units.apply_units(self.settings, 'GENERIC', system_value=2.5, system_unit='METERS')
        self.assertEqual(self.settings.system, 'NONE')
        values = self.units.read_units(self.settings)
        self.assertEqual(values["display"], 'GENERIC')
        self.assertAlmostEqual(values["system_value"], 2.5)

    def test_invalid(self):
        with self.assertRaises(ValueError):
            self.units.apply_units(self.settings, 'METRIC', system_value=0.0)

    def test_operator(self):
        self.assertEqual(bpy.ops.scene.mx_units_setup(display='METRIC', metric_unit='MILLIMETERS',
                                                      system_value=1.0, system_unit='MILLIMETERS'), {'FINISHED'})
        self.assertEqual(self.settings.length_unit, 'MILLIMETERS')
        self.assertAlmostEqual(self.settings.scale_length, 0.001)


class ThemeTest(unittest.TestCase):

    def tearDown(self):
        bpy.ops.preferences.reset_default_theme()

    def test_xml_parses_and_is_complete(self):
        theme_mod = mx_ui().theme
        doc = xml.dom.minidom.parse(theme_mod.THEME_PATH)
        root = doc.getElementsByTagName("bpy")[0]
        self.assertTrue(root.getElementsByTagName("Theme"))
        self.assertTrue(root.getElementsByTagName("ThemeStyle"))
        for tag in ("ThemeUserInterface", "ThemeView3D", "ThemeOutliner", "ThemeProperties",
                    "ThemeNodeEditor", "ThemeImageEditor", "ThemeTextEditor"):
            with self.subTest(tag=tag):
                self.assertTrue(root.getElementsByTagName(tag))

    def test_apply(self):
        theme = bpy.context.preferences.themes[0]
        default_vertex_select = tuple(theme.view_3d.vertex_select)
        default_back = tuple(theme.properties.space.back)
        self.assertEqual(bpy.ops.preferences.mx_apply_theme(), {'FINISHED'})
        palette = sys.modules["mx_ui.theme.palette"]
        self.assertNotEqual(tuple(theme.view_3d.vertex_select), default_vertex_select)
        for got, want in zip(theme.view_3d.vertex_select, palette.OVERRIDES["view_3d.vertex_select"]):
            self.assertAlmostEqual(got, want, delta=1.0 / 255.0 + 1e-6)
        # Neutral grays are lifted.
        self.assertGreater(theme.properties.space.back[0], default_back[0])
        self.assertTrue(theme.properties.space.back[0] < 0.4)

    def test_palette_functions(self):
        palette = sys.modules.get("mx_ui.theme.palette")
        if palette is None:
            from mx_ui.theme import palette
        self.assertEqual(palette.adjust_color("view_3d.vertex", (0.0, 0.0, 0.0)), (0.0, 0.0, 0.0))
        lifted = palette.adjust_color("properties.space.back", (0.2, 0.2, 0.2))
        self.assertGreater(lifted[0], 0.2)
        self.assertEqual(palette.adjust_color("user_interface.wcol_regular.inner_sel", palette.DEFAULT_ACCENT),
                         palette.ACCENT)
        self.assertEqual(palette.adjust_color("properties.space.back", (1.0, 0.0, 0.0)), (1.0, 0.0, 0.0))


class LayoutTest(unittest.TestCase):

    def setUp(self):
        self.layout = mx_ui().layout
        self.screen = bpy.context.window.screen

    def view3d_areas(self):
        return [a for a in self.screen.areas if a.type == 'VIEW_3D']

    def test_configure_viewports(self):
        space = self.view3d_areas()[0].spaces.active
        for role, (axis, shading) in self.layout.VIEWPORTS.items():
            with self.subTest(role=role):
                self.layout.configure_view3d(space, role)
                self.assertEqual(space.shading.type, shading)
                self.assertEqual(space.shading.color_type, 'OBJECT')
                rv3d = space.region_3d
                if axis is None:
                    self.assertEqual(rv3d.view_perspective, 'PERSP')
                else:
                    self.assertEqual(rv3d.view_perspective, 'ORTHO')
                    self.assertTrue(rv3d.is_orthographic_side_view)
        # Top looks straight down.
        self.layout.configure_view3d(space, 'TOP')
        view_dir = space.region_3d.view_rotation @ __import__("mathutils").Vector((0.0, 0.0, -1.0))
        self.assertAlmostEqual(view_dir.z, -1.0, places=4)
        # Left looks along +X (from the left side).
        self.layout.configure_view3d(space, 'LEFT')
        view_dir = space.region_3d.view_rotation @ __import__("mathutils").Vector((0.0, 0.0, -1.0))
        self.assertAlmostEqual(view_dir.x, 1.0, places=4)

    def test_configure_editors(self):
        from mx_ui import command_panel
        props = [a for a in self.screen.areas if a.type == 'PROPERTIES'][0].spaces.active
        self.layout.configure_command_panel(props)
        self.assertEqual(props.context, 'TOOL')
        self.assertTrue(command_panel.is_command_panel_space(props))
        outliner = [a for a in self.screen.areas if a.type == 'OUTLINER'][0].spaces.active
        self.layout.configure_outliner(outliner)
        self.assertEqual(outliner.display_mode, 'VIEW_LAYER')
        self.assertTrue(outliner.show_restrict_column_select)

    def test_split_steps(self):
        window = bpy.context.window
        area = self.view3d_areas()[0]
        before = list(self.screen.areas)
        steps = self.layout.split_steps(window, self.screen, area)
        for _step in range(4):
            next(steps)
        new_areas = [a for a in self.screen.areas if a not in before]
        self.assertEqual(sorted(a.type for a in new_areas), ['OUTLINER', 'PROPERTIES', 'VIEW_3D', 'VIEW_3D'])
        try:
            next(steps)
        except RuntimeError:
            # The last split divides an area created by a split: headless, its size is never computed
            # (no event loop), so Blender refuses. In a window the event loop runs between steps.
            return
        except StopIteration as ex:
            roles = ex.value
        else:
            self.fail("split_steps has more steps than expected")
        self.layout.configure_areas(window, self.screen, roles)
        self.assertEqual(len({a.as_pointer() for a in roles.values()}), 6)
        self.assertEqual(roles['EXPLORER'].type, 'OUTLINER')
        self.assertEqual(roles['COMMAND_PANEL'].type, 'PROPERTIES')
        self.assertEqual(roles['TOP'].spaces.active.shading.type, 'WIREFRAME')
        self.assertEqual(roles['PERSPECTIVE'].spaces.active.shading.type, 'SOLID')

    def test_operator_creates_workspace(self):
        self.assertEqual(bpy.ops.screen.mx_max_layout(), {'FINISHED'})
        self.assertIn(self.layout.WORKSPACE_NAME, bpy.data.workspaces)
        count = len(bpy.data.workspaces)
        self.assertEqual(bpy.ops.screen.mx_max_layout(), {'FINISHED'})
        self.assertEqual(len(bpy.data.workspaces), count)


class CreateTest(unittest.TestCase):

    def setUp(self):
        clear_scene()
        from mx_ui.command_panel import create
        self.create = create

    def test_objects(self):
        for kind, label, base, _group, available in self.create.OBJECTS:
            with self.subTest(kind=kind):
                if not available:
                    self.assertEqual(bpy.ops.object.mx_create(kind=kind), {'CANCELLED'})
                    continue
                self.assertEqual(bpy.ops.object.mx_create(kind=kind), {'FINISHED'})
                if kind == 'SKYLIGHT':
                    continue
                obj = bpy.context.view_layer.objects.active
                self.assertTrue(obj.name.startswith(base), obj.name)
                self.assertRegex(obj.name, r"\d{3}$")
        omni = bpy.data.objects["Omni001"]
        self.assertEqual(omni.data.type, 'POINT')
        spot = [o for o in bpy.data.objects if o.name.startswith("Spot") and o.type == 'LIGHT'][0]
        self.assertEqual(spot.data.type, 'SPOT')
        camera = bpy.data.objects["Camera001"]
        self.assertEqual(camera.constraints[0].type, 'TRACK_TO')
        self.assertEqual(camera.constraints[0].target.name, "Camera001.Target")
        self.assertEqual(bpy.data.objects["Dummy001"].empty_display_type, 'CUBE')

    def test_shapes(self):
        for kind, label in self.create.SHAPES:
            with self.subTest(kind=kind):
                self.assertEqual(bpy.ops.curve.mx_shape_add(kind=kind), {'FINISHED'})
                obj = bpy.context.view_layer.objects.active
                self.assertEqual(obj.name, label.replace(" ", "") + "001")
                if kind != 'TEXT':
                    self.assertTrue(obj.data.splines)
        self.assertEqual(len(bpy.data.objects["Donut001"].data.splines), 2)
        self.assertEqual(len(bpy.data.objects["Rectangle001"].data.splines[0].points), 4)

    def test_max_style_names(self):
        utils = mx_ui().utils
        self.assertEqual(utils.max_style_name("Box", []), "Box001")
        self.assertEqual(utils.max_style_name("Box", ["Box001", "Box003", "Boxer001"]), "Box002")


class HierarchyAndUtilitiesTest(unittest.TestCase):

    def setUp(self):
        clear_scene()
        self.cube = add_cube()

    def test_center_to_object(self):
        for v in self.cube.data.vertices:
            v.co.x += 3.0
        self.assertEqual(bpy.ops.object.mx_pivot(action='CENTER_TO_OBJECT'), {'FINISHED'})
        self.assertAlmostEqual(self.cube.location.x, 3.0, places=4)

    def test_align_to_world_and_reset_xform(self):
        self.cube.rotation_euler.z = math.radians(30.0)
        self.cube.scale = (2.0, 1.0, 1.0)
        bpy.ops.object.mx_pivot(action='ALIGN_TO_WORLD')
        self.assertAlmostEqual(self.cube.rotation_euler.z, 0.0, places=5)
        self.assertAlmostEqual(self.cube.scale.x, 2.0, places=5)
        bpy.ops.object.mx_reset_xform()
        self.assertAlmostEqual(self.cube.scale.x, 1.0, places=5)

    def test_measure(self):
        bpy.ops.object.mx_measure()
        state = bpy.context.window_manager.mx_ui
        self.assertAlmostEqual(state.measure_area, 24.0, places=3)
        self.assertAlmostEqual(state.measure_volume, 8.0, places=3)

    def test_subobject_levels(self):
        bpy.ops.object.mx_ui_subobject_level(level='EDGE')
        self.assertEqual(self.cube.mode, 'EDIT')
        self.assertEqual(tuple(bpy.context.tool_settings.mesh_select_mode), (False, True, False))
        bpy.ops.object.mx_ui_subobject_level(level='ELEMENT')
        self.assertEqual(tuple(bpy.context.tool_settings.mesh_select_mode), (False, False, True))
        bpy.ops.object.mx_ui_subobject_level(level='TOP')
        self.assertEqual(self.cube.mode, 'OBJECT')

    def test_display_toggles(self):
        bpy.ops.object.mx_display_toggle(property='BOX')
        self.assertEqual(self.cube.display_type, 'BOUNDS')
        bpy.ops.object.mx_display_toggle(property='BOX')
        self.assertEqual(self.cube.display_type, 'TEXTURED')
        bpy.ops.object.mx_display_toggle(property='SEE_THROUGH')
        self.assertLess(self.cube.color[3], 1.0)

    def test_attach(self):
        other = add_cube("Other")
        self.cube.select_set(True)
        bpy.context.view_layer.objects.active = self.cube
        self.assertEqual(bpy.ops.object.mx_attach(), {'FINISHED'})
        self.assertNotIn("Other", bpy.data.objects)
        self.assertEqual(len(self.cube.data.vertices), 16)
        del other


class LayersAndGroupsTest(unittest.TestCase):

    def setUp(self):
        clear_scene()

    def test_new_layer_from_selection(self):
        cube = add_cube()
        self.assertEqual(bpy.ops.object.mx_new_layer_from_selection(), {'FINISHED'})
        self.assertEqual([c.name for c in cube.users_collection], ["Layer001"])
        self.assertEqual(bpy.context.view_layer.active_layer_collection.name, "Layer001")
        other = add_cube("Other")
        bpy.context.view_layer.active_layer_collection = bpy.context.view_layer.layer_collection
        self.assertEqual(bpy.ops.object.mx_add_to_current_layer(), {'FINISHED'})
        self.assertEqual(other.users_collection[0], bpy.context.scene.collection)

    def test_group_ungroup(self):
        a = add_cube("A")
        a.location = (2.0, 0.0, 0.0)
        b = add_cube("B")
        b.location = (-2.0, 0.0, 0.0)
        a.select_set(True)
        bpy.context.view_layer.update()
        groups = mx_ui().groups
        head = groups.make_group(bpy.context, [a, b], "Group001")
        bpy.context.view_layer.update()
        self.assertTrue(groups.is_group(head))
        self.assertEqual({a.parent, b.parent}, {head})
        self.assertAlmostEqual(a.matrix_world.translation.x, 2.0, places=5)
        groups.ungroup(head)
        bpy.context.view_layer.update()
        self.assertIsNone(a.parent)
        self.assertAlmostEqual(a.matrix_world.translation.x, 2.0, places=5)


class SiblingAddonsTest(unittest.TestCase):
    """With ``mx_keymap`` and ``mx_primitives`` enabled, their operators and API are used."""

    @classmethod
    def setUpClass(cls):
        cls.enabled = []
        for name in ("mx_keymap", "mx_primitives"):
            if name in _runner_util.project_addons():
                enable(name)
                cls.enabled.append(name)

    @classmethod
    def tearDownClass(cls):
        for name in reversed(cls.enabled):
            addon_utils.disable(name, default_set=True)

    def setUp(self):
        if len(self.enabled) != 2:
            self.skipTest("mx_keymap and mx_primitives are needed")
        clear_scene()

    def add_box(self):
        self.assertEqual(bpy.ops.mesh.mx_primitive_add(kind='BOX'), {'FINISHED'})
        return bpy.context.view_layer.objects.active

    def test_quad_menu_uses_keymap_operators(self):
        add_cube()
        menu = types.SimpleNamespace(layout=new_layout())
        mx_ui().quad_menu.VIEW3D_MT_mx_quad.draw(menu, fake_context(mode='OBJECT'))
        ops = {c[1]["operator"] for c in menu.layout.calls("operator")}
        self.assertIn("mx_keymap.subobject_level", ops)
        self.assertIn("mx_keymap.clone", ops)
        self.assertNotIn("object.mx_ui_subobject_level", ops)

    def test_create_and_modify_live_primitive(self):
        from mx_ui.command_panel import create, modify
        layout = new_layout()
        bpy.context.window_manager.mx_ui.create_category = 'GEOMETRY'
        create.draw(layout, fake_context())
        kinds = [c for c in layout.calls("operator") if c[1]["operator"] == "object.mx_create_type"]
        # The Standard Primitives plus TextPlus.
        self.assertEqual(len(kinds), len(create.PRIMITIVES) + 1)
        box = self.add_box()
        self.assertTrue(mx_ui().utils.is_live_primitive(box))
        self.assertEqual(modify.base_label(box), "Box")
        layout = new_layout()
        modify.draw(layout, fake_context(active_object=box, object=box))
        # The base entry is selected and shows the primitive's own parameters.
        self.assertTrue(any(c[1].get("property") == "length" for c in layout.calls("prop")))

    def test_convert_menu_and_collapse(self):
        box = self.add_box()
        menu = types.SimpleNamespace(layout=new_layout())
        mx_ui().quad_menu.VIEW3D_MT_mx_quad_convert.draw(menu, fake_context(active_object=box))
        ops = [c[1]["operator"] for c in menu.layout.calls("operator")]
        self.assertEqual(ops[0], "object.mx_convert_to_editable_poly")
        mx_ui().modifier_map.add_modifier(bpy.context, box, "TURBOSMOOTH")
        self.assertEqual(bpy.ops.object.mx_collapse_stack(), {'FINISHED'})
        self.assertFalse(mx_ui().utils.is_live_primitive(box))
        self.assertEqual(len(box.modifiers), 0)

    def test_name_and_color_apply_to_primitives(self):
        state = bpy.context.window_manager.mx_ui
        mx_ui().wirecolor.reset_known_objects()
        state.next_name = "Crate"
        state.next_color = (0.1, 0.2, 0.3, 1.0)
        box = self.add_box()
        bpy.context.view_layer.update()
        self.assertEqual(box.name, "Crate")
        self.assertAlmostEqual(box.color[2], 0.3, places=5)


class KeymapTest(unittest.TestCase):

    def test_binding_choice(self):
        prefs_mod = mx_ui().prefs
        prefs = bpy.context.preferences.addons[ADDON].preferences
        self.assertTrue(prefs_mod.quad_binding_wanted(types.SimpleNamespace(quad_menu_binding='ALWAYS')))
        self.assertFalse(prefs_mod.quad_binding_wanted(types.SimpleNamespace(quad_menu_binding='NEVER')))
        self.assertEqual(prefs_mod.quad_binding_wanted(prefs), not prefs_mod.max_keyconfig_active())


class PlaceholderTest(unittest.TestCase):

    def test_placeholder(self):
        self.assertEqual(bpy.ops.mx_ui.placeholder(feature="Teapot"), {'FINISHED'})
        from mx_ui import placeholder
        layout = new_layout()
        placeholder.placeholder(layout, "Civil View")
        self.assertEqual(layout.calls("operator")[0][1]["operator"], "mx_ui.placeholder")


if __name__ == "__main__":
    _runner_util.main()

