"""Moving and locking buildings by hand.

This module is original to this port, and nothing in it needs Qt.

A dragged building shoves aside whatever it runs into, and those buildings
shove others in turn. City walls give way: a building that reaches one
bends that stretch of wall into a smooth bulge, with its towers and gates,
and anything beyond the wall is moved clear. A locked building never moves,
so it stops the dragged building, and it holds a wall back too. So does
water. If a step can't be fitted in, it is undone and the dragged building
tries to slide along the obstacle instead.

A wall has too few corners to curve, so a stretch about to bend gets more.
They are added to the outlines of the wards along it as well, and they have
no towers of their own.

Neighbouring buildings often share corner points, so a building is never
moved by changing its points. It gets new ones instead. The polygons
themselves stay in their wards, so drawing and exports see the moves.
"""

import math

from .geometry import Point, convex_hull, index_of
from .layers import THICK_STROKE
from .water import RIVER_WIDTH

CELL = 16.0  # The size of the squares used to find nearby buildings.
MAX_STEP = 1.0  # A long drag is taken in steps of this size.
MAX_REPEATS = 12  # A building shoved this often in one step is jammed.
MAX_PUSHES = 1500  # How much shoving one step may cause before giving up.
TOUCHING = 0.05  # Overlaps smaller than this are neighbours just touching.
PUSH_GAP = 0.15  # Pushed buildings end up this far apart.
RIVER_MARGIN = 0.3
WALL_MARGIN = 0.1
WALL_EASE = 0.05  # How far a squeezed building is moved past the limit.
WALL_SLACK = 0.8  # How far past the limit a wall is moved, to save moving it.
WALL_MAX_MOVE = 2.0  # The furthest a corner goes in one push, not to skip a house.
WALL_TRIES = 4  # How many times one building may move a wall in a step.
WALL_REACH = 20.0  # How far along a wall each way even a small push bends it.
WALL_MAX_REACH = 90.0  # How far along a wall each way any push can bend it.
WALL_SPREAD = 1.5  # How much further for each unit the wall has moved already.
WALL_SEGMENT = 7.0  # The longest edge in a stretch of wall that is bending.
WALL_LEVEL = 2  # How many corners each way decide which way a wall is facing.
WALL_EASING = 0.5  # How much of an inward corner is taken out each push.
ROAD_GAP = 2.0  # How far ahead of a moving wall a road is carried.
MIN_SHARE = 0.25  # Limits the swing of a wall that is held near the push.
MAX_SLIDES = 200  # The most steps one pointer move can take along an obstacle.
MAX_PUSHES_PER_MOVE = 2000  # The shoving allowed for one move of the pointer.
RETRY_DISTANCE = 1.0  # How far the pointer must go before a stuck drag retries.


def _project(hull, ax, ay):
    values = [x * ax + y * ay for x, y in hull]
    return min(values), max(values)


def overlap(hull_a, hull_b):
    """How to push b clear of a, as (dx, dy), or None if they don't overlap.

    Two convex shapes overlap unless some edge of one separates them, so this
    tries every edge direction and keeps the shallowest overlap.
    """
    best = None
    best_depth = math.inf

    for hull in (hull_a, hull_b):
        for i, (x0, y0) in enumerate(hull):
            x1, y1 = hull[(i + 1) % len(hull)]
            ax = y0 - y1
            ay = x1 - x0
            size = math.hypot(ax, ay)
            if size == 0:
                continue
            ax /= size
            ay /= size

            min_a, max_a = _project(hull_a, ax, ay)
            min_b, max_b = _project(hull_b, ax, ay)
            depth = min(max_a, max_b) - max(min_a, min_b)
            if depth <= TOUCHING:
                return None
            if depth < best_depth:
                best_depth = depth
                # Point the push from a towards b.
                direction = 1 if (min_b + max_b) >= (min_a + max_a) else -1
                best = (ax * direction, ay * direction)

    if best is None:
        return None
    # Leave only as much of a gap as a push needs, to keep streets open.
    push = best_depth + PUSH_GAP
    return best[0] * push, best[1] * push


def _distance_to_segment(px, py, ax, ay, bx, by):
    dx = bx - ax
    dy = by - ay
    length = dx * dx + dy * dy
    if length == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def _segments_cross(ax, ay, bx, by, cx, cy, dx, dy):
    def side(px, py, qx, qy, rx, ry):
        return (qx - px) * (ry - py) - (qy - py) * (rx - px)

    return (side(ax, ay, bx, by, cx, cy) * side(ax, ay, bx, by, dx, dy) < 0
            and side(cx, cy, dx, dy, ax, ay) * side(cx, cy, dx, dy, bx, by) < 0)


def _gap_to_hull(building, part):
    """How far a building is from a piece of wall, past its margin.

    A building overlapping the wall gets a figure for how far through it has
    gone, so that it can't be pushed on through without anyone noticing.
    """
    hull = building.hull
    ax, ay, bx, by, margin = part[:5]
    count = len(hull)
    nearest = math.inf
    for i in range(count):
        px, py = hull[i]
        qx, qy = hull[(i + 1) % count]
        if _segments_cross(px, py, qx, qy, ax, ay, bx, by):
            return -margin - _depth_through(building, part)
        nearest = min(nearest,
                      _distance_to_segment(px, py, ax, ay, bx, by),
                      _distance_to_segment(ax, ay, px, py, qx, qy),
                      _distance_to_segment(bx, by, px, py, qx, qy))
    if building.polygon.contains_point(Point(ax, ay)):
        return -margin - _depth_through(building, part)
    return nearest - margin


