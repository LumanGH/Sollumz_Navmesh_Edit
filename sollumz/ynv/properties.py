"""PropertyGroups and registration glue for YNV (navmesh) editing."""
import bpy
from bpy.props import (
    BoolProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import Object, PropertyGroup


# Standalone navmesh (vehicle / interior nav) uses this magic area_id.
STANDALONE_AREA_ID = 10000


class SzNavMeshProperties(PropertyGroup):
    """Root navmesh metadata. Stored on the NAVMESH parent object."""

    area_id: IntProperty(
        name="Area ID",
        description=(
            "Grid cell index (y * 100 + x) for map navmeshes, or 10000 for "
            "standalone (vehicle / interior) navmeshes"
        ),
        default=STANDALONE_AREA_ID,
        min=0,
    )
    content_flags: StringProperty(
        name="Content Flags",
        description="Comma-separated content flag names, e.g. 'Polygons, Portals, Unknown8'",
        default="Polygons, Portals",
    )
    bb_min: FloatVectorProperty(
        name="BB Min",
        description="Cell or asset bounding box minimum (as written to <BBMin>)",
        size=3,
        subtype="XYZ",
    )
    bb_max: FloatVectorProperty(
        name="BB Max",
        description="Cell or asset bounding box maximum (as written to <BBMax>)",
        size=3,
        subtype="XYZ",
    )
    auto_bb: BoolProperty(
        name="Auto Bounding Box",
        description=(
            "Recompute BB Min/Max from the polygon mesh on export. Disable to "
            "preserve the exact bounds the file was imported with"
        ),
        default=True,
    )
    auto_recompute_small_large: BoolProperty(
        name="Auto Recompute Small/Large",
        description=(
            "On export, reset the IsSmall/IsLarge bits of every polygon from "
            "its area (area < 2 → small, > 40 → large)"
        ),
        default=True,
    )
    auto_recompute_edges: BoolProperty(
        name="Auto Recompute Edge Adjacency",
        description=(
            "On export, rebuild each polygon's <Edges> from the current mesh "
            "topology. Required after deleting/adding polygons — otherwise the "
            "saved indices point at polygons that no longer exist and the game "
            "may crash. Boundary edges keep their original external references"
        ),
        default=True,
    )


class SzNavPortalProperties(PropertyGroup):
    """Per-portal data; one of these lives on each NAVMESH_PORTAL object."""

    portal_type: IntProperty(name="Type", default=1, min=0, max=255)
    angle: FloatProperty(name="Angle", default=0.0, subtype="ANGLE")
    poly_from: IntProperty(name="Poly From", default=0, min=0)
    poly_to: IntProperty(name="Poly To", default=0, min=0)


class SzNavPointProperties(PropertyGroup):
    """Per-point data; one of these lives on each NAVMESH_POINT object."""

    point_type: IntProperty(name="Type", default=0, min=0, max=255)


def register():
    Object.sz_navmesh = PointerProperty(type=SzNavMeshProperties)
    Object.sz_nav_portal = PointerProperty(type=SzNavPortalProperties)
    Object.sz_nav_point = PointerProperty(type=SzNavPointProperties)


def unregister():
    del Object.sz_navmesh
    del Object.sz_nav_portal
    del Object.sz_nav_point
