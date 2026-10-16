# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Everything the command panel shows, as data: every Create category, sub-category and button, the Editable
Poly and Editable Spline rollouts of the Modify tab, and the buttons of the other tabs.

Each control is a :class:`Button`. A button with an ``operator`` is implemented (by that Blender or add-on
operator, with ``props``); a button without one is a placeholder for a Max feature that doesn't exist yet
(drawn normally, reports "not implemented yet"). This module has no ``bpy`` dependency, so the same tables
can generate a supported-features matrix, and the tests iterate them.

Layout data: a :class:`Rollout` is a list of rows; a row is a tuple of cells drawn side by side (Max's
two-buttons-per-row look). A cell is a :class:`Button`, a :class:`Prop` (a Blender property drawn as a
field, owner resolved when drawing), a :class:`Label`, a :class:`Special` (a widget drawn by code) or
``None`` (an empty cell); a tuple of cells is drawn joined in one cell (Make Planar's X Y Z).
"""

__all__ = (
    "Button",
    "Prop",
    "Label",
    "Special",
    "StateValue",
    "Rollout",
    "SubCategory",
    "Category",
    "CREATE",
    "CREATE_BY_KEY",
    "EDITABLE_POLY",
    "EDITABLE_SPLINE",
    "COMMANDS",
    "iter_buttons",
)

import re
from dataclasses import dataclass, field, replace

# Add-on modules some operators come from.
PRIMITIVES = "mx_primitives"


@dataclass(frozen=True)
class StateValue:
    """An operator property value read from the command panel state (``window_manager.mx_ui``) on click."""
    name: str


@dataclass(frozen=True)
class Button:
    label: str
    operator: str = ""
    """Operator idname; empty for a placeholder."""
    props: dict = field(default_factory=dict, compare=False, hash=False)
    """Operator properties; values may be `StateValue`."""
    icon: str = 'NONE'
    description: str = ""
    """Tooltip (defaults to the operator's own description)."""
    key: str = ""
    """Unique identifier, filled in by the table builders."""
    requires: str = ""
    """Module of the add-on providing ``operator``, when not ``mx_ui`` or Blender."""
    needs_selection: bool = False
    """Create buttons acting on the selected object (e.g. Boolean)."""
    mode: str = 'EXEC'
    """Edit commands: 'EXEC' runs the operator at once; 'PICK' waits for a click in a viewport, then starts the
    (interactive) operator there, like Max's toggle buttons (Extrude, Chamfer, Cut, ...)."""
    edit: str = ""
    """Edit commands: object type ('MESH', 'CURVE') whose Edit Mode the command runs in ('' = any mode)."""
    settings: "Button | None" = None
    """Max's Settings (caddy) button next to the command: here the operator runs with default values and its
    Adjust Last Operation panel shows the settings."""
    checkbox: bool = False
    """Placeholder drawn as a checkbox."""

    @property
    def implemented(self):
        return bool(self.operator)


@dataclass(frozen=True)
class Prop:
    owner: str
    """'TOOL_SETTINGS', 'STATE', 'OBJECT', 'DATA', 'PREFS' or 'NURMS' (the base object's NURMS modifier)."""
    prop: str
    text: str = ""
    toggle: bool = False
    expand: bool = False
    icon: str = 'NONE'


@dataclass(frozen=True)
class Label:
    text: str


@dataclass(frozen=True)
class Special:
    """A widget drawn by code (``command_panel.widgets``): sub-object level icons, selection info, ..."""
    name: str


@dataclass(frozen=True)
class Rollout:
    key: str
    title: str
    rows: tuple
    levels: frozenset = frozenset()
    """Sub-object levels showing this rollout (Max numbers, 0 = object level); empty = always."""
    default_closed: bool = False


@dataclass(frozen=True)
class SubCategory:
    key: str
    label: str
    buttons: tuple


@dataclass(frozen=True)
class Category:
    key: str
    label: str
    subcategories: tuple


def _key(text):
    return re.sub(r"[^A-Z0-9]+", "_", text.upper()).strip("_")


def P(label, **kwargs):
    """A placeholder button."""
    return Button(label, **kwargs)


def B(label, operator, **kwargs):
    return Button(label, operator, **kwargs)


def C(label):
    """A placeholder checkbox."""
    return Button(label, checkbox=True)


# -----------------------------------------------------------------------------
# Create tab

def _primitive(label, kind, **kwargs):
    return Button(label, "mesh.mx_primitive_add", {"kind": kind}, requires=PRIMITIVES, **kwargs)


def _shape(label, kind):
    return Button(label, "curve.mx_shape_add", {"kind": kind})


def _object(label, kind):
    return Button(label, "object.mx_create", {"kind": kind})


def _effector(label, kind, description):
    return Button(label, "object.effector_add", {"type": kind}, description=description)


def _sub(key, label, *buttons):
    return SubCategory(key, label, tuple(replace(button, key=key + "." + _key(button.label)) for button in buttons))


def _category(key, label, *subcategories):
    return Category(key, label, tuple(
        SubCategory(key + "." + sub.key, sub.label,
                    tuple(replace(button, key=key + "." + button.key) for button in sub.buttons))
        for sub in subcategories))


TEAPOT_DESCRIPTION = (
    "Teapot: creates our original stand-in shape (a pot with lid, handle and spout), "
    "not the Utah teapot. Live parameters like the other primitives"
)

CREATE = (
    _category(
        'GEOMETRY', "Geometry",
        _sub("STANDARD", "Standard Primitives",
             _primitive("Box", 'BOX'),
             _primitive("Cone", 'CONE'),
             _primitive("Sphere", 'SPHERE'),
             _primitive("GeoSphere", 'GEOSPHERE'),
             _primitive("Cylinder", 'CYLINDER'),
             _primitive("Tube", 'TUBE'),
             _primitive("Torus", 'TORUS'),
             _primitive("Pyramid", 'PYRAMID'),
             _primitive("Teapot", 'TEST_SHAPE', description=TEAPOT_DESCRIPTION),
             _primitive("Plane", 'PLANE'),
             B("TextPlus", "curve.mx_shape_add", props={"kind": 'TEXT'},
               description="Create a text object (Blender text) at the 3D cursor")),
        _sub("EXTENDED", "Extended Primitives",
             P("Hedra"), P("Torus Knot"),
             P("ChamferBox"), P("ChamferCyl"),
             P("OilTank"), P("Capsule"),
             P("Spindle"), P("L-Ext"),
             P("Gengon"), P("C-Ext"),
             P("RingWave"), P("Hose"),
             P("Prism")),
        _sub("COMPOUND", "Compound Objects",
             P("Morph"), P("Scatter"),
             P("Conform"), P("Connect"),
             P("BlobMesh"), P("ShapeMerge"),
             P("Terrain"), P("Loft"),
             P("Mesher"), P("ProBoolean"),
             P("ProCutter"),
             B("Boolean", "object.mx_modifier_add", props={"kind": 'BOOLEAN'}, needs_selection=True,
               description="Boolean: adds a Boolean modifier to the selected object (pick the operand in "
               "its parameters)")),
        _sub("PARTICLES", "Particle Systems",
             P("PF Source"), P("Spray"),
             P("Snow"), P("Super Spray"),
             P("Blizzard"), P("PArray"),
             P("PCloud")),
        _sub("PATCH_GRIDS", "Patch Grids",
             P("Quad Patch"), P("Tri Patch")),
        _sub("NURBS", "NURBS Surfaces",
             P("Point Surf"),
             B("CV Surf", "surface.primitive_nurbs_surface_surface_add",
               description="Create a NURBS surface patch at the 3D cursor")),
        _sub("DOORS", "Doors",
             P("Pivot"), P("Sliding"),
             P("BiFold")),
        _sub("WINDOWS", "Windows",
             P("Awning"), P("Casement"),
             P("Fixed"), P("Pivoted"),
             P("Projected"), P("Sliding")),
        _sub("AEC", "AEC Extended",
             P("Foliage"), P("Railing"),
             P("Wall")),
        _sub("STAIRS", "Stairs",
             P("Straight Stair"), P("L-Type Stair"),
             P("U-Type Stair"), P("Spiral Stair")),
        _sub("POINT_CLOUD", "Point Cloud Objects",
             P("PointCloud")),
        _sub("DYNAMICS", "Dynamics Objects",
             P("Damper"), P("Spring")),
        _sub("BODY", "Body Objects",
             P("Body Object"), P("Join Bodies"),
             P("Body Cutter")),
        _sub("FLUIDS", "Fluids",
             P("Liquid")),
    ),
    _category(
        'SHAPES', "Shapes",
        _sub("SPLINES", "Splines",
             _shape("Line", 'LINE'), _shape("Rectangle", 'RECTANGLE'),
             _shape("Circle", 'CIRCLE'), _shape("Ellipse", 'ELLIPSE'),
             _shape("Arc", 'ARC'), _shape("Donut", 'DONUT'),
             _shape("NGon", 'NGON'), _shape("Star", 'STAR'),
             _shape("Text", 'TEXT'), _shape("Helix", 'HELIX'),
             _shape("Egg", 'EGG'), P("Section"),
             P("Freehand")),
        _sub("NURBS_CURVES", "NURBS Curves",
             P("Point Curve"),
             B("CV Curve", "curve.primitive_nurbs_curve_add",
               description="Create a NURBS curve at the 3D cursor")),
        _sub("COMPOUND_SHAPES", "Compound Shapes",
             P("ShapeBoolean")),
        _sub("EXTENDED_SPLINES", "Extended Splines",
             _shape("WRectangle", 'WRECTANGLE'), _shape("Channel", 'CHANNEL'),
             _shape("Angle", 'ANGLE'), _shape("Tee", 'TEE'),
             _shape("Wide Flange", 'WIDE_FLANGE')),
    ),
    _category(
        'LIGHTS', "Lights",
        _sub("PHOTOMETRIC", "Photometric",
             _object("Target Light", 'TARGET_LIGHT'), _object("Free Light", 'FREE_LIGHT'),
             _object("Sun Positioner", 'SUN_POSITIONER')),
        _sub("STANDARD", "Standard",
             _object("Target Spot", 'TARGET_SPOT'), _object("Free Spot", 'FREE_SPOT'),
             _object("Target Direct", 'TARGET_DIRECT'), _object("Free Direct", 'FREE_DIRECT'),
             _object("Omni", 'OMNI'), _object("Skylight", 'SKYLIGHT')),
    ),
    _category(
        'CAMERAS', "Cameras",
        _sub("STANDARD", "Standard",
             _object("Physical", 'PHYSICAL_CAMERA'), _object("Target", 'TARGET_CAMERA'),
             _object("Free", 'FREE_CAMERA')),
    ),
    _category(
        'HELPERS', "Helpers",
        _sub("STANDARD", "Standard",
             _object("Dummy", 'DUMMY'), P("Container"),
             P("Crowd"), P("Delegate"),
             P("ExposeTm"), P("Grid"),
             _object("Point", 'POINT'), P("Point Cloud"),
             P("Protractor"), P("Tape")),
        _sub("ATMOSPHERIC", "Atmospheric Apparatus",
             P("BoxGizmo"), P("SphereGizmo"),
             P("CylGizmo")),
        _sub("CAMERA_MATCH", "Camera Match",
             P("CamPoint")),
        _sub("ASSEMBLY_HEADS", "Assembly Heads",
             P("Luminaire")),
        _sub("MANIPULATORS", "Manipulators",
             P("Slider"), P("Plane Angle"),
             P("Cone Angle")),
        _sub("PARTICLE_FLOW", "Particle Flow",
             P("Speed By Icon"), P("Find Target")),
        _sub("CAT_OBJECTS", "CAT Objects",
             P("CATParent"), P("Muscle"),
             P("Muscle Strand")),
    ),
    _category(
        'SPACE_WARPS', "Space Warps",
        _sub("FORCES", "Forces",
             _effector("Push", 'FORCE', "Push: a force field at the 3D cursor"), P("Motor"),
             _effector("Vortex", 'VORTEX', "Vortex: a vortex force field at the 3D cursor"),
             _effector("Drag", 'DRAG', "Drag: a drag force field at the 3D cursor"),
             P("PBomb"),
             _effector("Path Follow", 'GUIDE', "Path Follow: a curve guide force field at the 3D cursor"),
             P("Displace"), P("Gravity"),
             _effector("Wind", 'WIND', "Wind: a wind force field at the 3D cursor")),
        _sub("DEFLECTORS", "Deflectors",
             P("POmniFlect"), P("PDynaFlect"),
             P("SOmniFlect"), P("UDynaFlect"),
             P("SDynaFlect"), P("UOmniFlect"),
             P("SDeflector"), P("UDeflector"),
             P("Deflector")),
        _sub("GEOMETRIC", "Geometric/Deformable",
             P("FFD(Box)"), P("FFD(Cyl)"),
             P("Wave"), P("Ripple"),
             P("Displace"), P("Conform"),
             P("Bomb")),
        _sub("MODIFIER_BASED", "Modifier-Based",
             P("Bend"), P("Noise"),
             P("Skew"), P("Taper"),
             P("Twist"), P("Stretch")),
    ),
    _category(
        'SYSTEMS', "Systems",
        _sub("STANDARD", "Standard",
             B("Bones", "object.armature_add", description="Bones: an armature with one bone at the 3D cursor"),
             P("Ring Array"),
             P("Biped"),
             B("Sunlight", "object.light_add", props={"type": 'SUN'},
               description="Sunlight: a sun light at the 3D cursor"),
             P("Daylight")),
    ),
)

CREATE_BY_KEY = {button.key: button for cat in CREATE for sub in cat.subcategories for button in sub.buttons}
CATEGORY_BY_KEY = {cat.key: cat for cat in CREATE}


# -----------------------------------------------------------------------------
# Modify tab: Editable Poly (Blender mesh objects)

def _m(label, operator, mode='EXEC', **kwargs):
    """A mesh edit-mode command."""
    return Button(label, operator, edit='MESH', mode=mode, **kwargs)


def _settings(operator, **kwargs):
    return Button("Settings", operator, edit='MESH', icon='PREFERENCES', **kwargs)


def _rollout(prefix, key, title, rows, levels=(), default_closed=False):
    full = prefix + "." + key
    seen = set()

    def keyed(cell, index):
        if isinstance(cell, tuple):
            # A group of buttons drawn joined in one cell (e.g. Make Planar's X Y Z).
            return tuple(keyed(sub, index * 100 + n) for n, sub in enumerate(cell))
        if not isinstance(cell, Button):
            return cell
        cell_key = "{:s}.{:s}".format(full, _key(cell.label) or str(index))
        if cell_key in seen:
            cell_key += "_{:d}".format(index)
        seen.add(cell_key)
        settings = cell.settings
        if settings is not None:
            settings = replace(settings, key=cell_key + ".SETTINGS")
        return replace(cell, key=cell_key, settings=settings)

    counter = iter(range(10000))
    keyed_rows = tuple(tuple(keyed(cell, next(counter)) for cell in row) for row in rows)
    return Rollout(full, title, keyed_rows, frozenset(levels), default_closed)


_BEVEL_SETTINGS = {"offset": 0.1, "segments": 1}
_PICK_HINT = "Click in a viewport to start, like Max's toggle buttons"

# Max sub-object levels: 1 Vertex, 2 Edge, 3 Border, 4 Polygon, 5 Element.
_SUBDIVIDE_ROWS = (
    (C("Smooth Result"),),
    (B("Use NURMS Subdivision", "object.mx_nurms_toggle"),),
    (C("Isoline Display"), C("Show Cage")),
    (Label("Display"),),
    (Special("NURMS_LEVELS"),),
    (P("Smoothness: 1.0"),),
    (Label("Render"),),
    (Special("NURMS_RENDER_LEVELS"),),
    (Label("Separate By"),),
    (C("Smoothing Groups"), C("Materials")),
    (Label("Update Options"),),
    (C("Always"), C("When Rendering"), C("Manually")),
    (P("Update"),),
)

EDITABLE_POLY = (
    _rollout("EPOLY", "SELECTION", "Selection", (
        (Special("SUBOBJECT_LEVELS"),),
        (C("By Vertex"), C("Ignore Backfacing")),
        (C("By Angle"), P("45.0")),
        (_m("Shrink", "mesh.select_less"), _m("Grow", "mesh.select_more")),
        (_m("Ring", "mesh.select_edge_ring_multi"), _m("Loop", "mesh.select_edge_loop_multi")),
        (Label("Preview Selection"),),
        (C("Off"), C("SubObj"), C("Multi")),
        (Special("SELECTION_INFO"),),
    )),
    _rollout("EPOLY", "SOFT_SELECTION", "Soft Selection", (
        (Prop('TOOL_SETTINGS', "use_proportional_edit", "Use Soft Selection"),),
        (Prop('TOOL_SETTINGS', "use_proportional_connected", "Edge Distance"),),
        (C("Affect Backfacing"),),
        (Prop('TOOL_SETTINGS', "proportional_size", "Falloff"),),
        (Prop('TOOL_SETTINGS', "proportional_edit_falloff", "Curve"),),
        (P("Pinch: 0.0"), P("Bubble: 0.0")),
        (P("Shaded Face Toggle"),),
        (C("Lock Soft Selection"),),
        (Label("Paint Soft Selection"),),
        (P("Paint"), P("Blur"), P("Revert")),
        (P("Selection Value: 1.0"),),
        (P("Brush Size: 20.0"), P("Brush Strength: 1.0")),
        (P("Brush Options"),),
    ), default_closed=True),
    _rollout("EPOLY", "EDIT_GEOMETRY", "Edit Geometry", (
        (B("Repeat Last", "screen.repeat_last"),),
        (Label("Constraints"),),
        (C("None"), C("Edge")),
        (C("Face"), C("Normal")),
        (Prop('TOOL_SETTINGS', "use_transform_correct_face_attributes", "Preserve UVs"),),
        (_m("Create", "mesh.edge_face_add", description="Create: a polygon (or edge) from the selected vertices"),
         _m("Collapse", "mesh.merge", props={"type": 'COLLAPSE'},
            description="Collapse: merge each connected selection into one vertex")),
        (B("Attach", "object.mx_attach",
           description="Attach: join the other selected objects into this one"),
         _m("Detach", "mesh.separate", props={"type": 'SELECTED'},
            description="Detach: move the selection into a new object")),
        (_m("Slice Plane", "mesh.bisect", 'PICK', description="Slice Plane: drag a line in a viewport to slice"),
         C("Split")),
        (_m("Slice", "mesh.bisect", 'PICK', description="Slice: drag a line in a viewport to slice"),
         P("Reset Plane")),
        (_m("QuickSlice", "mesh.bisect", 'PICK',
            description="QuickSlice: drag a line across the object in a viewport"),
         _m("Cut", "mesh.knife_tool", 'PICK', description="Cut: click in a viewport to cut new edges")),
        (_m("MSmooth", "mesh.subdivide", props={"smoothness": 1.0},
            description="MSmooth: subdivide the selection with smoothing",
            settings=_settings("mesh.subdivide", props={"smoothness": 1.0})),
         _m("Tessellate", "mesh.subdivide", props={"smoothness": 0.0},
            description="Tessellate: subdivide the selection",
            settings=_settings("mesh.subdivide", props={"smoothness": 0.0}))),
        (_m("Make Planar", "mesh.face_make_planar"),
         (_m("X", "transform.resize", props={"value": (0.0, 1.0, 1.0)},
             description="Make the selection planar along the X axis"),
          _m("Y", "transform.resize", props={"value": (1.0, 0.0, 1.0)},
             description="Make the selection planar along the Y axis"),
          _m("Z", "transform.resize", props={"value": (1.0, 1.0, 0.0)},
             description="Make the selection planar along the Z axis"))),
        (P("View Align"), P("Grid Align")),
        (_m("Relax", "mesh.vertices_smooth", props={"factor": 0.5},
            settings=_settings("mesh.vertices_smooth", props={"factor": 0.5, "repeat": 1})),),
        (_m("Hide Selected", "mesh.hide", props={"unselected": False}), _m("Unhide All", "mesh.reveal")),
        (_m("Hide Unselected", "mesh.hide", props={"unselected": True}),),
        (Label("Named Selections"),),
        (P("Copy"), P("Paste")),
        (C("Delete Isolated Vertices"),),
        (C("Full Interactivity"),),
    )),
    _rollout("EPOLY", "EDIT_VERTICES", "Edit Vertices", (
        (_m("Remove", "mesh.dissolve_verts"), _m("Break", "mesh.edge_split", props={"type": 'VERT'})),
        (_m("Extrude", "mesh.extrude_vertices_move", 'PICK', description="Extrude: " + _PICK_HINT),
         _m("Weld", "mesh.remove_doubles", props={"threshold": StateValue("weld_threshold")},
            settings=_settings("mesh.remove_doubles", props={"threshold": StateValue("weld_threshold")}))),
        (_m("Chamfer", "mesh.bevel", 'PICK', props={"affect": 'VERTICES'}, description="Chamfer: " + _PICK_HINT,
            settings=_settings("mesh.bevel", props={"affect": 'VERTICES', **_BEVEL_SETTINGS})),
         _m("Target Weld", "mesh.merge", props={"type": 'LAST'},
            description="Target Weld: merge the selected vertices into the last selected one")),
        (_m("Connect", "mesh.vert_connect_path"),),
        (_m("Remove Isolated Vertices", "mesh.delete_loose",
            props={"use_verts": True, "use_edges": False, "use_faces": False}),),
        (P("Remove Unused Map Verts"),),
        (P("Weight: 1.0"), _m("Crease", "transform.vert_crease", 'PICK')),
    ), levels={1}),
    _rollout("EPOLY", "EDIT_EDGES", "Edit Edges", (
        (_m("Insert Vertex", "mesh.subdivide", props={"number_cuts": 1}),),
        (_m("Remove", "mesh.dissolve_edges"), _m("Split", "mesh.edge_split", props={"type": 'EDGE'})),
        (_m("Extrude", "mesh.extrude_edges_move", 'PICK', description="Extrude: " + _PICK_HINT),
         _m("Weld", "mesh.remove_doubles", props={"threshold": StateValue("weld_threshold")})),
        (_m("Chamfer", "mesh.bevel", 'PICK', props={"affect": 'EDGES'}, description="Chamfer: " + _PICK_HINT,
            settings=_settings("mesh.bevel", props={"affect": 'EDGES', **_BEVEL_SETTINGS})),
         _m("Target Weld", "mesh.merge", props={"type": 'LAST'})),
        (_m("Bridge", "mesh.bridge_edge_loops"),
         _m("Connect", "mesh.subdivide_edgering", props={"number_cuts": 1},
            settings=_settings("mesh.subdivide_edgering", props={"number_cuts": 2}))),
        (P("Create Shape From Selection"),),
        (_m("Weight", "transform.edge_bevelweight", 'PICK'), _m("Crease", "transform.edge_crease", 'PICK')),
        (P("Edit Tri."), _m("Turn", "mesh.edge_rotate")),
    ), levels={2}),
    _rollout("EPOLY", "EDIT_BORDERS", "Edit Borders", (
        (_m("Extrude", "mesh.extrude_edges_move", 'PICK', description="Extrude: " + _PICK_HINT),
         _m("Insert Vertex", "mesh.subdivide", props={"number_cuts": 1})),
        (_m("Chamfer", "mesh.bevel", 'PICK', props={"affect": 'EDGES'}, description="Chamfer: " + _PICK_HINT,
            settings=_settings("mesh.bevel", props={"affect": 'EDGES', **_BEVEL_SETTINGS})),
         _m("Cap", "mesh.edge_face_add", description="Cap: fill the selected border with a polygon")),
        (_m("Bridge", "mesh.bridge_edge_loops"),
         _m("Connect", "mesh.subdivide_edgering", props={"number_cuts": 1})),
        (P("Create Shape From Selection"),),
        (_m("Weight", "transform.edge_bevelweight", 'PICK'), _m("Crease", "transform.edge_crease", 'PICK')),
        (P("Edit Tri."), _m("Turn", "mesh.edge_rotate")),
    ), levels={3}),
    _rollout("EPOLY", "EDIT_POLYGONS", "Edit Polygons", (
        (_m("Insert Vertex", "mesh.poke", description="Insert Vertex: add a vertex in the middle of each "
            "selected polygon"),),
        (_m("Extrude", "mesh.extrude_region_move", 'PICK', description="Extrude: " + _PICK_HINT,
            settings=_settings("mesh.extrude_region_shrink_fatten",
                               props={"TRANSFORM_OT_shrink_fatten": {"value": -0.1}})),
         _m("Outline", "transform.resize", 'PICK', description="Outline: scale the selection in a viewport")),
        (_m("Bevel", "mesh.inset", 'PICK', description="Bevel: inset in a viewport; hold Ctrl for height",
            settings=_settings("mesh.inset", props={"thickness": 0.05, "depth": 0.1})),
         _m("Inset", "mesh.inset", 'PICK', description="Inset: " + _PICK_HINT,
            settings=_settings("mesh.inset", props={"thickness": 0.1}))),
        (_m("Bridge", "mesh.bridge_edge_loops"), _m("Flip", "mesh.flip_normals")),
        (P("Hinge From Edge"),),
        (P("Extrude Along Spline"),),
        (P("Edit Triangulation"),),
        (P("Retriangulate"), P("Turn")),
    ), levels={4}),
    _rollout("EPOLY", "EDIT_ELEMENTS", "Edit Elements", (
        (_m("Insert Vertex", "mesh.poke"),),
        (_m("Flip", "mesh.flip_normals"),),
        (P("Edit Triangulation"),),
        (P("Retriangulate"), P("Turn")),
    ), levels={5}),
    _rollout("EPOLY", "MATERIAL_IDS", "Polygon: Material IDs", (
        (Prop('STATE', "material_id", "Set ID"),
         _m("Set", "mesh.mx_material_id", props={"action": 'SET'}, description="Assign the Set ID to the "
            "selected polygons")),
        (Prop('STATE', "select_material_id", "Select ID"),
         _m("Select", "mesh.mx_material_id", props={"action": 'SELECT'},
            description="Select the polygons with the Select ID")),
        (P("Select By Name"),),
        (Prop('STATE', "select_id_clear", "Clear Selection"),),
    ), levels={4, 5}),
    _rollout("EPOLY", "SMOOTHING_GROUPS", "Polygon: Smoothing Groups", (
        (Special("SMOOTHING_GROUPS"),),
        (P("Select By SG"), _m("Clear All", "mesh.faces_shade_flat",
                               description="Clear All: make the selected polygons flat shaded")),
        (_m("Auto Smooth", "mesh.mx_auto_smooth", description="Auto Smooth: smooth the selected polygons, "
            "keeping edges sharper than the threshold"),
         Prop('STATE', "auto_smooth_angle", "")),
    ), levels={4, 5}),
    _rollout("EPOLY", "VERTEX_COLORS", "Polygon: Vertex Colors", (
        (P("Color"), P("Illumination")),
        (P("Alpha: 100.0"),),
    ), levels={4, 5}, default_closed=True),
    _rollout("EPOLY", "VERTEX_PROPERTIES", "Edit Vertex Colors", (
        (P("Color"), P("Illumination")),
        (P("Alpha: 100.0"),),
        (Label("Select Vertices By"),),
        (C("Color"), C("Illumination")),
        (P("Select"),),
    ), levels={1}, default_closed=True),
    _rollout("EPOLY", "SUBDIVISION_SURFACE", "Subdivision Surface", _SUBDIVIDE_ROWS, default_closed=True),
    _rollout("EPOLY", "SUBDIVISION_DISPLACEMENT", "Subdivision Displacement", (
        (C("Subdivision Displacement"),),
        (C("Split Mesh"),),
        (Label("Subdivision Presets"),),
        (P("Low"), P("Medium"), P("High")),
        (Label("Subdivision Method"),),
        (P("Regular"), P("Spatial")),
    ), default_closed=True),
    _rollout("EPOLY", "PAINT_DEFORMATION", "Paint Deformation", (
        (P("Push/Pull"), P("Relax"), P("Revert")),
        (Label("Push/Pull Direction"),),
        (C("Original Normals"), C("Deformed Normals")),
        (C("Transform axis X"), C("Y"), C("Z")),
        (P("Push/Pull Value: 10.0"),),
        (P("Brush Size: 20.0"), P("Brush Strength: 1.0")),
        (P("Brush Options"),),
        (P("Commit"), P("Cancel")),
    ), default_closed=True),
)


# -----------------------------------------------------------------------------
# Modify tab: Editable Spline (Blender curve objects)

def _c(label, operator, mode='EXEC', **kwargs):
    return Button(label, operator, edit='CURVE', mode=mode, **kwargs)


EDITABLE_SPLINE = (
    _rollout("ESPLINE", "RENDERING", "Rendering", (
        (Prop('DATA', "bevel_depth", "Thickness"),),
        (Prop('DATA', "bevel_resolution", "Sides"),),
        (Prop('DATA', "fill_mode", "Fill"),),
        (C("Enable In Renderer"), C("Enable In Viewport")),
    )),
    _rollout("ESPLINE", "INTERPOLATION", "Interpolation", (
        (Prop('DATA', "resolution_u", "Steps"),),
        (C("Optimize"), C("Adaptive")),
    )),
    _rollout("ESPLINE", "SELECTION", "Selection", (
        (Special("SPLINE_LEVELS"),),
        (C("Lock Handles"), C("Area Selection")),
        (C("Segment End"),),
        (P("Select By..."),),
        (Special("SELECTION_INFO"),),
    )),
    _rollout("ESPLINE", "SOFT_SELECTION", "Soft Selection", (
        (Prop('TOOL_SETTINGS', "use_proportional_edit", "Use Soft Selection"),),
        (Prop('TOOL_SETTINGS', "proportional_size", "Falloff"),),
        (Prop('TOOL_SETTINGS', "proportional_edit_falloff", "Curve"),),
    ), default_closed=True),
    _rollout("ESPLINE", "GEOMETRY", "Geometry", (
        (Label("New Vertex Type"),),
        (C("Linear"), C("Bezier"), C("Smooth"), C("Bezier Corner")),
        (P("Create Line"), _c("Break", "curve.split")),
        (B("Attach", "object.mx_attach", description="Attach: join the other selected shapes into this one"),
         P("Attach Mult.")),
        (_c("Refine", "curve.subdivide"), _c("Connect", "curve.make_segment")),
        (P("Weld"), P("Fuse")),
        (P("Insert"), P("Make First")),
        (P("Cycle"), P("CrossInsert")),
        (P("Fillet"), P("Chamfer")),
        (P("Outline"), P("Boolean")),
        (P("Mirror"), P("Trim"), P("Extend")),
        (_c("Hide", "curve.hide"), _c("Unhide All", "curve.reveal")),
        (_c("Delete", "curve.delete", props={"type": 'VERT'}), _c("Close", "curve.cyclic_toggle")),
        (_c("Divide", "curve.subdivide"), _c("Detach", "curve.separate")),
        (_c("Reverse", "curve.switch_direction"), P("Explode")),
        (C("Show Selected Segs"),),
    )),
)


# -----------------------------------------------------------------------------
# Hierarchy tab

def _pivot(label, action, **kwargs):
    return Button(label, "object.mx_pivot", {"action": action}, **kwargs)


HIERARCHY_PIVOT = (
    _rollout("HIERARCHY", "ADJUST_PIVOT", "Adjust Pivot", (
        (Label("Move/Rotate/Scale:"),),
        (Prop('TOOL_SETTINGS', "use_transform_data_origin", "Affect Pivot Only", toggle=True),),
        (Prop('STATE', "affect_object_only", "Affect Object Only", toggle=True),),
        (P("Affect Hierarchy Only"),),
        (Label("Alignment:"),),
        (Special("PIVOT_ALIGNMENT"),),
        (Label("Pivot:"),),
        (_pivot("Reset Pivot", 'RESET_PIVOT'),),
    )),
    _rollout("HIERARCHY", "WORKING_PIVOT", "Working Pivot", (
        (P("Edit Working Pivot"),),
        (P("Use Working Pivot"),),
        (P("Align To View"), P("Reset")),
        (Label("Place Pivot To:"),),
        (C("View"), C("Surface")),
        (C("Align To View"),),
    ), default_closed=True),
    _rollout("HIERARCHY", "ADJUST_TRANSFORM", "Adjust Transform", (
        (Label("Move/Rotate/Scale:"),),
        (Prop('TOOL_SETTINGS', "use_transform_skip_children", "Don't Affect Children", toggle=True),),
        (Label("Reset:"),),
        (_pivot("Transform", 'RESET_TRANSFORM'),),
        (_pivot("Scale", 'RESET_SCALE'),),
    ), default_closed=True),
    _rollout("HIERARCHY", "SKIN_POSE", "Skin Pose", (
        (Label("Enabled:"),),
        (C("Position"), C("Rotation"), C("Scale")),
        (P("Skin Pose From Pose"),),
        (P("Pose From Skin Pose"),),
        (C("Skin Pose Mode"),),
    ), default_closed=True),
)

HIERARCHY_IK = (
    _rollout("IK", "INVERSE_KINEMATICS", "Inverse Kinematics", (
        (P("Interactive IK"),),
        (P("Apply IK"),),
        (C("Apply Only To Keys"),),
        (C("Update Viewports"), C("Clear Keys")),
        (Label("Start:"),),
        (P("Pick Object"), P("None")),
        (Label("End:"),),
        (P("Pick Object"), P("None")),
    )),
    _rollout("IK", "OBJECT_PARAMETERS", "Object Parameters", (
        (C("Terminator"),),
        (C("Bind Position"), C("Bind Orientation")),
        (P("Bind To Follow Object"),),
        (Label("Precedence:"),),
        (P("Child->Parent"), P("Parent->Child")),
        (C("Sliding Joints"), C("Rotational Joints")),
    ), default_closed=True),
    _rollout("IK", "AUTO_TERMINATION", "Auto Termination", (
        (C("Interactive IK Chain Length"),),
    ), default_closed=True),
    _rollout("IK", "ROTATIONAL_JOINTS", "Rotational Joints", (
        (C("X Axis Active"),),
        (C("Y Axis Active"),),
        (C("Z Axis Active"),),
    ), default_closed=True),
    _rollout("IK", "SLIDING_JOINTS", "Sliding Joints", (
        (C("X Axis Active"),),
        (C("Y Axis Active"),),
        (C("Z Axis Active"),),
    ), default_closed=True),
)

HIERARCHY_LINK_INFO = (
    _rollout("LINK_INFO", "LOCKS", "Locks", (
        (Special("LOCKS"),),
    )),
    _rollout("LINK_INFO", "INHERIT", "Inherit", (
        (Label("Move:"), C("X"), C("Y"), C("Z")),
        (Label("Rotate:"), C("X"), C("Y"), C("Z")),
        (Label("Scale:"), C("X"), C("Y"), C("Z")),
    )),
)


# -----------------------------------------------------------------------------
# Motion tab (kept minimal: modeling comes first)

def _key_button(label, operator, keying_set):
    return Button(label, operator, {"type": keying_set})


MOTION_PARAMETERS = (
    _rollout("MOTION", "ASSIGN_CONTROLLER", "Assign Controller", (
        (Label("Transform : Position/Rotation/Scale"),),
        (P("Assign Controller"),),
    )),
    _rollout("MOTION", "PRS_PARAMETERS", "PRS Parameters", (
        (Label("Create Key"), Label("Delete Key")),
        (_key_button("Position", "anim.keyframe_insert_by_name", "Location"),
         _key_button("Position", "anim.keyframe_delete_by_name", "Location")),
        (_key_button("Rotation", "anim.keyframe_insert_by_name", "Rotation"),
         _key_button("Rotation", "anim.keyframe_delete_by_name", "Rotation")),
        (_key_button("Scale", "anim.keyframe_insert_by_name", "Scaling"),
         _key_button("Scale", "anim.keyframe_delete_by_name", "Scaling")),
        (P("Position"), P("Rotation"), P("Scale")),
    )),
    _rollout("MOTION", "KEY_INFO_BASIC", "Key Info (Basic)", (
        (P("Previous Key"), P("Next Key")),
        (P("Time: 0"),),
        (P("In"), P("Out")),
    ), default_closed=True),
    _rollout("MOTION", "KEY_INFO_ADVANCED", "Key Info (Advanced)", (
        (P("In: 0.0"), P("Out: 0.0")),
        (C("Normalize Time"), C("Constant Velocity")),
    ), default_closed=True),
)

MOTION_PATHS = (
    _rollout("MOTION_PATHS", "VISIBILITY", "Visibility", (
        (C("Always Show"), C("Selected Only")),
    )),
    _rollout("MOTION_PATHS", "TRAJECTORIES", "Trajectories", (
        (P("Delete Key"), P("Add Key")),
        (P("Sub-Object"),),
        (P("Start Time: 0"), P("End Time: 100")),
        (P("Samples: 10"),),
        (P("Convert To"), P("Convert From")),
        (P("Collapse"),),
    )),
)


# -----------------------------------------------------------------------------
# Display tab

DISPLAY = (
    _rollout("DISPLAY", "DISPLAY_COLOR", "Display Color", (
        (Special("DISPLAY_COLOR"),),
    )),
    _rollout("DISPLAY", "HIDE_BY_CATEGORY", "Hide by Category", (
        (Special("HIDE_BY_CATEGORY"),),
        (P("All"), P("None"), P("Invert")),
    ), default_closed=True),
    _rollout("DISPLAY", "HIDE", "Hide", (
        (B("Hide Selected", "object.hide_view_set", props={"unselected": False}),),
        (B("Hide Unselected", "object.hide_view_set", props={"unselected": True}),),
        (P("Hide by Name..."),),
        (P("Hide by Hit"),),
        (B("Unhide All", "object.hide_view_clear", props={"select": False}),),
        (B("Unhide by Name...", "object.mx_unhide_by_name"),),
        (C("Hide Frozen Objects"),),
    )),
    _rollout("DISPLAY", "FREEZE", "Freeze", (
        (B("Freeze Selected", "object.mx_freeze_selected"),),
        (B("Freeze Unselected", "object.mx_freeze_unselected"),),
        (P("Freeze by Name..."),),
        (P("Freeze by Hit"),),
        (B("Unfreeze All", "object.mx_unfreeze_all"),),
        (B("Unfreeze by Name...", "object.mx_unfreeze_by_name"),),
        (P("Unfreeze by Hit"),),
    )),
    _rollout("DISPLAY", "DISPLAY_PROPERTIES", "Display Properties", (
        (Special("DISPLAY_PROPERTIES"),),
    ), default_closed=True),
    _rollout("DISPLAY", "LINK_DISPLAY", "Link Display", (
        (C("Display Links"),),
        (C("Link Replaces Object"),),
    ), default_closed=True),
)


# -----------------------------------------------------------------------------
# Utilities tab: the buttons of the Utilities rollout, in Max's order. Implemented utilities (with a key)
# open their rollout below, like Max (``utilities.py``); the others are placeholders.

UTILITIES = (
    P("Perspective Match"),
    Button("Collapse", key="COLLAPSE"),
    P("Color Clipboard"),
    Button("Measure", key="MEASURE"),
    P("Motion Capture"),
    Button("Reset XForm", key="RESET_XFORM"),
    P("MAXScript"),
    P("Flight Studio"),
)

# The "More..." list (Max's Utilities dialog), alphabetical like Max.
MORE_UTILITIES = (
    P("Assign Vertex Colors"),
    P("Bitmap/Photometric Path Editor"),
    P("Camera Match"),
    P("Camera Tracker"),
    Button("Collapse", key="COLLAPSE"),
    P("Color Clipboard"),
    P("Fix Ambient"),
    P("Level of Detail"),
    P("Link Inheritance"),
    P("MAXScript"),
    Button("Measure", key="MEASURE"),
    P("Motion Capture"),
    P("Panorama Exporter"),
    P("Polygon Counter"),
    P("Rescale World Units"),
    Button("Reset XForm", key="RESET_XFORM"),
    P("Skin Utilities"),
    P("Strokes"),
    P("Surface Approximation"),
    P("UVW Remove"),
    P("Visual MAXScript"),
)

ALL_ROLLOUTS = (*EDITABLE_POLY, *EDITABLE_SPLINE, *HIERARCHY_PIVOT, *HIERARCHY_IK, *HIERARCHY_LINK_INFO,
                *MOTION_PARAMETERS, *MOTION_PATHS, *DISPLAY)


def iter_buttons(rows):
    """Every `Button` in ``rows`` (a rollout's rows), including Settings buttons."""
    for row in rows:
        for cell in row:
            if isinstance(cell, tuple):
                yield from iter_buttons((cell,))
            elif isinstance(cell, Button):
                yield cell
                if cell.settings is not None:
                    yield cell.settings


# Edit commands, run through ``object.mx_edit_command(command=key)``.
COMMANDS = {button.key: button
            for rollout in (*EDITABLE_POLY, *EDITABLE_SPLINE)
            for button in iter_buttons(rollout.rows)
            if button.edit}
