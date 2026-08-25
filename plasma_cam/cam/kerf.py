"""Kerf compensation for closed path contours."""

from __future__ import annotations

import math

try:
    import pyclipper
except ModuleNotFoundError:
    pyclipper = None

try:
    from shapely.geometry import Polygon
except ModuleNotFoundError:
    Polygon = None

from ..model import PathContour, Point, signed_area
from .geometry import segments_intersect
from .options import QtPlasmaCOptions


def offset_path_points(contour: PathContour, options: QtPlasmaCOptions) -> list[Point]:
    raw = contour.points(max_chord=max(options.path_tolerance * 8.0, 0.5))
    if len(raw) < 3:
        if options.kerf_offset_fallback == "centerline" and len(raw) >= 2:
            return list(raw)
        raise ValueError(f"{contour.name} has fewer than 3 geometry points")
    offset = _effective_kerf_width(options) / 2.0
    try:
        points = _offset_closed_polygon(raw, offset, inward=contour.kind in ("hole", "inner"))
    except ValueError as exc:
        if options.kerf_offset_fallback != "centerline" or not _is_kerf_offset_failure(exc):
            raise
        return list(raw)
    desired_clockwise = contour.kind == "outer"
    area = signed_area(points)
    if abs(area) <= 1e-6:
        raise ValueError(f"{contour.name} offset path has zero area")
    if (area < 0) != desired_clockwise:
        points = list(reversed(points))
    return points


def _effective_kerf_width(options: QtPlasmaCOptions) -> float:
    if options.common_line_cutting and options.kerf_offset_fallback == "centerline":
        return 0.0
    if options.kerf_width is not None:
        return options.kerf_width
    if options.cut_settings is not None:
        return options.cut_settings.kerf_width_mm
    return 0.0


def _is_kerf_offset_failure(exc: ValueError) -> bool:
    message = str(exc)
    return "Kerf offset" in message or "offset path" in message or "self-intersects" in message or "zero area" in message


def _offset_closed_polygon(points: list[Point], distance: float, *, inward: bool) -> list[Point]:
    if abs(distance) <= 1e-9:
        output = list(points)
        _assert_valid_polygon(output, "Contour path")
        return output
    if pyclipper is not None:
        return _offset_closed_polygon_pyclipper(points, distance, inward=inward)
    return _offset_closed_polygon_fallback(points, distance, inward=inward)


def _offset_closed_polygon_pyclipper(points: list[Point], distance: float, *, inward: bool) -> list[Point]:
    _assert_valid_polygon(points, "Contour path")
    scale = 10000.0
    path = _points_to_clipper_path(points, scale)
    if len(path) < 3:
        raise ValueError("Contour path has fewer than 3 usable offset points")
    delta = -distance if inward else distance
    offset = pyclipper.PyclipperOffset(miter_limit=2.0)
    offset.AddPath(path, pyclipper.JT_MITER, pyclipper.ET_CLOSEDPOLYGON)
    solution = offset.Execute(delta * scale)
    if not solution:
        raise ValueError("Kerf offset collapsed contour")
    if len(solution) > 1:
        raise ValueError("Kerf offset split contour")
    output = _clipper_path_to_points(solution[0], scale)
    if len(output) < 3 or abs(signed_area(output)) <= 1e-6:
        raise ValueError("Kerf offset collapsed contour")
    _assert_valid_polygon(output, "Kerf offset")
    return output


def _points_to_clipper_path(points: list[Point], scale: float) -> list[tuple[int, int]]:
    path: list[tuple[int, int]] = []
    for point in points:
        scaled = (int(round(point.x * scale)), int(round(point.y * scale)))
        if not path or path[-1] != scaled:
            path.append(scaled)
    if len(path) > 1 and path[0] == path[-1]:
        path.pop()
    return path


