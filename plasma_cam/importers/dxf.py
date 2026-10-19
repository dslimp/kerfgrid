"""ASCII DXF import for standalone plasma nesting."""

from __future__ import annotations

import math
import io
import os
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

try:
    from shapely.geometry import Polygon as ShapelyPolygon
    from shapely.validation import explain_validity as shapely_explain_validity
except ModuleNotFoundError:
    ShapelyPolygon = None
    shapely_explain_validity = None

from ..model import ArcSegment, CircleContour, Contour, LineSegment, PathContour, Point, bbox_for_contours, contour_area, contour_centroid


SUPPORTED_ENTITIES = (
    "LINE",
    "ARC",
    "CIRCLE",
    "ELLIPSE",
    "LWPOLYLINE",
    "POLYLINE",
    "SPLINE",
    "SOLID",
    "TRACE",
    "3DFACE",
    "HATCH",
    "MPOLYGON",
    "REGION",
    "INSERT",
    "MINSERT",
)
RECOGNIZED_NON_CUT_ENTITIES = (
    "ACAD_TABLE",
    "ARCALIGNEDTEXT",
    "CAMERA",
    "COORDINATIONMODEL",
    "POINT",
    "SHAPE",
    "SECTION",
    "SEQEND",
    "SUN",
    "TABLE",
    "TEXT",
    "MTEXT",
    "ATTRIB",
    "ATTDEF",
    "DIMENSION",
    "LEADER",
    "MLEADER",
    "MLEADERSTYLE",
    "MULTILEADER",
    "TOLERANCE",
    "XLINE",
    "RAY",
    "VIEWPORT",
    "GEOPOSITIONMARKER",
    "IMAGE",
    "LIGHT",
    "OLEFRAME",
    "WIPEOUT",
    "OLE2FRAME",
    "UNDERLAY",
    "PDFUNDERLAY",
    "DGNUNDERLAY",
    "DWFUNDERLAY",
    "VERTEX",
)
BLOCKING_NON_CONTOUR_ENTITIES = (
    "3DSOLID",
    "ACAD_PROXY_ENTITY",
    "BODY",
    "HELIX",
    "MESH",
    "MLINE",
    "SURFACE",
)
LOOSE_SEGMENT_ENTITIES = "LINE/ARC/ELLIPSE/SPLINE/LWPOLYLINE/POLYLINE/HATCH"
LAYER_PROCESSES = ("cut", "ignore", "construction", "mark")
UNSAFE_ENTITY_POLICIES = ("block", "warn")
LAYER_PROCESS_ALIASES = {
    "CUT": "cut",
    "CUTTING": "cut",
    "PROFILE": "cut",
    "OUTER": "cut",
    "HOLE": "cut",
    "IGNORE": "ignore",
    "IGNORED": "ignore",
    "SKIP": "ignore",
    "OFF": "ignore",
    "NO_CUT": "ignore",
    "NOCUT": "ignore",
    "CONSTRUCTION": "construction",
    "CONSTRUCT": "construction",
    "REFERENCE": "construction",
    "CENTER": "construction",
    "CENTERLINE": "construction",
    "DIM": "construction",
    "DIMENSION": "construction",
    "TEXT": "construction",
    "HIDDEN": "construction",
    "MARK": "mark",
    "MARKING": "mark",
    "ETCH": "mark",
    "ETCHING": "mark",
    "BEND": "mark",
    "SCRIBE": "mark",
}
LAYER_NAME_HEURISTICS = (
    ("IGNORE", "ignore"),
    ("CONSTRUCTION", "construction"),
    ("CENTER", "construction"),
    ("CENTERLINE", "construction"),
    ("DIM", "construction"),
    ("DIMENSION", "construction"),
    ("REFERENCE", "construction"),
    ("TEXT", "construction"),
    ("HIDDEN", "construction"),
    ("MARK", "mark"),
    ("ETCH", "mark"),
    ("BEND", "mark"),
)
CHAIN_TOLERANCE_MM = 1e-6
MIN_CONTOUR_AREA_MM2 = 0.01
TINY_SEGMENT_MM = 0.05
MICRO_COLLINEAR_OVERLAP_WARN_MM = 0.5
GAP_SUGGESTION_MM = 1.0
ELLIPSE_CHORD_MM = 2.0
SPLINE_CHORD_MM = 1.0
SPLINE_MAX_STEPS = 160
ISSUE_DISPLAY_LIMIT_PER_CODE = 50
ISSUE_DISPLAY_LIMIT_TOTAL = 500
BBOX_INDEX_MIN_CONTOURS = 128
BBOX_INDEX_MAX_CELLS_PER_CONTOUR = 256
GRAPH_CYCLE_EXTRACTION_MAX_SEGMENTS = 3000
INITIAL_PLACEMENT_EXTRA_CLEARANCE_MM = 0.1
SHAPELY_INVALIDITY_POINT_RE = re.compile(r"\[([-+0-9.eE]+)\s+([-+0-9.eE]+)\]")


@dataclass(frozen=True)
class DxfUnits:
    code: int
    name: str
    scale_to_mm: float
    detected: bool


@dataclass(frozen=True)
class ParsedDxf:
    contours: tuple[Contour, ...]
    entity_counts: dict[str, int]
    units: DxfUnits
    issues: tuple["DxfImportIssue", ...] = ()


@dataclass(frozen=True)
class DxfImportIssue:
    code: str
    message: str
    entity_type: str | None = None
    x: float | None = None
    y: float | None = None
    target_x: float | None = None
    target_y: float | None = None
    gap_mm: float | None = None
    chain_length_mm: float | None = None
    layer: str | None = None
    process: str | None = None
    blocking: bool = True


@dataclass(frozen=True)
class DxfBlock:
    name: str
    base: Point
    entities: tuple[tuple[str, list[tuple[str, str]]], ...]


@dataclass(frozen=True)
class DxfPartGroup:
    name: str
    contours: tuple[Contour, ...]
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True)
class DxfTransform:
    a: float = 1.0
    b: float = 0.0
    c: float = 0.0
    d: float = 1.0
    e: float = 0.0
    f: float = 0.0

    @staticmethod
    def identity() -> "DxfTransform":
        return DxfTransform()

    @staticmethod
    def translation(dx: float, dy: float) -> "DxfTransform":
        return DxfTransform(e=dx, f=dy)

    @staticmethod
    def insert(dx: float, dy: float, scale_x: float, scale_y: float, rotation_deg: float) -> "DxfTransform":
        radians = math.radians(rotation_deg)
        cos_a = math.cos(radians)
        sin_a = math.sin(radians)
        return DxfTransform(
            a=cos_a * scale_x,
            b=-sin_a * scale_y,
            c=sin_a * scale_x,
            d=cos_a * scale_y,
            e=dx,
            f=dy,
        )

    def apply_point(self, point: Point) -> Point:
        return Point(
            self.a * point.x + self.b * point.y + self.e,
            self.c * point.x + self.d * point.y + self.f,
        )

    def compose(self, other: "DxfTransform") -> "DxfTransform":
        return DxfTransform(
            a=self.a * other.a + self.b * other.c,
            b=self.a * other.b + self.b * other.d,
            c=self.c * other.a + self.d * other.c,
            d=self.c * other.b + self.d * other.d,
            e=self.a * other.e + self.b * other.f + self.e,
            f=self.c * other.e + self.d * other.f + self.f,
        )

    def is_identity(self) -> bool:
        return (
            abs(self.a - 1.0) <= 1e-12
            and abs(self.b) <= 1e-12
            and abs(self.c) <= 1e-12
            and abs(self.d - 1.0) <= 1e-12
            and abs(self.e) <= 1e-12
            and abs(self.f) <= 1e-12
        )


UNIT_SCALE = {
    0: ("unitless_mm_assumed", 1.0),
    1: ("inch", 25.4),
    2: ("foot", 304.8),
    3: ("mile", 1_609_344.0),
    4: ("mm", 1.0),
    5: ("cm", 10.0),
    6: ("m", 1000.0),
    7: ("km", 1_000_000.0),
    8: ("microinch", 25.4e-6),
    9: ("mil", 0.0254),
    10: ("yard", 914.4),
    11: ("angstrom", 1e-7),
    12: ("nanometer", 1e-6),
    13: ("micron", 1e-3),
    14: ("dm", 100.0),
    15: ("dam", 10_000.0),
    16: ("hm", 100_000.0),
    17: ("gigameter", 1_000_000_000_000.0),
    18: ("astronomical_unit", 149_597_870_700_000.0),
    19: ("light_year", 9.4607304725808e18),
    20: ("parsec", 3.0856775814913673e19),
    21: ("us_survey_foot", 1200.0 / 3937.0 * 1000.0),
    22: ("us_survey_inch", 1200.0 / 3937.0 * 1000.0 / 12.0),
    23: ("us_survey_yard", 1200.0 / 3937.0 * 1000.0 * 3.0),
    24: ("us_survey_mile", 1200.0 / 3937.0 * 1000.0 * 5280.0),
}


def import_dxf_circles(
    content: str,
    *,
    name: str = "imported_part",
    sheet: dict[str, Any] | None = None,
    cut: dict[str, Any] | None = None,
    post: dict[str, Any] | None = None,
    spacing_mm: float = 5.0,
    auto_close_gaps: bool = False,
    import_options: dict[str, Any] | None = None,
    layer_mapping: dict[str, Any] | None = None,
) -> dict[str, Any]:
    import_options = import_options if isinstance(import_options, dict) else {}
    resolved_auto_close_gaps = bool(import_options.get("auto_close_gaps", auto_close_gaps))
    repair_geometry = bool(import_options.get("repair_geometry", False))
    unsafe_entity_policy = _normalize_unsafe_entity_policy(import_options.get("unsafe_entity_policy", "block"))
    include_issue_sheet_points = bool(import_options.get("include_issue_sheet_points", True))
    resolved_layer_mapping = _normalize_layer_mapping(
        layer_mapping
        if layer_mapping is not None
        else import_options.get("layer_mapping", import_options.get("layers"))
    )
    parsed = parse_dxf(
        content,
        strict=False,
        auto_close_gaps=resolved_auto_close_gaps,
        repair_geometry=repair_geometry,
        layer_mapping=resolved_layer_mapping,
        unsafe_entity_policy=unsafe_entity_policy,
    )
    contours = parsed.contours
    issues = tuple(parsed.issues)
    issues = (*issues, *_supplemental_open_contour_issues(contours, issues))
    issues = tuple(_issue_as_warning(issue) for issue in issues)
    if not contours:
        issues = (
            *issues,
            DxfImportIssue(
                code="no_displayable_contours",
                message="DXF import found no displayable contours; no fake diagnostic geometry was created",
                blocking=False,
            ),
        )

    sheet_data = dict(sheet or {"width_mm": 1000, "height_mm": 500})
    sheet_data.pop("margin_mm", None)
    cut_data = cut or {
        "material": "mild_steel",
        "thickness_mm": 3,
        "nozzle_mm": 0.9,
        "feed_rate_mode": "auto",
        "manual_feed_rate_mm_min": 1300,
    }
    post_data = post or {
        "lead_in_mode": "auto",
        "lead_in_mm": 5,
        "lead_out_mm": 0,
        "lead_in_min_hole_diameter_mm": 20,
        "small_hole_threshold_mm": 37,
        "small_hole_speed_percent": 65,
        "kerf_offset_fallback": "centerline",
        "open_path_mode": "centerline",
        "path_tolerance_mm": 0.1,
        "precision": 3,
    }
    part_name = _clean_part_name(name)
    groups = _part_groups_from_contours(contours, source=part_name)
    parts = [_part_from_group(group) for group in groups]
    placements = _initial_placements_for_groups(groups, sheet_data, spacing_mm)
    blocking_issue_count = 0
    has_default_cuttable_part = bool(parts)
    issue_counts = Counter(issue.code for issue in issues)
    issue_items = _issues_to_json(issues, groups, placements, include_sheet_points=include_issue_sheet_points)

    return {
        "format": "kerfgrid-project",
        "format_version": 2,
        "name": part_name,
        "sheet": sheet_data,
        "spacing_mm": spacing_mm,
        "cut": cut_data,
        "post": post_data,
        "parts": parts,
        "placements": placements,
        "import": {
            "source": "dxf",
            "supported_entities": list(SUPPORTED_ENTITIES),
            "entity_counts": parsed.entity_counts,
            "circle_count": parsed.entity_counts.get("CIRCLE", 0),
            "contour_count": sum(len(group.contours) for group in groups),
            "part_count": len(groups),
            "part_names": [group.name for group in groups],
            "review_marker_count": 0,
            "review_only_part_count": 0,
            "auto_close_gaps": bool(resolved_auto_close_gaps),
            "repair_geometry": repair_geometry,
            "layer_mapping": resolved_layer_mapping,
            "unsafe_entity_policy": unsafe_entity_policy,
            "safe_for_export": has_default_cuttable_part,
            "partial": bool(issues),
            "issue_count": len(issues),
            "issue_counts": dict(sorted(issue_counts.items())),
            "issue_display_limit_reached": len(issue_items) < len(issues),
            "blocking_issue_count": blocking_issue_count,
            "warning_count": sum(1 for issue in issues if not issue.blocking),
            "issues": issue_items,
            "units": {
                "code": parsed.units.code,
                "name": parsed.units.name,
                "scale_to_mm": parsed.units.scale_to_mm,
                "detected": parsed.units.detected,
            },
        },
        "simulation": {
            "playback_rate": 20,
            "rapid_rate_mm_min": 8000,
        },
    }


def import_dxf_circles_file(path: str | Path, **kwargs) -> dict[str, Any]:
    file_path = Path(path)
    return import_dxf_circles(
        file_path.read_text(encoding="utf-8", errors="ignore"),
        name=file_path.stem,
        **kwargs,
    )


def _issue_as_warning(issue: DxfImportIssue) -> DxfImportIssue:
    if issue.blocking is False:
        return issue
    return replace(issue, blocking=False)


