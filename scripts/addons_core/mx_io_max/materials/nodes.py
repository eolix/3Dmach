# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Build Blender materials (Principled BSDF node trees) from :mod:`model` descriptions.

The trees are laid out left to right (maps, then the BSDF, then the output) so they stay readable in the
Shader Editor, and frames are avoided so users can rework them freely.
"""

__all__ = (
    "MaterialBuilder",
    "uv_layer_name",
)

import bpy

from . import model

# Horizontal spacing between node columns.
COLUMN = 300.0
ROW = 280.0


def uv_layer_name(channel):
    """Blender UV layer name for a Max map channel (1 = the first UV set). Shared with the mesh import."""
    return "UVMap" if channel <= 1 else "UVChannel_{:d}".format(channel)


class MaterialBuilder:
    """Builds materials for one import, sharing images and reporting missing textures."""

    def __init__(self, resolver=None, report=None, unit_scale=1.0):
        self.resolver = resolver
        self.report = report
        self.unit_scale = unit_scale        # Metres per scene unit, for maps sized in scene units (Noise).
        self._images = {}

    # Public API.

    def build(self, desc):
        """Create a ``bpy.types.Material`` for a Surface, Blend or Placeholder."""
        if isinstance(desc, model.Surface):
            return self._build_surface(desc)
        if isinstance(desc, model.Blend):
            return self._build_blend(desc)
        if isinstance(desc, model.Placeholder):
            return self._build_placeholder(desc)
        raise TypeError("cannot build a material from {!r}".format(type(desc).__name__))

    # Materials.

    def _new_material(self, name):
        mat = bpy.data.materials.new(name)
        if mat.node_tree is None:
            # Before Blender 5.0 new materials had no node tree (`use_nodes` is deprecated since).
            mat.use_nodes = True
        tree = mat.node_tree
        for node in list(tree.nodes):
            tree.nodes.remove(node)
        out = tree.nodes.new("ShaderNodeOutputMaterial")
        out.location = (COLUMN, 0.0)
        return mat, tree, out

    def _build_placeholder(self, desc):
        mat, tree, out = self._new_material(desc.name)
        bsdf = tree.nodes.new("ShaderNodeBsdfPrincipled")
        bsdf.label = "Placeholder for " + desc.source_class
        color = desc.diffuse or (0.8, 0.0, 0.8)    # Magenta when even the colour is unknown.
        bsdf.inputs["Base Color"].default_value = (*color[:3], 1.0)
        tree.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
        mat.diffuse_color = (*color[:3], 1.0)
        mat["mx_source_class"] = desc.source_class
        mat["mx_placeholder"] = True
        if self.report is not None:
            self.report.add_unsupported("material", desc.source_class)
        return mat

    def _build_surface(self, desc):
        mat, tree, out = self._new_material(desc.name)
        bsdf = self._surface_bsdf(tree, desc, (0.0, 0.0))
        tree.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
        self._finish(mat, desc)
        return mat

    def _build_blend(self, desc):
        mat, tree, out = self._new_material(desc.name)
        shaders = []
        for index, sub in enumerate((desc.a, desc.b)):
            location = (-COLUMN, ROW * 2.0 * (0.5 - index))
            if isinstance(sub, model.Surface):
                shaders.append(self._surface_bsdf(tree, sub, location).outputs["BSDF"])
            elif sub is None:
                node = tree.nodes.new("ShaderNodeBsdfTransparent" if index else "ShaderNodeBsdfDiffuse")
                node.location = location
                shaders.append(node.outputs[0])
            else:
                # Nested blends are flattened to their first surface, and reported.
                if self.report is not None:
                    self.report.warn("Nested blend material in {!r} simplified".format(desc.name))
                first = sub.a if isinstance(sub.a, model.Surface) else model.Surface()
                shaders.append(self._surface_bsdf(tree, first, location).outputs["BSDF"])
        mix = tree.nodes.new("ShaderNodeMixShader")
        mix.location = (0.0, 0.0)
        self._connect_scalar(tree, desc.amount, mix.inputs["Fac"], (-COLUMN * 2.0, -ROW * 2.0))
        tree.links.new(shaders[0], mix.inputs[1])
        tree.links.new(shaders[1], mix.inputs[2])
        tree.links.new(mix.outputs["Shader"], out.inputs["Surface"])
        mat["mx_source_class"] = desc.source_class or "Blend"
        return mat

    def _finish(self, mat, desc):
        if desc.viewport_color:
            mat.diffuse_color = (*desc.viewport_color[:3], 1.0)
        if isinstance(desc.metallic.value, (int, float)):
            mat.metallic = desc.metallic.value
        if isinstance(desc.roughness.value, (int, float)):
            mat.roughness = desc.roughness.value
        uses_alpha = desc.alpha.has_map or (isinstance(desc.alpha.value, (int, float)) and desc.alpha.value < 1.0)
        if uses_alpha:
            mat.surface_render_method = 'DITHERED'
        mat.use_backface_culling = not desc.double_sided
        mat["mx_source_class"] = desc.source_class

    def _surface_bsdf(self, tree, desc, location):
        x, y = location
        bsdf = tree.nodes.new("ShaderNodeBsdfPrincipled")
        bsdf.location = (x, y)
        bsdf.label = desc.source_class or ""
        inputs = bsdf.inputs
        self._connect_input(tree, desc.base_color, inputs["Base Color"], (x - COLUMN, y), color=True)
        self._connect_input(tree, desc.metallic, inputs["Metallic"], (x - COLUMN, y - ROW * 0.5))
        self._connect_input(tree, desc.roughness, inputs["Roughness"], (x - COLUMN, y - ROW))
        self._connect_input(tree, desc.transmission, inputs["Transmission Weight"], (x - COLUMN, y - ROW * 1.5))
        self._connect_input(tree, desc.alpha, inputs["Alpha"], (x - COLUMN, y - ROW * 2.0))
        self._connect_input(tree, desc.emission_color, inputs["Emission Color"], (x - COLUMN, y - ROW * 2.5),
                            color=True)
        inputs["IOR"].default_value = desc.ior
        inputs["Specular IOR Level"].default_value = desc.specular_ior_level
        inputs["Specular Tint"].default_value = (*desc.specular_tint[:3], 1.0)
        inputs["Emission Strength"].default_value = desc.emission_strength
        inputs["Coat Weight"].default_value = desc.coat_weight
        inputs["Coat Roughness"].default_value = desc.coat_roughness
        inputs["Coat IOR"].default_value = desc.coat_ior
        inputs["Sheen Weight"].default_value = desc.sheen_weight
        inputs["Sheen Tint"].default_value = (*desc.sheen_tint[:3], 1.0)
        inputs["Subsurface Weight"].default_value = desc.subsurface_weight
        inputs["Subsurface Radius"].default_value = desc.subsurface_radius
        inputs["Anisotropic"].default_value = desc.anisotropic
        if desc.transmission_color and not desc.base_color.has_map and \
                isinstance(desc.transmission.value, (int, float)) and desc.transmission.value > 0.0:
            # Principled tints transmission with the base colour.
            inputs["Base Color"].default_value = (*desc.transmission_color[:3], 1.0)
        if desc.normal is not None:
            normal = self._normal_socket(tree, desc.normal, (x - COLUMN * 2.0, y - ROW * 3.0))
            if normal is not None:
                tree.links.new(normal, inputs["Normal"])
        return bsdf

    # Inputs and maps.

    def _connect_input(self, tree, inp, socket, location, color=False):
        value = inp.value
        if color:
            if isinstance(value, (tuple, list)):
                socket.default_value = (*tuple(value)[:3], 1.0)
        elif isinstance(value, (int, float)):
            socket.default_value = value
        elif isinstance(value, (tuple, list)):
            socket.default_value = model.luminance(value)
        if not inp.has_map:
            return
        out = self._map_socket(tree, inp.map, location, color=color)
        if out is None:
            return
        if inp.map_amount < 1.0:
            mix = tree.nodes.new("ShaderNodeMix")
            mix.data_type = 'RGBA' if color else 'FLOAT'
            mix.location = (location[0] + COLUMN * 0.5, location[1])
            mix.inputs["Factor"].default_value = inp.map_amount
            a, b = (mix.inputs[6], mix.inputs[7]) if color else (mix.inputs[2], mix.inputs[3])
            a.default_value = socket.default_value
            tree.links.new(out, b)
            out = mix.outputs[2] if color else mix.outputs[0]
        tree.links.new(out, socket)

    def _connect_scalar(self, tree, value, socket, location):
        if isinstance(value, model.TextureMap):
            out = self._map_socket(tree, value, location, color=False)
            if out is not None:
                tree.links.new(out, socket)
        else:
            socket.default_value = float(value)

    def _value_or_map(self, tree, value, socket, location, color=True):
        """Set ``socket`` from a colour/float constant, or link a map into it."""
        if isinstance(value, model.TextureMap):
            out = self._map_socket(tree, value, location, color=color)
            if out is not None:
                tree.links.new(out, socket)
        elif value is not None:
            if isinstance(value, (tuple, list)):
                socket.default_value = (*tuple(value)[:3], 1.0) if len(socket.default_value) == 4 else \
                    model.luminance(value)
            else:
                socket.default_value = value

    def _uv(self, tree, channel, tiling, offset, rotation, location):
        uvmap = tree.nodes.new("ShaderNodeUVMap")
        uvmap.location = (location[0] - COLUMN, location[1])
        uvmap.uv_map = uv_layer_name(channel)
        if tiling == (1.0, 1.0) and offset == (0.0, 0.0) and rotation == 0.0:
            return uvmap.outputs["UV"]
        from .maps import rotate_uv_center
        mapping = tree.nodes.new("ShaderNodeMapping")
        mapping.location = (location[0] - COLUMN * 0.5, location[1])
        # Max tiles and rotates around the map centre; Blender's mapping node works around the origin.
        (lx, ly), rz = rotate_uv_center(tiling, offset, rotation)
        mapping.inputs["Location"].default_value = (lx, ly, 0.0)
        mapping.inputs["Rotation"].default_value = (0.0, 0.0, rz)
        mapping.inputs["Scale"].default_value = (tiling[0], tiling[1], 1.0)
        tree.links.new(uvmap.outputs["UV"], mapping.inputs["Vector"])
        return mapping.outputs["Vector"]

    def _image(self, path, srgb, resolved_path=None):
        """Load each (file, colour space) once per import; never reuse or alter images already in the file."""
        key = (path, srgb)
        if key in self._images:
            return self._images[key]
        image = None
        local = self.resolver.resolve(path) if self.resolver else (path if path else None)
        if local is None and resolved_path and resolved_path != path:
            local = self.resolver.resolve(resolved_path) if self.resolver else resolved_path
            if local is not None and self.resolver is not None and path in self.resolver.missing:
                self.resolver.missing.remove(path)
        if local:
            try:
                image = bpy.data.images.load(local, check_existing=False)
            except RuntimeError:
                image = None
        if image is not None:
            image.colorspace_settings.is_data = not srgb
        elif self.report is not None:
            self.report.add_missing_texture(path)
        self._images[key] = image
        return image

    def _map_socket(self, tree, tex, location, color=True):
        """Create nodes for a texture map; returns the output socket (colour or float), or None."""
        x, y = location
        if isinstance(tex, model.Bitmap):
            srgb = tex.srgb if tex.srgb is not None else color
            image = self._image(tex.path or tex.resolved_path, srgb, tex.resolved_path)
            node = tree.nodes.new("ShaderNodeTexImage")
            node.location = (x - COLUMN * 0.5, y)
            node.label = tex.name or (tex.path.replace("\\", "/").rsplit("/", 1)[-1] if tex.path else "")
            if image is not None:
                node.image = image
            tree.links.new(self._uv(tree, tex.uv_channel, tuple(tex.tiling), tuple(tex.offset), tex.rotation,
                                    (x - COLUMN, y)), node.inputs["Vector"])
            out = node.outputs["Alpha"] if tex.use_alpha else node.outputs["Color"]
            if tex.invert:
                inv = tree.nodes.new("ShaderNodeInvert")
                inv.location = (x, y)
                tree.links.new(out, inv.inputs["Color"])
                out = inv.outputs["Color"]
            return out
        if isinstance(tex, model.Checker):
            node = tree.nodes.new("ShaderNodeTexChecker")
            node.location = (x - COLUMN * 0.5, y)
            node.inputs["Scale"].default_value = 2.0      # Max's checker has 2x2 squares per tile.
            self._value_or_map(tree, tex.map1 or tex.color1, node.inputs["Color1"], (x - COLUMN, y))
            self._value_or_map(tree, tex.map2 or tex.color2, node.inputs["Color2"], (x - COLUMN, y - ROW))
            tree.links.new(self._uv(tree, tex.uv_channel, tuple(tex.tiling), (0.0, 0.0), 0.0, (x - COLUMN, y)),
                           node.inputs["Vector"])
            return node.outputs["Color"]
        if isinstance(tex, model.Noise):
            coords = tree.nodes.new("ShaderNodeTexCoord")
            coords.location = (x - COLUMN * 1.6, y)
            node = tree.nodes.new("ShaderNodeTexNoise")
            node.location = (x - COLUMN, y)
            # Max noise works in object space with a feature size in scene units; Blender's scale is features
            # per metre of the object coordinates.
            tree.links.new(coords.outputs["Object"], node.inputs["Vector"])
            node.inputs["Scale"].default_value = 1.0 / max(tex.size * self.unit_scale, 1e-6)
            node.inputs["Detail"].default_value = tex.levels if tex.kind != "REGULAR" else 0.0
            ramp = tree.nodes.new("ShaderNodeMix")
            ramp.data_type = 'RGBA'
            ramp.location = (x - COLUMN * 0.4, y)
            ramp.inputs[6].default_value = (*tex.color1[:3], 1.0)
            ramp.inputs[7].default_value = (*tex.color2[:3], 1.0)
            if tex.map1 is not None:
                self._value_or_map(tree, tex.map1, ramp.inputs[6], (x - COLUMN * 1.5, y))
            if tex.map2 is not None:
                self._value_or_map(tree, tex.map2, ramp.inputs[7], (x - COLUMN * 1.5, y - ROW))
            tree.links.new(node.outputs["Fac"], ramp.inputs["Factor"])
            return ramp.outputs[2]
        if isinstance(tex, model.Gradient):
            uv = self._uv(tree, tex.uv_channel, (1.0, 1.0), (0.0, 0.0), 0.0, (x - COLUMN, y))
            grad = tree.nodes.new("ShaderNodeTexGradient")
            grad.location = (x - COLUMN * 0.7, y)
            grad.gradient_type = 'LINEAR' if tex.kind == "LINEAR" else 'SPHERICAL'
            tree.links.new(uv, grad.inputs["Vector"])
            ramp = tree.nodes.new("ShaderNodeValToRGB")
            ramp.location = (x - COLUMN * 0.4, y)
            elements = ramp.color_ramp.elements
            elements[0].color = (*tex.colors[2][:3], 1.0)    # Max's gradient runs colour 3 (bottom) to 1 (top).
            elements[1].color = (*tex.colors[0][:3], 1.0)
            mid = elements.new(tex.position2)
            mid.color = (*tex.colors[1][:3], 1.0)
            tree.links.new(grad.outputs["Fac"], ramp.inputs["Fac"])
            return ramp.outputs["Color"]
        if isinstance(tex, model.Mix):
            node = tree.nodes.new("ShaderNodeMix")
            node.data_type = 'RGBA'
            node.location = (x, y)
            self._value_or_map(tree, tex.a, node.inputs[6], (x - COLUMN, y))
            self._value_or_map(tree, tex.b, node.inputs[7], (x - COLUMN, y - ROW))
            self._connect_scalar(tree, tex.amount, node.inputs["Factor"], (x - COLUMN, y - ROW * 2.0))
            return node.outputs[2]
        if isinstance(tex, model.Falloff):
            weight = tree.nodes.new("ShaderNodeLayerWeight")
            weight.location = (x - COLUMN, y)
            weight.inputs["Blend"].default_value = 0.5
            mix = tree.nodes.new("ShaderNodeMix")
            mix.data_type = 'RGBA'
            mix.location = (x, y)
            if tex.kind == "FRESNEL":
                fresnel = tree.nodes.new("ShaderNodeFresnel")
                fresnel.location = (x - COLUMN, y - ROW * 0.5)
                fresnel.inputs["IOR"].default_value = tex.ior
                tree.links.new(fresnel.outputs["Fac"], mix.inputs["Factor"])
                tree.nodes.remove(weight)
            else:
                tree.links.new(weight.outputs["Facing"], mix.inputs["Factor"])
            self._value_or_map(tree, tex.near, mix.inputs[6], (x - COLUMN * 1.5, y))
            self._value_or_map(tree, tex.far, mix.inputs[7], (x - COLUMN * 1.5, y - ROW))
            if tex.kind not in {"PERPENDICULAR_PARALLEL", "TOWARDS_AWAY", "FRESNEL"} and self.report is not None:
                self.report.warn("Falloff type {:s} approximated as Perpendicular/Parallel".format(tex.kind))
            return mix.outputs[2]
        if isinstance(tex, model.ColorCorrection):
            hsv = tree.nodes.new("ShaderNodeHueSaturation")
            hsv.location = (x - COLUMN * 0.6, y)
            hsv.inputs["Hue"].default_value = 0.5 + tex.hue / 360.0
            hsv.inputs["Saturation"].default_value = 1.0 + tex.saturation / 100.0
            self._value_or_map(tree, tex.input, hsv.inputs["Color"], (x - COLUMN, y))
            bc = tree.nodes.new("ShaderNodeBrightContrast")
            bc.location = (x - COLUMN * 0.3, y)
            bc.inputs["Bright"].default_value = tex.brightness / 100.0
            bc.inputs["Contrast"].default_value = tex.contrast / 100.0
            tree.links.new(hsv.outputs["Color"], bc.inputs["Color"])
            out = bc.outputs["Color"]
            if tex.gamma != 1.0:
                gamma = tree.nodes.new("ShaderNodeGamma")
                gamma.location = (x, y)
                gamma.inputs["Gamma"].default_value = tex.gamma
                tree.links.new(out, gamma.inputs["Color"])
                out = gamma.outputs["Color"]
            return out
        if isinstance(tex, (model.NormalMap, model.Bump)):
            # As a colour input this makes no sense; the normal path handles these.
            return None
        if self.report is not None:
            self.report.add_unsupported("map", type(tex).__name__)
        return None

    def _normal_socket(self, tree, tex, location):
        x, y = location
        if isinstance(tex, model.NormalMap):
            out = None
            if tex.input is not None:
                if isinstance(tex.input, model.Bitmap):
                    tex.input.srgb = False
                color = self._map_socket(tree, tex.input, (x - COLUMN, y), color=False)
                if color is not None:
                    if tex.flip_green:
                        sep = tree.nodes.new("ShaderNodeSeparateColor")
                        sep.location = (x - COLUMN * 0.6, y)
                        comb = tree.nodes.new("ShaderNodeCombineColor")
                        comb.location = (x - COLUMN * 0.3, y)
                        inv = tree.nodes.new("ShaderNodeMath")
                        inv.operation = 'SUBTRACT'
                        inv.inputs[0].default_value = 1.0
                        inv.location = (x - COLUMN * 0.45, y - ROW * 0.4)
                        tree.links.new(color, sep.inputs["Color"])
                        tree.links.new(sep.outputs["Red"], comb.inputs["Red"])
                        tree.links.new(sep.outputs["Green"], inv.inputs[1])
                        tree.links.new(inv.outputs["Value"], comb.inputs["Green"])
                        tree.links.new(sep.outputs["Blue"], comb.inputs["Blue"])
                        color = comb.outputs["Color"]
                    nmap = tree.nodes.new("ShaderNodeNormalMap")
                    nmap.location = (x, y)
                    nmap.inputs["Strength"].default_value = tex.strength
                    tree.links.new(color, nmap.inputs["Color"])
                    out = nmap.outputs["Normal"]
            if tex.bump is not None:
                out = self._bump(tree, tex.bump, tex.bump_strength, out, (x + COLUMN * 0.5, y - ROW))
            return out
        if isinstance(tex, model.Bump):
            return self._bump(tree, tex.input, tex.strength, None, (x, y))
        return None

    def _bump(self, tree, tex, strength, normal, location):
        if tex is None:
            return normal
        height = self._map_socket(tree, tex, (location[0] - COLUMN, location[1]), color=False)
        if height is None:
            return normal
        bump = tree.nodes.new("ShaderNodeBump")
        bump.location = location
        bump.inputs["Strength"].default_value = min(max(strength, 0.0), 1.0)
        bump.inputs["Distance"].default_value = 0.01 * max(strength, 1.0)
        tree.links.new(height, bump.inputs["Height"])
        if normal is not None:
            tree.links.new(normal, bump.inputs["Normal"])
        return bump.outputs["Normal"]
