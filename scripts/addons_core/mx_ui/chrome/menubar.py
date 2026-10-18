# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
The Max-style menu bar: File, Edit, Tools, Group, Views, Create, Modifiers, Animation, Graph Editors,
Rendering, Civil View, Customize, Scripting, Interactive, Content and Help, with Max's items in Max's order.

While ``utils.use_max_chrome()`` is on, ``TOPBAR_MT_editor_menus.draw`` draws these menus instead of Blender's,
and the top bar no longer shows the workspace tabs (nor the scene and view layer selectors, which Max doesn't
have). Blender's ``draw`` functions are restored on unregister and drawn whenever the preference is off.

The menus are data (``MENUS``): every entry is an operator, a submenu, a viewport command, an editor window,
or a placeholder for a Max command that isn't implemented yet. Operators from our other add-ons are used when
those are enabled (``mx_keymap`` for the same behaviour as the hotkeys, ``mx_primitives`` for live primitives,
``mx_io_max`` for importing .max files), otherwise their entries fall back to Blender operators or
placeholders. The Menu classes are generated from the data, one per (sub)menu.
"""

import bpy
from bpy.types import Menu

from .. import utils
from .. import modifier_map
from ..placeholder import placeholder
from . import menu_ops


# -----------------------------------------------------------------------------
# Menu items

class Op:
    """An operator. ``fallback`` (an item) is drawn when the operator's add-on is not enabled."""
    __slots__ = ("idname", "text", "icon", "props", "fallback")

    def __init__(self, idname, text, icon='NONE', fallback=None, **props):
        self.idname = idname
        self.text = text
        self.icon = icon
        self.props = props
        self.fallback = fallback


class ViewOp(Op):
    """An operator run in the active 3D viewport (or in all of them) through ``mx_ui.viewport_call``."""
    __slots__ = ("all_viewports", "invoke")

    def __init__(self, idname, text, icon='NONE', fallback=None, all_viewports=False, invoke=False, **props):
        super().__init__(idname, text, icon, fallback, **props)
        self.all_viewports = all_viewports
        self.invoke = invoke


class Kind(Op):
    """An operator creating one ``kind`` of object, or a placeholder when that kind doesn't exist (yet)."""
    __slots__ = ()

    def __init__(self, idname, kind, text):
        super().__init__(idname, text, kind=kind)


class Mod:
    """A Max modifier from ``modifier_map``, looked up by name; a placeholder when it isn't available."""
    __slots__ = ("text",)

    def __init__(self, text):
        self.text = text


class Editor:
    """A button opening an editor window (``menu_ops.EDITOR_WINDOWS``)."""
    __slots__ = ("editor", "text", "props")

    def __init__(self, editor, text, **props):
        self.editor = editor
        self.text = text
        self.props = props


class Toggle:
    """A check box toggling a display option in every viewport (path relative to the 3D viewport space)."""
    __slots__ = ("path", "text")

    def __init__(self, path, text):
        self.path = path
        self.text = text


class Sub:
    """A submenu."""
    __slots__ = ("menu", "text")

    def __init__(self, menu, text):
        self.menu = menu
        self.text = text


class Ph:
    """A Max command that isn't implemented yet."""
    __slots__ = ("text",)

    def __init__(self, text):
        self.text = text


class Dyn:
    """Drawn by a function ``draw(layout, context)``, for entries that depend on the mode."""
    __slots__ = ("draw", "text")

    def __init__(self, draw, text):
        self.draw = draw
        self.text = text


SEP = None

MENU_PREFIX = "TOPBAR_MT_mx_"

# Menu idname → (label, items), filled by `_menu()` below.
MENUS = {}


def _menu(name, label, items):
    idname = MENU_PREFIX + name
    assert idname not in MENUS, idname
    MENUS[idname] = (label, items)
    return idname


def _sub(name, label, items):
    return Sub(_menu(name, label, items), label)


def _phs(*texts):
    return [Ph(text) for text in texts]


def _tool(tool_id, text):
    return Op("mx_ui.set_tool", text, name=tool_id)


# -----------------------------------------------------------------------------
# Availability

def _kind_available(item):
    kind = item.props["kind"]
    if kind not in menu_ops.operator_enum_values(item.idname, "kind"):
        return False
    if item.idname == "object.mx_create":
        # Lights, cameras and helpers listed in the Create panel without an implementation yet.
        try:
            from ..command_panel import create
            entry = create.OBJECTS_BY_KIND.get(kind)
        except (ImportError, AttributeError):
            entry = None
        if entry is not None and not entry[3]:
            return False
    return True


