"""Changing a location: picking, moving, turning, resizing and reshaping.

Nothing here needs Qt, so it can all be tested without a window.
"""

import math
import random

from citygen.gnomes import FARM_RADIUS, _home_at
from citygen.water import RIVER_WIDTH

from .drawing import DRAW_ORDER, LINE_WIDTHS
from .site import (
    MIN_AREA_POINTS,
    MIN_LINE_POINTS,
    Piece,
    inside,
    to_line,
    to_segment,
)

MIN_SIZE = 0.4  # The least a piece can be resized to, each way.
MIN_RADIUS = 0.2
PICK_MARGIN = 0.4  # Extra reach round a thin line, in map units.


def _rect(width, height):
    w = width / 2
    h = height / 2
    return [(-w, -h), (w, -h), (w, h), (-w, h)]


def _blob(width, height, corners=8):
    """A rough oval, for woods and meadows."""
    points = []
    for i in range(corners):
        a = 2 * math.pi * i / corners
        wobble = 1 + 0.12 * math.sin(3 * a + 1)
        points.append((math.cos(a) * width / 2 * wobble,
                       math.sin(a) * height / 2 * wobble))
    return points


def gnome_home(radius=FARM_RADIUS, sides=(0, 2, 4)):
    """A gnome home's outline and room joins, centred on its own origin."""
    home = _home_at(0.0, 0.0, radius, 0.0, radius * 0.6, list(sides))
    return [(v.x, v.y) for v in home], [tuple(j) for j in home.joins]


def new_piece(kind, x=0.0, y=0.0, seed=0):
    """A piece of a kind at its usual size, for adding to a location."""
    piece = Piece(kind, x, y, seed=seed)
    span = RIVER_WIDTH / 2 + 1.5
    shapes = {
        "field": _rect(24, 18),
        "orchard": _rect(14, 12),
        "yard": _rect(12, 9),
        "meadow": _blob(18, 14),
        "wood": _blob(30, 22, 10),
        "pond": _blob(7, 4.5, 6),
        "building": _rect(5, 3),
        "road": [(-20, 0), (0, 0), (20, 0)],
        "track": [(-10, 0), (0, 0), (10, 0)],
        "river": [(-25, 0), (0, 0), (25, 0)],
        "bridge": [(-span, 0), (span, 0)],
        "hedge": [(-10, 0), (10, 0)],
        "wall": [(-8, 0), (8, 0)],
        "gate": [(0, -1.4), (0, 1.4)],
    }
    if kind == "gnome_home":
        piece.points, piece.joins = gnome_home()
    elif kind == "tree":
        piece.radius = 1.8
    elif kind == "well":
        piece.radius = 0.6
    else:
        piece.points = shapes[kind]
    return piece


