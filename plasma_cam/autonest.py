"""Deterministic nesting algorithms for plasma CAM projects."""

from __future__ import annotations

import concurrent.futures
import os
import time
from dataclasses import dataclass, replace
from typing import TypeAlias

try:
    from shapely.affinity import translate as shapely_translate
    from shapely.geometry import Polygon, box as shapely_box
    from shapely.strtree import STRtree
except ModuleNotFoundError:
    Polygon = None
    STRtree = None
    shapely_box = None
    shapely_get_num_coordinates = None
    shapely_translate = None
else:
    try:
        from shapely import get_num_coordinates as shapely_get_num_coordinates
    except ImportError:
        shapely_get_num_coordinates = None

from .model import PartProfile, bbox_for_contours, contour_area
from .nesting import Sheet
from .project import NestedLayout, PartRequest, PlacedPart, Placement, validate_layout


NestItem: TypeAlias = tuple[PartProfile, int, tuple[float, ...]]
Box: TypeAlias = tuple[float, float, float, float]
MAX_GRID_CANDIDATE_POSITIONS = 3500
MAX_NFP_CANDIDATE_POSITIONS = 480
MAX_NFP_OBSTACLES = 120
MAX_EXACT_CHECK_GEOMETRY_POINTS = 2500
MAX_NFP_GEOMETRY_POINTS = 1500
MAX_POLYGON_FOOTPRINT_SEGMENTS = 5000


@dataclass(frozen=True)
class ShelfNestOptions:
    sheet: Sheet
    spacing: float = 5.0
    start_x: float | None = None
    start_y: float | None = None
    sort_by_area: bool = True
    blocked_boxes: tuple[Box, ...] = ()
    attempt_limit: int = 36
    angle_step_deg: float | None = 15.0
    allow_arbitrary_rotation: bool = True
    allow_hole_filler: bool = False
    hole_filler_part_names: tuple[str, ...] | None = None
    hole_parent_part_names: tuple[str, ...] | None = None
    max_runtime_s: float = 12.0
    parallel_workers: int = 1

    def __post_init__(self) -> None:
        if self.attempt_limit < 1:
            raise ValueError("Auto nest attempt limit must be positive")
        if self.angle_step_deg is not None and self.angle_step_deg <= 0:
            raise ValueError("Auto nest angle step must be positive")
        if self.max_runtime_s <= 0:
            raise ValueError("Auto nest runtime limit must be positive")
        if self.parallel_workers < 0:
            raise ValueError("Auto nest worker count cannot be negative")


@dataclass(frozen=True)
class NestSummary:
    attempt_count: int
    successful_attempt_count: int
    best_attempt: str
    geometry_engine: str
    runtime_ms: float
    parallel_worker_count: int
    attempts_per_second: float
    candidate_position_count: int
    nfp_candidate_count: int
    exact_clearance_check_count: int
    spatial_index_query_count: int
    spatial_index_fallback_count: int
    cache_hit_count: int
    cache_miss_count: int
    part_area_mm2: float
    used_bbox_area_mm2: float
    used_width_mm: float
    used_height_mm: float
    used_strip_area_mm2: float
    top_free_height_mm: float
    sheet_usable_area_mm2: float
    packing_utilization_percent: float
    bbox_utilization_percent: float
    sheet_utilization_percent: float
    hole_filler_relocation_count: int = 0
    time_limited: bool = False
    parallel_fallback_reason: str | None = None
    bbox_fallback_count: int = 0


@dataclass(frozen=True)
class NestResult:
    layout: NestedLayout
    summary: NestSummary


@dataclass(frozen=True)
class _AttemptSpec:
    label: str
    instances: list[NestItem]
    rotation_pool: tuple[float, ...] | None
    candidate_policy: str


@dataclass
class _NestStats:
    candidate_position_count: int = 0
    nfp_candidate_count: int = 0
    exact_clearance_check_count: int = 0
    spatial_index_query_count: int = 0
    spatial_index_fallback_count: int = 0
    cache_hit_count: int = 0
    cache_miss_count: int = 0
    bbox_fallback_count: int = 0

    def merge(self, other: "_NestStats") -> None:
        self.candidate_position_count += other.candidate_position_count
        self.nfp_candidate_count += other.nfp_candidate_count
        self.exact_clearance_check_count += other.exact_clearance_check_count
        self.spatial_index_query_count += other.spatial_index_query_count
        self.spatial_index_fallback_count += other.spatial_index_fallback_count
        self.cache_hit_count += other.cache_hit_count
        self.cache_miss_count += other.cache_miss_count
        self.bbox_fallback_count += other.bbox_fallback_count


@dataclass(frozen=True)
class _Footprint:
    bbox: Box
    polygon: object | None
    boundary_points: tuple[tuple[float, float], ...]
    fill_ratio: float
    signature: tuple[float, ...]


@dataclass(frozen=True)
class _WorkerAttemptResult:
    label: str
    score: tuple[float, ...] | None
    layout: NestedLayout | None
    stats: _NestStats
    error: str | None = None
    timeout: bool = False


class _GeometryCache:
    def __init__(self, stats: _NestStats | None = None) -> None:
        self.stats = stats
        self._footprints: dict[tuple[int, float], _Footprint] = {}

    def footprint(self, profile: PartProfile, rotation: float) -> _Footprint:
        key = (id(profile), round(rotation % 360.0, 3))
        cached = self._footprints.get(key)
        if cached is not None:
            if self.stats is not None:
                self.stats.cache_hit_count += 1
            return cached
        if self.stats is not None:
            self.stats.cache_miss_count += 1
        part = PlacedPart(profile, Placement(profile.name, 1, 0.0, 0.0, rotation))
        bbox = part.bbox()
        polygon = None
        if _profile_segment_count(profile) <= MAX_POLYGON_FOOTPRINT_SEGMENTS:
            polygon = part.polygon()
        elif self.stats is not None:
            self.stats.bbox_fallback_count += 1
        signature = _footprint_signature(bbox, polygon)
        footprint = _Footprint(
            bbox=bbox,
            polygon=polygon,
            boundary_points=_geometry_boundary_points(polygon, max_points=24) if polygon is not None else (),
            fill_ratio=_geometry_bbox_fill_ratio(polygon, bbox) if polygon is not None else 0.0,
            signature=signature,
        )
        self._footprints[key] = footprint
        return footprint

    def placed_bbox(self, part: PlacedPart) -> Box:
        footprint = self.footprint(part.profile, part.placement.rotation_deg)
        return _translate_box(footprint.bbox, part.placement.dx, part.placement.dy)

    def placed_polygon(self, part: PlacedPart):
        footprint = self.footprint(part.profile, part.placement.rotation_deg)
        return _translate_polygon(footprint.polygon, part.placement.dx, part.placement.dy)


class _SpatialIndex:
    def __init__(self, occupied: list[tuple[Box, object | None]], stats: _NestStats | None = None) -> None:
        self.occupied = occupied
        self.stats = stats
        self.tree = None
        self.geometries = []
        self._geometry_ids: dict[int, int] = {}
        if STRtree is None or shapely_box is None or len(occupied) < 8:
            return
        for index, (obstacle_box, obstacle_polygon) in enumerate(occupied):
            geometry = obstacle_polygon if obstacle_polygon is not None else shapely_box(*obstacle_box)
            if geometry is None:
                continue
            self._geometry_ids[id(geometry)] = index
            self.geometries.append(geometry)
        if self.geometries:
            self.tree = STRtree(self.geometries)

    def query(self, candidate: Box, clearance: float) -> list[tuple[Box, object | None]]:
        if self.tree is None or shapely_box is None:
            if self.stats is not None:
                self.stats.spatial_index_fallback_count += 1
            return [item for item in self.occupied if _boxes_overlap(candidate, item[0], clearance)]
        if self.stats is not None:
            self.stats.spatial_index_query_count += 1
        query_box = shapely_box(
            candidate[0] - clearance,
            candidate[1] - clearance,
            candidate[2] + clearance,
            candidate[3] + clearance,
        )
        output = []
        for item in self.tree.query(query_box):
            index = _spatial_index_item_index(item, self._geometry_ids)
            if index is None:
                continue
            obstacle = self.occupied[index]
            if _boxes_overlap(candidate, obstacle[0], clearance):
                output.append(obstacle)
        return output


def shelf_nest(
    name: str,
    requests: tuple[PartRequest, ...],
    options: ShelfNestOptions,
) -> NestedLayout:
    return shelf_nest_result(name, requests, options).layout