def parse_dxf(
    content: str,
    *,
    strict: bool = True,
    auto_close_gaps: bool = False,
    repair_geometry: bool = False,
    keep_open_contours: bool = True,
    layer_mapping: dict[str, Any] | None = None,
    unsafe_entity_policy: str = "block",
) -> ParsedDxf:
    pairs = _group_pairs(content)
    units = _detect_units(pairs)
    blocks = _block_definitions(pairs, units.scale_to_mm)
    normalized_layer_mapping = _normalize_layer_mapping(layer_mapping)
    normalized_unsafe_entity_policy = _normalize_unsafe_entity_policy(unsafe_entity_policy)
    contours: list[Contour] = []
    loose_segments: list[LineSegment | ArcSegment] = []
    issues: list[DxfImportIssue] = []
    region_acis_data = _decoded_region_acis_data_by_handle(content) if "REGION" in content else {}
    entity_counts = {
        name: 0
        for name in (
            *SUPPORTED_ENTITIES,
            *RECOGNIZED_NON_CUT_ENTITIES,
            *BLOCKING_NON_CONTOUR_ENTITIES,
        )
    }

    _parse_entity_blocks(
        _entity_blocks(pairs),
        scale=units.scale_to_mm,
        blocks=blocks,
        contours=contours,
        loose_segments=loose_segments,
        entity_counts=entity_counts,
        issues=issues,
        strict=strict,
        repair_geometry=repair_geometry,
        transform=DxfTransform.identity(),
        layer_mapping=normalized_layer_mapping,
        unsafe_entity_policy=normalized_unsafe_entity_policy,
        region_acis_data=region_acis_data,
        inherited_layer=None,
    )

    if strict and issues:
        raise ValueError("; ".join(issue.message for issue in issues))

    parsed_loose_segments = (
        _repair_unordered_segments(loose_segments, issues, LOOSE_SEGMENT_ENTITIES)
        if repair_geometry
        else list(loose_segments)
    )
    contours.extend(
        _chain_segments(
            parsed_loose_segments,
            start_index=len(contours) + 1,
            issues=issues,
            strict=strict,
            auto_close_gaps=auto_close_gaps,
            repair_geometry=repair_geometry,
            keep_open_contours=keep_open_contours,
        )
    )
    _detect_contour_issues(contours, issues, strict=strict)
    return ParsedDxf(contours=tuple(contours), entity_counts=entity_counts, units=units, issues=tuple(issues))


def _parse_entity_blocks(
    entity_blocks: list[tuple[str, list[tuple[str, str]]]] | tuple[tuple[str, list[tuple[str, str]]], ...],
    *,
    scale: float,
    blocks: dict[str, DxfBlock],
    contours: list[Contour],
    loose_segments: list[LineSegment | ArcSegment],
    entity_counts: dict[str, int],
    issues: list[DxfImportIssue],
    strict: bool,
    repair_geometry: bool,
    transform: DxfTransform,
    layer_mapping: dict[str, str],
    unsafe_entity_policy: str,
    region_acis_data: dict[str, tuple[str, ...]],
    inherited_layer: str | None,
    depth: int = 0,
) -> None:
    for entity_type, block in entity_blocks:
        if entity_type in entity_counts:
            entity_counts[entity_type] += 1
        layer = _effective_entity_layer(block, inherited_layer)
        process = _layer_process(layer, layer_mapping)
        if process != "cut":
            if process == "mark":
                issues.append(_mark_layer_issue(entity_type, layer))
            continue
        try:
            if entity_type == "LINE":
                loose_segments.extend(_transform_segments([_parse_line(block, scale)], transform))
            elif entity_type == "ARC":
                loose_segments.extend(_transform_segments([_parse_arc(block, scale)], transform))
            elif entity_type == "CIRCLE":
                circle = _parse_circle(block, scale, len(contours) + 1)
                contours.append(_transform_circle(circle, transform, len(contours) + 1))
            elif entity_type == "ELLIPSE":
                ellipse_segments, closed = _parse_ellipse(block, scale)
                ellipse_segments = _transform_segments(ellipse_segments, transform)
                if closed:
                    _append_path_contour(
                        contours, ellipse_segments, issues, entity_type, repair_geometry=repair_geometry
                    )
                else:
                    if repair_geometry:
                        ellipse_segments = _drop_tiny_segments(ellipse_segments, issues, entity_type)
                    loose_segments.extend(ellipse_segments)
            elif entity_type == "LWPOLYLINE":
                polyline_segments, closed = _parse_lwpolyline(block, scale)
                polyline_segments = _transform_segments(polyline_segments, transform)
                if closed:
                    _append_path_contour(
                        contours, polyline_segments, issues, entity_type, repair_geometry=repair_geometry
                    )
                else:
                    if repair_geometry:
                        polyline_segments = _drop_tiny_segments(polyline_segments, issues, entity_type)
                    loose_segments.extend(polyline_segments)
            elif entity_type == "POLYLINE":
                polyline_segments, closed = _parse_polyline(block, scale)
                polyline_segments = _transform_segments(polyline_segments, transform)
                if closed:
                    _append_path_contour(
                        contours, polyline_segments, issues, entity_type, repair_geometry=repair_geometry
                    )
                else:
                    if repair_geometry:
                        polyline_segments = _drop_tiny_segments(polyline_segments, issues, entity_type)
                    loose_segments.extend(polyline_segments)
            elif entity_type == "SPLINE":
                loose_segments.extend(_transform_segments(_parse_spline(block, scale), transform))
            elif entity_type in ("SOLID", "TRACE"):
                polygon_segments = _transform_segments(_parse_solid_or_trace(block, scale), transform)
                _append_path_contour(
                    contours, polygon_segments, issues, entity_type, repair_geometry=repair_geometry
                )
            elif entity_type == "3DFACE":
                face_segments = _transform_segments(_parse_3dface(block, scale), transform)
                _append_path_contour(contours, face_segments, issues, entity_type, repair_geometry=repair_geometry)
            elif entity_type in ("HATCH", "MPOLYGON"):
                for hatch_segments in _parse_hatch(block, scale):
                    hatch_segments = _transform_segments(hatch_segments, transform)
                    _append_path_contour(
                        contours, hatch_segments, issues, entity_type, repair_geometry=repair_geometry
                    )
            elif entity_type == "REGION":
                try:
                    region_segments = _parse_region_acis_segments(block, scale, region_acis_data)
                    if repair_geometry:
                        region_segments = _drop_tiny_segments(region_segments, issues, entity_type)
                    region_segments = _transform_segments(region_segments, transform)
                    contours.extend(
                        _chain_segments(
                            region_segments,
                            start_index=len(contours) + 1,
                            issues=issues,
                            strict=strict,
                            repair_geometry=repair_geometry,
                        )
                    )
                except Exception:
                    issues.append(_unsupported_unsafe_entity_issue(entity_type, layer, unsafe_entity_policy))
            elif entity_type in ("INSERT", "MINSERT"):
                _expand_insert(
                    block,
                    scale=scale,
                    blocks=blocks,
                    contours=contours,
                    loose_segments=loose_segments,
                    entity_counts=entity_counts,
                    issues=issues,
                    strict=strict,
                    repair_geometry=repair_geometry,
                    transform=transform,
                    layer_mapping=layer_mapping,
                    unsafe_entity_policy=unsafe_entity_policy,
                    region_acis_data=region_acis_data,
                    insert_layer=layer,
                    depth=depth,
                )
            elif entity_type in RECOGNIZED_NON_CUT_ENTITIES:
                continue
            elif entity_type in BLOCKING_NON_CONTOUR_ENTITIES:
                issues.append(_unsupported_unsafe_entity_issue(entity_type, layer, unsafe_entity_policy))
            else:
                issues.append(
                    DxfImportIssue(
                        code="unsupported_entity",
                        message=f"Unsupported DXF entity skipped: {entity_type}",
                        entity_type=entity_type,
                    )
                )
        except Exception as exc:
            issue = DxfImportIssue(
                code="entity_parse_error",
                message=f"{entity_type} parse error: {exc}",
                entity_type=entity_type,
            )
            if strict:
                raise ValueError(issue.message) from exc
            issues.append(issue)


def _expand_insert(
    block: list[tuple[str, str]],
    *,
    scale: float,
    blocks: dict[str, DxfBlock],
    contours: list[Contour],
    loose_segments: list[LineSegment | ArcSegment],
    entity_counts: dict[str, int],
    issues: list[DxfImportIssue],
    strict: bool,
    repair_geometry: bool,
    transform: DxfTransform,
    layer_mapping: dict[str, str],
    unsafe_entity_policy: str,
    region_acis_data: dict[str, tuple[str, ...]],
    insert_layer: str,
    depth: int,
) -> None:
    if depth >= 16:
        issue = DxfImportIssue(
            code="insert_recursion",
            message="INSERT nesting is too deep",
            entity_type="INSERT",
        )
        if strict:
            raise ValueError(issue.message)
        issues.append(issue)
        return

    block_name = _text_value(block, "2")
    definition = _find_block(blocks, block_name)
    if definition is None:
        issue = DxfImportIssue(
            code="missing_block",
            message=f"INSERT references missing block: {block_name}",
            entity_type="INSERT",
        )
        if strict:
            raise ValueError(issue.message)
        issues.append(issue)
        return

    insert_transform = DxfTransform.insert(
        dx=_value(block, "10", default=0.0) * scale,
        dy=_value(block, "20", default=0.0) * scale,
        scale_x=_value(block, "41", default=1.0),
        scale_y=_value(block, "42", default=1.0),
        rotation_deg=_value(block, "50", default=0.0),
    )
    columns = max(1, int(_value(block, "70", default=1.0)))
    rows = max(1, int(_value(block, "71", default=1.0)))
    column_spacing = _value(block, "44", default=0.0) * scale
    row_spacing = _value(block, "45", default=0.0) * scale
    for row in range(rows):
        for column in range(columns):
            combined = (
                transform.compose(insert_transform)
                .compose(DxfTransform.translation(column * column_spacing, row * row_spacing))
                .compose(DxfTransform.translation(-definition.base.x, -definition.base.y))
            )
            _parse_entity_blocks(
                definition.entities,
                scale=scale,
                blocks=blocks,
                contours=contours,
                loose_segments=loose_segments,
                entity_counts=entity_counts,
                issues=issues,
                strict=strict,
                repair_geometry=repair_geometry,
                transform=combined,
                layer_mapping=layer_mapping,
                unsafe_entity_policy=unsafe_entity_policy,
                region_acis_data=region_acis_data,
                inherited_layer=insert_layer,
                depth=depth + 1,
            )


def _append_path_contour(
    contours: list[Contour],
    segments: list[LineSegment | ArcSegment],
    issues: list[DxfImportIssue],
    entity_type: str,
    *,
    repair_geometry: bool,
) -> None:
    repair_issues: list[DxfImportIssue] = []
    if repair_geometry:
        segments = _repair_path_segments(segments, repair_issues, entity_type)
    if not segments:
        return
    contour = PathContour(
        name=f"path_{len(contours) + 1}",
        segments=tuple(segments),
        kind="outer",
        source="dxf",
    )
    if _chain_length(contour.segments) > CHAIN_TOLERANCE_MM:
        contours.append(contour)
    issues.extend(repair_issues)


def _repair_path_segments(
    segments: list[LineSegment | ArcSegment],
    issues: list[DxfImportIssue],
    entity_type: str,
) -> list[LineSegment | ArcSegment]:
    output = _repair_path_backtracks(segments, issues, entity_type)
    output = _repair_path_collinear_retrace_spikes(output, issues, entity_type)
    output = _repair_path_backtracks(output, issues, entity_type)
    return output


def _repair_path_backtracks(
    segments: list[LineSegment | ArcSegment],
    issues: list[DxfImportIssue],
    entity_type: str,
) -> list[LineSegment | ArcSegment]:
    output = list(segments)
    while len(output) >= 2:
        repaired = False
        for index in range(len(output)):
            next_index = (index + 1) % len(output)
            if next_index == index:
                continue
            first = output[index]
            second = output[next_index]
            if not _segments_are_opposite_lines(first, second):
                continue
            point = _segment_midpoint(first)
            issues.append(
                DxfImportIssue(
                    code="backtrack_segment_repaired",
                    message=f"Backtracking DXF path spur removed near X{point.x:.3f} Y{point.y:.3f}",
                    entity_type=entity_type,
                    x=round(point.x, 6),
                    y=round(point.y, 6),
                    blocking=False,
                )
            )
            if next_index > index:
                output.pop(next_index)
                output.pop(index)
            else:
                output.pop(index)
                output.pop(0)
            repaired = True
            break
        if not repaired:
            break
    return output


def _repair_path_collinear_retrace_spikes(
    segments: list[LineSegment | ArcSegment],
    issues: list[DxfImportIssue],
    entity_type: str,
) -> list[LineSegment | ArcSegment]:
    output = list(segments)
    while len(output) >= 4:
        repaired = False
        for index in range(len(output) - 2):
            span = _collinear_retrace_spike_span(output, index)
            if span is None:
                continue
            start_index, end_index = span
            candidate = output[:start_index] + output[end_index + 1 :]
            if not _path_repair_preserves_shape(output, candidate):
                continue
            first = output[start_index]
            point = _segment_midpoint(first)
            issues.append(
                DxfImportIssue(
                    code="collinear_overlap_repaired",
                    message=f"Collinear retrace DXF path spike removed near X{point.x:.3f} Y{point.y:.3f}",
                    entity_type=entity_type,
                    x=round(point.x, 6),
                    y=round(point.y, 6),
                    blocking=False,
                )
            )
            output = candidate
            repaired = True
            break
        if not repaired:
            break
    return output


def _collinear_retrace_spike_span(
    segments: list[LineSegment | ArcSegment],
    index: int,
) -> tuple[int, int] | None:
    first = segments[index]
    if not isinstance(first, LineSegment):
        return None
    base_length = _segment_length(first)
    if base_length <= CHAIN_TOLERANCE_MM:
        return None
    current = first.end
    for end_index in range(index + 1, len(segments)):
        segment = segments[end_index]
        if not isinstance(segment, LineSegment):
            return None
        if not segment.start.almost_equals(current, tolerance=CHAIN_TOLERANCE_MM):
            return None
        if not _line_segment_retraces_base(first, segment):
            return None
        current = segment.end
        if current.almost_equals(first.start, tolerance=CHAIN_TOLERANCE_MM):
            return index, end_index
        if _line_projection_parameter(first, current) < -CHAIN_TOLERANCE_MM / base_length:
            return None
    return None


