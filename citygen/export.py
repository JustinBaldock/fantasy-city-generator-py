"""Saving a city as JSON or SVG. PNG is in qt_render, since it needs Qt."""

import json
import math
from xml.sax.saxutils import escape

from . import __version__
from .geometry import Point

from .layers import build_layers, map_extent, scale_bar, scale_label
from .plots import Plot
from .streets import ways
from .model import Model, size_name

JSON_FORMAT_VERSION = 14


def _xy(polygon):
    return [[round(v.x, 3), round(v.y, 3)] for v in polygon]


def _wall(wall, model):
    return {
        "shape": _xy(wall.shape),
        # Corners added by editing, by their place in shape.
        "added": [i for i, v in enumerate(wall.shape)
                  if id(v) not in model.built_corners],
        "gates": _xy(wall.gates),
        "towers": _xy(wall.towers),
    }


def _building(polygon):
    return polygon.house if isinstance(polygon, Plot) else polygon


def city_to_dict(model):
    """The city as plain data. This is this app's own format.

    plots lines up with buildings, giving the border of each building's plot,
    or None for a building that has no plot of its own.
    """
    road_lines, street_lines, wall_streets = ways(model)

    def lines(found):
        return [[[round(x, 3), round(y, 3)] for x, y in line]
                for line in found]

    wards = []
    for patch in model.patches:
        wards.append({
            "type": type(patch.ward).__name__,
            "label": patch.ward.label,
            "within_city": patch.within_city,
            "within_walls": patch.within_walls,
            "shape": _xy(patch.shape),
            "buildings": [_xy(_building(b)) for b in patch.ward.geometry],
            "plots": [_xy(b) if isinstance(b, Plot) else None
                      for b in patch.ward.geometry],
            "garden_trees": [[round(x, 2), round(y, 2), round(r, 2)]
                             for b in patch.ward.geometry
                             if isinstance(b, Plot) for x, y, r in b.trees],
            "landmarks": [_xy(b) for b in patch.ward.landmarks],
        })

    return {
        "format": "fantasy-city-generator",
        "version": JSON_FORMAT_VERSION,
        # The version of the app that made it.
        "app_version": __version__,
        # What the city was made with. Importing makes it again from these,
        # then puts back any moves and wall changes from the rest.
        "settings": model.settings,
        "seed": model.seed,
        "size": model.size,
        "size_name": size_name(model.size),
        "city_radius": round(model.city_radius, 3),
        "center": [round(model.center.x, 3), round(model.center.y, 3)],
        "has_plaza": model.plaza is not None,
        "home_style": model.home_style,
        "sea_bearing": round(model.sea_bearing, 1) if model.shore else None,
        "shore": _xy(model.shore),
        "river": _xy(model.river),
        "bridges": [_xy(pair) for pair in model.bridges],
        "piers": [_xy(pair) for pair in model.piers],
        "fields": [_xy(plot) for plot in model.fields],
        "trees": [[round(x, 2), round(y, 2), round(r, 2)]
                  for x, y, r in model.trees],
        "field_ratio": round(model.field_ratio, 4),
        "orchard_ratio": model.orchard_ratio,
        "temple_count": model.temple_count,
        "orchards": [_xy(plot) for plot in model.orchards],
        "orchard_trees": [[round(x, 2), round(y, 2), round(r, 2)]
                          for x, y, r in model.orchard_trees],
        "wall": _wall(model.wall, model) if model.wall is not None else None,
        "castle_wall": (_wall(model.citadel.ward.wall, model)
                        if model.citadel is not None else None),
        "streets": [_xy(street) for street in model.streets],
        # The ways as drawn, bent round any moved buildings.
        "drawn_roads": lines(road_lines),
        "drawn_streets": lines(street_lines),
        "wall_streets": lines(wall_streets),
        "roads": [_xy(road) for road in model.roads],
        "wards": wards,
    }


