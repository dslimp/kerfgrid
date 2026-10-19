"""Conversion between project JSON and the geometry domain model."""

from __future__ import annotations

from typing import Any

from ..model import ArcSegment, CircleContour, Contour, LineSegment, PartProfile, PathContour, Point
from ..nesting import Sheet
from ..project import PartRequest, Placement


def sheet_from_project(project: dict[str, Any]) -> Sheet:
    sheet = project.get("sheet", {})
    return Sheet(
        width=float(sheet.get("width_mm", 1000.0)),
        height=float(sheet.get("height_mm", 500.0)),
    )


def common_line_enabled(project: dict[str, Any]) -> bool:
    nesting = project.get("nesting", {}) or {}
    post = project.get("post", {}) or {}
    return bool(nesting.get("common_line_cutting", post.get("common_line_cutting", False)))


def effective_spacing_from_project(project: dict[str, Any]) -> float:
    if common_line_enabled(project):
        return 0.0
    if project.get("spacing_mm") is not None:
        return float(project.get("spacing_mm", 5.0))
    cut = project.get("cut", {}) or {}
    if cut.get("spacing_mm") is not None:
        return float(cut.get("spacing_mm", 5.0))
    return 5.0


def requests_from_project(project: dict[str, Any]) -> list[PartRequest]:
    placement_counts: dict[str, int] = {}
    for placement in project.get("placements", []):
        part_name = str(placement.get("part_name", ""))
        placement_counts[part_name] = placement_counts.get(part_name, 0) + 1

    requests = []
    for part in project.get("parts", []):
        profile = profile_from_part_json(part)
        rotations = allowed_rotations_from_part(part)
        quantity = max(int(part.get("quantity", 1)), placement_counts.get(profile.name, 0))
        requests.append(PartRequest(profile=profile, quantity=quantity, allowed_rotations=rotations))
    return requests


def allowed_rotations_from_part(part: dict[str, Any]) -> tuple[float, ...]:
    if part.get("grain_lock"):
        return (0.0,)
    raw = part.get("allowed_rotations")
    values = raw if isinstance(raw, list) and raw else [0, 90, 180, 270]
    rotations: list[float] = []
    for value in values:
        try:
            angle = float(value) % 360.0
        except (TypeError, ValueError):
            continue
        if not any(abs(existing - angle) < 0.001 for existing in rotations):
            rotations.append(angle)
    return tuple(rotations or (0.0, 90.0, 180.0, 270.0))


def placements_from_project(
    project: dict[str, Any],
    *,
    allowed_part_names: set[str] | None = None,
) -> list[Placement]:
    placements = []
    for item in project.get("placements", []):
        part_name = str(item["part_name"])
        if allowed_part_names is not None and part_name not in allowed_part_names:
            continue
        placements.append(
            Placement(
                part_name=part_name,
                instance=int(item["instance"]),
                dx=float(item["dx"]),
                dy=float(item["dy"]),
                rotation_deg=float(item.get("rotation_deg", 0.0)),
                locked=bool(item.get("locked", False)),
                manual=bool(item.get("manual", False)),
            )
        )
    return placements


def profile_from_part_json(part: dict[str, Any]) -> PartProfile:
    name = str(part["name"])
    if part.get("contours"):
        return PartProfile(
            name=name,
            contours=tuple(contour_from_json(item, source=name) for item in part["contours"]),
        )

    outer = part.get("outer", {})
    if outer.get("type", "circle") != "circle":
        raise ValueError(f"Only circle outer contours are supported in this project shape: {name}")

    contours = [
        CircleContour(
            name=f"{name}_outer",
            center=Point(float(outer.get("x", 0.0)), float(outer.get("y", 0.0))),
            radius=float(outer["radius_mm"]),
            kind="outer",
            source=name,
        )
    ]
    for index, hole in enumerate(part.get("holes", []), start=1):
        if hole.get("type", "circle") != "circle":
            raise ValueError(f"Only circle holes are supported in this project shape: {name}")
        contours.append(
            CircleContour(
                name=f"{name}_hole_{index}",
                center=Point(float(hole.get("x", 0.0)), float(hole.get("y", 0.0))),
                radius=float(hole["radius_mm"]),
                kind="hole",
                source=name,
            )
        )
    return PartProfile(name=name, contours=tuple(contours))


def contour_from_json(item: dict[str, Any], *, source: str) -> Contour:
    contour_type = str(item.get("type", "circle"))
    kind = str(item.get("kind", "outer"))
    if kind not in ("outer", "hole", "inner"):
        raise ValueError(f"Unsupported contour kind: {kind}")
    name = str(item.get("name", f"{source}_{kind}"))
    if contour_type == "circle":
        center = item.get("center", {})
        return CircleContour(
            name=name,
            center=Point(float(center.get("x", item.get("x", 0.0))), float(center.get("y", item.get("y", 0.0)))),
            radius=float(item.get("radius_mm", item.get("radius", 0.0))),
            kind=kind,
            source=str(item.get("source", source)),
        )
    if contour_type == "path":
        segments = tuple(segment_from_json(segment) for segment in item.get("segments", []))
        return PathContour(name=name, segments=segments, kind=kind, source=str(item.get("source", source)))
    raise ValueError(f"Unsupported contour type: {contour_type}")


def segment_from_json(item: dict[str, Any]) -> LineSegment | ArcSegment:
    segment_type = str(item.get("type", "line"))
    start = point_from_json(item["start"])
    end = point_from_json(item["end"])
    if segment_type == "line":
        return LineSegment(start, end)
    if segment_type == "arc":
        return ArcSegment(
            start=start,
            end=end,
            center=point_from_json(item["center"]),
            clockwise=bool(item.get("clockwise", False)),
        )
    raise ValueError(f"Unsupported path segment type: {segment_type}")


def point_from_json(item: dict[str, Any]) -> Point:
    return Point(float(item["x"]), float(item["y"]))


def contour_preview(contour: Contour) -> dict[str, Any]:
    xmin, ymin, xmax, ymax = contour.bbox()
    base: dict[str, Any] = {
        "name": contour.name,
        "kind": contour.kind,
        "source": contour.source,
        "bbox": [xmin, ymin, xmax, ymax],
        "points": [{"x": round(point.x, 4), "y": round(point.y, 4)} for point in contour.points(max_chord=2.0)],
    }
    if isinstance(contour, CircleContour):
        base.update(
            {
                "type": "circle",
                "center": {"x": contour.center.x, "y": contour.center.y},
                "radius": contour.radius,
                "radius_mm": contour.radius,
            }
        )
        return base
    base.update(
        {
            "type": "path",
            "open": not contour.is_closed(),
            "segments": [segment_preview(segment) for segment in contour.segments],
        }
    )
    return base


def segment_preview(segment: LineSegment | ArcSegment) -> dict[str, Any]:
    if isinstance(segment, LineSegment):
        return {
            "type": "line",
            "start": {"x": segment.start.x, "y": segment.start.y},
            "end": {"x": segment.end.x, "y": segment.end.y},
        }
    return {
        "type": "arc",
        "start": {"x": segment.start.x, "y": segment.start.y},
        "end": {"x": segment.end.x, "y": segment.end.y},
        "center": {"x": segment.center.x, "y": segment.center.y},
        "clockwise": segment.clockwise,
    }
