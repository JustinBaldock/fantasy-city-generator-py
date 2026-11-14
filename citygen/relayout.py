"""Laying out one ward's buildings again, to fit its land as it is now.

This module is original to this port. When a city wall is moved by hand, the
wards along it stretch or shrink with it, and their buildings are laid out
afresh to fill the new shape, by the same rules that built the town: the
ward's own plan, then the town's home style, then the trees in the gardens
and round the greens.

Each ward uses its own random numbers, from the town's seed and the ward's
place in the town, so a ward of a given shape always comes out the same. The
original's shared random numbers are put back as they were afterwards.
"""

import random

from . import gnomes, plots, rng
from .editing import overlap
from .geometry import convex_hull
from .plots import Plot
from .wards import Farm, Park


def ward_seed(model, patch):
    """The seed for laying out one ward again."""
    index = model.patches.index(patch)
    return (model.seed * 7919 + index * 104729 + 12345) % 2147483646 + 1


def _hull(polygon):
    return convex_hull([(v.x, v.y) for v in polygon])


def lay_out_again(model, patch, keep=()):
    """Lay a ward's buildings out again to fit its patch.

    keep are buildings to leave just as they are, such as locked ones. New
    buildings that would overlap them are left out. Returns the ward's new
    buildings, not counting those kept.
    """
    ward = patch.ward
    saved = rng.get_seed()
    rng.reset(ward_seed(model, patch))
    try:
        ward.create_geometry()
    finally:
        rng.reset(saved)

    chooser = random.Random(f"{model.seed} laid out again "
                            f"{model.patches.index(patch)}")
    shapes = [polygon for polygon in ward.geometry if len(polygon) >= 3]
    if model.home_style == "gnome":
        if not isinstance(ward, Farm) and (ward.homes or ward.rectangle_share):
            shapes = gnomes._buildings_for(shapes, ward.rectangle_share,
                                           chooser)
    elif model.home_style == "burgage":
        if ward.homes:
            block = ward.get_city_block()
            shapes = [plots.burgage(plot, block, shapes, chooser)
                      for plot in shapes]
        elif ward.rectangle_share:
            shapes = [plots.plot_with_rectangle(plot, chooser)
                      for plot in shapes]
        shapes = [shape for shape in shapes if shape is not None]
    for shape in shapes:
        if isinstance(shape, Plot):
            plots._plant(shape, chooser)
    if isinstance(ward, Park):
        shapes = [plots.Green(green, plots._ring_of_trees(green, chooser))
                  for green in shapes]

    kept_hulls = [_hull(polygon) for polygon in keep]
    fresh = [shape for shape in shapes
             if not any(overlap(hull, _hull(shape)) is not None
                        for hull in kept_hulls)]
    ward.geometry = list(keep) + fresh
    ward.edits += 1
    # The new buildings count as where the town put them, so the roads
    # don't bend round them.
    kept = {id(polygon) for polygon in keep}
    for polygon in list(ward.geometry) + list(ward.landmarks):
        if id(polygon) not in kept:
            model.built_at[id(polygon)] = tuple((v.x, v.y) for v in polygon)
    return fresh
