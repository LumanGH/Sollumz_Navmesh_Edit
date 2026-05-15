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
    FLAG0_WATER,
    NavMeshAttr,
    POLY_FLAG_ATTRS,
    format_edges_str,
    format_flags_str,
    has_navmesh_attributes,
)

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


_EDGE_POS_EPS = 3  # round vertex coordinates to this many decimals for matching


def _build_boundary_edge_index(mesh) -> dict[tuple, list[int]]:
    """Index every polygon edge by its rounded XYZ positions.

    The returned dict maps ``(sorted_pos_a, sorted_pos_b)`` to the list of
    polygon indices that own that edge in ``mesh``. We round to
    ``_EDGE_POS_EPS`` decimals so float noise between cells doesn't break the
    match — CodeWalker stores positions at ~1mm precision in the source XML.
    """
    idx: dict[tuple, list[int]] = {}
    verts = mesh.vertices
    for face in mesh.polygons:
        n = len(face.vertices)
        for i in range(n):
            v0 = face.vertices[i]
            v1 = face.vertices[(i + 1) % n]
            p0 = tuple(round(float(c), _EDGE_POS_EPS) for c in verts[v0].co)
            p1 = tuple(round(float(c), _EDGE_POS_EPS) for c in verts[v1].co)
            key = (p0, p1) if p0 < p1 else (p1, p0)
            idx.setdefault(key, []).append(face.index)
    return idx


