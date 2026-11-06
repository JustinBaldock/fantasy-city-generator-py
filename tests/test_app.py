import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from citygen.app import MainWindow, SIZE_PRESETS
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
