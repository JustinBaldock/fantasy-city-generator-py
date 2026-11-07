"""Gnome homes.

This module is original to this port, and an option the original doesn't have.
A gnome home is a regular hexagon with square rooms built onto some of its
straight sides. Gnomes still build shops, workshops, stores, barns and
government buildings, and those are plain squares and rectangles. Each ward
says what share of its plots go to them.

The city is laid out as usual and each plot then gets its new building in
place of the ordinary one. This uses its own random numbers and the wards only
cut their land into bigger plots, so the streets, walls and water stay the
same.
"""

import math
import random

from .geometry import Point, Polygon, distance
from .wards import ALLEY, Farm

SIDES = 6
ROOMS = (2, 3, 3, 4)  # How many rooms a home would like.
ROOM_SIZE = (0.6, 0.85)  # A room's side, as a share of the hexagon's side.

# Sizes to try, as shares of the widest circle that fits the plot. The last
# one always has room for rooms, since they then stay inside that circle.
SCALES = (1.0, 0.9, 0.8, 0.7, 0.6, 0.5)
MIN_RADIUS = 0.9  # Smaller homes are too tiny to read, unless they have no room.

GRID = 4  # Spots to try across a plot, each way.
REFINE = 3  # How many times to look closer around the best spot.

LONG_PLOT = 2.6  # A plot this many times longer than wide gets two homes.
MIN_CLEARANCE = 1.0  # A plot narrower than this is left empty.
MARGIN = 0.2  # Open ground kept between a home and the edge of its plot.
FARM_RADIUS = 2.4

MAX_ASPECT = 3.0  # How many times longer than wide a rectangle can be.

# Sizes to try for a rectangle, as shares of the widest circle that fits. The
# last one always fits, since its corners then stay inside that circle.
RECTANGLE_SCALES = (1.5, 1.3, 1.15, 1.0, 0.85, 0.7, 0.6, 0.5)

BARN_SIZE = ((2.2, 3.6), (3.6, 6.0))  # The range of its width and length.
BARN_GAP = 1.0  # Between a barn and the rooms of its farmhouse.
FARM_EDGE = 1.0  # Kept between a barn and the edge of its land.


class GnomeHome(Polygon):
    """A home's outline, which remembers where its rooms join the hexagon.

    joins holds a pair of corner positions in the outline for each room, the
    two ends of the wall between that room and the hexagon. They stay right
    when the home moves, since moving one keeps its order of corners.
    """

    def __init__(self, points, joins):
        super().__init__(points)
        self.joins = joins

    def room_walls(self):
        return [(self[a], self[b]) for a, b in self.joins]


def outline(x, y, radius, turn, room, sides):
    """The (x, y) corners of a home, going round its hexagon.

    turn is the angle of the first corner, room is the length of a room's
    side, and sides says which sides of the hexagon have rooms.
    """
    corners = []
    for i in range(SIDES):
        angle = turn + i * 2 * math.pi / SIDES
        corners.append((x + radius * math.cos(angle),
                        y + radius * math.sin(angle)))

    points = []
    for side, (ax, ay) in enumerate(corners):
        points.append((ax, ay))
        if side not in sides:
            continue
        bx, by = corners[(side + 1) % SIDES]
        along_x = (bx - ax) / radius
        along_y = (by - ay) / radius
        out_x, out_y = along_y, -along_x
        start = (radius - room) / 2
        near_x = ax + along_x * start
        near_y = ay + along_y * start
        far_x = near_x + along_x * room
        far_y = near_y + along_y * room
        points += [(near_x, near_y),
                   (near_x + out_x * room, near_y + out_y * room),
                   (far_x + out_x * room, far_y + out_y * room),
                   (far_x, far_y)]
    return points


def _clearance(plot, x, y):
    """How far a point is from the plot's nearest edge, 0 if it's outside."""
    if not plot.contains_point(Point(x, y)):
        return 0.0
    nearest = math.inf
    for a, b in plot.edges():
        dx = b.x - a.x
        dy = b.y - a.y
        length = dx * dx + dy * dy
        along = ((x - a.x) * dx + (y - a.y) * dy) / length if length else 0.0
        along = max(0.0, min(1.0, along))
        nearest = min(nearest, math.hypot(x - a.x - along * dx,
                                          y - a.y - along * dy))
    return nearest


