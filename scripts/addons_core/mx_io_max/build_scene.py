# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Turn data parsed by ``maxfile`` into Blender objects.

Order of work for one file:

1. Open it with ``maxfile`` (a corrupt or unsupported file gives a clear error, never a crash).
2. Create one Blender object per Max node, keeping the hierarchy and transforms. Scene units are converted by
   scaling translations and geometry, so object scales stay as they were in Max.
3. Geometry (Editable Poly/Mesh, primitives, modifier stacks), materials, lights and cameras are converted
   when ``maxfile`` decodes them; anything else becomes an empty and is listed in the import report.
4. The import report goes to a text block, and a one-line summary to the status bar.

Object, material, modifier and primitive conversion live in ``materials/``, ``modifiers/``, ``lights.py`` and
``mesh_build.py``. Decoded data is matched by duck typing on ``maxfile``'s dataclass names, so this module
works with whatever decoders the installed ``maxfile`` provides.
"""

__all__ = (
    "ImportSettings",
    "import_file",
)

import array
import dataclasses
import os

import bpy
from mathutils import Matrix

UNIT_CHOICES = (
    ('AUTO', "From File", "Use the units stored in the file (inches when they can't be read)"),
    ('inches', "Inches", ""),
    ('feet', "Feet", ""),
    ('millimeters', "Millimeters", ""),
    ('centimeters', "Centimeters", ""),
    ('meters', "Meters", ""),
)


@dataclasses.dataclass
class ImportSettings:
    units: str = 'AUTO'
    global_scale: float = 1.0
    use_collection: bool = True
    keep_modifier_stack: bool = True        # False = collapse the stack (apply modifiers) on import.
    import_materials: bool = True
    import_lights: bool = True
    import_cameras: bool = True
    texture_search_dirs: tuple = ()


def _kind(value):
    return type(value).__name__ if value is not None else None


def _matrix(rows):
    return Matrix([list(row) for row in rows])


def _is_identity(matrix, eps=1e-5):
    return all(abs(matrix[i][j] - (1.0 if i == j else 0.0)) < eps for i in range(4) for j in range(4))


class SceneBuilder:
    """Builds one ``.max`` file into the current Blender scene."""

    def __init__(self, context, filepath, settings, report, file_units=None):
        from mx_common.units import METRES_PER_UNIT, scene_unit_in_metres
        from .materials import nodes as material_nodes, textures

        self.context = context
        self.filepath = filepath
        self.settings = settings
        self.report = report
        self.unit_scale = settings.global_scale
        units = settings.units
        unit_scale = 1.0
        if units == 'AUTO':
            # maxfile's SceneUnits (docs/format/overview.md §4.3); some files store a unit that doesn't match
            # their content, which the import options can override.
            if file_units is not None and file_units.unit in METRES_PER_UNIT and file_units.scale > 0.0:
                units, unit_scale = file_units.unit, file_units.scale
            else:
                units = "inches"
                report.warn("The file stores no readable system unit: assuming inches; "
                            "choose the units in the import options if the scale is wrong")
        self.unit_scale *= scene_unit_in_metres(units, unit_scale)
        self.resolver = textures.TextureResolver(filepath, settings.texture_search_dirs)
        self.materials = material_nodes.MaterialBuilder(self.resolver, report)
        self._mesh_cache = {}           # (geometry object index, offset matrix key) -> Mesh
        self._notes = {}                # Approximation note -> names of the objects it applies to.
        self._world_from = None         # Name of the node the World was made from.
        self._world_directions = {}     # Object name -> world direction its -Z must point along (sun systems).
        self.cameras = []               # (object, CameraDesc).
        self._physical_lights = 0       # Lights in physical units (photometric, sun systems).
        self._material_cache = {}       # material object index -> list of Blender materials (slots)
        self.objects = {}               # node index -> Blender object

    # Units.

    def _scaled(self, matrix):
        """Convert a 4x4 transform from scene units: scale the translation only."""
        result = matrix.copy()
        result.translation = matrix.translation * self.unit_scale
        return result

    # Entry point.

    def build(self, mf):
        if self.settings.use_collection:
            name = os.path.splitext(os.path.basename(self.filepath))[0]
            self.collection = bpy.data.collections.new(name)
            self.context.scene.collection.children.link(self.collection)
        else:
            self.collection = self.context.collection

        scene = mf.scene
        for node in self._parents_first(scene.roots):
            obj = self._build_node(scene, node)
            self.objects[node.index] = obj
            if node.parent is not None and node.parent.index in self.objects:
                obj.parent = self.objects[node.parent.index]
                obj.matrix_parent_inverse = Matrix.Identity(4)
            obj.matrix_basis = self._scaled(_matrix(node.local_matrix()))
        for node in scene.nodes:
            obj = self.objects.get(node.index)
            if obj is not None:
                self._link_target(scene, node, obj)
                self._apply_node_state(node, obj)
        self._aim_directions()
        self._finish_cameras()
        self._flush_notes()
        for warning in mf.warnings:
            self.report.warn(warning)
        return list(self.objects.values())

    def _aim_directions(self):
        """Lights whose direction is given in world space (sun systems): turn them so -Z points along it."""
        from mathutils import Vector
        if not self._world_directions:
            return
        self.context.view_layer.update()
        for name, direction in self._world_directions.items():
            obj = bpy.data.objects.get(name)
            if obj is None or Vector(direction).length == 0.0:
                continue
            rot = (-Vector(direction)).to_track_quat('Z', 'Y').to_matrix().to_4x4()
            world = obj.matrix_world
            obj.matrix_world = Matrix.Translation(world.translation) @ rot

    def _finish_cameras(self):
        """Make the first camera the scene camera (when the scene has none) and take its exposure."""
        from . import lights
        scene = self.context.scene
        if not self.cameras or scene.camera is not None:
            return
        obj, desc = self.cameras[0]
        scene.camera = obj
        if desc.exposure_value is not None and self._physical_lights:
            scene.view_settings.exposure = lights.exposure_from_ev(desc.exposure_value)
            self.note(obj.name, "Physical camera exposure EV {:g} set as the scene exposure ({:+.2f})".format(
                desc.exposure_value, scene.view_settings.exposure))

    @staticmethod
    def _parents_first(roots):
        stack = list(reversed(roots))
        while stack:
            node = stack.pop()
            yield node
            stack.extend(reversed(node.children))

    # Nodes.

    def _new_object(self, name, data):
        obj = bpy.data.objects.new(name, data)
        self.collection.objects.link(obj)
        return obj

    def _build_node(self, scene, node):
        name = node.name or "Node{:d}".format(node.index)
        target = node.object
        decoded = scene.decode(target) if target is not None else None
        kind = _kind(decoded)

        # Modifier stacks (possibly nested wrappers): the base geometry plus modifiers, top of the stack first.
        stack = None
        if kind == "ModifierStack":
            base, modifiers = scene.resolve_geometry(node)
            stack = list(reversed(modifiers))       # Bottom (applied first) to top.
            target = base
            decoded = scene.decode(base) if base is not None else None
            kind = _kind(decoded)

        obj = None
        if kind in {"MeshData", "PrimitiveData"}:
            obj = self._new_object(name, self._mesh_for(target.index, decoded, node, name))
            self.report.add_imported("objects")
        elif kind in {"LightData", "CameraData"}:
            obj = self._build_light_or_camera(name, decoded)
        if obj is None:
            from .node_state import HELPER_CLASSES
            obj = self._new_object(name, None)
            label = target.class_label() if target is not None else None
            helper = HELPER_CLASSES.get(label)
            if helper is not None:
                obj.empty_display_type = helper[0]
                obj.empty_display_size = min(max(helper[1] * self.unit_scale, 0.01), 0.5)
                self.report.add_imported("helpers")
            else:
                obj.empty_display_type = 'PLAIN_AXES'
                obj.empty_display_size = 0.2
                if target is not None:
                    self.report.add_unsupported("object", label)
                self.report.add_imported("empties")

        if obj.type == 'MESH':
            if stack is not None:
                self._build_stack(obj, scene, stack)
            if self.settings.import_materials and node.material is not None:
                self._assign_materials(obj, scene, node.material, decoded)
        obj["mx_node_index"] = node.index
        return obj

    def _build_light_or_camera(self, name, decoded):
        from . import lights
        if _kind(decoded) == "LightData" and self.settings.import_lights:
            params = dict(decoded.params, name=name)
            world = lights.world_from_light(decoded.class_name, params)
            if world is not None:
                self._set_world(name, world)
            desc = lights.light_from_params(decoded.class_name, params, unit_scale=self.unit_scale)
            if desc is None:
                if world is None:
                    return None
                obj = self._new_object(name, None)      # The light's node, kept as a helper.
                obj.empty_display_type = 'SPHERE'
                obj.empty_display_size = min(max(5.0 * self.unit_scale, 0.05), 0.5)
                obj["mx_source_class"] = decoded.class_name
                return obj
            self.report.add_imported("lights")
            if desc.source_class in lights.PHYSICAL_CLASSES:
                self._physical_lights += 1
            for note in desc.notes:
                self.note(name, note)
            obj = lights.create_light(desc, self.collection, self.unit_scale)
            if desc.direction is not None:
                self._world_directions[obj.name] = desc.direction
            return obj
        if _kind(decoded) == "CameraData" and self.settings.import_cameras:
            desc = lights.camera_from_params(decoded.class_name, dict(decoded.params, name=name))
            self.report.add_imported("cameras")
            obj = lights.create_camera(desc, self.collection, self.unit_scale)
            self.cameras.append((obj, desc))
            return obj
        return None

    def _set_world(self, name, desc):
        from . import lights
        if self._world_from is not None:
            self.note(name, "a second sky / environment light is not imported (the World comes from {!r})".format(
                self._world_from))
            return
        self._world_from = name
        lights.setup_world(self.context.scene, desc)
        self.report.add_imported("world")
        for note in desc.notes:
            self.note(name, note)
        self.note(name, "{:s} imported as the World".format(desc.source_class or "sky light"))

    def note(self, name, text):
        """An approximation worth reporting; the same note for several objects is reported once, with a count."""
        self._notes.setdefault(text, []).append(name)

    def _flush_notes(self):
        for text, names in self._notes.items():
            shown = ", ".join(repr(n) for n in names[:3]) + (", ..." if len(names) > 3 else "")
            self.report.warn("{:s} ({:d}: {:s})".format(text, len(names), shown))
        self._notes.clear()

    # Node state.

    def _link_target(self, scene, node, obj):
        """A Look At controller (target cameras / lights and any node aimed at a target) as a Track To constraint."""
        from . import lights
        try:
            from maxfile.objects.lights import target_node_of
        except ImportError:
            return
        target = target_node_of(scene, node)
        if target is None:
            return
        target_obj = self.objects.get(target.index)
        if target_obj is None or target_obj is obj:
            return
        roll = 0.0
        look_at = scene.decode(node.controller) if node.controller is not None else None
        if look_at is not None and isinstance(getattr(look_at, "roll", None), float):
            roll = look_at.roll
        lights.add_target_constraint(obj, target_obj, roll=roll)
        obj["mx_target"] = target_obj.name
        self.report.add_imported("targets")

    def _apply_node_state(self, node, obj):
        from . import node_state
        color = node_state.wire_color(getattr(node, "wire_color", None))
        if color is not None:
            obj.color = color
        if getattr(node, "is_frozen", False):
            node_state.apply_frozen(obj)
            self.report.add_imported("frozen objects")
        if getattr(node, "is_hidden", False):
            node_state.apply_hidden(obj)
            self.report.add_imported("hidden objects")

    # Geometry.

    def _mesh_for(self, geometry_index, decoded, node, name):
        offset = _matrix(node.object_offset.matrix())
        key = (geometry_index, tuple(round(v, 6) for row in offset for v in row))
        mesh = self._mesh_cache.get(key)
        if mesh is not None:
            self.report.add_imported("instances")
            return mesh
        live = False
        if _kind(decoded) == "PrimitiveData":
            # A live primitive regenerates from its parameters, so it can't hold an object offset: only
            # primitives whose pivot is at their object origin stay live (90 % of the corpus).
            mesh, live = self._primitive_mesh(decoded, name, live=_is_identity(offset))
        else:
            mesh = self._mesh_from_data(decoded, name)
        if not live:
            # Object offset: bake it into the geometry so the Blender origin sits at the Max pivot.
            mesh.transform(self._scaled(offset) @ Matrix.Scale(self.unit_scale, 4))
        self._mesh_cache[key] = mesh
        self.report.add_imported("meshes")
        return mesh

    def _mesh_from_data(self, data, name):
        from . import mesh_build, smoothing
        from .materials.nodes import uv_layer_name
        faces = [tuple(face) for face in data.faces]
        groups = list(data.smoothing_groups) if data.smoothing_groups else [1] * len(faces)
        sharp_edges, sharp_faces = smoothing.sharp_from_smoothing_groups(faces, groups)
        uv_layers = []
        for channel, mapping in sorted(data.map_channels.items()):
            if channel < 1:
                continue    # Vertex colour / illumination / alpha channels: not imported yet.
            if len(mapping.faces) != len(faces) or any(len(a) != len(b) for a, b in zip(mapping.faces, faces)):
                self.report.warn("{:s}: map channel {:d} doesn't match the geometry, skipped".format(name, channel))
                continue
            verts = mapping.vertices
            uvs = [tuple(verts[i][:2]) for face in mapping.faces for i in face]
            uv_layers.append((uv_layer_name(channel), uvs))
        mesh = mesh_build.build_mesh(
            name, data.positions, faces, uv_layers=uv_layers, sharp_edges=sharp_edges, sharp_faces=sharp_faces)
        mesh["mx_material_ids"] = list(data.material_ids) if data.material_ids else [1] * len(faces)
        return mesh

    def _primitive_mesh(self, data, name, live=True):
        """
        ``(mesh, is_live)`` for a primitive: a live primitive (sizes in metres) when the Max-Style Primitives
        add-on is enabled and ``live`` allows it, else a plain mesh in scene units (the caller scales it).
        """
        from .primitives import convert as primitive_convert
        if data.cached_mesh is not None:
            # Max's own cached mesh is exact (no corpus file has one, see docs/format/overview.md §6.4).
            return self._mesh_from_data(data.cached_mesh, name), False
        try:
            import mx_primitives
            geometry = mx_primitives.geometry
        except (ImportError, AttributeError):
            self.report.add_unsupported("primitive", data.kind)
            return bpy.data.meshes.new(name), False
        registered = hasattr(bpy.types.Mesh, "mx_primitive") and hasattr(mx_primitives, "create_primitive_object")
        live = live and registered
        kind, params, notes = primitive_convert.builder_params(
            data.kind, dict(data.params), geometry.PARAMETERS, self.unit_scale if live else 1.0)
        for note in notes:
            self.report.warn("{:s}: {:s}".format(name, note))
        if kind is None:
            self.report.add_unsupported("primitive", data.kind)
            return bpy.data.meshes.new(name), False
        try:
            if live:
                obj = mx_primitives.create_primitive_object(name, kind, params, collection=self.collection)
                mesh = obj.data
                bpy.data.objects.remove(obj)
                ids = array.array("i", [0]) * len(mesh.polygons)
                mesh.polygons.foreach_get("material_index", ids)
                mesh["mx_material_ids"] = [i + 1 for i in ids]
                self.report.add_imported("live primitives")
                return mesh, True
            mesh = self._mesh_from_generated(geometry.generate(kind, **params), name)
        except (TypeError, ValueError, KeyError) as ex:
            self.report.warn("{:s}: could not rebuild {:s} ({:s})".format(name, data.kind, str(ex)))
            return bpy.data.meshes.new(name), False
        self.report.add_imported("static primitives")
        return mesh, False

    def _mesh_from_generated(self, data, name):
        """A plain mesh from ``mx_primitives.geometry.MeshData`` (scene units)."""
        from . import mesh_build, smoothing
        from .materials.nodes import uv_layer_name
        faces = [tuple(face) for face in data.faces]
        sharp_edges, sharp_faces = smoothing.sharp_from_smoothing_groups(faces, list(data.smoothing_groups))
        uv_layers = []
        if data.uvs is not None:
            uv_layers.append((uv_layer_name(1), [tuple(uv) for face in data.uvs for uv in face]))
        mesh = mesh_build.build_mesh(name, data.vertices, faces, uv_layers=uv_layers, sharp_edges=sharp_edges,
                                     sharp_faces=sharp_faces)
        mesh["mx_material_ids"] = [i + 1 for i in data.material_ids]
        return mesh

    def _build_stack(self, obj, scene, modifiers):
        """Add Max modifiers (scene objects, bottom of the stack first) as Blender modifiers."""
        from .modifiers import convert as modifier_convert
        for mod_obj in modifiers:
            class_name = mod_obj.class_label()
            decoded = scene.decode(mod_obj)
            params = dict(getattr(decoded, "params", None) or {})
            if modifier_convert.add_modifier(obj, class_name, params, enabled=getattr(decoded, "enabled", None)):
                self.report.add_imported("modifiers")
            else:
                self.report.add_unsupported("modifier", class_name)
                break   # Import the stack up to the unsupported modifier (ROADMAP Phase 2d).
        if not self.settings.keep_modifier_stack:
            modifier_convert.collapse(obj)

    # Materials.

    def _blender_materials(self, scene, material_object):
        """Material slots for a Max material: one for a plain material, sub-materials for Multi/Sub."""
        from .materials import convert as material_convert
        if material_object.index in self._material_cache:
            return self._material_cache[material_object.index]
        decoded = scene.decode(material_object)
        result = (None, [])
        if _kind(decoded) == "MaterialData":
            if decoded.sub_materials is not None:
                built = []
                for sub in decoded.sub_materials:
                    built.append(self._build_material_data(sub) if sub is not None else None)
                result = (list(decoded.sub_ids) if decoded.sub_ids else list(range(1, len(built) + 1)), built)
            else:
                result = (None, [self._build_material_data(decoded)])
        else:
            # Not decoded: a placeholder named after the class (it is reported by the builder).
            label = material_object.class_label()
            result = (None, [self.materials.build(material_convert.convert(label, {"name": label}))])
        self._material_cache[material_object.index] = result
        return result

    def _build_material_data(self, data):
        from .materials import convert as material_convert
        params = dict(data.params)
        params.setdefault("name", data.name or data.class_name)
        for key, tex in (data.maps or {}).items():
            converted = self._convert_map(tex)
            if converted is not None:
                params[key] = converted
        desc = material_convert.convert(data.class_name, params)
        if _kind(desc) != "Placeholder":     # Placeholders are reported as unsupported by the builder.
            self.report.add_imported("materials")
        return self.materials.build(desc)

    def _convert_map(self, tex):
        """``maxfile`` MapData to a material model map (bitmaps only for now; others are reported)."""
        from .materials import model
        if tex is None:
            return None
        if tex.class_name in {"Bitmaptexture", "Bitmap", "VRayBitmap", "CoronaBitmap"} and tex.path:
            params = tex.params or {}
            return model.Bitmap(
                name=tex.name or "", path=tex.path,
                uv_channel=params.get("map_channel", 1),
                tiling=(params.get("u_tiling", 1.0), params.get("v_tiling", 1.0)),
                offset=(params.get("u_offset", 0.0), params.get("v_offset", 0.0)),
            )
        self.report.add_unsupported("map", tex.class_name)
        return None

    def _assign_materials(self, obj, scene, material_object, decoded):
        from . import material_ids
        sub_ids, mats = self._blender_materials(scene, material_object)
        mesh = obj.data
        face_ids = list(mesh.get("mx_material_ids", [1] * len(mesh.polygons)))
        if len(face_ids) != len(mesh.polygons):
            face_ids = [1] * len(mesh.polygons)
        slot_of_sub, face_slots = material_ids.slots_for_faces(face_ids, sub_ids)
        # Slots go on the object (Max assigns materials per node, instances can differ).
        slots = [None] * (max((s for s in slot_of_sub if s is not None), default=-1) + 1)
        for position, slot in enumerate(slot_of_sub):
            if slot is not None and position < len(mats):
                slots[slot] = mats[position]
        # The mesh may be shared with instances that already added the slots.
        while len(mesh.materials) < len(slots):
            mesh.materials.append(None)
        for index, mat in enumerate(slots):
            obj.material_slots[index].link = 'OBJECT'
            obj.material_slots[index].material = mat
        if len(slots) > 1:
            mesh.polygons.foreach_set("material_index", face_slots)


def import_file(operator, context, filepath, settings=None):
    """Import one ``.max`` file, reporting problems through ``operator``. Returns an operator result set."""
    import maxfile
    from mx_common.report import ImportReport, store_in_text

    settings = settings or ImportSettings()
    report = ImportReport(source=filepath)
    try:
        with maxfile.open(filepath) as mf:
            builder = SceneBuilder(context, filepath, settings, report, getattr(mf, "units", None))
            objects = builder.build(mf)
    except maxfile.NotCompoundFileError:
        operator.report({'ERROR'}, "Not a .max file (no Compound File signature): {!r}".format(filepath))
        return {'CANCELLED'}
    except maxfile.MaxFileError as ex:
        operator.report({'ERROR'}, "Cannot import {!r}: {:s}".format(os.path.basename(filepath), str(ex)))
        return {'CANCELLED'}
    except OSError as ex:
        operator.report({'ERROR'}, "Cannot read {!r}: {:s}".format(filepath, ex.strerror or str(ex)))
        return {'CANCELLED'}

    for obj in context.view_layer.objects:
        obj.select_set(False)
    for obj in objects:
        if obj.name in context.view_layer.objects:
            obj.select_set(True)
    if objects and objects[0].name in context.view_layer.objects:
        context.view_layer.objects.active = objects[0]

    store_in_text(report)
    operator.report({'WARNING'} if not report.is_clean else {'INFO'}, report.summary())
    return {'FINISHED'}
