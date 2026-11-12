import pytest

from citygen.model import Model
from citygen.population import (
    PEOPLE_PER_HECTARE,
    _gnome_homes,
    describe,
    estimate,
    gnomes_in,
    hectares,
    rounded,
)
from citygen.wards import Farm, Park


def test_bigger_towns_hold_more_people():
    sizes = (1, 6, 15, 24, 40)
    averages = [sum(estimate(Model(size, seed)) for seed in range(1, 4)) / 3
                for size in sizes]
    assert averages == sorted(averages)


@pytest.mark.parametrize("size, low, high", [
    (1, 30, 300), (6, 200, 1000), (15, 1200, 5000), (40, 8000, 30000)])
def test_estimates_are_in_a_medieval_range(size, low, high):
    assert low <= estimate(Model(size, 7)) <= high


def test_burgage_plots_and_classic_houses_give_the_same_town():
    assert estimate(Model(15, 7)) == estimate(Model(15, 7,
                                                    home_style="classic"))


def gnome_homes(model):
    return [home for patch in model.patches
            for home in _gnome_homes(patch.ward)]


def test_gnome_homes_hold_4_to_16_and_8_on_average():
    counts = [gnomes_in(home) for size in (9, 24) for seed in (1, 2, 3)
              for home in gnome_homes(Model(size, seed, home_style="gnome"))]
    assert min(counts) == 4 and max(counts) == 16
    assert sum(counts) / len(counts) == pytest.approx(8, abs=0.4)


def test_bigger_gnome_homes_hold_more():
    homes = sorted(gnome_homes(Model(24, 7, home_style="gnome")),
                   key=lambda home: abs(home.square))
    counts = [gnomes_in(home) for home in homes]
    assert counts == sorted(counts)


def test_a_gnome_town_counts_its_homes():
    model = Model(15, 7, home_style="gnome")
    in_homes = sum(gnomes_in(home) for patch in model.patches
                   if patch.within_city or isinstance(patch.ward, Farm)
                   if patch.ward.homes or isinstance(patch.ward, Farm)
                   for home in _gnome_homes(patch.ward))
    elsewhere = sum(hectares(p) * PEOPLE_PER_HECTARE.get(type(p.ward), 150)
                    for p in model.patches if p.within_city
                    and not p.ward.homes and not isinstance(p.ward, Farm))
    assert estimate(model) == round(in_homes + elsewhere)
    # The shops, stores and barns among the homes hold no one.
    assert estimate(model) < estimate(Model(15, 7))


def test_greens_hold_no_one():
    model = Model(24, 7, greens=True)
    parks = [p for p in model.patches if isinstance(p.ward, Park)]
    assert parks and sum(hectares(p) for p in parks) > 0
    people = estimate(model)
    # Turning a green into a craftsmen's ward would add its people.
    from citygen.wards import CraftsmenWard
    parks[0].ward.__class__ = CraftsmenWard
    assert estimate(model) > people


@pytest.mark.parametrize("people, shown", [
    (3, 5), (64, 65), (127, 130), (994, 990), (2451, 2500), (16294, 16300)])
def test_rounding(people, shown):
    assert rounded(people) == shown


def test_described_with_thousands_separated():
    assert "," in describe(Model(24, 7))
