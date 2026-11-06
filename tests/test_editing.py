import math

import pytest

from citygen import editing, export
from citygen.editing import CityEditor, convex_hull, overlap
from citygen.geometry import Point, distance
from citygen.layers import PALETTES
from citygen.model import Model


def city(**options):
    options = {"walls": False, "coast": False, "river": False, **options}
    return Model(15, 7, **options)


def positions(editor):
    return {b: b.corners() for b in editor.buildings}


def moved(editor, before):
    return [b for b in editor.buildings if b.corners() != before[b]]


def drag(editor, building, dx, dy):
    assert editor.begin_move(building)
    result = editor.drag_to(building, dx, dy)
    editor.end_move()
    return result


def crowded_building(editor):
    """A building in the thick of the city, near the middle of the list."""
    inner = [b for b in editor.buildings if b.ward.patch.within_city]
    return max(inner, key=lambda b: len(editor._nearby(b)))


def nearest_to(editor, building):
    return min(editor._nearby(building),
               key=lambda other: math.dist(other.center(), building.center()))


def square_hull(x, y, size=10):
    return convex_hull([(x, y), (x + size, y), (x + size, y + size),
                        (x, y + size)])


def test_convex_hull_drops_inner_points():
    assert len(convex_hull([(0, 0), (4, 0), (4, 4), (0, 4), (2, 2)])) == 4


def test_overlap_pushes_away_along_the_shallowest_side():
    push = overlap(square_hull(0, 0), square_hull(9, 0))
    assert push[0] > 0
    assert push[1] == pytest.approx(0)
    assert push[0] == pytest.approx(1.15)


def test_shapes_apart_or_just_touching_do_not_overlap():
    assert overlap(square_hull(0, 0), square_hull(20, 0)) is None
    assert overlap(square_hull(0, 0), square_hull(10, 0)) is None


def test_every_building_is_found():
    model = city()
    editor = CityEditor(model)
    total = sum(len(p.ward.geometry) + len(p.ward.landmarks)
                for p in model.patches)
    assert len(editor.buildings) == total


def test_clicking_finds_the_building_under_the_pointer():
    editor = CityEditor(city())
    building = crowded_building(editor)
    x, y = building.center()
    assert editor.building_at(Point(x, y)) is building


def test_clicking_open_ground_finds_nothing():
    editor = CityEditor(city())
    assert editor.building_at(Point(10000, 10000)) is None


def test_a_building_moves_to_where_it_is_dragged():
    editor = CityEditor(city())
    building = crowded_building(editor)
    x, y = building.center()
    assert drag(editor, building, 6, -3)
    assert building.center() == pytest.approx((x + 6, y - 3), abs=0.02)


def test_moving_a_building_leaves_shared_corners_alone():
    model = city()
    editor = CityEditor(model)
    # Find two buildings that share a corner point.
    owners = {}
    pair = None
    for b in editor.buildings:
        for v in b.polygon:
            if v in owners and owners[v] is not b:
                pair = (owners[v], b)
            owners[v] = b
    assert pair
    first, second = pair
    before = second.corners()
    first.shift(50, 50)
    assert second.corners() == before


def test_a_moved_building_pushes_its_neighbour_aside():
    editor = CityEditor(city())
    building = crowded_building(editor)
    other = nearest_to(editor, building)
    ox, oy = other.center()
    bx, by = building.center()
    before = positions(editor)

    assert drag(editor, building, (ox - bx) * 1.5, (oy - by) * 1.5)

    assert other in moved(editor, before)
    assert overlap(building.hull, other.hull) is None


def test_nothing_is_left_overlapping_what_moved():
    editor = CityEditor(city())
    building = crowded_building(editor)
    before = positions(editor)
    drag(editor, building, 12, 7)

    for shifted in moved(editor, before):
        for other in editor._nearby(shifted):
            if other.corners() != before[other]:
                continue
            assert overlap(shifted.hull, other.hull) is None


