import math

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from citygen import editing
from citygen.app import MainWindow
from citygen.editing import CityEditor
from citygen.geometry import Point
from citygen.model import Model


def walled_city(**options):
    options = {"walls": True, "coast": False, "river": False, **options}
    return Model(15, 7, **options)


def crosses_itself(shape):
    edges = shape.edges()
    for i, (a, b) in enumerate(edges):
        for c, d in edges[i + 2:]:
            if d is a:
                continue
            if editing._segments_cross(a.x, a.y, b.x, b.y, c.x, c.y, d.x, d.y):
                return True
    return False


def snapshot(model, editor):
    wall = model.wall
    return ([(v.x, v.y) for v in wall.shape], list(wall.segments),
            [(t.x, t.y) for t in wall.towers],
            [[(v.x, v.y) for v in p.shape] for p in model.patches],
            [b.corners() for b in editor.buildings])


def sides(model, editor):
    return [model.wall.shape.contains_point(Point(*b.center()))
            for b in editor.buildings]


def a_tower(model, editor):
    """A tower on the wall, away from the gates."""
    return next(t for t in model.wall.towers
                if t in model.wall.shape and t not in model.wall.gates
                and not editor.is_fixed_corner(t))


def drag_corner(editor, corner, dx, dy, steps=10):
    assert editor.begin_wall_move(corner) is corner
    reached = False
    for i in range(1, steps + 1):
        reached = editor.drag_wall_to(corner, dx * i / steps, dy * i / steps)
    editor.end_move()
    return reached


def outward(corner):
    size = math.hypot(corner.x, corner.y)
    return corner.x / size, corner.y / size


def test_a_tower_can_be_dragged_out_and_the_wall_follows():
    model = walled_city()
    editor = CityEditor(model)
    tower = a_tower(model, editor)
    x, y = tower.x, tower.y
    ox, oy = outward(tower)

    assert drag_corner(editor, tower, ox * 8, oy * 8)
    assert (tower.x, tower.y) == pytest.approx((x + ox * 8, y + oy * 8))
    assert tower in model.wall.shape and tower in model.wall.towers
    assert not crosses_itself(model.wall.shape)


def test_dragging_a_tower_in_pushes_buildings_out_of_the_way():
    model = walled_city()
    editor = CityEditor(model)
    start = sides(model, editor)
    tower = a_tower(model, editor)
    ox, oy = outward(tower)
    before = [b.corners() for b in editor.buildings]

    drag_corner(editor, tower, -ox * 10, -oy * 10)

    assert math.hypot(tower.x, tower.y) < math.hypot(
        tower.x + ox * 10, tower.y + oy * 10)
    assert [b.corners() for b in editor.buildings] != before
    assert sides(model, editor) == start
    assert not crosses_itself(model.wall.shape)


def test_undo_puts_a_dragged_corner_back():
    model = walled_city()
    editor = CityEditor(model)
    start = snapshot(model, editor)
    tower = a_tower(model, editor)
    ox, oy = outward(tower)
    drag_corner(editor, tower, -ox * 10, -oy * 10)
    assert snapshot(model, editor) != start

    assert editor.undo()
    assert snapshot(model, editor) == start


def test_dragging_an_edge_adds_a_corner_that_undo_takes_away():
    model = walled_city()
    editor = CityEditor(model)
    start = snapshot(model, editor)
    wall = model.wall
    i = next(i for i, built in enumerate(wall.segments) if built)
    a, b = wall.shape[i], wall.shape[(i + 1) % len(wall.shape)]
    count = len(wall.shape)

    corner = editor.begin_wall_move(edge=(a, b, 0.5))
    assert corner is not None
    assert len(wall.shape) == count + 1
    assert wall.shape[(i + 1) % len(wall.shape)] is corner
    assert corner not in wall.towers
    # The wards on each side of the wall get the corner too.
    assert any(corner in p.shape for p in model.patches)

    ox, oy = outward(corner)
    for step in range(1, 6):
        editor.drag_wall_to(corner, ox * step, oy * step)
    editor.end_move()
    assert not crosses_itself(wall.shape)

    assert editor.undo()
    assert snapshot(model, editor) == start


def test_corners_on_the_water_stay_put():
    model = Model(15, 7, walls=True, river=True)
    editor = CityEditor(model)
    fixed = [v for v in model.wall.shape if v in model.water_points]
    assert fixed
    corner = fixed[0]
    assert editor.begin_wall_move(corner) is None
    assert corner not in editor.wall_corners()


