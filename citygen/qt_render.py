"""Drawing the map's layers with Qt, for the screen and for PNG files."""

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

_CAPS = {"flat": Qt.PenCapStyle.FlatCap, "round": Qt.PenCapStyle.RoundCap}
_JOINS = {"miter": Qt.PenJoinStyle.MiterJoin, "round": Qt.PenJoinStyle.RoundJoin}


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


def prepare(model, palette):
    """Turn a city into paths, which Qt can then redraw quickly."""
    return [
        (_path(layer), _pen(layer), _brush(layer))
        for layer in build_layers(model, palette)
        if layer.polygons or layer.polylines or layer.circles
    ]


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
