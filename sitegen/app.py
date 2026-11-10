"""The Fantasy Location Generator window."""

import math
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
    QFrame,
    QGridLayout,
    QGroupBox,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from citygen import qt_render
from citygen.app import (
    FORM_SPACING,
    MAX_ZOOM,
    MIN_PANEL_WIDTH,
    MIN_ZOOM,
    SELECTED_COLOUR,
    _form,
)
from citygen.layers import PALETTES
from citygen.model import MAX_SEED

from . import __version__, files
from .drawing import build_layers
from .editing import SiteEditor
from .generate import HOME_STYLES, KIND_NAMES, KINDS, generate
from .site import KIND_NAMES as PIECE_NAMES
from .site import bounds

APP_NAME = "Fantasy Location Generator"

HANDLE_PIXELS = 5  # Half the size of a resize or point handle.
GRAB_PIXELS = 8  # How close the pointer must be to grab a handle.
TURN_HANDLE_PIXELS = 26  # How far above the selection its turn handle sits.
PICK_PIXELS = 3  # Extra reach when picking a piece.
TURN_STEP = 15  # Degrees for each press of a turn key.
SNAP = 15  # Degrees that turning snaps to with Shift held.
NUDGE = 0.5  # Map units an arrow key moves the selection.

# The pieces the Add buttons make, in the order they're shown.
ADDABLE = ("building", "gnome_home", "yard", "well", "field", "orchard",
           "meadow", "pond", "wood", "tree", "road", "track", "river",
           "bridge", "hedge", "wall", "gate")

# The resize handles round a piece's own box, as (hx, hy).
RESIZE_HANDLES = [(hx, hy) for hy in (-1, 0, 1) for hx in (-1, 0, 1)
                  if (hx, hy) != (0, 0)]


