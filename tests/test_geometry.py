import math

import pytest

from citygen import cutter, rng
from citygen.geometry import Point, Polygon, chaikin, fdiv
from citygen.topology import Node, find_path
from citygen.voronoi import Triangle, Voronoi


def square(size=10):
    return Polygon([Point(0, 0), Point(size, 0), Point(size, size), Point(0, size)])


def test_random_numbers_follow_the_published_sequence():
    rng.reset(1)
    values = [rng._next() for _ in range(10000)]
    assert values[0] == 48271
    assert values[1] == 182605794
    # The figure the C++ standard gives for minstd_rand.
    assert values[9999] == 399268537


def test_random_integers_stay_in_range():
    rng.reset(5)
    values = {rng.randint(3, 7) for _ in range(500)}
    assert values == {3, 4, 5, 6}


@pytest.mark.parametrize("a, b, expected", [
    (1, 2, 0.5), (1, 0, math.inf), (-1, 0, -math.inf), (1, -0.0, -math.inf),
])
def test_fdiv_divides_like_haxe(a, b, expected):
    assert fdiv(a, b) == expected


def test_fdiv_gives_nan_for_zero_over_zero():
    assert math.isnan(fdiv(0, 0))


def test_points_compare_by_identity():
    a = Point(1, 2)
    b = Point(1, 2)
    assert a in [a]
    assert b not in [a]


def test_copying_a_polygon_shares_its_points():
    original = square()
    copy = Polygon(original)
    copy[0].x = 99
    assert original[0].x == 99


def test_area_centroid_and_compactness():
    poly = square()
    assert poly.square == 100
    assert (poly.centroid.x, poly.centroid.y) == (5, 5)
    assert poly.compactness == pytest.approx(0.785, abs=0.001)


def test_cut_divides_the_area():
    pieces = square().cut(Point(5, -1), Point(5, 11))
    assert len(pieces) == 2
    assert sum(abs(p.square) for p in pieces) == pytest.approx(100)


def test_cut_that_misses_returns_one_piece():
    assert len(square().cut(Point(20, 0), Point(20, 10))) == 1


def test_cut_with_a_gap_removes_a_strip():
    pieces = square().cut(Point(5, -1), Point(5, 11), 1.0)
    assert sum(abs(p.square) for p in pieces) == pytest.approx(90)


def test_shrink_and_buffer_inset_a_square_alike():
    assert square().shrink([1, 1, 1, 1]).square == pytest.approx(64)
    assert square().buffer([1, 1, 1, 1]).square == pytest.approx(64)


def test_ring_leaves_a_courtyard():
    peel = cutter.ring(square(), 2)
    assert len(peel) == 4
    assert sum(abs(p.square) for p in peel) == pytest.approx(64)


def test_point_inside_polygon():
    assert square().contains_point(Point(5, 5))
    assert not square().contains_point(Point(15, 5))


def test_circumcentre_of_a_right_triangle():
    triangle = Triangle(Point(0, 0), Point(4, 0), Point(0, 2))
    assert (triangle.c.x, triangle.c.y) == pytest.approx((2, 1))
    assert triangle.r == pytest.approx(math.sqrt(5))


def test_voronoi_regions_cover_the_inner_points():
    points = [Point(x * 10 + (y % 2) * 3, y * 10)
              for x in range(6) for y in range(6)]
    regions = Voronoi.build(points).partitioning()
    assert regions
    for region in regions:
        assert len(region.vertices) >= 3


def test_find_path_takes_the_cheaper_way():
    a, b, c, d = Node(), Node(), Node(), Node()
    a.link(b, 1)
    b.link(d, 1)
    a.link(c, 5)
    c.link(d, 5)
    assert find_path(a, d) == [d, b, a]


def test_find_path_avoids_excluded_nodes():
    a, b, c = Node(), Node(), Node()
    a.link(b)
    b.link(c)
    assert find_path(a, c, {b}) is None


def test_chaikin_keeps_the_ends_of_an_open_line():
    line = [(0, 0), (10, 0), (10, 10)]
    rounded = chaikin(line, 2)
    assert rounded[0] == (0, 0)
    assert rounded[-1] == (10, 10)
    assert len(rounded) > len(line)


def test_rounding_a_polygon_trims_its_corners():
    assert 0 < square().rounded().square < 100


def test_find_path_copes_with_a_missing_end():
    a = Node()
    assert find_path(None, a) is None
    assert find_path(a, None) is None
