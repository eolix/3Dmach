# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""The Max-Style keymap add-on: registration, the keyconfig and its bindings, and the operators behind them."""

import filecmp
import json
import os
import sys
import unittest

import addon_utils
import bmesh
import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _runner_util

ADDON = "mx_keymap"
KC_NAME = "Max-Style"
NAV_ATTRS = ("use_rotate_around_active", "use_zoom_to_mouse", "use_auto_perspective")


def enable():
    errors = []
    mod = addon_utils.enable(ADDON, default_set=True, handle_error=lambda ex: errors.append(ex))
    if errors:
        raise errors[0]
    if mod is None:
        raise RuntimeError("add-on could not be enabled")
    return mod


def disable():
    addon_utils.disable(ADDON, default_set=True)


def set_blender_navigation():
    """Blender's default navigation preferences (the opposite of the Max-like ones for the checked attributes)."""
    inputs = bpy.context.preferences.inputs
    inputs.use_rotate_around_active = False
    inputs.use_zoom_to_mouse = False
    inputs.use_auto_perspective = True


def navigation_state():
    inputs = bpy.context.preferences.inputs
    return {attr: getattr(inputs, attr) for attr in NAV_ATTRS}


def use_blender_keyconfig():
    wm = bpy.context.window_manager
    wm.keyconfigs.active = wm.keyconfigs.default


def _mod(value):
    return value == 1 or value is True


def find_items(kc, keymap, idname, event_type, value='PRESS', *, shift=False, ctrl=False, alt=False, **props):
    km = kc.keymaps.get(keymap)
    if km is None:
        return []
    found = []
    for kmi in km.keymap_items:
        if kmi.idname != idname or kmi.type != event_type or kmi.value != value:
            continue
        if kmi.any or (_mod(kmi.shift), _mod(kmi.ctrl), _mod(kmi.alt)) != (shift, ctrl, alt):
            continue
        if any(getattr(kmi.properties, key) != expected for key, expected in props.items()):
            continue
        found.append(kmi)
    return found


def items_for_event(kc, keymap, event_type, value='PRESS', *, shift=False, ctrl=False, alt=False):
    km = kc.keymaps.get(keymap)
    return [
        kmi for kmi in km.keymap_items
        if kmi.type == event_type and kmi.value == value and not kmi.any and
        (_mod(kmi.shift), _mod(kmi.ctrl), _mod(kmi.alt)) == (shift, ctrl, alt)
    ]


def view3d_override():
    window = bpy.context.window_manager.windows[0]
    for area in window.screen.areas:
        if area.type == 'VIEW_3D':
            region = next(r for r in area.regions if r.type == 'WINDOW')
            return {"window": window, "area": area, "region": region}
    raise RuntimeError("no 3D viewport in the startup file")


