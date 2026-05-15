"""Operators: export a NAVMESH to .ynv.xml, and toggle a flag bit on selected polys."""
import os
import traceback

import bpy
from bpy.props import BoolProperty, IntProperty, StringProperty
from bpy.types import Operator

from ..sollumz_properties import SollumType
from .. import logger
from .cwxml_navmesh import YNV
from .navmesh_attributes import (
    FLAG0_FOOTPATH,
    FLAG0_STEEP_SLOPE,
    FLAG1_HAS_PATH_NODE,
    FLAG1_INTERACTION_UNK,
    FLAG2_FLAT_GROUND,
    FLAG2_ROAD,
    NavMeshAttr,
    POLY_FLAG_ATTRS,
)
from .navmesh_colors import flags_to_color
from .ynvexport import export_ynv


def _refresh_poly_colors(mesh, poly_indices) -> None:
    """Recompute the per-corner FLOAT_COLOR attribute for the given polygons."""
    color_attr = mesh.color_attributes.get(NavMeshAttr.POLY_COLOR.value)
    if color_attr is None:
        return
    color_data = color_attr.data
    f0_data = mesh.attributes[NavMeshAttr.POLY_FLAG_0.value].data
    f1_data = mesh.attributes[NavMeshAttr.POLY_FLAG_1.value].data
    f2_data = mesh.attributes[NavMeshAttr.POLY_FLAG_2.value].data
    for i in poly_indices:
        color = flags_to_color(
            f0_data[i].value, f1_data[i].value, f2_data[i].value,
        )
        for loop_idx in mesh.polygons[i].loop_indices:
            color_data[loop_idx].color = color


def _find_navmesh_root(obj):
    while obj is not None:
        if obj.sollum_type == SollumType.NAVMESH:
            return obj
        obj = obj.parent
    return None


class SOLLUMZ_OT_export_ynv(Operator):
    """Export the selected NAVMESH to a CodeWalker .ynv.xml file."""
    bl_idname = "sollumz.export_ynv"
    bl_label = "Export NavMesh (.ynv.xml)"
    bl_options = {"REGISTER"}

    filepath: StringProperty(subtype="FILE_PATH")
    filter_glob: StringProperty(default="*.ynv.xml", options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        return _find_navmesh_root(context.active_object) is not None

    def invoke(self, context, event):
        root = _find_navmesh_root(context.active_object)
        if not self.filepath:
            self.filepath = (root.name if root else "navmesh") + YNV.file_extension
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        root = _find_navmesh_root(context.active_object)
        if root is None:
            self.report({"ERROR"}, "No NAVMESH object found in the selection.")
            return {"CANCELLED"}

        path = bpy.path.abspath(self.filepath)
        if not path.endswith(YNV.file_extension):
            path += YNV.file_extension

        with logger.use_operator_logger(self):
            try:
                ok = export_ynv(root, path)
            except Exception:
                logger.error(f"Failed to export '{root.name}':\n{traceback.format_exc()}")
                return {"CANCELLED"}

        if not ok:
            self.report({"ERROR"}, f"Failed to export '{root.name}'. See Info log.")
            return {"CANCELLED"}

        self.report({"INFO"}, f"Exported {os.path.basename(path)}")
        return {"FINISHED"}


class SOLLUMZ_OT_navmesh_set_poly_flag_bit(Operator):
    """Set or clear a single flag bit on every selected polygon of the active navmesh."""
    bl_idname = "sollumz.navmesh_set_poly_flag_bit"
    bl_label = "Toggle Navmesh Polygon Flag Bit"
    bl_options = {"REGISTER", "UNDO"}

    attr_name: StringProperty()
    mask: IntProperty()
    value: BoolProperty()

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None
            and obj.type == "MESH"
            and obj.sollum_type == SollumType.NAVMESH_POLY_MESH
            and not obj.data.is_editmode
        )

    def execute(self, context):
        mesh = context.active_object.data
        attr = mesh.attributes.get(self.attr_name)
        if attr is None:
            self.report({"ERROR"}, f"Attribute '{self.attr_name}' not found on mesh.")
            return {"CANCELLED"}

        data = attr.data
        mask = int(self.mask)
        touched = []
        if self.value:
            for poly in mesh.polygons:
                if poly.select:
                    data[poly.index].value = (int(data[poly.index].value) | mask) & 0xFF
                    touched.append(poly.index)
        else:
            inv = (~mask) & 0xFF
            for poly in mesh.polygons:
                if poly.select:
                    data[poly.index].value = int(data[poly.index].value) & inv
                    touched.append(poly.index)

        # Keep the viewport color attribute in sync with the new flag values.
        _refresh_poly_colors(mesh, touched)
        mesh.update()
        return {"FINISHED"}


