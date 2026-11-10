"""Roads and streets as the map draws them.

This module is original to this port. The original draws only the roads
outside town, and leaves the streets as the gaps between the wards. Here:

- Each road carries on through its gate as the main street to the centre.
- The other gaps between wards in town get a street, drawn as a single line.
- A street runs just inside the city wall wherever no building is near it.
- Roads and streets meet bridges end on, so traffic can cross them. A way
  that crosses the river runs straight over its bridge, a street from a
  bridge starts at the bridge's end, and a bridge end with no way at it gets
  a short street to the nearest one on its bank.

All of it is worked out from where the buildings are each time the map is
drawn. Roads and streets bend smoothly round any building moved onto them,
and straighten again when it moves away, so they follow every edit and undo.
Buildings still where the city put them never bend a way, since some stand
right at the edge of one to begin with.

Ways keep clear of the buildings themselves, not their plots, so a way can
cross a garden to get round a house. They are drawn over the gardens.
"""

import math

from .geometry import Point, chaikin, convex_hull
from .wards import MAIN_STREET, Market, Ward
from .water import BRIDGE_WIDTH, RIVER_WIDTH

ROAD_HALF = MAIN_STREET / 2  # The room a road needs each side of its line.
STREET_HALF = 0.25  # The same for a street.
# A building reaching less than this into a way is no trouble. Some stand
# that close when the city is built.
TOLERANCE = 0.35
BEND_GAP = 0.25  # Kept between a bent way and the building it goes round.
EASE = 6.0  # How far a bend takes to ease in and out.
SAMPLE = 0.5  # The spacing of the points a way is checked at.
BEND_TRIES = 8
MAX_BEND = 6.0  # A way needing a longer detour than this stays put.

WALL_STREET = 2.0  # From the middle of the wall to the street inside it.
WALL_STREET_ROOM = 0.6  # Clear ground the street needs each side.
WALL_STREET_STEP = 1.0
MIN_WALL_STREET = 8.0  # Shorter stretches aren't worth a street.
RIVER_ROOM = RIVER_WIDTH / 2 + 1.0

CELL = 8.0

# Streets stop this far from the middle of a road, at the outside of its
# edge line, and are cut this finely to find where.
ROAD_EDGE = MAIN_STREET / 2 + 0.15
CLIP_STEP = 0.25
ROAD_ROUNDING = 2  # As the map draws roads.

BRIDGE_LINK = 15.0  # How far a bridge end looks for a way to join.
LINKED = 0.5  # A way this close to a bridge end already meets it.


def _outlines(model):
    """Each building's outline entry, and whether it has moved.

    The outlines are kept on the model between drawings and only made again
    for buildings that have moved since, which is few while editing.
    """
    kept = model.__dict__.setdefault("_way_outlines", {})
    found = []
    for patch in model.patches:
        ward = patch.ward
        if isinstance(ward, Market):
            continue
        for polygon in list(ward.geometry) + list(ward.landmarks):
            if len(polygon) < 3:
                continue
            footprint = getattr(polygon, "house", polygon)
            spot = (footprint[0].x, footprint[0].y, len(footprint))
            entry = kept.get(id(footprint))
            if entry is None or entry[0] != spot:
                hull = convex_hull([(v.x, v.y) for v in footprint])
                xs = [x for x, _ in hull]
                ys = [y for _, y in hull]
                entry = (spot, (hull, sum(xs) / len(xs), sum(ys) / len(ys),
                                min(xs), min(ys), max(xs), max(ys)))
                kept[id(footprint)] = entry
            found.append((entry[1], model.has_moved(polygon)))
    return found


