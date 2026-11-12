"""What a map draws, as plain data, from mapping/CityMap.hx.

The screen, PNG and SVG all draw from these layers, so they match. Nothing in
this module needs Qt.
"""

import math
from dataclasses import dataclass, field

from . import streets
from .geometry import chaikin
from .gnomes import GnomeHome
from .plots import Green, Plot
from .water import BRIDGE_WIDTH, RIVER_WIDTH
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

# The real size of a map unit, for the scale bar. The original gives none.
# At 4 metres a main street is 8 m across and a burgage plot about 28 m by
# 48 m, which suits a medieval town.
METRES_PER_UNIT = 4.0

NORMAL_STROKE = 0.3
THICK_STROKE = 1.8
PIER_WIDTH = 1.0
PLOT_BORDER = 0.15
FURROW_WIDTH = 0.14
STREET_LINE = 0.3
LINE_ROUNDING = 2

_BUILDING_WARDS = (
    Market, CraftsmenWard, MerchantWard, GateWard, Slum, AdministrationWard,
    MilitaryWard, PatriciateWard, Farm,
)


def _mix(colour_a, colour_b, amount):
    """A colour part way from a to b, for amount from 0 to 1."""
    mixed = 0
    for shift in (16, 8, 0):
        a = (colour_a >> shift) & 255
        b = (colour_b >> shift) & 255
        mixed |= round(a + (b - a) * amount) << shift
    return mixed


@dataclass(frozen=True)
class Palette:
    paper: int
    light: int
    medium: int
    dark: int

    @property
    def water(self):
        return _mix(self.medium, self.paper, 0.2)

    @property
    def green(self):
        return _mix(self.paper, self.light, 0.55)

    @property
    def garden(self):
        return _mix(self.paper, self.light, 0.25)

    @property
    def furrow(self):
        return _mix(self.paper, self.medium, 0.4)

    @property
    def forest(self):
        return _mix(self.medium, self.dark, 0.25)


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
    # When asked for, a layer drawn ward by ward holds its shapes here
    # instead, as (ward, edits, polygons, polylines, circles) for each ward,
    # so a window can redraw only the wards that editing has changed.
    groups: list = None


def _xy(polygon):
    return [(v.x, v.y) for v in polygon]


def _rounded(line):
    return chaikin(line, LINE_ROUNDING)


def _pairs(pairs):
    return [[(a.x, a.y), (b.x, b.y)] for a, b in pairs]


def _wall_line(wall, palette, prefix):
    """The wall, in separate runs where water interrupts it."""
    line = Layer(f"{prefix} wall", stroke=palette.dark, width=THICK_STROKE,
                 join="round")
    shape = _xy(wall.shape)
    count = len(shape)
    if all(wall.segments):
        line.polygons.append(shape)
        return line

    start = wall.segments.index(False)
    run = []
    for step in range(1, count + 1):
        i = (start + step) % count
        if wall.segments[i]:
            run = run or [shape[i]]
            run.append(shape[(i + 1) % count])
        elif run:
            line.polylines.append(run)
            run = []
    if run:
        line.polylines.append(run)
    return line


def _wall_features(wall, large, palette, prefix):
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
    return [gates, towers]


def _ward_drawing(ward):
    """What one ward draws, by the name of the layer it goes in."""
    gardens = []
    garden_trees = []
    room_walls = []
    built = []
    for polygon in ward.geometry:
        if isinstance(polygon, Plot):
            gardens.append(_xy(polygon))
            garden_trees += polygon.trees
            polygon = polygon.house
        if isinstance(polygon, GnomeHome):
            room_walls += _pairs(polygon.room_walls())
        built.append(polygon)
    shapes = [_xy(polygon) for polygon in built]
    drawing = {"Plots": gardens, "Garden trees": garden_trees,
               "Room walls": room_walls,
               "Green trees": [tree for green in ward.geometry
                               if isinstance(green, Green)
                               for tree in green.trees]}
    if isinstance(ward, Castle):
        drawing["Castle"] = shapes
    elif isinstance(ward, Cathedral):
        drawing["Buildings"] = shapes
        drawing["Temple"] = [_xy(polygon) for polygon in ward.landmarks]
    elif isinstance(ward, _BUILDING_WARDS):
        drawing["Buildings"] = shapes
    elif isinstance(ward, Park):
        drawing["Greens"] = shapes
    return drawing


def ward_drawings(model):
    """What each ward draws, as (ward, edits, drawing), in the wards' order.

    They're kept on the model, and a ward is worked out again only when
    editing has changed it since, which is few while dragging.
    """
    kept = model.__dict__.setdefault("_ward_drawings", {})
    found = []
    for patch in model.patches:
        ward = patch.ward
        held = kept.get(ward)
        if held is None or held[1] != ward.edits:
            held = (ward, ward.edits, _ward_drawing(ward))
            kept[ward] = held
        found.append(held)
    return found


