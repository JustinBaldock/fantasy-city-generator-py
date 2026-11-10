"""The whole city, ported from building/Model.hx.

A city is built in stages: patches of land from a Voronoi spiral, the walls
and gates, the streets, then a ward for each patch and its buildings. Some
seeds lead to a shape that can't be used. As in the original, the model then
carries on from the same random sequence and tries again, so a seed always
gives the same city.
"""

import math
import random

from . import countryside, gnomes, plots, rng, water
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
HOME_STYLES = ("burgage", "gnome", "classic")
# Parts of wheat field to each part of orchard, where there are both.
ORCHARD_RATIOS = (10, 8, 4)
DEFAULT_ORCHARD_RATIO = 8
MAX_TEMPLES = 10
# Wheat fields for each ward of the town, from a farming town to very few.
FIELD_RATIOS = (4, 3, 2, 1, 1 / 3, 1 / 4)
DEFAULT_FIELD_RATIO = 1

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

COAST_CHANCE = 0.4
RIVER_CHANCE = 0.3
FIELDS_CHANCE = 0.75
FORESTS_CHANCE = 0.4
ORCHARDS_CHANCE = 0.5

# A failed attempt shows up as one of these. Anything else is a bug.
_ATTEMPT_FAILED = (
    GenerationError, ArithmeticError, IndexError, KeyError, ValueError,
    RecursionError,
)


