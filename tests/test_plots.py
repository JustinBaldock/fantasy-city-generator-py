import random

import pytest

from citygen import export, plots
from citygen.editing import CityEditor
from citygen.geometry import Point, Polygon
from citygen.layers import PALETTES, build_layers
from citygen.model import Model
from citygen.plots import Plot
from citygen.wards import AdministrationWard, Castle, Farm, Market, MilitaryWard

PALETTE = PALETTES["Default"]
OPTIONS = [dict(size=9, seed=3), dict(size=15, seed=7),
           dict(size=24, seed=21, coast=True, river=True),
           dict(size=15, seed=5, walls=True, citadel=True, temple=True)]


def rect(left, top, right, bottom):
    return Polygon([Point(left, top), Point(right, top), Point(right, bottom),
                    Point(left, bottom)])


def is_rectangle(building):
    if len(building) != 4:
        return False
    for i in range(4):
        one = building[i].subtract(building[i - 1])
        other = building[(i + 1) % 4].subtract(building[i])
        if abs(one.dot(other)) > 1e-6:
            return False
    return True


def within(polygon, v):
    """Inside the polygon, or on its edge, give or take rounding."""
    return polygon.contains_point(v) or any(
        plots._to_segment(v.x, v.y, a, b) < 1e-6 for a, b in polygon.edges())


def flat(points):
    return [c for p in points for c in p]


def plots_in(model):
    return [(patch.ward, plot) for patch in model.patches
            for plot in patch.ward.geometry if isinstance(plot, Plot)]


def test_a_house_stands_at_the_street_front_with_its_garden_behind():
    block = rect(0, 0, 30, 30)
    plot = rect(10, 0, 16, 14)  # Only its top edge is on the street.
    chooser = random.Random(1)
    for _ in range(30):
        house = plots.burgage(plot, block, [plot], chooser).house
        assert is_rectangle(house)
        assert min(v.y for v in house) == pytest.approx(plots.FRONT_GAP)
        assert max(v.y for v in house) <= 14 * plots.MAX_HOUSE_DEPTH + 0.5
        assert all(plot.contains_point(v) for v in house)


def test_a_house_away_from_the_street_faces_its_lane():
    block = rect(0, 0, 40, 40)
    plot = rect(10, 10, 16, 24)
    # Neighbours on three sides, and a lane down the right-hand side.
    neighbours = [plot, rect(4, 10, 10, 24), rect(10, 4, 16, 10),
                  rect(10, 24, 16, 30)]
    chooser = random.Random(1)
    for _ in range(20):
        house = plots.burgage(plot, block, neighbours, chooser).house
        assert max(v.x for v in house) == pytest.approx(16 - plots.FRONT_GAP)


def test_a_cramped_plot_gets_a_cottage_that_fills_it():
    block = rect(0, 0, 30, 30)
    plot = rect(10, 0, 13, 3)
    built = plots.burgage(plot, block, [plot], random.Random(1))
    assert is_rectangle(built.house)
    assert all(plot.contains_point(v) for v in built.house)


def test_a_sliver_gets_nothing():
    block = rect(0, 0, 30, 30)
    sliver = rect(10, 0, 30, 0.4)
    assert plots.burgage(sliver, block, [sliver], random.Random(1)) is None


@pytest.mark.parametrize("options", OPTIONS)
def test_homes_are_burgage_plots_unless_gnomes_are_asked_for(options):
    model = Model(**options)
    for patch in model.patches:
        ward = patch.ward
        # Wards on the outskirts can be thinned out to nothing.
        if ward.homes or isinstance(ward, (AdministrationWard, MilitaryWard)):
            for plot in ward.geometry:
                assert isinstance(plot, Plot)
                assert is_rectangle(plot.house)
        elif isinstance(ward, (Castle, Market, Farm)):
            assert not any(isinstance(b, Plot) for b in ward.geometry)


@pytest.mark.parametrize("options", OPTIONS)
def test_houses_stay_inside_their_plots_and_plots_in_their_blocks(options):
    model = Model(**options)
    for ward, plot in plots_in(model):
        block = ward.get_city_block()
        assert all(within(block, v) for v in plot)
        assert all(within(plot, v) for v in plot.house)
        assert plot.house.square < plot.square


def test_most_houses_front_a_street_or_lane():
    """A cottage filling a cramped plot is the only house set back."""
    at_front = total = 0
    for seed in range(1, 6):
        for ward, plot in plots_in(Model(size=15, seed=seed)):
            if not ward.homes:
                continue
            total += 1
            at_front += any(plots.clearance(plot, v.x, v.y)
                            < plots.FRONT_GAP + 0.01 for v in plot.house)
    assert at_front / total > 0.75


