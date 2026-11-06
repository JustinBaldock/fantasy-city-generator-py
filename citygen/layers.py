"""What a map draws, as plain data, from mapping/CityMap.hx.

The screen, PNG and SVG all draw from these layers, so they match. Nothing in
this module needs Qt.
"""

from dataclasses import dataclass, field

from .wards import (
    AdministrationWard,
    Castle,
    Cathedral,
    CraftsmenWard,
    Farm,
    GateWard,
    Market,
    MAIN_STREET,
    MerchantWard,
    MilitaryWard,
    Park,
    PatriciateWard,
    Slum,
)

NORMAL_STROKE = 0.3
THICK_STROKE = 1.8

_BUILDING_WARDS = (
    Market, CraftsmenWard, MerchantWard, GateWard, Slum, AdministrationWard,
    MilitaryWard, PatriciateWard, Farm,
)


@dataclass(frozen=True)
class Palette:
    paper: int
    light: int
    medium: int
    dark: int


PALETTES = {
    "Default": Palette(0xccc5b8, 0x99948a, 0x67635c, 0x1a1917),
    "Blueprint": Palette(0x455b8d, 0x7383aa, 0xa1abc6, 0xfcfbff),
    "Black and white": Palette(0xffffff, 0xcccccc, 0x888888, 0x000000),
    "Ink": Palette(0xcccac2, 0x9a979b, 0x6c6974, 0x130f26),
    "Night": Palette(0x000000, 0x402306, 0x674b14, 0x99913d),
    "Ancient": Palette(0xccc5a3, 0xa69974, 0x806f4d, 0x342414),
    "Colour": Palette(0xfff2c8, 0xd6a36e, 0x869a81, 0x4c5950),
    "Simple": Palette(0xffffff, 0x000000, 0x000000, 0x000000),
}


@dataclass
class Layer:
    """Shapes that share one style.

    polygons are closed, polylines are open, and each is a list of (x, y).
    circles are (x, y, radius).
    """

    name: str
    fill: int = None
    stroke: int = None
    width: float = 0.0
    cap: str = "round"
    join: str = "miter"
    polygons: list = field(default_factory=list)
    polylines: list = field(default_factory=list)
    circles: list = field(default_factory=list)


def _xy(polygon):
    return [(v.x, v.y) for v in polygon]


def _wall_layers(wall, large, palette, prefix):
    line = Layer(f"{prefix} wall", stroke=palette.dark, width=THICK_STROKE,
                 join="round", polygons=[_xy(wall.shape)])

    gates = Layer(f"{prefix} gates", stroke=palette.dark,
                  width=THICK_STROKE * 2, cap="flat")
    for gate in wall.gates:
        direction = wall.shape.next(gate).subtract(wall.shape.prev(gate))
        direction = direction.norm(THICK_STROKE * 1.5)
        a = gate.subtract(direction)
        b = gate.add(direction)
        gates.polylines.append([(a.x, a.y), (b.x, b.y)])

    radius = THICK_STROKE * (1.5 if large else 1)
    towers = Layer(f"{prefix} towers", fill=palette.dark,
                   circles=[(t.x, t.y, radius) for t in wall.towers])
    return [line, gates, towers]


def build_layers(model, palette):
    """Everything on the map, in drawing order."""
    roads = [_xy(road) for road in model.roads]
    layers = [
        Layer("Road edges", stroke=palette.medium,
              width=MAIN_STREET + NORMAL_STROKE, cap="flat", polylines=roads),
        Layer("Roads", stroke=palette.paper,
              width=MAIN_STREET - NORMAL_STROKE, cap="flat", polylines=roads),
    ]

    buildings = []
    parks = []
    castles = []
    temples = []
    for patch in model.patches:
        ward = patch.ward
        shapes = [_xy(polygon) for polygon in ward.geometry]
        if isinstance(ward, Castle):
            castles += shapes
        elif isinstance(ward, Cathedral):
            temples += shapes
        elif isinstance(ward, _BUILDING_WARDS):
            buildings += shapes
        elif isinstance(ward, Park):
            parks += shapes

    layers.append(Layer("Parks", fill=palette.medium, stroke=palette.medium,
                        width=NORMAL_STROKE, polygons=parks))
    layers.append(Layer("Buildings", fill=palette.light, stroke=palette.dark,
                        width=NORMAL_STROKE, polygons=buildings))

    # A heavy line drawn first, with the fill on top, leaves an outer outline.
    for name, shapes, thickness in (
            ("Castle", castles, NORMAL_STROKE * 2),
            ("Temple", temples, NORMAL_STROKE)):
        layers.append(Layer(f"{name} outline", stroke=palette.dark,
                            width=thickness * 2, polygons=shapes))
        layers.append(Layer(name, fill=palette.light, polygons=shapes))

    if model.wall is not None:
        layers += _wall_layers(model.wall, False, palette, "City")
    if model.citadel is not None:
        layers += _wall_layers(model.citadel.ward.wall, True, palette, "Castle")

    return layers


def map_extent(model):
    """How far the map reaches from its centre, in map units."""
    return model.city_radius * 1.1