def _normalize(name):
    return "".join(ch for ch in name.lower() if ch.isalnum())


# Max menu names that differ from the Modifier List names.
_MODIFIER_ALIASES = {
    "normalmodifier": "normal",
    "renderablesplinemodifier": "renderablespline",
}


def modifier_entry(text):
    """The ``modifier_map`` entry for a Max modifier name, or None."""
    key = _normalize(text)
    key = _MODIFIER_ALIASES.get(key, key)
    for entry in modifier_map.MODIFIERS:
        if _normalize(entry.label) == key:
            return entry
    return None


# -----------------------------------------------------------------------------
# Mode-dependent entries

def _select_all(action, text):
    def draw(layout, context):
        mode = getattr(context, "mode", 'OBJECT')
        idname = {'EDIT_MESH': "mesh.select_all", 'EDIT_CURVE': "curve.select_all"}.get(mode, "object.select_all")
        layout.operator(idname, text=text).action = action
    return Dyn(draw, text)


def _draw_delete(layout, context):
    mode = getattr(context, "mode", 'OBJECT')
    if mode == 'EDIT_MESH':
        if menu_ops.has_operator("mx_keymap.delete_subobject"):
            layout.operator("mx_keymap.delete_subobject", text="Delete")
        else:
            layout.operator("mesh.delete", text="Delete").type = 'VERT'
    elif mode == 'EDIT_CURVE':
        layout.operator("curve.delete", text="Delete").type = 'VERT'
    else:
        op = layout.operator("object.delete", text="Delete")
        op.use_global = False
        op.confirm = False


def _draw_select_similar(layout, context):
    if getattr(context, "mode", 'OBJECT') == 'EDIT_MESH':
        layout.menu("VIEW3D_MT_edit_mesh_select_similar", text="Select Similar")
    else:
        layout.operator("object.select_grouped", text="Select Similar").type = 'TYPE'


def _crossing(value, text):
    def draw(layout, context):
        state = utils.get_state(context)
        current = bool(getattr(state, "select_crossing", False))
        op = layout.operator("wm.context_set_boolean", text=text,
                             icon='RADIOBUT_ON' if current == value else 'RADIOBUT_OFF')
        op.data_path = "window_manager.mx_ui.select_crossing"
        op.value = value
    return Dyn(draw, text)


# -----------------------------------------------------------------------------
# The menus, in Max's order

def _primitive(kind, text):
    return Kind(utils.PRIMITIVE_OPERATOR_IDNAME, kind, text)


def _shape(kind, text):
    return Kind("curve.mx_shape_add", kind, text)


def _object(kind, text):
    return Kind("object.mx_create", kind, text)


_SELECTION_REGION = _sub("edit_selection_region", "Selection Region", [
    _tool("builtin.select_box", "Rectangular Region"),
    Ph("Circular Region"),
    Ph("Fence Region"),
    _tool("builtin.select_lasso", "Lasso Region"),
    _tool("builtin.select_circle", "Paint Selection Region"),
    SEP,
    _crossing(False, "Window"),
    _crossing(True, "Crossing"),
])

_ALIGN = [
    Op("object.align", "Align...", relative_to='OPT_4'),
    Op("view3d.snap_selected_to_active", "Quick Align"),
    Ph("Spacing Tool..."),
    Ph("Clone and Align..."),
    SEP,
    Ph("Normal Align..."),
    Ph("Place Highlight"),
    Ph("Align Camera"),
    Ph("Align to View..."),
]

