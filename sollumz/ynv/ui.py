"""N-panel UI for editing navmesh data: root metadata, polygon flags, portals, points."""
import bpy
from bpy.types import Context, Panel

from ..sollumz_properties import SollumType
from .navmesh_attributes import (
    FLAG0_AVOID_UNK0,
    FLAG0_AVOID_UNK1,
    FLAG0_FOOTPATH,
    FLAG0_STEEP_SLOPE,
    FLAG0_UNDERGROUND,
    FLAG0_WATER,
    FLAG1_HAS_PATH_NODE,
    FLAG1_INTERACTION_UNK,
    FLAG1_INTERIOR,
    FLAG1_UNDERGROUND_UNK0,
    FLAG1_UNDERGROUND_UNK1,
    FLAG1_UNDERGROUND_UNK2,
    FLAG1_UNDERGROUND_UNK3,
    FLAG2_CELL_EDGE,
    FLAG2_FLAT_GROUND,
    FLAG2_FOOTPATH_MALL,
    FLAG2_FOOTPATH_UNK1,
    FLAG2_FOOTPATH_UNK2,
    FLAG2_ROAD,
    FLAG2_SHALLOW_WATER,
    FLAG2_TRAIN_TRACK,
    FLAG3_SLOPE_EAST,
    FLAG3_SLOPE_NORTH,
    FLAG3_SLOPE_NORTH_EAST,
    FLAG3_SLOPE_NORTH_WEST,
    FLAG3_SLOPE_SOUTH,
    FLAG3_SLOPE_SOUTH_EAST,
    FLAG3_SLOPE_SOUTH_WEST,
    FLAG3_SLOPE_WEST,
    NavMeshAttr,
)