class _Obstacles:
    """The buildings, as convex outlines in a grid for finding them quickly.

    A building on a plot counts as its house, not the whole plot.
    """

    def __init__(self, entries):
        self.grid = {}
        self.entries = entries
        for entry in entries:
            hull, _, _, left, top, right, bottom = entry
            for i in range(int(left // CELL), int(right // CELL) + 1):
                for j in range(int(top // CELL), int(bottom // CELL) + 1):
                    self.grid.setdefault((i, j), []).append(entry)

    def near(self, x, y, reach):
        found = {}
        for i in range(int((x - reach) // CELL), int((x + reach) // CELL) + 1):
            for j in range(int((y - reach) // CELL),
                           int((y + reach) // CELL) + 1):
                for entry in self.grid.get((i, j), ()):
                    if (entry[3] - reach <= x <= entry[5] + reach
                            and entry[4] - reach <= y <= entry[6] + reach):
                        found[id(entry)] = entry
        return found.values()

    def distance(self, x, y, reach):
        """How far a point is from the nearest building, up to reach."""
        nearest = reach
        for hull, *_ in self.near(x, y, reach):
            nearest = min(nearest, _to_hull(hull, x, y))
        return nearest


def _to_hull(hull, x, y):
    """Distance from a point to a convex outline, 0 inside it."""
    inside = True
    nearest = math.inf
    count = len(hull)
    for i in range(count):
        ax, ay = hull[i]
        bx, by = hull[(i + 1) % count]
        dx = bx - ax
        dy = by - ay
        if dx * (y - ay) - dy * (x - ax) < 0:
            inside = False
        length = dx * dx + dy * dy
        t = ((x - ax) * dx + (y - ay) * dy) / length if length else 0.0
        t = max(0.0, min(1.0, t))
        nearest = min(nearest, math.hypot(x - ax - t * dx, y - ay - t * dy))
    if count >= 3 and inside:
        return 0.0
    return nearest


def _samples(line):
    """Points along a line about SAMPLE apart, each with its direction.

    The line's own corners are kept, marked True.
    """
    out = []
    for (ax, ay), (bx, by) in zip(line, line[1:]):
        length = math.hypot(bx - ax, by - ay)
        if length == 0:
            continue
        tx = (bx - ax) / length
        ty = (by - ay) / length
        steps = max(1, math.ceil(length / SAMPLE))
        for k in range(steps):
            t = k / steps
            out.append((ax + (bx - ax) * t, ay + (by - ay) * t, tx, ty, k == 0))
    if out:
        x, y = line[-1]
        out.append((x, y, out[-1][2], out[-1][3], True))
    # A corner faces halfway between the ways in and out of it, so that a
    # bend there doesn't jump from one side to the other.
    for i in range(1, len(out) - 1):
        x, y, tx, ty, corner = out[i]
        if corner:
            bx = out[i - 1][2] + tx
            by = out[i - 1][3] + ty
            size = math.hypot(bx, by)
            if size > 1e-9:
                out[i] = (x, y, bx / size, by / size, True)
    return out


def _conflicts(obstacles, px, py, tx, ty, half):
    """The buildings in a way's path at a point, as their extent across it."""
    nx, ny = -ty, tx
    found = []
    for hull, *_ in obstacles.near(px, py, half + 1.0):
        along = [(hx - px) * tx + (hy - py) * ty for hx, hy in hull]
        if max(along) < -half or min(along) > half:
            continue
        across = [(hx - px) * nx + (hy - py) * ny for hx, hy in hull]
        low = min(across)
        high = max(across)
        room = half - TOLERANCE
        if high > -room and low < room:
            found.append((low, high))
    return found


def _push_at(obstacles, x, y, tx, ty, half, side):
    """How far across its line a way must move at a point to clear buildings,
    going round them on one side, +1 or -1."""
    nx, ny = -ty, tx
    shift = 0.0
    for _ in range(BEND_TRIES):
        found = _conflicts(obstacles, x + nx * shift, y + ny * shift,
                           tx, ty, half)
        if not found:
            return shift
        if side > 0:
            shift += max(high for _, high in found) + half + BEND_GAP
        else:
            shift += min(low for low, _ in found) - half - BEND_GAP
    return shift


def bend_around(line, moved, half, everything=None):
    """A way's line, bent round any moved building in its way.

    line is a list of (x, y). It comes back as it was if no moved building
    is in the way. Otherwise it gains points where it bends, easing in and
    out. The bend keeps clear of everything, moved or not. Each stretch with
    buildings in the way goes round whichever side is the shorter detour,
    so it never weaves from one side to the other. A stretch with no room
    either side within MAX_BEND stays where it is.
    """
    everything = moved if everything is None else everything
    # Nothing moved near the way leaves it as it is, without looking along it.
    margin = half + 1.0
    left = min(x for x, _ in line) - margin
    right = max(x for x, _ in line) + margin
    top = min(y for _, y in line) - margin
    bottom = max(y for _, y in line) + margin
    entries = getattr(moved, "entries", None)
    if entries is not None and not any(
            e[3] <= right and e[5] >= left and e[4] <= bottom and e[6] >= top
            for e in entries):
        return list(line)
    samples = _samples(line)
    if not samples:
        return list(line)
    blocked = [bool(_conflicts(moved, x, y, tx, ty, half))
               for x, y, tx, ty, _ in samples]
    if not any(blocked):
        return list(line)

    # Group the blocked points into stretches, joining ones close together.
    reach = max(1, round(EASE / 2 / SAMPLE))
    stretches = []
    for i, hit in enumerate(blocked):
        if not hit:
            continue
        if stretches and i - stretches[-1][-1] <= 2 * reach:
            stretches[-1].append(i)
        else:
            stretches.append([i])

    shifts = [0.0] * len(samples)
    for stretch in stretches:
        indices = range(stretch[0], stretch[-1] + 1)
        options = []
        for side in (1, -1):
            pushes = {i: _push_at(everything, *samples[i][:4], half, side)
                      for i in indices}
            options.append((max(abs(v) for v in pushes.values()), pushes))
        detour, pushes = min(options, key=lambda option: option[0])
        if detour > MAX_BEND:
            continue
        for i, value in pushes.items():
            shifts[i] = value

    if not any(shifts):
        return list(line)
    eased = _ease(shifts, reach)
    # The ends stay put, so a way still meets its gate, square or junction,
    # and a bend eases in from them.
    last = len(eased) - 1
    for i in range(len(eased)):
        from_end = min(i, last - i) * SAMPLE
        if from_end < EASE:
            eased[i] *= from_end / EASE

    bent = []
    for i, (x, y, tx, ty, corner) in enumerate(samples):
        keep = (corner or abs(eased[i]) > 1e-9
                or (i > 0 and abs(eased[i - 1]) > 1e-9)
                or (i + 1 < len(eased) and abs(eased[i + 1]) > 1e-9))
        if not keep:
            continue
        point = (x - ty * eased[i], y + tx * eased[i])
        # On the inside of a tight turn a bent way can loop back on itself,
        # so a point that would take it backwards is left out.
        if bent and ((point[0] - bent[-1][0]) * tx
                     + (point[1] - bent[-1][1]) * ty) <= 0:
            continue
        bent.append(point)
    return bent


def _ease(shifts, reach):
    """A smooth version of the shifts, never less than any of them.

    Each side is widened to the biggest shift within reach, then averaged
    over the same reach. The average of a widened peak still covers the
    peak, so the way still clears the building, and it eases in and out
    over twice the reach. Where buildings on both sides push, the bigger
    push wins.
    """
    count = len(shifts)

    def widened(values):
        return [max(values[max(0, i - reach):i + reach + 1])
                for i in range(count)]

    def averaged(values):
        total = [0.0]
        for value in values:
            total.append(total[-1] + value)
        out = []
        for i in range(count):
            low = max(0, i - reach)
            high = min(count, i + reach + 1)
            out.append((total[high] - total[low]) / (high - low))
        return out

    ahead = averaged(widened([max(shift, 0.0) for shift in shifts]))
    behind = averaged(widened([max(-shift, 0.0) for shift in shifts]))
    return [a if a >= b else -b for a, b in zip(ahead, behind)]


def _xy(points):
    return [(v.x, v.y) for v in points]


def _main_ways(model):
    """Each road joined to its main street, and the main streets alone."""
    joined = []
    used = set()
    for road in model.roads:
        gate = road[-1]
        street = next((s for s in model.streets if s[0] is gate), None)
        if street is not None:
            used.add(id(street))
            joined.append(_xy(road) + _xy(street[1:]))
        else:
            joined.append(_xy(road))
    joined += [_xy(s) for s in model.streets if id(s) not in used]
    return joined


def _side_streets(model):
    """The edges between wards in town that no road or wall runs along."""
    on_ways = set()
    for artery in model.arteries:
        for a, b in zip(artery, artery[1:]):
            on_ways.add((id(a), id(b)))
            on_ways.add((id(b), id(a)))

    def open_square(patch):
        # Squares and empty land have no street through them.
        return (patch is model.plaza or isinstance(patch.ward, Market)
                or type(patch.ward) is Ward)

    owners = {}
    for patch in model.patches:
        for a, b in patch.shape.edges():
            owners.setdefault((id(a), id(b)), []).append(patch)

    lines = []
    seen = set()
    for patch in model.patches:
        if not patch.within_city or open_square(patch):
            continue
        if patch is model.citadel:
            continue
        for a, b in patch.shape.edges():
            key = (id(a), id(b))
            if key in seen or key in on_ways:
                continue
            seen.add(key)
            seen.add((id(b), id(a)))
            other = owners.get((id(b), id(a)), [])
            if not other:
                continue
            neighbour = other[0]
            if (not neighbour.within_city or open_square(neighbour)
                    or neighbour is model.citadel):
                continue
            if ((a, b) in model.river_edges or (b, a) in model.river_edges
                    or (a, b) in model.shore_edges
                    or (b, a) in model.shore_edges):
                continue
            if model.wall is not None and (
                    model.wall.borders_by(patch, a, b)
                    or model.wall.borders_by(neighbour, b, a)):
                continue
            lines.append([(a.x, a.y), (b.x, b.y)])
    return lines


def _on_water(model, x, y):
    if model.sea is not None and model.sea.contains_point(Point(x, y)):
        return True
    return _Water.of(model, RIVER_ROOM, bridges=False).covers(x, y)


def _wall_streets(model, obstacles):
    """Stretches of street just inside the city wall, where there's room."""
    wall = model.wall
    if wall is None:
        return []

    shape = wall.shape
    count = len(shape)
    area = sum(a.x * b.y - b.x * a.y for a, b in shape.edges())
    inward = 1.0 if area > 0 else -1.0

    def normal(a, b):
        length = math.hypot(b.x - a.x, b.y - a.y) or 1.0
        return (-(b.y - a.y) / length * inward, (b.x - a.x) / length * inward)

    # The line WALL_STREET inside the wall, with mitred corners.
    offset = []
    for i in range(count):
        before = normal(shape[i - 1], shape[i])
        after = normal(shape[i], shape[(i + 1) % count])
        nx = before[0] + after[0]
        ny = before[1] + after[1]
        size = math.hypot(nx, ny)
        if size < 1e-9:
            nx, ny = after
        else:
            nx /= size
            ny /= size
        cos = max(0.5, nx * after[0] + ny * after[1])
        reach = WALL_STREET / cos
        offset.append((shape[i].x + nx * reach, shape[i].y + ny * reach))

    castle = model.citadel.ward.wall.shape if model.citadel else None
    runs = []
    run = []
    for i in range(count):
        if not wall.segments[i]:
            if run:
                runs.append(run)
            run = []
            continue
        (ax, ay), (bx, by) = offset[i], offset[(i + 1) % count]
        steps = max(1, math.ceil(math.hypot(bx - ax, by - ay)
                                 / WALL_STREET_STEP))
        for k in range(steps):
            x = ax + (bx - ax) * k / steps
            y = ay + (by - ay) * k / steps
            clear = (obstacles.distance(x, y, WALL_STREET_ROOM)
                     >= WALL_STREET_ROOM
                     and shape.contains_point(Point(x, y))
                     and not _on_water(model, x, y)
                     and (castle is None
                          or not castle.contains_point(Point(x, y))))
            if clear:
                run.append((x, y))
            elif run:
                runs.append(run)
                run = []
    if run:
        # Join up with the first run if the wall's start was clear too.
        if runs and wall.segments[0] and runs[0][0] == (
                offset[0][0], offset[0][1]):
            runs[0] = run + runs[0]
        else:
            runs.append(run)

    def length(points):
        return sum(math.hypot(b[0] - a[0], b[1] - a[1])
                   for a, b in zip(points, points[1:]))

    return [r for r in runs if length(r) >= MIN_WALL_STREET]


class _Roads:
    """The pieces of the roads as drawn, in a grid, for trimming streets."""

    def __init__(self, roads):
        self.grid = {}
        for road in roads:
            line = chaikin(road, ROAD_ROUNDING)
            for a, b in zip(line, line[1:]):
                piece = (a, b)
                for i in range(int((min(a[0], b[0]) - ROAD_EDGE) // CELL),
                               int((max(a[0], b[0]) + ROAD_EDGE) // CELL) + 1):
                    for j in range(
                            int((min(a[1], b[1]) - ROAD_EDGE) // CELL),
                            int((max(a[1], b[1]) + ROAD_EDGE) // CELL) + 1):
                        self.grid.setdefault((i, j), []).append(piece)

    def covers(self, x, y):
        for (ax, ay), (bx, by) in self.grid.get(
                (int(x // CELL), int(y // CELL)), ()):
            dx = bx - ax
            dy = by - ay
            length = dx * dx + dy * dy
            t = ((x - ax) * dx + (y - ay) * dy) / length if length else 0.0
            t = max(0.0, min(1.0, t))
            if math.hypot(x - ax - t * dx, y - ay - t * dy) < ROAD_EDGE:
                return True
        return False


def _edge_between(roads, inside, outside):
    """Where between two points a road's edge is, found by halving."""
    for _ in range(12):
        middle = ((inside[0] + outside[0]) / 2, (inside[1] + outside[1]) / 2)
        if roads.covers(*middle):
            inside = middle
        else:
            outside = middle
    return outside


def trim(line, roads):
    """A line with the parts that roads covers taken out, as separate lines.

    roads is anything with a covers(x, y) and a grid, such as the roads or
    the river.
    """
    if not _grid_touches(roads.grid, line):
        return [list(line)]
    points = []
    for a, b in zip(line, line[1:]):
        if not _segment_touches(roads.grid, a, b):
            points.append(a)  # Nothing near this stretch to cut it.
            continue
        steps = max(1, math.ceil(math.dist(a, b) / CLIP_STEP))
        points += [(a[0] + (b[0] - a[0]) * k / steps,
                    a[1] + (b[1] - a[1]) * k / steps) for k in range(steps)]
    points.append(line[-1])

    pieces = []
    current = []
    last_on_road = None
    covered = False
    for point in points:
        if roads.covers(*point):
            covered = True
            if current:
                current.append(_edge_between(roads, point, current[-1]))
                pieces.append(current)
                current = []
            last_on_road = point
            continue
        if not current and last_on_road is not None:
            # Coming off a road, so start at its edge.
            current = [_edge_between(roads, last_on_road, point)]
        current.append(point)
        last_on_road = None
    if current:
        pieces.append(current)
    if not covered:
        return [list(line)]
    return [_tidy(piece) for piece in pieces
            if len(piece) >= 2 and _length(piece) > CLIP_STEP]


def _tidy(points):
    """Drop the steps that lie on a straight run, keeping the bends."""
    kept = [points[0]]
    for before, point, after in zip(points, points[1:], points[2:]):
        cross = ((point[0] - before[0]) * (after[1] - point[1])
                 - (point[1] - before[1]) * (after[0] - point[0]))
        if abs(cross) > 1e-9:
            kept.append(point)
    kept.append(points[-1])
    return kept


def _grid_touches(grid, line):
    """Whether any square of a grid near a line has something in it."""
    left = int(min(x for x, _ in line) // CELL)
    right = int(max(x for x, _ in line) // CELL)
    top = int(min(y for _, y in line) // CELL)
    bottom = int(max(y for _, y in line) // CELL)
    if (right - left + 1) * (bottom - top + 1) > len(grid):
        return any(left <= i <= right and top <= j <= bottom
                   for i, j in grid)
    return any((i, j) in grid for i in range(left, right + 1)
               for j in range(top, bottom + 1))


def _segment_touches(grid, a, b):
    """Whether any square of a grid along a stretch has something in it."""
    steps = max(1, math.ceil(math.dist(a, b) / (CELL / 2)))
    for k in range(steps + 1):
        x = a[0] + (b[0] - a[0]) * k / steps
        y = a[1] + (b[1] - a[1]) * k / steps
        if (int(x // CELL), int(y // CELL)) in grid:
            return True
    return False


class _Water:
    """The river, less its bridges, for stopping ways at the water's edge.

    Its pieces are kept in a grid, since every point of every way asks.
    """

    def __init__(self, model, reach=RIVER_WIDTH / 2, bridges=True):
        self.bridges = ([((a.x, a.y), (b.x, b.y)) for a, b in model.bridges]
                        if bridges else [])
        self.reach = reach
        self.grid = {}
        # The river runs on far past the map, where no way goes.
        view = getattr(model, "view_radius", model.city_radius * 1.1)
        limit = int(view * 1.5 // CELL) + 1
        river = [(v.x, v.y) for v in model.river]
        for a, b in zip(river, river[1:]):
            for i in range(
                    max(-limit, int((min(a[0], b[0]) - reach) // CELL)),
                    min(limit, int((max(a[0], b[0]) + reach) // CELL)) + 1):
                for j in range(
                        max(-limit, int((min(a[1], b[1]) - reach) // CELL)),
                        min(limit, int((max(a[1], b[1]) + reach) // CELL))
                        + 1):
                    if _to_xy_segment((i + 0.5) * CELL, (j + 0.5) * CELL,
                                      a, b) < reach + CELL:
                        self.grid.setdefault((i, j), []).append((a, b))

    @staticmethod
    def of(model, reach=RIVER_WIDTH / 2, bridges=True):
        """The water for a model, kept on it since the river never moves."""
        kept = model.__dict__.setdefault("_way_water", {})
        key = (reach, bridges)
        if key not in kept:
            kept[key] = _Water(model, reach, bridges)
        return kept[key]

    def covers(self, x, y):
        pieces = self.grid.get((int(x // CELL), int(y // CELL)))
        if not pieces or not any(_to_xy_segment(x, y, a, b) < self.reach
                                 for a, b in pieces):
            return False
        return not any(_to_xy_segment(x, y, a, b) < BRIDGE_WIDTH / 2
                       for a, b in self.bridges)


def _to_xy_segment(x, y, a, b):
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    length = dx * dx + dy * dy
    t = ((x - a[0]) * dx + (y - a[1]) * dy) / length if length else 0.0
    t = max(0.0, min(1.0, t))
    return math.hypot(x - a[0] - t * dx, y - a[1] - t * dy)


def _bridge_ends(model):
    """Each bridge's middle point, as (x, y), and its two ends."""
    ends = {}
    for a, b in model.bridges:
        middle = ((a.x + b.x) / 2, (a.y + b.y) / 2)
        ends[middle] = ((a.x, a.y), (b.x, b.y))
    return ends


def _close(p, q):
    return abs(p[0] - q[0]) < 1e-6 and abs(p[1] - q[1]) < 1e-6


def onto_bridges(line, ends):
    """A way that meets bridges end on, instead of at their middles.

    A way crossing a bridge's middle runs from one end to the other. A way
    starting or stopping at a bridge's middle starts or stops at the end on
    its own bank.
    """
    out = []
    for i, point in enumerate(line):
        bridge = next((pair for middle, pair in ends.items()
                       if _close(point, middle)), None)
        if bridge is None:
            out.append(point)
            continue
        before = line[i - 1] if i > 0 else None
        after = line[i + 1] if i + 1 < len(line) else None
        first, second = bridge
        if before is not None:
            # The end nearer where the way comes from comes first.
            if math.dist(second, before) < math.dist(first, before):
                first, second = second, first
            out.append(first)
            if after is not None:
                out.append(second)
        elif after is not None:
            near = min(bridge, key=lambda end: math.dist(end, after))
            out.append(near)
    return out


def _crosses_river(model, a, b):
    steps = max(1, math.ceil(math.dist(a, b) / CLIP_STEP))
    reach = RIVER_WIDTH / 2
    for k in range(1, steps):
        x = a[0] + (b[0] - a[0]) * k / steps
        y = a[1] + (b[1] - a[1]) * k / steps
        for c, d in zip(model.river, model.river[1:]):
            if _to_segment_xy(x, y, c, d) < reach:
                return True
    return False


def _to_segment_xy(x, y, a, b):
    dx = b.x - a.x
    dy = b.y - a.y
    length = dx * dx + dy * dy
    t = ((x - a.x) * dx + (y - a.y) * dy) / length if length else 0.0
    t = max(0.0, min(1.0, t))
    return math.hypot(x - a.x - t * dx, y - a.y - t * dy)


def _nearest_on(lines, point):
    """The nearest point on any of the lines, and how far it is."""
    best = None
    gap = math.inf
    for line in lines:
        for a, b in zip(line, line[1:]):
            dx = b[0] - a[0]
            dy = b[1] - a[1]
            length = dx * dx + dy * dy
            t = (((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length
                 if length else 0.0)
            t = max(0.0, min(1.0, t))
            spot = (a[0] + t * dx, a[1] + t * dy)
            here = math.dist(spot, point)
            if here < gap:
                best = spot
                gap = here
    return best, gap


def _bridge_links(model, ends, lines):
    """Short streets from bridge ends that no way meets yet."""
    links = []
    for first, second in ends.values():
        for end in (first, second):
            if any(_close(end, p) for line in lines for p in (line[0],
                                                               line[-1])):
                continue
            spot, gap = _nearest_on(lines, end)
            if spot is None or gap <= LINKED:
                continue
            if gap > BRIDGE_LINK or _crosses_river(model, end, spot):
                # Look along the ways for the nearest point on this bank.
                spot = None
                gap = BRIDGE_LINK
                for line in lines:
                    for p in line:
                        here = math.dist(p, end)
                        if here < gap and not _crosses_river(model, end, p):
                            spot = p
                            gap = here
                if spot is None:
                    continue
            links.append([end, spot])
    return links


def ways(model):
    """Every road and street to draw, as lists of (x, y).

    Returns the roads, which include the main streets in town, then the side
    streets, then the stretches of street inside the wall.
    """
    outlines = _outlines(model)
    moved = _Obstacles([entry for entry, has_moved in outlines if has_moved])
    everything = _Obstacles([entry for entry, _ in outlines])
    ends = _bridge_ends(model)
    main = [onto_bridges(line, ends) for line in _main_ways(model)]
    side = [onto_bridges(line, ends) for line in _side_streets(model)]
    side += _bridge_links(model, ends, main + side)
    # Ways stop at the water's edge unless they're on a bridge.
    water = _Water.of(model)
    roads = [piece for line in main
             for piece in trim(bend_around(line, moved, ROAD_HALF, everything),
                               water)]
    streets = [piece for line in side
               for piece in trim(bend_around(line, moved, STREET_HALF,
                                             everything), water)]
    # Streets stop at the edge of a road instead of running onto it.
    drawn = _Roads(roads)
    streets = [piece for line in streets for piece in trim(line, drawn)]
    walls = [piece for line in _wall_streets(model, everything)
             for piece in trim(line, drawn)
             if _length(piece) >= MIN_WALL_STREET / 2]
    return roads, streets, walls


def _length(points):
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))