FILE = _menu("file", "File", [
    _sub("file_new", "New", [
        Op("wm.read_homefile", "New All", use_empty=True),
        Ph("Keep Objects"),
        Ph("Keep Objects and Hierarchy"),
        SEP,
        Sub("TOPBAR_MT_file_new", "New from Template"),
    ]),
    Op("wm.read_homefile", "Reset"),
    Op("wm.open_mainfile", "Open..."),
    Sub("TOPBAR_MT_file_open_recent", "Open Recent"),
    Editor('IMAGE', "View Image File..."),
    SEP,
    Op("wm.save_mainfile", "Save"),
    Op("wm.save_as_mainfile", "Save As..."),
    Op("wm.save_as_mainfile", "Save Copy As...", copy=True),
    Ph("Save Selected..."),
    Ph("Archive..."),
    SEP,
    _sub("file_import", "Import", [
        Op("import_scene.mx_max", "Import...", fallback=Sub("TOPBAR_MT_file_import", "Import...")),
        Op("wm.append", "Merge..."),
        Ph("Replace..."),
        SEP,
        Sub("TOPBAR_MT_file_import", "Other Formats"),
    ]),
    _sub("file_export", "Export", [
        Sub("TOPBAR_MT_file_export", "Export..."),
        Ph("Export Selected..."),
    ]),
    SEP,
    _sub("file_reference", "Reference", [
        Op("wm.link", "XRef Objects..."),
        Op("wm.link", "XRef Scene..."),
        SEP,
        Ph("Inherit Container..."),
        SEP,
        Sub("TOPBAR_MT_file_external_data", "Asset Tracking"),
        Ph("File Link Manager..."),
    ]),
    _sub("file_project", "Project", _phs(
        "Create Default Project...", "Create Project from Current...", "Create Empty...",
        "Set Active Project...")),
    SEP,
    Ph("Summary Info..."),
    Ph("File Properties..."),
    SEP,
    Op("wm.quit_blender", "Exit"),
])

EDIT = _menu("edit", "Edit", [
    Op("ed.undo", "Undo"),
    Op("ed.redo", "Redo"),
    Ph("Hold"),
    Ph("Fetch"),
    SEP,
    Dyn(_draw_delete, "Delete"),
    Op("mx_keymap.clone", "Clone", fallback=Op("object.duplicate", "Clone")),
    _tool("builtin.move", "Move"),
    _tool("builtin.rotate", "Rotate"),
    _tool("builtin.scale", "Scale"),
    Ph("Placement"),
    Ph("Transform Toolbox..."),
    SEP,
    _select_all('SELECT', "Select All"),
    _select_all('DESELECT', "Select None"),
    _select_all('INVERT', "Select Invert"),
    Dyn(_draw_select_similar, "Select Similar"),
    Op("object.select_linked", "Select Instances", type='OBDATA'),
    _sub("edit_select_by", "Select By", [
        Op("object.select_grouped", "Color", type='COLOR'),
        Op("mx_keymap.select_by_name", "Name...", fallback=Op("object.select_pattern", "Name...")),
        Op("object.select_grouped", "Layer", type='COLLECTION'),
    ]),
    _SELECTION_REGION,
    SEP,
    Ph("Manage Selection Sets..."),
    SEP,
    Op("wm.call_panel", "Object Properties...", name="VIEW3D_PT_mx_object_properties", keep_open=True),
])

TOOLS = _menu("tools", "Tools", [
    Editor('EXPLORER', "Scene Explorer..."),
    Editor('EXPLORER', "Layer Explorer..."),
    _sub("tools_global_explorers", "All Global Explorers", _phs("Scene Explorer", "Layer Explorer")),
    _sub("tools_local_explorers", "Local Scene Explorers", _phs("New Local Scene Explorer")),
    Ph("Manage Local Explorers..."),
    _sub("tools_containers", "Containers", _phs(
        "Container Explorer...", "Create Container from Selection", "Inherit Container...",
        "Add Selected to Container", "Remove Selected from Container", "Open", "Close", "Save", "Update")),
    SEP,
    Op("mx_ui.isolate_selection", "Isolate Selection"),
    Op("mx_ui.isolate_selection", "End Isolate", end=True),
    SEP,
    Ph("Display Floater..."),
    Ph("Manage Scene States..."),
    Ph("Light Lister..."),
    SEP,
    Op("object.mx_mirror", "Mirror..."),
    Ph("Array..."),
    _sub("tools_align", "Align", _ALIGN),
    Ph("Snapshot..."),
    Op("wm.batch_rename", "Rename Objects..."),
    Ph("Assign Vertex Colors..."),
    Ph("Color Clipboard..."),
    Ph("Camera Match..."),
    Ph("Viewport Canvas..."),
    _sub("tools_grab_viewport", "Grab Viewport", [
        ViewOp("render.opengl", "Create Animated Sequence File...", invoke=True, animation=True),
        ViewOp("render.opengl", "Capture Static Image of Active Viewport...", invoke=True),
    ]),
    _sub("tools_grids_and_snaps", "Grids and Snaps", [
        Op("wm.call_panel", "Grid and Snap Settings...", name="VIEW3D_PT_snapping", keep_open=True),
        SEP,
        ViewOp("mx_keymap.toggle_grid", "Show Home Grid", all_viewports=True,
               fallback=Toggle("overlay.show_floor", "Show Home Grid")),
        Ph("Activate Home Grid"),
        Ph("Activate Grid Object"),
        Ph("Align Grid to View"),
    ]),
    SEP,
    Ph("Measure Distance"),
    Ph("Channel Info..."),
])