def _line_segment_retraces_base(base: LineSegment, segment: LineSegment) -> bool:
    if not _line_segment_is_collinear_with_base(base, segment):
        return False
    bx = base.end.x - base.start.x
    by = base.end.y - base.start.y
    sx = segment.end.x - segment.start.x
    sy = segment.end.y - segment.start.y
    if bx * sx + by * sy >= 0:
        return False
    tolerance = CHAIN_TOLERANCE_MM / max(_segment_length(base), CHAIN_TOLERANCE_MM)
    start_t = _line_projection_parameter(base, segment.start)
    end_t = _line_projection_parameter(base, segment.end)
    return -tolerance <= start_t <= 1.0 + tolerance and -tolerance <= end_t <= 1.0 + tolerance


def _line_segment_is_collinear_with_base(base: LineSegment, segment: LineSegment) -> bool:
    bx = base.end.x - base.start.x
    by = base.end.y - base.start.y
    length = math.hypot(bx, by)
    if length <= 1e-9:
        return False
    for point in (segment.start, segment.end):
        if abs(bx * (point.y - base.start.y) - by * (point.x - base.start.x)) > CHAIN_TOLERANCE_MM * length:
            return False
    return True


def _line_projection_parameter(base: LineSegment, point: Point) -> float:
    bx = base.end.x - base.start.x
    by = base.end.y - base.start.y
    length_sq = bx * bx + by * by
    if length_sq <= 1e-12:
        return 0.0
    return ((point.x - base.start.x) * bx + (point.y - base.start.y) * by) / length_sq


def _path_repair_preserves_shape(
    original_segments: list[LineSegment | ArcSegment],
    candidate_segments: list[LineSegment | ArcSegment],
) -> bool:
    if len(candidate_segments) < 3:
        return False
    if not _segments_form_contiguous_closed_path(candidate_segments):
        return False
    original = PathContour("repair_original", tuple(original_segments), "outer", "dxf")
    candidate = PathContour("repair_candidate", tuple(candidate_segments), "outer", "dxf")
    if not original.is_closed(tolerance=CHAIN_TOLERANCE_MM) or not candidate.is_closed(tolerance=CHAIN_TOLERANCE_MM):
        return False
    if not _bbox_almost_equal(original.bbox(), candidate.bbox()):
        return False
    area_tolerance = max(0.05, abs(contour_area(original)) * 1e-6)
    if abs(contour_area(original) - contour_area(candidate)) > area_tolerance:
        return False
    if _self_intersection_issue(original) is None and _self_intersection_issue(candidate) is not None:
        return False
    return _collinear_overlap_pair_count(candidate_segments) < _collinear_overlap_pair_count(original_segments)


def _segments_form_contiguous_closed_path(segments: list[LineSegment | ArcSegment]) -> bool:
    if not segments:
        return False
    for first, second in zip(segments, segments[1:]):
        if not first.end.almost_equals(second.start, tolerance=CHAIN_TOLERANCE_MM):
            return False
    return segments[-1].end.almost_equals(segments[0].start, tolerance=CHAIN_TOLERANCE_MM)


