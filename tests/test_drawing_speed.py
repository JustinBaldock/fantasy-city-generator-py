"""The shortcuts that make redrawing fast while editing draw the same map."""

import math

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from citygen import layers, qt_render, streets
from citygen.editing import CityEditor
from citygen.layers import PALETTES, build_layers
from citygen.model import Model
from citygen.plots import Plot

PALETTE = PALETTES["Default"]


def dragged(model, steps=6):
    editor = CityEditor(model)
    building = min(editor.buildings, key=lambda b: math.hypot(b.cx, b.cy))
    editor.begin_move(building)
    for i in range(1, steps + 1):
        editor.drag_to(building, i * 0.6, i * 0.2)
    editor.end_move()
    return editor, building


def flattened(layer):
    if layer.groups is None:
        return layer.polygons, layer.polylines, layer.circles
    polygons, polylines, circles = [], [], []
    for _, _, p, l, c in layer.groups:
        polygons += p
        polylines += l
        circles += c
    return polygons, polylines, circles


def test_ward_by_ward_layers_hold_the_same_shapes():
    model = Model(24, 3, home_style="gnome", greens=True, temple=True,
                  citadel=True)
    dragged(model)
    plain = build_layers(model, PALETTE)
    grouped = build_layers(model, PALETTE, grouped=True)
    assert [layer.name for layer in plain] == [layer.name for layer in grouped]
    for a, b in zip(plain, grouped):
        assert flattened(a) == flattened(b), a.name


def test_editing_counts_on_the_ward_and_redraws_only_it():
    model = Model(15, 7)
    before = {id(ward): ward for ward, _, _ in layers.ward_drawings(model)}
    drawings = {ward: drawing for ward, _, drawing in
                layers.ward_drawings(model)}
    _, building = dragged(model)
    assert building.ward.edits > 0
    for ward, _, drawing in layers.ward_drawings(model):
        if ward.edits == 0:
            assert drawing is drawings[ward]
    assert len(before) == len(drawings)


def test_a_cached_redraw_matches_a_fresh_one():
    model = Model(24, 5, home_style="gnome")
    kept = {}
    qt_render.prepare(model, PALETTE, kept)
    dragged(model)
    again = qt_render.prepare(model, PALETTE, kept)
    assert qt_render.changed_area(kept) is not None
    assert not qt_render.changed_area(kept).isEmpty()
    fresh = qt_render.prepare(model, PALETTE)
    assert picture(again) == picture(fresh)


def worst_difference(a, b, step=1):
    worst = 0
    for y in range(0, a.height(), step):
        for x in range(0, a.width(), step):
            p = a.pixel(x, y)
            q = b.pixel(x, y)
            if p != q:
                worst = max(worst, max(abs(((p >> s) & 255) - ((q >> s) & 255))
                                       for s in (0, 8, 16)))
    return worst


def picture(prepared):
    from PySide6.QtGui import QColor, QImage, QPainter

    image = QImage(400, 400, QImage.Format.Format_RGB32)
    image.fill(QColor(PALETTE.paper))
    painter = QPainter(image)
    painter.translate(200, 200)
    painter.scale(2, 2)
    qt_render.paint(painter, prepared)
    painter.end()
    return image


def test_nothing_changed_means_nothing_to_redraw():
    model = Model(15, 7)
    kept = {}
    qt_render.prepare(model, PALETTE, kept)
    assert qt_render.changed_area(kept) is None
    qt_render.prepare(model, PALETTE, kept)
    assert qt_render.changed_area(kept).isEmpty()


def test_buildings_share_no_points_with_wards_walls_or_roads():
    """Editing moves those corners in place. Buildings only change through
    the editor, which counts it, so they mustn't share a point with them."""
    for options in (dict(size=15, seed=1), dict(size=24, seed=3,
                                                home_style="gnome",
                                                greens=True),
                    dict(size=24, seed=2, home_style="classic", walls=True,
                         citadel=True, temple=True)):
        model = Model(**options)
        corners = {id(v) for patch in model.patches for v in patch.shape}
        corners |= {id(v) for wall in model.walls() for v in wall.shape}
        corners |= {id(v) for way in model.roads + model.streets for v in way}
        for patch in model.patches:
            for polygon in list(patch.ward.geometry) + list(
                    patch.ward.landmarks):
                shapes = [polygon] + ([polygon.house]
                                      if isinstance(polygon, Plot) else [])
                assert not any(id(v) in corners
                               for shape in shapes for v in shape)


def test_kept_trims_come_back_as_new_lists():
    model = Model(15, 7, river=True)
    water = streets._Water.of(model)
    line = [(-50.0, 0.0), (50.0, 0.0)]
    first = streets.trim(line, water)
    first[0].append((999, 999))
    assert streets.trim(line, water) != first


def test_the_kept_building_grid_finds_what_a_new_one_does():
    model = Model(24, 4)
    streets.ways(model)
    dragged(model)
    streets.ways(model)
    kept = model.__dict__["_way_obstacles"]
    fresh = streets._Obstacles(kept.entries)
    for x in range(-60, 61, 7):
        for y in range(-60, 61, 7):
            assert {id(e) for e in kept.near(x, y, 3.0)} == {
                id(e) for e in fresh.near(x, y, 3.0)}


def test_a_drag_drawn_in_parts_looks_the_same_as_a_full_redraw(qapp,
                                                               monkeypatch):
    from citygen.app import MainWindow

    monkeypatch.setattr(QMessageBox, "question",
                        lambda *args: QMessageBox.StandardButton.Yes)
    window = MainWindow()
    window.resize(900, 700)
    window.show()
    window.size_box.blockSignals(True)
    window.size_box.setValue(24)
    window.size_box.blockSignals(False)
    window._set_seed(5)
    window.build()
    QApplication.processEvents()
    view = window.view
    window.edit_button.setChecked(True)
    editor = window.editor
    building = editor.buildings[len(editor.buildings) // 2]
    view.zoom = 2.0
    centre = view._transform().map(QPointF(building.cx, building.cy))
    view.pan -= centre - QPointF(view.width() / 2, view.height() / 2)
    view.repaint()
    start = view._transform().map(QPointF(building.cx, building.cy)).toPoint()
    QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=start)
    assert view.moving is building
    for i in range(1, 15):
        QTest.mouseMove(view, start + QPoint(i * 3, i))
        view.repaint()
    in_parts = view._cache.toImage()
    view._cache = None
    view._map_picture()
    whole = view._cache.toImage()
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton,
                       pos=start + QPoint(42, 14))
    # Only the smoothing along edges may round a shade differently.
    assert worst_difference(whole, in_parts, 3) <= 8
    window.close()
