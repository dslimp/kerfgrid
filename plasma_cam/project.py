"""Project, placement, and validation model for plasma cutting jobs."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable

try:
    from shapely.geometry import Polygon, box
    from shapely.ops import unary_union
except ModuleNotFoundError:
    Polygon = None
    box = None
    unary_union = None

from .model import CircleContour, Contour, CutPlan, PartProfile, PathContour, bbox_for_contours, contour_centroid
from .nesting import Sheet
from .post import QtPlasmaCOptions, generate_gcode


SHEET_BOUNDS_TOLERANCE_MM = 0.001


@dataclass(frozen=True)
class PartRequest:
    profile: PartProfile
    quantity: int = 1
    allowed_rotations: tuple[float, ...] = (0.0,)

    def __post_init__(self) -> None:
        if self.quantity < 1:
            raise ValueError("Part quantity must be positive")
        if not self.allowed_rotations:
            raise ValueError("At least one rotation must be allowed")


@dataclass(frozen=True)
class Placement:
    part_name: str
    instance: int
    dx: float
    dy: float
    rotation_deg: float = 0.0
    locked: bool = False
    manual: bool = False

    @property
    def instance_id(self) -> str:
        return f"{self.part_name}_{self.instance}"

    def moved(self, dx: float, dy: float, *, absolute: bool = False, manual: bool = True) -> "Placement":
        if self.locked:
            raise ValueError(f"Placement is locked: {self.instance_id}")
        return replace(
            self,
            dx=dx if absolute else self.dx + dx,
            dy=dy if absolute else self.dy + dy,
            manual=manual or self.manual,
        )

    def rotated(self, degrees: float, *, absolute: bool = False, manual: bool = True) -> "Placement":
        if self.locked:
            raise ValueError(f"Placement is locked: {self.instance_id}")
        value = degrees if absolute else self.rotation_deg + degrees
        return replace(self, rotation_deg=value % 360.0, manual=manual or self.manual)


@dataclass(frozen=True)
class PlacedPart:
    profile: PartProfile
    placement: Placement

    @property
    def instance_id(self) -> str:
        return self.placement.instance_id

    def contours(self) -> tuple[Contour, ...]:
        prefix = f"{self.instance_id}_"
        return tuple(
            contour.transformed(
                dx=self.placement.dx,
                dy=self.placement.dy,
                rotation_deg=self.placement.rotation_deg,
                name_prefix=prefix,
            )
            for contour in self.profile.contours
        )

    def bbox(self) -> tuple[float, float, float, float]:
        return bbox_for_contours(self.contours())

    def polygon(self, max_chord: float = 1.0):
        if Polygon is None or unary_union is None:
            return None
        outers = []
        holes = []
        for contour in self.contours():
            polygon = _contour_polygon(contour, max_chord=max_chord)
            if polygon is None:
                continue
            if contour.kind == "outer":
                outers.append((contour, polygon))
            else:
                holes.append((contour, polygon))
        solids = []
        for _outer_contour, outer_polygon in outers:
            hole_polygons = [
                hole_polygon
                for hole_contour, hole_polygon in holes
                if outer_polygon.contains(_point_polygon(contour_centroid(hole_contour)))
            ]
            solid = outer_polygon
            for hole_polygon in hole_polygons:
                solid = solid.difference(hole_polygon)
            if not solid.is_empty:
                solids.append(solid)
        if not solids and holes:
            solids = [polygon for _contour, polygon in holes]
        if not solids:
            return None
        return unary_union(solids).buffer(0)


@dataclass(frozen=True)
class NestedLayout:
    name: str
    sheet: Sheet
    placed_parts: tuple[PlacedPart, ...]
    spacing: float = 0.0

    def __post_init__(self) -> None:
        if self.spacing < 0:
            raise ValueError("Spacing cannot be negative")

    def contours(self) -> tuple[CircleContour, ...]:
        contours: list[CircleContour] = []
        for part in self.placed_parts:
            contours.extend(part.contours())
        return tuple(contours)

    def cut_plan(self) -> CutPlan:
        return CutPlan(self.name, self.contours())


@dataclass(frozen=True)
class LayoutIssue:
    code: str
    message: str
    instance_id: str | None = None


class LayoutValidationError(ValueError):
    def __init__(self, issues: list[LayoutIssue]):
        self.issues = issues
        super().__init__("; ".join(issue.message for issue in issues))


def build_layout(
    *,
    name: str,
    sheet: Sheet,
    requests: Iterable[PartRequest],
    placements: Iterable[Placement],
    spacing: float = 0.0,
) -> NestedLayout:
    profiles = {request.profile.name: request.profile for request in requests}
    placed_parts = []
    for placement in placements:
        try:
            profile = profiles[placement.part_name]
        except KeyError as exc:
            raise ValueError(f"Placement references unknown part: {placement.part_name}") from exc
        placed_parts.append(PlacedPart(profile, placement))
    return NestedLayout(name=name, sheet=sheet, placed_parts=tuple(placed_parts), spacing=spacing)


def move_part(layout: NestedLayout, instance_id: str, dx: float, dy: float, *, absolute: bool = False) -> NestedLayout:
    return _replace_part_placement(
        layout,
        instance_id,
        lambda placement: placement.moved(dx, dy, absolute=absolute),
    )


def rotate_part(layout: NestedLayout, instance_id: str, degrees: float, *, absolute: bool = False) -> NestedLayout:
    return _replace_part_placement(
        layout,
        instance_id,
        lambda placement: placement.rotated(degrees, absolute=absolute),
    )


def lock_part(layout: NestedLayout, instance_id: str, *, locked: bool = True) -> NestedLayout:
    return _replace_part_placement(
        layout,
        instance_id,
        lambda placement: replace(placement, locked=locked),
    )


def validate_layout(layout: NestedLayout) -> list[LayoutIssue]:
    issues: list[LayoutIssue] = []
    seen: set[str] = set()
    boxes: list[tuple[PlacedPart, tuple[float, float, float, float]]] = []
    polygons: dict[str, object | None] = {}

    for part in layout.placed_parts:
        if part.instance_id in seen:
            issues.append(LayoutIssue("duplicate_instance", f"Duplicate instance id: {part.instance_id}", part.instance_id))
        seen.add(part.instance_id)

        bbox = part.bbox()
        boxes.append((part, bbox))
        issues.extend(_sheet_issues(part, bbox, layout.sheet))

    sorted_boxes = sorted(boxes, key=lambda item: item[1][0])
    for index, (left, left_box) in enumerate(sorted_boxes):
        for right, right_box in sorted_boxes[index + 1 :]:
            if right_box[0] > left_box[2] + layout.spacing:
                break
            if not _boxes_overlap(left_box, right_box, layout.spacing):
                continue
            left_polygon = _cached_part_polygon(left, polygons)
            right_polygon = _cached_part_polygon(right, polygons)
            if _parts_overlap(left_box, right_box, left_polygon, right_polygon, layout.spacing):
                issues.append(
                    LayoutIssue(
                        "part_collision",
                        f"{left.instance_id} overlaps {right.instance_id} with spacing {layout.spacing:g} mm",
                        left.instance_id,
                    )
                )

    return issues


def _cached_part_polygon(part: PlacedPart, cache: dict[str, object | None]) -> object | None:
    if part.instance_id not in cache:
        cache[part.instance_id] = part.polygon()
    return cache[part.instance_id]


def assert_valid_layout(layout: NestedLayout) -> None:
    issues = validate_layout(layout)
    if issues:
        raise LayoutValidationError(issues)


def generate_layout_gcode(layout: NestedLayout, options: QtPlasmaCOptions) -> str:
    assert_valid_layout(layout)
    return generate_gcode(layout.contours(), options)


def _replace_part_placement(layout: NestedLayout, instance_id: str, updater) -> NestedLayout:
    updated = []
    found = False
    for part in layout.placed_parts:
        if part.instance_id == instance_id:
            updated.append(PlacedPart(part.profile, updater(part.placement)))
            found = True
        else:
            updated.append(part)
    if not found:
        raise ValueError(f"Unknown layout instance: {instance_id}")
    return replace(layout, placed_parts=tuple(updated))


def _sheet_issues(
    part: PlacedPart,
    bbox: tuple[float, float, float, float],
    sheet: Sheet,
) -> list[LayoutIssue]:
    xmin, ymin, xmax, ymax = bbox
    min_x = sheet.margin
    min_y = sheet.margin
    max_x = sheet.width - sheet.margin
    max_y = sheet.height - sheet.margin

    issues = []
    tolerance = SHEET_BOUNDS_TOLERANCE_MM
    if xmin < min_x - tolerance:
        issues.append(LayoutIssue("outside_sheet", f"{part.instance_id} xmin {xmin:.3f} < {min_x:.3f}", part.instance_id))
    if ymin < min_y - tolerance:
        issues.append(LayoutIssue("outside_sheet", f"{part.instance_id} ymin {ymin:.3f} < {min_y:.3f}", part.instance_id))
    if xmax > max_x + tolerance:
        issues.append(LayoutIssue("outside_sheet", f"{part.instance_id} xmax {xmax:.3f} > {max_x:.3f}", part.instance_id))
    if ymax > max_y + tolerance:
        issues.append(LayoutIssue("outside_sheet", f"{part.instance_id} ymax {ymax:.3f} > {max_y:.3f}", part.instance_id))
    return issues


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


def _parts_overlap(
    left_box: tuple[float, float, float, float],
    right_box: tuple[float, float, float, float],
    left_polygon,
    right_polygon,
    clearance: float,
) -> bool:
    if not _boxes_overlap(left_box, right_box, clearance):
        return False
    if left_polygon is None or right_polygon is None:
        return True
    if clearance <= 1e-6:
        intersection = left_polygon.intersection(right_polygon)
        return bool(not intersection.is_empty and intersection.area > 1e-6)
    return left_polygon.distance(right_polygon) < clearance - 1e-6


def _contour_polygon(contour: Contour, *, max_chord: float):
    if isinstance(contour, PathContour) and not contour.is_closed():
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


def _point_polygon(point):
    return box(point.x - 1e-6, point.y - 1e-6, point.x + 1e-6, point.y + 1e-6)