class SOLLUMZ_OT_navmesh_select_polys_by_flag(Operator):
    """Select every polygon whose given flag bit is on.

    With ``extend`` enabled, the operator adds to the current selection
    instead of replacing it — useful for stacking multiple categories.
    """
    bl_idname = "sollumz.navmesh_select_polys_by_flag"
    bl_label = "Select Polys by Navmesh Flag"
    bl_options = {"REGISTER", "UNDO"}

    attr_name: StringProperty()
    mask: IntProperty()
    extend: BoolProperty(default=False)

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None
            and obj.type == "MESH"
            and obj.sollum_type == SollumType.NAVMESH_POLY_MESH
            and not obj.data.is_editmode
        )

    def execute(self, context):
        mesh = context.active_object.data
        attr = mesh.attributes.get(self.attr_name)
        if attr is None:
            self.report({"ERROR"}, f"Attribute '{self.attr_name}' not found on mesh.")
            return {"CANCELLED"}
        data = attr.data
        mask = int(self.mask)
        matched = 0
        if not self.extend:
            for p in mesh.polygons:
                p.select = False
        for p in mesh.polygons:
            if int(data[p.index].value) & mask:
                p.select = True
                matched += 1
        mesh.update()
        self.report({"INFO"}, f"{matched} polygon(s) match the flag.")
        return {"FINISHED"}