def _clipper_path_to_points(path: list[tuple[int, int]], scale: float) -> list[Point]:
    points = [Point(x / scale, y / scale) for x, y in path]
    if len(points) > 1 and points[0].almost_equals(points[-1], tolerance=1e-9):
        points.pop()
    return points


def _offset_closed_polygon_fallback(points: list[Point], distance: float, *, inward: bool) -> list[Point]:
    area = signed_area(points)
    if abs(area) <= 1e-6:
        raise ValueError("Cannot offset zero-area contour")
    _assert_valid_polygon(points, "Contour path")
    side = (1.0 if area > 0 else -1.0) * (1.0 if inward else -1.0)
    output: list[Point] = []
    count = len(points)
    miter_limit = max(abs(distance) * 8.0, 2.0)
    for index, vertex in enumerate(points):
        prev_point = points[index - 1]
        next_point = points[(index + 1) % count]
        prev_line = _offset_line(prev_point, vertex, distance * side)
        next_line = _offset_line(vertex, next_point, distance * side)
        intersection = _line_intersection(prev_line[0], prev_line[1], next_line[0], next_line[1])
        if intersection is not None and vertex.distance_to(intersection) <= miter_limit:
            _append_offset_point(output, intersection)
        else:
            _append_offset_point(output, prev_line[1])
            _append_offset_point(output, next_line[0])
    if len(output) > 1 and output[0].almost_equals(output[-1], tolerance=1e-6):
        output.pop()
    if len(output) < 3 or abs(signed_area(output)) <= 1e-6:
        raise ValueError("Kerf offset collapsed contour")
    _assert_valid_polygon(output, "Kerf offset")
    return output


def _assert_valid_polygon(points: list[Point], label: str) -> None:
    if len(points) < 3 or abs(signed_area(points)) <= 1e-6:
        raise ValueError(f"{label} has zero area")
    if Polygon is not None:
        polygon = Polygon((point.x, point.y) for point in points)
        if polygon.is_empty or polygon.area <= 1e-6:
            raise ValueError(f"{label} has zero area")
        if not polygon.is_valid:
            raise ValueError(f"{label} self-intersects")
        return
    if _has_self_intersections(points):
        raise ValueError(f"{label} self-intersects")


def _has_self_intersections(points: list[Point]) -> bool:
    count = len(points)
    if count < 4:
        return False
    for left_index in range(count):
        left_start = points[left_index]
        left_end = points[(left_index + 1) % count]
        for right_index in range(left_index + 1, count):
            if abs(left_index - right_index) <= 1:
                continue
            if left_index == 0 and right_index == count - 1:
                continue
            right_start = points[right_index]
            right_end = points[(right_index + 1) % count]
            if segments_intersect(left_start, left_end, right_start, right_end):
                return True
    return False


def _append_offset_point(points: list[Point], point: Point) -> None:
    if not points or not points[-1].almost_equals(point, tolerance=1e-6):
        points.append(point)


def _offset_line(start: Point, end: Point, signed_distance: float) -> tuple[Point, Point]:
    normal = _left_normal(start, end)
    return (
        Point(start.x + normal.x * signed_distance, start.y + normal.y * signed_distance),
        Point(end.x + normal.x * signed_distance, end.y + normal.y * signed_distance),
    )


def _left_normal(start: Point, end: Point) -> Point:
    dx = end.x - start.x
    dy = end.y - start.y
    length = math.hypot(dx, dy)
    if length <= 1e-9:
        raise ValueError("Cannot offset zero-length segment")
    return Point(-dy / length, dx / length)


def _line_intersection(a0: Point, a1: Point, b0: Point, b1: Point) -> Point | None:
    dax = a1.x - a0.x
    day = a1.y - a0.y
    dbx = b1.x - b0.x
    dby = b1.y - b0.y
    denominator = dax * dby - day * dbx
    if abs(denominator) <= 1e-9:
        return None
    t = ((b0.x - a0.x) * dby - (b0.y - a0.y) * dbx) / denominator
    return Point(a0.x + dax * t, a0.y + day * t)
