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
    (6, "Small Town"), (14, "Large Town"), (15, "Small City"),
    (39, "Large City"), (40, "Metropolis"),
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
