"""Mesh attribute layers for storing GTA V navmesh data on faces/edges.

Each flag byte is its own INT attribute on the FACE domain. We avoid bit-packing
two bytes into one 16-bit attribute so that values stay easy to inspect and so
that shader nodes can read them directly without bitshift logic.

Centroid bytes (slots 4 and 5 of the ``<Flags>`` element) are NOT stored — they
are recomputed from the polygon geometry on export.

Edge adjacency (``<Edges>`` element) is split across two EDGE-domain attributes:
  EDGE_ADJACENT_AREA  — area_id of the polygon on the other side (16383 = none)
  EDGE_ADJACENT_POLY  — its index within that area
"""
from enum import Enum

from bpy.types import Mesh


class NavMeshAttr(str, Enum):
    POLY_FLAG_0 = ".navmesh.poly_flag0"
    POLY_FLAG_1 = ".navmesh.poly_flag1"
    POLY_FLAG_2 = ".navmesh.poly_flag2"
    POLY_FLAG_3 = ".navmesh.poly_flag3"
    POLY_FLAG_4 = ".navmesh.poly_flag4"
    # CodeWalker writes two extra bytes inside <Flags> that look like a
    # compressed XY centroid. The encoding doesn't match a straightforward
    # bbox-relative quantization, so we just round-trip the bytes verbatim.
    POLY_CENTROID_X = ".navmesh.poly_centroid_x"
    POLY_CENTROID_Y = ".navmesh.poly_centroid_y"
    POLY_HAS_CENTROID = ".navmesh.poly_has_centroid"  # 0 = new poly, recompute
    # Float-RGBA color attribute on the CORNER (face-corner) domain.
    # CORNER is the only domain Blender's Solid viewport will sample for a
    # color attribute — FACE domain looks visually identical but the
    # viewport renderer skips it. Filled at import time from the flag
    # bytes; each face's loops all get the same color so it reads like a
    # per-face shading.
    POLY_COLOR = "navmesh_color"
    EDGE_ADJACENT_AREA = ".navmesh.edge_adjacent_area"
    EDGE_ADJACENT_POLY = ".navmesh.edge_adjacent_poly"

    @property
    def blender_type(self) -> str:
        if self == NavMeshAttr.POLY_COLOR:
            return "FLOAT_COLOR"
        return "INT"

    @property
    def domain(self) -> str:
        if self == NavMeshAttr.POLY_COLOR:
            return "CORNER"
        if self.name.startswith("POLY"):
            return "FACE"
        return "EDGE"


POLY_FLAG_ATTRS = (
    NavMeshAttr.POLY_FLAG_0,
    NavMeshAttr.POLY_FLAG_1,
    NavMeshAttr.POLY_FLAG_2,
    NavMeshAttr.POLY_FLAG_3,
    NavMeshAttr.POLY_FLAG_4,
)

EDGE_ATTRS = (
    NavMeshAttr.EDGE_ADJACENT_AREA,
    NavMeshAttr.EDGE_ADJACENT_POLY,
)


def ensure_navmesh_attributes(mesh: Mesh) -> None:
    for attr in NavMeshAttr:
        if attr.value in mesh.attributes:
            continue
        # Color attributes need to be created via ``color_attributes`` so the
        # viewport's Solid-mode renderer registers them as a sampling source.
        if attr.blender_type in {"FLOAT_COLOR", "BYTE_COLOR"}:
            mesh.color_attributes.new(attr.value, attr.blender_type, attr.domain)
        else:
            mesh.attributes.new(attr.value, attr.blender_type, attr.domain)


def has_navmesh_attributes(mesh: Mesh) -> bool:
    return all(attr.value in mesh.attributes for attr in NavMeshAttr)


# --- flag-bit constants (per CodeWalker UI; the QOL fork's names disagree
# in several places, e.g. it calls flag0 bits 0/1 "Small/Large" but they are
# really AvoidUnk0/1, and it claims flag1's low nibble is audio properties
# while CodeWalker labels it UndergroundUnk0..3) -----------------------------

# flag0
FLAG0_AVOID_UNK0 = 1
FLAG0_AVOID_UNK1 = 2
FLAG0_FOOTPATH = 4         # was 'Pavement' in QOL
FLAG0_UNDERGROUND = 8      # was 'InShelter' in QOL
# bits 4, 5 unused
FLAG0_STEEP_SLOPE = 64     # was 'TooSteepToWalkOn'
FLAG0_WATER = 128

# flag1
FLAG1_UNDERGROUND_UNK0 = 1
FLAG1_UNDERGROUND_UNK1 = 2
FLAG1_UNDERGROUND_UNK2 = 4
FLAG1_UNDERGROUND_UNK3 = 8
# bit 4 unused
FLAG1_HAS_PATH_NODE = 32   # was 'NearCarNode' in QOL
FLAG1_INTERIOR = 64
FLAG1_INTERACTION_UNK = 128  # NOT 'Isolated' as QOL suggested