@pytest.mark.parametrize("options", OPTIONS)
def test_both_kinds_of_home_have_plots(options):
    for style in ("burgage", "gnome"):
        model = Model(home_style=style, **options)
        assert plots_in(model)


def test_every_plot_is_drawn_with_its_house():
    model = Model(size=15, seed=7)
    layers = {layer.name: layer for layer in build_layers(model, PALETTE)}
    plotted = [plot for _, plot in plots_in(model)]
    assert len(layers["Plots"].polygons) == len(plotted)
    drawn = layers["Buildings"].polygons
    for plot in plotted:
        assert [(v.x, v.y) for v in plot.house] in drawn
        assert [(v.x, v.y) for v in plot] not in drawn


def test_plots_show_in_the_svg():
    assert 'id="plots"' in export.city_to_svg(Model(size=9, seed=3), PALETTE)


def test_the_json_gives_each_building_its_plot():
    model = Model(size=15, seed=7)
    data = export.city_to_dict(model)
    for patch, ward in zip(model.patches, data["wards"]):
        assert len(ward["plots"]) == len(ward["buildings"])
        for polygon, border, building in zip(
                patch.ward.geometry, ward["plots"], ward["buildings"]):
            if isinstance(polygon, Plot):
                assert len(border) == len(polygon)
                assert len(building) == len(polygon.house)
            else:
                assert border is None


def plot_in_editor(editor):
    return next(b for b in sorted(editor.buildings,
                                  key=lambda b: (b.cx * b.cx + b.cy * b.cy))
                if isinstance(b.polygon, Plot))


def test_clicking_the_garden_selects_the_plot():
    editor = CityEditor(Model(size=15, seed=7))
    building = plot_in_editor(editor)
    plot = building.polygon
    corners = sorted(plot, key=lambda v: min(
        (v.x - h.x) ** 2 + (v.y - h.y) ** 2 for h in plot.house))
    far = corners[-1]
    centre = plot.centroid
    in_garden = Point(far.x + (centre.x - far.x) * 0.1,
                      far.y + (centre.y - far.y) * 0.1)
    assert not plot.house.contains_point(in_garden)
    assert editor.building_at(in_garden) is building


def test_a_house_moves_with_its_plot_and_comes_back_on_undo():
    editor = CityEditor(Model(size=15, seed=7))
    building = plot_in_editor(editor)
    house = building.polygon.house
    before = [(v.x, v.y) for v in house]
    x, y = building.center()

    assert editor.begin_move(building)
    editor.drag_to(building, 2.0, 1.0)
    editor.end_move()

    assert building.polygon.house is house
    dx, dy = building.cx - x, building.cy - y
    assert (dx, dy) != (0, 0)
    assert flat((v.x, v.y) for v in house) == pytest.approx(
        flat((px + dx, py + dy) for px, py in before))

    assert editor.undo()
    assert flat((v.x, v.y) for v in house) == pytest.approx(flat(before))


def test_pushed_plots_carry_their_houses():
    editor = CityEditor(Model(size=15, seed=7))
    homes = {b: [(v.x, v.y) for v in b.polygon.house]
             for b in editor.buildings if isinstance(b.polygon, Plot)}
    starts = {b: b.center() for b in homes}
    building = plot_in_editor(editor)
    assert editor.begin_move(building)
    for step in range(1, 11):
        editor.drag_to(building, step * 0.8, 0.0)
    editor.end_move()

    pushed = 0
    for other, corners in homes.items():
        dx = other.cx - starts[other][0]
        dy = other.cy - starts[other][1]
        if other is not building and (dx, dy) != (0, 0):
            pushed += 1
        assert flat((v.x, v.y) for v in other.polygon.house) == pytest.approx(
            flat((px + dx, py + dy) for px, py in corners))
    assert pushed


@pytest.mark.parametrize("options", OPTIONS)
def test_classic_houses_fill_their_plots_with_no_borders(options):
    model = Model(home_style="classic", **options)
    assert not plots_in(model)
    layers = {layer.name: layer for layer in build_layers(model, PALETTE)}
    assert layers["Plots"].polygons == []
    assert layers["Buildings"].polygons
    assert all(plot is None for ward in export.city_to_dict(model)["wards"]
               for plot in ward["plots"])


@pytest.mark.parametrize("options", OPTIONS)
def test_every_home_style_keeps_the_same_streets_walls_and_water(options):
    maps = [export.city_to_dict(Model(home_style=style, **options))
            for style in ("burgage", "gnome", "classic")]
    for key in ("streets", "roads", "wall", "castle_wall", "river", "shore"):
        assert maps[0][key] == maps[1][key] == maps[2][key]
    assert ([w["shape"] for w in maps[0]["wards"]]
            == [w["shape"] for w in maps[2]["wards"]])


