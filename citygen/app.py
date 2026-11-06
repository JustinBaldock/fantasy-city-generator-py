"""The desktop app."""

import random
import sys

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QKeySequence,
    QPainter,
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

MIN_ZOOM = 0.3
MAX_ZOOM = 40.0


class MapView(QWidget):
    """The map. Drag to pan, scroll to zoom, double-click to reset."""

    hovered = Signal(str)

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

    def set_city(self, model, palette, reset_view=True):
        self.model = model
        self.palette_colours = palette
        self.prepared = qt_render.prepare(model, palette)
        if reset_view:
            self.reset_view()
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
        painter.resetTransform()

        if self.hover_text:
            self._paint_label(painter, colours)

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

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_start = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseReleaseEvent(self, event):
        self.drag_start = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mouseDoubleClickEvent(self, event):
        self.reset_view()

    def mouseMoveEvent(self, event):
        if self.model is None:
            return
        position = event.position()
        if self.drag_start is not None:
            self.pan += position - self.drag_start
            self.drag_start = position
            self.update()

        inverse, invertible = self._transform().inverted()
        if not invertible:
            return
        spot = inverse.map(position)
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
        self.roads_box = QComboBox()
        self.roads_box.addItem("All gates", True)
        self.roads_box.addItem("Two roads", False)
        self.roads_box.setToolTip("How many roads lead out of town")
        for label, box in (("Walls", self.walls_box),
                           ("Castle", self.citadel_box),
                           ("Plaza", self.plaza_box),
                           ("Temple", self.temple_box),
                           ("Greens", self.greens_box),
                           ("Coast", self.coast_box),
                           ("River", self.river_box),
                           ("Fields", self.fields_box),
                           ("Forests", self.forests_box),
                           ("Roads", self.roads_box)):
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

    def build(self):
        """Build the city the controls describe."""
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
            )
        except GenerationError as error:
            QMessageBox.warning(self, APP_NAME, str(error))
            return

        self.model = model
        self.view.set_city(model, self.palette())
        self.city_label.setText(
            f"{size_name(model.size)}, {model.size} wards, seed {model.seed}")

    def _palette_changed(self):
        if self.model is not None:
            self.view.set_city(self.model, self.palette(), reset_view=False)

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