class SiteView(QWidget):
    """The location. Click to select, Shift-click to add to the selection,
    and drag open ground to select everything in a box. Drag a selection to
    move it, its round handle to turn it and the square handles to resize or
    reshape it. Drag with the right or middle button, or with Space held, to
    pan, and scroll to zoom."""

    hovered = Signal(str)
    selection_changed = Signal()
    edited = Signal()

    def __init__(self):
        super().__init__()
        self.setMouseTracking(True)
        self.setMinimumSize(400, 400)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.site = None
        self.editor = None
        self.palette_colours = PALETTES["Default"]
        self.prepared = []
        self.extent = 50.0
        self.zoom = 1.0
        self.pan = QPointF(0, 0)
        self.selection = []
        self.reshaping = False
        self.show_scale_bar = True
        self.space_held = False
        self.hover_text = ""
        self.hover_position = QPointF(0, 0)
        # What a drag is doing, and what it needs to remember.
        self.mode = None
        self.drag_from = None
        self.last_spot = None
        self.band = None
        self.originals = []
        self.handle = None
        self.turn_centre = None
        self.turn_from = 0.0

    def set_site(self, site, palette, reset_view=True):
        self.site = site
        self.editor = SiteEditor(site)
        self.palette_colours = palette
        self.reshaping = False
        self.select([])
        if reset_view:
            self.extent = site.extent()
            self.reset_view()
        self.refresh()

    def set_palette(self, palette):
        self.palette_colours = palette
        self.refresh()

    def refresh(self):
        self.prepared = qt_render.prepare_layers(
            build_layers(self.site, self.palette_colours))
        self.update()

    def select(self, pieces):
        pieces = list(pieces)
        if [id(p) for p in pieces] != [id(p) for p in self.selection]:
            self.selection = pieces
            if len(pieces) != 1:
                self.reshaping = False
            self.selection_changed.emit()
        self.update()

    def reset_view(self):
        self.zoom = 1.0
        self.pan = QPointF(0, 0)
        self.update()

    # Map and window positions.

    def _transform(self):
        scale = self.zoom * min(self.width(), self.height()) / (self.extent * 2)
        transform = QTransform()
        transform.translate(self.width() / 2 + self.pan.x(),
                            self.height() / 2 + self.pan.y())
        transform.scale(scale, scale)
        return transform

    def _scale(self):
        return self._transform().m11()

    def spot(self, position):
        """The place on the map under a position in the window."""
        inverse, _ = self._transform().inverted()
        point = inverse.map(QPointF(position))
        return point.x(), point.y()

    def window_point(self, x, y):
        return self._transform().map(QPointF(x, y))

    def centre_spot(self):
        return self.spot(QPointF(self.width() / 2, self.height() / 2))

    # Handles.

    def single(self):
        return self.selection[0] if len(self.selection) == 1 else None

    def shows_points(self):
        piece = self.single()
        return piece is not None and (piece.is_line or (
            self.reshaping and piece.is_area))

    def resize_handles(self):
        """Where each resize handle is on the map, as {(hx, hy): (x, y)}."""
        piece = self.single()
        if piece is None or piece.is_line or self.shows_points():
            return {}
        left, top, right, bottom = piece.local_box()
        middle_x = (left + right) / 2
        middle_y = (top + bottom) / 2
        found = {}
        for hx, hy in RESIZE_HANDLES:
            if piece.is_round and 0 in (hx, hy):
                continue
            x = {-1: left, 0: middle_x, 1: right}[hx]
            y = {-1: top, 0: middle_y, 1: bottom}[hy]
            found[hx, hy] = piece.to_map(x, y)
        return found

    def selection_box(self):
        """The box round the selection on the map."""
        return bounds(self.selection) if self.selection else None

    def turn_handle(self):
        """Where the handle for turning the selection is, in the window."""
        box = self.selection_box()
        if box is None:
            return None
        left, top, right, _ = box
        corner = self.window_point((left + right) / 2, top)
        return QPointF(corner.x(), corner.y() - TURN_HANDLE_PIXELS)

    def _near(self, position, point, pixels=GRAB_PIXELS):
        gap = position - point
        return math.hypot(gap.x(), gap.y()) <= pixels

    # Drawing.

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colours = self.palette_colours
        painter.fillRect(self.rect(), QColor(colours.paper))
        if self.site is None:
            return
        painter.setTransform(self._transform())
        qt_render.paint(painter, self.prepared)
        painter.resetTransform()
        self._paint_selection(painter)
        if self.band is not None:
            pen = QPen(QColor(SELECTED_COLOUR), 1, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            fill = QColor(SELECTED_COLOUR)
            fill.setAlpha(30)
            painter.setBrush(fill)
            painter.drawRect(QRectF(self.drag_from, self.band).normalized())
        if self.show_scale_bar:
            qt_render.paint_scale_bar(painter, colours, 16, self.height() - 14,
                                      self._scale(), 160, 12)
        if self.hover_text and self.mode is None:
            self._paint_label(painter, colours)

    def _paint_selection(self, painter):
        if not self.selection:
            return
        blue = QColor(SELECTED_COLOUR)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(blue, 2))
        for piece in self.selection:
            if piece.is_round:
                centre = self.window_point(piece.x, piece.y)
                radius = piece.radius * self._scale()
                painter.drawEllipse(centre, radius, radius)
            else:
                points = [self.window_point(x, y) for x, y in piece.world()]
                if piece.is_line:
                    painter.drawPolyline(QPolygonF(points))
                else:
                    painter.drawPolygon(QPolygonF(points))

        # The box round the selection, and the handle that turns it.
        painter.setPen(QPen(blue, 1, Qt.PenStyle.DashLine))
        piece = self.single()
        left, top, right, bottom = self.selection_box()
        if piece is not None and not piece.is_line:
            corners = piece.box_corners()
        else:
            corners = [(left, top), (right, top), (right, bottom),
                       (left, bottom)]
        painter.drawPolygon(QPolygonF([self.window_point(x, y)
                                       for x, y in corners]))
        turn = self.turn_handle()
        painter.setPen(QPen(blue, 1))
        painter.drawLine(turn, self.window_point((left + right) / 2, top))
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(turn, HANDLE_PIXELS + 1, HANDLE_PIXELS + 1)

        painter.setPen(QPen(blue, 1))
        painter.setBrush(QColor("#ffffff"))
        for x, y in self.resize_handles().values():
            centre = self.window_point(x, y)
            painter.drawRect(QRectF(centre.x() - HANDLE_PIXELS,
                                    centre.y() - HANDLE_PIXELS,
                                    HANDLE_PIXELS * 2, HANDLE_PIXELS * 2))
        if self.shows_points():
            painter.setBrush(blue)
            for x, y in self.single().world():
                painter.drawEllipse(self.window_point(x, y), HANDLE_PIXELS,
                                    HANDLE_PIXELS)

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

    # The pointer.

    def wheelEvent(self, event):
        if self.site is None:
            return
        steps = event.angleDelta().y()
        new_zoom = max(MIN_ZOOM, min(MAX_ZOOM, self.zoom * 1.0015 ** steps))
        centre = QPointF(self.width() / 2, self.height() / 2) + self.pan
        cursor = event.position()
        self.pan += (cursor - centre) * (1 - new_zoom / self.zoom)
        self.zoom = new_zoom
        self.update()

    def _point_at(self, position):
        """Which point of the selected piece is under the pointer."""
        if not self.shows_points():
            return None
        x, y = self.spot(position)
        return self.editor.point_at(self.single(), x, y,
                                    GRAB_PIXELS / self._scale())

    def _resize_handle_at(self, position):
        for handle, (x, y) in self.resize_handles().items():
            if self._near(position, self.window_point(x, y)):
                return handle
        return None

    def piece_under(self, position):
        x, y = self.spot(position)
        return self.editor.piece_at(x, y, PICK_PIXELS / self._scale())

    def mousePressEvent(self, event):
        if self.site is None:
            return
        position = event.position()
        self.drag_from = position
        self.last_spot = self.spot(position)
        button = event.button()
        if button == Qt.MouseButton.RightButton:
            index = self._point_at(position)
            if index is not None:
                if self.editor.remove_point(self.single(), index):
                    self._changed()
                return
        if (button in (Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton)
                or self.space_held):
            self.mode = "pan"
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if button != Qt.MouseButton.LeftButton:
            return

        turn = self.turn_handle()
        if turn is not None and self._near(position, turn):
            self.mode = "turn"
            left, top, right, bottom = self.selection_box()
            self.turn_centre = ((left + right) / 2, (top + bottom) / 2)
            self.turn_from = self._angle_to(position)
            self.originals = [piece.copy() for piece in self.selection]
            return
        index = self._point_at(position)
        if index is not None:
            self.mode = "point"
            self.handle = index
            return
        handle = self._resize_handle_at(position)
        if handle is not None:
            self.mode = "resize"
            self.handle = handle
            self.originals = [self.single().copy()]
            return

        piece = self.piece_under(position)
        adding = bool(event.modifiers() & (Qt.KeyboardModifier.ShiftModifier
                                           | Qt.KeyboardModifier.ControlModifier
                                           | Qt.KeyboardModifier.MetaModifier))
        if piece is None:
            if not adding:
                self.select([])
            self.mode = "band"
            self.band = position
            self.originals = list(self.selection) if adding else []
            return
        if adding:
            if any(p is piece for p in self.selection):
                self.select([p for p in self.selection if p is not piece])
                return
            self.select(self.selection + [piece])
        elif not any(p is piece for p in self.selection):
            self.select([piece])
        self.mode = "move"

    def _angle_to(self, position):
        cx, cy = self.turn_centre
        x, y = self.spot(position)
        return math.atan2(y - cy, x - cx)

    def mouseMoveEvent(self, event):
        if self.site is None:
            return
        position = event.position()
        x, y = self.spot(position)
        if self.mode == "pan":
            self.pan += position - self.drag_from
            self.drag_from = position
            self.update()
            return
        if self.mode == "band":
            self.band = position
            self.update()
            return
        if self.mode == "move":
            lx, ly = self.last_spot
            self.editor.move(self.selection, x - lx, y - ly)
            self.last_spot = (x, y)
            self.refresh()
            return
        if self.mode == "turn":
            turn = self._angle_to(position) - self.turn_from
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                step = math.radians(SNAP)
                turn = round(turn / step) * step
            for piece, original in zip(self.selection, self.originals):
                piece.x, piece.y, piece.angle = (original.x, original.y,
                                                 original.angle)
            self.editor.rotate(self.selection, turn, *self.turn_centre)
            self.refresh()
            return
        if self.mode == "resize":
            self.editor.resize(self.single(), self.originals[0], self.handle,
                               x, y)
            self.refresh()
            return
        if self.mode == "point":
            self.editor.move_point(self.single(), self.handle, x, y)
            self.refresh()
            return
        self._hover(position)

    def _hover(self, position):
        turn = self.turn_handle()
        if turn is not None and self._near(position, turn):
            cursor = Qt.CursorShape.CrossCursor
        elif (self._point_at(position) is not None
              or self._resize_handle_at(position) is not None):
            cursor = Qt.CursorShape.SizeAllCursor
        elif self.space_held:
            cursor = Qt.CursorShape.OpenHandCursor
        else:
            cursor = Qt.CursorShape.ArrowCursor
        self.setCursor(cursor)
        piece = self.piece_under(position)
        text = piece.label if piece is not None else ""
        self.hover_position = position
        if text != self.hover_text:
            self.hover_text = text
            self.hovered.emit(text)
        if text:
            self.update()

    def mouseReleaseEvent(self, event):
        mode = self.mode
        self.mode = None
        if mode == "band":
            left, top = self.spot(QRectF(self.drag_from, self.band)
                                  .normalized().topLeft())
            right, bottom = self.spot(QRectF(self.drag_from, self.band)
                                      .normalized().bottomRight())
            found = self.editor.pieces_in(left, top, right, bottom)
            kept = self.originals + [p for p in found if not any(
                p is q for q in self.originals)]
            self.band = None
            self.select(kept)
        elif mode in ("move", "turn", "resize", "point"):
            moved = mode != "move" or self.last_spot != self.spot(
                self.drag_from)
            if moved:
                self.edited.emit()
        self.originals = []
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()

    def mouseDoubleClickEvent(self, event):
        """Add a corner or bend to the selected piece, or else switch a
        piece's corners on for reshaping, or reset the view."""
        position = event.position()
        piece = self.single()
        if piece is not None and self.shows_points():
            x, y = self.spot(position)
            index = self.editor.edge_at(piece, x, y,
                                        GRAB_PIXELS / self._scale())
            if index is not None and self._point_at(position) is None:
                self.editor.insert_point(piece, index, x, y)
                self._changed()
                return
        under = self.piece_under(position)
        if under is not None:
            self.select([under])
            if under.is_area:
                self.set_reshaping(not self.reshaping)
            return
        self.reset_view()

    def set_reshaping(self, on):
        on = bool(on) and self.single() is not None and self.single().is_area
        if on != self.reshaping:
            self.reshaping = on
            self.selection_changed.emit()
            self.update()

    def _changed(self):
        self.refresh()
        self.edited.emit()

    def leaveEvent(self, event):
        if self.hover_text:
            self.hover_text = ""
            self.hovered.emit("")
            self.update()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self.space_held = True
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self.space_held = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            return
        super().keyReleaseEvent(event)

    # Changes from the window's buttons and keys.

    def turn_selection(self, degrees):
        if not self.selection:
            return
        left, top, right, bottom = self.selection_box()
        self.editor.rotate(self.selection, math.radians(degrees),
                           (left + right) / 2, (top + bottom) / 2)
        self._changed()

    def nudge(self, dx, dy):
        if self.selection:
            self.editor.move(self.selection, dx, dy)
            self._changed()

    def delete_selection(self):
        if self.selection:
            self.editor.delete(self.selection)
            self.select([])
            self._changed()

    def add_piece(self, kind):
        x, y = self.centre_spot()
        piece = self.editor.add(kind, x, y)
        self.select([piece])
        self._changed()
        return piece


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.resize(1100, 820)
        self.site = None
        self.changed = False
        self.built_state = None

        self.view = SiteView()
        self.view.hovered.connect(self._show_hovered)
        self.view.selection_changed.connect(self._update_selection_controls)
        self.view.edited.connect(self._edited)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self.view)
        panel = self._build_side_panel()
        splitter.addWidget(panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([1, panel.minimumWidth()])
        self.splitter = splitter
        self.side_panel = panel
        self.setCentralWidget(splitter)

        self._build_menu()
        for key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            QShortcut(QKeySequence(key), self, self._return_pressed)
        self.location_label = QLabel()
        self.statusBar().addPermanentWidget(self.location_label)

        self.new_location()

    # Building the window.

    def _build_side_panel(self):
        controls = self._build_controls()
        scroller = QScrollArea()
        scroller.setWidget(controls)
        scroller.setWidgetResizable(True)
        scroller.setFrameShape(QFrame.Shape.NoFrame)
        scroller.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(6, 0, 6, 8)
        layout.setSpacing(4)
        layout.addWidget(scroller, 1)

        file_box = QGroupBox("File")
        grid = QGridLayout(file_box)
        grid.setVerticalSpacing(FORM_SPACING)
        grid.setContentsMargins(8, 4, 8, 4)
        for i, (text, tip, handler) in enumerate((
                ("Open...", "Open a saved location (Ctrl+O)", self.open_json),
                ("Save...", "Save the location to open again later (Ctrl+S)",
                 self.save_json),
                ("Export PNG...", "Save the map as a picture (Ctrl+E)",
                 self.export_png),
                ("Export SVG...", "Save the map as a drawing that scales "
                                  "(Ctrl+Shift+E)", self.export_svg))):
            button = QPushButton(text)
            button.setToolTip(tip)
            button.clicked.connect(handler)
            grid.addWidget(button, i // 2, i % 2)
        file_box.setSizePolicy(QSizePolicy.Policy.Preferred,
                               QSizePolicy.Policy.Fixed)
        layout.addWidget(file_box)

        scrollbar = scroller.verticalScrollBar().sizeHint().width()
        width = max(controls.minimumSizeHint().width() + scrollbar,
                    file_box.minimumSizeHint().width()) + 12
        panel.setMinimumWidth(max(width, MIN_PANEL_WIDTH))
        return panel

    def _build_controls(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)

        new_button = QPushButton("New location")
        new_button.setToolTip("A new seed for this kind of location (Return)")
        new_button.clicked.connect(self.new_location)
        layout.addWidget(new_button)

        location_box = QGroupBox("Location")
        form = _form(location_box)
        self.kind_box = QComboBox()
        for kind in KINDS:
            self.kind_box.addItem(KIND_NAMES[kind], kind)
        self.kind_box.setToolTip("What kind of place to lay out")
        self.homes_box = QComboBox()
        for style in HOME_STYLES:
            self.homes_box.addItem(style.capitalize(), style)
        self.homes_box.setToolTip(
            "Whether the main house is a plain building or a gnome home")
        self.seed_box = QSpinBox()
        self.seed_box.setRange(1, MAX_SEED)
        self.seed_box.setKeyboardTracking(False)
        self.seed_box.setToolTip(
            "The same seed and settings give the same location")
        form.addRow("Kind", self.kind_box)
        form.addRow("Homes", self.homes_box)
        form.addRow("Seed", self.seed_box)
        self.kind_box.currentIndexChanged.connect(self.build)
        self.homes_box.currentIndexChanged.connect(self.build)
        self.seed_box.valueChanged.connect(self.build)
        layout.addWidget(location_box)

        add_box = QGroupBox("Add")
        grid = QGridLayout(add_box)
        grid.setVerticalSpacing(FORM_SPACING)
        self.add_buttons = {}
        for i, kind in enumerate(ADDABLE):
            button = QPushButton(PIECE_NAMES[kind])
            button.setToolTip(f"Add a {PIECE_NAMES[kind].lower()} in the "
                              "middle of the view")
            button.clicked.connect(
                lambda checked=False, k=kind: self.add_piece(k))
            grid.addWidget(button, i // 2, i % 2)
            self.add_buttons[kind] = button
        layout.addWidget(add_box)

        selection_box = QGroupBox("Selection")
        grid = QGridLayout(selection_box)
        grid.setVerticalSpacing(FORM_SPACING)
        self.selection_label = QLabel()
        self.selection_label.setWordWrap(True)
        grid.addWidget(self.selection_label, 0, 0, 1, 2)
        self.turn_left_button = QPushButton(f"Turn left {TURN_STEP}\N{DEGREE SIGN}")
        self.turn_left_button.setToolTip("Turn the selection anticlockwise ([)")
        self.turn_left_button.clicked.connect(
            lambda: self.view.turn_selection(-TURN_STEP))
        self.turn_right_button = QPushButton(
            f"Turn right {TURN_STEP}\N{DEGREE SIGN}")
        self.turn_right_button.setToolTip("Turn the selection clockwise (])")
        self.turn_right_button.clicked.connect(
            lambda: self.view.turn_selection(TURN_STEP))
        self.reshape_button = QPushButton("Reshape")
        self.reshape_button.setCheckable(True)
        self.reshape_button.setToolTip(
            "Show the corners of the selected area to drag them. Double-click "
            "an edge to add a corner and right-click a corner to remove it (R)")
        self.reshape_button.toggled.connect(self.view.set_reshaping)
        self.delete_button = QPushButton("Delete")
        self.delete_button.setToolTip("Remove the selection (Delete)")
        self.delete_button.clicked.connect(self.view.delete_selection)
        for i, button in enumerate((self.turn_left_button,
                                    self.turn_right_button,
                                    self.reshape_button, self.delete_button)):
            grid.addWidget(button, 1 + i // 2, i % 2)
        layout.addWidget(selection_box)

        style_box = QGroupBox("Style")
        self.palette_box = QComboBox()
        self.palette_box.addItems(PALETTES)
        self.palette_box.currentTextChanged.connect(
            lambda: self.view.set_palette(self.palette()))
        QVBoxLayout(style_box).addWidget(self.palette_box)
        layout.addWidget(style_box)

        layout.addStretch(1)
        return panel

    def _build_menu(self):
        file_menu = self.menuBar().addMenu("File")
        for text, shortcut, handler in (
                ("Open...", "Ctrl+O", self.open_json),
                ("Save...", "Ctrl+S", self.save_json),
                ("Export PNG...", "Ctrl+E", self.export_png),
                ("Export SVG...", "Ctrl+Shift+E", self.export_svg)):
            action = QAction(text, self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(handler)
            file_menu.addAction(action)

        edit_menu = self.menuBar().addMenu("Edit")
        view = self.view
        for text, shortcuts, handler in (
                ("Select all", ["Ctrl+A"],
                 lambda: view.select(self.site.pieces)),
                ("Select none", ["Esc"], lambda: view.select([])),
                ("Delete", ["Del", "Backspace"], view.delete_selection),
                (f"Turn left {TURN_STEP}\N{DEGREE SIGN}", ["["],
                 lambda: view.turn_selection(-TURN_STEP)),
                (f"Turn right {TURN_STEP}\N{DEGREE SIGN}", ["]"],
                 lambda: view.turn_selection(TURN_STEP)),
                ("Turn left 1\N{DEGREE SIGN}", ["Shift+["],
                 lambda: view.turn_selection(-1)),
                ("Turn right 1\N{DEGREE SIGN}", ["Shift+]"],
                 lambda: view.turn_selection(1)),
                ("Reshape", ["R"], self.reshape_button.toggle)):
            action = QAction(text, self)
            action.setShortcuts([QKeySequence(s) for s in shortcuts])
            # Only on the map, so typing in a box doesn't delete or turn.
            action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
            action.triggered.connect(handler)
            edit_menu.addAction(action)
            view.addAction(action)
        for key, dx, dy in ((Qt.Key.Key_Left, -1, 0), (Qt.Key.Key_Right, 1, 0),
                            (Qt.Key.Key_Up, 0, -1), (Qt.Key.Key_Down, 0, 1)):
            for modifier, step in ((Qt.KeyboardModifier.NoModifier, NUDGE),
                                   (Qt.KeyboardModifier.ShiftModifier,
                                    NUDGE * 10)):
                shortcut = QShortcut(
                    QKeySequence(modifier.value | key.value), self.view,
                    lambda dx=dx, dy=dy, step=step:
                    view.nudge(dx * step, dy * step))
                shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)

        view_menu = self.menuBar().addMenu("View")
        action = QAction("Reset view", self)
        action.setShortcut(QKeySequence("Ctrl+0"))
        action.triggered.connect(view.reset_view)
        view_menu.addAction(action)
        self.scale_bar_action = QAction("Scale bar", self)
        self.scale_bar_action.setCheckable(True)
        self.scale_bar_action.setChecked(True)
        self.scale_bar_action.toggled.connect(self._scale_bar_toggled)
        view_menu.addAction(self.scale_bar_action)

    # Making locations.

    def palette(self):
        return PALETTES[self.palette_box.currentText()]

    def _control_state(self):
        return (self.kind_box.currentIndex(), self.homes_box.currentIndex(),
                self.seed_box.value())

    def _restore_controls(self):
        boxes = (self.kind_box, self.homes_box, self.seed_box)
        for box in boxes:
            box.blockSignals(True)
        kind, homes, seed = self.built_state
        self.kind_box.setCurrentIndex(kind)
        self.homes_box.setCurrentIndex(homes)
        self.seed_box.setValue(seed)
        for box in boxes:
            box.blockSignals(False)

    def _may_discard_changes(self):
        if not self.changed:
            return True
        answer = QMessageBox.question(
            self, APP_NAME,
            "Making a new location will lose the changes you've made. Save "
            "this one first if you want to keep it.\n\nMake a new location "
            "anyway?")
        return answer == QMessageBox.StandardButton.Yes

    def _return_pressed(self):
        if self.seed_box.hasFocus():
            self.seed_box.interpretText()
            self.build()
        else:
            self.new_location()

    def new_location(self):
        if not self._may_discard_changes():
            return
        self.changed = False
        self.seed_box.blockSignals(True)
        self.seed_box.setValue(random.randint(1, MAX_SEED))
        self.seed_box.blockSignals(False)
        self.build()

    def build(self):
        if self._control_state() == self.built_state and not self.changed:
            return
        if not self._may_discard_changes():
            self._restore_controls()
            return
        site = generate(self.kind_box.currentData(), self.seed_box.value(),
                        self.homes_box.currentData())
        self._show(site)
        self.built_state = self._control_state()

    def _show(self, site, changed=False):
        self.site = site
        self.changed = changed
        self.view.set_site(site, self.palette())
        self.location_label.setText(
            f"{KIND_NAMES.get(site.kind, 'Location')}, seed {site.seed}, "
            f"{len(site.pieces)} pieces")
        self._update_selection_controls()

    def _edited(self):
        self.changed = True
        self.location_label.setText(
            f"{KIND_NAMES.get(self.site.kind, 'Location')}, seed "
            f"{self.site.seed}, {len(self.site.pieces)} pieces, changed")
        self._update_selection_controls()

    def add_piece(self, kind):
        self.view.add_piece(kind)
        self.view.setFocus()

    # The selection.

    def _update_selection_controls(self):
        selection = self.view.selection
        piece = self.view.single()
        if not selection:
            text = ("Nothing selected. Click a piece, Shift-click for more, "
                    "or drag across open ground.")
        elif piece is not None:
            text = piece.label
            if piece.is_line:
                text += ". Drag its points. Double-click the line to add a bend."
        else:
            text = f"{len(selection)} pieces selected"
        self.selection_label.setText(text)
        for button in (self.turn_left_button, self.turn_right_button,
                       self.delete_button):
            button.setEnabled(bool(selection))
        self.reshape_button.setEnabled(piece is not None and piece.is_area)
        self.reshape_button.blockSignals(True)
        self.reshape_button.setChecked(self.view.reshaping)
        self.reshape_button.blockSignals(False)

    def _show_hovered(self, text):
        self.statusBar().showMessage(text)

    def _scale_bar_toggled(self, on):
        self.view.show_scale_bar = on
        self.view.update()

    # Files.

    def _default_name(self, extension):
        kind = self.site.kind.replace("_", "-")
        return f"{kind}-{self.site.seed}.{extension}"

    def _ask_path(self, title, extension, description):
        path, _ = QFileDialog.getSaveFileName(
            self, title, self._default_name(extension),
            f"{description} (*.{extension})")
        if path and not path.lower().endswith(f".{extension}"):
            path += f".{extension}"
        return path

    def _save(self, path, save):
        try:
            save()
        except OSError as error:
            QMessageBox.warning(self, APP_NAME,
                                f"Couldn't save the location.\n{error}")
            return False
        self.statusBar().showMessage(f"Saved {path}", 5000)
        return True

    def export_png(self):
        pixels, accepted = QInputDialog.getInt(
            self, "Export PNG", "Width and height in pixels", 3000, 500, 16000,
            500)
        if not accepted:
            return
        path = self._ask_path("Export PNG", "png", "PNG image")
        if path:
            self._save(path, lambda: files.save_png(
                self.site, self.palette(), path, pixels,
                self.view.show_scale_bar))

    def export_svg(self):
        path = self._ask_path("Export SVG", "svg", "SVG image")
        if path:
            self._save(path, lambda: files.save_svg(
                self.site, self.palette(), path, self.view.show_scale_bar))

    def save_json(self):
        path = self._ask_path("Save location", "json", "Location")
        if path and self._save(path, lambda: files.save_json(self.site, path)):
            self.changed = False

    def open_json(self, path=None):
        if not self._may_discard_changes():
            return False
        if not path:
            path, _ = QFileDialog.getOpenFileName(
                self, "Open location", "", "Location (*.json)")
            if not path:
                return False
        try:
            site, made_with = files.load_json(path)
        except files.OpenError as error:
            QMessageBox.warning(self, APP_NAME,
                                f"Couldn't open {path}.\n\n{error}")
            return False
        self.changed = False
        self._show_settings(site)
        self._show(site)
        if made_with and made_with != __version__:
            QMessageBox.information(
                self, APP_NAME,
                f"This location was saved with version {made_with} of the "
                f"app, and this is version {__version__}. It opens as it was "
                "saved, but a new location from the same seed may differ.")
        return True

    def _show_settings(self, site):
        """Set the controls to what a saved location was made with."""
        index = self.kind_box.findData(site.kind)
        if index >= 0:
            self.kind_box.blockSignals(True)
            self.kind_box.setCurrentIndex(index)
            self.kind_box.blockSignals(False)
        self.seed_box.blockSignals(True)
        self.seed_box.setValue(max(1, min(MAX_SEED, site.seed)))
        self.seed_box.blockSignals(False)
        self.built_state = self._control_state()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    window = MainWindow()
    window.show()
    return app.exec()
