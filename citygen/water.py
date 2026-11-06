"""Coasts, rivers and bridges.

This module is original to this port. The published source has no water, so
these are our own methods, written to give a similar kind of map.

Water follows the edges between patches rather than cutting through them. A
coast is a set of patches turned to sea, and a river is a path along patch
edges. Buildings then need no clipping, because each ward insets its own
block from any edge that has water on it.
"""

import math

from .geometry import (
    GenerationError,
    Point,
    Polygon,
    distance,
    interpolate,
    max_by,
    min_by,
)
from .patch import Patch
from .topology import Node, find_path

RIVER_WIDTH = 6.0
BANK = 0.8
QUAY = 1.2
BRIDGE_WIDTH = 2.0
BRIDGE_OVERHANG = 1.0

MIN_BRIDGE_SPACING = 30
MIN_BRIDGE_EDGE = 6
PIER_SPACING = 8
PIER_CHANCE = 0.75


def direction_from_bearing(degrees):
    """A unit vector for a compass bearing. On the map, north is up."""
    angle = math.radians(degrees)
    return Point(math.sin(angle), -math.cos(angle))


def _map_scale(size):
    """Roughly how far out the size-th patch sits."""
    return 10 + 2.5 * size


def edge_owners(patches):
    """Which patch owns each directed edge."""
    owners = {}
    for patch in patches:
        for edge in patch.shape.edges():
            owners[edge] = patch
    return owners


def _connected(start, allowed, owners):
    """The allowed patches reachable from a start patch, edge to edge."""
    found = {start}
    waiting = [start]
    while waiting:
        patch = waiting.pop()
        for a, b in patch.shape.edges():
            other = owners.get((b, a))
            if other in allowed and other not in found:
                found.add(other)
                waiting.append(other)
    return found


def plan_coast(model, patches):
    """Turn the patches beyond a wavy shoreline to sea."""
    features = model.features
    scale = _map_scale(model.size)
    direction = model.sea_direction
    across = direction.rotate90()

    offset = max(24.0, scale * features.uniform(0.35, 0.7))
    bend = features.uniform(-0.25, 0.5)
    wobble = scale * 0.06
    wave = scale * 0.7
    phase = features.uniform(0, 2 * math.pi)

    def seaward(p):
        side = p.dot(across)
        return (p.dot(direction) - offset - bend * side * side / scale
                + wobble * math.sin(side / wave + phase))

    model.seaward = seaward

    # The water has to be one sea, and the land one piece around the centre.
    owners = edge_owners(patches)
    wet = {p for p in patches if seaward(p.shape.center) > 0}
    if not wet or patches[0] in wet:
        raise GenerationError("No usable shoreline")

    wettest = max_by(patches, lambda p: seaward(p.shape.center))
    wet = _connected(wettest, wet, owners)
    land = _connected(patches[0], set(patches) - wet, owners)
    for patch in patches:
        patch.water = patch not in land


def _walk_chains(following):
    chains = []
    ends = set(following.values())
    for start in following:
        if start in ends:
            continue
        chain = [start]
        while chain[-1] in following and len(chain) <= len(following):
            chain.append(following[chain[-1]])
        chains.append(chain)
    return chains


def finish_coast(model):
    """Find the shore, smooth it, and shape the sea."""
    owners = edge_owners(model.patches)
    following = {}
    for patch in model.patches:
        if patch.water:
            continue
        for a, b in patch.shape.edges():
            other = owners.get((b, a))
            if other is not None and other.water:
                following[a] = b
                model.shore_edges.add((a, b))
                model.shore_edges.add((b, a))

    chains = _walk_chains(following)
    if not chains:
        raise GenerationError("The shore is a closed loop")
    shore = max(chains, key=len)
    if len(shore) < 4:
        raise GenerationError("The shore is too short")

    for _ in range(3):
        moved = [
            Point((shore[i - 1].x + 2 * shore[i].x + shore[i + 1].x) / 4,
                  (shore[i - 1].y + 2 * shore[i].y + shore[i + 1].y) / 4)
            for i in range(1, len(shore) - 1)
        ]
        for point, target in zip(shore[1:-1], moved):
            point.set(target)

    model.shore = shore
    model.shore_points.update(following)
    model.shore_points.update(following.values())
    model.sea = _sea_shape(shore, model.sea_direction, model.size)