class SOLLUMZ_OT_navmesh_select_same_flags(Operator):
    """Select every polygon whose flag bytes exactly match the active polygon.

    Works in Object Mode (uses ``poly.select``) and Edit Mode (uses bmesh's
    face layers). With ``extend`` enabled, the matching polygons are added to
    the current selection instead of replacing it.

    ``mask_f3`` controls whether cover-direction bits (flag3) participate in
    the comparison — usually they're noise and you only care about the
    semantic flags 0/1/2.
    """
    bl_idname = "sollumz.navmesh_select_same_flags"
    bl_label = "Select Polys with Same Flags"
    bl_options = {"REGISTER", "UNDO"}

    extend: BoolProperty(name="Extend", default=False)
    mask_f3: BoolProperty(
        name="Include Cover Directions (flag3)", default=False,
        description=(
            "Also require flag3 (per-direction cover bits) to match. Usually "
            "left off — flag3 is per-polygon noise and matching on it shrinks "
            "results to almost nothing"
        ),
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None
            and obj.type == "MESH"
            and obj.sollum_type == SollumType.NAVMESH_POLY_MESH
        )

    def execute(self, context):
        obj = context.active_object
        mesh = obj.data

        if mesh.is_editmode:
            import bmesh
            bm = bmesh.from_edit_mesh(mesh)
            bm.faces.ensure_lookup_table()

            try:
                f0_layer = bm.faces.layers.int[NavMeshAttr.POLY_FLAG_0.value]
                f1_layer = bm.faces.layers.int[NavMeshAttr.POLY_FLAG_1.value]
                f2_layer = bm.faces.layers.int[NavMeshAttr.POLY_FLAG_2.value]
                f3_layer = (bm.faces.layers.int[NavMeshAttr.POLY_FLAG_3.value]
                            if self.mask_f3 else None)
            except KeyError:
                self.report({"ERROR"}, "Navmesh flag attributes not found on this mesh.")
                return {"CANCELLED"}

            active = bm.faces.active
            if active is None:
                self.report({"ERROR"}, "No active face. Click one in Edit Mode first.")
                return {"CANCELLED"}

            ref0 = active[f0_layer]
            ref1 = active[f1_layer]
            ref2 = active[f2_layer]
            ref3 = active[f3_layer] if f3_layer is not None else None

            matched = 0
            for f in bm.faces:
                same = (f[f0_layer] == ref0
                        and f[f1_layer] == ref1
                        and f[f2_layer] == ref2)
                if same and f3_layer is not None and f[f3_layer] != ref3:
                    same = False
                if same:
                    f.select = True
                    matched += 1
                elif not self.extend:
                    f.select = False
            bmesh.update_edit_mesh(mesh)
            self.report({"INFO"}, f"{matched} matching polygon(s).")
            return {"FINISHED"}

        # Object Mode path
        f0_data = mesh.attributes[NavMeshAttr.POLY_FLAG_0.value].data
        f1_data = mesh.attributes[NavMeshAttr.POLY_FLAG_1.value].data
        f2_data = mesh.attributes[NavMeshAttr.POLY_FLAG_2.value].data
        f3_data = mesh.attributes[NavMeshAttr.POLY_FLAG_3.value].data

        active_idx = mesh.polygons.active
        if active_idx < 0 or active_idx >= len(mesh.polygons):
            self.report({"ERROR"}, "No active polygon. Select one first.")
            return {"CANCELLED"}

        ref0 = f0_data[active_idx].value
        ref1 = f1_data[active_idx].value
        ref2 = f2_data[active_idx].value
        ref3 = f3_data[active_idx].value if self.mask_f3 else None

        matched = 0
        for p in mesh.polygons:
            same = (f0_data[p.index].value == ref0
                    and f1_data[p.index].value == ref1
                    and f2_data[p.index].value == ref2)
            if same and self.mask_f3 and f3_data[p.index].value != ref3:
                same = False
            if same:
                p.select = True
                matched += 1
            elif not self.extend:
                p.select = False
        mesh.update()
        self.report({"INFO"}, f"{matched} matching polygon(s).")
        return {"FINISHED"}


class SOLLUMZ_OT_navmesh_delete_polys(Operator):
    """Delete selected polygons cleanly — every downstream reference is fixed.

    Why a custom operator instead of Blender's Delete:
      The plain delete leaves the file layer pointing at stale indices —
      cross-cell edges from neighbour navmeshes, portal PolyFrom/PolyTo, the
      <Edges> list of the polygons that survived. That's what crashed the
      game the first time we tried deleting polygons.

    This operator drops selected polys + orphaned verts in a single
    undo step. The export path already rebuilds adjacency, re-resolves
    portals via nearest-poly, and re-projects NavPoints onto remaining
    geometry whenever ``Auto Recompute Edge Adjacency`` is enabled (the
    default), so the resulting .ynv is internally consistent.

    Use this when 'Sink' isn't enough: sunk polys still live in the file
    and the game's spawn lookup keeps finding them via XY, which is why
    peds spawn and stand still in the sunk area.
    """
    bl_idname = "sollumz.navmesh_delete_polys"
    bl_label = "Delete Selected Polygons (Clean)"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None
            and obj.type == "MESH"
            and obj.sollum_type == SollumType.NAVMESH_POLY_MESH
            and not obj.data.is_editmode
        )

    def execute(self, context):
        import bmesh
        obj = context.active_object
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bm.faces.ensure_lookup_table()
        faces = [f for f in bm.faces if f.select]
        if not faces:
            bm.free()
            self.report({"ERROR"}, "Select polygons in Object Mode first.")
            return {"CANCELLED"}
        bmesh.ops.delete(bm, geom=faces, context="FACES")
        bm.to_mesh(obj.data)
        bm.free()
        obj.data.update()
        self.report(
            {"INFO"},
            f"Deleted {len(faces)} polygon(s). Re-export to rebuild adjacency.",
        )
        return {"FINISHED"}



