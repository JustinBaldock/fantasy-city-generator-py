"""A rough estimate of how many people live in a town.

This module is original to this port. The estimate comes from the land each
kind of ward covers, at the map's scale, and the people a hectare of that
kind of ward would hold in a medieval town, with a household on each
farmstead round it. It goes by the land rather than by counting houses, so
burgage plots and classic houses give the same town the same population, and
moving buildings doesn't change it.

The densities are in the range historians give for walled medieval towns,
about 100 to 200 people a hectare overall, with crowded slums and nearly
empty markets and temple closes either side of that.

Gnome homes are counted instead. Each holds 4 to 16 gnomes, 8 in a home of
the usual size, more in a bigger one, and the shops, stores and barns among
them hold no one. Wards without homes, such as castles, barracks and
markets, still go by their land.
"""

import math

from .gnomes import GnomeHome
from .layers import METRES_PER_UNIT
from .plots import Plot
from .wards import (
    AdministrationWard,
    Castle,
    Cathedral,
    CraftsmenWard,
    Farm,
    GateWard,
    Market,
    MerchantWard,
    MilitaryWard,
    Park,
    PatriciateWard,
    Slum,
)

SQUARE_METRES_PER_HECTARE = 10_000

# People for each hectare of a kind of ward.
PEOPLE_PER_HECTARE = {
    CraftsmenWard: 200,
    GateWard: 180,
    MerchantWard: 160,
    Slum: 400,
    PatriciateWard: 100,
    AdministrationWard: 60,
    MilitaryWard: 150,  # Barracks.
    Castle: 80,  # The lord's household and the garrison.
    Cathedral: 40,  # Clergy and the temple's servants.
    Market: 30,
    Park: 0,
}
UNKNOWN_WARD = 150  # For any kind of ward in town not listed above.
FARM_HOUSEHOLD = 8  # People on each farmstead round the town.

GNOMES_PER_HOME = (4, 8, 16)  # The fewest, the usual and the most.
# A gnome home of this many square units holds the usual number. Bigger homes
# hold more, by the square root of their floor, which makes 8 the average.
USUAL_GNOME_HOME = 9.75


def hectares(patch):
    square_units = abs(patch.shape.square)
    return square_units * METRES_PER_UNIT ** 2 / SQUARE_METRES_PER_HECTARE


def gnomes_in(home):
    """How many gnomes live in a gnome home, by its size."""
    fewest, usual, most = GNOMES_PER_HOME
    people = round(usual * math.sqrt(abs(home.square) / USUAL_GNOME_HOME))
    return max(fewest, min(most, people))


def _gnome_homes(ward):
    for building in ward.geometry:
        house = building.house if isinstance(building, Plot) else building
        if isinstance(house, GnomeHome):
            yield house


def estimate(model):
    """Roughly how many people live in the town and on its farms."""
    gnomes = model.home_style == "gnome"
    people = 0.0
    for patch in model.patches:
        ward = patch.ward
        if gnomes and (ward.homes or isinstance(ward, Farm)) and (
                patch.within_city or isinstance(ward, Farm)):
            people += sum(gnomes_in(home) for home in _gnome_homes(ward))
        elif isinstance(ward, Farm):
            if ward.geometry:
                people += FARM_HOUSEHOLD
        elif patch.within_city:
            density = PEOPLE_PER_HECTARE.get(type(ward), UNKNOWN_WARD)
            people += hectares(patch) * density
    return round(people)


def rounded(people):
    """An estimate rounded to show it's an estimate: to the nearest 5 below
    100, the nearest 10 below 1,000, and the nearest 100 above."""
    step = 5 if people < 100 else 10 if people < 1000 else 100
    return max(step, round(people / step) * step)


def describe(model):
    """The estimate as shown, such as "2,400"."""
    return f"{rounded(estimate(model)):,}"
