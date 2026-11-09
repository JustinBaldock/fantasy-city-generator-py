"""Farm fields, orchards and forests.

This module is original to this port. The published source leaves the land
around a city empty, so these are our own methods.

The fields are wheat fields, two to three times the size of an orchard.
Orchards take some of the farm plots nearest each farmhouse, and the higher
farmland near town that is too steep for fields. Their trees stand in rows
along the plot's longest edge. They use their own random numbers, and the
higher land is divided after the fields, so turning orchards on or off
leaves the fields alone.

A smooth terrain pattern decides what grows where. Fields fill whole patches
near the city. Forests ignore the patches and follow the pattern instead, so
their edges wander. A forest is many overlapping circles of one colour, which
merge into a single mass with a bumpy edge.
"""

import math
import random

from .geometry import Point, distance, interpolate, max_by
from .plots import clearance
from .wards import Farm, Ward, create_alleys
from .water import RIVER_WIDTH

VIEW_MARGIN = 1.3  # How far past the city land is worth filling.

FIELD_REACH = 0.55  # How far out fields go, in city radii.
FIELD_SHARE = 0.45  # The share of the land low enough for fields.
MIN_FIELD_BLOCK = 300
PLOT_SIZE = 220  # An orchard.
WHEAT_FIELD = PLOT_SIZE * 2.5  # Two to three orchards.
FURROW_SPACING = 0.9

TREE_SPACING = 5.0
TREE_JITTER = 1.2
TREE_RADIUS = (4.0, 5.2)
FOREST_SHARE = 0.8  # The share of the visible open ground that is forest.
LONE_TREE_BAND = 0.14
LONE_TREE_CHANCE = 0.05
LONE_TREE_RADIUS = (1.4, 2.2)

ORCHARD_SHARE = 0.6  # Of the plots nearest a farmhouse, when it has any.
HILL_ORCHARDS = 0.6  # The share of the higher farmland that is orchard.
ORCHARD_REACH = 25.0  # How far from its farmhouse an orchard can be.
ORCHARD_CHANCE = 0.5  # Of a farm having an orchard at all.
ORCHARD_SPACING = 3.0  # Between trees in a row, and between the rows.
ORCHARD_RADIUS = (0.9, 1.2)
ORCHARD_EDGE = 0.4  # Kept between a tree and the edge of its orchard.

CLEARING = 9.0  # Open ground between the city and any forest.
ROAD_CLEARANCE = 2.4

CELL = 3.0  # The size of the squares used to mark ground as taken.


def _terrain(model):
    """A smooth pattern over the map, running from about -1 to 1."""
    features = model.features
    wave = model.city_radius * 1.5
    waves = []
    for _ in range(3):
        angle = features.uniform(0, 2 * math.pi)
        waves.append((math.cos(angle) / wave, math.sin(angle) / wave,
                      features.uniform(0, 2 * math.pi)))

    def height(x, y):
        return sum(math.sin(x * a + y * b + c) for a, b, c in waves) / 2

    return height


def _height_at_share(model, height, share):
    """The height with that share of the map above it."""
    limit = model.city_radius * 1.1 * VIEW_MARGIN
    steps = 16
    samples = sorted(
        height(limit * (2 * i / (steps - 1) - 1),
               limit * (2 * j / (steps - 1) - 1))
        for i in range(steps) for j in range(steps))
    return samples[int((1 - share) * (len(samples) - 1))]


def furrows(plot, spacing=FURROW_SPACING):
    """Parallel lines across a plot, along its longest edge."""
    start = max_by(plot, lambda v: plot.vector(v).length)
    along = plot.vector(start).norm(1.0)
    across = along.rotate90()

    def height(v):
        return v.subtract(start).dot(across)

    heights = [height(v) for v in plot]
    lines = []
    level = min(heights) + spacing / 2
    while level < max(heights):
        hits = []
        for v0, v1 in plot.edges():
            h0 = height(v0) - level
            h1 = height(v1) - level
            if (h0 < 0) != (h1 < 0):
                hits.append(interpolate(v0, v1, h0 / (h0 - h1)))
        hits.sort(key=lambda p: p.subtract(start).dot(along))
        for i in range(0, len(hits) - 1, 2):
            lines.append((hits[i], hits[i + 1]))
        level += spacing
    return lines


