"""Moving and locking buildings by hand.

This module is original to this port, and nothing in it needs Qt.

A dragged building pushes aside whatever it runs into, and those buildings
push others in turn. A locked building never moves, so it stops whatever
pushes against it. So does water. If a step can't be fitted in, the whole
step is undone, which makes the dragged building stop at the obstacle.

Neighbouring buildings often share corner points, so a building is never
moved by changing its points. It gets new ones instead. The polygons
themselves stay in their wards, so drawing and exports see the moves.
"""

import math

from .geometry import Point
from .water import RIVER_WIDTH

CELL = 16.0  # The size of the squares used to find nearby buildings.
MAX_STEP = 1.0  # A long drag is taken in steps of this size.
MAX_PUSHES = 2000  # How much shoving one step may cause before giving up.
TOUCHING = 0.05  # Overlaps smaller than this are neighbours just touching.
PUSH_GAP = 0.15  # Pushed buildings end up this far apart.
RIVER_MARGIN = 0.3


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


def _distance_to_segment(px, py, a, b):
    dx = b.x - a.x
    dy = b.y - a.y
    length = dx * dx + dy * dy
    if length == 0:
        return math.hypot(px - a.x, py - a.y)
    t = max(0.0, min(1.0, ((px - a.x) * dx + (py - a.y) * dy) / length))
    return math.hypot(px - a.x - t * dx, py - a.y - t * dy)


class Building:
    """One building, and the convex outline used for collisions."""

    __slots__ = ("polygon", "ward", "hull", "cells")

    def __init__(self, polygon, ward):
        self.polygon = polygon
        self.ward = ward
        self.hull = convex_hull([(v.x, v.y) for v in polygon])
        self.cells = ()

    def corners(self):
        return [(v.x, v.y) for v in self.polygon]

    def place(self, corners):
        """Give the building new points, leaving its neighbours' alone."""
        self.polygon[:] = [Point(x, y) for x, y in corners]
        self.hull = convex_hull(corners)

    def shift(self, dx, dy):
        self.place([(x + dx, y + dy) for x, y in self.corners()])

    def center(self):
        corners = self.corners()
        return (sum(c[0] for c in corners) / len(corners),
                sum(c[1] for c in corners) / len(corners))


class CityEditor:
    """The moves and locks made to one generated city."""

    def __init__(self, model):
        self.model = model
        self.buildings = []
        self.locked = set()
        self.history = []
        self.grid = {}
        self._drag_start = None
        self._drag_origin = None

        for patch in model.patches:
            for polygon in list(patch.ward.geometry) + list(patch.ward.landmarks):
                if len(polygon) >= 3:
                    self.buildings.append(Building(polygon, patch.ward))
        for building in self.buildings:
            self._index(building)

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
                if _distance_to_segment(x, y, a, b) < reach:
                    return True
        return False

    def _try_step(self, mover, dx, dy):
        """Move a building and shove the others. False if it won't fit."""
        before = {}

        def shift(building, x, y):
            before.setdefault(building, building.corners())
            building.shift(x, y)
            self._reindex(building)

        def give_up():
            for building, corners in before.items():
                building.place(corners)
                self._reindex(building)
            return False

        shift(mover, dx, dy)
        if self._on_water(mover):
            return give_up()

        waiting = [mover]
        queued = {mover}
        pushes = 0
        while waiting:
            active = waiting.pop(0)
            queued.discard(active)

            for other in self._nearby(active):
                push = overlap(active.hull, other.hull)
                if push is None:
                    continue

                pushes += 1
                if pushes > MAX_PUSHES:
                    return give_up()

                if other is mover or other in self.locked:
                    # This one can't give way, so the active one must.
                    if active is mover or active in self.locked:
                        return give_up()
                    shift(active, -push[0], -push[1])
                    if self._on_water(active):
                        return give_up()
                    if active not in queued:
                        waiting.append(active)
                        queued.add(active)
                    break

                shift(other, push[0], push[1])
                if self._on_water(other):
                    return give_up()
                if other not in queued:
                    waiting.append(other)
                    queued.add(other)

        if self._drag_start is not None:
            for building, corners in before.items():
                self._drag_start.setdefault(building, corners)
        return True

    def begin_move(self, building):
        """Start a drag. Returns False for a locked building."""
        if building in self.locked:
            return False
        self._drag_start = {}
        self._drag_origin = building.center()
        return True

    def drag_to(self, building, offset_x, offset_y):
        """Take a dragged building towards an offset from where it started.

        Returns True if it reached the offset. If something stops it, it
        waits at the obstacle, and catches up once the pointer comes clear.
        """
        if self._drag_origin is None or building in self.locked:
            return False

        while True:
            cx, cy = building.center()
            dx = self._drag_origin[0] + offset_x - cx
            dy = self._drag_origin[1] + offset_y - cy
            distance = math.hypot(dx, dy)
            if distance < 0.01:
                return True
            step = min(1.0, MAX_STEP / distance)
            if not self._try_step(building, dx * step, dy * step):
                return False

    def end_move(self):
        """Finish a drag, so that it can be undone as one step."""
        if self._drag_start:
            self.history.append(self._drag_start)
        self._drag_start = None
        self._drag_origin = None

    def undo(self):
        """Put back everything the last drag moved."""
        if not self.history:
            return False
        for building, corners in self.history.pop().items():
            building.place(corners)
            self._reindex(building)
        return True
