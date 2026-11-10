import math

import pytest

from citygen import streets
from citygen.editing import CityEditor
from citygen.geometry import Point, convex_hull
from citygen.layers import PALETTES, build_layers
from citygen.model import Model
from citygen.wards import Market, Ward

OPTIONS = [dict(size=9, seed=3, walls=True),
           dict(size=15, seed=7, walls=True, home_style="classic"),
           dict(size=24, seed=5, walls=True, home_style="gnome", river=True),
           dict(size=15, seed=2, walls=False, coast=True)]


def length(line):
    return sum(math.dist(a, b) for a, b in zip(line, line[1:]))


@pytest.mark.parametrize("options", OPTIONS)
def test_nothing_bends_on_a_map_nobody_has_edited(options):
    """Every drawn point lies on a way as the city laid it out."""
    model = Model(**options)
    roads, side, _ = streets.ways(model)
    ends = streets._bridge_ends(model)
    main = [streets.onto_bridges(line, ends)
            for line in streets._main_ways(model)]
    plain = [streets.onto_bridges(line, ends)
             for line in streets._side_streets(model)]
    plain += streets._bridge_links(model, ends, main + plain)
    for drawn, laid_out in ((roads, main), (side, plain)):
        for line in drawn:
            for point in line:
                assert streets._nearest_on(laid_out, point)[1] < 1e-6


@pytest.mark.parametrize("options", OPTIONS)
def test_roads_carry_on_through_town_to_the_centre(options):
    model = Model(**options)
    roads, _, _ = streets.ways(model)
    drawn = {point for road in roads for point in road}
    for line in list(model.streets) + list(model.roads):
        assert all((v.x, v.y) in drawn for v in line
                   if v not in model.bridge_points)


@pytest.mark.parametrize("options", OPTIONS)
def test_side_streets_run_between_wards_in_town(options):
    model = Model(**options)
    assert streets.ways(model)[1]
    for (ax, ay), (bx, by) in streets._side_streets(model):
        middle = Point((ax + bx) / 2, (ay + by) / 2)
        owners = [p for p in model.patches
                  if any(math.dist((ax, ay), (v.x, v.y)) < 1e-9
                         for v in p.shape)
                  and any(math.dist((bx, by), (v.x, v.y)) < 1e-9
                          for v in p.shape)]
        assert len(owners) == 2
        for patch in owners:
            assert patch.within_city
            assert patch is not model.plaza and patch is not model.citadel
            assert not isinstance(patch.ward, Market)
            assert type(patch.ward) is not Ward
        if model.wall is not None:
            assert model.wall.shape.contains_point(middle) or not all(
                p.within_walls for p in owners)