def _depth_through(building, part):
    """How far a building sticks out past the far side of a piece of wall."""
    ax, ay = part[:2]
    x, y = part[8]
    if building.ward.patch not in part[7].patches:
        x, y = -x, -y
    return max(0.0, max((px - ax) * x + (py - ay) * y
                        for px, py in building.hull))


def _bulge_share(along, grown):
    """A corner's share of a push, from 0 at the peak to 1 at the far end.

    The bulge itself is a cosine curve, which leaves the unmoved wall and
    rounds its peak with no kink. While a bulge is also widening, its sides
    have to move faster than its peak to keep that shape, which is what the
    second term does. Without it the sides fall behind and form a wedge.
    """
    wave = math.pi * along
    return (1 + math.cos(wave)) / 2 + grown * along * math.pi / 2 * math.sin(wave)


class Building:
    """One building, and the convex outline used for collisions.

    place and shift are the only ways editing changes a building, and both
    count an edit on its ward, so drawing knows which wards have changed.
    """

    __slots__ = ("polygon", "ward", "hull", "cells", "cx", "cy", "radius")

    def __init__(self, polygon, ward):
        self.polygon = polygon
        self.ward = ward
        self.cells = ()
        self._measure(self.corners())

    def corners(self):
        return [(v.x, v.y) for v in self.polygon]

    def place(self, corners):
        """Give the building new points, leaving its neighbours' alone."""
        first = self.polygon[0]
        self._carry_house(corners[0][0] - first.x, corners[0][1] - first.y)
        self.polygon[:] = [Point(x, y) for x, y in corners]
        self._measure(corners)
        self.ward.edits += 1

    def _carry_house(self, dx, dy):
        """Move what stands on a plot with it. Plots only ever slide."""
        carry = getattr(self.polygon, "carry", None)
        if carry is not None:
            carry(dx, dy)

    def _measure(self, corners):
        self.hull = convex_hull(corners)
        self.cx = sum(c[0] for c in corners) / len(corners)
        self.cy = sum(c[1] for c in corners) / len(corners)
        self.radius = max(math.hypot(x - self.cx, y - self.cy)
                          for x, y in corners)

    def shift(self, dx, dy):
        """Slide the building, which keeps its shape, so nothing is remeasured."""
        self._carry_house(dx, dy)
        self.polygon[:] = [Point(v.x + dx, v.y + dy) for v in self.polygon]
        self.ward.edits += 1
        self.hull = [(x + dx, y + dy) for x, y in self.hull]
        self.cx += dx
        self.cy += dy

    def center(self):
        return self.cx, self.cy

    def may_reach(self, part):
        """A quick check that rules out most buildings and pieces of wall."""
        ax, ay, bx, by, margin = part[:5]
        return (_distance_to_segment(self.cx, self.cy, ax, ay, bx, by)
                < self.radius + margin)


