"""Cut-chart metadata and calibration coupon project generation."""

from __future__ import annotations

import math
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from ..cut_settings import (
    apply_coupon_results_to_cut_chart,
    cut_chart_row_to_dict,
    default_cut_chart_profile,
    select_cut_settings,
)


def cut_chart_table() -> list[dict[str, Any]]:
    profile = default_cut_chart_profile()
    return [cut_chart_row_to_dict(row) for row in profile.rows]


def cut_chart_profile_metadata() -> dict[str, Any]:
    profile = default_cut_chart_profile()
    return {
        "profile_id": profile.profile_id,
        "version": profile.version,
        "revision": profile.revision,
        "updated_at": profile.updated_at,
        "machine": profile.machine,
        "source": profile.source,
        "notes": list(profile.notes),
    }


def build_coupon_test_project(config: dict[str, Any]) -> dict[str, Any]:
    material = str(config.get("material", "mild_steel"))
    thickness_mm = float(config["thickness_mm"])
    nozzle_mm = float(config.get("nozzle_mm") or 0.0) or None
    base_settings = select_cut_settings(material=material, thickness_mm=thickness_mm, nozzle_mm=nozzle_mm)
    feed_rates = _coupon_values(
        config,
        "feed_rate_mm_min",
        "feed_rate_range",
        default=(base_settings.feed_rate_mm_min,),
        integer=True,
    )
    kerfs = _coupon_values(config, "kerf_width_mm", "kerf_range", default=(base_settings.kerf_width_mm,))
    pierce_delays = _coupon_values(
        config,
        "pierce_delay_s",
        "pierce_delay_range",
        default=(base_settings.pierce_delay_s,),
    )
    coupons = []
    for feed_rate in feed_rates:
        for kerf_width in kerfs:
            for pierce_delay in pierce_delays:
                coupon_id = f"coupon-{len(coupons) + 1:02d}"
                coupons.append(
                    {
                        "coupon_id": coupon_id,
                        "part_name": coupon_id,
                        "material": base_settings.material,
                        "thickness_mm": base_settings.thickness_mm,
                        "nozzle_mm": base_settings.nozzle_mm,
                        "current_a": base_settings.current_a,
                        "feed_rate_mm_min": int(round(feed_rate)),
                        "kerf_width_mm": round(float(kerf_width), 3),
                        "pierce_delay_s": round(float(pierce_delay), 3),
                    }
                )
    if not coupons:
        raise ValueError("Coupon plan must contain at least one coupon")
    if len(coupons) > 36:
        raise ValueError("Coupon plan is limited to 36 coupons")

    coupon_width = float(config.get("coupon_width_mm", 90.0))
    coupon_height = float(config.get("coupon_height_mm", 45.0))
    slot_width = min(coupon_width - 30.0, float(config.get("slot_width_mm", 45.0)))
    slot_height = min(coupon_height - 20.0, float(config.get("slot_height_mm", 8.0)))
    if coupon_width <= 30 or coupon_height <= 25 or slot_width <= 0 or slot_height <= 0:
        raise ValueError("Coupon dimensions are too small for a validation slot")

    spacing = float(config.get("spacing_mm", 12.0))
    columns = max(1, int(config.get("columns", min(6, math.ceil(math.sqrt(len(coupons)))))))
    rows = math.ceil(len(coupons) / columns)
    sheet_width = max(
        float(config.get("sheet_width_mm", 0.0)),
        columns * coupon_width + max(0, columns - 1) * spacing,
    )
    sheet_height = max(
        float(config.get("sheet_height_mm", 0.0)),
        rows * coupon_height + max(0, rows - 1) * spacing,
    )
    parts = []
    placements = []
    candidate_rows = []
    for index, coupon in enumerate(coupons):
        part_name = coupon["part_name"]
        parts.append(_coupon_part_json(part_name, coupon_width, coupon_height, slot_width, slot_height))
        column = index % columns
        row = index // columns
        placements.append(
            {
                "part_name": part_name,
                "instance": 1,
                "dx": coupon_width / 2 + column * (coupon_width + spacing),
                "dy": coupon_height / 2 + row * (coupon_height + spacing),
                "rotation_deg": 0,
                "manual": True,
            }
        )
        candidate_rows.append(
            {
                "row_id": f"fubag40-{coupon['coupon_id']}",
                "revision": str(config.get("revision", "coupon-test")),
                "calibration_state": "starter",
                "coupon_id": coupon["coupon_id"],
                "material": coupon["material"],
                "thickness_mm": coupon["thickness_mm"],
                "nozzle_mm": coupon["nozzle_mm"],
                "current_a": coupon["current_a"],
                "feed_rate_mm_min": coupon["feed_rate_mm_min"],
                "kerf_width_mm": coupon["kerf_width_mm"],
                "pierce_delay_s": coupon["pierce_delay_s"],
                "pierce_height_mm": base_settings.pierce_height_mm,
                "cut_height_mm": base_settings.cut_height_mm,
                "arc_voltage_v": base_settings.cut_volts,
                "thc_enabled": base_settings.thc_enabled,
                "air_pressure_bar": base_settings.air_pressure_bar,
                "notes": ["coupon test candidate"],
            }
        )

    revision = str(config.get("revision", datetime.now(timezone.utc).strftime("%Y%m%d")))
    return {
        "format": "kerfgrid-project",
        "format_version": 2,
        "name": str(config.get("name") or f"fubag40_coupon_{_number_token(thickness_mm)}mm_n{_number_token(base_settings.nozzle_mm)}"),
        "sheet": {"width_mm": round(sheet_width, 3), "height_mm": round(sheet_height, 3)},
        "spacing_mm": spacing,
        "cut": {
            "material": base_settings.material,
            "thickness_mm": base_settings.thickness_mm,
            "nozzle_mm": base_settings.nozzle_mm,
            "feed_rate_mode": "auto",
        },
        "post": {
            "lead_in_mode": "none",
            "lead_in_mm": 0,
            "lead_in_min_hole_diameter_mm": 0,
            "small_hole_threshold_mm": 0,
            "path_tolerance_mm": 0.1,
            "precision": 3,
            "safe_travel": True,
        },
        "cut_chart": {
            "profile_id": "fubag-plasma-40-coupon-test",
            "version": str(config.get("version", "coupon-test")),
            "revision": revision,
            "machine": base_settings.machine,
            "source": "Fubag Plasma 40 coupon-test generated project",
            "rows": candidate_rows,
        },
        "parts": parts,
        "placements": placements,
        "coupon_plan": {
            "machine": base_settings.machine,
            "material": base_settings.material,
            "thickness_mm": base_settings.thickness_mm,
            "nozzle_mm": base_settings.nozzle_mm,
            "revision": revision,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "coupon_width_mm": coupon_width,
            "coupon_height_mm": coupon_height,
            "slot_width_mm": slot_width,
            "slot_height_mm": slot_height,
            "coupons": coupons,
            "candidate_rows": candidate_rows,
        },
        "simulation": {"playback_rate": 20, "rapid_rate_mm_min": 8000},
    }


