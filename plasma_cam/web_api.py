"""Standalone plasma nesting project adapter."""

from __future__ import annotations

import math
import re
import time
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any

try:
    from shapely.geometry import LineString, Point as ShapelyPoint, Polygon, box
    from shapely.ops import unary_union
except ModuleNotFoundError:
    LineString = None
    ShapelyPoint = None
    Polygon = None
    box = None
    unary_union = None

from .autonest import NestSummary, ShelfNestOptions, shelf_nest, shelf_nest_result
from .application.gcode_simulation import build_gcode_simulation, segments_from_gcode as _segments_from_gcode
from .application.coupons import (
    build_coupon_test_project,
    cut_chart_profile_metadata,
    cut_chart_table,
    import_coupon_results,
)
from .application.project_codec import (
    allowed_rotations_from_part as _allowed_rotations_from_part,
    common_line_enabled as _common_line_enabled,
    contour_from_json as _contour_from_json,
    contour_preview as _contour_preview,
    effective_spacing_from_project as _effective_spacing_from_project,
    placements_from_project as _placements_from_project,
    point_from_json as _point_from_json,
    profile_from_part_json as _profile_from_part_json,
    requests_from_project as _requests_from_project,
    segment_from_json as _segment_from_json,
    segment_preview as _segment_preview,
    sheet_from_project as _sheet_from_project,
)
from .application.project_store import dump_project, load_project
from .application.linuxcnc_transfer import LinuxCNCGCodeFile, send_gcode_bundle_to_linuxcnc
from .cut_settings import cut_chart_rows_from_dicts, default_cut_chart_profile, select_cut_settings
from .importers.dxf import import_dxf_circles
from .model import ArcSegment, CircleContour, Contour, LineSegment, PartProfile, PathContour, Point, contour_area
from .nesting import Sheet
from .post import (
    CutTab,
    LeadOverride,
    QtPlasmaCOptions,
    TravelObstacle,
    generate_gcode,
    planned_cut_sequence,
    planned_lead_moves,
)
from .project import (
    NestedLayout,
    PartRequest,
    Placement,
    assert_valid_layout,
    build_layout,
    generate_layout_gcode,
    validate_layout,
)
from .validation import assert_valid_gcode, validate_gcode


MAX_NEST_RUN_HISTORY = 20
SAFE_TRAVEL_VALIDATION_MAX_CONTOURS = 200
SAFE_TRAVEL_VALIDATION_MAX_SEGMENTS = 12_000
CAM_GEOMETRY_VALIDATION_MAX_CONTOURS = 2_000
CAM_GEOMETRY_VALIDATION_MAX_SEGMENTS = 12_000
LEAD_VALIDATION_MAX_CONTOURS = 2_000
LEAD_VALIDATION_MAX_SEGMENTS = 12_000
HOLE_FILLER_BRIDGE_VALIDATION_MAX_PARTS = 500
HOLE_FILLER_BRIDGE_VALIDATION_MAX_CONTOURS = 2_000
LAYOUT_VALIDATION_MAX_PARTS = 3_000
LAYOUT_VALIDATION_MAX_CONTOURS = 12_000
AUTO_NEST_COMPLEXITY_FALLBACK_MAX_INSTANCES = 2_000
AUTO_NEST_COMPLEXITY_FALLBACK_MAX_CONTOURS = 5_000
AUTO_NEST_FINAL_RESERVE_S = 0.35
AUTO_NEST_AUTO_LEAD_MAX_RUNTIME_S = 0.5


@dataclass(frozen=True)
class _LeadSafetyContext:
    crater_radius: float
    clearance: float
    sheet_bounds: tuple[float, float, float, float]
    part_entries: tuple[tuple[Any, object | None, tuple[float, float, float, float]], ...]
    blocked_zones: tuple[dict[str, Any], ...]
    pierce_zones: tuple[dict[str, Any], ...]
    remnants: tuple[dict[str, Any], ...]
    remnant_area: object | None


def layout_from_project(project: dict[str, Any]) -> NestedLayout:
    sheet = _sheet_from_project(project)
    requests = tuple(_requests_from_project(project))
    spacing = _effective_spacing_from_project(project)
    if not requests:
        return NestedLayout(name=str(project.get("name", "kerfgrid_job")), sheet=sheet, placed_parts=(), spacing=spacing)
    if project.get("auto_nest", False) or not project.get("placements"):
        return shelf_nest(
            str(project.get("name", "kerfgrid_job")),
            requests,
            _nest_options_from_project(project, sheet=sheet, spacing=spacing),
        )

    placements = tuple(_placements_from_project(project, allowed_part_names={request.profile.name for request in requests}))
    if not placements:
        return shelf_nest(
            str(project.get("name", "kerfgrid_job")),
            requests,
            _nest_options_from_project(project, sheet=sheet, spacing=spacing),
        )
    return build_layout(
        name=str(project.get("name", "kerfgrid_job")),
        sheet=sheet,
        requests=requests,
        placements=placements,
        spacing=spacing,
    )


def validate_project(project: dict[str, Any]) -> list[dict[str, Any]]:
    import_issues = _import_issue_items(project)
    layout = layout_from_project(project)
    issues = _layout_issue_items(layout)
    issues.extend(_zone_issue_items(project, layout))
    issues.extend(_hole_filler_bridge_issue_items(project, layout))
    issues.extend(_common_line_issue_items(project, layout))
    issues.extend(_cam_geometry_issue_items(project, layout))
    issues.extend(_lead_issue_items(project, layout))
    issues.extend(_safe_travel_issue_items(project, layout))
    issues.extend(import_issues)
    return _warning_only_issues(issues)


def auto_nest_project(project: dict[str, Any]) -> dict[str, Any]:
    nested_project = deepcopy(project)
    started_at = time.monotonic()
    deadline = started_at + _auto_nest_runtime_limit_s(nested_project)
    sheet = _sheet_from_project(nested_project)
    requests = tuple(_requests_from_project(nested_project))
    if not requests:
        raise ValueError("Auto nest has no cuttable parts")
    spacing = _effective_spacing_from_project(nested_project)
    complexity_fallback_reason = _auto_nest_complexity_fallback_reason(nested_project, requests)
    if complexity_fallback_reason is not None and nested_project.get("placements"):
        fallback = _current_layout_complexity_fallback(
            nested_project,
            sheet,
            requests,
            spacing,
            reason=complexity_fallback_reason,
            started_at=started_at,
        )
        if fallback is not None:
            _record_nest_run(nested_project, fallback)
            return nested_project
    current_fallback = _valid_current_layout_fallback(nested_project, sheet, requests, spacing)
    nested_project["auto_nest"] = True
    if time.monotonic() >= deadline:
        raise ValueError("Auto nest exceeded time budget")
    used_current_layout_fallback = False
    try:
        nested_project, layout = _auto_nest_with_spacing(nested_project, sheet, requests, spacing, deadline=deadline)
    except ValueError as exc:
        if current_fallback is None:
            raise
        nested_project, layout = _project_from_fallback_layout(
            nested_project,
            current_fallback,
            reason=f"{type(exc).__name__}: {exc}",
            started_at=started_at,
        )
        used_current_layout_fallback = True
    fallback_spacing = _lead_fallback_spacing(nested_project, spacing)
    can_retry_leads = False
    if used_current_layout_fallback:
        lead_spacing_skip_reason = "current_layout_fallback"
    else:
        can_retry_leads = _auto_nest_has_followup_budget(deadline)
        lead_spacing_skip_reason = None if can_retry_leads else "time_budget"
    if lead_spacing_skip_reason is None:
        lead_spacing_skip_reason = _auto_lead_skip_reason(layout, deadline)
    lead_issues = _lead_issue_items(nested_project, layout) if lead_spacing_skip_reason is None else []
    if lead_issues and can_retry_leads and not _common_line_enabled(nested_project) and fallback_spacing > spacing + 1e-6:
        try:
            retry_project, retry_layout = _auto_nest_with_spacing(
                deepcopy(project) | {"auto_nest": True},
                sheet,
                requests,
                fallback_spacing,
                deadline=deadline,
            )
        except ValueError:
            retry_project = None
            retry_layout = None
        if retry_project is not None and retry_layout is not None:
            retry_issues = _lead_issue_items(retry_project, retry_layout)
            if len(retry_issues) < len(lead_issues):
                nested_project = retry_project
                layout = retry_layout
                lead_issues = retry_issues
                nested_project.setdefault("nesting", {}).setdefault("last_result", {})["lead_spacing_fallback"] = True
                nested_project["nesting"]["last_result"]["lead_spacing_mm"] = fallback_spacing
    nesting = nested_project.setdefault("nesting", {})
    last_result = nesting.setdefault("last_result", {})
    last_result.setdefault("lead_spacing_fallback", False)
    last_result.setdefault("lead_spacing_mm", spacing)
    if lead_spacing_skip_reason is not None:
        last_result["lead_spacing_fallback_skipped"] = lead_spacing_skip_reason
    issues = [
        {"code": issue.code, "message": issue.message, "instance_id": issue.instance_id}
        for issue in validate_layout(layout)
    ]
    issues.extend(_zone_issue_items(nested_project, layout))
    if issues:
        last_result["validation_warning_count"] = len(issues)
        last_result["validation_warning_codes"] = dict(Counter(str(issue.get("code", "unknown")) for issue in issues))
        last_result["validation_warning_examples"] = issues[:5]
    _record_nest_run(nested_project, layout)
    return nested_project


def _valid_current_layout_fallback(
    project: dict[str, Any],
    sheet: Sheet,
    requests: tuple[PartRequest, ...],
    spacing: float,
) -> NestedLayout | None:
    if not project.get("placements"):
        return None
    try:
        layout = build_layout(
            name=str(project.get("name", "kerfgrid_job")),
            sheet=sheet,
            requests=requests,
            placements=tuple(_placements_from_project(project, allowed_part_names={request.profile.name for request in requests})),
            spacing=spacing,
        )
    except (KeyError, TypeError, ValueError):
        return None
    if validate_layout(layout):
        return None
    return layout


def _project_from_fallback_layout(
    project: dict[str, Any],
    layout: NestedLayout,
    *,
    reason: str,
    started_at: float,
) -> tuple[dict[str, Any], NestedLayout]:
    project["placements"] = _placement_dicts_from_layout(layout, manual=False)
    project["auto_nest"] = False
    project.setdefault("nesting", {})["last_result"] = _current_layout_fallback_summary(layout, reason, started_at)
    return project, layout


def _placement_dicts_from_layout(layout: NestedLayout, *, manual: bool) -> list[dict[str, Any]]:
    return [
        {
            "part_name": part.placement.part_name,
            "instance": part.placement.instance,
            "dx": part.placement.dx,
            "dy": part.placement.dy,
            "rotation_deg": part.placement.rotation_deg,
            "locked": part.placement.locked,
            "manual": manual,
        }
        for part in layout.placed_parts
    ]


def _current_layout_fallback_summary(layout: NestedLayout, reason: str, started_at: float) -> dict[str, Any]:
    boxes = [part.bbox() for part in layout.placed_parts]
    part_area = sum(_fast_placed_part_area(part) for part in layout.placed_parts)
    if boxes:
        xmin = min(box[0] for box in boxes)
        ymin = min(box[1] for box in boxes)
        xmax = max(box[2] for box in boxes)
        ymax = max(box[3] for box in boxes)
        used_bbox_area = max(0.0, xmax - xmin) * max(0.0, ymax - ymin)
        used_width = max(0.0, xmax - layout.sheet.margin)
        used_height = max(0.0, ymax - layout.sheet.margin)
        used_strip_area = used_width * used_height
        top_free_height = max(0.0, layout.sheet.height - layout.sheet.margin - ymax)
    else:
        used_bbox_area = 0.0
        used_width = 0.0
        used_height = 0.0
        used_strip_area = 0.0
        top_free_height = max(0.0, layout.sheet.height - layout.sheet.margin * 2.0)
    usable_area = max(0.0, layout.sheet.width - layout.sheet.margin * 2.0) * max(
        0.0, layout.sheet.height - layout.sheet.margin * 2.0
    )
    return {
        "attempt_count": 0,
        "successful_attempt_count": 1,
        "best_attempt": "current_layout_fallback",
        "geometry_engine": "current-layout",
        "runtime_ms": round((time.monotonic() - started_at) * 1000.0, 3),
        "parallel_worker_count": 1,
        "attempts_per_second": 0.0,
        "candidate_position_count": 0,
        "nfp_candidate_count": 0,
        "exact_clearance_check_count": 0,
        "spatial_index_query_count": 0,
        "spatial_index_fallback_count": 0,
        "cache_hit_count": 0,
        "cache_miss_count": 0,
        "used_width_mm": round(used_width, 3),
        "used_height_mm": round(used_height, 3),
        "used_bbox_area_mm2": round(used_bbox_area, 3),
        "used_strip_area_mm2": round(used_strip_area, 3),
        "top_free_height_mm": round(top_free_height, 3),
        "packing_utilization_percent": _percent(part_area, used_strip_area),
        "bbox_utilization_percent": _percent(part_area, used_bbox_area),
        "sheet_utilization_percent": _percent(part_area, usable_area),
        "hole_filler_relocation_count": 0,
        "time_limited": True,
        "parallel_fallback_reason": reason,
        "current_layout_fallback": True,
        "auto_lead_override_count": 0,
        "auto_lead_override_skipped": "current_layout_fallback",
    }


def _fast_placed_part_area(part) -> float:
    outer = 0.0
    holes = 0.0
    for contour in part.profile.contours:
        area = abs(contour_area(contour))
        if contour.kind == "outer":
            outer += area
        else:
            holes += area
    return max(0.0, outer - holes)