# (keymap, operator, event type, value, modifiers, properties) that must be in the keyconfig.
EXPECTED = [
    # Navigation.
    ("3D View", "view3d.rotate", 'MIDDLEMOUSE', 'PRESS', {"alt": True}, {}),
    ("3D View", "view3d.move", 'MIDDLEMOUSE', 'PRESS', {}, {}),
    ("3D View", "view3d.zoom", 'WHEELINMOUSE', 'PRESS', {}, {"delta": 1}),
    ("3D View", "view3d.zoom", 'WHEELOUTMOUSE', 'PRESS', {}, {"delta": -1}),
    ("3D View", "view3d.zoom", 'MIDDLEMOUSE', 'PRESS', {"ctrl": True, "alt": True}, {}),
    ("3D View", "mx_keymap.zoom_extents", 'Z', 'PRESS', {}, {}),
    ("3D View", "mx_keymap.viewport_maximize", 'W', 'PRESS', {"alt": True}, {}),
    # Tools.
    ("3D View", "wm.tool_set_by_id", 'Q', 'PRESS', {}, {"name": "builtin.select_box"}),
    ("3D View", "wm.tool_set_by_id", 'W', 'PRESS', {}, {"name": "builtin.move"}),
    ("3D View", "wm.tool_set_by_id", 'E', 'PRESS', {}, {"name": "builtin.rotate"}),
    ("3D View", "wm.tool_set_by_id", 'R', 'PRESS', {}, {"name": "builtin.scale"}),
    # Sub-object levels.
    *(("3D View", "mx_keymap.subobject_level", key, 'PRESS', {}, {"level": level})
      for level, key in enumerate(('ONE', 'TWO', 'THREE', 'FOUR', 'FIVE', 'SIX'), start=1)),
    # Views.
    ("3D View", "mx_keymap.view_axis", 'T', 'PRESS', {}, {"type": 'TOP'}),
    ("3D View", "mx_keymap.view_axis", 'B', 'PRESS', {}, {"type": 'BOTTOM'}),
    ("3D View", "mx_keymap.view_axis", 'F', 'PRESS', {}, {"type": 'FRONT'}),
    ("3D View", "mx_keymap.view_axis", 'L', 'PRESS', {}, {"type": 'LEFT'}),
    ("3D View", "mx_keymap.view_projection", 'P', 'PRESS', {}, {"mode": 'PERSP'}),
    ("3D View", "mx_keymap.view_projection", 'U', 'PRESS', {}, {"mode": 'ORTHO'}),
    ("3D View", "mx_keymap.view_camera", 'C', 'PRESS', {}, {}),
    # Display.
    ("3D View", "view3d.toggle_shading", 'F3', 'PRESS', {}, {"type": 'WIREFRAME'}),
    ("3D View", "wm.context_toggle", 'F4', 'PRESS', {}, {"data_path": "space_data.overlay.show_wireframes"}),
    ("3D View", "mx_keymap.toggle_grid", 'G', 'PRESS', {}, {}),
    ("3D View", "mx_keymap.select_by_name", 'H', 'PRESS', {}, {}),
    ("3D View", "mx_keymap.snap_toggle", 'S', 'PRESS', {}, {"kind": 'SNAP'}),
    ("3D View", "mx_keymap.snap_toggle", 'A', 'PRESS', {}, {"kind": 'ANGLE'}),
    ("3D View", "wm.context_toggle", 'X', 'PRESS', {}, {"data_path": "space_data.show_gizmo_tool"}),
    ("3D View", "view3d.localview", 'Q', 'PRESS', {"alt": True}, {}),
    ("Frames", "mx_keymap.selection_lock_toggle", 'SPACE', 'PRESS', {}, {}),
    ("3D View", "mx_keymap.open_editor", 'M', 'PRESS', {}, {"editor": 'MATERIAL'}),
    ("Window", "mx_keymap.open_editor", 'F10', 'PRESS', {}, {"editor": 'RENDER'}),
    ("Window", "render.render", 'Q', 'PRESS', {"shift": True}, {}),
    ("Window", "render.render", 'F9', 'PRESS', {}, {}),
    ("Screen", "ed.undo", 'Z', 'PRESS', {"ctrl": True}, {}),
    ("Screen", "ed.redo", 'Y', 'PRESS', {"ctrl": True}, {}),
    # Selection.
    ("3D View", "view3d.select", 'LEFTMOUSE', 'CLICK', {}, {"deselect_all": True}),
    ("3D View", "view3d.select", 'LEFTMOUSE', 'CLICK', {"ctrl": True}, {"extend": True}),
    ("3D View", "view3d.select", 'LEFTMOUSE', 'CLICK', {"alt": True}, {"deselect": True}),
    *((km, "view3d.select_box", 'LEFTMOUSE', 'CLICK_DRAG', mods, props)
      for km in ("3D View Tool: Select Box", "3D View Tool: Select Box (fallback)", "3D View Tool: Move")
      for mods, props in (({}, {}), ({"ctrl": True}, {"mode": 'ADD'}), ({"alt": True}, {"mode": 'SUB'}))),
    ("3D View Tool: Select Lasso", "view3d.select_lasso", 'LEFTMOUSE', 'CLICK_DRAG', {"alt": True}, {"mode": 'SUB'}),
    ("3D View Tool: Tweak", "mx_keymap.select_pick", 'LEFTMOUSE', 'PRESS', {"ctrl": True}, {"extend": True}),
    # Drag on objects and clone.
    *((km, idname, 'LEFTMOUSE', 'CLICK_DRAG', mods, {})
      for km in ("3D View Tool: Move", "3D View Tool: Rotate", "3D View Tool: Scale",
                 "3D View Tool: Select Box (fallback)", "3D View Tool: Tweak (fallback)")
      for idname, mods in (("mx_keymap.select_drag", {}), ("mx_keymap.clone_drag", {"shift": True}))),
    ("Generic Gizmo Maybe Drag", "mx_keymap.clone_gizmo_drag", 'LEFTMOUSE', 'CLICK_DRAG', {"shift": True}, {}),
    # Quad menu.
    ("Object Mode", "wm.call_menu_pie", 'RIGHTMOUSE', 'PRESS', {}, {"name": "VIEW3D_MT_mx_quad"}),
    ("Mesh", "wm.call_menu_pie", 'RIGHTMOUSE', 'PRESS', {}, {"name": "VIEW3D_MT_mx_quad"}),
    # Delete without confirmation.
    ("Object Mode", "object.delete", 'DEL', 'PRESS', {}, {"confirm": False}),
    ("Mesh", "mx_keymap.delete_subobject", 'DEL', 'PRESS', {}, {}),
    # Select all / none / invert.
    ("Object Mode", "object.select_all", 'A', 'PRESS', {"ctrl": True}, {"action": 'SELECT'}),
    ("Object Mode", "object.select_all", 'D', 'PRESS', {"ctrl": True}, {"action": 'DESELECT'}),
    ("Mesh", "mesh.select_all", 'I', 'PRESS', {"ctrl": True}, {"action": 'INVERT'}),
    # Other Max defaults.
    ("Object Mode", "mx_keymap.clone", 'V', 'PRESS', {"ctrl": True}, {}),
    ("3D View", "view3d.pastebuffer", 'V', 'PRESS', {"ctrl": True, "shift": True}, {}),
    ("Object Mode", "object.select_hierarchy", 'PAGE_UP', 'PRESS', {}, {"direction": 'PARENT'}),
    ("Pose", "pose.select_hierarchy", 'PAGE_DOWN', 'PRESS', {}, {"direction": 'CHILD'}),
    ("3D View", "view3d.zoom", 'LEFT_BRACKET', 'PRESS', {}, {"delta": 1}),
    ("3D View", "view3d.zoom_border", 'W', 'PRESS', {"ctrl": True}, {}),
    ("Frames", "screen.animation_play", 'SLASH', 'PRESS', {}, {}),
    ("Mesh", "mesh.loop_select", 'LEFTMOUSE', 'DOUBLE_CLICK', {}, {}),
    # Blender bindings that are kept.
    ("Object Non-modal", "object.mode_set", 'TAB', 'PRESS', {}, {"mode": 'EDIT'}),
    ("Window", "wm.save_mainfile", 'S', 'PRESS', {"ctrl": True}, {}),
    ("3D View Generic", "wm.context_toggle", 'N', 'PRESS', {}, {"data_path": "space_data.show_region_ui"}),
    ("Screen", "render.render", 'F12', 'PRESS', {}, {}),
]

