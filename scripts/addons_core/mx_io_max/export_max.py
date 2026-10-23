# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Experimental ``.max`` export: Blender data to ``maxfile.writer``'s neutral scene model, then a file.

The inverse of the importer's conversions (``build_scene.py``): object transforms become Max node transforms
relative to the parent (translations and geometry converted from Blender units to the chosen system unit, object
offset identity), meshes become Editable Poly objects (evaluated with their modifiers, which are baked: modifier
stacks are not written yet), material slots become Multi/Sub-Object materials with IDs 1, 2, ..., Principled
BSDF materials become Standard (or Physical) materials with Bitmap maps, the object colour the wire colour.
Everything that isn't written is listed in the export report (``mx_common.report`` style).

See ``docs/design/max-writer.md`` for what the file contains.
"""

__all__ = ("ExportSettings", "export_file", "UNIT_CHOICES", "MATERIAL_CHOICES")

import dataclasses
import math
import os

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, StringProperty
from bpy_extras.io_utils import ExportHelper

UNIT_CHOICES = (
    ('AUTO', "From Scene", "The scene's length unit (Scene > Units), metres when it has none"),
    ('inches', "Inches", ""),
    ('feet', "Feet", ""),
    ('millimeters', "Millimeters", ""),
    ('centimeters', "Centimeters", ""),
    ('meters', "Meters", ""),
)
MATERIAL_CHOICES = (
    ('STANDARD', "Standard", "Standard materials (Blinn): open in every Max version"),
    ('PHYSICAL', "Physical", "Physical Materials: Max 2017 and later only (experimental)"),
)
# Blender length units -> Max system units ('AUTO').
_SCENE_UNITS = {
    'INCHES': "inches", 'THOU': "inches", 'FEET': "feet", 'MILES': "miles", 'MILLIMETERS': "millimeters",
    'MICROMETERS': "millimeters", 'CENTIMETERS': "centimeters", 'METERS': "meters", 'KILOMETERS': "kilometers",
}
_GEOMETRY_TYPES = {'CURVE': "curve", 'SURFACE': "surface", 'FONT': "text", 'META': "metaball",
                   'CURVES': "hair curves", 'POINTCLOUD': "point cloud", 'VOLUME': "volume",
                   'GREASEPENCIL': "grease pencil", 'GPENCIL': "grease pencil"}


@dataclasses.dataclass
class ExportSettings:
    use_selection: bool = False
    apply_modifiers: bool = True
    units: str = 'AUTO'
    global_scale: float = 1.0
    material_type: str = 'STANDARD'


def _export_report(source):
    from mx_common.report import ImportReport

    class ExportReport(ImportReport):
        """The import report's layout, worded for an export."""

        def summary(self):
            return super().summary().replace("Imported", "Exported", 1).replace("import report", "export report")

        def to_text(self):
            text = super().to_text()
            return text.replace("Import report\n=============", "Export report\n=============", 1) \
                .replace("Imported:", "Written:", 1) \
                .replace("Not supported yet (skipped or placeholder):", "Not written:", 1) \
                .replace("Missing textures:", "Textures not found on disk (paths written anyway):", 1)

    return ExportReport(source=source)


def linear_to_srgb(c):
    c = min(max(c, 0.0), 1.0)
    return c * 12.92 if c <= 0.0031308 else 1.055 * c ** (1.0 / 2.4) - 0.055


def wire_color_8bit(color):
    """``Object.color`` (linear RGBA) -> Max wire colour (0-255 sRGB), the inverse of node_state.wire_color."""
    return tuple(int(round(linear_to_srgb(c) * 255.0)) for c in color[:3])


def max_unit_for(scene, choice):
    if choice != 'AUTO':
        return choice
    settings = scene.unit_settings
    if settings.system == 'NONE':
        return "meters"
    return _SCENE_UNITS.get(settings.length_unit, "meters")


# -----------------------------------------------------------------------------
# Materials

