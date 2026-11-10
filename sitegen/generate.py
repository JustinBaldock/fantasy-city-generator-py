"""Laying out a remote farm, toll house or roadhouse from a seed.

Each kind of location is laid out with its road running east and west, on a
grid of fields round the buildings, and the whole thing is then turned to a
random heading. The fields are cells of a grid whose inner corners wander, so
neighbours share their edges and nothing lines up too neatly.
"""

import math
import random

from citygen.geometry import Point, Polygon
from citygen.water import RIVER_WIDTH

from .editing import SiteEditor, gnome_home
from .site import Piece, Site

KINDS = ("farm", "toll_house", "roadhouse")
KIND_NAMES = {"farm": "Farm", "toll_house": "Toll house",
              "roadhouse": "Roadhouse"}
HOME_STYLES = ("plain", "gnome")

CELL = 22.0  # How wide a cell of the field grid is, east to west.
CELL_DEPTH = 20.0  # And north to south.
ROAD_GAP = 3.5  # Between the middle of the road and the first fields.
WANDER = 3.0  # How far an inner corner of the grid can move.
FIELD_GAP = 0.8  # Kept between neighbouring fields.
HEDGE_CHANCE = 0.6  # Of a hedge between two neighbouring fields.
HEDGE_TREE_SPACING = 7.0
HEDGE_TREE_CHANCE = 0.45
LONE_TREE_RADIUS = (1.4, 2.2)
GARDEN_TREE_RADIUS = (0.8, 1.4)
BANK_TREE_CHANCE = 0.5
TILT = math.radians(12)  # The most a layout is turned off square.
GNOME_SIZE = 0.55  # A gnome home's radius, as a share of a plain house.
MIN_GNOME_RADIUS = 1.0
MIN_YARD = 10.0  # The least depth of a farmyard, front to back.
# Roads and rivers run this much further than the land, so they leave the map
# at its edges whichever way the location is turned.
OFF_THE_MAP = 1.6