def import_coupon_results(payload: dict[str, Any]) -> dict[str, Any]:
    project = deepcopy(payload.get("project", payload.get("base_project", {})))
    if not isinstance(project, dict):
        raise ValueError("Coupon results project must be an object")
    result = apply_coupon_results_to_cut_chart({**payload, "project": project})
    project["cut_chart"] = result["cut_chart"]
    return {
        "project": project,
        "cut_chart": result["cut_chart"],
        "measured_rows": result["measured_rows"],
        "imported_count": result["imported_count"],
        "coupon_ids": result["coupon_ids"],
    }


def _coupon_values(
    config: dict[str, Any],
    value_key: str,
    range_key: str,
    *,
    default: tuple[float, ...],
    integer: bool = False,
) -> tuple[float, ...]:
    plural_key = f"{value_key}s"
    value = config.get(plural_key, config.get(value_key))
    if value is None and range_key in config:
        range_value = config[range_key]
        if not isinstance(range_value, dict):
            raise ValueError(f"{range_key} must be an object with start/stop/step")
        values = _range_values(float(range_value["start"]), float(range_value["stop"]), float(range_value.get("step", 1)))
    elif value is None:
        values = default
    elif isinstance(value, (list, tuple)):
        values = tuple(float(item) for item in value)
    else:
        values = (float(value),)
    if not values:
        raise ValueError(f"{value_key} cannot be empty")
    cleaned = []
    for item in values:
        if item <= 0:
            raise ValueError(f"{value_key} must contain positive values")
        cleaned.append(float(int(round(item))) if integer else round(float(item), 3))
    return tuple(cleaned)


def _range_values(start: float, stop: float, step: float) -> tuple[float, ...]:
    if step <= 0:
        raise ValueError("Coupon range step must be positive")
    if stop < start:
        raise ValueError("Coupon range stop must be greater than or equal to start")
    values = []
    value = start
    while value <= stop + step / 1000:
        values.append(round(value, 6))
        value += step
    return tuple(values)


def _coupon_part_json(name: str, width: float, height: float, slot_width: float, slot_height: float) -> dict[str, Any]:
    return {
        "name": name,
        "quantity": 1,
        "contours": [
            _rectangle_contour_json(f"{name}_outer", "outer", width, height),
            _rectangle_contour_json(f"{name}_slot", "hole", slot_width, slot_height),
        ],
    }


def _rectangle_contour_json(name: str, kind: str, width: float, height: float) -> dict[str, Any]:
    points = [
        {"x": -width / 2, "y": -height / 2},
        {"x": width / 2, "y": -height / 2},
        {"x": width / 2, "y": height / 2},
        {"x": -width / 2, "y": height / 2},
    ]
    return {
        "type": "path",
        "kind": kind,
        "name": name,
        "segments": [{"type": "line", "start": start, "end": end} for start, end in zip(points, [*points[1:], points[0]])],
    }


def _number_token(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".").replace(".", "p")
