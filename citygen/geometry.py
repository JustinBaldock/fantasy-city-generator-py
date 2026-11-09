"""Points and polygons, ported from geom/GeomUtils.hx and geom/Polygon.hx.

Two things about the original shape this module.

Points are compared by identity. Wards share vertex objects, and moving a
vertex moves it in every ward that uses it, so Point has no __eq__, and
list.index and `in` find the very same object.

Haxe floats divide by zero without complaint, giving infinity or NaN, and the
original relies on that. fdiv does the same where it matters. Everywhere else
a bad shape raises an error here and the model tries again.
"""

import math


class GenerationError(Exception):
    """This attempt at a city failed. The model starts again."""


def fdiv(a, b):
    """Divide the way Haxe does, giving infinity or NaN for a zero divisor."""
    if b != 0:
        return a / b
    if a == 0 or a != a:
        return math.nan
    return math.copysign(math.inf, a) * math.copysign(1.0, b)


def sign(value):
    if value == 0:
        return 0
    return -1 if value < 0 else 1


def index_of(items, value, start=0):
    """Like Array.indexOf, -1 when it isn't there."""
    for i in range(start, len(items)):
        if items[i] is value:
            return i
    return -1


def last_index_of(items, value):
    for i in range(len(items) - 1, -1, -1):
        if items[i] is value:
            return i
    return -1


def min_by(items, measure):
    """The first item with the lowest measure."""
    result = items[0]
    lowest = measure(result)
    for item in items[1:]:
        value = measure(item)
        if value < lowest:
            result, lowest = item, value
    return result


def max_by(items, measure):
    """The first item with the highest measure."""
    result = items[0]
    highest = measure(result)
    for item in items[1:]:
        value = measure(item)
        if value > highest:
            result, highest = item, value
    return result


class Point:
    __slots__ = ("x", "y")

    def __init__(self, x=0.0, y=0.0):
        self.x = x
        self.y = y

    def __repr__(self):
        return f"Point({self.x:.3f}, {self.y:.3f})"

    @property
    def length(self):
        return math.hypot(self.x, self.y)

    def set(self, other):
        self.x = other.x
        self.y = other.y

    def add(self, other):
        return Point(self.x + other.x, self.y + other.y)

    def subtract(self, other):
        return Point(self.x - other.x, self.y - other.y)

    def scale(self, factor):
        return Point(self.x * factor, self.y * factor)

    def norm(self, length=1.0):
        """A copy of this vector with the given length."""
        size = math.hypot(self.x, self.y)
        if size == 0:
            return Point(self.x, self.y)
        return Point(self.x * length / size, self.y * length / size)

    def add_eq(self, other):
        self.x += other.x
        self.y += other.y

    def scale_eq(self, factor):
        self.x *= factor
        self.y *= factor

    def offset(self, dx, dy):
        self.x += dx
        self.y += dy

    def dot(self, other):
        return self.x * other.x + self.y * other.y

    def rotate90(self):
        return Point(-self.y, self.x)


def distance(a, b):
    return math.hypot(a.x - b.x, a.y - b.y)


def convex_hull(points):
    """The convex outline of a list of (x, y) pairs."""
    points = sorted(set(points))
    if len(points) < 3:
        return points

    def half(ordered):
        hull = []
        for p in ordered:
            while len(hull) >= 2:
                (ax, ay), (bx, by) = hull[-2], hull[-1]
                if (bx - ax) * (p[1] - ay) - (by - ay) * (p[0] - ax) > 0:
                    break
                hull.pop()
            hull.append(p)
        return hull[:-1]

    return half(points) + half(points[::-1])


def interpolate(p1, p2, ratio=0.5):
    return Point(p1.x + (p2.x - p1.x) * ratio, p1.y + (p2.y - p1.y) * ratio)


def cross(x1, y1, x2, y2):
    return x1 * y2 - y1 * x2


