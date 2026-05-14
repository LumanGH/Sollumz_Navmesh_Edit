"""Local CWXML wrapper for GTA V .ynv navmesh.

The shipped szio.gta5.cwxml.navmesh has two issues that prevent writing:
  1. NavPolygonVertices doesn't override ``to_xml()`` so the default list
     serializer tries to call ``Vector.to_xml()`` and crashes.
  2. NavPortal.type uses the tag ``Value`` but CodeWalker writes ``Type``.

Both are fixed here. The classes match the on-disk format used by
CodeWalker 30+ (the same format used in the user's navmesh[123][99].ynv.xml).
"""
from xml.etree import ElementTree as ET

import numpy as np

from szio.types import Vector
from szio.xml import (
    ElementTree,
    ListProperty,
    TextProperty,
    ValueProperty,
    VectorProperty,
)


def fmt_float(v) -> str:
    """Format a coordinate the way CodeWalker does: float32 round-trip, no trailing zeros.

    The on-disk file holds positions as 32-bit floats, so we cast through
    float32 before formatting; otherwise we'd see double-precision noise like
    ``244.00091552734375``. The ``.9g`` precision is enough to round-trip every
    float32 value uniquely.
    """
    f32 = float(np.float32(float(v)))
    if f32 == int(f32):
        return str(int(f32))
    return f"{f32:.9g}"


class NavPolygonVertices(ListProperty):
    list_type = Vector
    tag_name = "Vertices"

    def __init__(self, tag_name=None, value=None):
        super().__init__(tag_name=tag_name, value=value)

    @classmethod
    def from_xml(cls, element: ET.Element):
        new = cls()
        verts = []
        if element.text:
            for line in element.text.strip().split("\n"):
                nums = line.strip().split(",")
                if len(nums) != 3:
                    continue
                verts.append(Vector((float(nums[0]), float(nums[1]), float(nums[2]))))
        new.value = verts
        return new

    def to_xml(self):
        if not self.value:
            return None
        elem = ET.Element(self.tag_name)
        lines = [f"{fmt_float(v[0])}, {fmt_float(v[1])}, {fmt_float(v[2])}" for v in self.value]
        elem.text = "\n" + "\n".join(lines) + "\n"
        return elem


class NavPoint(ElementTree):
    tag_name = "Item"

    def __init__(self):
        super().__init__()
        self.type = ValueProperty("Type")
        self.angle = ValueProperty("Angle")
        self.position = VectorProperty("Position")


class NavPointList(ListProperty):
    list_type = NavPoint
    tag_name = "Points"


class NavPortal(ElementTree):
    tag_name = "Item"

    def __init__(self):
        super().__init__()
        self.type = ValueProperty("Type")
        self.angle = ValueProperty("Angle")
        self.poly_from = ValueProperty("PolyFrom")
        self.poly_to = ValueProperty("PolyTo")
        self.position_from = VectorProperty("PositionFrom")
        self.position_to = VectorProperty("PositionTo")


class NavPortalList(ListProperty):
    list_type = NavPortal
    tag_name = "Portals"


class NavPolygon(ElementTree):
    tag_name = "Item"

    def __init__(self):
        super().__init__()
        self.flags = TextProperty("Flags")
        self.vertices = NavPolygonVertices("Vertices")
        self.edges = TextProperty("Edges")


class NavPolygonList(ListProperty):
    list_type = NavPolygon
    tag_name = "Polygons"


class Navmesh(ElementTree):
    tag_name = "NavMesh"

    def __init__(self):
        super().__init__()
        self.content_flags = TextProperty("ContentFlags")
        self.area_id = ValueProperty("AreaID")
        self.bb_min = VectorProperty("BBMin")
        self.bb_max = VectorProperty("BBMax")
        self.bb_size = VectorProperty("BBSize")
        self.polygons = NavPolygonList()
        self.portals = NavPortalList()
        self.points = NavPointList()


class YNV:
    file_extension = ".ynv.xml"

    @staticmethod
    def from_xml_file(filepath):
        return Navmesh.from_xml_file(filepath)

    @staticmethod
    def write_xml(nav, filepath):
        return nav.write_xml(filepath)
