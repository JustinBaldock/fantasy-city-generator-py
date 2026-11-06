"""The street network, ported from building/Topology.hx and geom/Graph.hx."""

from collections import deque

from .geometry import distance


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

    def build_path(self, start, goal, exclude=None):
        path = find_path(
            self.pt2node.get(start), self.pt2node.get(goal), exclude)
        if path is None:
            return None
        return [self.node2pt[node] for node in path]
