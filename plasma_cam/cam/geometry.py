"""Small geometry predicates shared by CAM planners."""

from __future__ import annotations

from ..model import Point


def segments_intersect(a0: Point, a1: Point, b0: Point, b1: Point) -> bool:
    o1 = orientation(a0, a1, b0)
    o2 = orientation(a0, a1, b1)
    o3 = orientation(b0, b1, a0)
    o4 = orientation(b0, b1, a1)
    if o1 * o2 < 0 and o3 * o4 < 0:
        return True
    if abs(o1) <= 1e-9 and point_on_segment(b0, a0, a1):
        return True
    if abs(o2) <= 1e-9 and point_on_segment(b1, a0, a1):
        return True
    if abs(o3) <= 1e-9 and point_on_segment(a0, b0, b1):
        return True
    if abs(o4) <= 1e-9 and point_on_segment(a1, b0, b1):
        return True
    return False


def orientation(a: Point, b: Point, c: Point) -> float:
    return (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x)


def point_on_segment(point: Point, start: Point, end: Point) -> bool:
    return (
        min(start.x, end.x) - 1e-9 <= point.x <= max(start.x, end.x) + 1e-9
        and min(start.y, end.y) - 1e-9 <= point.y <= max(start.y, end.y) + 1e-9
    )