GROUP = _menu("group", "Group", [
    Op("object.mx_group", "Group..."),
    Op("object.mx_ungroup", "Ungroup"),
    Ph("Open"),
    Ph("Open Recursively"),
    Ph("Close"),
    Op("object.mx_group_attach", "Attach"),
    Op("object.mx_group_detach", "Detach"),
    Ph("Explode"),
    SEP,
    _sub("group_assembly", "Assembly", _phs(
        "Assemble...", "Disassemble", "Open", "Close", "Attach", "Detach", "Explode")),
])


def _view_axis(kind, text):
    return ViewOp("mx_keymap.view_axis", text, type=kind, fallback=ViewOp("view3d.view_axis", text, type=kind))


VIEWS = _menu("views", "Views", [
    Ph("Undo View Change"),
    Ph("Redo View Change"),
    SEP,
    Ph("Viewport Configuration..."),
    Op("mx_ui.redraw_views", "Redraw All Views"),
    _sub("views_set_active", "Set Active Viewport", [
        ViewOp("mx_keymap.view_projection", "Perspective", mode='PERSP',
               fallback=ViewOp("view3d.view_persportho", "Perspective / Orthographic")),
        ViewOp("mx_keymap.view_projection", "Orthographic", mode='ORTHO',
               fallback=ViewOp("view3d.view_persportho", "Perspective / Orthographic")),
        _view_axis('FRONT', "Front"),
        _view_axis('BACK', "Back"),
        _view_axis('TOP', "Top"),
        _view_axis('BOTTOM', "Bottom"),
        _view_axis('LEFT', "Left"),
        _view_axis('RIGHT', "Right"),
        ViewOp("mx_keymap.view_camera", "Camera", fallback=ViewOp("view3d.view_camera", "Camera")),
    ]),
    Ph("Save Active Perspective View"),
    Ph("Restore Active Perspective View"),
    SEP,
    _sub("views_viewcube", "ViewCube", _phs("Show the ViewCube", "Show for Active View Only", "Configure...")),
    _sub("views_steeringwheels", "SteeringWheels", _phs("Toggle SteeringWheels", "Configure...")),
    SEP,
    Op("object.mx_camera_from_view", "Create Standard Camera From View"),
    Op("object.mx_camera_from_view", "Create Physical Camera From View", physical=True),
    Ph("Add Default Lights to Scene"),
    SEP,
    _sub("views_materials", "Show Materials in Viewport As", _phs(
        "Shaded Materials", "Shaded Materials with Maps", "Realistic Materials", "Realistic Materials with Maps")),
    _sub("views_lighting", "Viewport Lighting and Shadows", _phs(
        "Default Lights", "Scene Lights", "Shadows", "Ambient Occlusion")),
    _sub("views_xview", "xView", [
        Toggle("overlay.show_stats", "Show Statistics"),
        SEP,
        *_phs("Face Normals", "Face Orientation", "Isolated Vertices", "Open Edges", "Overlapping Faces"),
    ]),
    _sub("views_background", "Viewport Background", _phs(
        "Gradient Color", "Solid Color", "Environment Background", "Custom Image File",
        "Configure Viewport Background...")),
    SEP,
    Toggle("show_gizmo", "Show Transform Gizmo"),
    Ph("Show Ghosting"),
    Ph("Show Key Times"),
    Ph("Shade Selected"),
    Ph("Show Dependencies"),
    SEP,
    Ph("Update During Spinner Drag"),
    Ph("Progressive Display"),
    ViewOp("screen.screen_full_area", "Expert Mode", use_hide_panels=True),
])