def shelf_nest_result(
    name: str,
    requests: tuple[PartRequest, ...],
    options: ShelfNestOptions,
) -> NestResult:
    started_at = time.monotonic()
    final_deadline = started_at + options.max_runtime_s
    packing_deadline = _packing_deadline(started_at, options.max_runtime_s)
    instances = _expand_instances(requests)
    stats = _NestStats()
    cache = _GeometryCache(stats)
    seed_best: tuple[tuple[float, ...], NestedLayout, str] | None = None
    try:
        seed_layout, seed_score = _pack_shelf_seed(
            name,
            instances,
            options,
            deadline=packing_deadline,
            cache=cache,
        )
    except (TimeoutError, ValueError):
        pass
    else:
        seed_best = (seed_score, seed_layout, "shelf-seed")
    attempts, build_time_limited = _build_attempts(instances, options, cache, deadline=packing_deadline)
    best: tuple[tuple[float, ...], NestedLayout, str] | None = None
    successful = 0
    time_limited = build_time_limited
    lattice_attempt_count = 0
    parallel_fallback_reason: str | None = None
    for layout, score, label in _pack_lattice_attempts(
        name,
        instances,
        options,
        deadline=packing_deadline,
        stats=stats,
        cache=cache,
    ):
        lattice_attempt_count += 1
        successful += 1
        if best is None or score <= best[0]:
            best = (score, layout, label)
    time_limited = time_limited or _deadline_reached(packing_deadline)
    worker_count = _parallel_worker_count(options, len(attempts))
    if time_limited:
        attempt_best = None
        attempt_successful = 0
        attempt_time_limited = True
    else:
        if worker_count > 1:
            try:
                attempt_best, attempt_successful, attempt_time_limited, parallel_stats = _pack_attempts_parallel(
                    name,
                    attempts,
                    options,
                    deadline=packing_deadline,
                    worker_count=worker_count,
                )
                stats.merge(parallel_stats)
            except (OSError, RuntimeError) as exc:
                parallel_fallback_reason = f"{type(exc).__name__}: {exc}"
                worker_count = 1
                attempt_best, attempt_successful, attempt_time_limited = _pack_attempts_serial(
                    name,
                    attempts,
                    options,
                    deadline=packing_deadline,
                    stats=stats,
                    cache=cache,
                )
        else:
            attempt_best, attempt_successful, attempt_time_limited = _pack_attempts_serial(
                name,
                attempts,
                options,
                deadline=packing_deadline,
                stats=stats,
                cache=cache,
            )
    successful += attempt_successful
    time_limited = time_limited or attempt_time_limited
    if attempt_best is not None and (best is None or attempt_best[0] < best[0]):
        best = attempt_best
    if best is None and seed_best is not None:
        best = seed_best
    if best is None and time_limited:
        raise ValueError("Auto nest could not fit parts on the current sheet within the optimization budget")
    if best is None:
        raise ValueError("Could not fit parts on sheet")
    if _deadline_reached(final_deadline):
        time_limited = True
        compacted = best[1]
    else:
        compacted = _compact_layout(best[1], options, deadline=final_deadline, stats=stats, cache=cache)
    hole_filler_relocation_count = 0
    if options.allow_hole_filler and not _deadline_reached(final_deadline):
        compacted, hole_filler_relocation_count = _relocate_parts_into_internal_holes(
            compacted,
            options,
            deadline=final_deadline,
            stats=stats,
            cache=cache,
        )
    summary = _nest_summary(
        compacted,
        options.sheet,
        attempt_count=max(1, len(attempts) + lattice_attempt_count),
        successful_attempt_count=successful or 1,
        best_attempt=best[2],
        time_limited=time_limited,
        runtime_ms=(time.monotonic() - started_at) * 1000.0,
        stats=stats,
        parallel_worker_count=worker_count,
        cache=cache,
        hole_filler_relocation_count=hole_filler_relocation_count,
        parallel_fallback_reason=parallel_fallback_reason,
        bbox_fallback_count=stats.bbox_fallback_count,
    )
    return NestResult(layout=compacted, summary=summary)


def _pack_shelf_seed(
    name: str,
    instances: list[NestItem],
    options: ShelfNestOptions,
    *,
    deadline: float | None = None,
    cache: _GeometryCache | None = None,
) -> tuple[NestedLayout, tuple[float, ...]]:
    cache = cache or _GeometryCache()
    margin_x = options.start_x if options.start_x is not None else options.sheet.margin
    margin_y = options.start_y if options.start_y is not None else options.sheet.margin
    usable_xmax = options.sheet.width - options.sheet.margin
    usable_ymax = options.sheet.height - options.sheet.margin
    ordered = sorted(
        instances,
        key=lambda item: (
            -_profile_area_bbox(item[0]),
            -_profile_max_side(item[0]),
            item[0].name,
            item[1],
        ),
    )
    occupied = list(options.blocked_boxes)
    placed: list[PlacedPart] = []
    score_boxes: list[Box] = []
    for profile, instance, allowed_rotations in ordered:
        _raise_if_deadline_reached(deadline)
        x_values = {margin_x}
        y_values = {margin_y}
        for obstacle in occupied:
            x_values.add(obstacle[2] + options.spacing)
            y_values.add(obstacle[3] + options.spacing)
        best: tuple[tuple[float, ...], Placement, Box] | None = None
        rotations = _unique_profile_rotations(profile, _unique_angles(allowed_rotations or (0.0,)), cache, deadline=deadline)
        for rotation in rotations:
            footprint = cache.footprint(profile, rotation)
            xmin, ymin, xmax, ymax = footprint.bbox
            width = xmax - xmin
            height = ymax - ymin
            for y in sorted(y_values):
                if y + height > usable_ymax + 0.001:
                    continue
                for x in sorted(x_values):
                    _raise_if_deadline_reached(deadline)
                    if x + width > usable_xmax + 0.001:
                        continue
                    box = (x, y, x + width, y + height)
                    if any(_boxes_overlap(box, obstacle, options.spacing) for obstacle in occupied):
                        continue
                    placement = Placement(
                        part_name=profile.name,
                        instance=instance,
                        dx=x - xmin,
                        dy=y - ymin,
                        rotation_deg=rotation,
                    )
                    score = (y, x, box[3], box[2], abs(rotation) % 360.0)
                    if best is None or score < best[0]:
                        best = (score, placement, box)
        if best is None:
            raise ValueError(f"Could not fit {profile.name}_{instance} on sheet")
        _score, placement, box = best
        placed.append(PlacedPart(profile, placement))
        occupied.append(box)
        score_boxes.append(box)
    layout = NestedLayout(name=name, sheet=options.sheet, placed_parts=tuple(placed), spacing=options.spacing)
    return layout, _nest_score(score_boxes, margin_x, margin_y)


def _build_attempts(
    instances: list[NestItem],
    options: ShelfNestOptions,
    cache: _GeometryCache,
    *,
    deadline: float | None = None,
) -> tuple[list[_AttemptSpec], bool]:
    if not options.sort_by_area:
        ordered_specs = [("current", instances)]
    else:
        sort_specs = (
            ("area", lambda item: -_profile_area_bbox(item[0])),
            ("max-side", lambda item: -_profile_max_side(item[0])),
            ("wide", lambda item: -_profile_width(item[0])),
            ("tall", lambda item: -_profile_height(item[0])),
            ("current", lambda item: 0),
        )
        ordered_specs = []
        seen: set[tuple[tuple[str, int], ...]] = set()
        for label, spec in sort_specs:
            ordered = sorted(instances, key=lambda item: (spec(item), item[0].name, item[1]))
            key = tuple((profile.name, instance) for profile, instance, _rotations in ordered)
            if key in seen:
                continue
            seen.add(key)
            ordered_specs.append((label, ordered))
    rotation_sets = _rotation_sets(options)
    candidate_policies = ("compact", "bottom", "left", "short-height")
    attempts = []
    seen_attempts = set()
    time_limited = False
    for order_label, ordered in ordered_specs:
        if _deadline_reached(deadline):
            time_limited = True
            break
        for policy in candidate_policies:
            if _deadline_reached(deadline):
                time_limited = True
                break
            for rotation_label, rotation_pool in rotation_sets:
                if _deadline_reached(deadline):
                    time_limited = True
                    break
                attempt_key = (
                    tuple((profile.name, instance) for profile, instance, _rotations in ordered),
                    policy,
                    _attempt_rotation_pool_key(ordered, rotation_pool, options),
                )
                if attempt_key in seen_attempts:
                    continue
                seen_attempts.add(attempt_key)
                attempts.append(
                    _AttemptSpec(
                        label=f"{order_label}/{rotation_label}/{policy}",
                        instances=ordered,
                        rotation_pool=rotation_pool,
                        candidate_policy=policy,
                    )
                )
                if len(attempts) >= options.attempt_limit:
                    return attempts, time_limited
    return attempts, time_limited


def _attempt_rotation_key(
    instances: list[NestItem],
    rotation_pool: tuple[float, ...] | None,
    options: ShelfNestOptions,
    cache: _GeometryCache,
) -> tuple[tuple[str, tuple[tuple[float, ...], ...]], ...]:
    return tuple(
        (
            profile.name,
            tuple(
                _profile_rotation_signature(profile, rotation, cache)
                for rotation in _unique_profile_rotations(profile, _rotations_for_attempt(rotations, rotation_pool, options), cache)
            ),
        )
        for profile, _instance, rotations in instances
    )


