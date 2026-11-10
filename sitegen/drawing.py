"""What a location draws, as the city generator's layers.

The pieces are drawn with the city map's own styles, widths and colours, so a
farm here looks like a farm outside a town there. The furrows of a field, the
rows of an orchard and the trees of a wood are worked out from the piece's
shape each time it's drawn, so they follow it when it moves, turns or changes
shape.
"""

import math
import random

from citygen.countryside import (
    FURROW_SPACING,
    TREE_JITTER,
    TREE_RADIUS,
    TREE_SPACING,
    furrows,
    orchard_rows,
)
from citygen.geometry import chaikin
from citygen.plots import clearance
from citygen.layers import (
    FURROW_WIDTH,
    LINE_ROUNDING,
    NORMAL_STROKE,
    PLOT_BORDER,
    STREET_LINE,
    Layer,
)
from citygen.water import BRIDGE_WIDTH, RIVER_WIDTH
from citygen.wards import MAIN_STREET

from .site import inside

HEDGE_WIDTH = 1.1
WALL_WIDTH = 0.45
GATE_WIDTH = 0.6
POND_ROUNDING = 3
# How much of a tree's radius stays inside its wood.
WOOD_EDGE = 0.6

# How wide each kind of line is drawn, for picking it out with the pointer.
LINE_WIDTHS = {
    "road": MAIN_STREET + NORMAL_STROKE,
    "track": STREET_LINE,
    "river": RIVER_WIDTH,
    "bridge": BRIDGE_WIDTH + NORMAL_STROKE,
    "hedge": HEDGE_WIDTH,
    "wall": WALL_WIDTH,
    "gate": GATE_WIDTH,
}

# The order kinds are drawn in, bottom first. Picking with the pointer goes
# the other way, so what's on top is picked first.
DRAW_ORDER = ("meadow", "field", "wood", "orchard", "yard", "pond", "river",
              "tree", "road", "track", "bridge", "hedge", "wall", "building",
              "gnome_home", "gate", "well")


def wood_trees(piece):
    """The trees of a wood, as (x, y, radius), filling its outline."""
    outline = piece.world()
    polygon = piece.polygon()
    chooser = random.Random(piece.seed)
    xs = [x for x, _ in outline]
    ys = [y for _, y in outline]
    trees = []
    row = 0
    y = min(ys) + TREE_SPACING / 2
    while y < max(ys):
        # Every other row is shifted half a step, so the trees pack tightly.
        x = min(xs) + TREE_SPACING * (0.25 + 0.5 * (row % 2))
        while x < max(xs):
            tx = x + chooser.uniform(-TREE_JITTER, TREE_JITTER)
            ty = y + chooser.uniform(-TREE_JITTER, TREE_JITTER)
            radius = chooser.uniform(*TREE_RADIUS)
            # Mostly inside, so a wood keeps to its own ground.
            if (inside(outline, tx, ty)
                    and clearance(polygon, tx, ty) >= radius * WOOD_EDGE):
                trees.append((tx, ty, radius))
            x += TREE_SPACING
        y += TREE_SPACING * math.sqrt(3) / 2
        row += 1
    if not trees:
        cx = sum(xs) / len(xs)
        cy = sum(ys) / len(ys)
        trees.append((cx, cy, TREE_RADIUS[0]))
    return trees


def orchard_trees(piece):
    return orchard_rows(piece.polygon(), random.Random(piece.seed))


def field_furrows(piece):
    return [[(a.x, a.y), (b.x, b.y)]
            for a, b in furrows(piece.polygon(), FURROW_SPACING)]


def _room_walls(piece):
    outline = piece.world()
    return [[outline[a], outline[b]] for a, b in piece.joins
            if a < len(outline) and b < len(outline)]


def _ordered(pieces):
    rank = {kind: i for i, kind in enumerate(DRAW_ORDER)}
    return sorted(pieces, key=lambda piece: rank[piece.kind])


def build_layers(site, palette):
    """Everything in a location, in drawing order."""
    groups = {kind: [] for kind in DRAW_ORDER}
    for piece in _ordered(site.pieces):
        groups[piece.kind].append(piece)

    def shapes(kind):
        return [piece.world() for piece in groups[kind]]

    def rounded(kind):
        return [chaikin(piece.world(), LINE_ROUNDING) for piece in groups[kind]]

    furrow_lines = [line for piece in groups["field"]
                    for line in field_furrows(piece)]
    forest = [tree for piece in groups["wood"] for tree in wood_trees(piece)]
    orchards = [tree for piece in groups["orchard"]
                for tree in orchard_trees(piece)]
    ponds = [chaikin(piece.world(), POND_ROUNDING, closed=True)
             for piece in groups["pond"]]
    roads = rounded("road")
    buildings = shapes("building") + shapes("gnome_home")
    room_walls = [wall for piece in groups["gnome_home"]
                  for wall in _room_walls(piece)]

    def circles(kind):
        return [(piece.x, piece.y, piece.radius) for piece in groups[kind]]

    return [
        Layer("Meadows", fill=palette.green, polygons=shapes("meadow")),
        Layer("Furrows", stroke=palette.furrow, width=FURROW_WIDTH, cap="flat",
              polylines=furrow_lines),
        Layer("Forest", fill=palette.forest, circles=forest),
        Layer("Orchard edges", stroke=palette.furrow, width=FURROW_WIDTH * 2,
              polygons=shapes("orchard")),
        Layer("Orchards", fill=palette.forest, circles=orchards),
        Layer("Plots", fill=palette.garden, stroke=palette.medium,
              width=PLOT_BORDER, polygons=shapes("yard")),
        Layer("Ponds", fill=palette.water, polygons=ponds),
        Layer("River", stroke=palette.water, width=RIVER_WIDTH, cap="flat",
              join="round", polylines=rounded("river")),
        Layer("Trees", fill=palette.forest, circles=circles("tree")),
        Layer("Road edges", stroke=palette.medium,
              width=MAIN_STREET + NORMAL_STROKE, cap="flat", polylines=roads),
        Layer("Roads", stroke=palette.paper,
              width=MAIN_STREET - NORMAL_STROKE, cap="flat", polylines=roads),
        Layer("Tracks", stroke=palette.medium, width=STREET_LINE,
              join="round", polylines=rounded("track")),
        Layer("Bridge edges", stroke=palette.medium,
              width=BRIDGE_WIDTH + NORMAL_STROKE, cap="flat",
              polylines=shapes("bridge")),
        Layer("Bridges", stroke=palette.paper,
              width=BRIDGE_WIDTH - NORMAL_STROKE, cap="flat",
              polylines=shapes("bridge")),
        Layer("Hedges", stroke=palette.forest, width=HEDGE_WIDTH,
              join="round", polylines=rounded("hedge")),
        Layer("Stone walls", stroke=palette.dark, width=WALL_WIDTH,
              join="round", polylines=shapes("wall")),
        Layer("Buildings", fill=palette.light, stroke=palette.dark,
              width=NORMAL_STROKE, polygons=buildings),
        Layer("Room walls", stroke=palette.dark, width=NORMAL_STROKE,
              cap="flat", polylines=room_walls),
        Layer("Gates", stroke=palette.dark, width=GATE_WIDTH, cap="flat",
              polylines=shapes("gate")),
        Layer("Wells", fill=palette.dark, circles=circles("well")),
    ]
