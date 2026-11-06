"""Moving and locking buildings by hand.

This module is original to this port, and nothing in it needs Qt.

A dragged building shoves aside whatever it runs into, and those buildings
shove others in turn. City walls give way: a building that reaches one
moves that stretch of wall, with its towers and gates, and anything beyond
the wall is moved clear. A locked building never moves, so it stops the
dragged building, and it holds a wall back too. So does water. If a step
can't be fitted in, it is undone and the dragged building tries to slide
along the obstacle instead.

Neighbouring buildings often share corner points, so a building is never
moved by changing its points. It gets new ones instead. The polygons
themselves stay in their wards, so drawing and exports see the moves.
"""

import math

from .geometry import Point
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
WALL_EASE = 0.05  # How far past the limit a wall is moved each time.
WALL_TRIES = 4  # How many times one building may move a wall in a step.
MAX_SLIDES = 200  # The most steps one pointer move can take along an obstacle.
MAX_PUSHES_PER_MOVE = 2000  # The shoving allowed for one move of the pointer.
RETRY_DISTANCE = 1.0  # How far the pointer must go before a stuck drag retries.


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


def _gap_to_hull(hull, polygon, part):
    """How far a building is from a piece of wall, past its margin."""
    ax, ay, bx, by, margin = part[:5]
    count = len(hull)
    nearest = math.inf
    for i in range(count):
        px, py = hull[i]
        qx, qy = hull[(i + 1) % count]
        if _segments_cross(px, py, qx, qy, ax, ay, bx, by):
            return -margin
        nearest = min(nearest,
                      _distance_to_segment(px, py, ax, ay, bx, by),
                      _distance_to_segment(ax, ay, px, py, qx, qy),
                      _distance_to_segment(bx, by, px, py, qx, qy))
    if polygon.contains_point(Point(ax, ay)):
        return -margin
    return nearest - margin