def _attempt_rotation_pool_key(
    instances: list[NestItem],
    rotation_pool: tuple[float, ...] | None,
    options: ShelfNestOptions,
) -> tuple[tuple[str, tuple[float, ...]], ...]:
    return tuple(
        (
            profile.name,
            tuple(round(angle % 360.0, 3) for angle in _rotations_for_attempt(rotations, rotation_pool, options)),
        )
        for profile, _instance, rotations in instances
    )


def _rotation_sets(options: ShelfNestOptions) -> tuple[tuple[str, tuple[float, ...] | None], ...]:
    if not options.allow_arbitrary_rotation:
        return (("allowed", None),)
    step = options.angle_step_deg or 15.0
    sets: list[tuple[str, tuple[float, ...] | None]] = [
        ("allowed", None),
        ("quarter", (0.0, 90.0, 180.0, 270.0)),
    ]
    for candidate_step in (45.0, 30.0, 15.0, step):
        if candidate_step + 1e-6 >= step:
            sets.append((f"{candidate_step:g}deg", _angle_range(candidate_step, 0.0)))
    sets.append((f"{step:g}deg-half", _angle_range(step, step / 2.0)))
    return tuple(_unique_rotation_sets(sets))


def _unique_rotation_sets(
    sets: list[tuple[str, tuple[float, ...] | None]],
) -> list[tuple[str, tuple[float, ...] | None]]:
    output = []
    seen = set()
    for label, pool in sets:
        key = None if pool is None else tuple(round(angle, 3) for angle in pool)
        if key in seen:
            continue
        seen.add(key)
        output.append((label, pool))
    return output


def _default_rotation_sets() -> tuple[tuple[str, tuple[float, ...] | None], ...]:
    return (
        ("allowed", None),
        ("quarter", (0.0, 90.0, 180.0, 270.0)),
        ("45deg", _angle_range(45.0, 0.0)),
        ("30deg", _angle_range(30.0, 0.0)),
        ("15deg", _angle_range(15.0, 0.0)),
        ("15deg-half", _angle_range(15.0, 7.5)),
    )


def _angle_range(step: float, phase: float) -> tuple[float, ...]:
    values = []
    angle = phase
    while angle < 360.0 - 1e-6:
        values.append(round(angle % 360.0, 3))
        angle += step
    return tuple(values)


def _pack_attempt(
    name: str,
    attempt: _AttemptSpec,
    options: ShelfNestOptions,
    *,
    deadline: float | None = None,
    stats: _NestStats | None = None,
    cache: _GeometryCache | None = None,
) -> tuple[NestedLayout, tuple[float, ...]]:
    cache = cache or _GeometryCache(stats)
    x = options.start_x if options.start_x is not None else options.sheet.margin
    y = options.start_y if options.start_y is not None else options.sheet.margin
    margin_x = x
    margin_y = y
    usable_xmax = options.sheet.width - options.sheet.margin
    usable_ymax = options.sheet.height - options.sheet.margin
    placed: list[PlacedPart] = []
    occupied: list[tuple[Box, object | None]] = [(box, None) for box in options.blocked_boxes]
    score_boxes: list[Box] = []
    for profile, instance, rotations in attempt.instances:
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("Auto nest time budget reached")
        candidate = _best_candidate(
            profile,
            instance,
            _rotations_for_attempt(rotations, attempt.rotation_pool, options),
            occupied,
            score_boxes,
            margin_x,
            margin_y,
            usable_xmax,
            usable_ymax,
            options.spacing,
            attempt.candidate_policy,
            deadline,
            stats,
            cache,
        )
        if candidate is None:
            raise ValueError(f"Could not fit {profile.name}_{instance} on sheet")
        placement, box, polygon = candidate
        placed.append(PlacedPart(profile, placement))
        occupied.append((box, polygon))
        score_boxes.append(box)
    layout = NestedLayout(name=name, sheet=options.sheet, placed_parts=tuple(placed), spacing=options.spacing)
    return layout, _nest_score(score_boxes, margin_x, margin_y)


def _pack_attempts_parallel(
    name: str,
    attempts: list[_AttemptSpec],
    options: ShelfNestOptions,
    *,
    deadline: float,
    worker_count: int,
) -> tuple[tuple[tuple[float, ...], NestedLayout, str] | None, int, bool, _NestStats]:
    stats = _NestStats()
    best: tuple[tuple[float, ...], NestedLayout, str] | None = None
    best_order: int | None = None
    successful = 0
    time_limited = False
    order_by_label = {attempt.label: index for index, attempt in enumerate(attempts)}
    iterator = iter(attempts)
    executor = concurrent.futures.ProcessPoolExecutor(max_workers=worker_count)
    running: dict[concurrent.futures.Future[_WorkerAttemptResult], str] = {}

    def submit_next() -> bool:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        try:
            attempt = next(iterator)
        except StopIteration:
            return False
        future = executor.submit(_pack_attempt_worker, name, attempt, options, deadline)
        running[future] = attempt.label
        return True

    try:
        for _index in range(worker_count):
            if not submit_next():
                break
        while running:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                time_limited = True
                break
            done, _pending = concurrent.futures.wait(
                running,
                timeout=remaining,
                return_when=concurrent.futures.FIRST_COMPLETED,
            )
            if not done:
                time_limited = True
                break
            for future in done:
                label = running.pop(future)
                try:
                    result = future.result()
                except Exception as exc:
                    result = _WorkerAttemptResult(label=label, score=None, layout=None, stats=_NestStats(), error=str(exc))
                stats.merge(result.stats)
                if result.timeout:
                    time_limited = True
                    continue
                if result.score is not None and result.layout is not None:
                    order = order_by_label.get(result.label, len(order_by_label))
                    successful += 1
                    if best is None or result.score < best[0] or (result.score == best[0] and (best_order is None or order < best_order)):
                        best = (result.score, result.layout, result.label)
                        best_order = order
                if not time_limited:
                    submit_next()
            if time_limited:
                break
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
    return best, successful, time_limited, stats


def _pack_attempts_serial(
    name: str,
    attempts: list[_AttemptSpec],
    options: ShelfNestOptions,
    *,
    deadline: float,
    stats: _NestStats,
    cache: _GeometryCache,
) -> tuple[tuple[tuple[float, ...], NestedLayout, str] | None, int, bool]:
    best: tuple[tuple[float, ...], NestedLayout, str] | None = None
    successful = 0
    time_limited = False
    for attempt in attempts:
        if time.monotonic() >= deadline:
            time_limited = True
            break
        try:
            layout, score = _pack_attempt(name, attempt, options, deadline=deadline, stats=stats, cache=cache)
        except TimeoutError:
            time_limited = True
            break
        except ValueError:
            if time.monotonic() >= deadline:
                time_limited = True
                break
            continue
        successful += 1
        if best is None or score < best[0]:
            best = (score, layout, attempt.label)
        if time.monotonic() >= deadline:
            time_limited = True
            break
    return best, successful, time_limited


def _pack_attempt_worker(
    name: str,
    attempt: _AttemptSpec,
    options: ShelfNestOptions,
    deadline: float,
) -> _WorkerAttemptResult:
    stats = _NestStats()
    cache = _GeometryCache(stats)
    try:
        layout, score = _pack_attempt(
            name,
            attempt,
            options,
            deadline=deadline,
            stats=stats,
            cache=cache,
        )
    except TimeoutError as exc:
        return _WorkerAttemptResult(label=attempt.label, score=None, layout=None, stats=stats, error=str(exc), timeout=True)
    except ValueError as exc:
        return _WorkerAttemptResult(label=attempt.label, score=None, layout=None, stats=stats, error=str(exc))
    return _WorkerAttemptResult(label=attempt.label, score=score, layout=layout, stats=stats)


def _expand_instances(requests: tuple[PartRequest, ...]) -> list[tuple[PartProfile, int, tuple[float, ...]]]:
    instances = []
    for request in requests:
        for instance in range(1, request.quantity + 1):
            instances.append((request.profile, instance, request.allowed_rotations))
    return instances


def _pack_lattice_attempts(
    name: str,
    instances: list[NestItem],
    options: ShelfNestOptions,
    *,
    deadline: float | None,
    stats: _NestStats | None,
    cache: _GeometryCache,
) -> list[tuple[NestedLayout, tuple[float, ...], str]]:
    if len(instances) < 2 or len({profile.name for profile, _instance, _rotations in instances}) != 1:
        return []
    layouts = []
    for rotation in _common_lattice_rotations(instances, options, cache):
        if deadline is not None and time.monotonic() >= deadline:
            break
        try:
            layout = _pack_lattice_rotation(name, instances, options, rotation, deadline=deadline, stats=stats, cache=cache)
        except TimeoutError:
            break
        if layout is None:
            continue
        score = _nest_score([_part_bbox(part, cache) for part in layout.placed_parts], options.sheet.margin, options.sheet.margin)
        layouts.append((layout, score, f"lattice/{rotation:g}deg"))
    return layouts


