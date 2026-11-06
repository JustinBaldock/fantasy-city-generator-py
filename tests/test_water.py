import pytest

from citygen.export import city_to_dict
from citygen.layers import PALETTES, build_layers
from citygen.model import Model
from citygen.water import direction_from_bearing
from citygen.wards import Cathedral, Park

SEEDS = range(1, 9)


def layer_names(model):
    names = []
    for layer in build_layers(model, PALETTES["Default"]):
        if layer.polygons or layer.polylines or layer.circles:
            names.append(layer.name)
    return names


def test_no_water_leaves_nothing_of_it_behind():
    model = Model(15, 12, coast=False, river=False)
    assert model.sea is None
    assert not model.river and not model.bridges and not model.piers


def test_turning_a_feature_on_keeps_the_seed_repeatable():
    first = city_to_dict(Model(15, 5, coast=True, river=True))
    second = city_to_dict(Model(15, 5, coast=True, river=True))
    assert first == second


@pytest.mark.parametrize("bearing", [0, 90, 180, 270])
def test_coast_lies_on_the_chosen_side(bearing):
    direction = direction_from_bearing(bearing)
    for seed in SEEDS:
        model = Model(15, seed, coast=True, river=False, sea=bearing)
        middle = model.shore[len(model.shore) // 2]
        assert middle.dot(direction) > 0


def test_bearings_follow_the_compass():
    north = direction_from_bearing(0)
    east = direction_from_bearing(90)
    assert (round(north.x), round(north.y)) == (0, -1)
    assert (round(east.x), round(east.y)) == (1, 0)


def test_no_ward_stands_in_the_sea():
    for seed in SEEDS:
        model = Model(15, seed, coast=True, river=False)
        for patch in model.inner:
            assert model.seaward(patch.shape.center) < 12
        assert all(not patch.water for patch in model.patches)


def test_coastal_walls_stop_at_the_water():
    found = False
    for seed in range(1, 30):
        model = Model(15, seed, coast=True, river=False, walls=True)
        if not all(model.wall.segments):
            found = True
            assert not any(gate in model.shore_points
                           for gate in model.wall.gates)
    assert found


def test_coastal_city_has_piers():
    assert any(Model(15, seed, coast=True, river=False).piers for seed in SEEDS)


def test_a_river_runs_along_ward_edges():
    for seed in SEEDS:
        model = Model(15, seed, coast=False, river=True)
        edges = {edge for patch in model.patches
                 for edge in patch.shape.edges()}
        on_edges = sum((a, b) in edges or (b, a) in edges
                       for a, b in zip(model.river, model.river[1:]))
        assert on_edges >= len(model.river) // 2


def test_every_river_city_is_bridged_and_stays_one_city():
    for seed in SEEDS:
        model = Model(15, seed, coast=False, river=True, walls=True)
        assert model.bridges
        assert model.streets
        for street in model.streets:
            assert not any(v in model.river_points - model.bridge_points
                           for v in street)


def test_streets_only_cross_at_bridges():
    for seed in SEEDS:
        model = Model(15, seed, river=True, coast=True)
        for street in model.streets:
            for a, b in zip(street, street[1:]):
                assert (a, b) not in model.river_edges


def test_river_reaches_the_sea():
    for seed in SEEDS:
        model = Model(15, seed, coast=True, river=True)
        assert any(v in model.shore_points for v in model.river)


def test_gates_stay_off_the_water():
    for seed in SEEDS:
        model = Model(15, seed, coast=True, river=True, walls=True)
        for gate in model.gates:
            assert gate not in model.river_points
            assert gate not in model.shore_points


def test_buildings_stay_off_the_river():
    from citygen.geometry import distance

    for seed in SEEDS:
        model = Model(15, seed, coast=False, river=True)
        for patch in model.inner:
            for building in patch.ward.geometry:
                for v in building:
                    near = min(distance(v, p) for p in model.river)
                    assert near > 2


def test_temple_can_be_forced_and_has_a_landmark():
    for seed in SEEDS:
        model = Model(15, seed, temple=True)
        temples = [p.ward for p in model.patches
                   if isinstance(p.ward, Cathedral)]
        assert temples
        assert all(ward.landmarks for ward in temples)


def test_temple_can_be_ruled_out():
    for seed in SEEDS:
        model = Model(24, seed, temple=False)
        assert not any(isinstance(p.ward, Cathedral) for p in model.patches)


def test_greens_can_be_forced_or_ruled_out():
    for seed in SEEDS:
        assert any(isinstance(p.ward, Park)
                   for p in Model(15, seed, greens=True).patches)
        assert not any(isinstance(p.ward, Park)
                       for p in Model(40, seed, greens=False).patches)


def test_two_road_option_keeps_two():
    for seed in SEEDS:
        assert len(Model(24, seed, hub=False).roads) <= 2


def test_water_gets_its_own_layers():
    names = layer_names(Model(15, 3, coast=True, river=True, walls=True))
    assert {"Sea", "River", "Bridges", "Piers"} <= set(names)
    assert names.index("City wall") < names.index("River")
