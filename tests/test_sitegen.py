import json
import math

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from citygen.layers import PALETTES
from sitegen import __version__, files
from sitegen.drawing import LINE_WIDTHS, build_layers, wood_trees
from sitegen.editing import SiteEditor, new_piece
from sitegen.generate import HOME_STYLES, KINDS, generate
from sitegen.site import KINDS as PIECE_KINDS
from sitegen.site import Piece, Site, inside, to_line, to_segment

PALETTE = PALETTES["Default"]
SEEDS = range(1, 16)


def crosses(a, b):
    """Whether two outlines overlap, by their edges or one inside the other."""
    def edges(outline):
        return list(zip(outline, outline[1:] + outline[:1]))

    def cut(p, q, r, s):
        def side(a, b, c):
            return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        return (side(p, q, r) * side(p, q, s) < 0
                and side(r, s, p) * side(r, s, q) < 0)

    if any(cut(p, q, r, s) for p, q in edges(a) for r, s in edges(b)):
        return True
    return inside(b, *a[0]) or inside(a, *b[0])


def of_kind(site, *kinds):
    return [piece for piece in site.pieces if piece.kind in kinds]


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("homes", HOME_STYLES)
def test_the_same_seed_gives_the_same_location(kind, homes):
    first = files.site_to_dict(generate(kind, 7, homes))
    assert first == files.site_to_dict(generate(kind, 7, homes))
    assert first != files.site_to_dict(generate(kind, 8, homes))


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("homes", HOME_STYLES)
def test_every_location_has_a_road_and_buildings_in_their_yards(kind, homes):
    for seed in SEEDS:
        site = generate(kind, seed, homes)
        assert of_kind(site, "road")
        buildings = of_kind(site, "building", "gnome_home")
        assert len(buildings) >= 2
        yards = [yard.world() for yard in of_kind(site, "yard")]
        for building in buildings:
            assert any(all(inside(yard, x, y) for x, y in building.world())
                       for yard in yards), (seed, building.label)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("homes", HOME_STYLES)
def test_buildings_stand_clear_of_each_other_and_the_roads(kind, homes):
    for seed in SEEDS:
        site = generate(kind, seed, homes)
        buildings = of_kind(site, "building", "gnome_home")
        for i, a in enumerate(buildings):
            for b in buildings[i + 1:]:
                assert not crosses(a.world(), b.world()), (
                    seed, a.label, b.label)
        for road in of_kind(site, "road"):
            line = road.world()
            for building in buildings:
                assert all(to_line(x, y, line) > LINE_WIDTHS["road"] / 2
                           for x, y in building.world()), (seed, building.label)


def test_a_farm_has_its_farmyard_fields_and_orchard():
    for seed in SEEDS:
        site = generate("farm", seed)
        labels = {piece.label for piece in site.pieces}
        assert {"Farmhouse", "Barn", "Byre", "Farmyard", "Orchard"} <= labels
        assert of_kind(site, "field")


def test_a_gnome_farm_has_a_gnome_farmhouse():
    site = generate("farm", 3, "gnome")
    house = next(p for p in site.pieces if p.label == "Farmhouse")
    assert house.kind == "gnome_home" and house.joins


def test_a_toll_house_has_its_gate_across_the_road():
    rivers = 0
    for seed in SEEDS:
        site = generate("toll_house", seed)
        gate = next(p for p in site.pieces if p.label == "Toll gate")
        road = of_kind(site, "road")[0].world()
        middle = [sum(v) / 2 for v in zip(*gate.world())]
        assert to_line(*middle, road) < 0.5
        if of_kind(site, "river"):
            rivers += 1
            assert of_kind(site, "bridge")
    assert 0 < rivers < len(SEEDS)


def test_a_roadhouse_has_an_inn_and_a_side_road():
    for seed in SEEDS:
        site = generate("roadhouse", seed)
        labels = {piece.label for piece in site.pieces}
        assert {"Inn", "Stables", "Coach house", "Inn yard"} <= labels
        assert len(of_kind(site, "road")) == 2


def test_unknown_kinds_are_refused():
    with pytest.raises(ValueError):
        generate("castle", 1)
    with pytest.raises(ValueError):
        generate("farm", 1, "tall")
    with pytest.raises(ValueError):
        Piece("dragon")