CREATE = _menu("create", "Create", [
    _sub("create_standard_primitives", "Standard Primitives", [
        _primitive('BOX', "Box"),
        _primitive('CONE', "Cone"),
        _primitive('SPHERE', "Sphere"),
        _primitive('GEOSPHERE', "GeoSphere"),
        _primitive('CYLINDER', "Cylinder"),
        _primitive('TUBE', "Tube"),
        _primitive('TORUS', "Torus"),
        _primitive('PYRAMID', "Pyramid"),
        _primitive('TEST_SHAPE', "Test Shape"),
        _primitive('PLANE', "Plane"),
        _shape('TEXT', "TextPlus"),
    ]),
    _sub("create_extended_primitives", "Extended Primitives", [
        _primitive(kind, text) for kind, text in (
            ('HEDRA', "Hedra"), ('TORUS_KNOT', "Torus Knot"), ('CHAMFER_BOX', "ChamferBox"),
            ('CHAMFER_CYL', "ChamferCyl"), ('OIL_TANK', "OilTank"), ('CAPSULE', "Capsule"),
            ('SPINDLE', "Spindle"), ('L_EXT', "L-Extrusion"), ('GENGON', "Gengon"), ('C_EXT', "C-Extrusion"),
            ('RING_WAVE', "RingWave"), ('HOSE', "Hose"), ('PRISM', "Prism"),
        )
    ]),
    _sub("create_aec", "AEC Objects", _phs(
        "Foliage", "Railing", "Wall", "Doors", "Windows", "Stairs")),
    _sub("create_compound", "Compound", [
        *_phs("Morph", "Scatter", "Conform", "Connect", "BlobMesh", "ShapeMerge", "Terrain", "Loft", "Mesher",
              "ProBoolean", "ProCutter"),
        Op("object.mx_modifier_add", "Boolean", kind='BOOLEAN', fallback=Ph("Boolean")),
    ]),
    _sub("create_particles", "Particles", _phs(
        "Particle Flow Source", "Spray", "Snow", "Super Spray", "Blizzard", "PArray", "PCloud")),
    _sub("create_patch_grids", "Patch Grids", _phs("Quad Patch", "Tri Patch")),
    _sub("create_nurbs", "NURBS", [
        Op("surface.primitive_nurbs_surface_surface_add", "CV Surface"),
        Ph("Point Surface"),
        Op("curve.primitive_nurbs_curve_add", "CV Curve"),
        Ph("Point Curve"),
    ]),
    _sub("create_dynamics", "Dynamics", _phs("Damper", "Spring")),
    SEP,
    _sub("create_shapes", "Shapes", [
        _shape(kind, text) for kind, text in (
            ('LINE', "Line"), ('RECTANGLE', "Rectangle"), ('CIRCLE', "Circle"), ('ELLIPSE', "Ellipse"),
            ('ARC', "Arc"), ('DONUT', "Donut"), ('NGON', "NGon"), ('STAR', "Star"), ('TEXT', "Text"),
            ('HELIX', "Helix"), ('EGG', "Egg"), ('SECTION', "Section"), ('FREEHAND', "Freehand"),
        )
    ]),
    _sub("create_extended_shapes", "Extended Shapes", _phs(
        "WRectangle", "Channel", "Angle", "Tee", "Wide Flange")),
    SEP,
    _sub("create_lights", "Lights", [
        _sub("create_lights_standard", "Standard Lights", [
            _object('TARGET_SPOT', "Target Spotlight"),
            _object('FREE_SPOT', "Free Spotlight"),
            _object('TARGET_DIRECT', "Target Directional"),
            _object('FREE_DIRECT', "Directional"),
            _object('OMNI', "Omni"),
            _object('SKYLIGHT', "Skylight"),
        ]),
        _sub("create_lights_photometric", "Photometric Lights", [
            _object('TARGET_LIGHT', "Target Light"),
            _object('FREE_LIGHT', "Free Light"),
            _object('SUN_POSITIONER', "Sun Positioner"),
        ]),
        Ph("Daylight System"),
    ]),
    _sub("create_cameras", "Cameras", [
        _object('PHYSICAL_CAMERA', "Physical Camera"),
        _object('TARGET_CAMERA', "Target Camera"),
        _object('FREE_CAMERA', "Free Camera"),
        SEP,
        Op("object.mx_camera_from_view", "Create Physical Camera From View", physical=True),
    ]),
    _sub("create_helpers", "Helpers", [
        _object('DUMMY', "Dummy"),
        _object('POINT', "Point"),
        _object('GRID', "Grid"),
        _object('TAPE', "Tape Measure"),
        *_phs("Protractor", "Compass", "ExposeTransform", "Container"),
    ]),
    _sub("create_spacewarps", "SpaceWarps", [
        _sub("create_spacewarps_forces", "Forces", _phs(
            "Motor", "Push", "Vortex", "Drag", "PBomb", "Path Follow", "Displace", "Gravity", "Wind")),
        _sub("create_spacewarps_deflectors", "Deflectors", _phs(
            "POmniFlect", "PDynaFlect", "SOmniFlect", "UOmniFlect", "Deflector")),
        _sub("create_spacewarps_geometric", "Geometric/Deformable", _phs(
            "FFD(Box)", "FFD(Cyl)", "Wave", "Ripple", "Displace", "Conform", "Bomb")),
        _sub("create_spacewarps_modifier_based", "Modifier-Based", _phs(
            "Bend", "Noise", "Skew", "Taper", "Twist", "Stretch")),
    ]),
    _sub("create_systems", "Systems", [
        Op("object.armature_add", "Bones IK Chain"),
        *_phs("Daylight System", "Biped"),
    ]),
])