def _common_lattice_rotations(instances: list[NestItem], options: ShelfNestOptions, cache: _GeometryCache) -> tuple[float, ...]:
    if not instances:
        return ()
    pools = _rotation_sets(options)
    common: set[float] | None = None
    for _profile, _instance, rotations in instances:
        values: list[float] = []
        for _label, pool in pools:
            values.extend(_rotations_for_attempt(rotations, pool, options))
        current = {round(angle % 360.0, 3) for angle in values}
        common = current if common is None else common & current
    return _unique_profile_rotations(instances[0][0], _unique_angles(tuple(sorted(common or ()))), cache)


def _pack_lattice_rotation(
    name: str,
    instances: list[NestItem],
    options: ShelfNestOptions,
    rotation: float,
    *,
    deadline: float | None = None,
    stats: _NestStats | None = None,
    cache: _GeometryCache | None = None,
) -> NestedLayout | None:
    cache = cache or _GeometryCache(stats)
    profile = instances[0][0]
    xmin, ymin, xmax, ymax = _rotated_bbox(profile, rotation, cache)
    width = xmax - xmin
    height = ymax - ymin
    x_values = _lattice_axis_values(options.sheet.margin, options.sheet.width - options.sheet.margin, width, options.spacing)
    y_values = _lattice_axis_values(options.sheet.margin, options.sheet.height - options.sheet.margin, height, options.spacing)
    if not x_values or not y_values:
        return None
    occupied: list[tuple[Box, object | None]] = [(box, None) for box in options.blocked_boxes]
    placed: list[PlacedPart] = []
    instance_index = 0
    for y in y_values:
        for x in x_values:
            _raise_if_deadline_reached(deadline)
            if instance_index >= len(instances):
                return NestedLayout(name=name, sheet=options.sheet, placed_parts=tuple(placed), spacing=options.spacing)
            item_profile, instance, _rotations = instances[instance_index]
            placement = Placement(
                part_name=item_profile.name,
                instance=instance,
                dx=x - xmin,
                dy=y - ymin,
                rotation_deg=rotation,
            )
            part = PlacedPart(item_profile, placement)
            if not _part_fits(part, options.sheet, occupied, options.spacing, stats=stats, cache=cache, deadline=deadline):
                continue
            _raise_if_deadline_reached(deadline)
            occupied.append((_part_bbox(part, cache), _part_polygon(part, cache)))
            placed.append(part)
            instance_index += 1
    if instance_index < len(instances):
        return None
    return NestedLayout(name=name, sheet=options.sheet, placed_parts=tuple(placed), spacing=options.spacing)


def _lattice_axis_values(minimum: float, maximum: float, size: float, spacing: float) -> tuple[float, ...]:
    values = []
    value = minimum
    last = maximum - size
    while value <= last + 0.001:
        values.append(round(value, 6))
        value += size + spacing
    return tuple(values)


def _best_candidate(
    profile: PartProfile,
    instance: int,
    rotations: tuple[float, ...],
    occupied: list[tuple[Box, object | None]],
    score_boxes: list[Box],
    margin_x: float,
    margin_y: float,
    usable_xmax: float,
    usable_ymax: float,
    spacing: float,
    candidate_policy: str,
    deadline: float | None,
    stats: _NestStats | None = None,
    cache: _GeometryCache | None = None,
) -> tuple[Placement, Box, object | None] | None:
    cache = cache or _GeometryCache(stats)
    best: tuple[tuple[float, ...], Placement, Box, object | None] | None = None
    obstacle_index = _SpatialIndex(occupied, stats)
    for rotation in _unique_profile_rotations(profile, rotations, cache, deadline=deadline):
        footprint = cache.footprint(profile, rotation)
        xmin, ymin, xmax, ymax = footprint.bbox
        width = xmax - xmin
        height = ymax - ymin
        for index, (x, y) in enumerate(
            _candidate_positions(
                width,
                height,
                occupied,
                margin_x,
                margin_y,
                usable_xmax,
                usable_ymax,
                spacing,
                moving_polygon=footprint.polygon,
                moving_bounds=(xmin, ymin, xmax, ymax),
                moving_boundary_points=footprint.boundary_points,
                moving_fill=footprint.fill_ratio,
                deadline=deadline,
                stats=stats,
            )
        ):
            if deadline is not None and index % 128 == 0 and time.monotonic() >= deadline:
                if best is not None:
                    return best[1], best[2], best[3]
                raise TimeoutError("Auto nest time budget reached")
            box = (x, y, x + width, y + height)
            placement = Placement(
                part_name=profile.name,
                instance=instance,
                dx=x - xmin,
                dy=y - ymin,
                rotation_deg=rotation,
            )
            overlapping = obstacle_index.query(box, spacing)
            polygon = None
            if overlapping:
                polygon = _translate_polygon(footprint.polygon, placement.dx, placement.dy)
            if any(
                _occupied_overlap(
                    box,
                    polygon,
                    occupied_box,
                    occupied_polygon,
                    spacing,
                    stats=stats,
                    deadline=deadline,
                )
                for occupied_box, occupied_polygon in overlapping
            ):
                continue
            score = _candidate_score(box, [*score_boxes, box], margin_x, margin_y, candidate_policy)
            if best is None or score < best[0]:
                if polygon is None:
                    polygon = _translate_polygon(footprint.polygon, placement.dx, placement.dy)
                best = (score, placement, box, polygon)
    if best is None:
        return None
    return best[1], best[2], best[3]


def _rotations_for_attempt(
    allowed: tuple[float, ...],
    rotation_pool: tuple[float, ...] | None,
    options: ShelfNestOptions,
) -> tuple[float, ...]:
    if not options.allow_arbitrary_rotation or rotation_pool is None:
        return _unique_angles(allowed)
    if options.angle_step_deg is None:
        return _unique_angles((*allowed, *rotation_pool))
    coarse_pool = tuple(angle for angle in rotation_pool if _angle_matches_step(angle, options.angle_step_deg))
    return _unique_angles((*allowed, *(coarse_pool or rotation_pool)))


def _angle_matches_step(angle: float, step: float) -> bool:
    if step <= 0:
        return True
    value = (angle % step)
    return value <= 1e-6 or abs(value - step) <= 1e-6


def _unique_angles(values: tuple[float, ...]) -> tuple[float, ...]:
    output = []
    for value in values:
        angle = round(value % 360.0, 3)
        if not any(abs(angle - existing) <= 1e-6 for existing in output):
            output.append(angle)
    return tuple(output or [0.0])


def _unique_profile_rotations(
    profile: PartProfile,
    rotations: tuple[float, ...],
    cache: _GeometryCache,
    *,
    deadline: float | None = None,
) -> tuple[float, ...]:
    output = []
    seen = set()
    for rotation in _unique_angles(rotations):
        _raise_if_deadline_reached(deadline)
        if _deadline_near(deadline, 0.02) and output:
            break
        key = _profile_rotation_signature(profile, rotation, cache)
        if key in seen:
            continue
        seen.add(key)
        output.append(rotation)
        if _deadline_near(deadline, 0.02):
            break
    return tuple(output or [0.0])


def _profile_rotation_signature(profile: PartProfile, rotation: float, cache: _GeometryCache) -> tuple[float, ...]:
    return cache.footprint(profile, rotation).signature


def _candidate_score(box: Box, boxes: list[Box], margin_x: float, margin_y: float, policy: str) -> tuple[float, ...]:
    compact = _nest_score(boxes, margin_x, margin_y)
    if policy == "bottom":
        return (box[3], box[1], *compact, box[0])
    if policy == "left":
        return (box[2], box[0], *compact, box[1])
    if policy == "short-height":
        return (compact[0], box[3], compact[1], compact[2], box[1], box[0])
    return (*compact, box[1], box[0], box[3], box[2])


