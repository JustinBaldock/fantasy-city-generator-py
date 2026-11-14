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
from fractions import Fraction

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


MIN_EDGE_WARDS = 3  # The fewest wards the ring at a town's edge can have.


def _ring_points(radius, turn, fractions):
    """The points round a ring, at shares of a turn, filled in so that no
    straight piece is longer than ARC_STEP. Returns {share: point}."""
    shares = sorted(set(fractions))
    filled = []
    circumference = 2 * math.pi * radius
    for i, share in enumerate(shares):
        following = shares[(i + 1) % len(shares)] + (1 if i == len(shares) - 1
                                                     else 0)
        filled.append(share)
        pieces = math.ceil((following - share) * circumference / ARC_STEP)
        for k in range(1, pieces):
            filled.append(share + (following - share) * Fraction(k, pieces))
    points = {}
    for share in filled:
        share = share % 1
        angle = turn + 2 * math.pi * float(share)
        points[share] = Point(math.cos(angle) * radius,
                              math.sin(angle) * radius)
    return points


def radial(count, town=None):
    """A hub, and enough wards in rings round it to make at least count.

    town is how many wards the town has. The town takes whole rings, so its
    edge is round: the ring at its edge has just the wards still needed, at
    least MIN_EDGE_WARDS, and those before it have the usual number. Further
    out, the rings go back to the usual number.
    """
    turn = rng.random() * 2 * math.pi
    radii = [HUB]
    spokes = []  # For each band between two rings.
    total = 1
    while total < count:
        usual = _spokes_for(radii[-1])
        if town is not None and total < town:
            needed = town - total
            if needed < usual:
                # The first ring can be two halves, so a town of three is
                # round too.
                least = MIN_EDGE_WARDS if spokes else 2
                usual = max(least, needed)
            elif needed - usual < MIN_EDGE_WARDS:
                # Too few would be left for a ring of their own, so this
                # ring takes them too.
                usual = needed
        spokes.append(usual)
        radii.append(radii[-1] + _between(*BAND))
        total += spokes[-1]

    # The points round each ring are shared by the wards either side, so
    # each ring has a point at every spoke that meets it.
    rings = []
    for j, radius in enumerate(radii):
        shares = [Fraction(0)]
        for k in (j - 1, j):
            if 0 <= k < len(spokes):
                shares += [Fraction(a, spokes[k]) for a in range(spokes[k])]
        rings.append(_ring_points(radius, turn, shares))

    def between(ring, low, high):
        """The points of a ring from one share to another, in order."""
        found = [share for share in ring if low <= share <= high]
        if high == 1:
            found.append(Fraction(1))
        return [ring[share % 1] for share in sorted(found)]

    hub = rings[0]
    shapes = [_wound([hub[share] for share in sorted(hub)])]
    for band, count_here in enumerate(spokes):
        ward_shapes = []
        for s in range(count_here):
            low = Fraction(s, count_here)
            high = Fraction(s + 1, count_here)
            near = between(rings[band], low, high)
            far = between(rings[band + 1], low, high)
            ward_shapes.append(_wound(near + list(reversed(far))))
        # Ring by ring, so the town takes whole rings, and in a jumbled order
        # round each ring, so the castle and the first fields vary.
        order = sorted(range(len(ward_shapes)), key=lambda i: rng.random())
        shapes += [ward_shapes[i] for i in order]
    return shapes
