import pytest

from citygen.model import Model
from citygen.population import describe, estimate, hectares, rounded
from citygen.wards import Park


def test_bigger_towns_hold_more_people():
    sizes = (1, 6, 15, 24, 40)
    averages = [sum(estimate(Model(size, seed)) for seed in range(1, 4)) / 3
                for size in sizes]
    assert averages == sorted(averages)


@pytest.mark.parametrize("size, low, high", [
    (1, 30, 300), (6, 200, 1000), (15, 1200, 5000), (40, 8000, 30000)])
def test_estimates_are_in_a_medieval_range(size, low, high):
    assert low <= estimate(Model(size, 7)) <= high


def test_the_home_style_and_moved_buildings_dont_change_it():
    people = estimate(Model(15, 7))
    for style in ("classic", "gnome"):
        assert estimate(Model(15, 7, home_style=style)) == people


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