def _sea_shape(shore, direction, size):
    """Close the shore into a polygon reaching well past the map."""
    far = _map_scale(size) * 12
    across = direction.rotate90()

    def out_past(point):
        side = 1 if point.dot(across) > 0 else -1
        return across.scale(side * far).add(direction.scale(point.dot(direction)))

    start = shore[0]
    end = shore[-1]
    end_out = out_past(end)
    start_out = out_past(start)
    return Polygon(shore + [
        end_out,
        end_out.add(direction.scale(far)),
        start_out.add(direction.scale(far)),
        start_out,
    ])


def _route_graph(patches, barred):
    """A graph of patch vertices for a river to follow."""
    nodes = {}

    def node_for(v):
        if v not in nodes:
            nodes[v] = Node()
        return nodes[v]

    for patch in patches:
        for a, b in patch.shape.edges():
            if a not in barred and b not in barred:
                node_for(a).link(node_for(b), distance(a, b))
    return nodes


def _nearest(points, target):
    return min_by(points, lambda v: distance(v, target))


def build_river(model):
    """Run a river past the centre, to the sea or across the map."""
    features = model.features
    scale = _map_scale(model.size)

    # Keep clear of the plaza's ward and the castle.
    barred = set(model.inner[0].shape)
    if model.citadel is not None:
        barred.update(model.citadel.shape)

    if model.shore:
        heading = math.atan2(model.sea_direction.y, model.sea_direction.x)
        source_angle = heading + math.pi + features.uniform(-1.0, 1.0)
    else:
        source_angle = features.uniform(0, 2 * math.pi)

    # The shore is out of the route, or the river would run along it.
    nodes = _route_graph(model.patches, barred | model.shore_points)
    usable = list(nodes)
    if len(usable) < 3:
        raise GenerationError("No room for a river")

    source = _nearest(usable, Point(math.cos(source_angle) * scale * 2.4,
                                    math.sin(source_angle) * scale * 2.4))

    # The river passes the centre on one side.
    pass_angle = source_angle + math.pi / 2 * (1 if features.random() < 0.5
                                               else -1)
    reach = scale * features.uniform(0.2, 0.45)
    waypoint = _nearest(usable, Point(math.cos(pass_angle) * reach,
                                      math.sin(pass_angle) * reach))

    if model.shore:
        # Let the river reach the shore at one chosen spot.
        end = _nearest(model.shore[1:-1], waypoint)
        nodes[end] = Node()
        for patch in model.patches:
            for a, b in patch.shape.edges():
                if a is end and b in nodes:
                    nodes[end].link(nodes[b], distance(a, b))
                elif b is end and a in nodes:
                    nodes[end].link(nodes[a], distance(a, b))
    else:
        far_angle = source_angle + math.pi + features.uniform(-0.6, 0.6)
        end = _nearest(usable, Point(math.cos(far_angle) * scale * 2.4,
                                     math.sin(far_angle) * scale * 2.4))

    points_of = {node: point for point, node in nodes.items()}

    first_leg = find_path(nodes[source], nodes[waypoint])
    if first_leg is None:
        raise GenerationError("The river can't reach the city")
    used = set(first_leg) - {nodes[waypoint]}
    second_leg = find_path(nodes[waypoint], nodes[end], used)
    if second_leg is None:
        raise GenerationError("The river can't leave the city")

    route = second_leg + first_leg[1:]
    route.reverse()
    river = [points_of[node] for node in route]
    if len(river) < 4:
        raise GenerationError("The river is too short")

    for _ in range(3):
        moved = [
            Point((river[i - 1].x + 2 * river[i].x + river[i + 1].x) / 4,
                  (river[i - 1].y + 2 * river[i].y + river[i + 1].y) / 4)
            for i in range(1, len(river) - 1)
        ]
        for point, target in zip(river[1:-1], moved):
            point.set(target)

    for a, b in zip(river, river[1:]):
        model.river_edges.add((a, b))
        model.river_edges.add((b, a))
    model.river = river
    model.river_points.update(river)

    _add_bridges(model)

    # Past its last vertex a river carries on in open country or at sea, so
    # that it never stops in plain view.
    model.river.insert(0, _run_off(river[0], river[1], scale * 12))
    if model.shore:
        river.append(river[-1].add(model.sea_direction.scale(RIVER_WIDTH)))
    else:
        river.append(_run_off(river[-1], river[-2], scale * 12))


