"""Voronoi regions by adding points to a triangulation, from geom/Voronoi.hx."""

import math
from functools import cmp_to_key

from .geometry import GenerationError, Point, distance, index_of, sign


class Triangle:
    """A triangle with its vertices in order, and its circumcircle."""

    __slots__ = ("p1", "p2", "p3", "c", "r", "cx", "cy", "split")

    def __init__(self, p1, p2, p3):
        s = ((p2.x - p1.x) * (p2.y + p1.y)
             + (p3.x - p2.x) * (p3.y + p2.y)
             + (p1.x - p3.x) * (p1.y + p3.y))
        self.p1 = p1
        self.p2 = p2 if s > 0 else p3
        self.p3 = p3 if s > 0 else p2

        # The original works this out with a slope, which is infinite for
        # some edges. This is the same circumcentre without that case.
        d = 2 * (p1.x * (p2.y - p3.y)
                 + p2.x * (p3.y - p1.y)
                 + p3.x * (p1.y - p2.y))
        if d == 0:
            raise GenerationError("Three points in a line")
        s1 = p1.x * p1.x + p1.y * p1.y
        s2 = p2.x * p2.x + p2.y * p2.y
        s3 = p3.x * p3.x + p3.y * p3.y
        self.c = Point(
            (s1 * (p2.y - p3.y) + s2 * (p3.y - p1.y) + s3 * (p1.y - p2.y)) / d,
            (s1 * (p3.x - p2.x) + s2 * (p1.x - p3.x) + s3 * (p2.x - p1.x)) / d,
        )
        self.r = distance(self.c, p1)
        # Kept as plain numbers too, for the search in add_point.
        self.cx = self.c.x
        self.cy = self.c.y
        self.split = False  # Set once add_point replaces it.

    def has_edge(self, a, b):
        return ((self.p1 is a and self.p2 is b)
                or (self.p2 is a and self.p3 is b)
                or (self.p3 is a and self.p1 is b))


class Region:
    """A seed point and the triangles around it, sorted by direction."""

    __slots__ = ("seed", "vertices")

    def __init__(self, seed, vertices):
        self.seed = seed
        self.vertices = sorted(vertices, key=cmp_to_key(self._compare_angles))

    def center(self):
        c = Point()
        for v in self.vertices:
            c.add_eq(v.c)
        c.scale_eq(1 / len(self.vertices))
        return c

    def _compare_angles(self, v1, v2):
        x1 = v1.c.x - self.seed.x
        y1 = v1.c.y - self.seed.y
        x2 = v2.c.x - self.seed.x
        y2 = v2.c.y - self.seed.y

        if x1 >= 0 and x2 < 0:
            return 1
        if x2 >= 0 and x1 < 0:
            return -1
        if x1 == 0 and x2 == 0:
            return 1 if y2 > y1 else -1
        return sign(x2 * y1 - x1 * y2)


class Voronoi:

    def __init__(self, minx, miny, maxx, maxy):
        c1 = Point(minx, miny)
        c2 = Point(minx, maxy)
        c3 = Point(maxx, miny)
        c4 = Point(maxx, maxy)
        self.frame = [c1, c2, c3, c4]
        self.points = [c1, c2, c3, c4]
        self.triangles = [Triangle(c1, c2, c3), Triangle(c2, c3, c4)]

    def add_point(self, p):
        # The same sum as distance(p, tr.c), without a call for each one.
        hypot = math.hypot
        px = p.x
        py = p.y
        to_split = [tr for tr in self.triangles
                    if hypot(px - tr.cx, py - tr.cy) < tr.r]
        if not to_split:
            return

        self.points.append(p)

        # The edges no other split triangle shares are the hole's outline.
        # Shared edges run in opposite directions.
        a = []
        b = []
        for t1 in to_split:
            e1 = e2 = e3 = True
            for t2 in to_split:
                if t2 is t1:
                    continue
                if e1 and t2.has_edge(t1.p2, t1.p1):
                    e1 = False
                if e2 and t2.has_edge(t1.p3, t1.p2):
                    e2 = False
                if e3 and t2.has_edge(t1.p1, t1.p3):
                    e3 = False
                if not (e1 or e2 or e3):
                    break
            if e1:
                a.append(t1.p1)
                b.append(t1.p2)
            if e2:
                a.append(t1.p2)
                b.append(t1.p3)
            if e3:
                a.append(t1.p3)
                b.append(t1.p1)

        index = 0
        for _ in range(len(a) + 1):
            self.triangles.append(Triangle(p, a[index], b[index]))
            index = index_of(a, b[index])
            if index == 0:
                break
            if index == -1:
                raise GenerationError("Triangulation outline didn't close")
        else:
            raise GenerationError("Triangulation outline didn't close")

        for tr in to_split:
            tr.split = True
        self.triangles = [tr for tr in self.triangles if not tr.split]

    def _is_real(self, tr):
        frame = self.frame
        return not any(
            f is tr.p1 or f is tr.p2 or f is tr.p3 for f in frame)

    def _regions(self):
        around = {id(p): [] for p in self.points}
        for tr in self.triangles:
            around[id(tr.p1)].append(tr)
            around[id(tr.p2)].append(tr)
            around[id(tr.p3)].append(tr)
        return around

    def partitioning(self):
        """The regions that don't touch the frame, in point order."""
        around = self._regions()
        result = []
        for p in self.points:
            triangles = around[id(p)]
            if triangles and all(self._is_real(tr) for tr in triangles):
                result.append(Region(p, triangles))
        return result

    @staticmethod
    def relax(voronoi, to_relax):
        """Rebuild with the chosen regions' seeds moved to their centres."""
        regions = voronoi.partitioning()
        chosen = set(map(id, to_relax))

        frame = set(map(id, voronoi.frame))
        points = [p for p in voronoi.points if id(p) not in frame]

        for region in regions:
            if id(region.seed) in chosen:
                points.remove(region.seed)
                points.append(region.center())

        return Voronoi.build(points)

    @staticmethod
    def build(vertices):
        minx = min(v.x for v in vertices)
        miny = min(v.y for v in vertices)
        maxx = max(v.x for v in vertices)
        maxy = max(v.y for v in vertices)
        dx = (maxx - minx) * 0.5
        dy = (maxy - miny) * 0.5

        voronoi = Voronoi(minx - dx / 2, miny - dy / 2,
                          maxx + dx / 2, maxy + dy / 2)
        for v in vertices:
            voronoi.add_point(v)
        return voronoi