def _auto_nest_with_spacing(
    nested_project: dict[str, Any],
    sheet: Sheet,
    requests: tuple[PartRequest, ...],
    spacing: float,
    *,
    deadline: float | None = None,
) -> tuple[dict[str, Any], NestedLayout]:
    options = _nest_options_from_project(nested_project, sheet=sheet, spacing=spacing)
    if deadline is not None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("Auto nest exceeded time budget")
        search_budget = _auto_nest_search_budget_s(remaining)
        options = replace(options, max_runtime_s=max(0.001, min(options.max_runtime_s, search_budget)))
    result = shelf_nest_result(
        str(nested_project.get("name", "kerfgrid_job")),
        requests,
        options,
    )
    layout = result.layout
    nested_project["placements"] = [
        {
            "part_name": part.placement.part_name,
            "instance": part.placement.instance,
            "dx": part.placement.dx,
            "dy": part.placement.dy,
            "rotation_deg": part.placement.rotation_deg,
            "locked": part.placement.locked,
            "manual": False,
        }
        for part in layout.placed_parts
    ]
    nested_project["auto_nest"] = False
    nesting = nested_project.setdefault("nesting", {})
    nesting["last_result"] = _nest_summary_dict(result.summary)
    auto_lead_deadline = _auto_nest_followup_deadline(deadline)
    auto_lead_skip_reason = _auto_lead_skip_reason(layout, auto_lead_deadline)
    if auto_lead_skip_reason is None:
        nested_project, auto_lead_count = _apply_auto_lead_overrides(nested_project, layout, deadline=auto_lead_deadline)
    else:
        auto_lead_count = 0
    nesting = nested_project.setdefault("nesting", {})
    nesting["last_result"]["auto_lead_override_count"] = auto_lead_count
    if auto_lead_skip_reason is not None:
        nesting["last_result"]["auto_lead_override_skipped"] = auto_lead_skip_reason
    return nested_project, layout


def _auto_nest_complexity_fallback_reason(
    project: dict[str, Any],
    requests: tuple[PartRequest, ...],
) -> str | None:
    instance_count = sum(request.quantity for request in requests)
    contour_count = sum(len(request.profile.contours) * request.quantity for request in requests)
    nesting = project.get("nesting", {}) or {}
    if bool(nesting.get("force_complex_auto_nest", False)):
        return None
    if instance_count > AUTO_NEST_COMPLEXITY_FALLBACK_MAX_INSTANCES:
        return (
            f"current layout preserved because {instance_count} part instances exceed "
            f"auto-nest complexity limit {AUTO_NEST_COMPLEXITY_FALLBACK_MAX_INSTANCES}"
        )
    if contour_count > AUTO_NEST_COMPLEXITY_FALLBACK_MAX_CONTOURS:
        return (
            f"current layout preserved because {contour_count} contours exceed "
            f"auto-nest complexity limit {AUTO_NEST_COMPLEXITY_FALLBACK_MAX_CONTOURS}"
        )
    return None


def _current_layout_complexity_fallback(
    project: dict[str, Any],
    sheet: Sheet,
    requests: tuple[PartRequest, ...],
    spacing: float,
    *,
    reason: str,
    started_at: float,
) -> NestedLayout | None:
    try:
        layout = build_layout(
            name=str(project.get("name", "kerfgrid_job")),
            sheet=sheet,
            requests=requests,
            placements=tuple(
                _placements_from_project(project, allowed_part_names={request.profile.name for request in requests})
            ),
            spacing=spacing,
        )
    except (KeyError, TypeError, ValueError):
        return None
    project["placements"] = _placement_dicts_from_layout(layout, manual=False)
    project["auto_nest"] = False
    nesting = project.setdefault("nesting", {})
    nesting["last_result"] = _current_layout_complexity_summary(
        layout,
        requests,
        reason=reason,
        started_at=started_at,
    )
    return layout


def _current_layout_complexity_summary(
    layout: NestedLayout,
    requests: tuple[PartRequest, ...],
    *,
    reason: str,
    started_at: float,
) -> dict[str, Any]:
    usable_width = max(0.0, layout.sheet.width - layout.sheet.margin * 2.0)
    usable_height = max(0.0, layout.sheet.height - layout.sheet.margin * 2.0)
    usable_area = usable_width * usable_height
    part_area = sum(_fast_profile_area(request.profile) * request.quantity for request in requests)
    instance_count = sum(request.quantity for request in requests)
    contour_count = sum(len(request.profile.contours) * request.quantity for request in requests)
    return {
        "attempt_count": 0,
        "successful_attempt_count": 1,
        "best_attempt": "current_layout_complexity_fallback",
        "geometry_engine": "current-layout",
        "runtime_ms": round((time.monotonic() - started_at) * 1000.0, 3),
        "parallel_worker_count": 1,
        "attempts_per_second": 0.0,
        "candidate_position_count": 0,
        "nfp_candidate_count": 0,
        "exact_clearance_check_count": 0,
        "spatial_index_query_count": 0,
        "spatial_index_fallback_count": 0,
        "cache_hit_count": 0,
        "cache_miss_count": 0,
        "used_width_mm": round(usable_width, 3),
        "used_height_mm": round(usable_height, 3),
        "used_bbox_area_mm2": round(usable_area, 3),
        "used_strip_area_mm2": round(usable_area, 3),
        "top_free_height_mm": 0.0,
        "packing_utilization_percent": _percent(part_area, usable_area),
        "bbox_utilization_percent": _percent(part_area, usable_area),
        "sheet_utilization_percent": _percent(part_area, usable_area),
        "hole_filler_relocation_count": 0,
        "time_limited": True,
        "parallel_fallback_reason": reason,
        "current_layout_fallback": True,
        "complexity_fallback": True,
        "complexity_fallback_reason": reason,
        "complexity_instance_count": instance_count,
        "complexity_contour_count": contour_count,
        "auto_lead_override_count": 0,
        "auto_lead_override_skipped": "complexity_fallback",
        "lead_spacing_fallback": False,
        "lead_spacing_mm": layout.spacing,
        "lead_spacing_fallback_skipped": "complexity_fallback",
    }


def _fast_profile_area(profile: PartProfile) -> float:
    outer = 0.0
    holes = 0.0
    for contour in profile.contours:
        area = abs(contour_area(contour))
        if contour.kind == "outer":
            outer += area
        else:
            holes += area
    return max(0.0, outer - holes)


def _layout_issue_items(layout: NestedLayout) -> list[dict[str, Any]]:
    part_count = len(layout.placed_parts)
    contour_count = sum(len(part.profile.contours) for part in layout.placed_parts)
    if part_count > LAYOUT_VALIDATION_MAX_PARTS or contour_count > LAYOUT_VALIDATION_MAX_CONTOURS:
        return [
            {
                "code": "layout_complexity",
                "message": (
                    f"Layout collision precheck skipped for complex layout with {part_count} parts and "
                    f"{contour_count} contours; export remains allowed and operator review is required"
                ),
                "instance_id": None,
                "blocking": False,
            }
        ]
    return [
        {"code": issue.code, "message": issue.message, "instance_id": issue.instance_id}
        for issue in validate_layout(layout)
    ]


def _lead_fallback_spacing(project: dict[str, Any], current_spacing: float) -> float:
    if _common_line_enabled(project):
        return current_spacing
    post = project.get("post", {})
    lead = 0.0 if str(post.get("lead_in_mode", "auto")) == "none" else float(post.get("lead_in_mm", 5.0))
    lead_out = float(post.get("lead_out_mm", 0.0))
    crater_radius = max(0.0, float(post.get("pierce_crater_diameter_mm", 4.0)) / 2.0)
    clearance = max(0.0, float(post.get("lead_clearance_mm", 1.0)))
    padding = max(lead, lead_out, crater_radius) + crater_radius + clearance
    return max(current_spacing, float(project.get("spacing_mm", current_spacing)) + padding)


def _auto_nest_runtime_limit_s(project: dict[str, Any]) -> float:
    nesting = project.get("nesting", {}) or {}
    value = float(nesting.get("auto_nest_max_runtime_s", nesting.get("max_runtime_s", 12.0)))
    return max(1.0, min(120.0, value))


def _auto_nest_search_budget_s(remaining_s: float) -> float:
    if remaining_s <= 0:
        return 0.0
    if remaining_s <= 0.25:
        return max(0.001, remaining_s)
    reserve = min(1.5, max(0.25, remaining_s * 0.25))
    return max(0.001, remaining_s - reserve)


def _auto_nest_followup_deadline(
    deadline: float | None,
    *,
    max_budget_s: float = AUTO_NEST_AUTO_LEAD_MAX_RUNTIME_S,
    final_reserve_s: float = AUTO_NEST_FINAL_RESERVE_S,
) -> float | None:
    if deadline is None:
        return None
    now = time.monotonic()
    available = deadline - now - final_reserve_s
    if available <= 0:
        return now
    return now + min(max_budget_s, available)


def _auto_nest_has_followup_budget(deadline: float | None, *, reserve_s: float = AUTO_NEST_FINAL_RESERVE_S) -> bool:
    if deadline is None:
        return True
    return deadline - time.monotonic() > reserve_s


def export_project_gcode(project: dict[str, Any], validation_issues: list[dict[str, Any]] | None = None) -> str:
    layout = layout_from_project(project)
    if not layout.placed_parts:
        raise ValueError("Project has no cuttable placed parts to export")
    settings = _cut_settings_from_project(project)
    options = _post_options_from_project(project, layout, settings=settings)
    warnings = [issue for issue in (validation_issues if validation_issues is not None else validate_project(project)) if issue.get("message")]
    while True:
        try:
            gcode = _generate_layout_gcode_warning_only(layout, options)
            break
        except ValueError as exc:
            if _is_centerline_fallback_error(exc) and options.kerf_offset_fallback != "centerline":
                options = replace(options, kerf_offset_fallback="centerline")
                warnings.append(
                    {
                        "code": "kerf_offset_centerline",
                        "message": f"{exc}; auto centerline fallback used because validation issues are warning-only.",
                        "blocking": False,
                        "review_required": True,
                    }
                )
                continue
            if _is_open_path_fallback_error(exc) and options.open_path_mode != "centerline":
                options = replace(options, open_path_mode="centerline")
                warnings.append(
                    {
                        "code": "open_path_centerline",
                        "message": f"{exc}; auto centerline open-path export used because validation issues are warning-only.",
                        "blocking": False,
                        "review_required": True,
                    }
                )
                continue
            raise
    if warnings:
        warnings = sorted(warnings, key=_gcode_warning_priority)
        warning_lines = [
            f"(WARNING: {issue.get('code', 'issue')}: {_gcode_comment_text(issue['message'] or '')})" for issue in warnings[:50]
        ]
        if len(warnings) > 50:
            warning_lines.append(f"(WARNING: {len(warnings) - 50} additional validation issue(s) omitted from G-code header)")
        gcode = "\n".join(warning_lines) + "\n" + gcode
    return gcode


def send_project_to_linuxcnc(project: dict[str, Any]) -> dict[str, Any]:
    gcode = export_project_gcode(project)
    filename = "kerfgrid_job_live.ngc"
    outline_filename = "kerfgrid_outline_live.ngc"
    warnings: list[str] = []
    try:
        outline_gcode = export_project_outline_gcode(project)
    except ValueError as exc:
        outline_gcode = _outline_unavailable_gcode(str(exc))
        warnings.append(f"Outline file contains no motion: {exc}")
    result = send_gcode_bundle_to_linuxcnc(
        files=(
            LinuxCNCGCodeFile(filename=filename, gcode=gcode),
            LinuxCNCGCodeFile(filename=outline_filename, gcode=outline_gcode),
        ),
        load_filename=filename,
    )
    transfer_warnings = list(result.get("warnings", []))
    return {
        "filename": filename,
        "outline_filename": outline_filename,
        "line_count": len(gcode.splitlines()),
        "outline_line_count": len(outline_gcode.splitlines()),
        **result,
        "warnings": [*warnings, *transfer_warnings],
    }


def _outline_unavailable_gcode(message: str) -> str:
    lines = [
        "(Generated by plasma_cam)",
        f"(WARNING: outline unavailable: {_gcode_comment_text(message)})",
        "(Torch is never started in this file)",
        "G21",
        "G90",
        "G17",
        "G40",
        "G49",
        "G80",
        "M5 $-1",
        "M2",
    ]
    gcode = "\n".join(lines) + "\n"
    assert_valid_gcode(gcode)
    return gcode


def _generate_layout_gcode_warning_only(layout: NestedLayout, options: QtPlasmaCOptions) -> str:
    return generate_gcode(layout.contours(), options)


def _gcode_warning_priority(issue: dict[str, Any]) -> tuple[int, str]:
    code = str(issue.get("code", ""))
    if code.startswith("import_"):
        return (0, code)
    if code in ("open_path_centerline", "kerf_offset_centerline"):
        return (1, code)
    return (2, code)


def export_project_outline_gcode(project: dict[str, Any]) -> str:
    layout = layout_from_project(project)
    post = project.get("post", {})
    precision = int(post.get("precision", 3))
    feed_rate = float(post.get("outline_feed_rate_mm_min", 3000))
    path_tolerance = float(post.get("path_tolerance_mm", 0.1))
    if feed_rate <= 0:
        raise ValueError("Outline feed rate must be positive")
    outer_contours = [contour for contour in layout.contours() if contour.kind == "outer"]
    if not outer_contours:
        raise ValueError("Project has no outer contours to outline")
    lines = [
        "(Generated by plasma_cam)",
        "(Target: LinuxCNC QtPlasmaC dry outline)",
        "(Torch is never started in this file)",
        "G21",
        "G90",
        "G17",
        "G40",
        "G49",
        "G80",
        "G54",
        f"G64 P{_gcode_number(path_tolerance, precision)}",
        "M52 P1",
        "M68 E3 Q0",
        "M5 $-1",
        f"#<kerfgrid_outline_feed> = {_gcode_number(feed_rate, precision)}",
        "F#<kerfgrid_outline_feed>",
    ]
    for contour in outer_contours:
        lines.extend(_outline_contour_lines(contour, precision=precision))
    lines.extend(["M68 E3 Q0", "M5 $-1", "M2"])
    gcode = "\n".join(lines) + "\n"
    assert_valid_gcode(gcode)
    return gcode