def _mods(*names):
    return [Mod(name) for name in names]


MODIFIERS = _menu("modifiers", "Modifiers", [
    _sub("modifiers_selection", "Selection", _mods(
        "FFD Select", "Mesh Select", "Patch Select", "Poly Select", "Select By Channel", "Spline Select",
        "Volume Select")),
    _sub("modifiers_patch_spline", "Patch/Spline Editing", _mods(
        "Cross Section", "Delete Patch", "Delete Spline", "Edit Patch", "Edit Spline", "Fillet/Chamfer", "Lathe",
        "Normalize Spline", "Renderable Spline Modifier", "Surface", "Sweep", "Trim/Extend")),
    _sub("modifiers_mesh_editing", "Mesh Editing", _mods(
        "Boolean", "Cap Holes", "Chamfer", "Delete Mesh", "Edit Mesh", "Edit Normals", "Edit Poly", "Extrude",
        "Face Extrude", "MultiRes", "Normal Modifier", "Optimize", "ProOptimizer", "Quadify Mesh", "Smooth",
        "STL Check", "Symmetry", "Tessellate", "Vertex Paint", "Vertex Weld", "Weighted Normals", "Weld")),
    _sub("modifiers_conversion", "Conversion", _mods("Turn to Mesh", "Turn to Patch", "Turn to Poly")),
    _sub("modifiers_animation", "Animation", _mods(
        "Attribute Holder", "Flex", "Linked XForm", "Melt", "Morpher", "Patch Deform", "Path Deform", "Skin",
        "Skin Morph", "Skin Wrap", "Skin Wrap Patch", "Spline IK Control", "Surf Deform")),
    _sub("modifiers_cloth", "Cloth", _mods("Cloth", "Garment Maker", "Welder")),
    _sub("modifiers_hair", "Hair and Fur", _mods("Hair and Fur (WSM)")),
    _sub("modifiers_uv", "UV Coordinates", _mods(
        "Camera Map", "MapScaler", "Projection", "Unwrap UVW", "UVW Map", "UVW Mapping Add", "UVW Mapping Clear",
        "UVW XForm")),
    _sub("modifiers_cache", "Cache Tools", _mods("Point Cache")),
    _sub("modifiers_subdivision", "Subdivision Surfaces", _mods("HSDS", "MeshSmooth", "OpenSubdiv", "TurboSmooth")),
    _sub("modifiers_ffd", "Free Form Deformers", _mods("FFD 2x2x2", "FFD 3x3x3", "FFD 4x4x4", "FFD (Box)",
                                                       "FFD (Cyl)")),
    _sub("modifiers_parametric", "Parametric Deformers", _mods(
        "Affect Region", "Array", "Bend", "Displace", "Lattice", "Mirror", "Noise", "Push", "Preserve", "Relax",
        "Ripple", "Shell", "Slice", "Skew", "Stretch", "Spherify", "Squeeze", "Twist", "Taper", "Substitute",
        "XForm", "Wave")),
    _sub("modifiers_surface", "Surface", _mods("Disp Approx", "Displace Mesh", "Material", "Material By Element")),
    _sub("modifiers_nurbs", "NURBS Editing", _mods("Disp Approx", "Surf Deform", "Surface Select")),
    _sub("modifiers_radiosity", "Radiosity", _mods("Subdivide")),
    _sub("modifiers_cameras", "Cameras", _mods("Camera Correction")),
])

ANIMATION = _menu("animation", "Animation", _phs(
    "Load Animation...", "Save Animation...", "IK Solvers", "Constraints", "Transform Controllers",
    "Parameter Editor...", "Wire Parameters", "Make Preview...", "Delete Selected Animation"))

