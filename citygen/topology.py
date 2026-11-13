"""The street network, ported from building/Topology.hx and geom/Graph.hx."""

import heapq
import math
from collections import deque

from .geometry import distance

# What a turn adds to a planned town's street, in map units, so a street
# keeps straight where it can. Gentler bends, round a ring, cost nothing.
TURN_COST = 30.0
GENTLE_TURN = math.radians(40)


class Node:
    __slots__ = ("links",)

    def __init__(self):
        self.links = {}

    def link(self, node, price=1.0):
        self.links[node] = price
        node.links[self] = price


def find_path(start, goal, exclude=None):
    """The path from start to goal, listed from the goal back to the start.

    The original calls this A*, but it has no heuristic and takes nodes first
    come, first served.
    """
    if start is None or goal is None:
        return None

    closed = set(exclude or ())
    waiting = deque([start])
    queued = {start}
    came_from = {}
    score = {start: 0}

    while waiting:
        current = waiting.popleft()
        queued.discard(current)
        if current is goal:
            path = [current]
            while current in came_from:
                current = came_from[current]
                path.append(current)
            return path

        closed.add(current)
        current_score = score[current]
        for neighbour, price in current.links.items():
            if neighbour in closed:
                continue
            new_score = current_score + price
            if neighbour not in queued:
                waiting.append(neighbour)
                queued.add(neighbour)
            elif new_score >= score[neighbour]:
                continue
            came_from[neighbour] = current
            score[neighbour] = new_score
    return None


def shortest_path(start, goal, exclude=None):
    """Like find_path, but the shortest way by distance, for the grid and
    circular plans, where the fewest steps can wander a long way round."""
    if start is None or goal is None:
        return None
    closed = set(exclude or ())
    best = {start: 0.0}
    came_from = {}
    waiting = [(0.0, 0, start)]
    count = 1
    done = set()
    while waiting:
        cost, _, current = heapq.heappop(waiting)
        if current in done:
            continue
        if current is goal:
            path = [current]
            while current in came_from:
                current = came_from[current]
                path.append(current)
            return path
        done.add(current)
        for neighbour, price in current.links.items():
            if neighbour in closed or neighbour in done:
                continue
            new = cost + price
            if new < best.get(neighbour, math.inf):
                best[neighbour] = new
                came_from[neighbour] = current
                count += 1
                heapq.heappush(waiting, (new, count, neighbour))
    return None


class Topology:

    def __init__(self, model):
        self.pt2node = {}
        self.node2pt = {}
        self.inner = set()
        self.outer = set()

        # Roads can't cross walls, except at the gates.
        blocked = []
        if model.citadel is not None:
            blocked += model.citadel.shape
        if model.wall is not None:
            blocked += model.wall.shape
        self.blocked = {v for v in blocked if v not in model.gates}
        # Streets cross a river at its bridges and nowhere else.
        self.blocked |= model.river_points - model.bridge_points

        border = set(model.border.shape)

        for patch in model.patches:
            side = self.inner if patch.within_city else self.outer

            v1 = patch.shape.last()
            n1 = self._process_point(v1)
            for v in patch.shape:
                v0, v1 = v1, v
                n0, n1 = n1, self._process_point(v1)

                if n0 is not None and v0 not in border:
                    side.add(n0)
                if n1 is not None and v1 not in border:
                    side.add(n1)

                if (n0 is not None and n1 is not None
                        and (v0, v1) not in model.river_edges):
                    n0.link(n1, distance(v0, v1))

    def _process_point(self, v):
        node = self.pt2node.get(v)
        if node is None:
            node = Node()
            self.pt2node[v] = node
            self.node2pt[node] = v
        return None if v in self.blocked else node

    def straight_path(self, start, goal, exclude=None):
        """The shortest way from start to goal with the fewest sharp turns,
        listed from goal back to start like build_path. This port's own, for
        the grid and circular plans."""
        first = self.pt2node.get(start)
        last = self.pt2node.get(goal)
        if first is None or last is None:
            return None
        closed = set(exclude or ())
        closed.discard(first)
        closed.discard(last)
        point = self.node2pt
        order = {node: i for i, node in enumerate(self.node2pt)}

        def heading(a, b):
            pa = point[a]
            pb = point[b]
            return math.atan2(pb.y - pa.y, pb.x - pa.x)

        # Each state is a node and the node it was reached from.
        best = {(first, None): 0.0}
        came_from = {}
        waiting = [(0.0, 0, order[first], first, None)]
        count = 1
        while waiting:
            cost, _, _, node, before = heapq.heappop(waiting)
            if cost > best.get((node, before), math.inf):
                continue
            if node is last:
                path = [node]
                state = (node, before)
                while state in came_from:
                    state = came_from[state]
                    path.append(state[0])
                return [point[n] for n in path]
            for neighbour, price in node.links.items():
                if neighbour in closed and neighbour is not last:
                    continue
                step = price
                if before is not None:
                    turn = abs(math.remainder(
                        heading(node, neighbour) - heading(before, node),
                        2 * math.pi))
                    if turn > GENTLE_TURN:
                        step += TURN_COST
                new = cost + step
                state = (neighbour, node)
                if new < best.get(state, math.inf):
                    best[state] = new
                    came_from[state] = (node, before)
                    count += 1
                    heapq.heappush(waiting, (new, count, order[neighbour],
                                             neighbour, node))
        return None

    def build_path(self, start, goal, exclude=None):
        path = find_path(
            self.pt2node.get(start), self.pt2node.get(goal), exclude)
        if path is None:
            return None
        return [self.node2pt[node] for node in path]