def export_project_review_dxf(project: dict[str, Any]) -> str:
    layout = layout_from_project(project)
    precision = int(project.get("post", {}).get("precision", 3))
    lines: list[str] = [
        "0",
        "SECTION",
        "2",
        "HEADER",
        "9",
        "$ACADVER",
        "1",
        "AC1009",
        "0",
        "ENDSEC",
        *_dxf_layer_table(("SHEET", "MARGIN", "OUTER", "HOLE", "ZONES", "LEAD", "TABS", "ANNOTATION")),
        "0",
        "SECTION",
        "2",
        "ENTITIES",
    ]
    _dxf_rectangle(lines, "SHEET", 0.0, 0.0, layout.sheet.width, layout.sheet.height, precision)
    margin = layout.sheet.margin
    if margin > 0 and layout.sheet.width > margin * 2 and layout.sheet.height > margin * 2:
        _dxf_rectangle(
            lines,
            "MARGIN",
            margin,
            margin,
            layout.sheet.width - margin,
            layout.sheet.height - margin,
            precision,
        )
    _dxf_text(
        lines,
        "ANNOTATION",
        margin,
        max(margin, layout.sheet.height - margin - 10),
        f"Review DXF: {layout.name}",
        6.0,
        precision,
    )
    for zone in _enabled_zones(project):
        _dxf_rectangle(
            lines,
            "ZONES",
            zone["x_mm"],
            zone["y_mm"],
            zone["x_mm"] + zone["width_mm"],
            zone["y_mm"] + zone["height_mm"],
            precision,
        )
        _dxf_text(
            lines,
            "ZONES",
            zone["x_mm"],
            zone["y_mm"] + zone["height_mm"] + 2.0,
            str(zone.get("name", zone["type"])),
            4.0,
            precision,
        )
    for part in layout.placed_parts:
        for contour in part.contours():
            _dxf_contour(lines, contour, precision)
        xmin, ymin, xmax, ymax = part.bbox()
        _dxf_text(lines, "ANNOTATION", xmin, ymax + 2.0, part.instance_id, 4.0, precision)
    for lead in project.get("lead_overrides", []) or []:
        _dxf_lead(lines, lead, precision)
    for tab in _tabs_from_project(project):
        half = max(0.5, tab.length / 2.0)
        _dxf_line(lines, "TABS", Point(tab.x - half, tab.y), Point(tab.x + half, tab.y), precision)
        _dxf_circle(lines, "TABS", Point(tab.x, tab.y), max(0.75, min(half, 2.0)), precision)
    lines.extend(["0", "ENDSEC", "0", "EOF"])
    return "\n".join(lines) + "\n"


def project_review_report(project: dict[str, Any]) -> dict[str, Any]:
    layout = layout_from_project(project)
    issues = validate_project(project)
    warnings = [
        {"code": issue.get("code"), "message": issue.get("message"), "instance_id": issue.get("instance_id")}
        for issue in issues
        if issue.get("blocking", True) is False
    ]
    settings: dict[str, Any] | None
    try:
        settings = cut_settings_preview(project)
    except Exception as exc:
        settings = None
        warnings.append({"code": "cut_settings_unavailable", "message": str(exc), "type": type(exc).__name__})
    try:
        simulation = simulation_from_project(project)
        simulation_metrics = _review_simulation_metrics(simulation)
    except Exception as exc:
        simulation_metrics = _empty_review_simulation_metrics()
        warnings.append({"code": "simulation_unavailable", "message": str(exc), "type": type(exc).__name__})
    import_summary = _review_import_summary(project)
    current_utilization = _review_layout_utilization(layout)
    cut_settings = _review_cut_settings_metadata(settings)
    cut_order = _review_cut_order(project, layout)
    cam_geometry = _review_cam_geometry(issues)
    dxf_repair_plan = _review_dxf_repair_plan(project, issues)
    export_preflight = _review_export_preflight(project, issues)
    issue_summary = _review_issue_summary(issues)
    return {
        "name": str(project.get("name", layout.name)),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "sheet": {
            "width_mm": layout.sheet.width,
            "height_mm": layout.sheet.height,
            "margin_mm": layout.sheet.margin,
            "spacing_mm": layout.spacing,
        },
        "parts": _review_part_counts(project, layout),
        "import_summary": import_summary,
        "nesting": {
            "current_utilization": current_utilization,
            "last_result": (project.get("nesting", {}) or {}).get("last_result", {}),
            "run_history": list((project.get("nesting", {}) or {}).get("run_history", []) or [])[-MAX_NEST_RUN_HISTORY:],
        },
        "cut_settings": cut_settings,
        "cut_order": cut_order,
        "cam_geometry": cam_geometry,
        "dxf_repair_plan": dxf_repair_plan,
        "export_preflight": export_preflight,
        "issue_summary": issue_summary,
        "validation_issues": issues,
        "simulation_metrics": simulation_metrics,
        "operator_checklist": _review_operator_checklist(
            layout=layout,
            settings=settings,
            warnings=warnings,
            issue_summary=issue_summary,
            export_preflight=export_preflight,
            simulation_metrics=simulation_metrics,
            cut_order=cut_order,
            current_utilization=current_utilization,
        ),
        "warnings": warnings,
    }


def cut_settings_preview(project: dict[str, Any]) -> dict[str, Any]:
    settings = _cut_settings_from_project(project)
    cut = project.get("cut", {})
    return {
        **settings.to_dict(),
        "feed_rate_mode": str(cut.get("feed_rate_mode", "auto")),
    }


def generate_coupon_test_project(config: dict[str, Any]) -> dict[str, Any]:
    project = build_coupon_test_project(config)
    issues = validate_project(project)
    blocking = [issue for issue in issues if issue.get("blocking", True) is not False]
    if blocking:
        message = "; ".join(str(issue.get("message") or issue.get("code")) for issue in blocking[:3])
        raise ValueError(f"Generated coupon project is invalid: {message}")
    return project


def simulation_from_project(project: dict[str, Any]) -> dict[str, Any]:
    gcode = export_project_gcode(project)
    return simulation_from_gcode(project, gcode)


def simulation_from_gcode(project: dict[str, Any], gcode: str) -> dict[str, Any]:
    settings = _cut_settings_from_project(project)
    return build_gcode_simulation(
        project,
        gcode,
        cut_feed_rate_mm_min=float(settings.feed_rate_mm_min),
        pierce_delay_s=float(settings.pierce_delay_s),
    )


def import_dxf_project(payload: dict[str, Any]) -> dict[str, Any]:
    base = payload.get("base_project") or {}
    import_options = base.get("import_options") or {}
    payload_options = payload.get("import_options") or {}
    merged_import_options = {
        **(import_options if isinstance(import_options, dict) else {}),
        **(payload_options if isinstance(payload_options, dict) else {}),
    }
    auto_close_gaps = bool(merged_import_options.get("auto_close_gaps", False))
    return _import_dxf_project_with_options(
        payload,
        base,
        merged_import_options,
        auto_close_gaps=auto_close_gaps,
    )


def _import_dxf_project_with_options(
    payload: dict[str, Any],
    base: dict[str, Any],
    import_options: dict[str, Any],
    *,
    auto_close_gaps: bool,
) -> dict[str, Any]:
    return import_dxf_circles(
        str(payload.get("content", "")),
        name=str(payload.get("filename", "imported_part")),
        sheet=base.get("sheet"),
        cut=base.get("cut"),
        post=base.get("post"),
        spacing_mm=float(base.get("spacing_mm", 5.0)),
        auto_close_gaps=auto_close_gaps,
        import_options=import_options,
        layer_mapping=payload.get("layer_mapping"),
    )


def preview_from_project(project: dict[str, Any]) -> dict[str, Any]:
    layout = layout_from_project(project)
    return {
        "name": layout.name,
        "sheet": {
            "width": layout.sheet.width,
            "height": layout.sheet.height,
            "margin": layout.sheet.margin,
        },
        "spacing_mm": layout.spacing,
        "issues": validate_project(project),
        "import": project.get("import", {}),
        "nesting": project.get("nesting", {}),
        "zones": project.get("zones", []),
        "tabs": project.get("tabs", []),
        "lead_overrides": project.get("lead_overrides", []),
        "parts": [
            {
                "instance_id": part.instance_id,
                "part_name": part.profile.name,
                "placement": {
                    "dx": part.placement.dx,
                    "dy": part.placement.dy,
                    "rotation_deg": part.placement.rotation_deg,
                    "locked": part.placement.locked,
                    "manual": part.placement.manual,
                },
                "bbox": part.bbox(),
                "contours": [
                    _contour_preview(contour)
                    for contour in part.contours()
                ],
            }
            for part in layout.placed_parts
        ],
    }


def _common_line_issue_items(project: dict[str, Any], layout: NestedLayout) -> list[dict[str, str | None]]:
    if not _common_line_enabled(project):
        return []
    try:
        settings = _cut_settings_from_project(project)
    except ValueError as exc:
        return [{"code": "cut_settings", "message": str(exc), "instance_id": None}]
    kerf = float(settings.kerf_width_mm)
    if kerf <= 1e-9:
        return []
    tolerance = float(project.get("post", {}).get("common_line_tolerance_mm", 0.05))
    shared_segments = _shared_outer_line_segment_count(layout, tolerance=max(tolerance, 1e-9))
    if not shared_segments:
        return []
    centerline_fallback = str(project.get("post", {}).get("kerf_offset_fallback", "block")) == "centerline"
    if centerline_fallback:
        return [
            {
                "code": "common_line_centerline",
                "message": (
                    f"Common-line cutting found {shared_segments} shared straight edge(s); "
                    "centerline fallback will cut without geometry kerf compensation."
                ),
                "instance_id": None,
                "blocking": False,
            }
        ]
    return [
        {
            "code": "common_line_kerf_offset",
            "message": (
                f"Common-line cutting found {shared_segments} shared straight edge(s), "
                f"but geometry kerf offset is active ({kerf:g} mm). Disable common-line "
                "or use externally compensated/zero-kerf export before cutting."
            ),
            "instance_id": None,
        }
    ]


def _shared_outer_line_segment_count(layout: NestedLayout, *, tolerance: float) -> int:
    seen: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    repeated = 0
    for contour in layout.contours():
        if not isinstance(contour, PathContour) or contour.kind != "outer":
            continue
        for segment in contour.segments:
            if not isinstance(segment, LineSegment):
                continue
            key = _common_line_segment_key(segment.start, segment.end, tolerance)
            if key in seen:
                repeated += 1
            else:
                seen.add(key)
    return repeated


def _common_line_segment_key(start: Point, end: Point, tolerance: float) -> tuple[tuple[int, int], tuple[int, int]]:
    left = (round(start.x / tolerance), round(start.y / tolerance))
    right = (round(end.x / tolerance), round(end.y / tolerance))
    return (left, right) if left <= right else (right, left)


def _outline_contour_lines(contour: Contour, *, precision: int) -> list[str]:
    if isinstance(contour, CircleContour):
        return _outline_circle_lines(contour, precision=precision)
    if isinstance(contour, PathContour):
        return _outline_path_lines(contour, precision=precision)
    raise TypeError(f"Unsupported contour type: {type(contour).__name__}")


def _outline_circle_lines(contour: CircleContour, *, precision: int) -> list[str]:
    start = Point(contour.center.x + contour.radius, contour.center.y)
    mid = Point(contour.center.x - contour.radius, contour.center.y)
    return [
        f"G0 X{_gcode_number(start.x, precision)} Y{_gcode_number(start.y, precision)} ({contour.name} outer dry outline)",
        (
            f"G2 X{_gcode_number(mid.x, precision)} Y{_gcode_number(mid.y, precision)} "
            f"I{_gcode_number(contour.center.x - start.x, precision)} J{_gcode_number(contour.center.y - start.y, precision)}"
        ),
        (
            f"G2 X{_gcode_number(start.x, precision)} Y{_gcode_number(start.y, precision)} "
            f"I{_gcode_number(contour.center.x - mid.x, precision)} J{_gcode_number(contour.center.y - mid.y, precision)}"
        ),
    ]


def _outline_path_lines(contour: PathContour, *, precision: int) -> list[str]:
    if not contour.is_closed():
        raise ValueError(f"{contour.name} is not closed")
    start = contour.segments[0].start
    lines = [
        f"G0 X{_gcode_number(start.x, precision)} Y{_gcode_number(start.y, precision)} ({contour.name} outer dry outline)"
    ]
    for segment in contour.segments:
        if isinstance(segment, LineSegment):
            lines.append(f"G1 X{_gcode_number(segment.end.x, precision)} Y{_gcode_number(segment.end.y, precision)}")
        elif isinstance(segment, ArcSegment):
            command = "G2" if segment.clockwise else "G3"
            lines.append(
                (
                    f"{command} X{_gcode_number(segment.end.x, precision)} Y{_gcode_number(segment.end.y, precision)} "
                    f"I{_gcode_number(segment.center.x - segment.start.x, precision)} "
                    f"J{_gcode_number(segment.center.y - segment.start.y, precision)}"
                )
            )
        else:
            raise TypeError(f"Unsupported path segment type: {type(segment).__name__}")
    if not contour.segments[-1].end.almost_equals(start, tolerance=0.001):
        lines.append(f"G1 X{_gcode_number(start.x, precision)} Y{_gcode_number(start.y, precision)}")
    return lines


def _gcode_number(value: float, precision: int) -> str:
    text = f"{value:.{precision}f}".rstrip("0").rstrip(".")
    if text == "-0":
        return "0"
    return text or "0"


def _dxf_layer_table(layers: tuple[str, ...]) -> list[str]:
    color_by_layer = {
        "SHEET": 7,
        "MARGIN": 1,
        "OUTER": 3,
        "HOLE": 6,
        "ZONES": 5,
        "LEAD": 4,
        "TABS": 2,
        "ANNOTATION": 8,
    }
    lines = [
        "0",
        "SECTION",
        "2",
        "TABLES",
        "0",
        "TABLE",
        "2",
        "LAYER",
        "70",
        str(len(layers)),
    ]
    for layer in layers:
        lines.extend(
            [
                "0",
                "LAYER",
                "2",
                layer,
                "70",
                "0",
                "62",
                str(color_by_layer.get(layer, 7)),
                "6",
                "CONTINUOUS",
            ]
        )
    lines.extend(["0", "ENDTAB", "0", "ENDSEC"])
    return lines


