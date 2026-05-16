"""UI panels for navmesh editing.

* **N-panel "NavMesh Polygon Flags"** — main flag editor under the
  "Sollumz Tools" category. Active in Edit Mode (where polygon selection
  is meaningful); disabled with a hint in Object Mode.
* **N-panel "NavMesh"** — root metadata + export button (shown for the
  NAVMESH parent object).
* **Material Properties → "NavMesh Category"** — read-only blurb that
  tells the user which category the current material represents; nothing
  to edit there.
"""
import bpy
from bpy.types import Panel

from ..sollumz_properties import SollumType
from .navmesh_attributes import (
    FLAG0_BITS,
    FLAG1_BITS,
    FLAG2_BITS,
    FLAG3_BITS,
    NavMeshAttr,
)
from .navmesh_material import (
    CATEGORY_LABELS,
    MATERIAL_NAME_PREFIX,
    material_category,
)


def _is_navmesh_material(mat) -> bool:
    return mat is not None and mat.name.startswith(MATERIAL_NAME_PREFIX)


def _active_navmesh_polymesh(context):
    obj = context.active_object
    if obj is None:
        return None
    if obj.sollum_type == SollumType.NAVMESH_POLY_MESH and obj.type == "MESH":
        return obj
    return None


def _bm_selected_count(mesh):
    """Cheap selected-face count for an Edit Mode mesh."""
    import bmesh
    bm = bmesh.from_edit_mesh(mesh)
    return sum(1 for f in bm.faces if f.select), bm


def _draw_flag_group(layout, mesh, bm, sel_count, label, attr, bits, enabled: bool):
    box = layout.box()
    box.label(text=label)
    body = box.column(align=True)
    body.enabled = enabled

    layer = None
    if bm is not None:
        try:
            layer = bm.faces.layers.int[attr.value]
        except KeyError:
            body.label(text="(attribute missing)", icon="ERROR")
            return

    for bit_idx, bit_label in bits:
        mask = 1 << bit_idx
        if layer is not None:
            count_on = sum(1 for f in bm.faces if f.select and f[layer] & mask)
            display = (f"{bit_label}  ({count_on}/{sel_count})"
                       if sel_count else bit_label)
        else:
            display = bit_label
        row = body.row(align=True)
        row.label(text=display)
        sub = row.row(align=True)
        sub.enabled = enabled and sel_count > 0
        op_on = sub.operator("sollumz.navmesh_set_poly_flag_bit", text="On")
        op_on.attr_name = attr.value
        op_on.mask = mask
        op_on.value = True
        op_off = sub.operator("sollumz.navmesh_set_poly_flag_bit", text="Off")
        op_off.attr_name = attr.value
        op_off.mask = mask
        op_off.value = False
        op_sel = row.operator("sollumz.navmesh_select_polys_by_flag",
                              text="", icon="RESTRICT_SELECT_OFF")
        op_sel.attr_name = attr.value
        op_sel.mask = mask
        op_sel.extend = False


class SOLLUMZ_PT_navmesh_poly_flags(Panel):
    """N-panel: per-polygon flag editor for the active navmesh polygon mesh."""
    bl_label = "NavMesh Polygon Flags"
    bl_idname = "SOLLUMZ_PT_navmesh_poly_flags"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Sollumz Tools"

    @classmethod
    def poll(cls, context):
        return _active_navmesh_polymesh(context) is not None

    def draw(self, context):
        layout = self.layout
        obj = _active_navmesh_polymesh(context)
        mesh = obj.data

        if not mesh.is_editmode:
            warn = layout.column(align=True)
            warn.label(text="Enter Edit Mode to edit polygon flags.", icon="INFO")
            warn.label(text="(polygon selection isn't available in Object Mode.)")
            sel_count, bm = 0, None
        else:
            sel_count, bm = _bm_selected_count(mesh)
            layout.label(text=(f"{sel_count} polygon(s) selected"
                               if sel_count else "Select polygon(s) to edit"),
                         icon="FACESEL")

        enabled = mesh.is_editmode

        # "Disable" workflow — front and centre because plain Delete is the
        # main cause of in-game crashes. Sink is the safe replacement.
        layout.separator()
        sink_box = layout.box()
        sink_box.label(text="Disable Polygons", icon="ERROR")
        warn = sink_box.column(align=True)
        warn.scale_y = 0.85
        warn.label(text="DON'T use Delete — it shifts indices and")
        warn.label(text="crashes the game. Use Sink instead:")
        sink_row = sink_box.row()
        sink_row.enabled = enabled and sel_count > 0
        sink_row.operator("sollumz.navmesh_sink_polys",
                          text="Sink Selected (-100m Z)", icon="TRIA_DOWN_BAR")

        layout.separator()
        for label, attr, bits in (
            ("Flag 0", NavMeshAttr.POLY_FLAG_0, FLAG0_BITS),
            ("Flag 1", NavMeshAttr.POLY_FLAG_1, FLAG1_BITS),
            ("Flag 2 (Category)", NavMeshAttr.POLY_FLAG_2, FLAG2_BITS),
            ("Flag 3 (Slope)", NavMeshAttr.POLY_FLAG_3, FLAG3_BITS),
        ):
            _draw_flag_group(layout, mesh, bm, sel_count, label, attr, bits, enabled)


class SOLLUMZ_PT_navmesh_root(Panel):
    """N-panel: root metadata + export button (shown on the NAVMESH parent)."""
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
        props = context.active_object.sz_navmesh

        col = layout.column(align=True)
        col.prop(props, "area_id")
        col.prop(props, "content_flags")

        layout.separator()
        col = layout.column(align=True)
        col.prop(props, "bb_min")
        col.prop(props, "bb_max")

        layout.separator()
        layout.operator("sollumz.export_ynv", icon="EXPORT")

        # Multi-cell export — required when deleting polygons that touch a
        # cell border (cross-cell edge indices in sibling files would go
        # stale otherwise).
        scene_navmesh_count = sum(
            1 for o in context.scene.objects
            if o.sollum_type == "sollumz_navmesh"
        )
        layout.separator()
        box = layout.box()
        box.label(text=f"Scene: {scene_navmesh_count} navmesh cell(s)",
                  icon="WORLD_DATA")
        if scene_navmesh_count <= 1:
            warn = box.column(align=True)
            warn.scale_y = 0.85
            warn.label(text="Load surrounding cells (3x3 grid)", icon="INFO")
            warn.label(text="before deleting border polygons —")
            warn.label(text="multi-cell export keeps neighbours")
            warn.label(text="from crashing the game.")
        box.operator("sollumz.export_all_navmeshes", icon="EXPORT")


class SOLLUMZ_PT_navmesh_material_category(Panel):
    """Material Properties: read-only category info for the active material."""
    bl_label = "NavMesh Category"
    bl_idname = "SOLLUMZ_PT_navmesh_material_category"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "material"

    @classmethod
    def poll(cls, context):
        return _is_navmesh_material(getattr(context, "material", None))

    def draw(self, context):
        layout = self.layout
        cat = material_category(context.material)
        if cat is not None:
            layout.label(text=f"Category: {CATEGORY_LABELS[cat]}", icon="MATERIAL")
        info = layout.column(align=True)
        info.scale_y = 0.85
        info.label(text="Edit Mode → 'Select' above picks every", icon="INFO")
        info.label(text="polygon using this material. Flags are")
        info.label(text="edited in the N-panel (Sollumz Tools).")


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
