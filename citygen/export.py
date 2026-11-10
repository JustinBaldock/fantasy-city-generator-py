"""Saving a city as JSON or SVG. PNG is in qt_render, since it needs Qt."""

import json
from xml.sax.saxutils import escape

from .layers import build_layers, map_extent, scale_bar, scale_label
from .plots import Plot
from .streets import ways
from .model import size_name

JSON_FORMAT_VERSION = 12


def _xy(polygon):
    return [[round(v.x, 3), round(v.y, 3)] for v in polygon]


def _wall(wall):
    return {
        "shape": _xy(wall.shape),
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
        "wall": _wall(model.wall) if model.wall is not None else None,
        "castle_wall": (_wall(model.citadel.ward.wall)
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


def city_to_svg(model, palette, pixels=2000, show_scale_bar=True):
    extent = map_extent(model)
    side = extent * 2
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{pixels}" '
        f'height="{pixels}" viewBox="{-extent:.3f} {-extent:.3f} '
        f'{side:.3f} {side:.3f}">',
        f'<title>{escape(size_name(model.size))}, seed {model.seed}</title>',
        f'<rect x="{-extent:.3f}" y="{-extent:.3f}" width="{side:.3f}" '
        f'height="{side:.3f}" fill="{_colour(palette.paper)}"/>',
    ]
    for layer in build_layers(model, palette):
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


def save_svg(model, palette, path, show_scale_bar=True):
    with open(path, "w", encoding="utf-8") as file:
        file.write(city_to_svg(model, palette,
                               show_scale_bar=show_scale_bar))