# (keymap, event type, value, modifiers, operator) bindings of Blender that must be gone.
REMOVED = [
    ("Object Mode", 'G', 'PRESS', {}, "transform.translate"),
    ("Object Mode", 'R', 'PRESS', {}, "transform.rotate"),
    ("Object Mode", 'S', 'PRESS', {}, "transform.resize"),
    ("Object Mode", 'X', 'PRESS', {}, "object.delete"),
    ("Object Mode", 'H', 'PRESS', {}, "object.hide_view_set"),
    ("Object Mode", 'A', 'PRESS', {}, "object.select_all"),
    ("Object Mode", 'M', 'PRESS', {}, "wm.call_menu"),
    ("Object Mode", 'RIGHTMOUSE', 'PRESS', {}, "wm.call_menu"),
    ("Object Non-modal", 'Q', 'PRESS', {"alt": True}, "object.transfer_mode"),
    ("Mesh", 'E', 'PRESS', {}, "view3d.edit_mesh_extrude_move_normal"),
    ("Mesh", 'ONE', 'PRESS', {}, "mesh.select_mode"),
    ("Mesh", 'DEL', 'PRESS', {}, "wm.call_menu"),
    ("Mesh", 'LEFTMOUSE', 'CLICK', {"ctrl": True}, "mesh.shortest_path_pick"),
    ("Mesh", 'LEFTMOUSE', 'CLICK', {"alt": True}, "mesh.loop_select"),
    ("3D View", 'Z', 'PRESS', {}, "wm.call_menu_pie"),
    ("3D View", 'B', 'PRESS', {}, "view3d.select_box"),
    ("3D View", 'C', 'PRESS', {}, "view3d.select_circle"),
    ("3D View", 'MIDDLEMOUSE', 'PRESS', {}, "view3d.rotate"),
    ("3D View", 'MIDDLEMOUSE', 'CLICK', {"alt": True}, "view3d.view_center_pick"),
    ("3D View", 'SLASH', 'PRESS', {}, "view3d.localview"),
    ("3D View Generic", 'T', 'PRESS', {}, "wm.context_toggle"),
    ("Screen", 'F9', 'PRESS', {}, "screen.redo_last"),
    ("3D View Tool: Move", 'LEFTMOUSE', 'CLICK_DRAG', {}, "transform.translate"),
]


class A_RegistrationTest(unittest.TestCase):
    """Runs first, in a fresh Blender: enabling the add-on must not change anything by itself."""

    def test_enable_disable(self):
        before = navigation_state()
        enable()
        try:
            self.assertTrue(hasattr(bpy.types, "MX_KEYMAP_OT_subobject_level"))
            self.assertEqual(bpy.context.window_manager.keyconfigs.active.name, "Blender")
            self.assertEqual(navigation_state(), before)
            # The preset is selectable in Preferences > Keymap.
            presets = [
                os.path.join(d, KC_NAME + ".py") for d in bpy.utils.preset_paths("keyconfig")
                if os.path.exists(os.path.join(d, KC_NAME + ".py"))
            ]
            self.assertEqual(len(presets), 1, presets)
        finally:
            disable()
        self.assertFalse(hasattr(bpy.types, "MX_KEYMAP_OT_subobject_level"))
        self.assertNotIn(KC_NAME + ".py", [
            name for d in bpy.utils.preset_paths("keyconfig") for name in os.listdir(d)
        ])

    def test_fork_preset_matches_addon(self):
        root = os.environ["MX_TEST_ROOT"]
        fork = os.path.join(root, "scripts", "presets", "keyconfig", KC_NAME + ".py")
        addon = os.path.join(root, "scripts", "addons_core", ADDON, "presets", "keyconfig", KC_NAME + ".py")
        self.assertTrue(filecmp.cmp(fork, addon, shallow=False), "the two preset copies must be identical")

    def test_keymap_data_conflicts(self):
        from mx_keymap import keymap_data
        conflict = keymap_data.events_conflict
        self.assertTrue(conflict({"type": 'G', "value": 'PRESS'}, {"type": 'G', "value": 'PRESS'}))
        self.assertFalse(conflict({"type": 'G', "value": 'PRESS'}, {"type": 'G', "value": 'PRESS', "shift": True}))
        self.assertTrue(conflict({"type": 'A', "value": 'PRESS'}, {"type": 'A', "value": 'DOUBLE_CLICK'}))
        self.assertTrue(conflict(
            {"type": 'MIDDLEMOUSE', "value": 'PRESS', "alt": True},
            {"type": 'MIDDLEMOUSE', "value": 'CLICK_DRAG', "alt": True, "direction": 'NORTH'}))
        self.assertFalse(conflict(
            {"type": 'LEFTMOUSE', "value": 'CLICK'}, {"type": 'LEFTMOUSE', "value": 'CLICK_DRAG'}))
        self.assertTrue(conflict(
            {"type": 'X', "value": 'PRESS', "any": True}, {"type": 'X', "value": 'PRESS', "alt": True}))