def save_json(model, path):
    with open(path, "w", encoding="utf-8") as file:
        json.dump(city_to_dict(model), file, indent=1)
        file.write("\n")


def _colour(value):
    return f"#{value:06x}"


def _path_data(layer):
    parts = []
    for polygon in layer.polygons:
        points = " L".join(f"{x:.3f} {y:.3f}" for x, y in polygon)
        parts.append(f"M{points} Z")
    for line in layer.polylines:
        points = " L".join(f"{x:.3f} {y:.3f}" for x, y in line)
        parts.append(f"M{points}")
    return " ".join(parts)


def _style(layer):
    style = [f'fill="{_colour(layer.fill)}"' if layer.fill is not None
             else 'fill="none"']
    if layer.stroke is not None:
        cap = "butt" if layer.cap == "flat" else "round"
        style += [
            f'stroke="{_colour(layer.stroke)}"',
            f'stroke-width="{layer.width:.3f}"',
            f'stroke-linecap="{cap}"',
            f'stroke-linejoin="{layer.join}"',
        ]
        if layer.join == "miter":
            style.append('stroke-miterlimit="3"')
    return " ".join(style)


def _svg_scale_bar(extent, palette):
    """A scale bar in the bottom left corner, in map units."""
    side = extent * 2
    metres, length = scale_bar(1.0, side * 0.2)
    size = side * 0.018
    height = size * 0.45
    left = -extent + side * 0.03
    bottom = extent - side * 0.03
    top = bottom - height
    dark = _colour(palette.dark)
    pad = size * 0.5
    parts = [f'<rect x="{left - size - pad / 2:.3f}" '
             f'y="{top - size * 1.3 - pad:.3f}" '
             f'width="{length + size * 2 + pad * 3:.3f}" '
             f'height="{height + size * 1.3 + pad * 2:.3f}" rx="{pad:.3f}" '
             f'fill="{_colour(palette.paper)}" fill-opacity="0.85" '
             f'stroke="none"/>']
    for part in range(4):
        fill = dark if part % 2 == 0 else _colour(palette.paper)
        parts.append(f'<rect x="{left + length * part / 4:.3f}" '
                     f'y="{top:.3f}" width="{length / 4:.3f}" '
                     f'height="{height:.3f}" fill="{fill}"/>')
    text = (f'font-family="sans-serif" font-size="{size:.3f}" '
            f'fill="{dark}" stroke="none" text-anchor="middle"')
    baseline = top - size * 0.3
    parts.append(f'<text x="{left:.3f}" y="{baseline:.3f}" {text}>0</text>')
    parts.append(f'<text x="{left + length:.3f}" y="{baseline:.3f}" {text}>'
                 f'{escape(scale_label(metres))}</text>')
    return (f'<g id="scale-bar" stroke="{dark}" '
            f'stroke-width="{size / 12:.3f}">' + "".join(parts) + "</g>")


def layers_to_svg(layers, extent, palette, title, pixels=2000,
                  show_scale_bar=True):
    """Any set of layers as an SVG, showing extent map units round the
    centre each way. The city and the location generator both use this."""
    side = extent * 2
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{pixels}" '
        f'height="{pixels}" viewBox="{-extent:.3f} {-extent:.3f} '
        f'{side:.3f} {side:.3f}">',
        f'<title>{escape(title)}</title>',
        f'<rect x="{-extent:.3f}" y="{-extent:.3f}" width="{side:.3f}" '
        f'height="{side:.3f}" fill="{_colour(palette.paper)}"/>',
    ]
    for layer in layers:
        if not (layer.polygons or layer.polylines or layer.circles):
            continue
        lines.append(f'<g id="{escape(layer.name.lower().replace(" ", "-"))}" '
                     f'{_style(layer)}>')
        data = _path_data(layer)
        if data:
            lines.append(f'<path d="{data}"/>')
        for x, y, r in layer.circles:
            lines.append(f'<circle cx="{x:.3f}" cy="{y:.3f}" r="{r:.3f}"/>')
        lines.append("</g>")
    if show_scale_bar:
        lines.append(_svg_scale_bar(extent, palette))
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def city_to_svg(model, palette, pixels=2000, show_scale_bar=True):
    return layers_to_svg(build_layers(model, palette), map_extent(model),
                         palette, f"{size_name(model.size)}, seed {model.seed}",
                         pixels, show_scale_bar)


