"""Build a CWXML .ynv.xml file from a NAVMESH object hierarchy."""
from typing import Optional

from mathutils import Vector

from ..sollumz_properties import SollumType
from .. import logger
from .cwxml_navmesh import (
    NavPoint,
    NavPolygon,
    NavPortal,
    Navmesh,
    YNV,
)
from .navmesh_attributes import (
    ADJACENT_NONE,
    FLAG0_LARGE,
    FLAG0_SMALL,
    FLAG0_WATER,
    NavMeshAttr,
    POLY_FLAG_ATTRS,
    format_edges_str,
    format_flags_str,
    has_navmesh_attributes,
)

# Match QOL fork's poly-area thresholds.
POLY_SMALL_MAX_AREA = 2.0
POLY_LARGE_MIN_AREA = 40.0

# Centroid is encoded as a single byte per axis, range 0..255.
POLY_BBOX_RESOLUTION = 0.25


def _find_polymesh(navmesh_obj) -> Optional[object]:
    for child in navmesh_obj.children:
        if child.sollum_type == SollumType.NAVMESH_POLY_MESH and child.type == "MESH":
            return child
    return None


def _find_group_with_children_of_type(navmesh_obj, sollum_type):
    """Find the empty parent (e.g. 'Portals', 'Points') that contains the items."""
    for child in navmesh_obj.children:
        for grandchild in child.children:
            if grandchild.sollum_type == sollum_type:
                return child
    return None


def _compress_centroid(centroid: Vector, poly_min: Vector, poly_max: Vector) -> tuple[int, int]:
    """Encode the polygon's XY centroid as a byte-pair, matching QOL/CodeWalker."""
    min_low = Vector((
        int(poly_min.x / POLY_BBOX_RESOLUTION) * POLY_BBOX_RESOLUTION,
        int(poly_min.y / POLY_BBOX_RESOLUTION) * POLY_BBOX_RESOLUTION,
        0.0,
    ))
    max_low = Vector((
        int(poly_max.x / POLY_BBOX_RESOLUTION) * POLY_BBOX_RESOLUTION,
        int(poly_max.y / POLY_BBOX_RESOLUTION) * POLY_BBOX_RESOLUTION,
        0.0,
    ))
    size = max_low - min_low

    cx = int((centroid.x - min_low.x) / size.x * 256) if size.x != 0.0 else 0
    cy = int((centroid.y - min_low.y) / size.y * 256) if size.y != 0.0 else 0
    return max(0, min(255, cx)), max(0, min(255, cy))


def _polygons_from_mesh(
    mesh,
    area_id: int,
    recompute_small_large: bool,
    recompute_edges: bool,
) -> tuple[list[NavPolygon], bool]:
    """Walk every face, repack flag bytes from FACE attrs, edges from EDGE attrs.

    When ``recompute_edges`` is True (the default), we ignore the stored
    adjacency for internal edges and look up the actual neighbouring polygon
    in the current mesh — this is what keeps the file consistent after a poly
    has been added or deleted. Boundary edges (no neighbour in this mesh) still
    fall back to the stored external reference so cross-cell stitching works.
    """
    if not has_navmesh_attributes(mesh):
        raise ValueError(
            "Navmesh polygon mesh is missing the .navmesh.* attribute layers — "
            "re-import the source .ynv.xml so they get created."
        )

    flag_data = [mesh.attributes[a.value].data for a in POLY_FLAG_ATTRS]
    cx_data = mesh.attributes[NavMeshAttr.POLY_CENTROID_X.value].data
    cy_data = mesh.attributes[NavMeshAttr.POLY_CENTROID_Y.value].data
    has_centroid = mesh.attributes[NavMeshAttr.POLY_HAS_CENTROID.value].data
    area_data = mesh.attributes[NavMeshAttr.EDGE_ADJACENT_AREA.value].data
    poly_data = mesh.attributes[NavMeshAttr.EDGE_ADJACENT_POLY.value].data

    out: list[NavPolygon] = []
    has_water = False

    # (v_min, v_max) → undirected edge index, for reading EDGE attrs.
    edge_index_by_pair: dict[tuple[int, int], int] = {}
    for edge in mesh.edges:
        v0, v1 = edge.vertices[0], edge.vertices[1]
        edge_index_by_pair[(min(v0, v1), max(v0, v1))] = edge.index

    # (v_min, v_max) → list of face indices that share this edge. Used to find
    # the other side of an internal edge.
    edge_to_faces: dict[tuple[int, int], list[int]] = {}
    for face in mesh.polygons:
        n = len(face.vertices)
        for i in range(n):
            v0 = face.vertices[i]
            v1 = face.vertices[(i + 1) % n]
            edge_to_faces.setdefault((min(v0, v1), max(v0, v1)), []).append(face.index)

    for face in mesh.polygons:
        verts = [Vector(mesh.vertices[v].co) for v in face.vertices]
        if len(verts) < 3:
            continue  # Blender shouldn't have these, but be defensive

        f0 = flag_data[0][face.index].value & 0xFF
        f1 = flag_data[1][face.index].value & 0xFF
        f2 = flag_data[2][face.index].value & 0xFF
        f3 = flag_data[3][face.index].value & 0xFF
        f4 = flag_data[4][face.index].value & 0xFF

        if recompute_small_large:
            f0 &= ~(FLAG0_SMALL | FLAG0_LARGE)
            area = face.area
            if area < POLY_SMALL_MAX_AREA:
                f0 |= FLAG0_SMALL
            elif area > POLY_LARGE_MIN_AREA:
                f0 |= FLAG0_LARGE

        if f0 & FLAG0_WATER:
            has_water = True

        if has_centroid[face.index].value:
            cx = cx_data[face.index].value & 0xFF
            cy = cy_data[face.index].value & 0xFF
        else:
            poly_min = Vector((
                min(v.x for v in verts),
                min(v.y for v in verts),
                min(v.z for v in verts),
            ))
            poly_max = Vector((
                max(v.x for v in verts),
                max(v.y for v in verts),
                max(v.z for v in verts),
            ))
            centroid = Vector(face.center)
            cx, cy = _compress_centroid(centroid, poly_min, poly_max)

        n = len(face.vertices)
        edge_list = []
        for i in range(n):
            v0 = face.vertices[i]
            v1 = face.vertices[(i + 1) % n]
            key = (min(v0, v1), max(v0, v1))

            neighbour_idx = None
            if recompute_edges:
                neighbours = [f for f in edge_to_faces.get(key, ()) if f != face.index]
                if neighbours:
                    neighbour_idx = neighbours[0]

            if neighbour_idx is not None:
                edge_list.append((area_id & 0xFFFF, neighbour_idx & 0xFFFF))
                continue

            # No internal neighbour (boundary edge, OR recompute disabled) —
            # fall back to whatever was stored for this edge.
            edge_idx = edge_index_by_pair.get(key)
            if edge_idx is None:
                edge_list.append((ADJACENT_NONE, ADJACENT_NONE))
                continue
            stored_area = area_data[edge_idx].value & 0xFFFF
            stored_poly = poly_data[edge_idx].value & 0xFFFF
            edge_list.append((stored_area, stored_poly))

        poly_xml = NavPolygon()
        poly_xml.vertices = verts
        poly_xml.flags = format_flags_str(f0, f1, f2, f3, cx, cy, f4, include_f4=False)
        poly_xml.edges = format_edges_str(edge_list)
        out.append(poly_xml)

    return out, has_water