def _bbox_almost_equal(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> bool:
    return _bbox_almost_equal_with_tolerance(first, second, tolerance=CHAIN_TOLERANCE_MM)


def _bbox_almost_equal_with_tolerance(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
    *,
    tolerance: float,
) -> bool:
    return all(abs(a - b) <= tolerance for a, b in zip(first, second))


def _points_bbox(points: list[Point]) -> tuple[float, float, float, float]:
    return (
        min(point.x for point in points),
        min(point.y for point in points),
        max(point.x for point in points),
        max(point.y for point in points),
    )


def _collinear_overlap_pair_count(
    segments: list[LineSegment | ArcSegment],
    *,
    limit: int = 10_000,
) -> int:
    line_segments = [(index, segment) for index, segment in enumerate(segments) if isinstance(segment, LineSegment)]
    compared: set[tuple[int, int]] = set()
    count = 0
    for group in _line_overlap_candidate_groups(line_segments):
        for first_pos, first_item in enumerate(group):
            first_index = first_item[2]
            first = first_item[3]
            first_end = first_item[1]
            for second_item in group[first_pos + 1 :]:
                if second_item[0] > first_end + CHAIN_TOLERANCE_MM:
                    break
                second_index = second_item[2]
                pair_key = (min(first_index, second_index), max(first_index, second_index))
                if pair_key in compared:
                    continue
                compared.add(pair_key)
                overlap = _line_collinear_overlap(first, second_item[3])
                if overlap is None:
                    continue
                if overlap[0].distance_to(overlap[1]) <= CHAIN_TOLERANCE_MM:
                    continue
                count += 1
                if count >= limit:
                    return count
    return count


def _drop_tiny_segments(
    segments: list[LineSegment | ArcSegment],
    issues: list[DxfImportIssue],
    entity_type: str,
) -> list[LineSegment | ArcSegment]:
    output: list[LineSegment | ArcSegment] = []
    for segment in segments:
        if _segment_length(segment) <= TINY_SEGMENT_MM:
            point = _segment_midpoint(segment)
            issues.append(
                DxfImportIssue(
                    code="tiny_segment_repaired",
                    message=f"Tiny DXF segment removed near X{point.x:.3f} Y{point.y:.3f}",
                    entity_type=entity_type,
                    x=round(point.x, 6),
                    y=round(point.y, 6),
                    blocking=False,
                )
            )
            continue
        output.append(segment)
    return output


def _repair_unordered_segments(
    segments: list[LineSegment | ArcSegment],
    issues: list[DxfImportIssue],
    entity_type: str,
) -> list[LineSegment | ArcSegment]:
    compact = _drop_tiny_segments(segments, issues, entity_type)
    grouped: dict[tuple[Any, ...], list[LineSegment | ArcSegment]] = defaultdict(list)
    for segment in compact:
        grouped[_segment_key(segment)].append(segment)
    isolated_duplicate_keys = _isolated_duplicate_pair_keys(grouped)
    seen: set[tuple[Any, ...]] = set()
    reported_isolated: set[tuple[Any, ...]] = set()
    output: list[LineSegment | ArcSegment] = []
    for segment in compact:
        key = _segment_key(segment)
        if key in isolated_duplicate_keys:
            if key not in reported_isolated:
                point = _segment_midpoint(segment)
                issues.append(
                    DxfImportIssue(
                        code="duplicate_segment_repaired",
                        message=f"Degenerate duplicate DXF segment pair removed near X{point.x:.3f} Y{point.y:.3f}",
                        entity_type=entity_type,
                        x=round(point.x, 6),
                        y=round(point.y, 6),
                        blocking=False,
                    )
                )
                reported_isolated.add(key)
            continue
        if key in seen:
            point = _segment_midpoint(segment)
            issues.append(
                DxfImportIssue(
                    code="duplicate_segment_repaired",
                    message=f"Duplicate DXF segment removed near X{point.x:.3f} Y{point.y:.3f}",
                    entity_type=entity_type,
                    x=round(point.x, 6),
                    y=round(point.y, 6),
                    blocking=False,
                )
            )
            continue
        seen.add(key)
        output.append(segment)
    return output


def _isolated_duplicate_pair_keys(
    grouped: dict[tuple[Any, ...], list[LineSegment | ArcSegment]],
) -> set[tuple[Any, ...]]:
    output: set[tuple[Any, ...]] = set()
    endpoint_counts = _endpoint_connection_counts(grouped)
    for key, items in grouped.items():
        if len(items) != 2:
            continue
        first, second = items
        if not _segments_are_opposite_lines(first, second):
            continue
        endpoints = {_point_key(first.start), _point_key(first.end)}
        own_connections: dict[tuple[int, int], int] = defaultdict(int)
        for item in items:
            own_connections[_point_key(item.start)] += 1
            own_connections[_point_key(item.end)] += 1
        outside_connections = sum(endpoint_counts[endpoint] - own_connections[endpoint] for endpoint in endpoints)
        if outside_connections == 0:
            output.add(key)
    return output


def _endpoint_connection_counts(
    grouped: dict[tuple[Any, ...], list[LineSegment | ArcSegment]],
) -> dict[tuple[int, int], int]:
    counts: dict[tuple[int, int], int] = defaultdict(int)
    for items in grouped.values():
        for item in items:
            counts[_point_key(item.start)] += 1
            counts[_point_key(item.end)] += 1
    return counts


def _segments_are_opposite_lines(first: LineSegment | ArcSegment, second: LineSegment | ArcSegment) -> bool:
    return (
        isinstance(first, LineSegment)
        and isinstance(second, LineSegment)
        and first.start.almost_equals(second.end, tolerance=CHAIN_TOLERANCE_MM)
        and first.end.almost_equals(second.start, tolerance=CHAIN_TOLERANCE_MM)
    )


def _detect_contour_issues(contours: list[Contour], issues: list[DxfImportIssue], *, strict: bool) -> None:
    for contour in contours:
        if not isinstance(contour, PathContour):
            continue
        if not contour.is_closed(tolerance=CHAIN_TOLERANCE_MM):
            if contour.source != "dxf_review_open":
                issue = _open_path_contour_issue(contour)
                if strict:
                    raise ValueError(issue.message)
                issues.append(issue)
            continue
        overlap_issue = _path_collinear_overlap_issue(contour)
        if overlap_issue is not None:
            if overlap_issue.blocking and strict:
                raise ValueError(overlap_issue.message)
            issues.append(overlap_issue)
            if overlap_issue.blocking:
                edge_issue = _edge_sweep_self_intersection_issue(contour.points(max_chord=1.0))
                if edge_issue is not None:
                    issues.append(edge_issue)
                continue
        issue = _self_intersection_issue(contour)
        if issue is None:
            continue
        if strict:
            raise ValueError(issue.message)
        issues.append(issue)


def _open_path_contour_issue(contour: PathContour) -> DxfImportIssue:
    points = contour.points(max_chord=1.0)
    start = points[0] if points else Point(0.0, 0.0)
    end = points[-1] if points else Point(0.0, 0.0)
    length = _chain_length(contour.segments)
    return DxfImportIssue(
        code="open_contour",
        message=(
            f"Open DXF path contour retained for centerline cutting from X{start.x:.3f} Y{start.y:.3f} "
            f"to X{end.x:.3f} Y{end.y:.3f}"
        ),
        entity_type="PATH",
        x=round(end.x, 6),
        y=round(end.y, 6),
        target_x=round(start.x, 6),
        target_y=round(start.y, 6),
        chain_length_mm=round(length, 6),
    )


def _detect_segment_overlaps(
    segments: list[LineSegment | ArcSegment],
    issues: list[DxfImportIssue],
    entity_type: str,
    *,
    strict: bool,
) -> None:
    issue = _collinear_overlap_issue(segments, entity_type)
    if issue is None:
        return
    if strict:
        raise ValueError(issue.message)
    issues.append(issue)


def _path_collinear_overlap_issue(contour: PathContour) -> DxfImportIssue | None:
    return _collinear_overlap_issue(list(contour.segments), "PATH")


def _collinear_overlap_issue(
    segments: list[LineSegment | ArcSegment],
    entity_type: str,
) -> DxfImportIssue | None:
    line_segments = [(index, segment) for index, segment in enumerate(segments) if isinstance(segment, LineSegment)]
    compared: set[tuple[int, int]] = set()
    first_micro_issue: DxfImportIssue | None = None
    for group in _line_overlap_candidate_groups(line_segments):
        for first_pos, first_item in enumerate(group):
            first_index = first_item[2]
            first = first_item[3]
            first_end = first_item[1]
            for second_item in group[first_pos + 1 :]:
                if second_item[0] > first_end + CHAIN_TOLERANCE_MM:
                    break
                second_index = second_item[2]
                pair_key = (min(first_index, second_index), max(first_index, second_index))
                if pair_key in compared:
                    continue
                compared.add(pair_key)
                second = second_item[3]
                if entity_type != "PATH" and _segments_are_exact_duplicate_lines(first, second):
                    continue
                overlap = _line_collinear_overlap(first, second)
                if overlap is None:
                    continue
                start, end = overlap
                overlap_length = start.distance_to(end)
                if overlap_length <= CHAIN_TOLERANCE_MM:
                    continue
                if overlap_length <= MICRO_COLLINEAR_OVERLAP_WARN_MM:
                    if first_micro_issue is None:
                        first_micro_issue = DxfImportIssue(
                            code="micro_collinear_overlap",
                            message=(
                                f"Micro collinear overlapping DXF line edges from X{start.x:.3f} Y{start.y:.3f} "
                                f"to X{end.x:.3f} Y{end.y:.3f} ({overlap_length:.3f} mm); review source CAD"
                            ),
                            entity_type=entity_type,
                            x=round(start.x, 6),
                            y=round(start.y, 6),
                            target_x=round(end.x, 6),
                            target_y=round(end.y, 6),
                            blocking=False,
                        )
                    continue
                return DxfImportIssue(
                    code="collinear_overlap",
                    message=(
                        f"Collinear overlapping DXF line edges from X{start.x:.3f} Y{start.y:.3f} "
                        f"to X{end.x:.3f} Y{end.y:.3f}; remove overlapping/self-overlap geometry before export"
                    ),
                    entity_type=entity_type,
                    x=round(start.x, 6),
                    y=round(start.y, 6),
                    target_x=round(end.x, 6),
                    target_y=round(end.y, 6),
                )
    return first_micro_issue


def _line_overlap_candidate_groups(
    line_segments: list[tuple[int, LineSegment]],
) -> list[list[tuple[float, float, int, LineSegment]]]:
    groups: dict[tuple[int, int, int], list[tuple[float, float, int, LineSegment]]] = defaultdict(list)
    for index, segment in line_segments:
        axis = _line_axis_bucket(segment)
        if axis is None:
            continue
        direction_x, direction_y, offset_bucket = axis
        start_projection = segment.start.x * direction_x + segment.start.y * direction_y
        end_projection = segment.end.x * direction_x + segment.end.y * direction_y
        projection_min = min(start_projection, end_projection)
        projection_max = max(start_projection, end_projection)
        item = (projection_min, projection_max, index, segment)
        for neighbor_offset in (offset_bucket - 1, offset_bucket, offset_bucket + 1):
            groups[(round(direction_x * 1_000_000), round(direction_y * 1_000_000), neighbor_offset)].append(item)
    return [sorted(group, key=lambda item: item[0]) for group in groups.values() if len(group) > 1]


def _line_axis_bucket(segment: LineSegment) -> tuple[float, float, int] | None:
    dx = segment.end.x - segment.start.x
    dy = segment.end.y - segment.start.y
    length = math.hypot(dx, dy)
    if length <= 1e-9:
        return None
    direction_x = dx / length
    direction_y = dy / length
    if direction_x < -1e-12 or (abs(direction_x) <= 1e-12 and direction_y < 0):
        direction_x = -direction_x
        direction_y = -direction_y
    normal_x = -direction_y
    normal_y = direction_x
    offset = segment.start.x * normal_x + segment.start.y * normal_y
    return direction_x, direction_y, round(offset / CHAIN_TOLERANCE_MM)


def _segments_are_exact_duplicate_lines(first: LineSegment, second: LineSegment) -> bool:
    return (
        (first.start.almost_equals(second.start, tolerance=CHAIN_TOLERANCE_MM) and first.end.almost_equals(second.end, tolerance=CHAIN_TOLERANCE_MM))
        or (first.start.almost_equals(second.end, tolerance=CHAIN_TOLERANCE_MM) and first.end.almost_equals(second.start, tolerance=CHAIN_TOLERANCE_MM))
    )


def _line_collinear_overlap(first: LineSegment, second: LineSegment) -> tuple[Point, Point] | None:
    fx = first.end.x - first.start.x
    fy = first.end.y - first.start.y
    length_sq = fx * fx + fy * fy
    if length_sq <= 1e-12:
        return None
    sx = second.end.x - second.start.x
    sy = second.end.y - second.start.y
    if abs(fx * sy - fy * sx) > CHAIN_TOLERANCE_MM * math.sqrt(length_sq):
        return None
    if abs(fx * (second.start.y - first.start.y) - fy * (second.start.x - first.start.x)) > CHAIN_TOLERANCE_MM * math.sqrt(length_sq):
        return None
    first_start = 0.0
    first_end = 1.0
    second_start = ((second.start.x - first.start.x) * fx + (second.start.y - first.start.y) * fy) / length_sq
    second_end = ((second.end.x - first.start.x) * fx + (second.end.y - first.start.y) * fy) / length_sq
    overlap_start = max(min(first_start, first_end), min(second_start, second_end))
    overlap_end = min(max(first_start, first_end), max(second_start, second_end))
    overlap_length = (overlap_end - overlap_start) * math.sqrt(length_sq)
    if overlap_length <= CHAIN_TOLERANCE_MM:
        return None
    return (
        Point(first.start.x + fx * overlap_start, first.start.y + fy * overlap_start),
        Point(first.start.x + fx * overlap_end, first.start.y + fy * overlap_end),
    )


def _self_intersection_issue(contour: PathContour) -> DxfImportIssue | None:
    points = contour.points(max_chord=1.0)
    if len(points) < 4:
        return None
    edge_issue = _edge_sweep_self_intersection_issue(points)
    if edge_issue is not None:
        return edge_issue
    return _shapely_polygon_issue(points)


def _edge_sweep_self_intersection_issue(points: list[Point]) -> DxfImportIssue | None:
    edges = [
        (
            index,
            start,
            end,
            min(start.x, end.x),
            max(start.x, end.x),
            min(start.y, end.y),
            max(start.y, end.y),
        )
        for index, (start, end) in enumerate(zip(points, [*points[1:], points[0]]))
    ]
    sorted_edges = sorted(edges, key=lambda edge: edge[3])
    tolerance = 1e-9
    for first_position, first in enumerate(sorted_edges):
        first_index, first_start, first_end, _first_min_x, first_max_x, first_min_y, first_max_y = first
        for second in sorted_edges[first_position + 1 :]:
            second_index, second_start, second_end, second_min_x, _second_max_x, second_min_y, second_max_y = second
            if second_min_x > first_max_x + tolerance:
                break
            if second_max_y < first_min_y - tolerance or second_min_y > first_max_y + tolerance:
                continue
            if _edges_are_adjacent(first_index, second_index, len(edges)):
                continue
            point = _segment_intersection_point(first_start, first_end, second_start, second_end)
            if point is None:
                continue
            return DxfImportIssue(
                code="self_intersection",
                message=f"Self-intersecting DXF contour near X{point.x:.3f} Y{point.y:.3f}",
                entity_type="PATH",
                x=round(point.x, 6),
                y=round(point.y, 6),
            )
    return None


def _shapely_polygon_issue(points: list[Point]) -> DxfImportIssue | None:
    if ShapelyPolygon is None:
        return None
    polygon = ShapelyPolygon((point.x, point.y) for point in points)
    if polygon.is_empty or polygon.area <= MIN_CONTOUR_AREA_MM2:
        return None
    if polygon.is_valid:
        return None
    reason = shapely_explain_validity(polygon) if shapely_explain_validity is not None else "invalid polygon"
    point = _invalidity_point_from_reason(str(reason)) or _average_point(points)
    return DxfImportIssue(
        code="self_intersection",
        message=f"Self-intersecting DXF contour near X{point.x:.3f} Y{point.y:.3f}: {reason}",
        entity_type="PATH",
        x=round(point.x, 6),
        y=round(point.y, 6),
    )


def _invalidity_point_from_reason(reason: str) -> Point | None:
    match = SHAPELY_INVALIDITY_POINT_RE.search(reason)
    if match is None:
        return None
    return Point(float(match.group(1)), float(match.group(2)))


def _average_point(points: list[Point]) -> Point:
    return Point(
        sum(point.x for point in points) / len(points),
        sum(point.y for point in points) / len(points),
    )


def _edges_are_adjacent(first: int, second: int, count: int) -> bool:
    return abs(first - second) <= 1 or {first, second} == {0, count - 1}


def _segment_intersection_point(a: Point, b: Point, c: Point, d: Point) -> Point | None:
    denominator = (b.x - a.x) * (d.y - c.y) - (b.y - a.y) * (d.x - c.x)
    if abs(denominator) <= 1e-12:
        return None
    u = ((c.x - a.x) * (d.y - c.y) - (c.y - a.y) * (d.x - c.x)) / denominator
    v = ((c.x - a.x) * (b.y - a.y) - (c.y - a.y) * (b.x - a.x)) / denominator
    eps = 1e-6
    if eps < u < 1.0 - eps and eps < v < 1.0 - eps:
        return Point(a.x + u * (b.x - a.x), a.y + u * (b.y - a.y))
    return None


def _segment_length(segment: LineSegment | ArcSegment) -> float:
    points = segment.points(max_chord=1.0)
    return sum(start.distance_to(end) for start, end in zip(points, points[1:]))


def _segment_midpoint(segment: LineSegment | ArcSegment) -> Point:
    return Point((segment.start.x + segment.end.x) / 2.0, (segment.start.y + segment.end.y) / 2.0)


def _segment_key(segment: LineSegment | ArcSegment) -> tuple[Any, ...]:
    if isinstance(segment, LineSegment):
        start = _point_key(segment.start)
        end = _point_key(segment.end)
        ordered = tuple(sorted((start, end)))
        return ("line", *ordered)
    return (
        "arc",
        _point_key(segment.start),
        _point_key(segment.end),
        _point_key(segment.center),
        bool(segment.clockwise),
    )


def _point_key(point: Point) -> tuple[int, int]:
    return (round(point.x / CHAIN_TOLERANCE_MM), round(point.y / CHAIN_TOLERANCE_MM))


def _detect_units(pairs: list[tuple[str, str]]) -> DxfUnits:
    for index, (code, value) in enumerate(pairs):
        if code == "9" and value.upper() == "$INSUNITS":
            for header_code, header_value in pairs[index + 1 : index + 8]:
                if header_code == "70":
                    unit_code = int(float(header_value))
                    try:
                        name, scale = UNIT_SCALE[unit_code]
                    except KeyError as exc:
                        raise ValueError(f"Unsupported DXF INSUNITS code: {unit_code}") from exc
                    return DxfUnits(unit_code, name, scale, True)
    name, scale = UNIT_SCALE[0]
    return DxfUnits(0, name, scale, False)


def _block_definitions(pairs: list[tuple[str, str]], scale: float) -> dict[str, DxfBlock]:
    start = _section_start(pairs, "BLOCKS")
    if start is None:
        return {}

    blocks: dict[str, DxfBlock] = {}
    index = start
    while index < len(pairs):
        code, value = pairs[index]
        if code == "0" and value.upper() == "ENDSEC":
            break
        if code != "0" or value.upper() != "BLOCK":
            index += 1
            continue

        index += 1
        header: list[tuple[str, str]] = []
        while index < len(pairs) and pairs[index][0] != "0":
            header.append(pairs[index])
            index += 1

        name = _text_value(header, "2", default="")
        base = Point(
            _value(header, "10", default=0.0) * scale,
            _value(header, "20", default=0.0) * scale,
        )
        entities: list[tuple[str, list[tuple[str, str]]]] = []
        while index < len(pairs):
            code, value = pairs[index]
            if code != "0":
                index += 1
                continue
            if value.upper() == "ENDBLK":
                index += 1
                while index < len(pairs) and pairs[index][0] != "0":
                    index += 1
                break
            if value.upper() == "ENDSEC":
                break
            entity_type, entity_block, index = _read_entity_block(pairs, index)
            entities.append((entity_type, entity_block))

        if name:
            definition = DxfBlock(name=name, base=base, entities=tuple(entities))
            blocks[name] = definition
            blocks.setdefault(name.upper(), definition)
    return blocks


def _section_start(pairs: list[tuple[str, str]], name: str) -> int | None:
    section_name = name.upper()
    for index in range(len(pairs) - 1):
        if pairs[index][0] == "0" and pairs[index][1].upper() == "SECTION":
            cursor = index + 1
            while cursor < len(pairs) and pairs[cursor][0] != "0":
                if pairs[cursor][0] == "2" and pairs[cursor][1].upper() == section_name:
                    return cursor + 1
                cursor += 1
    return None


def _find_block(blocks: dict[str, DxfBlock], name: str) -> DxfBlock | None:
    return blocks.get(name) or blocks.get(name.upper())


def _entity_blocks(pairs: list[tuple[str, str]]) -> list[tuple[str, list[tuple[str, str]]]]:
    start = _section_start(pairs, "ENTITIES")
    if start is None:
        return []

    blocks: list[tuple[str, list[tuple[str, str]]]] = []
    index = start
    while index < len(pairs):
        code, value = pairs[index]
        if code != "0":
            index += 1
            continue
        entity_type = value.upper()
        if entity_type in ("ENDSEC", "EOF"):
            break
        entity_type, block, index = _read_entity_block(pairs, index)
        blocks.append((entity_type, block))
    return blocks


def _read_entity_block(pairs: list[tuple[str, str]], index: int) -> tuple[str, list[tuple[str, str]], int]:
    entity_type = pairs[index][1].upper()
    index += 1
    block: list[tuple[str, str]] = []
    while index < len(pairs) and pairs[index][0] != "0":
        block.append(pairs[index])
        index += 1
    if entity_type == "POLYLINE":
        while index < len(pairs) and pairs[index][0] == "0":
            nested_type = pairs[index][1].upper()
            if nested_type == "VERTEX":
                block.append(("0", "VERTEX"))
                index += 1
                while index < len(pairs) and pairs[index][0] != "0":
                    block.append(pairs[index])
                    index += 1
                continue
            if nested_type == "SEQEND":
                index += 1
                while index < len(pairs) and pairs[index][0] != "0":
                    index += 1
                break
            break
    return entity_type, block, index


def _transform_segments(
    segments: list[LineSegment | ArcSegment],
    transform: DxfTransform,
) -> list[LineSegment | ArcSegment]:
    if transform.is_identity():
        return list(segments)
    output: list[LineSegment | ArcSegment] = []
    for segment in segments:
        if isinstance(segment, LineSegment):
            start = transform.apply_point(segment.start)
            end = transform.apply_point(segment.end)
            if start.distance_to(end) > 1e-9:
                output.append(LineSegment(start, end))
        else:
            points = [transform.apply_point(point) for point in segment.points(max_chord=1.0)]
            output.extend(_line_segments_from_points(points, closed=False))
    return output


def _transform_circle(circle: CircleContour, transform: DxfTransform, index: int) -> Contour:
    if transform.is_identity():
        return circle
    points = [transform.apply_point(point) for point in circle.points(max_chord=1.0)]
    segments = _line_segments_from_points(points, closed=True)
    return PathContour(name=f"path_{index}", segments=tuple(segments), kind=circle.kind, source=circle.source)


def _line_segments_from_points(points: list[Point], *, closed: bool) -> list[LineSegment]:
    if len(points) < 2:
        return []
    pairs = zip(points, [*points[1:], points[0]] if closed else points[1:])
    return [LineSegment(start, end) for start, end in pairs if start.distance_to(end) > 1e-9]


def _parse_line(block: list[tuple[str, str]], scale: float) -> LineSegment:
    return LineSegment(
        start=Point(_value(block, "10") * scale, _value(block, "20") * scale),
        end=Point(_value(block, "11") * scale, _value(block, "21") * scale),
    )


def _parse_arc(block: list[tuple[str, str]], scale: float) -> ArcSegment:
    center = Point(_value(block, "10") * scale, _value(block, "20") * scale)
    radius = _value(block, "40") * scale
    start_angle = math.radians(_value(block, "50"))
    end_angle = math.radians(_value(block, "51"))
    return ArcSegment(
        start=Point(center.x + math.cos(start_angle) * radius, center.y + math.sin(start_angle) * radius),
        end=Point(center.x + math.cos(end_angle) * radius, center.y + math.sin(end_angle) * radius),
        center=center,
        clockwise=False,
    )


def _parse_circle(block: list[tuple[str, str]], scale: float, index: int) -> CircleContour:
    return CircleContour(
        name=f"circle_{index}",
        center=Point(_value(block, "10") * scale, _value(block, "20") * scale),
        radius=_value(block, "40") * scale,
        kind="outer",
        source="dxf",
    )


def _parse_solid_or_trace(block: list[tuple[str, str]], scale: float) -> list[LineSegment]:
    points = [
        _point_from_codes(block, "10", "20", scale),
        _point_from_codes(block, "11", "21", scale),
    ]
    if _has_group(block, "13") and _has_group(block, "23"):
        points.append(_point_from_codes(block, "13", "23", scale))
    points.append(_point_from_codes(block, "12", "22", scale))
    return _closed_polygon_segments(points, "SOLID/TRACE")


def _parse_3dface(block: list[tuple[str, str]], scale: float) -> list[LineSegment]:
    points = [
        _point_from_codes(block, "10", "20", scale),
        _point_from_codes(block, "11", "21", scale),
        _point_from_codes(block, "12", "22", scale),
    ]
    if _has_group(block, "13") and _has_group(block, "23"):
        points.append(_point_from_codes(block, "13", "23", scale))
    return _closed_polygon_segments(points, "3DFACE")


def _closed_polygon_segments(points: list[Point], entity_type: str) -> list[LineSegment]:
    compact: list[Point] = []
    for point in points:
        if compact and point.almost_equals(compact[-1], tolerance=1e-9):
            continue
        compact.append(point)
    if len(compact) > 1 and compact[0].almost_equals(compact[-1], tolerance=1e-9):
        compact.pop()
    if len(compact) < 3:
        raise ValueError(f"{entity_type} must contain at least three distinct vertices")
    return _line_segments_from_points(compact, closed=True)


def _parse_ellipse(block: list[tuple[str, str]], scale: float) -> tuple[list[LineSegment], bool]:
    center = Point(_value(block, "10") * scale, _value(block, "20") * scale)
    major = Point(_value(block, "11") * scale, _value(block, "21") * scale)
    ratio = _value(block, "40")
    start_param = _value(block, "41", default=0.0)
    end_param = _value(block, "42", default=math.tau)
    return _ellipse_segments_from_params(center, major, ratio, start_param, end_param, ccw=True)


def _ellipse_segments_from_params(
    center: Point,
    major: Point,
    ratio: float,
    start_param: float,
    end_param: float,
    *,
    ccw: bool,
) -> tuple[list[LineSegment], bool]:
    major_radius = math.hypot(major.x, major.y)
    if major_radius <= 1e-9:
        raise ValueError("ELLIPSE major axis is zero")
    ratio = abs(ratio)
    if ratio <= 1e-9:
        raise ValueError("ELLIPSE minor/major ratio is zero")
    minor = Point(-major.y * ratio, major.x * ratio)
    minor_radius = math.hypot(minor.x, minor.y)
    sweep = end_param - start_param
    closed = abs(sweep) <= 1e-9 or abs(abs(sweep) - math.tau) <= 1e-9 or abs(sweep) >= math.tau - 1e-9
    if closed:
        sweep = math.tau if ccw else -math.tau
    elif ccw:
        while sweep <= 0:
            sweep += math.tau
    else:
        while sweep >= 0:
            sweep -= math.tau

    circumference = math.pi * (
        3.0 * (major_radius + minor_radius)
        - math.sqrt((3.0 * major_radius + minor_radius) * (major_radius + 3.0 * minor_radius))
    )
    steps = max(16, min(720, math.ceil(abs(sweep) / math.tau * circumference / ELLIPSE_CHORD_MM)))
    point_count = steps if closed else steps + 1
    points = [
        _ellipse_point(center, major, minor, start_param + sweep * index / steps)
        for index in range(point_count)
    ]
    return _line_segments_from_points(points, closed=closed), closed


def _ellipse_point(center: Point, major: Point, minor: Point, parameter: float) -> Point:
    return Point(
        center.x + major.x * math.cos(parameter) + minor.x * math.sin(parameter),
        center.y + major.y * math.cos(parameter) + minor.y * math.sin(parameter),
    )


def _decoded_region_acis_data_by_handle(content: str) -> dict[str, tuple[str, ...]]:
    try:
        os.environ.setdefault("XDG_CACHE_HOME", str(Path(os.environ.get("TMPDIR") or "/tmp") / "ezdxf-cache"))
        import ezdxf

        doc = ezdxf.read(io.StringIO(content))
    except Exception:
        return {}
    entity_db = getattr(doc, "entitydb", None)
    values = entity_db.values() if entity_db is not None and hasattr(entity_db, "values") else ()
    output: dict[str, tuple[str, ...]] = {}
    for entity in values:
        try:
            if entity.dxftype() != "REGION":
                continue
            handle = str(entity.dxf.handle).upper()
            acis_data = tuple(str(line) for line in (entity.acis_data or ()))
        except Exception:
            continue
        if handle and acis_data:
            output[handle] = acis_data
    return output


def _parse_region_acis_segments(
    block: list[tuple[str, str]],
    scale: float,
    region_acis_data: dict[str, tuple[str, ...]],
) -> list[LineSegment]:
    handle = _text_value(block, "5", default="").upper()
    acis_data = region_acis_data.get(handle)
    if not acis_data:
        raise ValueError("REGION ACIS data is unavailable")
    segments = _segments_from_region_acis(acis_data, scale)
    if not segments:
        raise ValueError("REGION ACIS boundary contains no supported 2D edges")
    return segments


def _segments_from_region_acis(acis_data: tuple[str, ...], scale: float) -> list[LineSegment]:
    records = _sat_records(acis_data)
    matrix = _sat_body_transform(records)
    output: list[LineSegment] = []
    for record in records:
        if not record or record[0] != "edge":
            continue
        output.extend(_segments_from_sat_edge(record, records, matrix, scale))
    return [segment for segment in output if segment.start.distance_to(segment.end) > 1e-9]


def _sat_records(acis_data: tuple[str, ...]) -> list[list[str]]:
    lines = [line.strip() for line in acis_data if str(line).strip()]
    records: list[list[str]] = []
    for line in lines[3:]:
        if line == "End-of-ACIS-data":
            break
        tokens = [token for token in line.replace("#", " #").split() if token != "#"]
        if tokens:
            records.append(tokens)
    return records


def _sat_body_transform(records: list[list[str]]) -> tuple[float, ...]:
    identity = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0)
    for record in records:
        if not record or record[0] != "body":
            continue
        for token in record[1:]:
            transform_record = _sat_record_by_pointer(records, token)
            if transform_record is None or transform_record[0] != "transform":
                continue
            values: list[float] = []
            for item in transform_record[3:]:
                number = _sat_optional_float(item)
                if number is None:
                    break
                values.append(number)
                if len(values) >= 12:
                    return tuple(values[:12])
    return identity