def save_svg(model, palette, path, show_scale_bar=True):
    with open(path, "w", encoding="utf-8") as file:
        file.write(city_to_svg(model, palette,
                               show_scale_bar=show_scale_bar))


class ImportError_(ValueError):
    """A JSON file that can't be opened as a city."""


# The file keeps points to this many places, so a point that rounds to
# what the file says is where it should be.
PLACES = 3
MOVED = 10 ** -PLACES  # For matching towers to corners.

# Parts of the file that are worked out from the rest, so they're left out
# when checking an import came back the same.
_DERIVED = ("version", "app_version", "drawn_roads", "drawn_streets",
            "wall_streets")


def _matches(point, x, y):
    return (round(point.x, PLACES), round(point.y, PLACES)) == (x, y)


def _move(point, x, y):
    if not _matches(point, x, y):
        point.x = x
        point.y = y


def _restore_wall(editor, wall, saved, built):
    """Put back a wall's corners, adding any that editing added."""
    added = set(saved.get("added", []))
    for i, (x, y) in enumerate(saved["shape"]):
        live = wall.shape[i] if i < len(wall.shape) else None
        if i in added and (live is None or id(live) in built):
            # Not there yet, so add it on the edge where it belongs.
            before = wall.shape[i - 1]
            after = wall.shape[i % len(wall.shape)]
            editor._put_corners(before, after, [0.5])
        if i >= len(wall.shape):
            raise ImportError_("A wall in the file doesn't match its town")
        _move(wall.shape[i], x, y)
    if len(wall.shape) != len(saved["shape"]):
        raise ImportError_("A wall in the file doesn't match its town")


def _restore_towers(wall, saved):
    """Put back the towers, including any added, taken off or moved."""
    spare = [t for t in wall.towers if t not in wall.shape]
    towers = []
    for x, y in saved["towers"]:
        corner = next((v for v in wall.shape
                       if abs(v.x - x) <= MOVED and abs(v.y - y) <= MOVED),
                      None)
        if corner is None and spare:
            # A tower beside a river, off the wall's corners.
            corner = min(spare, key=lambda t: math.hypot(t.x - x, t.y - y))
            spare.remove(corner)
            _move(corner, x, y)
        if corner is not None and corner not in towers:
            towers.append(corner)
    wall.towers[:] = towers


def _restore_points(points, saved):
    if len(points) == len(saved):
        for point, (x, y) in zip(points, saved):
            _move(point, x, y)


def _restore_building(polygon, saved, house=None):
    """Put a building where the file has it, with what stands on it.

    Buildings slide, so what stands on one goes the same way. A building
    can also share a corner with a wall, which moves that corner alone.
    """
    if not saved or len(saved) != len(polygon):
        raise ImportError_("A building in the file doesn't match its town")
    if all(_matches(v, x, y) for v, (x, y) in zip(polygon, saved)):
        return
    dx = saved[0][0] - polygon[0].x
    dy = saved[0][1] - polygon[0].y
    carry = getattr(polygon, "carry", None)
    if carry is not None:
        carry(dx, dy)
    # New points, since neighbouring buildings can share them.
    polygon[:] = [Point(x, y) for x, y in saved]
    if house is not None and len(house) == len(polygon.house):
        polygon.house[:] = [Point(x, y) for x, y in house]