class SiteEditor:
    """Edits to one location's pieces."""

    def __init__(self, site):
        self.site = site
        self._seeds = random.Random(f"{site.seed} added pieces")

    # Picking.

    def piece_at(self, x, y, tolerance=0.0):
        """The piece on top at a point on the map, or None."""
        rank = {kind: i for i, kind in enumerate(DRAW_ORDER)}
        order = sorted(enumerate(self.site.pieces),
                       key=lambda item: (rank[item[1].kind], item[0]))
        for _, piece in reversed(order):
            if self.covers(piece, x, y, tolerance):
                return piece
        return None

    @staticmethod
    def covers(piece, x, y, tolerance=0.0):
        if piece.is_round:
            return math.hypot(x - piece.x, y - piece.y) <= (
                piece.radius + tolerance)
        if piece.is_line:
            reach = LINE_WIDTHS[piece.kind] / 2 + PICK_MARGIN + tolerance
            return to_line(x, y, piece.world()) <= reach
        outline = piece.world()
        if inside(outline, x, y):
            return True
        return tolerance > 0 and min(
            to_segment(x, y, a, b)
            for a, b in zip(outline, outline[1:] + outline[:1])) <= tolerance

    def pieces_in(self, left, top, right, bottom):
        """The pieces wholly inside a box on the map."""
        return [piece for piece in self.site.pieces
                if all(left <= x <= right and top <= y <= bottom
                       for x, y in piece.reach())]

    def pieces_within(self, corners):
        """The pieces wholly inside a four-sided area of the map, given by
        its corners, such as a box drawn on a turned map."""
        return [piece for piece in self.site.pieces
                if all(inside(corners, x, y) for x, y in piece.reach())]

    def point_at(self, piece, x, y, tolerance):
        """Which corner or point of a piece is at a spot, or None."""
        best = None
        nearest = tolerance
        for i, (px, py) in enumerate(piece.world()):
            gap = math.hypot(x - px, y - py)
            if gap <= nearest:
                best = i
                nearest = gap
        return best

    def edge_at(self, piece, x, y, tolerance):
        """The place a new point would go on a piece's edge, or None.

        This is the place in points it would take.
        """
        outline = piece.world()
        pairs = list(zip(outline, outline[1:]))
        if piece.is_area:
            pairs.append((outline[-1], outline[0]))
        best = None
        nearest = tolerance
        for i, (a, b) in enumerate(pairs):
            gap = to_segment(x, y, a, b)
            if gap <= nearest:
                best = i + 1
                nearest = gap
        return best

    # Changing pieces.

    def add(self, kind, x, y):
        piece = new_piece(kind, x, y, self._seeds.randrange(1, 2 ** 31))
        self.site.pieces.append(piece)
        return piece

    def delete(self, pieces):
        doomed = {id(piece) for piece in pieces}
        self.site.pieces = [piece for piece in self.site.pieces
                            if id(piece) not in doomed]

    @staticmethod
    def move(pieces, dx, dy):
        for piece in pieces:
            piece.x += dx
            piece.y += dy

    @staticmethod
    def rotate(pieces, turn, cx, cy):
        """Turn pieces together round a point, by an angle in radians."""
        c = math.cos(turn)
        s = math.sin(turn)
        for piece in pieces:
            dx = piece.x - cx
            dy = piece.y - cy
            piece.x = cx + dx * c - dy * s
            piece.y = cy + dx * s + dy * c
            piece.angle = (piece.angle + turn) % (2 * math.pi)

    @staticmethod
    def resize(piece, original, handle, mx, my):
        """Stretch a piece by dragging one side or corner of its own box.

        original is a copy of the piece from when the drag began. handle is
        (hx, hy), each -1, 0 or 1, for the side being dragged, and the side
        across from it stays put. (mx, my) is the pointer on the map.
        """
        hx, hy = handle
        px, py = original.to_local(mx, my)
        left, top, right, bottom = original.local_box()
        if piece.is_round:
            reach = max(abs(px) if hx else 0, abs(py) if hy else 0)
            piece.radius = max(MIN_RADIUS, reach)
            return

        def scaled(low, high, way, to):
            """The new low and high edges, and how to map a coordinate."""
            if way == 0 or high - low < 1e-9:
                return lambda v: v
            if way > 0:
                new_high = max(low + MIN_SIZE, to)
                factor = (new_high - low) / (high - low)
                return lambda v: low + (v - low) * factor
            new_low = min(high - MIN_SIZE, to)
            factor = (high - new_low) / (high - low)
            return lambda v: high - (high - v) * factor

        map_x = scaled(left, right, hx, px)
        map_y = scaled(top, bottom, hy, py)
        piece.points = [(map_x(x), map_y(y)) for x, y in original.points]

    @staticmethod
    def move_point(piece, index, mx, my):
        points = list(piece.points)
        points[index] = piece.to_local(mx, my)
        piece.points = points

    @staticmethod
    def insert_point(piece, index, mx, my):
        """Add a corner, or a bend in a line, at a spot."""
        if piece.is_round:
            return False
        piece.points = (piece.points[:index] + [piece.to_local(mx, my)]
                        + piece.points[index:])
        # A gnome home's room walls are counted by place in its outline.
        piece.joins = [(a + (a >= index), b + (b >= index))
                       for a, b in piece.joins]
        return True

    @staticmethod
    def remove_point(piece, index):
        """Take away a corner or bend, if the piece keeps enough of them."""
        least = MIN_AREA_POINTS if piece.is_area else MIN_LINE_POINTS
        if piece.is_round or len(piece.points) <= least:
            return False
        piece.points = piece.points[:index] + piece.points[index + 1:]
        piece.joins = [(a - (a > index), b - (b > index))
                       for a, b in piece.joins if index not in (a, b)]
        return True