def test_classic_plots_are_smaller_than_burgage_plots():
    def homes(style):
        return sum(len(p.ward.geometry) for p in
                   Model(home_style=style, size=15, seed=7).patches
                   if p.ward.homes)

    assert homes("classic") > homes("burgage")


def test_an_unknown_home_style_is_refused():
    with pytest.raises(ValueError):
        Model(size=9, seed=3, home_style="elvish")


def trees_of(model):
    return [(plot, tree) for _, plot in plots_in(model) for tree in plot.trees]


@pytest.mark.parametrize("style", ["burgage", "gnome"])
def test_bigger_gardens_have_trees_clear_of_the_house(style):
    model = Model(home_style=style, size=15, seed=7)
    planted = trees_of(model)
    assert planted
    for plot, (x, y, radius) in planted:
        assert plots.clearance(plot, x, y) >= radius
        assert not plot.house.contains_point(Point(x, y))
        assert plots._to_outline(plot.house, x, y) >= radius
        garden = abs(plot.square) - abs(plot.house.square)
        assert garden >= plots.MIN_GARDEN


def test_small_gardens_have_no_trees():
    model = Model(size=15, seed=7)
    for _, plot in plots_in(model):
        if abs(plot.square) - abs(plot.house.square) < plots.MIN_GARDEN:
            assert not plot.trees


def test_classic_maps_have_no_garden_trees():
    model = Model(home_style="classic", size=15, seed=7)
    layer = next(x for x in build_layers(model, PALETTE)
                 if x.name == "Garden trees")
    assert layer.circles == []


def test_garden_trees_are_drawn_and_exported():
    model = Model(size=15, seed=7)
    planted = [tree for _, tree in trees_of(model)]
    layer = next(x for x in build_layers(model, PALETTE)
                 if x.name == "Garden trees")
    assert layer.circles == planted
    exported = [tree for ward in export.city_to_dict(model)["wards"]
                for tree in ward["garden_trees"]]
    assert len(exported) == len(planted)
    assert 'id="garden-trees"' in export.city_to_svg(model, PALETTE)


def test_trees_move_with_their_plot_and_come_back_on_undo():
    editor = CityEditor(Model(size=15, seed=7))
    building = next(b for b in sorted(editor.buildings,
                                      key=lambda b: b.cx * b.cx + b.cy * b.cy)
                    if isinstance(b.polygon, Plot) and b.polygon.trees)
    before = list(building.polygon.trees)
    x, y = building.center()

    assert editor.begin_move(building)
    editor.drag_to(building, 2.0, 1.0)
    editor.end_move()

    dx, dy = building.cx - x, building.cy - y
    assert (dx, dy) != (0, 0)
    assert flat(building.polygon.trees) == pytest.approx(
        flat((tx + dx, ty + dy, r) for tx, ty, r in before))

    assert editor.undo()
    assert flat(building.polygon.trees) == pytest.approx(flat(before))


def greens_of(model):
    from citygen.plots import Green
    return [g for p in model.patches for g in p.ward.geometry
            if isinstance(g, Green)]


@pytest.mark.parametrize("style", ["burgage", "gnome", "classic"])
def test_greens_have_trees_round_their_edges(style):
    model = Model(size=24, seed=5, greens=True, home_style=style)
    greens = greens_of(model)
    assert greens
    for green in greens:
        assert len(green.trees) >= 5
        for x, y, radius in green.trees:
            gap = plots.clearance(green, x, y)
            assert gap >= radius
            # Near the edge, not out in the middle.
            assert gap <= plots.GREEN_TREE_INSET + plots.GREEN_TREE_JITTER * 2


def test_green_trees_are_drawn():
    model = Model(size=24, seed=5, greens=True)
    layer = next(x for x in build_layers(model, PALETTE)
                 if x.name == "Green trees")
    assert layer.circles == [t for g in greens_of(model) for t in g.trees]


def test_green_trees_move_with_their_green():
    model = Model(size=24, seed=5, greens=True)
    editor = CityEditor(model)
    green = max(greens_of(model), key=lambda g: abs(g.square))
    building = next(b for b in editor.buildings if b.polygon is green)
    before = list(green.trees)
    x, y = building.center()
    assert editor.begin_move(building)
    editor.drag_to(building, 1.5, 0.5)
    editor.end_move()
    dx, dy = building.cx - x, building.cy - y
    assert (dx, dy) != (0, 0)
    assert flat(green.trees) == pytest.approx(
        flat((tx + dx, ty + dy, r) for tx, ty, r in before))
    assert editor.undo()
    assert flat(green.trees) == pytest.approx(flat(before))
