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
    EDGE_ADJACENT_AREA = ".navmesh.edge_adjacent_area"
    EDGE_ADJACENT_POLY = ".navmesh.edge_adjacent_poly"

    @property
    def blender_type(self) -> str:
        return "INT"

    @property
    def domain(self) -> str:
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
        if attr.value not in mesh.attributes:
            mesh.attributes.new(attr.value, attr.blender_type, attr.domain)


def has_navmesh_attributes(mesh: Mesh) -> bool:
    return all(attr.value in mesh.attributes for attr in NavMeshAttr)


# --- flag-bit constants (per CodeWalker 30+, see QOL fork's notes) -----------
# flag0
FLAG0_SMALL = 1            # area < 2.0 (computed on export)
FLAG0_LARGE = 2            # area > 40.0 (computed on export)
FLAG0_PAVEMENT = 4
FLAG0_IN_SHELTER = 8
FLAG0_TOO_STEEP = 64
FLAG0_WATER = 128

# flag1: low nibble = audio properties, high bits = misc
FLAG1_AUDIO_MASK = 0x0F
FLAG1_NEAR_CAR_NODE = 32
FLAG1_INTERIOR = 64
FLAG1_ISOLATED = 128

# flag2: low bits = misc, high 3 bits = ped density
FLAG2_NETWORK_SPAWN = 1
FLAG2_ROAD = 2
FLAG2_LIES_ALONG_EDGE = 4
FLAG2_TRAIN_TRACK = 8
FLAG2_SHALLOW_WATER = 16
FLAG2_PED_DENSITY_MASK = 0xE0
FLAG2_PED_DENSITY_SHIFT = 5

# flag3: cover directions, 8 bits — one bit per 45-degree direction
# (bit 0: +Y, bit 1: -X+Y, bit 2: -X, bit 3: -X-Y, bit 4: -Y,
#  bit 5: +X-Y, bit 6: +X, bit 7: +X+Y)

# flag4: only bit 0 used = is DLC stitch poly


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