GRAPH_EDITORS = _menu("graph_editors", "Graph Editors", [
    Editor('CURVE_EDITOR', "Track View - Curve Editor..."),
    Editor('DOPE_SHEET', "Track View - Dope Sheet..."),
    Ph("New Track View..."),
    SEP,
    Ph("New Schematic View..."),
    SEP,
    Ph("Particle View"),
    Ph("Motion Mixer..."),
])

RENDERING = _menu("rendering", "Rendering", [
    Op("render.render", "Render", use_viewport=True),
    Editor('RENDER_SETUP', "Render Setup..."),
    Op("render.view_show", "Rendered Frame Window..."),
    Ph("State Sets..."),
    Ph("Camera Sequencer..."),
    SEP,
    Editor('RENDER_SETUP', "Exposure Control..."),
    Editor('ENVIRONMENT', "Environment..."),
    Editor('COMPOSITOR', "Effects..."),
    SEP,
    Ph("Render To Texture..."),
    Ph("Bake to Texture..."),
    Ph("Render Surface Map..."),
    SEP,
    _sub("rendering_material_editor", "Material Editor", [
        Editor('MATERIAL', "Compact Material Editor..."),
        Editor('MATERIAL', "Slate Material Editor..."),
    ]),
    Ph("Material/Map Browser..."),
    Ph("Material Explorer..."),
    SEP,
    Editor('VIDEO_POST', "Video Post..."),
    SEP,
    Editor('IMAGE', "View Image File..."),
    Ph("Panorama Exporter..."),
    Ph("Batch Render..."),
    Editor('OUTPUT', "Print Size Assistant..."),
    Ph("Gamma/LUT Setup..."),
    Editor('MESSAGES', "Render Message Window..."),
    Ph("Compare Media in RAM Player..."),
])

CIVIL_VIEW = _menu("civil_view", "Civil View", _phs("Initialize Civil View...", "Civil View Explorer..."))

CUSTOMIZE = _menu("customize", "Customize", [
    Op("screen.userpref_show", "Customize User Interface...", section='INTERFACE'),
    Ph("Load Custom UI Scheme..."),
    Ph("Save Custom UI Scheme..."),
    Op("screen.mx_max_layout", "Revert to Startup Layout"),
    Ph("Custom UI and Defaults Switcher..."),
    SEP,
    Op("screen.userpref_show", "Hotkey Editor", section='KEYMAP'),
    SEP,
    Ph("Lock UI Layout"),
    _sub("customize_show_ui", "Show UI", _phs(
        "Show Command Panel", "Show Floating Toolbars", "Show Main Toolbar", "Show Track Bar")),
    SEP,
    Op("screen.userpref_show", "Configure User and System Paths...", section='FILE_PATHS'),
    Ph("Configure Project Paths..."),
    SEP,
    Op("scene.mx_units_setup", "Units Setup..."),
    SEP,
    Op("screen.userpref_show", "Plug-in Manager...", section='ADDONS'),
    Op("screen.userpref_show", "Preferences..."),
])

SCRIPTING = _menu("scripting", "Scripting", [
    Editor('SCRIPT_EDITOR', "New Script", new_text=True),
    Editor('SCRIPT_EDITOR', "Open Script..."),
    Op("mx_ui.run_script", "Run Script..."),
    SEP,
    Editor('LISTENER', "MAXScript Listener..."),
    Editor('MESSAGES', "Macro Recorder"),
    SEP,
    Ph("Visual MAXScript Editor..."),
    Ph("Debugger Dialog..."),
    SEP,
    Op("wm.url_open_preset", "Scripting Reference", type='API'),
])

INTERACTIVE = _menu("interactive", "Interactive", _phs("Interactive Mode..."))

CONTENT = _menu("content", "Content", _phs("Asset Library..."))

HELP = _menu("help", "Help", [
    Op("wm.splash", "Welcome Screen..."),
    SEP,
    Op("wm.url_open_preset", "Help...", type='MANUAL'),
    Op("screen.userpref_show", "Hotkey Map...", section='KEYMAP'),
    Op("wm.search_operator", "Search Commands..."),
    SEP,
    Ph("Tutorials"),
    Ph("Additional Help..."),
    Op("wm.url_open_preset", "Scripting Help", type='API'),
    SEP,
    Ph("Report a Problem..."),
    SEP,
    Op("wm.splash_about", "About..."),
])