class Building:
    """One building, and the convex outline used for collisions."""

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
        self.polygon[:] = [Point(x, y) for x, y in corners]
        self._measure(corners)

    def _measure(self, corners):
        self.hull = convex_hull(corners)
        self.cx = sum(c[0] for c in corners) / len(corners)
        self.cy = sum(c[1] for c in corners) / len(corners)
        self.radius = max(math.hypot(x - self.cx, y - self.cy)
                          for x, y in corners)

    def shift(self, dx, dy):
        self.place([(x + dx, y + dy) for x, y in self.corners()])

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
        self.wall_parts = {}
        self.all_wall_parts = {}
        self.wall_allowance = {}
        self.squeezed = {}
        self.pushes_spent = 0
        self._stuck_at = None

        for patch in model.patches:
            for polygon in list(patch.ward.geometry) + list(patch.ward.landmarks):
                if len(polygon) >= 3:
                    self.buildings.append(Building(polygon, patch.ward))
        for building in self.buildings:
            self._index(building)
        self._index_walls()
        self._note_wall_allowances()

    def _walls(self):
        walls = []
        if self.model.wall is not None:
            walls.append((self.model.wall, THICK_STROKE))
        if self.model.citadel is not None:
            walls.append((self.model.citadel.ward.wall, THICK_STROKE * 1.5))
        return walls

    def _index_walls(self):
        """Note which squares of map have walls, gates or towers in them.

        Each part keeps the points it came from, so that it can be moved.
        """
        self.wall_parts = {}
        self.all_wall_parts = {}
        for wall, tower_radius in self._walls():
            line = THICK_STROKE / 2 + WALL_MARGIN
            for i, (a, b) in enumerate(wall.shape.edges()):
                if wall.segments[i]:
                    self._add_wall_part(a.x, a.y, b.x, b.y, line, a, b)
            for t in wall.towers:
                self._add_wall_part(t.x, t.y, t.x, t.y,
                                    tower_radius + WALL_MARGIN, t, t)
            for gate in wall.gates:
                along = wall.shape.next(gate).subtract(wall.shape.prev(gate))
                along = along.norm(THICK_STROKE * 1.5)
                self._add_wall_part(gate.x - along.x, gate.y - along.y,
                                    gate.x + along.x, gate.y + along.y,
                                    THICK_STROKE + WALL_MARGIN, gate, gate)

    def _note_wall_allowances(self):
        """Let buildings that start out close to a wall stay that close."""
        for building in self.buildings:
            gap = self._wall_gap(building)
            if gap < 0:
                self.wall_allowance[building] = gap

    def _add_wall_part(self, ax, ay, bx, by, margin, a, b):
        part = (ax, ay, bx, by, margin, a, b)
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
        return min((_gap_to_hull(building.hull, building.polygon, part)
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
            gap = _gap_to_hull(building.hull, building.polygon, part)
            if gap < lowest:
                lowest = gap
                tightest = part
        return tightest, limit - lowest

    @staticmethod
    def _away_from(part, x, y):
        """The way a piece of wall lies from a point, as a unit vector."""
        ax, ay, bx, by = part[:4]
        if ax == bx and ay == by:
            nx, ny = ax - x, ay - y
        else:
            nx, ny = ay - by, bx - ax
            if nx * (ax - x) + ny * (ay - y) < 0:
                nx, ny = -nx, -ny
        size = math.hypot(nx, ny) or 1.0
        return nx / size, ny / size

    def _clear_walls(self, building, moved_walls):
        """Move any wall this building has reached. False if it won't go."""
        for _ in range(WALL_TRIES):
            part, depth = self._tightest_wall_part(building)
            if part is None:
                return True

            fixed = self.model.water_points
            free = [p for p in dict.fromkeys(part[5:7]) if p not in fixed]
            if not free:
                return False

            cx, cy = building.center()
            nx, ny = self._away_from(part, cx, cy)
            # With one end held, the other has to swing further.
            amount = (depth + WALL_EASE) * (2 / len(free) if len(part[5:7]) > 1
                                            and part[5] is not part[6] else 1)
            for point in free:
                moved_walls.setdefault(point, (point.x, point.y))
                point.x += nx * amount
                point.y += ny * amount
            self._index_walls()
            self._note_squeezed(building, free)
        return self._tightest_wall_part(building)[0] is None

    def _note_squeezed(self, pusher, points):
        """Find the buildings a moved piece of wall has run into."""
        for part in self.all_wall_parts:
            if part[5] not in points and part[6] not in points:
                continue
            for cell in self._cells_along(part, spread=1):
                for building in self.grid.get(cell, {}):
                    if (building is pusher or building in self.squeezed
                            or not building.may_reach(part)):
                        continue
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

    def _on_water(self, building):
        model = self.model
        for x, y in building.corners():
            if model.sea is not None and model.sea.contains_point(Point(x, y)):
                return True
            reach = RIVER_WIDTH / 2 + RIVER_MARGIN
            for a, b in zip(model.river, model.river[1:]):
                if _distance_to_segment(x, y, a.x, a.y, b.x, b.y) < reach:
                    return True
        return False

    def _try_step(self, mover, dx, dy):
        """Move a building and clear its way. False if it won't fit."""
        before = {}
        moved_walls = {}
        self.squeezed = {}

        def place_back(building, x, y):
            building.shift(-x, -y)
            self._reindex(building)
            return False

        def shift(building, x, y, move_walls=True):
            """Move a building. False if something solid is in the way."""
            before.setdefault(building, building.corners())
            building.shift(x, y)
            self._reindex(building)
            if self._on_water(building):
                return place_back(building, x, y)
            if move_walls and not self._clear_walls(building, moved_walls):
                return place_back(building, x, y)
            return True

        def give_up():
            for building, corners in before.items():
                building.place(corners)
                self._reindex(building)
            for point, (x, y) in moved_walls.items():
                point.x = x
                point.y = y
            if moved_walls:
                self._index_walls()
            self.squeezed = {}
            return False

        if not shift(mover, dx, dy):
            return give_up()

        waiting = [mover]
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
                nx, ny = self._away_from(part, *building.center())
                amount = needed + WALL_EASE
                before.setdefault(building, building.corners())
                building.shift(-nx * amount, -ny * amount)
                self._reindex(building)
                if self._on_water(building):
                    return give_up()
                if building not in waiting:
                    waiting.append(building)

            if not waiting:
                break
            active = waiting.pop(0)
            for other in self._nearby(active):
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
        return True

    def begin_move(self, building):
        """Start a drag. Returns False for a locked building."""
        if building in self.locked:
            return False
        self._drag_start = {}
        self._drag_walls = {}
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
        if self._drag_start:
            self.history.append((self._drag_start, self._drag_walls))
        self._drag_start = None
        self._drag_walls = None
        self._drag_origin = None

    def undo(self):
        """Put back everything the last drag moved, walls included."""
        if not self.history:
            return False
        buildings, walls = self.history.pop()
        for building, corners in buildings.items():
            building.place(corners)
            self._reindex(building)
        for point, (x, y) in walls.items():
            point.x = x
            point.y = y
        self._index_walls()
        return True
