"""The desktop app."""

import random
import sys

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QKeySequence,
    QPainter,
    QPen,
    QPolygonF,
    QShortcut,
    QTransform,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from . import export, qt_render
from .editing import CityEditor
from .geometry import GenerationError, Point
from .layers import PALETTES, map_extent
from .model import (
    DEFAULT_SIZE,
    MAX_SEED,
    MAX_SIZE,
    MIN_SIZE,
    Model,
    size_name,
)

APP_NAME = "Fantasy City Generator"

# Label, then the smallest and largest size for that kind of settlement.
SIZE_PRESETS = (
    ("Small Town", 6, 9),
    ("Large Town", 10, 14),
    ("Small City", 15, 23),
    ("Large City", 24, 39),
    ("Metropolis", 40, 40),
)

LOCKED_COLOUR = "#c0392b"
SELECTED_COLOUR = "#2f7de1"

HANDLE_PIXELS = 7  # How close the pointer must be to grab a wall corner.
EDGE_PIXELS = 4  # How close to grab a stretch of wall and add a corner.

MIN_ZOOM = 0.3
MAX_ZOOM = 40.0


class MapView(QWidget):
    """The map. Drag to pan, scroll to zoom, double-click to reset.

    In edit mode, a click selects a building and dragging moves it. Dragging
    a wall corner moves it, and dragging a stretch of wall adds a corner there
    and moves that. A right click locks a building or puts a tower on a wall
    corner. Dragging open ground still pans.
    """

    hovered = Signal(str)
    selection_changed = Signal()
    edited = Signal()

    def __init__(self):
        super().__init__()
        self.setMouseTracking(True)
        self.setMinimumSize(400, 400)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.model = None
        self.palette_colours = None
        self.prepared = []
        self.zoom = 1.0
        self.pan = QPointF(0, 0)
        self.drag_start = None
        self.hover_text = ""
        self.hover_position = QPointF(0, 0)
        self.editor = None
        self.edit_mode = False
        self.selected = None
        self.moving = None
        self.moving_corner = None
        self.pending_edge = None
        self.move_start = None

    def set_city(self, model, palette, editor=None, reset_view=True):
        self.model = model
        self.palette_colours = palette
        if editor is not self.editor:
            self.editor = editor
            self.select(None)
        self.refresh()
        if reset_view:
            self.reset_view()

    def refresh(self):
        """Redraw the city after something on it has changed."""
        self.prepared = qt_render.prepare(self.model, self.palette_colours)
        self.update()

    def set_edit_mode(self, on):
        self.edit_mode = on
        if not on:
            self.select(None)
        self.setCursor(Qt.CursorShape.ArrowCursor if on
                       else Qt.CursorShape.OpenHandCursor)
        self.update()

    def select(self, building):
        if building is not self.selected:
            self.selected = building
            self.selection_changed.emit()
            self.update()

    def reset_view(self):
        self.zoom = 1.0
        self.pan = QPointF(0, 0)
        self.update()

    def _transform(self):
        scale = self.zoom * min(self.width(), self.height()) / (
            map_extent(self.model) * 2)
        transform = QTransform()
        transform.translate(self.width() / 2 + self.pan.x(),
                            self.height() / 2 + self.pan.y())
        transform.scale(scale, scale)
        return transform

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.model is None:
            painter.fillRect(self.rect(), QColor("#ccc5b8"))
            return

        colours = self.palette_colours
        painter.fillRect(self.rect(), QColor(colours.paper))
        painter.setTransform(self._transform())
        qt_render.paint(painter, self.prepared)
        if self.edit_mode and self.editor is not None:
            self._paint_edit_marks(painter)
        painter.resetTransform()

        if self.hover_text:
            self._paint_label(painter, colours)

    def _paint_edit_marks(self, painter):
        def outline(building):
            return QPolygonF([QPointF(x, y) for x, y in building.corners()])

        locked = QColor(LOCKED_COLOUR)
        pen = QPen(locked, 2)
        pen.setCosmetic(True)
        painter.setPen(pen)
        locked.setAlpha(110)
        painter.setBrush(locked)
        for building in self.editor.locked:
            painter.drawPolygon(outline(building))

        # Handles on the wall corners that can be dragged, filled for towers.
        radius = HANDLE_PIXELS * 0.6 / self._scale()
        pen = QPen(QColor(SELECTED_COLOUR), 1.5)
        pen.setCosmetic(True)
        painter.setPen(pen)
        for corner, tower in self.editor.wall_corners().items():
            moving = corner is self.moving_corner
            colour = QColor(SELECTED_COLOUR if moving or tower else "#ffffff")
            colour.setAlpha(255 if moving else 170)
            painter.setBrush(colour)
            painter.drawEllipse(QPointF(corner.x, corner.y), radius, radius)

        if self.selected is not None:
            pen = QPen(QColor(SELECTED_COLOUR), 3)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPolygon(outline(self.selected))

    def _paint_label(self, painter, colours):
        metrics = painter.fontMetrics()
        box = QRectF(metrics.boundingRect(self.hover_text)).adjusted(-5, -3, 5, 3)
        box.moveTopLeft(self.hover_position + QPointF(12, 6))
        box.moveRight(min(box.right(), self.width() - 2))
        box.moveBottom(min(box.bottom(), self.height() - 2))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(colours.dark))
        painter.drawRect(box)
        painter.setPen(QColor(colours.paper))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, self.hover_text)

    def wheelEvent(self, event):
        if self.model is None:
            return
        steps = event.angleDelta().y()
        new_zoom = max(MIN_ZOOM, min(MAX_ZOOM, self.zoom * 1.0015 ** steps))

        # Keep the spot under the pointer where it is.
        centre = QPointF(self.width() / 2, self.height() / 2) + self.pan
        cursor = event.position()
        self.pan += (cursor - centre) * (1 - new_zoom / self.zoom)
        self.zoom = new_zoom
        self.update()

    def _scale(self):
        """Pixels for each unit of map."""
        return self._transform().m11()

    def _wall_handle_at(self, spot):
        """A wall corner, or else a stretch of wall, under the pointer."""
        scale = self._scale()
        corner = self.editor.wall_corner_at(spot, HANDLE_PIXELS / scale)
        if corner is not None:
            return corner, None
        return None, self.editor.wall_edge_at(spot, EDGE_PIXELS / scale)

    def _spot(self, position):
        """The place on the map under a position in the window."""
        inverse, _ = self._transform().inverted()
        spot = inverse.map(QPointF(position))
        return Point(spot.x(), spot.y())

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self.edit_mode and self.editor is not None:
            spot = self._spot(event.position())
            corner, edge = self._wall_handle_at(spot)
            if corner is not None:
                if self.editor.begin_wall_move(corner) is not None:
                    self.select(None)
                    self.moving_corner = corner
                    self.move_start = spot
                    self.update()
                return
            if edge is not None:
                # The corner goes in once the pointer moves, so a click alone
                # changes nothing.
                self.select(None)
                self.pending_edge = (edge, spot)
                return
            building = self.editor.building_at(spot)
            self.select(building)
            if building is not None:
                if self.editor.begin_move(building):
                    self.moving = building
                    self.move_start = spot
                return
        self.drag_start = event.position()
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseReleaseEvent(self, event):
        self.pending_edge = None
        if self.moving_corner is not None:
            self.editor.end_move()
            self.moving_corner = None
            self.edited.emit()
            self.update()
        if self.moving is not None:
            self.editor.end_move()
            self.moving = None
            self.edited.emit()
        self.drag_start = None
        self.setCursor(Qt.CursorShape.ArrowCursor if self.edit_mode
                       else Qt.CursorShape.OpenHandCursor)

    def mouseDoubleClickEvent(self, event):
        if self.edit_mode:
            # A quick second click is still a click on a building.
            self.mousePressEvent(event)
        else:
            self.reset_view()

    def contextMenuEvent(self, event):
        """A right click locks or unlocks a building, or toggles a tower."""
        if not self.edit_mode or self.editor is None:
            return
        spot = self._spot(event.pos())
        corner, _ = self._wall_handle_at(spot)
        if corner is not None:
            if self.editor.toggle_tower(corner):
                self.refresh()
                self.edited.emit()
            return
        building = self.editor.building_at(spot)
        if building is not None:
            self.select(building)
            self.editor.toggle_lock(building)
            self.selection_changed.emit()
            self.edited.emit()
            self.update()

    def mouseMoveEvent(self, event):
        if self.model is None:
            return
        position = event.position()
        if self.pending_edge is not None:
            edge, start = self.pending_edge
            self.pending_edge = None
            corner = self.editor.begin_wall_move(edge=edge)
            if corner is not None:
                self.moving_corner = corner
                self.move_start = start
        if self.moving_corner is not None:
            spot = self._spot(position)
            self.editor.drag_wall_to(self.moving_corner,
                                     spot.x - self.move_start.x,
                                     spot.y - self.move_start.y)
            self.refresh()
            return
        if self.moving is not None:
            spot = self._spot(position)
            self.editor.drag_to(self.moving, spot.x - self.move_start.x,
                                spot.y - self.move_start.y)
            self.refresh()
            return
        if self.drag_start is not None:
            self.pan += position - self.drag_start
            self.drag_start = position
            self.update()

        inverse, invertible = self._transform().inverted()
        if not invertible:
            return
        spot = inverse.map(position)
        if (self.edit_mode and self.editor is not None
                and self.drag_start is None):
            corner, edge = self._wall_handle_at(Point(spot.x(), spot.y()))
            self.setCursor(
                Qt.CursorShape.SizeAllCursor if corner is not None
                else Qt.CursorShape.CrossCursor if edge is not None
                else Qt.CursorShape.ArrowCursor)
        patch = self.model.patch_at(Point(spot.x(), spot.y()))
        text = (patch.ward.label or "") if patch is not None else ""
        self.hover_position = position
        if text != self.hover_text:
            self.hover_text = text
            self.hovered.emit(text)
        if text:
            self.update()

    def leaveEvent(self, event):
        if self.hover_text:
            self.hover_text = ""
            self.hovered.emit("")
            self.update()


