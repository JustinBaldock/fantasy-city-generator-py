"""The kinds of ward and how each fills its land, from the wards/ folder."""

import math

from . import cutter, rng
from .geometry import (
    GenerationError,
    Polygon,
    distance,
    distance_to_line,
    fdiv,
    interpolate,
    max_by,
    min_by,
)
from .walls import CurtainWall

MAIN_STREET = 2.0
REGULAR_STREET = 1.0
ALLEY = 0.6


def _longest_edge_start(poly):
    return min_by(poly, lambda v: -poly.vector(v).length)


def create_alleys(p, min_sq, grid_chaos, size_chaos, empty_prob=0.04,
                  split=True):
    """Divide a block into buildings, splitting along its longest edge."""
    v = None
    length = -1.0
    for p0, p1 in p.edges():
        edge_length = distance(p0, p1)
        if edge_length > length:
            length = edge_length
            v = p0

    spread = 0.8 * grid_chaos
    ratio = (1 - spread) / 2 + rng.random() * spread

    # Keep buildings rectangular, even in chaotic wards.
    small = p.square < min_sq * 4
    angle_spread = math.pi / 6 * grid_chaos * (0.0 if small else 1)
    b = (rng.random() - 0.5) * angle_spread

    halves = cutter.bisect(p, v, ratio, b, ALLEY if split else 0.0)

    buildings = []
    for half in halves:
        if half.square < min_sq * 2 ** (4 * size_chaos * (rng.random() - 0.5)):
            if not rng.chance(empty_prob):
                buildings.append(half)
        else:
            buildings += create_alleys(
                half, min_sq, grid_chaos, size_chaos, empty_prob,
                half.square > min_sq / (rng.random() * rng.random()))
    return buildings


def create_ortho_building(poly, min_block_sq, fill):
    """Divide a shape at right angles, for castles and big buildings."""

    def slice_block(block, c1, c2):
        v0 = _longest_edge_start(block)
        v1 = block.next(v0)
        v = v1.subtract(v0)

        ratio = 0.4 + rng.random() * 0.2
        p1 = interpolate(v0, v1, ratio)

        c = c1 if abs(v.dot(c1)) < abs(v.dot(c2)) else c2

        buildings = []
        for half in block.cut(p1, p1.add(c)):
            if half.square < min_block_sq * 2 ** (rng.normal() * 2 - 1):
                if rng.chance(fill):
                    buildings.append(half)
            else:
                buildings += slice_block(half, c1, c2)
        return buildings

    if poly.square < min_block_sq:
        return [poly]

    c1 = poly.vector(_longest_edge_start(poly))
    c2 = c1.rotate90()
    for _ in range(1000):
        blocks = slice_block(poly, c1, c2)
        if blocks:
            return blocks
    raise GenerationError("A building came out empty every time")


class Ward:
    """Land with nothing on it, and the base of all the others.

    A ward type with a rate_location gets the best place it can find in the
    city, and the lowest rate wins. The others land anywhere.
    """

    label = None
    rate_location = None

    def __init__(self, model, patch):
        self.model = model
        self.patch = patch
        self.geometry = []

    def create_geometry(self):
        self.geometry = []

    def get_city_block(self):
        model = self.model
        patch = self.patch
        inset = []

        inner_patch = model.wall is None or patch.within_walls
        for v0, v1 in patch.shape.edges():
            if model.wall is not None and model.wall.borders_by(patch, v0, v1):
                # Not too close to the wall.
                inset.append(MAIN_STREET / 2)
                continue

            on_street = (inner_patch
                         and model.plaza is not None
                         and model.plaza.shape.find_edge(v1, v0) != -1)
            if not on_street:
                on_street = any(
                    v0 in street and v1 in street
                    for street in model.arteries)
            if on_street:
                inset.append(MAIN_STREET / 2)
            elif inner_patch:
                inset.append(REGULAR_STREET / 2)
            else:
                inset.append(ALLEY / 2)

        if patch.shape.is_convex():
            return patch.shape.shrink(inset)
        return patch.shape.buffer(inset)

    def filter_outskirts(self):
        """Thin out the buildings towards the edge of the city."""
        model = self.model
        shape = self.patch.shape
        populated_edges = []

        def add_edge(v1, v2, factor=1.0):
            dx = v2.x - v1.x
            dy = v2.y - v1.y

            def reach(v):
                if v is v1 or v is v2:
                    return 0.0
                return distance_to_line(v1.x, v1.y, dx, dy, v.x, v.y) * factor

            d = reach(max_by(shape, reach))
            populated_edges.append((v1.x, v1.y, dx, dy, d))

        for v1, v2 in shape.edges():
            on_road = any(
                v1 in street and v2 in street for street in model.arteries)
            if on_road:
                add_edge(v1, v2, 1)
            else:
                neighbour = model.get_neighbour(self.patch, v1)
                if neighbour is not None and neighbour.within_city:
                    add_edge(v1, v2,
                             1 if model.is_enclosed(neighbour) else 0.4)

        # How built-up the land around each vertex is.
        density = []
        for v in shape:
            if v in model.gates:
                density.append(1)
            elif all(p.within_city for p in model.patch_by_vertex(v)):
                density.append(2 * rng.random())
            else:
                density.append(0)

        kept = []
        for building in self.geometry:
            min_dist = 1.0
            for x, y, dx, dy, reach in populated_edges:
                for v in building:
                    dist = fdiv(distance_to_line(x, y, dx, dy, v.x, v.y), reach)
                    if dist < min_dist:
                        min_dist = dist

            weights = shape.interpolate(building.center)
            p = sum(density[j] * weights[j] for j in range(len(weights)))
            min_dist = fdiv(min_dist, p)

            if rng.fuzzy(1) > min_dist:
                kept.append(building)
        self.geometry = kept


