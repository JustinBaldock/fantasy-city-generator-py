"""Drawing the map's layers with Qt, for the screen and for PNG files."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)

from .layers import (
    build_layers,
    compass_rose,
    map_extent,
    scale_bar,
    scale_label,
)

# Qt fills many small paths far faster than one huge one, and a forest can
# have thousands of trees, so its circles are grouped by square of map. Big
# layers of shapes, such as the buildings, are split the same way.
CIRCLE_TILE = 10
SHAPE_TILE = 10
TILE_FROM = 10  # Layers with fewer shapes than this are drawn whole.

_CAPS = {"flat": Qt.PenCapStyle.FlatCap, "round": Qt.PenCapStyle.RoundCap}
_JOINS = {"miter": Qt.PenJoinStyle.MiterJoin, "round": Qt.PenJoinStyle.RoundJoin}


def _tiles(layer):
    """Split a big layer into a group of shapes for each square of map.

    Each shape goes by its first point. Shapes in one layer share a style, so
    drawing them in groups looks the same as drawing them all at once.
    Returns (square, polygons, polylines, circles) for each group.
    """
    if layer.circles:
        groups = {}
        for circle in layer.circles:
            x, y, _ = circle
            groups.setdefault((x // CIRCLE_TILE, y // CIRCLE_TILE),
                              []).append(circle)
        return [(square, (), (), group) for square, group in groups.items()]

    if len(layer.polygons) + len(layer.polylines) < TILE_FROM:
        return [(None, layer.polygons, layer.polylines, ())]
    groups = {}
    for kind, shapes in ((0, layer.polygons), (1, layer.polylines)):
        for shape in shapes:
            x, y = shape[0]
            group = groups.setdefault((x // SHAPE_TILE, y // SHAPE_TILE),
                                      ([], []))
            group[kind].append(shape)
    return [(square, polygons, polylines, ())
            for square, (polygons, polylines) in groups.items()]


def _path(polygons, polylines, circles):
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.WindingFill)
    for polygon in polygons:
        path.moveTo(*polygon[0])
        for x, y in polygon[1:]:
            path.lineTo(x, y)
        path.closeSubpath()
    for line in polylines:
        path.moveTo(*line[0])
        for x, y in line[1:]:
            path.lineTo(x, y)
    for x, y, r in circles:
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


def _contents(polygons, polylines, circles):
    """What a group of shapes holds, to tell whether it has changed.

    Unchanged buildings bring the very same lists each time, which Python
    compares at once, and others are compared point by point.
    """
    return (tuple(polygons), tuple(polylines), tuple(circles))


def _reach(path, layer):
    """The part of the map a path can mark, with room for its outline."""
    # A mitred corner can reach out up to its limit, three times half the
    # line's width, so leave room for that.
    margin = layer.width * 1.5 + 0.05
    return path.controlPointRect().adjusted(-margin, -margin, margin, margin)


def _prepare_layer(layer, drawn=None, changed=None):
    """The layer's paths, one for each square of map, as (path, pen, brush,
    reach), where reach is the part of the map the path can mark.

    drawn holds the paths made last time for each square of this layer, with
    what each held. A square holding just what it held then keeps its path,
    so dragging one building only makes paths again where something moved.
    The parts of the map that changed are added to the list changed.
    """
    pen = _pen(layer)
    brush = _brush(layer)
    prepared = []
    fresh = {}
    if layer.groups is not None:
        # Drawn ward by ward, and a ward is the same until it's edited, so
        # its edit count tells whether it has changed.
        parts = [(ward, (edits,), polygons, polylines, circles)
                 for ward, edits, polygons, polylines, circles in layer.groups]
    else:
        parts = [(square, None, polygons, polylines, circles)
                 for square, polygons, polylines, circles in _tiles(layer)]
    for square, token, polygons, polylines, circles in parts:
        if not (polygons or polylines or circles):
            continue
        if drawn is None:
            path = _path(polygons, polylines, circles)
            reach = _reach(path, layer)
        else:
            contents = (token if token is not None
                        else _contents(polygons, polylines, circles))
            before = drawn.get(square)
            if before is not None and before[0] == contents:
                _, path, reach = before
            else:
                path = _path(polygons, polylines, circles)
                reach = _reach(path, layer)
                if changed is not None:
                    changed.append(reach)
                    if before is not None:
                        changed.append(before[2])
            fresh[square] = (contents, path, reach)
        prepared.append((path, pen, brush, reach))
    if drawn is not None:
        if changed is not None:
            changed += [held[2] for square, held in drawn.items()
                        if square not in fresh]
        drawn.clear()
        drawn.update(fresh)
    return prepared


def prepare_layers(layers):
    """Turn any set of layers into paths that Qt can redraw quickly, as
    (path, pen, brush, reach) for each."""
    prepared = []
    for layer in layers:
        prepared += _prepare_layer(layer)
    return prepared


def prepare(model, palette, kept=None):
    """Turn a city into paths, which Qt can then redraw quickly.

    kept is a dict for a view that redraws one city many times as it's
    edited. It holds the fixed layers whole, and the paths of each square of
    the others. The first call fills it, and later ones use what it holds
    instead of making again what hasn't changed.
    """
    prepared = []
    # What changed since the last call, or None for everything.
    changed = [] if kept else None
    # Drawn ward by ward everywhere, so the window and a PNG match, since
    # where shapes touch, which one is drawn last shows its border whole.
    for layer in build_layers(model, palette, grouped=True):
        if kept is None:
            prepared += _prepare_layer(layer)
        elif layer.name in FIXED_LAYERS:
            # Kept whole until its token says it has changed, as farmland
            # does when a wall is moved over it. Then only the squares that
            # changed are made again.
            held = kept.get(layer.name)
            if held is None or held[0] != layer.token:
                squares = kept.setdefault(("fixed squares", layer.name), {})
                if held is None:
                    changed = None
                held = (layer.token, _prepare_layer(layer, squares, changed))
                kept[layer.name] = held
            prepared += held[1]
        else:
            # The other layers change with editing, but mostly only in a
            # few squares, so each square's path is kept until it changes.
            style = ("squares", layer.name, layer.fill, layer.stroke,
                     layer.width, layer.cap, layer.join)
            if style not in kept:
                changed = None
            prepared += _prepare_layer(layer, kept.setdefault(style, {}),
                                       changed)
    if kept is not None:
        kept["changed"] = changed
    return prepared


def changed_area(kept):
    """The part of the map the last prepare changed, as a QRectF in map
    units, an empty one if nothing changed, or None if it can't say."""
    changed = kept.get("changed")
    if changed is None:
        return None
    area = QRectF()
    for rect in changed:
        area = area.united(rect)
    return area


