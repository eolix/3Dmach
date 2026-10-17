# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
``mx_ui`` window frame (``mx_ui.chrome``: strips, Scene Explorer, viewport labels, ViewCube, time slider,
status line, navigation controls, and the Max Layout builder): registration, every draw function against the
recording layout of ``test_ui.py``, header overrides restored, the mini-listener, the transform type-in and
the parts of the layout builder that run headless.
"""

import math
import os
import sys
import types
import unittest

import addon_utils
import bpy
from mathutils import Euler, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _runner_util
from test_ui import ADDON, clear_scene, add_cube, enable, fake_context, new_layout, mx_ui, _operator_rna


def setUpModule():
    enable(ADDON)


def tearDownModule():
    addon_utils.disable(ADDON, default_set=True)


def chrome(name):
    return sys.modules[ADDON + ".chrome." + name]


def screen():
    return bpy.context.window.screen


def first_area(kind):
    return next(a for a in screen().areas if a.type == kind)


def region_of(area, kind='WINDOW'):
    return next(r for r in area.regions if r.type == kind)


def prefs():
    return bpy.context.preferences.addons[ADDON].preferences


class MaxWorkspace:
    """Context manager marking the current workspace as the Max Layout."""

    def __enter__(self):
        self.workspace = bpy.context.window.workspace
        self.had = self.workspace.get(chrome("_areas").WORKSPACE_KEY)
        chrome("_areas").mark_workspace(self.workspace)
        return self.workspace

    def __exit__(self, *_args):
        key = chrome("_areas").WORKSPACE_KEY
        if self.had is None:
            del self.workspace[key]
        else:
            self.workspace[key] = self.had


def frame_context(area=None, region=None, **overrides):
    """A fake context for drawing in ``area`` of the current screen."""
    ctx = bpy.context
    values = {
        "workspace": ctx.window.workspace,
        "area": area,
        "region": region if region is not None else types.SimpleNamespace(width=1200, height=600, x=0, y=0),
        "space_data": area.spaces.active if area is not None else None,
        "tool_settings": ctx.scene.tool_settings,
        "region_data": None,
    }
    values.update(overrides)
    return fake_context(**values)


# -----------------------------------------------------------------------------

class RegistrationTest(unittest.TestCase):

    def test_types_registered(self):
        for name in (
            "MXUI_PT_strip", "SCREEN_MT_mx_viewport_layouts",
            "OUTLINER_MT_mx_explorer_select", "OUTLINER_MT_mx_explorer_display", "OUTLINER_MT_mx_explorer_edit",
            "OUTLINER_MT_mx_explorer_customize", "OUTLINER_MT_mx_explorer_selector",
            "VIEW3D_MT_mx_viewport_plus", "VIEW3D_MT_mx_viewport_view", "VIEW3D_MT_mx_viewport_quality",
            "VIEW3D_MT_mx_viewport_shading", "VIEW3D_MT_mx_zoom_extents", "VIEW3D_MT_mx_orbit",
            "DOPESHEET_PT_mx_time_configuration",
        ):
            with self.subTest(name=name):
                self.assertTrue(hasattr(bpy.types, name), name)

    def test_operators_registered(self):
        for idname in (
            "mx_ui.viewport_nav", "mx_ui.viewport_nav_mode", "mx_ui.viewport_maximize_toggle",
            "mx_ui.viewport_shading", "mx_ui.viewport_view", "mx_ui.viewport_camera", "mx_ui.viewcube_home",
            "mx_ui.listener_run", "mx_ui.explorer_display", "mx_ui.explorer_sort", "mx_ui.explorer_select",
            "mx_ui.explorer_outliner_op", "screen.mx_time_slider", "screen.mx_viewport_layout",
        ):
            with self.subTest(idname=idname):
                _operator_rna(idname)

    def test_viewcube_registered(self):
        viewcube = chrome("viewcube")
        for cls in (viewcube.VIEW3D_GGT_mx_viewcube, viewcube.MXUI_GT_viewcube):
            self.assertEqual(cls.bl_rna.identifier, cls.bl_idname)

    def test_state(self):
        state = bpy.context.window_manager.mx_ui_frame
        self.assertTrue(state.show_viewcube)
        self.assertFalse(state.coord_offset)
        self.assertEqual(state.nav_mode, "")

    def test_overrides_installed(self):
        for cls in (bpy.types.INFO_HT_header, bpy.types.OUTLINER_HT_header, bpy.types.VIEW3D_HT_header,
                    bpy.types.DOPESHEET_HT_header, bpy.types.STATUSBAR_HT_header):
            with self.subTest(cls=cls.__name__):
                names = [f.__qualname__ for f in cls._dyn_ui_initialize()]
                self.assertIn("mx_override_" + cls.__name__, names)
                self.assertNotIn(cls.__name__ + ".draw", names)


class OverrideRestoreTest(unittest.TestCase):

    def test_disable_restores_blender_draw(self):
        classes = (bpy.types.INFO_HT_header, bpy.types.OUTLINER_HT_header, bpy.types.VIEW3D_HT_header,
                   bpy.types.DOPESHEET_HT_header, bpy.types.STATUSBAR_HT_header)
        addon_utils.disable(ADDON, default_set=True)
        try:
            for cls in classes:
                with self.subTest(cls=cls.__name__):
                    names = [f.__qualname__ for f in cls._dyn_ui_initialize()]
                    self.assertIn(cls.__name__ + ".draw", names)
                    self.assertFalse(any(name.startswith("mx_override_") for name in names))
            self.assertFalse(hasattr(bpy.types.WindowManager, "mx_ui_frame"))
        finally:
            enable(ADDON)

    def test_appended_functions_survive(self):
        def extra(_self, _context):
            pass
        bpy.types.STATUSBAR_HT_header.append(extra)
        try:
            addon_utils.disable(ADDON, default_set=True)
            enable(ADDON)
            self.assertIn(extra, bpy.types.STATUSBAR_HT_header._dyn_ui_initialize())
        finally:
            bpy.types.STATUSBAR_HT_header.remove(extra)

    def test_chrome_off_draws_blender(self):
        areas = chrome("_areas")
        info = first_area('VIEW_3D')
        holder = types.SimpleNamespace(layout=new_layout())
        with MaxWorkspace():
            ctx = frame_context(info, region_of(info, 'HEADER'))
            self.assertTrue(chrome("viewport")._draw_header(holder, ctx))
            prefs().use_max_chrome = False
            try:
                self.assertFalse(areas.max_context(ctx))
                self.assertFalse(chrome("viewport")._draw_header(holder, ctx))
                self.assertFalse(chrome("statusbar")._draw_statusbar(holder, ctx))
            finally:
                prefs().use_max_chrome = True
        # Outside the Max Layout the Blender header is drawn.
        self.assertFalse(chrome("viewport")._draw_header(holder, frame_context(info)))

    def test_chrome_toggle_restores_viewports(self):
        area = first_area('VIEW_3D')
        space = area.spaces.active
        with MaxWorkspace():
            chrome("viewport").chrome_toggled(True)
            self.assertFalse(space.overlay.show_text)
            self.assertFalse(space.show_gizmo_navigate)
            chrome("viewport").chrome_toggled(False)
            self.assertTrue(space.overlay.show_text)
            self.assertTrue(space.show_gizmo_navigate)

    def test_transparent_header_restored(self):
        viewport = chrome("viewport")
        color = bpy.context.preferences.themes[0].view_3d.space.header
        before = color[3]
        viewport.set_transparent_headers(True)
        self.assertAlmostEqual(color[3], viewport.HEADER_ALPHA, places=3)
        viewport.set_transparent_headers(False)
        self.assertAlmostEqual(color[3], before if before > 1e-3 else viewport.DEFAULT_HEADER_ALPHA, places=3)


class DrawTest(unittest.TestCase):
    """Every draw function, against the recording layout (operator, property, menu and icon names)."""

    def setUp(self):
        clear_scene()
        self.cube = add_cube("Box001")

    def tearDown(self):
        clear_scene()

    def draw_menu(self, name, ctx):
        holder = types.SimpleNamespace(layout=new_layout())
        getattr(bpy.types, name).draw(holder, ctx)
        self.assertTrue(holder.layout.calls(), name)
        return holder.layout

    def test_strips(self):
        strips = chrome("strips")
        for kind, drawer in chrome("_areas").DRAWERS.items():
            with self.subTest(kind=kind):
                layout = new_layout()
                drawer(layout, frame_context(region=types.SimpleNamespace(width=300, height=500, x=0, y=0)))
                self.assertTrue(layout.calls())
        layout = new_layout()
        strips.draw_main_toolbar_strip(layout, frame_context())
        if strips.main_toolbar_function() is None:
            self.assertEqual(layout.calls("label")[0][1]["text"], "Main Toolbar")
        self.draw_menu("SCREEN_MT_mx_viewport_layouts", frame_context())

    def test_filter_bar_maps_outliner_filters(self):
        layout = new_layout()
        chrome("explorer").draw_filter_bar(layout, frame_context())
        props = {c[1]["property"] for c in layout.calls("prop")}
        self.assertTrue({"use_filter_object_mesh", "use_filter_object_light", "use_filter_object_camera",
                         "use_filter_object_empty", "use_sync_select"} <= props)
        icons = [c[1].get("icon") for c in layout.calls("operator") + layout.calls("prop")]
        self.assertGreaterEqual(len(icons), 20)

    def test_explorer(self):
        explorer = chrome("explorer")
        outliner = first_area('OUTLINER')
        with MaxWorkspace():
            ctx = frame_context(outliner, region_of(outliner, 'HEADER'))
            self.assertTrue(explorer.is_explorer(ctx))
            layout = new_layout()
            explorer.draw_columns(layout, ctx)
            self.assertIn("Frozen", [c[1].get("text") for c in layout.calls("label")])
        for name in ("OUTLINER_MT_mx_explorer_select", "OUTLINER_MT_mx_explorer_display",
                     "OUTLINER_MT_mx_explorer_edit", "OUTLINER_MT_mx_explorer_customize",
                     "OUTLINER_MT_mx_explorer_selector"):
            with self.subTest(menu=name):
                self.draw_menu(name, frame_context())

    def test_viewport_labels_and_menus(self):
        area = first_area('VIEW_3D')
        space = area.spaces.active
        mx_ui().layout.configure_view3d(space, 'TOP')
        ctx = frame_context(area, region_of(area, 'HEADER'))
        layout = new_layout()
        chrome("viewport").draw_labels(layout, ctx)
        texts = [c[1]["text"] for c in layout.calls("menu")]
        self.assertEqual(texts, ["[+]", "[Top]", "[Standard]", "[Wireframe Override]"])
        for name in ("VIEW3D_MT_mx_viewport_plus", "VIEW3D_MT_mx_viewport_view", "VIEW3D_MT_mx_viewport_cameras",
                     "VIEW3D_MT_mx_viewport_quality", "VIEW3D_MT_mx_viewport_shading", "VIEW3D_MT_mx_viewcube",
                     "VIEW3D_MT_mx_viewport_lighting", "VIEW3D_MT_mx_viewport_materials",
                     "VIEW3D_MT_mx_zoom_extents", "VIEW3D_MT_mx_zoom_extents_all", "VIEW3D_MT_mx_fov",
                     "VIEW3D_MT_mx_orbit"):
            with self.subTest(menu=name):
                self.draw_menu(name, ctx)

    def test_status_rows(self):
        statusbar = chrome("statusbar")
        for draw in (statusbar.draw_row1, statusbar.draw_row2):
            with self.subTest(row=draw.__name__):
                layout = new_layout()
                draw(layout, frame_context())
                self.assertTrue(layout.calls("operator"))
        layout = new_layout()
        statusbar.draw_row1(layout, frame_context())
        props = {c[1]["property"] for c in layout.calls("prop")}
        self.assertTrue({"listener_input", "coord_x", "coord_y", "coord_z", "use_keyframe_insert_auto"} <= props)
        labels = [c[1].get("text") for c in layout.calls("label")]
        self.assertIn("1 Object Selected", labels)
        self.assertTrue(any(text.startswith("Grid = ") for text in labels))
        holder = types.SimpleNamespace(layout=new_layout())
        statusbar.DOPESHEET_PT_mx_time_configuration.draw(holder, frame_context())

    def test_time_slider(self):
        timeslider = chrome("timeslider")
        scene = bpy.context.scene
        layout = new_layout()
        timeslider.draw_time_slider(layout, frame_context())
        texts = [c[1].get("text") for c in layout.calls("operator")]
        self.assertIn(timeslider.slider_text(scene), texts)
        self.assertEqual(timeslider.slider_text(scene), "{:d} / {:d}".format(scene.frame_current, scene.frame_end))


class ListenerTest(unittest.TestCase):

    def setUp(self):
        self.frame_state = chrome("frame_state")
        self.state = bpy.context.window_manager.mx_ui_frame

    def test_run_listener(self):
        run = self.frame_state.run_listener
        self.assertEqual(run("1 + 1"), (True, "2"))
        self.assertEqual(run("listener_test_value = 3"), (True, "OK"))
        self.assertEqual(run("len(D.objects) >= 0"), (True, "True"))
        ok, text = run("1 / 0")
        self.assertFalse(ok)
        self.assertIn("ZeroDivisionError", text)
        ok, text = run("def (")
        self.assertFalse(ok)
        self.assertIn("SyntaxError", text)
        self.assertEqual(run("   "), (True, ""))

    def test_field_runs_on_confirm(self):
        self.state.listener_input = "2 * 21"
        self.assertEqual(self.state.listener_result, "42")
        self.assertTrue(self.state.listener_ok)
        self.state.listener_input = "undefined_name_xyz"
        self.assertFalse(self.state.listener_ok)
        self.assertIn("NameError", self.state.listener_result)

    def test_operator(self):
        self.assertEqual(bpy.ops.mx_ui.listener_run(code="3 + 4"), {'FINISHED'})
        self.assertEqual(self.state.listener_result, "7")


class TypeInTest(unittest.TestCase):

    def setUp(self):
        clear_scene()
        self.cube = add_cube("Box001")
        self.state = bpy.context.window_manager.mx_ui_frame
        self.state.coord_offset = False

    def tearDown(self):
        self.state.coord_offset = False
        clear_scene()

    def test_absolute(self):
        self.state.coord_x = 3.0
        self.state.coord_z = -1.5
        self.assertAlmostEqual(self.cube.location.x, 3.0)
        self.assertAlmostEqual(self.cube.location.z, -1.5)
        self.assertAlmostEqual(self.state.coord_x, 3.0)
        self.state.rot_z = math.radians(90.0)
        self.assertAlmostEqual(self.cube.rotation_euler.z, math.radians(90.0), places=5)
        self.state.scale_y = 200.0
        self.assertAlmostEqual(self.cube.scale.y, 2.0)

    def test_offset(self):
        self.cube.location = (1.0, 1.0, 1.0)
        self.state.coord_offset = True
        self.assertEqual(self.state.coord_y, 0.0)
        self.state.coord_y = 2.0
        self.assertAlmostEqual(self.cube.location.y, 3.0)
        self.assertEqual(self.state.scale_x, 100.0)
        self.state.scale_x = 50.0
        self.assertAlmostEqual(self.cube.scale.x, 0.5)

    def test_kind_follows_tool(self):
        self.assertEqual(self.frame_state_kind(), 'LOCATION')
        self.assertEqual(chrome("frame_state").coord_property_names('ROTATION'), ["rot_x", "rot_y", "rot_z"])

    def frame_state_kind(self):
        return chrome("frame_state").transform_kind(frame_context())

    def test_no_selection(self):
        self.cube.select_set(False)
        bpy.context.view_layer.objects.active = None
        self.assertEqual(self.state.coord_x, 0.0)
        self.state.coord_x = 5.0
        self.assertAlmostEqual(self.cube.location.x, 0.0)


class StatusTextTest(unittest.TestCase):

    def setUp(self):
        clear_scene()

    def tearDown(self):
        bpy.context.window_manager.mx_ui_frame.nav_mode = ""
        clear_scene()

    def test_selection_count(self):
        statusbar = chrome("statusbar")
        self.assertEqual(statusbar.selection_text(bpy.context), "None Selected")
        add_cube("A")
        self.assertEqual(statusbar.selection_text(bpy.context), "1 Object Selected")
        add_cube("B").select_set(True)
        bpy.data.objects["A"].select_set(True)
        self.assertEqual(statusbar.selection_text(bpy.context), "2 Objects Selected")

    def test_prompt(self):
        statusbar = chrome("statusbar")
        self.assertTrue(statusbar.prompt_text(frame_context()).startswith("Click"))
        bpy.context.window_manager.mx_ui_frame.nav_mode = 'PAN'
        self.assertIn("pan", statusbar.prompt_text(frame_context()))
        self.assertTrue(statusbar.grid_text(frame_context()).startswith("Grid = "))


class ExplorerTest(unittest.TestCase):

    def setUp(self):
        clear_scene()
        self.explorer = chrome("explorer")
        self.space = first_area('OUTLINER').spaces.active

    def tearDown(self):
        self.explorer.set_type_filters(self.space, 'ALL')
        clear_scene()

    def test_state_filters(self):
        ex = self.explorer
        for frozen, hidden in ((True, True), (True, False), (False, False)):
            ex.set_state_filters(self.space, frozen, hidden)
            self.assertEqual(ex.shows_frozen(self.space), frozen)
            self.assertEqual(ex.shows_hidden(self.space), hidden)

    def test_type_filters_and_sort(self):
        ex = self.explorer
        ex.set_type_filters(self.space, 'NONE')
        self.assertFalse(self.space.use_filter_object_mesh)
        ex.set_type_filters(self.space, 'INVERT')
        self.assertTrue(self.space.use_filter_object_camera)
        ex.set_sort_mode(self.space, 'LAYER')
        self.assertEqual(ex.sort_mode(self.space), 'LAYER')
        ex.set_sort_mode(self.space, 'HIERARCHY')
        self.assertFalse(self.space.use_filter_collection)
        ex.configure_explorer(self.space)
        self.assertTrue(self.space.show_restrict_column_select)
        self.assertEqual(self.space.display_mode, 'VIEW_LAYER')

    def test_operators(self):
        a = add_cube("A")
        b = add_cube("B")
        self.assertEqual(bpy.ops.mx_ui.explorer_select(action='SELECT'), {'FINISHED'})
        self.assertTrue(a.select_get() and b.select_get())
        bpy.ops.mx_ui.explorer_select(action='INVERT')
        self.assertFalse(a.select_get() or b.select_get())
        self.assertEqual(bpy.ops.mx_ui.explorer_display(action='NONE'), {'FINISHED'})
        self.assertFalse(self.space.use_filter_object_mesh)
        bpy.ops.mx_ui.explorer_display(action='FROZEN')
        self.assertEqual(self.space.filter_state, 'SELECTABLE')
        bpy.ops.mx_ui.explorer_display(action='ALL')
        self.assertEqual(self.space.filter_state, 'ALL')

    def test_frozen_column_freezes(self):
        ex = self.explorer
        cube = add_cube("Box001")
        cube.color = (1.0, 0.0, 0.0, 1.0)
        ex._snapshot()
        cube.hide_select = True
        frozen, _unfrozen = ex.sync_frozen(gray=True)
        self.assertEqual(frozen, [cube])
        self.assertTrue(mx_ui().freeze.is_frozen(cube))
        self.assertNotEqual(tuple(cube.color), (1.0, 0.0, 0.0, 1.0))
        cube.hide_select = False
        _frozen, unfrozen = ex.sync_frozen()
        self.assertEqual(unfrozen, [cube])
        self.assertEqual(tuple(cube.color), (1.0, 0.0, 0.0, 1.0))
        # Unchanged objects are left alone.
        self.assertEqual(ex.sync_frozen(), ([], []))


class ViewportTest(unittest.TestCase):

    def setUp(self):
        self.viewport = chrome("viewport")
        self.area = first_area('VIEW_3D')
        self.space = self.area.spaces.active

    def tearDown(self):
        mx_ui().layout.configure_view3d(self.space, 'PERSPECTIVE')

    def test_labels(self):
        layout = mx_ui().layout
        expected = {'TOP': "Top", 'FRONT': "Front", 'LEFT': "Left", 'PERSPECTIVE': "Perspective"}
        for role, label in expected.items():
            with self.subTest(role=role):
                layout.configure_view3d(self.space, role)
                self.assertEqual(self.viewport.view_label(self.space), label)
        self.space.region_3d.is_orthographic_side_view = False
        self.space.region_3d.view_perspective = 'ORTHO'
        self.space.region_3d.view_rotation = Euler((1.0, 0.2, 0.3)).to_quaternion()
        self.assertEqual(self.viewport.view_label(self.space), "Orthographic")

    def test_shading_styles(self):
        vp = self.viewport
        vp.apply_shading(self.space, 'DEFAULT')
        self.assertEqual(vp.shading_label(self.space), "Default Shading")
        vp.apply_shading(self.space, 'EDGED_FACES')
        self.assertEqual(vp.shading_label(self.space), "Default Shading + Edged Faces")
        vp.apply_shading(self.space, 'EDGED_FACES')
        vp.apply_shading(self.space, 'CLAY')
        self.assertEqual(vp.shading_label(self.space), "Clay")
        vp.apply_shading(self.space, 'FLAT_COLOR')
        self.assertEqual(vp.shading_label(self.space), "Flat Color")
        vp.apply_shading(self.space, 'WIREFRAME')
        self.assertEqual(vp.shading_label(self.space), "Wireframe Override")
        vp.apply_shading(self.space, 'HIGH_QUALITY')
        self.assertEqual(vp.quality_label(self.space), "High Quality")
        vp.apply_shading(self.space, 'STANDARD')
        self.assertEqual(vp.quality_label(self.space), "Standard")
        xray = self.space.shading.show_xray
        vp.apply_shading(self.space, 'SEE_THROUGH')
        self.assertNotEqual(self.space.shading.show_xray, xray)
        for style, _label, _desc in vp.SHADING_STYLES:
            vp.apply_shading(self.space, style, bpy.context.scene)

    def test_tripod(self):
        mx_ui().layout.configure_view3d(self.space, 'TOP')
        lines = self.viewport.tripod_lines(self.space.region_3d)
        self.assertEqual(sorted(line[0] for line in lines), ["x", "y", "z"])
        by_axis = {line[0]: line for line in lines}
        # Top view: x points right, y up, z at the viewer (a point).
        self.assertGreater(by_axis["x"][3][0], by_axis["x"][2][0])
        self.assertGreater(by_axis["y"][3][1], by_axis["y"][2][1])
        self.assertAlmostEqual(by_axis["z"][3][0], by_axis["z"][2][0], places=3)

    def test_configured_viewports_hide_blender_overlays(self):
        mx_ui().layout.configure_view3d(self.space, 'FRONT')
        self.assertFalse(self.space.overlay.show_text)
        self.assertFalse(self.space.show_gizmo_navigate)


class ViewCubeTest(unittest.TestCase):

    def setUp(self):
        self.cube = chrome("viewcube")

    def test_top_view_shows_top_face(self):
        cells = self.cube.cube_cells(Euler((0.0, 0.0, 0.0)).to_quaternion(), (100.0, 100.0), 30.0)
        self.assertEqual(len(cells), 9)
        self.assertEqual(self.cube.pick_part(cells, (100.0, 100.0)), (0, 0, 1))
        # Top view: +Y is up on screen, so the cell above the centre is the back edge.
        self.assertEqual(self.cube.pick_part(cells, (100.0, 127.0)), (0, 1, 1))
        self.assertEqual(self.cube.pick_part(cells, (128.0, 128.0)), (1, 1, 1))
        self.assertIsNone(self.cube.pick_part(cells, (200.0, 200.0)))

    def test_perspective_shows_three_faces(self):
        rotation = Euler((math.radians(65.0), 0.0, math.radians(-45.0))).to_quaternion()
        cells = self.cube.cube_cells(rotation, (0.0, 0.0), 30.0)
        self.assertEqual(len(cells), 27)
        parts = {cell[0] for cell in cells}
        self.assertIn((0, 0, 1), parts)
        # 3 faces, 9 edges (3 between them, 6 on the outline) and 7 corners.
        self.assertEqual(len(parts), 3 + 9 + 7)

    def test_rotation_for_part(self):
        view = self.cube.rotation_for_part((0, 0, 1))
        self.assertAlmostEqual((view @ Vector((0.0, 0.0, -1.0))).z, -1.0, places=5)
        self.assertAlmostEqual((view @ Vector((0.0, 1.0, 0.0))).y, 1.0, places=5)
        view = self.cube.rotation_for_part((1, -1, 1))
        direction = view @ Vector((0.0, 0.0, 1.0))
        self.assertTrue(direction.x > 0 and direction.y < 0 and direction.z > 0)
        up = view @ Vector((0.0, 1.0, 0.0))
        self.assertGreater(up.z, 0.0)
        for part in self.cube.FACE_VIEWS:
            with self.subTest(part=part):
                self.assertAlmostEqual((self.cube.rotation_for_part(part) @ Vector((0, 0, 1))).dot(Vector(part)), 1.0,
                                       places=5)


    def test_apply_part(self):
        area = first_area('VIEW_3D')
        region = region_of(area)
        mx_ui().layout.configure_view3d(area.spaces.active, 'TOP')
        self.cube.apply_part(bpy.context, area, region, (1, -1, 1))
        rv3d = region.data
        self.assertEqual(rv3d.view_perspective, 'PERSP')
        expected = self.cube.rotation_for_part((1, -1, 1))
        self.assertAlmostEqual(expected.rotation_difference(rv3d.view_rotation).angle, 0.0, places=4)
        mx_ui().layout.configure_view3d(area.spaces.active, 'PERSPECTIVE')


class NavigationTest(unittest.TestCase):

    def test_target_viewport(self):
        nav = chrome("navigation")
        area, region = nav.target_viewport(frame_context())
        self.assertEqual(area.type, 'VIEW_3D')
        self.assertEqual(region.type, 'WINDOW')
        nav.note_viewport(area)
        self.assertEqual(nav.target_viewport(frame_context())[0], area)

    def test_fov_and_zoom(self):
        nav = chrome("navigation")
        space = first_area('VIEW_3D').spaces.active
        lens = space.lens
        nav.change_fov(space, 10.0)
        self.assertLess(space.lens, lens)
        space.lens = lens
        rv3d = space.region_3d
        distance = rv3d.view_distance
        nav.zoom_view(rv3d, 0.5)
        self.assertAlmostEqual(rv3d.view_distance, distance * 0.5, places=4)
        rv3d.view_distance = distance

    def test_orbit(self):
        nav = chrome("navigation")
        space = first_area('VIEW_3D').spaces.active
        mx_ui().layout.configure_view3d(space, 'TOP')
        rv3d = space.region_3d
        before = rv3d.view_rotation.copy()
        nav.orbit_view(rv3d, 30, 10)
        self.assertNotAlmostEqual(before.rotation_difference(rv3d.view_rotation).angle, 0.0, places=3)
        # Orbiting an axis view leaves it, in perspective.
        self.assertFalse(rv3d.is_orthographic_side_view)
        self.assertEqual(rv3d.view_perspective, 'PERSP')
        mx_ui().layout.configure_view3d(space, 'PERSPECTIVE')

    def test_time_slider_mapping(self):
        timeslider = chrome("timeslider")
        scene = bpy.context.scene
        start, width, thumb = timeslider._track_geometry(1000, 1.0)
        self.assertEqual(timeslider.frame_at(scene, 0, 1000, 1.0), scene.frame_start)
        self.assertEqual(timeslider.frame_at(scene, 1000, 1000, 1.0), scene.frame_end)
        middle = start + thumb / 2.0 + (width - thumb) / 2.0
        self.assertAlmostEqual(timeslider.frame_at(scene, middle, 1000, 1.0),
                               (scene.frame_start + scene.frame_end) / 2.0, delta=1.0)


class AreaMarkTest(unittest.TestCase):

    def test_mark_and_resolve(self):
        areas = chrome("_areas")
        scr = screen()
        info = first_area('PROPERTIES')
        outliner = first_area('OUTLINER')
        try:
            areas.mark_areas(scr, {'FILTER_BAR': info, 'EXPLORER': outliner})
            self.assertEqual(areas.find_area(scr, 'FILTER_BAR'), info)
            self.assertEqual(areas.area_role(scr, outliner), 'EXPLORER')
            # A wrong index (e.g. after the user closed an area) is matched again by type and position.
            data = scr[areas.SCREEN_KEY]
            data['FILTER_BAR']['index'] = 99
            areas.clear_cache()
            self.assertEqual(areas.find_area(scr, 'FILTER_BAR'), info)
            ctx = frame_context(info)
            prefs().use_max_chrome = False
            self.assertIsNone(areas.strip_kind(ctx))
            prefs().use_max_chrome = True
            self.assertEqual(areas.strip_kind(ctx), 'FILTER_BAR')
            self.assertEqual(areas.explorer_space(ctx), outliner.spaces.active)
        finally:
            del scr[areas.SCREEN_KEY]
            areas.clear_cache()

    def test_setup_strip(self):
        areas = chrome("_areas")
        props = first_area('PROPERTIES')
        space = props.spaces.active
        old_context = space.context
        try:
            areas.setup_strip(props, 'TAB_BAR')
            self.assertEqual(space.context, 'COLLECTION')
            self.assertEqual(space.pin_id, bpy.context.scene.collection)
            self.assertFalse(areas.strip_needs_repin(space, bpy.context.scene))
            self.assertFalse(space.show_region_header)
        finally:
            space.use_pin_id = False
            space.pin_id = None
            space.show_region_header = True
            for prop in space.bl_rna.properties:
                if prop.identifier.startswith("show_properties_"):
                    setattr(space, prop.identifier, True)
            try:
                space.context = old_context
            except TypeError:
                pass  # The available tabs are only updated on redraw.


class ZLayoutBuildTest(unittest.TestCase):
    """Runs last: splits the screen."""

    def test_configure_timeline(self):
        area = first_area('DOPESHEET_EDITOR')
        mx_ui().layout.configure_timeline(area)
        space = area.spaces.active
        self.assertEqual(space.mode, 'TIMELINE')
        with MaxWorkspace():
            ctx = frame_context(area, region_of(area, 'HEADER'))
            self.assertTrue(chrome("timeslider").is_max_timeline(ctx))

    def test_split_steps(self):
        layout = mx_ui().layout
        window = bpy.context.window
        scr = screen()
        area = max((a for a in scr.areas if a.type == 'VIEW_3D'), key=lambda a: a.width * a.height)
        before = list(scr.areas)
        steps = layout.split_steps(window, scr, area)
        roles = None
        try:
            for _step in range(1000):
                next(steps)
        except RuntimeError:
            # Splitting an area created by a split needs its size, computed by the event loop between steps,
            # which doesn't run headless. The splits of the original area are done by then.
            pass
        except StopIteration as ex:
            roles = ex.value
        new_types = sorted(a.type for a in scr.areas if a not in before)
        if roles is None:
            self.assertEqual(new_types, sorted(['DOPESHEET_EDITOR', 'INFO', 'INFO', 'PROPERTIES', 'OUTLINER',
                                                'PROPERTIES', 'VIEW_3D', 'VIEW_3D']))
        else:
            self.assertEqual(len(roles), 14)
        strips = sorted((a for a in scr.areas if a not in before and a.type == 'INFO'), key=lambda a: a.y)
        # The status row at the bottom, the main toolbar at the top.
        self.assertEqual(len(strips), 2)
        self.assertLess(strips[0].y, strips[1].y)
        if roles is not None:
            layout.configure_areas(window, scr, roles)
            self.assertEqual(chrome("_areas").find_area(scr, 'FILTER_BAR'), roles['FILTER_BAR'])

    def test_operator_marks_workspace(self):
        bpy.ops.screen.mx_max_layout()
        workspace = bpy.data.workspaces[mx_ui().layout.WORKSPACE_NAME]
        self.assertTrue(chrome("_areas").is_max_workspace(workspace))


if __name__ == "__main__":
    _runner_util.main()