def _segments_from_sat_edge(
    edge_record: list[str],
    records: list[list[str]],
    matrix: tuple[float, ...],
    scale: float,
) -> list[LineSegment]:
    if len(edge_record) < 10:
        raise ValueError("REGION ACIS edge record is incomplete")
    start_param = _sat_float(edge_record[5])
    end_param = _sat_float(edge_record[7])
    curve_record = _sat_record_by_pointer(records, edge_record[9])
    if curve_record is None:
        raise ValueError("REGION ACIS edge references missing curve")
    curve_type = curve_record[0]
    if curve_type == "straight-curve":
        start = _sat_curve_point(curve_record, start_param, matrix, scale)
        end = _sat_curve_point(curve_record, end_param, matrix, scale)
        return [LineSegment(start, end)] if start.distance_to(end) > 1e-9 else []
    if curve_type == "ellipse-curve":
        return _sat_ellipse_segments(curve_record, start_param, end_param, matrix, scale)
    raise ValueError(f"Unsupported REGION ACIS curve: {curve_type}")


def _sat_ellipse_segments(
    curve_record: list[str],
    start_param: float,
    end_param: float,
    matrix: tuple[float, ...],
    scale: float,
) -> list[LineSegment]:
    center, _normal, major, ratio = _sat_ellipse_components(curve_record)
    major_radius = _vector_length3(major) * scale
    minor_radius = major_radius * abs(ratio)
    sweep = end_param - start_param
    if abs(sweep) <= 1e-12:
        return []
    circumference = math.pi * (
        3.0 * (major_radius + minor_radius)
        - math.sqrt((3.0 * major_radius + minor_radius) * (major_radius + 3.0 * minor_radius))
    )
    steps = max(2, min(720, math.ceil(abs(sweep) / math.tau * circumference / ELLIPSE_CHORD_MM)))
    points = [_sat_curve_point(curve_record, start_param + sweep * index / steps, matrix, scale) for index in range(steps + 1)]
    return [LineSegment(start, end) for start, end in zip(points, points[1:]) if start.distance_to(end) > 1e-9]


def _sat_curve_point(
    curve_record: list[str],
    parameter: float,
    matrix: tuple[float, ...],
    scale: float,
) -> Point:
    curve_type = curve_record[0]
    if curve_type == "straight-curve":
        if len(curve_record) < 10:
            raise ValueError("REGION ACIS straight-curve record is incomplete")
        origin = (_sat_float(curve_record[4]), _sat_float(curve_record[5]), _sat_float(curve_record[6]))
        direction = (_sat_float(curve_record[7]), _sat_float(curve_record[8]), _sat_float(curve_record[9]))
        point = (
            origin[0] + direction[0] * parameter,
            origin[1] + direction[1] * parameter,
            origin[2] + direction[2] * parameter,
        )
        return _sat_transform_point(point, matrix, scale)
    if curve_type == "ellipse-curve":
        center, normal, major, ratio = _sat_ellipse_components(curve_record)
        minor = _vector_scale3(_vector_cross3(_vector_normalize3(normal), major), ratio)
        point = (
            center[0] + major[0] * math.cos(parameter) + minor[0] * math.sin(parameter),
            center[1] + major[1] * math.cos(parameter) + minor[1] * math.sin(parameter),
            center[2] + major[2] * math.cos(parameter) + minor[2] * math.sin(parameter),
        )
        return _sat_transform_point(point, matrix, scale)
    raise ValueError(f"Unsupported REGION ACIS curve: {curve_type}")


def _sat_ellipse_components(curve_record: list[str]) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float], float]:
    if len(curve_record) < 14:
        raise ValueError("REGION ACIS ellipse-curve record is incomplete")
    center = (_sat_float(curve_record[4]), _sat_float(curve_record[5]), _sat_float(curve_record[6]))
    normal = (_sat_float(curve_record[7]), _sat_float(curve_record[8]), _sat_float(curve_record[9]))
    major = (_sat_float(curve_record[10]), _sat_float(curve_record[11]), _sat_float(curve_record[12]))
    ratio = _sat_float(curve_record[13])
    if _vector_length3(major) <= 1e-9 or abs(ratio) <= 1e-9:
        raise ValueError("REGION ACIS ellipse-curve has zero radius")
    return center, normal, major, ratio


def _sat_transform_point(
    point: tuple[float, float, float],
    matrix: tuple[float, ...],
    scale: float,
) -> Point:
    x, y, z = point
    transformed_x = matrix[0] * x + matrix[3] * y + matrix[6] * z + matrix[9]
    transformed_y = matrix[1] * x + matrix[4] * y + matrix[7] * z + matrix[10]
    return Point(transformed_x * scale, transformed_y * scale)


def _sat_record_by_pointer(records: list[list[str]], token: str) -> list[str] | None:
    if not token.startswith("$"):
        return None
    try:
        index = int(token[1:])
    except ValueError:
        return None
    if index < 0 or index >= len(records):
        return None
    return records[index]


def _sat_float(value: str) -> float:
    number = _sat_optional_float(value)
    if number is None or not math.isfinite(number):
        raise ValueError(f"REGION ACIS numeric value expected, got {value!r}")
    return number


def _sat_optional_float(value: str) -> float | None:
    if value == "I":
        return math.inf
    if value == "-I":
        return -math.inf
    try:
        return float(value)
    except ValueError:
        return None


def _vector_cross3(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
) -> tuple[float, float, float]:
    return (
        first[1] * second[2] - first[2] * second[1],
        first[2] * second[0] - first[0] * second[2],
        first[0] * second[1] - first[1] * second[0],
    )


def _vector_scale3(vector: tuple[float, float, float], factor: float) -> tuple[float, float, float]:
    return (vector[0] * factor, vector[1] * factor, vector[2] * factor)


def _vector_length3(vector: tuple[float, float, float]) -> float:
    return math.sqrt(vector[0] * vector[0] + vector[1] * vector[1] + vector[2] * vector[2])


def _vector_normalize3(vector: tuple[float, float, float]) -> tuple[float, float, float]:
    length = _vector_length3(vector)
    if length <= 1e-12:
        raise ValueError("REGION ACIS vector has zero length")
    return (vector[0] / length, vector[1] / length, vector[2] / length)


def _parse_hatch(block: list[tuple[str, str]], scale: float) -> list[list[LineSegment | ArcSegment]]:
    loop_count = int(_value(block, "91", default=0.0))
    if loop_count <= 0:
        raise ValueError("HATCH must contain at least one boundary loop")

    loops: list[list[LineSegment | ArcSegment]] = []
    index = _first_group_index(block, "91") + 1
    parsed_loops = 0
    while parsed_loops < loop_count and index < len(block):
        while index < len(block) and block[index][0] != "92":
            index += 1
        if index >= len(block):
            break
        index += 1
        while index < len(block) and block[index][0] not in ("72", "93"):
            index += 1
        if index >= len(block):
            break
        if block[index][0] == "72":
            segments, closed, index = _parse_hatch_polyline_loop(block, index, scale)
        else:
            segments, closed, index = _parse_hatch_edge_loop(block, index, scale)
        parsed_loops += 1
        if not segments:
            continue
        if closed or _segments_form_closed_loop(segments):
            loops.append(segments)
            continue
        raise ValueError("HATCH boundary loop is open")

    if parsed_loops != loop_count:
        raise ValueError(f"HATCH expected {loop_count} boundary loops, parsed {parsed_loops}")
    if not loops:
        raise ValueError("HATCH contains no supported closed boundary loops")
    return loops


def _parse_hatch_polyline_loop(
    block: list[tuple[str, str]],
    index: int,
    scale: float,
) -> tuple[list[LineSegment | ArcSegment], bool, int]:
    has_bulges = bool(int(float(block[index][1])))
    index += 1
    closed = True
    if index < len(block) and block[index][0] == "73":
        closed = bool(int(float(block[index][1])))
        index += 1
    if index >= len(block) or block[index][0] != "93":
        raise ValueError("HATCH polyline boundary is missing vertex count")
    vertex_count = int(float(block[index][1]))
    index += 1
    vertices: list[dict[str, float]] = []
    for _ in range(vertex_count):
        while index < len(block) and block[index][0] != "10":
            index += 1
        if index >= len(block):
            raise ValueError("HATCH polyline boundary ended before all vertices")
        x = float(block[index][1]) * scale
        index += 1
        if index >= len(block) or block[index][0] != "20":
            raise ValueError("HATCH polyline vertex is missing Y coordinate")
        y = float(block[index][1]) * scale
        index += 1
        bulge = 0.0
        if has_bulges and index < len(block) and block[index][0] == "42":
            bulge = float(block[index][1])
            index += 1
        vertices.append({"x": x, "y": y, "bulge": bulge})

    return _polyline_segments_from_vertices(vertices, closed), closed, index


