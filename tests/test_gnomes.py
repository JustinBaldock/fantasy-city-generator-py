import json
import math
import random

import pytest

from citygen import editing, export, gnomes
from citygen.editing import CityEditor
from citygen.geometry import Point, Polygon
from citygen.gnomes import GnomeHome, outline
from citygen.layers import PALETTES, build_layers
from citygen.model import Model
from citygen.wards import (
    AdministrationWard,
    Cathedral,
    CraftsmenWard,
    Farm,
    MerchantWard,
    MilitaryWard,
)

PALETTE = PALETTES["Default"]
OPTIONS = [dict(size=9, seed=3), dict(size=15, seed=7),
           dict(size=24, seed=21, coast=True, river=True),
           dict(size=15, seed=5, walls=True, citadel=True, temple=True)]


def homes_in(model):
    return [(patch.ward, home) for patch in model.patches
            for home in patch.ward.geometry if isinstance(home, GnomeHome)]


def is_home_ward(ward):
    return ward.homes or isinstance(ward, Farm)


def between(a, b):
    return math.hypot(b[0] - a[0], b[1] - a[1])


def outlines_cross(a, b):
    for i in range(len(a)):
        for j in range(len(b)):
            if editing._segments_cross(
                    a[i].x, a[i].y, a[i - 1].x, a[i - 1].y,
                    b[j].x, b[j].y, b[j - 1].x, b[j - 1].y):
                return True
    return False


@pytest.mark.parametrize("sides", [{0}, {1, 3}, {0, 2, 5}, {0, 1, 2, 3}])
def test_a_home_is_a_regular_hexagon_with_rooms_on_the_sides_asked_for(sides):
    radius = 3.0
    points = outline(2, 5, radius, 0.4, 2.0, sides)
    assert len(points) == 6 + 4 * len(sides)

    home = gnomes._home_at(2, 5, radius, 0.4, 2.0, sides)
    assert len(home.joins) == len(sides)
    inner = set(range(len(points)))
    for a, b in home.joins:
        inner -= {a + 1, a + 2, a, b}
    # What's left is every corner of the hexagon, each one radius from centre.
    assert len(inner) == 6
    for i in inner:
        assert between((2, 5), points[i]) == pytest.approx(radius)


def test_rooms_are_square():
    home = gnomes._home_at(0, 0, 3.0, 0.4, 2.0, {0, 2, 3})
    for a, b in home.joins:
        near, out1, out2, far = (home[a], home[a + 1], home[a + 2], home[b])
        lengths = [math.hypot(q.x - p.x, q.y - p.y) for p, q in (
            (near, out1), (out1, out2), (out2, far), (far, near))]
        assert lengths == pytest.approx([2.0] * 4)
        assert out1.subtract(near).dot(far.subtract(near)) == pytest.approx(0)


def test_rooms_grow_outwards():
    home = gnomes._home_at(0, 0, 3.0, 0.4, 2.0, {0, 1, 2, 3, 4, 5})
    for a, b in home.joins:
        assert math.hypot(home[a + 1].x, home[a + 1].y) > 3.0
        assert math.hypot(home[a].x, home[a].y) <= 3.0


def test_the_option_is_off_unless_asked_for():
    assert not homes_in(Model(size=15, seed=7))


@pytest.mark.parametrize("options", OPTIONS)
def test_homes_have_some_rooms_but_never_a_full_ring(options):
    model = Model(gnome_homes=True, **options)
    homes = homes_in(model)
    assert homes
    assert all(1 <= len(home.joins) <= max(gnomes.ROOMS) for _, home in homes)
    assert any(len(home.joins) >= 2 for _, home in homes)


@pytest.mark.parametrize("options", OPTIONS)
def test_gnome_homes_only_go_in_wards_where_people_live(options):
    model = Model(gnome_homes=True, **options)
    for patch in model.patches:
        if not is_home_ward(patch.ward):
            assert not any(isinstance(b, GnomeHome)
                           for b in patch.ward.geometry)


def is_rectangle(building):
    if len(building) != 4:
        return False
    for i in range(4):
        one = building[i].subtract(building[i - 1])
        other = building[(i + 1) % 4].subtract(building[i])
        if abs(one.dot(other)) > 1e-6:
            return False
    return True


@pytest.mark.parametrize("options", OPTIONS)
def test_home_wards_hold_only_homes_and_true_rectangles(options):
    model = Model(gnome_homes=True, **options)
    for patch in model.patches:
        ward = patch.ward
        if is_home_ward(ward):
            for building in ward.geometry:
                assert isinstance(building, GnomeHome) or is_rectangle(building)


