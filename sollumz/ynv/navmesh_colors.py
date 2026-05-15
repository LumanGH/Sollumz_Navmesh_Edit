"""Map navmesh polygon flag bytes to an RGBA color, in one place.

Used by:
  * the polygon FLOAT_COLOR attribute filled at import time so Solid mode
    viewport shading shows the categorization without a material preview;
  * the shader material's fallback Attribute node;
  * the "Refresh Colors" operator triggered after a flag edit.
"""
from .navmesh_attributes import (
    FLAG0_FOOTPATH,
    FLAG0_STEEP_SLOPE,
    FLAG0_UNDERGROUND,
    FLAG0_WATER,
    FLAG1_HAS_PATH_NODE,
    FLAG1_INTERACTION_UNK,
    FLAG1_INTERIOR,
    FLAG2_CELL_EDGE,
    FLAG2_FLAT_GROUND,
    FLAG2_ROAD,
    FLAG2_SHALLOW_WATER,
    FLAG2_TRAIN_TRACK,
    FLAG2_UNK0,
)


# Layered look: higher entries override lower ones when multiple bits are set
# on the same polygon. Tweak here once and both viewport + shader follow.
_BASE_COLOR = (0.55, 0.55, 0.55, 1.0)  # neutral grey (no flags / generic walkable)

_FLAG0_LAYERS = (
    (FLAG0_FOOTPATH,    (0.20, 0.65, 0.20, 1.0)),  # footpath -> green
    (FLAG0_UNDERGROUND, (0.30, 0.45, 0.55, 1.0)),  # underground -> slate
    (FLAG0_STEEP_SLOPE, (0.65, 0.20, 0.20, 1.0)),  # steep -> red
    (FLAG0_WATER,       (0.15, 0.40, 0.85, 1.0)),  # water -> blue
)
_FLAG1_LAYERS = (
    (FLAG1_HAS_PATH_NODE,   (0.85, 0.55, 0.15, 1.0)),  # has path node -> amber
    (FLAG1_INTERIOR,        (0.70, 0.65, 0.20, 1.0)),  # interior -> mustard
    (FLAG1_INTERACTION_UNK, (0.35, 0.35, 0.35, 1.0)),  # interaction unk -> dark grey
)
_FLAG2_LAYERS = (
    (FLAG2_FLAT_GROUND,   (0.55, 0.55, 0.55, 1.0)),  # flat ground -> grey (kept neutral)
    (FLAG2_ROAD,          (0.80, 0.45, 0.10, 1.0)),  # road -> orange
    (FLAG2_TRAIN_TRACK,   (0.45, 0.10, 0.55, 1.0)),  # train track -> purple
    (FLAG2_SHALLOW_WATER, (0.30, 0.65, 0.85, 1.0)),  # shallow water -> teal
    (FLAG2_CELL_EDGE,     (0.85, 0.85, 0.15, 1.0)),  # cell edge -> yellow
    (FLAG2_UNK0,          (0.95, 0.30, 0.65, 1.0)),  # unk0 (don't delete!) -> pink
)


def flags_to_color(flag0: int, flag1: int, flag2: int) -> tuple[float, float, float, float]:
    """Return a Linear RGBA color for the given polygon flag bytes."""
    color = _BASE_COLOR
    for mask, c in _FLAG0_LAYERS:
        if flag0 & mask:
            color = c
    for mask, c in _FLAG1_LAYERS:
        if flag1 & mask:
            color = c
    for mask, c in _FLAG2_LAYERS:
        if flag2 & mask:
            color = c
    return color