def _restore_garden_trees(ward, saved):
    """Put garden trees where the file has them, plot by plot."""
    plots = [p for p in ward.geometry if isinstance(p, Plot)]
    if sum(len(p.trees) for p in plots) != len(saved):
        return
    place = 0
    for plot in plots:
        mine = saved[place:place + len(plot.trees)]
        place += len(plot.trees)
        if any((round(x, 2), round(y, 2), round(r, 2)) != tuple(s)
               for (x, y, r), s in zip(plot.trees, mine)):
            plot.trees = [tuple(s) for s in mine]


def city_from_dict(data):
    """A city made again from exported data, with its edits put back.

    The city is made from its settings, which gives the town as it first
    was, and then the walls, roads and buildings are moved to match the
    file. Returns the city and a list of anything that didn't come back the
    same, which is empty for a file this app saved.
    """
    from .editing import CityEditor

    if data.get("format") != "fantasy-city-generator":
        raise ImportError_("This isn't a city exported from this app")
    settings = data.get("settings")
    if settings is None:
        raise ImportError_(
            "This file was exported by an older version of the app, which "
            "didn't save the settings needed to open it again")

    if data.get("version", 0) > JSON_FORMAT_VERSION:
        raise ImportError_(
            "This file was exported by a newer version of the app. Update "
            "the app to open it")
    try:
        model = Model(**settings)
    except TypeError as error:
        raise ImportError_(
            "This file has settings this version of the app doesn't know. "
            "It may need a newer version") from error
    editor = CityEditor(model)
    built = set(model.built_corners)
    saved_walls = (data.get("wall"), data.get("castle_wall"))
    walls = (model.wall,
             model.citadel.ward.wall if model.citadel is not None else None)
    for wall, saved in zip(walls, saved_walls):
        if (wall is None) != (saved is None):
            raise ImportError_("The file's walls don't match its town")
        if wall is not None:
            _restore_wall(editor, wall, saved, built)
    for wall, saved in zip(walls, saved_walls):
        if wall is not None:
            _restore_towers(wall, saved)

    saved_wards = data.get("wards", [])
    if len(saved_wards) != len(model.patches):
        raise ImportError_("The file's wards don't match its town")
    for patch, saved in zip(model.patches, saved_wards):
        _restore_points(patch.shape, saved["shape"])
    for road, saved in zip(model.roads, data.get("roads", [])):
        _restore_points(road, saved)
    for street, saved in zip(model.streets, data.get("streets", [])):
        _restore_points(street, saved)

    for patch, saved in zip(model.patches, saved_wards):
        ward = patch.ward
        if len(saved["buildings"]) != len(ward.geometry):
            raise ImportError_("A ward in the file doesn't match its town")
        borders = saved.get("plots") or [None] * len(ward.geometry)
        for polygon, border, building in zip(ward.geometry, borders,
                                             saved["buildings"]):
            if border is not None and isinstance(polygon, Plot):
                _restore_building(polygon, border, building)
            else:
                _restore_building(polygon, building)
        _restore_garden_trees(ward, saved.get("garden_trees", []))
        for polygon, landmark in zip(ward.landmarks, saved["landmarks"]):
            _restore_building(polygon, landmark)

    again = city_to_dict(model)
    # A file from an older version may not have every setting this one
    # records, so only the settings it has are compared.
    again["settings"] = {key: value for key, value in again["settings"].items()
                         if key in settings}
    differences = [key for key in data
                   if key not in _DERIVED and again.get(key) != data[key]]
    return model, differences


def load_json(path):
    """Open an exported city.

    Returns the city, anything that didn't come back the same, and the
    version of the app that made the file, or None if it doesn't say.
    """
    try:
        with open(path, encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, ValueError) as error:
        raise ImportError_(f"Couldn't read {path}: {error}") from error
    if not isinstance(data, dict):
        raise ImportError_("This isn't a city exported from this app")
    try:
        model, differences = city_from_dict(data)
    except (TypeError, KeyError, IndexError) as error:
        raise ImportError_("The file is damaged or incomplete") from error
    return model, differences, data.get("app_version")
