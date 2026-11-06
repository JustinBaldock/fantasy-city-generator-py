"""The whole city, ported from building/Model.hx.

A city is built in stages: patches of land from a Voronoi spiral, the walls
and gates, the streets, then a ward for each patch and its buildings. Some
seeds lead to a shape that can't be used. As in the original, the model then
carries on from the same random sequence and tries again, so a seed always
gives the same city.
"""

import math

from . import rng
from .geometry import (
    GenerationError,
    Point,
    Polygon,
    distance,
    index_of,
    min_by,
)
from .patch import Patch
from .topology import Topology
from .voronoi import Voronoi
from .walls import CurtainWall
from .wards import (
    AdministrationWard,
    Castle,
    Cathedral,
    CraftsmenWard,
    Farm,
    GateWard,
    Market,
    MerchantWard,
    MilitaryWard,
    Park,
    PatriciateWard,
    Slum,
    Ward,
)

MIN_SIZE = 6
MAX_SIZE = 40
DEFAULT_SIZE = 15
MAX_SEED = 2147483646
MAX_ATTEMPTS = 500

# The order wards are handed out in, lightly shuffled for each city.
WARDS = [
    CraftsmenWard, CraftsmenWard, MerchantWard, CraftsmenWard, CraftsmenWard,
    Cathedral, CraftsmenWard, CraftsmenWard, CraftsmenWard, CraftsmenWard,
    CraftsmenWard, CraftsmenWard, CraftsmenWard, CraftsmenWard,
    AdministrationWard, CraftsmenWard, Slum, CraftsmenWard, Slum,
    PatriciateWard, Market, Slum, CraftsmenWard, CraftsmenWard, CraftsmenWard,
    Slum, CraftsmenWard, CraftsmenWard, CraftsmenWard, MilitaryWard, Slum,
    CraftsmenWard, Park, PatriciateWard, Market, MerchantWard,
]

# A failed attempt shows up as one of these. Anything else is a bug.
_ATTEMPT_FAILED = (
    GenerationError, ArithmeticError, IndexError, KeyError, ValueError,
    RecursionError,
)


def size_name(size):
    if size < 10:
        return "Small Town"
    if size < 15:
        return "Large Town"
    if size < 24:
        return "Small City"
    if size < 40:
        return "Large City"
    return "Metropolis"