def _candidate_positions(
    width: float,
    height: float,
    occupied: list[tuple[Box, object | None]],
    margin_x: float,
    margin_y: float,
    usable_xmax: float,
    usable_ymax: float,
    spacing: float,
    *,
    moving_polygon=None,
    moving_bounds: Box | None = None,
    moving_boundary_points: tuple[tuple[float, float], ...] = (),
    moving_fill: float | None = None,
    deadline: float | None = None,
    stats: _NestStats | None = None,
) -> list[tuple[float, float]]:
    _raise_if_deadline_reached(deadline)
    xmax = usable_xmax - width
    ymax = usable_ymax - height
    if xmax < margin_x - 0.001 or ymax < margin_y - 0.001:
        return []
    x_values: set[float] = set()
    y_values: set[float] = set()
    _add_candidate_value(x_values, margin_x, margin_x, xmax)
    _add_candidate_value(x_values, xmax, margin_x, xmax)
    _add_candidate_value(y_values, margin_y, margin_y, ymax)
    _add_candidate_value(y_values, ymax, margin_y, ymax)
    for box, _polygon in occupied:
        _raise_if_deadline_reached(deadline)
        _add_candidate_value(x_values, box[0], margin_x, xmax)
        _add_candidate_value(x_values, box[2] + spacing, margin_x, xmax)
        _add_candidate_value(x_values, box[0] - width - spacing, margin_x, xmax)
        _add_candidate_value(x_values, box[2] - width, margin_x, xmax)
        _add_candidate_value(y_values, box[1], margin_y, ymax)
        _add_candidate_value(y_values, box[3] + spacing, margin_y, ymax)
        _add_candidate_value(y_values, box[1] - height - spacing, margin_y, ymax)
        _add_candidate_value(y_values, box[3] - height, margin_y, ymax)
    positions = _grid_candidate_positions(
        sorted(x_values),
        sorted(y_values),
        deadline=deadline,
        max_positions=_candidate_grid_limit(len(occupied)),
    )
    nfp_positions = _nfp_candidate_positions(
        moving_polygon,
        moving_bounds,
        occupied,
        spacing,
        margin_x,
        margin_y,
        xmax,
        ymax,
        moving_boundary_points=moving_boundary_points,
        moving_fill=moving_fill,
        deadline=deadline,
    )
    if stats is not None:
        stats.nfp_candidate_count += len(nfp_positions)
    positions.extend(nfp_positions)
    output = _unique_positions(positions)
    if stats is not None:
        stats.candidate_position_count += len(output)
    return output


def _candidate_grid_limit(occupied_count: int) -> int:
    return min(MAX_GRID_CANDIDATE_POSITIONS, max(256, 64 + occupied_count * 16))


def _grid_candidate_positions(
    x_values: list[float],
    y_values: list[float],
    *,
    deadline: float | None,
    max_positions: int,
) -> list[tuple[float, float]]:
    positions: list[tuple[float, float]] = []
    for y in y_values:
        for x in x_values:
            if len(positions) % 256 == 0:
                _raise_if_deadline_reached(deadline)
            positions.append((x, y))
            if len(positions) >= max_positions:
                return positions
    return positions


def _nfp_candidate_positions(
    moving_polygon,
    moving_bounds: Box | None,
    occupied: list[tuple[Box, object | None]],
    spacing: float,
    min_x: float,
    min_y: float,
    max_x: float,
    max_y: float,
    *,
    moving_boundary_points: tuple[tuple[float, float], ...] = (),
    moving_fill: float | None = None,
    deadline: float | None = None,
    max_positions: int = MAX_NFP_CANDIDATE_POSITIONS,
) -> list[tuple[float, float]]:
    _raise_if_deadline_reached(deadline)
    if moving_polygon is None or moving_bounds is None:
        return []
    moving_fill = _geometry_bbox_fill_ratio(moving_polygon, moving_bounds) if moving_fill is None else moving_fill
    moving_points = moving_boundary_points or _geometry_boundary_points(moving_polygon, max_points=24)
    if not moving_points:
        return []
    moving_complexity = _geometry_point_count(moving_polygon)
    positions: list[tuple[float, float]] = []
    seen: set[tuple[float, float]] = set()
    for _box, obstacle_polygon in _nfp_obstacles(occupied, max_obstacles=MAX_NFP_OBSTACLES):
        _raise_if_deadline_reached(deadline)
        if _deadline_near(deadline, 0.05):
            break
        if moving_complexity + _geometry_point_count(obstacle_polygon) > MAX_NFP_GEOMETRY_POINTS:
            continue
        if moving_fill >= 0.98 and _geometry_bbox_fill_ratio(obstacle_polygon, obstacle_polygon.bounds) >= 0.98:
            continue
        expanded = obstacle_polygon.buffer(max(0.0, spacing), quad_segs=8) if spacing > 1e-6 else obstacle_polygon
        boundary_points = _geometry_boundary_points(expanded, max_points=24)
        for ox, oy in boundary_points:
            _raise_if_deadline_reached(deadline)
            for mx, my in moving_points:
                x = ox - mx + moving_bounds[0]
                y = oy - my + moving_bounds[1]
                if x < min_x - 0.001 or x > max_x + 0.001 or y < min_y - 0.001 or y > max_y + 0.001:
                    continue
                key = (round(min(max(x, min_x), max_x), 3), round(min(max(y, min_y), max_y), 3))
                if key in seen:
                    continue
                seen.add(key)
                positions.append(key)
                if len(positions) >= max_positions:
                    return sorted(positions, key=lambda item: (item[1], item[0]))
    return sorted(positions, key=lambda item: (item[1], item[0]))


