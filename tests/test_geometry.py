import math

from src.schemas.models import Point
from src.utils.geometry import distance, line_angle_deg, midpoint


def test_midpoint():
    m = midpoint(Point(0, 0), Point(2, 4))
    assert (m.x, m.y) == (1, 2)


def test_distance():
    assert math.isclose(distance(Point(0, 0), Point(3, 4)), 5)


def test_horizontal_line_has_zero_angle():
    assert math.isclose(line_angle_deg(Point(0, 0.5), Point(1, 0.5)), 0)
