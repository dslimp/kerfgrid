"""Route rapids around fixed obstacles and completed cutouts."""

from __future__ import annotations

import math
import heapq
from dataclasses import dataclass
from functools import lru_cache
import re
from typing import Iterable

try:
    from shapely.geometry import LineString, Polygon, Point as ShapePoint, box
    from shapely.ops import unary_union
except ModuleNotFoundError:
    LineString = None
    box = None
    Polygon = None

from ..model import ArcSegment, CircleContour, Contour, PathContour, Point
from .gcode import comment_text, format_number, gcode_line
from .options import QtPlasmaCOptions, TravelObstacle


_WORD_RE = re.compile(r"([A-Z])([-+]?(?:\d+(?:\.\d*)?|\.\d+))")
SAFE_TRAVEL_MAX_ROUTE_NODES = 1024
SAFE_TRAVEL_MAX_OBSTACLES = 200


def line_comment(line: str) -> str | None:
    start = line.find("(")
    end = line.rfind(")")
    return line[start + 1 : end] if start >= 0 and end > start else None


def last_motion_point(lines: Iterable[str], current: Point) -> Point:
    point = current
    for line in lines:
        target = motion_target_from_line(line, point)
        if target is not None:
            point = target
    return point


def motion_target_from_line(line: str, current: Point) -> Point | None:
    code = re.sub(r"\([^)]*\)", "", line).upper()
    words = {match.group(1): float(match.group(2)) for match in _WORD_RE.finditer(code)}
    if "G" not in words or int(words["G"]) not in (0, 1, 2, 3):
        return None
    return Point(float(words.get("X", current.x)), float(words.get("Y", current.y)))


@dataclass(frozen=True)
class _Region:
    shape: object
    core: object
    completed: bool


_EPS = 1e-6


def safe_rapid_lines(start, end, obstacles, options, comment):
    direct = f"G0 X{format_number(end.x, options.precision)} Y{format_number(end.y, options.precision)}"
    if start.distance_to(end) <= _EPS or not options.safe_travel:
        return [gcode_line(direct, comment, options)]
    if len(obstacles) > SAFE_TRAVEL_MAX_OBSTACLES:
        return _unresolved_rapid(direct, start, end, options, comment, f"obstacle set too complex ({len(obstacles)} obstacles)")
    if LineString is None:
        return _unresolved_rapid(direct, start, end, options, comment, "geometry routing unavailable") if obstacles else [gcode_line(direct, comment, options)]
    clearance = options.travel_clearance + 2 * 10 ** -options.precision
    active = _expanded_obstacles(obstacles, clearance)
    if not active or not _segment_blocked(start, end, active):
        return [gcode_line(direct, comment, options)]
    route = _safe_travel_route(start, end, active, options.travel_bounds)
    if route is None:
        return _unresolved_rapid(direct, start, end, options, comment, "route blocked")
    return [gcode_line(
        f"G0 X{format_number(point.x, options.precision)} Y{format_number(point.y, options.precision)}",
        comment if index == len(route) - 1 else "safe rapid", options,
    ) for index, point in enumerate(route[1:], start=1)]


def rapid_distance(start, end, obstacles, options):
    if not options.safe_travel or not obstacles:
        return start.distance_to(end)
    if LineString is None or len(obstacles) > SAFE_TRAVEL_MAX_OBSTACLES:
        return math.inf
    active = _expanded_obstacles(obstacles, options.travel_clearance + 2 * 10 ** -options.precision)
    if not _segment_blocked(start, end, active):
        return start.distance_to(end)
    route = _safe_travel_route(start, end, active, options.travel_bounds)
    return math.inf if route is None else sum(a.distance_to(b) for a, b in zip(route, route[1:]))


def _unresolved_rapid(direct, start, end, options, comment, reason):
    warning = comment_text(f"WARNING: safe travel {reason}")[:76]
    lines = ["M0 (Safe travel blocked: clear the route before resuming)",
             "(using direct rapid after operator pause)"]
    if comment and options.include_comments:
        lines.append(f"({comment_text(comment)[:76]})")
    return [*lines, f"{direct} ({warning})"]


@lru_cache(maxsize=2048)
def contour_obstacle(contour: Contour) -> TravelObstacle | None:
    if isinstance(contour, PathContour) and not contour.is_closed():
        return None
    xmin, ymin, xmax, ymax = contour.bbox()
    if isinstance(contour, CircleContour):
        count = 24
        radius = contour.radius / math.cos(math.pi / count)
        outline = tuple(Point(contour.center.x + radius * math.cos(math.tau * i / count),
                              contour.center.y + radius * math.sin(math.tau * i / count)) for i in range(count))
    else:
        outline = tuple(contour.points(max_chord=2.0))
        if len(outline) < 3:
            return None
        if Polygon is not None:
            padding = 0.0
            for segment in contour.segments:
                if isinstance(segment, ArcSegment):
                    points = segment.points(max_chord=2.0)
                    padding = max(padding, max(segment.radius - math.hypot((a.x + b.x) / 2 - segment.center.x,
                                                                           (a.y + b.y) / 2 - segment.center.y)
                                               for a, b in zip(points, points[1:])))
            polygon = Polygon([(p.x, p.y) for p in outline])
            if polygon.is_valid and padding > 0:
                outline = tuple(Point(x, y) for x, y in polygon.buffer(padding, join_style=2).exterior.coords[:-1])
    return TravelObstacle(xmin, ymin, xmax, ymax, contour.name, outline, True)


def _point_label(point, options):
    return f"X{format_number(point.x, options.precision)} Y{format_number(point.y, options.precision)}"


