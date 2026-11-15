"""Pure 2D geometry helpers on normalized landmark coordinates."""
import math

from src.schemas.models import Point


def midpoint(a: Point, b: Point) -> Point:
    return Point((a.x + b.x) / 2, (a.y + b.y) / 2, min(a.visibility, b.visibility))


def distance(a: Point, b: Point) -> float:
    return math.hypot(b.x - a.x, b.y - a.y)


def line_angle_deg(a: Point, b: Point) -> float:
    """Angle of the line a->b relative to horizontal, in degrees (-180..180)."""
    return math.degrees(math.atan2(b.y - a.y, b.x - a.x))