def _dxf_contour(lines: list[str], contour: Contour, precision: int) -> None:
    layer = "OUTER" if contour.kind == "outer" else "HOLE"
    if isinstance(contour, CircleContour):
        _dxf_circle(lines, layer, contour.center, contour.radius, precision)
        return
    if isinstance(contour, PathContour):
        for segment in contour.segments:
            if isinstance(segment, LineSegment):
                _dxf_line(lines, layer, segment.start, segment.end, precision)
            elif isinstance(segment, ArcSegment):
                _dxf_arc(lines, layer, segment, precision)
            else:
                raise TypeError(f"Unsupported path segment type: {type(segment).__name__}")
        return
    raise TypeError(f"Unsupported contour type: {type(contour).__name__}")


def _dxf_rectangle(
    lines: list[str],
    layer: str,
    xmin: float,
    ymin: float,
    xmax: float,
    ymax: float,
    precision: int,
) -> None:
    points = (
        Point(xmin, ymin),
        Point(xmax, ymin),
        Point(xmax, ymax),
        Point(xmin, ymax),
    )
    for start, end in zip(points, [*points[1:], points[0]]):
        _dxf_line(lines, layer, start, end, precision)


def _dxf_line(lines: list[str], layer: str, start: Point, end: Point, precision: int) -> None:
    lines.extend(
        [
            "0",
            "LINE",
            "8",
            layer,
            "10",
            _dxf_number(start.x, precision),
            "20",
            _dxf_number(start.y, precision),
            "30",
            "0",
            "11",
            _dxf_number(end.x, precision),
            "21",
            _dxf_number(end.y, precision),
            "31",
            "0",
        ]
    )


def _dxf_circle(lines: list[str], layer: str, center: Point, radius: float, precision: int) -> None:
    if radius <= 0:
        return
    lines.extend(
        [
            "0",
            "CIRCLE",
            "8",
            layer,
            "10",
            _dxf_number(center.x, precision),
            "20",
            _dxf_number(center.y, precision),
            "30",
            "0",
            "40",
            _dxf_number(radius, precision),
        ]
    )


def _dxf_arc(lines: list[str], layer: str, segment: ArcSegment, precision: int) -> None:
    radius = segment.radius
    if radius <= 0:
        _dxf_line(lines, layer, segment.start, segment.end, precision)
        return
    start_angle = _dxf_angle(segment.center, segment.start)
    end_angle = _dxf_angle(segment.center, segment.end)
    if segment.clockwise:
        start_angle, end_angle = end_angle, start_angle
    lines.extend(
        [
            "0",
            "ARC",
            "8",
            layer,
            "10",
            _dxf_number(segment.center.x, precision),
            "20",
            _dxf_number(segment.center.y, precision),
            "30",
            "0",
            "40",
            _dxf_number(radius, precision),
            "50",
            _dxf_number(start_angle, precision),
            "51",
            _dxf_number(end_angle, precision),
        ]
    )


def _dxf_text(
    lines: list[str],
    layer: str,
    x: float,
    y: float,
    text: str,
    height: float,
    precision: int,
) -> None:
    value = _dxf_text_value(text)
    if not value:
        return
    lines.extend(
        [
            "0",
            "TEXT",
            "8",
            layer,
            "10",
            _dxf_number(x, precision),
            "20",
            _dxf_number(y, precision),
            "30",
            "0",
            "40",
            _dxf_number(height, precision),
            "1",
            value,
        ]
    )


def _dxf_lead(lines: list[str], lead: dict[str, Any], precision: int) -> None:
    start_x = _maybe_float(lead.get("start_x_mm", lead.get("start_x")))
    start_y = _maybe_float(lead.get("start_y_mm", lead.get("start_y")))
    if start_x is None or start_y is None:
        return
    start = Point(start_x, start_y)
    pierce_x = _maybe_float(lead.get("pierce_x_mm", lead.get("pierce_x")))
    pierce_y = _maybe_float(lead.get("pierce_y_mm", lead.get("pierce_y")))
    if pierce_x is not None and pierce_y is not None:
        _dxf_line(lines, "LEAD", Point(pierce_x, pierce_y), start, precision)
        _dxf_circle(lines, "LEAD", Point(pierce_x, pierce_y), 1.5, precision)
    _dxf_circle(lines, "LEAD", start, 1.25, precision)
    _dxf_text(lines, "LEAD", start.x + 2.0, start.y + 2.0, str(lead.get("contour_name", "lead")), 3.0, precision)


def _dxf_angle(center: Point, point: Point) -> float:
    angle = math.degrees(math.atan2(point.y - center.y, point.x - center.x))
    return angle + 360.0 if angle < 0 else angle


def _dxf_number(value: float, precision: int) -> str:
    text = f"{float(value):.{precision}f}".rstrip("0").rstrip(".")
    if text == "-0":
        return "0"
    return text or "0"


def _dxf_text_value(value: str) -> str:
    return str(value).encode("ascii", "replace").decode("ascii").replace("\n", " ")[:240]


def _maybe_float(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _review_part_counts(project: dict[str, Any], layout: NestedLayout) -> dict[str, Any]:
    placed_counts: dict[str, int] = {}
    for part in layout.placed_parts:
        placed_counts[part.profile.name] = placed_counts.get(part.profile.name, 0) + 1
    definitions = []
    for part in project.get("parts", []) or []:
        name = str(part.get("name", "part"))
        import_issues = part.get("import_issues", []) if isinstance(part.get("import_issues"), list) else []
        definitions.append(
            {
                "name": name,
                "source_file": part.get("source_file", part.get("file_name", name)),
                "requested_quantity": int(part.get("quantity", placed_counts.get(name, 0) or 1)),
                "placed_quantity": placed_counts.get(name, 0),
                "import_issue_count": len(import_issues),
                "grain_lock": bool(part.get("grain_lock", False)),
                "allowed_rotations": list(part.get("allowed_rotations", [])),
            }
        )
    return {
        "definition_count": len(definitions),
        "placed_instance_count": len(layout.placed_parts),
        "definitions": definitions,
    }


def _review_import_summary(project: dict[str, Any]) -> dict[str, Any]:
    summary = dict(project.get("import", {}) or {})
    issues = list(summary.get("issues", []) or [])
    summary["issue_count"] = len(issues)
    review_required_count = int(summary.get("blocking_issue_count", sum(1 for issue in issues if issue.get("blocking", True))))
    summary["review_required_issue_count"] = review_required_count
    summary["blocking_issue_count"] = 0
    summary["warning_count"] = len(issues)
    summary["issues"] = issues
    return summary


def _review_layout_utilization(layout: NestedLayout) -> dict[str, Any]:
    boxes = [part.bbox() for part in layout.placed_parts]
    if not boxes:
        used_width = 0.0
        used_height = 0.0
        used_bbox_area = 0.0
    else:
        xmin = min(box[0] for box in boxes)
        ymin = min(box[1] for box in boxes)
        xmax = max(box[2] for box in boxes)
        ymax = max(box[3] for box in boxes)
        used_width = max(0.0, xmax - xmin)
        used_height = max(0.0, ymax - ymin)
        used_bbox_area = used_width * used_height
    part_area = sum(_review_part_area(part) for part in layout.placed_parts)
    usable_width = max(0.0, layout.sheet.width - layout.sheet.margin * 2)
    usable_height = max(0.0, layout.sheet.height - layout.sheet.margin * 2)
    usable_area = usable_width * usable_height
    return {
        "part_area_mm2": round(part_area, 3),
        "used_width_mm": round(used_width, 3),
        "used_height_mm": round(used_height, 3),
        "used_bbox_area_mm2": round(used_bbox_area, 3),
        "sheet_usable_area_mm2": round(usable_area, 3),
        "packing_utilization_percent": _percent(part_area, used_bbox_area),
        "sheet_utilization_percent": _percent(part_area, usable_area),
        "top_free_height_mm": round(max(0.0, layout.sheet.height - layout.sheet.margin - (max((box[3] for box in boxes), default=layout.sheet.margin))), 3),
    }


def _review_part_area(part) -> float:
    polygon = part.polygon()
    if polygon is not None:
        return max(0.0, float(polygon.area))
    total = 0.0
    for contour in part.contours():
        area = abs(contour_area(contour))
        total += area if contour.kind == "outer" else -area
    return max(0.0, total)


def _review_cut_settings_metadata(settings: dict[str, Any] | None) -> dict[str, Any]:
    if settings is None:
        return {}
    fields = (
        "machine",
        "material",
        "thickness_mm",
        "nozzle_mm",
        "current_a",
        "feed_rate_mm_min",
        "feed_rate_mode",
        "kerf_width_mm",
        "pierce_height_mm",
        "pierce_delay_s",
        "cut_height_mm",
        "cut_volts",
        "thc_enabled",
        "air_pressure_bar",
        "small_hole_threshold_mm",
        "small_shape_threshold_mm",
        "small_hole_speed_percent",
        "small_hole_overburn_mm",
        "small_hole_torch_off_before_end_mm",
        "profile_id",
        "profile_version",
        "profile_revision",
        "row_id",
        "row_revision",
        "calibration_state",
        "measured_at",
        "operator",
        "coupon_id",
        "quality_notes",
        "source",
    )
    return {field: settings.get(field) for field in fields if field in settings}


def _review_cut_order(project: dict[str, Any], layout: NestedLayout) -> dict[str, Any]:
    post = project.get("post", {}) or {}
    try:
        options = _post_options_from_project(project, layout)
        sequence = list(planned_cut_sequence(layout.contours(), options))
    except Exception as exc:
        return {
            "available": False,
            "error": str(exc),
            "type": type(exc).__name__,
            "strategy": str(post.get("cut_order_strategy", "nearest")),
            "sequence": [],
        }
    return {
        "available": True,
        "strategy": options.cut_order_strategy,
        "optimize_cut_order": options.optimize_cut_order,
        "keep_part_contours_together": options.keep_part_contours_together,
        "avoid_completed_contours": options.avoid_completed_contours,
        "safe_travel": options.safe_travel,
        "manual_groups": list(options.cut_order_groups),
        "heat_spread_weight": options.heat_spread_weight,
        "heat_lookback": options.heat_lookback,
        "sequence": sequence,
    }


def _review_cam_geometry(issues: list[dict[str, Any]]) -> dict[str, Any]:
    cam_codes = {"kerf_offset", "kerf_offset_centerline", "small_feature_below_kerf"}
    cam_issues = [issue for issue in issues if str(issue.get("code", "")) in cam_codes]
    blocking = [issue for issue in cam_issues if issue.get("blocking", True) is not False]
    centerline = [issue for issue in cam_issues if issue.get("code") == "kerf_offset_centerline"]
    return {
        "total_count": len(cam_issues),
        "blocking_count": len(blocking),
        "centerline_fallback_count": len(centerline),
        "codes": dict(Counter(str(issue.get("code", "unknown")) for issue in cam_issues)),
        "examples": _review_issue_examples(cam_issues),
    }


def _review_dxf_repair_plan(project: dict[str, Any], issues: list[dict[str, Any]]) -> dict[str, Any]:
    import_summary = _review_import_summary(project)
    dxf_issues = [issue for issue in issues if str(issue.get("code", "")).startswith("import_")]
    review_required = [issue for issue in dxf_issues if issue.get("review_required", False)]
    warnings = [issue for issue in dxf_issues if issue.get("blocking", True) is False]
    repair_warnings = [issue for issue in warnings if str(issue.get("code", "")).endswith("_repaired")]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for issue in review_required:
        grouped.setdefault(str(issue.get("code", "import_issue")), []).append(issue)
    actions = [
        {
            "code": code,
            "count": len(grouped_issues),
            "action": _dxf_repair_action(code),
            "auto_repair": _dxf_repair_auto_policy(code),
            "examples": _review_issue_examples(grouped_issues, limit=5),
            "sheet_marker_count": sum(
                1
                for issue in grouped_issues
                if issue.get("sheet_x") is not None and issue.get("sheet_y") is not None
            ),
        }
        for code, grouped_issues in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0]))
    ]
    return {
        "required": False,
        "review_required": bool(review_required),
        "source": import_summary.get("source"),
        "safe_for_export": True,
        "blocking_count": 0,
        "blocking_codes": {},
        "review_required_count": len(review_required),
        "review_required_codes": dict(Counter(str(issue.get("code", "unknown")) for issue in review_required)),
        "action_count": len(actions),
        "actions": actions,
        "warning_count": len(warnings),
        "completed_repair_warning_count": len(repair_warnings),
        "completed_repair_codes": dict(Counter(str(issue.get("code", "unknown")) for issue in repair_warnings)),
    }


def _dxf_repair_action(code: str) -> str:
    actions = {
        "import_self_intersection": (
            "Split crossing or touching loops in CAD, remove accidental crossing edges, then reimport."
        ),
        "import_collinear_overlap": (
            "Remove overlapping or retraced duplicate line edges before cutting; repeated edges would recut the same path."
        ),
        "import_open_contour": (
            "Close the contour in CAD, enable small-gap auto close after review, or use centerline open-path mode only for intentional slots."
        ),
        "import_unsupported_unsafe_entity": (
            "Explode unsafe 3D/proxy/region entities to explicit 2D cut geometry, or review and downgrade only non-cut reference entities."
        ),
        "import_gap_closure_suggestion": (
            "Review the endpoint gap, then either repair the source CAD or enable Auto close DXF gaps for this import."
        ),
    }
    return actions.get(code, "Repair or simplify the DXF source geometry, then reimport and validate before export.")


def _dxf_repair_auto_policy(code: str) -> str:
    policies = {
        "import_self_intersection": "limited_line_only",
        "import_collinear_overlap": "limited_duplicate_retrace_only",
        "import_open_contour": "small_gap_or_centerline_opt_in",
        "import_unsupported_unsafe_entity": "operator_review_only",
        "import_gap_closure_suggestion": "opt_in",
    }
    return policies.get(code, "manual_review")


def _review_issue_summary(issues: list[dict[str, Any]]) -> dict[str, Any]:
    blocking = [issue for issue in issues if issue.get("blocking", True) is not False]
    warnings = [issue for issue in issues if issue.get("blocking", True) is False]
    return {
        "total_count": len(issues),
        "blocking_count": len(blocking),
        "warning_count": len(warnings),
        "blocking_codes": dict(Counter(str(issue.get("code", "unknown")) for issue in blocking)),
        "warning_codes": dict(Counter(str(issue.get("code", "unknown")) for issue in warnings)),
        "blocking_examples": _review_issue_examples(blocking),
        "warning_examples": _review_issue_examples(warnings),
    }