def paint(painter, prepared, area=None):
    """Draw prepared paths, or only those that reach into an area of the map,
    a QRectF, when redrawing just that part."""
    for path, pen, brush, reach in prepared:
        if area is not None and not reach.intersects(area):
            continue
        painter.setPen(pen)
        painter.setBrush(brush)
        painter.drawPath(path)


def paint_scale_bar(painter, palette, left, bottom, per_unit, most, size):
    """A scale bar with its bottom left corner at a point, in pixels.

    per_unit is pixels for each map unit, most the longest the bar may be,
    and size the height of its lettering.
    """
    metres, length = scale_bar(per_unit, most)
    height = size * 0.45
    top = bottom - height
    dark = QColor(palette.dark)
    painter.save()
    # A pale backing keeps it readable over forest or sea.
    backing = QColor(palette.paper)
    backing.setAlpha(215)
    pad = size * 0.5
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(backing)
    painter.drawRoundedRect(QRectF(left - size - pad / 2, top - size * 1.3 - pad,
                                   length + size * 2 + pad * 3,
                                   height + size * 1.3 + pad * 2),
                            pad, pad)
    painter.setPen(QPen(dark, max(1.0, size / 12)))
    for part in range(4):
        painter.setBrush(dark if part % 2 == 0 else QColor(palette.paper))
        painter.drawRect(QRectF(left + length * part / 4, top, length / 4,
                                height))
    font = QFont(painter.font())
    font.setPixelSize(max(6, round(size)))
    painter.setFont(font)
    painter.setPen(dark)
    gap = size * 0.3
    painter.drawText(QRectF(left - size, top - size - gap, size * 2, size),
                     Qt.AlignmentFlag.AlignCenter, "0")
    label = scale_label(metres)
    painter.drawText(QRectF(left + length - size * 4, top - size - gap,
                            size * 8, size),
                     Qt.AlignmentFlag.AlignCenter, label)
    painter.restore()


def paint_compass(painter, palette, cx, cy, radius, bearing):
    """A compass rose centred on a point, in pixels, with north bearing
    degrees clockwise from straight up."""
    shapes, letters = compass_rose(bearing)
    dark = QColor(palette.dark)
    painter.save()
    backing = QColor(palette.paper)
    backing.setAlpha(215)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(backing)
    painter.drawEllipse(QPointF(cx, cy), radius * 1.62, radius * 1.62)
    pen = QPen(dark, max(1.0, radius / 30))
    pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
    painter.setPen(pen)
    for points, shaded in shapes:
        painter.setBrush(dark if shaded else QColor(palette.paper))
        painter.drawPolygon(QPolygonF([QPointF(cx + x * radius, cy + y * radius)
                                       for x, y in points]))
    font = QFont(painter.font())
    font.setPixelSize(max(6, round(radius * 0.36)))
    for letter, x, y in letters:
        font.setBold(letter == "N")
        painter.setFont(font)
        box = QRectF(cx + x * radius - radius, cy + y * radius - radius,
                     radius * 2, radius * 2)
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, letter)
    painter.restore()


def compass_place(width, height, size):
    """Where the compass goes, its centre and radius, in the top right
    corner of a picture."""
    radius = size
    margin = radius * 1.75
    return width - margin, margin, radius


def save_layers_png(layers, extent, palette, path, pixels=3000,
                    show_scale_bar=True, rotation=0, compass=None):
    """Any set of layers as a square PNG, showing extent map units round the
    centre each way.

    rotation turns the map clockwise by that many degrees, and compass, if
    given, is the bearing of north on the map, for a compass rose that
    turns with it.
    """
    image = QImage(pixels, pixels, QImage.Format.Format_RGB32)
    image.fill(QColor(palette.paper))

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.translate(pixels / 2, pixels / 2)
    painter.rotate(rotation)
    scale = pixels / (extent * 2)
    painter.scale(scale, scale)
    paint(painter, prepare_layers(layers))
    painter.resetTransform()
    if show_scale_bar:
        margin = pixels * 0.03
        paint_scale_bar(painter, palette, margin, pixels - margin, scale,
                        pixels * 0.2, pixels * 0.018)
    if compass is not None:
        cx, cy, radius = compass_place(pixels, pixels, pixels * 0.035)
        paint_compass(painter, palette, cx, cy, radius, compass + rotation)
    painter.end()

    if not image.save(str(path), "PNG"):
        raise OSError(f"Couldn't save {path}")


def save_png(model, palette, path, pixels=3000, show_scale_bar=True,
             rotation=0, compass=None):
    save_layers_png(build_layers(model, palette, grouped=True),
                    map_extent(model), palette, path, pixels, show_scale_bar,
                    rotation, compass)