def intersect_lines(x1, y1, dx1, dy1, x2, y2, dx2, dy2):
    """Where two lines cross, as (t1, t2) along each, or None if parallel."""
    d = dx1 * dy2 - dy1 * dx2
    if d == 0:
        return None
    t2 = (dy1 * (x2 - x1) - dx1 * (y2 - y1)) / d
    if dx1 != 0:
        t1 = (x2 - x1 + dx2 * t2) / dx1
    else:
        t1 = (y2 - y1 + dy2 * t2) / dy1
    return t1, t2


def distance_to_line(x1, y1, dx1, dy1, x0, y0):
    return fdiv(
        dx1 * y0 - dy1 * x0 + (y1 + dy1) * x1 - (x1 + dx1) * y1,
        math.sqrt(dx1 * dx1 + dy1 * dy1),
    )


def chaikin(points, iterations=2, closed=False):
    """Round off a line of (x, y) pairs by cutting its corners.

    An open line keeps its two ends where they are.
    """
    for _ in range(iterations):
        if len(points) < 3:
            return points
        rounded = [] if closed else [points[0]]
        pairs = list(zip(points, points[1:]))
        if closed:
            pairs.append((points[-1], points[0]))
        for (x0, y0), (x1, y1) in pairs:
            rounded.append((0.75 * x0 + 0.25 * x1, 0.75 * y0 + 0.25 * y1))
            rounded.append((0.25 * x0 + 0.75 * x1, 0.25 * y0 + 0.75 * y1))
        if closed:
            points = rounded
        else:
            # The cuts next to each end would otherwise leave a stub.
            points = [points[0]] + rounded[2:-1] + [points[-1]]
    return points