def _polygons_from_mesh(
    mesh,
    area_id: int,
    recompute_small_large: bool,
    recompute_edges: bool,
    sibling_indices: dict[int, dict[tuple, list[int]]] | None = None,
) -> tuple[list[NavPolygon], bool]:
    """Walk every face, repack flag bytes from FACE attrs, edges from EDGE attrs.

    When ``recompute_edges`` is True (the default), we ignore the stored
    adjacency for internal edges and look up the actual neighbouring polygon
    in the current mesh — this is what keeps the file consistent after a poly
    has been added or deleted.

    For boundary edges (no neighbour in this mesh):
      * If a sibling navmesh with that ``area_id`` was provided in
        ``sibling_indices``, we look up the edge by rounded XYZ positions to
        find the new poly index there. If the polygon was deleted/moved in the
        sibling, we emit ``16383:16383`` (no neighbour) — which is safe and
        won't crash the game.
      * Otherwise we keep whatever was stored in the EDGE attrs (lets stitching
        survive single-cell edits where adjacent cells aren't being touched).
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

        # NOTE: ``recompute_small_large`` used to mask flag0 bits 0/1 here as
        # if they were computed Small/Large markers. They are actually
        # CodeWalker's AvoidUnk0/AvoidUnk1 — user-set avoidance hints. We now
        # leave them alone; the parameter is accepted for API compatibility
        # but intentionally has no effect.
        _ = recompute_small_large

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

            # Boundary edge. Read the stored adjacency first — it tells us
            # which sibling cell this edge used to point at.
            edge_idx = edge_index_by_pair.get(key)
            stored_area = ADJACENT_NONE
            stored_poly = ADJACENT_NONE
            if edge_idx is not None:
                stored_area = area_data[edge_idx].value & 0xFFFF
                stored_poly = poly_data[edge_idx].value & 0xFFFF

            # CRITICAL: when recompute_edges is on and the stored neighbour
            # lives in OUR area_id, the recompute step above already searched
            # the current mesh and found nothing — so the saved poly index is
            # stale (the neighbour was deleted, or every face that used to use
            # this edge is gone). Emitting the stale index crashes the game.
            if recompute_edges and stored_area == area_id:
                edge_list.append((ADJACENT_NONE, ADJACENT_NONE))
                continue

            # If the sibling cell is being exported alongside us, look up the
            # edge by world-space vertex positions and emit the sibling's
            # current poly index. A missing match means the sibling polygon
            # was deleted/moved — emit ADJACENT_NONE so the game gracefully
            # treats this as a dead end instead of crashing on a stale index.
            if (recompute_edges
                    and sibling_indices is not None
                    and stored_area != ADJACENT_NONE
                    and stored_area in sibling_indices):
                p0 = tuple(round(float(c), _EDGE_POS_EPS) for c in mesh.vertices[v0].co)
                p1 = tuple(round(float(c), _EDGE_POS_EPS) for c in mesh.vertices[v1].co)
                pos_key = (p0, p1) if p0 < p1 else (p1, p0)
                hits = sibling_indices[stored_area].get(pos_key, ())
                if hits:
                    edge_list.append((stored_area, hits[0] & 0xFFFF))
                else:
                    edge_list.append((ADJACENT_NONE, ADJACENT_NONE))
                continue

            edge_list.append((stored_area, stored_poly))

        poly_xml = NavPolygon()
        poly_xml.vertices = verts
        poly_xml.flags = format_flags_str(f0, f1, f2, f3, cx, cy, f4, include_f4=False)
        poly_xml.edges = format_edges_str(edge_list)
        out.append(poly_xml)

    return out, has_water


# Portal endpoints are expected to sit on their target polygon (~ground level).
# When the nearest polygon is farther than this threshold (m), it means the
# polygon the portal used to live on has been deleted — there's no sane
# replacement, so the portal must be dropped from the export.
PORTAL_REPAIR_MAX_DIST = 5.0

# NavPoints (spawn/cover) sit on top of a walkable polygon. To keep a point
# we require a polygon close in XY (the point should project onto the polygon)
# AND close enough in Z (the polygon shouldn't be 100m below — that means the
# user sank it and the point is orphaned). Both checks together are what
# stops peds from spawning at sunk areas and standing still.
NAVPOINT_KEEP_XY_DIST = 2.5
NAVPOINT_KEEP_Z_DIST = 8.0  # allows rooftop / elevated walkway points


def _find_nearest_poly_in_area(
    pos: Vector,
    own_polymesh,
    own_area_id: int,
    sibling_meshes: dict[int, "bpy.types.Mesh"],
    target_area: int,
) -> tuple[int, float]:
    """Return ``(poly_index, distance)`` for the closest polygon centre to ``pos``.

    Returns ``(-1, inf)`` when ``target_area`` is not present in the scene.
    """
    mesh = None
    if target_area == own_area_id:
        mesh = own_polymesh.data if own_polymesh is not None else None
    else:
        mesh = sibling_meshes.get(target_area)
    if mesh is None or len(mesh.polygons) == 0:
        return -1, float("inf")
    best_idx = -1
    best_dist_sq = float("inf")
    for face in mesh.polygons:
        c = face.center
        dx = c[0] - pos[0]
        dy = c[1] - pos[1]
        dz = c[2] - pos[2]
        d = dx * dx + dy * dy + dz * dz
        if d < best_dist_sq:
            best_dist_sq = d
            best_idx = face.index
    return best_idx, best_dist_sq ** 0.5


def _portal_from_obj(
    portal_obj,
    own_polymesh,
    own_area_id: int,
    sibling_meshes: dict[int, "bpy.types.Mesh"],
    repair_indices: bool,
) -> Optional[NavPortal]:
    """Build a NavPortal. Returns ``None`` when the portal's endpoint(s) no
    longer sit on any polygon — that means the underlying polygons were
    deleted and the portal is now orphaned. Keeping it would write a stale
    index that the game dereferences and crashes on, so we drop it instead.
    """
    props = portal_obj.sz_nav_portal
    from_child = next((c for c in portal_obj.children if c.name.startswith("from")), None)
    to_child = next((c for c in portal_obj.children if c.name.startswith("to")), None)

    pos_from = Vector(from_child.matrix_world.translation) if from_child else Vector(portal_obj.location)
    pos_to = Vector(to_child.matrix_world.translation) if to_child else Vector(portal_obj.location)

    poly_from = int(props.poly_from)
    poly_to = int(props.poly_to)

    if repair_indices:
        new_from, dist_from = _find_nearest_poly_in_area(
            pos_from, own_polymesh, own_area_id, sibling_meshes, own_area_id,
        )
        if new_from < 0 or dist_from > PORTAL_REPAIR_MAX_DIST:
            logger.warning(
                f"Dropping portal '{portal_obj.name}': PositionFrom is "
                f"{dist_from:.2f}m away from the nearest polygon (max "
                f"{PORTAL_REPAIR_MAX_DIST}m). The polygon it lived on was "
                f"probably deleted."
            )
            return None
        poly_from = new_from

        new_to, dist_to = _find_nearest_poly_in_area(
            pos_to, own_polymesh, own_area_id, sibling_meshes, own_area_id,
        )
        if new_to < 0 or dist_to > PORTAL_REPAIR_MAX_DIST:
            logger.warning(
                f"Dropping portal '{portal_obj.name}': PositionTo is "
                f"{dist_to:.2f}m away from the nearest polygon."
            )
            return None
        poly_to = new_to

    p = NavPortal()
    p.type = int(props.portal_type)
    p.angle = float(props.angle)
    p.position_from = pos_from
    p.position_to = pos_to
    p.poly_from = poly_from & 0xFFFF
    p.poly_to = poly_to & 0xFFFF
    return p


def _point_from_obj(point_obj) -> NavPoint:
    p = NavPoint()
    p.type = int(point_obj.sz_nav_point.point_type)
    p.angle = float(point_obj.rotation_euler.z)
    p.position = Vector(point_obj.matrix_world.translation)
    return p


def _collect_sibling_meshes(navmesh_obj, own_area_id: int) -> dict[int, "bpy.types.Mesh"]:
    """Return ``{area_id: Mesh}`` for every other NAVMESH in the scene."""
    import bpy as _bpy

    out: dict[int, "bpy.types.Mesh"] = {}
    for obj in _bpy.context.scene.objects:
        if obj is navmesh_obj or obj.sollum_type != SollumType.NAVMESH:
            continue
        polymesh = _find_polymesh(obj)
        if polymesh is None:
            continue
        sibling_area = int(obj.sz_navmesh.area_id)
        if sibling_area == own_area_id:
            continue
        out[sibling_area] = polymesh.data
    return out


def _collect_sibling_indices(navmesh_obj, own_area_id: int) -> dict[int, dict[tuple, list[int]]]:
    """Find every other NAVMESH in the scene and index its boundary edges.

    Result: ``{area_id: edge_pos_index}``. ``edge_pos_index`` maps a sorted
    pair of rounded XYZ positions to the polygon index(es) sharing that edge.
    """
    meshes = _collect_sibling_meshes(navmesh_obj, own_area_id)
    return {area: _build_boundary_edge_index(m) for area, m in meshes.items()}


def navmesh_from_object(
    navmesh_obj,
    sibling_indices: dict[int, dict[tuple, list[int]]] | None = None,
    sibling_meshes: dict[int, "bpy.types.Mesh"] | None = None,
) -> Optional[Navmesh]:
    """Build the in-memory CWXML object for ``navmesh_obj``.

    Pass ``sibling_indices`` (from :func:`_collect_sibling_indices`) when other
    cells are being exported in the same pass so cross-cell edge stitching can
    be repaired against their current geometry.

    ``sibling_meshes`` is the raw ``{area_id: Mesh}`` map; it powers the
    portal PolyFrom/PolyTo repair which needs polygon centres, not just edges.
    """
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
    own_area = int(props.area_id)

    if sibling_meshes is None:
        sibling_meshes = _collect_sibling_meshes(navmesh_obj, own_area)
    if sibling_indices is None:
        sibling_indices = {area: _build_boundary_edge_index(m)
                           for area, m in sibling_meshes.items()}

    polygons, has_water = _polygons_from_mesh(
        polymesh.data,
        own_area,
        props.auto_recompute_small_large,
        props.auto_recompute_edges,
        sibling_indices,
    )
    nav.polygons = polygons

    portals_group = _find_group_with_children_of_type(navmesh_obj, SollumType.NAVMESH_PORTAL)
    if portals_group is not None:
        for portal_obj in portals_group.children:
            if portal_obj.sollum_type == SollumType.NAVMESH_PORTAL:
                portal_xml = _portal_from_obj(
                    portal_obj,
                    polymesh,
                    own_area,
                    sibling_meshes,
                    props.auto_recompute_edges,
                )
                if portal_xml is not None:
                    nav.portals.append(portal_xml)

    points_group = _find_group_with_children_of_type(navmesh_obj, SollumType.NAVMESH_POINT)
    if points_group is not None:
        # For each point we need to know: is there a walkable polygon directly
        # under it? "Under" means close in XY AND close in Z. The Z check is
        # what catches sunk polygons — their XY centroid doesn't move when
        # we sink, so an XY-only filter would still find them as a valid
        # neighbour and the point would be kept (then the game spawns a ped
        # there and it stands still because the real walkable surface is
        # 100m below).
        poly_centroids = [(p.center[0], p.center[1], p.center[2])
                          for p in polymesh.data.polygons]

        def _has_polygon_under(px: float, py: float, pz: float) -> bool:
            for cx, cy, cz in poly_centroids:
                dx = cx - px
                dy = cy - py
                if (dx * dx + dy * dy) > (NAVPOINT_KEEP_XY_DIST * NAVPOINT_KEEP_XY_DIST):
                    continue
                if abs(cz - pz) <= NAVPOINT_KEEP_Z_DIST:
                    return True
            return False

        kept = dropped = 0
        for point_obj in points_group.children:
            if point_obj.sollum_type != SollumType.NAVMESH_POINT:
                continue
            if props.auto_recompute_edges and poly_centroids:
                pos = point_obj.matrix_world.translation
                if not _has_polygon_under(pos[0], pos[1], pos[2]):
                    dropped += 1
                    continue
            nav.points.append(_point_from_obj(point_obj))
            kept += 1
        if dropped:
            logger.info(
                f"Dropped {dropped} orphan NavPoint(s) (no polygon within "
                f"{NAVPOINT_KEEP_XY_DIST}m XY and {NAVPOINT_KEEP_Z_DIST}m Z) "
                f"— kept {kept}."
            )

    # Bounding box.
    # MAP navmeshes (area_id != STANDALONE) have BBMin/BBMax fixed to the
    # 150x150m grid-cell bounds. The game uses these to look up which file
    # to load per cell — if we shrink them after deleting interior polys,
    # the navmesh ends up in the wrong cell and the game crashes. So for
    # map navmeshes we ALWAYS keep the imported BB (only Z is updated to
    # actual polygon range). Standalone navmeshes (vehicles, interiors)
    # use the fitted bbox.
    from .properties import STANDALONE_AREA_ID
    is_standalone = int(props.area_id) == STANDALONE_AREA_ID
    if is_standalone and props.auto_bb and nav.polygons:
        all_verts = [v for poly in nav.polygons for v in poly.vertices]
        bb_min = Vector((min(v[0] for v in all_verts),
                         min(v[1] for v in all_verts),
                         min(v[2] for v in all_verts)))
        bb_max = Vector((max(v[0] for v in all_verts),
                         max(v[1] for v in all_verts),
                         max(v[2] for v in all_verts)))
    else:
        # Map navmesh: pin BBMin/BBMax to the imported values verbatim. We
        # USED to refit Z to actual polygon span, but that breaks the moment
        # the user sinks polygons (sunk verts at Z=-100m push BBMin.z to
        # -100m and the game crashes — it expects BB to roughly match the
        # original cell-volume the engine was loaded with). Sunk polys live
        # outside the BB, which is fine: they exist in the file for index
        # consistency but the broad-phase never picks them.
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


def export_ynv(navmesh_obj, filepath: str,
               sibling_indices: dict[int, dict[tuple, list[int]]] | None = None) -> bool:
    nav = navmesh_from_object(navmesh_obj, sibling_indices=sibling_indices)
    if nav is None:
        return False
    YNV.write_xml(nav, filepath)
    return True