def _parse_hatch_edge_loop(
    block: list[tuple[str, str]],
    index: int,
    scale: float,
) -> tuple[list[LineSegment | ArcSegment], bool, int]:
    if block[index][0] != "93":
        raise ValueError("HATCH edge boundary is missing edge count")
    edge_count = int(float(block[index][1]))
    index += 1
    segments: list[LineSegment | ArcSegment] = []
    for _ in range(edge_count):
        while index < len(block) and block[index][0] != "72":
            if block[index][0] == "92":
                raise ValueError("HATCH edge boundary ended before all edges")
            index += 1
        if index >= len(block):
            raise ValueError("HATCH edge boundary ended before all edges")
        edge_type = int(float(block[index][1]))
        index += 1
        edge_block, index = _hatch_edge_block(block, index)
        segments.extend(_parse_hatch_edge(edge_type, edge_block, scale))
    return segments, _segments_form_closed_loop(segments), index


def _hatch_edge_block(
    block: list[tuple[str, str]],
    index: int,
) -> tuple[list[tuple[str, str]], int]:
    edge_block: list[tuple[str, str]] = []
    while index < len(block) and block[index][0] not in ("72", "92"):
        edge_block.append(block[index])
        index += 1
    return edge_block, index


def _parse_hatch_edge(
    edge_type: int,
    block: list[tuple[str, str]],
    scale: float,
) -> list[LineSegment | ArcSegment]:
    if edge_type == 1:
        return [_parse_hatch_line_edge(block, scale)]
    if edge_type == 2:
        return [_parse_hatch_arc_edge(block, scale)]
    if edge_type == 3:
        return _parse_hatch_ellipse_edge(block, scale)
    if edge_type == 4:
        return _parse_hatch_spline_edge(block, scale)
    raise ValueError(f"HATCH boundary edge type {edge_type} is not supported")


def _parse_hatch_line_edge(block: list[tuple[str, str]], scale: float) -> LineSegment:
    return LineSegment(
        start=Point(_value(block, "10") * scale, _value(block, "20") * scale),
        end=Point(_value(block, "11") * scale, _value(block, "21") * scale),
    )


def _parse_hatch_arc_edge(block: list[tuple[str, str]], scale: float) -> ArcSegment:
    center = Point(_value(block, "10") * scale, _value(block, "20") * scale)
    radius = _value(block, "40") * scale
    start_angle = math.radians(_value(block, "50"))
    end_angle = math.radians(_value(block, "51"))
    return ArcSegment(
        start=Point(center.x + math.cos(start_angle) * radius, center.y + math.sin(start_angle) * radius),
        end=Point(center.x + math.cos(end_angle) * radius, center.y + math.sin(end_angle) * radius),
        center=center,
        clockwise=not bool(int(_value(block, "73", default=1.0))),
    )


def _parse_hatch_ellipse_edge(block: list[tuple[str, str]], scale: float) -> list[LineSegment]:
    center = Point(_value(block, "10") * scale, _value(block, "20") * scale)
    major = Point(_value(block, "11") * scale, _value(block, "21") * scale)
    ratio = _value(block, "40")
    start_param = math.radians(_value(block, "50"))
    end_param = math.radians(_value(block, "51"))
    ccw = bool(int(_value(block, "73", default=1.0)))
    segments, _closed = _ellipse_segments_from_params(center, major, ratio, start_param, end_param, ccw=ccw)
    return segments


def _parse_hatch_spline_edge(block: list[tuple[str, str]], scale: float) -> list[LineSegment]:
    degree = int(_value(block, "94", default=3.0))
    return _parse_spline([("71", str(degree)), *block], scale)


def _segments_form_closed_loop(segments: list[LineSegment | ArcSegment]) -> bool:
    return bool(segments) and segments[0].start.almost_equals(segments[-1].end, tolerance=CHAIN_TOLERANCE_MM)


def _parse_lwpolyline(block: list[tuple[str, str]], scale: float) -> tuple[list[LineSegment | ArcSegment], bool]:
    flags = int(_value(block, "70", default=0))
    vertices: list[dict[str, float]] = []
    current: dict[str, float] | None = None
    for code, value in block:
        if code == "10":
            if current is not None and "x" in current and "y" in current:
                vertices.append(current)
            current = {"x": float(value) * scale, "y": 0.0, "bulge": 0.0}
        elif code == "20" and current is not None:
            current["y"] = float(value) * scale
        elif code == "42" and current is not None:
            current["bulge"] = float(value)
    if current is not None and "x" in current and "y" in current:
        vertices.append(current)
    if len(vertices) < 2:
        raise ValueError("LWPOLYLINE must contain at least two vertices")

    closed = bool(flags & 1)
    return _polyline_segments_from_vertices(vertices, closed), closed


def _polyline_segments_from_vertices(
    vertices: list[dict[str, float]],
    closed: bool,
) -> list[LineSegment | ArcSegment]:
    segments: list[LineSegment | ArcSegment] = []
    limit = len(vertices) if closed else len(vertices) - 1
    for index in range(limit):
        start = vertices[index]
        end = vertices[(index + 1) % len(vertices)]
        start_point = Point(start["x"], start["y"])
        end_point = Point(end["x"], end["y"])
        if start_point.almost_equals(end_point, tolerance=1e-9):
            continue
        segments.append(
            _segment_from_bulge(
                start_point,
                end_point,
                start.get("bulge", 0.0),
            )
        )
    return segments


def _parse_polyline(block: list[tuple[str, str]], scale: float) -> tuple[list[LineSegment | ArcSegment], bool]:
    header: list[tuple[str, str]] = []
    vertex_blocks: list[list[tuple[str, str]]] = []
    current: list[tuple[str, str]] | None = None
    for code, value in block:
        if code == "0" and value.upper() == "VERTEX":
            if current is not None:
                vertex_blocks.append(current)
            current = []
            continue
        if current is None:
            header.append((code, value))
        else:
            current.append((code, value))
    if current is not None:
        vertex_blocks.append(current)

    flags = int(_value(header, "70", default=0))
    if flags & 16 or flags & 64:
        raise ValueError("POLYLINE mesh/polyface is not a 2D cut contour")
    vertices = [
        {
            "x": _value(vertex, "10") * scale,
            "y": _value(vertex, "20") * scale,
            "bulge": _value(vertex, "42", default=0.0),
        }
        for vertex in vertex_blocks
    ]
    if len(vertices) < 2:
        raise ValueError("POLYLINE must contain at least two vertices")

    closed = bool(flags & 1)
    first = Point(vertices[0]["x"], vertices[0]["y"])
    last = Point(vertices[-1]["x"], vertices[-1]["y"])
    if not closed and first.almost_equals(last, tolerance=CHAIN_TOLERANCE_MM):
        closed = True
        vertices = vertices[:-1]

    return _polyline_segments_from_vertices(vertices, closed), closed


def _parse_spline(block: list[tuple[str, str]], scale: float) -> list[LineSegment]:
    return list(_parse_spline_cached(tuple(block), scale))


@lru_cache(maxsize=8192)
def _parse_spline_cached(block: tuple[tuple[str, str], ...], scale: float) -> tuple[LineSegment, ...]:
    flags = int(_value(block, "70", default=0))
    degree = int(_value(block, "71", default=3))
    knots: list[float] = []
    controls: list[Point] = []
    fits: list[Point] = []
    index = 0
    while index < len(block):
        code, value = block[index]
        if code == "40":
            knots.append(float(value))
        elif code == "10":
            x = float(value) * scale
            y = _next_group_value(block, index, "20") * scale
            controls.append(Point(x, y))
        elif code == "11":
            x = float(value) * scale
            y = _next_group_value(block, index, "21") * scale
            fits.append(Point(x, y))
        index += 1

    if len(fits) >= 2:
        points = fits
    elif len(controls) >= 2 and len(knots) >= len(controls) + degree + 1:
        points = _sample_bspline(controls, knots, degree)
    elif len(controls) >= 2:
        points = controls
    else:
        raise ValueError("SPLINE entity must contain at least two control or fit points")
    if flags & 1 and points and not points[0].almost_equals(points[-1], tolerance=CHAIN_TOLERANCE_MM):
        points = [*points, points[0]]
    return tuple(LineSegment(start, end) for start, end in zip(points, points[1:]) if start.distance_to(end) > 1e-9)


def _sample_bspline(controls: list[Point], knots: list[float], degree: int) -> list[Point]:
    start_t = knots[degree]
    end_t = knots[len(controls)]
    if end_t <= start_t:
        return controls
    control_length = sum(start.distance_to(end) for start, end in zip(controls, controls[1:]))
    steps = max(4, min(SPLINE_MAX_STEPS, math.ceil(control_length / SPLINE_CHORD_MM)))
    points = []
    for index in range(steps + 1):
        t = end_t if index == steps else start_t + (end_t - start_t) * index / steps
        points.append(_de_boor(controls, knots, degree, t))
    compact = [points[0]]
    for point in points[1:]:
        if point.distance_to(compact[-1]) > 0.05:
            compact.append(point)
    return compact


def _de_boor(controls: list[Point], knots: list[float], degree: int, t: float) -> Point:
    count = len(controls)
    span = degree
    for index in range(degree, count):
        if knots[index] <= t <= knots[index + 1]:
            span = index
            break
    if t >= knots[count]:
        span = count - 1
    work = [controls[span - degree + offset] for offset in range(degree + 1)]
    for r in range(1, degree + 1):
        for j in range(degree, r - 1, -1):
            left = knots[span - degree + j]
            right = knots[span + 1 + j - r]
            alpha = 0.0 if abs(right - left) <= 1e-12 else (t - left) / (right - left)
            work[j] = Point(
                (1.0 - alpha) * work[j - 1].x + alpha * work[j].x,
                (1.0 - alpha) * work[j - 1].y + alpha * work[j].y,
            )
    return work[degree]


def _segment_from_bulge(start: Point, end: Point, bulge: float) -> LineSegment | ArcSegment:
    if abs(bulge) <= 1e-9:
        return LineSegment(start, end)
    chord = start.distance_to(end)
    if chord <= 1e-9:
        raise ValueError("Bulge segment has zero chord length")
    theta = 4.0 * math.atan(bulge)
    radius = abs(chord / (2.0 * math.sin(theta / 2.0)))
    mid = Point((start.x + end.x) / 2.0, (start.y + end.y) / 2.0)
    left = Point(-(end.y - start.y) / chord, (end.x - start.x) / chord)
    center_offset = chord / (2.0 * math.tan(theta / 2.0))
    center = Point(mid.x + left.x * center_offset, mid.y + left.y * center_offset)
    if abs(start.distance_to(center) - radius) > 0.05:
        raise ValueError("Invalid bulge arc geometry")
    return ArcSegment(start=start, end=end, center=center, clockwise=theta < 0)


def _chain_segments(
    segments: list[LineSegment | ArcSegment],
    *,
    start_index: int,
    issues: list[DxfImportIssue] | None = None,
    strict: bool = True,
    auto_close_gaps: bool = False,
    repair_geometry: bool = False,
    keep_open_contours: bool = True,
) -> list[PathContour]:
    contours: list[PathContour] = []
    contour_index = start_index
    issues = issues if issues is not None else []
    lookup = _segment_endpoint_lookup(segments)
    gap_lookup = _segment_endpoint_lookup(segments, bucket_size=GAP_SUGGESTION_MM)
    unused = set(range(len(segments)))
    if len(unused) <= GRAPH_CYCLE_EXTRACTION_MAX_SEGMENTS:
        for cycle_indices, cycle in _extract_degree_two_cycles(segments, unused):
            repair_issues: list[DxfImportIssue] = []
            if repair_geometry:
                cycle = _repair_path_segments(cycle, repair_issues, LOOSE_SEGMENT_ENTITIES)
            unused.difference_update(cycle_indices)
            if not cycle:
                continue
            issues.extend(repair_issues)
            contour = PathContour(
                name=f"path_{contour_index}",
                segments=tuple(cycle),
                kind="outer",
                source="dxf",
            )
            if _chain_length(contour.segments) > CHAIN_TOLERANCE_MM:
                contours.append(contour)
                contour_index += 1
    while unused:
        first_index = next(iter(unused))
        unused.remove(first_index)
        chain = [segments[first_index]]
        start = chain[0].start
        while not chain[-1].end.almost_equals(start, tolerance=CHAIN_TOLERANCE_MM):
            match_index = _find_connecting_segment(segments, lookup, unused, chain[-1].end)
            if match_index is None:
                end = chain[-1].end
                gap_issue = _gap_closure_issue(end, start, segments, gap_lookup, unused)
                if gap_issue is not None and auto_close_gaps:
                    target = Point(float(gap_issue.target_x), float(gap_issue.target_y))
                    chain.append(LineSegment(end, target))
                    issues.append(_gap_closed_repaired_issue(gap_issue))
                    continue
                issue = gap_issue or DxfImportIssue(
                    code="open_contour",
                    message=(
                        f"Open DXF contour retained for centerline cutting from X{start.x:.3f} Y{start.y:.3f} "
                        f"to X{end.x:.3f} Y{end.y:.3f}"
                    ),
                    entity_type=LOOSE_SEGMENT_ENTITIES,
                    x=round(end.x, 6),
                    y=round(end.y, 6),
                    target_x=round(start.x, 6),
                    target_y=round(start.y, 6),
                    chain_length_mm=round(_chain_length(chain), 6),
                )
                if strict:
                    raise ValueError(issue.message)
                issues.append(issue)
                if keep_open_contours:
                    contour = PathContour(
                        name=f"path_{contour_index}",
                        segments=tuple(chain),
                        kind="outer",
                        source="dxf_review_open",
                    )
                    contours.append(contour)
                    contour_index += 1
                break
            segment_index, reverse = match_index
            unused.remove(segment_index)
            selected = segments[segment_index]
            chain.append(selected.reversed() if reverse else selected)
        else:
            repair_issues: list[DxfImportIssue] = []
            if repair_geometry:
                chain = _repair_path_segments(chain, repair_issues, LOOSE_SEGMENT_ENTITIES)
            if not chain:
                continue
            issues.extend(repair_issues)
            contour = PathContour(
                name=f"path_{contour_index}",
                segments=tuple(chain),
                kind="outer",
                source="dxf",
            )
            if _chain_length(contour.segments) > CHAIN_TOLERANCE_MM:
                contours.append(contour)
                contour_index += 1
            continue

        continue
    return contours