class B_KeyconfigTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        enable()
        set_blender_navigation()
        result = bpy.ops.mx_keymap.keyconfig_activate()
        assert result == {'FINISHED'}, result
        cls.kc = bpy.context.window_manager.keyconfigs.active

    @classmethod
    def tearDownClass(cls):
        use_blender_keyconfig()
        disable()

    def test_active(self):
        self.assertEqual(self.kc.name, KC_NAME)
        self.assertGreater(len(self.kc.keymaps), 100)

    def test_navigation_applied_on_activation(self):
        self.assertEqual(navigation_state(), {
            "use_rotate_around_active": True, "use_zoom_to_mouse": True, "use_auto_perspective": False,
        })
        prefs = bpy.context.preferences.addons[ADDON].preferences
        self.assertEqual(json.loads(prefs.saved_navigation)["use_zoom_to_mouse"], False)

    def test_user_preset_installed(self):
        user_dir = bpy.utils.user_resource('SCRIPTS', path=os.path.join("presets", "keyconfig"))
        path = os.path.join(user_dir, KC_NAME + ".py")
        self.assertTrue(os.path.exists(path))
        # Listed once: the add-on's own copy is no longer registered as a preset path.
        listed = [d for d in bpy.utils.preset_paths("keyconfig") if os.path.exists(os.path.join(d, KC_NAME + ".py"))]
        self.assertEqual(len(listed), 1, listed)

    def test_expected_bindings(self):
        for keymap, idname, event_type, value, mods, props in EXPECTED:
            with self.subTest(keymap=keymap, idname=idname, type=event_type, mods=mods, props=props):
                self.assertTrue(find_items(self.kc, keymap, idname, event_type, value, **mods, **props))

    def test_removed_bindings(self):
        for keymap, event_type, value, mods, idname in REMOVED:
            with self.subTest(keymap=keymap, type=event_type, mods=mods, idname=idname):
                self.assertFalse(find_items(self.kc, keymap, idname, event_type, value, **mods))

    def test_max_keys_win_in_viewport_keymaps(self):
        # No other binding of the Max keys in the viewport key-maps that are checked before "3D View".
        for keymap in ("Object Mode", "Mesh", "Object Non-modal", "3D View Generic", "Pose", "Curve"):
            for key in "QWERTBFLPUCZGHSAXM":
                with self.subTest(keymap=keymap, key=key):
                    self.assertFalse(items_for_event(self.kc, keymap, key), [k.idname for k in items_for_event(
                        self.kc, keymap, key)])

    def test_first_item_wins(self):
        def index(km, idname, event_type, value='PRESS'):
            for i, kmi in enumerate(self.kc.keymaps[km].keymap_items):
                if kmi.idname == idname and kmi.type == event_type and kmi.value == value:
                    return i
            self.fail("{:s} not in {:s}".format(idname, km))
        # The selection lock guard runs before click selection, the lock toggle before Space-to-play.
        self.assertLess(index("3D View", "mx_keymap.selection_lock_guard", 'LEFTMOUSE', 'CLICK'),
                        index("3D View", "view3d.select", 'LEFTMOUSE', 'CLICK'))
        self.assertLess(index("Frames", "mx_keymap.selection_lock_toggle", 'SPACE'),
                        index("Frames", "screen.animation_play", 'SPACE'))
        # Drag on an object is tried before the selection rectangle.
        fallback = "3D View Tool: Select Box (fallback)"
        self.assertLess(index(fallback, "mx_keymap.select_drag", 'LEFTMOUSE', 'CLICK_DRAG'),
                        index(fallback, "view3d.select_box", 'LEFTMOUSE', 'CLICK_DRAG'))

    def test_shift_is_not_precision(self):
        km = self.kc.keymaps["Transform Modal Map"]
        self.assertFalse([kmi for kmi in km.keymap_items if kmi.propvalue == 'PRECISION'])
        self.assertTrue([kmi for kmi in km.keymap_items if kmi.propvalue == 'CONFIRM'])

    def test_operators_exist(self):
        for km in self.kc.keymaps:
            if km.is_modal:
                continue
            for kmi in km.keymap_items:
                if kmi.idname.startswith("mx_keymap."):
                    with self.subTest(idname=kmi.idname):
                        module, name = kmi.idname.split(".")
                        getattr(getattr(bpy.ops, module), name).get_rna_type()

    def test_startup_reload_fills_without_touching_preferences(self):
        # Blender reloads the active preset at startup (and when input preferences change), before add-ons are
        # registered; that must not count as an activation.
        set_blender_navigation()
        bpy.utils.keyconfig_init()
        kc = bpy.context.window_manager.keyconfigs.active
        self.assertEqual(kc.name, KC_NAME)
        self.assertTrue(find_items(kc, "3D View", "mx_keymap.zoom_extents", 'Z'))
        self.assertEqual(navigation_state()["use_zoom_to_mouse"], False)
        type(self).kc = kc

    def test_script_reload_keeps_keymap(self):
        # A script reload unregisters and registers the add-on without changing the preferences.
        addon_utils.disable(ADDON)
        kc = bpy.context.window_manager.keyconfigs.active
        self.assertEqual(kc.name, KC_NAME)
        self.assertEqual(len(kc.keymaps), 0)
        addon_utils.enable(ADDON)
        kc = bpy.context.window_manager.keyconfigs.active
        self.assertEqual(kc.name, KC_NAME)
        self.assertTrue(find_items(kc, "3D View", "mx_keymap.zoom_extents", 'Z'))
        type(self).kc = kc

    def test_fork_preset_loads(self):
        path = os.path.join(os.environ["MX_TEST_ROOT"], "scripts", "presets", "keyconfig", KC_NAME + ".py")
        self.assertTrue(bpy.utils.keyconfig_set(path))
        kc = bpy.context.window_manager.keyconfigs.active
        self.assertEqual(kc.name, KC_NAME)
        self.assertTrue(find_items(kc, "3D View", "mx_keymap.subobject_level", 'ONE', level=1))
        type(self).kc = kc