class Model:
    """A generated city.

    walls, citadel and plaza can each be True or False to force that feature.
    None leaves it to the seed.
    """

    def __init__(self, size=DEFAULT_SIZE, seed=-1, walls=None, citadel=None,
                 plaza=None):
        if seed > 0:
            rng.reset(seed)
        else:
            rng.reset()
            seed = rng.get_seed()

        self.seed = seed
        self.size = size

        # Drawn even when forced, so that forcing one leaves the rest alike.
        plaza_roll = rng.chance()
        citadel_roll = rng.chance()
        walls_roll = rng.chance()
        self.plaza_needed = plaza_roll if plaza is None else plaza
        self.citadel_needed = citadel_roll if citadel is None else citadel
        self.walls_needed = walls_roll if walls is None else walls

        self.failures = []
        for _ in range(MAX_ATTEMPTS):
            try:
                self._build()
                return
            except _ATTEMPT_FAILED as error:
                self.failures.append(f"{type(error).__name__}: {error}")
        raise GenerationError(
            f"No usable city after {MAX_ATTEMPTS} attempts "
            f"(seed {seed}, size {size})")

    def _build(self):
        self.streets = []
        self.roads = []
        self.plaza = None
        self.citadel = None
        self.wall = None

        self._build_patches()
        self._optimize_junctions()
        self._build_walls()
        self._build_streets()
        self._create_wards()
        self._build_geometry()

    def _build_patches(self):
        start_angle = rng.random() * 2 * math.pi
        points = []
        for i in range(self.size * 8):
            a = start_angle + math.sqrt(i) * 5
            r = 0 if i == 0 else 10 + i * (2 + rng.random())
            points.append(Point(math.cos(a) * r, math.sin(a) * r))
        voronoi = Voronoi.build(points)

        # Relax the central wards.
        for _ in range(3):
            to_relax = voronoi.points[:3] + [voronoi.points[self.size]]
            voronoi = Voronoi.relax(voronoi, to_relax)

        voronoi.points.sort(key=lambda p: p.length)
        regions = voronoi.partitioning()

        self.patches = []
        self.inner = []

        for count, region in enumerate(regions):
            patch = Patch.from_region(region)
            self.patches.append(patch)

            if count == 0:
                self.center = min_by(patch.shape, lambda p: p.length)
                if self.plaza_needed:
                    self.plaza = patch
            elif count == self.size and self.citadel_needed:
                self.citadel = patch
                self.citadel.within_city = True

            if count < self.size:
                patch.within_city = True
                patch.within_walls = self.walls_needed
                self.inner.append(patch)

    def _optimize_junctions(self):
        """Merge vertices that sit very close together."""
        to_optimize = list(self.inner)
        if self.citadel is not None:
            to_optimize.append(self.citadel)

        to_clean = []
        for w in to_optimize:
            index = 0
            while index < len(w.shape):
                v0 = w.shape[index]
                v1 = w.shape[(index + 1) % len(w.shape)]

                if v0 is not v1 and distance(v0, v1) < 8:
                    for w1 in self.patch_by_vertex(v1):
                        if w1 is not w:
                            w1.shape[index_of(w1.shape, v1)] = v0
                            to_clean.append(w1)

                    v0.add_eq(v1)
                    v0.scale_eq(0.5)
                    w.shape.remove(v1)
                index += 1

        # A merge can leave a patch with the same vertex twice.
        for w in to_clean:
            i = 0
            while i < len(w.shape):
                v = w.shape[i]
                duplicate = index_of(w.shape, v, i + 1)
                while duplicate != -1:
                    del w.shape[duplicate]
                    duplicate = index_of(w.shape, v, i + 1)
                i += 1

    def _build_walls(self):
        reserved = list(self.citadel.shape) if self.citadel is not None else []

        self.border = CurtainWall(self.walls_needed, self, self.inner, reserved)
        if self.walls_needed:
            self.wall = self.border
            self.wall.build_towers()

        radius = self.border.get_radius()
        self.patches = [
            p for p in self.patches
            if p.shape.distance(self.center) < radius * 3
        ]

        self.gates = self.border.gates

        if self.citadel is not None:
            castle = Castle(self, self.citadel)
            castle.wall.build_towers()
            self.citadel.ward = castle

            if self.citadel.shape.compactness < 0.75:
                raise GenerationError("Bad citadel shape")

            self.gates = self.gates + castle.wall.gates

    def patch_by_vertex(self, v):
        return [patch for patch in self.patches if v in patch.shape]

    def _build_streets(self):
        self.topology = Topology(self)

        for gate in self.gates:
            # Each gate leads to the nearest corner of the plaza, or to the
            # central junction.
            if self.plaza is not None:
                end = min_by(self.plaza.shape, lambda v: distance(v, gate))
            else:
                end = self.center

            street = self.topology.build_path(gate, end, self.topology.outer)
            if street is None:
                raise GenerationError("Unable to build a street")
            self.streets.append(Polygon(street))

            if gate in self.border.gates:
                aim = gate.norm(1000)
                start = None
                nearest = math.inf
                for p in self.topology.node2pt.values():
                    d = distance(p, aim)
                    if d < nearest:
                        nearest = d
                        start = p

                road = self.topology.build_path(
                    start, gate, self.topology.inner)
                if road is not None:
                    self.roads.append(Polygon(road))

        self._tidy_up_roads()

        for artery in self.arteries:
            smoothed = artery.smooth_vertex_eq(3)
            for i in range(1, len(artery) - 1):
                artery[i].set(smoothed[i])

    def _tidy_up_roads(self):
        """Join streets and roads into arteries with no repeated segments."""
        segments = []
        seen = set()

        def add_segments(street):
            for v0, v1 in zip(street, street[1:]):
                # Leave out segments running along the plaza.
                if (self.plaza is not None and v0 in self.plaza.shape
                        and v1 in self.plaza.shape):
                    continue
                if (v0, v1) not in seen:
                    seen.add((v0, v1))
                    segments.append((v0, v1))

        for street in self.streets:
            add_segments(street)
        for road in self.roads:
            add_segments(road)

        self.arteries = []
        while segments:
            start, end = segments.pop()

            for artery in self.arteries:
                if artery[0] is end:
                    artery.insert(0, start)
                    break
                if artery[-1] is start:
                    artery.append(end)
                    break
            else:
                self.arteries.append(Polygon([start, end]))

    def _create_wards(self):
        unassigned = list(self.inner)
        if self.plaza is not None:
            self.plaza.ward = Market(self, self.plaza)
            unassigned.remove(self.plaza)

        # Inner city gate wards.
        for gate in self.border.gates:
            for patch in self.patch_by_vertex(gate):
                if (patch.within_city and patch.ward is None
                        and rng.chance(0.2 if self.wall is None else 0.5)):
                    patch.ward = GateWard(self, patch)
                    unassigned.remove(patch)

        wards = list(WARDS)
        # Some shuffling.
        for _ in range(len(wards) // 10):
            index = rng.randint(0, len(wards) - 1)
            wards[index], wards[index + 1] = wards[index + 1], wards[index]

        # The rest of the inner city.
        while unassigned:
            ward_class = wards.pop(0) if wards else Slum
            rate = ward_class.rate_location

            if rate is None:
                best = rng.choice(unassigned)
            else:
                best = min_by(unassigned, lambda patch: rate(self, patch))

            best.ward = ward_class(self, best)
            unassigned.remove(best)

        # Outskirts.
        if self.wall is not None:
            for gate in self.wall.gates:
                if not rng.chance(1 / max(1, self.size - 5)):
                    for patch in self.patch_by_vertex(gate):
                        if patch.ward is None:
                            patch.within_city = True
                            patch.ward = GateWard(self, patch)

        # The city's radius, and the countryside.
        self.city_radius = 0.0
        for patch in self.patches:
            if patch.within_city:
                for v in patch.shape:
                    self.city_radius = max(self.city_radius, v.length)
            elif patch.ward is None:
                if rng.chance(0.2) and patch.shape.compactness >= 0.7:
                    patch.ward = Farm(self, patch)
                else:
                    patch.ward = Ward(self, patch)

    def _build_geometry(self):
        for patch in self.patches:
            patch.ward.create_geometry()

    def get_neighbour(self, patch, v):
        following = patch.shape.next(v)
        for p in self.patches:
            if p.shape.find_edge(following, v) != -1:
                return p
        return None

    def get_neighbours(self, patch):
        return [
            p for p in self.patches
            if p is not patch and p.shape.borders(patch.shape)
        ]

    def is_enclosed(self, patch):
        """Whether a ward is in the city and surrounded by city wards."""
        return patch.within_city and (
            patch.within_walls
            or all(p.within_city for p in self.get_neighbours(patch)))

    def patch_at(self, point):
        """The patch under a point on the map, if there is one."""
        for patch in self.patches:
            if patch.shape.contains_point(point):
                return patch
        return None