def build_layers(model, palette, grouped=False):
    """Everything on the map, in drawing order.

    grouped puts what the wards draw in each layer's groups, ward by ward,
    for a window to redraw only what editing changes.
    """
    road_lines, street_lines, wall_streets = streets.ways(model)
    roads = [_rounded(road) for road in road_lines]
    layers = [
        Layer("Furrows", stroke=palette.furrow, width=FURROW_WIDTH, cap="flat",
              polylines=_pairs(model.furrows)),
        Layer("Forest", fill=palette.forest, circles=model.trees),
        Layer("Orchard edges", stroke=palette.furrow, width=FURROW_WIDTH * 2,
              polygons=[_xy(plot) for plot in model.orchards]),
        Layer("Orchards", fill=palette.forest, circles=model.orchard_trees),
    ]
    if model.sea is not None:
        layers.append(Layer("Sea", fill=palette.water,
                            polygons=[_xy(model.sea)]))

    drawings = ward_drawings(model)

    def by_ward(name, kind, source=None, **style):
        """A layer of what the wards draw, one group for each ward."""
        source = source or name
        layer = Layer(name, **style)
        if grouped:
            layer.groups = []
            for ward, edits, drawing in drawings:
                shapes = drawing.get(source, ())
                parts = {"polygons": (), "polylines": (), "circles": ()}
                parts[kind] = shapes
                layer.groups.append((ward, edits, parts["polygons"],
                                     parts["polylines"], parts["circles"]))
        else:
            setattr(layer, kind, [shape for _, _, drawing in drawings
                                  for shape in drawing.get(source, ())])
        return layer

    layers.append(by_ward("Greens", "polygons", fill=palette.green))
    layers.append(by_ward("Green trees", "circles", fill=palette.forest))
    layers.append(by_ward("Plots", "polygons", fill=palette.garden,
                          stroke=palette.medium, width=PLOT_BORDER))
    layers.append(by_ward("Garden trees", "circles", fill=palette.forest))
    # Over the gardens, since a way can cut across one to pass a house.
    layers += [
        Layer("Road edges", stroke=palette.medium,
              width=MAIN_STREET + NORMAL_STROKE, cap="flat", polylines=roads),
        Layer("Roads", stroke=palette.paper,
              width=MAIN_STREET - NORMAL_STROKE, cap="flat", polylines=roads),
        Layer("Streets", stroke=palette.medium, width=STREET_LINE,
              join="round", polylines=street_lines + [
                  _rounded(line) for line in wall_streets]),
    ]
    layers.append(by_ward("Buildings", "polygons", fill=palette.light,
                          stroke=palette.dark, width=NORMAL_STROKE))
    layers.append(by_ward("Room walls", "polylines", stroke=palette.dark,
                          width=NORMAL_STROKE, cap="flat"))

    # A heavy line drawn first, with the fill on top, leaves an outer outline.
    layers.append(by_ward("Castle outline", "polygons", "Castle",
                          stroke=palette.dark, width=NORMAL_STROKE * 4))
    layers.append(by_ward("Castle", "polygons", fill=palette.light))
    layers.append(by_ward("Temple", "polygons", fill=palette.dark))

    walls = []
    if model.wall is not None:
        walls.append((model.wall, False, "City"))
    if model.citadel is not None:
        walls.append((model.citadel.ward.wall, True, "Castle"))

    for wall, _, prefix in walls:
        layers.append(_wall_line(wall, palette, prefix))

    # Over the walls, so the river makes its own gap in them.
    if model.river:
        layers.append(Layer("River", stroke=palette.water, width=RIVER_WIDTH,
                            cap="flat", join="round",
                            polylines=[_rounded(_xy(model.river))]))
    for name, pairs, width in (("Bridge", model.bridges, BRIDGE_WIDTH),
                               ("Pier", model.piers, PIER_WIDTH)):
        layers.append(Layer(f"{name} edges", stroke=palette.medium,
                            width=width + NORMAL_STROKE, cap="flat",
                            polylines=_pairs(pairs)))
        layers.append(Layer(f"{name}s", stroke=palette.paper,
                            width=width - NORMAL_STROKE, cap="flat",
                            polylines=_pairs(pairs)))

    for wall, large, prefix in walls:
        layers += _wall_features(wall, large, palette, prefix)

    return layers


def map_extent(model):
    """How far the map reaches from its centre, in map units."""
    return getattr(model, "view_radius", model.city_radius * 1.1)


def scale_bar(units_per_length, most):
    """The longest round length that fits a scale bar, and its size.

    units_per_length is how many drawing units, such as pixels, a map unit
    takes, and most is the most drawing units the bar may take. Returns the
    length in metres, as 1, 2 or 5 times a power of ten, and its size in
    drawing units.
    """
    metres = most / units_per_length * METRES_PER_UNIT
    power = 10 ** math.floor(math.log10(metres))
    for step in (5, 2, 1):
        if step * power <= metres:
            length = step * power
            break
    return length, length / METRES_PER_UNIT * units_per_length


def scale_label(metres):
    if metres >= 1000:
        return f"{metres / 1000:g} km"
    return f"{metres:g} m"