class CommonWard(Ward):

    def __init__(self, model, patch, min_sq, grid_chaos, size_chaos,
                 empty_prob=0.04):
        super().__init__(model, patch)
        self.min_sq = min_sq
        self.grid_chaos = grid_chaos
        self.size_chaos = size_chaos
        self.empty_prob = empty_prob

    def create_geometry(self):
        block = self.get_city_block()
        self.geometry = create_alleys(
            block, self.min_sq, self.grid_chaos, self.size_chaos,
            self.empty_prob)
        if not self.model.is_enclosed(self.patch):
            self.filter_outskirts()


def _plaza_or_center(model):
    if model.plaza is not None:
        return model.plaza.shape.center
    return model.center


class CraftsmenWard(CommonWard):
    label = "Craftsmen"

    def __init__(self, model, patch):
        super().__init__(
            model, patch,
            10 + 80 * rng.random() * rng.random(),  # small to large
            0.5 + rng.random() * 0.2, 0.6)  # moderately regular


class GateWard(CommonWard):
    label = "Gate"

    def __init__(self, model, patch):
        super().__init__(
            model, patch,
            10 + 50 * rng.random() * rng.random(),
            0.5 + rng.random() * 0.3, 0.7)


class MerchantWard(CommonWard):
    label = "Merchant"

    def __init__(self, model, patch):
        super().__init__(
            model, patch,
            50 + 60 * rng.random() * rng.random(),  # medium to large
            0.5 + rng.random() * 0.3, 0.7,  # moderately regular
            0.15)

    @staticmethod
    def rate_location(model, patch):
        # As close to the centre as possible.
        return patch.shape.distance(_plaza_or_center(model))


class AdministrationWard(CommonWard):
    label = "Administration"

    def __init__(self, model, patch):
        super().__init__(
            model, patch,
            80 + 30 * rng.random() * rng.random(),  # large
            0.1 + rng.random() * 0.3, 0.3)  # regular

    @staticmethod
    def rate_location(model, patch):
        # Ideally overlooking the plaza, otherwise as close as possible.
        if model.plaza is None:
            return patch.shape.distance(model.center)
        if patch.shape.borders(model.plaza.shape):
            return 0
        return patch.shape.distance(model.plaza.shape.center)


class PatriciateWard(CommonWard):
    label = "Patriciate"

    def __init__(self, model, patch):
        super().__init__(
            model, patch,
            80 + 30 * rng.random() * rng.random(),  # large
            0.5 + rng.random() * 0.3, 0.8,  # moderately regular
            0.2)

    @staticmethod
    def rate_location(model, patch):
        # Prefers to border a park and not to border slums.
        rate = 0
        for p in model.patches:
            if p.ward is not None and p.shape.borders(patch.shape):
                if isinstance(p.ward, Park):
                    rate -= 1
                elif isinstance(p.ward, Slum):
                    rate += 1
        return rate