def spot_of(polygon):
    return tuple((v.x, v.y) for v in polygon)


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

    walls, citadel, plaza, temple, greens, coast, river, fields and forests
    can each be True or False to force that feature. None leaves it to the
    seed. temples is how many temples there are, when there are any.

    hub False keeps only two roads out of town. sea is the compass bearing of
    the coast in degrees, or None to leave it to the seed.

    home_style is one of HOME_STYLES. "burgage" puts each house at the street
    front of its plot with a garden behind, "gnome" builds gnome homes, and
    "classic" fills each plot with its house, as the original does. It is
    never left to the seed.

    coast, river, hub and the water's shape use their own random numbers, so
    a city with no water is built exactly as the original would build it.
    """

    def __init__(self, size=DEFAULT_SIZE, seed=-1, walls=None, citadel=None,
                 plaza=None, temple=None, greens=None, coast=None, river=None,
                 hub=True, sea=None, fields=None, forests=None,
                 home_style="burgage", orchards=None,
                 orchard_ratio=DEFAULT_ORCHARD_RATIO, temples=1,
                 field_ratio=DEFAULT_FIELD_RATIO):
        if home_style not in HOME_STYLES:
            raise ValueError(f"Unknown home style {home_style!r}")
        if seed > 0:
            rng.reset(seed)
        else:
            rng.reset()
            seed = rng.get_seed()

        self.seed = seed
        self.size = size
        # Everything the city was made with, so it can be made again.
        self.settings = dict(
            size=size, seed=seed, walls=walls, citadel=citadel, plaza=plaza,
            temple=temple, greens=greens, coast=coast, river=river, hub=hub,
            sea=sea, fields=fields, forests=forests, home_style=home_style,
            orchards=orchards, orchard_ratio=orchard_ratio, temples=temples,
            field_ratio=field_ratio)
        self.temple_option = temple
        self.greens_option = greens
        self.hub = hub
        self.home_style = home_style

        self.features = random.Random(seed)
        coast_roll = self.features.random() < COAST_CHANCE
        river_roll = self.features.random() < RIVER_CHANCE
        bearing_roll = self.features.uniform(0, 360)
        fields_roll = self.features.random() < FIELDS_CHANCE
        forests_roll = self.features.random() < FORESTS_CHANCE
        self.coast_needed = coast_roll if coast is None else coast
        self.river_needed = river_roll if river is None else river
        self.sea_bearing = bearing_roll if sea is None else sea
        self.fields_needed = fields_roll if fields is None else fields
        self.forests_needed = forests_roll if forests is None else forests
        # Its own random numbers, so the rest of the countryside is the same
        # whether or not there are orchards.
        orchards_roll = (random.Random(f"{seed} orchards option").random()
                         < ORCHARDS_CHANCE)
        self.orchards_needed = orchards_roll if orchards is None else orchards
        if orchard_ratio <= 0:
            raise ValueError(f"Orchard ratio must be positive, not {orchard_ratio}")
        self.orchard_ratio = orchard_ratio
        if not 1 <= temples <= MAX_TEMPLES:
            raise ValueError(f"A town has 1 to {MAX_TEMPLES} temples, "
                             f"not {temples}")
        self.temple_count = temples
        if field_ratio <= 0:
            raise ValueError(f"Field ratio must be positive, not {field_ratio}")
        self.field_ratio = field_ratio
        self.sea_direction = water.direction_from_bearing(self.sea_bearing)

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
        self.seaward = None
        self.shore = []
        self.sea = None
        self.shore_edges = set()
        self.shore_points = set()
        self.river = []
        self.river_edges = set()
        self.river_points = set()
        self.bridge_points = set()
        self.bridges = []
        self.piers = []
        self.fields = []
        self.furrows = []
        self.orchards = []
        self.orchard_trees = []
        self.trees = []

        self._build_patches()
        self._optimize_junctions()
        self._build_water()
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
        self.patches = [Patch.from_region(r) for r in voronoi.partitioning()]
        self.inner = []

        if self.coast_needed:
            water.plan_coast(self, self.patches)

        land = [patch for patch in self.patches if not patch.water]
        for count, patch in enumerate(land):
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

    def _build_water(self):
        if self.coast_needed:
            water.finish_coast(self)
        self.patches = [patch for patch in self.patches if not patch.water]
        if self.river_needed:
            water.build_river(self)

    @property
    def water_points(self):
        return self.shore_points | self.river_points

    def _build_walls(self):
        reserved = list(self.citadel.shape) if self.citadel is not None else []
        reserved += self.water_points

        self.border = CurtainWall(self.walls_needed, self, self.inner, reserved)
        self.border.mask_water(self)
        if self.walls_needed:
            self.wall = self.border
            self.wall.build_towers(self)

        radius = self.border.get_radius()
        self.patches = [
            p for p in self.patches
            if p.shape.distance(self.center) < radius * 3
        ]

        # If the outline found a small loop inside the city instead of its
        # outer edge, the radius is far too small and real wards are lost.
        # The original would carry on and fail later.
        kept = set(self.patches)
        if any(p not in kept for p in self.inner) or (
                self.citadel is not None and self.citadel not in kept):
            raise GenerationError("Lost part of the city")

        self.gates = self.border.gates

        if self.citadel is not None:
            castle = Castle(self, self.citadel)
            castle.wall.build_towers(self)
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

        if not self.hub:
            self._keep_two_roads()

        self._tidy_up_roads()

        fixed = self.water_points
        for artery in self.arteries:
            smoothed = artery.smooth_vertex_eq(3)
            for i in range(1, len(artery) - 1):
                if artery[i] not in fixed:
                    artery[i].set(smoothed[i])

    def _keep_two_roads(self):
        """Keep one road at random and the one leaving most opposite it."""
        if len(self.roads) <= 2:
            return
        first = self.features.choice(self.roads)
        others = [road for road in self.roads if road is not first]
        second = min_by(others, lambda road: first[0].dot(road[0]))
        self.roads = [first, second]

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

        if self.temple_option is not None:
            wards = [w for w in wards if w is not Cathedral]
            if self.temple_option:
                wards[0:0] = [Cathedral] * self.temple_count
        elif self.temple_count > 1:
            # Left to the seed, the temples come all together or not at all.
            index = wards.index(Cathedral)
            wards[index:index + 1] = [Cathedral] * self.temple_count
        if self.greens_option is not None:
            wards = [w for w in wards if w is not Park]
            if self.greens_option:
                wards[1:1] = [Park] * max(1, self.size // 10)

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
        if self.home_style == "gnome":
            gnomes.build_gnome_homes(self)
        elif self.home_style == "burgage":
            plots.build_burgage_plots(self)
        plots.plant_gardens(self)
        plots.plant_greens(self)
        self.built_at = {}
        if self.shore:
            water.build_piers(self)
        # How far the map reaches from its centre. Farmland can widen it.
        self.view_radius = self.city_radius * 1.1
        countryside.build_countryside(self)
        # Where each building stood when the city was built, so the drawing
        # can tell which ones have been moved since.
        self.built_at = {
            id(polygon): spot_of(polygon)
            for patch in self.patches
            for polygon in list(patch.ward.geometry) + list(patch.ward.landmarks)
        }
        # The wall corners the city was built with. Editing can add more.
        self.built_corners = {id(v) for wall in self.walls() for v in wall.shape}

    def walls(self):
        """The city wall and the castle wall, where there are any."""
        found = []
        if self.wall is not None:
            found.append(self.wall)
        if self.citadel is not None:
            found.append(self.citadel.ward.wall)
        return found

    def has_moved(self, polygon):
        """Whether a building has moved since the city was built."""
        return self.built_at.get(id(polygon)) != spot_of(polygon)

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