def test_small_moves_in_open_space_push_nothing():
    editor = CityEditor(city())
    farms = [b for b in editor.buildings if not b.ward.patch.within_city]
    building = next(b for b in farms if not editor._nearby(b))
    before = positions(editor)
    assert drag(editor, building, 3, 3)
    assert moved(editor, before) == [building]


def test_a_locked_building_cannot_be_moved():
    editor = CityEditor(city())
    building = crowded_building(editor)
    before = building.corners()
    editor.set_locked(building, True)

    assert not editor.begin_move(building)
    assert not editor.drag_to(building, 10, 10)
    assert building.corners() == before


def test_an_unlocked_building_can_be_moved_again():
    editor = CityEditor(city())
    building = crowded_building(editor)
    editor.toggle_lock(building)
    assert editor.is_locked(building)
    editor.toggle_lock(building)
    assert not editor.is_locked(building)
    assert drag(editor, building, 4, 0)


def test_a_locked_building_is_not_pushed():
    editor = CityEditor(city())
    building = crowded_building(editor)
    other = nearest_to(editor, building)
    editor.set_locked(other, True)
    before = other.corners()

    ox, oy = other.center()
    bx, by = building.center()
    drag(editor, building, (ox - bx) * 1.5, (oy - by) * 1.5)

    assert other.corners() == before
    assert overlap(building.hull, other.hull) is None


def test_a_locked_building_stops_the_drag():
    editor = CityEditor(city())
    building = crowded_building(editor)
    other = nearest_to(editor, building)
    editor.set_locked(other, True)
    ox, oy = other.center()
    bx, by = building.center()

    assert not drag(editor, building, ox - bx, oy - by)


def test_a_dragged_building_catches_up_when_the_way_is_clear():
    editor = CityEditor(city())
    building = crowded_building(editor)
    other = nearest_to(editor, building)
    editor.set_locked(other, True)
    ox, oy = other.center()
    bx, by = building.center()

    editor.begin_move(building)
    assert not editor.drag_to(building, ox - bx, oy - by)
    assert editor.drag_to(building, 0, 0)
    editor.end_move()
    assert building.center() == pytest.approx((bx, by), abs=0.02)


def test_undo_puts_everything_back():
    editor = CityEditor(city())
    building = crowded_building(editor)
    before = positions(editor)
    drag(editor, building, 12, 7)
    assert moved(editor, before)

    assert editor.undo()
    assert not moved(editor, before)
    assert not editor.undo()


def test_undo_works_one_drag_at_a_time():
    editor = CityEditor(city())
    building = crowded_building(editor)
    drag(editor, building, 4, 0)
    after_first = positions(editor)
    drag(editor, building, 4, 0)
    editor.undo()
    assert positions(editor) == after_first


def test_buildings_cannot_be_dragged_into_the_sea():
    for seed in range(1, 10):
        model = Model(15, seed, coast=True, river=False)
        editor = CityEditor(model)
        near = [b for b in editor.buildings
                if b.ward.patch.within_city
                and model.seaward(Point(*b.center())) > -14]
        if not near:
            continue
        building = near[0]
        out = model.sea_direction.scale(60)
        drag(editor, building, out.x, out.y)
        for x, y in building.corners():
            assert not model.sea.contains_point(Point(x, y))
        return
    pytest.fail("no city with buildings near the shore")