class Slum(CommonWard):
    label = "Slum"

    def __init__(self, model, patch):
        super().__init__(
            model, patch,
            10 + 30 * rng.random() * rng.random(),  # small to medium
            0.6 + rng.random() * 0.4, 0.8,  # chaotic
            0.03)

    @staticmethod
    def rate_location(model, patch):
        # As far from the centre as possible.
        return -patch.shape.distance(_plaza_or_center(model))


class MilitaryWard(Ward):
    label = "Military"

    def create_geometry(self):
        block = self.get_city_block()
        self.geometry = create_alleys(
            block,
            math.sqrt(block.square) * (1 + rng.random()),
            0.1 + rng.random() * 0.3, 0.3,  # regular
            0.25)  # squares

    @staticmethod
    def rate_location(model, patch):
        # Should border the citadel or the city walls.
        if model.citadel is not None and model.citadel.shape.borders(
                patch.shape):
            return 0
        if model.wall is not None and model.wall.borders(patch):
            return 1
        if model.citadel is None and model.wall is None:
            return 0
        return math.inf


class Cathedral(Ward):
    label = "Temple"

    def create_geometry(self):
        if rng.chance(0.4):
            self.geometry = cutter.ring(
                self.get_city_block(), 2 + rng.random() * 4)
        else:
            self.geometry = create_ortho_building(
                self.get_city_block(), 50, 0.8)

    @staticmethod
    def rate_location(model, patch):
        # Ideally overlooking the plaza, otherwise as close as possible.
        if model.plaza is not None and patch.shape.borders(model.plaza.shape):
            return -1 / patch.shape.square
        return patch.shape.distance(_plaza_or_center(model)) * patch.shape.square


class Castle(Ward):
    label = "Castle"

    def __init__(self, model, patch):
        super().__init__(model, patch)
        reserved = [
            v for v in patch.shape
            if any(not p.within_city for p in model.patch_by_vertex(v))
        ]
        self.wall = CurtainWall(True, model, [patch], reserved)

    def create_geometry(self):
        block = self.patch.shape.shrink_eq(MAIN_STREET * 2)
        self.geometry = create_ortho_building(
            block, math.sqrt(block.square) * 4, 0.6)


class Market(Ward):
    label = "Market"

    def create_geometry(self):
        shape = self.patch.shape

        # A statue or a fountain.
        statue = rng.chance(0.6)
        # A statue always sits off centre, and a fountain sometimes does.
        offset = statue or rng.chance(0.3)

        v0 = v1 = None
        if statue or offset:
            # An edge to turn a statue by and to offset towards.
            length = -1.0
            for p0, p1 in shape.edges():
                edge_length = distance(p0, p1)
                if edge_length > length:
                    length = edge_length
                    v0 = p0
                    v1 = p1

        if statue:
            feature = Polygon.rect(1 + rng.random(), 1 + rng.random())
            feature.rotate(math.atan2(v1.y - v0.y, v1.x - v0.x))
        else:
            feature = Polygon.circle(1 + rng.random())

        if offset:
            gravity = interpolate(v0, v1)
            feature.offset(interpolate(
                shape.centroid, gravity, 0.2 + rng.random() * 0.4))
        else:
            feature.offset(shape.centroid)

        self.geometry = [feature]

    @staticmethod
    def rate_location(model, patch):
        # One market shouldn't touch another.
        for p in model.inner:
            if isinstance(p.ward, Market) and p.shape.borders(patch.shape):
                return math.inf

        # A market shouldn't be much larger than the plaza.
        if model.plaza is not None:
            return patch.shape.square / model.plaza.shape.square
        return patch.shape.distance(model.center)


class Park(Ward):
    label = "Park"

    def create_geometry(self):
        block = self.get_city_block()
        if block.compactness >= 0.7:
            self.geometry = cutter.radial(block, None, ALLEY)
        else:
            self.geometry = cutter.semi_radial(block, None, ALLEY)


class Farm(Ward):
    label = "Farm"

    def create_geometry(self):
        shape = self.patch.shape
        housing = Polygon.rect(4, 4)
        pos = interpolate(rng.choice(shape), shape.centroid,
                          0.3 + rng.random() * 0.4)
        housing.rotate(rng.random() * math.pi)
        housing.offset(pos)
        self.geometry = create_ortho_building(housing, 8, 0.5)