class _Ground:
    """A grid of squares for marking land that trees must stay off."""

    def __init__(self):
        self.taken = set()

    def _cell(self, x, y):
        return int(x // CELL), int(y // CELL)

    def mark(self, x, y, reach):
        cells = int(reach // CELL) + 1
        cx, cy = self._cell(x, y)
        for i in range(cx - cells, cx + cells + 1):
            for j in range(cy - cells, cy + cells + 1):
                if math.hypot((i - cx) * CELL, (j - cy) * CELL) <= reach + CELL:
                    self.taken.add((i, j))

    def mark_line(self, a, b, reach):
        steps = max(1, int(distance(a, b) / CELL))
        for i in range(steps + 1):
            p = interpolate(a, b, i / steps)
            self.mark(p.x, p.y, reach)

    def mark_inside(self, polygon):
        left, top = self._cell(min(v.x for v in polygon),
                               min(v.y for v in polygon))
        right, bottom = self._cell(max(v.x for v in polygon),
                                   max(v.y for v in polygon))
        for i in range(left, right + 1):
            for j in range(top, bottom + 1):
                if polygon.contains_point(Point((i + 0.5) * CELL,
                                                (j + 0.5) * CELL)):
                    self.taken.add((i, j))

    def is_free(self, x, y):
        return self._cell(x, y) not in self.taken


def _land_patches(model):
    limit = model.city_radius * 1.1 * VIEW_MARGIN
    for patch in model.patches:
        center = patch.shape.center
        if (not patch.within_city and abs(center.x) < limit
                and abs(center.y) < limit):
            yield patch


def _distance_from_city(model):
    points = [v for p in model.patches if p.within_city for v in p.shape]

    def measure(point):
        return min(distance(point, v) for v in points)

    return measure


def orchard_rows(plot, chooser, spacing=ORCHARD_SPACING, roads=()):
    """Trees in straight rows across a plot, as (x, y, radius).

    roads are (a, b) pieces of road that the trees keep clear of.
    """
    start = max_by(plot, lambda v: plot.vector(v).length)
    along = plot.vector(start).norm(1.0)
    across = along.rotate90()
    reach_along = [v.subtract(start).dot(along) for v in plot]
    reach_across = [v.subtract(start).dot(across) for v in plot]

    # The grid is centred, with room at the edges for the biggest tree, so
    # every row that fits is whole.
    room = ORCHARD_RADIUS[1] + ORCHARD_EDGE

    def places(low, high):
        count = int((high - low - 2 * room) // spacing) + 1
        if count < 1:
            return []
        first = (low + high - (count - 1) * spacing) / 2
        return [first + i * spacing for i in range(count)]

    trees = []
    for row in places(min(reach_across), max(reach_across)):
        for place in places(min(reach_along), max(reach_along)):
            x = start.x + along.x * place + across.x * row
            y = start.y + along.y * place + across.y * row
            if (clearance(plot, x, y) >= room
                    and all(_to_road(x, y, a, b) >= room + ROAD_CLEARANCE
                            for a, b in roads)):
                trees.append((x, y, chooser.uniform(*ORCHARD_RADIUS)))
    return trees


def _to_road(x, y, a, b):
    dx = b.x - a.x
    dy = b.y - a.y
    length = dx * dx + dy * dy
    t = ((x - a.x) * dx + (y - a.y) * dy) / length if length else 0.0
    t = max(0.0, min(1.0, t))
    return math.hypot(x - a.x - t * dx, y - a.y - t * dy)


def _road_pieces(model):
    return [(a, b) for road in model.roads for a, b in zip(road, road[1:])]


def _farmhouse(ward):
    points = [v for building in ward.geometry for v in building]
    if not points:
        return None
    return Point(sum(v.x for v in points) / len(points),
                 sum(v.y for v in points) / len(points))


def _plant_orchards(model, farm_plots):
    """Turn the plots nearest each farmhouse into orchards.

    Returns the plots left for fields.
    """
    chooser = random.Random(f"{model.seed} orchards")
    roads = _road_pieces(model)
    left = []
    for ward, plots in farm_plots:
        house = _farmhouse(ward) if isinstance(ward, Farm) else None
        if house is None or chooser.random() > ORCHARD_CHANCE:
            left += plots
            continue
        near = sorted(plots, key=lambda p: distance(p.centroid, house))
        count = max(1, round(len(near) * ORCHARD_SHARE * chooser.random()))
        for i, field in enumerate(near):
            if i >= count or distance(field.centroid, house) >= ORCHARD_REACH:
                left.append(field)
                continue
            # A field's worth of land makes a few orchards.
            for plot in _cut(field, PLOT_SIZE):
                trees = orchard_rows(plot, chooser, roads=roads)
                if trees:
                    model.orchards.append(plot)
                    model.orchard_trees += trees
    return left


def _cut(land, size):
    return [plot for plot in create_alleys(land, size, 0.25, 0.3, 0.12)
            if len(plot) >= 3]


def _farm_plots(ward, size):
    """The ward's land cut into plots, missing any with a house on them."""
    block = ward.get_city_block().shrink_eq(1.0)
    if len(block) < 3 or block.square < MIN_FIELD_BLOCK:
        return None
    houses = [v for building in ward.geometry for v in building]
    return [plot for plot in _cut(block, size)
            if not any(plot.contains_point(v) for v in houses)]


def _plant_hill_orchards(model, hill_plots):
    chooser = random.Random(f"{model.seed} hill orchards")
    roads = _road_pieces(model)
    for ward, plots in hill_plots:
        planted = False
        for plot in plots:
            if chooser.random() < HILL_ORCHARDS:
                trees = orchard_rows(plot, chooser, roads=roads)
                if trees:
                    model.orchards.append(plot)
                    model.orchard_trees += trees
                    planted = True
        if planted and ward.label is None:
            ward.label = "Orchard"


def _build_fields(model, height):
    from_city = _distance_from_city(model)
    reach = model.city_radius * FIELD_REACH
    top = _height_at_share(model, height, 1 - FIELD_SHARE)
    farm_plots = []
    hills = []

    for patch in _land_patches(model):
        ward = patch.ward
        if type(ward) not in (Ward, Farm):
            continue
        center = patch.shape.center
        if from_city(center) > reach:
            continue
        if height(center.x, center.y) > top:
            hills.append(ward)
            continue
        plots = _farm_plots(ward, WHEAT_FIELD)
        if plots is not None:
            farm_plots.append((ward, plots))

    if model.orchards_needed:
        hill_plots = [(ward, _farm_plots(ward, PLOT_SIZE)) for ward in hills]
        _plant_hill_orchards(
            model, [(w, p) for w, p in hill_plots if p is not None])
        left = _plant_orchards(model, farm_plots)
    else:
        left = [plot for _, plots in farm_plots for plot in plots]
    if model.fields_needed:
        for plot in left:
            model.fields.append(plot)
            model.furrows += furrows(plot)

    fields = {id(plot) for plot in model.fields}
    for ward, plots in farm_plots:
        if ward.label is not None:
            continue
        if model.fields_needed and (
                not plots or any(id(plot) in fields for plot in plots)):
            ward.label = "Wheat fields"
        elif plots:
            ward.label = "Orchard"


def _ground_for_trees(model):
    ground = _Ground()
    tree_room = TREE_RADIUS[1]

    for patch in model.patches:
        if patch.within_city:
            ground.mark_inside(patch.shape)
            for a, b in patch.shape.edges():
                ground.mark_line(a, b, CLEARING)
        elif isinstance(patch.ward, Farm):
            for building in patch.ward.geometry:
                for v in building:
                    ground.mark(v.x, v.y, tree_room + 2)

    for road in model.roads:
        for a, b in zip(road, road[1:]):
            ground.mark_line(a, b, ROAD_CLEARANCE + tree_room)
    for a, b in zip(model.river, model.river[1:]):
        ground.mark_line(a, b, RIVER_WIDTH / 2 + tree_room + 1)

    for plot in model.fields + model.orchards:
        ground.mark_inside(plot)
        for a, b in plot.edges():
            ground.mark_line(a, b, tree_room)
    return ground


def _tree_sites(model):
    """Scattered points on all the open ground, staying off water."""
    features = model.features
    ground = _ground_for_trees(model)
    limit = model.city_radius * 1.1 * VIEW_MARGIN
    rows = int(limit * 2 / TREE_SPACING) + 1

    sites = []
    for row in range(rows):
        for column in range(rows):
            x = (column * TREE_SPACING - limit
                 + features.uniform(-TREE_JITTER, TREE_JITTER))
            y = (row * TREE_SPACING - limit
                 + features.uniform(-TREE_JITTER, TREE_JITTER))
            if not ground.is_free(x, y):
                continue
            if (model.seaward is not None and model.seaward(Point(x, y))
                    > -(TREE_RADIUS[1] + 2)):
                continue
            sites.append((x, y))
    return sites


def _build_trees(model, height):
    features = model.features
    sites = _tree_sites(model)
    if not sites:
        return

    # Going by the open ground in view means a forced forest always shows,
    # even when the terrain's high ground lies under the city.
    edge = model.city_radius * 1.1
    visible = [s for s in sites if abs(s[0]) < edge and abs(s[1]) < edge]
    levels = sorted(height(x, y) for x, y in visible or sites)
    forest_line = levels[int((1 - FOREST_SHARE) * (len(levels) - 1))]

    for x, y in sites:
        level = height(x, y)
        if level > forest_line:
            radius = features.uniform(*TREE_RADIUS)
        elif (level > forest_line - LONE_TREE_BAND
              and features.random() < LONE_TREE_CHANCE):
            radius = features.uniform(*LONE_TREE_RADIUS)
        else:
            continue
        model.trees.append((x, y, radius))


def build_countryside(model):
    """Fill the land around the city with fields and forest."""
    if not (model.fields_needed or model.forests_needed
            or model.orchards_needed):
        return
    height = _terrain(model)
    if model.fields_needed or model.orchards_needed:
        _build_fields(model, height)
    if model.forests_needed:
        _build_trees(model, height)