class C_ActivationOptionsTest(unittest.TestCase):

    def setUp(self):
        enable()
        use_blender_keyconfig()

    def tearDown(self):
        use_blender_keyconfig()
        disable()

    def test_navigation_preference_off(self):
        prefs = bpy.context.preferences.addons[ADDON].preferences
        prefs.apply_navigation = False
        try:
            set_blender_navigation()
            before = navigation_state()
            self.assertEqual(bpy.ops.mx_keymap.keyconfig_activate(), {'FINISHED'})
            self.assertEqual(navigation_state(), before)
        finally:
            prefs.apply_navigation = True

    def test_restore_navigation(self):
        prefs = bpy.context.preferences.addons[ADDON].preferences
        prefs.saved_navigation = json.dumps({"use_zoom_to_mouse": False, "use_rotate_around_active": False})
        bpy.context.preferences.inputs.use_zoom_to_mouse = True
        self.assertEqual(bpy.ops.mx_keymap.navigation_restore(), {'FINISHED'})
        self.assertFalse(bpy.context.preferences.inputs.use_zoom_to_mouse)
        self.assertEqual(prefs.saved_navigation, "")

    def test_menu_activation_from_addon_preset(self):
        # Picking the preset in Preferences > Keymap runs it through `preferences.keyconfig_activate`.
        from mx_keymap import keyconfig
        set_blender_navigation()
        self.assertEqual(bpy.ops.preferences.keyconfig_activate(filepath=keyconfig.ADDON_PRESET), {'FINISHED'})
        self.assertEqual(bpy.context.window_manager.keyconfigs.active.name, KC_NAME)
        self.assertTrue(navigation_state()["use_zoom_to_mouse"])


def new_mesh_object(name, bm_fn, location=(0.0, 0.0, 0.0)):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bm_fn(bm)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    ob.location = location
    bpy.context.scene.collection.objects.link(ob)
    # Evaluate `matrix_world`.
    bpy.context.view_layer.update()
    return ob


def make_active(ob):
    view_layer = bpy.context.view_layer
    for other in view_layer.objects:
        other.select_set(False)
    ob.select_set(True)
    view_layer.objects.active = ob


class D_SubObjectTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        enable()

    @classmethod
    def tearDownClass(cls):
        disable()

    def setUp(self):
        if bpy.context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        # A 3x3 grid (open borders) and a separate quad, in one mesh.
        def build(bm):
            bmesh.ops.create_grid(bm, x_segments=3, y_segments=3, size=1.0)
            verts = [bm.verts.new(co) for co in ((5, 0, 0), (6, 0, 0), (6, 1, 0), (5, 1, 0))]
            bm.faces.new(verts)
        self.ob = new_mesh_object("SubObj", build)
        make_active(self.ob)

    def tearDown(self):
        if bpy.context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        bpy.data.objects.remove(self.ob)

    def level(self, level):
        self.assertEqual(bpy.ops.mx_keymap.subobject_level(level=level), {'FINISHED'})

    def select_mode(self):
        return tuple(bpy.context.tool_settings.mesh_select_mode)

    def test_levels(self):
        from mx_keymap import subobject
        self.level(1)
        self.assertEqual(bpy.context.mode, 'EDIT_MESH')
        self.assertEqual(self.select_mode(), (True, False, False))
        self.level(2)
        self.assertEqual(self.select_mode(), (False, True, False))
        self.assertEqual(subobject.current_level(bpy.context), 2)
        self.level(4)
        self.assertEqual(self.select_mode(), (False, False, True))
        self.level(6)
        self.assertEqual(bpy.context.mode, 'OBJECT')
        self.assertEqual(subobject.current_level(bpy.context), 0)

    def test_same_level_again_returns_to_object_level(self):
        self.level(2)
        self.level(2)
        self.assertEqual(bpy.context.mode, 'OBJECT')

    def test_border_level(self):
        from mx_keymap import subobject
        self.level(2)
        bm = bmesh.from_edit_mesh(self.ob.data)
        for e in bm.edges:
            e.select_set(False)
        boundary = [e for e in bm.edges if e.is_boundary]
        interior = [e for e in bm.edges if not e.is_boundary]
        # One edge of the grid's outer border, plus an interior edge.
        grid_border = [e for e in boundary if max(v.co.x for v in e.verts) < 2.0]
        grid_border[0].select_set(True)
        interior[0].select_set(True)
        bmesh.update_edit_mesh(self.ob.data)
        self.level(3)
        self.assertEqual(subobject.current_level(bpy.context), 3)
        bm = bmesh.from_edit_mesh(self.ob.data)
        selected = {e.index for e in bm.edges if e.select}
        # The whole outer loop of the grid (12 edges), not the interior edge nor the separate quad.
        self.assertEqual(len(selected), len(grid_border))
        self.assertEqual(selected, {e.index for e in bm.edges if e.is_boundary and max(v.co.x for v in e.verts) < 2})

    def test_element_level(self):
        self.level(4)
        bm = bmesh.from_edit_mesh(self.ob.data)
        for f in bm.faces:
            f.select_set(False)
        bm.faces.ensure_lookup_table()
        bm.faces[0].select_set(True)
        bmesh.update_edit_mesh(self.ob.data)
        self.level(5)
        bm = bmesh.from_edit_mesh(self.ob.data)
        # The 9 grid faces (the connected element), not the separate quad.
        self.assertEqual(sum(f.select for f in bm.faces), 9)

    def test_no_levels_for_empties(self):
        empty = bpy.data.objects.new("Helper", None)
        bpy.context.scene.collection.objects.link(empty)
        make_active(empty)
        try:
            self.assertEqual(bpy.ops.mx_keymap.subobject_level(level=1), {'CANCELLED'})
        finally:
            bpy.data.objects.remove(empty)


