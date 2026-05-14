"""Import a CodeWalker .ynv.xml into a Blender NAVMESH object hierarchy."""
import os

import bpy
from mathutils import Vector

from ..sollumz_properties import SOLLUMZ_UI_NAMES, SollumType
from ..tools.meshhelper import create_box
from .cwxml_navmesh import YNV, Navmesh
from .navmesh_attributes import (
    ADJACENT_NONE,
    EDGE_ATTRS,
    NavMeshAttr,
    POLY_FLAG_ATTRS,
    ensure_navmesh_attributes,
    parse_edges_str,
    parse_flags_str,
)
from .navmesh_material import get_navmesh_material


def _polygons_to_obj(name: str, polygons) -> bpy.types.Object:
    """Build the mesh that holds the navmesh polygons + flag/edge attributes.

    We deliberately do NOT share vertices between polygons. Edges are 1:1 with
    polygon corners — that lets us store the per-edge ``area:idx`` adjacency
    on the EDGE domain without ambiguity over which polygon claims an edge.
    """
    vertices: list[Vector] = []
    faces: list[list[int]] = []
    face_flags: list[tuple[int, int, int, int, int]] = []  # f0..f4 per face
    face_centroid: list[tuple[int, int]] = []  # (cx, cy) bytes preserved verbatim
    edge_adj: list[tuple[int, int]] = []  # (area, poly_idx) per emitted edge

    for poly in polygons:
        f0, f1, f2, f3, cx, cy, f4 = parse_flags_str(poly.flags)
        edges = parse_edges_str(poly.edges)

        verts = list(poly.vertices)
        if not verts:
            continue

        face_idx = []
        for vi, v in enumerate(verts):
            face_idx.append(len(vertices))
            vertices.append(Vector((float(v[0]), float(v[1]), float(v[2]))))
            if vi < len(edges):
                edge_adj.append(edges[vi])
            else:
                edge_adj.append((ADJACENT_NONE, ADJACENT_NONE))

        if len(face_idx) < 3:
            # Degenerate polygon (DLC stitch, etc) — drop the geometry but skip
            # silently. A 1- or 2-vertex face cannot be created in Blender.
            del vertices[-len(verts):]
            del edge_adj[-len(verts):]
            continue

        faces.append(face_idx)
        face_flags.append((f0, f1, f2, f3, f4))
        face_centroid.append((cx, cy))

    mesh = bpy.data.meshes.new(SOLLUMZ_UI_NAMES[SollumType.NAVMESH_POLY_MESH])
    mesh.from_pydata(vertices, [], faces)

    ensure_navmesh_attributes(mesh)

    # FACE-domain flag attrs
    for col, attr in enumerate(POLY_FLAG_ATTRS):
        data = mesh.attributes[attr.value].data
        for i, flags in enumerate(face_flags):
            data[i].value = flags[col]

    # Centroid bytes — preserved verbatim so the export round-trips byte-perfect.
    cx_data = mesh.attributes[NavMeshAttr.POLY_CENTROID_X.value].data
    cy_data = mesh.attributes[NavMeshAttr.POLY_CENTROID_Y.value].data
    has_data = mesh.attributes[NavMeshAttr.POLY_HAS_CENTROID.value].data
    for i, (cx, cy) in enumerate(face_centroid):
        cx_data[i].value = cx
        cy_data[i].value = cy
        has_data[i].value = 1

    # EDGE-domain adjacency. Blender re-orders edges versus the order we fed in
    # to ``from_pydata``, so we map them back via (v_start, v_end) pairs.
    edge_lookup: dict[tuple[int, int], tuple[int, int]] = {}
    cursor = 0
    for face_verts in faces:
        n = len(face_verts)
        for i in range(n):
            v0 = face_verts[i]
            v1 = face_verts[(i + 1) % n]
            edge_lookup[(min(v0, v1), max(v0, v1))] = edge_adj[cursor]
            cursor += 1

    area_data = mesh.attributes[NavMeshAttr.EDGE_ADJACENT_AREA.value].data
    poly_data = mesh.attributes[NavMeshAttr.EDGE_ADJACENT_POLY.value].data
    for edge in mesh.edges:
        key = (min(edge.vertices[0], edge.vertices[1]),
               max(edge.vertices[0], edge.vertices[1]))
        area, poly_idx = edge_lookup.get(key, (ADJACENT_NONE, ADJACENT_NONE))
        area_data[edge.index].value = area
        poly_data[edge.index].value = poly_idx

    mesh.materials.append(get_navmesh_material())

    obj = bpy.data.objects.new(name, mesh)
    obj.sollum_type = SollumType.NAVMESH_POLY_MESH
    return obj