# Drawing.

def test_the_layers_use_the_city_maps_styles():
    names = {layer.name for layer in build_layers(generate("farm", 1),
                                                  PALETTE)}
    assert {"Furrows", "Forest", "Orchards", "Plots", "Road edges", "Roads",
            "Buildings"} <= names


def test_a_woods_trees_keep_to_it_and_follow_it():
    wood = new_piece("wood", seed=4)
    trees = wood_trees(wood)
    assert len(trees) > 5
    outline = wood.world()
    assert all(inside(outline, x, y) for x, y, _ in trees)
    SiteEditor.move([wood], 10, 0)
    moved = [v for x, y, r in wood_trees(wood) for v in (x - 10, y, r)]
    assert moved == pytest.approx([v for tree in trees for v in tree])


def test_every_kind_of_piece_draws():
    site = Site(pieces=[new_piece(kind, seed=3) for kind in PIECE_KINDS])
    layers = build_layers(site, PALETTE)
    drawn = sum(len(layer.polygons) + len(layer.polylines)
                + len(layer.circles) for layer in layers)
    assert drawn >= len(PIECE_KINDS)


# Editing.

def test_pieces_keep_their_shape_when_moved_and_turned():
    building = new_piece("building", 3, 4)
    before = building.world()
    SiteEditor.move([building], 2, -1)
    assert [v for point in building.world() for v in point] == pytest.approx(
        [v for x, y in before for v in (x + 2, y - 1)])
    SiteEditor.rotate([building], math.radians(30), 0, 0)
    after = building.world()
    sides = [math.dist(a, b) for a, b in zip(before, before[1:])]
    assert [math.dist(a, b) for a, b in zip(after, after[1:])] == (
        pytest.approx(sides))


def test_turning_several_pieces_turns_them_together():
    a = new_piece("building", 0, 0)
    b = new_piece("tree", 10, 0)
    gap = math.dist((a.x, a.y), (b.x, b.y))
    SiteEditor.rotate([a, b], math.pi / 2, 5, 0)
    assert (a.x, a.y) == pytest.approx((5, -5))
    assert (b.x, b.y) == pytest.approx((5, 5))
    assert math.dist((a.x, a.y), (b.x, b.y)) == pytest.approx(gap)
    assert a.angle == pytest.approx(math.pi / 2)


def test_resizing_keeps_the_far_side_still():
    piece = new_piece("field")
    SiteEditor.rotate([piece], math.radians(40), 0, 0)
    original = piece.copy()
    left, top, right, bottom = original.local_box()
    far = original.to_map(left, 0)
    target = original.to_map(right + 6, 0)
    SiteEditor.resize(piece, original, (1, 0), *target)
    new_left, new_top, new_right, new_bottom = piece.local_box()
    assert new_left == pytest.approx(left)
    assert new_right == pytest.approx(right + 6)
    assert (new_top, new_bottom) == pytest.approx((top, bottom))
    assert piece.to_map(new_left, 0) == pytest.approx(far)


def test_resizing_has_a_least_size():
    piece = new_piece("building")
    original = piece.copy()
    left, _, right, _ = original.local_box()
    SiteEditor.resize(piece, original, (1, 0), *original.to_map(left - 9, 0))
    new_left, _, new_right, _ = piece.local_box()
    assert new_right - new_left == pytest.approx(0.4)


def test_resizing_a_tree_changes_its_radius():
    tree = new_piece("tree", 5, 5)
    SiteEditor.resize(tree, tree.copy(), (1, 1), 8, 9)
    assert tree.radius == pytest.approx(4)


def test_corners_can_be_moved_added_and_removed():
    pond = new_piece("pond", 2, 2)
    count = len(pond.points)
    SiteEditor.move_point(pond, 0, 20, 20)
    assert pond.world()[0] == pytest.approx((20, 20))
    assert SiteEditor.insert_point(pond, 1, 10, 10)
    assert len(pond.points) == count + 1
    assert pond.world()[1] == pytest.approx((10, 10))
    while len(pond.points) > 3:
        assert SiteEditor.remove_point(pond, 0)
    assert not SiteEditor.remove_point(pond, 0)
    road = new_piece("road")
    while len(road.points) > 2:
        SiteEditor.remove_point(road, 1)
    assert not SiteEditor.remove_point(road, 0)