# Full CodeWalker flag set, grouped by source byte. Tuple: (label, attr, mask).
FLAG_BIT_LABELS: list[tuple[str, NavMeshAttr, int]] = [
    # --- flag0 ---
    ("Avoid Unk0",          NavMeshAttr.POLY_FLAG_0, FLAG0_AVOID_UNK0),
    ("Avoid Unk1",          NavMeshAttr.POLY_FLAG_0, FLAG0_AVOID_UNK1),
    ("Is Footpath",         NavMeshAttr.POLY_FLAG_0, FLAG0_FOOTPATH),
    ("Is Underground",      NavMeshAttr.POLY_FLAG_0, FLAG0_UNDERGROUND),
    ("Is Steep Slope",      NavMeshAttr.POLY_FLAG_0, FLAG0_STEEP_SLOPE),
    ("Is Water",            NavMeshAttr.POLY_FLAG_0, FLAG0_WATER),
    # --- flag1 ---
    ("Underground Unk0",    NavMeshAttr.POLY_FLAG_1, FLAG1_UNDERGROUND_UNK0),
    ("Underground Unk1",    NavMeshAttr.POLY_FLAG_1, FLAG1_UNDERGROUND_UNK1),
    ("Underground Unk2",    NavMeshAttr.POLY_FLAG_1, FLAG1_UNDERGROUND_UNK2),
    ("Underground Unk3",    NavMeshAttr.POLY_FLAG_1, FLAG1_UNDERGROUND_UNK3),
    ("Has Path Node",       NavMeshAttr.POLY_FLAG_1, FLAG1_HAS_PATH_NODE),
    ("Is Interior",         NavMeshAttr.POLY_FLAG_1, FLAG1_INTERIOR),
    ("Interaction Unk",     NavMeshAttr.POLY_FLAG_1, FLAG1_INTERACTION_UNK),
    # --- flag2 --- (Is Flat Ground at bit 0; deleting polygons with this
    # bit set crashes the game — use 'Strip Spawn' / 'Mark Isolated' instead)
    ("Is Flat Ground",      NavMeshAttr.POLY_FLAG_2, FLAG2_FLAT_GROUND),
    ("Is Road",             NavMeshAttr.POLY_FLAG_2, FLAG2_ROAD),
    ("Is Cell Edge",        NavMeshAttr.POLY_FLAG_2, FLAG2_CELL_EDGE),
    ("Is Train Track",      NavMeshAttr.POLY_FLAG_2, FLAG2_TRAIN_TRACK),
    ("Is Shallow Water",    NavMeshAttr.POLY_FLAG_2, FLAG2_SHALLOW_WATER),
    ("Footpath Unk1",       NavMeshAttr.POLY_FLAG_2, FLAG2_FOOTPATH_UNK1),
    ("Footpath Unk2",       NavMeshAttr.POLY_FLAG_2, FLAG2_FOOTPATH_UNK2),
    ("Footpath Mall",       NavMeshAttr.POLY_FLAG_2, FLAG2_FOOTPATH_MALL),
    # --- flag3 (slope direction) ---
    ("Slope South",         NavMeshAttr.POLY_FLAG_3, FLAG3_SLOPE_SOUTH),
    ("Slope SE",            NavMeshAttr.POLY_FLAG_3, FLAG3_SLOPE_SOUTH_EAST),
    ("Slope East",          NavMeshAttr.POLY_FLAG_3, FLAG3_SLOPE_EAST),
    ("Slope NE",            NavMeshAttr.POLY_FLAG_3, FLAG3_SLOPE_NORTH_EAST),
    ("Slope North",         NavMeshAttr.POLY_FLAG_3, FLAG3_SLOPE_NORTH),
    ("Slope NW",            NavMeshAttr.POLY_FLAG_3, FLAG3_SLOPE_NORTH_WEST),
    ("Slope West",          NavMeshAttr.POLY_FLAG_3, FLAG3_SLOPE_WEST),
    ("Slope SW",            NavMeshAttr.POLY_FLAG_3, FLAG3_SLOPE_SOUTH_WEST),
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

        # Viewport shading hint — the user has to flip Solid → Color =
        # Attribute once for the color attribute we ship with the mesh.
        info = layout.column(align=True)
        info.scale_y = 0.85
        info.label(text="Solid-mode tip:", icon="INFO")
        info.label(text="Viewport Shading → Solid → Color: Attribute")

        layout.separator()
        row = layout.row(align=True)
        row.operator("sollumz.navmesh_refresh_colors", icon="FILE_REFRESH")
        # Select-Same works in both Object and Edit mode; surfacing it here so
        # the workflow ("click a poly, then 'find me the rest like it'") is
        # one click away regardless of which mode the user is in.
        row.operator("sollumz.navmesh_select_same_flags",
                     text="Select Same Flags", icon="SHADERFX")

        # Deleting Network-Spawn polygons crashes the game. Surface the
        # "disable instead of delete" workflow front-and-center.
        layout.separator()
        warn = layout.column(align=True)
        warn.scale_y = 0.85
        warn.label(text="DO NOT delete polygons with Network Spawn", icon="ERROR")
        warn.label(text="(crashes GTA V). Use one of these instead:")
        row = layout.row(align=True)
        row.operator("sollumz.navmesh_mark_isolated",
                     text="Mark Isolated", icon="CANCEL")
        row.operator("sollumz.navmesh_strip_spawn",
                     text="Strip Spawn", icon="X")
        # Mark Isolated only flips flag bits — the game's spawn spatial index
        # still keeps those polys as candidates, so peds spawn there but
        # stand still. Sink physically pushes the polys 100m down — same
        # trick the 3ds max ONV exporter relied on, and it works.
        layout.operator("sollumz.navmesh_sink_polys",
                        text="Sink Selected", icon="TRIA_DOWN_BAR")
        # Full delete: only safe now that the export path rebuilds adjacency
        # and re-resolves portals / NavPoints. If the game still crashes a
        # few seconds after entering the zone with Sink active, try this —
        # the polys disappear from the file entirely, removing them from
        # whatever spawn-spatial index keeps causing the delayed crash.
        layout.operator("sollumz.navmesh_delete_polys",
                        text="Delete Selected (Clean)", icon="TRASH")

        layout.separator()
        if mesh.is_editmode:
            layout.label(text="Edit mode: use 'Select Same Flags' above.", icon="INFO")
            layout.label(text="On/Off requires Object Mode.")
            return

        selected = [p for p in mesh.polygons if p.select]
        sel_count = len(selected)
        layout.label(text=(f"{sel_count} polygon(s) selected"
                           if sel_count else "Select polygon(s) to edit flags"))

        for label, attr, mask in FLAG_BIT_LABELS:
            data = mesh.attributes.get(attr.value)
            if data is None:
                continue
            data = data.data
            counts_on = sum(1 for p in selected if data[p.index].value & mask)

            row = layout.row(align=True)
            row.label(text=f"{label}  ({counts_on}/{sel_count})" if sel_count else label)

            # On / Off only meaningful when polygons are selected.
            sub = row.row(align=True)
            sub.enabled = sel_count > 0
            op_on = sub.operator("sollumz.navmesh_set_poly_flag_bit", text="On")
            op_on.attr_name = attr.value
            op_on.mask = mask
            op_on.value = True
            op_off = sub.operator("sollumz.navmesh_set_poly_flag_bit", text="Off")
            op_off.attr_name = attr.value
            op_off.mask = mask
            op_off.value = False

            # Select: pick all polys with this bit on. Always available.
            op_sel = row.operator("sollumz.navmesh_select_polys_by_flag",
                                  text="", icon="RESTRICT_SELECT_OFF")
            op_sel.attr_name = attr.value
            op_sel.mask = mask
            op_sel.extend = False
            op_add = row.operator("sollumz.navmesh_select_polys_by_flag",
                                  text="", icon="ADD")
            op_add.attr_name = attr.value
            op_add.mask = mask
            op_add.extend = True


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
