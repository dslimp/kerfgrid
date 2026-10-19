"""Cut settings for small air plasma machines."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CutChartRow:
    material: str
    thickness_mm: float
    nozzle_mm: float
    current_a: int
    feed_rate_mm_min: int
    kerf_width_mm: float
    pierce_delay_s: float
    pierce_height_mm: float = 3.0
    cut_height_mm: float = 1.5
    cut_volts: float | None = None
    thc_enabled: bool = True
    air_pressure_bar: float = 5.0
    small_hole_threshold_mm: float | None = None
    small_shape_threshold_mm: float | None = None
    small_hole_speed_percent: float | None = None
    small_hole_overburn_mm: float | None = None
    small_hole_torch_off_before_end_mm: float | None = None
    notes: tuple[str, ...] = ()
    row_id: str = ""
    revision: str = ""
    calibration_state: str = "starter"
    measured_at: str = ""
    operator: str = ""
    coupon_id: str = ""
    quality_notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class CutSettings:
    machine: str
    material: str
    thickness_mm: float
    nozzle_mm: float
    current_a: int
    feed_rate_mm_min: int
    kerf_width_mm: float
    pierce_height_mm: float
    pierce_delay_s: float
    cut_height_mm: float
    cut_volts: float | None
    thc_enabled: bool
    air_pressure_bar: float
    small_hole_threshold_mm: float
    small_shape_threshold_mm: float
    small_hole_speed_percent: float
    small_hole_overburn_mm: float
    small_hole_torch_off_before_end_mm: float
    source: str
    notes: tuple[str, ...] = ()
    profile_id: str = ""
    profile_version: str = ""
    profile_revision: str = ""
    row_id: str = ""
    row_revision: str = ""
    calibration_state: str = "starter"
    measured_at: str = ""
    operator: str = ""
    coupon_id: str = ""
    quality_notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class CutChartProfile:
    profile_id: str
    version: str
    machine: str
    source: str
    rows: tuple[CutChartRow, ...]
    revision: str = ""
    updated_at: str = ""
    notes: tuple[str, ...] = ()


DEFAULT_CUT_PROFILE_PATH = (
    Path(__file__).resolve().parent / "data" / "cut_profiles" / "fubag-plasma-40.json"
)
DEFAULT_SMALL_HOLE_SPEED_PERCENT = 65.0
DEFAULT_SMALL_HOLE_OVERBURN_MM = 0.0
DEFAULT_SMALL_HOLE_TORCH_OFF_BEFORE_END_MM = 0.0


def _calibration_state(value: object) -> str:
    state = str(value or "starter").strip().lower()
    if state not in ("starter", "measured"):
        raise ValueError(f"Unsupported cut chart calibration_state: {state}")
    return state


def _string_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value else ()
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value if str(item))
    return (str(value),)


def _default_row_id(
    material: str,
    thickness_mm: float,
    nozzle_mm: float,
    calibration_state: str,
    revision: str,
) -> str:
    suffix = f"-{revision}" if revision else ""
    return (
        f"{material}-{_number_id(thickness_mm)}mm-n{_number_id(nozzle_mm)}-"
        f"{calibration_state}{suffix}"
    )


def _number_id(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".").replace(".", "p")


def load_cut_chart_profile(path: str | Path = DEFAULT_CUT_PROFILE_PATH) -> CutChartProfile:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = tuple(_row_from_dict(item) for item in data.get("rows", ()))
    if not rows:
        raise ValueError(f"Cut chart profile {path} has no rows")
    return CutChartProfile(
        profile_id=str(data.get("profile_id") or data.get("id") or "cut-profile"),
        version=str(data.get("version") or "0"),
        machine=str(data.get("machine") or "unknown"),
        source=str(data.get("source") or ""),
        rows=rows,
        revision=str(data.get("revision") or data.get("profile_revision") or data.get("version") or "0"),
        updated_at=str(data.get("updated_at") or ""),
        notes=_string_tuple(data.get("notes", ())),
    )


def default_cut_chart_profile() -> CutChartProfile:
    return FUBAG_PLASMA_40_PROFILE


def cut_chart_rows_from_dicts(rows: object) -> tuple[CutChartRow, ...]:
    if not isinstance(rows, list):
        raise ValueError("Cut chart rows must be a list")
    parsed = tuple(_row_from_dict(item) for item in rows if isinstance(item, dict))
    if len(parsed) != len(rows):
        raise ValueError("Cut chart rows must be objects")
    if not parsed:
        raise ValueError("Cut chart profile has no rows")
    return parsed


def cut_chart_row_to_dict(row: CutChartRow) -> dict[str, Any]:
    return _row_to_chart_dict(row)


def apply_coupon_results_to_cut_chart(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Coupon results payload must be an object")
    project = payload.get("project", payload.get("base_project"))
    if project is not None and not isinstance(project, dict):
        raise ValueError("Coupon results project must be an object")
    chart = payload.get("cut_chart")
    if chart is None and isinstance(project, dict):
        chart = project.get("cut_chart")
    if chart is not None and not isinstance(chart, dict):
        raise ValueError("Coupon results cut_chart must be an object")

    base_chart = _coupon_base_chart(chart)
    existing_rows = tuple(_row_from_dict(row) for row in base_chart["rows"])
    result_items = _coupon_result_items(payload)
    measured_rows = [
        _coupon_result_measured_row(
            result,
            existing_rows=existing_rows,
            revision=str(payload.get("revision") or base_chart.get("revision") or "measured"),
        )
        for result in result_items
    ]
    if not measured_rows:
        raise ValueError("Coupon results payload has no results")

    measured_by_key = {_row_match_key(row): row for row in measured_rows}
    measured_coupon_ids = {row.coupon_id for row in measured_rows if row.coupon_id}
    preserved_rows = []
    for row in existing_rows:
        if row.calibration_state == "measured" and (
            _row_match_key(row) in measured_by_key or row.coupon_id in measured_coupon_ids
        ):
            continue
        preserved_rows.append(_row_to_chart_dict(row))

    updated_rows = [*preserved_rows, *(_row_to_chart_dict(row) for row in measured_rows)]
    updated_chart = {
        **base_chart,
        "profile_id": str(payload.get("profile_id") or base_chart.get("profile_id") or "project-measured-cut-chart"),
        "version": str(payload.get("version") or base_chart.get("version") or "measured"),
        "revision": str(payload.get("revision") or base_chart.get("revision") or "measured"),
        "source": str(payload.get("source") or "Project measured coupon results"),
        "rows": updated_rows,
    }
    return {
        "cut_chart": updated_chart,
        "measured_rows": [_row_to_chart_dict(row) for row in measured_rows],
        "imported_count": len(measured_rows),
        "coupon_ids": [row.coupon_id for row in measured_rows],
    }


def _row_from_dict(data: dict[str, object]) -> CutChartRow:
    cut_volts = data.get("cut_volts", data.get("arc_voltage_v"))
    material = str(data["material"])
    thickness_mm = float(data["thickness_mm"])
    nozzle_mm = float(data["nozzle_mm"])
    calibration_state = _calibration_state(data.get("calibration_state", "starter"))
    revision = str(data.get("revision") or data.get("row_revision") or "")
    return CutChartRow(
        material=material,
        thickness_mm=thickness_mm,
        nozzle_mm=nozzle_mm,
        current_a=int(data["current_a"]),
        feed_rate_mm_min=int(data["feed_rate_mm_min"]),
        kerf_width_mm=float(data["kerf_width_mm"]),
        pierce_delay_s=float(data["pierce_delay_s"]),
        pierce_height_mm=float(data.get("pierce_height_mm", 3.0)),
        cut_height_mm=float(data.get("cut_height_mm", 1.5)),
        cut_volts=float(cut_volts) if cut_volts is not None else None,
        thc_enabled=bool(data.get("thc_enabled", True)),
        air_pressure_bar=float(data.get("air_pressure_bar", 5.0)),
        small_hole_threshold_mm=_optional_nonnegative_float(data.get("small_hole_threshold_mm")),
        small_shape_threshold_mm=_optional_nonnegative_float(data.get("small_shape_threshold_mm")),
        small_hole_speed_percent=_optional_percent(data.get("small_hole_speed_percent")),
        small_hole_overburn_mm=_optional_nonnegative_float(data.get("small_hole_overburn_mm")),
        small_hole_torch_off_before_end_mm=_optional_nonnegative_float(
            data.get("small_hole_torch_off_before_end_mm")
        ),
        notes=_string_tuple(data.get("notes", ())),
        row_id=str(
            data.get("row_id")
            or _default_row_id(material, thickness_mm, nozzle_mm, calibration_state, revision)
        ),
        revision=revision,
        calibration_state=calibration_state,
        measured_at=str(data.get("measured_at") or ""),
        operator=str(data.get("operator") or ""),
        coupon_id=str(data.get("coupon_id") or ""),
        quality_notes=_string_tuple(data.get("quality_notes", ())),
    )


def _row_to_chart_dict(row: CutChartRow) -> dict[str, Any]:
    return {
        "material": row.material,
        "thickness_mm": row.thickness_mm,
        "nozzle_mm": row.nozzle_mm,
        "current_a": row.current_a,
        "feed_rate_mm_min": row.feed_rate_mm_min,
        "kerf_width_mm": row.kerf_width_mm,
        "pierce_delay_s": row.pierce_delay_s,
        "pierce_height_mm": row.pierce_height_mm,
        "cut_height_mm": row.cut_height_mm,
        "arc_voltage_v": cut_voltage_for_row(row),
        "thc_enabled": row.thc_enabled,
        "air_pressure_bar": row.air_pressure_bar,
        "small_hole_threshold_mm": _row_small_hole_threshold(row),
        "small_shape_threshold_mm": _row_small_shape_threshold(row),
        "small_hole_speed_percent": _row_small_hole_speed_percent(row),
        "small_hole_overburn_mm": _row_small_hole_overburn(row),
        "small_hole_torch_off_before_end_mm": _row_small_hole_torch_off_before_end(row),
        "notes": list(row.notes),
        "row_id": row.row_id,
        "revision": row.revision,
        "calibration_state": row.calibration_state,
        "measured_at": row.measured_at,
        "operator": row.operator,
        "coupon_id": row.coupon_id,
        "quality_notes": list(row.quality_notes),
    }


def _coupon_base_chart(chart: object) -> dict[str, Any]:
    profile = default_cut_chart_profile()
    if isinstance(chart, dict) and chart.get("rows"):
        rows = chart.get("rows")
        if not isinstance(rows, list):
            raise ValueError("Coupon results cut_chart rows must be a list")
        return {
            "profile_id": str(chart.get("profile_id") or chart.get("id") or "project-cut-chart"),
            "version": str(chart.get("version") or ""),
            "revision": str(chart.get("revision") or chart.get("profile_revision") or chart.get("version") or ""),
            "machine": str(chart.get("machine") or profile.machine),
            "source": str(chart.get("source") or "Project cut chart"),
            "rows": [dict(row) for row in rows if isinstance(row, dict)],
        }
    return {
        "profile_id": profile.profile_id,
        "version": profile.version,
        "revision": profile.revision,
        "machine": profile.machine,
        "source": profile.source,
        "rows": [_row_to_chart_dict(row) for row in profile.rows],
    }


def _coupon_result_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    value = payload.get("results", payload.get("coupon_results", payload.get("rows")))
    if value is None:
        value = payload.get("result")
    if value is None:
        value = payload
    if isinstance(value, dict):
        items = [value]
    elif isinstance(value, list):
        items = value
    else:
        raise ValueError("Coupon results must be an object or a list")
    if not all(isinstance(item, dict) for item in items):
        raise ValueError("Coupon results must contain objects")
    return [dict(item) for item in items]


def _coupon_result_measured_row(
    result: dict[str, Any],
    *,
    existing_rows: tuple[CutChartRow, ...],
    revision: str,
) -> CutChartRow:
    material = normalize_material(_required_text(result, "material"))
    thickness_mm = _required_positive_float(result, "thickness_mm")
    nozzle_mm = _required_positive_float(result, "nozzle_mm")
    current_a = int(round(_required_positive_float(result, "current_a")))
    feed_rate_mm_min = int(round(_required_positive_float(result, "feed_rate_mm_min")))
    kerf_width_mm = _required_positive_float(result, "kerf_width_mm")
    pierce_delay_s = _required_nonnegative_float(result, "pierce_delay_s")
    cut_height_mm = _required_positive_float(result, "cut_height_mm")
    cut_volts = _required_positive_float(result, "arc_voltage_v")
    thc_enabled = _required_bool(result, "thc_enabled")
    coupon_id = _required_text(result, "coupon_id")
    operator = _required_text(result, "operator")
    measured_at = _required_timestamp(result, "measured_at")
    quality_notes = _string_tuple(result.get("quality_notes", ()))
    base = _matching_cut_chart_row(existing_rows, material, thickness_mm, nozzle_mm)
    return CutChartRow(
        material=material,
        thickness_mm=round(thickness_mm, 3),
        nozzle_mm=round(nozzle_mm, 3),
        current_a=current_a,
        feed_rate_mm_min=feed_rate_mm_min,
        kerf_width_mm=round(kerf_width_mm, 3),
        pierce_delay_s=round(pierce_delay_s, 3),
        pierce_height_mm=base.pierce_height_mm if base else 3.0,
        cut_height_mm=round(cut_height_mm, 3),
        cut_volts=round(cut_volts, 3),
        thc_enabled=thc_enabled,
        air_pressure_bar=base.air_pressure_bar if base else 5.0,
        small_hole_threshold_mm=_optional_nonnegative_float(result.get("small_hole_threshold_mm"))
        if result.get("small_hole_threshold_mm") is not None
        else (base.small_hole_threshold_mm if base else None),
        small_shape_threshold_mm=_optional_nonnegative_float(result.get("small_shape_threshold_mm"))
        if result.get("small_shape_threshold_mm") is not None
        else (base.small_shape_threshold_mm if base else None),
        small_hole_speed_percent=_optional_percent(result.get("small_hole_speed_percent"))
        if result.get("small_hole_speed_percent") is not None
        else (base.small_hole_speed_percent if base else None),
        small_hole_overburn_mm=_optional_nonnegative_float(result.get("small_hole_overburn_mm"))
        if result.get("small_hole_overburn_mm") is not None
        else (base.small_hole_overburn_mm if base else None),
        small_hole_torch_off_before_end_mm=_optional_nonnegative_float(
            result.get("small_hole_torch_off_before_end_mm")
        )
        if result.get("small_hole_torch_off_before_end_mm") is not None
        else (base.small_hole_torch_off_before_end_mm if base else None),
        notes=("coupon test measured result",),
        row_id=str(result.get("row_id") or _measured_coupon_row_id(material, thickness_mm, nozzle_mm, coupon_id)),
        revision=str(result.get("revision") or revision),
        calibration_state="measured",
        measured_at=measured_at,
        operator=operator,
        coupon_id=coupon_id,
        quality_notes=quality_notes,
    )


def _matching_cut_chart_row(
    rows: tuple[CutChartRow, ...],
    material: str,
    thickness_mm: float,
    nozzle_mm: float,
) -> CutChartRow | None:
    for row in rows:
        if (
            row.material == material
            and abs(row.thickness_mm - thickness_mm) < 1e-6
            and abs(row.nozzle_mm - nozzle_mm) < 1e-6
            and row.calibration_state == "measured"
        ):
            return row
    for row in rows:
        if (
            row.material == material
            and abs(row.thickness_mm - thickness_mm) < 1e-6
            and abs(row.nozzle_mm - nozzle_mm) < 1e-6
        ):
            return row
    return None


def _row_match_key(row: CutChartRow) -> tuple[str, float, float]:
    return (row.material, round(row.thickness_mm, 6), round(row.nozzle_mm, 6))


def _required_text(data: dict[str, Any], field: str) -> str:
    value = data.get(field)
    if value is None:
        raise ValueError(f"Coupon result missing required metadata field: {field}")
    text = str(value).strip()
    if not text:
        raise ValueError(f"Coupon result metadata field cannot be empty: {field}")
    return text


def _required_positive_float(data: dict[str, Any], field: str) -> float:
    value = _required_float(data, field)
    if value <= 0:
        raise ValueError(f"Coupon result numeric field must be positive: {field}")
    return value


def _required_nonnegative_float(data: dict[str, Any], field: str) -> float:
    value = _required_float(data, field)
    if value < 0:
        raise ValueError(f"Coupon result numeric field cannot be negative: {field}")
    return value


def _required_float(data: dict[str, Any], field: str) -> float:
    if field not in data:
        raise ValueError(f"Coupon result missing required numeric field: {field}")
    try:
        return float(data[field])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Coupon result numeric field is invalid: {field}") from exc


def _required_bool(data: dict[str, Any], field: str) -> bool:
    if field not in data:
        raise ValueError(f"Coupon result missing required metadata field: {field}")
    value = data[field]
    if isinstance(value, bool):
        return value
    raise ValueError(f"Coupon result metadata field must be boolean: {field}")


def _required_timestamp(data: dict[str, Any], field: str) -> str:
    text = _required_text(data, field)
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Coupon result metadata field must be ISO timestamp: {field}") from exc
    return text


def _optional_nonnegative_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    parsed = float(value)
    if parsed < 0:
        raise ValueError("Cut chart optional numeric field cannot be negative")
    return parsed


def _optional_percent(value: object) -> float | None:
    if value is None or value == "":
        return None
    parsed = float(value)
    if parsed <= 0 or parsed > 100:
        raise ValueError("Cut chart percentage field must be in the 0-100 range")
    return parsed


def _measured_coupon_row_id(
    material: str,
    thickness_mm: float,
    nozzle_mm: float,
    coupon_id: str,
) -> str:
    token = "".join(ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in coupon_id.strip())
    token = "-".join(part for part in token.split("-") if part)
    return (
        f"{material}-{_number_id(thickness_mm)}mm-n{_number_id(nozzle_mm)}-"
        f"measured-{token or 'coupon'}"
    )


FUBAG_PLASMA_40_PROFILE = load_cut_chart_profile()
FUBAG_PLASMA_40_SOURCE = FUBAG_PLASMA_40_PROFILE.source
FUBAG_PLASMA_40_MILD_STEEL = FUBAG_PLASMA_40_PROFILE.rows
FUBAG_PLASMA_40_PROFILE_ID = FUBAG_PLASMA_40_PROFILE.profile_id
FUBAG_PLASMA_40_PROFILE_VERSION = FUBAG_PLASMA_40_PROFILE.version
FUBAG_PLASMA_40_PROFILE_REVISION = FUBAG_PLASMA_40_PROFILE.revision


def normalize_material(material: str) -> str:
    key = material.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "steel": "mild_steel",
        "ms": "mild_steel",
        "mild": "mild_steel",
        "mild_steel": "mild_steel",
        "carbon_steel": "mild_steel",
        "black_steel": "mild_steel",
    }
    try:
        return aliases[key]
    except KeyError as exc:
        raise ValueError(f"Unsupported material for Fubag Plasma 40 chart: {material}") from exc


def recommended_nozzle_for_thickness(thickness_mm: float) -> float:
    if thickness_mm <= 0:
        raise ValueError("Metal thickness must be positive")
    if thickness_mm <= 2.0:
        return 0.8
    return 0.9


def select_cut_settings(
    *,
    material: str = "mild_steel",
    thickness_mm: float,
    nozzle_mm: float | None = None,
    chart: tuple[CutChartRow, ...] = FUBAG_PLASMA_40_MILD_STEEL,
    machine: str = "Fubag Plasma 40",
    source: str = FUBAG_PLASMA_40_SOURCE,
    profile_id: str = FUBAG_PLASMA_40_PROFILE_ID,
    profile_version: str = FUBAG_PLASMA_40_PROFILE_VERSION,
    profile_revision: str = FUBAG_PLASMA_40_PROFILE_REVISION,
) -> CutSettings:
    material_key = normalize_material(material)
    if thickness_mm <= 0:
        raise ValueError("Metal thickness must be positive")
    selected_nozzle = nozzle_mm if nozzle_mm is not None else recommended_nozzle_for_thickness(thickness_mm)
    rows = _preferred_rows(
        (
            row
            for row in chart
            if row.material == material_key and abs(row.nozzle_mm - selected_nozzle) < 1e-6
        )
    )
    if not rows:
        raise ValueError(f"No cut chart rows for {material_key} with {selected_nozzle:g} mm nozzle")

    if thickness_mm < rows[0].thickness_mm or thickness_mm > rows[-1].thickness_mm:
        raise ValueError(
            f"No Fubag Plasma 40 starter row for {material_key} {thickness_mm:g} mm "
            f"with {selected_nozzle:g} mm nozzle; supported range is "
            f"{rows[0].thickness_mm:g}-{rows[-1].thickness_mm:g} mm"
        )

    for row in rows:
        if abs(row.thickness_mm - thickness_mm) < 1e-6:
            return _settings_from_row(
                row,
                thickness_mm,
                row.notes,
                machine=machine,
                source=source,
                profile_id=profile_id,
                profile_version=profile_version,
                profile_revision=profile_revision,
            )

    lower, upper = _bounds_for_thickness(rows, thickness_mm)
    ratio = (thickness_mm - lower.thickness_mm) / (upper.thickness_mm - lower.thickness_mm)
    notes = tuple(
        item
        for item in (
            f"Interpolated between {lower.thickness_mm:g} mm and {upper.thickness_mm:g} mm starter rows",
            *lower.notes,
            *upper.notes,
        )
        if item
    )
    return CutSettings(
        machine=machine,
        material=material_key,
        thickness_mm=round(thickness_mm, 3),
        nozzle_mm=upper.nozzle_mm,
        current_a=upper.current_a,
        feed_rate_mm_min=_round_to_step(_lerp(lower.feed_rate_mm_min, upper.feed_rate_mm_min, ratio), 10),
        kerf_width_mm=_round_to_step(_lerp(lower.kerf_width_mm, upper.kerf_width_mm, ratio), 0.05),
        pierce_height_mm=_round_to_step(_lerp(lower.pierce_height_mm, upper.pierce_height_mm, ratio), 0.05),
        pierce_delay_s=_round_to_step(_lerp(lower.pierce_delay_s, upper.pierce_delay_s, ratio), 0.05),
        cut_height_mm=_round_to_step(_lerp(lower.cut_height_mm, upper.cut_height_mm, ratio), 0.05),
        cut_volts=_round_to_step(_lerp(_row_cut_volts(lower), _row_cut_volts(upper), ratio), 0.5),
        thc_enabled=lower.thc_enabled and upper.thc_enabled,
        air_pressure_bar=_round_to_step(_lerp(lower.air_pressure_bar, upper.air_pressure_bar, ratio), 0.1),
        small_hole_threshold_mm=_round_to_step(
            _lerp(_row_small_hole_threshold(lower), _row_small_hole_threshold(upper), ratio),
            0.5,
        ),
        small_shape_threshold_mm=_round_to_step(
            _lerp(_row_small_shape_threshold(lower), _row_small_shape_threshold(upper), ratio),
            0.5,
        ),
        small_hole_speed_percent=_round_to_step(
            _lerp(_row_small_hole_speed_percent(lower), _row_small_hole_speed_percent(upper), ratio),
            1.0,
        ),
        small_hole_overburn_mm=_round_to_step(
            _lerp(_row_small_hole_overburn(lower), _row_small_hole_overburn(upper), ratio),
            0.1,
        ),
        small_hole_torch_off_before_end_mm=_round_to_step(
            _lerp(
                _row_small_hole_torch_off_before_end(lower),
                _row_small_hole_torch_off_before_end(upper),
                ratio,
            ),
            0.1,
        ),
        source=source,
        notes=notes,
        profile_id=profile_id,
        profile_version=profile_version,
        profile_revision=profile_revision,
        row_id=f"interpolated:{lower.row_id}:{upper.row_id}",
        row_revision=_join_unique((lower.revision, upper.revision)),
        calibration_state="measured"
        if lower.calibration_state == "measured" and upper.calibration_state == "measured"
        else "starter",
        coupon_id=_join_unique((lower.coupon_id, upper.coupon_id)),
        quality_notes=tuple((*lower.quality_notes, *upper.quality_notes)),
    )


def format_qtplasmac_material_comment(
    settings: CutSettings,
    *,
    material_number: int = 0,
    name: str | None = None,
) -> str:
    params = [
        "o=0",
        f"ph={_fmt(settings.pierce_height_mm)}",
        f"pd={_fmt(settings.pierce_delay_s)}",
        f"ch={_fmt(settings.cut_height_mm)}",
        f"fr={settings.feed_rate_mm_min}",
        f"mt={_fmt(settings.thickness_mm)}",
        f"kw={_fmt(settings.kerf_width_mm)}",
        f"th={1 if settings.thc_enabled else 0}",
        f"ca={settings.current_a}",
    ]
    if settings.cut_volts is not None:
        params.append(f"cv={_fmt(settings.cut_volts)}")
    return f"({', '.join(params)})"


def cut_voltage_for_row(row: CutChartRow) -> float:
    return _row_cut_volts(row)


def _settings_from_row(
    row: CutChartRow,
    thickness_mm: float,
    notes: tuple[str, ...],
    *,
    machine: str,
    source: str,
    profile_id: str,
    profile_version: str,
    profile_revision: str,
) -> CutSettings:
    return CutSettings(
        machine=machine,
        material=row.material,
        thickness_mm=round(thickness_mm, 3),
        nozzle_mm=row.nozzle_mm,
        current_a=row.current_a,
        feed_rate_mm_min=row.feed_rate_mm_min,
        kerf_width_mm=row.kerf_width_mm,
        pierce_height_mm=row.pierce_height_mm,
        pierce_delay_s=row.pierce_delay_s,
        cut_height_mm=row.cut_height_mm,
        cut_volts=_row_cut_volts(row),
        thc_enabled=row.thc_enabled,
        air_pressure_bar=row.air_pressure_bar,
        small_hole_threshold_mm=_row_small_hole_threshold(row),
        small_shape_threshold_mm=_row_small_shape_threshold(row),
        small_hole_speed_percent=_row_small_hole_speed_percent(row),
        small_hole_overburn_mm=_row_small_hole_overburn(row),
        small_hole_torch_off_before_end_mm=_row_small_hole_torch_off_before_end(row),
        source=source,
        notes=notes,
        profile_id=profile_id,
        profile_version=profile_version,
        profile_revision=profile_revision,
        row_id=row.row_id,
        row_revision=row.revision,
        calibration_state=row.calibration_state,
        measured_at=row.measured_at,
        operator=row.operator,
        coupon_id=row.coupon_id,
        quality_notes=row.quality_notes,
    )


def _preferred_rows(rows: object) -> list[CutChartRow]:
    preferred: dict[float, CutChartRow] = {}
    for row in sorted(rows, key=lambda item: (item.thickness_mm, _calibration_priority(item), item.row_id)):
        key = round(row.thickness_mm, 6)
        preferred.setdefault(key, row)
    return [preferred[key] for key in sorted(preferred)]


def _calibration_priority(row: CutChartRow) -> int:
    if row.calibration_state == "measured":
        return 0
    return 1


def _join_unique(values: tuple[str, ...]) -> str:
    return ",".join(dict.fromkeys(value for value in values if value))


def _bounds_for_thickness(rows: list[CutChartRow], thickness_mm: float) -> tuple[CutChartRow, CutChartRow]:
    for lower, upper in zip(rows, rows[1:]):
        if lower.thickness_mm <= thickness_mm <= upper.thickness_mm:
            return lower, upper
    raise ValueError(f"No interpolation bounds for {thickness_mm:g} mm")


def _lerp(a: float, b: float, ratio: float) -> float:
    return a + (b - a) * ratio


def _optional_lerp(a: float | None, b: float | None, ratio: float) -> float | None:
    if a is None or b is None:
        return None
    return _round_to_step(_lerp(a, b, ratio), 0.5)


def _row_small_hole_threshold(row: CutChartRow) -> float:
    if row.small_hole_threshold_mm is not None:
        return row.small_hole_threshold_mm
    return _round_to_step(min(60.0, max(12.0, row.thickness_mm * 12.0)), 0.5)


def _row_small_shape_threshold(row: CutChartRow) -> float:
    if row.small_shape_threshold_mm is not None:
        return row.small_shape_threshold_mm
    return _row_small_hole_threshold(row)


def _row_small_hole_speed_percent(row: CutChartRow) -> float:
    if row.small_hole_speed_percent is not None:
        return row.small_hole_speed_percent
    return DEFAULT_SMALL_HOLE_SPEED_PERCENT


def _row_small_hole_overburn(row: CutChartRow) -> float:
    if row.small_hole_overburn_mm is not None:
        return row.small_hole_overburn_mm
    return DEFAULT_SMALL_HOLE_OVERBURN_MM


def _row_small_hole_torch_off_before_end(row: CutChartRow) -> float:
    if row.small_hole_torch_off_before_end_mm is not None:
        return row.small_hole_torch_off_before_end_mm
    return DEFAULT_SMALL_HOLE_TORCH_OFF_BEFORE_END_MM


def _row_cut_volts(row: CutChartRow) -> float:
    if row.cut_volts is not None:
        return row.cut_volts
    return _round_to_step(92.0 + row.thickness_mm * 3.0 + max(0.0, row.nozzle_mm - 0.8) * 20.0, 0.5)


def _round_to_step(value: float, step: float) -> float:
    return round(round(value / step) * step, 3)


def _fmt(value: float) -> str:
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return text if text != "-0" else "0"


def _default_material_name(settings: CutSettings) -> str:
    return (
        f"Fubag40 mild steel {_fmt(settings.thickness_mm)}mm "
        f"n{_fmt(settings.nozzle_mm)} {settings.current_a}A"
    )


def _sanitize_material_name(name: str) -> str:
    cleaned = name.replace(",", " ").replace("(", " ").replace(")", " ")
    return " ".join(cleaned.split())[:64]