class Polygon(list):
    """A list of Points. Copying the polygon shares the points."""

    DELTA = 0.000001

    def set(self, other):
        """Move this polygon's own points to match another's."""
        for i in range(len(other)):
            self[i].set(other[i])

    def last(self):
        return self[-1]

    def edges(self):
        """Every edge in order, including the closing one."""
        count = len(self)
        return [(self[i], self[(i + 1) % count]) for i in range(count)]

    @property
    def square(self):
        """The signed area."""
        v1 = self[-1]
        v2 = self[0]
        s = v1.x * v2.y - v2.x * v1.y
        for i in range(1, len(self)):
            v1 = v2
            v2 = self[i]
            s += v1.x * v2.y - v2.x * v1.y
        return s * 0.5

    @property
    def perimeter(self):
        return sum(distance(v0, v1) for v0, v1 in self.edges())

    @property
    def compactness(self):
        """1.00 for a circle, 0.79 for a square, 0.60 for a triangle."""
        p = self.perimeter
        return fdiv(4 * math.pi * self.square, p * p)

    @property
    def center(self):
        """A quick approximation of the centroid."""
        c = Point()
        for v in self:
            c.add_eq(v)
        c.scale_eq(1 / len(self))
        return c

    @property
    def centroid(self):
        x = y = a = 0.0
        for v0, v1 in self.edges():
            f = cross(v0.x, v0.y, v1.x, v1.y)
            a += f
            x += (v0.x + v1.x) * f
            y += (v0.y + v1.y) * f
        s6 = fdiv(1, 3 * a)
        return Point(s6 * x, s6 * y)

    def contains_point(self, p):
        """Whether a point is inside the shape, by ray casting."""
        inside = False
        for v0, v1 in self.edges():
            if (v0.y > p.y) != (v1.y > p.y):
                if p.x < (v1.x - v0.x) * (p.y - v0.y) / (v1.y - v0.y) + v0.x:
                    inside = not inside
        return inside

    def rounded(self, iterations=3):
        """A copy with its corners rounded off."""
        points = chaikin([(v.x, v.y) for v in self], iterations, closed=True)
        return Polygon(Point(x, y) for x, y in points)

    def offset(self, p):
        for v in self:
            v.offset(p.x, p.y)

    def rotate(self, angle):
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        for v in self:
            v.x, v.y = v.x * cos_a - v.y * sin_a, v.y * cos_a + v.x * sin_a

    def is_convex_vertex(self, v1):
        v0 = self.prev(v1)
        v2 = self.next(v1)
        return cross(v1.x - v0.x, v1.y - v0.y, v2.x - v1.x, v2.y - v1.y) > 0

    def is_convex(self):
        return all(self.is_convex_vertex(v) for v in self)

    def smooth_vertex(self, v, f=1.0):
        before = self.prev(v)
        after = self.next(v)
        return Point(
            before.x + v.x * f + after.x,
            before.y + v.y * f + after.y,
        ).scale(1 / (2 + f))

    def distance(self, p):
        """The distance from the first vertex to a point.

        The original means this to be the distance from the nearest vertex,
        but it never updates its running value, so this is what it returns.
        Ward placement and the map limits were tuned with this behaviour, so
        it stays.
        """
        return distance(self[0], p)

    def smooth_vertex_eq(self, f=1.0):
        count = len(self)
        v1 = self[-1]
        v2 = self[0]
        result = Polygon()
        for i in range(count):
            v0 = v1
            v1 = v2
            v2 = self[(i + 1) % count]
            result.append(Point(
                (v0.x + v1.x * f + v2.x) / (2 + f),
                (v0.y + v1.y * f + v2.y) / (2 + f),
            ))
        return result

    def buffer(self, d):
        """Inset every edge by its own distance.

        Fairly reliable for convex and concave shapes alike when the distances
        match, and it changes the number of vertices.
        """
        # Offset each edge, which may leave the polygon crossing itself.
        q = Polygon()
        for i, (v0, v1) in enumerate(self.edges()):
            dd = d[i]
            if dd == 0:
                q.append(v0)
                q.append(v1)
            else:
                n = v1.subtract(v0).rotate90().norm(dd)
                q.append(v0.add(n))
                q.append(v1.add(n))

        # Add a shared vertex at every place where two edges cross.
        was_cut = True
        last_edge = 0
        while was_cut:
            was_cut = False
            n = len(q)
            for i in range(last_edge, n - 2):
                last_edge = i
                p11 = q[i]
                p12 = q[i + 1]
                x1 = p11.x
                y1 = p11.y
                dx1 = p12.x - x1
                dy1 = p12.y - y1
                for j in range(i + 2, n if i > 0 else n - 1):
                    p21 = q[j]
                    p22 = q[j + 1] if j < n - 1 else q[0]
                    x2 = p21.x
                    y2 = p21.y
                    hit = intersect_lines(
                        x1, y1, dx1, dy1, x2, y2, p22.x - x2, p22.y - y2)
                    if (hit is not None
                            and self.DELTA < hit[0] < 1 - self.DELTA
                            and self.DELTA < hit[1] < 1 - self.DELTA):
                        pn = Point(x1 + dx1 * hit[0], y1 + dy1 * hit[0])
                        q.insert(j + 1, pn)
                        q.insert(i + 1, pn)
                        was_cut = True
                        break
                if was_cut:
                    break

        # Those vertices divide it into loops. Keep the biggest.
        regular = list(range(len(q)))
        best_part = None
        best_square = -math.inf
        while regular:
            indices = []
            start = regular[0]
            i = start
            for _ in range(len(q) + 1):
                indices.append(i)
                if i in regular:
                    regular.remove(i)
                following = (i + 1) % len(q)
                v = q[following]
                jump = index_of(q, v)
                if jump == following:
                    jump = last_index_of(q, v)
                i = following if jump == -1 else jump
                if i == start:
                    break
            else:
                raise GenerationError("Buffered polygon didn't close")

            part = Polygon(q[k] for k in indices)
            s = part.square
            if s > best_square:
                best_part = part
                best_square = s
        return best_part

    def shrink(self, d):
        """Inset every edge by its own distance, keeping the shape convex."""
        q = Polygon(self)
        for i, (v1, v2) in enumerate(self.edges()):
            dd = d[i]
            if dd > 0:
                n = v2.subtract(v1).rotate90().norm(dd)
                q = q.cut(v1.add(n), v2.add(n), 0)[0]
        return q

    def shrink_eq(self, d):
        return self.shrink([d] * len(self))

    def peel(self, v1, d):
        """Cut a strip off along the edge that starts at v1."""
        i1 = index_of(self, v1)
        i2 = 0 if i1 == len(self) - 1 else i1 + 1
        v2 = self[i2]
        n = v2.subtract(v1).rotate90().norm(d)
        return self.cut(v1.add(n), v2.add(n), 0)[0]

    def find_edge(self, a, b):
        index = index_of(self, a)
        if index != -1 and self[(index + 1) % len(self)] is b:
            return index
        return -1

    def next(self, a):
        return self[(index_of(self, a) + 1) % len(self)]

    def prev(self, a):
        return self[(index_of(self, a) + len(self) - 1) % len(self)]

    def vector(self, v):
        return self.next(v).subtract(v)

    def vectori(self, i):
        return self[0 if i == len(self) - 1 else i + 1].subtract(self[i])

    def borders(self, another):
        len1 = len(self)
        len2 = len(another)
        for i in range(len1):
            j = index_of(another, self[i])
            if j != -1:
                following = self[(i + 1) % len1]
                if (following is another[(j + 1) % len2]
                        or following is another[(j + len2 - 1) % len2]):
                    return True
        return False

    def split(self, p1, p2):
        i1 = index_of(self, p1)
        i2 = index_of(self, p2)
        if i1 > i2:
            i1, i2 = i2, i1
        return [
            Polygon(self[i1:i2 + 1]),
            Polygon(self[i2:] + self[:i1 + 1]),
        ]

    def cut(self, p1, p2, gap=0.0):
        """Slice along the line through two points, returning the pieces."""
        x1 = p1.x
        y1 = p1.y
        dx1 = p2.x - x1
        dy1 = p2.y - y1

        count = len(self)
        edge1 = edge2 = 0
        ratio1 = ratio2 = 0.0
        hits = 0
        for i in range(count):
            v0 = self[i]
            v1 = self[(i + 1) % count]
            x2 = v0.x
            y2 = v0.y
            t = intersect_lines(
                x1, y1, dx1, dy1, x2, y2, v1.x - x2, v1.y - y2)
            if t is not None and 0 <= t[1] <= 1:
                if hits == 0:
                    edge1, ratio1 = i, t[0]
                elif hits == 1:
                    edge2, ratio2 = i, t[0]
                hits += 1

        if hits != 2:
            return [Polygon(self)]

        direction = p2.subtract(p1)
        point1 = p1.add(direction.scale(ratio1))
        point2 = p1.add(direction.scale(ratio2))

        half1 = Polygon([point1] + self[edge1 + 1:edge2 + 1] + [point2])
        half2 = Polygon(
            [point2] + self[edge2 + 1:] + self[:edge1 + 1] + [point1])

        if gap > 0:
            half1 = half1.peel(point2, gap / 2)
            half2 = half2.peel(point1, gap / 2)

        v = self.vectori(edge1)
        if cross(dx1, dy1, v.x, v.y) > 0:
            return [half1, half2]
        return [half2, half1]

    def interpolate(self, p):
        """A weight for each vertex, by how near it is to a point."""
        weights = [fdiv(1, distance(v, p)) for v in self]
        total = sum(weights)
        return [fdiv(w, total) for w in weights]

    @staticmethod
    def rect(w=1.0, h=1.0):
        return Polygon([
            Point(-w / 2, -h / 2),
            Point(w / 2, -h / 2),
            Point(w / 2, h / 2),
            Point(-w / 2, h / 2),
        ])

    @staticmethod
    def regular(n=8, r=1.0):
        points = []
        for i in range(n):
            a = i / n * math.pi * 2
            points.append(Point(r * math.cos(a), r * math.sin(a)))
        return Polygon(points)

    @staticmethod
    def circle(r=1.0):
        return Polygon.regular(16, r)