def test_a_corner_cannot_be_dragged_across_the_wall():
    model = walled_city()
    editor = CityEditor(model)
    tower = a_tower(model, editor)
    shape = model.wall.shape
    # Straight across the town, which would tangle the wall.
    drag_corner(editor, tower, -tower.x * 1.9, -tower.y * 1.9, steps=40)
    assert not crosses_itself(shape)


def test_a_locked_building_stops_a_wall():
    model = walled_city()
    editor = CityEditor(model)
    tower = a_tower(model, editor)
    nearest = min(editor.buildings, key=lambda b: math.hypot(
        b.cx - tower.x, b.cy - tower.y))
    editor.set_locked(nearest, True)
    held = nearest.corners()
    assert not drag_corner(editor, tower, nearest.cx - tower.x,
                           nearest.cy - tower.y, steps=20)
    assert nearest.corners() == held


def test_towers_can_be_taken_away_and_put_back():
    model = walled_city()
    editor = CityEditor(model)
    wall = model.wall
    tower = a_tower(model, editor)
    assert editor.toggle_tower(tower)
    assert tower not in wall.towers
    assert not editor.wall_corners()[tower]
    assert editor.toggle_tower(tower)
    assert tower in wall.towers

    assert editor.undo()
    assert tower not in wall.towers
    assert editor.undo()
    assert tower in wall.towers


def test_a_new_corner_can_get_a_tower():
    model = walled_city()
    editor = CityEditor(model)
    wall = model.wall
    i = next(i for i, built in enumerate(wall.segments) if built)
    corner = editor.begin_wall_move(
        edge=(wall.shape[i], wall.shape[(i + 1) % len(wall.shape)], 0.5))
    editor.end_move()
    assert corner not in wall.towers
    assert editor.toggle_tower(corner)
    assert corner in wall.towers


def test_gates_never_get_towers():
    model = walled_city()
    editor = CityEditor(model)
    gate = model.wall.gates[0]
    assert not editor.toggle_tower(gate)
    assert gate not in model.wall.towers


def test_the_castle_wall_can_be_reshaped_too():
    model = Model(15, 5, walls=True, citadel=True, coast=False, river=False)
    editor = CityEditor(model)
    castle = model.citadel.ward.wall
    centre = castle.shape.center
    moved = False
    for corner in castle.shape:
        if editor.is_fixed_corner(corner):
            continue
        for size in (3, -3):
            way = corner.subtract(centre).norm(size)
            x, y = corner.x, corner.y
            drag_corner(editor, corner, way.x, way.y)
            moved = moved or (corner.x, corner.y) != (x, y)
            assert not crosses_itself(castle.shape)
            assert not crosses_itself(model.wall.shape)
    assert moved


@pytest.fixture
def window(qapp):
    window = MainWindow()
    window.resize(1000, 800)
    window.show()
    window.seed_box.setValue(7)
    window.walls_box.setCurrentIndex(1)
    QApplication.processEvents()
    window.edit_button.setChecked(True)
    QApplication.processEvents()
    yield window
    window.close()


def on_screen(view, point):
    return view._transform().map(QPointF(point.x, point.y)).toPoint()


def test_dragging_a_wall_corner_in_the_window(window):
    view = window.view
    model = window.model
    tower = a_tower(model, window.editor)
    x, y = tower.x, tower.y
    start = on_screen(view, tower)
    QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=start)
    for i in range(1, 6):
        QTest.mouseMove(view, start + QPoint(i * 6, 0))
        QApplication.processEvents()
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton, pos=start + QPoint(30, 0))
    QApplication.processEvents()
    assert (tower.x, tower.y) != (x, y)
    assert window.undo_button.isEnabled()
    window.undo_move()
    assert (tower.x, tower.y) == pytest.approx((x, y))


def test_a_click_on_the_wall_alone_adds_no_corner(window):
    view = window.view
    wall = window.model.wall
    i = next(i for i, built in enumerate(wall.segments) if built)
    a, b = wall.shape[i], wall.shape[(i + 1) % len(wall.shape)]
    middle = Point((a.x + b.x) / 2, (a.y + b.y) / 2)
    count = len(wall.shape)
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=on_screen(view, middle))
    QApplication.processEvents()
    assert len(wall.shape) == count
    assert not window.editor.history
