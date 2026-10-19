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
import math
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


# Editable Mesh triangles are merged into Max's polygons (hidden edges dissolved) for meshes up to this many
# faces, and for any mesh under a subdivision modifier.
MERGE_TRIANGLES_UP_TO = 20000


def _is_identity(matrix, eps=1e-5):
    return all(abs(matrix[i][j] - (1.0 if i == j else 0.0)) < eps for i in range(4) for j in range(4))


class SceneBuilder:
    """Builds one ``.max`` file into the current Blender scene."""

    def __init__(self, context, filepath, settings, report, file_units=None):
        from mx_common.units import METRES_PER_UNIT, scene_unit_in_metres
        from .materials import maps as material_maps, nodes as material_nodes, textures

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
        self.materials = material_nodes.MaterialBuilder(self.resolver, report, unit_scale=self.unit_scale)
        self.maps = material_maps.MapConverter(
            param_reader=self._map_params,
            unsupported=lambda name: report.add_unsupported("map", name),
            note=lambda text: self.note("materials", text))
        self._scene = None
        self._mesh_cache = {}           # (geometry object index, offset matrix key) -> Mesh
        self._notes = {}                # Approximation note -> names of the objects it applies to.
        self._world_from = None         # Name of the node the World was made from.
        self._world_directions = {}     # Object name -> world direction its -Z must point along (sun systems).
        self.cameras = []               # (object, CameraDesc).
        self._physical_lights = 0       # Lights in physical units (photometric, sun systems).
        self._material_cache = {}       # material object index -> list of Blender materials (slots)
        self._built_materials = {}      # material object index -> Blender material
        self._curve_cache = {}          # (shape object index, Edit Splines, offset key) -> Curve
        self._uv_meshes = {}            # (mesh name, UV modifier objects) -> Mesh with those UVs
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
        self._scene = scene
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
        if desc.exposure_value is not None and self._physical_lights and not self._world_directions:
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

        # Modifier stacks (possibly nested wrappers): the base geometry plus modifiers, bottom of the stack first.
        stack = None
        if kind == "ModifierStack":
            base, stack = self._stack_entries(scene, node)
            target = base
            decoded = scene.decode(base) if base is not None else None
            kind = _kind(decoded)

        obj = None
        if kind in {"MeshData", "PrimitiveData"}:
            from .modifiers.convert import SUBDIVISION, converter_key
            subdivided = any(converter_key(m.class_label()) in SUBDIVISION for m, _r, _d in stack or ())
            obj = self._new_object(name, self._mesh_for(target.index, decoded, node, name, subdivided))
            self.report.add_imported("objects")
        elif kind == "ShapeData":
            obj, stack = self._build_shape(scene, node, name, target, decoded, stack or [])
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
            if stack:
                self._build_stack(obj, scene, node, stack)
            if self.settings.import_materials and node.material is not None:
                self._assign_materials(obj, scene, node.material, decoded)
        elif obj.type == 'CURVE':
            if self.settings.import_materials and node.material is not None:
                sub_ids, mats = self._blender_materials(scene, node.material)
                if mats and not obj.data.materials:
                    obj.data.materials.append(mats[0])
        obj["mx_node_index"] = node.index
        return obj

    # Modifier stacks.

    def _stack_entries(self, scene, node):
        """
        ``(base object, [(modifier object, ModifierRef or None, context data chunk or None)])`` for a node, the
        modifiers bottom of the stack first, through nested derived objects.
        """
        entries = []        # Top of the stack first, as stored.
        obj = node.object
        seen = set()
        while obj is not None and obj.index not in seen:
            seen.add(obj.index)
            value = scene.decode(obj)
            if _kind(value) != "ModifierStack":
                break
            contexts = obj.chunk.find_all(0x2500)
            if len(contexts) != len(value.modifiers):
                contexts = [None] * len(value.modifiers)
            for ref, chunk in zip(value.modifiers, contexts):
                data = chunk.find(0x2512) if chunk is not None and chunk.is_container else None
                entries.append((scene.objects[ref.object_index], ref, data))
            obj = scene.objects[value.base] if value.base is not None else None
        if obj is not None and _kind(scene.decode(obj)) == "ModifierStack":
            obj = None
        return obj, list(reversed(entries))

    def _mod_context(self, scene, mod_obj, decoded, ref, data, to_object):
        from .modifiers import convert as modifier_convert
        ctx = modifier_convert.ModContext(unit_scale=self.unit_scale, to_object=to_object, data=data)
        if ref is not None:
            ctx.context_tm = ref.context_tm
            ctx.bbox = ref.context_bbox
        gizmo_index = getattr(decoded, "gizmo", None)
        if gizmo_index is not None:
            gizmo = scene.decode(scene.objects[gizmo_index])
            if _kind(gizmo) == "Transform":
                ctx.gizmo = gizmo
        if modifier_convert.converter_key(mod_obj.class_label()) in {"Bend", "Twist", "Taper"}:
            center = scene.ref(mod_obj, 1)
            value = scene.decode(center) if center is not None else None
            if isinstance(value, tuple) and len(value) == 3:
                ctx.center = value
        ctx.display_name = getattr(decoded, "name", None)
        return ctx

    def _to_object(self, node):
        """Mesh coordinates to Max object space (scene units): the inverse of the baked offset and unit scale."""
        offset = _matrix(node.object_offset.matrix())
        return (self._scaled(offset) @ Matrix.Scale(self.unit_scale, 4)).inverted_safe()

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

    def _mesh_for(self, geometry_index, decoded, node, name, merge_triangles=False):
        offset = _matrix(node.object_offset.matrix())
        # Only big triangle meshes are built differently under a subdivision modifier (see _mesh_from_data).
        merge_triangles = merge_triangles and bool(getattr(decoded, "edge_visibility", None)) and \
            len(decoded.faces) > MERGE_TRIANGLES_UP_TO
        key = (geometry_index, tuple(round(v, 6) for row in offset for v in row), merge_triangles)
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
            mesh = self._mesh_from_data(decoded, name, merge_triangles)
        if not live:
            # Object offset: bake it into the geometry so the Blender origin sits at the Max pivot.
            mesh.transform(self._scaled(offset) @ Matrix.Scale(self.unit_scale, 4))
        self._mesh_cache[key] = mesh
        self.report.add_imported("meshes")
        return mesh

    def _mesh_from_data(self, data, name, merge_triangles=False):
        from . import mesh_build, polygons
        from .materials.nodes import uv_layer_name
        faces = data.faces
        groups = data.smoothing_groups if data.smoothing_groups else [1] * len(faces)
        mat_ids = data.material_ids if data.material_ids else None
        channels = [(channel, mapping.vertices, mapping.faces)
                    for channel, mapping in sorted(data.map_channels.items()) if channel >= 1]
        visibility = getattr(data, "edge_visibility", None)
        if visibility and (merge_triangles or len(faces) <= MERGE_TRIANGLES_UP_TO):
            # Editable Mesh: Max's polygons back from the triangles (subdivision modifiers work on them).
            usable = [c for c in channels if len(c[2]) == len(faces)]
            merged = polygons.merge_triangles(faces, visibility, [c[2] for c in usable])
            if merged is not None:
                faces, sources, channel_faces = merged
                groups = [groups[i] for i in sources]
                mat_ids = [mat_ids[i] for i in sources] if mat_ids else None
                channels = [(c[0], c[1], f) for c, f in zip(usable, channel_faces)]
                self.report.add_imported("triangle meshes shown as polygons")
        sizes = None
        uv_layers = []
        for channel, vertices, channel_faces in channels:
            if sizes is None:
                sizes = mesh_build._face_arrays(faces)[0]
            uvs = mesh_build.corner_uvs(vertices, channel_faces, sizes)
            if uvs is None:
                self.note(name, "map channel {:d} doesn't match the geometry, skipped".format(channel))
                continue
            uv_layers.append((uv_layer_name(channel), uvs))
        return mesh_build.build_mesh(
            name, data.positions, faces, uv_layers=uv_layers, smoothing_groups=groups, material_ids=mat_ids)

    def _primitive_mesh(self, data, name, live=True):
        """
        ``(mesh, is_live)`` for a primitive: a live primitive (sizes in metres) when the Max-Style Primitives
        add-on is enabled and ``live`` allows it, else a plain mesh in scene units (the caller scales it).
        """
        from . import mesh_build
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
        decoded_params = dict(data.params)
        if not decoded_params:
            # Kinds maxfile doesn't map onto the builder (Teapot) keep their values in extra_params.
            decoded_params = dict(getattr(data, "extra_params", None) or {})
        kind, params, notes = primitive_convert.builder_params(
            data.kind, decoded_params, geometry.PARAMETERS, self.unit_scale if live else 1.0)
        for note in notes:
            self.note(name, note)
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
                attribute = mesh.attributes.get(mesh_build.MATERIAL_ID_ATTRIBUTE) or mesh.attributes.new(
                    mesh_build.MATERIAL_ID_ATTRIBUTE, 'INT', 'FACE')
                attribute.data.foreach_set("value", array.array("i", (i + 1 for i in ids)))
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
        from . import mesh_build
        from .materials.nodes import uv_layer_name
        uv_layers = []
        if data.uvs is not None:
            uv_layers.append((uv_layer_name(1), [tuple(uv) for face in data.uvs for uv in face]))
        return mesh_build.build_mesh(name, data.vertices, data.faces, uv_layers=uv_layers,
                                     smoothing_groups=data.smoothing_groups,
                                     material_ids=[i + 1 for i in data.material_ids])

    def _build_stack(self, obj, scene, node, entries):
        """Add Max modifiers (``_stack_entries``, bottom of the stack first) as Blender modifiers."""
        from .modifiers import convert as modifier_convert
        to_object = self._to_object(node)
        uv_keys = tuple(m.index for m, _r, _d in entries
                        if modifier_convert.converter_key(m.class_label()) in {"UVW_Map", "Unwrap_UVW"})
        if uv_keys:
            # The modifiers write UVs into the mesh: instances with the same UV modifiers share one copy.
            key = (obj.data.name, uv_keys)
            shared = self._uv_meshes.get(key)
            if shared is not None:
                obj.data = shared
            else:
                obj.data = obj.data.copy()
                self._uv_meshes[key] = obj.data
        uv_done = bool(uv_keys) and list(obj.data.get("mx_uv_from", [])) == list(uv_keys)
        for mod_obj, ref, data in entries:
            class_name = mod_obj.class_label()
            decoded = scene.decode(mod_obj)
            params = dict(getattr(decoded, "params", None) or {})
            key = modifier_convert.converter_key(class_name)
            if uv_done and key in {"UVW_Map", "Unwrap_UVW"}:
                self.report.add_imported("modifiers")
                continue
            ctx = self._mod_context(scene, mod_obj, decoded, ref, data, to_object)
            result = modifier_convert.add_modifier(obj, class_name, params, enabled=getattr(decoded, "enabled", None),
                                                   ctx=ctx)
            for text in ctx.notes:
                self.note(obj.name, "{:s}: {:s}".format(class_name, text))
            if result == modifier_convert.SKIPPED:
                self.report.add_imported("modifiers left out")
            elif result:
                self.report.add_imported("modifiers")
            else:
                self.report.add_unsupported("modifier", class_name)
                break   # Import the stack up to the unsupported modifier (ROADMAP Phase 2d).
        if uv_keys:
            obj.data["mx_uv_from"] = list(uv_keys)
        if not self.settings.keep_modifier_stack:
            modifier_convert.collapse(obj)

    # Shapes.

    def _build_shape(self, scene, node, name, target, shape, entries):
        """
        A shape node: a curve, or a mesh when an Extrude / Lathe at the bottom of its stack turns it into one.
        Returns ``(object, remaining stack entries)``.
        """
        from . import shapes
        from .modifiers import convert as modifier_convert
        splines = shape.splines
        index = 0
        edited = []
        while index < len(entries) and modifier_convert.converter_key(entries[index][0].class_label()) == "Edit_Spline":
            mod_obj, _ref, data = entries[index]
            stored = self._edit_spline_result(data)
            if stored is None:
                self.note(name, "Edit Spline result not readable: the shape below it is used")
            else:
                splines = stored
            edited.append(mod_obj.index)
            self.report.add_imported("modifiers")
            index += 1
        offset = _matrix(node.object_offset.matrix())
        key = (target.index, tuple(edited), tuple(round(v, 6) for row in offset for v in row))
        steps = shape.steps if shape.steps is not None else 6
        if index < len(entries):
            mod_obj, ref, data = entries[index]
            gen = modifier_convert.converter_key(mod_obj.class_label())
            if gen in {"Extrude", "Lathe"}:
                mesh_key = key + (mod_obj.index,)
                mesh = self._mesh_cache.get(mesh_key)
                if mesh is not None:
                    self.report.add_imported("instances")
                    obj = self._new_object(name, mesh)
                else:
                    raw = self._raw_params(scene, mod_obj,
                                           shapes.EXTRUDE_SLOT if gen == "Extrude" else shapes.LATHE_SLOT)
                    if gen == "Extrude":
                        obj = self._extrude(name, splines, raw, steps, node)
                    else:
                        obj = self._lathe(name, splines, raw, steps, node, scene, mod_obj, ref, data)
                    self._mesh_cache[mesh_key] = obj.data
                    self.report.add_imported("meshes")
                self.report.add_imported("objects")
                self.report.add_imported("modifiers")
                return obj, entries[index + 1:]
        curve = self._curve_cache.get(key)
        if curve is None:
            curve = self._curve(name, shape, splines, steps)
            curve.transform(self._scaled(offset) @ Matrix.Scale(self.unit_scale, 4))
            self._curve_cache[key] = curve
            self.report.add_imported("shapes")
        else:
            self.report.add_imported("instances")
        obj = self._new_object(name, curve)
        for mod_obj, _ref, _data in entries[index:]:
            label = mod_obj.class_label()
            if modifier_convert.converter_key(label) in {"UVW_Map", "Attribute_Holder"}:
                continue    # No effect on a curve.
            self.report.add_unsupported("modifier", label)
            break
        return obj, []

    def _raw_params(self, scene, mod_obj, slot):
        ref = scene.ref(mod_obj, slot)
        block = scene.param_block(ref) if ref is not None else None
        if block is None:
            return {}
        return {pid: param.value for pid, param in block.params.items()}

    @staticmethod
    def _edit_spline_result(data):
        """The splines an Edit Spline stores for its node (``0x2512`` > ``0x1000`` > ``0x1040`` Bezier shape)."""
        if data is None:
            return None
        try:
            from maxfile.objects.shapes import read_bezier_shape
            from maxfile.errors import MaxFileError
        except ImportError:
            return None
        holder = data.find(0x1000)
        bezier = holder.find(0x1040) if holder is not None and holder.is_container else None
        if bezier is None or not bezier.is_container:
            return None
        try:
            splines = read_bezier_shape(bezier)
        except MaxFileError:
            return None
        return splines or None

    def _curve(self, name, shape, splines, steps):
        """A Bezier curve datablock (scene units) from shape splines."""
        from . import shapes
        curve = bpy.data.curves.new(name, 'CURVE')
        curve.dimensions = '3D'
        curve.resolution_u = max(1, min(64, steps + 1))
        curve.render_resolution_u = curve.resolution_u
        for spline in splines:
            knots = spline.knots
            if not knots:
                continue
            sp = curve.splines.new('BEZIER')
            sp.bezier_points.add(len(knots) - 1)
            sp.use_cyclic_u = spline.closed
            for point, knot in zip(sp.bezier_points, knots):
                point.handle_left_type = point.handle_right_type = 'FREE'
                point.co = knot.position
                point.handle_left = knot.in_handle
                point.handle_right = knot.out_handle
                if knot.knot_type in shapes.SMOOTH_KNOTS:
                    point.handle_left_type = point.handle_right_type = 'ALIGNED'
        rendering = shape.rendering
        if rendering is not None and (rendering.renderable or rendering.display_render_mesh):
            thickness = rendering.thickness
            sides = rendering.sides
            if rendering.use_viewport_settings and rendering.display_render_mesh and not rendering.renderable:
                thickness, sides = rendering.viewport_thickness, rendering.viewport_sides
            if rendering.rectangular:
                thickness = max(rendering.rectangular_length, rendering.rectangular_width)
                self.note(name, "rectangular spline rendering imported as a round bevel")
            curve.bevel_mode = 'ROUND'
            curve.bevel_depth = thickness / 2.0      # Scene units: the curve is scaled with its points.
            curve.bevel_resolution = max(0, int(round(sides / 4.0)) - 1)
            curve.use_fill_caps = True
            if not rendering.renderable:
                self.note(name, "spline shown with thickness in the viewport only: rendered too")
        curve["mx_shape_kind"] = shape.kind
        return curve

    def _extrude(self, name, splines, raw, steps, node):
        from mathutils.geometry import tessellate_polygon
        from . import mesh_build, shapes
        p = {key: raw[pid] for pid, key in shapes.EXTRUDE_PARAMS.items() if pid in raw}
        positions, faces, mat_ids, groups, sharp = shapes.extrude_mesh(
            splines, float(p.get("amount", 0.0)), int(p.get("segments", 1) or 1),
            bool(p.get("cap_start", 1)), bool(p.get("cap_end", 1)), steps, tessellate=tessellate_polygon)
        mesh = mesh_build.build_mesh(
            name, positions, faces, sharp_edges=sharp, smoothing_groups=groups,
            material_ids=mat_ids if p.get("generate_material_ids", 1) else [1] * len(faces))
        offset = _matrix(node.object_offset.matrix())
        mesh.transform(self._scaled(offset) @ Matrix.Scale(self.unit_scale, 4))
        return self._new_object(name, mesh)

    def _lathe(self, name, splines, raw, steps, node, scene, mod_obj, ref, data):
        from . import mesh_build, shapes
        from .modifiers import convert as modifier_convert
        p = {key: raw[pid] for pid, key in shapes.LATHE_PARAMS.items() if pid in raw}
        positions, edges = [], []
        for spline in splines:
            pts, _owners = shapes.polyline(spline, steps)
            base = len(positions)
            positions.extend(pts)
            n = len(pts)
            count = n if spline.closed and n > 2 else n - 1
            edges.extend((base + i, base + (i + 1) % n) for i in range(count))
        mesh = mesh_build.build_mesh(name, positions, [], edges=edges)
        offset = _matrix(node.object_offset.matrix())
        mesh.transform(self._scaled(offset) @ Matrix.Scale(self.unit_scale, 4))
        obj = self._new_object(name, mesh)
        mod = obj.modifiers.new("Lathe", 'SCREW')
        mod.angle = math.radians(p.get("degrees", 360.0))
        segments = int(p.get("segments", 16) or 16)
        mod.steps = mod.render_steps = max(segments, 2)
        mod.screw_offset = 0.0
        mod.use_merge_vertices = bool(p.get("weld_core", 0))
        mod.merge_threshold = 0.001 * self.unit_scale
        mod.use_normal_calculate = True
        mod.use_smooth_shade = True
        mod.axis = 'Z'
        decoded = scene.decode(mod_obj)
        gizmo_ref = scene.ref(mod_obj, shapes.LATHE_GIZMO_SLOT)
        ctx = modifier_convert.ModContext(unit_scale=self.unit_scale, to_object=self._to_object(node))
        if ref is not None:
            ctx.context_tm = ref.context_tm
        gizmo = scene.decode(gizmo_ref) if gizmo_ref is not None else None
        if _kind(gizmo) == "Transform":
            ctx.gizmo = gizmo
        axis = modifier_convert._gizmo_empty(obj, "Lathe", ctx)
        if axis is not None:
            mod.object = axis
        if p.get("degrees", 360.0) < 360.0 and (p.get("cap_start") or p.get("cap_end")):
            self.note(name, "Lathe caps of a partial revolution are not generated")
        del decoded
        return obj

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
                    built.append(self._built_material(sub) if sub is not None else None)
                # maxfile gives the IDs 1-based (stored 0-based, see MaterialData.sub_ids).
                result = (list(decoded.sub_ids) if decoded.sub_ids else list(range(1, len(built) + 1)), built)
            else:
                result = (None, [self._built_material(decoded)])
        else:
            # Not decoded: a placeholder named after the class (it is reported by the builder).
            label = material_object.class_label()
            result = (None, [self.materials.build(material_convert.convert(label, {"name": label}))])
        self._material_cache[material_object.index] = result
        return result

    def _built_material(self, data):
        """A Blender material for a decoded material, shared by every slot that uses the same Max material."""
        key = getattr(data, "index", None)
        if key is not None and key in self._built_materials:
            return self._built_materials[key]
        desc = self._material_desc(data, depth=0)
        mat = self.materials.build(desc)
        if _kind(desc) != "Placeholder":     # Placeholders are reported as unsupported by the builder.
            self.report.add_imported("materials")
        if key is not None:
            self._built_materials[key] = mat
        return mat

    def _material_desc(self, data, depth):
        """A material model description (Surface, Blend or Placeholder) for decoded material data."""
        from .materials import convert as material_convert, model
        name = data.name or data.class_name
        if depth > 8:
            return model.Placeholder(name=name, source_class=data.class_name)
        components = getattr(data, "components", None)
        if data.sub_materials is not None:
            # A Multi/Sub-Object inside another material: Blender has one material per slot.
            first = next((m for m in data.sub_materials if m is not None), None)
            self.note(name, "nested Multi/Sub-Object material: its first sub-material is used")
            return self._material_desc(first, depth + 1) if first is not None else model.Placeholder(
                name=name, source_class=data.class_name)
        if data.class_name == "Blend" and components:
            a, b = (self._material_desc(c, depth + 1) if c is not None else None for c in (components + [None])[:2])
            params = data.params or {}
            amount = params.get("mix_amount", 0.0)
            amount = amount / 100.0 if amount > 1.0 else amount
            mask = (data.maps or {}).get("mask_map")
            if mask is not None and params.get("mask_enabled", True) is not False:
                converted = self._convert_map(mask)
                if converted is not None:
                    amount = converted
            return model.Blend(name=name, a=a, b=b, amount=amount, source_class="Blend")
        if components and data.class_name not in material_convert.CONVERTERS:
            first = next((c for c in components if c is not None), None)
            if first is not None:
                labels = list((data.params or {}).get("components") or [])
                self.note(name, "{:s} material imported as its {:s} material".format(
                    data.class_name, labels[0] if labels else "first"))
                desc = self._material_desc(first, depth + 1)
                if hasattr(desc, "name"):
                    desc.name = name
                return desc
        params = dict(data.params or {})
        params.setdefault("name", name)
        for key, tex in (data.maps or {}).items():
            converted = self._convert_map(tex)
            if converted is not None:
                params[key] = converted
        return material_convert.convert(data.class_name, params)

    def _convert_map(self, tex):
        """``maxfile`` MapData to a material model map (see ``materials/maps.py``)."""
        return self.maps.convert(tex)

    def _map_params(self, tex, slot):
        """Raw parameter block values (param ID -> value) in reference ``slot`` of a map object."""
        index = getattr(tex, "index", None)
        if index is None or self._scene is None or not 0 <= index < len(self._scene.objects):
            return None
        obj = self._scene.objects[index]
        ref = obj.references.get(slot)
        block = self._scene.param_block(self._scene.objects[ref]) if ref is not None else None
        if block is None:
            return None
        return {pid: param.value for pid, param in block.params.items()}

    def _assign_materials(self, obj, scene, material_object, decoded):
        import numpy as np
        from . import material_ids, mesh_build
        sub_ids, mats = self._blender_materials(scene, material_object)
        mesh = obj.data
        face_ids = mesh_build.face_material_ids(mesh)
        if face_ids is None:
            face_ids = np.ones(len(mesh.polygons), dtype=np.int32)
        # Slots per distinct ID (vectorised over the faces).
        unique, inverse = np.unique(face_ids, return_inverse=True)
        slot_of_sub, unique_slots = material_ids.slots_for_faces(unique.tolist(), sub_ids)
        face_slots = np.asarray(unique_slots, dtype=np.int32)[inverse] if len(unique) else face_ids
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
            mesh.polygons.foreach_set("material_index", np.ascontiguousarray(face_slots, dtype=np.int32))


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

    view_layer_objects = set(context.view_layer.objects)    # Name lookups in the collection are linear.
    for obj in view_layer_objects:
        if obj.select_get():
            obj.select_set(False)
    for obj in objects:
        if obj in view_layer_objects and not obj.hide_get():
            obj.select_set(True)
    if objects and objects[0] in view_layer_objects:
        context.view_layer.objects.active = objects[0]

    store_in_text(report)
    operator.report({'WARNING'} if not report.is_clean else {'INFO'}, report.summary())
    return {'FINISHED'}