def test_a_gnome_homes_room_walls_follow_added_corners():
    home = new_piece("gnome_home")
    walls = [(home.points[a], home.points[b]) for a, b in home.joins]
    SiteEditor.insert_point(home, 0, 30, 30)
    assert [(home.points[a], home.points[b]) for a, b in home.joins] == walls


def test_picking_finds_what_is_on_top():
    site = Site(pieces=[new_piece("yard"), new_piece("building"),
                        new_piece("road", 0, 30), new_piece("tree", 20, 0)])
    editor = SiteEditor(site)
    assert editor.piece_at(0, 0).kind == "building"
    assert editor.piece_at(5, 3).kind == "yard"
    assert editor.piece_at(0, 30.9).kind == "road"
    assert editor.piece_at(20.5, 0.5).kind == "tree"
    assert editor.piece_at(50, 50) is None
    assert {p.kind for p in editor.pieces_in(-7, -5, 7, 5)} == {
        "yard", "building"}


def test_added_pieces_go_where_asked_and_can_be_deleted():
    site = Site()
    editor = SiteEditor(site)
    wood = editor.add("wood", 4, 5)
    tree = editor.add("tree", 1, 1)
    assert (wood.x, wood.y) == (4, 5) and wood.seed
    editor.delete([wood])
    assert site.pieces == [tree]


def test_segment_and_line_distances():
    assert to_segment(0, 5, (-1, 0), (1, 0)) == pytest.approx(5)
    assert to_segment(4, 0, (-1, 0), (1, 0)) == pytest.approx(3)
    assert to_line(0, 2, [(-5, 0), (0, 0), (0, 10)]) == pytest.approx(0)


# Files.

def through_file(site):
    return json.loads(json.dumps(files.site_to_dict(site)))


@pytest.mark.parametrize("kind", KINDS)
def test_a_saved_location_opens_as_it_was(kind):
    site = generate(kind, 5, "gnome")
    editor = SiteEditor(site)
    SiteEditor.rotate(site.pieces[:4], 0.3, 1, 1)
    editor.add("pond", 3, 3)
    data = through_file(site)
    again = files.site_from_dict(data)
    assert files.site_to_dict(again) == data
    assert len(again.pieces) == len(site.pieces)


def test_the_file_says_which_version_saved_it(tmp_path):
    path = tmp_path / "farm.json"
    files.save_json(generate("farm", 2), path)
    site, version = files.load_json(path)
    assert version == __version__ and site.kind == "farm"


def test_other_files_are_refused(tmp_path):
    path = tmp_path / "x.json"
    for text in ("not json", '{"format": "city"}',
                 '{"format": "fantasy-location", "pieces": [{"kind": "x"}]}',
                 '{"format": "fantasy-location", "pieces": [{}]}',
                 '{"format": "fantasy-location", "format_version": 99,'
                 ' "pieces": []}'):
        path.write_text(text)
        with pytest.raises(files.OpenError):
            files.load_json(path)


def test_svg_and_png_exports(tmp_path, qapp):
    site = generate("roadhouse", 4)
    svg = files.site_to_svg(site, PALETTE)
    assert svg.startswith("<?xml") and 'id="buildings"' in svg
    assert "Roadhouse, seed 4" in svg
    path = tmp_path / "inn.png"
    files.save_png(site, PALETTE, path, 600)
    assert path.stat().st_size > 1000


# The window.

@pytest.fixture
def window(qapp, monkeypatch):
    from sitegen.app import MainWindow
    asked = []
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *args: asked.append(args[2])
                        or QMessageBox.StandardButton.Yes)
    window = MainWindow()
    window.asked = asked
    window.resize(1000, 800)
    window.show()
    window.seed_box.setValue(11)
    QApplication.processEvents()
    yield window
    window.close()


def at(view, x, y):
    return view.window_point(x, y).toPoint()


def test_the_window_makes_each_kind(window):
    for index in range(window.kind_box.count()):
        window.kind_box.setCurrentIndex(index)
        assert window.site.kind == window.kind_box.currentData()
        assert window.view.prepared