def test_a_gnome_city_still_has_plenty_of_rectangles():
    model = Model(gnome_homes=True, size=24, seed=21)
    wards = [p.ward for p in model.patches if p.ward.homes]
    buildings = [b for ward in wards for b in ward.geometry]
    rectangles = [b for b in buildings if is_rectangle(b)]
    assert 0.1 < len(rectangles) / len(buildings) < 0.5


def test_merchants_have_more_shops_than_craftsmen_have_workshops():
    def share(ward_type):
        buildings = [
            b for seed in range(1, 13)
            for p in Model(gnome_homes=True, size=24, seed=seed).patches
            if type(p.ward) is ward_type for b in p.ward.geometry]
        return sum(map(is_rectangle, buildings)) / len(buildings)

    assert share(MerchantWard) > share(CraftsmenWard)


def test_government_and_military_buildings_are_all_rectangles():
    found = 0
    for seed in range(1, 13):
        model = Model(gnome_homes=True, size=24, seed=seed)
        for patch in model.patches:
            if isinstance(patch.ward, (AdministrationWard, MilitaryWard)):
                found += len(patch.ward.geometry)
                assert all(is_rectangle(b) for b in patch.ward.geometry)
    assert found


def farms_of(model):
    return [p.ward for p in model.patches if isinstance(p.ward, Farm)]


def test_farms_have_one_home_and_often_a_barn():
    wards = [ward for seed in range(1, 7)
             for ward in farms_of(Model(gnome_homes=True, size=15, seed=seed))
             if ward.geometry]
    assert wards
    for ward in wards:
        homes = [b for b in ward.geometry if isinstance(b, GnomeHome)]
        barns = [b for b in ward.geometry if is_rectangle(b)]
        assert len(homes) == 1 and len(barns) <= 1
        assert len(ward.geometry) == len(homes) + len(barns)
    assert sum(len(ward.geometry) == 2 for ward in wards) > len(wards) / 2


def test_barns_clear_their_farmhouses_and_stay_on_their_land():
    for seed in range(1, 7):
        for ward in farms_of(Model(gnome_homes=True, size=15, seed=seed,
                                   coast=True)):
            if len(ward.geometry) == 2:
                home, barn = ward.geometry
                assert not outlines_cross(home, barn)
                assert not home.contains_point(barn[0])
                assert all(ward.patch.shape.contains_point(v) for v in barn)


def test_temples_keep_their_landmarks():
    model = Model(gnome_homes=True, size=15, seed=5, temple=True)
    wards = [p.ward for p in model.patches if isinstance(p.ward, Cathedral)]
    assert wards
    for ward in wards:
        assert ward.landmarks
        assert not any(isinstance(b, GnomeHome) for b in ward.landmarks)


@pytest.mark.parametrize("options", OPTIONS)
def test_homes_stay_in_their_blocks(options):
    model = Model(gnome_homes=True, **options)
    for patch in model.patches:
        ward = patch.ward
        if isinstance(ward, Farm) or not (ward.homes or ward.rectangle_share):
            continue
        block = ward.get_city_block()
        for building in ward.geometry:
            assert all(block.contains_point(v) for v in building)


@pytest.mark.parametrize("options", OPTIONS)
def test_buildings_do_not_touch_each_other(options):
    model = Model(gnome_homes=True, **options)
    buildings = [b for p in model.patches if is_home_ward(p.ward)
                 or p.ward.rectangle_share for b in p.ward.geometry]
    for i, a in enumerate(buildings):
        for b in buildings[i + 1:]:
            if abs(a[0].x - b[0].x) + abs(a[0].y - b[0].y) < 25:
                assert not outlines_cross(a, b)
                assert not a.contains_point(b[0])


@pytest.mark.parametrize("options", OPTIONS)
def test_the_option_leaves_the_city_around_the_homes_alone(options):
    ordinary = export.city_to_dict(Model(**options))
    gnome = export.city_to_dict(Model(gnome_homes=True, **options))
    for key in ("streets", "roads", "wall", "castle_wall", "river", "bridges",
                "shore", "center", "city_radius"):
        assert ordinary[key] == gnome[key]
    assert ([w["shape"] for w in ordinary["wards"]]
            == [w["shape"] for w in gnome["wards"]])
    assert ([w["type"] for w in ordinary["wards"]]
            == [w["type"] for w in gnome["wards"]])


