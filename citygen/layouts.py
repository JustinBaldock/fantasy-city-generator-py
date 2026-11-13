"""The grid and circular town plans.

This module is original to this port. The original lays a town out on a
Voronoi diagram, which gives its organic look. These make the patches another
way, and the rest of the generator builds on them as it would on the
original's: the town takes the patches nearest the centre, the walls go round
them, and the countryside fills the rest.

A grid town is blocks of straight streets, its rows and columns a little
different in size. A circular town has a round hub at its centre, rings
round it, and spokes running out from it. The spokes double as the rings
grow, so the outer wards are no wider than the inner ones.

Neighbouring patches share their corner points, as the Voronoi patches do,
since the streets and walls are found by following shared edges.
"""

import math

from . import rng
from .geometry import Point, Polygon

LAYOUTS = ("organic", "grid", "radial")

BLOCK = (22.0, 30.0)  # The range of a grid block's width and depth.

HUB = 13.0  # The radius of a circular town's hub.
BAND = (20.0, 24.0)  # The range of the gap between rings.
SPOKES = 8  # Round the hub. They double as the rings grow.
SECTOR = 28.0  # The widest a ward between two spokes gets before they double.
ARC_STEP = 9.0  # The longest straight piece of a ring.

# How much a patch's distance from the centre is jumbled when choosing which
# ones the town takes, so its edge isn't too regular.
JUMBLE = 0.12


def _between(low, high):
    return low + (high - low) * rng.random()


def _wound(points):
    """A polygon wound the same way as the Voronoi patches."""
    polygon = Polygon(points)
    if polygon.square < 0:
        polygon = Polygon(reversed(polygon))
    return polygon


def _in_order(shapes):
    """The patches nearest the centre first, a little jumbled."""
    keyed = [(shape.center.length * (1 + JUMBLE * (rng.random() * 2 - 1)), i)
             for i, shape in enumerate(shapes)]
    return [shapes[i] for _, i in sorted(keyed)]


def grid(count):
    """At least count square-ish blocks, round a crossroads at the centre."""
    side = math.ceil(math.sqrt(count))
    side += 1 - side % 2  # Odd, so a crossroads is in the middle.
    side += 2

    def edges():
        sizes = [_between(*BLOCK) for _ in range(side)]
        middle = side // 2
        # The edges are measured from the one at the centre, which is at 0.
        found = [0.0]
        for size in sizes[middle:]:
            found.append(found[-1] + size)
        before = [0.0]
        for size in reversed(sizes[:middle]):
            before.append(before[-1] - size)
        return list(reversed(before[1:])) + found

    xs = edges()
    ys = edges()
    nodes = {(i, j): Point(x, y) for i, x in enumerate(xs)
             for j, y in enumerate(ys)}
    shapes = [_wound([nodes[i, j], nodes[i + 1, j], nodes[i + 1, j + 1],
                      nodes[i, j + 1]])
              for i in range(len(xs) - 1) for j in range(len(ys) - 1)]
    return _in_order(shapes)


def _spokes_for(radius):
    """How many spokes a ring this far out has, a doubling of SPOKES."""
    spokes = SPOKES
    while 2 * math.pi * radius / spokes > SECTOR:
        spokes *= 2
    return spokes


def radial(count):
    """A hub, and enough wards in rings round it to make at least count."""
    turn = rng.random() * 2 * math.pi
    radii = [HUB]
    spokes = []  # For each band between two rings.
    total = 1
    while total < count:
        spokes.append(_spokes_for(radii[-1]))
        radii.append(radii[-1] + _between(*BAND))
        total += spokes[-1]

    # The points round each ring, enough for every spoke that meets it, and
    # close enough together to look round.
    rings = []
    for j, radius in enumerate(radii):
        meeting = [spokes[k] for k in (j - 1, j) if 0 <= k < len(spokes)]
        points = max(meeting)
        while 2 * math.pi * radius / points > ARC_STEP:
            points *= 2
        rings.append([Point(math.cos(turn + 2 * math.pi * a / points) * radius,
                            math.sin(turn + 2 * math.pi * a / points) * radius)
                      for a in range(points)])

    shapes = [_wound(rings[0])]
    for band, count_here in enumerate(spokes):
        inner = rings[band]
        outer = rings[band + 1]
        step_in = len(inner) // count_here
        step_out = len(outer) // count_here
        for s in range(count_here):
            near = [inner[(s * step_in + a) % len(inner)]
                    for a in range(step_in + 1)]
            far = [outer[(s * step_out + a) % len(outer)]
                   for a in range(step_out, -1, -1)]
            shapes.append(_wound(near + far))
    return _in_order(shapes)