class SOLLUMZ_OT_navmesh_mark_isolated(Operator):
    """Mark selected polygons as 'isolated' instead of deleting them.

    Deleting polygons that carry the Network Spawn flag tends to crash GTA V
    — the binary .ynv builds an auxiliary spatial index for spawn lookups
    that desyncs when geometry vanishes. Stripping the spawn / road /
    pavement bits and setting Isolated keeps the polygon in place (so all
    adjacency and spatial indices stay consistent), but tells the game that
    the polygon is dead: peds won't spawn on it and AI ignores it for
    routing.

    Use this instead of Delete for any polygon that originally had Network
    Spawn turned on.
    """
    bl_idname = "sollumz.navmesh_mark_isolated"
    bl_label = "Mark Selected as Isolated"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None
            and obj.type == "MESH"
            and obj.sollum_type == SollumType.NAVMESH_POLY_MESH
            and not obj.data.is_editmode
        )

    def execute(self, context):
        mesh = context.active_object.data
        f0_data = mesh.attributes[NavMeshAttr.POLY_FLAG_0.value].data
        f1_data = mesh.attributes[NavMeshAttr.POLY_FLAG_1.value].data
        f2_data = mesh.attributes[NavMeshAttr.POLY_FLAG_2.value].data

        # SteepSlope is the only bit we know for certain blocks AI walking.
        # We also clear category bits the game uses for spawn/path-node
        # lookups so the polygon stops contributing to those systems but its
        # geometry stays in place (which keeps spatial / adjacency indices
        # consistent — the actual reason for the no-delete rule).
        clear_f0 = (FLAG0_FOOTPATH) & 0xFF
        set_f0 = FLAG0_STEEP_SLOPE
        clear_f1 = FLAG1_HAS_PATH_NODE & 0xFF
        set_f1 = FLAG1_INTERACTION_UNK
        clear_f2 = (FLAG2_FLAT_GROUND | FLAG2_ROAD) & 0xFF

        touched = []
        for poly in mesh.polygons:
            if not poly.select:
                continue
            i = poly.index
            f0_data[i].value = (int(f0_data[i].value) & ~clear_f0 | set_f0) & 0xFF
            f1_data[i].value = (int(f1_data[i].value) & ~clear_f1 | set_f1) & 0xFF
            f2_data[i].value = int(f2_data[i].value) & ~clear_f2 & 0xFF
            touched.append(i)

        _refresh_poly_colors(mesh, touched)
        mesh.update()
        self.report({"INFO"}, f"Marked {len(touched)} polygon(s) as isolated.")
        return {"FINISHED"}


class SOLLUMZ_OT_navmesh_strip_spawn(Operator):
    """Clear the Network Spawn flag on every selected polygon.

    Less aggressive than 'Mark Isolated' — only the spawn bit is removed,
    keeping the polygon walkable, road-flagged, etc. Use when you don't want
    peds to spawn here but still want AI to route through.
    """
    bl_idname = "sollumz.navmesh_strip_spawn"
    bl_label = "Strip Network Spawn"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None
            and obj.type == "MESH"
            and obj.sollum_type == SollumType.NAVMESH_POLY_MESH
            and not obj.data.is_editmode
        )

    def execute(self, context):
        mesh = context.active_object.data
        f2_data = mesh.attributes[NavMeshAttr.POLY_FLAG_2.value].data
        touched = []
        # bit 0 of flag2 is the "no-delete" bit (IsFlatGround in the 3ds Max
        # tool, NetworkSpawnCandidate in QOL). Whatever its true semantic,
        # clearing it lets us strip the polygon from the spawn / spatial
        # index that crashes the game when its index disappears.
        inv = (~FLAG2_FLAT_GROUND) & 0xFF
        for poly in mesh.polygons:
            if not poly.select:
                continue
            f2_data[poly.index].value = int(f2_data[poly.index].value) & inv
            touched.append(poly.index)
        _refresh_poly_colors(mesh, touched)
        mesh.update()
        self.report({"INFO"}, f"Cleared spawn flag on {len(touched)} polygon(s).")
        return {"FINISHED"}


