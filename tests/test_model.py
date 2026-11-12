import json
import math

import pytest

from citygen.export import city_to_dict
from citygen.model import Model, size_name
from citygen.wards import Castle, Market, Ward

SIZES = (6, 10, 15, 24, 40)


def cities():
    for size in SIZES:
        for seed in range(1, 16):
            yield Model(size, seed * 7919 + size)


def test_a_seed_always_gives_the_same_city():
    first = json.dumps(city_to_dict(Model(15, 12345)))
    second = json.dumps(city_to_dict(Model(15, 12345)))
    assert first == second


def test_different_seeds_give_different_cities():
    first = json.dumps(city_to_dict(Model(15, 1)))
    second = json.dumps(city_to_dict(Model(15, 2)))
    assert first != second


@pytest.mark.parametrize("size, name", [
    (1, "Hamlet"), (2, "Hamlet"), (3, "Village"), (5, "Village"),
    (6, "Small Town"), (14, "Large Town"), (15, "Small City"),
    (39, "Large City"), (40, "Metropolis"), (69, "Metropolis"),
    (70, "Capital"), (100, "Capital"),
])
def test_size_names(size, name):
    assert size_name(size) == name


def test_every_city_is_whole():
    for model in cities():
        assert model.city_radius > 0
        assert model.gates
        assert model.streets

        built = 0
        for patch in model.patches:
            assert patch.ward is not None
            for building in patch.ward.geometry:
                assert len(building) >= 3
                built += 1
                for v in building:
                    assert math.isfinite(v.x) and math.isfinite(v.y)
        assert built > 0


def test_retries_are_only_the_expected_failures():
    for model in cities():
        for failure in model.failures:
            assert failure.startswith("GenerationError"), failure


def test_wall_gates_lie_on_the_wall():
    for model in cities():
        if model.wall is not None:
            for gate in model.wall.gates:
                assert gate in model.wall.shape


def test_inner_wards_share_their_vertices():
    # Neighbours must hold the very same point objects, or moving a vertex
    # would tear them apart.
    model = Model(15, 42)
    shared = 0
    for patch in model.inner:
        for neighbour in model.get_neighbours(patch):
            shared += sum(1 for v in patch.shape if v in neighbour.shape)
    assert shared > 0


@pytest.mark.parametrize("value", [True, False])
def test_walls_can_be_forced(value):
    for seed in range(1, 6):
        assert (Model(15, seed, walls=value).wall is not None) == value


@pytest.mark.parametrize("value", [True, False])
def test_castle_can_be_forced(value):
    for seed in range(1, 6):
        model = Model(15, seed, citadel=value)
        assert (model.citadel is not None) == value
        if value:
            assert isinstance(model.citadel.ward, Castle)


@pytest.mark.parametrize("value", [True, False])
def test_plaza_can_be_forced(value):
    for seed in range(1, 6):
        model = Model(15, seed, plaza=value)
        assert (model.plaza is not None) == value
        if value:
            assert isinstance(model.plaza.ward, Market)


def test_patch_at_finds_the_ward_under_a_point():
    model = Model(15, 42)
    patch = model.patches[0]
    assert model.patch_at(patch.shape.center) is patch


def test_land_outside_the_city_has_no_label():
    model = Model(15, 42)
    assert any(type(p.ward) is Ward and p.ward.label is None
               for p in model.patches)


def temples_in(model):
    from citygen.wards import Cathedral
    return [p for p in model.patches if isinstance(p.ward, Cathedral)]


@pytest.mark.parametrize("count", [1, 2, 5, 10])
def test_a_town_gets_the_temples_asked_for(count):
    assert len(temples_in(Model(24, 7, temple=True, temples=count))) == count


def test_a_small_town_gets_as_many_temples_as_it_has_room_for():
    model = Model(8, 7, temple=True, temples=10)
    temples = temples_in(model)
    assert 1 <= len(temples) < 10
    others = [p for p in model.inner if p not in temples]
    from citygen.wards import GateWard, Market
    assert all(isinstance(p.ward, (GateWard, Market)) for p in others)


