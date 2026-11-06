"""The generator's random numbers, ported from utils/Random.hx.

This is a Park-Miller generator with a single shared state, as in the
original. Every map is fully decided by its seed, so the order of the calls
matters, and the code that uses them keeps the original's order.
"""

import time

_G = 48271
_N = 2147483647

_seed = 1


def reset(seed=-1):
    """Set the seed, or take one from the clock if none is given."""
    global _seed
    _seed = seed if seed != -1 else int(time.time() * 1000) % _N


def get_seed():
    return _seed


def _next():
    global _seed
    _seed = (_seed * _G) % _N
    return _seed


def random():
    """A float from 0 up to, but not including, 1."""
    return _next() / _N


def normal():
    """A float from 0 to 1, bunched around 0.5."""
    return (random() + random() + random()) / 3


def randint(low, high):
    """An integer from low up to, but not including, high."""
    return int(low + _next() / _N * (high - low))


def chance(probability=0.5):
    return random() < probability


def fuzzy(f=1.0):
    if f == 0:
        return 0.5
    return (1 - f) / 2 + f * normal()


def choice(items):
    return items[int(random() * len(items))]