# The menu bar, left to right.
MENUBAR = (
    FILE, EDIT, TOOLS, GROUP, VIEWS, CREATE, MODIFIERS, ANIMATION, GRAPH_EDITORS, RENDERING, CIVIL_VIEW,
    CUSTOMIZE, SCRIPTING, INTERACTIVE, CONTENT, HELP,
)


# -----------------------------------------------------------------------------
# Drawing

def _set_props(op, props):
    for key, value in props.items():
        setattr(op, key, value)


def draw_item(layout, context, item):
    if item is SEP:
        layout.separator()
    elif isinstance(item, Ph):
        placeholder(layout, item.text)
    elif isinstance(item, Sub):
        layout.menu(item.menu, text=item.text)
    elif isinstance(item, Dyn):
        item.draw(layout, context)
    elif isinstance(item, Mod):
        entry = modifier_entry(item.text)
        if entry is not None and entry.available:
            layout.operator(modifier_map.OBJECT_OT_mx_modifier_add.bl_idname, text=item.text).kind = entry.key
        else:
            placeholder(layout, item.text)
    elif isinstance(item, Editor):
        menu_ops.open_editor(layout, item.editor, item.text, **item.props)
    elif isinstance(item, Toggle):
        menu_ops.viewport_toggle(layout, context, item.path, item.text)
    elif isinstance(item, Kind):
        if _kind_available(item):
            layout.operator(item.idname, text=item.text).kind = item.props["kind"]
        else:
            placeholder(layout, item.text)
    elif isinstance(item, Op):
        if not menu_ops.has_operator(item.idname):
            if item.fallback is not None:
                draw_item(layout, context, item.fallback)
            else:
                placeholder(layout, item.text)
        elif isinstance(item, ViewOp):
            menu_ops.viewport_call(layout, item.idname, item.text, item.icon, all_viewports=item.all_viewports,
                                   invoke=item.invoke, **item.props)
        else:
            _set_props(layout.operator(item.idname, text=item.text, icon=item.icon), item.props)
    else:
        raise TypeError("unknown menu item {!r}".format(item))


def draw_menu(layout, context, idname):
    layout.operator_context = 'INVOKE_REGION_WIN'
    for item in MENUS[idname][1]:
        draw_item(layout, context, item)


def _make_menu_class(idname, label):
    def draw(self, context):
        draw_menu(self.layout, context, idname)
    return type(idname, (Menu,), {"bl_idname": idname, "bl_label": label, "draw": draw})


classes = tuple(_make_menu_class(idname, label) for idname, (label, _items) in MENUS.items())


# -----------------------------------------------------------------------------
# Top bar overrides

def draw_menubar(layout):
    for idname in MENUBAR:
        layout.menu(idname)


def _draw_editor_menus(self, context):
    if not utils.use_max_chrome(context):
        return _originals["editor_menus"](self, context)
    draw_menubar(self.layout)


def _draw_upper_bar_left(self, context):
    if not utils.use_max_chrome(context):
        return _originals["upper_left"](self, context)
    layout = self.layout
    bpy.types.TOPBAR_MT_editor_menus.draw_collapsible(context, layout)
    # No workspace tabs: the Max layout is the workspace.
    if context.screen.show_fullscreen:
        layout.separator(type='LINE')
        layout.operator("screen.back_to_previous", icon='SCREEN_BACK', text="Back to Previous")


def _draw_upper_bar_right(self, context):
    if not utils.use_max_chrome(context):
        return _originals["upper_right"](self, context)
    layout = self.layout
    if not context.screen.show_statusbar:
        layout.template_reports_banner()
        layout.template_running_jobs()


_originals = {}

_OVERRIDES = (
    # (key, class name, attribute, replacement)
    ("editor_menus", "TOPBAR_MT_editor_menus", "draw", _draw_editor_menus),
    ("upper_left", "TOPBAR_HT_upper_bar", "draw_left", _draw_upper_bar_left),
    ("upper_right", "TOPBAR_HT_upper_bar", "draw_right", _draw_upper_bar_right),
)


def overridden():
    """Whether the top bar draw functions are currently replaced."""
    return bool(_originals)


def register():
    for key, cls_name, attr, func in _OVERRIDES:
        cls = getattr(bpy.types, cls_name)
        _originals.setdefault(key, getattr(cls, attr))
        setattr(cls, attr, func)


def unregister():
    for key, cls_name, attr, _func in _OVERRIDES:
        original = _originals.pop(key, None)
        cls = getattr(bpy.types, cls_name, None)
        if original is not None and cls is not None:
            setattr(cls, attr, original)
