"""Drawing the map's layers with Qt, for the screen and for PNG files."""

from dataclasses import replace

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
)

from .layers import build_layers, map_extent

# Qt fills many small paths far faster than one huge one, and a forest can
# have thousands of trees, so its circles are grouped by square of map. Big
# layers of shapes, such as the buildings, are split the same way.
CIRCLE_TILE = 10
SHAPE_TILE = 10
TILE_FROM = 10  # Layers with fewer shapes than this are drawn whole.

_CAPS = {"flat": Qt.PenCapStyle.FlatCap, "round": Qt.PenCapStyle.RoundCap}
_JOINS = {"miter": Qt.PenJoinStyle.MiterJoin, "round": Qt.PenJoinStyle.RoundJoin}


def _tiles(layer):
    """Split a big layer into one layer for each square of map.

    Each shape goes by its first point. Shapes in one layer share a style, so
    drawing them in groups looks the same as drawing them all at once.
    """
    if layer.circles:
        groups = {}
        for circle in layer.circles:
            x, y, _ = circle
            groups.setdefault((x // CIRCLE_TILE, y // CIRCLE_TILE),
                              []).append(circle)
        return [replace(layer, circles=group) for group in groups.values()]

    if len(layer.polygons) + len(layer.polylines) < TILE_FROM:
        return [layer]
    groups = {}
    for kind in ("polygons", "polylines"):
        for shape in getattr(layer, kind):
            x, y = shape[0]
            group = groups.setdefault((x // SHAPE_TILE, y // SHAPE_TILE),
                                      {"polygons": [], "polylines": []})
            group[kind].append(shape)
    return [replace(layer, **group) for group in groups.values()]


def _path(layer):
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.WindingFill)
    for polygon in layer.polygons:
        path.moveTo(*polygon[0])
        for x, y in polygon[1:]:
            path.lineTo(x, y)
        path.closeSubpath()
    for line in layer.polylines:
        path.moveTo(*line[0])
        for x, y in line[1:]:
            path.lineTo(x, y)
    for x, y, r in layer.circles:
        path.addEllipse(QRectF(x - r, y - r, r * 2, r * 2))
    return path


def _pen(layer):
    if layer.stroke is None:
        return QPen(Qt.PenStyle.NoPen)
    pen = QPen(QColor(layer.stroke), layer.width, Qt.PenStyle.SolidLine,
               _CAPS[layer.cap], _JOINS[layer.join])
    pen.setMiterLimit(3)
    return pen


def _brush(layer):
    if layer.fill is None:
        return QBrush(Qt.BrushStyle.NoBrush)
    return QBrush(QColor(layer.fill))


# Layers that editing never changes, so a view can keep them between redraws.
FIXED_LAYERS = frozenset({
    "Furrows", "Forest", "Orchard edges", "Orchards", "Sea", "River",
    "Bridge edges", "Bridges", "Pier edges", "Piers",
})


def _prepare_layer(layer):
    pen = _pen(layer)
    brush = _brush(layer)
    return [(_path(part), pen, brush) for part in _tiles(layer)
            if part.polygons or part.polylines or part.circles]


def prepare(model, palette, kept=None):
    """Turn a city into paths, which Qt can then redraw quickly.

    kept is a dict for the fixed layers, for a view that redraws one city in
    one palette many times as it's edited. The first call fills it, and later
    ones use what it holds instead of making those layers again.
    """
    prepared = []
    for layer in build_layers(model, palette):
        if kept is not None and layer.name in FIXED_LAYERS:
            if layer.name not in kept:
                kept[layer.name] = _prepare_layer(layer)
            prepared += kept[layer.name]
        else:
            prepared += _prepare_layer(layer)
    return prepared


def paint(painter, prepared):
    for path, pen, brush in prepared:
        painter.setPen(pen)
        painter.setBrush(brush)
        painter.drawPath(path)


def save_png(model, palette, path, pixels=3000):
    image = QImage(pixels, pixels, QImage.Format.Format_RGB32)
    image.fill(QColor(palette.paper))

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.translate(pixels / 2, pixels / 2)
    scale = pixels / (map_extent(model) * 2)
    painter.scale(scale, scale)
    paint(painter, prepare(model, palette))
    painter.end()

    if not image.save(str(path), "PNG"):
        raise OSError(f"Couldn't save {path}")
