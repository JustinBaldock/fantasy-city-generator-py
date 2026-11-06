from citygen.countryside import furrows
from citygen.export import city_to_dict
from citygen.geometry import Point, Polygon, distance
from citygen.layers import PALETTES, build_layers
from citygen.model import Model

SEEDS = range(1, 9)


def strip(width=20, height=10):
    return Polygon([Point(0, 0), Point(width, 0), Point(width, height),
                    Point(0, height)])


def test_furrows_run_along_the_longest_edge():
    lines = furrows(strip(), 1.0)
    assert len(lines) == 10
    for a, b in lines:
        assert a.y == b.y
        assert abs(a.x - b.x) == 20


def test_furrows_stay_inside_their_plot():
    plot = Polygon([Point(0, 0), Point(20, 2), Point(16, 12), Point(3, 9)])
    for a, b in furrows(plot):
        middle = Point((a.x + b.x) / 2, (a.y + b.y) / 2)
        assert plot.contains_point(middle)


def test_fields_can_be_forced_or_ruled_out():
    assert any(Model(15, seed, fields=True, forests=False).fields
               for seed in SEEDS)
    for seed in SEEDS:
        model = Model(15, seed, fields=False)
        assert not model.fields and not model.furrows


def test_forests_can_be_forced_or_ruled_out():
    for size in (6, 15, 28, 40):
        for seed in SEEDS:
            assert Model(size, seed, forests=True, fields=False).trees
    for seed in SEEDS:
        assert not Model(15, seed, forests=False).trees


def test_the_countryside_does_not_change_the_city():
    plain = city_to_dict(Model(15, 21, fields=False, forests=False))
    full = city_to_dict(Model(15, 21, fields=True, forests=True))
    assert plain["streets"] == full["streets"]
    assert plain["roads"] == full["roads"]
    city_only = lambda data: [w["buildings"] for w in data["wards"]
                              if w["within_city"]]
    assert city_only(plain) == city_only(full)


def test_the_countryside_keeps_the_seed_repeatable():
    first = city_to_dict(Model(15, 8, fields=True, forests=True))
    second = city_to_dict(Model(15, 8, fields=True, forests=True))
    assert first == second


def test_trees_stay_off_roads_and_rivers():
    for seed in SEEDS:
        model = Model(15, seed, forests=True, coast=False, river=True)
        lines = model.roads + [model.river]
        for x, y, radius in model.trees:
            tree = Point(x, y)
            for line in lines:
                assert all(distance(tree, v) > radius for v in line)


def test_trees_stay_out_of_the_city():
    for seed in SEEDS:
        model = Model(15, seed, forests=True)
        for x, y, _ in model.trees:
            assert model.patch_at(Point(x, y)) is None or not (
                model.patch_at(Point(x, y)).within_city)


def test_trees_stay_out_of_the_sea():
    for seed in SEEDS:
        model = Model(15, seed, forests=True, coast=True)
        for x, y, radius in model.trees:
            assert model.seaward(Point(x, y)) < -radius


def test_trees_stay_off_the_fields():
    for seed in SEEDS:
        model = Model(15, seed, forests=True, fields=True)
        for x, y, _ in model.trees:
            assert not any(plot.contains_point(Point(x, y))
                           for plot in model.fields)


def test_countryside_has_its_own_layers_under_the_roads():
    model = next(m for m in (Model(15, s, forests=True, fields=True)
                             for s in SEEDS) if m.trees and m.fields)
    names = [layer.name for layer in build_layers(model, PALETTES["Default"])]
    assert names.index("Furrows") < names.index("Road edges")
    assert names.index("Forest") < names.index("Road edges")