class E_SelectionTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        enable()

    @classmethod
    def tearDownClass(cls):
        from mx_keymap import selection
        selection.set_selection_locked(bpy.context, False)
        disable()

    def test_filter_names(self):
        from mx_keymap.selection import filter_names
        names = ["Box001", "Box002", "Sphere001", "box_lid"]
        self.assertEqual(filter_names(names, ""), names)
        self.assertEqual(filter_names(names, "box"), ["Box001", "Box002", "box_lid"])
        self.assertEqual(filter_names(names, "Box00?"), ["Box001", "Box002"])
        self.assertEqual(filter_names(names, "*001"), ["Box001", "Sphere001"])

    def test_select_by_name(self):
        from mx_keymap import selection
        a = bpy.data.objects.new("SbnA", None)
        b = bpy.data.objects.new("SbnB", None)
        for ob in (a, b):
            bpy.context.scene.collection.objects.link(ob)
        try:
            make_active(a)
            selection.fill_name_list(bpy.context)
            items = bpy.context.window_manager.mx_keymap_select_by_name_items
            names = [item.name for item in items]
            self.assertIn("SbnA", names)
            self.assertEqual(names, sorted(names, key=str.lower))
            self.assertTrue(items["SbnA"].select)
            items["SbnA"].select = False
            items["SbnB"].select = True
            self.assertEqual(bpy.ops.mx_keymap.select_by_name('EXEC_DEFAULT'), {'FINISHED'})
            self.assertEqual([ob.name for ob in bpy.context.selected_objects], ["SbnB"])
            self.assertEqual(bpy.context.view_layer.objects.active, b)
            # Multi-select, extend.
            selection.select_objects_by_name(bpy.context.view_layer, ["SbnA"], extend=True)
            self.assertEqual({ob.name for ob in bpy.context.selected_objects}, {"SbnA", "SbnB"})
        finally:
            bpy.data.objects.remove(a)
            bpy.data.objects.remove(b)

    def test_lock_selection(self):
        from mx_keymap import selection
        override = view3d_override()
        selection.set_selection_locked(bpy.context, False)
        with bpy.context.temp_override(**override):
            self.assertFalse(bpy.ops.mx_keymap.selection_lock_guard.poll())
            self.assertEqual(bpy.ops.mx_keymap.selection_lock_toggle(), {'FINISHED'})
            self.assertTrue(selection.is_selection_locked(bpy.context))
            # While locked, the guard in front of every click-select item swallows the click.
            self.assertTrue(bpy.ops.mx_keymap.selection_lock_guard.poll())
            self.assertEqual(bpy.ops.mx_keymap.selection_lock_toggle(), {'FINISHED'})
        self.assertFalse(selection.is_selection_locked(bpy.context))
        # Outside the 3D viewport, Space plays animation instead.
        self.assertFalse(bpy.ops.mx_keymap.selection_lock_toggle.poll())