def _portals_to_obj(portals) -> bpy.types.Object:
    pobj = bpy.data.objects.new("Portals", None)
    pobj.empty_display_size = 0

    for idx, portal in enumerate(portals):
        from_mesh = bpy.data.meshes.new("from")
        create_box(from_mesh, 0.5)
        from_obj = bpy.data.objects.new("from", from_mesh)
        from_obj.location = portal.position_from

        to_mesh = bpy.data.meshes.new("to")
        create_box(to_mesh, 0.5)
        to_obj = bpy.data.objects.new("to", to_mesh)
        to_obj.location = portal.position_to

        portal_obj = bpy.data.objects.new(
            f"{SOLLUMZ_UI_NAMES[SollumType.NAVMESH_PORTAL]} {idx}", None,
        )
        portal_obj.sollum_type = SollumType.NAVMESH_PORTAL
        portal_obj.empty_display_size = 0
        portal_obj.sz_nav_portal.portal_type = int(portal.type)
        portal_obj.sz_nav_portal.angle = float(portal.angle)
        portal_obj.sz_nav_portal.poly_from = int(portal.poly_from)
        portal_obj.sz_nav_portal.poly_to = int(portal.poly_to)
        from_obj.parent = portal_obj
        to_obj.parent = portal_obj
        portal_obj.parent = pobj

        bpy.context.collection.objects.link(from_obj)
        bpy.context.collection.objects.link(to_obj)
        bpy.context.collection.objects.link(portal_obj)

    return pobj


def _points_to_obj(points) -> bpy.types.Object:
    pobj = bpy.data.objects.new("Points", None)
    pobj.empty_display_size = 0

    for idx, point in enumerate(points):
        mesh = bpy.data.meshes.new(SOLLUMZ_UI_NAMES[SollumType.NAVMESH_POINT])
        create_box(mesh, 0.5)
        obj = bpy.data.objects.new(
            f"{SOLLUMZ_UI_NAMES[SollumType.NAVMESH_POINT]} {idx}", mesh,
        )
        obj.sollum_type = SollumType.NAVMESH_POINT
        obj.location = point.position
        obj.rotation_euler = (0, 0, float(point.angle))
        obj.sz_nav_point.point_type = int(point.type)
        obj.parent = pobj
        bpy.context.collection.objects.link(obj)

    return pobj


def _navmesh_to_obj(navmesh: Navmesh, filepath: str) -> bpy.types.Object:
    name = os.path.basename(filepath.replace(YNV.file_extension, ""))

    root = bpy.data.objects.new(name, None)
    root.sollum_type = SollumType.NAVMESH
    root.empty_display_size = 0
    root.sz_navmesh.area_id = int(navmesh.area_id) if navmesh.area_id is not None else 0
    root.sz_navmesh.content_flags = navmesh.content_flags or ""
    if navmesh.bb_min is not None:
        root.sz_navmesh.bb_min = (float(navmesh.bb_min[0]),
                                  float(navmesh.bb_min[1]),
                                  float(navmesh.bb_min[2]))
    if navmesh.bb_max is not None:
        root.sz_navmesh.bb_max = (float(navmesh.bb_max[0]),
                                  float(navmesh.bb_max[1]),
                                  float(navmesh.bb_max[2]))
    bpy.context.collection.objects.link(root)

    poly_obj = _polygons_to_obj(name + "_polys", navmesh.polygons)
    poly_obj.parent = root
    bpy.context.collection.objects.link(poly_obj)

    portals_obj = _portals_to_obj(navmesh.portals)
    portals_obj.parent = root
    bpy.context.collection.objects.link(portals_obj)

    points_obj = _points_to_obj(navmesh.points)
    points_obj.parent = root
    bpy.context.collection.objects.link(points_obj)

    return root


def import_ynv(filepath: str) -> bpy.types.Object:
    ynv_xml = YNV.from_xml_file(filepath)
    return _navmesh_to_obj(ynv_xml, filepath)
