"""Geometry model for plasma CAM exports."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Literal, TypeAlias


CutKind = Literal["hole", "inner", "outer"]
EPSILON = 1e-6


@dataclass(frozen=True)
class Point:
    x: float
    y: float

    def translated(self, dx: float, dy: float) -> "Point":
        return Point(self.x + dx, self.y + dy)

    def rotated(self, degrees: float, origin: "Point" | None = None) -> "Point":
        origin = origin or Point(0.0, 0.0)
        radians = math.radians(degrees)
        cos_a = math.cos(radians)
        sin_a = math.sin(radians)
        x = self.x - origin.x
        y = self.y - origin.y
        return Point(
            origin.x + x * cos_a - y * sin_a,
            origin.y + x * sin_a + y * cos_a,
        )

    def distance_to(self, other: "Point") -> float:
        return math.hypot(self.x - other.x, self.y - other.y)

    def almost_equals(self, other: "Point", tolerance: float = 0.01) -> bool:
        return self.distance_to(other) <= tolerance


@dataclass(frozen=True)
class LineSegment:
    start: Point
    end: Point

    def transformed(
        self,
        *,
        dx: float = 0.0,
        dy: float = 0.0,
        rotation_deg: float = 0.0,
    ) -> "LineSegment":
        if abs(rotation_deg) <= EPSILON:
            return LineSegment(
                start=self.start.translated(dx, dy),
                end=self.end.translated(dx, dy),
            )
        return LineSegment(
            start=self.start.rotated(rotation_deg).translated(dx, dy),
            end=self.end.rotated(rotation_deg).translated(dx, dy),
        )

    def reversed(self) -> "LineSegment":
        return LineSegment(self.end, self.start)

    def points(self, max_chord: float = 2.0) -> list[Point]:
        return [self.start, self.end]


@dataclass(frozen=True)
class ArcSegment:
    start: Point
    end: Point
    center: Point
    clockwise: bool = False

    @property
    def radius(self) -> float:
        return self.start.distance_to(self.center)

    def transformed(
        self,
        *,
        dx: float = 0.0,
        dy: float = 0.0,
        rotation_deg: float = 0.0,
    ) -> "ArcSegment":
        if abs(rotation_deg) <= EPSILON:
            return ArcSegment(
                start=self.start.translated(dx, dy),
                end=self.end.translated(dx, dy),
                center=self.center.translated(dx, dy),
                clockwise=self.clockwise,
            )
        return ArcSegment(
            start=self.start.rotated(rotation_deg).translated(dx, dy),
            end=self.end.rotated(rotation_deg).translated(dx, dy),
            center=self.center.rotated(rotation_deg).translated(dx, dy),
            clockwise=self.clockwise,
        )

    def reversed(self) -> "ArcSegment":
        return ArcSegment(
            start=self.end,
            end=self.start,
            center=self.center,
            clockwise=not self.clockwise,
        )

    def points(self, max_chord: float = 2.0) -> list[Point]:
        radius = self.radius
        if radius <= EPSILON:
            return [self.start, self.end]
        start_angle = math.atan2(self.start.y - self.center.y, self.start.x - self.center.x)
        end_angle = math.atan2(self.end.y - self.center.y, self.end.x - self.center.x)
        if self.clockwise:
            if end_angle >= start_angle:
                end_angle -= math.tau
        elif end_angle <= start_angle:
            end_angle += math.tau
        sweep = end_angle - start_angle
        length = abs(sweep) * radius
        steps = max(4, math.ceil(length / max(max_chord, 0.1)))
        return [
            Point(
                self.center.x + math.cos(start_angle + sweep * index / steps) * radius,
                self.center.y + math.sin(start_angle + sweep * index / steps) * radius,
            )
            for index in range(steps + 1)
        ]


Segment: TypeAlias = LineSegment | ArcSegment


@dataclass(frozen=True)
class CircleContour:
    name: str
    center: Point
    radius: float
    kind: CutKind
    source: str = ""

    @property
    def diameter(self) -> float:
        return self.radius * 2.0

    def bbox(self) -> tuple[float, float, float, float]:
        return (
            self.center.x - self.radius,
            self.center.y - self.radius,
            self.center.x + self.radius,
            self.center.y + self.radius,
        )

    def transformed(
        self,
        *,
        dx: float = 0.0,
        dy: float = 0.0,
        rotation_deg: float = 0.0,
        name_prefix: str = "",
    ) -> "CircleContour":
        center = self.center.translated(dx, dy) if abs(rotation_deg) <= EPSILON else self.center.rotated(rotation_deg).translated(dx, dy)
        name = f"{name_prefix}{self.name}" if name_prefix else self.name
        return CircleContour(
            name=name,
            center=center,
            radius=self.radius,
            kind=self.kind,
            source=self.source,
        )

    def points(self, max_chord: float = 2.0) -> list[Point]:
        steps = max(24, math.ceil(math.tau * self.radius / max(max_chord, 0.1)))
        return [
            Point(
                self.center.x + math.cos(math.tau * index / steps) * self.radius,
                self.center.y + math.sin(math.tau * index / steps) * self.radius,
            )
            for index in range(steps)
        ]


@dataclass(frozen=True)
class PathContour:
    name: str
    segments: tuple[Segment, ...]
    kind: CutKind
    source: str = ""

    def __post_init__(self) -> None:
        if not self.segments:
            raise ValueError("Path contour must contain at least one segment")

    def bbox(self) -> tuple[float, float, float, float]:
        points = self.points()
        return (
            min(point.x for point in points),
            min(point.y for point in points),
            max(point.x for point in points),
            max(point.y for point in points),
        )

    def points(self, max_chord: float = 2.0) -> list[Point]:
        output: list[Point] = []
        for segment in self.segments:
            segment_points = segment.points(max_chord=max_chord)
            if output and output[-1].almost_equals(segment_points[0], tolerance=EPSILON):
                output.extend(segment_points[1:])
            else:
                output.extend(segment_points)
        if len(output) > 1 and output[0].almost_equals(output[-1], tolerance=EPSILON):
            output.pop()
        return output

    def is_closed(self, tolerance: float = 1e-6) -> bool:
        return self.segments[0].start.almost_equals(self.segments[-1].end, tolerance=tolerance)

    def transformed(
        self,
        *,
        dx: float = 0.0,
        dy: float = 0.0,
        rotation_deg: float = 0.0,
        name_prefix: str = "",
    ) -> "PathContour":
        name = f"{name_prefix}{self.name}" if name_prefix else self.name
        return PathContour(
            name=name,
            segments=tuple(
                segment.transformed(dx=dx, dy=dy, rotation_deg=rotation_deg)
                for segment in self.segments
            ),
            kind=self.kind,
            source=self.source,
        )

    def reversed(self) -> "PathContour":
        return PathContour(
            name=self.name,
            segments=tuple(segment.reversed() for segment in reversed(self.segments)),
            kind=self.kind,
            source=self.source,
        )


Contour: TypeAlias = CircleContour | PathContour


@dataclass(frozen=True)
class PartProfile:
    name: str
    contours: tuple[Contour, ...]

    def bbox(self) -> tuple[float, float, float, float]:
        return bbox_for_contours(self.contours)


@dataclass(frozen=True)
class CutPlan:
    name: str
    contours: tuple[Contour, ...]

    def ordered_contours(self) -> tuple[Contour, ...]:
        return tuple(order_contours(self.contours))

    def bbox(self) -> tuple[float, float, float, float]:
        return bbox_for_contours(self.contours)


def bbox_for_contours(contours: Iterable[Contour]) -> tuple[float, float, float, float]:
    boxes = [contour.bbox() for contour in contours]
    if not boxes:
        raise ValueError("No contours")
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def contour_points(contour: Contour, max_chord: float = 2.0) -> list[Point]:
    return contour.points(max_chord=max_chord)


def contour_area(contour: Contour) -> float:
    if isinstance(contour, CircleContour):
        return math.pi * contour.radius * contour.radius
    return signed_area(contour.points())


def contour_diameter(contour: Contour) -> float:
    xmin, ymin, xmax, ymax = contour.bbox()
    return max(xmax - xmin, ymax - ymin)


def contour_centroid(contour: Contour) -> Point:
    if isinstance(contour, CircleContour):
        return contour.center
    points = contour.points()
    area = signed_area(points)
    if abs(area) <= EPSILON:
        x = sum(point.x for point in points) / len(points)
        y = sum(point.y for point in points) / len(points)
        return Point(x, y)
    factor = 0.0
    cx = 0.0
    cy = 0.0
    for current, following in zip(points, [*points[1:], points[0]]):
        cross = current.x * following.y - following.x * current.y
        factor += cross
        cx += (current.x + following.x) * cross
        cy += (current.y + following.y) * cross
    return Point(cx / (3.0 * factor), cy / (3.0 * factor))


def signed_area(points: list[Point]) -> float:
    if len(points) < 3:
        return 0.0
    total = 0.0
    for current, following in zip(points, [*points[1:], points[0]]):
        total += current.x * following.y - following.x * current.y
    return total / 2.0


def reverse_contour(contour: Contour) -> Contour:
    if isinstance(contour, PathContour):
        return contour.reversed()
    return contour


def order_contours(contours: Iterable[Contour]) -> list[Contour]:
    priority = {"hole": 0, "inner": 1, "outer": 2}
    return sorted(contours, key=lambda item: (priority[item.kind], item.source, abs(contour_area(item))))


def classify_largest_outer(contours: Iterable[CircleContour]) -> tuple[CircleContour, ...]:
    raw = list(contours)
    if not raw:
        raise ValueError("No contours to classify")
    outer = max(raw, key=lambda item: item.radius)
    classified = []
    for contour in raw:
        kind: CutKind = "outer" if contour is outer else "hole"
        classified.append(
            CircleContour(
                name=contour.name,
                center=contour.center,
                radius=contour.radius,
                kind=kind,
                source=contour.source,
            )
        )
    return tuple(order_contours(classified))
