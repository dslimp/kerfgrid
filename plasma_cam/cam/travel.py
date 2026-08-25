"""Safe rapid routing around rectangular travel obstacles."""

from __future__ import annotations

import math
import re
from typing import Iterable

try:
    from shapely.geometry import LineString, box
except ModuleNotFoundError:
    LineString = None
    box = None

from ..model import Contour, Point
from .gcode import format_number, gcode_line
from .geometry import segments_intersect
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


def safe_rapid_lines(
    start: Point,
    end: Point,
    obstacles: list[TravelObstacle],
    options: QtPlasmaCOptions,
    comment: str | None,
) -> list[str]:
    direct = f"G0 X{format_number(end.x, options.precision)} Y{format_number(end.y, options.precision)}"
    if start.distance_to(end) <= 1e-9 or not options.safe_travel:
        return [gcode_line(direct, comment, options)]
    if len(obstacles) > SAFE_TRAVEL_MAX_OBSTACLES:
        return [gcode_line(direct, _complexity_warning(start, end, len(obstacles), comment, options), options)]
    active = _expanded_obstacles(obstacles, options.travel_clearance)
    if len(active) > SAFE_TRAVEL_MAX_OBSTACLES:
        return [gcode_line(direct, _complexity_warning(start, end, len(active), comment, options), options)]
    if not active or not _segment_blocked(start, end, active):
        return [gcode_line(direct, comment, options)]
    route = _safe_travel_route(start, end, active, options.travel_bounds)
    if route is None:
        warning = f"WARNING: safe travel route blocked from {_point_label(start, options)} to {_point_label(end, options)}; using direct rapid"
        if comment:
            warning = f"{warning}; {comment}"
        return [gcode_line(direct, warning, options)]
    output = []
    for index, point in enumerate(route[1:], start=1):
        output.append(
            gcode_line(
                f"G0 X{format_number(point.x, options.precision)} Y{format_number(point.y, options.precision)}",
                comment if index == len(route) - 1 else "safe rapid",
                options,
            )
        )
    return output


def contour_obstacle(contour: Contour) -> TravelObstacle:
    xmin, ymin, xmax, ymax = contour.bbox()
    return TravelObstacle(xmin, ymin, xmax, ymax, contour.name)


def _complexity_warning(
    start: Point,
    end: Point,
    count: int,
    comment: str | None,
    options: QtPlasmaCOptions,
) -> str:
    warning = (
        f"WARNING: safe travel obstacle set too complex ({count} obstacles); "
        f"using direct rapid from {_point_label(start, options)} to {_point_label(end, options)}"
    )
    return f"{warning}; {comment}" if comment else warning


def _expanded_obstacles(obstacles: Iterable[TravelObstacle], clearance: float) -> list[TravelObstacle]:
    return [obstacle.expanded(clearance) for obstacle in obstacles if obstacle.xmax > obstacle.xmin and obstacle.ymax > obstacle.ymin]


def _point_label(point: Point, options: QtPlasmaCOptions) -> str:
    return f"X{format_number(point.x, options.precision)} Y{format_number(point.y, options.precision)}"


def _safe_travel_route(
    start: Point,
    end: Point,
    obstacles: list[TravelObstacle],
    bounds: tuple[float, float, float, float] | None,
) -> list[Point] | None:
    x_values = {round(start.x, 3), round(end.x, 3)}
    y_values = {round(start.y, 3), round(end.y, 3)}
    for obstacle in obstacles:
        for value in (obstacle.xmin, obstacle.xmax):
            _add_route_value(x_values, value, bounds[0], bounds[2]) if bounds else x_values.add(round(value, 3))
        for value in (obstacle.ymin, obstacle.ymax):
            _add_route_value(y_values, value, bounds[1], bounds[3]) if bounds else y_values.add(round(value, 3))
    if bounds is not None:
        _add_route_value(x_values, bounds[0], bounds[0], bounds[2])
        _add_route_value(x_values, bounds[2], bounds[0], bounds[2])
        _add_route_value(y_values, bounds[1], bounds[1], bounds[3])
        _add_route_value(y_values, bounds[3], bounds[1], bounds[3])
    if len(x_values) * len(y_values) > SAFE_TRAVEL_MAX_ROUTE_NODES:
        return None
    nodes = _route_nodes(x_values, y_values, bounds)
    start_index = _ensure_route_node(nodes, start)
    end_index = _ensure_route_node(nodes, end)
    distances = [math.inf] * len(nodes)
    previous: list[int | None] = [None] * len(nodes)
    pending = set(range(len(nodes)))
    distances[start_index] = 0.0
    while pending:
        current_index = min(pending, key=lambda item: distances[item])
        if distances[current_index] == math.inf:
            break
        pending.remove(current_index)
        if current_index == end_index:
            break
        current = nodes[current_index]
        for neighbor_index in list(pending):
            neighbor = nodes[neighbor_index]
            if abs(current.x - neighbor.x) > 1e-6 and abs(current.y - neighbor.y) > 1e-6:
                continue
            if _segment_blocked(current, neighbor, obstacles):
                continue
            cost = current.distance_to(neighbor)
            if distances[current_index] + cost < distances[neighbor_index]:
                distances[neighbor_index] = distances[current_index] + cost
                previous[neighbor_index] = current_index
    if distances[end_index] == math.inf:
        return None
    route = []
    cursor: int | None = end_index
    while cursor is not None:
        route.append(nodes[cursor])
        cursor = previous[cursor]
    route.reverse()
    return _simplify_route(route, obstacles)


