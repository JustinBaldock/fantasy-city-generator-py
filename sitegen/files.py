"""Saving and opening locations as JSON, and exporting them as SVG or PNG.

PNG needs Qt, so it's only imported when asked for.
"""

import json
import math

from citygen.export import layers_to_svg

from . import __version__
from .drawing import build_layers
from .generate import KIND_NAMES
from .site import KINDS, Piece, Site

FORMAT = "fantasy-location"
FORMAT_VERSION = 1


class OpenError(ValueError):
    """A file that isn't a location this app can open."""


def _round(values, places=4):
    return [[round(x, places), round(y, places)] for x, y in values]


def site_to_dict(site):
    """The location as plain data. Angles are in degrees."""
    pieces = []
    for piece in site.pieces:
        data = {"kind": piece.kind, "label": piece.label,
                "x": round(piece.x, 4), "y": round(piece.y, 4),
                "angle": round(math.degrees(piece.angle), 4)}
        if piece.is_round:
            data["radius"] = round(piece.radius, 4)
        else:
            data["points"] = _round(piece.points)
        if piece.kind in ("wood", "orchard"):
            data["seed"] = piece.seed
        if piece.joins:
            data["joins"] = [list(pair) for pair in piece.joins]
        pieces.append(data)
    return {"format": FORMAT, "format_version": FORMAT_VERSION,
            "app_version": __version__, "kind": site.kind, "seed": site.seed,
            "pieces": pieces}


def site_from_dict(data):
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise OpenError("This isn't a location saved by the Fantasy Location "
                        "Generator.")
    if data.get("format_version", 0) > FORMAT_VERSION:
        raise OpenError("This location was saved by a newer version of the "
                        "app. Update the app to open it.")
    pieces = []
    try:
        for item in data["pieces"]:
            if item["kind"] not in KINDS:
                raise OpenError(f"Unknown kind of piece {item['kind']!r}.")
            pieces.append(Piece(
                item["kind"], float(item["x"]), float(item["y"]),
                math.radians(float(item.get("angle", 0.0))),
                [(float(x), float(y)) for x, y in item.get("points", [])],
                float(item.get("radius", 0.0)), item.get("label", ""),
                int(item.get("seed", 0)),
                [tuple(int(i) for i in pair) for pair in item.get("joins", [])]))
        return Site(data.get("kind", "farm"), int(data.get("seed", 1)), pieces)
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, OpenError):
            raise
        raise OpenError(f"The file is damaged ({error}).") from error


def save_json(site, path):
    with open(path, "w", encoding="utf-8") as file:
        json.dump(site_to_dict(site), file, indent=1)
        file.write("\n")


def load_json(path):
    """The location in a file, and the version of the app that saved it."""
    try:
        with open(path, encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OpenError(f"Couldn't read the file ({error}).") from error
    return site_from_dict(data), data.get("app_version")


def title(site):
    return f"{KIND_NAMES.get(site.kind, 'Location')}, seed {site.seed}"


def site_to_svg(site, palette, pixels=2000, show_scale_bar=True):
    return layers_to_svg(build_layers(site, palette), site.extent(), palette,
                         title(site), pixels, show_scale_bar)


def save_svg(site, palette, path, show_scale_bar=True):
    with open(path, "w", encoding="utf-8") as file:
        file.write(site_to_svg(site, palette, show_scale_bar=show_scale_bar))


def save_png(site, palette, path, pixels=3000, show_scale_bar=True):
    from citygen.qt_render import save_layers_png
    save_layers_png(build_layers(site, palette), site.extent(), palette, path,
                    pixels, show_scale_bar)
