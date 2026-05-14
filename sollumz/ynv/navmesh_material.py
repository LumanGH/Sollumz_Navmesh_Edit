"""Single shader-node material that colors navmesh polygons by their flag bits.

We use one material instead of one-per-flag-string (the legacy approach) so the
mesh exports cleanly and edits don't multiply materials. The color is driven by
``POLY_FLAG_0`` / ``POLY_FLAG_1`` attributes via Math+Mix nodes.
"""
import bpy
from bpy.types import Material

from .navmesh_attributes import NavMeshAttr

NAVMESH_MATERIAL_NAME = ".sollumz_navmesh"


def _bit(node_tree, attr_name: str, mask: int, location):
    """Build (attribute >> 0) & mask != 0 → 0/1 float."""
    attr = node_tree.nodes.new("ShaderNodeAttribute")
    attr.attribute_name = attr_name
    attr.location = location

    mod = node_tree.nodes.new("ShaderNodeMath")
    mod.operation = "MODULO"
    mod.location = (location[0] + 200, location[1])
    mod.inputs[1].default_value = mask * 2

    div = node_tree.nodes.new("ShaderNodeMath")
    div.operation = "DIVIDE"
    div.location = (location[0] + 400, location[1])
    div.inputs[1].default_value = mask

    floor = node_tree.nodes.new("ShaderNodeMath")
    floor.operation = "FLOOR"
    floor.location = (location[0] + 600, location[1])

    node_tree.links.new(attr.outputs["Fac"], mod.inputs[0])
    node_tree.links.new(mod.outputs[0], div.inputs[0])
    node_tree.links.new(div.outputs[0], floor.inputs[0])
    return floor.outputs[0]


def _scale_color(node_tree, bit_out, color, location):
    """Multiply a constant color by a 0/1 bit signal."""
    rgb = node_tree.nodes.new("ShaderNodeRGB")
    rgb.outputs[0].default_value = (*color, 1.0)
    rgb.location = location

    mix = node_tree.nodes.new("ShaderNodeMixRGB")
    mix.blend_type = "MIX"
    mix.location = (location[0] + 200, location[1])
    mix.inputs[0].default_value = 0.0
    mix.inputs[1].default_value = (0.0, 0.0, 0.0, 1.0)

    node_tree.links.new(rgb.outputs[0], mix.inputs[2])
    node_tree.links.new(bit_out, mix.inputs[0])
    return mix.outputs[0]


def _add_colors(node_tree, a, b, location):
    add = node_tree.nodes.new("ShaderNodeMixRGB")
    add.blend_type = "ADD"
    add.location = location
    add.inputs[0].default_value = 1.0
    node_tree.links.new(a, add.inputs[1])
    node_tree.links.new(b, add.inputs[2])
    return add.outputs[0]


def _build_navmesh_material() -> Material:
    mat = bpy.data.materials.new(NAVMESH_MATERIAL_NAME)
    mat.use_nodes = True
    tree = mat.node_tree
    tree.nodes.clear()

    output = tree.nodes.new("ShaderNodeOutputMaterial")
    output.location = (1800, 0)

    bsdf = tree.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (1500, 0)
    tree.links.new(bsdf.outputs[0], output.inputs[0])

    # Colorize a handful of high-value bits. Keeping the shader graph small
    # (full coverage of every flag bit would blow up the editor view).
    flag0 = NavMeshAttr.POLY_FLAG_0.value
    flag1 = NavMeshAttr.POLY_FLAG_1.value
    flag2 = NavMeshAttr.POLY_FLAG_2.value

    layers = [
        (flag0, 4,   (0.0, 0.5, 0.0)),   # Pavement → green
        (flag0, 128, (0.0, 0.3, 0.8)),   # Water → blue
        (flag1, 64,  (0.4, 0.4, 0.0)),   # Interior → yellow
        (flag1, 128, (0.5, 0.5, 0.5)),   # Isolated → grey
        (flag2, 2,   (0.6, 0.2, 0.0)),   # Road → orange
        (flag2, 8,   (0.3, 0.0, 0.3)),   # TrainTrack → purple
    ]

    accumulated = None
    for i, (attr_name, mask, color) in enumerate(layers):
        x = -800 + i * 50
        y = -250 * i
        bit_out = _bit(tree, attr_name, mask, (x, y))
        scaled = _scale_color(tree, bit_out, color, (x + 700, y))
        if accumulated is None:
            accumulated = scaled
        else:
            accumulated = _add_colors(tree, accumulated, scaled, (x + 1000, y))

    if accumulated is not None:
        tree.links.new(accumulated, bsdf.inputs["Base Color"])

    bsdf.inputs["Roughness"].default_value = 1.0
    if "Alpha" in bsdf.inputs:
        bsdf.inputs["Alpha"].default_value = 0.75
    mat.blend_method = "BLEND" if bpy.app.version < (4, 2, 0) else "BLEND"

    return mat


def get_navmesh_material() -> Material:
    """Return the shared navmesh material, creating it if absent."""
    mat = bpy.data.materials.get(NAVMESH_MATERIAL_NAME)
    if mat is None:
        mat = _build_navmesh_material()
    return mat
