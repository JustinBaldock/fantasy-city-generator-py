"""Plots of land with a building on each, and burgage plots.

This module is original to this port. The original fills each plot with its
building, edge to edge. Here a plot is drawn as a property with a border, and
its building stands inside it, so there is open ground around the house.

A burgage plot is the medieval town plot. Its house stands at the street
front, and the land behind is the garden, for growing food and keeping
animals. Government and military buildings stand in the middle of their plots
instead.

All of this uses its own random numbers and the wards only cut their land
into bigger plots, so the streets, walls and water stay the same.
"""

import math
import random

from .geometry import Point, Polygon, distance

GRID = 4  # Spots to try across a plot, each way.
REFINE = 3  # How many times to look closer around the best spot.

MIN_CLEARANCE = 1.0  # A plot narrower than this is left empty.
MARGIN = 0.2  # Open ground kept between a building and its plot's border.
MAX_ASPECT = 3.0  # How many times longer than wide a rectangle can be.

# Sizes to try for a rectangle, as shares of the widest circle that fits. The
# last one always fits, since its corners then stay inside that circle.
RECTANGLE_SCALES = (1.5, 1.3, 1.15, 1.0, 0.85, 0.7, 0.6, 0.5)

FRONT_GAP = 0.15  # Between a burgage house and the street edge of its plot.
FRONT_SHARE = (0.55, 0.85)  # How much of the street front a house takes.
HOUSE_DEPTH = (0.7, 1.3)  # A house's depth, as a share of its width.
MAX_HOUSE_DEPTH = 0.45  # Of the plot's depth, leaving the rest as garden.
MIN_HOUSE = 1.2  # A smaller house is too tiny to read.
FIT_TRIES = 8
ON_EDGE = 0.05  # How close a corner must be to the block's edge to be on it.
LANE_PROBE = 0.3  # How far out from an edge to look for a lane.

GARDEN_TREE_RADIUS = (0.8, 1.4)
MIN_GARDEN = 30  # The least open ground, in square units, that has trees.
GARDEN_PER_TREE = 22  # Square units of open ground for each tree.
MAX_GARDEN_TREES = 6
GARDEN_CHANCE = 0.8  # Of a big enough garden having any trees.
TREE_TRIES = 40  # Spots to try for each tree.
TREE_GAP = 0.3  # Between a tree and its house or its plot's border.
TREE_OVERLAP = 0.9  # Trees closer than this share of their radii overlap.


class Plot(Polygon):
    """A property's border, with the building that stands on it.

    The border is what the editor moves and pushes, and the house goes with
    it.
    """

    def __init__(self, points, house):
        super().__init__(points)
        self.house = house
        self.trees = []  # (x, y, radius) for each tree in the garden.

    def shift(self, dx, dy):
        """Move the house and trees, which go wherever the plot goes."""
        self.house[:] = [Point(v.x + dx, v.y + dy) for v in self.house]
        self.trees = [(x + dx, y + dy, r) for x, y, r in self.trees]


def clearance(plot, x, y):
    """How far a point is from the plot's nearest edge, 0 if it's outside."""
    if not plot.contains_point(Point(x, y)):
        return 0.0
    nearest = math.inf
    for a, b in plot.edges():
        nearest = min(nearest, _to_segment(x, y, a, b))
    return nearest


def _to_segment(x, y, a, b):
    dx = b.x - a.x
    dy = b.y - a.y
    length = dx * dx + dy * dy
    along = ((x - a.x) * dx + (y - a.y) * dy) / length if length else 0.0
    along = max(0.0, min(1.0, along))
    return math.hypot(x - a.x - along * dx, y - a.y - along * dy)


def roomiest_spot(plot):
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
    x, y = max(spots, key=lambda s: clearance(plot, *s))

    for _ in range(REFINE):
        step_x /= 2
        step_y /= 2
        spots = [(x + i * step_x, y + j * step_y)
                 for i in (-1, 0, 1) for j in (-1, 0, 1)]
        x, y = max(spots, key=lambda s: clearance(plot, *s))
    return x, y, clearance(plot, x, y)


def long_way(plot):
    """The start of the plot's longest edge, and that edge's direction."""
    start, end = max(plot.edges(), key=lambda e: distance(e[0], e[1]))
    return start, end.subtract(start).norm(1.0)


def length_of(plot, start, along):
    """How far the plot reaches back and forward from a point along a line."""
    reach = [v.subtract(start).dot(along) for v in plot]
    return min(reach), max(reach)


def rectangle(x, y, along, half_length, half_width):
    """A rectangle around a point, with its length in the direction given."""
    across = along.rotate90()
    return Polygon(
        Point(x + way * half_length * along.x + side * half_width * across.x,
              y + way * half_length * along.y + side * half_width * across.y)
        for way, side in ((-1, -1), (1, -1), (1, 1), (-1, 1)))


def rectangle_on(plot, spot, chooser):
    """A square or rectangle in the middle of a plot, along its longest edge."""
    x, y, room = spot
    if room < MIN_CLEARANCE:
        return None
    room -= MARGIN

    start, along = long_way(plot)
    low, high = length_of(plot, start, along)
    longest = min((high - low) / (2 * room), MAX_ASPECT)
    aspect = math.sqrt(chooser.uniform(1.0, max(1.0, longest)))

    for scale in RECTANGLE_SCALES:
        shape = rectangle(x, y, along, room * scale * aspect,
                          room * scale / aspect)
        if all(clearance(plot, v.x, v.y) >= MARGIN for v in shape):
            break
    return shape