def _warning_only_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for issue in issues:
        item = dict(issue)
        original_blocking = item.get("blocking", True) is not False
        item["blocking"] = False
        if original_blocking:
            item["review_required"] = True
        output.append(item)
    return output


def _review_operator_checklist(
    *,
    layout: NestedLayout,
    settings: dict[str, Any] | None,
    warnings: list[dict[str, Any]],
    issue_summary: dict[str, Any],
    export_preflight: dict[str, Any],
    simulation_metrics: dict[str, Any],
    cut_order: dict[str, Any],
    current_utilization: dict[str, Any],
) -> dict[str, Any]:
    checks = [
        _operator_check(
            "placements",
            bool(layout.placed_parts),
            f"{len(layout.placed_parts)} placed part(s)",
            "No placed parts on the sheet.",
        ),
        _operator_check(
            "blocking_issues",
            int(issue_summary.get("blocking_count", 0)) == 0,
            "No blocking validation issues.",
            f"{int(issue_summary.get('blocking_count', 0))} blocking validation issue(s).",
        ),
        _operator_check(
            "cut_settings",
            settings is not None,
            _cut_settings_check_message(settings),
            "Cut settings are unavailable for the current material/thickness/nozzle.",
        ),
        _operator_check(
            "simulation",
            float(simulation_metrics.get("cut_length_mm", 0.0) or 0.0) > 0,
            (
                f"Simulation has {int(simulation_metrics.get('pierce_count', 0) or 0)} pierce(s), "
                f"{float(simulation_metrics.get('cut_length_mm', 0.0) or 0.0):.1f} mm cut."
            ),
            "Simulation has no cut length.",
        ),
        _operator_check(
            "cut_order",
            bool(cut_order.get("available", False)),
            f"Cut order ready with {len(cut_order.get('sequence', []) or [])} contour(s).",
            str(cut_order.get("error", "Cut order unavailable.")),
        ),
        _operator_check(
            "gcode_preflight",
            bool(export_preflight.get("can_export", False)),
            f"G-code preflight ready, {int(export_preflight.get('gcode_line_count', 0) or 0)} line(s).",
            _export_preflight_check_message(export_preflight),
        ),
    ]
    safe_travel_warning_count = int(simulation_metrics.get("safe_travel_warning_count", 0) or 0)
    gcode_issue_count = int(export_preflight.get("gcode_validation_issue_count", 0) or 0)
    warning_codes = [str(item.get("code", "unknown")) for item in warnings]
    checklist_warnings = [
        _operator_warning("validation_warnings", f"{len(warnings)} validation warning(s): {', '.join(warning_codes[:8])}")
        for _ in [None]
        if warnings
    ]
    if gcode_issue_count:
        checklist_warnings.append(
            _operator_warning("gcode_validation", f"{gcode_issue_count} G-code validation issue(s).")
        )
    if safe_travel_warning_count:
        checklist_warnings.append(
            _operator_warning(
                "safe_travel",
                (
                    f"{safe_travel_warning_count} safe-travel rapid warning(s), "
                    f"{float(simulation_metrics.get('safe_travel_warning_length_mm', 0.0) or 0.0):.1f} mm total."
                ),
            )
        )
    blocking_checks = [check for check in checks if check["status"] == "block"]
    status = "blocked" if blocking_checks else "warnings" if checklist_warnings else "ready"
    return {
        "status": status,
        "ready_to_export": status != "blocked",
        "requires_warning_ack": status == "warnings"
        or int(export_preflight.get("warning_count", 0) or 0) > 0
        or gcode_issue_count > 0,
        "blocking_count": len(blocking_checks),
        "warning_count": len(checklist_warnings),
        "checks": checks,
        "warnings": checklist_warnings,
        "sheet_utilization_percent": current_utilization.get("sheet_utilization_percent", 0.0),
        "packing_utilization_percent": current_utilization.get("packing_utilization_percent", 0.0),
    }


def _operator_check(code: str, ok: bool, ok_message: str, block_message: str) -> dict[str, Any]:
    return {
        "code": code,
        "status": "ok" if ok else "block",
        "message": ok_message if ok else block_message,
    }


def _operator_warning(code: str, message: str) -> dict[str, Any]:
    return {"code": code, "status": "warn", "message": message}


def _cut_settings_check_message(settings: dict[str, Any] | None) -> str:
    if settings is None:
        return ""
    return (
        f"{settings.get('material', 'material')} {settings.get('thickness_mm', '?')} mm, "
        f"nozzle {settings.get('nozzle_mm', '?')} mm, feed {settings.get('feed_rate_mm_min', '?')} mm/min."
    )


def _export_preflight_check_message(export_preflight: dict[str, Any]) -> str:
    if export_preflight.get("error"):
        error = export_preflight["error"]
        return f"{error.get('type', 'Error')}: {error.get('message', '')}"
    if int(export_preflight.get("gcode_validation_issue_count", 0) or 0) > 0:
        return f"{int(export_preflight.get('gcode_validation_issue_count', 0) or 0)} G-code validation issue(s)."
    return "Export preflight blocked."


def _review_issue_examples(issues: list[dict[str, Any]], *, limit: int = 10) -> list[dict[str, Any]]:
    examples = []
    for issue in issues[:limit]:
        item = {
            "code": issue.get("code"),
            "message": issue.get("message"),
            "instance_id": issue.get("instance_id"),
        }
        for key in (
            "entity_type",
            "x",
            "y",
            "target_x",
            "target_y",
            "gap_mm",
            "chain_length_mm",
            "sheet_x",
            "sheet_y",
            "target_sheet_x",
            "target_sheet_y",
        ):
            if issue.get(key) is not None:
                item[key] = issue[key]
        examples.append(item)
    return examples


def _review_export_preflight(project: dict[str, Any], issues: list[dict[str, Any]]) -> dict[str, Any]:
    blocking = [issue for issue in issues if issue.get("blocking", True) is not False]
    warnings = [issue for issue in issues if issue.get("blocking", True) is False]
    report: dict[str, Any] = {
        "can_export": False,
        "blocking_issue_count": len(blocking),
        "warning_count": len(warnings),
        "blocking_codes": [str(issue.get("code", "unknown")) for issue in blocking],
        "warning_codes": [str(issue.get("code", "unknown")) for issue in warnings],
    }
    try:
        gcode = export_project_gcode(project, validation_issues=issues)
    except Exception as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
        return report
    gcode_issues = validate_gcode(gcode)
    report["can_export"] = True
    report["gcode_line_count"] = len(gcode.splitlines())
    report["gcode_validation_issue_count"] = len(gcode_issues)
    report["gcode_validation_codes"] = [issue.code for issue in gcode_issues]
    return report


def _review_simulation_metrics(simulation: dict[str, Any]) -> dict[str, Any]:
    segments = list(simulation.get("segments", []) or [])
    cut_segments = [segment for segment in segments if segment.get("type") == "cut"]
    rapid_segments = [segment for segment in segments if segment.get("type") == "rapid"]
    pierce_segments = [segment for segment in segments if segment.get("type") == "pierce"]
    safe_travel_warning_segments = [segment for segment in rapid_segments if segment.get("safe_travel_warning")]
    return {
        "pierce_count": len(pierce_segments),
        "cut_length_mm": round(sum(float(segment.get("length_mm", 0.0)) for segment in cut_segments), 3),
        "rapid_length_mm": round(sum(float(segment.get("length_mm", 0.0)) for segment in rapid_segments), 3),
        "estimated_cut_s": simulation.get("estimated_cut_s", 0),
        "estimated_rapid_s": simulation.get("estimated_rapid_s", 0),
        "estimated_pierce_s": simulation.get("estimated_pierce_s", 0),
        "estimated_total_s": simulation.get("estimated_total_s", 0),
        "reduced_feed_segment_count": sum(1 for segment in cut_segments if segment.get("reduced_feed")),
        "thc_disabled_segment_count": sum(1 for segment in cut_segments if segment.get("thc_disabled")),
        "tab_bridge_count": sum(1 for segment in rapid_segments if segment.get("tab_bridge")),
        "safe_travel_warning_count": len(safe_travel_warning_segments),
        "safe_travel_warning_length_mm": round(
            sum(float(segment.get("length_mm", 0.0)) for segment in safe_travel_warning_segments),
            3,
        ),
    }


def _empty_review_simulation_metrics() -> dict[str, Any]:
    return {
        "pierce_count": 0,
        "cut_length_mm": 0.0,
        "rapid_length_mm": 0.0,
        "estimated_cut_s": 0.0,
        "estimated_rapid_s": 0.0,
        "estimated_pierce_s": 0.0,
        "estimated_total_s": 0.0,
        "reduced_feed_segment_count": 0,
        "thc_disabled_segment_count": 0,
        "tab_bridge_count": 0,
        "safe_travel_warning_count": 0,
        "safe_travel_warning_length_mm": 0.0,
    }


def _percent(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator * 100.0, 3)


def _nest_options_from_project(project: dict[str, Any], *, sheet: Sheet, spacing: float) -> ShelfNestOptions:
    nesting = project.get("nesting", {}) or {}
    attempt_limit = int(nesting.get("auto_nest_attempts", nesting.get("attempts", 12)))
    angle_step = nesting.get("auto_nest_angle_step_deg", nesting.get("angle_step_deg", 30.0))
    max_runtime = float(nesting.get("auto_nest_max_runtime_s", nesting.get("max_runtime_s", 12.0)))
    parallel_workers = int(nesting.get("auto_nest_parallel_workers", nesting.get("parallel_workers", 1)))
    return ShelfNestOptions(
        sheet=sheet,
        spacing=spacing,
        blocked_boxes=tuple(_blocked_zone_boxes(project)),
        attempt_limit=max(1, min(240, attempt_limit)),
        angle_step_deg=float(angle_step) if angle_step is not None else None,
        allow_arbitrary_rotation=bool(nesting.get("allow_arbitrary_rotation", True)),
        allow_hole_filler=bool(nesting.get("allow_hole_filler", False)),
        hole_filler_part_names=tuple(
            str(part.get("name", ""))
            for part in project.get("parts", []) or []
            if str(part.get("name", "")) and part.get("allow_hole_filler", True) is not False
        ),
        hole_parent_part_names=tuple(
            str(part.get("name", ""))
            for part in project.get("parts", []) or []
            if str(part.get("name", "")) and part.get("allow_hole_parent", True) is not False
        ),
        max_runtime_s=max(1.0, min(120.0, max_runtime)),
        parallel_workers=max(0, min(16, parallel_workers)),
    )


def _nest_summary_dict(summary: NestSummary) -> dict[str, Any]:
    return {
        "attempt_count": summary.attempt_count,
        "successful_attempt_count": summary.successful_attempt_count,
        "best_attempt": summary.best_attempt,
        "geometry_engine": summary.geometry_engine,
        "runtime_ms": round(summary.runtime_ms, 3),
        "parallel_worker_count": summary.parallel_worker_count,
        "attempts_per_second": round(summary.attempts_per_second, 3),
        "candidate_position_count": summary.candidate_position_count,
        "nfp_candidate_count": summary.nfp_candidate_count,
        "exact_clearance_check_count": summary.exact_clearance_check_count,
        "spatial_index_query_count": summary.spatial_index_query_count,
        "spatial_index_fallback_count": summary.spatial_index_fallback_count,
        "cache_hit_count": summary.cache_hit_count,
        "cache_miss_count": summary.cache_miss_count,
        "part_area_mm2": round(summary.part_area_mm2, 3),
        "used_bbox_area_mm2": round(summary.used_bbox_area_mm2, 3),
        "used_width_mm": round(summary.used_width_mm, 3),
        "used_height_mm": round(summary.used_height_mm, 3),
        "used_strip_area_mm2": round(summary.used_strip_area_mm2, 3),
        "top_free_height_mm": round(summary.top_free_height_mm, 3),
        "sheet_usable_area_mm2": round(summary.sheet_usable_area_mm2, 3),
        "packing_utilization_percent": round(summary.packing_utilization_percent, 3),
        "bbox_utilization_percent": round(summary.bbox_utilization_percent, 3),
        "sheet_utilization_percent": round(summary.sheet_utilization_percent, 3),
        "hole_filler_relocation_count": summary.hole_filler_relocation_count,
        "time_limited": summary.time_limited,
        "parallel_fallback_reason": summary.parallel_fallback_reason,
        "bbox_fallback_count": summary.bbox_fallback_count,
        "current_layout_fallback": False,
    }


def _record_nest_run(project: dict[str, Any], layout: NestedLayout) -> None:
    nesting = project.setdefault("nesting", {})
    result = nesting.get("last_result")
    if not isinstance(result, dict):
        return
    history = [item for item in nesting.get("run_history", []) if isinstance(item, dict)]
    next_id = max((int(item.get("run_id", 0) or 0) for item in history), default=0) + 1
    history.append(_nest_run_history_entry(project, layout, result, next_id))
    nesting["run_history"] = history[-MAX_NEST_RUN_HISTORY:]


