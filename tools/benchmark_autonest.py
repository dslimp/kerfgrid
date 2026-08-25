#!/usr/bin/env python3
"""Small reproducible auto-nest quality/time benchmark."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from plasma_cam.autonest import ShelfNestOptions, shelf_nest_result
from plasma_cam.model import CircleContour, LineSegment, PartProfile, PathContour, Point
from plasma_cam.nesting import Sheet
from plasma_cam.project import PartRequest


@dataclass(frozen=True)
class BenchmarkCase:
    name: str
    sheet: Sheet
    spacing: float
    requests: tuple[PartRequest, ...]


def run_benchmark(
    *,
    max_runtime_s: float = 2.0,
    attempt_limit: int = 3,
    angle_step_deg: float = 90.0,
    parallel_workers: int = 1,
) -> list[dict[str, Any]]:
    """Run deterministic, short auto-nest benchmark cases."""
    summaries = []
    for case in build_benchmark_cases():
        result = shelf_nest_result(
            case.name,
            case.requests,
            ShelfNestOptions(
                sheet=case.sheet,
                spacing=case.spacing,
                attempt_limit=attempt_limit,
                angle_step_deg=angle_step_deg,
                allow_arbitrary_rotation=True,
                max_runtime_s=max_runtime_s,
                parallel_workers=parallel_workers,
            ),
        )
        summary = result.summary
        summaries.append(
            {
                "case": case.name,
                "requested_count": sum(request.quantity for request in case.requests),
                "placed_count": len(result.layout.placed_parts),
                "sheet_utilization_percent": round(summary.sheet_utilization_percent, 3),
                "packing_utilization_percent": round(summary.packing_utilization_percent, 3),
                "bbox_utilization_percent": round(summary.bbox_utilization_percent, 3),
                "runtime_ms": round(summary.runtime_ms, 3),
                "attempt_count": summary.attempt_count,
                "successful_attempt_count": summary.successful_attempt_count,
                "best_attempt": summary.best_attempt,
                "geometry_engine": summary.geometry_engine,
                "parallel_worker_count": summary.parallel_worker_count,
                "parallel_fallback_reason": summary.parallel_fallback_reason,
                "candidate_position_count": summary.candidate_position_count,
                "nfp_candidate_count": summary.nfp_candidate_count,
                "exact_clearance_check_count": summary.exact_clearance_check_count,
                "spatial_index_query_count": summary.spatial_index_query_count,
                "spatial_index_fallback_count": summary.spatial_index_fallback_count,
                "cache_hit_count": summary.cache_hit_count,
                "cache_miss_count": summary.cache_miss_count,
                "used_width_mm": round(summary.used_width_mm, 3),
                "used_height_mm": round(summary.used_height_mm, 3),
                "top_free_height_mm": round(summary.top_free_height_mm, 3),
                "time_limited": summary.time_limited,
            }
        )
    return summaries


def build_benchmark_cases() -> tuple[BenchmarkCase, ...]:
    circle = circle_profile("circle_hole", outer_radius=55, hole_radius=16)
    long_rect = rectangle_profile("long_rect", 140, 55)
    short_rect = rectangle_profile("short_rect", 85, 75)
    notch = notched_profile("notched_plate", 150, 92, notch_width=36, notch_depth=26)

    return (
        BenchmarkCase(
            name="circles",
            sheet=Sheet(width=520, height=360, margin=10),
            spacing=6,
            requests=(PartRequest(circle, quantity=6, allowed_rotations=(0.0, 90.0, 180.0, 270.0)),),
        ),
        BenchmarkCase(
            name="rectangles",
            sheet=Sheet(width=620, height=360, margin=10),
            spacing=6,
            requests=(
                PartRequest(long_rect, quantity=4, allowed_rotations=(0.0, 90.0)),
                PartRequest(short_rect, quantity=4, allowed_rotations=(0.0, 90.0)),
            ),
        ),
        BenchmarkCase(
            name="mixed",
            sheet=Sheet(width=720, height=420, margin=10),
            spacing=7,
            requests=(
                PartRequest(circle, quantity=3, allowed_rotations=(0.0, 90.0, 180.0, 270.0)),
                PartRequest(short_rect, quantity=3, allowed_rotations=(0.0, 90.0)),
                PartRequest(notch, quantity=3, allowed_rotations=(0.0, 90.0, 180.0, 270.0)),
            ),
        ),
    )


def rectangle_profile(name: str, width: float, height: float) -> PartProfile:
    points = (
        Point(-width / 2.0, -height / 2.0),
        Point(width / 2.0, -height / 2.0),
        Point(width / 2.0, height / 2.0),
        Point(-width / 2.0, height / 2.0),
    )
    return path_profile(name, points)


def notched_profile(name: str, width: float, height: float, *, notch_width: float, notch_depth: float) -> PartProfile:
    half_width = width / 2.0
    half_height = height / 2.0
    half_notch = notch_width / 2.0
    points = (
        Point(-half_width, -half_height),
        Point(half_width, -half_height),
        Point(half_width, half_height),
        Point(half_notch, half_height),
        Point(half_notch, half_height - notch_depth),
        Point(-half_notch, half_height - notch_depth),
        Point(-half_notch, half_height),
        Point(-half_width, half_height),
    )
    return path_profile(name, points)


def circle_profile(name: str, *, outer_radius: float, hole_radius: float | None = None) -> PartProfile:
    contours = [CircleContour(f"{name}_outer", Point(0.0, 0.0), outer_radius, "outer", name)]
    if hole_radius is not None and hole_radius > 0:
        contours.append(CircleContour(f"{name}_hole", Point(0.0, 0.0), hole_radius, "hole", name))
    return PartProfile(name, tuple(contours))


def path_profile(name: str, points: tuple[Point, ...]) -> PartProfile:
    if len(points) < 3:
        raise ValueError("Path profile needs at least three points")
    return PartProfile(
        name,
        (
            PathContour(
                f"{name}_outer",
                tuple(LineSegment(start, end) for start, end in zip(points, (*points[1:], points[0]))),
                "outer",
                name,
            ),
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a short plasma CAM auto-nest benchmark")
    parser.add_argument("--max-runtime-s", type=float, default=2.0)
    parser.add_argument("--attempt-limit", type=int, default=3)
    parser.add_argument("--angle-step-deg", type=float, default=90.0)
    parser.add_argument("--parallel-workers", type=int, default=1)
    parser.add_argument("--indent", type=int, default=2)
    args = parser.parse_args(argv)

    summary = run_benchmark(
        max_runtime_s=args.max_runtime_s,
        attempt_limit=args.attempt_limit,
        angle_step_deg=args.angle_step_deg,
        parallel_workers=args.parallel_workers,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=args.indent, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