class SOLLUMZ_OT_navmesh_sink_polys(Operator):
    """Push selected polygons down along -Z so the game treats them as 'gone'.

    Why this exists: deleting polygons or just stripping their walkable flags
    isn't enough — the game keeps spawning peds on them ('static' peds that
    don't move) because some auxiliary spatial index inside the binary .ynv
    still classifies them as spawn candidates. CodeWalker doesn't rebuild
    that index when going XML → binary, so we can't fix it from XML alone.

    Moving the polygons 100m straight down keeps adjacency / portal / point
    indices intact (so no crash) but puts the geometry far enough from the
    surface that the spawn lookups find nothing usable — peds neither spawn
    on them nor route through them. This matches the old 3ds max ONV trick.

    Only the vertices that are *exclusively* used by selected polygons are
    moved; shared vertices stay put so the rest of the mesh doesn't drag
    along with them.
    """
    bl_idname = "sollumz.navmesh_sink_polys"
    bl_label = "Sink Selected Polygons (-100m Z)"
    bl_options = {"REGISTER", "UNDO"}

    distance: bpy.props.FloatProperty(
        name="Distance (m)", default=100.0, min=0.1, soft_max=500.0,
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None
            and obj.type == "MESH"
            and obj.sollum_type == SollumType.NAVMESH_POLY_MESH
            and not obj.data.is_editmode
        )

    def execute(self, context):
        mesh = context.active_object.data
        # Collect vertices that belong ONLY to selected polygons. Shared
        # vertices are skipped so we don't tear neighbours along with us.
        sel_polys = {p.index for p in mesh.polygons if p.select}
        if not sel_polys:
            self.report({"WARNING"}, "Select polygons first.")
            return {"CANCELLED"}

        from collections import defaultdict
        vert_users = defaultdict(set)
        for p in mesh.polygons:
            for v in p.vertices:
                vert_users[v].add(p.index)

        verts_to_sink = [
            v for v, users in vert_users.items()
            if users.issubset(sel_polys)
        ]
        if not verts_to_sink:
            self.report({"WARNING"},
                        "Selected polygons share all their vertices with "
                        "neighbours. Sinking would distort the rest of the "
                        "mesh — pick polygons that aren't bridged to kept "
                        "geometry, or detach them first.")
            return {"CANCELLED"}

        for v in verts_to_sink:
            mesh.vertices[v].co.z -= self.distance

        mesh.update()
        self.report({"INFO"},
                    f"Sunk {len(verts_to_sink)} vertex/vertices of "
                    f"{len(sel_polys)} polygon(s) by {self.distance:.1f}m.")
        return {"FINISHED"}


class SOLLUMZ_OT_navmesh_refresh_colors(Operator):
    """Recompute the FLOAT_COLOR attribute from current flag bytes.

    Use this after bulk-editing flag attributes directly (e.g. via Geometry
    Nodes or external scripts) to bring the viewport color back in sync.
    """
    bl_idname = "sollumz.navmesh_refresh_colors"
    bl_label = "Refresh Navmesh Colors"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None
            and obj.type == "MESH"
            and obj.sollum_type == SollumType.NAVMESH_POLY_MESH
        )

    def execute(self, context):
        mesh = context.active_object.data
        _refresh_poly_colors(mesh, range(len(mesh.polygons)))
        # Ensure the attribute is active for both edit and render so Solid
        # mode (Color = Attribute) picks it up.
        color_attr = mesh.color_attributes.get(NavMeshAttr.POLY_COLOR.value)
        if color_attr is not None:
            idx = list(mesh.color_attributes).index(color_attr)
            mesh.color_attributes.render_color_index = idx
            mesh.color_attributes.active_color_index = idx
        mesh.update()
        return {"FINISHED"}


def menu_func_export(self, context):
    self.layout.operator(SOLLUMZ_OT_export_ynv.bl_idname, text="CodeWalker NavMesh (.ynv.xml)")


def register():
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)


def unregister():
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)
