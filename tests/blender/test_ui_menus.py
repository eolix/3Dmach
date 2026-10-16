# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
``mx_ui`` menu bar and main toolbar: registration, the top bar override (and its restoration), every menu and
the toolbar drawn into a recording layout that checks operator, property, menu and icon names against
Blender's RNA (with and without the sibling add-ons), the Reference Coordinate System mapping, flyouts, snap
toggles and Mirror.
"""

import json
import os
import sys
import types
import unittest

import addon_utils
import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _runner_util

ADDON = "mx_ui"
SIBLINGS = ("mx_keymap", "mx_primitives", "mx_io_max")


def enable(name):
    errors = []
    mod = addon_utils.enable(name, default_set=True, handle_error=lambda ex: errors.append(ex))
    if errors:
        raise errors[0]
    if mod is None:
        raise RuntimeError("add-on {!r} could not be enabled".format(name))
    return mod


def disable(name):
    addon_utils.disable(name, default_set=True)


def setUpModule():
    enable(ADDON)


def tearDownModule():
    for name in (ADDON, *SIBLINGS):
        disable(name)


def chrome(name):
    return sys.modules["{:s}.chrome.{:s}".format(ADDON, name)]


def prefs():
    return bpy.context.preferences.addons[ADDON].preferences


# -----------------------------------------------------------------------------
# Recording layout (as in `test_ui.py`, plus menus defined in C and operator property checks after drawing)

_UILAYOUT = bpy.types.UILayout.bl_rna
_LAYOUT_ATTRS = {prop.identifier for prop in _UILAYOUT.properties}
_ICONS = {item.identifier for item in _UILAYOUT.functions["label"].parameters["icon"].enum_items}
_SUBLAYOUTS = {"row", "column", "box", "split", "grid_flow", "column_flow", "menu_pie"}
_PROP_FUNCS = {"prop", "prop_menu_enum", "prop_enum", "props_enum", "prop_search", "prop_with_popover",
               "prop_with_menu", "prop_tabs_enum", "prop_decorator"}
_OPERATOR_FUNCS = {"operator", "operator_menu_enum", "operator_enum", "operator_menu_hold"}

# Menus defined in C, so not in `bpy.types`.
_C_MENUS = {"TOPBAR_MT_file_open_recent", "TOPBAR_MT_undo_history"}


class LayoutError(AssertionError):
    pass


def _operator_rna(idname):
    category, _, name = idname.partition(".")
    try:
        return getattr(getattr(bpy.ops, category), name).get_rna_type()
    except (AttributeError, KeyError) as ex:
        raise LayoutError("unknown operator {!r}".format(idname)) from ex


def _check_menu(name):
    if name not in _C_MENUS and not hasattr(bpy.types, name):
        raise LayoutError("unknown menu {!r}".format(name))


def _check_prop(data, prop_name, where):
    if data is None:
        raise LayoutError("{:s}: data is None for {!r}".format(where, prop_name))
    props = data.bl_rna.properties
    if prop_name not in props:
        raise LayoutError("{:s}: {:s} has no property {!r}".format(where, data.bl_rna.identifier, prop_name))
    return props[prop_name]


def _check_enum_value(prop, value, where):
    if prop.type == 'ENUM' and not prop.is_enum_flag and prop.enum_items:
        if value not in {item.identifier for item in prop.enum_items}:
            raise LayoutError("{:s}: {!r} is not a valid {:s}".format(where, value, prop.identifier))


class OperatorProps:
    """Stands in for the operator properties returned by ``layout.operator()``."""

    def __init__(self, idname, rna):
        object.__setattr__(self, "idname", idname)
        object.__setattr__(self, "values", {})
        object.__setattr__(self, "_rna", rna)

    def __setattr__(self, name, value):
        props = self._rna.properties
        if name not in props:
            raise LayoutError("operator {!r} has no property {!r}".format(self.idname, name))
        _check_enum_value(props[name], value, "operator {!r}".format(self.idname))
        self.values[name] = value


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
        result = self._result(name, bound)
        self._log.append((name, bound, result))
        return result

    def _result(self, name, bound):
        icon = bound.get("icon")
        if icon is not None and icon not in _ICONS:
            raise LayoutError("unknown icon {!r} in {:s}()".format(icon, name))
        if name in _SUBLAYOUTS:
            return RecordingLayout(self._log)
        if name in _PROP_FUNCS:
            prop = _check_prop(bound.get("data"), bound.get("property"), name)
            if name == "prop_enum":
                _check_enum_value(prop, bound["value"], name)
            return None
        if name in _OPERATOR_FUNCS:
            idname = bound["operator"]
            if name == "operator_menu_hold":
                _check_menu(bound["menu"])
            return OperatorProps(idname, _operator_rna(idname))
        if name in {"menu", "menu_contents"}:
            _check_menu(bound["menu"])
        if name == "popover" and not hasattr(bpy.types, bound["panel"]):
            raise LayoutError("unknown panel {!r}".format(bound["panel"]))
        return None

    def calls(self, name=None):
        return [c for c in self._log if name is None or c[0] == name]

    def operators(self, idname=None):
        return [c[2] for c in self._log if c[0] in _OPERATOR_FUNCS and (idname is None or c[2].idname == idname)]


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
        "tool_settings": ctx.scene.tool_settings,
        "workspace": ctx.workspace,
        "mode": ctx.mode,
        "window": ctx.window,
        "screen": ctx.screen,
        "area": types.SimpleNamespace(show_menus=True, type='TOPBAR'),
        "region": types.SimpleNamespace(alignment='LEFT'),
    }
    values.update(overrides)
    return types.SimpleNamespace(**values)


def view3d_space():
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                return area.spaces.active
    return None


def check_indirect_operators(test, layout, context):
    """Validate operator names and properties carried as data by the indirect operators."""
    for op in layout.operators("mx_ui.viewport_call"):
        rna = _operator_rna(op.values["operator"])
        for key, value in json.loads(op.values.get("properties") or "{}").items():
            test.assertIn(key, rna.properties, op.values["operator"])
            _check_enum_value(rna.properties[key], value, op.values["operator"])
    for op in layout.operators("mx_ui.viewport_toggle"):
        test.assertIsNotNone(view3d_space().path_resolve(op.values["path"]))
    for op in layout.operators("mx_ui.toolbar_flyout"):
        test.assertIsNotNone(chrome("main_toolbar")._variant(op.values["flyout"], op.values["variant"]))
    for op in layout.operators("wm.context_set_enum") + layout.operators("wm.context_set_boolean"):
        owner_path, _, prop_name = op.values["data_path"].rpartition(".")
        owner = context
        for part in owner_path.split("."):
            owner = getattr(owner, part)
        prop = _check_prop(owner, prop_name, op.values["data_path"])
        _check_enum_value(prop, op.values["value"], op.values["data_path"])
    for op in layout.operators("wm.tool_set_by_id"):
        test.assertTrue(op.values["name"].startswith("builtin."), op.values["name"])
        test.assertEqual(op.values.get("space_type"), 'VIEW_3D')
    for op in layout.operators("mx_ui.set_tool"):
        test.assertTrue(op.values["name"].startswith("builtin."), op.values["name"])


# -----------------------------------------------------------------------------
# Scene helpers

def clear_scene():
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)


def add_cube(name="Box001", location=(0.0, 0.0, 0.0)):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(
        [(x, y, z) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)],
        [],
        [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)],
    )
    obj = bpy.data.objects.new(name, mesh)
    obj.location = location
    bpy.context.scene.collection.objects.link(obj)
    for other in bpy.context.scene.objects:
        other.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.context.view_layer.update()
    return obj


# -----------------------------------------------------------------------------
# Tests

class RegistrationTest(unittest.TestCase):

    def test_menus_registered(self):
        menubar = chrome("menubar")
        self.assertEqual(len(menubar.MENUBAR), 16)
        for idname in menubar.MENUS:
            with self.subTest(menu=idname):
                self.assertTrue(hasattr(bpy.types, idname))
        # Names kept from the earlier top bar menus.
        for idname in ("TOPBAR_MT_mx_create", "TOPBAR_MT_mx_modifiers", "TOPBAR_MT_mx_group"):
            self.assertIn(idname, menubar.MENUS)

    def test_menubar_labels(self):
        menubar = chrome("menubar")
        labels = [menubar.MENUS[idname][0] for idname in menubar.MENUBAR]
        self.assertEqual(labels, [
            "File", "Edit", "Tools", "Group", "Views", "Create", "Modifiers", "Animation", "Graph Editors",
            "Rendering", "Civil View", "Customize", "Scripting", "Interactive", "Content", "Help",
        ])

    def test_operators_registered(self):
        for idname in ("mx_ui.viewport_call", "mx_ui.viewport_toggle", "mx_ui.isolate_selection",
                       "mx_ui.open_editor_window", "mx_ui.run_script", "mx_ui.active_shade", "mx_ui.redraw_views",
                       "mx_ui.toolbar_flyout", "mx_ui.snap_toggle", "mx_ui.set_tool", "object.mx_mirror",
                       "object.mx_camera_from_view"):
            with self.subTest(idname=idname):
                _operator_rna(idname)

    def test_state_properties(self):
        state = bpy.context.window_manager.mx_ui
        self.assertEqual(state.selection_filter, 'ALL')
        state.selection_filter = 'LIGHTS'
        self.assertEqual(state.selection_filter, 'LIGHTS')
        state.selection_filter = 'ALL'
        self.assertIsInstance(state.select_crossing, bool)

    def test_no_topbar_module(self):
        self.assertNotIn(ADDON + ".topbar", sys.modules)


class OverrideTest(unittest.TestCase):

    def tearDown(self):
        prefs().use_max_chrome = True
        if ADDON not in bpy.context.preferences.addons:
            enable(ADDON)

    def draw_editor_menus(self):
        holder = types.SimpleNamespace(layout=new_layout())
        bpy.types.TOPBAR_MT_editor_menus.draw(holder, fake_context())
        return [c[1]["menu"] for c in holder.layout.calls("menu")]

    def draw_upper_bar(self, attr):
        holder = types.SimpleNamespace(layout=new_layout())
        screen = types.SimpleNamespace(show_fullscreen=False, show_statusbar=True)
        getattr(bpy.types.TOPBAR_HT_upper_bar, attr)(holder, fake_context(screen=screen))
        return holder.layout

    def test_menubar_replaces_blender_menus(self):
        menubar = chrome("menubar")
        self.assertTrue(menubar.overridden())
        self.assertEqual(self.draw_editor_menus(), list(menubar.MENUBAR))

    def test_pref_off_draws_blender(self):
        prefs().use_max_chrome = False
        menus = self.draw_editor_menus()
        self.assertIn("TOPBAR_MT_file", menus)
        self.assertNotIn("TOPBAR_MT_mx_file", menus)
        self.assertTrue(self.draw_upper_bar("draw_left").calls("template_ID_tabs"))
        self.assertTrue(self.draw_upper_bar("draw_right").calls("template_ID"))

    def test_workspace_tabs_hidden(self):
        layout = self.draw_upper_bar("draw_left")
        self.assertFalse(layout.calls("template_ID_tabs"))
        self.assertTrue(layout.calls("menu_contents"))
        self.assertFalse(self.draw_upper_bar("draw_right").calls("template_ID"))

    def test_restored_on_unregister(self):
        disable(ADDON)
        try:
            self.assertEqual(bpy.types.TOPBAR_MT_editor_menus.draw.__module__, "bl_ui.space_topbar")
            self.assertEqual(bpy.types.TOPBAR_HT_upper_bar.draw_left.__module__, "bl_ui.space_topbar")
            self.assertEqual(bpy.types.TOPBAR_HT_upper_bar.draw_right.__module__, "bl_ui.space_topbar")
            self.assertFalse(hasattr(bpy.types, "TOPBAR_MT_mx_file"))
        finally:
            enable(ADDON)
        self.assertEqual(bpy.types.TOPBAR_MT_editor_menus.draw.__module__, ADDON + ".chrome.menubar")
        # Enabling twice must not lose Blender's functions.
        self.assertEqual(chrome("menubar")._originals["editor_menus"].__module__, "bl_ui.space_topbar")


class MenuDrawTest(unittest.TestCase):

    def setUp(self):
        clear_scene()
        self.cube = add_cube()

    def tearDown(self):
        clear_scene()

    def draw_all(self, context):
        menubar = chrome("menubar")
        total = new_layout()
        for idname in menubar.MENUS:
            with self.subTest(menu=idname, mode=context.mode):
                cls = getattr(bpy.types, idname)
                holder = types.SimpleNamespace(layout=new_layout())
                cls.draw(holder, context)
                self.assertTrue(holder.layout.calls(), idname)
                check_indirect_operators(self, holder.layout, context)
                total._log.extend(holder.layout._log)
        return total

    def test_draw_with_siblings(self):
        for name in SIBLINGS:
            enable(name)
        try:
            layout = self.draw_all(fake_context(active_object=self.cube, object=self.cube))
            features = {op.values.get("feature") for op in layout.operators("mx_ui.placeholder")}
            self.assertNotIn("Box", features)
            kinds = {op.values.get("kind") for op in layout.operators("mesh.mx_primitive_add")}
            self.assertTrue({'BOX', 'SPHERE', 'PLANE'} <= kinds)
            self.assertTrue(layout.operators("mx_keymap.clone"))
            self.assertTrue(layout.operators("import_scene.mx_max"))
            self.draw_all(fake_context(active_object=self.cube, object=self.cube, mode='EDIT_MESH'))
        finally:
            for name in SIBLINGS:
                disable(name)

    def test_draw_standalone(self):
        layout = self.draw_all(fake_context(active_object=self.cube, object=self.cube))
        features = {op.values.get("feature") for op in layout.operators("mx_ui.placeholder")}
        self.assertIn("Box", features)
        self.assertFalse(layout.operators("mx_keymap.clone"))
        self.assertTrue(layout.operators("object.duplicate"))
        self.draw_all(fake_context(active_object=None, object=None, selected_objects=[]))

    def test_mode_dependent_entries(self):
        menubar = chrome("menubar")
        holder = types.SimpleNamespace(layout=new_layout())
        getattr(bpy.types, menubar.EDIT).draw(holder, fake_context(mode='EDIT_MESH'))
        self.assertTrue(holder.layout.operators("mesh.select_all"))
        self.assertTrue(holder.layout.operators("mesh.delete"))
        holder = types.SimpleNamespace(layout=new_layout())
        getattr(bpy.types, menubar.EDIT).draw(holder, fake_context(mode='OBJECT'))
        self.assertTrue(holder.layout.operators("object.select_all"))
        self.assertTrue(holder.layout.operators("object.delete"))

    def test_every_modifier_reachable(self):
        menubar = chrome("menubar")
        modifier_map = sys.modules[ADDON + ".modifier_map"]
        listed = set()
        for _label, items in menubar.MENUS.values():
            for item in items:
                if isinstance(item, menubar.Mod):
                    entry = menubar.modifier_entry(item.text)
                    if entry is not None:
                        listed.add(entry.key)
        self.assertEqual({entry.key for entry in modifier_map.MODIFIERS} - listed, set())

    def test_submenus_exist(self):
        menubar = chrome("menubar")
        for idname, (_label, items) in menubar.MENUS.items():
            for item in items:
                if isinstance(item, menubar.Sub):
                    with self.subTest(menu=idname, submenu=item.menu):
                        _check_menu(item.menu)

    def test_no_product_names(self):
        menubar = chrome("menubar")
        for _label, items in menubar.MENUS.values():
            for item in items:
                text = getattr(item, "text", "") or ""
                for word in ("3ds", "Autodesk", "Arnold", "Revit", "AutoCAD", "Maya"):
                    self.assertNotIn(word, text)


class ToolbarTest(unittest.TestCase):

    def setUp(self):
        clear_scene()
        self.cube = add_cube()
        self.toolbar = chrome("main_toolbar")
        self._active_tool = self.toolbar.active_tool_id

    def tearDown(self):
        self.toolbar.active_tool_id = self._active_tool
        self.toolbar._chosen.clear()
        clear_scene()

    def draw(self, **overrides):
        layout = new_layout()
        context = fake_context(active_object=self.cube, object=self.cube, **overrides)
        self.toolbar.draw_main_toolbar(layout, context)
        check_indirect_operators(self, layout, context)
        return layout

    def test_draw(self):
        layout = self.draw()
        self.assertGreaterEqual(len(layout.operators()), 30)
        self.assertEqual(len(layout.calls("operator_menu_hold")), 9)
        self.assertEqual({c[1]["property"] for c in layout.calls("prop")},
                         {"selection_filter", "select_crossing", "ref_coord_sys", "named_selection_set"})

    def test_draw_with_siblings(self):
        for name in SIBLINGS:
            enable(name)
        try:
            layout = self.draw()
            self.assertTrue(layout.operators("mx_keymap.select_by_name"))
            self.assertTrue(layout.operators("mx_keymap.open_editor"))
        finally:
            for name in SIBLINGS:
                disable(name)

    def test_active_tool_depressed(self):
        self.toolbar.active_tool_id = lambda _context: "builtin.move"
        layout = self.draw()
        depressed = [c[2].values.get("name") for c in layout.calls()
                     if c[0] in {"operator", "operator_menu_hold"} and c[1].get("depress")
                     and c[2].idname == "wm.tool_set_by_id"]
        self.assertEqual(depressed, ["builtin.move"])
        self.toolbar.active_tool_id = lambda _context: "builtin.select_lasso"
        layout = self.draw()
        hold = [c for c in layout.calls("operator_menu_hold") if c[1]["menu"].endswith("select_region")][0]
        self.assertEqual(hold[2].values["name"], "builtin.select_lasso")

    def test_flyout_menus(self):
        for flyout in self.toolbar.FLYOUTS:
            with self.subTest(flyout=flyout):
                cls = getattr(bpy.types, self.toolbar._flyout_menu_idname(flyout))
                holder = types.SimpleNamespace(layout=new_layout())
                cls.draw(holder, fake_context())
                self.assertEqual(len(holder.layout.operators("mx_ui.toolbar_flyout")),
                                 len(self.toolbar.FLYOUTS[flyout]))
                check_indirect_operators(self, holder.layout, fake_context())
            for variant in self.toolbar.FLYOUTS[flyout]:
                with self.subTest(flyout=flyout, variant=variant.key):
                    self.toolbar._chosen[flyout] = variant.key
                    self.draw()

    def test_pivot_flyout(self):
        ts = bpy.context.scene.tool_settings
        for variant, value in (('PIVOT', 'INDIVIDUAL_ORIGINS'), ('SELECTION', 'BOUNDING_BOX_CENTER'),
                               ('TRANSFORM', 'CURSOR')):
            bpy.ops.mx_ui.toolbar_flyout(flyout='PIVOT', variant=variant)
            self.assertEqual(ts.transform_pivot_point, value)
            self.assertEqual(self.toolbar.shown_variant(bpy.context, 'PIVOT').key, variant)
        # The shown variant follows the setting, not only the last pick.
        ts.transform_pivot_point = 'INDIVIDUAL_ORIGINS'
        self.assertEqual(self.toolbar.shown_variant(bpy.context, 'PIVOT').key, 'PIVOT')
        ts.transform_pivot_point = 'MEDIAN_POINT'
        self.assertEqual(self.toolbar.shown_variant(bpy.context, 'PIVOT').key, 'SELECTION')

    def test_placeholder_variant_remembered(self):
        bpy.ops.mx_ui.toolbar_flyout(flyout='ALIGN', variant='NORMAL')
        self.assertEqual(self.toolbar.shown_variant(bpy.context, 'ALIGN').key, 'NORMAL')
        layout = self.draw()
        self.assertIn("Normal Align", {op.values.get("feature") for op in layout.operators("mx_ui.placeholder")})

    def test_coordinate_system_round_trip(self):
        state = bpy.context.window_manager.mx_ui
        slot = bpy.context.scene.transform_orientation_slots[0]
        for blender, max_name in (('GLOBAL', 'WORLD'), ('LOCAL', 'LOCAL'), ('VIEW', 'VIEW'), ('GIMBAL', 'GIMBAL'),
                                  ('PARENT', 'PARENT'), ('CURSOR', 'WORKING'), ('NORMAL', 'LOCAL_ALIGNED')):
            with self.subTest(blender=blender):
                slot.type = blender
                self.assertEqual(state.ref_coord_sys, max_name)
                slot.type = 'GLOBAL' if blender != 'GLOBAL' else 'LOCAL'
                state.ref_coord_sys = max_name
                self.assertEqual(slot.type, blender)
        state.ref_coord_sys = 'SCREEN'
        self.assertEqual(slot.type, 'VIEW')
        slot.type = 'LOCAL'
        for unmapped in ('GRID', 'PICK'):
            state.ref_coord_sys = unmapped
            self.assertEqual(slot.type, 'LOCAL')
        slot.type = 'GLOBAL'

    def test_snap_toggles_independent(self):
        ts = bpy.context.scene.tool_settings
        ts.use_snap = False
        toggle = self.toolbar.toggle_snap
        self.assertTrue(toggle(ts, 'PERCENT'))
        self.assertTrue(ts.use_snap)
        self.assertFalse(self.toolbar.snap_enabled(ts, 'SNAP'))
        self.assertTrue(toggle(ts, 'ANGLE'))
        self.assertTrue(self.toolbar.snap_enabled(ts, 'PERCENT'))
        self.assertFalse(toggle(ts, 'PERCENT'))
        self.assertFalse(toggle(ts, 'ANGLE'))
        self.assertFalse(ts.use_snap)
        self.assertTrue(ts.use_snap_translate)
        self.assertTrue(toggle(ts, 'SNAP'))
        self.assertTrue(ts.use_snap)
        self.assertFalse(toggle(ts, 'SNAP'))


class MirrorTest(unittest.TestCase):

    def setUp(self):
        clear_scene()

    def tearDown(self):
        clear_scene()

    def test_mirror_in_place(self):
        a = add_cube("Box001", (2.0, 0.0, 0.0))
        b = add_cube("Box002", (6.0, 0.0, 0.0))
        a.select_set(True)
        result = chrome("menu_ops").mirror_objects(bpy.context, [a, b], 'X')
        self.assertEqual(set(result), {a, b})
        bpy.context.view_layer.update()
        # Centre of the selection's bounding box: x = 4 (from 1 to 7).
        self.assertAlmostEqual(a.matrix_world.translation.x, 6.0, places=5)
        self.assertAlmostEqual(b.matrix_world.translation.x, 2.0, places=5)
        self.assertLess(a.matrix_world.determinant(), 0.0)

    def test_mirror_copy_and_instance(self):
        a = add_cube("Box001", (2.0, 0.0, 0.0))
        menu_ops = chrome("menu_ops")
        copies = menu_ops.mirror_objects(bpy.context, [a], 'Y', offset=1.0, clone='COPY')
        self.assertEqual(len(copies), 1)
        self.assertIsNot(copies[0].data, a.data)
        self.assertEqual(copies[0].name, "Box002")
        self.assertAlmostEqual(copies[0].matrix_world.translation.y, 1.0, places=5)
        instances = menu_ops.mirror_objects(bpy.context, [a], 'Z', clone='INSTANCE')
        self.assertIs(instances[0].data, a.data)
        self.assertAlmostEqual(a.matrix_world.translation.x, 2.0, places=5)

    def test_mirror_operator(self):
        a = add_cube("Box001", (2.0, 0.0, 0.0))
        self.assertEqual(bpy.ops.object.mx_mirror(axis='X', clone='COPY'), {'FINISHED'})
        self.assertEqual(len(bpy.data.objects), 2)
        self.assertIsNot(bpy.context.active_object, a)


if __name__ == "__main__":
    _runner_util.main()
