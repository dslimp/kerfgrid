"""QtPlasmaC G-code generator."""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Iterable

try:
    from shapely.geometry import Polygon
except ModuleNotFoundError:
    Polygon = None

from .cut_settings import format_qtplasmac_material_comment
from .cam.kerf import offset_path_points as _offset_path_points
from .cam.gcode import comment_text as _comment_text, format_number as _fmt, gcode_line as _line
from .cam.options import CutTab, LeadMove, LeadOverride, QtPlasmaCOptions, TravelObstacle
from .cam.travel import (
    contour_obstacle as _contour_obstacle,
    last_motion_point as _last_motion_point,
    line_comment as _line_comment,
    motion_target_from_line as _motion_target_from_line,
    safe_rapid_lines as _safe_rapid_lines,
    rapid_distance as _rapid_distance,
)
from .model import (
    ArcSegment,
    CircleContour,
    Contour,
    LineSegment,
    PathContour,
    Point,
    bbox_for_contours,
    contour_diameter,
    order_contours,
    signed_area,
)
from .validation import assert_valid_gcode


CUT_ORDER_OPTIMIZE_MAX_CONTOURS = 2_000
GCODE_COMMENT_MAX_LEN = 80


def _append_comment(lines: list[str], text: str) -> None:
    lines.append(f"({_comment_text(text)})")


def _append_wrapped_comment(lines: list[str], prefix: str, text: str) -> None:
    value = _comment_text(text or "-")
    first_prefix = prefix
    next_prefix = f"{prefix}+"
    while value:
        active_prefix = first_prefix if not lines or not lines[-1].startswith(f"({prefix}") else next_prefix
        available = max(1, GCODE_COMMENT_MAX_LEN - len(active_prefix) - 2)
        if len(value) <= available:
            _append_comment(lines, f"{active_prefix}{value}")
            return
        cut = value.rfind(" ", 0, available + 1)
        if cut <= 0:
            cut = available
        _append_comment(lines, f"{active_prefix}{value[:cut]}")
        value = value[cut:].strip()


def _effective_kerf_width(options: QtPlasmaCOptions) -> float:
    if options.common_line_cutting and options.kerf_offset_fallback == "centerline":
        return 0.0
    if options.kerf_width is not None:
        return options.kerf_width
    if options.cut_settings is not None:
        return options.cut_settings.kerf_width_mm
    return 0.0


def _path_radius(contour: CircleContour, options: QtPlasmaCOptions) -> float:
    offset = _effective_kerf_width(options) / 2.0
    radius = contour.radius - offset if contour.kind in ("hole", "inner") else contour.radius + offset
    if radius <= 0:
        if options.kerf_offset_fallback == "centerline" and contour.radius > 0:
            return contour.radius
        raise ValueError(f"{contour.name} path radius is not positive")
    return radius


def _is_small_feature(contour: Contour, options: QtPlasmaCOptions) -> bool:
    diameter = contour_diameter(contour)
    if contour.kind in ("hole", "inner"):
        return diameter <= options.small_hole_threshold
    return diameter <= options.small_shape_threshold


def _lead_in_for_contour(contour: Contour, contour_size: float, options: QtPlasmaCOptions) -> tuple[str, float]:
    override = _lead_override_for(contour, options)
    mode_setting = override.lead_in_mode if override and override.lead_in_mode is not None else options.lead_in_mode
    lead_setting = override.lead_in if override and override.lead_in is not None else options.lead_in
    if mode_setting == "none" or lead_setting <= 0:
        return ("none", 0.0)
    if contour.kind == "hole" and contour_size < options.lead_in_min_hole_diameter:
        return ("none", 0.0)
    lead = min(lead_setting, contour_size * 0.4)
    if lead <= 0:
        return ("none", 0.0)
    mode = "arc" if mode_setting == "auto" else mode_setting
    return (mode, lead)


def _lead_out_for_contour(contour: Contour, contour_size: float, options: QtPlasmaCOptions) -> float:
    override = _lead_override_for(contour, options)
    lead_out = override.lead_out if override and override.lead_out is not None else options.lead_out
    return min(max(lead_out, 0.0), contour_size * 0.4)


def _lead_override_for(contour: Contour, options: QtPlasmaCOptions) -> LeadOverride | None:
    for override in options.lead_overrides:
        if _name_matches(contour.name, override.contour_name):
            return override
    return None


def _tabs_for_contour(contour: Contour, options: QtPlasmaCOptions) -> list[CutTab]:
    explicit = [tab for tab in options.tabs if _name_matches(contour.name, tab.contour_name)]
    if explicit or not options.auto_tabs:
        return explicit
    return _auto_tabs_for_contour(contour, options)