def test_a_seed_always_gives_the_same_homes():
    first = Model(gnome_homes=True, size=15, seed=7)
    second = Model(gnome_homes=True, size=15, seed=7)
    assert export.city_to_dict(first) == export.city_to_dict(second)


def test_a_sliver_of_a_plot_stops_being_cut():
    sliver = Polygon([Point(0, 0), Point(40, 0), Point(40, 0.2),
                             Point(0, 0.2)])
    assert gnomes._shares_of(sliver)[0][0] is sliver
    assert gnomes._buildings_for([sliver], 0.0, random.Random(1)) == []


def test_a_long_plot_gets_more_than_one_home():
    plot = Polygon([Point(0, 0), Point(40, 0), Point(40, 8),
                           Point(0, 8)])
    assert len(gnomes._buildings_for([plot], 0.0, random.Random(1))) >= 2


def test_a_long_plot_can_be_one_long_building():
    plot = Polygon([Point(0, 0), Point(40, 0), Point(40, 8), Point(0, 8)])
    chooser = random.Random(1)
    built = [gnomes._buildings_for([plot], 1.0, chooser)[0] for _ in range(20)]
    assert all(is_rectangle(b) for b in built)
    assert max(b[0].subtract(b[1]).length for b in built) > 10


def test_rectangles_fit_tight_and_awkward_plots():
    plot = Polygon([Point(0, 0), Point(9, 1), Point(7, 6), Point(1, 4)])
    chooser = random.Random(1)
    for _ in range(50):
        building = gnomes._buildings_for([plot], 1.0, chooser)[0]
        assert is_rectangle(building)
        assert all(plot.contains_point(v) for v in building)


def walls_of(model):
    layer = next(x for x in build_layers(model, PALETTE)
                 if x.name == "Room walls")
    return layer.polylines


def test_each_room_gets_a_wall_on_the_map():
    model = Model(gnome_homes=True, size=15, seed=7)
    assert len(walls_of(model)) == sum(
        len(home.joins) for _, home in homes_in(model))


def test_ordinary_maps_have_no_room_walls():
    assert walls_of(Model(size=15, seed=7)) == []


def test_room_walls_show_in_the_svg():
    model = Model(gnome_homes=True, size=15, seed=7)
    assert 'id="room-walls"' in export.city_to_svg(model, PALETTE)
    assert 'id="room-walls"' not in export.city_to_svg(
        Model(size=15, seed=7), PALETTE)


def test_the_json_says_which_homes_it_has(tmp_path):
    path = tmp_path / "city.json"
    export.save_json(Model(gnome_homes=True, size=9, seed=3), path)
    assert json.loads(path.read_text())["gnome_homes"] is True
    assert export.city_to_dict(Model(size=9, seed=3))["gnome_homes"] is False


def home_in_editor(editor):
    return next(b for b in sorted(editor.buildings,
                                  key=lambda b: (b.cx, b.cy))
                if isinstance(b.polygon, GnomeHome))


def test_clicking_a_room_selects_its_home():
    editor = CityEditor(Model(gnome_homes=True, size=15, seed=7))
    building = home_in_editor(editor)
    home = building.polygon
    a, _ = home.joins[0]
    out1, out2 = home[a + 1], home[a + 3]
    inside_room = Point((out1.x + out2.x) / 2, (out1.y + out2.y) / 2)
    assert editor.building_at(inside_room) is building


def test_a_home_moves_whole_and_its_rooms_go_with_it():
    editor = CityEditor(Model(gnome_homes=True, size=15, seed=7))
    building = home_in_editor(editor)
    home = building.polygon
    before = [(a.x, a.y, b.x, b.y) for a, b in home.room_walls()]
    x, y = building.center()

    assert editor.begin_move(building)
    editor.drag_to(building, 1.5, -1.0)
    editor.end_move()

    assert isinstance(building.polygon, GnomeHome)
    moved_x, moved_y = building.center()
    dx, dy = moved_x - x, moved_y - y
    assert (dx, dy) != (0, 0)
    after = [(a.x, a.y, b.x, b.y) for a, b in home.room_walls()]
    for old, new in zip(before, after):
        assert new == pytest.approx(
            (old[0] + dx, old[1] + dy, old[2] + dx, old[3] + dy))

    assert editor.undo()
    assert building.center() == pytest.approx((x, y))
    assert [(a.x, a.y, b.x, b.y) for a, b in home.room_walls()] == before


def test_a_locked_home_stays_put():
    editor = CityEditor(Model(gnome_homes=True, size=15, seed=7))
    building = home_in_editor(editor)
    editor.set_locked(building, True)
    assert not editor.begin_move(building)