class _Layout:
    """A location being laid out, in the frame where the road runs east."""

    def __init__(self, kind, seed, homes):
        self.chooser = random.Random(f"{seed} {kind}")
        self.homes = homes
        self.pieces = []

    def uniform(self, low, high):
        return self.chooser.uniform(low, high)

    def chance(self, odds):
        return self.chooser.random() < odds

    def seed(self):
        return self.chooser.randrange(1, 2 ** 31)

    def area(self, kind, corners, label=""):
        """A piece from its corners on the map, framed along its longest
        edge so its own box hugs it."""
        count = len(corners)
        a, b = max(((corners[i], corners[(i + 1) % count])
                    for i in range(count)),
                   key=lambda pair: math.dist(*pair))
        angle = math.atan2(b[1] - a[1], b[0] - a[0])
        cx = sum(x for x, _ in corners) / count
        cy = sum(y for _, y in corners) / count
        piece = Piece(kind, cx, cy, angle, label=label, seed=self.seed())
        piece.points = [piece.to_local(x, y) for x, y in corners]
        self.pieces.append(piece)
        return piece

    def line(self, kind, points, label=""):
        (x0, y0), (x1, y1) = points[0], points[-1]
        angle = math.atan2(y1 - y0, x1 - x0)
        cx = (x0 + x1) / 2
        cy = (y0 + y1) / 2
        piece = Piece(kind, cx, cy, angle, label=label)
        piece.points = [piece.to_local(x, y) for x, y in points]
        self.pieces.append(piece)
        return piece

    def box(self, kind, cx, cy, width, depth, angle=0.0, label=""):
        """A rectangle with its width along the angle given."""
        w = width / 2
        d = depth / 2
        piece = Piece(kind, cx, cy, angle, label=label, seed=self.seed())
        piece.points = [(-w, -d), (w, -d), (w, d), (-w, d)]
        self.pieces.append(piece)
        return piece

    def home(self, cx, cy, width, depth, label, room):
        """The main house, a gnome home if that's the style.

        room is how far a gnome home can reach each way, as (across, deep),
        since its rooms stick out past the box a plain house would take.
        """
        if self.homes != "gnome":
            return self.box("building", cx, cy, width, depth, label=label)
        sides = sorted(self.chooser.sample(range(6),
                                           self.chooser.choice((2, 3, 4))))
        piece = Piece("gnome_home", cx, cy, self.uniform(0, math.pi / 3),
                      label=label)
        across, deep = room
        radius = min(width, depth) * GNOME_SIZE
        while True:
            piece.points, piece.joins = gnome_home(radius, sides)
            if radius <= MIN_GNOME_RADIUS or all(
                    abs(x - cx) <= across and abs(y - cy) <= deep
                    for x, y in piece.world()):
                break
            radius *= 0.95
        self.pieces.append(piece)
        return piece

    def tree(self, x, y, sizes=LONE_TREE_RADIUS):
        piece = Piece("tree", x, y, radius=self.uniform(*sizes))
        self.pieces.append(piece)
        return piece

    def well(self, x, y):
        piece = Piece("well", x, y, radius=0.6)
        self.pieces.append(piece)

    def road(self, half, bend=1.5, label="Road"):
        """A road across the whole map and off its edges, straight where the
        buildings are."""
        ys = [self.uniform(-bend, bend) for _ in range(2)]
        far = half * OFF_THE_MAP
        straight = half * 0.45
        return self.line("road", [(-far, ys[0]), (-straight, 0.0),
                                  (straight, 0.0), (far, ys[1])], label)

    def grid(self, columns, rows, wander=WANDER):
        """The corners of a grid of cells, keyed by (column, row).

        columns and rows are the edges' positions east and south. Corners on
        the grid's outside, and beside a road, stay put.
        """
        nodes = {}
        for i, x in enumerate(columns):
            for j, y in enumerate(rows):
                inner_x = 0 < i < len(columns) - 1
                inner_y = 0 < j < len(rows) - 1
                dx = self.uniform(-wander, wander) if inner_x else 0.0
                dy = self.uniform(-wander, wander) if inner_y else 0.0
                nodes[i, j] = (x + dx, y + dy)
        return nodes

    @staticmethod
    def cell(nodes, i, j):
        return [nodes[i, j], nodes[i + 1, j], nodes[i + 1, j + 1],
                nodes[i, j + 1]]

    def inset(self, corners, gap=FIELD_GAP):
        """A cell pulled in from its neighbours."""
        polygon = Polygon(Point(x, y) for x, y in corners)
        if polygon.square < 0:
            polygon = Polygon(reversed(polygon))
        try:
            smaller = polygon.shrink_eq(gap)
        except (ValueError, ArithmeticError, IndexError):
            return corners
        if not smaller or abs(smaller.square) >= abs(polygon.square):
            smaller = Polygon(reversed(polygon)).shrink_eq(gap)
        return [(v.x, v.y) for v in smaller]

    def hedge(self, a, b):
        self.line("hedge", [a, b])
        steps = int(math.dist(a, b) // HEDGE_TREE_SPACING)
        for k in range(1, steps + 1):
            if self.chance(HEDGE_TREE_CHANCE):
                t = k / (steps + 1)
                self.tree(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)

    def farmland(self, nodes, columns, rows, taken, outer_rows,
                 outer_columns=None):
        """Fields, meadows and woods in every cell not already taken.

        Woods grow in the corners of the map, where an outer row, along its
        edge, meets an outer column.
        """
        if outer_columns is None:
            outer_columns = (0, len(columns) - 2)
        kinds = {}
        for i in range(len(columns) - 1):
            for j in range(len(rows) - 1):
                if (i, j) in taken:
                    continue
                outer_column = i in outer_columns
                if j in outer_rows and outer_column and self.chance(0.6):
                    kind = "wood"
                elif self.chance(0.18):
                    kind = "meadow"
                else:
                    kind = "field"
                kinds[i, j] = kind
                corners = self.cell(nodes, i, j)
                self.area(kind, self.inset(corners))
                if kind == "meadow" and self.chance(0.4):
                    self.pond_in(corners)

        # Hedges between neighbouring fields, along their shared edge.
        for (i, j), kind in kinds.items():
            if kind != "field":
                continue
            if kinds.get((i + 1, j)) == "field" and self.chance(HEDGE_CHANCE):
                self.hedge(nodes[i + 1, j], nodes[i + 1, j + 1])
            if kinds.get((i, j + 1)) == "field" and self.chance(HEDGE_CHANCE):
                self.hedge(nodes[i, j + 1], nodes[i + 1, j + 1])
        return kinds

    def pond_in(self, corners):
        cx = sum(x for x, _ in corners) / 4 + self.uniform(-3, 3)
        cy = sum(y for _, y in corners) / 4 + self.uniform(-3, 3)
        width = self.uniform(5, 8)
        depth = width * self.uniform(0.5, 0.8)
        turn = self.uniform(0, math.pi)
        points = []
        for k in range(7):
            a = 2 * math.pi * k / 7
            wobble = self.uniform(0.85, 1.15)
            points.append((cx + (math.cos(a) * width / 2 * math.cos(turn)
                                 - math.sin(a) * depth / 2 * math.sin(turn))
                           * wobble,
                           cy + (math.cos(a) * width / 2 * math.sin(turn)
                                 + math.sin(a) * depth / 2 * math.cos(turn))
                           * wobble))
        self.area("pond", points)

    def garden_trees(self, left, top, right, bottom, count):
        for _ in range(count):
            self.tree(self.uniform(left, right), self.uniform(top, bottom),
                      GARDEN_TREE_RADIUS)

    def turned(self, kind, seed):
        """The finished location, turned to a random heading."""
        turn = (self.chooser.randrange(4) * math.pi / 2
                + self.uniform(-TILT, TILT))
        site = Site(kind, seed, self.pieces)
        SiteEditor.rotate(site.pieces, turn, 0.0, 0.0)
        return site


def _across_at(line, y):
    """Where a line running north and south crosses a level."""
    for (x0, y0), (x1, y1) in zip(line, line[1:]):
        if min(y0, y1) <= y <= max(y0, y1) and y0 != y1:
            return x0 + (x1 - x0) * (y - y0) / (y1 - y0)
    return line[0][0]


def _columns(count, start):
    return [start + CELL * k for k in range(count + 1)]


def _farm(layout):
    half = CELL * 2
    layout.road(half + 6)
    columns = _columns(4, -half)
    north = [-ROAD_GAP - CELL_DEPTH * 2, -ROAD_GAP - CELL_DEPTH, -ROAD_GAP]
    south = [ROAD_GAP, ROAD_GAP + CELL_DEPTH, ROAD_GAP + CELL_DEPTH * 2]
    north_nodes = layout.grid(columns, north)
    south_nodes = layout.grid(columns, south)

    # The farmstead takes a cell beside the road, its yard at the front and
    # an orchard behind.
    column = layout.chooser.choice((1, 2))
    corners = layout.cell(north_nodes, column, 1)
    left = max(corners[0][0], corners[3][0]) + FIELD_GAP
    right = min(corners[1][0], corners[2][0]) - FIELD_GAP
    front = -ROAD_GAP - FIELD_GAP
    back = max(corners[0][1], corners[1][1]) + FIELD_GAP
    yard_back = front - max(MIN_YARD, (front - back) * layout.uniform(0.55, 0.65))
    layout.area("yard", [(left, yard_back), (right, yard_back),
                         (right, front), (left, front)], "Farmyard")
    layout.area("orchard", layout.inset(
        [corners[0], corners[1], (right + FIELD_GAP, yard_back),
         (left - FIELD_GAP, yard_back)]), "Orchard")
    _farmstead(layout, left, right, yard_back, front)

    # A paddock beside it, with a pond.
    beside = column + layout.chooser.choice((-1, 1))
    paddock = layout.cell(north_nodes, beside, 1)
    layout.area("meadow", layout.inset(paddock), "Paddock")
    layout.pond_in(paddock)

    layout.farmland(north_nodes, columns, north, {(column, 1), (beside, 1)},
                    (0,))
    layout.farmland(south_nodes, columns, south, set(), (1,))
    for _ in range(layout.chooser.randrange(2, 5)):
        x = layout.uniform(-half, half)
        side = layout.chooser.choice((-1, 1))
        layout.tree(x, side * (ROAD_GAP - 0.2))


def _farmstead(layout, left, right, yard_back, front):
    """A farmhouse and shed at the front of a yard, a barn along its back
    and a byre down one side, with a track in from the road."""
    width = right - left
    depth = front - yard_back
    byre_side = layout.chooser.choice((-1, 1))

    def x_at(x):
        """Measured from the house side of the yard."""
        return left + x if byre_side > 0 else right - x

    middle = (left + right) / 2
    layout.line("track", [(middle + layout.uniform(-2, 2), 0.0),
                          (middle, front)], "Farm track")
    house_width = layout.uniform(5.0, 6.0)
    layout.home(x_at(0.6 + house_width / 2), front - 2.6, house_width,
                layout.uniform(3.0, 3.6), "Farmhouse",
                (house_width / 2 + 0.5, 2.2))
    shed = house_width + (3.4 if layout.homes == "gnome" else 2.2)
    layout.box("building", x_at(shed), front - 2.0, 2.4, 2.0,
               label="Shed")

    byre = min(layout.uniform(5.0, 6.5), depth - 1.6)
    layout.box("building", x_at(width - 2.0), yard_back + 0.8 + byre / 2,
               byre, layout.uniform(2.6, 3.0), math.pi / 2, "Byre")
    barn = min(layout.uniform(8.0, 10.0), width - 6.0)
    layout.box("building", x_at(width - 4.3 - barn / 2), yard_back + 2.4,
               barn, layout.uniform(3.4, 4.0), label="Barn")
    layout.well(middle + byre_side, yard_back + depth / 2 + 0.5)
    if depth > 12:
        a = x_at(1.0)
        b = x_at(6.0)
        layout.garden_trees(min(a, b), front - 7.0, max(a, b), front - 5.6,
                            layout.chooser.choice((1, 2)))


def _toll_house(layout):
    half = CELL * 2 + 6
    gap = RIVER_WIDTH / 2 + 5
    has_river = layout.chance(0.75)
    layout.road(half + 6, label="Turnpike road")
    west = [-half, -half + CELL, -gap]
    east = [gap, gap + CELL, half]
    north = [-ROAD_GAP - CELL_DEPTH * 2, -ROAD_GAP - CELL_DEPTH, -ROAD_GAP]
    south = [ROAD_GAP, ROAD_GAP + CELL_DEPTH, ROAD_GAP + CELL_DEPTH * 2]

    if has_river:
        bend = gap - RIVER_WIDTH / 2 - 1.5
        reach = (north[0] - 6) * OFF_THE_MAP
        river = [(layout.uniform(-bend, bend), reach),
                 (layout.uniform(-bend, bend), reach / 2),
                 (0.0, -ROAD_GAP - 4), (0.0, ROAD_GAP + 4),
                 (layout.uniform(-bend, bend), -reach / 2),
                 (layout.uniform(-bend, bend), -reach)]
        layout.line("river", river, "River")
        span = RIVER_WIDTH / 2 + 1.8
        layout.line("bridge", [(-span, 0.0), (span, 0.0)], "Bridge")
        # Trees along the banks, on the land the map shows.
        for y in (north[0], north[1], south[1], south[2]):
            y += layout.uniform(-4, 4)
            x = _across_at(river, y)
            for side in (-1, 1):
                if layout.chance(BANK_TREE_CHANCE):
                    layout.tree(x + side * (RIVER_WIDTH / 2 + 2.2), y)
    else:
        # A side track joins the road where the toll is taken.
        layout.line("track", [(0.0, ROAD_GAP), (layout.uniform(-3, 3),
                                                 south[-1] + 4)],
                    "Track")

    # The toll house stands just past the bridge, with its gate across the
    # road and a garden behind.
    side = layout.chooser.choice((-1, 1))
    house_x = side * (gap + 3.4)
    layout.home(house_x, -ROAD_GAP - FIELD_GAP - 2.4, 4.2, 3.2, "Toll house",
                (2.5, 2.1))
    layout.line("gate", [(house_x + side * 3.4, -1.5),
                         (house_x + side * 3.4, 1.5)], "Toll gate")
    near = gap + FIELD_GAP
    far = gap + CELL * layout.uniform(0.5, 0.65)
    garden = [(side * near, -ROAD_GAP - 9.0), (side * far, -ROAD_GAP - 9.0),
              (side * far, -ROAD_GAP - FIELD_GAP),
              (side * near, -ROAD_GAP - FIELD_GAP)]
    layout.area("yard", garden, "Toll house garden")
    layout.box("building", side * (far - 2.0), -ROAD_GAP - 6.5, 3.6, 2.4,
               math.pi / 2, "Stable")
    layout.garden_trees(side * near + 1, -ROAD_GAP - 8.0,
                        side * (near + 4), -ROAD_GAP - 5.5, 2)

    for columns, edge in ((west, 0), (east, 1)):
        north_nodes = layout.grid(columns, north)
        south_nodes = layout.grid(columns, south)
        taken = set()
        if (edge == 1) == (side > 0):
            # The garden takes the front of the cell by the toll house, and
            # the rest of it is a meadow.
            corners = layout.cell(north_nodes, 1 - edge, 1)
            back = [corners[0], corners[1]]
            layout.area("meadow", layout.inset(
                back + [(back[1][0], -ROAD_GAP - 10.0),
                        (back[0][0], -ROAD_GAP - 10.0)]), "Meadow")
            taken.add((1 - edge, 1))
        outer = {0} if edge == 0 else {1}
        _farmland_by_columns(layout, north_nodes, columns, north, taken,
                             (0,), outer)
        _farmland_by_columns(layout, south_nodes, columns, south, set(),
                             (1,), outer)


def _farmland_by_columns(layout, nodes, columns, rows, taken, outer_rows,
                         outer_columns):
    """Farmland whose woods keep to the map's outer columns."""
    kept = set(taken)
    for i in range(len(columns) - 1):
        if i not in outer_columns:
            for j in outer_rows:
                if (i, j) not in kept and layout.chance(0.15):
                    layout.area("meadow", layout.inset(
                        layout.cell(nodes, i, j)))
                    kept.add((i, j))
    layout.farmland(nodes, columns, rows, kept, outer_rows, outer_columns)


def _roadhouse(layout):
    half = CELL * 2 + 5
    gap = 5.0
    layout.road(half + 6, label="High road")
    north_end = (-ROAD_GAP - CELL_DEPTH * 2 - 6) * OFF_THE_MAP
    crossroads = layout.chance(0.6)
    lane = [(layout.uniform(-1.5, 1.5), north_end), (0.0, -ROAD_GAP - 6),
            (0.0, 0.0)]
    if crossroads:
        lane += [(0.0, ROAD_GAP + 6), (layout.uniform(-1.5, 1.5), -north_end)]
    layout.line("road", lane, "Side road")

    west = [-half, -half + CELL, -gap]
    east = [gap, gap + CELL, half]
    north = [-ROAD_GAP - CELL_DEPTH * 2, -ROAD_GAP - CELL_DEPTH, -ROAD_GAP]
    south = [ROAD_GAP, ROAD_GAP + CELL_DEPTH, ROAD_GAP + CELL_DEPTH * 2]

    # The inn takes the corner of the crossroads: a courtyard with the inn
    # along the road, its wing reaching back on the crossroads side, stables
    # at the back and a coach house on the far side.
    side = layout.chooser.choice((-1, 1))
    near = gap + FIELD_GAP
    far = gap + CELL - FIELD_GAP
    front = -ROAD_GAP - FIELD_GAP
    back = -ROAD_GAP - CELL_DEPTH * layout.uniform(0.75, 0.85)
    layout.area("yard", [(side * near, back), (side * far, back),
                         (side * far, front), (side * near, front)],
                "Inn yard")
    middle = (near + far) / 2
    length = layout.uniform(10.0, 12.0)
    depth = layout.uniform(3.8, 4.4)
    wing = layout.uniform(3.0, 5.0)
    wing_width = layout.uniform(3.6, 4.2)
    start = middle - length / 2 - 1.0
    end = start + length
    face = front - 0.6
    rear = face - depth
    inn = [(start, face), (end, face), (end, rear), (start + wing_width, rear),
           (start + wing_width, rear - wing), (start, rear - wing)]
    layout.area("building", [(side * x, y) for x, y in inn], "Inn")
    stables = min(layout.uniform(10.0, 12.0), far - near - 7.0)
    layout.box("building", side * (middle - 1.5), back + 2.2, stables,
               layout.uniform(3.2, 3.8), label="Stables")
    layout.box("building", side * (far - 2.2), (front + back) / 2 - 1.0,
               layout.uniform(4.5, 6.0), 3.2, math.pi / 2, "Coach house")
    layout.well(side * (middle + 2.0), (front + back) / 2)
    layout.line("track", [(side * 1.2, (front + back) / 2 - 1.0),
                          (side * near, (front + back) / 2 - 1.0)],
                "Yard gate")

    # A garden for drinkers next door, and a paddock across the road.
    beer = [(side * (far + FIELD_GAP * 2), back + 4),
            (side * (half - FIELD_GAP), back + 4),
            (side * (half - FIELD_GAP), front),
            (side * (far + FIELD_GAP * 2), front)]
    layout.area("yard", beer, "Inn garden")
    xs = sorted((beer[0][0], beer[1][0]))
    layout.garden_trees(xs[0] + 1.5, back + 6, xs[1] - 1.5, front - 1.5, 4)
    if layout.chance(0.5):
        layout.box("building", side * (far + 6.0), front - 2.5, 4.2, 3.2,
                   label="Brewhouse")

    for columns, edge in ((west, 0), (east, 1)):
        north_nodes = layout.grid(columns, north)
        south_nodes = layout.grid(columns, south)
        taken_north = set()
        taken_south = set()
        if (edge == 1) == (side > 0):
            taken_north = {(0, 1), (1, 1)}
            corners = layout.cell(south_nodes, 1 - edge, 0)
            layout.area("meadow", layout.inset(corners), "Paddock")
            layout.pond_in(corners)
            taken_south.add((1 - edge, 0))
        outer = {0} if edge == 0 else {1}
        _farmland_by_columns(layout, north_nodes, columns, north, taken_north,
                             (0,), outer)
        _farmland_by_columns(layout, south_nodes, columns, south, taken_south,
                             (1,), outer)


_BUILDERS = {"farm": _farm, "toll_house": _toll_house,
             "roadhouse": _roadhouse}


def generate(kind="farm", seed=1, homes="plain"):
    """A new location of a kind, the same every time for the same seed."""
    if kind not in _BUILDERS:
        raise ValueError(f"Unknown kind of location {kind!r}")
    if homes not in HOME_STYLES:
        raise ValueError(f"Unknown home style {homes!r}")
    layout = _Layout(kind, seed, homes)
    _BUILDERS[kind](layout)
    return layout.turned(kind, seed)