def test_buildings_cannot_be_dragged_into_the_river():
    model = Model(15, 3, coast=False, river=True)
    editor = CityEditor(model)
    building = crowded_building(editor)
    middle = model.river[len(model.river) // 2]
    x, y = building.center()
    drag(editor, building, middle.x - x, middle.y - y)
    for bx, by in building.corners():
        assert min(distance(Point(bx, by), p) for p in model.river) > 2


def test_exports_show_the_moved_buildings():
    model = city()
    editor = CityEditor(model)
    building = crowded_building(editor)
    drag(editor, building, 9, 0)
    (x, y) = building.corners()[0]

    rounded = [round(x, 3), round(y, 3)]
    wards = export.city_to_dict(model)["wards"]
    assert any(rounded in shape for ward in wards
               for shape in ward["buildings"] + ward["landmarks"])
    assert f"{x:.3f} {y:.3f}" in export.city_to_svg(
        model, PALETTES["Default"])


def test_an_editor_starts_with_no_changes():
    editor = CityEditor(city())
    assert not editor.has_changes
    editor.set_locked(editor.buildings[0], True)
    assert editor.has_changes
    editor.unlock_all()
    assert not editor.has_changes


def walled_city(**options):
    options = {"walls": True, "coast": False, "river": False, **options}
    return Model(15, 7, **options)


def inside_buildings(model, editor):
    return [b for b in editor.buildings if b.ward.patch.within_walls]


def outer_building(model, editor):
    return max(inside_buildings(model, editor),
               key=lambda b: math.hypot(*b.center()))


def wall_corners(wall):
    return [(v.x, v.y) for v in wall.shape]


def drag_outwards(editor, building, length):
    x, y = building.center()
    size = math.hypot(x, y)
    return drag(editor, building, x / size * length, y / size * length)


def test_a_building_dragged_outwards_moves_the_wall():
    model = walled_city()
    editor = CityEditor(model)
    building = outer_building(model, editor)
    start = wall_corners(model.wall)

    assert drag_outwards(editor, building, 25)
    assert wall_corners(model.wall) != start


def test_a_moved_wall_still_encloses_the_building_that_moved_it():
    model = walled_city()
    editor = CityEditor(model)
    building = outer_building(model, editor)
    drag_outwards(editor, building, 25)
    for x, y in building.corners():
        assert model.wall.shape.contains_point(Point(x, y))


def test_everything_inside_stays_inside_a_moved_wall():
    model = walled_city()
    editor = CityEditor(model)
    inside = inside_buildings(model, editor)
    for building in sorted(inside, key=lambda b: -math.hypot(*b.center()))[:4]:
        drag_outwards(editor, building, 20)
    for building in inside:
        assert model.wall.shape.contains_point(Point(*building.center()))


def test_buildings_beyond_a_moved_wall_are_moved_clear():
    model = walled_city()
    editor = CityEditor(model)
    outside = [b for b in editor.buildings
               if not model.wall.shape.contains_point(Point(*b.center()))]
    for building in sorted(inside_buildings(model, editor),
                           key=lambda b: -math.hypot(*b.center()))[:4]:
        drag_outwards(editor, building, 20)
    for building in outside:
        assert not model.wall.shape.contains_point(Point(*building.center()))
        assert editor._tightest_wall_part(building)[1] < 0.2


def test_towers_and_gates_move_with_their_wall():
    model = walled_city()
    editor = CityEditor(model)
    building = outer_building(model, editor)
    drag_outwards(editor, building, 25)
    for tower in model.wall.towers:
        assert tower in model.wall.shape
    for gate in model.wall.gates:
        assert gate in model.wall.shape


def test_roads_stay_joined_to_their_gates():
    model = walled_city()
    editor = CityEditor(model)
    for building in sorted(inside_buildings(model, editor),
                           key=lambda b: -math.hypot(*b.center()))[:6]:
        drag_outwards(editor, building, 20)
    assert model.roads
    for road in model.roads:
        assert any(v in road for v in model.wall.gates)


def test_undo_puts_the_wall_back():
    model = walled_city()
    editor = CityEditor(model)
    building = outer_building(model, editor)
    start = wall_corners(model.wall)
    before = positions(editor)
    drag_outwards(editor, building, 25)

    editor.undo()
    assert wall_corners(model.wall) == start
    assert not moved(editor, before)


def test_a_locked_building_holds_the_wall_back():
    model = walled_city()
    editor = CityEditor(model)
    building = outer_building(model, editor)
    x, y = building.center()
    size = math.hypot(x, y)
    outside = [b for b in editor.buildings
               if not model.wall.shape.contains_point(Point(*b.center()))]
    guard = min(outside, key=lambda b: math.dist(
        b.center(), (x + x / size * 12, y + y / size * 12)))
    editor.set_locked(guard, True)
    held = guard.corners()

    drag_outwards(editor, building, 80)
    assert guard.corners() == held
    assert model.wall.shape.contains_point(Point(*guard.center())) is False


def test_a_wall_along_the_water_stays_put():
    for seed in range(1, 12):
        model = Model(15, seed, walls=True, coast=False, river=True)
        fixed = [v for v in model.wall.shape if v in model.water_points]
        if not fixed:
            continue
        editor = CityEditor(model)
        spots = [(v.x, v.y) for v in fixed]
        for building in sorted(inside_buildings(model, editor),
                               key=lambda b: -math.hypot(*b.center()))[:6]:
            drag_outwards(editor, building, 20)
        assert [(v.x, v.y) for v in fixed] == spots
        return
    pytest.fail("no walled city with a river crossing")


def test_a_dragged_building_can_cross_a_packed_walled_city():
    model = walled_city()
    editor = CityEditor(model)
    building = outer_building(model, editor)
    x, y = building.center()

    assert editor.begin_move(building)
    for step in range(1, 41):
        reached = editor.drag_to(building, -x * 0.7 * step / 40,
                                 -y * 0.7 * step / 40)
    editor.end_move()

    assert reached
    assert building.center() == pytest.approx((x * 0.3, y * 0.3), abs=0.05)


def test_a_jump_past_the_limit_catches_up_on_the_next_move():
    model = walled_city()
    editor = CityEditor(model)
    building = outer_building(model, editor)
    x, y = building.center()

    assert editor.begin_move(building)
    assert not editor.drag_to(building, -x * 0.7, -y * 0.7)
    for _ in range(30):
        if editor.drag_to(building, -x * 0.7, -y * 0.7):
            break
    editor.end_move()
    assert building.center() == pytest.approx((x * 0.3, y * 0.3), abs=0.05)


def test_undo_also_brings_back_buildings_that_were_shoved():
    model = walled_city()
    editor = CityEditor(model)
    before = positions(editor)
    building = outer_building(model, editor)
    x, y = building.center()
    drag(editor, building, -x * 0.3, -y * 0.3)
    assert len(moved(editor, before)) > 1

    editor.undo()
    assert not moved(editor, before)


def test_a_ring_of_locked_buildings_never_moves():
    model = walled_city()
    editor = CityEditor(model)
    building = outer_building(model, editor)
    for other in editor._nearby(building):
        editor.set_locked(other, True)
    held = {b: b.corners() for b in editor.locked}

    x, y = building.center()
    drag(editor, building, -x * 0.7, -y * 0.7)
    for other, corners in held.items():
        assert other.corners() == corners


def test_every_walled_city_can_still_be_edited():
    for seed in range(1, 8):
        model = Model(15, seed, walls=True, citadel=True, coast=False,
                      river=False)
        editor = CityEditor(model)
        inner = [b for b in editor.buildings if b.ward.patch.within_city]
        sample = inner[::7]
        movable = 0
        for building in sample:
            assert editor.begin_move(building)
            movable += editor.drag_to(building, 0.5, 0.5)
            editor.end_move()
        assert movable > len(sample) * 0.9


def sharpest_turn(shape):
    worst = 0.0
    for i, point in enumerate(shape):
        before = shape[i - 1]
        after = shape[(i + 1) % len(shape)]
        into = math.atan2(point.y - before.y, point.x - before.x)
        out = math.atan2(after.y - point.y, after.x - point.x)
        turn = abs((out - into + math.pi) % (2 * math.pi) - math.pi)
        worst = max(worst, turn)
    return math.degrees(worst)


def test_a_long_push_bends_the_wall_in_a_smooth_curve():
    model = walled_city()
    editor = CityEditor(model)
    limit = sharpest_turn(model.wall.shape)
    start = len(model.wall.shape)
    drag_outwards(editor, outer_building(model, editor), 45)
    assert len(model.wall.shape) > start
    assert sharpest_turn(model.wall.shape) <= limit + 5


def test_a_bulge_is_rounded_not_a_spike():
    model = walled_city()
    editor = CityEditor(model)
    building = outer_building(model, editor)
    home = {v: (v.x, v.y) for v in model.wall.shape}
    drag_outwards(editor, building, 45)
    moved = [v for v, spot in home.items()
             if math.hypot(v.x - spot[0], v.y - spot[1]) > 10]
    # A spike would take only the corners beside the building that far.
    assert len(moved) >= len(home) / 4


def test_a_small_push_only_bends_a_short_stretch():
    model = walled_city()
    editor = CityEditor(model)
    home = {v: (v.x, v.y) for v in model.wall.shape}
    drag_outwards(editor, outer_building(model, editor), 6)
    still = [v for v, spot in home.items()
             if math.hypot(v.x - spot[0], v.y - spot[1]) < 0.01]
    assert len(still) >= len(home) / 2


def test_new_wall_corners_join_the_ward_outlines():
    model = walled_city()
    editor = CityEditor(model)
    drag_outwards(editor, outer_building(model, editor), 30)
    shape = model.wall.shape
    assert len(model.wall.segments) == len(shape)
    for a, b in shape.edges():
        inside = [p for p in model.wall.patches if p.shape.find_edge(a, b) != -1]
        assert len(inside) == 1


def test_new_wall_corners_have_no_towers():
    model = walled_city()
    editor = CityEditor(model)
    towers = list(model.wall.towers)
    drag_outwards(editor, outer_building(model, editor), 30)
    assert all(a is b for a, b in zip(model.wall.towers, towers))
    assert len(model.wall.towers) == len(towers)


def test_undo_takes_away_the_new_wall_corners():
    model = walled_city(citadel=True)
    editor = CityEditor(model)
    corners = list(model.wall.shape)
    start = wall_corners(model.wall)
    segments = list(model.wall.segments)
    outlines = {p: list(p.shape) for p in model.patches}
    drag_outwards(editor, outer_building(model, editor), 30)
    assert len(model.wall.shape) > len(corners)
    assert editor.undo()
    assert all(a is b for a, b in zip(model.wall.shape, corners))
    assert wall_corners(model.wall) == start
    assert model.wall.segments == segments
    for patch, outline in outlines.items():
        assert len(patch.shape) == len(outline)


def test_a_step_that_fails_takes_away_its_new_wall_corners(monkeypatch):
    model = walled_city()
    editor = CityEditor(model)
    building = outer_building(model, editor)
    divided = []
    divide = editor._divide_edge

    def counting(*args):
        divided.append(args)
        divide(*args)

    editor._divide_edge = counting
    monkeypatch.setattr(editing, "MAX_PUSHES", -1)
    x, y = building.center()
    size = math.hypot(x, y)
    editor.begin_move(building)
    for _ in range(40):
        divided.clear()
        corners = len(model.wall.shape)
        if not editor._try_step(building, x / size * 2, y / size * 2) and divided:
            assert len(model.wall.shape) == corners
            assert len(model.wall.segments) == corners
            return
    pytest.fail("no step failed after adding wall corners")


def test_roads_stay_outside_a_bulge():
    model = walled_city()
    editor = CityEditor(model)
    drag_outwards(editor, outer_building(model, editor), 45)
    for road in model.roads:
        for v in road:
            if v not in model.wall.shape:
                assert not model.wall.shape.contains_point(v)


def test_a_building_outside_can_dent_the_wall_inwards():
    model = walled_city()
    editor = CityEditor(model)
    outside = [b for b in editor.buildings
               if b.ward.patch not in model.wall.patches]
    building = min(outside, key=lambda b: editor._wall_gap(b))
    x, y = building.center()
    size = math.hypot(x, y)
    home = wall_corners(model.wall)
    drag(editor, building, -x / size * 8, -y / size * 8)
    assert wall_corners(model.wall) != home
    assert not model.wall.shape.contains_point(Point(*building.center()))


def test_a_wall_bends_around_a_locked_building():
    model = walled_city()
    editor = CityEditor(model)
    building = outer_building(model, editor)
    outside = [b for b in editor.buildings
               if b.ward.patch not in model.wall.patches]
    guard = min(outside, key=lambda b: math.hypot(
        b.cx - building.cx, b.cy - building.cy))
    editor.set_locked(guard, True)
    spot = guard.center()
    drag_outwards(editor, building, 30)
    assert guard.center() == spot
    assert not model.wall.shape.contains_point(Point(*spot))


def test_towers_by_a_river_stay_on_their_wall():
    for seed in range(40):
        model = Model(15, seed, walls=True, coast=False, river=True)
        editor = CityEditor(model)
        if not editor.bank_towers:
            continue
        for building in sorted(inside_buildings(model, editor),
                               key=lambda b: -math.hypot(*b.center()))[:4]:
            drag_outwards(editor, building, 15)
        for tower, (crossing, step) in editor.bank_towers.items():
            along = editor._along_wall(model.wall, crossing, step)
            ax = along.x - crossing.x
            ay = along.y - crossing.y
            tx = tower.x - crossing.x
            ty = tower.y - crossing.y
            assert abs(ax * ty - ay * tx) / math.hypot(ax, ay) < 0.01
        return
    pytest.fail("no walled city with a river crossing")


def test_a_building_touching_a_wall_cant_be_shoved_through_it():
    model = walled_city()
    editor = CityEditor(model)
    touching = [b for b in inside_buildings(model, editor)
                if b in editor.wall_allowance]
    assert touching
    for building in touching[:6]:
        drag_outwards(editor, building, 15)
        assert model.wall.shape.contains_point(Point(*building.center()))


def test_a_wall_moves_a_building_it_comes_towards_though_they_touched():
    model = walled_city()
    editor = CityEditor(model)
    touching = [b for b in editor.buildings if b in editor.wall_allowance
                and b.ward.patch not in model.wall.patches]
    if not touching:
        pytest.skip("no building outside touches the wall")
    near = min(touching, key=lambda b: math.hypot(*b.center()))
    x, y = near.center()
    inner = min(inside_buildings(model, editor), key=lambda b: math.hypot(
        b.cx - x, b.cy - y))
    drag(editor, inner, x - inner.cx, y - inner.cy)
    assert not model.wall.shape.contains_point(Point(*near.center()))


def crosses_itself(shape):
    edges = shape.edges()
    for i, (a, b) in enumerate(edges):
        for c, d in edges[i + 2:]:
            if d is a:
                continue
            if editing._segments_cross(a.x, a.y, b.x, b.y, c.x, c.y, d.x, d.y):
                return True
    return False


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_walls_never_cross_themselves(seed):
    model = Model(10, seed, walls=True, citadel=True, coast=False, river=False)
    editor = CityEditor(model)
    for building in sorted(inside_buildings(model, editor),
                           key=lambda b: -math.hypot(*b.center()))[:5]:
        drag_outwards(editor, building, 25)
    assert not crosses_itself(model.wall.shape)
    assert not crosses_itself(model.citadel.ward.wall.shape)


def test_a_wall_stays_out_of_the_sea():
    for seed in range(1, 10):
        model = Model(15, seed, walls=True, coast=True, river=False)
        if model.wall is None or model.sea is None:
            continue
        editor = CityEditor(model)
        for building in sorted(inside_buildings(model, editor),
                               key=lambda b: -math.hypot(*b.center()))[:4]:
            drag_outwards(editor, building, 20)
        for corner in model.wall.shape:
            if corner not in model.water_points:
                assert not model.sea.contains_point(corner)
        return
    pytest.fail("no walled city on a coast")