def _auto_tabs_for_contour(contour: Contour, options: QtPlasmaCOptions) -> list[CutTab]:
    if contour.kind != "outer" or options.auto_tab_length <= 0:
        return []
    if contour_diameter(contour) < options.auto_tab_min_outer_diameter:
        return []
    points = contour.points(max_chord=max(options.path_tolerance * 12.0, 2.0))
    if len(points) < 4:
        return []
    count = min(options.auto_tab_count, max(1, len(points) // 2))
    perimeter = sum(start.distance_to(end) for start, end in zip(points, [*points[1:], points[0]]))
    if perimeter <= 1e-6:
        return []
    output = []
    for index in range(count):
        point = _point_at_polyline_distance(points, (index + 0.5) * perimeter / count)
        output.append(CutTab(contour.name, point.x, point.y, options.auto_tab_length))
    return output


def _point_at_polyline_distance(points: list[Point], target_distance: float) -> Point:
    traveled = 0.0
    for start, end in zip(points, [*points[1:], points[0]]):
        length = start.distance_to(end)
        if length <= 1e-9:
            continue
        if traveled + length >= target_distance:
            fraction = (target_distance - traveled) / length
            return Point(start.x + (end.x - start.x) * fraction, start.y + (end.y - start.y) * fraction)
        traveled += length
    return points[-1]


def _name_matches(actual: str, requested: str) -> bool:
    return actual == requested or actual.endswith(f"_{requested}") or requested.endswith(f"_{actual}")


def planned_lead_moves(contours: Iterable[Contour], options: QtPlasmaCOptions) -> tuple[LeadMove, ...]:
    ordered = _optimized_cut_order(contours, options)
    common_line_skips = _common_line_skip_map(ordered, options) if options.common_line_cutting else {}
    moves: list[LeadMove] = []
    for contour in ordered:
        skips = common_line_skips.get(contour.name, frozenset())
        if skips and isinstance(contour, PathContour):
            moves.extend(_common_line_lead_moves(contour, skips, options))
            continue
        moves.append(_lead_move_for_contour(contour, options))
    return tuple(moves)


def planned_cut_sequence(contours: Iterable[Contour], options: QtPlasmaCOptions) -> tuple[dict[str, object], ...]:
    ordered = _optimized_cut_order(contours, options)
    output: list[dict[str, object]] = []
    for index, contour in enumerate(ordered, start=1):
        xmin, ymin, xmax, ymax = contour.bbox()
        entry = _contour_entry_point(contour, options)
        output.append(
            {
                "sequence": index,
                "name": contour.name,
                "kind": contour.kind,
                "source": contour.source,
                "group": _contour_group_key(contour),
                "entry": {"x": round(entry.x, options.precision), "y": round(entry.y, options.precision)},
                "bbox": {
                    "xmin": round(xmin, options.precision),
                    "ymin": round(ymin, options.precision),
                    "xmax": round(xmax, options.precision),
                    "ymax": round(ymax, options.precision),
                },
                "small_feature": _is_small_feature(contour, options),
            }
        )
    return tuple(output)


def _lead_move_for_contour(contour: Contour, options: QtPlasmaCOptions) -> LeadMove:
    if isinstance(contour, CircleContour):
        return _circle_lead_move(contour, options)
    if isinstance(contour, PathContour):
        return _path_lead_move(contour, options)
    raise TypeError(f"Unsupported contour type: {type(contour).__name__}")


def _common_line_lead_moves(
    contour: PathContour,
    skip_segments: frozenset[int],
    options: QtPlasmaCOptions,
) -> list[LeadMove]:
    moves = []
    small_feature = _is_small_feature(contour, options)
    for index, chain in enumerate(_open_chains_from_skipped_segments(contour, skip_segments, options), start=1):
        if len(chain) < 2:
            continue
        moves.append(
            LeadMove(
                contour_name=f"{contour.name}_common_{index}",
                contour_kind=contour.kind,
                pierce=chain[0],
                start=chain[0],
                lead_in_mode="none",
                lead_in=0.0,
                small_feature=small_feature,
            )
        )
    return moves


def _circle_lead_move(contour: CircleContour, options: QtPlasmaCOptions) -> LeadMove:
    radius = _path_radius(contour, options)
    small_feature = _is_small_feature(contour, options)
    lead_mode, lead = _lead_in_for_contour(contour, radius * 2.0, options)
    override = _lead_override_for(contour, options)
    start_angle = 0.0
    if override and override.start_x is not None and override.start_y is not None:
        start_angle = math.atan2(override.start_y - contour.center.y, override.start_x - contour.center.x)
    start = Point(
        contour.center.x + math.cos(start_angle) * radius,
        contour.center.y + math.sin(start_angle) * radius,
    )
    radial = Point(math.cos(start_angle), math.sin(start_angle))
    if override and override.start_x is not None and override.start_y is not None and lead_mode == "arc":
        lead_mode = "line"
    if contour.kind in ("hole", "inner"):
        line_pierce = Point(start.x - radial.x * lead, start.y - radial.y * lead)
        arc_pierce = Point(start.x - lead, start.y - lead)
        arc_center = Point(start.x - lead, start.y)
    else:
        line_pierce = Point(start.x + radial.x * lead, start.y + radial.y * lead)
        arc_pierce = Point(start.x + lead, start.y + lead)
        arc_center = Point(start.x + lead, start.y)
    if lead_mode == "arc":
        pierce = arc_pierce
        lead_in_points = tuple(ArcSegment(pierce, start, arc_center, clockwise=False).points(max_chord=0.5))
    elif lead_mode == "line":
        pierce = line_pierce
        lead_in_points = (pierce, start)
    else:
        pierce = start
        lead_in_points = ()
    if override and override.pierce_x is not None and override.pierce_y is not None:
        pierce = Point(override.pierce_x, override.pierce_y)
        lead_in_points = (pierce, start) if not pierce.almost_equals(start) else ()
        if lead_mode == "arc":
            lead_mode = "line"
    lead_out = _lead_out_for_contour(contour, radius * 2.0, options)
    lead_out_points: tuple[Point, ...] = ()
    if lead_out > 0 and not small_feature:
        out_y = start.y + lead_out if contour.kind in ("hole", "inner") else start.y - lead_out
        lead_out_points = (start, Point(start.x, out_y))
    return LeadMove(
        contour_name=contour.name,
        contour_kind=contour.kind,
        pierce=pierce,
        start=start,
        lead_in_mode=lead_mode,
        lead_in=lead,
        lead_in_points=lead_in_points,
        lead_out_points=lead_out_points,
        small_feature=small_feature,
    )


def _path_lead_move(contour: PathContour, options: QtPlasmaCOptions) -> LeadMove:
    if not contour.is_closed():
        return _open_path_lead_move(contour, options)
    points = _offset_path_points(contour, options)
    if len(points) < 2:
        raise ValueError(f"{contour.name} path has fewer than 2 points")
    small_feature = _is_small_feature(contour, options)
    diameter = contour_diameter(contour)
    override = _lead_override_for(contour, options)
    if override and override.start_x is not None and override.start_y is not None:
        points = _rotate_points_to_nearest(points, Point(override.start_x, override.start_y))
    lead_mode, lead = _lead_in_for_contour(contour, diameter, options)
    start = points[0]
    direction = _path_waste_direction(points, contour.kind)
    pierce = start if lead_mode == "none" else Point(start.x + direction.x * lead, start.y + direction.y * lead)
    if override and override.pierce_x is not None and override.pierce_y is not None:
        pierce = Point(override.pierce_x, override.pierce_y)
    lead_in_points = (pierce, start) if lead_mode != "none" and not pierce.almost_equals(start) else ()
    lead_out = _lead_out_for_contour(contour, diameter, options)
    lead_out_points: tuple[Point, ...] = ()
    if lead_out > 0 and not small_feature:
        lead_out_points = (start, Point(start.x + direction.x * lead_out, start.y + direction.y * lead_out))
    return LeadMove(
        contour_name=contour.name,
        contour_kind=contour.kind,
        pierce=pierce,
        start=start,
        lead_in_mode=lead_mode,
        lead_in=lead,
        lead_in_points=lead_in_points,
        lead_out_points=lead_out_points,
        small_feature=small_feature,
    )


def _path_waste_direction(points: list[Point], kind: str) -> Point:
    incoming = _unit_vector(points[-1], points[0])
    outgoing = _unit_vector(points[0], points[1])
    side = 1.0 if signed_area(points) > 0 else -1.0
    if kind == "outer":
        side = -side
    normal = Point(-(incoming.y + outgoing.y) * side, (incoming.x + outgoing.x) * side)
    length = math.hypot(normal.x, normal.y)
    if length <= 1e-9:
        return Point(-outgoing.y * side, outgoing.x * side)
    return Point(normal.x / length, normal.y / length)


def _open_path_lead_move(contour: PathContour, options: QtPlasmaCOptions) -> LeadMove:
    if options.open_path_mode != "centerline":
        raise ValueError(f"{contour.name} is not closed")
    points = _open_path_points(contour, options)
    small_feature = _is_small_feature(contour, options)
    return LeadMove(
        contour_name=contour.name,
        contour_kind=contour.kind,
        pierce=points[0],
        start=points[0],
        lead_in_mode="none",
        lead_in=0.0,
        small_feature=small_feature,
    )


def _circle_gcode(contour: CircleContour, options: QtPlasmaCOptions) -> list[str]:
    precision = options.precision
    radius = _path_radius(contour, options)
    small_feature = _is_small_feature(contour, options)
    lead_mode, lead = _lead_in_for_contour(contour, radius * 2.0, options)
    override = _lead_override_for(contour, options)
    start_angle = 0.0
    if override and override.start_x is not None and override.start_y is not None:
        start_angle = math.atan2(override.start_y - contour.center.y, override.start_x - contour.center.x)
    x_start = contour.center.x + math.cos(start_angle) * radius
    y_start = contour.center.y + math.sin(start_angle) * radius
    radial = Point(math.cos(start_angle), math.sin(start_angle))
    if override and override.start_x is not None and override.start_y is not None and lead_mode == "arc":
        lead_mode = "line"

    if contour.kind in ("hole", "inner"):
        arc_cmd = "G3"
        line_pierce = (x_start - radial.x * lead, y_start - radial.y * lead)
        arc_pierce = (x_start - lead, y_start - lead, "G3", 0.0, lead)
    else:
        arc_cmd = "G2"
        line_pierce = (x_start + radial.x * lead, y_start + radial.y * lead)
        arc_pierce = (x_start + lead, y_start + lead, "G3", 0.0, -lead)

    x_mid = contour.center.x - math.cos(start_angle) * radius
    y_mid = contour.center.y - math.sin(start_angle) * radius
    x_start_s = _fmt(x_start, precision)
    x_mid_s = _fmt(x_mid, precision)
    y_s = _fmt(y_start, precision)
    y_mid_s = _fmt(y_mid, precision)
    start_i = contour.center.x - x_start
    start_j = contour.center.y - y_start
    mid_i = contour.center.x - x_mid
    mid_j = contour.center.y - y_mid
    if lead_mode == "arc":
        x_pierce, y_pierce, lead_cmd, lead_i, lead_j = arc_pierce
    elif lead_mode == "line":
        x_pierce, y_pierce = line_pierce
        lead_cmd = ""
        lead_i = 0.0
        lead_j = 0.0
    else:
        x_pierce, y_pierce = x_start, y_start
        lead_cmd = ""
        lead_i = 0.0
        lead_j = 0.0
    if override and override.pierce_x is not None and override.pierce_y is not None:
        x_pierce = override.pierce_x
        y_pierce = override.pierce_y
        if lead_mode == "arc":
            lead_mode = "line"

    lines = [
        _line(
            f"G0 X{_fmt(x_pierce, precision)} Y{_fmt(y_pierce, precision)}",
            f"{contour.name} {contour.kind} pierce",
            options,
        )
    ]
    lines.extend(_torch_prepare_lines(contour, small_feature, options))
    lines.append("M3 $0 S1")
    if lead_mode == "arc":
        lines.append(
            _line(
                (
                    f"{lead_cmd} X{x_start_s} Y{y_s} "
                    f"I{_fmt(lead_i, precision)} J{_fmt(lead_j, precision)}"
                ),
                "arc lead in",
                options,
            )
        )
    elif lead_mode == "line":
        lines.append(_line(f"G1 X{x_start_s} Y{y_s}", "lead in", options))
    tabs = _tabs_for_contour(contour, options)
    if tabs:
        _append_circle_segments(lines, contour, radius, start_angle, tabs, options)
    else:
        lines.extend(
            [
                f"{arc_cmd} X{x_mid_s} Y{y_mid_s} I{_fmt(start_i, precision)} J{_fmt(start_j, precision)}",
                f"{arc_cmd} X{x_start_s} Y{y_s} I{_fmt(mid_i, precision)} J{_fmt(mid_j, precision)}",
            ]
        )
    lead_out = _lead_out_for_contour(contour, radius * 2.0, options)
    if lead_out > 0 and not small_feature:
        out_y = y_start + lead_out if contour.kind in ("hole", "inner") else y_start - lead_out
        lines.append(_line(f"G1 X{x_start_s} Y{_fmt(out_y, precision)}", "lead out", options))
    lines.append("M5 $0")
    lines.extend(_torch_restore_lines(small_feature, options))
    return lines


def _path_gcode(contour: PathContour, options: QtPlasmaCOptions, skip_segments: frozenset[int] = frozenset()) -> list[str]:
    if not contour.is_closed():
        return _open_path_gcode(contour, options)
    if skip_segments:
        return _path_gcode_with_common_line_skips(contour, skip_segments, options)

    precision = options.precision
    points = _offset_path_points(contour, options)
    if len(points) < 2:
        raise ValueError(f"{contour.name} path has fewer than 2 points")

    small_feature = _is_small_feature(contour, options)
    diameter = contour_diameter(contour)
    override = _lead_override_for(contour, options)
    if override and override.start_x is not None and override.start_y is not None:
        points = _rotate_points_to_nearest(points, Point(override.start_x, override.start_y))
    lead_mode, lead = _lead_in_for_contour(contour, diameter, options)
    start = points[0]
    next_point = points[1]
    tangent = _unit_vector(start, next_point)
    if lead_mode == "none":
        pierce = start
    else:
        direction = _path_waste_direction(points, contour.kind)
        pierce = Point(start.x + direction.x * lead, start.y + direction.y * lead)
    if override and override.pierce_x is not None and override.pierce_y is not None:
        pierce = Point(override.pierce_x, override.pierce_y)

    lines = [
        _line(
            f"G0 X{_fmt(pierce.x, precision)} Y{_fmt(pierce.y, precision)}",
            f"{contour.name} {contour.kind} pierce",
            options,
        )
    ]
    lines.extend(_torch_prepare_lines(contour, small_feature, options))
    lines.append("M3 $0 S1")
    if lead_mode != "none":
        lines.append(_line(f"G1 X{_fmt(start.x, precision)} Y{_fmt(start.y, precision)}", "lead in", options))
    tabs = _tabs_for_contour(contour, options)
    used_tabs: set[int] = set()
    previous = start
    for point in points[1:]:
        _append_path_segment(lines, previous, point, tabs, used_tabs, options)
        previous = point

    early_off = options.small_hole_torch_off_before_end if small_feature else 0.0
    closing_length = points[-1].distance_to(start)
    if early_off > 0 and closing_length > early_off + 1e-6:
        previous = points[-1]
        close_tangent = _unit_vector(previous, start)
        stop_point = Point(start.x - close_tangent.x * early_off, start.y - close_tangent.y * early_off)
        lines.append(
            _line(
                f"G1 X{_fmt(stop_point.x, precision)} Y{_fmt(stop_point.y, precision)}",
                "small feature early torch off",
                options,
            )
        )
        lines.append("M5 $0")
        lines.append(
            _line(
                f"G0 X{_fmt(start.x, precision)} Y{_fmt(start.y, precision)}",
                "torch off finish",
                options,
            )
        )
        lines.extend(_torch_restore_lines(small_feature, options))
        return lines

    _append_path_segment(lines, points[-1], start, tabs, used_tabs, options)
    if small_feature and options.small_hole_overburn > 0:
        overburn = min(options.small_hole_overburn, max(0.0, diameter * 0.25))
        if overburn > 0:
            over_point = Point(start.x + tangent.x * overburn, start.y + tangent.y * overburn)
            lines.append(
                _line(
                    f"G1 X{_fmt(over_point.x, precision)} Y{_fmt(over_point.y, precision)}",
                    "small feature overburn",
                    options,
                )
            )
    lead_out = _lead_out_for_contour(contour, diameter, options)
    if lead_out > 0 and not small_feature:
        direction = _path_waste_direction(points, contour.kind)
        out_point = Point(start.x + direction.x * lead_out, start.y + direction.y * lead_out)
        lines.append(_line(f"G1 X{_fmt(out_point.x, precision)} Y{_fmt(out_point.y, precision)}", "lead out", options))
    lines.append("M5 $0")
    lines.extend(_torch_restore_lines(small_feature, options))
    return lines


def _open_path_gcode(contour: PathContour, options: QtPlasmaCOptions) -> list[str]:
    if options.open_path_mode != "centerline":
        raise ValueError(f"{contour.name} is not closed")
    precision = options.precision
    points = _open_path_points(contour, options)
    small_feature = _is_small_feature(contour, options)
    start = points[0]
    lines = [
        _line(
            f"G0 X{_fmt(start.x, precision)} Y{_fmt(start.y, precision)}",
            f"{contour.name} open centerline pierce",
            options,
        )
    ]
    lines.extend(_torch_prepare_lines(contour, small_feature, options))
    lines.append("M3 $0 S1")
    for point in points[1:]:
        lines.append(f"G1 X{_fmt(point.x, precision)} Y{_fmt(point.y, precision)}")
    lines.append("M5 $0")
    lines.extend(_torch_restore_lines(small_feature, options))
    return lines


def _open_path_points(contour: PathContour, options: QtPlasmaCOptions) -> list[Point]:
    points = contour.points(max_chord=max(options.path_tolerance * 8.0, 0.5))
    if len(points) < 2:
        raise ValueError(f"{contour.name} open path has fewer than 2 points")
    return points


def _path_gcode_with_common_line_skips(
    contour: PathContour,
    skip_segments: frozenset[int],
    options: QtPlasmaCOptions,
) -> list[str]:
    if _effective_kerf_width(options) > 1e-9:
        raise ValueError("Common-line export requires kerf offset disabled or external compensation")
    if contour.kind != "outer":
        return _path_gcode(contour, options, frozenset())
    chains = _open_chains_from_skipped_segments(contour, skip_segments, options)
    if not chains:
        return []
    lines = [
        _line(
            f"(common line skipped {len(skip_segments)} shared segment{'s' if len(skip_segments) != 1 else ''} on {contour.name})",
            None,
            options,
        )
    ]
    small_feature = _is_small_feature(contour, options)
    precision = options.precision
    for chain_index, chain in enumerate(chains, start=1):
        if len(chain) < 2:
            continue
        start = chain[0]
        lines.append(
            _line(
                f"G0 X{_fmt(start.x, precision)} Y{_fmt(start.y, precision)}",
                f"{contour.name} common-line chain {chain_index} pierce",
                options,
            )
        )
        lines.extend(_torch_prepare_lines(contour, small_feature, options))
        lines.append("M3 $0 S1")
        for point in chain[1:]:
            lines.append(f"G1 X{_fmt(point.x, precision)} Y{_fmt(point.y, precision)}")
        lines.append("M5 $0")
        lines.extend(_torch_restore_lines(small_feature, options))
    return lines


def _open_chains_from_skipped_segments(
    contour: PathContour,
    skip_segments: frozenset[int],
    options: QtPlasmaCOptions,
) -> list[list[Point]]:
    count = len(contour.segments)
    if count == 0:
        return []
    starts = [
        index
        for index in range(count)
        if index not in skip_segments and (index - 1) % count in skip_segments
    ]
    chains = []
    visited: set[int] = set()
    for start_index in starts:
        chain: list[Point] = []
        index = start_index
        while index not in visited and index not in skip_segments:
            points = contour.segments[index].points(max_chord=max(options.path_tolerance * 8.0, 0.5))
            if chain and points and chain[-1].almost_equals(points[0], tolerance=1e-6):
                chain.extend(points[1:])
            else:
                chain.extend(points)
            visited.add(index)
            index = (index + 1) % count
        if len(chain) >= 2:
            chains.append(chain)
    return chains


def _torch_prepare_lines(contour: Contour, small_feature: bool, options: QtPlasmaCOptions) -> list[str]:
    lines: list[str] = []
    if small_feature and options.small_hole_disable_thc:
        lines.append("M64 P2")
    if small_feature:
        lines.append(f"M67 E3 Q{_fmt(options.small_hole_speed_percent, options.precision)}")
    return lines


def _torch_restore_lines(small_feature: bool, options: QtPlasmaCOptions) -> list[str]:
    lines: list[str] = []
    if small_feature:
        lines.append("M68 E3 Q0")
    if small_feature and options.small_hole_disable_thc:
        lines.append("M65 P2")
    return lines


def _rotate_points_to_nearest(points: list[Point], target: Point) -> list[Point]:
    if not points:
        return points
    best = None
    for index, start in enumerate(points):
        end = points[(index + 1) % len(points)]
        dx, dy = end.x - start.x, end.y - start.y
        squared = dx * dx + dy * dy
        fraction = max(0.0, min(1.0, ((target.x - start.x) * dx + (target.y - start.y) * dy) / squared)) if squared > 1e-12 else 0.0
        point = Point(start.x + fraction * dx, start.y + fraction * dy)
        candidate = (point.distance_to(target), index, point)
        if best is None or candidate[0] < best[0]:
            best = candidate
    _distance, index, point = best
    if point.almost_equals(points[index]):
        return [*points[index:], *points[:index]]
    following = (index + 1) % len(points)
    if point.almost_equals(points[following]):
        return [*points[following:], *points[:following]]
    return [point, *points[following:], *points[:following]]


def _append_path_segment(
    lines: list[str],
    start: Point,
    end: Point,
    tabs: list[CutTab],
    used_tabs: set[int],
    options: QtPlasmaCOptions,
) -> None:
    gap = _tab_gap_for_segment(start, end, tabs, used_tabs)
    precision = options.precision
    if gap is None:
        lines.append(f"G1 X{_fmt(end.x, precision)} Y{_fmt(end.y, precision)}")
        return
    tab_index, gap_start, gap_end = gap
    used_tabs.add(tab_index)
    if start.distance_to(gap_start) > 1e-6:
        lines.append(
            _line(
                f"G1 X{_fmt(gap_start.x, precision)} Y{_fmt(gap_start.y, precision)}",
                "tab start",
                options,
            )
        )
    lines.append(_line("M5 $0", "tab torch off", options))
    lines.append(
        _line(
            f"G0 X{_fmt(gap_end.x, precision)} Y{_fmt(gap_end.y, precision)}",
            "tab bridge skip",
            options,
        )
    )
    lines.append(_line("M3 $0 S1", "tab torch on", options))
    if gap_end.distance_to(end) > 1e-6:
        lines.append(f"G1 X{_fmt(end.x, precision)} Y{_fmt(end.y, precision)}")


def _tab_gap_for_segment(
    start: Point,
    end: Point,
    tabs: list[CutTab],
    used_tabs: set[int],
) -> tuple[int, Point, Point] | None:
    length = start.distance_to(end)
    if length <= 1e-6:
        return None
    dx = end.x - start.x
    dy = end.y - start.y
    best: tuple[float, int, float, float] | None = None
    for index, tab in enumerate(tabs):
        if index in used_tabs or tab.length <= 0:
            continue
        t = ((tab.x - start.x) * dx + (tab.y - start.y) * dy) / (length * length)
        if t <= 0.0 or t >= 1.0:
            continue
        projected = Point(start.x + dx * t, start.y + dy * t)
        distance = projected.distance_to(Point(tab.x, tab.y))
        if distance > max(tab.length, 3.0):
            continue
        half = min(tab.length / 2.0, length * 0.45)
        start_distance = max(0.0, t * length - half)
        end_distance = min(length, t * length + half)
        score = distance + abs(t - 0.5) * 0.01
        if best is None or score < best[0]:
            best = (score, index, start_distance, end_distance)
    if best is None:
        return None
    _score, index, start_distance, end_distance = best
    unit = _unit_vector(start, end)
    return (
        index,
        Point(start.x + unit.x * start_distance, start.y + unit.y * start_distance),
        Point(start.x + unit.x * end_distance, start.y + unit.y * end_distance),
    )


def _append_circle_segments(
    lines: list[str],
    contour: CircleContour,
    radius: float,
    start_angle: float,
    tabs: list[CutTab],
    options: QtPlasmaCOptions,
) -> None:
    direction = 1.0 if contour.kind in ("hole", "inner") else -1.0
    steps = max(64, math.ceil(math.tau * radius / max(options.path_tolerance * 12.0, 2.0)))
    points = [
        Point(
            contour.center.x + math.cos(start_angle + direction * math.tau * index / steps) * radius,
            contour.center.y + math.sin(start_angle + direction * math.tau * index / steps) * radius,
        )
        for index in range(steps)
    ]
    used_tabs: set[int] = set()
    previous = points[0]
    for point in points[1:]:
        _append_path_segment(lines, previous, point, tabs, used_tabs, options)
        previous = point
    _append_path_segment(lines, previous, points[0], tabs, used_tabs, options)


def _unit_vector(start: Point, end: Point) -> Point:
    dx = end.x - start.x
    dy = end.y - start.y
    length = math.hypot(dx, dy)
    if length <= 1e-9:
        raise ValueError("Cannot build lead for zero-length segment")
    return Point(dx / length, dy / length)


def _contour_lines(contour: Contour, options: QtPlasmaCOptions, skip_segments: frozenset[int] = frozenset()) -> list[str]:
    if isinstance(contour, CircleContour):
        return _circle_gcode(contour, options)
    if isinstance(contour, PathContour):
        return _path_gcode(contour, options, skip_segments)
    raise TypeError(f"Unsupported contour type: {type(contour).__name__}")


def _append_contour_with_safe_travel(
    lines: list[str],
    contour: Contour,
    current: Point,
    obstacles: list[TravelObstacle],
    options: QtPlasmaCOptions,
    skip_segments: frozenset[int] = frozenset(),
) -> Point:
    contour_lines = _contour_lines(contour, options, skip_segments)
    if not contour_lines:
        return current
    first_motion = _motion_target_from_line(contour_lines[0], current)
    if first_motion is None:
        lines.extend(contour_lines)
        return _last_motion_point(contour_lines, current)
    lines.extend(_safe_rapid_lines(current, first_motion, obstacles, options, _line_comment(contour_lines[0])))
    lines.extend(contour_lines[1:])
    return _last_motion_point(contour_lines[1:], first_motion)


def _optimized_cut_order(contours: Iterable[Contour], options: QtPlasmaCOptions) -> list[Contour]:
    raw = list(contours)
    if not raw:
        return []
    entry_cache: dict[int, Point] = {}
    exit_cache: dict[int, Point] = {}
    if not options.optimize_cut_order or len(raw) > CUT_ORDER_OPTIMIZE_MAX_CONTOURS:
        return order_contours(raw)
    groups = (_contour_groups(raw) if options.keep_part_contours_together else
              {f"{index}:{contour.name}": [contour] for index, contour in enumerate(raw)})
    prerequisites = _group_cut_prerequisites(groups)
    if not options.keep_part_contours_together:
        for key, sequence in groups.items():
            contour = sequence[0]
            if contour.kind != "outer":
                continue
            prerequisites[key].update(
                other for other, items in groups.items()
                if items[0].kind != "outer" and _contour_group_key(items[0]) == _contour_group_key(contour)
            )
    remaining = set(groups)
    current = Point(0.0, 0.0)
    ordered: list[Contour] = []
    recent_centers: list[Point] = []
    completed = list(options.travel_obstacles)
    while remaining:
        candidates = []
        eligible = [key for key in remaining if not (prerequisites.get(key, set()) & remaining)]
        for key in sorted(eligible or remaining):
            sequence = _order_group(groups[key], current, options, entry_cache, exit_cache)
            if not sequence:
                continue
            entry = _contour_entry_point_cached(sequence[0], options, entry_cache)
            distance = current.distance_to(entry)
            if options.safe_travel and options.avoid_completed_contours:
                distance = _rapid_distance(current, entry, completed, options)
            score = _group_order_score(key, sequence, recent_centers, options, distance)
            candidates.append((score, key, sequence))
        if not candidates:
            break
        candidates.sort(key=lambda item: item[0])
        selected = candidates[0]
        if options.safe_travel and options.avoid_completed_contours and len(remaining) > 1:
            for candidate in candidates:
                score, key, sequence = candidate
                if score[0] != candidates[0][0][0] or score[1]:
                    break
                after = completed + [obstacle for item in sequence if (obstacle := _contour_obstacle(item)) is not None]
                exit_point = _contour_exit_point_cached(sequence[-1], options, exit_cache)
                following = [other for other in remaining if other != key
                             and not (prerequisites.get(other, set()) & (remaining - {key}))]
                can_leave = not following
                for other in sorted(following):
                    next_sequence = _order_group(groups[other], exit_point, options, entry_cache, exit_cache)
                    if next_sequence and math.isfinite(_rapid_distance(exit_point, _contour_entry_point_cached(next_sequence[0], options, entry_cache), after, options)):
                        can_leave = True
                        break
                if can_leave:
                    selected = candidate
                    break
        _, best_key, best_sequence = selected
        ordered.extend(best_sequence)
        if options.avoid_completed_contours:
            completed.extend(obstacle for contour in best_sequence if (obstacle := _contour_obstacle(contour)) is not None)
        current = _contour_exit_point_cached(best_sequence[-1], options, exit_cache)
        recent_centers.append(_sequence_center(best_sequence))
        recent_centers = recent_centers[-options.heat_lookback:]
        remaining.remove(best_key)
    return ordered


def _group_order_score(
    key: str,
    sequence: list[Contour],
    recent_centers: list[Point],
    options: QtPlasmaCOptions,
    travel_distance: float,
) -> tuple[float, ...]:
    xmin, ymin, xmax, ymax = bbox_for_contours(sequence)
    area = (xmax - xmin) * (ymax - ymin)
    key_score = _stable_key_score(key)
    reachable = 0 if math.isfinite(travel_distance) else 1
    if options.cut_order_strategy == "lower_left":
        return (_manual_group_rank(key, sequence, options), reachable, ymin, xmin, travel_distance, area, key_score)
    if options.cut_order_strategy == "heat_spread" and recent_centers:
        center = Point((xmin + xmax) / 2.0, (ymin + ymax) / 2.0)
        nearest_recent = min(center.distance_to(item) for item in recent_centers)
        heat_score = travel_distance - options.heat_spread_weight * nearest_recent
        return (_manual_group_rank(key, sequence, options), reachable, heat_score, travel_distance, area, key_score)
    return (_manual_group_rank(key, sequence, options), reachable, travel_distance, area, key_score)


def _manual_group_rank(key: str, sequence: list[Contour], options: QtPlasmaCOptions) -> float:
    if not options.cut_order_groups:
        return 0.0
    tokens = {key}
    for contour in sequence:
        tokens.add(contour.name)
        tokens.add(_contour_group_key(contour))
        if contour.source:
            tokens.add(contour.source)
    for index, requested in enumerate(options.cut_order_groups):
        requested_key = str(requested)
        if any(_name_matches(token, requested_key) for token in tokens):
            return float(index)
    return float(len(options.cut_order_groups))


def _sequence_center(sequence: list[Contour]) -> Point:
    xmin, ymin, xmax, ymax = bbox_for_contours(sequence)
    return Point((xmin + xmax) / 2.0, (ymin + ymax) / 2.0)


def _stable_key_score(value: str) -> float:
    total = 0
    for index, char in enumerate(value):
        total += (index + 1) * ord(char)
    return float(total)


def _group_cut_prerequisites(groups: dict[str, list[Contour]]) -> dict[str, set[str]]:
    prerequisites: dict[str, set[str]] = {key: set() for key in groups}
    hole_regions = {
        key: [region for region in (_contour_region(contour) for contour in contours if contour.kind != "outer") if region is not None]
        for key, contours in groups.items()
    }
    outer_regions = {
        key: [region for region in (_contour_region(contour) for contour in contours if contour.kind == "outer") if region is not None]
        for key, contours in groups.items()
    }
    for child_key, child_regions in outer_regions.items():
        for parent_key, parent_holes in hole_regions.items():
            if child_key == parent_key:
                continue
            if _group_inside_hole(child_regions, parent_holes):
                prerequisites.setdefault(parent_key, set()).add(child_key)
    return prerequisites


def _group_inside_hole(child_regions: list[object], parent_holes: list[object]) -> bool:
    for child in child_regions:
        for hole in parent_holes:
            try:
                if hole.covers(child):
                    return True
            except Exception:
                continue
    return False


def _contour_region(contour: Contour):
    if Polygon is None:
        return None
    if isinstance(contour, PathContour) and not contour.is_closed():
        return None
    points = contour.points(max_chord=1.0)
    if len(points) < 3:
        return None
    polygon = Polygon((point.x, point.y) for point in points)
    if polygon.is_empty or polygon.area <= 1e-6:
        return None
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    if polygon.is_empty or polygon.area <= 1e-6:
        return None
    return polygon


def _nearest_order(
    contours: list[Contour],
    current: Point,
    options: QtPlasmaCOptions,
    entry_cache: dict[int, Point] | None = None,
    exit_cache: dict[int, Point] | None = None,
) -> list[Contour]:
    entry_cache = entry_cache if entry_cache is not None else {}
    exit_cache = exit_cache if exit_cache is not None else {}
    remaining = list(contours)
    ordered = []
    while remaining:
        index = min(
            range(len(remaining)),
            key=lambda item: (
                current.distance_to(_contour_entry_point_cached(remaining[item], options, entry_cache)),
                _cut_priority(remaining[item]),
                remaining[item].name,
            ),
        )
        contour = remaining.pop(index)
        ordered.append(contour)
        current = _contour_exit_point_cached(contour, options, exit_cache)
    return ordered


def _contour_groups(contours: list[Contour]) -> dict[str, list[Contour]]:
    groups: dict[str, list[Contour]] = {}
    for contour in contours:
        groups.setdefault(_contour_group_key(contour), []).append(contour)
    return groups


def _contour_group_key(contour: Contour) -> str:
    if contour.source:
        marker = f"_{contour.source}_"
        index = contour.name.find(marker)
        if index > 0:
            return contour.name[:index]
        if contour.name.startswith(f"{contour.source}_"):
            match = re.match(rf"^({re.escape(contour.source)}_\d+)_", contour.name)
            if match:
                return match.group(1)
        return contour.source
    match = re.match(r"^(.+_\d+)_", contour.name)
    if match:
        return match.group(1)
    return contour.name


def _order_group(
    contours: list[Contour],
    current: Point,
    options: QtPlasmaCOptions,
    entry_cache: dict[int, Point],
    exit_cache: dict[int, Point],
) -> list[Contour]:
    ordered: list[Contour] = []
    cursor = current
    for priority in (0, 1, 2):
        bucket = [contour for contour in contours if _cut_priority(contour) == priority]
        bucket_order = _nearest_order(bucket, cursor, options, entry_cache, exit_cache)
        if bucket_order:
            ordered.extend(bucket_order)
            cursor = _contour_exit_point_cached(bucket_order[-1], options, exit_cache)
    return ordered


def _cut_priority(contour: Contour) -> int:
    return {"hole": 0, "inner": 1, "outer": 2}[contour.kind]


def _contour_entry_point(contour: Contour, options: QtPlasmaCOptions) -> Point:
    lines = _contour_lines(contour, options)
    return _motion_target_from_line(lines[0], Point(0.0, 0.0)) if lines else Point(0.0, 0.0)


def _contour_entry_point_cached(contour: Contour, options: QtPlasmaCOptions, cache: dict[int, Point]) -> Point:
    key = id(contour)
    point = cache.get(key)
    if point is None:
        point = _contour_entry_point(contour, options)
        cache[key] = point
    return point


def _contour_exit_point(contour: Contour, options: QtPlasmaCOptions) -> Point:
    return _last_motion_point(_contour_lines(contour, options), _contour_entry_point(contour, options))


def _contour_exit_point_cached(contour: Contour, options: QtPlasmaCOptions, cache: dict[int, Point]) -> Point:
    key = id(contour)
    point = cache.get(key)
    if point is None:
        point = _contour_exit_point(contour, options)
        cache[key] = point
    return point


def _common_line_skip_map(contours: list[Contour], options: QtPlasmaCOptions) -> dict[str, frozenset[int]]:
    seen: dict[tuple[tuple[int, int], tuple[int, int]], str] = {}
    skipped: dict[str, set[int]] = {}
    for contour in contours:
        if not isinstance(contour, PathContour) or contour.kind != "outer" or not contour.is_closed():
            continue
        for index, segment in enumerate(contour.segments):
            if not isinstance(segment, LineSegment):
                continue
            key = _common_line_key(segment.start, segment.end, options.common_line_tolerance)
            if key in seen:
                skipped.setdefault(contour.name, set()).add(index)
            else:
                seen[key] = contour.name
    return {name: frozenset(indexes) for name, indexes in skipped.items()}


def _common_line_key(start: Point, end: Point, tolerance: float) -> tuple[tuple[int, int], tuple[int, int]]:
    left = (round(start.x / tolerance), round(start.y / tolerance))
    right = (round(end.x / tolerance), round(end.y / tolerance))
    return (left, right) if left <= right else (right, left)


def generate_gcode(contours: Iterable[Contour], options: QtPlasmaCOptions) -> str:
    ordered = _optimized_cut_order(contours, options)
    if not ordered:
        raise ValueError("No contours to export")
    common_line_skips = _common_line_skip_map(ordered, options) if options.common_line_cutting else {}

    units_code = "G21" if options.units == "mm" else "G20"
    lines = []
    if options.include_comments:
        lines.extend(
            [
                "(Generated by plasma_cam)",
                "(Target: LinuxCNC QtPlasmaC)",
            ]
        )
        if options.cut_settings is not None:
            settings = options.cut_settings
            _append_comment(
                lines,
                (
                    f"Cut settings: {settings.machine} {settings.material} "
                    f"t={_fmt(settings.thickness_mm, options.precision)}mm "
                    f"n={_fmt(settings.nozzle_mm, options.precision)}mm "
                    f"I={settings.current_a}A F={settings.feed_rate_mm_min}"
                ),
            )
            _append_comment(lines, f"Cut chart row: {settings.calibration_state}")
            _append_comment(lines, f"row={settings.row_id or '-'}")
            _append_comment(lines, f"revision={settings.row_revision or settings.profile_revision or '-'}")
            _append_comment(lines, f"coupon={settings.coupon_id or '-'}")
            _append_wrapped_comment(lines, "source=", settings.source or "-")
    if options.cut_settings is not None and options.emit_temporary_material:
        lines.append(
            format_qtplasmac_material_comment(
                options.cut_settings,
                material_number=options.temporary_material_number,
            )
        )
    lines.extend(
        [
            units_code,
            "G90",
            "G17",
            "G40",
            "G49",
            "G80",
            "G54",
            f"G64 P{_fmt(options.path_tolerance, options.precision)}",
            "M52 P1",
            "M68 E3 Q0",
        ]
    )
    if options.material is not None:
        lines.extend(
            [
                f"M190 P{options.material}",
                f"M66 P3 L3 Q{_fmt(options.material_wait_s, options.precision)}",
            ]
        )
    if options.use_material_feed:
        lines.append("F#<_hal[plasmac.cut-feed-rate]>")
    elif options.cut_settings is not None:
        lines.append(f"F{options.cut_settings.feed_rate_mm_min}")

    current = Point(0.0, 0.0)
    obstacles = list(options.travel_obstacles)
    for contour in ordered:
        current = _append_contour_with_safe_travel(
            lines,
            contour,
            current,
            obstacles,
            options,
            common_line_skips.get(contour.name, frozenset()),
        )
        if options.avoid_completed_contours and (obstacle := _contour_obstacle(contour)) is not None:
            obstacles.append(obstacle)

    lines.extend(["M68 E3 Q0", "M5 $-1", "M2"])
    gcode = "\n".join(lines) + "\n"
    if options.validate_before_write:
        assert_valid_gcode(gcode)
    return gcode


def write_gcode(
    contours: Iterable[Contour],
    filename: str | Path,
    options: QtPlasmaCOptions,
) -> str:
    gcode = generate_gcode(contours, options)
    Path(filename).write_text(gcode, encoding="ascii")
    return gcode