def _nfp_obstacles(
    occupied: list[tuple[Box, object | None]],
    *,
    max_obstacles: int,
) -> list[tuple[Box, object]]:
    polygon_obstacles = [(box, polygon) for box, polygon in occupied if polygon is not None]
    if len(polygon_obstacles) <= max_obstacles:
        return polygon_obstacles
    bottom_left = sorted(polygon_obstacles, key=lambda item: (item[0][1], item[0][0]))[: max_obstacles // 2]
    recent = polygon_obstacles[-(max_obstacles - len(bottom_left)) :]
    output: list[tuple[Box, object]] = []
    seen: set[int] = set()
    for item in (*bottom_left, *recent):
        key = id(item[1])
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def _part_bbox(part: PlacedPart, cache: _GeometryCache) -> Box:
    return cache.placed_bbox(part)


def _part_polygon(part: PlacedPart, cache: _GeometryCache):
    return cache.placed_polygon(part)


def _translate_box(box: Box, dx: float, dy: float) -> Box:
    return (box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy)


def _translate_polygon(polygon, dx: float, dy: float):
    if polygon is None:
        return None
    if shapely_translate is None:
        return polygon
    return shapely_translate(polygon, xoff=dx, yoff=dy)


def _footprint_signature(bounds: Box, polygon) -> tuple[float, ...]:
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    if polygon is None:
        return (round(width, 3), round(height, 3))
    centroid = polygon.centroid
    return (
        round(width, 3),
        round(height, 3),
        round(float(polygon.area), 3),
        round(float(centroid.x - bounds[0]), 3),
        round(float(centroid.y - bounds[1]), 3),
    )


def _spatial_index_item_index(item, geometry_ids: dict[int, int]) -> int | None:
    try:
        return int(item)
    except (TypeError, ValueError):
        return geometry_ids.get(id(item))


def _geometry_bbox_fill_ratio(geometry, bounds: Box) -> float:
    width = max(0.0, bounds[2] - bounds[0])
    height = max(0.0, bounds[3] - bounds[1])
    area = width * height
    if area <= 1e-9:
        return 0.0
    return min(1.0, max(0.0, float(geometry.area) / area))


def _geometry_boundary_points(geometry, *, max_points: int) -> tuple[tuple[float, float], ...]:
    coords = list(_geometry_boundary_coords(geometry))
    if not coords:
        return ()
    if len(coords) <= max_points:
        return tuple(coords)
    step = len(coords) / max_points
    return tuple(coords[min(len(coords) - 1, int(index * step))] for index in range(max_points))


def _geometry_boundary_coords(geometry):
    geom_type = getattr(geometry, "geom_type", "")
    if geom_type == "Polygon":
        yield from _ring_coords(geometry.exterior.coords)
        return
    if geom_type in ("MultiPolygon", "GeometryCollection"):
        for item in geometry.geoms:
            yield from _geometry_boundary_coords(item)


def _geometry_point_count(geometry) -> int:
    if geometry is None:
        return 0
    if shapely_get_num_coordinates is not None:
        return int(shapely_get_num_coordinates(geometry))
    geom_type = getattr(geometry, "geom_type", "")
    if geom_type == "Polygon":
        return len(list(geometry.exterior.coords)) + sum(len(list(ring.coords)) for ring in geometry.interiors)
    if geom_type in ("MultiPolygon", "GeometryCollection"):
        return sum(_geometry_point_count(item) for item in geometry.geoms)
    coords = getattr(geometry, "coords", None)
    if coords is None:
        return 0
    try:
        return len(list(coords))
    except NotImplementedError:
        return 0


def _ring_coords(coords) -> tuple[tuple[float, float], ...]:
    return tuple((float(x), float(y)) for x, y in list(coords)[:-1])


def _unique_positions(positions: list[tuple[float, float]]) -> list[tuple[float, float]]:
    seen = set()
    output = []
    for x, y in sorted(positions, key=lambda item: (item[1], item[0])):
        key = (round(x, 3), round(y, 3))
        if key in seen:
            continue
        seen.add(key)
        output.append(key)
    return output


def _add_candidate_value(values: set[float], value: float, minimum: float, maximum: float) -> None:
    if value < minimum - 0.001 or value > maximum + 0.001:
        return
    values.add(round(min(max(value, minimum), maximum), 3))


def _boxes_overlap(left: Box, right: Box, clearance: float) -> bool:
    return not (
        left[2] + clearance <= right[0]
        or right[2] + clearance <= left[0]
        or left[3] + clearance <= right[1]
        or right[3] + clearance <= left[1]
    )


def _occupied_overlap(
    left: Box,
    left_polygon,
    right: Box,
    right_polygon,
    clearance: float,
    *,
    stats: _NestStats | None = None,
    deadline: float | None = None,
) -> bool:
    if not _boxes_overlap(left, right, clearance):
        return False
    if left_polygon is None or right_polygon is None:
        return True
    _raise_if_deadline_reached(deadline)
    if _deadline_near(deadline, 0.02):
        return True
    if _geometry_point_count(left_polygon) + _geometry_point_count(right_polygon) > MAX_EXACT_CHECK_GEOMETRY_POINTS:
        return True
    if stats is not None:
        stats.exact_clearance_check_count += 1
    if clearance <= 1e-6:
        intersection = left_polygon.intersection(right_polygon)
        return bool(not intersection.is_empty and intersection.area > 1e-6)
    return left_polygon.distance(right_polygon) < clearance - 1e-6


@dataclass(frozen=True)
class _HoleContainer:
    owner_instance_id: str
    polygon: object
    bounds: Box
    area: float


def _relocate_parts_into_internal_holes(
    layout: NestedLayout,
    options: ShelfNestOptions,
    *,
    deadline: float | None = None,
    stats: _NestStats | None = None,
    cache: _GeometryCache | None = None,
) -> tuple[NestedLayout, int]:
    if Polygon is None or shapely_translate is None:
        return layout, 0
    cache = cache or _GeometryCache(stats)
    placed = list(layout.placed_parts)
    relocation_count = 0
    while True:
        if deadline is not None and time.monotonic() >= deadline:
            break
        current_score = _nest_score([_part_bbox(part, cache) for part in placed], options.sheet.margin, options.sheet.margin)
        best_move: tuple[tuple[float, ...], int, PlacedPart] | None = None
        holes = _internal_hole_containers(placed, options)
        if not holes:
            break
        for index in _hole_filler_candidate_order(placed, cache):
            part = placed[index]
            if part.placement.locked or not _hole_filler_allowed(part, options):
                continue
            candidate = _best_internal_hole_candidate(part, index, placed, holes, options, deadline=deadline, stats=stats, cache=cache)
            if candidate is None:
                continue
            candidate_placed = [*placed[:index], candidate, *placed[index + 1 :]]
            if validate_layout(NestedLayout(layout.name, layout.sheet, tuple(candidate_placed), layout.spacing)):
                continue
            candidate_score = _nest_score(
                [_part_bbox(item, cache) for item in candidate_placed],
                options.sheet.margin,
                options.sheet.margin,
            )
            if candidate_score >= current_score:
                continue
            if best_move is None or candidate_score < best_move[0]:
                best_move = (candidate_score, index, candidate)
        if best_move is None:
            break
        _score, index, candidate = best_move
        placed[index] = candidate
        relocation_count += 1
    if relocation_count <= 0:
        return layout, 0
    return NestedLayout(layout.name, layout.sheet, tuple(placed), layout.spacing), relocation_count


def _hole_filler_candidate_order(placed: list[PlacedPart], cache: _GeometryCache) -> list[int]:
    return sorted(
        range(len(placed)),
        key=lambda index: (
            -_part_bbox(placed[index], cache)[3],
            -_part_bbox(placed[index], cache)[2],
            _placed_part_area(placed[index], cache),
            placed[index].instance_id,
        ),
    )


def _internal_hole_containers(placed: list[PlacedPart], options: ShelfNestOptions) -> list[_HoleContainer]:
    holes: list[_HoleContainer] = []
    for part in placed:
        if not _hole_parent_allowed(part, options):
            continue
        for contour in part.contours():
            if contour.kind == "outer":
                continue
            polygon = _contour_polygon(contour)
            if polygon is None:
                continue
            target = polygon.buffer(-options.spacing, quad_segs=8) if options.spacing > 1e-6 else polygon
            if target.is_empty or float(target.area) <= 1e-6:
                continue
            holes.append(
                _HoleContainer(
                    owner_instance_id=part.instance_id,
                    polygon=target,
                    bounds=tuple(float(value) for value in target.bounds),
                    area=float(target.area),
                )
            )
    return sorted(holes, key=lambda item: (-item.area, item.owner_instance_id))


def _hole_filler_allowed(part: PlacedPart, options: ShelfNestOptions) -> bool:
    return _part_name_allowed(part.profile.name, options.hole_filler_part_names)


def _hole_parent_allowed(part: PlacedPart, options: ShelfNestOptions) -> bool:
    return _part_name_allowed(part.profile.name, options.hole_parent_part_names)


def _part_name_allowed(name: str, allowed_names: tuple[str, ...] | None) -> bool:
    return allowed_names is None or name in allowed_names


def _contour_polygon(contour) -> object | None:
    if Polygon is None:
        return None
    points = contour.points(max_chord=1.0)
    if len(points) < 3:
        return None
    polygon = Polygon((point.x, point.y) for point in points)
    if polygon.is_empty or float(polygon.area) <= 1e-6:
        return None
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    if polygon.is_empty or float(polygon.area) <= 1e-6:
        return None
    return polygon


def _best_internal_hole_candidate(
    part: PlacedPart,
    part_index: int,
    placed: list[PlacedPart],
    holes: list[_HoleContainer],
    options: ShelfNestOptions,
    *,
    deadline: float | None = None,
    stats: _NestStats | None = None,
    cache: _GeometryCache | None = None,
) -> PlacedPart | None:
    cache = cache or _GeometryCache(stats)
    obstacles = _compaction_obstacles(placed, part_index, [(box, None) for box in options.blocked_boxes], cache)
    best: tuple[tuple[float, ...], PlacedPart] | None = None
    rotations = _hole_filler_rotations(part, options, cache)
    for hole in holes:
        if _deadline_reached(deadline):
            return best[1] if best is not None else None
        if hole.owner_instance_id == part.instance_id:
            continue
        for rotation in rotations:
            if _deadline_reached(deadline):
                return best[1] if best is not None else None
            footprint = cache.footprint(part.profile, rotation)
            if footprint.polygon is None:
                continue
            for dx, dy in _hole_candidate_offsets(hole, footprint):
                candidate = PlacedPart(
                    part.profile,
                    replace(part.placement, dx=dx, dy=dy, rotation_deg=rotation % 360.0, manual=False),
                )
                candidate_box = _part_bbox(candidate, cache)
                candidate_polygon = _part_polygon(candidate, cache)
                if candidate_polygon is None or not hole.polygon.covers(candidate_polygon):
                    continue
                try:
                    fits = _part_fits(
                        candidate,
                        options.sheet,
                        obstacles,
                        options.spacing,
                        stats=stats,
                        cache=cache,
                        deadline=deadline,
                    )
                except TimeoutError:
                    return best[1] if best is not None else None
                if not fits:
                    continue
                score = (
                    candidate_box[1],
                    candidate_box[0],
                    candidate_box[3],
                    candidate_box[2],
                    part.instance_id,
                )
                if best is None or score < best[0]:
                    best = (score, candidate)
    return best[1] if best is not None else None


def _hole_filler_rotations(part: PlacedPart, options: ShelfNestOptions, cache: _GeometryCache) -> tuple[float, ...]:
    rotations = [part.placement.rotation_deg]
    if options.allow_arbitrary_rotation:
        step = options.angle_step_deg or 15.0
        rotations.extend((0.0, 90.0, 180.0, 270.0))
        rotations.extend(_angle_range(step, 0.0))
    return _unique_profile_rotations(part.profile, _unique_angles(tuple(rotations)), cache)


def _hole_candidate_offsets(hole: _HoleContainer, footprint: _Footprint) -> list[tuple[float, float]]:
    hxmin, hymin, hxmax, hymax = hole.bounds
    xmin, ymin, xmax, ymax = footprint.bbox
    width = xmax - xmin
    height = ymax - ymin
    if width <= 0 or height <= 0 or width > hxmax - hxmin + 0.001 or height > hymax - hymin + 0.001:
        return []
    centers = (
        (hxmin, hymin),
        (hxmax - width, hymin),
        (hxmin, hymax - height),
        (hxmax - width, hymax - height),
        ((hxmin + hxmax - width) / 2.0, (hymin + hymax - height) / 2.0),
    )
    points = list(centers)
    for x, y in _geometry_boundary_points(hole.polygon, max_points=24):
        points.append((min(max(x - width / 2.0, hxmin), hxmax - width), min(max(y - height / 2.0, hymin), hymax - height)))
    output = []
    seen = set()
    for x, y in points:
        key = (round(x - xmin, 3), round(y - ymin, 3))
        if key in seen:
            continue
        seen.add(key)
        output.append(key)
    return sorted(output, key=lambda item: (item[1], item[0]))


def _nest_score(boxes: list[Box], margin_x: float, margin_y: float) -> tuple[float, ...]:
    if not boxes:
        return (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    max_x = max(box[2] for box in boxes)
    max_y = max(box[3] for box in boxes)
    used_width = max(0.0, max_x - margin_x)
    used_height = max(0.0, max_y - margin_y)
    skyline_waste_area = _skyline_waste_area(boxes, margin_x, margin_y)
    lower_left_y_mass = sum(max(0.0, box[1] - margin_y) for box in boxes)
    lower_left_x_mass = sum(max(0.0, box[0] - margin_x) for box in boxes)
    return (
        used_height,
        used_width * used_height,
        max_x,
        used_width,
        skyline_waste_area,
        lower_left_y_mass,
        lower_left_x_mass,
        max_y,
    )


def _skyline_waste_area(boxes: list[Box], margin_x: float, margin_y: float) -> float:
    if not boxes:
        return 0.0
    x_values = sorted({round(max(margin_x, box[0]), 6) for box in boxes} | {round(max(margin_x, box[2]), 6) for box in boxes})
    if len(x_values) < 2:
        return 0.0
    skyline_area = 0.0
    for left, right in zip(x_values, x_values[1:]):
        if right <= left + 1e-9:
            continue
        top = max((box[3] for box in boxes if box[0] < right - 1e-9 and box[2] > left + 1e-9), default=margin_y)
        skyline_area += (right - left) * max(0.0, top - margin_y)
    return max(0.0, skyline_area - _box_union_area(boxes))


def _box_union_area(boxes: list[Box]) -> float:
    x_values = sorted({round(box[0], 6) for box in boxes} | {round(box[2], 6) for box in boxes})
    area = 0.0
    for left, right in zip(x_values, x_values[1:]):
        if right <= left + 1e-9:
            continue
        intervals = sorted((box[1], box[3]) for box in boxes if box[0] < right - 1e-9 and box[2] > left + 1e-9)
        merged_length = 0.0
        current_start: float | None = None
        current_end: float | None = None
        for start, end in intervals:
            if current_start is None or current_end is None:
                current_start = start
                current_end = end
                continue
            if start > current_end + 1e-9:
                merged_length += max(0.0, current_end - current_start)
                current_start = start
                current_end = end
            else:
                current_end = max(current_end, end)
        if current_start is not None and current_end is not None:
            merged_length += max(0.0, current_end - current_start)
        area += (right - left) * merged_length
    return max(0.0, area)


def _nest_summary(
    layout: NestedLayout,
    sheet: Sheet,
    *,
    attempt_count: int,
    successful_attempt_count: int,
    best_attempt: str,
    time_limited: bool,
    runtime_ms: float,
    stats: _NestStats,
    parallel_worker_count: int,
    cache: _GeometryCache,
    hole_filler_relocation_count: int = 0,
    parallel_fallback_reason: str | None = None,
    bbox_fallback_count: int = 0,
) -> NestSummary:
    boxes = [_part_bbox(part, cache) for part in layout.placed_parts]
    part_area = sum(_placed_part_area(part, cache) for part in layout.placed_parts)
    usable_ymax = sheet.height - sheet.margin
    if boxes:
        xmin = min(box[0] for box in boxes)
        ymin = min(box[1] for box in boxes)
        xmax = max(box[2] for box in boxes)
        ymax = max(box[3] for box in boxes)
        used_bbox_area = max(0.0, xmax - xmin) * max(0.0, ymax - ymin)
        used_width = max(0.0, xmax - sheet.margin)
        used_height = max(0.0, ymax - sheet.margin)
        used_strip_area = used_width * used_height
        top_free_height = max(0.0, usable_ymax - ymax)
    else:
        used_bbox_area = 0.0
        used_width = 0.0
        used_height = 0.0
        used_strip_area = 0.0
        top_free_height = max(0.0, usable_ymax - sheet.margin)
    usable_area = max(0.0, sheet.width - sheet.margin * 2.0) * max(0.0, sheet.height - sheet.margin * 2.0)
    return NestSummary(
        attempt_count=attempt_count,
        successful_attempt_count=successful_attempt_count,
        best_attempt=best_attempt,
        geometry_engine="polygon-nfp-v1",
        runtime_ms=runtime_ms,
        parallel_worker_count=parallel_worker_count,
        attempts_per_second=_attempts_per_second(attempt_count, runtime_ms),
        candidate_position_count=stats.candidate_position_count,
        nfp_candidate_count=stats.nfp_candidate_count,
        exact_clearance_check_count=stats.exact_clearance_check_count,
        spatial_index_query_count=stats.spatial_index_query_count,
        spatial_index_fallback_count=stats.spatial_index_fallback_count,
        cache_hit_count=stats.cache_hit_count,
        cache_miss_count=stats.cache_miss_count,
        part_area_mm2=part_area,
        used_bbox_area_mm2=used_bbox_area,
        used_width_mm=used_width,
        used_height_mm=used_height,
        used_strip_area_mm2=used_strip_area,
        top_free_height_mm=top_free_height,
        sheet_usable_area_mm2=usable_area,
        packing_utilization_percent=_percent(part_area, used_strip_area),
        bbox_utilization_percent=_percent(part_area, used_bbox_area),
        sheet_utilization_percent=_percent(part_area, usable_area),
        hole_filler_relocation_count=hole_filler_relocation_count,
        time_limited=time_limited,
        parallel_fallback_reason=parallel_fallback_reason,
        bbox_fallback_count=bbox_fallback_count,
    )


def _compact_layout(
    layout: NestedLayout,
    options: ShelfNestOptions,
    *,
    passes: int = 6,
    deadline: float | None = None,
    stats: _NestStats | None = None,
    cache: _GeometryCache | None = None,
) -> NestedLayout:
    cache = cache or _GeometryCache(stats)
    blocked = [(box, None) for box in options.blocked_boxes]
    best_valid = layout
    best_score = _layout_score(layout, options, cache)
    strategies = (
        ("bottom-left", ("y", "x")),
        ("left-bottom", ("x", "y")),
        ("bottom-right", ("y", "x")),
        ("left-top", ("x", "y")),
    )
    for _pass in range(passes):
        if deadline is not None and time.monotonic() >= deadline:
            break
        pass_best: tuple[tuple[float, ...], NestedLayout] | None = None
        for order_policy, axis_order in strategies:
            if deadline is not None and time.monotonic() >= deadline:
                break
            candidate = _compact_layout_sweep(
                best_valid,
                options,
                blocked,
                order_policy,
                axis_order,
                deadline=deadline,
                stats=stats,
                cache=cache,
            )
            if validate_layout(candidate):
                continue
            score = _layout_score(candidate, options, cache)
            if pass_best is None or score < pass_best[0]:
                pass_best = (score, candidate)
        if pass_best is None or pass_best[0] >= best_score:
            break
        best_score, best_valid = pass_best
    return best_valid


def _box_sort_key(box: Box) -> tuple[float, float]:
    return (box[1], box[0])


def _layout_score(layout: NestedLayout, options: ShelfNestOptions, cache: _GeometryCache) -> tuple[float, ...]:
    return _nest_score([_part_bbox(part, cache) for part in layout.placed_parts], options.sheet.margin, options.sheet.margin)


def _compact_layout_sweep(
    layout: NestedLayout,
    options: ShelfNestOptions,
    blocked: list[tuple[Box, object | None]],
    order_policy: str,
    axis_order: tuple[str, str],
    *,
    deadline: float | None = None,
    stats: _NestStats | None = None,
    cache: _GeometryCache | None = None,
) -> NestedLayout:
    cache = cache or _GeometryCache(stats)
    placed = list(layout.placed_parts)
    for index in _compaction_order(placed, cache, order_policy):
        if deadline is not None and time.monotonic() >= deadline:
            return layout
        moved = placed[index]
        for axis in axis_order:
            obstacles = _compaction_obstacles([*placed[:index], moved, *placed[index + 1 :]], index, blocked, cache)
            moved = _slide_part_axis(moved, axis, options, obstacles, deadline=deadline, stats=stats, cache=cache)
        placed[index] = moved
    return NestedLayout(name=layout.name, sheet=layout.sheet, placed_parts=tuple(placed), spacing=layout.spacing)


def _compaction_order(placed: list[PlacedPart], cache: _GeometryCache, policy: str) -> list[int]:
    def key(index: int) -> tuple[float, float, str]:
        box = _part_bbox(placed[index], cache)
        if policy == "bottom-right":
            return (box[1], -box[2], placed[index].instance_id)
        if policy == "left-bottom":
            return (box[0], box[1], placed[index].instance_id)
        if policy == "left-top":
            return (box[0], -box[3], placed[index].instance_id)
        return (box[1], box[0], placed[index].instance_id)

    return sorted(range(len(placed)), key=key)


def _compaction_obstacles(
    placed: list[PlacedPart],
    moving_index: int,
    blocked: list[tuple[Box, object | None]],
    cache: _GeometryCache,
) -> list[tuple[Box, object | None]]:
    obstacles = list(blocked)
    for index, part in enumerate(placed):
        if index == moving_index:
            continue
        obstacles.append((_part_bbox(part, cache), _part_polygon(part, cache)))
    return obstacles


def _slide_part_axis(
    part: PlacedPart,
    axis: str,
    options: ShelfNestOptions,
    obstacles: list[tuple[Box, object | None]],
    *,
    deadline: float | None = None,
    stats: _NestStats | None = None,
    cache: _GeometryCache | None = None,
) -> PlacedPart:
    cache = cache or _GeometryCache(stats)
    bbox = _part_bbox(part, cache)
    current = bbox[0] if axis == "x" else bbox[1]
    lower = options.sheet.margin
    if current <= lower + 0.001:
        return part
    previous = lower
    for position in _slide_positions(lower, current, obstacles, axis, bbox, options.spacing):
        if _deadline_reached(deadline):
            return part
        candidate = _part_with_axis_min(part, axis, position, cache)
        try:
            fits = _part_fits(candidate, options.sheet, obstacles, options.spacing, stats=stats, cache=cache, deadline=deadline)
        except TimeoutError:
            return part
        if fits:
            refined = _refine_slide_position(
                part,
                axis,
                previous,
                position,
                options.sheet,
                obstacles,
                options.spacing,
                deadline=deadline,
                stats=stats,
                cache=cache,
            )
            refined_candidate = _part_with_axis_min(part, axis, refined, cache)
            try:
                refined_fits = _part_fits(
                    refined_candidate,
                    options.sheet,
                    obstacles,
                    options.spacing,
                    stats=stats,
                    cache=cache,
                    deadline=deadline,
                )
            except TimeoutError:
                return candidate
            if refined_fits:
                return refined_candidate
            return candidate
        previous = position
    return part


def _slide_positions(
    lower: float,
    current: float,
    obstacles: list[tuple[Box, object | None]],
    axis: str,
    bbox: Box,
    spacing: float,
) -> list[float]:
    values = {round(lower, 3), round(current, 3)}
    span = max(0.0, current - lower)
    step = 2.0 if span <= 1000.0 else 5.0
    value = lower
    while value < current - 0.001:
        values.add(round(value, 3))
        value += step
    for obstacle, _polygon in obstacles:
        if axis == "x":
            if not _ranges_overlap((bbox[1], bbox[3]), (obstacle[1], obstacle[3]), spacing):
                continue
            values.add(round(obstacle[2] + spacing, 3))
        else:
            if not _ranges_overlap((bbox[0], bbox[2]), (obstacle[0], obstacle[2]), spacing):
                continue
            values.add(round(obstacle[3] + spacing, 3))
    return [value for value in sorted(values) if lower - 0.001 <= value <= current + 0.001]


def _ranges_overlap(left: tuple[float, float], right: tuple[float, float], clearance: float) -> bool:
    return not (left[1] + clearance <= right[0] or right[1] + clearance <= left[0])


def _refine_slide_position(
    part: PlacedPart,
    axis: str,
    lower: float,
    upper: float,
    sheet: Sheet,
    obstacles: list[tuple[Box, object | None]],
    spacing: float,
    *,
    deadline: float | None = None,
    stats: _NestStats | None = None,
    cache: _GeometryCache | None = None,
) -> float:
    if upper <= lower + 0.001:
        return upper
    low = lower
    high = upper
    for _iteration in range(12):
        if _deadline_reached(deadline):
            return upper
        mid = (low + high) / 2.0
        candidate = _part_with_axis_min(part, axis, mid, cache)
        try:
            fits = _part_fits(candidate, sheet, obstacles, spacing, stats=stats, cache=cache, deadline=deadline)
        except TimeoutError:
            return upper
        if fits:
            high = mid
        else:
            low = mid
    return round(high, 3)


def _part_with_axis_min(part: PlacedPart, axis: str, value: float, cache: _GeometryCache | None = None) -> PlacedPart:
    bbox = _part_bbox(part, cache) if cache is not None else part.bbox()
    if axis == "x":
        delta = value - bbox[0]
        placement = replace(part.placement, dx=part.placement.dx + delta)
    else:
        delta = value - bbox[1]
        placement = replace(part.placement, dy=part.placement.dy + delta)
    return PlacedPart(part.profile, placement)


def _part_fits(
    part: PlacedPart,
    sheet: Sheet,
    obstacles: list[tuple[Box, object | None]],
    spacing: float,
    *,
    stats: _NestStats | None = None,
    cache: _GeometryCache | None = None,
    deadline: float | None = None,
) -> bool:
    cache = cache or _GeometryCache(stats)
    bbox = _part_bbox(part, cache)
    if bbox[0] < sheet.margin - 0.001 or bbox[1] < sheet.margin - 0.001:
        return False
    if bbox[2] > sheet.width - sheet.margin + 0.001 or bbox[3] > sheet.height - sheet.margin + 0.001:
        return False
    polygon = None
    for obstacle_box, obstacle_polygon in obstacles:
        if not _boxes_overlap(bbox, obstacle_box, spacing):
            continue
        if polygon is None:
            polygon = _part_polygon(part, cache)
        if _occupied_overlap(bbox, polygon, obstacle_box, obstacle_polygon, spacing, stats=stats, deadline=deadline):
            return False
    return True


def _placed_part_area(part: PlacedPart, cache: _GeometryCache | None = None) -> float:
    polygon = _part_polygon(part, cache) if cache is not None else part.polygon()
    if polygon is not None:
        return float(polygon.area)
    outer = 0.0
    holes = 0.0
    for contour in part.profile.contours:
        area = abs(contour_area(contour))
        if contour.kind == "outer":
            outer += area
        else:
            holes += area
    return max(0.0, outer - holes)


def _percent(value: float, total: float) -> float:
    if total <= 0:
        return 0.0
    return value / total * 100.0


def _deadline_reached(deadline: float | None) -> bool:
    return deadline is not None and time.monotonic() >= deadline


def _packing_deadline(started_at: float, max_runtime_s: float) -> float:
    final_deadline = started_at + max_runtime_s
    if max_runtime_s <= 0.1:
        return final_deadline
    compaction_reserve_s = min(5.0, max(0.25, max_runtime_s * 0.15), max_runtime_s * 0.5)
    return final_deadline - compaction_reserve_s


def _deadline_near(deadline: float | None, remaining_s: float) -> bool:
    return deadline is not None and deadline - time.monotonic() <= remaining_s


def _raise_if_deadline_reached(deadline: float | None) -> None:
    if _deadline_reached(deadline):
        raise TimeoutError("Auto nest time budget reached")


def _attempts_per_second(attempt_count: int, runtime_ms: float) -> float:
    if runtime_ms <= 0:
        return 0.0
    return attempt_count / runtime_ms * 1000.0


def _parallel_worker_count(options: ShelfNestOptions, attempt_count: int) -> int:
    if attempt_count <= 1:
        return 1
    requested = int(options.parallel_workers)
    if requested == 0:
        requested = os.cpu_count() or 1
    return max(1, min(requested, attempt_count, os.cpu_count() or 1, 8))


def _rotated_bbox(profile: PartProfile, rotation_deg: float, cache: _GeometryCache | None = None) -> tuple[float, float, float, float]:
    if cache is not None:
        return cache.footprint(profile, rotation_deg).bbox
    return bbox_for_contours(tuple(contour.transformed(rotation_deg=rotation_deg) for contour in profile.contours))


def _profile_area_bbox(profile: PartProfile) -> float:
    xmin, ymin, xmax, ymax = profile.bbox()
    return (xmax - xmin) * (ymax - ymin)


def _profile_segment_count(profile: PartProfile) -> int:
    count = 0
    for contour in profile.contours:
        if hasattr(contour, "segments"):
            count += len(contour.segments)
        else:
            count += 1
    return count


def _profile_width(profile: PartProfile) -> float:
    xmin, _ymin, xmax, _ymax = profile.bbox()
    return xmax - xmin


def _profile_height(profile: PartProfile) -> float:
    _xmin, ymin, _xmax, ymax = profile.bbox()
    return ymax - ymin


def _profile_max_side(profile: PartProfile) -> float:
    return max(_profile_width(profile), _profile_height(profile))