def _run_off(end, inner, length):
    """A point beyond a river's end, leaving the map heading outwards."""
    outward = end.norm(1.0).add(end.subtract(inner).norm(1.0))
    return end.add(outward.norm(length))


def _split_bank(model, patch, a, b, middle):
    """Add a bridge's vertex to a bank, and a street leading away from it."""
    index = patch.shape.find_edge(a, b)
    patch.shape.insert(index + 1, middle)

    inward = patch.shape.center.subtract(middle)
    options = [
        v for v in patch.shape
        if v is not a and v is not b and v is not middle
        and v not in model.river_points and v not in model.shore_points
    ]
    if not options:
        return

    def facing(v):
        offset = v.subtract(middle)
        return offset.dot(inward) / offset.length

    opposite = max_by(options, facing)
    halves = [Patch(half) for half in patch.shape.split(middle, opposite)]
    for half in halves:
        half.within_city = patch.within_city
        half.within_walls = patch.within_walls

    index = model.patches.index(patch)
    model.patches[index:index + 1] = halves
    if patch in model.inner:
        index = model.inner.index(patch)
        model.inner[index:index + 1] = halves


def _add_bridges(model):
    """Bridge the river where it runs between city wards.

    A river vertex has a street on one bank at most, so two banks rarely have
    streets that line up. Each bridge therefore gets its own vertex, partway
    along a river edge, and a new street on each bank.
    """
    features = model.features
    river = model.river
    placed = []

    for _ in range(max(1, len(model.inner) // 5)):
        owners = edge_owners(model.patches)
        options = []
        for a, b in zip(river, river[1:]):
            left = owners.get((a, b))
            right = owners.get((b, a))
            if left is None or right is None:
                continue
            if not (left.within_city and right.within_city):
                continue
            if distance(a, b) < MIN_BRIDGE_EDGE:
                continue
            middle = interpolate(a, b)
            if any(distance(middle, m) < MIN_BRIDGE_SPACING for m in placed):
                continue
            options.append((a, b, left, right, middle))

        if not options:
            break

        a, b, left, right, middle = options[
            int(features.random() * len(options))]

        river.insert(river.index(b), middle)
        for edge in ((a, b), (b, a)):
            model.river_edges.discard(edge)
        for edge in ((a, middle), (middle, a), (middle, b), (b, middle)):
            model.river_edges.add(edge)
        model.river_points.add(middle)
        model.bridge_points.add(middle)
        placed.append(middle)

        _split_bank(model, left, a, b, middle)
        _split_bank(model, right, b, a, middle)

        half = b.subtract(a).rotate90().norm(RIVER_WIDTH / 2 + BRIDGE_OVERHANG)
        model.bridges.append((middle.subtract(half), middle.add(half)))


def build_piers(model):
    """Add jetties along the city's waterfront."""
    features = model.features
    for patch in model.patches:
        if not patch.within_city or features.random() > PIER_CHANCE:
            continue
        for a, b in patch.shape.edges():
            if (a, b) not in model.shore_edges:
                continue
            length = distance(a, b)
            middle = interpolate(a, b)
            out = b.subtract(a).rotate90().norm(1.0)
            if model.seaward(middle.add(out)) < model.seaward(middle):
                out = out.scale(-1)

            count = int(length / PIER_SPACING)
            for i in range(count):
                base = interpolate(a, b, (i + 0.5) / count)
                reach = features.uniform(3.5, 6.5)
                model.piers.append((base, base.add(out.scale(reach))))