def _extract_degree_two_cycles(
    segments: list[LineSegment | ArcSegment],
    unused: set[int],
) -> list[tuple[set[int], list[LineSegment | ArcSegment]]]:
    core = set(unused)
    while True:
        degrees = _endpoint_degrees(segments, core)
        removable = {
            index
            for index in core
            if degrees[_point_key(segments[index].start)] <= 1 or degrees[_point_key(segments[index].end)] <= 1
        }
        if not removable:
            break
        core.difference_update(removable)
    if not core:
        return []
    endpoint_segments = _endpoint_segments(segments, core)
    degrees = _endpoint_degrees(segments, core)
    visited: set[int] = set()
    cycles: list[tuple[set[int], list[LineSegment | ArcSegment]]] = []
    for start_index in sorted(core):
        if start_index in visited:
            continue
        component = _segment_component(start_index, segments, endpoint_segments, core)
        visited.update(component)
        vertices = {
            key
            for index in component
            for key in (_point_key(segments[index].start), _point_key(segments[index].end))
        }
        if any(degrees[vertex] != 2 for vertex in vertices):
            continue
        cycle = _orient_cycle_component(segments, component, endpoint_segments)
        if cycle is not None:
            cycles.append((component, cycle))
    return cycles


def _endpoint_degrees(
    segments: list[LineSegment | ArcSegment],
    indices: set[int],
) -> dict[tuple[int, int], int]:
    degrees: dict[tuple[int, int], int] = defaultdict(int)
    for index in indices:
        degrees[_point_key(segments[index].start)] += 1
        degrees[_point_key(segments[index].end)] += 1
    return degrees


def _endpoint_segments(
    segments: list[LineSegment | ArcSegment],
    indices: set[int],
) -> dict[tuple[int, int], set[int]]:
    output: dict[tuple[int, int], set[int]] = defaultdict(set)
    for index in indices:
        output[_point_key(segments[index].start)].add(index)
        output[_point_key(segments[index].end)].add(index)
    return output


def _segment_component(
    start_index: int,
    segments: list[LineSegment | ArcSegment],
    endpoint_segments: dict[tuple[int, int], set[int]],
    indices: set[int],
) -> set[int]:
    component: set[int] = set()
    stack = [start_index]
    while stack:
        index = stack.pop()
        if index in component:
            continue
        component.add(index)
        for endpoint in (_point_key(segments[index].start), _point_key(segments[index].end)):
            connected = endpoint_segments[endpoint]
            stack.extend(candidate for candidate in connected if candidate in indices and candidate not in component)
    return component


def _orient_cycle_component(
    segments: list[LineSegment | ArcSegment],
    component: set[int],
    endpoint_segments: dict[tuple[int, int], set[int]],
) -> list[LineSegment | ArcSegment] | None:
    start_index = min(component)
    first = segments[start_index]
    chain: list[LineSegment | ArcSegment] = [first]
    used = {start_index}
    start_key = _point_key(first.start)
    current_key = _point_key(first.end)
    while current_key != start_key:
        candidates = [index for index in endpoint_segments[current_key] if index in component and index not in used]
        if len(candidates) != 1:
            return None
        index = candidates[0]
        segment = segments[index]
        if _point_key(segment.start) == current_key:
            oriented = segment
        elif _point_key(segment.end) == current_key:
            oriented = segment.reversed()
        else:
            return None
        chain.append(oriented)
        used.add(index)
        current_key = _point_key(oriented.end)
    if used != component:
        return None
    if not chain[-1].end.almost_equals(chain[0].start, tolerance=CHAIN_TOLERANCE_MM):
        return None
    return chain


def _gap_closed_repaired_issue(issue: DxfImportIssue) -> DxfImportIssue:
    return DxfImportIssue(
        code="gap_closed_repaired",
        message=(
            f"DXF gap auto-closed from X{issue.x:.3f} Y{issue.y:.3f} "
            f"to X{issue.target_x:.3f} Y{issue.target_y:.3f}; verify repaired geometry before cutting"
        ),
        entity_type=issue.entity_type,
        x=issue.x,
        y=issue.y,
        target_x=issue.target_x,
        target_y=issue.target_y,
        gap_mm=issue.gap_mm,
        blocking=False,
    )


def _chain_length(segments: Iterable[LineSegment | ArcSegment]) -> float:
    return sum(_segment_length(segment) for segment in segments)


def _gap_closure_issue(
    end: Point,
    start: Point,
    segments: list[LineSegment | ArcSegment],
    lookup: dict[tuple[int, int], list[tuple[int, bool]]],
    unused: set[int],
) -> DxfImportIssue | None:
    candidates: list[tuple[Point, float]] = [(start, end.distance_to(start))]
    for bucket in _nearby_point_buckets(end, bucket_size=GAP_SUGGESTION_MM):
        for index, reverse in lookup.get(bucket, []):
            if index not in unused:
                continue
            segment = segments[index]
            candidate = segment.end if reverse else segment.start
            candidates.append((candidate, end.distance_to(candidate)))
    target, distance = min(candidates, key=lambda item: item[1])
    if not (CHAIN_TOLERANCE_MM < distance <= GAP_SUGGESTION_MM):
        return None
    return DxfImportIssue(
        code="gap_closure_suggestion",
        message=(
            f"DXF contour has {distance:.3f} mm gap from X{end.x:.3f} Y{end.y:.3f} "
            f"to X{target.x:.3f} Y{target.y:.3f}; close endpoints before export"
        ),
        entity_type=LOOSE_SEGMENT_ENTITIES,
        x=round(end.x, 6),
        y=round(end.y, 6),
        target_x=round(target.x, 6),
        target_y=round(target.y, 6),
        gap_mm=round(distance, 6),
    )


def _segment_endpoint_lookup(
    segments: list[LineSegment | ArcSegment],
    *,
    bucket_size: float = CHAIN_TOLERANCE_MM,
) -> dict[tuple[int, int], list[tuple[int, bool]]]:
    lookup: dict[tuple[int, int], list[tuple[int, bool]]] = defaultdict(list)
    for index, segment in enumerate(segments):
        lookup[_point_bucket(segment.start, bucket_size=bucket_size)].append((index, False))
        lookup[_point_bucket(segment.end, bucket_size=bucket_size)].append((index, True))
    return lookup


def _find_connecting_segment(
    segments: list[LineSegment | ArcSegment],
    lookup: dict[tuple[int, int], list[tuple[int, bool]]],
    unused: set[int],
    point: Point,
) -> tuple[int, bool] | None:
    for bucket in _nearby_point_buckets(point, bucket_size=CHAIN_TOLERANCE_MM):
        for index, reverse in lookup.get(bucket, []):
            if index not in unused:
                continue
            segment = segments[index]
            candidate = segment.end if reverse else segment.start
            if candidate.almost_equals(point, tolerance=CHAIN_TOLERANCE_MM):
                return index, reverse
    return None


def _point_bucket(point: Point, *, bucket_size: float) -> tuple[int, int]:
    return (round(point.x / bucket_size), round(point.y / bucket_size))


def _nearby_point_buckets(point: Point, *, bucket_size: float) -> list[tuple[int, int]]:
    x, y = _point_bucket(point, bucket_size=bucket_size)
    return [(x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)]


def _classify_contours(contours: tuple[Contour, ...], *, source: str) -> tuple[Contour, ...]:
    classified: list[Contour] = []
    contour_info = [
        {
            "contour": contour,
            "area": abs(contour_area(contour)),
            "point": contour_centroid(contour),
            "bbox": contour.bbox(),
            "closed": _contour_is_closed(contour),
        }
        for contour in contours
    ]
    points_cache = {
        id(contour): contour.points(max_chord=1.0)
        for contour in contours
        if isinstance(contour, PathContour)
    }
    bbox_index = _build_bbox_container_index(contour_info)
    for index, info in enumerate(contour_info, start=1):
        contour = info["contour"]
        point = info["point"]
        if not info["closed"]:
            classified.append(_with_kind_and_name(contour, "outer", f"{source}_review_{index}", source))
            continue
        depth = sum(
            1
            for other_index in _bbox_container_candidate_indices(bbox_index, contour_info, point)
            if (other := contour_info[other_index]) is not info
            and other["area"] > info["area"]
            and _bbox_contains_point(other["bbox"], point)
            and _contains_point(other["contour"], point, points_cache.get(id(other["contour"])))
        )
        kind = "hole" if depth % 2 else "outer"
        classified.append(_with_kind_and_name(contour, kind, f"{source}_{kind}_{index}", source))
    return tuple(classified)


def _part_groups_from_contours(contours: tuple[Contour, ...], *, source: str) -> tuple[DxfPartGroup, ...]:
    if not contours:
        return ()
    contour_info = [
        {
            "contour": contour,
            "area": abs(contour_area(contour)),
            "point": contour_centroid(contour),
            "bbox": contour.bbox(),
            "closed": _contour_is_closed(contour),
        }
        for contour in contours
    ]
    points_cache = {
        id(contour): contour.points(max_chord=1.0)
        for contour in contours
        if isinstance(contour, PathContour)
    }
    bbox_index = _build_bbox_container_index(contour_info)
    parents: dict[int, int | None] = {}
    for index, info in enumerate(contour_info):
        containers = [
            (other_index, other)
            for other_index in _bbox_container_candidate_indices(bbox_index, contour_info, info["point"])
            if (other := contour_info[other_index])
            if other_index != index
            and other["closed"]
            and other["area"] > info["area"]
            and _bbox_contains_point(other["bbox"], info["point"])
            and _contains_point(other["contour"], info["point"], points_cache.get(id(other["contour"])))
        ]
        parent = min(containers, key=lambda item: item[1]["area"])[0] if containers else None
        parents[index] = parent

    root_by_index = {index: _root_for_contour(index, parents) for index in range(len(contour_info))}
    roots = sorted(set(root_by_index.values()), key=lambda index: (contour_info[index]["bbox"][0], contour_info[index]["bbox"][1]))
    if not roots:
        roots = [max(range(len(contour_info)), key=lambda index: contour_info[index]["area"])]
        root_by_index = {index: roots[0] for index in range(len(contour_info))}

    contours_by_root: dict[int, list[Contour]] = defaultdict(list)
    for index, root in root_by_index.items():
        contours_by_root[root].append(contour_info[index]["contour"])
    groups: list[DxfPartGroup] = []
    multiple = len(roots) > 1
    for group_index, root in enumerate(roots, start=1):
        raw_group = tuple(contours_by_root[root])
        group_name = f"{source}_{group_index}" if multiple else source
        classified = _classify_contours(raw_group, source=group_name)
        normalized, bbox = _normalize_contours(classified)
        groups.append(DxfPartGroup(name=group_name, contours=normalized, bbox=bbox))
    return tuple(groups)


def _root_for_contour(index: int, parents: dict[int, int | None]) -> int:
    current = index
    seen: set[int] = set()
    while parents.get(current) is not None and current not in seen:
        seen.add(current)
        parent = parents[current]
        if parent is None:
            break
        current = parent
    return current


def _contains_point(contour: Contour, point: Point, points: list[Point] | None = None) -> bool:
    if isinstance(contour, CircleContour):
        return point.distance_to(contour.center) < contour.radius - CHAIN_TOLERANCE_MM
    points = points if points is not None else contour.points(max_chord=1.0)
    inside = False
    previous = points[-1]
    for current in points:
        if ((current.y > point.y) != (previous.y > point.y)) and (
            point.x
            < (previous.x - current.x) * (point.y - current.y) / (previous.y - current.y + 1e-12)
            + current.x
        ):
            inside = not inside
        previous = current
    return inside


def _contour_is_closed(contour: Contour) -> bool:
    return not isinstance(contour, PathContour) or contour.is_closed(tolerance=CHAIN_TOLERANCE_MM)


def _build_bbox_container_index(contour_info: list[dict[str, Any]]) -> dict[str, Any] | None:
    if len(contour_info) < BBOX_INDEX_MIN_CONTOURS:
        return None
    min_x = min(info["bbox"][0] for info in contour_info)
    min_y = min(info["bbox"][1] for info in contour_info)
    max_x = max(info["bbox"][2] for info in contour_info)
    max_y = max(info["bbox"][3] for info in contour_info)
    span = max(max_x - min_x, max_y - min_y, 1.0)
    bucket_size = max(10.0, span / 128.0)
    buckets: dict[tuple[int, int], list[int]] = defaultdict(list)
    large: list[int] = []
    for index, info in enumerate(contour_info):
        bbox = info["bbox"]
        x0 = math.floor((bbox[0] - min_x - CHAIN_TOLERANCE_MM) / bucket_size)
        x1 = math.floor((bbox[2] - min_x + CHAIN_TOLERANCE_MM) / bucket_size)
        y0 = math.floor((bbox[1] - min_y - CHAIN_TOLERANCE_MM) / bucket_size)
        y1 = math.floor((bbox[3] - min_y + CHAIN_TOLERANCE_MM) / bucket_size)
        cell_count = (x1 - x0 + 1) * (y1 - y0 + 1)
        if cell_count > BBOX_INDEX_MAX_CELLS_PER_CONTOUR:
            large.append(index)
            continue
        for x_bucket in range(x0, x1 + 1):
            for y_bucket in range(y0, y1 + 1):
                buckets[(x_bucket, y_bucket)].append(index)
    return {"min_x": min_x, "min_y": min_y, "bucket_size": bucket_size, "buckets": buckets, "large": large}


def _bbox_container_candidate_indices(
    bbox_index: dict[str, Any] | None,
    contour_info: list[dict[str, Any]],
    point: Point,
) -> tuple[int, ...]:
    if bbox_index is None:
        return tuple(range(len(contour_info)))
    bucket_size = float(bbox_index["bucket_size"])
    x_bucket = math.floor((point.x - float(bbox_index["min_x"])) / bucket_size)
    y_bucket = math.floor((point.y - float(bbox_index["min_y"])) / bucket_size)
    candidates = {
        *bbox_index["large"],
        *bbox_index["buckets"].get((x_bucket, y_bucket), []),
    }
    return tuple(candidates)


