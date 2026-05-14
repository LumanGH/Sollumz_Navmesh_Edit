"""Operators: export a NAVMESH to .ynv.xml, and toggle a flag bit on selected polys."""
import os
import traceback

import bpy
from bpy.props import BoolProperty, IntProperty, StringProperty
from bpy.types import Operator

from ..sollumz_properties import SollumType
from .. import logger
from .cwxml_navmesh import YNV
from .ynvexport import export_ynv


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
        if self.value:
            for poly in mesh.polygons:
                if poly.select:
                    data[poly.index].value = (int(data[poly.index].value) | mask) & 0xFF
        else:
            inv = (~mask) & 0xFF
            for poly in mesh.polygons:
                if poly.select:
                    data[poly.index].value = int(data[poly.index].value) & inv
        return {"FINISHED"}


def menu_func_export(self, context):
    self.layout.operator(SOLLUMZ_OT_export_ynv.bl_idname, text="CodeWalker NavMesh (.ynv.xml)")


def register():
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)


def unregister():
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)