def _linked_from(socket, skip=("ShaderNodeNormalMap", "ShaderNodeBump", "ShaderNodeSeparateColor",
                               "ShaderNodeSeparateRGB", "ShaderNodeMapRange", "ShaderNodeInvert",
                               "ShaderNodeGamma", "ShaderNodeHueSaturation", "ShaderNodeBrightContrast",
                               "ShaderNodeMix", "ShaderNodeMixRGB", "ShaderNodeValToRGB")):
    """The Image Texture node feeding ``socket`` (through simple converter nodes), or None."""
    seen = set()
    stack = [socket]
    while stack:
        sock = stack.pop()
        for link in getattr(sock, "links", ()):
            node = link.from_node
            if node.as_pointer() in seen:
                continue
            seen.add(node.as_pointer())
            if node.bl_idname == "ShaderNodeTexImage":
                return node
            if node.bl_idname in skip or node.type == 'GROUP':
                stack.extend(i for i in node.inputs if i.is_linked)
    return None


def _uv_placement(tex_node):
    """(tiling, offset, w angle, channel) of an Image Texture node's vector input (inverse of the importer's)."""
    tiling, offset, angle, channel = (1.0, 1.0), (0.0, 0.0), 0.0, 1
    vector = tex_node.inputs.get("Vector")
    if vector is None or not vector.is_linked:
        return tiling, offset, angle, channel
    node = vector.links[0].from_node
    if node.bl_idname == "ShaderNodeMapping":
        scale = node.inputs["Scale"].default_value
        loc = node.inputs["Location"].default_value
        rz = node.inputs["Rotation"].default_value[2]
        tiling = (scale[0] or 1.0, scale[1] or 1.0)
        c, s = math.cos(rz), math.sin(rz)
        qx, qy = 0.5 - loc[0], 0.5 - loc[1]
        px, py = c * qx + s * qy, -s * qx + c * qy
        offset = (px / tiling[0] - 0.5, py / tiling[1] - 0.5)
        angle = -rz
        inner = node.inputs["Vector"]
        node = inner.links[0].from_node if inner.is_linked else None
    if node is not None and node.bl_idname == "ShaderNodeUVMap" and node.uv_map.startswith("UVChannel_"):
        try:
            channel = int(node.uv_map[len("UVChannel_"):])
        except ValueError:
            pass
    return tiling, offset, angle, channel