def _roomiest_spot(plot):
    """Roughly the centre of the widest circle that fits, and its radius."""
    left = min(v.x for v in plot)
    right = max(v.x for v in plot)
    top = min(v.y for v in plot)
    bottom = max(v.y for v in plot)
    step_x = (right - left) / GRID
    step_y = (bottom - top) / GRID

    centre = plot.centroid
    spots = [(centre.x, centre.y)]
    for i in range(GRID):
        for j in range(GRID):
            spots.append((left + (i + 0.5) * step_x, top + (j + 0.5) * step_y))
    x, y = max(spots, key=lambda s: _clearance(plot, *s))

    for _ in range(REFINE):
        step_x /= 2
        step_y /= 2
        spots = [(x + i * step_x, y + j * step_y)
                 for i in (-1, 0, 1) for j in (-1, 0, 1)]
        x, y = max(spots, key=lambda s: _clearance(plot, *s))
    return x, y, _clearance(plot, x, y)


def _long_way(plot):
    """The start of the plot's longest edge, and that edge's direction."""
    start, end = max(plot.edges(), key=lambda e: distance(e[0], e[1]))
    return start, end.subtract(start).norm(1.0)


def _rooms_that_fit(plot, x, y, radius, turn, room):
    """Which sides of a hexagon have space for a room inside the plot."""
    sides = []
    for side in range(SIDES):
        shape = outline(x, y, radius, turn, room, {side})
        # The room's two outer corners are the ones furthest out.
        far_corners = shape[side + 2:side + 4]
        if all(_clearance(plot, *p) >= MARGIN for p in far_corners):
            sides.append(side)
    return sides


def _home_at(x, y, radius, turn, room, sides):
    points = outline(x, y, radius, turn, room, sides)
    joins = []
    for rooms_before, side in enumerate(sorted(sides)):
        # Each corner before it takes one place, and each room takes four.
        near = side + 1 + rooms_before * 4
        joins.append((near, near + 3))
    return GnomeHome((Point(px, py) for px, py in points), joins)


def _home_on(plot, spot, chooser):
    x, y, clearance = spot
    if clearance < MIN_CLEARANCE:
        return None
    clearance -= MARGIN

    wanted = chooser.choice(ROOMS)
    room_size = chooser.uniform(*ROOM_SIZE)
    _, along = _long_way(plot)
    edge_angle = math.atan2(along.y, along.x)
    turns = [edge_angle, edge_angle + math.pi / SIDES]
    chooser.shuffle(turns)

    # The biggest hexagon that leaves space for the rooms it wants.
    best = None
    for scale in SCALES:
        radius = clearance * scale
        for turn in turns:
            sides = _rooms_that_fit(plot, x, y, radius, turn,
                                    radius * room_size)
            if best is None or len(sides) > len(best[2]):
                best = (radius, turn, sides)
        if len(best[2]) >= wanted or (best[2] and radius < MIN_RADIUS):
            break

    radius, turn, sides = best
    chosen = chooser.sample(sides, min(wanted, len(sides)))
    return _home_at(x, y, radius, turn, radius * room_size, chosen)


def _length_of(plot, start, along):
    reach = [v.subtract(start).dot(along) for v in plot]
    return min(reach), max(reach)


def _rectangle(x, y, along, half_length, half_width):
    """A rectangle around a point, with its length in the direction given."""
    across = along.rotate90()
    return Polygon(
        Point(x + way * half_length * along.x + side * half_width * across.x,
              y + way * half_length * along.y + side * half_width * across.y)
        for way, side in ((-1, -1), (1, -1), (1, 1), (-1, 1)))


