"""City and castle walls, ported from building/CurtainWall.hx."""

import math

from . import rng
from .geometry import GenerationError, Point, Polygon, index_of, max_by
from .patch import Patch, find_circumference
from .water import RIVER_WIDTH


class CurtainWall:

    def __init__(self, real, model, patches, reserved):
        # The original always sets this to true, whatever it was passed, and
        # only asks for towers on walls that exist.
        self.real = True
        self.patches = patches
        self.towers = []

        if len(patches) == 1:
            self.shape = patches[0].shape
        else:
            self.shape = find_circumference(patches)
            if real:
                smooth_factor = min(1, 40 / len(patches))
                self.shape.set(Polygon(
                    v if v in reserved
                    else self.shape.smooth_vertex(v, smooth_factor)
                    for v in self.shape
                ))

        self.segments = [True] * len(self.shape)
        self._build_gates(real, model, reserved)

    def _build_gates(self, real, model, reserved):
        self.gates = []
        shape = self.shape

        # An entrance needs more than one inner ward beside it, so that a
        # street can run between them to the city centre.
        if len(self.patches) > 1:
            entrances = [
                v for v in shape
                if v not in reserved
                and sum(1 for p in self.patches if v in p.shape) > 1
            ]
        else:
            entrances = [v for v in shape if v not in reserved]

        if not entrances:
            raise GenerationError("Bad walled area shape")

        while True:
            index = rng.randint(0, len(entrances))
            gate = entrances[index]
            self.gates.append(gate)

            if real:
                outer_wards = [
                    w for w in model.patch_by_vertex(gate)
                    if w not in self.patches
                ]
                if len(outer_wards) == 1:
                    # No road leads out here, so split the ward outside.
                    self._split_outer_ward(
                        model, gate, outer_wards[0], reserved)

            # Drop the neighbouring entrances so gates aren't too close.
            if index == 0:
                del entrances[0:2]
                if entrances:
                    entrances.pop()
            elif index == len(entrances) - 1:
                del entrances[index - 1:index + 1]
                if entrances:
                    entrances.pop(0)
            else:
                del entrances[index - 1:index + 2]

            if len(entrances) < 3:
                break

        if real:
            for gate in self.gates:
                gate.set(shape.smooth_vertex(gate))

    def _split_outer_ward(self, model, gate, outer, reserved):
        if len(outer.shape) <= 3:
            return

        shape = self.shape
        wall = shape.next(gate).subtract(shape.prev(gate))
        out = Point(wall.y, -wall.x)

        def outwardness(v):
            if v in shape or v in reserved:
                return -math.inf
            direction = v.subtract(gate)
            return direction.dot(out) / direction.length

        farthest = max_by(outer.shape, outwardness)
        halves = [Patch(half) for half in outer.shape.split(gate, farthest)]
        index = model.patches.index(outer)
        model.patches[index:index + 1] = halves

    def mask_water(self, model):
        """Leave out the stretches where water already guards the city."""
        for i, edge in enumerate(self.shape.edges()):
            if edge in model.shore_edges or edge in model.river_edges:
                self.segments[i] = False

    def build_towers(self, model):
        self.towers = []
        if self.real:
            count = len(self.shape)
            for i in range(count):
                t = self.shape[i]
                before = self.segments[(i + count - 1) % count]
                after = self.segments[i]
                if t in self.gates or not (before or after):
                    continue
                if t in model.river_points:
                    # The wall stops at the banks, with a tower on each side.
                    if before:
                        self._add_bank_tower(t, self.shape.prev(t))
                    if after:
                        self._add_bank_tower(t, self.shape.next(t))
                else:
                    self.towers.append(t)

    def _add_bank_tower(self, crossing, along):
        offset = along.subtract(crossing).norm(RIVER_WIDTH / 2 + 1.0)
        self.towers.append(crossing.add(offset))

    def get_radius(self):
        return max((v.length for v in self.shape), default=0.0)

    def borders_by(self, patch, v0, v1):
        if patch in self.patches:
            index = self.shape.find_edge(v0, v1)
        else:
            index = self.shape.find_edge(v1, v0)
        return index != -1 and self.segments[index]

    def borders(self, patch):
        within_walls = patch in self.patches
        count = len(self.shape)
        for i in range(count):
            if self.segments[i]:
                v0 = self.shape[i]
                v1 = self.shape[(i + 1) % count]
                if within_walls:
                    index = patch.shape.find_edge(v0, v1)
                else:
                    index = patch.shape.find_edge(v1, v0)
                if index != -1:
                    return True
        return False