def plot_with_rectangle(plot, chooser):
    """The plot with a building in its middle, or None if it's too small."""
    house = rectangle_on(plot, roomiest_spot(plot), chooser)
    return None if house is None else Plot(plot, house)


def _frontage(plot, block, neighbours):
    """The edge the house faces: a street, else a lane, else the longest.

    The block is the ward's land inside its streets, so a plot edge along the
    block's edge faces a street. Lanes run between plots inside the block, so
    just beyond an edge on a lane there's no neighbouring plot.
    """
    centre = plot.centroid

    def on_street(a, b):
        return any(_to_segment(a.x, a.y, c, d) < ON_EDGE
                   and _to_segment(b.x, b.y, c, d) < ON_EDGE
                   for c, d in block.edges())

    def on_lane(a, b):
        middle = Point((a.x + b.x) / 2, (a.y + b.y) / 2)
        out = b.subtract(a).rotate90().norm(LANE_PROBE)
        if out.dot(middle.subtract(centre)) < 0:
            out = out.scale(-1)
        probe = middle.add(out)
        return not any(other is not plot and other.contains_point(probe)
                       for other in neighbours)

    edges = [(a, b) for a, b in plot.edges() if distance(a, b) > 0]
    front = ([e for e in edges if on_street(*e)]
             or [e for e in edges if on_lane(*e)] or edges)
    return max(front, key=lambda e: distance(e[0], e[1]))


def burgage(plot, block, neighbours, chooser):
    """A plot with its house at the street front and its garden behind.

    neighbours are the other plots in the ward, for finding lanes.
    """
    a, b = _frontage(plot, block, neighbours)
    front = distance(a, b)
    along = b.subtract(a).norm(1.0)
    inward = along.rotate90()
    centre = plot.centroid
    if centre.subtract(a).dot(inward) < 0:
        inward = inward.scale(-1)
    _, deep = length_of(plot, a, inward)

    width = front * chooser.uniform(*FRONT_SHARE)
    depth = min(width * chooser.uniform(*HOUSE_DEPTH), deep * MAX_HOUSE_DEPTH)
    place = chooser.random()

    for _ in range(FIT_TRIES):
        if min(width, depth) < MIN_HOUSE:
            break
        # Anywhere along the front that the house fits.
        slack = max(0.0, front - width - 2 * MARGIN)
        middle = MARGIN + width / 2 + slack * place
        x = a.x + along.x * middle + inward.x * (FRONT_GAP + depth / 2)
        y = a.y + along.y * middle + inward.y * (FRONT_GAP + depth / 2)
        house = rectangle(x, y, along, width / 2, depth / 2)
        if all(clearance(plot, v.x, v.y) >= FRONT_GAP / 2 for v in house):
            return Plot(plot, house)
        width *= 0.85
        depth *= 0.9

    # Too tight for a house and garden, so a cottage fills it.
    return plot_with_rectangle(plot, chooser)


def _to_outline(polygon, x, y):
    return min(_to_segment(x, y, a, b) for a, b in polygon.edges())


def _plant(plot, chooser):
    """A few trees in the open ground of a big enough plot."""
    garden = abs(plot.square) - abs(plot.house.square)
    if garden < MIN_GARDEN or chooser.random() > GARDEN_CHANCE:
        return
    wanted = min(MAX_GARDEN_TREES,
                 max(1, round(garden / GARDEN_PER_TREE * chooser.random() * 2)))
    left = min(v.x for v in plot)
    right = max(v.x for v in plot)
    top = min(v.y for v in plot)
    bottom = max(v.y for v in plot)

    for _ in range(wanted):
        radius = chooser.uniform(*GARDEN_TREE_RADIUS)
        for _ in range(TREE_TRIES):
            x = chooser.uniform(left, right)
            y = chooser.uniform(top, bottom)
            if (clearance(plot, x, y) >= radius + TREE_GAP
                    and not plot.house.contains_point(Point(x, y))
                    and _to_outline(plot.house, x, y) >= radius + TREE_GAP
                    and all(math.hypot(x - tx, y - ty)
                            >= (radius + tr) * TREE_OVERLAP
                            for tx, ty, tr in plot.trees)):
                plot.trees.append((x, y, radius))
                break


def plant_gardens(model):
    """Put trees in the gardens of the bigger plots."""
    chooser = random.Random(f"{model.seed} garden trees")
    for patch in model.patches:
        for plot in patch.ward.geometry:
            if isinstance(plot, Plot):
                _plant(plot, chooser)


def build_burgage_plots(model):
    """Put a house at the front of each home plot, with its garden behind.

    Government and military buildings stand in the middle of their plots.
    Castles, temples, markets and farms stay as they are.
    """
    chooser = random.Random(f"{model.seed} burgage plots")
    for patch in model.patches:
        ward = patch.ward
        plots = [plot for plot in ward.geometry if len(plot) >= 3]
        if ward.homes:
            block = ward.get_city_block()
            built = [burgage(plot, block, plots, chooser) for plot in plots]
        elif ward.rectangle_share:
            built = [plot_with_rectangle(plot, chooser) for plot in plots]
        else:
            continue
        ward.geometry = [plot for plot in built if plot is not None]
