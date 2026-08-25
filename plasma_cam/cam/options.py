"""CAM options and immutable planning records."""

from __future__ import annotations

from dataclasses import dataclass

from ..cut_settings import CutSettings
from ..model import Point


@dataclass(frozen=True)
class TravelObstacle:
    xmin: float
    ymin: float
    xmax: float
    ymax: float
    label: str = "obstacle"

    def expanded(self, clearance: float) -> "TravelObstacle":
        return TravelObstacle(
            self.xmin - clearance,
            self.ymin - clearance,
            self.xmax + clearance,
            self.ymax + clearance,
            self.label,
        )


@dataclass(frozen=True)
class CutTab:
    contour_name: str
    x: float
    y: float
    length: float = 8.0


@dataclass(frozen=True)
class LeadOverride:
    contour_name: str
    start_x: float | None = None
    start_y: float | None = None
    pierce_x: float | None = None
    pierce_y: float | None = None
    lead_in_mode: str | None = None
    lead_in: float | None = None
    lead_out: float | None = None


@dataclass(frozen=True)
class LeadMove:
    contour_name: str
    contour_kind: str
    pierce: Point
    start: Point
    lead_in_mode: str
    lead_in: float
    lead_in_points: tuple[Point, ...] = ()
    lead_out_points: tuple[Point, ...] = ()
    small_feature: bool = False


@dataclass(frozen=True)
class QtPlasmaCOptions:
    units: str = "mm"
    material: int | None = None
    material_wait_s: float = 1.0
    kerf_width: float | None = None
    lead_in_mode: str = "auto"
    lead_in: float = 5.0
    lead_out: float = 0.0
    lead_in_min_hole_diameter: float = 20.0
    small_hole_threshold: float = 37.0
    small_shape_threshold: float = 37.0
    small_hole_speed_percent: float = 65.0
    small_hole_disable_thc: bool = True
    small_hole_overburn: float = 0.0
    small_hole_torch_off_before_end: float = 0.0
    path_tolerance: float = 0.1
    precision: int = 3
    use_material_feed: bool = True
    include_comments: bool = True
    validate_before_write: bool = True
    cut_settings: CutSettings | None = None
    emit_temporary_material: bool = True
    temporary_material_number: int = 0
    safe_travel: bool = True
    travel_clearance: float = 8.0
    travel_bounds: tuple[float, float, float, float] | None = None
    travel_obstacles: tuple[TravelObstacle, ...] = ()
    avoid_completed_contours: bool = True
    optimize_cut_order: bool = True
    keep_part_contours_together: bool = True
    cut_order_strategy: str = "nearest"
    cut_order_groups: tuple[str, ...] = ()
    heat_spread_weight: float = 0.35
    heat_lookback: int = 3
    tabs: tuple[CutTab, ...] = ()
    lead_overrides: tuple[LeadOverride, ...] = ()
    common_line_cutting: bool = False
    common_line_tolerance: float = 0.05
    kerf_offset_fallback: str = "centerline"
    open_path_mode: str = "centerline"
    auto_tabs: bool = False
    auto_tab_count: int = 2
    auto_tab_length: float = 8.0
    auto_tab_min_outer_diameter: float = 60.0

    def __post_init__(self) -> None:
        if self.cut_settings is not None and self.material is not None and self.emit_temporary_material:
            raise ValueError("Use either QtPlasmaC material number or temporary cut settings, not both")
        if self.cut_settings is not None and not self.emit_temporary_material and self.use_material_feed and self.material is None:
            raise ValueError("Cut settings require temporary or fixed QtPlasmaC material when material feed is enabled")
        if self.material_wait_s < 0:
            raise ValueError("Material wait cannot be negative")
        if self.kerf_width is not None and self.kerf_width < 0:
            raise ValueError("Kerf width cannot be negative")
        if self.lead_in < 0:
            raise ValueError("Lead-in cannot be negative")
        if self.lead_out < 0:
            raise ValueError("Lead-out cannot be negative")
        if self.lead_in_min_hole_diameter < 0:
            raise ValueError("Lead-in minimum hole diameter cannot be negative")
        if self.small_hole_threshold < 0:
            raise ValueError("Small-hole threshold cannot be negative")
        if self.small_shape_threshold < 0:
            raise ValueError("Small-shape threshold cannot be negative")
        if self.small_hole_overburn < 0:
            raise ValueError("Small-feature overburn cannot be negative")
        if self.small_hole_torch_off_before_end < 0:
            raise ValueError("Small-feature torch-off-before-end cannot be negative")
        if self.lead_in_mode not in ("auto", "arc", "line", "none"):
            raise ValueError("Lead-in mode must be auto, arc, line, or none")
        if self.travel_clearance < 0:
            raise ValueError("Travel clearance cannot be negative")
        if self.common_line_tolerance <= 0:
            raise ValueError("Common-line tolerance must be positive")
        if self.kerf_offset_fallback not in ("block", "centerline"):
            raise ValueError("Kerf offset fallback must be block or centerline")
        if self.open_path_mode not in ("block", "centerline"):
            raise ValueError("Open path mode must be block or centerline")
        if self.cut_order_strategy not in ("nearest", "lower_left", "heat_spread"):
            raise ValueError("Cut order strategy must be nearest, lower_left, or heat_spread")
        if self.heat_spread_weight < 0:
            raise ValueError("Heat spread weight cannot be negative")
        if self.heat_lookback < 1:
            raise ValueError("Heat lookback must be positive")
        if self.auto_tab_count < 1:
            raise ValueError("Auto tab count must be positive")
        if self.auto_tab_length < 0:
            raise ValueError("Auto tab length cannot be negative")
        if self.auto_tab_min_outer_diameter < 0:
            raise ValueError("Auto tab minimum diameter cannot be negative")
        for tab in self.tabs:
            if tab.length < 0:
                raise ValueError("Tab length cannot be negative")
        for override in self.lead_overrides:
            if override.lead_in_mode is not None and override.lead_in_mode not in ("auto", "arc", "line", "none"):
                raise ValueError("Lead override mode must be auto, arc, line, or none")