def _bbox_contains_point(bbox: tuple[float, float, float, float], point: Point) -> bool:
    return (
        bbox[0] - CHAIN_TOLERANCE_MM <= point.x <= bbox[2] + CHAIN_TOLERANCE_MM
        and bbox[1] - CHAIN_TOLERANCE_MM <= point.y <= bbox[3] + CHAIN_TOLERANCE_MM
    )


def _normalize_contours(contours: tuple[Contour, ...]) -> tuple[tuple[Contour, ...], tuple[float, float, float, float]]:
    bbox = bbox_for_contours(contours)
    center_x = (bbox[0] + bbox[2]) / 2.0
    center_y = (bbox[1] + bbox[3]) / 2.0
    return tuple(contour.transformed(dx=-center_x, dy=-center_y) for contour in contours), bbox


def _with_kind_and_name(contour: Contour, kind: str, name: str, source: str) -> Contour:
    output_source = contour.source if contour.source.startswith("dxf_review") else source
    if isinstance(contour, CircleContour):
        return CircleContour(name=name, center=contour.center, radius=contour.radius, kind=kind, source=output_source)
    return PathContour(name=name, segments=contour.segments, kind=kind, source=output_source)


def _part_from_group(group: DxfPartGroup) -> dict[str, Any]:
    center_x = (group.bbox[0] + group.bbox[2]) / 2.0
    center_y = (group.bbox[1] + group.bbox[3]) / 2.0
    part = {
        "name": group.name,
        "quantity": 1,
        "allowed_rotations": [0, 45, 90, 135, 180, 225, 270, 315],
        "source_bbox": [round(value, 6) for value in group.bbox],
        "source_center": {"x": round(center_x, 6), "y": round(center_y, 6)},
        "contours": [_contour_to_json(contour) for contour in group.contours],
    }
    _add_legacy_circle_shape(part, group.contours)
    return part


def _initial_placements_for_groups(
    groups: tuple[DxfPartGroup, ...],
    sheet_data: dict[str, Any],
    spacing_mm: float,
) -> list[dict[str, Any]]:
    sheet_width = float(sheet_data.get("width_mm", 1000))
    spacing = max(float(spacing_mm), 0.0)
    placement_spacing = spacing + INITIAL_PLACEMENT_EXTRA_CLEARANCE_MM
    cursor_x = 0.0
    cursor_y = 0.0
    row_height = 0.0
    placements: list[dict[str, Any]] = []
    for group in groups:
        width = group.bbox[2] - group.bbox[0]
        height = group.bbox[3] - group.bbox[1]
        if cursor_x > 0 and cursor_x + width > sheet_width:
            cursor_x = 0.0
            cursor_y += row_height + placement_spacing
            row_height = 0.0
        placements.append(
            {
                "part_name": group.name,
                "instance": 1,
                "dx": cursor_x + width / 2.0,
                "dy": cursor_y + height / 2.0,
                "rotation_deg": 0,
                "manual": False,
            }
        )
        cursor_x += width + placement_spacing
        row_height = max(row_height, height)
    return placements


def _issues_to_json(
    issues: tuple[DxfImportIssue, ...],
    groups: tuple[DxfPartGroup, ...],
    placements: list[dict[str, Any]],
    *,
    include_sheet_points: bool = True,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    emitted: dict[str, int] = defaultdict(int)
    totals = Counter(issue.code for issue in issues)
    first_by_code: dict[str, DxfImportIssue] = {}
    sheet_lookup = _issue_sheet_lookup(groups, placements) if include_sheet_points else None
    for issue in issues:
        first_by_code.setdefault(issue.code, issue)
        if len(output) >= ISSUE_DISPLAY_LIMIT_TOTAL:
            continue
        if emitted[issue.code] >= ISSUE_DISPLAY_LIMIT_PER_CODE:
            continue
        output.append(_issue_to_json(issue, sheet_lookup))
        emitted[issue.code] += 1
    for code in sorted(totals):
        omitted = totals[code] - emitted[code]
        if omitted <= 0:
            continue
        sample = first_by_code[code]
        summary = DxfImportIssue(
            code=code,
            message=f"{omitted} additional DXF {code} issue(s) omitted from display; inspect issue_counts for totals",
            entity_type=sample.entity_type,
            layer=sample.layer,
            process=sample.process,
            blocking=sample.blocking,
        )
        output.append(_issue_to_json(summary, sheet_lookup))
    return output


def _issue_to_json(
    issue: DxfImportIssue,
    sheet_lookup: dict[str, Any] | None,
) -> dict[str, Any]:
    data = asdict(issue)
    if sheet_lookup is None:
        return data
    point = _issue_sheet_point(issue.x, issue.y, sheet_lookup)
    if point is not None:
        data["sheet_x"] = round(point.x, 6)
        data["sheet_y"] = round(point.y, 6)
    target = _issue_sheet_point(issue.target_x, issue.target_y, sheet_lookup)
    if target is not None:
        data["target_sheet_x"] = round(target.x, 6)
        data["target_sheet_y"] = round(target.y, 6)
    return data


def _issue_sheet_lookup(
    groups: tuple[DxfPartGroup, ...],
    placements: list[dict[str, Any]],
) -> dict[str, Any]:
    items = [
        {
            "bbox": group.bbox,
            "placement": placement,
        }
        for group, placement in zip(groups, placements)
    ]
    return {"items": items, "index": _build_bbox_container_index(items)}


def _issue_sheet_point(
    x: float | None,
    y: float | None,
    sheet_lookup: dict[str, Any],
) -> Point | None:
    if x is None or y is None:
        return None
    point = Point(float(x), float(y))
    items = sheet_lookup["items"]
    for index in _bbox_container_candidate_indices(sheet_lookup["index"], items, point):
        item = items[index]
        bbox = item["bbox"]
        if not _point_near_bbox(x, y, bbox):
            continue
        center_x = (bbox[0] + bbox[2]) / 2.0
        center_y = (bbox[1] + bbox[3]) / 2.0
        placement = item["placement"]
        return Point(float(placement["dx"]) + x - center_x, float(placement["dy"]) + y - center_y)
    return None


def _point_near_bbox(x: float, y: float, bbox: tuple[float, float, float, float]) -> bool:
    tolerance = max(GAP_SUGGESTION_MM, CHAIN_TOLERANCE_MM)
    return bbox[0] - tolerance <= x <= bbox[2] + tolerance and bbox[1] - tolerance <= y <= bbox[3] + tolerance


def _supplemental_open_contour_issues(
    contours: tuple[Contour, ...],
    issues: tuple[DxfImportIssue, ...],
) -> tuple[DxfImportIssue, ...]:
    known = {
        (round(float(issue.x) / CHAIN_TOLERANCE_MM), round(float(issue.y) / CHAIN_TOLERANCE_MM))
        for issue in issues
        if issue.code == "open_contour" and issue.x is not None and issue.y is not None
    }
    output: list[DxfImportIssue] = []
    for contour in contours:
        if not isinstance(contour, PathContour) or contour.is_closed(tolerance=CHAIN_TOLERANCE_MM):
            continue
        issue = _open_path_contour_issue(contour)
        key = (round(float(issue.x) / CHAIN_TOLERANCE_MM), round(float(issue.y) / CHAIN_TOLERANCE_MM))
        if key in known:
            continue
        known.add(key)
        output.append(issue)
    return tuple(output)


def _contour_to_json(contour: Contour) -> dict[str, Any]:
    if isinstance(contour, CircleContour):
        return {
            "type": "circle",
            "name": contour.name,
            "kind": contour.kind,
            "source": contour.source,
            "center": {"x": round(contour.center.x, 6), "y": round(contour.center.y, 6)},
            "radius_mm": round(contour.radius, 6),
        }
    return {
        "type": "path",
        "name": contour.name,
        "kind": contour.kind,
        "source": contour.source,
        "open": not contour.is_closed(tolerance=CHAIN_TOLERANCE_MM),
        "segments": [_segment_to_json(segment) for segment in contour.segments],
    }


def _segment_to_json(segment: LineSegment | ArcSegment) -> dict[str, Any]:
    if isinstance(segment, LineSegment):
        return {
            "type": "line",
            "start": _point_to_json(segment.start),
            "end": _point_to_json(segment.end),
        }
    return {
        "type": "arc",
        "start": _point_to_json(segment.start),
        "end": _point_to_json(segment.end),
        "center": _point_to_json(segment.center),
        "clockwise": segment.clockwise,
    }


def _point_to_json(point: Point) -> dict[str, float]:
    return {"x": round(point.x, 6), "y": round(point.y, 6)}


def _add_legacy_circle_shape(part: dict[str, Any], contours: tuple[Contour, ...]) -> None:
    if not all(isinstance(contour, CircleContour) for contour in contours):
        return
    outers = [contour for contour in contours if contour.kind == "outer"]
    holes = [contour for contour in contours if contour.kind == "hole"]
    if len(outers) != 1:
        return
    outer = outers[0]
    part["outer"] = {
        "type": "circle",
        "x": outer.center.x,
        "y": outer.center.y,
        "radius_mm": outer.radius,
    }
    part["holes"] = [
        {
            "type": "circle",
            "x": hole.center.x,
            "y": hole.center.y,
            "radius_mm": hole.radius,
        }
        for hole in holes
    ]


def _value(block: list[tuple[str, str]], code: str, *, default: float | None = None) -> float:
    for group_code, value in block:
        if group_code == code:
            return float(value)
    if default is not None:
        return default
    raise ValueError(f"Missing DXF group code {code}")


def _has_group(block: list[tuple[str, str]], code: str) -> bool:
    return any(group_code == code for group_code, _value_text in block)


def _first_group_index(block: list[tuple[str, str]], code: str) -> int:
    for index, (group_code, _value_text) in enumerate(block):
        if group_code == code:
            return index
    raise ValueError(f"Missing DXF group code {code}")


def _point_from_codes(block: list[tuple[str, str]], x_code: str, y_code: str, scale: float) -> Point:
    return Point(_value(block, x_code) * scale, _value(block, y_code) * scale)


def _effective_entity_layer(block: list[tuple[str, str]], inherited_layer: str | None) -> str:
    layer = _text_value(block, "8", default="").strip()
    if not layer or (layer == "0" and inherited_layer):
        return inherited_layer or "0"
    return layer


def _layer_process(layer: str, layer_mapping: dict[str, str]) -> str:
    key = _layer_key(layer)
    mapped = layer_mapping.get(key)
    if mapped is not None:
        return mapped
    heuristic_tokens = set(_heuristic_layer_tokens(layer))
    for keyword, process in LAYER_NAME_HEURISTICS:
        if keyword in heuristic_tokens:
            return process
    return "cut"


def _normalize_layer_mapping(raw_mapping: Any) -> dict[str, str]:
    if not isinstance(raw_mapping, dict):
        return {}
    output: dict[str, str] = {}
    for raw_layer_or_process, raw_process_or_layers in raw_mapping.items():
        maybe_process = _normalize_layer_process(raw_layer_or_process)
        if maybe_process is not None and isinstance(raw_process_or_layers, (list, tuple, set)):
            for raw_layer in raw_process_or_layers:
                layer_key = _layer_key(str(raw_layer))
                if layer_key:
                    output[layer_key] = maybe_process
            continue
        process = _normalize_layer_process(raw_process_or_layers)
        layer_key = _layer_key(str(raw_layer_or_process))
        if process is not None and layer_key:
            output[layer_key] = process
    return output


def _normalize_layer_process(value: Any) -> str | None:
    key = _heuristic_layer_key(str(value))
    if key in LAYER_PROCESSES:
        return key
    return LAYER_PROCESS_ALIASES.get(key)


def _normalize_unsafe_entity_policy(value: Any) -> str:
    policy = str(value or "block").strip().lower()
    return policy if policy in UNSAFE_ENTITY_POLICIES else "block"


def _unsupported_unsafe_entity_issue(entity_type: str, layer: str, policy: str) -> DxfImportIssue:
    blocking = _normalize_unsafe_entity_policy(policy) == "block"
    suffix = ""
    if not blocking:
        suffix = "; ignored by explicit unsafe_entity_policy=warn import option"
    return DxfImportIssue(
        code="unsupported_unsafe_entity",
        message=(
            f"DXF entity {entity_type} is not an explicit 2D cut contour; "
            "explode/convert it to LINE/ARC/CIRCLE/ELLIPSE/POLYLINE/SPLINE/HATCH before export"
            f"{suffix}"
        ),
        entity_type=entity_type,
        layer=layer,
        process="cut",
        blocking=blocking,
    )


def _layer_key(layer: str) -> str:
    return layer.strip().upper()


def _heuristic_layer_key(layer: str) -> str:
    return "".join(character if character.isalnum() else "_" for character in layer.strip().upper())


def _heuristic_layer_tokens(layer: str) -> tuple[str, ...]:
    return tuple(token for token in _heuristic_layer_key(layer).split("_") if token)


def _mark_layer_issue(entity_type: str, layer: str) -> DxfImportIssue:
    return DxfImportIssue(
        code="mark_layer_skipped",
        message=f"DXF layer {layer} classified as mark/etch; {entity_type} was not added to cut geometry",
        entity_type=entity_type,
        layer=layer,
        process="mark",
        blocking=False,
    )


def _text_value(block: list[tuple[str, str]], code: str, *, default: str | None = None) -> str:
    for group_code, value in block:
        if group_code == code:
            return value
    if default is not None:
        return default
    raise ValueError(f"Missing DXF group code {code}")


def _next_group_value(block: list[tuple[str, str]], start_index: int, code: str) -> float:
    for group_code, value in block[start_index + 1 : start_index + 6]:
        if group_code == code:
            return float(value)
    raise ValueError(f"Missing DXF group code {code}")


def _group_pairs(content: str) -> list[tuple[str, str]]:
    raw = [line.strip() for line in content.splitlines()]
    while raw and raw[0] == "":
        raw.pop(0)
    while raw and raw[-1] == "":
        raw.pop()
    pairs = []
    for index in range(0, len(raw) - 1, 2):
        pairs.append((raw[index], raw[index + 1]))
    return pairs


def _clean_part_name(name: str) -> str:
    stem = Path(name).stem if name else "imported_part"
    cleaned = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in stem.strip())
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    return cleaned or "imported_part"
