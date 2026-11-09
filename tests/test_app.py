import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from citygen.app import MainWindow, SIZE_PRESETS
from citygen.gnomes import GnomeHome
from citygen.model import MAX_SIZE, MIN_SIZE


@pytest.fixture
def window(qapp):
    window = MainWindow()
    window.resize(1000, 800)
    window.show()
    QApplication.processEvents()
    yield window
    window.close()


def scene_to_widget(view, patch):
    centre = patch.shape.center
    return view._transform().map(QPointF(centre.x, centre.y)).toPoint()


def labelled_patch(model):
    return next(p for p in model.inner if p.ward.label)


def scroll(view, position, amount):
    event = QWheelEvent(
        QPointF(position), QPointF(view.mapToGlobal(position)),
        QPoint(0, 0), QPoint(0, amount), Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(view, event)


def test_homes_can_be_switched_to_gnome_homes_and_back(window):
    def gnome_homes():
        return sum(isinstance(getattr(building, "house", None), GnomeHome)
                   for patch in window.model.patches
                   for building in patch.ward.geometry)

    assert gnome_homes() == 0
    seed = window.model.seed

    window.homes_box.setCurrentIndex(1)
    assert gnome_homes() > 0
    assert window.model.seed == seed

    window.homes_box.setCurrentIndex(0)
    assert gnome_homes() == 0


def test_hovering_names_the_ward(window):
    view = window.view
    patch = labelled_patch(window.model)
    QTest.mouseMove(view, scene_to_widget(view, patch))
    QApplication.processEvents()
    assert view.hover_text == patch.ward.label


def test_scrolling_zooms_around_the_pointer(window):
    view = window.view
    position = QPoint(200, 200)
    before = view._transform().inverted()[0].map(QPointF(position))
    scroll(view, position, 240)
    after = view._transform().inverted()[0].map(QPointF(position))
    assert view.zoom > 1
    assert after.x() == pytest.approx(before.x())
    assert after.y() == pytest.approx(before.y())


def test_dragging_pans_and_double_click_resets(window):
    view = window.view
    QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
    view.mouseMoveEvent(_move_event(view, QPointF(150, 130)))
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton, pos=QPoint(150, 130))
    assert (view.pan.x(), view.pan.y()) == (50, 30)

    view.mouseDoubleClickEvent(None)
    assert (view.pan.x(), view.pan.y()) == (0, 0)


def _move_event(view, position):
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QMouseEvent

    return QMouseEvent(
        QEvent.Type.MouseMove, position, QPointF(view.mapToGlobal(position)),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier)


def test_return_makes_a_new_map(window):
    seed = window.model.seed
    window._return_pressed()
    assert window.model.seed != seed


def test_return_in_the_seed_box_uses_the_typed_seed(window, monkeypatch):
    monkeypatch.setattr(window.seed_box, "hasFocus", lambda: True)
    window.seed_box.lineEdit().setText("4242")
    window._return_pressed()
    assert window.model.seed == 4242


@pytest.mark.parametrize("name, low, high", SIZE_PRESETS)
def test_size_presets_stay_in_their_range(window, name, low, high):
    assert MIN_SIZE <= low <= high <= MAX_SIZE
    window.new_preset(low, high)
    assert low <= window.model.size <= high


def test_same_controls_rebuild_the_same_city(window):
    from citygen.export import city_to_dict

    first = city_to_dict(window.model)
    window.build()
    assert city_to_dict(window.model) == first


def test_export_names_describe_the_city(window):
    window.seed_box.setValue(77)
    window.build()
    assert window._default_name("png").endswith("-77.png")


def inner_building(window):
    editor = window.editor
    return max((b for b in editor.buildings if b.ward.patch.within_city),
               key=lambda b: len(editor._nearby(b)))


def widget_point(view, building):
    x, y = building.center()
    return view._transform().map(QPointF(x, y)).toPoint()