def _add_route_value(values: set[float], value: float, minimum: float, maximum: float) -> None:
    if minimum - 1e-6 <= value <= maximum + 1e-6:
        values.add(round(min(max(value, minimum), maximum), 3))


def _route_nodes(
    x_values: set[float],
    y_values: set[float],
    bounds: tuple[float, float, float, float] | None,
) -> list[Point]:
    nodes = []
    seen = set()
    for x in sorted(x_values):
        for y in sorted(y_values):
            if bounds is not None and (x < bounds[0] - 1e-6 or x > bounds[2] + 1e-6 or y < bounds[1] - 1e-6 or y > bounds[3] + 1e-6):
                continue
            key = (round(x, 3), round(y, 3))
            if key not in seen:
                seen.add(key)
                nodes.append(Point(key[0], key[1]))
    return nodes


def _ensure_route_node(nodes: list[Point], point: Point) -> int:
    for index, node in enumerate(nodes):
        if node.distance_to(point) <= 1e-6:
            return index
    nodes.append(point)
    return len(nodes) - 1


def _simplify_route(route: list[Point], obstacles: list[TravelObstacle]) -> list[Point]:
    if len(route) <= 2:
        return route
    simplified = [route[0]]
    index = 0
    while index < len(route) - 1:
        next_index = len(route) - 1
        while next_index > index + 1 and _segment_blocked(route[index], route[next_index], obstacles):
            next_index -= 1
        simplified.append(route[next_index])
        index = next_index
    return simplified


def _segment_blocked(start: Point, end: Point, obstacles: list[TravelObstacle]) -> bool:
    if start.distance_to(end) <= 1e-9:
        return False
    for obstacle in obstacles:
        if _point_in_obstacle(start, obstacle) or _point_in_obstacle(end, obstacle):
            continue
        if _segment_hits_obstacle(start, end, obstacle):
            return True
    return False


def _point_in_obstacle(point: Point, obstacle: TravelObstacle) -> bool:
    return obstacle.xmin - 1e-6 <= point.x <= obstacle.xmax + 1e-6 and obstacle.ymin - 1e-6 <= point.y <= obstacle.ymax + 1e-6


def _segment_hits_obstacle(start: Point, end: Point, obstacle: TravelObstacle) -> bool:
    if not _boxes_overlap(
        (min(start.x, end.x), min(start.y, end.y), max(start.x, end.x), max(start.y, end.y)),
        (obstacle.xmin, obstacle.ymin, obstacle.xmax, obstacle.ymax),
    ):
        return False
    if LineString is not None and box is not None:
        line = LineString([(start.x, start.y), (end.x, end.y)])
        rect = box(obstacle.xmin, obstacle.ymin, obstacle.xmax, obstacle.ymax)
        return not (line.disjoint(rect) or line.touches(rect))
    corners = [
        Point(obstacle.xmin, obstacle.ymin),
        Point(obstacle.xmax, obstacle.ymin),
        Point(obstacle.xmax, obstacle.ymax),
        Point(obstacle.xmin, obstacle.ymax),
    ]
    return any(segments_intersect(start, end, corner, corners[(index + 1) % len(corners)]) for index, corner in enumerate(corners))


def _boxes_overlap(left: tuple[float, float, float, float], right: tuple[float, float, float, float]) -> bool:
    return not (left[2] <= right[0] or right[2] <= left[0] or left[3] <= right[1] or right[3] <= left[1])