@lru_cache(maxsize=4096)
def _region(obstacle, clearance):
    core = Polygon([(p.x, p.y) for p in obstacle.outline]) if obstacle.outline else box(obstacle.xmin, obstacle.ymin, obstacle.xmax, obstacle.ymax)
    if not core.is_valid or core.is_empty or core.area <= 0:
        core = box(obstacle.xmin, obstacle.ymin, obstacle.xmax, obstacle.ymax)
    return _Region(core.buffer(clearance, join_style=2), core, obstacle.completed)


def _expanded_obstacles(obstacles, clearance):
    return [_region(obstacle, clearance) for obstacle in obstacles
            if obstacle.xmax > obstacle.xmin and obstacle.ymax > obstacle.ymin]


def _rings(shape):
    for polygon in shape.geoms if hasattr(shape, 'geoms') else [shape]:
        if polygon.geom_type == 'Polygon':
            yield list(polygon.exterior.coords)
            for ring in polygon.interiors:
                yield list(ring.coords)


def _inside_bounds(point, bounds):
    return bounds is None or (bounds[0] - _EPS <= point.x <= bounds[2] + _EPS and bounds[1] - _EPS <= point.y <= bounds[3] + _EPS)


def _safe_travel_route(start, end, obstacles, bounds):
    return _cached_route(start, end, tuple(obstacles), bounds)


@lru_cache(maxsize=512)
def _cached_route(start, end, obstacles, bounds):
    if not _inside_bounds(start, bounds) or not _inside_bounds(end, bounds):
        return None
    boundary = unary_union([obstacle.shape for obstacle in obstacles])
    if bounds is not None:
        boundary = boundary.intersection(box(*bounds))
    nodes = [start, end]
    candidates = [Point(x, y) for ring in _rings(boundary) for x, y in ring[:-1]]
    for endpoint in (start, end):
        source = ShapePoint(endpoint.x, endpoint.y)
        for obstacle in obstacles:
            if not obstacle.completed or not obstacle.shape.contains(source):
                continue
            minimum = obstacle.shape.boundary.distance(source)
            for ring in _rings(obstacle.shape):
                for a, b in zip(ring, ring[1:]):
                    edge = LineString([a, b])
                    point = edge.interpolate(edge.project(source))
                    if point.distance(source) <= minimum + _EPS:
                        candidates.append(Point(point.x, point.y))
    if bounds:
        candidates.extend(Point(x, y) for x in (bounds[0], bounds[2]) for y in (bounds[1], bounds[3]))
    seen = {(start.x, start.y), (end.x, end.y)}
    for candidate in candidates:
        key = (round(candidate.x, 8), round(candidate.y, 8))
        if key not in seen and _inside_bounds(candidate, bounds):
            nodes.append(candidate)
            seen.add(key)
    if len(nodes) > SAFE_TRAVEL_MAX_ROUTE_NODES:
        return None
    distances = [math.inf] * len(nodes)
    previous = [None] * len(nodes)
    distances[0] = 0.0
    pending = [(start.distance_to(end), 0.0, 0)]
    visited = set()
    while pending:
        _, cost, index = heapq.heappop(pending)
        if index in visited:
            continue
        if index == 1:
            route = []
            while index is not None:
                route.append(nodes[index])
                index = previous[index]
            return tuple(_simplify_route(list(reversed(route)), obstacles))
        visited.add(index)
        for neighbor, point in enumerate(nodes):
            if neighbor in visited or neighbor == index:
                continue
            distance = cost + nodes[index].distance_to(point)
            if distance + _EPS >= distances[neighbor] or _segment_blocked(nodes[index], point, obstacles):
                continue
            distances[neighbor] = distance
            previous[neighbor] = index
            heapq.heappush(pending, (distance + point.distance_to(end), distance, neighbor))
    return None


def _simplify_route(route, obstacles):
    simplified = [route[0]]
    index = 0
    while index < len(route) - 1:
        following = len(route) - 1
        while following > index + 1 and _segment_blocked(route[index], route[following], obstacles):
            following -= 1
        simplified.append(route[following])
        index = following
    return simplified


def _segment_blocked(start, end, obstacles):
    if start.distance_to(end) <= _EPS:
        return False
    line = LineString([(start.x, start.y), (end.x, end.y)])
    source = ShapePoint(start.x, start.y)
    target = ShapePoint(end.x, end.y)
    xmin, ymin, xmax, ymax = line.bounds
    for obstacle in obstacles:
        left, bottom, right, top = obstacle.shape.bounds
        if xmax < left or xmin > right or ymax < bottom or ymin > top:
            continue
        if line.relate_pattern(obstacle.shape, 'F********'):
            continue
        if not obstacle.completed:
            return True
        if not _endpoint_overlap_only(line, obstacle.shape, source, target, allow_entry=True):
            return True
        if not _endpoint_overlap_only(line, obstacle.core, source, target, allow_entry=False):
            return True
    return False


def _endpoint_overlap_only(line, shape, source, target, *, allow_entry):
    if line.relate_pattern(shape, 'F********'):
        return True
    prefix = shape.boundary.distance(source) if shape.covers(source) else 0.0
    suffix = shape.boundary.distance(target) if allow_entry and shape.covers(target) else 0.0
    intersection = line.intersection(shape.buffer(-_EPS / 10))
    for piece in intersection.geoms if hasattr(intersection, 'geoms') else [intersection]:
        if piece.geom_type != 'LineString' or piece.length <= _EPS:
            continue
        positions = [line.project(ShapePoint(x, y)) for x, y in piece.coords]
        a, b = min(positions), max(positions)
        if a <= _EPS and b <= prefix + _EPS:
            continue
        if b >= line.length - _EPS and a >= line.length - suffix - _EPS:
            continue
        return False
    return True