def test_clicks_do_nothing_to_buildings_until_edit_mode(window):
    view = window.view
    building = inner_building(window)
    before = building.corners()
    QTest.mouseClick(view, Qt.MouseButton.LeftButton,
                     pos=widget_point(view, building))
    assert view.selected is None
    assert building.corners() == before


def test_edit_mode_selects_and_drags_a_building(window):
    view = window.view
    window.edit_button.setChecked(True)
    building = inner_building(window)
    start = widget_point(view, building)
    cx, cy = building.center()

    QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=start)
    assert view.selected is building
    assert window.lock_button.isEnabled()

    finish = QPointF(start) + QPointF(40, 0)
    view.mouseMoveEvent(_move_event(view, finish))
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton, pos=finish.toPoint())

    assert building.center()[0] > cx
    assert window.undo_button.isEnabled()

    window.undo_move()
    assert building.center() == pytest.approx((cx, cy), abs=0.02)
    assert not window.undo_button.isEnabled()


def test_dragging_open_ground_still_pans_in_edit_mode(window):
    view = window.view
    window.edit_button.setChecked(True)
    corner = QPoint(2, 2)
    assert view.editor.building_at(view._spot(corner)) is None

    QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=corner)
    view.mouseMoveEvent(_move_event(view, QPointF(32, 22)))
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton, pos=QPoint(32, 22))
    assert (view.pan.x(), view.pan.y()) == (30, 20)


def test_lock_button_locks_and_unlocks(window):
    view = window.view
    window.edit_button.setChecked(True)
    building = inner_building(window)
    view.select(building)
    assert window.lock_button.text() == "Lock building"

    window.lock_button.click()
    assert window.editor.is_locked(building)
    assert window.lock_button.text() == "Unlock building"
    assert window.unlock_all_button.isEnabled()

    window.lock_button.click()
    assert not window.editor.is_locked(building)


def test_right_click_locks_a_building(window):
    from PySide6.QtGui import QContextMenuEvent

    view = window.view
    window.edit_button.setChecked(True)
    building = inner_building(window)
    point = widget_point(view, building)
    view.contextMenuEvent(QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse, point, view.mapToGlobal(point)))
    assert window.editor.is_locked(building)
    assert view.selected is building


def test_a_locked_building_stays_put_when_dragged(window):
    view = window.view
    window.edit_button.setChecked(True)
    building = inner_building(window)
    window.editor.set_locked(building, True)
    before = building.corners()
    start = widget_point(view, building)

    QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=start)
    view.mouseMoveEvent(_move_event(view, QPointF(start) + QPointF(40, 0)))
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton, pos=start)
    assert building.corners() == before


def test_changing_style_keeps_the_edits(window):
    window.edit_button.setChecked(True)
    building = inner_building(window)
    window.editor.set_locked(building, True)
    editor = window.editor
    window.palette_box.setCurrentText("Ink")
    assert window.editor is editor
    assert window.view.editor is editor


def test_declining_to_discard_keeps_the_map_and_controls(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "question", lambda *args:
                        QMessageBox.StandardButton.No)
    model = window.model
    seed = window.seed_box.value()
    size = window.size_box.value()
    window.editor.set_locked(inner_building(window), True)

    window.new_map()
    assert window.model is model
    assert window.seed_box.value() == seed

    window.walls_box.setCurrentIndex(2)
    assert window.model is model
    assert window.walls_box.currentIndex() == 0

    window.new_preset(40, 40)
    assert window.size_box.value() == size


def test_accepting_the_discard_builds_the_new_map(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "question", lambda *args:
                        QMessageBox.StandardButton.Yes)
    model = window.model
    window.editor.set_locked(inner_building(window), True)
    window.new_map()
    assert window.model is not model
    assert not window.editor.has_changes


def test_an_unedited_map_is_replaced_without_asking(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    def fail(*args):
        raise AssertionError("asked needlessly")

    monkeypatch.setattr(QMessageBox, "question", fail)
    window.new_map()
