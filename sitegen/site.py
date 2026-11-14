"""A location as a list of pieces, and the sums for placing them.

Each piece has an outline or a path in its own frame, centred on its own
origin, and a position and angle that place it on the map. Moving a piece
changes only its position, and turning it only its angle, so its shape stays
exactly as it was. A tree or a well is a circle, with a radius instead of an
outline.
"""

import math
from dataclasses import dataclass, field

from citygen.geometry import Point, Polygon

# What each kind of piece is, by how it's shaped.
AREAS = ("field", "orchard", "yard", "meadow", "wood", "pond", "building",
         "gnome_home")
LINES = ("road", "track", "river", "bridge", "hedge", "wall", "gate")
ROUND = ("tree", "well")
KINDS = AREAS + LINES + ROUND

# What each kind is called, for labels and the Add buttons.
KIND_NAMES = {
    "field": "Wheat field", "orchard": "Orchard", "yard": "Yard",
    "meadow": "Meadow", "wood": "Wood", "pond": "Pond",
    "building": "Building", "gnome_home": "Gnome home", "road": "Road",
    "track": "Track", "river": "River", "bridge": "Bridge", "hedge": "Hedge",
    "wall": "Stone wall", "gate": "Gate", "tree": "Tree", "well": "Well",
}

# The fewest corners an area or points a line can be left with.
MIN_AREA_POINTS = 3
MIN_LINE_POINTS = 2


@dataclass
class Piece:
    """One thing on the map.

    points are (x, y) in the piece's own frame. x, y and angle place it, with
    angle in radians. seed keeps the trees of a wood or an orchard the same
    each time it's drawn. joins, for a gnome home, are pairs of places in
    points where a room meets the hexagon.
    """

    kind: str
    x: float = 0.0
    y: float = 0.0
    angle: float = 0.0
    points: list = field(default_factory=list)
    radius: float = 0.0
    label: str = ""
    seed: int = 0
    joins: list = field(default_factory=list)

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError(f"Unknown kind of piece {self.kind!r}")
        if not self.label:
            self.label = KIND_NAMES[self.kind]

    @property
    def is_area(self):
        return self.kind in AREAS

    @property
    def is_line(self):
        return self.kind in LINES

    @property
    def is_round(self):
        return self.kind in ROUND

    def to_map(self, px, py):
        """A point in the piece's frame, on the map."""
        c = math.cos(self.angle)
        s = math.sin(self.angle)
        return (self.x + px * c - py * s, self.y + px * s + py * c)

    def to_local(self, mx, my):
        """A point on the map, in the piece's frame."""
        dx = mx - self.x
        dy = my - self.y
        c = math.cos(self.angle)
        s = math.sin(self.angle)
        return (dx * c + dy * s, -dx * s + dy * c)

    def world(self):
        """The piece's outline or path on the map, as (x, y)."""
        return [self.to_map(px, py) for px, py in self.points]

    def polygon(self):
        return Polygon(Point(x, y) for x, y in self.world())

    def local_box(self):
        """The piece's box in its own frame, as (left, top, right, bottom)."""
        if self.is_round:
            r = self.radius
            return (-r, -r, r, r)
        xs = [px for px, _ in self.points]
        ys = [py for _, py in self.points]
        return (min(xs), min(ys), max(xs), max(ys))

    def box_corners(self):
        """The corners of the piece's own box, on the map."""
        left, top, right, bottom = self.local_box()
        return [self.to_map(px, py) for px, py in
                ((left, top), (right, top), (right, bottom), (left, bottom))]

    def reach(self):
        """Every point the piece covers, on the map, for working out boxes."""
        if self.is_round:
            r = self.radius
            return [(self.x - r, self.y - r), (self.x + r, self.y + r)]
        return self.world()

    def copy(self):
        return Piece(self.kind, self.x, self.y, self.angle, list(self.points),
                     self.radius, self.label, self.seed,
                     [tuple(j) for j in self.joins])


@dataclass
class Site:
    """A single location: what kind it is, its seed and its pieces.

    Pieces are drawn in their kinds' order, and in list order within a kind,
    so the last of a kind is on top.
    """

    kind: str = "farm"
    seed: int = 1
    pieces: list = field(default_factory=list)
    # How the window showed it when it was saved, if it says: the map's turn
    # and north in degrees, and whether the compass and scale bar show.
    view: dict = None

    def extent(self, margin=1.05, least=20.0):
        """How far the location reaches from the centre, in map units.

        Roads, rivers and the like don't count, since they can run on past
        the edge of the map, unless there's nothing else.
        """
        far = least / margin
        pieces = [p for p in self.pieces if not p.is_line] or self.pieces
        for piece in pieces:
            for x, y in piece.reach():
                far = max(far, abs(x), abs(y))
        return far * margin


def bounds(pieces):
    """The box round some pieces on the map, as (left, top, right, bottom)."""
    xs = []
    ys = []
    for piece in pieces:
        for x, y in piece.reach():
            xs.append(x)
            ys.append(y)
    return (min(xs), min(ys), max(xs), max(ys))


def inside(polygon, x, y):
    """Whether a point is inside a polygon of (x, y)."""
    found = False
    count = len(polygon)
    for i in range(count):
        x0, y0 = polygon[i]
        x1, y1 = polygon[(i + 1) % count]
        if (y0 > y) != (y1 > y):
            if x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
                found = not found
    return found


def to_segment(x, y, a, b):
    """How far a point is from the segment between (x, y) pairs a and b."""
    ax, ay = a
    bx, by = b
    dx = bx - ax
    dy = by - ay
    length = dx * dx + dy * dy
    if length == 0:
        return math.hypot(x - ax, y - ay)
    t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / length))
    return math.hypot(x - ax - t * dx, y - ay - t * dy)


def to_line(x, y, line):
    return min(to_segment(x, y, a, b) for a, b in zip(line, line[1:]))