def test_clicking_selects_and_shift_click_adds(window):
    view = window.view
    a, b = [p for p in window.site.pieces if p.kind == "building"][:2]
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=at(view, a.x, a.y))
    assert view.selection == [a]
    QTest.mouseClick(view, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.ShiftModifier, at(view, b.x, b.y))
    assert view.selection == [a, b]
    assert "2 pieces" in window.selection_label.text()


def test_dragging_moves_the_selection(window):
    view = window.view
    building = next(p for p in window.site.pieces if p.kind == "building")
    start = at(view, building.x, building.y)
    x, y = building.x, building.y
    QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(view, start + QPoint(30, 0))
    QTest.mouseMove(view, start + QPoint(60, 20))
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton,
                       pos=start + QPoint(60, 20))
    scale = view._scale()
    assert building.x - x == pytest.approx(60 / scale, abs=0.05)
    assert building.y - y == pytest.approx(20 / scale, abs=0.05)
    assert window.changed


def test_dragging_open_ground_selects_a_box(window):
    view = window.view
    window.site.pieces[:] = [new_piece("tree", 0, 0), new_piece("well", 5, 3),
                             new_piece("tree", 30, 30)]
    view.refresh()
    corner = at(view, -5, -5)
    QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=corner)
    QTest.mouseMove(view, corner + QPoint(160, 160))
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton,
                       pos=corner + QPoint(160, 160))
    assert {p.kind for p in view.selection} == {"tree", "well"}


def test_the_turn_handle_turns_the_selection(window):
    view = window.view
    building = next(p for p in window.site.pieces if p.kind == "building")
    view.select([building])
    angle = building.angle
    handle = view.turn_handle().toPoint()
    left, top, right, bottom = view.selection_box()
    centre = view.window_point((left + right) / 2, (top + bottom) / 2)
    # Round to the right of the centre is a quarter turn clockwise.
    target = QPointF(centre.x() + (centre.y() - handle.y()), centre.y())
    QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=handle)
    QTest.mouseMove(view, target.toPoint())
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton, pos=target.toPoint())
    turned = (building.angle - angle) % (2 * math.pi)
    assert turned == pytest.approx(math.pi / 2, abs=0.05)


def test_a_resize_handle_stretches_a_piece(window):
    view = window.view
    piece = window.view.add_piece("field")
    width = piece.local_box()[2] - piece.local_box()[0]
    handle = view.window_point(*view.resize_handles()[1, 0]).toPoint()
    QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=handle)
    QTest.mouseMove(view, handle + QPoint(40, 0))
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton,
                       pos=handle + QPoint(40, 0))
    stretched = piece.local_box()[2] - piece.local_box()[0]
    assert stretched > width


def test_reshape_shows_corners_to_drag(window):
    view = window.view
    piece = view.add_piece("yard")
    window.reshape_button.setChecked(True)
    assert view.shows_points() and not view.resize_handles()
    corner = view.window_point(*piece.world()[0]).toPoint()
    QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=corner)
    QTest.mouseMove(view, corner + QPoint(-30, -30))
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton,
                       pos=corner + QPoint(-30, -30))
    moved = view.window_point(*piece.world()[0])
    assert (moved.x(), moved.y()) == pytest.approx(
        (corner.x() - 30, corner.y() - 30), abs=1)
    view.select([])
    assert not window.reshape_button.isChecked()


def test_buttons_add_turn_and_delete(window):
    count = len(window.site.pieces)
    window.add_buttons["gnome_home"].click()
    piece = window.view.selection[0]
    assert piece.kind == "gnome_home" and len(window.site.pieces) == count + 1
    window.turn_right_button.click()
    assert math.degrees(piece.angle) == pytest.approx(15)
    window.delete_button.click()
    assert len(window.site.pieces) == count
    assert not window.delete_button.isEnabled()


def test_typing_in_the_seed_box_doesnt_delete(window):
    window.view.select(window.site.pieces[:1])
    count = len(window.site.pieces)
    window.seed_box.setFocus()
    QTest.keyClick(window.seed_box, Qt.Key.Key_Backspace)
    assert len(window.site.pieces) == count