def _rectangle_on(plot, spot, chooser):
    """A square or rectangle lined up with the plot's longest edge."""
    x, y, clearance = spot
    if clearance < MIN_CLEARANCE:
        return None
    clearance -= MARGIN

    start, along = _long_way(plot)
    low, high = _length_of(plot, start, along)
    longest = min((high - low) / (2 * clearance), MAX_ASPECT)
    aspect = math.sqrt(chooser.uniform(1.0, max(1.0, longest)))

    for scale in RECTANGLE_SCALES:
        rectangle = _rectangle(x, y, along, clearance * scale * aspect,
                               clearance * scale / aspect)
        if all(_clearance(plot, v.x, v.y) >= MARGIN for v in rectangle):
            break
    return rectangle


def _shares_of(plot):
    """Plots with their roomiest spots, cut across if too long for one home."""
    spot = _roomiest_spot(plot)
    clearance = spot[2]
    start, along = _long_way(plot)
    low, high = _length_of(plot, start, along)
    length = high - low
    # Halves too thin for a home stay whole, which also ends the cutting.
    if clearance < MIN_CLEARANCE or length < LONG_PLOT * 2 * clearance:
        return [(plot, spot)]

    middle = start.add(along.scale((low + high) / 2))
    across = along.rotate90().scale(length * 2)
    pieces = plot.cut(middle.subtract(across), middle.add(across), ALLEY)
    if len(pieces) < 2:
        return [(plot, spot)]
    return [share for piece in pieces for share in _shares_of(piece)]


def _buildings_for(plots, rectangle_share, chooser):
    """Homes and plain buildings for a ward's plots.

    A plain building takes its whole plot, so the long thin ones make
    warehouses and halls instead of being cut in two.
    """
    buildings = []
    for plot in plots:
        if len(plot) < 3:
            continue
        if chooser.random() < rectangle_share:
            building = _rectangle_on(plot, _roomiest_spot(plot), chooser)
            buildings += [building] if building is not None else []
            continue
        for share, spot in _shares_of(plot):
            home = _home_on(share, spot, chooser)
            if home is not None:
                buildings.append(home)
    return buildings


def _barn_near(ward, x, y, turn, sides, room, chooser):
    """A barn across the yard from a farmhouse, if the land has space for it.

    It stands off a side with no room, far enough out to clear the rooms.
    """
    length = chooser.uniform(*BARN_SIZE[1])
    width = chooser.uniform(*BARN_SIZE[0])
    apothem = FARM_RADIUS * math.cos(math.pi / SIDES)
    reach = apothem + room + BARN_GAP + width / 2

    free = [side for side in range(SIDES) if side not in sides]
    chooser.shuffle(free)
    model = ward.model
    for side in free:
        angle = turn + (side + 0.5) * 2 * math.pi / SIDES
        out = Point(math.cos(angle), math.sin(angle))
        barn = _rectangle(x + out.x * reach, y + out.y * reach,
                          out.rotate90(), length / 2, width / 2)
        if (all(_clearance(ward.patch.shape, v.x, v.y) >= FARM_EDGE
                for v in barn)
                and (model.seaward is None or all(
                    model.seaward(v) < -FARM_EDGE for v in barn))):
            return barn
    return None


def _farmstead(ward, chooser):
    """A home where the farm's buildings were, and a barn if there's space."""
    points = [v for building in ward.geometry for v in building]
    x = sum(v.x for v in points) / len(points)
    y = sum(v.y for v in points) / len(points)
    room = FARM_RADIUS * chooser.uniform(*ROOM_SIZE)
    sides = chooser.sample(range(SIDES), chooser.choice(ROOMS))
    turn = chooser.uniform(0, 2 * math.pi)
    home = _home_at(x, y, FARM_RADIUS, turn, room, sides)
    barn = _barn_near(ward, x, y, turn, sides, room, chooser)
    return [home] if barn is None else [home, barn]


def build_gnome_homes(model):
    """Swap the city's buildings for gnome homes and plain rectangles.

    Castles, temple landmarks and market statues stay as they are.
    """
    chooser = random.Random(f"{model.seed} gnome homes")
    for patch in model.patches:
        ward = patch.ward
        if isinstance(ward, Farm):
            if ward.geometry:
                ward.geometry = _farmstead(ward, chooser)
        elif ward.homes or ward.rectangle_share:
            ward.geometry = _buildings_for(ward.geometry, ward.rectangle_share,
                                           chooser)
