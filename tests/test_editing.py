import math

import pytest

from citygen import export
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