def test_a_new_location_asks_before_losing_changes(window):
    window.add_buttons["tree"].click()
    assert window.changed
    window.new_location()
    assert window.asked and not window.changed


def test_save_and_open_again(window, tmp_path):
    window.add_buttons["pond"].click()
    path = tmp_path / "farm.json"
    files.save_json(window.site, path)
    saved = files.site_to_dict(window.site)
    window.changed = False
    window.kind_box.setCurrentIndex(1)
    assert window.open_json(str(path))
    assert files.site_to_dict(window.site) == saved
    assert window.kind_box.currentData() == "farm"
    assert window.seed_box.value() == 11


def test_the_side_panel_shows_every_button_in_full(window):
    panel = window.side_panel
    for button in list(window.add_buttons.values()) + [
            window.turn_left_button, window.turn_right_button,
            window.reshape_button, window.delete_button]:
        right = button.mapTo(panel, QPoint(button.width(), 0)).x()
        assert right <= panel.width()
        assert button.width() >= button.minimumSizeHint().width()


# Turning the map, and the compass.

def test_the_map_and_compass_turn_15_degrees_a_press(window):
    window.turn_map(15)
    window.turn_map(15)
    window.turn_compass(-15)
    assert window.view.rotation == 30 and window.view.north == 345
    assert "30" in window.turn_label.text()
    assert "345" in window.north_label.text()
    window.compass_action.setChecked(False)
    assert not window.view.show_compass


def test_a_turned_map_still_picks_the_right_spot(window):
    view = window.view
    window.turn_map(45)
    for x, y in ((10, 0), (-7, 22), (31, -4)):
        back = view.spot(view.window_point(x, y))
        assert back == pytest.approx((x, y))


def test_a_box_on_a_turned_map_selects_what_it_covers(window):
    view = window.view
    window.site.pieces[:] = [new_piece("tree", 0, 0), new_piece("well", 4, 0),
                             new_piece("tree", 0, 30)]
    view.refresh()
    window.turn_map(90)
    # On screen the trees at 0, 0 and 4, 0 are one above the other.
    top = view.window_point(0, 0)
    corner = QPoint(round(top.x()) - 40, round(top.y()) - 20)
    QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=corner)
    QTest.mouseMove(view, corner + QPoint(80, 90))
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton,
                       pos=corner + QPoint(80, 90))
    assert {p.kind for p in view.selection} == {"tree", "well"}
    assert len(view.selection) == 2


def test_arrow_keys_move_the_selection_up_the_screen_on_a_turned_map(window):
    view = window.view
    piece = window.view.add_piece("tree")
    window.turn_map(90)
    before = view.window_point(piece.x, piece.y)
    view.nudge(0, -1)
    after = view.window_point(piece.x, piece.y)
    assert after.y() < before.y()
    assert after.x() == pytest.approx(before.x(), abs=1e-6)


def test_the_turn_handle_sits_above_the_selection_on_screen(window):
    view = window.view
    piece = view.add_piece("building")
    window.turn_map(60)
    handle = view.turn_handle()
    corners = [view.window_point(x, y) for x, y in piece.box_corners()]
    assert handle.y() < min(p.y() for p in corners)


def test_exports_turn_and_show_the_compass(tmp_path, qapp):
    site = generate("farm", 2)
    svg = files.site_to_svg(site, PALETTE, rotation=30, compass=15)
    assert 'transform="rotate(30)"' in svg and 'id="compass"' in svg
    assert 'id="compass"' not in files.site_to_svg(site, PALETTE)
    path = tmp_path / "farm.png"
    files.save_png(site, PALETTE, path, 400, rotation=30, compass=15)
    assert path.stat().st_size > 1000


def test_the_view_is_saved_and_opened_with_the_location(window, tmp_path):
    window.turn_map(45)
    window.turn_compass(30)
    window.compass_action.setChecked(False)
    path = tmp_path / "inn.json"
    files.save_json(window.site, path, window.view_settings())
    assert json.loads(path.read_text())["view"]["rotation"] == 45
    window.turn_map(-45)
    window.turn_compass(-30)
    window.compass_action.setChecked(True)
    window.changed = False
    assert window.open_json(str(path))
    assert window.view.rotation == 45 and window.view.north == 30
    assert not window.view.show_compass