def _nest_run_history_entry(
    project: dict[str, Any],
    layout: NestedLayout,
    result: dict[str, Any],
    run_id: int,
) -> dict[str, Any]:
    nesting = project.get("nesting", {}) or {}
    sheet = project.get("sheet", {}) or {}
    fields = (
        "attempt_count",
        "successful_attempt_count",
        "best_attempt",
        "geometry_engine",
        "runtime_ms",
        "parallel_worker_count",
        "attempts_per_second",
        "candidate_position_count",
        "nfp_candidate_count",
        "exact_clearance_check_count",
        "spatial_index_query_count",
        "spatial_index_fallback_count",
        "cache_hit_count",
        "cache_miss_count",
        "used_width_mm",
        "used_height_mm",
        "top_free_height_mm",
        "packing_utilization_percent",
        "bbox_utilization_percent",
        "sheet_utilization_percent",
        "lead_spacing_fallback",
        "lead_spacing_fallback_skipped",
        "lead_spacing_mm",
        "auto_lead_override_count",
        "hole_filler_relocation_count",
        "time_limited",
        "parallel_fallback_reason",
        "bbox_fallback_count",
        "current_layout_fallback",
        "complexity_fallback",
        "complexity_fallback_reason",
        "complexity_instance_count",
        "complexity_contour_count",
    )
    entry = {key: result.get(key) for key in fields if key in result}
    entry.update(
        {
            "run_id": run_id,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "part_instance_count": len(layout.placed_parts),
            "sheet_width_mm": float(sheet.get("width_mm", layout.sheet.width)),
            "sheet_height_mm": float(sheet.get("height_mm", layout.sheet.height)),
            "sheet_margin_mm": float(sheet.get("margin_mm", layout.sheet.margin)),
            "spacing_mm": float(project.get("spacing_mm", layout.spacing)),
            "requested_attempts": int(nesting.get("auto_nest_attempts", nesting.get("attempts", 12))),
            "requested_angle_step_deg": float(
                nesting.get("auto_nest_angle_step_deg", nesting.get("angle_step_deg", 30.0))
            ),
            "requested_max_runtime_s": float(
                nesting.get("auto_nest_max_runtime_s", nesting.get("max_runtime_s", 12.0))
            ),
            "requested_parallel_workers": int(
                nesting.get("auto_nest_parallel_workers", nesting.get("parallel_workers", 1))
            ),
            "allow_arbitrary_rotation": bool(nesting.get("allow_arbitrary_rotation", True)),
            "allow_hole_filler": bool(nesting.get("allow_hole_filler", False)),
            "common_line_cutting": _common_line_enabled(project),
        }
    )
    return entry


def _cut_settings_from_project(project: dict[str, Any]):
    cut = project.get("cut", {})
    chart, machine, source, profile_id, profile_version, profile_revision = _cut_chart_from_project(project)
    settings = select_cut_settings(
        material=str(cut.get("material", "mild_steel")),
        thickness_mm=float(cut.get("thickness_mm", 3.0)),
        nozzle_mm=float(cut["nozzle_mm"]) if cut.get("nozzle_mm") is not None else None,
        chart=chart,
        machine=machine,
        source=source,
        profile_id=profile_id,
        profile_version=profile_version,
        profile_revision=profile_revision,
    )
    if str(cut.get("feed_rate_mode", "auto")) == "manual":
        feed_rate = int(round(float(cut.get("manual_feed_rate_mm_min", settings.feed_rate_mm_min))))
        if feed_rate <= 0:
            raise ValueError("Manual feed rate must be positive")
        settings = replace(
            settings,
            feed_rate_mm_min=feed_rate,
            notes=(*settings.notes, "Manual feed rate override"),
        )
    return settings


def _cut_chart_from_project(project: dict[str, Any]):
    default_profile = default_cut_chart_profile()
    chart = project.get("cut_chart")
    if not isinstance(chart, dict) or not chart.get("rows"):
        return (
            default_profile.rows,
            default_profile.machine,
            default_profile.source,
            default_profile.profile_id,
            default_profile.version,
            default_profile.revision,
        )
    rows = cut_chart_rows_from_dicts(chart.get("rows"))
    machine = str(chart.get("machine") or default_profile.machine)
    source = str(chart.get("source") or f"Project cut chart {chart.get('version', '')}".strip())
    profile_id = str(chart.get("profile_id") or chart.get("id") or "project-cut-chart")
    profile_version = str(chart.get("version") or "")
    profile_revision = str(chart.get("revision") or chart.get("profile_revision") or profile_version)
    return rows, machine, source, profile_id, profile_version, profile_revision


def _post_options_from_project(
    project: dict[str, Any],
    layout: NestedLayout,
    *,
    settings=None,
) -> QtPlasmaCOptions:
    settings = settings or _cut_settings_from_project(project)
    post = project.get("post", {})
    small_feature_source = str(post.get("small_feature_source", "manual"))
    if small_feature_source not in ("manual", "cut_chart"):
        raise ValueError("Small feature source must be manual or cut_chart")
    if small_feature_source == "cut_chart":
        small_hole_threshold = settings.small_hole_threshold_mm
        small_shape_threshold = settings.small_shape_threshold_mm
        small_hole_speed_percent = settings.small_hole_speed_percent
        small_hole_overburn = settings.small_hole_overburn_mm
        small_hole_torch_off_before_end = settings.small_hole_torch_off_before_end_mm
    else:
        small_hole_threshold = float(post.get("small_hole_threshold_mm", settings.small_hole_threshold_mm))
        small_shape_threshold = float(
            post.get("small_shape_threshold_mm", post.get("small_hole_threshold_mm", settings.small_shape_threshold_mm))
        )
        small_hole_speed_percent = float(post.get("small_hole_speed_percent", settings.small_hole_speed_percent))
        small_hole_overburn = float(post.get("small_hole_overburn_mm", settings.small_hole_overburn_mm))
        small_hole_torch_off_before_end = float(
            post.get("small_hole_torch_off_before_end_mm", settings.small_hole_torch_off_before_end_mm)
        )
    material_mode = str(post.get("qtplasmac_material_mode", "temporary"))
    if material_mode not in ("temporary", "fixed"):
        raise ValueError("QtPlasmaC material mode must be temporary or fixed")
    fixed_material = None
    emit_temporary = material_mode == "temporary"
    if material_mode == "fixed":
        fixed_material = int(post.get("qtplasmac_material_number", 0))
        if fixed_material < 0:
            raise ValueError("QtPlasmaC material number cannot be negative")
    return QtPlasmaCOptions(
        cut_settings=settings,
        material=fixed_material,
        material_wait_s=float(post.get("qtplasmac_material_wait_s", 1.0)),
        emit_temporary_material=emit_temporary,
        lead_in_mode=str(post.get("lead_in_mode", "auto")),
        lead_in=float(post.get("lead_in_mm", 5.0)),
        lead_out=float(post.get("lead_out_mm", 0.0)),
        lead_in_min_hole_diameter=float(post.get("lead_in_min_hole_diameter_mm", 20.0)),
        small_hole_threshold=small_hole_threshold,
        small_shape_threshold=small_shape_threshold,
        small_hole_speed_percent=small_hole_speed_percent,
        small_hole_overburn=small_hole_overburn,
        small_hole_torch_off_before_end=small_hole_torch_off_before_end,
        path_tolerance=float(post.get("path_tolerance_mm", 0.1)),
        precision=int(post.get("precision", 3)),
        safe_travel=bool(post.get("safe_travel", True)),
        travel_clearance=float(post.get("travel_clearance_mm", 8.0)),
        travel_bounds=_travel_bounds(layout.sheet),
        travel_obstacles=tuple(_travel_obstacles_from_project(project)),
        tabs=tuple(_tabs_from_project(project)),
        lead_overrides=tuple(_lead_overrides_from_project(project)),
        avoid_completed_contours=bool(post.get("avoid_completed_contours", True)),
        optimize_cut_order=bool(post.get("optimize_cut_order", True)),
        keep_part_contours_together=bool(post.get("keep_part_contours_together", True)),
        cut_order_strategy=str(post.get("cut_order_strategy", "nearest")),
        cut_order_groups=tuple(str(item) for item in post.get("cut_order_groups", post.get("cut_order_override", ())) or ()),
        heat_spread_weight=float(post.get("heat_spread_weight", 0.35)),
        heat_lookback=int(post.get("heat_lookback", 3)),
        common_line_cutting=_common_line_enabled(project),
        common_line_tolerance=float(post.get("common_line_tolerance_mm", 0.05)),
        kerf_offset_fallback=str(post.get("kerf_offset_fallback", "centerline")),
        open_path_mode=str(post.get("open_path_mode", "centerline")),
        auto_tabs=bool(post.get("auto_tabs", False)),
        auto_tab_count=int(post.get("auto_tab_count", 2)),
        auto_tab_length=float(post.get("auto_tab_length_mm", 8.0)),
        auto_tab_min_outer_diameter=float(post.get("auto_tab_min_outer_diameter_mm", 60.0)),
    )


def _auto_lead_skip_reason(layout: NestedLayout, deadline: float | None) -> str | None:
    if deadline is not None and time.monotonic() >= deadline:
        return "time_budget"
    if _layout_segment_count(layout) > 2000:
        return "geometry_complexity"
    return None


def _layout_segment_count(layout: NestedLayout) -> int:
    count = 0
    for part in layout.placed_parts:
        for contour in part.profile.contours:
            if isinstance(contour, PathContour):
                count += len(contour.segments)
            else:
                count += 1
    return count


def _apply_auto_lead_overrides(
    project: dict[str, Any],
    layout: NestedLayout,
    *,
    deadline: float | None = None,
) -> tuple[dict[str, Any], int]:
    if deadline is not None and time.monotonic() >= deadline:
        return project, 0
    manual_overrides = [
        item
        for item in project.get("lead_overrides", []) or []
        if not bool(item.get("auto_generated", False))
    ]
    working_project = {**project, "lead_overrides": manual_overrides}
    try:
        options = _post_options_from_project(working_project, layout)
    except ValueError:
        return ({**project, "lead_overrides": manual_overrides}, 0)
    if _common_line_enabled(project):
        return ({**project, "lead_overrides": manual_overrides}, 0)
    generated: list[dict[str, Any]] = []
    for part in layout.placed_parts:
        if deadline is not None and time.monotonic() >= deadline:
            break
        for contour in part.contours():
            if deadline is not None and time.monotonic() >= deadline:
                break
            if _has_lead_override(contour.name, manual_overrides):
                continue
            active_overrides = [*manual_overrides, *generated]
            active_options = replace(
                options,
                lead_overrides=tuple(_lead_overrides_from_items(active_overrides)),
            )
            if not _contour_has_lead_issues(working_project, layout, part, contour, active_options):
                continue
            override = _best_auto_lead_override(
                working_project,
                layout,
                part,
                contour,
                active_overrides,
                options,
                deadline=deadline,
            )
            if override is not None:
                generated.append(override)
    updated = {**project, "lead_overrides": [*manual_overrides, *generated]}
    return updated, len(generated)


def _best_auto_lead_override(
    project: dict[str, Any],
    layout: NestedLayout,
    part,
    contour: Contour,
    active_overrides: list[dict[str, Any]],
    options: QtPlasmaCOptions,
    *,
    deadline: float | None = None,
) -> dict[str, Any] | None:
    for candidate in _auto_lead_candidates(contour, options):
        if deadline is not None and time.monotonic() >= deadline:
            return None
        candidate_items = [*active_overrides, candidate]
        candidate_options = replace(
            options,
            lead_overrides=tuple(_lead_overrides_from_items(candidate_items)),
        )
        if not _contour_has_lead_issues(project, layout, part, contour, candidate_options):
            return candidate
    return None


def _contour_has_lead_issues(
    project: dict[str, Any],
    layout: NestedLayout,
    part,
    contour: Contour,
    options: QtPlasmaCOptions,
) -> bool:
    context = _lead_safety_context(project, layout)
    try:
        moves = planned_lead_moves((contour,), options)
    except ValueError:
        return True
    return any(_lead_move_issue_items(part, move, context) for move in moves)


def _auto_lead_candidates(contour: Contour, options: QtPlasmaCOptions) -> list[dict[str, Any]]:
    mode = _auto_lead_override_mode(options)
    points = _auto_lead_candidate_points(contour, options)
    return [
        {
            "id": f"auto_lead_{_safe_identifier(contour.name)}_{index}",
            "contour_name": contour.name,
            "start_x_mm": point.x,
            "start_y_mm": point.y,
            "pierce_x_mm": None,
            "pierce_y_mm": None,
            "lead_in_mode": mode,
            "lead_in_mm": options.lead_in,
            "lead_out_mm": options.lead_out,
            "auto_generated": True,
        }
        for index, point in enumerate(points, start=1)
    ]


def _auto_lead_override_mode(options: QtPlasmaCOptions) -> str:
    if options.lead_in_mode == "none" or options.lead_in <= 0:
        return "none"
    return "line"


def _auto_lead_candidate_points(contour: Contour, options: QtPlasmaCOptions) -> list[Point]:
    if isinstance(contour, CircleContour):
        return _circle_auto_lead_points(contour)
    if isinstance(contour, PathContour):
        return _path_auto_lead_points(contour, options)
    return []


def _circle_auto_lead_points(contour: CircleContour) -> list[Point]:
    angles = (180, 90, 270, 0, 135, 225, 45, 315, 150, 210, 120, 240, 60, 300, 30, 330)
    return [
        Point(
            contour.center.x + math.cos(math.radians(angle)) * contour.radius,
            contour.center.y + math.sin(math.radians(angle)) * contour.radius,
        )
        for angle in angles
    ]


def _path_auto_lead_points(contour: PathContour, options: QtPlasmaCOptions) -> list[Point]:
    points = contour.points(max_chord=max(options.path_tolerance * 20.0, 3.0))
    if not points:
        return []
    scored = sorted(
        points,
        key=lambda point: (
            round(point.y, 3),
            round(point.x, 3),
        ),
    )
    return _dedupe_points(scored, tolerance=0.5)[:48]


def _dedupe_points(points: list[Point], *, tolerance: float) -> list[Point]:
    output: list[Point] = []
    for point in points:
        if any(point.distance_to(existing) <= tolerance for existing in output):
            continue
        output.append(point)
    return output


def _has_lead_override(contour_name: str, overrides: list[dict[str, Any]]) -> bool:
    return any(_contour_name_matches(contour_name, str(item.get("contour_name", ""))) for item in overrides)


def _contour_name_matches(actual: str, requested: str) -> bool:
    return actual == requested or actual.endswith(f"_{requested}") or requested.endswith(f"_{actual}")


def _lead_overrides_from_items(items: list[dict[str, Any]]) -> list[LeadOverride]:
    return _lead_overrides_from_project({"lead_overrides": items})


