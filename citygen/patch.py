"""A patch of land, ported from building/Patch.hx."""

from .geometry import GenerationError, Polygon, index_of


class Patch:

    def __init__(self, vertices):
        self.shape = Polygon(vertices)
        self.ward = None
        self.within_walls = False
        self.within_city = False

    @staticmethod
    def from_region(region):
        return Patch([triangle.c for triangle in region.vertices])


def find_circumference(wards):
    """The outline around a group of adjoining patches."""
    if not wards:
        return Polygon()
    if len(wards) == 1:
        return Polygon(wards[0].shape)

    a = []
    b = []
    for w1 in wards:
        for v0, v1 in w1.shape.edges():
            if all(w2.shape.find_edge(v1, v0) == -1 for w2 in wards):
                a.append(v0)
                b.append(v1)

    result = Polygon()
    index = 0
    for _ in range(len(a) + 1):
        result.append(a[index])
        index = index_of(a, b[index])
        if index == 0:
            return result
        if index == -1:
            break
    raise GenerationError("The outline of the wards didn't close")
