"""Ways of dividing a polygon, ported from building/Cutter.hx."""

import math

from .geometry import Point, Polygon, distance, interpolate, min_by


def bisect(poly, vertex, ratio=0.5, angle=0.0, gap=0.0):
    following = poly.next(vertex)
    p1 = interpolate(vertex, following, ratio)
    d = following.subtract(vertex)

    cos_b = math.cos(angle)
    sin_b = math.sin(angle)
    vx = d.x * cos_b - d.y * sin_b
    vy = d.y * cos_b + d.x * sin_b
    p2 = Point(p1.x - vy, p1.y + vx)

    return poly.cut(p1, p2, gap)


def radial(poly, center=None, gap=0.0):
    if center is None:
        center = poly.centroid

    sectors = []
    for v0, v1 in poly.edges():
        sector = Polygon([center, v0, v1])
        if gap > 0:
            sector = sector.shrink([gap / 2, 0, gap / 2])
        sectors.append(sector)
    return sectors


def semi_radial(poly, center=None, gap=0.0):
    if center is None:
        centroid = poly.centroid
        center = min_by(poly, lambda v: distance(v, centroid))

    gap /= 2

    sectors = []
    for v0, v1 in poly.edges():
        if v0 is center or v1 is center:
            continue
        sector = Polygon([center, v0, v1])
        if gap > 0:
            sector = sector.shrink([
                gap if poly.find_edge(center, v0) == -1 else 0,
                0,
                gap if poly.find_edge(v1, center) == -1 else 0,
            ])
        sectors.append(sector)
    return sectors


def ring(poly, thickness):
    slices = []
    for v1, v2 in poly.edges():
        v = v2.subtract(v1)
        n = v.rotate90().norm(thickness)
        slices.append((v.length, v1.add(n), v2.add(n)))

    # Short sides are sliced first.
    slices.sort(key=lambda s: s[0])

    peel = []
    p = poly
    for _, p1, p2 in slices:
        halves = p.cut(p1, p2)
        p = halves[0]
        if len(halves) == 2:
            peel.append(halves[1])
    return peel