def _safe_identifier(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_") or "contour"


def _enabled_zones(project: dict[str, Any]) -> list[dict[str, Any]]:
    zones = []
    for zone in project.get("zones", []) or []:
        if not bool(zone.get("enabled", True)):
            continue
        zone_type = str(zone.get("type", "keepout"))
        x = float(zone.get("x_mm", zone.get("x", 0.0)))
        y = float(zone.get("y_mm", zone.get("y", 0.0)))
        width = float(zone.get("width_mm", zone.get("width", 0.0)))
        height = float(zone.get("height_mm", zone.get("height", 0.0)))
        if width <= 0 or height <= 0:
            continue
        zones.append(
            {
                **zone,
                "type": zone_type,
                "x_mm": x,
                "y_mm": y,
                "width_mm": width,
                "height_mm": height,
            }
        )
    return zones


def _blocked_zone_boxes(project: dict[str, Any]) -> list[tuple[float, float, float, float]]:
    output = []
    for zone in _enabled_zones(project):
        if zone["type"] not in {"keepout", "clamp", "damaged", "slat"}:
            continue
        output.append(
            (
                zone["x_mm"],
                zone["y_mm"],
                zone["x_mm"] + zone["width_mm"],
                zone["y_mm"] + zone["height_mm"],
            )
        )
    return output


def _zone_issue_items(project: dict[str, Any], layout: NestedLayout) -> list[dict[str, str | None]]:
    issues: list[dict[str, str | None]] = []
    zones = _enabled_zones(project)
    if not zones:
        return issues
    blocked = [zone for zone in zones if zone["type"] in {"keepout", "clamp", "damaged", "slat"}]
    remnants = [zone for zone in zones if zone["type"] == "remnant"]
    remnant_area = _zone_union(remnants)
    for part in layout.placed_parts:
        part_polygon = part.polygon()
        part_box = part.bbox()
        for zone in blocked:
            if _part_intersects_zone(part_polygon, part_box, zone):
                issues.append(
                    {
                        "code": "zone_collision",
                        "message": f"{part.instance_id} intersects {zone['type']} zone {zone.get('name', zone.get('id', 'zone'))}",
                        "instance_id": part.instance_id,
                    }
                )
        if remnants and not _part_inside_remnant(part_polygon, part_box, remnant_area, remnants):
            issues.append(
                {
                    "code": "outside_remnant",
                    "message": f"{part.instance_id} is outside enabled remnant area",
                    "instance_id": part.instance_id,
                }
            )
    return issues


def _assert_zone_safe(project: dict[str, Any], layout: NestedLayout) -> None:
    issues = _zone_issue_items(project, layout)
    if not issues:
        return
    messages = "; ".join(issue["message"] or "" for issue in issues[:5])
    if len(issues) > 5:
        messages += f"; and {len(issues) - 5} more zone issues"
    raise ValueError(f"Project has unsafe sheet zones: {messages}")


def _hole_filler_bridge_issue_items(project: dict[str, Any], layout: NestedLayout) -> list[dict[str, Any]]:
    if Polygon is None:
        return []
    part_count = len(layout.placed_parts)
    contour_count = sum(len(part.profile.contours) for part in layout.placed_parts)
    if part_count > HOLE_FILLER_BRIDGE_VALIDATION_MAX_PARTS or contour_count > HOLE_FILLER_BRIDGE_VALIDATION_MAX_CONTOURS:
        return [
            {
                "code": "hole_filler_bridge_complexity",
                "message": (
                    f"Hole-filler bridge precheck skipped for complex layout with {part_count} parts and "
                    f"{contour_count} contours; manually verify part-in-hole bridges when using hole filler nesting"
                ),
                "instance_id": None,
                "blocking": False,
            }
        ]
    tabs = _tabs_from_project(project)
    part_entries = tuple((part, part.polygon(), part.bbox()) for part in layout.placed_parts)
    issues: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for parent, _parent_polygon, _parent_box in part_entries:
        for contour in parent.contours():
            if contour.kind == "outer":
                continue
            hole_polygon = _single_contour_polygon(contour, max_chord=1.0)
            if hole_polygon is None:
                continue
            hole_box = contour.bbox()
            for child, child_polygon, child_box in part_entries:
                if child.instance_id == parent.instance_id:
                    continue
                if not _box_contains_box(hole_box, child_box, tolerance=1e-6):
                    continue
                if child_polygon is None:
                    continue
                if not hole_polygon.buffer(1e-6).covers(child_polygon):
                    continue
                key = (child.instance_id, parent.instance_id, contour.name)
                if key in seen:
                    continue
                seen.add(key)
                found = _positive_tab_count_for_contour(tabs, contour.name)
                required = 2
                if found >= required:
                    continue
                issues.append(
                    {
                        "code": "hole_filler_requires_bridge",
                        "message": (
                            f"{child.instance_id} is nested inside {parent.instance_id} internal cutout "
                            f"{contour.name}; found {found}/{required} bridge tabs on that contour. "
                            f"Add at least {required} tabs before cutting this hole."
                        ),
                        "instance_id": child.instance_id,
                        "parent_instance_id": parent.instance_id,
                        "contour_name": contour.name,
                        "tabs_found": found,
                        "tabs_required": required,
                    }
                )
    return issues


def _assert_hole_filler_bridge_safe(project: dict[str, Any], layout: NestedLayout) -> None:
    issues = _hole_filler_bridge_issue_items(project, layout)
    if not issues:
        return
    messages = "; ".join(issue["message"] or "" for issue in issues[:5])
    if len(issues) > 5:
        messages += f"; and {len(issues) - 5} more hole filler bridge issues"
    raise ValueError(f"Project has unsafe hole filler bridges: {messages}")


def _positive_tab_count_for_contour(tabs: list[CutTab], contour_name: str) -> int:
    return sum(1 for tab in tabs if tab.length > 0 and _contour_name_matches(contour_name, tab.contour_name))


def _single_contour_polygon(contour: Contour, *, max_chord: float):
    if Polygon is None:
        return None
    points = contour.points(max_chord=max_chord)
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


def _box_contains_box(
    outer: tuple[float, float, float, float],
    inner: tuple[float, float, float, float],
    *,
    tolerance: float,
) -> bool:
    return (
        inner[0] >= outer[0] - tolerance
        and inner[1] >= outer[1] - tolerance
        and inner[2] <= outer[2] + tolerance
        and inner[3] <= outer[3] + tolerance
    )


def _cam_geometry_issue_items(
    project: dict[str, Any],
    layout: NestedLayout,
    options: QtPlasmaCOptions | None = None,
) -> list[dict[str, str | None]]:
    issues: list[dict[str, str | None]] = []
    seen: set[tuple[str, str | None]] = set()
    contour_count = sum(len(part.profile.contours) for part in layout.placed_parts)
    segment_count = _layout_segment_count(layout)
    if contour_count > CAM_GEOMETRY_VALIDATION_MAX_CONTOURS or segment_count > CAM_GEOMETRY_VALIDATION_MAX_SEGMENTS:
        return [
            {
                "code": "cam_geometry_complexity",
                "message": (
                    f"CAM geometry precheck skipped for complex layout with {contour_count} contours and "
                    f"{segment_count} segments; export will still use centerline fallback for failed offsets"
                ),
                "instance_id": None,
                "blocking": False,
            }
        ]
    try:
        options = options or _post_options_from_project(project, layout)
    except ValueError as exc:
        return [{"code": "cam_settings", "message": str(exc), "instance_id": None}]
    strict_options = (
        replace(options, kerf_offset_fallback="block")
        if options.kerf_offset_fallback == "centerline"
        else options
    )
    for part in layout.placed_parts:
        for contour in part.contours():
            try:
                planned_lead_moves((contour,), strict_options)
            except ValueError as exc:
                if not _is_cam_geometry_error(exc):
                    continue
                centerline_fallback = (
                    options.kerf_offset_fallback == "centerline"
                    and _is_centerline_fallback_error(exc)
                )
                key = (str(exc), part.instance_id)
                if key in seen:
                    continue
                seen.add(key)
                suffix = (
                    "; centerline fallback will cut without kerf compensation"
                    if centerline_fallback
                    else ""
                )
                issue_code = _cam_geometry_issue_code(exc, centerline_fallback=centerline_fallback)
                issues.append(
                    {
                        "code": issue_code,
                        "message": f"{part.instance_id}: {exc}{suffix}",
                        "instance_id": part.instance_id,
                        "blocking": not centerline_fallback,
                    }
                )
    return issues


def _assert_cam_geometry_safe(project: dict[str, Any], layout: NestedLayout, options: QtPlasmaCOptions) -> None:
    issues = [
        issue
        for issue in _cam_geometry_issue_items(project, layout, options)
        if issue["code"] != "kerf_offset_centerline"
    ]
    if not issues:
        return
    messages = "; ".join(issue["message"] or "" for issue in issues[:5])
    if len(issues) > 5:
        messages += f"; and {len(issues) - 5} more kerf/geometry issues"
    raise ValueError(f"Project has invalid kerf offset: {messages}")


def _cam_geometry_issue_code(exc: ValueError, *, centerline_fallback: bool) -> str:
    if centerline_fallback:
        return "kerf_offset_centerline"
    if "path radius is not positive" in str(exc):
        return "small_feature_below_kerf"
    return "kerf_offset"


def _is_cam_geometry_error(exc: ValueError) -> bool:
    message = str(exc)
    markers = (
        "Kerf offset",
        "Contour path",
        "offset path",
        "Cannot offset",
        "zero-area contour",
        "zero-length segment",
        "fewer than 3 geometry points",
        "path radius is not positive",
        "self-intersects",
    )
    return any(marker in message for marker in markers)


def _is_centerline_fallback_error(exc: ValueError) -> bool:
    message = str(exc)
    return (
        "Kerf offset" in message
        or "offset path" in message
        or "path radius is not positive" in message
        or "fewer than 3 geometry points" in message
        or "Common-line export requires kerf offset disabled" in message
        or "self-intersects" in message
        or "zero area" in message
    )


def _is_open_path_fallback_error(exc: ValueError) -> bool:
    return str(exc).endswith(" is not closed")


def _safe_travel_issue_items(project: dict[str, Any], layout: NestedLayout) -> list[dict[str, str | None]]:
    contour_count = sum(len(part.profile.contours) for part in layout.placed_parts)
    segment_count = _layout_segment_count(layout)
    if contour_count > SAFE_TRAVEL_VALIDATION_MAX_CONTOURS or segment_count > SAFE_TRAVEL_VALIDATION_MAX_SEGMENTS:
        return [
            {
                "code": "safe_travel",
                "message": (
                    f"Safe travel precheck skipped for complex layout with {contour_count} contours and {segment_count} segments; "
                    "export/simulation will still emit route fallback warnings"
                ),
                "instance_id": None,
                "blocking": False,
            }
        ]
    try:
        options = _post_options_from_project(project, layout)
        gcode = _generate_layout_gcode_warning_only(layout, options)
    except ValueError as exc:
        if not _is_safe_travel_error(exc):
            return []
        messages = [str(exc)]
    else:
        messages = _safe_travel_warning_messages(gcode)
    return [
        {
            "code": "safe_travel",
            "message": message,
            "instance_id": None,
            "blocking": False,
        }
        for message in messages
    ]


def _is_safe_travel_error(exc: ValueError) -> bool:
    return str(exc).startswith("Safe travel route blocked")


def _safe_travel_warning_messages(gcode: str) -> list[str]:
    messages = []
    seen = set()
    for line in gcode.splitlines():
        if "WARNING: safe travel " not in line:
            continue
        message = _extract_gcode_comment(line) or line
        if message in seen:
            continue
        seen.add(message)
        messages.append(message)
    return messages


def _extract_gcode_comment(line: str) -> str | None:
    start = line.find("(")
    end = line.rfind(")")
    if start >= 0 and end > start:
        return line[start + 1 : end]
    return None


def _gcode_comment_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("(", "[").replace(")", "]")).strip()[:220]


def _lead_issue_items(
    project: dict[str, Any],
    layout: NestedLayout,
    options: QtPlasmaCOptions | None = None,
) -> list[dict[str, str | None]]:
    issues: list[dict[str, str | None]] = []
    seen: set[tuple[str, str, str | None]] = set()
    contour_count = sum(len(part.profile.contours) for part in layout.placed_parts)
    segment_count = _layout_segment_count(layout)
    if contour_count > LEAD_VALIDATION_MAX_CONTOURS or segment_count > LEAD_VALIDATION_MAX_SEGMENTS:
        issues.extend(_stale_cut_modifier_issue_items(project, layout))
        issues.append(
            {
                "code": "lead_geometry_complexity",
                "message": (
                    f"Lead-in/out precheck skipped for complex layout with {contour_count} contours and "
                    f"{segment_count} segments; export will still emit available lead moves"
                ),
                "instance_id": None,
                "blocking": False,
            }
        )
        return issues
    try:
        options = options or _post_options_from_project(project, layout)
    except ValueError as exc:
        return [{"code": "lead_settings", "message": str(exc), "instance_id": None}]
    context = _lead_safety_context(project, layout)

    def add(code: str, message: str, instance_id: str | None) -> None:
        key = (code, message, instance_id)
        if key in seen:
            return
        seen.add(key)
        issues.append({"code": code, "message": message, "instance_id": instance_id})

    for issue in _stale_cut_modifier_issue_items(project, layout):
        add(str(issue["code"]), str(issue["message"]), issue["instance_id"])

    for part, _part_polygon, _part_box in context.part_entries:
        try:
            moves = planned_lead_moves(part.contours(), options)
        except ValueError as exc:
            if _is_cam_geometry_error(exc):
                continue
            add("lead_invalid", f"{part.instance_id}: {exc}", part.instance_id)
            continue
        for move in moves:
            for issue in _lead_move_issue_items(part, move, context):
                add(str(issue["code"]), str(issue["message"]), issue["instance_id"])
    return issues