def test_temples_keep_apart_where_there_is_room():
    model = Model(24, 7, temple=True, temples=4)
    temples = temples_in(model)
    for i, a in enumerate(temples):
        for b in temples[i + 1:]:
            assert not a.shape.borders(b.shape)


def test_no_temple_means_none_whatever_the_count():
    assert not temples_in(Model(15, 7, temple=False, temples=6))


def test_left_to_the_seed_temples_come_all_together_or_not_at_all():
    for seed in range(1, 13):
        found = len(temples_in(Model(15, seed, temples=3)))
        assert found in (0, 3)


def test_one_temple_leaves_the_town_as_it_was():
    from citygen.export import city_to_dict
    plain = city_to_dict(Model(15, 7))
    one = city_to_dict(Model(15, 7, temples=1))
    assert plain == one


@pytest.mark.parametrize("count", [0, 11])
def test_temple_counts_stay_in_range(count):
    with pytest.raises(ValueError):
        Model(9, 3, temples=count)


SMALL_OPTIONS = [
    dict(),
    dict(walls=True, citadel=True, river=True, coast=True, fields=True,
         orchards=True, greens=True, temple=True, temples=3, field_ratio=4),
    dict(home_style="gnome", walls=False, fields=True, field_ratio=4),
    dict(home_style="classic", plaza=True),
]


@pytest.mark.parametrize("size", range(1, 6))
@pytest.mark.parametrize("options", SMALL_OPTIONS)
def test_hamlets_and_villages_build(size, options):
    for seed in range(1, 6):
        model = Model(size=size, seed=seed, **options)
        assert len(model.inner) == size
        # There is countryside round even the smallest town.
        assert any(not p.within_city for p in model.patches)


def test_a_hamlet_has_houses_not_just_a_plaza():
    for seed in range(1, 11):
        model = Model(size=1, seed=seed, plaza=True)
        assert model.plaza is None
        assert model.inner[0].ward.geometry


def test_a_hamlet_with_a_castle_has_a_way_in():
    for seed in range(1, 6):
        model = Model(size=1, seed=seed, citadel=True, walls=True)
        castle = model.citadel.ward
        assert castle.wall.gates
        assert model.citadel.shape.compactness >= 0.75


def _bearing_gaps(model):
    bearings = sorted(math.atan2(road[0].y, road[0].x) for road in model.roads)
    gaps = [b - a for a, b in zip(bearings, bearings[1:])]
    return gaps + [2 * math.pi - (bearings[-1] - bearings[0])]


@pytest.mark.parametrize("wanted", [1, 2, 4, 6, 8, 10])
def test_a_big_inland_town_gets_the_roads_asked_for(wanted):
    for seed in range(1, 4):
        model = Model(60, seed, roads=wanted, coast=False, river=False)
        assert len(model.roads) == wanted


def test_roads_spread_round_the_town():
    model = Model(40, 2, roads=6, coast=False, river=False)
    assert len(model.roads) == 6
    # No two leave within a fifth of an even share of the circle.
    assert min(_bearing_gaps(model)) > 2 * math.pi / 6 / 5


def test_a_small_town_gets_as_many_roads_as_its_walls_have_room_for():
    for seed in range(1, 6):
        model = Model(6, seed, roads=10)
        assert 1 <= len(model.roads) <= 10
        assert len(model.roads) >= len(Model(6, seed).roads)


def test_all_gates_and_the_old_two_roads_are_unchanged():
    from citygen.export import city_to_dict

    def town(**options):
        data = city_to_dict(Model(24, 4, **options))
        del data["settings"]
        return data

    assert town() == town(roads=None)
    two = town(hub=False)
    assert len(Model(24, 4, hub=False).roads) <= 2
    assert two == town(hub=False, roads=None)


@pytest.mark.parametrize("roads", [0, 11])
def test_road_counts_stay_in_range(roads):
    with pytest.raises(ValueError):
        Model(9, 3, roads=roads)


def test_a_capital_of_a_hundred_wards_builds():
    model = Model(100, 1, home_style="gnome")
    assert len(model.inner) == 100
