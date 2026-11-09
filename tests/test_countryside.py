import pytest

from citygen.countryside import furrows, orchard_rows
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


def test_orchard_trees_stand_in_straight_rows():
    import random
    trees = orchard_rows(strip(21, 12), random.Random(1), spacing=3.0)
    xs = sorted({round(x, 6) for x, _, _ in trees})
    ys = sorted({round(y, 6) for _, y, _ in trees})
    assert len(trees) == len(xs) * len(ys)
    assert all(b - a == pytest.approx(3.0) for a, b in zip(xs, xs[1:]))
    assert all(b - a == pytest.approx(3.0) for a, b in zip(ys, ys[1:]))
    for x, y, r in trees:
        assert 0 < x - r and x + r < 21 and 0 < y - r and y + r < 12


def test_orchards_can_be_forced_or_ruled_out():
    for seed in SEEDS:
        assert not Model(size=15, seed=seed, orchards=False).orchards
    assert all(Model(size=15, seed=seed, orchards=True).orchard_trees
               for seed in SEEDS)


def test_orchards_need_no_fields():
    model = Model(size=15, seed=3, orchards=True, fields=False)
    assert model.orchards and not model.fields


def test_orchards_leave_the_other_fields_alone():
    def plots(model):
        return {tuple((round(v.x, 6), round(v.y, 6)) for v in plot)
                for plot in model.fields}

    for seed in SEEDS:
        without = plots(Model(size=15, seed=seed, fields=True, orchards=False))
        with_orchards = plots(Model(size=15, seed=seed, fields=True,
                                    orchards=True))
        assert with_orchards <= without


def test_orchard_trees_stay_in_their_orchards_and_off_the_roads():
    from citygen import countryside
    from citygen.plots import clearance

    for seed in SEEDS:
        model = Model(size=15, seed=seed, orchards=True)
        roads = countryside._road_pieces(model)
        for x, y, r in model.orchard_trees:
            assert any(clearance(plot, x, y) >= r for plot in model.orchards)
            assert all(countryside._to_road(x, y, a, b) >= r
                       for a, b in roads)


def test_forests_keep_out_of_orchards():
    model = Model(size=15, seed=3, orchards=True, forests=True)
    for x, y, _ in model.trees:
        assert not any(plot.contains_point(Point(x, y))
                       for plot in model.orchards)


def test_orchards_are_drawn_and_exported():
    model = Model(size=15, seed=3, orchards=True)
    layers = {layer.name: layer for layer in build_layers(
        model, PALETTES["Default"])}
    assert layers["Orchards"].circles == model.orchard_trees
    assert len(layers["Orchard edges"].polygons) == len(model.orchards)
    data = city_to_dict(model)
    assert len(data["orchards"]) == len(model.orchards)
    assert len(data["orchard_trees"]) == len(model.orchard_trees)


def test_wheat_fields_are_two_to_three_times_an_orchard():
    import statistics

    models = [Model(size=15, seed=seed, orchards=True, fields=True)
              for seed in SEEDS]
    fields = [abs(p.square) for m in models for p in m.fields]
    orchards = [abs(p.square) for m in models for p in m.orchards]
    ratio = statistics.median(fields) / statistics.median(orchards)
    assert 2 <= ratio <= 3


def test_farmland_is_labelled_wheat_fields():
    model = Model(size=15, seed=7, fields=True, orchards=False)
    assert any(p.ward.label == "Wheat fields" for p in model.patches)