def _stale_cut_modifier_issue_items(project: dict[str, Any], layout: NestedLayout) -> list[dict[str, str | None]]:
    contour_names = tuple(contour.name for contour in layout.contours())
    issues: list[dict[str, str | None]] = []
    seen: set[tuple[str, str]] = set()

    def add(code: str, contour_name: str, label: str) -> None:
        key = (code, contour_name)
        if key in seen:
            return
        seen.add(key)
        instance_id = _referenced_instance_id(contour_name, layout)
        issues.append(
            {
                "code": code,
                "message": (
                    f"{label} references missing contour {contour_name}; "
                    "clear or recreate it after reimporting the part geometry."
                ),
                "instance_id": instance_id,
            }
        )

    for item in project.get("lead_overrides", []) or []:
        contour_name = str(item.get("contour_name", ""))
        if contour_name and not _referenced_contour_exists(contour_name, contour_names):
            add("stale_lead_override", contour_name, "Lead override")
    for item in project.get("tabs", []) or []:
        contour_name = str(item.get("contour_name", ""))
        if contour_name and not _referenced_contour_exists(contour_name, contour_names):
            add("stale_tab", contour_name, "Tab")
    return issues


def _referenced_contour_exists(requested: str, contour_names: tuple[str, ...]) -> bool:
    return any(_contour_name_matches(actual, requested) for actual in contour_names)


def _referenced_instance_id(contour_name: str, layout: NestedLayout) -> str | None:
    for part in layout.placed_parts:
        if contour_name == part.instance_id or contour_name.startswith(f"{part.instance_id}_"):
            return part.instance_id
    return None


def _lead_safety_context(project: dict[str, Any], layout: NestedLayout) -> _LeadSafetyContext:
    post = project.get("post", {})
    zones = _enabled_zones(project)
    blocked_zones = tuple(zone for zone in zones if zone["type"] in {"keepout", "clamp", "damaged", "slat"})
    pierce_zones = tuple(zone for zone in zones if zone["type"] == "pierce_keepout")
    remnants = tuple(zone for zone in zones if zone["type"] == "remnant")
    return _LeadSafetyContext(
        crater_radius=max(0.0, float(post.get("pierce_crater_diameter_mm", 4.0)) / 2.0),
        clearance=max(0.0, float(post.get("lead_clearance_mm", 1.0))),
        sheet_bounds=_physical_sheet_bounds(layout.sheet),
        part_entries=tuple((part, part.polygon(), part.bbox()) for part in layout.placed_parts),
        blocked_zones=blocked_zones,
        pierce_zones=pierce_zones,
        remnants=remnants,
        remnant_area=_zone_union(list(remnants)),
    )


def _lead_move_issue_items(part, move, context: _LeadSafetyContext) -> list[dict[str, str | None]]:
    issues: list[dict[str, str | None]] = []
    for label, geometry, bounds in _lead_geometries(move, context.crater_radius):
        if _bounds_outside(bounds, context.sheet_bounds):
            issues.append(
                {
                    "code": "lead_outside_sheet",
                    "message": f"{part.instance_id} {move.contour_name} {label} is outside sheet area",
                    "instance_id": part.instance_id,
                }
            )
        if context.remnants and not _geometry_inside_remnant(geometry, bounds, context.remnant_area, list(context.remnants)):
            issues.append(
                {
                    "code": "lead_outside_remnant",
                    "message": f"{part.instance_id} {move.contour_name} {label} is outside enabled remnant area",
                    "instance_id": part.instance_id,
                }
            )
        if label in {"pierce point", "pierce crater"}:
            for zone in context.pierce_zones:
                if _geometry_conflicts_with_zone(geometry, bounds, zone, context.clearance):
                    issues.append(
                        {
                            "code": "pierce_zone_collision",
                            "message": (
                                f"{part.instance_id} {move.contour_name} {label} conflicts with "
                                f"pierce keepout zone {zone.get('name', zone.get('id', 'zone'))}"
                            ),
                            "instance_id": part.instance_id,
                        }
                    )
                    break
        if label == "pierce point":
            continue
        for other, other_polygon, other_box in context.part_entries:
            if "_common_" in move.contour_name:
                break
            if other.instance_id == part.instance_id:
                continue
            if _geometry_conflicts_with_polygon(geometry, bounds, other_polygon, other_box, context.clearance):
                issues.append(
                    {
                        "code": "lead_collision",
                        "message": f"{part.instance_id} {move.contour_name} {label} conflicts with {other.instance_id}",
                        "instance_id": part.instance_id,
                    }
                )
                break
        for zone in context.blocked_zones:
            if _geometry_conflicts_with_zone(geometry, bounds, zone, context.clearance):
                issues.append(
                    {
                        "code": "lead_zone_collision",
                        "message": (
                            f"{part.instance_id} {move.contour_name} {label} conflicts with "
                            f"{zone['type']} zone {zone.get('name', zone.get('id', 'zone'))}"
                        ),
                        "instance_id": part.instance_id,
                    }
                )
                break
    return issues


def _assert_lead_safe(project: dict[str, Any], layout: NestedLayout, options: QtPlasmaCOptions) -> None:
    issues = _lead_issue_items(project, layout, options)
    if not issues:
        return
    messages = "; ".join(issue["message"] or "" for issue in issues[:5])
    if len(issues) > 5:
        messages += f"; and {len(issues) - 5} more lead issues"
    raise ValueError(f"Project has unsafe lead-in/out: {messages}")


def _lead_geometries(move, crater_radius: float):
    output = []
    if move.lead_in_points:
        geometry = _polyline_geometry(move.lead_in_points)
        output.append(("lead-in", geometry, _points_bounds(move.lead_in_points)))
    if move.lead_out_points:
        geometry = _polyline_geometry(move.lead_out_points)
        output.append(("lead-out", geometry, _points_bounds(move.lead_out_points)))
    if crater_radius > 0:
        point_geometry = _point_geometry(move.pierce, crater_radius)
        output.append(("pierce crater", point_geometry, _point_bounds(move.pierce, crater_radius)))
    else:
        output.append(("pierce point", _point_geometry(move.pierce, 0.0), _point_bounds(move.pierce, 0.0)))
    return output


def _polyline_geometry(points: tuple[Point, ...] | list[Point]):
    if LineString is None or len(points) < 2:
        return None
    coordinates = [(point.x, point.y) for point in points]
    if len(set(coordinates)) < 2:
        return None
    return LineString(coordinates)


def _point_geometry(point: Point, radius: float):
    if ShapelyPoint is None:
        return None
    geometry = ShapelyPoint(point.x, point.y)
    return geometry.buffer(radius, quad_segs=12) if radius > 0 else geometry


def _points_bounds(points: tuple[Point, ...] | list[Point]) -> tuple[float, float, float, float]:
    return (
        min(point.x for point in points),
        min(point.y for point in points),
        max(point.x for point in points),
        max(point.y for point in points),
    )


def _point_bounds(point: Point, radius: float) -> tuple[float, float, float, float]:
    return (point.x - radius, point.y - radius, point.x + radius, point.y + radius)


def _bounds_outside(
    bounds: tuple[float, float, float, float],
    containing: tuple[float, float, float, float],
) -> bool:
    return (
        bounds[0] < containing[0] - 1e-6
        or bounds[1] < containing[1] - 1e-6
        or bounds[2] > containing[2] + 1e-6
        or bounds[3] > containing[3] + 1e-6
    )


def _geometry_conflicts_with_polygon(
    geometry,
    geometry_bounds: tuple[float, float, float, float],
    polygon,
    polygon_bounds: tuple[float, float, float, float],
    clearance: float,
) -> bool:
    if not _boxes_overlap(geometry_bounds, polygon_bounds, clearance):
        return False
    if geometry is not None and polygon is not None:
        return geometry.intersects(polygon) or geometry.distance(polygon) <= clearance + 1e-6
    return True


def _geometry_conflicts_with_zone(
    geometry,
    geometry_bounds: tuple[float, float, float, float],
    zone: dict[str, Any],
    clearance: float,
) -> bool:
    zone_bounds = (
        zone["x_mm"],
        zone["y_mm"],
        zone["x_mm"] + zone["width_mm"],
        zone["y_mm"] + zone["height_mm"],
    )
    if not _boxes_overlap(geometry_bounds, zone_bounds, clearance):
        return False
    if geometry is not None and box is not None:
        zone_polygon = _zone_polygon(zone)
        return geometry.intersects(zone_polygon) or geometry.distance(zone_polygon) <= clearance + 1e-6
    return True


def _geometry_inside_remnant(
    geometry,
    geometry_bounds: tuple[float, float, float, float],
    remnant_area,
    remnants: list[dict[str, Any]],
) -> bool:
    if geometry is not None and remnant_area is not None:
        return remnant_area.buffer(1e-6).covers(geometry)
    return any(_box_contains_zone(zone, geometry_bounds) for zone in remnants)


def _zone_union(zones: list[dict[str, Any]]):
    if box is None or unary_union is None or not zones:
        return None
    return unary_union([_zone_polygon(zone) for zone in zones]).buffer(0)


def _zone_polygon(zone: dict[str, Any]):
    return box(zone["x_mm"], zone["y_mm"], zone["x_mm"] + zone["width_mm"], zone["y_mm"] + zone["height_mm"])


def _part_intersects_zone(part_polygon, part_box: tuple[float, float, float, float], zone: dict[str, Any]) -> bool:
    zone_box = (
        zone["x_mm"],
        zone["y_mm"],
        zone["x_mm"] + zone["width_mm"],
        zone["y_mm"] + zone["height_mm"],
    )
    if not _boxes_overlap(part_box, zone_box, 0.0):
        return False
    if part_polygon is None or box is None:
        return True
    return part_polygon.intersects(_zone_polygon(zone))


def _part_inside_remnant(part_polygon, part_box: tuple[float, float, float, float], remnant_area, remnants: list[dict[str, Any]]) -> bool:
    if part_polygon is not None and remnant_area is not None:
        return remnant_area.covers(part_polygon)
    return any(_box_contains_zone(zone, part_box) for zone in remnants)


def _box_contains_zone(zone: dict[str, Any], part_box: tuple[float, float, float, float]) -> bool:
    return (
        part_box[0] >= zone["x_mm"] - 1e-6
        and part_box[1] >= zone["y_mm"] - 1e-6
        and part_box[2] <= zone["x_mm"] + zone["width_mm"] + 1e-6
        and part_box[3] <= zone["y_mm"] + zone["height_mm"] + 1e-6
    )


def _boxes_overlap(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
    clearance: float,
) -> bool:
    return not (
        left[2] + clearance <= right[0]
        or right[2] + clearance <= left[0]
        or left[3] + clearance <= right[1]
        or right[3] + clearance <= left[1]
    )


def _travel_bounds(sheet: Sheet) -> tuple[float, float, float, float]:
    return (sheet.margin, sheet.margin, sheet.width - sheet.margin, sheet.height - sheet.margin)


def _physical_sheet_bounds(sheet: Sheet) -> tuple[float, float, float, float]:
    return (0.0, 0.0, sheet.width, sheet.height)


def _travel_obstacles_from_project(project: dict[str, Any]) -> list[TravelObstacle]:
    obstacles = []
    for zone in _enabled_zones(project):
        if zone["type"] == "remnant":
            continue
        obstacles.append(
            TravelObstacle(
                zone["x_mm"],
                zone["y_mm"],
                zone["x_mm"] + zone["width_mm"],
                zone["y_mm"] + zone["height_mm"],
                str(zone.get("name", zone.get("id", zone["type"]))),
            )
        )
    return obstacles


def _tabs_from_project(project: dict[str, Any]) -> list[CutTab]:
    tabs = []
    for item in project.get("tabs", []) or []:
        contour_name = str(item.get("contour_name", ""))
        if not contour_name:
            continue
        tabs.append(
            CutTab(
                contour_name=contour_name,
                x=float(item.get("x_mm", item.get("x", 0.0))),
                y=float(item.get("y_mm", item.get("y", 0.0))),
                length=float(item.get("length_mm", item.get("length", 8.0))),
            )
        )
    return tabs


def _lead_overrides_from_project(project: dict[str, Any]) -> list[LeadOverride]:
    overrides = []
    for item in project.get("lead_overrides", []) or []:
        contour_name = str(item.get("contour_name", ""))
        if not contour_name:
            continue
        overrides.append(
            LeadOverride(
                contour_name=contour_name,
                start_x=_optional_float(item.get("start_x_mm", item.get("start_x"))),
                start_y=_optional_float(item.get("start_y_mm", item.get("start_y"))),
                pierce_x=_optional_float(item.get("pierce_x_mm", item.get("pierce_x"))),
                pierce_y=_optional_float(item.get("pierce_y_mm", item.get("pierce_y"))),
                lead_in_mode=str(item["lead_in_mode"]) if item.get("lead_in_mode") is not None else None,
                lead_in=_optional_float(item.get("lead_in_mm", item.get("lead_in"))),
                lead_out=_optional_float(item.get("lead_out_mm", item.get("lead_out"))),
            )
        )
    return overrides


def _optional_float(value) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _import_issue_items(project: dict[str, Any], *, blocking_only: bool = False) -> list[dict[str, Any]]:
    if blocking_only:
        return []
    items = []
    open_path_centerline = _open_path_centerline_enabled(project)
    for issue in project.get("import", {}).get("issues", []) or []:
        code = str(issue.get("code", "import_issue"))
        message = str(issue.get("message", "DXF import issue"))
        if code == "open_contour" and open_path_centerline:
            message = f"{message}; exporting as centerline open cut"
        item: dict[str, Any] = {
            "code": f"import_{code}",
            "message": message,
            "instance_id": None,
            "blocking": False,
            "review_required": False,
        }
        for key in (
            "entity_type",
            "x",
            "y",
            "target_x",
            "target_y",
            "gap_mm",
            "chain_length_mm",
            "sheet_x",
            "sheet_y",
            "target_sheet_x",
            "target_sheet_y",
        ):
            if issue.get(key) is not None:
                item[key] = issue[key]
        items.append(item)
    return items


def _open_path_centerline_enabled(project: dict[str, Any]) -> bool:
    post = project.get("post", {}) or {}
    return str(post.get("open_path_mode", "centerline")) == "centerline"


def _assert_import_safe(project: dict[str, Any]) -> None:
    issues = _import_issue_items(project, blocking_only=True)
    if not issues:
        return
    messages = "; ".join(item["message"] or "" for item in issues[:5])
    if len(issues) > 5:
        messages += f"; and {len(issues) - 5} more import issues"
    raise ValueError(f"Project has unresolved DXF import issues: {messages}")