class MaterialConverter:
    """Blender materials -> writer materials (one model object per Blender material, shared)."""

    def __init__(self, writer, kind, report):
        self.w = writer
        self.kind = kind
        self.report = report
        self._done = {}
        self._bitmaps = {}
        self._multi = {}

    def bitmap(self, tex_node):
        image = tex_node.image
        if image is None:
            return None
        path = image.filepath_raw or image.filepath
        if path:
            path = os.path.normpath(bpy.path.abspath(path, library=image.library))
        else:
            path = image.name
        if image.packed_file is not None and not os.path.isfile(path):
            self.report.add_unsupported("texture", "packed image (path written only): " + image.name)
        elif not os.path.isfile(path):
            self.report.add_missing_texture(path)
        tiling, offset, angle, channel = _uv_placement(tex_node)
        key = (path, tiling, offset, angle, channel)
        if key not in self._bitmaps:
            self._bitmaps[key] = self.w.Bitmap(path, name=image.name, u_tiling=tiling[0], v_tiling=tiling[1],
                                               u_offset=offset[0], v_offset=offset[1], w_angle=angle,
                                               map_channel=channel)
            self.report.add_imported("bitmaps")
        return self._bitmaps[key]

    def material(self, mat):
        if mat is None:
            return None
        if mat.name not in self._done:
            self._done[mat.name] = self._convert(mat)
            self.report.add_imported("materials")
        return self._done[mat.name]

    def multi(self, mats):
        """A Multi/Sub-Object for an object's slots (IDs 1, 2, ... = slot order), shared by identical slot lists."""
        key = tuple(m.name if m is not None else None for m in mats)
        if key not in self._multi:
            name = "Multi " + " ".join(n for n in key if n)[:40]
            self._multi[key] = self.w.MultiSubMaterial(name.strip(), [self.material(m) for m in mats],
                                                       ids=list(range(1, len(mats) + 1)),
                                                       names=[n or "" for n in key])
            self.report.add_imported("multi/sub-object materials")
        return self._multi[key]

    def _principled(self, mat):
        tree = mat.node_tree
        if tree is None:
            return None
        output = next((n for n in tree.nodes if n.bl_idname == "ShaderNodeOutputMaterial" and n.is_active_output),
                      None)
        if output is not None and output.inputs["Surface"].is_linked:
            node = output.inputs["Surface"].links[0].from_node
            if node.bl_idname == "ShaderNodeBsdfPrincipled":
                return node
        return next((n for n in tree.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled"), None)

    def _convert(self, mat):
        bsdf = self._principled(mat)
        if bsdf is None:
            if mat.node_tree is not None and len(mat.node_tree.nodes) > 2:
                self.report.add_unsupported("material", "node tree without Principled BSDF (viewport colour "
                                            "written): " + mat.name)
            return self._from_values(mat, tuple(mat.diffuse_color[:3]), mat.roughness, mat.metallic,
                                     mat.diffuse_color[3], {})
        inputs = bsdf.inputs

        def value(name, default):
            sock = inputs.get(name)
            if sock is None:
                return default
            v = sock.default_value
            return tuple(v) if hasattr(v, "__len__") else float(v)

        maps = {}
        for socket_name, key in (("Base Color", "base"), ("Roughness", "roughness"), ("Metallic", "metallic"),
                                 ("Alpha", "alpha")):
            sock = inputs.get(socket_name)
            node = _linked_from(sock) if sock is not None and sock.is_linked else None
            if node is not None:
                maps[key] = self.bitmap(node)
        normal = inputs.get("Normal")
        if normal is not None and normal.is_linked:
            node = _linked_from(normal)
            if node is not None:
                maps["bump"] = self.bitmap(node)
                if normal.links[0].from_node.bl_idname == "ShaderNodeNormalMap":
                    self.report.warn("{:s}: normal map written as a bump map (Max reads it as a height map; "
                                     "use a Normal Bump map in Max)".format(mat.name))
        base = value("Base Color", (0.8, 0.8, 0.8, 1.0))[:3]
        result = self._from_values(mat, base, value("Roughness", 0.5), value("Metallic", 0.0),
                                   value("Alpha", 1.0), maps)
        if self.kind == 'STANDARD':
            result.specular_level = min(value("Specular IOR Level", 0.5) * 200.0, 999.0)
            tint = value("Specular Tint", (1.0, 1.0, 1.0, 1.0))
            result.specular = tuple(tint[:3])
            strength = value("Emission Strength", 0.0)
            emit = value("Emission Color", (0.0, 0.0, 0.0, 1.0))
            if strength > 0.0 and max(emit[:3]) > 0.0:
                result.self_illumination = min(100.0, 100.0 * strength * max(emit[:3]))
        else:
            result.emission = value("Emission Strength", 0.0)
            result.emit_color = tuple(value("Emission Color", (1.0, 1.0, 1.0, 1.0))[:3])
            result.trans_ior = value("IOR", 1.5)
            result.transparency = value("Transmission Weight", 0.0)
        return result

    def _from_values(self, mat, base, roughness, metallic, alpha, maps):
        two_sided = not mat.use_backface_culling
        if self.kind == 'PHYSICAL':
            m = self.w.PhysicalMaterial(mat.name, base_color=tuple(base), roughness=roughness, metalness=metallic,
                                        thin_walled=False)
            m.base_color_map = maps.get("base")
            m.roughness_map = maps.get("roughness")
            m.metalness_map = maps.get("metallic")
            m.cutout_map = maps.get("alpha")
            m.bump_map = maps.get("bump")
            if alpha < 1.0:
                m.transparency = 1.0 - alpha
            return m
        if metallic > 0.0 or maps.get("metallic") is not None:
            self.report.add_unsupported("material", "metallic (Standard material has none): " + mat.name)
        m = self.w.StandardMaterial(mat.name, diffuse=tuple(base), glossiness=(1.0 - roughness) * 100.0,
                                    opacity=alpha * 100.0, two_sided=two_sided)
        m.diffuse_map = maps.get("base")
        m.glossiness_map = maps.get("roughness")
        m.opacity_map = maps.get("alpha")
        m.bump_map = maps.get("bump")
        return m


# -----------------------------------------------------------------------------
# Meshes

def _mesh_model(writer, mesh, factor, report, name):
    import numpy as np
    from .smoothing import smoothing_groups_from_sharp

    n_verts = len(mesh.vertices)
    co = np.empty(n_verts * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", co)
    co *= factor
    positions = [tuple(p) for p in co.reshape(-1, 3).tolist()]
    n_loops = len(mesh.loops)
    loop_verts = np.empty(n_loops, dtype=np.int64)
    mesh.loops.foreach_get("vertex_index", loop_verts)
    n_polys = len(mesh.polygons)
    starts = np.empty(n_polys, dtype=np.int64)
    totals = np.empty(n_polys, dtype=np.int64)
    mesh.polygons.foreach_get("loop_start", starts)
    mesh.polygons.foreach_get("loop_total", totals)
    lv = loop_verts.tolist()
    polygons = [lv[s:s + t] for s, t in zip(starts.tolist(), totals.tolist())]
    mat_index = np.empty(n_polys, dtype=np.int64)
    mesh.polygons.foreach_get("material_index", mat_index)

    sharp_faces = None
    attr = mesh.attributes.get("sharp_face")
    if attr is not None and attr.domain == 'FACE':
        values = np.empty(n_polys, dtype=bool)
        attr.data.foreach_get("value", values)
        sharp_faces = values.tolist()
    sharp_edges = []
    attr = mesh.attributes.get("sharp_edge")
    if attr is not None and attr.domain == 'EDGE':
        values = np.empty(len(mesh.edges), dtype=bool)
        attr.data.foreach_get("value", values)
        edge_verts = np.empty(len(mesh.edges) * 2, dtype=np.int64)
        mesh.edges.foreach_get("vertices", edge_verts)
        pairs = edge_verts.reshape(-1, 2)[values]
        sharp_edges = [tuple(p) for p in pairs.tolist()]
    groups = smoothing_groups_from_sharp(polygons, sharp_edges, sharp_faces)

    channels = {}
    for index, layer in enumerate(mesh.uv_layers):
        channel = index + 1
        if layer.name.startswith("UVChannel_"):
            try:
                channel = int(layer.name[len("UVChannel_"):])
            except ValueError:
                pass
        if channel in channels:
            report.add_unsupported("UV layer", "duplicate channel {:d} ({:s})".format(channel, name))
            continue
        uv = np.empty(n_loops * 2, dtype=np.float64)
        layer.data.foreach_get("uv", uv)
        unique, inverse = np.unique(uv.reshape(-1, 2), axis=0, return_inverse=True)
        inverse = inverse.reshape(-1).tolist()
        verts = [(u, v, 0.0) for u, v in unique.tolist()]
        faces = [inverse[s:s + t] for s, t in zip(starts.tolist(), totals.tolist())]
        channels[channel] = writer.MapChannel(verts, faces)
    return polygons, positions, mat_index.tolist(), groups, channels


def _drop_degenerate(polygons, mat_index, groups, channels, report, name):
    keep = [i for i, p in enumerate(polygons) if len(p) >= 3 and len(set(p)) == len(p)]
    if len(keep) == len(polygons):
        return polygons, mat_index, groups, channels
    report.warn("{:s}: {:d} degenerate polygon(s) not written".format(name, len(polygons) - len(keep)))
    for ch in channels.values():
        ch.faces = [ch.faces[i] for i in keep]
    return [polygons[i] for i in keep], [mat_index[i] for i in keep], [groups[i] for i in keep], channels


# -----------------------------------------------------------------------------
# Scene

class SceneExporter:

    def __init__(self, context, settings, report):
        from mx_common.units import scene_unit_in_metres
        import maxfile.writer as writer
        self.w = writer
        self.context = context
        self.settings = settings
        self.report = report
        scene = context.scene
        self.unit = max_unit_for(scene, settings.units)
        metres_per_bu = scene.unit_settings.scale_length if scene.unit_settings.system != 'NONE' else 1.0
        self.factor = metres_per_bu * settings.global_scale / scene_unit_in_metres(self.unit)
        self.materials = MaterialConverter(writer, settings.material_type, report)
        self.depsgraph = context.evaluated_depsgraph_get()
        self._meshes = {}
        self._with_ids = {}

    def candidates(self):
        objects = list(self.context.view_layer.objects)
        if self.settings.use_selection:
            objects = [o for o in objects if o.select_get()]
        return objects

    def build(self):
        w = self.w
        render = self.context.scene.render
        scene = w.Scene(unit=self.unit, frame_rate=max(1, int(round(render.fps / render.fps_base))),
                        animation_end=max(0, self.context.scene.frame_end))
        objects = [o for o in self.candidates() if self._exportable(o)]
        exported = set(o.name for o in objects)
        nodes = {}
        # Parents first (Blender parent chains), so a node's parent node exists when it is created.
        objects.sort(key=self._depth)
        for obj in objects:
            parent = obj.parent
            while parent is not None and parent.name not in exported:
                parent = parent.parent
            node = self._node(obj, nodes.get(parent.name) if parent is not None else None, parent)
            if node is not None:
                nodes[obj.name] = node
                scene.add(node)
        return scene

    @staticmethod
    def _depth(obj):
        depth, parent = 0, obj.parent
        while parent is not None:
            depth, parent = depth + 1, parent.parent
        return depth

    def _exportable(self, obj):
        if obj.type in ('MESH', 'EMPTY'):
            if obj.type == 'EMPTY' and obj.instance_type == 'COLLECTION' and obj.instance_collection:
                self.report.add_unsupported("object", "collection instance (written as a Dummy)")
            return True
        label = {'CAMERA': "camera", 'LIGHT': "light", 'ARMATURE': "armature", 'LATTICE': "lattice",
                 'SPEAKER': "speaker", 'LIGHT_PROBE': "light probe"}.get(obj.type) or \
            _GEOMETRY_TYPES.get(obj.type, obj.type.lower())
        self.report.add_unsupported("object", label)
        return False

    def _transform(self, obj, parent_obj):
        world = obj.matrix_world
        local = parent_obj.matrix_world.inverted_safe() @ world if parent_obj is not None else world
        loc, rot, scale = local.decompose()
        return self.w.Transform(tuple(v * self.factor for v in loc), (rot.w, rot.x, rot.y, rot.z), tuple(scale))

    def _node(self, obj, parent_node, parent_obj):
        w = self.w
        color = obj.get("mx_frozen_color") if obj.get("mx_frozen") else None
        wire = wire_color_8bit(color if color is not None else obj.color)
        node = w.Node(obj.name, parent=parent_node, transform=self._transform(obj, parent_obj), wire_color=wire,
                      hidden=obj.hide_get() or obj.hide_viewport, frozen=bool(obj.get("mx_frozen")) or obj.hide_select)
        if obj.type == 'EMPTY':
            # The node scale applies on top, as Blender scales the empty's display.
            node.dummy_size = max(obj.empty_display_size * 2.0 * self.factor, 1e-3)
            self.report.add_imported("helpers")
            return node
        mesh_model, mat_index = self._mesh(obj)
        if mesh_model is None:
            node.mesh = None
            self.report.add_unsupported("object", "empty mesh (written as a Dummy)")
            return node
        node.mesh = mesh_model
        self._materials(obj, node, mat_index)
        self.report.add_imported("objects")
        if node.hidden:
            self.report.add_imported("hidden objects")
        if node.frozen:
            self.report.add_imported("frozen objects")
        return node

    def _mesh(self, obj):
        modifiers = [m for m in obj.modifiers if m.show_viewport]
        shared = not modifiers and not (obj.data.shape_keys and obj.data.shape_keys.key_blocks)
        key = obj.data.name if shared else None
        if key is not None and key in self._meshes:
            return self._meshes[key]
        if self.settings.apply_modifiers:
            source = obj.evaluated_get(self.depsgraph)
            mesh = source.to_mesh(preserve_all_data_layers=True, depsgraph=self.depsgraph)
            if modifiers:
                self.report.add_imported("modifiers baked into Editable Poly", len(modifiers))
        else:
            mesh = obj.data
            for m in modifiers:
                self.report.add_unsupported("modifier", m.type.replace("_", " ").title())
        try:
            if len(mesh.polygons) == 0:
                result = (None, [])
            else:
                polygons, positions, mat_index, groups, channels = _mesh_model(
                    self.w, mesh, self.factor, self.report, obj.name)
                polygons, mat_index, groups, channels = _drop_degenerate(
                    polygons, mat_index, groups, channels, self.report, obj.name)
                model = self.w.EditablePoly(positions, polygons, material_ids=[1] * len(polygons),
                                            smoothing_groups=groups, map_channels=channels)
                result = (model, mat_index)
                if any(e.is_loose for e in mesh.edges):
                    self.report.add_unsupported("geometry", "loose edges (no polygon)")
        finally:
            if self.settings.apply_modifiers:
                obj.evaluated_get(self.depsgraph).to_mesh_clear()
        if key is not None:
            self._meshes[key] = result
        return result

    def _materials(self, obj, node, mat_index):
        slots = [s.material for s in obj.material_slots]
        if not slots or all(m is None for m in slots):
            return
        count = len(slots)
        used = sorted({min(i, count - 1) for i in mat_index}) if mat_index else [0]
        if len(used) == 1:
            # One slot in use: a plain material keeps the file simple.
            node.material = self.materials.material(slots[used[0]])
            return
        node.material = self.materials.multi(slots)
        # Face IDs: slot index + 1 (out-of-range indices clamp to the last slot, as Blender draws them).
        ids = [min(i, count - 1) + 1 for i in mat_index]
        key = (id(node.mesh), tuple(ids))
        if key not in self._with_ids:
            self._with_ids[key] = dataclasses.replace(node.mesh, material_ids=ids)
        node.mesh = self._with_ids[key]


def export_file(operator, context, filepath, settings=None):
    """Export the scene to ``filepath``; reports through ``operator``. Returns an operator result set."""
    from mx_common.report import store_in_text

    settings = settings or ExportSettings()
    report = _export_report(filepath)
    try:
        import maxfile.writer as writer
    except ImportError as ex:
        operator.report({'ERROR'}, "The maxfile library is missing: {:s}".format(str(ex)))
        return {'CANCELLED'}
    try:
        exporter = SceneExporter(context, settings, report)
        scene = exporter.build()
        options = writer.WriterOptions()
        writer.write(scene, filepath, options)
    except (OSError, ValueError) as ex:
        operator.report({'ERROR'}, "Cannot write {!r}: {:s}".format(filepath, str(ex)))
        return {'CANCELLED'}
    report.warn("Experimental writer: the file imitates Max 2015; please report how it opens in Max")
    store_in_text(report, name="Export Report")
    operator.report({'WARNING'} if report.unsupported or report.errors else {'INFO'}, report.summary())
    return {'FINISHED'}


# -----------------------------------------------------------------------------
# Operator (registered by the add-on's __init__)

class EXPORT_SCENE_OT_mx_max(bpy.types.Operator, ExportHelper):
    """Export the scene as a .max file (experimental: imitates files saved by Max 2015)"""
    bl_idname = "export_scene.mx_max"
    bl_label = "Export .max"
    bl_options = {'PRESET'}

    filename_ext = ".max"
    filter_glob: StringProperty(default="*.max", options={'HIDDEN'})

    use_selection: BoolProperty(
        name="Selected Only",
        description="Export only the selected objects",
        default=False,
    )
    apply_modifiers: BoolProperty(
        name="Apply Modifiers",
        description="Bake modifiers into the Editable Poly (modifier stacks are not written yet; off: the "
                    "base mesh only)",
        default=True,
    )
    units: EnumProperty(
        name="System Unit",
        description="Max system unit of the file; lengths are converted to it",
        items=UNIT_CHOICES,
        default='AUTO',
    )
    global_scale: FloatProperty(
        name="Scale",
        description="Extra scale factor applied on export",
        min=1e-6, max=1e6, soft_min=0.001, soft_max=1000.0,
        default=1.0,
    )
    material_type: EnumProperty(
        name="Materials",
        description="Max material class written for Blender materials",
        items=MATERIAL_CHOICES,
        default='STANDARD',
    )

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        for name in ("use_selection", "apply_modifiers", "units", "global_scale", "material_type"):
            layout.prop(self, name)

    def execute(self, context):
        settings = ExportSettings(
            use_selection=self.use_selection,
            apply_modifiers=self.apply_modifiers,
            units=self.units,
            global_scale=self.global_scale,
            material_type=self.material_type,
        )
        return export_file(self, context, self.filepath, settings)


def menu_func_export(self, _context):
    self.layout.operator(EXPORT_SCENE_OT_mx_max.bl_idname, text=".max Scene (.max, experimental)")