class CityEditor:
    """The moves and locks made to one generated city."""

    def __init__(self, model):
        self.model = model
        self.buildings = []
        self.locked = set()
        self.history = []
        self.grid = {}
        self._drag_start = None
        self._drag_walls = None
        self._drag_origin = None
        self._drag_lists = None
        self._corner = None
        self.wall_parts = {}
        self.all_wall_parts = {}
        self.wall_allowance = {}
        self.released = {}
        self.wall_home = {}
        self.bank_towers = {}
        self.changed_lists = {}
        self.squeezed = {}
        self.pushes_spent = 0
        self._stuck_at = None

        for patch in model.patches:
            for polygon in list(patch.ward.geometry) + list(patch.ward.landmarks):
                if len(polygon) >= 3:
                    self.buildings.append(Building(polygon, patch.ward))
        for building in self.buildings:
            self._index(building)
        self._find_bank_towers()
        self._index_walls()
        self._note_wall_allowances()

    def _walls(self):
        walls = []
        if self.model.wall is not None:
            walls.append((self.model.wall, THICK_STROKE))
        if self.model.citadel is not None:
            walls.append((self.model.citadel.ward.wall, THICK_STROKE * 1.5))
        return walls

    def _find_bank_towers(self):
        """Note the towers that stand beside a river, not on a wall corner."""
        for wall, _ in self._walls():
            crossings = [v for v in wall.shape if v in self.model.river_points]
            for tower in wall.towers:
                if tower in wall.shape or not crossings:
                    continue
                crossing = min(crossings, key=lambda v: math.hypot(
                    v.x - tower.x, v.y - tower.y))
                step = max((1, -1), key=lambda s: self._leans_towards(
                    wall, crossing, s, tower))
                self.bank_towers[tower] = (crossing, step)

    @staticmethod
    def _along_wall(wall, point, step):
        shape = wall.shape
        return shape[(index_of(shape, point) + step) % len(shape)]

    def _leans_towards(self, wall, crossing, step, tower):
        along = self._along_wall(wall, crossing, step)
        return ((along.x - crossing.x) * (tower.x - crossing.x)
                + (along.y - crossing.y) * (tower.y - crossing.y)
                ) / (math.hypot(along.x - crossing.x, along.y - crossing.y)
                     or 1.0)

    def _follow_banks(self, wall, moved_walls):
        """Keep each tower by a river on the line of its wall."""
        for tower, (crossing, step) in self.bank_towers.items():
            if tower not in wall.towers:
                continue
            along = self._along_wall(wall, crossing, step)
            size = math.hypot(along.x - crossing.x, along.y - crossing.y)
            if size == 0:
                continue
            reach = math.hypot(tower.x - crossing.x, tower.y - crossing.y)
            moved_walls.setdefault(tower, (tower.x, tower.y))
            tower.x = crossing.x + (along.x - crossing.x) / size * reach
            tower.y = crossing.y + (along.y - crossing.y) / size * reach

    def _index_walls(self):
        """Note which squares of map have walls, gates or towers in them.

        Each part keeps the points it came from, so that it can be moved, and
        the way out of the walled area from it.
        """
        self.wall_parts = {}
        self.all_wall_parts = {}
        for wall, tower_radius in self._walls():
            shape = wall.shape
            winding = sum(a.x * b.y - b.x * a.y for a, b in shape.edges())

            def outward(a, b):
                x, y = b.y - a.y, a.x - b.x
                size = math.hypot(x, y) or 1.0
                if winding < 0:
                    size = -size
                return x / size, y / size

            line = THICK_STROKE / 2 + WALL_MARGIN
            for i, (a, b) in enumerate(shape.edges()):
                if wall.segments[i]:
                    self._add_wall_part(a.x, a.y, b.x, b.y, line, a, b, wall,
                                        outward(a, b))
            for t in wall.towers:
                if t in self.bank_towers:
                    a, step = self.bank_towers[t]
                    b = self._along_wall(wall, a, step)
                    way = outward(a, b) if step > 0 else outward(b, a)
                else:
                    a = b = t
                    way = outward(shape.prev(t), shape.next(t))
                self._add_wall_part(t.x, t.y, t.x, t.y,
                                    tower_radius + WALL_MARGIN, a, b, wall, way)
            for gate in wall.gates:
                along = shape.next(gate).subtract(shape.prev(gate))
                along = along.norm(THICK_STROKE * 1.5)
                self._add_wall_part(gate.x - along.x, gate.y - along.y,
                                    gate.x + along.x, gate.y + along.y,
                                    THICK_STROKE + WALL_MARGIN, gate, gate,
                                    wall,
                                    outward(shape.prev(gate), shape.next(gate)))

    def _note_wall_allowances(self):
        """Let buildings that start out close to a wall stay that close."""
        for building in self.buildings:
            gap = self._wall_gap(building)
            if gap < 0:
                self.wall_allowance[building] = gap

    def _add_wall_part(self, ax, ay, bx, by, margin, a, b, wall, way):
        part = (ax, ay, bx, by, margin, a, b, wall, way)
        self.all_wall_parts[part] = True
        for i, j in self._cells_along(part, spread=1):
            self.wall_parts.setdefault((i, j), {})[part] = True

    @staticmethod
    def _cells_along(part, spread=0):
        ax, ay, bx, by = part[:4]
        steps = max(1, int(math.hypot(bx - ax, by - ay) / CELL) + 1)
        cells = {}
        for step in range(steps + 1):
            t = step / steps
            cx = int((ax + (bx - ax) * t) // CELL)
            cy = int((ay + (by - ay) * t) // CELL)
            for i in range(cx - spread, cx + spread + 1):
                for j in range(cy - spread, cy + spread + 1):
                    cells[(i, j)] = True
        return cells

    def _nearby_wall_parts(self, building):
        found = {}
        for cell in building.cells:
            found.update(self.wall_parts.get(cell, {}))
        return found

    def _wall_gap(self, building):
        return min((_gap_to_hull(building, part)
                    for part in self._nearby_wall_parts(building)
                    if building.may_reach(part)),
                   default=math.inf)

    def _tightest_wall_part(self, building):
        """The piece of wall a building is furthest inside the margin of."""
        limit = self.wall_allowance.get(building, 0.0)
        tightest = None
        lowest = limit
        for part in self._nearby_wall_parts(building):
            if not building.may_reach(part):
                continue
            gap = _gap_to_hull(building, part)
            if gap < lowest:
                lowest = gap
                tightest = part
        return tightest, limit - lowest

    def _away_from(self, part, building):
        """The way a piece of wall lies from a building, as a unit vector.

        This goes by the ward the building is in. Its position won't do, as
        the wall around a bulge can have its middle on the wrong side.
        """
        wall, (x, y) = part[7:9]
        if building.ward.patch in wall.patches:
            return x, y
        return -x, -y

    def _clear_walls(self, building, moved_walls):
        """Move any wall this building has reached. False if it won't go."""
        for _ in range(WALL_TRIES):
            part, depth = self._tightest_wall_part(building)
            if part is None:
                return True
            if self._add_wall_corners(part):
                self._index_walls()
                part, depth = self._tightest_wall_part(building)
                if part is None:
                    return True

            motion = self._away_from(part, building)
            points = self._bend_wall(part, building, depth, moved_walls)
            if not points:
                return False
            self._note_squeezed(building, points, motion)
        return self._tightest_wall_part(building)[0] is None

    def _home(self, point):
        """Where a corner of a wall stood when the city was built."""
        return self.wall_home.get(point, (point.x, point.y))

    def _raised(self, point):
        """How far a corner of a wall has moved since the city was built."""
        x, y = self._home(point)
        return math.hypot(point.x - x, point.y - y)

    def _reach(self, part):
        """How far along the wall, each way, a push at this part bends it.

        Returns that and how much of it comes from the wall having moved
        already, from 0 to 1. The further a wall has moved the wider it
        bends, so that a bulge stays a broad curve and doesn't become a spike.
        Distances are along the wall as it was built, which keeps the curve
        the same shape while the wall stretches.
        """
        wall = part[7]
        homes = [self._home(v) for v in wall.shape]
        perimeter = sum(math.hypot(a[0] - b[0], a[1] - b[1])
                        for a, b in zip(homes, homes[1:] + homes[:1]))
        grown = WALL_SPREAD * max(self._raised(part[5]), self._raised(part[6]))
        reach = WALL_REACH + grown
        limit = min(perimeter / 4, WALL_MAX_REACH)
        if reach > limit:
            return limit, 0.0
        return reach, grown / reach

    def _add_wall_corners(self, part):
        """Divide the long edges a push is about to bend. True if any were."""
        wall = part[7]
        shape = wall.shape
        reach = self._reach(part)[0]
        x, y = self._home(part[5])

        added = False
        for i in range(len(shape) - 1, -1, -1):
            a = shape[i]
            b = shape[(i + 1) % len(shape)]
            length = math.hypot(a.x - b.x, a.y - b.y)
            if (wall.segments[i] and length > WALL_SEGMENT
                    and _distance_to_segment(x, y, *self._home(a),
                                             *self._home(b)) < reach + length):
                self._divide_edge(a, b, math.ceil(length / WALL_SEGMENT))
                added = True
        return added

    def _divide_edge(self, a, b, pieces):
        """Put new corners on an edge, in everything that shares that edge."""
        self._put_corners(a, b, [i / pieces for i in range(1, pieces)])

    def _put_corners(self, a, b, shares):
        """New corners part way along an edge, from a, in everything sharing it.

        Returns the new corners.
        """
        home_a = self._home(a)
        home_b = self._home(b)
        middle = []
        for t in shares:
            point = Point(a.x + (b.x - a.x) * t, a.y + (b.y - a.y) * t)
            self.wall_home[point] = (home_a[0] + (home_b[0] - home_a[0]) * t,
                                     home_a[1] + (home_b[1] - home_a[1]) * t)
            middle.append(point)

        for wall, _ in self._walls():
            self._note_list(wall.segments)
            for first, last, points in ((a, b, middle), (b, a, middle[::-1])):
                index = wall.shape.find_edge(first, last)
                if index != -1:
                    wall.segments[index + 1:index + 1] = [True] * len(points)
                    self._insert_corners(wall.shape, index, points)

        for patch in self.model.patches:
            for first, last, points in ((a, b, middle), (b, a, middle[::-1])):
                index = patch.shape.find_edge(first, last)
                if index != -1:
                    self._insert_corners(patch.shape, index, points)
        return middle

    def _insert_corners(self, polygon, index, points):
        self._note_list(polygon)
        polygon[index + 1:index + 1] = points

    def _note_list(self, items):
        self.changed_lists.setdefault(id(items), (items, list(items)))

    def _restore_lists(self, saved):
        for items, contents in saved.values():
            items[:] = contents

    def _bend_wall(self, part, building, depth, moved_walls):
        """Bulge a wall away from a building. Returns the corners moved."""
        a, b, wall = part[5:8]
        cx, cy = building.center()
        ways = self._corner_ways(wall, building)
        size = depth + WALL_SLACK
        fixed = self.model.water_points

        # How far along the edge the building is touching it.
        along = 0.0
        length = math.hypot(b.x - a.x, b.y - a.y)
        if a is not b and length > 0:
            along = ((cx - a.x) * (b.x - a.x)
                     + (cy - a.y) * (b.y - a.y)) / (length * length)
            along = max(0.0, min(1.0, along))

        home_a = self._home(a)
        home_b = self._home(b)
        span = math.hypot(home_b[0] - home_a[0], home_b[1] - home_a[1])
        shares = self._shares(wall, a, -1, along * span, part, ways, size, fixed)
        if a is b:
            if a not in shares:
                return {}
            start = self._along_wall(wall, a, 1)
            home = self._home(start)
            gap = math.hypot(home[0] - home_a[0], home[1] - home_a[1])
        else:
            start = b
            gap = (1 - along) * span
        shares.update(self._shares(wall, start, 1, gap, part, ways, size, fixed))

        share = (1 - along) * shares.get(a, 0.0) + along * shares.get(b, 0.0)
        if share == 0:
            return {}

        # The wall must clear the building where they touch, so the rest of
        # the bulge scales from there. A wall held close by swings further.
        scale = size / max(share, MIN_SHARE)
        scale = min(scale, WALL_MAX_MOVE / max(shares.values()))
        spots = {point: (point.x, point.y) for point in shares}
        for point, weight in shares.items():
            moved_walls.setdefault(point, spots[point])
            self.wall_home.setdefault(point, spots[point])
            point.x += ways[point][0] * scale * weight
            point.y += ways[point][1] * scale * weight
        self._ease_corners(wall, shares, ways, moved_walls)
        self._follow_banks(wall, moved_walls)
        self._index_walls()

        if self._wall_gone_wrong(wall, shares):
            for point, (x, y) in spots.items():
                point.x = x
                point.y = y
            self._follow_banks(wall, moved_walls)
            self._index_walls()
            return {}

        self._carry_roads(wall, shares, ways, moved_walls)
        return shares

    def _wall_gone_wrong(self, wall, points, check_water=True):
        """True if a push put a wall in water or took it across a wall.

        Every wall is checked against itself. A city wall being pushed isn't
        checked against the castle, which it moves away from. The two share
        corners, so they can graze each other where they join. A castle wall
        mustn't break out of the city wall, though.
        """
        if check_water and any(self._water_at(point.x, point.y)
                               for point in points):
            return True
        city_wall = wall is self.model.wall
        for part in self.all_wall_parts:
            a, b = part[5:7]
            if a is b or (a not in points and b not in points):
                continue
            ax, ay, bx, by = part[:4]
            for cell in self._cells_along(part):
                for other in self.wall_parts.get(cell, ()):
                    c, d = other[5:7]
                    if (c is d or c is a or c is b or d is a or d is b
                            or (city_wall and other[7] is not part[7])):
                        continue
                    if _segments_cross(ax, ay, bx, by, *other[:4]):
                        return True
        return False

    def _ease_corners(self, wall, points, ways, moved_walls):
        """Fill out the inward corners where a bulge leaves the wall.

        These only move with the push, so they can't close in on the building
        behind it, and left alone they fold up into a sharp crease.
        """
        shape = wall.shape
        fixed = self.model.water_points
        for point in points:
            if point in fixed:
                continue
            index = index_of(shape, point)
            before = shape[index - 1]
            after = shape[(index + 1) % len(shape)]
            x = (before.x + after.x) / 2 - point.x
            y = (before.y + after.y) / 2 - point.y
            x *= WALL_EASING
            y *= WALL_EASING
            if (x * ways[point][0] + y * ways[point][1] > 0
                    and not self._water_at(point.x + x, point.y + y)):
                moved_walls.setdefault(point, (point.x, point.y))
                self.wall_home.setdefault(point, (point.x, point.y))
                point.x += x
                point.y += y

    def _carry_roads(self, wall, points, ways, moved_walls):
        """Take any road a wall has passed along with it, ahead of the wall.

        Only the gates may let a road through a wall.
        """
        if wall is not self.model.wall or not points:
            return
        left = min(p.x for p in points) - ROAD_GAP
        right = max(p.x for p in points) + ROAD_GAP
        top = min(p.y for p in points) - ROAD_GAP
        bottom = max(p.y for p in points) + ROAD_GAP
        fixed = self.model.water_points
        for road in self.model.roads:
            for point in road:
                if (not left < point.x < right or not top < point.y < bottom
                        or point in wall.shape or point in fixed
                        or not wall.shape.contains_point(point)):
                    continue
                nearest = min(points, key=lambda p: math.hypot(
                    p.x - point.x, p.y - point.y))
                moved_walls.setdefault(point, (point.x, point.y))
                point.x = nearest.x + ways[nearest][0] * ROAD_GAP
                point.y = nearest.y + ways[nearest][1] * ROAD_GAP

    def _corner_ways(self, wall, building):
        """The way each corner of a wall moves to get away from a building.

        Each corner goes straight out from the wall where it stands, so a
        bulge swells like a balloon. If all went the same way, the sides of
        the bulge would only slide along themselves and leave a narrow point.
        """
        shape = wall.shape
        count = len(shape)
        winding = sum(a.x * b.y - b.x * a.y for a, b in shape.edges())
        sign = 1 if (winding > 0) == (building.ward.patch in wall.patches) else -1
        ways = {}
        for i, point in enumerate(shape):
            before = shape[(i - WALL_LEVEL) % count]
            after = shape[(i + WALL_LEVEL) % count]
            x, y = after.y - before.y, before.x - after.x
            size = math.hypot(x, y) or 1.0
            ways[point] = (x / size * sign, y / size * sign)
        return ways

    def _shares(self, wall, start, step, distance, part, ways, size, fixed):
        """Each corner's share of a push, going one way along a wall."""
        shape = wall.shape
        reach, grown = self._reach(part)
        found = []
        index = index_of(shape, start)
        for _ in range(len(shape)):
            point = shape[index]
            if distance >= reach:
                break
            if point in fixed or self._would_hit(point, ways[point], size * 2):
                reach = distance
                grown = 0.0
                break
            found.append((point, distance))
            index = (index + step) % len(shape)
            x, y = self._home(point)
            home = self._home(shape[index])
            distance += math.hypot(home[0] - x, home[1] - y)
        if reach <= 0:
            return {}
        return {point: _bulge_share(gap / reach, grown)
                for point, gap in found}

    def _would_hit(self, point, way, size):
        """True if a push would take a wall corner into water or a lock."""
        x = point.x + way[0] * size
        y = point.y + way[1] * size
        if self._water_at(x, y):
            return True
        for building in self.locked:
            after = math.hypot(x - building.cx, y - building.cy)
            if (after < building.radius + THICK_STROKE
                    and after < math.hypot(point.x - building.cx,
                                           point.y - building.cy)):
                return True
        return False

    def _note_squeezed(self, pusher, points, motion):
        """Find the buildings a moved piece of wall has run into.

        A building that began close to a wall may stay close only until that
        wall comes towards it. Otherwise the wall would pass straight over it.
        """
        cells = {}
        for part in self.all_wall_parts:
            if part[5] in points or part[6] in points:
                cells.update(self._cells_along(part, spread=1))
        nearby = {}
        for cell in cells:
            nearby.update(self.grid.get(cell, {}))

        for building in nearby:
            if building is pusher or building in self.squeezed:
                continue
            if building in self.wall_allowance:
                for part in self._nearby_wall_parts(building):
                    x, y = self._away_from(part, building)
                    if (part[5] in points or part[6] in points) and (
                            x * motion[0] + y * motion[1] < 0
                            and building.may_reach(part)):
                        self.released[building] = self.wall_allowance.pop(
                            building)
                        break
            if self._tightest_wall_part(building)[0] is not None:
                self.squeezed[building] = True

    @property
    def has_changes(self):
        return bool(self.history or self.locked)

    def _index(self, building):
        xs = [x for x, _ in building.hull]
        ys = [y for _, y in building.hull]
        cells = [
            (i, j)
            for i in range(int(min(xs) // CELL), int(max(xs) // CELL) + 1)
            for j in range(int(min(ys) // CELL), int(max(ys) // CELL) + 1)
        ]
        building.cells = cells
        for cell in cells:
            self.grid.setdefault(cell, {})[building] = True

    def _unindex(self, building):
        for cell in building.cells:
            del self.grid[cell][building]

    def _reindex(self, building):
        self._unindex(building)
        self._index(building)

    def _nearby(self, building):
        found = {}
        for cell in building.cells:
            found.update(self.grid.get(cell, {}))
        found.pop(building, None)
        return list(found)

    def building_at(self, point):
        """The smallest building under a point, or None."""
        cell = (int(point.x // CELL), int(point.y // CELL))
        under = [b for b in self.grid.get(cell, {})
                 if b.polygon.contains_point(point)]
        if not under:
            return None
        return min(under, key=lambda b: abs(b.polygon.square))

    def is_locked(self, building):
        return building in self.locked

    def set_locked(self, building, locked):
        if locked:
            self.locked.add(building)
        else:
            self.locked.discard(building)

    def toggle_lock(self, building):
        self.set_locked(building, building not in self.locked)

    def unlock_all(self):
        self.locked.clear()

    def _water_at(self, x, y):
        model = self.model
        if model.sea is not None and model.sea.contains_point(Point(x, y)):
            return True
        reach = RIVER_WIDTH / 2 + RIVER_MARGIN
        return any(_distance_to_segment(x, y, a.x, a.y, b.x, b.y) < reach
                   for a, b in zip(model.river, model.river[1:]))

    def _river_gap(self, x, y):
        """How far a point is from the middle of the river."""
        return min((_distance_to_segment(x, y, a.x, a.y, b.x, b.y)
                    for a, b in zip(self.model.river, self.model.river[1:])),
                   default=math.inf)

    def _on_water(self, building):
        return any(self._water_at(x, y) for x, y in building.corners())

    def _try_step(self, mover, dx, dy):
        """Move a building and clear its way. False if it won't fit."""
        return self._step(mover, lambda shift, moved_walls: shift(mover, dx, dy))

    def _step(self, mover, start, walls_give_way=True, heading=None):
        """Make one change, then push aside whatever it runs into.

        start makes the change, given the shift function below and the wall
        corners moved so far, and returns False if the change won't go. mover
        is the building being dragged, if any, which nothing may push. With
        walls_give_way False, a building pushed into a wall stops there.
        heading, a unit vector, is the way the change is going. A building
        that can't be pushed aside is then tried that way instead, which lets
        a row of buildings along a wall move ahead of it. Everything is put
        back if it can't all be made to fit.
        """
        before = {}
        moved_walls = {}
        self.squeezed = {}
        self.changed_lists = {}
        self.released = {}

        def place_back(building, x, y):
            building.shift(-x, -y)
            self._reindex(building)
            return False

        def shift(building, x, y, move_walls=walls_give_way):
            """Move a building. False if something solid is in the way."""
            before.setdefault(building, building.corners())
            building.shift(x, y)
            self._reindex(building)
            if self._on_water(building):
                return place_back(building, x, y)
            if move_walls:
                if not self._clear_walls(building, moved_walls):
                    return place_back(building, x, y)
            elif self._tightest_wall_part(building)[0] is not None:
                # Walls that can't give way stop it instead.
                return place_back(building, x, y)
            return True

        def give_up():
            for building, corners in before.items():
                building.place(corners)
                self._reindex(building)
            self._restore_lists(self.changed_lists)
            for point, (x, y) in moved_walls.items():
                point.x = x
                point.y = y
            if moved_walls or self.changed_lists:
                self._index_walls()
            self.wall_allowance.update(self.released)
            self.changed_lists = {}
            self.squeezed = {}
            return False

        if not start(shift, moved_walls):
            return give_up()

        waiting = [] if mover is None else [mover]
        pushes = 0
        shoves = {}
        while waiting or self.squeezed:
            # Whatever a moved wall has run into goes first.
            while self.squeezed:
                building = next(iter(self.squeezed))
                del self.squeezed[building]
                part, needed = self._tightest_wall_part(building)
                if part is None:
                    continue
                pushes += 1
                self.pushes_spent += 1
                if pushes > MAX_PUSHES or building in self.locked:
                    return give_up()
                nx, ny = self._away_from(part, building)
                amount = needed + WALL_EASE
                before.setdefault(building, building.corners())
                building.shift(-nx * amount, -ny * amount)
                self._reindex(building)
                if self._on_water(building):
                    return give_up()
                if self._tightest_wall_part(building)[0] is not None:
                    self.squeezed[building] = True
                if building not in waiting:
                    waiting.append(building)

            if not waiting:
                break
            active = waiting.pop(0)
            for other in self._nearby(active):
                if (math.hypot(active.cx - other.cx, active.cy - other.cy)
                        > active.radius + other.radius):
                    continue
                push = overlap(active.hull, other.hull)
                if push is None:
                    continue

                pushes += 1
                self.pushes_spent += 1
                shoves[other] = shoves.get(other, 0) + 1
                if pushes > MAX_PUSHES or shoves[other] > MAX_REPEATS:
                    return give_up()

                solid = other is mover or other in self.locked
                if not solid and shift(other, push[0], push[1]):
                    if other not in waiting:
                        waiting.append(other)
                    continue
                if not solid and heading is not None:
                    size = math.hypot(*push) + PUSH_GAP
                    if shift(other, heading[0] * size, heading[1] * size):
                        if other not in waiting:
                            waiting.append(other)
                        continue

                # The other can't give way, so this one must.
                if (active is mover or active in self.locked
                        or not shift(active, -push[0], -push[1])):
                    return give_up()
                if active not in waiting:
                    waiting.append(active)
                break

        if self._drag_start is not None:
            for building, corners in before.items():
                self._drag_start.setdefault(building, corners)
            for point, spot in moved_walls.items():
                self._drag_walls.setdefault(point, spot)
            for key, saved in self.changed_lists.items():
                self._drag_lists.setdefault(key, saved)
        return True

    def begin_move(self, building):
        """Start a drag. Returns False for a locked building."""
        if building in self.locked:
            return False
        self._drag_start = {}
        self._drag_walls = {}
        self._drag_lists = {}
        self._drag_origin = building.center()
        self._stuck_at = None
        return True

    def drag_to(self, building, offset_x, offset_y):
        """Take a dragged building towards an offset from where it started.

        Returns True if it reached the offset. If something stops it, it
        waits at the obstacle, and catches up once the pointer comes clear.
        """
        if self._drag_origin is None or building in self.locked:
            return False

        # Trying again from nearly the same place would only fail again, and
        # a failed try is the slowest thing a drag can do.
        if (self._stuck_at is not None
                and math.hypot(offset_x - self._stuck_at[0],
                               offset_y - self._stuck_at[1]) < RETRY_DISTANCE):
            return False
        self._stuck_at = None

        self.pushes_spent = 0
        for _ in range(MAX_SLIDES):
            if self.pushes_spent > MAX_PUSHES_PER_MOVE:
                return False

            cx, cy = building.center()
            dx = self._drag_origin[0] + offset_x - cx
            dy = self._drag_origin[1] + offset_y - cy
            distance = math.hypot(dx, dy)
            if distance < 0.01:
                return True

            step = min(1.0, MAX_STEP / distance)
            sx = dx * step
            sy = dy * step
            if self._try_step(building, sx, sy):
                continue

            # Blocked head on, so try sliding along the obstacle.
            slid = abs(sx) > 0.05 and self._try_step(building, sx, 0.0)
            if not slid and abs(sy) > 0.05:
                slid = self._try_step(building, 0.0, sy)
            if not slid:
                self._stuck_at = (offset_x, offset_y)
                return False
        return False

    def end_move(self):
        """Finish a drag, so that it can be undone as one step."""
        if self._drag_start or self._drag_walls or self._drag_lists:
            self.history.append((self._drag_start, self._drag_walls,
                                 self._drag_lists))
        self._drag_start = None
        self._drag_walls = None
        self._drag_lists = None
        self._drag_origin = None
        self._corner = None

    # Walls edited by hand.

    def _corner_walls(self, corner):
        return [wall for wall, _ in self._walls() if corner in wall.shape]

    def is_fixed_corner(self, corner):
        """Corners on the water stay put, so the wall still meets it."""
        return corner in self.model.water_points

    def wall_corners(self):
        """Every wall corner that can be dragged, and whether it's a tower."""
        corners = {}
        for wall, _ in self._walls():
            for corner in wall.shape:
                if not self.is_fixed_corner(corner):
                    corners[corner] = corners.get(corner) or (
                        corner in wall.towers)
        return corners

    def wall_corner_at(self, point, reach):
        """The draggable wall corner nearest a point, if one is in reach."""
        nearest = None
        best = reach
        for corner in self.wall_corners():
            gap = math.hypot(corner.x - point.x, corner.y - point.y)
            if gap <= best:
                nearest = corner
                best = gap
        return nearest

    def wall_edge_at(self, point, reach):
        """The stretch of wall under a point, as (a, b, share along), or None.

        Only stretches that are built, not gaps for water, count.
        """
        nearest = None
        best = reach
        for wall, _ in self._walls():
            shape = wall.shape
            for i, a in enumerate(shape):
                b = shape[(i + 1) % len(shape)]
                if not wall.segments[i]:
                    continue
                gap = _distance_to_segment(point.x, point.y, a.x, a.y, b.x, b.y)
                if gap <= best:
                    length = (b.x - a.x) ** 2 + (b.y - a.y) ** 2
                    t = ((point.x - a.x) * (b.x - a.x)
                         + (point.y - a.y) * (b.y - a.y)) / (length or 1.0)
                    nearest = (a, b, max(0.05, min(0.95, t)))
                    best = gap
        return nearest

    def begin_wall_move(self, corner=None, edge=None):
        """Start dragging a wall corner, or a new one put on an edge.

        Returns the corner, or None if it can't be moved.
        """
        if edge is not None:
            a, b, t = edge
            if self._water_at(a.x + (b.x - a.x) * t, a.y + (b.y - a.y) * t):
                return None
            self.changed_lists = {}
            corner = self._put_corners(a, b, [t])[0]
            self._index_walls()
            lists = self.changed_lists
            self.changed_lists = {}
        else:
            lists = {}
        if corner is None or self.is_fixed_corner(corner):
            return None
        self._drag_start = {}
        self._drag_walls = {}
        self._drag_lists = dict(lists)
        self._drag_origin = (corner.x, corner.y)
        self._corner = corner
        self._stuck_at = None
        return corner

    def drag_wall_to(self, corner, offset_x, offset_y):
        """Take a dragged wall corner towards an offset from where it began.

        The wall bends with it, and buildings in its way are pushed aside.
        Returns True if it got there. Like a building, it waits at anything
        that stops it.
        """
        if self._drag_origin is None or corner is not self._corner:
            return False
        if (self._stuck_at is not None
                and math.hypot(offset_x - self._stuck_at[0],
                               offset_y - self._stuck_at[1]) < RETRY_DISTANCE):
            return False
        self._stuck_at = None

        self.pushes_spent = 0
        for _ in range(MAX_SLIDES):
            if self.pushes_spent > MAX_PUSHES_PER_MOVE:
                return False
            dx = self._drag_origin[0] + offset_x - corner.x
            dy = self._drag_origin[1] + offset_y - corner.y
            distance = math.hypot(dx, dy)
            if distance < 0.01:
                return True
            step = min(1.0, MAX_STEP / distance)
            if not self._step(None, lambda shift, moved: self._move_corner(
                    corner, dx * step, dy * step, moved), walls_give_way=False,
                    heading=(dx / distance, dy / distance)):
                self._stuck_at = (offset_x, offset_y)
                return False
        return False

    def _move_corner(self, corner, dx, dy, moved_walls):
        """Move a wall corner. False if the wall would go wrong."""
        moved_walls.setdefault(corner, (corner.x, corner.y))
        self.wall_home.setdefault(corner, (corner.x, corner.y))
        wet = self._water_at(corner.x, corner.y)
        river_gap = self._river_gap(corner.x, corner.y)
        corner.x += dx
        corner.y += dy
        if self._water_at(corner.x, corner.y) and (
                not wet or self._river_gap(corner.x, corner.y) < river_gap):
            # A corner built a little too near the river may only move away.
            return False
        walls = self._corner_walls(corner)
        for wall in walls:
            self._follow_banks(wall, moved_walls)
        self._index_walls()
        if any(self._wall_gone_wrong(wall, {corner: 1.0}, check_water=False)
               for wall in walls):
            return False
        size = math.hypot(dx, dy) or 1.0
        self._note_squeezed(None, {corner: 1.0}, (dx / size, dy / size))
        return True

    def toggle_tower(self, corner):
        """Put a tower on a wall corner, or take one off. Gates have none.

        Returns True if it changed anything. It can be undone.
        """
        if self.is_fixed_corner(corner):
            return False
        lists = {}
        for wall in self._corner_walls(corner):
            if corner in wall.gates:
                return False
            lists.setdefault(id(wall.towers), (wall.towers, list(wall.towers)))
            if corner in wall.towers:
                wall.towers.remove(corner)
            else:
                wall.towers.append(corner)
        if not lists:
            return False
        self.history.append(({}, {}, lists))
        self._index_walls()
        return True

    def undo(self):
        """Put back everything the last drag moved, walls included."""
        if not self.history:
            return False
        buildings, walls, lists = self.history.pop()
        for building, corners in buildings.items():
            building.place(corners)
            self._reindex(building)
        self._restore_lists(lists)
        for point, (x, y) in walls.items():
            point.x = x
            point.y = y
        self._index_walls()
        self.wall_allowance = {}
        self._note_wall_allowances()
        return True