def _portal_from_obj(portal_obj) -> NavPortal:
    props = portal_obj.sz_nav_portal
    from_child = next((c for c in portal_obj.children if c.name.startswith("from")), None)
    to_child = next((c for c in portal_obj.children if c.name.startswith("to")), None)

    p = NavPortal()
    p.type = int(props.portal_type)
    p.angle = float(props.angle)
    p.poly_from = int(props.poly_from)
    p.poly_to = int(props.poly_to)
    p.position_from = Vector(from_child.matrix_world.translation) if from_child else Vector(portal_obj.location)
    p.position_to = Vector(to_child.matrix_world.translation) if to_child else Vector(portal_obj.location)
    return p


def _point_from_obj(point_obj) -> NavPoint:
    p = NavPoint()
    p.type = int(point_obj.sz_nav_point.point_type)
    p.angle = float(point_obj.rotation_euler.z)
    p.position = Vector(point_obj.matrix_world.translation)
    return p


def navmesh_from_object(navmesh_obj) -> Optional[Navmesh]:
    """Build the in-memory CWXML object for ``navmesh_obj``."""
    if navmesh_obj.sollum_type != SollumType.NAVMESH:
        logger.error(f"'{navmesh_obj.name}' is not a NAVMESH root object.")
        return None

    polymesh = _find_polymesh(navmesh_obj)
    if polymesh is None:
        logger.error(f"'{navmesh_obj.name}' has no NAVMESH_POLY_MESH child.")
        return None

    props = navmesh_obj.sz_navmesh
    nav = Navmesh()
    nav.area_id = int(props.area_id)

    polygons, has_water = _polygons_from_mesh(
        polymesh.data,
        int(props.area_id),
        props.auto_recompute_small_large,
        props.auto_recompute_edges,
    )
    nav.polygons = polygons

    portals_group = _find_group_with_children_of_type(navmesh_obj, SollumType.NAVMESH_PORTAL)
    if portals_group is not None:
        for portal_obj in portals_group.children:
            if portal_obj.sollum_type == SollumType.NAVMESH_PORTAL:
                nav.portals.append(_portal_from_obj(portal_obj))

    points_group = _find_group_with_children_of_type(navmesh_obj, SollumType.NAVMESH_POINT)
    if points_group is not None:
        for point_obj in points_group.children:
            if point_obj.sollum_type == SollumType.NAVMESH_POINT:
                nav.points.append(_point_from_obj(point_obj))

    # Bounding box
    if props.auto_bb and nav.polygons:
        all_verts = [v for poly in nav.polygons for v in poly.vertices]
        bb_min = Vector((min(v[0] for v in all_verts),
                         min(v[1] for v in all_verts),
                         min(v[2] for v in all_verts)))
        bb_max = Vector((max(v[0] for v in all_verts),
                         max(v[1] for v in all_verts),
                         max(v[2] for v in all_verts)))
    else:
        bb_min = Vector(props.bb_min)
        bb_max = Vector(props.bb_max)
    nav.bb_min = bb_min
    nav.bb_max = bb_max
    nav.bb_size = bb_max - bb_min

    # Content flags. Honor whatever the user has set, but ensure Polygons/Portals
    # are correctly reflected.
    flags = [f.strip() for f in (props.content_flags or "").split(",") if f.strip()]
    if "Polygons" not in flags and nav.polygons:
        flags.append("Polygons")
    if nav.portals:
        if "Portals" not in flags:
            flags.append("Portals")
    else:
        flags = [f for f in flags if f != "Portals"]
    if has_water and "Unknown8" not in flags:
        flags.append("Unknown8")
    nav.content_flags = ", ".join(flags) if flags else "Polygons"

    return nav


def export_ynv(navmesh_obj, filepath: str) -> bool:
    nav = navmesh_from_object(navmesh_obj)
    if nav is None:
        return False
    YNV.write_xml(nav, filepath)
    return True