class F_CloneTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        enable()

    @classmethod
    def tearDownClass(cls):
        disable()

    def setUp(self):
        self.objects_before = set(bpy.data.objects.keys())
        self.box = new_mesh_object("Box001", lambda bm: bmesh.ops.create_cube(bm, size=1.0), location=(1, 2, 3))

    def tearDown(self):
        from mx_keymap import clone
        clone.cancel_pending(bpy.context)
        for name in set(bpy.data.objects.keys()) - self.objects_before:
            bpy.data.objects.remove(bpy.data.objects[name])

    def test_names(self):
        from mx_keymap.clone import next_clone_names, first_clone_names
        self.assertEqual(next_clone_names("Box001", 2, {"Box001"}), ["Box002", "Box003"])
        self.assertEqual(next_clone_names("Box001", 1, {"Box001", "Box002"}), ["Box003"])
        self.assertEqual(next_clone_names("Teapot", 1, set()), ["Teapot001"])
        self.assertEqual(next_clone_names("Cube.001", 1, set()), ["Cube.002"])
        self.assertEqual(first_clone_names("Pillar", 3, {"Pillar"}), ["Pillar001", "Pillar002", "Pillar003"])
        self.assertEqual(first_clone_names("Column", 2, set()), ["Column", "Column001"])

    def test_copy_cumulative(self):
        from mx_keymap.clone import make_clones
        copies = make_clones([self.box], mode='COPY', count=3, delta=Matrix.Translation((2, 0, 0)))
        self.assertEqual([c[0].name for c in copies], ["Box002", "Box003", "Box004"])
        for i, (ob,) in enumerate(copies, start=1):
            self.assertAlmostEqual((ob.matrix_world.translation - Vector((1 + 2 * i, 2, 3))).length, 0.0, places=5)
            self.assertIsNot(ob.data, self.box.data)
            self.assertEqual(set(ob.users_collection), set(self.box.users_collection))
        self.assertEqual(self.box.location, Vector((1, 2, 3)))

    def test_instance_shares_data(self):
        from mx_keymap.clone import make_clones
        for mode in ('INSTANCE', 'REFERENCE'):
            copies = make_clones([self.box], mode=mode, count=2, delta=Matrix.Translation((0, 0, 1)))
            for (ob,) in copies:
                self.assertIs(ob.data, self.box.data)

    def test_rotation_is_cumulative(self):
        from math import radians
        from mx_keymap.clone import make_clones
        self.box.location = (1, 0, 0)
        bpy.context.view_layer.update()
        delta = Matrix.Rotation(radians(90), 4, 'Z')
        copies = make_clones([self.box], mode='INSTANCE', count=2, delta=delta)
        self.assertAlmostEqual((copies[0][0].matrix_world.translation - Vector((0, 1, 0))).length, 0.0, places=5)
        self.assertAlmostEqual((copies[1][0].matrix_world.translation - Vector((-1, 0, 0))).length, 0.0, places=5)

    def test_hierarchy(self):
        from mx_keymap.clone import make_clones
        child = bpy.data.objects.new("Lid", None)
        bpy.context.scene.collection.objects.link(child)
        child.parent = self.box
        copies = make_clones([self.box, child], mode='INSTANCE', count=2, delta=Matrix.Translation((5, 0, 0)))
        for parent_copy, child_copy in copies:
            self.assertIs(child_copy.parent, parent_copy)

    def test_drag_then_dialog(self):
        from mx_keymap import clone
        make_active(self.box)
        previews = clone.begin_pending(bpy.context, [self.box])
        preview_names = [ob.name for ob in previews]
        self.assertEqual(bpy.context.selected_objects, previews)
        # What the interactive move would do.
        previews[0].matrix_world = Matrix.Translation((0, 3, 0)) @ previews[0].matrix_world
        self.assertTrue(clone.end_drag(bpy.context))
        self.assertEqual(
            bpy.ops.mx_keymap.clone_options('EXEC_DEFAULT', clone_type='INSTANCE', count=2, name="Pillar"),
            {'FINISHED'})
        self.assertFalse(clone.pending())
        self.assertFalse(set(preview_names) & set(bpy.data.objects.keys()))
        new = [ob for ob in bpy.data.objects if ob.name.startswith("Pillar")]
        self.assertEqual(sorted(ob.name for ob in new), ["Pillar", "Pillar001"])
        by_name = {ob.name: ob for ob in new}
        self.assertAlmostEqual(by_name["Pillar"].location.y, 5.0, places=5)
        self.assertAlmostEqual(by_name["Pillar001"].location.y, 8.0, places=5)
        self.assertIs(by_name["Pillar"].data, self.box.data)
        self.assertEqual(self.box.location, Vector((1, 2, 3)))
        # The last copy is selected, like Max.
        self.assertEqual(bpy.context.selected_objects, [by_name["Pillar001"]])

    def test_clone_in_place(self):
        from mx_keymap import clone
        make_active(self.box)
        clone.begin_in_place(bpy.context, [self.box])
        # The number of copies is ignored when cloning in place.
        self.assertEqual(bpy.ops.mx_keymap.clone_options('EXEC_DEFAULT', clone_type='COPY', count=5), {'FINISHED'})
        new = [ob for ob in bpy.data.objects if ob.name.startswith("Box") and ob != self.box]
        self.assertEqual([ob.name for ob in new], ["Box002"])
        self.assertEqual(new[0].matrix_world, self.box.matrix_world)
        self.assertIsNot(new[0].data, self.box.data)

    def test_cancelled_drag(self):
        from mx_keymap import clone
        make_active(self.box)
        before = set(bpy.data.objects.keys())
        clone.begin_pending(bpy.context, [self.box])
        self.assertFalse(clone.end_drag(bpy.context))
        self.assertEqual(set(bpy.data.objects.keys()), before)
        self.assertEqual(bpy.context.selected_objects, [self.box])


