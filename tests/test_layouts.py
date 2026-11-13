"""The grid and circular town plans, and turning the map and compass."""

import json
import math

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from citygen import export, layers, qt_render
from citygen.export import city_from_dict, city_to_dict, city_to_svg
from citygen.layers import PALETTES, compass_rose
from citygen.model import Model

PALETTE = PALETTES["Default"]
PLANNED = ("grid", "radial")


@pytest.mark.parametrize("layout", PLANNED)
@pytest.mark.parametrize("size", [1, 4, 15, 40])
def test_planned_towns_build_at_every_size(layout, size):
    for seed in range(1, 4):
        for options in (dict(), dict(walls=True, citadel=True, river=True,
                                     coast=True, fields=True)):
            model = Model(size, seed, layout=layout, **options)
            # A river can split a ward in two along its course.
            assert len(model.inner) >= size
            assert model.layout == layout


def test_unknown_layouts_are_refused():
    with pytest.raises(ValueError):
        Model(9, 1, layout="spiral")


def test_a_grid_town_is_square_blocks_with_straight_streets():
    model = Model(24, 3, layout="grid", walls=True, river=False, coast=False)
    town = [p for p in model.patches if p.within_city and p is not
            model.citadel]
    assert all(len(p.shape) == 4 for p in town)
    for street in model.streets:
        for a, b in zip(street, street[1:]):
            # Along the grid, east and west or north and south.
            assert abs(a.x - b.x) < 1e-9 or abs(a.y - b.y) < 1e-9


def test_a_grid_town_has_avenues_through_its_centre():
    model = Model(24, 5, layout="grid", walls=False, river=False, coast=False)
    centre = model.center
    through = [s for s in model.streets if any(v is centre for v in s)]
    assert len(through) >= 2


def test_a_grid_towns_gates_lead_straight_out():
    for seed in range(1, 6):
        model = Model(24, seed, layout="grid", walls=True, river=False,
                      coast=False)
        for gate in model.wall.gates:
            outside = [p for p in model.patch_by_vertex(gate)
                       if p not in model.wall.patches]
            assert len(outside) >= 2


def test_a_circular_town_has_a_hub_rings_and_spokes():
    model = Model(24, 3, layout="radial", walls=True, river=False,
                  coast=False)
    hub = model.inner[0]
    assert len(hub.shape) >= 8
    radius = hub.shape[0].length
    assert all(abs(v.length - radius) < 1e-6 for v in hub.shape)
    rings = [s for s in model.streets if len(s) > 4 and abs(
        max(v.length for v in s) - min(v.length for v in s)) < 1e-6]
    assert rings, "no ring road"
    spokes = [s for s in model.streets if len(s) >= 2 and all(
        abs(math.remainder(math.atan2(v.y, v.x) - math.atan2(s[0].y, s[0].x),
                           2 * math.pi)) < 1e-6 for v in s)
              and s[-1].length > s[0].length + 1]
    assert spokes, "no spoke"


def test_planned_towns_come_back_from_a_file():
    for layout in PLANNED:
        model = Model(15, 4, layout=layout, walls=True)
        data = json.loads(json.dumps(city_to_dict(model)))
        again, differences = city_from_dict(data)
        assert differences == [] and again.layout == layout


def test_the_compass_rose_turns_with_its_bearing():
    shapes, letters = compass_rose(0)
    north = next((x, y) for letter, x, y in letters if letter == "N")
    assert north[0] == pytest.approx(0) and north[1] < 0
    _, letters = compass_rose(90)
    north = next((x, y) for letter, x, y in letters if letter == "N")
    assert north[0] > 0 and north[1] == pytest.approx(0, abs=1e-9)
    assert len(shapes) == 16


def test_svg_exports_turn_the_map_and_show_the_compass():
    model = Model(9, 3)
    plain = city_to_svg(model, PALETTE)
    assert 'id="compass"' not in plain and "rotate(" not in plain
    turned = city_to_svg(model, PALETTE, rotation=90, compass=30)
    assert 'transform="rotate(90)"' in turned and 'id="compass"' in turned


def test_png_exports_turn_the_map(tmp_path, qapp):
    from PySide6.QtGui import QImage, QTransform

    model = Model(9, 3)
    straight = tmp_path / "straight.png"
    turned = tmp_path / "turned.png"
    qt_render.save_png(model, PALETTE, straight, 300, False)
    qt_render.save_png(model, PALETTE, turned, 300, False, rotation=90)
    a = QImage(str(straight)).transformed(QTransform().rotate(90))
    b = QImage(str(turned))
    def apart(p, q):
        return max(abs(((p >> k) & 255) - ((q >> k) & 255)) for k in (0, 8, 16))

    # Edges are smoothed a little differently when drawn turned, so only
    # count pixels that are clearly different.
    differing = sum(1 for y in range(0, 300, 5) for x in range(0, 300, 5)
                    if apart(a.pixel(x, y), b.pixel(x, y)) > 60)
    assert differing < 3600 * 0.02
    with_compass = tmp_path / "compass.png"
    qt_render.save_png(model, PALETTE, with_compass, 300, False, compass=0)
    assert QImage(str(with_compass)) != QImage(str(straight))


@pytest.fixture
def window(qapp, monkeypatch):
    from citygen.app import MainWindow

    for kind in ("information", "warning"):
        monkeypatch.setattr(QMessageBox, kind, lambda *args: None)
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *args: QMessageBox.StandardButton.Yes)
    window = MainWindow()
    window.resize(1000, 800)
    window.show()
    window._set_seed(7)
    window.build()
    QApplication.processEvents()
    yield window
    window.close()


def test_the_layout_box_builds_each_plan(window):
    for index, layout in enumerate(("organic", "grid", "radial")):
        window.layout_box.setCurrentIndex(index)
        assert window.model.layout == layout


def test_turning_the_map_keeps_clicks_on_the_right_spot(window):
    from PySide6.QtCore import QPointF

    view = window.view
    window.turn_map(90)
    assert view.rotation == 90
    spot = view._transform().map(QPointF(10, 0))
    # A quarter turn clockwise takes east to south, down the screen.
    centre = view._transform().map(QPointF(0, 0))
    assert spot.y() > centre.y() and abs(spot.x() - centre.x()) < 1e-6
    back = view._spot(spot)
    assert (back.x, back.y) == pytest.approx((10, 0))
    window.turn_map(-90)
    window.turn_map(-90)
    assert view.rotation == 270


def test_the_compass_turns_on_its_own_and_with_the_map(window):
    window.turn_compass(15)
    window.turn_compass(15)
    assert window.view.north == 30
    assert "30" in window.north_label.text()
    window.turn_map(90)
    assert window.view.north == 30 and window.view.rotation == 90
    window.compass_action.setChecked(False)
    assert not window.view.show_compass


def test_the_view_is_saved_and_opened_with_the_town(window, tmp_path):
    window.turn_map(90)
    window.turn_compass(45)
    window.compass_action.setChecked(False)
    path = tmp_path / "town.json"
    export.save_json(window.model, path, window.view_settings())
    window.turn_map(-90)
    window.turn_compass(-45)
    window.compass_action.setChecked(True)
    assert window.open_json(str(path))
    assert window.view.rotation == 90 and window.view.north == 45
    assert not window.view.show_compass