# flag2 — bit numbers as labelled in the 3ds Max ONV tool (one bit per row).
# Deleting polygons that carry IsFlatGround (bit 0) crashes the game; the
# binary .ynv builds a separate spawn-spatial index over them. Strip the
# flag instead, or mark the polygon as Isolated.
FLAG2_FLAT_GROUND   = 1
FLAG2_ROAD          = 2
FLAG2_CELL_EDGE     = 4    # was 'LiesAlongEdge' in QOL
FLAG2_TRAIN_TRACK   = 8
FLAG2_SHALLOW_WATER = 16
FLAG2_FOOTPATH_UNK1 = 32
FLAG2_FOOTPATH_UNK2 = 64
FLAG2_FOOTPATH_MALL = 128

# flag3 — slope directions (one bit per 45° wedge, names from CodeWalker UI).
FLAG3_SLOPE_SOUTH = 1
FLAG3_SLOPE_SOUTH_EAST = 2
FLAG3_SLOPE_EAST = 4
FLAG3_SLOPE_NORTH_EAST = 8
FLAG3_SLOPE_NORTH = 16
FLAG3_SLOPE_NORTH_WEST = 32
FLAG3_SLOPE_WEST = 64
FLAG3_SLOPE_SOUTH_WEST = 128

# flag4: only bit 0 used = is DLC stitch poly

# --- back-compat aliases (operators / colors written before the rename) -----
# Keep these so external user scripts and any cached references in the
# extension build keep importing cleanly. Drop after a couple of releases.
FLAG0_PAVEMENT = FLAG0_FOOTPATH
FLAG0_IN_SHELTER = FLAG0_UNDERGROUND
FLAG0_TOO_STEEP = FLAG0_STEEP_SLOPE
FLAG0_SMALL = FLAG0_AVOID_UNK0
FLAG0_LARGE = FLAG0_AVOID_UNK1
FLAG1_NEAR_CAR_NODE = FLAG1_HAS_PATH_NODE
FLAG1_ISOLATED = FLAG1_INTERACTION_UNK
FLAG2_UNK0 = FLAG2_FLAT_GROUND           # legacy name during the rename
FLAG2_NETWORK_SPAWN = FLAG2_FLAT_GROUND  # legacy name from QOL fork
FLAG2_LIES_ALONG_EDGE = FLAG2_CELL_EDGE


# Adjacency: a 14-bit value of all 1s means "no neighbor"
ADJACENT_NONE = 16383


def parse_flags_str(flags_str: str) -> tuple[int, int, int, int, int, int, int]:
    """Parse the ``<Flags>`` text into (f0, f1, f2, f3, cx, cy, f4).

    CodeWalker writes 6 numbers for older formats (no f4) and 7 for newer
    (with f4). Missing values default to 0.
    """
    parts = (flags_str or "").split()
    nums = [int(p) for p in parts if p]
    while len(nums) < 7:
        nums.append(0)
    f0, f1, f2, f3, cx, cy, f4 = nums[:7]
    return f0, f1, f2, f3, cx, cy, f4


def format_flags_str(f0: int, f1: int, f2: int, f3: int, cx: int, cy: int, f4: int,
                     include_f4: bool = False) -> str:
    """Render the ``<Flags>`` text. f4 is only emitted when newer-format requested."""
    base = f"{f0 & 0xFF} {f1 & 0xFF} {f2 & 0xFF} {f3 & 0xFF} {cx & 0xFF} {cy & 0xFF}"
    if include_f4:
        return base + f" {f4 & 0xFF}"
    return base


def parse_edges_str(edges_str: str) -> list[tuple[int, int]]:
    """Parse the ``<Edges>`` text into a list of (area_id, poly_idx) per edge.

    Each line in the source XML looks like ``3341:303, 3341:303`` — two copies of
    the same area:idx pair. We only store the first; on export we re-emit both
    copies (CodeWalker always writes them as a pair).
    """
    result = []
    if not edges_str:
        return result
    for line in edges_str.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        first = line.split(",", 1)[0].strip()
        if ":" not in first:
            continue
        area_s, poly_s = first.split(":", 1)
        try:
            result.append((int(area_s), int(poly_s)))
        except ValueError:
            continue
    return result


def format_edges_str(edges: list[tuple[int, int]]) -> str:
    """Render the ``<Edges>`` text, emitting each pair twice as CodeWalker does."""
    return "\n".join(f"{a}:{p}, {a}:{p}" for a, p in edges)