class G_ViewTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        enable()

    @classmethod
    def tearDownClass(cls):
        disable()

    def test_snap_toggles(self):
        from mx_keymap.view import toggle_snap_state
        self.assertEqual(toggle_snap_state(False, True, False, 'SNAP'), (True, True, False))
        self.assertEqual(toggle_snap_state(False, True, False, 'ANGLE'), (True, False, True))
        self.assertEqual(toggle_snap_state(True, False, True, 'SNAP'), (True, True, True))
        self.assertEqual(toggle_snap_state(True, True, True, 'ANGLE'), (True, True, False))
        self.assertEqual(toggle_snap_state(True, False, True, 'ANGLE'), (False, True, False))
        ts = bpy.context.tool_settings
        ts.use_snap = False
        ts.use_snap_translate = True
        ts.use_snap_rotate = False
        self.assertEqual(bpy.ops.mx_keymap.snap_toggle(kind='ANGLE'), {'FINISHED'})
        self.assertEqual((ts.use_snap, ts.use_snap_translate, ts.use_snap_rotate), (True, False, True))
        self.assertEqual(bpy.ops.mx_keymap.snap_toggle(kind='ANGLE'), {'FINISHED'})
        self.assertEqual((ts.use_snap, ts.use_snap_translate, ts.use_snap_rotate), (False, True, False))

    def test_projection(self):
        from mx_keymap.view import set_projection
        override = view3d_override()
        rv3d = override["area"].spaces.active.region_3d
        set_projection(rv3d, 'ORTHO')
        self.assertEqual(rv3d.view_perspective, 'ORTHO')
        set_projection(rv3d, 'PERSP')
        self.assertEqual(rv3d.view_perspective, 'PERSP')
        camera = bpy.context.scene.camera
        rv3d.view_perspective = 'CAMERA'
        set_projection(rv3d, 'ORTHO', camera=camera)
        self.assertEqual(rv3d.view_perspective, 'ORTHO')
        # The camera's viewpoint is kept.
        self.assertAlmostEqual(
            rv3d.view_rotation.rotation_difference(camera.matrix_world.to_quaternion()).angle, 0.0, places=4)

    def test_view_operators(self):
        override = view3d_override()
        rv3d = override["area"].spaces.active.region_3d
        with bpy.context.temp_override(**override):
            rv3d.view_perspective = 'PERSP'
            # T: orthographic top view, whatever the projection was.
            self.assertEqual(bpy.ops.mx_keymap.view_axis(type='TOP'), {'FINISHED'})
            self.assertEqual(rv3d.view_perspective, 'ORTHO')
            self.assertAlmostEqual(rv3d.view_rotation.angle, 0.0, places=4)
            self.assertEqual(bpy.ops.mx_keymap.view_projection(mode='PERSP'), {'FINISHED'})
            self.assertEqual(rv3d.view_perspective, 'PERSP')
            # C: camera view; pressing it again stays in the camera.
            self.assertEqual(bpy.ops.mx_keymap.view_camera(), {'FINISHED'})
            self.assertEqual(rv3d.view_perspective, 'CAMERA')
            bpy.ops.mx_keymap.view_camera()
            self.assertEqual(rv3d.view_perspective, 'CAMERA')
            self.assertEqual(bpy.ops.mx_keymap.view_axis(type='FRONT'), {'FINISHED'})
            self.assertEqual(rv3d.view_perspective, 'ORTHO')
            for ob in bpy.context.view_layer.objects:
                ob.select_set(False)
            self.assertEqual(bpy.ops.mx_keymap.zoom_extents(), {'FINISHED'})

    def test_delete_subobject(self):
        ob = new_mesh_object("DeleteMe", lambda bm: bmesh.ops.create_cube(bm, size=1.0))
        make_active(ob)
        try:
            self.assertFalse(bpy.ops.mx_keymap.delete_subobject.poll())
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_mode(type='FACE')
            bm = bmesh.from_edit_mesh(ob.data)
            bm.faces.ensure_lookup_table()
            for f in bm.faces:
                f.select_set(False)
            bm.faces[0].select_set(True)
            bmesh.update_edit_mesh(ob.data)
            # Face level: Delete removes the selected face only, without a menu.
            self.assertEqual(bpy.ops.mx_keymap.delete_subobject(), {'FINISHED'})
            bpy.ops.object.mode_set(mode='OBJECT')
            self.assertEqual((len(ob.data.polygons), len(ob.data.vertices)), (5, 8))
        finally:
            if bpy.context.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            bpy.data.objects.remove(ob)

    def test_grid_toggle(self):
        override = view3d_override()
        overlay = override["area"].spaces.active.overlay
        overlay.show_floor = True
        overlay.show_ortho_grid = True
        with bpy.context.temp_override(**override):
            self.assertEqual(bpy.ops.mx_keymap.toggle_grid(), {'FINISHED'})
            self.assertFalse(overlay.show_floor or overlay.show_ortho_grid)
            bpy.ops.mx_keymap.toggle_grid()
            self.assertTrue(overlay.show_floor and overlay.show_ortho_grid)

    def test_zoom_extents_selection(self):
        from mx_keymap.view import has_selection
        view_layer = bpy.context.view_layer
        for ob in view_layer.objects:
            ob.select_set(False)
        self.assertFalse(has_selection(bpy.context))
        cube = bpy.data.objects["Cube"]
        make_active(cube)
        self.assertTrue(has_selection(bpy.context))
        bpy.ops.object.mode_set(mode='EDIT')
        try:
            bpy.ops.mesh.select_all(action='DESELECT')
            self.assertFalse(has_selection(bpy.context))
            bpy.ops.mesh.select_all(action='SELECT')
            self.assertTrue(has_selection(bpy.context))
        finally:
            bpy.ops.object.mode_set(mode='OBJECT')


class Z_DisableTest(unittest.TestCase):
    """Runs last: disabling the add-on for good gives Blender's keymap back."""

    def test_disable_switches_back(self):
        enable()
        self.assertEqual(bpy.ops.mx_keymap.keyconfig_activate(), {'FINISHED'})
        from mx_keymap import keyconfig
        disable()
        # Normally run from a timer right after the add-on is disabled.
        keyconfig.after_unregister()
        wm = bpy.context.window_manager
        self.assertIsNone(wm.keyconfigs.get(KC_NAME))
        self.assertEqual(wm.keyconfigs.active.name, "Blender")


if __name__ == "__main__":
    _runner_util.main()