def a_building_by_a_road(model, editor):
    street = max(model.streets, key=len)
    middle = street[len(street) // 2]
    after = street[len(street) // 2 + 1]
    building = min(editor.buildings, key=lambda b: math.hypot(
        b.cx - middle.x, b.cy - middle.y))
    along = after.subtract(middle).norm(1)
    across = Point(-along.y, along.x)
    side = (building.cx - middle.x) * across.x + (
        building.cy - middle.y) * across.y
    way = across.scale(-math.copysign(1, side))
    return building, way


def drag(editor, building, dx, dy, steps=8):
    assert editor.begin_move(building)
    for i in range(1, steps + 1):
        editor.drag_to(building, dx * i / steps, dy * i / steps)
    editor.end_move()


def test_a_road_bends_round_a_building_moved_onto_it_and_back_on_undo():
    model = Model(15, 7, walls=True)
    editor = CityEditor(model)
    before, _, _ = streets.ways(model)
    building, way = a_building_by_a_road(model, editor)
    drag(editor, building, way.x * 4, way.y * 4)

    roads, _, _ = streets.ways(model)
    assert roads != before
    footprint = getattr(building.polygon, "house", building.polygon)
    hull = convex_hull([(v.x, v.y) for v in footprint])
    plain = streets._main_ways(model)
    for road, straight in zip(roads, plain):
        unmoved = set(straight)
        # Bent points clear the house. A stretch with no room either side
        # keeps to its line.
        for x, y in road:
            if (x, y) not in unmoved:
                assert streets._to_hull(hull, x, y) >= (
                    streets.ROAD_HALF - streets.TOLERANCE)

    assert editor.undo()
    assert streets.ways(model)[0] == before


class Houses:
    """Stand-in buildings for bending a way, as streets._Obstacles has them."""

    def __init__(self, *boxes):
        self.entries = []
        for left, top, right, bottom in boxes:
            hull = [(left, top), (right, top), (right, bottom), (left, bottom)]
            self.entries.append((hull, (left + right) / 2, (top + bottom) / 2,
                                 left, top, right, bottom))

    def near(self, x, y, reach):
        return [e for e in self.entries
                if e[3] - reach <= x <= e[5] + reach
                and e[4] - reach <= y <= e[6] + reach]


def test_a_way_goes_round_a_house_on_the_side_with_room():
    line = [(0, 0), (40, 0)]
    house = Houses((18, -0.5, 22, 3))  # Sits on the way, mostly above it.
    bent = streets.bend_around(line, house, 1.0)
    assert bent[0] == (0, 0) and bent[-1] == (40, 0)
    lowest = min(y for x, y in bent if 18 <= x <= 22)
    assert lowest <= -0.5 - 1.0
    for x, y in bent:
        assert streets._to_hull(house.entries[0][0], x, y) >= 1.0 - 0.35


def test_a_way_with_no_room_either_side_keeps_to_its_line():
    line = [(0, 0), (40, 0)]
    moved = Houses((18, -0.5, 22, 3))
    everything = Houses((18, -0.5, 22, 3), (10, -12, 30, -1.2),
                        (10, 3.2, 30, 14))
    assert streets.bend_around(line, moved, 1.0, everything) == line


def test_a_house_beside_a_way_leaves_it_alone():
    line = [(0, 0), (40, 0)]
    assert streets.bend_around(line, Houses((18, 1.0, 22, 4)), 1.0) == line


def test_bends_ease_in_and_out_smoothly():
    model = Model(15, 7, walls=True)
    editor = CityEditor(model)
    building, way = a_building_by_a_road(model, editor)
    drag(editor, building, way.x * 4, way.y * 4)
    roads, _, _ = streets.ways(model)
    plain = streets._main_ways(model)
    for bent, straight in zip(roads, plain):
        if bent == straight:
            continue
        turns = []
        for a, b, c in zip(bent, bent[1:], bent[2:]):
            if math.dist(a, b) < 0.2 or math.dist(b, c) < 0.2:
                continue
            first = math.atan2(b[1] - a[1], b[0] - a[0])
            second = math.atan2(c[1] - b[1], c[0] - b[0])
            turns.append(abs((second - first + math.pi) % (2 * math.pi)
                             - math.pi))
        assert max(turns) < math.radians(75)


def test_ways_keep_their_ends_where_they_were():
    model = Model(15, 7, walls=True)
    editor = CityEditor(model)
    building, way = a_building_by_a_road(model, editor)
    drag(editor, building, way.x * 4, way.y * 4)
    for bent, straight in zip(streets.ways(model)[0],
                              streets._main_ways(model)):
        assert bent[0] == pytest.approx(straight[0])
        assert bent[-1] == pytest.approx(straight[-1])


def test_ease_never_falls_short_of_a_push():
    shifts = [0] * 8 + [1.5, 1.6, 1.4] + [0] * 8 + [-0.8] + [0] * 8
    eased = streets._ease(shifts, 2)
    for shift, value in zip(shifts, eased):
        if shift > 0:
            assert value >= shift - 1e-9
        if shift < 0:
            assert value <= shift + 1e-9
    assert eased[0] == 0 and eased[-1] == 0


def test_a_wall_street_appears_where_a_wall_is_pushed_out():
    model = Model(15, 7, walls=True)
    editor = CityEditor(model)
    _, _, before = streets.ways(model)
    north = max((b for b in editor.buildings
                 if b.ward.patch.within_walls), key=lambda b: -b.cy)
    drag(editor, north, 0, -24, steps=20)
    _, _, after = streets.ways(model)
    assert sum(map(length, after)) > sum(map(length, before)) + 20


@pytest.mark.parametrize("options", OPTIONS)
def test_wall_streets_keep_clear_of_buildings_and_water(options):
    model = Model(**options)
    editor = CityEditor(model)
    if model.wall is not None:
        north = max((b for b in editor.buildings
                     if b.ward.patch.within_walls), key=lambda b: -b.cy)
        drag(editor, north, 0, -20, steps=16)
    everything = streets._Obstacles([e for e, _ in streets._outlines(model)])
    _, _, wall_streets = streets.ways(model)
    for line in wall_streets:
        assert length(line) >= streets.MIN_WALL_STREET
        for x, y in line:
            assert model.wall.shape.contains_point(Point(x, y))
            assert everything.distance(x, y, 1.0) >= (
                streets.WALL_STREET_ROOM - 1e-6)
            assert not streets._on_water(model, x, y)


def test_ways_are_drawn():
    model = Model(15, 7, walls=True)
    layers = {layer.name: layer for layer in build_layers(
        model, PALETTES["Default"])}
    roads, side, _ = streets.ways(model)
    assert len(layers["Roads"].polylines) == len(roads)
    assert len(layers["Streets"].polylines) >= len(side)


def test_working_out_the_ways_is_quick():
    import time
    model = Model(40, 5, walls=True, river=True, coast=True,
                  home_style="gnome")
    streets.ways(model)
    start = time.perf_counter()
    streets.ways(model)
    assert time.perf_counter() - start < 0.25


def test_the_json_has_the_ways_as_drawn():
    from citygen.export import city_to_dict

    model = Model(15, 7, walls=True)
    data = city_to_dict(model)
    roads, side, wall = streets.ways(model)
    assert len(data["drawn_roads"]) == len(roads)
    assert len(data["drawn_streets"]) == len(side)
    assert len(data["wall_streets"]) == len(wall)


def distance_to_roads(roads, x, y):
    from citygen.geometry import chaikin
    best = math.inf
    for road in roads:
        line = chaikin(road, streets.ROAD_ROUNDING)
        for (ax, ay), (bx, by) in zip(line, line[1:]):
            dx, dy = bx - ax, by - ay
            size = dx * dx + dy * dy
            t = max(0, min(1, ((x - ax) * dx + (y - ay) * dy) / size)) if size else 0
            best = min(best, math.hypot(x - ax - t * dx, y - ay - t * dy))
    return best


@pytest.mark.parametrize("options", OPTIONS)
def test_street_lines_stop_at_the_edge_of_roads(options):
    model = Model(**options)
    editor = CityEditor(model)
    if model.wall is not None:
        north = max((b for b in editor.buildings
                     if b.ward.patch.within_walls), key=lambda b: -b.cy)
        drag(editor, north, 0, -20, steps=16)
    roads, side, wall = streets.ways(model)
    for line in side + wall:
        for sample in streets._samples(line):
            assert distance_to_roads(roads, sample[0], sample[1]) >= (
                streets.ROAD_EDGE - 0.01)


def test_trimming_cuts_a_street_where_it_crosses_a_road():
    road = [(0, -20), (0, 20)]
    street = [(-10, 0), (10, 0)]
    pieces = streets.trim(street, streets._Roads([road]))
    assert len(pieces) == 2
    left, right = sorted(pieces, key=lambda piece: piece[0][0])
    assert left[0] == (-10, 0) and right[-1] == (10, 0)
    assert max(x for x, _ in left) == pytest.approx(-streets.ROAD_EDGE, abs=0.01)
    assert min(x for x, _ in right) == pytest.approx(streets.ROAD_EDGE, abs=0.01)


RIVER_TOWNS = [dict(size=20, seed=seed, river=True, walls=True)
               for seed in (7, 3, 11, 5, 9)]


def to_line(lines, point):
    return streets._nearest_on(lines, point)[1]


@pytest.mark.parametrize("options", RIVER_TOWNS)
def test_every_bridge_end_meets_a_road_or_street(options):
    model = Model(**options)
    roads, side, _ = streets.ways(model)
    ways = roads + side
    for a, b in model.bridges:
        for end in ((a.x, a.y), (b.x, b.y)):
            if to_line(ways, end) > 1e-6:
                # Only where nothing on that bank is near enough to join.
                assert not any(
                    math.dist(p, end) < streets.BRIDGE_LINK
                    and not streets._crosses_river(model, end, p)
                    for line in ways for p in line)


@pytest.mark.parametrize("options", RIVER_TOWNS)
def test_ways_cross_the_river_only_on_bridges(options):
    model = Model(**options)
    roads, side, wall = streets.ways(model)
    bridges = [[(a.x, a.y), (b.x, b.y)] for a, b in model.bridges]
    river = [(v.x, v.y) for v in model.river]
    for line in roads + side + wall:
        for sample in streets._samples(line):
            point = sample[:2]
            if to_line([river], point) < 2.0:
                assert to_line(bridges, point) < 0.5


def test_a_road_over_a_bridge_runs_straight_across_it():
    model = Model(size=20, seed=11, river=True, walls=True)
    roads, _, _ = streets.ways(model)
    crossed = 0
    for a, b in model.bridges:
        ends = {(a.x, a.y), (b.x, b.y)}
        for road in roads:
            for p, q in zip(road, road[1:]):
                if {p, q} == ends:
                    crossed += 1
    assert crossed >= 1


def test_onto_bridges_swaps_a_middle_for_the_ends():
    ends = {(0.0, 0.0): ((0.0, -4.0), (0.0, 4.0))}
    assert streets.onto_bridges([(1, -10), (0.0, 0.0), (-1, 10)], ends) == [
        (1, -10), (0.0, -4.0), (0.0, 4.0), (-1, 10)]
    assert streets.onto_bridges([(0.0, 0.0), (2, 9)], ends) == [
        (0.0, 4.0), (2, 9)]
