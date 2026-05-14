"""N-panel UI for editing navmesh data: root metadata, polygon flags, portals, points."""
import bpy
from bpy.types import Context, Panel

from ..sollumz_properties import SollumType
from .navmesh_attributes import (
    FLAG0_IN_SHELTER,
    FLAG0_LARGE,
    FLAG0_PAVEMENT,
    FLAG0_SMALL,
    FLAG0_TOO_STEEP,
    FLAG0_WATER,
    FLAG1_INTERIOR,
    FLAG1_ISOLATED,
    FLAG1_NEAR_CAR_NODE,
    FLAG2_LIES_ALONG_EDGE,
    FLAG2_NETWORK_SPAWN,
    FLAG2_ROAD,
    FLAG2_SHALLOW_WATER,
    FLAG2_TRAIN_TRACK,
    NavMeshAttr,
)


# Layout: (label, attribute, mask)
FLAG_BIT_LABELS: list[tuple[str, NavMeshAttr, int]] = [
    ("Is Small (auto)",       NavMeshAttr.POLY_FLAG_0, FLAG0_SMALL),
    ("Is Large (auto)",       NavMeshAttr.POLY_FLAG_0, FLAG0_LARGE),
    ("Is Pavement",           NavMeshAttr.POLY_FLAG_0, FLAG0_PAVEMENT),
    ("In Shelter",            NavMeshAttr.POLY_FLAG_0, FLAG0_IN_SHELTER),
    ("Too Steep To Walk On",  NavMeshAttr.POLY_FLAG_0, FLAG0_TOO_STEEP),
    ("Is Water",              NavMeshAttr.POLY_FLAG_0, FLAG0_WATER),
    ("Near Car Node",         NavMeshAttr.POLY_FLAG_1, FLAG1_NEAR_CAR_NODE),
    ("Is Interior",           NavMeshAttr.POLY_FLAG_1, FLAG1_INTERIOR),
    ("Is Isolated",           NavMeshAttr.POLY_FLAG_1, FLAG1_ISOLATED),
    ("Network Spawn",         NavMeshAttr.POLY_FLAG_2, FLAG2_NETWORK_SPAWN),
    ("Is Road",               NavMeshAttr.POLY_FLAG_2, FLAG2_ROAD),
    ("Lies Along Edge",       NavMeshAttr.POLY_FLAG_2, FLAG2_LIES_ALONG_EDGE),
    ("Is Train Track",        NavMeshAttr.POLY_FLAG_2, FLAG2_TRAIN_TRACK),
    ("Is Shallow Water",      NavMeshAttr.POLY_FLAG_2, FLAG2_SHALLOW_WATER),
]


def _get_active_navmesh_mesh(context: Context):
    obj = context.active_object
    if obj is None:
        return None
    if obj.sollum_type == SollumType.NAVMESH_POLY_MESH and obj.type == "MESH":
        return obj
    return None


class SOLLUMZ_PT_navmesh_root(Panel):
    bl_label = "NavMesh"
    bl_idname = "SOLLUMZ_PT_navmesh_root"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Sollumz Tools"

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.sollum_type == SollumType.NAVMESH

    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        props = obj.sz_navmesh

        col = layout.column(align=True)
        col.prop(props, "area_id")
        col.prop(props, "content_flags")

        layout.separator()
        col = layout.column(align=True)
        col.prop(props, "auto_bb")
        sub = col.column(align=True)
        sub.enabled = not props.auto_bb
        sub.prop(props, "bb_min")
        sub.prop(props, "bb_max")

        layout.separator()
        layout.prop(props, "auto_recompute_small_large")
        layout.prop(props, "auto_recompute_edges")

        layout.separator()
        layout.operator("sollumz.export_ynv", icon="EXPORT")


class SOLLUMZ_PT_navmesh_poly_flags(Panel):
    bl_label = "Polygon Flags"
    bl_idname = "SOLLUMZ_PT_navmesh_poly_flags"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Sollumz Tools"

    @classmethod
    def poll(cls, context):
        return _get_active_navmesh_mesh(context) is not None

    def draw(self, context):
        layout = self.layout
        obj = _get_active_navmesh_mesh(context)
        mesh = obj.data

        selected = [p for p in mesh.polygons if p.select] if not mesh.is_editmode else []
        if mesh.is_editmode:
            layout.label(text="Exit edit mode to edit flags", icon="INFO")
            return
        if not selected:
            layout.label(text="Select polygon(s) in Object Mode to edit flags")
            return

        layout.label(text=f"{len(selected)} polygon(s) selected")

        for label, attr, mask in FLAG_BIT_LABELS:
            data = mesh.attributes.get(attr.value)
            if data is None:
                continue
            data = data.data
            counts_on = sum(1 for p in selected if data[p.index].value & mask)
            row = layout.row(align=True)
            row.label(text=f"{label}  ({counts_on}/{len(selected)})")
            op_on = row.operator("sollumz.navmesh_set_poly_flag_bit", text="On")
            op_on.attr_name = attr.value
            op_on.mask = mask
            op_on.value = True
            op_off = row.operator("sollumz.navmesh_set_poly_flag_bit", text="Off")
            op_off.attr_name = attr.value
            op_off.mask = mask
            op_off.value = False


class SOLLUMZ_PT_navmesh_portal(Panel):
    bl_label = "NavMesh Portal"
    bl_idname = "SOLLUMZ_PT_navmesh_portal"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Sollumz Tools"

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.sollum_type == SollumType.NAVMESH_PORTAL

    def draw(self, context):
        layout = self.layout
        props = context.active_object.sz_nav_portal
        layout.prop(props, "portal_type")
        layout.prop(props, "angle")
        layout.prop(props, "poly_from")
        layout.prop(props, "poly_to")


class SOLLUMZ_PT_navmesh_point(Panel):
    bl_label = "NavMesh Point"
    bl_idname = "SOLLUMZ_PT_navmesh_point"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Sollumz Tools"

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.sollum_type == SollumType.NAVMESH_POINT

    def draw(self, context):
        layout = self.layout
        props = context.active_object.sz_nav_point
        layout.prop(props, "point_type")