class TriState(QComboBox):
    """Random, yes or no, for one feature of the city."""

    def __init__(self):
        super().__init__()
        self.addItem("Random", None)
        self.addItem("Yes", True)
        self.addItem("No", False)


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1100, 820)
        self.model = None

        self.view = MapView()
        self.view.hovered.connect(self._show_hovered)
        self.view.selection_changed.connect(self._update_edit_controls)
        self.view.edited.connect(self._update_edit_controls)
        self.editor = None
        self.built_state = None

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.view, 1)
        layout.addWidget(self._build_side_panel())
        self.setCentralWidget(central)

        self._build_menu()

        for key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            QShortcut(QKeySequence(key), self, self._return_pressed)

        self.city_label = QLabel()
        self.statusBar().addPermanentWidget(self.city_label)

        self.new_map()

    def _build_side_panel(self):
        """The controls, which scroll if the screen is too short for them."""
        scroller = QScrollArea()
        scroller.setWidget(self._build_controls())
        scroller.setWidgetResizable(True)
        scroller.setFrameShape(QFrame.Shape.NoFrame)
        scroller.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        panel = QWidget()
        panel.setFixedWidth(256)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.addWidget(scroller, 1)
        buttons = QVBoxLayout()
        buttons.setContentsMargins(10, 0, 18, 0)
        layout.addLayout(buttons)

        self.edit_button = QPushButton("Edit buildings")
        self.edit_button.setCheckable(True)
        self.edit_button.setToolTip(
            "Click a building to select it, drag to move it, "
            "right-click to lock it. Drag wall corners and edges to reshape "
            "the walls, and right-click a corner for a tower (E)")
        self.edit_button.toggled.connect(self._edit_toggled)
        buttons.addWidget(self.edit_button)

        self.lock_button = QPushButton("Lock building")
        self.lock_button.clicked.connect(self.toggle_lock)
        buttons.addWidget(self.lock_button)

        row = QHBoxLayout()
        self.undo_button = QPushButton("Undo move")
        self.undo_button.clicked.connect(self.undo_move)
        row.addWidget(self.undo_button)
        self.unlock_all_button = QPushButton("Unlock all")
        self.unlock_all_button.clicked.connect(self.unlock_all)
        row.addWidget(self.unlock_all_button)
        buttons.addLayout(row)

        for text, handler in (("Export PNG...", self.export_png),
                              ("Export SVG...", self.export_svg),
                              ("Export JSON...", self.export_json)):
            button = QPushButton(text)
            button.clicked.connect(handler)
            buttons.addWidget(button)
        return panel

    def _build_controls(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)

        new_button = QPushButton("New map")
        new_button.setToolTip("A new seed at this size (Return)")
        new_button.clicked.connect(self.new_map)
        layout.addWidget(new_button)

        size_box = QGroupBox("Size")
        size_layout = QVBoxLayout(size_box)
        for name, low, high in SIZE_PRESETS:
            button = QPushButton(name)
            button.clicked.connect(
                lambda checked=False, a=low, b=high: self.new_preset(a, b))
            size_layout.addWidget(button)
        self.size_box = QSpinBox()
        self.size_box.setRange(MIN_SIZE, MAX_SIZE)
        self.size_box.setValue(DEFAULT_SIZE)
        self.size_box.setKeyboardTracking(False)
        self.size_box.setToolTip("How many wards sit at the heart of the city")
        self.size_box.valueChanged.connect(self.build)
        form = QFormLayout()
        form.addRow("Wards", self.size_box)
        size_layout.addLayout(form)
        layout.addWidget(size_box)

        city_box = QGroupBox("City")
        city_layout = QFormLayout(city_box)
        self.seed_box = QSpinBox()
        self.seed_box.setRange(1, MAX_SEED)
        self.seed_box.setKeyboardTracking(False)
        self.seed_box.setToolTip("The same seed and settings give the same map")
        city_layout.addRow("Seed", self.seed_box)
        self.walls_box = TriState()
        self.citadel_box = TriState()
        self.plaza_box = TriState()
        self.temple_box = TriState()
        self.greens_box = TriState()
        self.coast_box = TriState()
        self.river_box = TriState()
        self.fields_box = TriState()
        self.forests_box = TriState()
        self.orchards_box = TriState()
        self.roads_box = QComboBox()
        self.roads_box.addItem("All gates", True)
        self.roads_box.addItem("Two roads", False)
        self.roads_box.setToolTip("How many roads lead out of town")
        self.homes_box = QComboBox()
        self.homes_box.addItem("Burgage plots", "burgage")
        self.homes_box.addItem("Gnome", "gnome")
        self.homes_box.addItem("Classic", "classic")
        self.homes_box.setToolTip(
            "Burgage plots have the house at the street front and a garden "
            "behind. Gnome homes are hexagons with square rooms off their "
            "sides, among rectangular shops, stores and barns. Classic "
            "houses fill their plots, as on the original generator.")
        features = (("Walls", self.walls_box),
                    ("Castle", self.citadel_box),
                    ("Plaza", self.plaza_box),
                    ("Temple", self.temple_box),
                    ("Greens", self.greens_box),
                    ("Coast", self.coast_box),
                    ("River", self.river_box),
                    ("Fields", self.fields_box),
                    ("Forests", self.forests_box),
                    ("Orchards", self.orchards_box),
                    ("Roads", self.roads_box),
                    ("Homes", self.homes_box))
        self.feature_boxes = [box for _, box in features]
        for label, box in features:
            box.currentIndexChanged.connect(self.build)
            city_layout.addRow(label, box)

        self.sea_box = QSpinBox()
        self.sea_box.setRange(-1, 359)
        self.sea_box.setValue(-1)
        self.sea_box.setSpecialValueText("Random")
        self.sea_box.setSuffix("\N{DEGREE SIGN}")
        self.sea_box.setKeyboardTracking(False)
        self.sea_box.setToolTip(
            "The compass bearing of the sea, 0 for north and 90 for east")
        self.sea_box.valueChanged.connect(self.build)
        city_layout.addRow("Sea to", self.sea_box)
        layout.addWidget(city_box)

        self.palette_box = QComboBox()
        self.palette_box.addItems(PALETTES)
        self.palette_box.currentTextChanged.connect(self._palette_changed)
        style_box = QGroupBox("Style")
        QVBoxLayout(style_box).addWidget(self.palette_box)
        layout.addWidget(style_box)

        layout.addStretch(1)
        return panel

    def _build_menu(self):
        file_menu = self.menuBar().addMenu("File")
        for text, shortcut, handler in (
                ("Export PNG...", "Ctrl+E", self.export_png),
                ("Export SVG...", "Ctrl+Shift+E", self.export_svg),
                ("Export JSON...", "Ctrl+J", self.export_json)):
            action = QAction(text, self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(handler)
            file_menu.addAction(action)

        edit_menu = self.menuBar().addMenu("Edit")
        for text, shortcut, handler in (
                ("Edit buildings", "E", self.edit_button.toggle),
                ("Lock or unlock building", "L", self.toggle_lock),
                ("Undo move", "Ctrl+Z", self.undo_move),
                ("Unlock all", "Ctrl+Shift+L", self.unlock_all)):
            action = QAction(text, self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(handler)
            edit_menu.addAction(action)

        view_menu = self.menuBar().addMenu("View")
        action = QAction("Reset view", self)
        action.setShortcut(QKeySequence("Ctrl+0"))
        action.triggered.connect(self.view.reset_view)
        view_menu.addAction(action)

    def palette(self):
        return PALETTES[self.palette_box.currentText()]

    def _return_pressed(self):
        # Return in the seed or size box means "use what I typed".
        if self.seed_box.hasFocus() or self.size_box.hasFocus():
            self.seed_box.interpretText()
            self.size_box.interpretText()
            self.build()
        else:
            self.new_map()

    def new_map(self):
        self._set_seed(random.randint(1, MAX_SEED))
        self.build()

    def new_preset(self, low, high):
        self.size_box.blockSignals(True)
        self.size_box.setValue(random.randint(low, high))
        self.size_box.blockSignals(False)
        self.new_map()

    def _set_seed(self, seed):
        self.seed_box.blockSignals(True)
        self.seed_box.setValue(seed)
        self.seed_box.blockSignals(False)

    def _control_state(self):
        return ([self.size_box.value(), self.seed_box.value(),
                 self.sea_box.value()],
                [box.currentIndex() for box in self.feature_boxes])

    def _restore_controls(self):
        """Put the controls back to match the city on screen."""
        values, indexes = self.built_state
        boxes = [self.size_box, self.seed_box, self.sea_box]
        for box in boxes + self.feature_boxes:
            box.blockSignals(True)
        for box, value in zip(boxes, values):
            box.setValue(value)
        for box, index in zip(self.feature_boxes, indexes):
            box.setCurrentIndex(index)
        for box in boxes + self.feature_boxes:
            box.blockSignals(False)

    def _may_discard_edits(self):
        if self.editor is None or not self.editor.has_changes:
            return True
        answer = QMessageBox.question(
            self, APP_NAME,
            "Building a new map will lose the buildings you've moved and "
            "locked. Export this map first if you want to keep it.\n\n"
            "Build a new map anyway?")
        return answer == QMessageBox.StandardButton.Yes

    def build(self):
        """Build the city the controls describe."""
        if not self._may_discard_edits():
            self._restore_controls()
            return

        try:
            model = Model(
                size=self.size_box.value(),
                seed=self.seed_box.value(),
                walls=self.walls_box.currentData(),
                citadel=self.citadel_box.currentData(),
                plaza=self.plaza_box.currentData(),
                temple=self.temple_box.currentData(),
                greens=self.greens_box.currentData(),
                coast=self.coast_box.currentData(),
                river=self.river_box.currentData(),
                hub=self.roads_box.currentData(),
                sea=None if self.sea_box.value() < 0 else self.sea_box.value(),
                fields=self.fields_box.currentData(),
                forests=self.forests_box.currentData(),
                orchards=self.orchards_box.currentData(),
                home_style=self.homes_box.currentData(),
            )
        except GenerationError as error:
            QMessageBox.warning(self, APP_NAME, str(error))
            return

        self.model = model
        self.editor = CityEditor(model)
        self.built_state = self._control_state()
        self.view.set_city(model, self.palette(), self.editor)
        self._update_edit_controls()
        self.city_label.setText(
            f"{size_name(model.size)}, {model.size} wards, seed {model.seed}")

    def _palette_changed(self):
        if self.model is not None:
            self.view.set_city(self.model, self.palette(), self.editor,
                               reset_view=False)

    def _edit_toggled(self, on):
        self.view.set_edit_mode(on)
        self._update_edit_controls()

    def _update_edit_controls(self):
        editor = self.editor
        selected = self.view.selected
        locked = (editor is not None and selected is not None
                  and editor.is_locked(selected))

        self.lock_button.setEnabled(selected is not None)
        self.lock_button.setText(
            "Unlock building" if locked else "Lock building")
        self.undo_button.setEnabled(editor is not None and bool(editor.history))
        self.unlock_all_button.setEnabled(
            editor is not None and bool(editor.locked))

        if selected is not None:
            name = selected.ward.label or "Building"
            state = "locked" if locked else "drag to move, L to lock"
            self.statusBar().showMessage(f"{name}: {state}")
        elif self.view.edit_mode:
            self.statusBar().showMessage(
                "Drag a building to move it, or a wall corner or edge to "
                "reshape the wall. Right-click a corner for a tower")

    def toggle_lock(self):
        selected = self.view.selected
        if selected is not None:
            self.editor.toggle_lock(selected)
            self._update_edit_controls()
            self.view.update()

    def undo_move(self):
        if self.editor is not None and self.editor.undo():
            self.view.refresh()
            self._update_edit_controls()

    def unlock_all(self):
        if self.editor is not None:
            self.editor.unlock_all()
            self._update_edit_controls()
            self.view.update()

    def _show_hovered(self, text):
        self.statusBar().showMessage(text)

    def _default_name(self, extension):
        name = size_name(self.model.size).lower().replace(" ", "-")
        return f"{name}-{self.model.seed}.{extension}"

    def _ask_path(self, title, extension, description):
        path, _ = QFileDialog.getSaveFileName(
            self, title, self._default_name(extension),
            f"{description} (*.{extension})")
        if path and not path.lower().endswith(f".{extension}"):
            path += f".{extension}"
        return path

    def _report_saved(self, path):
        self.statusBar().showMessage(f"Saved {path}", 5000)

    def _save(self, path, save):
        try:
            save()
        except OSError as error:
            QMessageBox.warning(self, APP_NAME, f"Couldn't save the map.\n{error}")
        else:
            self._report_saved(path)

    def export_png(self):
        pixels, accepted = QInputDialog.getInt(
            self, "Export PNG", "Width and height in pixels", 3000, 500, 16000,
            500)
        if not accepted:
            return
        path = self._ask_path("Export PNG", "png", "PNG image")
        if path:
            self._save(path, lambda: qt_render.save_png(
                self.model, self.palette(), path, pixels))

    def export_svg(self):
        path = self._ask_path("Export SVG", "svg", "SVG image")
        if path:
            self._save(path, lambda: export.save_svg(
                self.model, self.palette(), path))

    def export_json(self):
        path = self._ask_path("Export JSON", "json", "City data")
        if path:
            self._save(path, lambda: export.save_json(self.model, path))


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    window = MainWindow()
    window.show()
    return app.exec()
