from __future__ import annotations

import io
import math
import os
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import plasma_cam.autonest as autonest_module
import plasma_cam.cam.travel as travel_module
import plasma_cam.importers.dxf as dxf_importer_module
import plasma_cam.post as post_module
import plasma_cam.web_api as web_api_module
from plasma_cam.autonest import ShelfNestOptions, _compact_layout, shelf_nest, shelf_nest_result
from plasma_cam.cut_settings import (
    DEFAULT_CUT_PROFILE_PATH,
    apply_coupon_results_to_cut_chart,
    cut_chart_rows_from_dicts,
    format_qtplasmac_material_comment,
    load_cut_chart_profile,
    select_cut_settings,
)
from plasma_cam.importers.dxf import import_dxf_circles
from plasma_cam.model import CircleContour, LineSegment, PartProfile, PathContour, Point
from plasma_cam.nesting import ArraySpec, Sheet, array_nest, assert_within_sheet
from plasma_cam.post import CutTab, LeadOverride, QtPlasmaCOptions, TravelObstacle, generate_gcode, planned_cut_sequence, planned_lead_moves
from plasma_cam.project import (
    LayoutValidationError,
    NestedLayout,
    PartRequest,
    PlacedPart,
    Placement,
    assert_valid_layout,
    move_part,
    rotate_part,
    validate_layout,
)
from plasma_cam.validation import GCodeValidationError, assert_valid_gcode, validate_gcode
from plasma_cam.web_api import (
    auto_nest_project,
    cut_chart_profile_metadata,
    cut_chart_table,
    cut_settings_preview,
    export_project_review_dxf,
    export_project_outline_gcode,
    export_project_gcode,
    generate_coupon_test_project,
    import_coupon_results,
    import_dxf_project,
    load_project,
    preview_from_project,
    project_review_report,
    simulation_from_gcode,
    simulation_from_project,
    validate_project,
)


def demo_contours(hole_radius: float = 10.0) -> tuple[CircleContour, ...]:
    return (
        CircleContour("center_hole", Point(0, 0), hole_radius, "hole", "demo"),
        CircleContour("outer", Point(0, 0), 200, "outer", "demo"),
    )


def example_project() -> dict:
    return load_project(PROJECT_ROOT / "examples" / "circle-hole.project.json")


def rectangle_profile(name: str, width: float, height: float) -> PartProfile:
    points = [
        Point(-width / 2, -height / 2),
        Point(width / 2, -height / 2),
        Point(width / 2, height / 2),
        Point(-width / 2, height / 2),
    ]
    return PartProfile(
        name,
        (
            PathContour(
                f"{name}_outer",
                tuple(LineSegment(start, end) for start, end in zip(points, [*points[1:], points[0]])),
                "outer",
                name,
            ),
        ),
    )


def segmented_rectangle_profile(name: str, width: float, height: float, segments_per_side: int) -> PartProfile:
    points: list[Point] = []
    half_w = width / 2
    half_h = height / 2
    for index in range(segments_per_side):
        points.append(Point(-half_w + width * index / segments_per_side, -half_h))
    for index in range(segments_per_side):
        points.append(Point(half_w, -half_h + height * index / segments_per_side))
    for index in range(segments_per_side):
        points.append(Point(half_w - width * index / segments_per_side, half_h))
    for index in range(segments_per_side):
        points.append(Point(-half_w, half_h - height * index / segments_per_side))
    return PartProfile(
        name,
        (
            PathContour(
                f"{name}_outer",
                tuple(LineSegment(start, end) for start, end in zip(points, [*points[1:], points[0]])),
                "outer",
                name,
            ),
        ),
    )


def rectangle_part_json(name: str, width: float, height: float, quantity: int = 1) -> dict:
    points = [
        {"x": -width / 2, "y": -height / 2},
        {"x": width / 2, "y": -height / 2},
        {"x": width / 2, "y": height / 2},
        {"x": -width / 2, "y": height / 2},
    ]
    return {
        "name": name,
        "quantity": quantity,
        "contours": [
            {
                "type": "path",
                "kind": "outer",
                "name": f"{name}_outer",
                "segments": [
                    {"type": "line", "start": start, "end": end}
                    for start, end in zip(points, [*points[1:], points[0]])
                ],
            }
        ],
    }


def rectangle_with_rect_hole_part_json(
    name: str,
    width: float,
    height: float,
    hole_width: float,
    hole_height: float,
    quantity: int = 1,
) -> dict:
    part = rectangle_part_json(name, width, height, quantity=quantity)
    points = [
        {"x": -hole_width / 2, "y": -hole_height / 2},
        {"x": hole_width / 2, "y": -hole_height / 2},
        {"x": hole_width / 2, "y": hole_height / 2},
        {"x": -hole_width / 2, "y": hole_height / 2},
    ]
    part["contours"].append(
        {
            "type": "path",
            "kind": "hole",
            "name": f"{name}_window",
            "segments": [
                {"type": "line", "start": start, "end": end}
                for start, end in zip(points, [*points[1:], points[0]])
            ],
        }
    )
    return part


def circle_part_json(name: str, radius: float, quantity: int = 1) -> dict:
    return {
        "name": name,
        "quantity": quantity,
        "contours": [
            {
                "type": "circle",
                "kind": "outer",
                "name": f"{name}_outer",
                "center": {"x": 0, "y": 0},
                "radius_mm": radius,
            }
        ],
    }


def capsule_part_json(name: str, quantity: int = 1) -> dict:
    return {
        "name": name,
        "quantity": quantity,
        "contours": [
            {
                "type": "path",
                "kind": "outer",
                "name": f"{name}_outer",
                "segments": [
                    {"type": "line", "start": {"x": -20, "y": -10}, "end": {"x": 20, "y": -10}},
                    {
                        "type": "arc",
                        "start": {"x": 20, "y": -10},
                        "end": {"x": 20, "y": 10},
                        "center": {"x": 20, "y": 0},
                        "clockwise": False,
                    },
                    {"type": "line", "start": {"x": 20, "y": 10}, "end": {"x": -20, "y": 10}},
                    {
                        "type": "arc",
                        "start": {"x": -20, "y": 10},
                        "end": {"x": -20, "y": -10},
                        "center": {"x": -20, "y": 0},
                        "clockwise": False,
                    },
                ],
            },
            {
                "type": "circle",
                "kind": "hole",
                "name": f"{name}_hole",
                "center": {"x": 0, "y": 0},
                "radius_mm": 4,
            },
        ],
    }


def rectangle_contour(name: str, xmin: float, ymin: float, xmax: float, ymax: float) -> PathContour:
    points = [
        Point(xmin, ymin),
        Point(xmax, ymin),
        Point(xmax, ymax),
        Point(xmin, ymax),
    ]
    return PathContour(
        name,
        tuple(LineSegment(start, end) for start, end in zip(points, [*points[1:], points[0]])),
        "outer",
        name,
    )


def placed_profile_at(profile: PartProfile, instance: int, min_x: float, min_y: float) -> PlacedPart:
    xmin, ymin, _xmax, _ymax = profile.bbox()
    return PlacedPart(
        profile,
        Placement(
            part_name=profile.name,
            instance=instance,
            dx=min_x - xmin,
            dy=min_y - ymin,
        ),
    )


def test_qtplasmac_gcode_is_valid_and_cuts_hole_before_outer() -> None:
    gcode = generate_gcode(
        demo_contours(hole_radius=50),
        QtPlasmaCOptions(lead_in=5, small_hole_threshold=37),
    )

    assert_valid_gcode(gcode)
    assert "Z" not in gcode
    assert gcode.index("center_hole hole pierce") < gcode.index("outer outer pierce")
    assert "M3 $0 S1" in gcode
    assert "M5 $0" in gcode
    assert "F#<_hal[plasmac.cut-feed-rate]>" in gcode


def test_cut_order_keeps_part_holes_with_outer_before_next_part() -> None:
    contours = (
        CircleContour("plate_1_plate_hole", Point(0, 0), 10, "hole", "plate"),
        CircleContour("plate_2_plate_hole", Point(300, 0), 10, "hole", "plate"),
        CircleContour("plate_1_plate_outer", Point(0, 0), 50, "outer", "plate"),
        CircleContour("plate_2_plate_outer", Point(300, 0), 50, "outer", "plate"),
    )

    gcode = generate_gcode(
        contours,
        QtPlasmaCOptions(lead_in_mode="none", safe_travel=False),
    )

    assert_valid_gcode(gcode)
    assert (
        gcode.index("plate_1_plate_hole hole pierce")
        < gcode.index("plate_1_plate_outer outer pierce")
        < gcode.index("plate_2_plate_hole hole pierce")
        < gcode.index("plate_2_plate_outer outer pierce")
    )


def test_heat_spread_cut_order_separates_recently_cut_groups() -> None:
    contours = (
        CircleContour("near_outer", Point(20, 0), 5, "outer", "near"),
        CircleContour("warm_neighbor_outer", Point(55, 0), 5, "outer", "warm_neighbor"),
        CircleContour("far_outer", Point(220, 0), 5, "outer", "far"),
    )
    options = QtPlasmaCOptions(
        lead_in_mode="none",
        safe_travel=False,
        cut_order_strategy="heat_spread",
        heat_spread_weight=1.2,
    )

    sequence = planned_cut_sequence(contours, options)
    gcode = generate_gcode(contours, options)

    assert [item["name"] for item in sequence] == ["near_outer", "far_outer", "warm_neighbor_outer"]
    assert (
        gcode.index("near_outer outer pierce")
        < gcode.index("far_outer outer pierce")
        < gcode.index("warm_neighbor_outer outer pierce")
    )


def test_manual_cut_order_groups_override_strategy_without_breaking_hole_order() -> None:
    contours = (
        CircleContour("plate_1_hole", Point(0, 0), 10, "hole", "plate"),
        CircleContour("plate_2_hole", Point(300, 0), 10, "hole", "plate"),
        CircleContour("plate_1_outer", Point(0, 0), 50, "outer", "plate"),
        CircleContour("plate_2_outer", Point(300, 0), 50, "outer", "plate"),
    )
    options = QtPlasmaCOptions(
        lead_in_mode="none",
        safe_travel=False,
        cut_order_strategy="lower_left",
        cut_order_groups=("plate_2", "plate_1"),
    )

    sequence = planned_cut_sequence(contours, options)
    gcode = generate_gcode(contours, options)

    assert [item["group"] for item in sequence] == ["plate_2", "plate_2", "plate_1", "plate_1"]
    assert [item["kind"] for item in sequence] == ["hole", "outer", "hole", "outer"]
    assert (
        gcode.index("plate_2_hole hole pierce")
        < gcode.index("plate_2_outer outer pierce")
        < gcode.index("plate_1_hole hole pierce")
        < gcode.index("plate_1_outer outer pierce")
    )


def test_fubag_plasma_40_cut_settings_emit_qtplasmac_temporary_material() -> None:
    settings = select_cut_settings(thickness_mm=3.0, nozzle_mm=0.9)

    assert settings.current_a == 35
    assert settings.feed_rate_mm_min == 1300
    assert settings.kerf_width_mm == 1.2
    assert settings.pierce_delay_s == 0.35
    assert settings.cut_height_mm == 1.5
    assert settings.cut_volts is not None
    assert settings.small_hole_threshold_mm == 36
    assert settings.small_shape_threshold_mm == 36
    assert settings.small_hole_speed_percent == 65

    comment = format_qtplasmac_material_comment(settings)
    assert comment.startswith("(o=0, nu=0, na=Fubag40 mild steel 3mm n0.9 35A")
    assert "fr=1300" in comment
    assert "kw=1.2" in comment
    assert "th=1" in comment
    assert "ca=35" in comment
    assert "cv=" in comment


def test_cut_settings_can_interpolate_and_reject_out_of_chart_jobs() -> None:
    settings = select_cut_settings(thickness_mm=2.5, nozzle_mm=0.9)

    assert settings.current_a == 35
    assert settings.feed_rate_mm_min == 1600
    assert settings.kerf_width_mm == 1.15
    assert settings.small_hole_threshold_mm == 30
    assert settings.notes == ("Interpolated between 2 mm and 3 mm starter rows",)

    with pytest.raises(ValueError):
        select_cut_settings(thickness_mm=4.0, nozzle_mm=0.8)


def test_cut_settings_drive_gcode_feed_and_kerf_when_enabled() -> None:
    settings = select_cut_settings(thickness_mm=3.0, nozzle_mm=0.9)
    gcode = generate_gcode(
        demo_contours(hole_radius=50),
        QtPlasmaCOptions(cut_settings=settings, lead_in_mode="line", lead_in=5),
    )

    assert_valid_gcode(gcode)
    assert "(o=0, nu=0, na=Fubag40 mild steel 3mm n0.9 35A" in gcode
    assert "fr=1300" in gcode
    assert "kw=1.2" in gcode
    assert "F#<_hal[plasmac.cut-feed-rate]>" in gcode
    assert "G1 X49.4 Y0" in gcode


def test_fixed_qtplasmac_material_mode_uses_m190_wait_and_hal_feed() -> None:
    project = example_project()
    project["post"]["qtplasmac_material_mode"] = "fixed"
    project["post"]["qtplasmac_material_number"] = 7
    project["post"]["qtplasmac_material_wait_s"] = 2

    gcode = export_project_gcode(project)

    assert_valid_gcode(gcode)
    assert "(o=0, nu=0" not in gcode
    assert "M190 P7" in gcode
    assert "M66 P3 L3 Q2" in gcode
    assert "F#<_hal[plasmac.cut-feed-rate]>" in gcode


def test_arc_lead_in_is_used_for_curves_and_skipped_for_tiny_holes() -> None:
    gcode = generate_gcode(
        demo_contours(hole_radius=6),
        QtPlasmaCOptions(
            lead_in_mode="arc",
            lead_in=5,
            lead_in_min_hole_diameter=20,
            small_hole_threshold=37,
        ),
    )

    assert_valid_gcode(gcode)
    assert "G0 X6 Y0 (center_hole hole pierce)" in gcode
    assert "G3 X6 Y0 I0 J5 (arc lead in)" not in gcode
    assert "G0 X205 Y5 (outer outer pierce)" in gcode
    assert "G3 X200 Y0 I0 J-5 (arc lead in)" in gcode


def test_project_post_lead_in_settings_drive_export() -> None:
    project = example_project()
    project["post"]["lead_in_mode"] = "arc"
    project["post"]["lead_in_mm"] = 4
    project["post"]["lead_in_min_hole_diameter_mm"] = 10

    gcode = export_project_gcode(project)

    assert_valid_gcode(gcode)
    assert "G3 X299.4 Y250 I0 J4 (arc lead in)" in gcode


def test_manual_feed_overrides_qtplasmac_material_feed() -> None:
    project = example_project()
    project["cut"]["feed_rate_mode"] = "manual"
    project["cut"]["manual_feed_rate_mm_min"] = 777

    settings = cut_settings_preview(project)
    gcode = export_project_gcode(project)

    assert settings["feed_rate_mm_min"] == 777
    assert settings["feed_rate_mode"] == "manual"
    assert "fr=777" in gcode
    assert "Manual feed rate override" in settings["notes"]


def test_cut_chart_table_exposes_fubag_speed_rows() -> None:
    rows = cut_chart_table()
    row = next(item for item in rows if item["thickness_mm"] == 3.0 and item["nozzle_mm"] == 0.9)

    assert row["row_id"] == "mild_steel-3mm-n0p9-starter"
    assert row["calibration_state"] == "starter"
    assert "revision" in row
    assert "quality_notes" in row
    assert row["feed_rate_mm_min"] == 1300
    assert row["cut_height_mm"] == 1.5
    assert row["pierce_height_mm"] == 3.0
    assert row["arc_voltage_v"] is not None
    assert row["thc_enabled"] is True
    assert row["small_hole_threshold_mm"] == 36
    assert row["small_shape_threshold_mm"] == 36
    assert row["small_hole_speed_percent"] == 65
    assert row["small_hole_overburn_mm"] == 0
    assert row["small_hole_torch_off_before_end_mm"] == 0
    assert any(
        row["thickness_mm"] == 3.0
        and row["nozzle_mm"] == 0.9
        and row["feed_rate_mm_min"] == 1300
        for row in rows
    )


def test_cut_chart_profile_is_loaded_from_versioned_json() -> None:
    profile = load_cut_chart_profile(DEFAULT_CUT_PROFILE_PATH)
    metadata = cut_chart_profile_metadata()

    assert profile.profile_id == "fubag-plasma-40-starter"
    assert profile.version == metadata["version"]
    assert profile.revision == metadata["revision"]
    assert profile.machine == "Fubag Plasma 40"
    assert len(profile.rows) == len(cut_chart_table())
    assert any(row.thickness_mm == 3.0 and row.nozzle_mm == 0.9 for row in profile.rows)


def test_project_cut_chart_overrides_starter_profile() -> None:
    project = example_project()
    rows = cut_chart_table()
    override_rows = []
    for row in rows:
        copied = dict(row)
        if copied["thickness_mm"] == 3.0 and copied["nozzle_mm"] == 0.9:
            copied["feed_rate_mm_min"] = 777
            copied["kerf_width_mm"] = 1.77
            copied["pierce_delay_s"] = 0.77
            copied["arc_voltage_v"] = 107.7
        override_rows.append(copied)
    project["cut_chart"] = {
        "profile_id": "project-calibrated",
        "version": "shop-test",
        "machine": "Fubag Plasma 40",
        "source": "Project calibrated cut chart",
        "rows": override_rows,
    }

    settings = cut_settings_preview(project)

    assert settings["feed_rate_mm_min"] == 777
    assert settings["kerf_width_mm"] == 1.77
    assert settings["pierce_delay_s"] == 0.77
    assert settings["cut_volts"] == 107.7
    assert settings["source"] == "Project calibrated cut chart"


def test_project_cut_chart_must_cover_current_nozzle_and_thickness() -> None:
    project = example_project()
    project["cut_chart"] = {
        "profile_id": "wrong-nozzle-profile",
        "version": "shop-test",
        "machine": "Fubag Plasma 40",
        "source": "Wrong nozzle test profile",
        "rows": [
            {
                "material": "mild_steel",
                "thickness_mm": 3.0,
                "nozzle_mm": 0.8,
                "current_a": 35,
                "feed_rate_mm_min": 1300,
                "kerf_width_mm": 1.2,
                "pierce_delay_s": 0.5,
            }
        ],
    }

    with pytest.raises(ValueError, match="No cut chart rows"):
        cut_settings_preview(project)


def test_cut_chart_small_feature_rules_drive_export() -> None:
    project = example_project()
    rows = cut_chart_table()
    row = dict(next(item for item in rows if item["thickness_mm"] == 3.0 and item["nozzle_mm"] == 0.9))
    row.update(
        {
            "row_id": "shop-small-feature-3mm",
            "small_hole_threshold_mm": 120,
            "small_shape_threshold_mm": 120,
            "small_hole_speed_percent": 50,
            "small_hole_overburn_mm": 1.2,
            "small_hole_torch_off_before_end_mm": 0.8,
        }
    )
    project["cut_chart"] = {
        "profile_id": "shop-chart",
        "version": "r1",
        "revision": "r1",
        "machine": "Fubag Plasma 40",
        "source": "shop small feature rules",
        "rows": [row],
    }
    project["post"]["small_feature_source"] = "cut_chart"
    project["post"]["small_hole_threshold_mm"] = 0
    project["post"]["small_shape_threshold_mm"] = 0
    project["post"]["small_hole_speed_percent"] = 90

    settings = cut_settings_preview(project)
    gcode = export_project_gcode(project)
    simulation = simulation_from_project(project)
    report = project_review_report(project)

    assert settings["small_hole_threshold_mm"] == 120
    assert settings["small_hole_speed_percent"] == 50
    assert "M67 E3 Q50" in gcode
    assert any(segment.get("reduced_feed") for segment in simulation["segments"])
    assert report["cut_settings"]["small_hole_threshold_mm"] == 120
    assert report["cut_settings"]["small_hole_speed_percent"] == 50


def test_measured_cut_chart_row_is_preferred_and_exposed_in_header() -> None:
    project = example_project()
    rows = cut_chart_table()
    measured = dict(next(row for row in rows if row["thickness_mm"] == 3.0 and row["nozzle_mm"] == 0.9))
    measured.update(
        {
            "row_id": "shop-ms3-n09-coupon-17",
            "revision": "rev-2",
            "calibration_state": "measured",
            "measured_at": "2026-08-23T10:00:00Z",
            "operator": "shop",
            "coupon_id": "coupon-17",
            "feed_rate_mm_min": 1180,
            "kerf_width_mm": 1.28,
            "pierce_delay_s": 0.42,
            "quality_notes": ["clean top edge"],
        }
    )
    project["cut_chart"] = {
        "profile_id": "shop-fubag40",
        "version": "2026-08",
        "revision": "shop-r2",
        "machine": "Fubag Plasma 40",
        "source": "Shop measured Fubag profile",
        "rows": [*rows, measured],
    }

    settings = cut_settings_preview(project)
    gcode = export_project_gcode(project)

    assert settings["feed_rate_mm_min"] == 1180
    assert settings["kerf_width_mm"] == 1.28
    assert settings["pierce_delay_s"] == 0.42
    assert settings["calibration_state"] == "measured"
    assert settings["row_id"] == "shop-ms3-n09-coupon-17"
    assert settings["row_revision"] == "rev-2"
    assert settings["profile_revision"] == "shop-r2"
    assert settings["coupon_id"] == "coupon-17"
    assert settings["quality_notes"] == ("clean top edge",)
    assert "Cut chart row: measured" in gcode
    assert "row=shop-ms3-n09-coupon-17" in gcode
    assert "revision=rev-2" in gcode
    assert "coupon=coupon-17" in gcode
    assert "source=Shop measured Fubag profile" in gcode
    assert "fr=1180" in gcode


def test_coupon_test_project_validates_and_exports_qtplasmac_gcode() -> None:
    project = generate_coupon_test_project(
        {
            "material": "mild_steel",
            "thickness_mm": 3.0,
            "nozzle_mm": 0.9,
            "feed_rate_range": {"start": 1100, "stop": 1200, "step": 100},
            "kerf_width_mm": [1.2, 1.3],
            "pierce_delay_s": [0.35],
            "revision": "coupon-r1",
        }
    )

    issues = validate_project(project)
    gcode = export_project_gcode(project)

    assert all(issue.get("blocking") is False for issue in issues)
    assert_valid_gcode(gcode)
    assert project["coupon_plan"]["revision"] == "coupon-r1"
    assert len(project["coupon_plan"]["coupons"]) == 4
    assert project["coupon_plan"]["candidate_rows"][0]["coupon_id"] == "coupon-01"
    assert len(project["parts"]) == 4
    assert all(len(part["contours"]) == 2 for part in project["parts"])
    assert "Cut chart row: starter" in gcode
    assert "coupon=coupon-01" in gcode
    assert "F#<_hal[plasmac.cut-feed-rate]>" in gcode


def test_coupon_result_import_adds_measured_row_and_drives_export_header() -> None:
    response = import_coupon_results(
        {
            "project": example_project(),
            "revision": "shop-measured-r1",
            "source": "Shop coupon measured profile",
            "results": [
                {
                    "material": "mild_steel",
                    "thickness_mm": 3.0,
                    "nozzle_mm": 0.9,
                    "current_a": 35,
                    "feed_rate_mm_min": 1120,
                    "kerf_width_mm": 1.34,
                    "pierce_delay_s": 0.48,
                    "cut_height_mm": 1.45,
                    "arc_voltage_v": 104.5,
                    "thc_enabled": False,
                    "coupon_id": "coupon-17",
                    "operator": "shop",
                    "measured_at": "2026-08-23T10:00:00Z",
                    "quality_notes": "clean edge, slight bottom dross",
                }
            ],
        }
    )

    project = response["project"]
    settings = cut_settings_preview(project)
    gcode = export_project_gcode(project)

    assert response["imported_count"] == 1
    assert response["coupon_ids"] == ["coupon-17"]
    assert response["measured_rows"][0]["calibration_state"] == "measured"
    assert response["measured_rows"][0]["row_id"] == "mild_steel-3mm-n0p9-measured-coupon-17"
    assert settings["feed_rate_mm_min"] == 1120
    assert settings["kerf_width_mm"] == 1.34
    assert settings["pierce_delay_s"] == 0.48
    assert settings["cut_height_mm"] == 1.45
    assert settings["cut_volts"] == 104.5
    assert settings["thc_enabled"] is False
    assert settings["calibration_state"] == "measured"
    assert settings["row_revision"] == "shop-measured-r1"
    assert settings["operator"] == "shop"
    assert settings["coupon_id"] == "coupon-17"
    assert settings["quality_notes"] == ("clean edge, slight bottom dross",)
    assert "Cut chart row: measured" in gcode
    assert "row=mild_steel-3mm-n0p9-measured-coupon-17" in gcode
    assert "revision=shop-measured-r1" in gcode
    assert "coupon=coupon-17" in gcode
    assert "source=Shop coupon measured profile" in gcode
    assert "fr=1120" in gcode
    assert "th=0" in gcode


def test_coupon_result_import_replaces_prior_measured_row_for_same_cut_slot() -> None:
    project = example_project()
    first = apply_coupon_results_to_cut_chart(
        {
            "project": project,
            "revision": "r1",
            "results": [
                {
                    "material": "mild_steel",
                    "thickness_mm": 3,
                    "nozzle_mm": 0.9,
                    "current_a": 35,
                    "feed_rate_mm_min": 1200,
                    "kerf_width_mm": 1.25,
                    "pierce_delay_s": 0.4,
                    "cut_height_mm": 1.5,
                    "arc_voltage_v": 103,
                    "thc_enabled": True,
                    "coupon_id": "coupon-old",
                    "operator": "shop",
                    "measured_at": "2026-08-23T09:00:00Z",
                    "quality_notes": [],
                }
            ],
        }
    )
    second = apply_coupon_results_to_cut_chart(
        {
            "project": {"cut_chart": first["cut_chart"]},
            "revision": "r2",
            "results": [
                {
                    "material": "mild_steel",
                    "thickness_mm": 3,
                    "nozzle_mm": 0.9,
                    "current_a": 35,
                    "feed_rate_mm_min": 1110,
                    "kerf_width_mm": 1.31,
                    "pierce_delay_s": 0.45,
                    "cut_height_mm": 1.45,
                    "arc_voltage_v": 104,
                    "thc_enabled": True,
                    "coupon_id": "coupon-new",
                    "operator": "shop",
                    "measured_at": "2026-08-23T11:00:00Z",
                    "quality_notes": [],
                }
            ],
        }
    )

    rows = second["cut_chart"]["rows"]
    measured_rows = [row for row in rows if row["calibration_state"] == "measured"]
    chart = cut_chart_rows_from_dicts(rows)
    settings = select_cut_settings(
        material="mild_steel",
        thickness_mm=3,
        nozzle_mm=0.9,
        chart=chart,
        source=second["cut_chart"]["source"],
    )

    assert len(measured_rows) == 1
    assert measured_rows[0]["coupon_id"] == "coupon-new"
    assert settings.feed_rate_mm_min == 1110
    assert settings.calibration_state == "measured"
    assert settings.coupon_id == "coupon-new"


def test_coupon_result_import_validates_required_numeric_and_metadata_fields() -> None:
    valid_result = {
        "material": "mild_steel",
        "thickness_mm": 3,
        "nozzle_mm": 0.9,
        "current_a": 35,
        "feed_rate_mm_min": 1200,
        "kerf_width_mm": 1.25,
        "pierce_delay_s": 0.4,
        "cut_height_mm": 1.5,
        "arc_voltage_v": 103,
        "thc_enabled": True,
        "coupon_id": "coupon-01",
        "operator": "shop",
        "measured_at": "2026-08-23T09:00:00Z",
        "quality_notes": [],
    }

    missing_feed = dict(valid_result)
    missing_feed.pop("feed_rate_mm_min")
    with pytest.raises(ValueError, match="feed_rate_mm_min"):
        apply_coupon_results_to_cut_chart({"project": example_project(), "results": [missing_feed]})

    missing_coupon = dict(valid_result)
    missing_coupon["coupon_id"] = ""
    with pytest.raises(ValueError, match="coupon_id"):
        apply_coupon_results_to_cut_chart({"project": example_project(), "results": [missing_coupon]})

    bad_timestamp = dict(valid_result)
    bad_timestamp["measured_at"] = "not-a-date"
    with pytest.raises(ValueError, match="measured_at"):
        apply_coupon_results_to_cut_chart({"project": example_project(), "results": [bad_timestamp]})


def test_kerf_offset_split_is_reported_as_cam_geometry_not_lead(monkeypatch: pytest.MonkeyPatch) -> None:
    project = example_project()

    def split_offset(_contours, _options):
        raise ValueError("Kerf offset split contour")

    monkeypatch.setattr(web_api_module, "planned_lead_moves", split_offset)

    issues = validate_project(project)

    assert any(issue["code"] == "kerf_offset_centerline" for issue in issues)
    assert not any(issue["code"] == "lead_invalid" for issue in issues)
    gcode = export_project_gcode(project)
    assert "WARNING: kerf_offset_centerline" in gcode
    assert "Kerf offset split contour" in gcode


def test_circle_offset_collapse_is_reported_as_small_feature_below_kerf(monkeypatch: pytest.MonkeyPatch) -> None:
    project = example_project()

    def collapsed_circle_offset(_contours, _options):
        raise ValueError("tiny_hole path radius is not positive")

    monkeypatch.setattr(web_api_module, "planned_lead_moves", collapsed_circle_offset)

    issues = validate_project(project)

    assert any(issue["code"] == "kerf_offset_centerline" for issue in issues)
    assert not any(issue["code"] == "lead_invalid" for issue in issues)
    gcode = export_project_gcode(project)
    assert "WARNING: kerf_offset_centerline" in gcode
    assert "tiny_hole path radius is not positive" in gcode


def test_centerline_fallback_warns_and_allows_export(monkeypatch: pytest.MonkeyPatch) -> None:
    project = example_project()
    project["post"]["kerf_offset_fallback"] = "centerline"

    def split_offset_on_strict(_contours, options):
        if options.kerf_offset_fallback == "centerline":
            return ()
        raise ValueError("Kerf offset split contour")

    monkeypatch.setattr(web_api_module, "planned_lead_moves", split_offset_on_strict)

    issues = validate_project(project)
    issue_codes = {issue["code"] for issue in issues}

    assert "kerf_offset_centerline" in issue_codes
    assert "kerf_offset" not in issue_codes
    assert all(issue.get("blocking") is False for issue in issues if issue["code"] == "kerf_offset_centerline")
    gcode = export_project_gcode(project)
    assert "(WARNING:" in gcode
    assert "without kerf compensation" in gcode
    assert_valid_gcode(gcode)
    report = project_review_report(project)
    assert report["cam_geometry"]["centerline_fallback_count"] >= 1
    assert report["cam_geometry"]["blocking_count"] == 0
    assert report["cam_geometry"]["codes"]["kerf_offset_centerline"] >= 1


def test_tiny_circle_hole_blocks_without_centerline_fallback() -> None:
    project = example_project()
    project["parts"][0]["holes"][0]["radius_mm"] = 0.3

    issues = validate_project(project)
    issue_codes = {issue["code"] for issue in issues}

    assert "kerf_offset_centerline" in issue_codes
    gcode = export_project_gcode(project)
    assert "WARNING: kerf_offset_centerline" in gcode
    assert "without kerf compensation" in gcode


def test_tiny_circle_hole_centerline_fallback_warns_and_simulates() -> None:
    project = example_project()
    project["parts"][0]["holes"][0]["radius_mm"] = 0.3
    project["post"]["kerf_offset_fallback"] = "centerline"

    issues = validate_project(project)
    centerline_issues = [issue for issue in issues if issue["code"] == "kerf_offset_centerline"]

    assert centerline_issues
    assert all(issue.get("blocking") is False for issue in centerline_issues)
    assert "small_feature_below_kerf" not in {issue["code"] for issue in issues}
    gcode = export_project_gcode(project)
    assert "(WARNING:" in gcode
    assert "without kerf compensation" in gcode
    assert_valid_gcode(gcode)
    simulation = simulation_from_project(project)
    assert simulation["segments"]


def test_simulation_uses_generated_gcode_path_and_feed() -> None:
    project = example_project()
    project["cut"]["feed_rate_mode"] = "manual"
    project["cut"]["manual_feed_rate_mm_min"] = 1000
    project["post"]["lead_in_mode"] = "arc"
    project["post"]["lead_in_mm"] = 4

    simulation = simulation_from_project(project)
    cut_segments = [segment for segment in simulation["segments"] if segment["type"] == "cut"]
    rapid_segments = [segment for segment in simulation["segments"] if segment["type"] == "rapid"]

    assert simulation["feed_rate_mm_min"] == 1000
    assert simulation["estimated_cut_s"] > 0
    assert simulation["estimated_rapid_s"] > 0
    assert cut_segments
    assert rapid_segments
    assert any(segment["motion"] == "arc_ccw" for segment in cut_segments)


def test_simulation_can_reuse_exported_gcode() -> None:
    project = example_project()
    gcode = export_project_gcode(project)

    direct = simulation_from_gcode(project, gcode)
    regenerated = simulation_from_project(project)

    assert direct["estimated_total_s"] == regenerated["estimated_total_s"]
    assert len(direct["segments"]) == len(regenerated["segments"])


def test_simulation_marks_pierce_reduced_feed_and_thc_disabled_states() -> None:
    project = example_project()
    project["post"]["small_hole_threshold_mm"] = 120
    project["post"]["small_hole_speed_percent"] = 60

    simulation = simulation_from_project(project)

    assert any(segment["type"] == "pierce" for segment in simulation["segments"])
    assert any(segment.get("reduced_feed") for segment in simulation["segments"])
    assert any(segment.get("thc_disabled") for segment in simulation["segments"])


def test_cut_settings_reject_unapplied_material_feed_configuration() -> None:
    settings = select_cut_settings(thickness_mm=3.0, nozzle_mm=0.9)

    with pytest.raises(ValueError):
        QtPlasmaCOptions(cut_settings=settings, emit_temporary_material=False)

    fixed = generate_gcode(
        demo_contours(hole_radius=50),
        QtPlasmaCOptions(
            cut_settings=settings,
            material=3,
            emit_temporary_material=False,
        ),
    )
    assert "M190 P3" in fixed
    assert "F#<_hal[plasmac.cut-feed-rate]>" in fixed

    gcode = generate_gcode(
        demo_contours(hole_radius=50),
        QtPlasmaCOptions(
            cut_settings=settings,
            emit_temporary_material=False,
            use_material_feed=False,
        ),
    )
    assert "F1300" in gcode


def test_common_line_export_skips_duplicate_straight_shared_edge() -> None:
    gcode = generate_gcode(
        (
            rectangle_contour("left_outer", 0, 0, 50, 50),
            rectangle_contour("right_outer", 50, 0, 100, 50),
        ),
        QtPlasmaCOptions(
            kerf_width=0,
            lead_in_mode="none",
            safe_travel=False,
            common_line_cutting=True,
        ),
    )

    assert_valid_gcode(gcode)
    assert "common line skipped 1 shared segment on right_outer" in gcode
    assert "right_outer common-line chain 1 pierce" in gcode


def test_common_line_export_rejects_active_geometry_kerf_offset() -> None:
    with pytest.raises(ValueError, match="Common-line export requires kerf offset disabled"):
        generate_gcode(
            (
                rectangle_contour("left_outer", 0, 0, 50, 50),
                rectangle_contour("right_outer", 50, 0, 100, 50),
            ),
            QtPlasmaCOptions(
                kerf_width=1.2,
                lead_in_mode="none",
                safe_travel=False,
                common_line_cutting=True,
                kerf_offset_fallback="block",
            ),
        )


def test_small_hole_uses_thc_lock_and_velocity_reduction() -> None:
    gcode = generate_gcode(
        demo_contours(hole_radius=10),
        QtPlasmaCOptions(small_hole_threshold=37, small_hole_speed_percent=65),
    )

    assert_valid_gcode(gcode)
    assert "M64 P2" in gcode
    assert "M67 E3 Q65" in gcode
    assert "M68 E3 Q0" in gcode
    assert "M65 P2" in gcode


def test_small_path_hole_gets_speed_thc_overburn_and_early_torch_off() -> None:
    points = [
        Point(-8, -8),
        Point(8, -8),
        Point(8, 8),
        Point(-8, 8),
    ]
    contour = PathContour(
        "small_square_hole",
        tuple(LineSegment(start, end) for start, end in zip(points, [*points[1:], points[0]])),
        "hole",
        "test",
    )

    gcode = generate_gcode(
        (contour,),
        QtPlasmaCOptions(
            kerf_width=1.0,
            lead_in_mode="line",
            lead_in=0,
            lead_out=5,
            small_hole_threshold=37,
            small_hole_overburn=1.5,
            small_hole_torch_off_before_end=1.0,
        ),
    )

    assert_valid_gcode(gcode)
    assert "M64 P2" in gcode
    assert "M67 E3 Q65" in gcode
    assert "small feature early torch off" in gcode
    assert "lead out" not in gcode


def test_small_hole_without_thc_lock_only_resets_velocity() -> None:
    gcode = generate_gcode(
        demo_contours(hole_radius=10),
        QtPlasmaCOptions(
            small_hole_threshold=37,
            small_hole_speed_percent=65,
            small_hole_disable_thc=False,
        ),
    )

    assert_valid_gcode(gcode)
    assert "M64 P2" not in gcode
    assert "M65 P2" not in gcode
    assert "M67 E3 Q65" in gcode
    assert "M68 E3 Q0" in gcode


def test_safe_travel_routes_rapid_around_obstacle() -> None:
    contours = (
        CircleContour("left_slug", Point(20, 20), 5, "outer", "test"),
        CircleContour("right_slug", Point(120, 20), 5, "outer", "test"),
    )

    gcode = generate_gcode(
        contours,
        QtPlasmaCOptions(
            lead_in_mode="none",
            safe_travel=True,
            travel_clearance=0,
            travel_bounds=(0, 0, 180, 80),
            travel_obstacles=(TravelObstacle(50, 0, 90, 40, "clamp"),),
        ),
    )

    assert_valid_gcode(gcode)
    assert "safe rapid" in gcode
    assert "right_slug outer pierce" in gcode


def test_safe_travel_blocked_warns_and_uses_direct_rapid(monkeypatch: pytest.MonkeyPatch) -> None:
    def box_contour(name: str, xmin: float, ymin: float, xmax: float, ymax: float) -> PathContour:
        points = [
            Point(xmin, ymin),
            Point(xmax, ymin),
            Point(xmax, ymax),
            Point(xmin, ymax),
        ]
        return PathContour(
            name,
            tuple(LineSegment(start, end) for start, end in zip(points, [*points[1:], points[0]])),
            "outer",
            "test",
        )

    contours = (
        box_contour("left_slug", 15, 15, 25, 25),
        box_contour("right_slug", 115, 15, 125, 25),
    )
    monkeypatch.setattr(travel_module, "_safe_travel_route", lambda *_args, **_kwargs: None)

    gcode = generate_gcode(
        contours,
        QtPlasmaCOptions(
            lead_in_mode="none",
            safe_travel=True,
            travel_clearance=0,
            travel_bounds=(0, 0, 180, 80),
            travel_obstacles=(TravelObstacle(50, -1, 90, 81, "clamp"),),
            optimize_cut_order=False,
        ),
    )

    assert_valid_gcode(gcode)
    assert "WARNING: safe travel route blocked" in gcode
    assert "using direct rapid" in gcode
    assert "right_slug outer pierce" in gcode


def test_safe_travel_large_route_grid_warns_instead_of_exhaustive_search() -> None:
    contours = (
        CircleContour("left_slug", Point(20, 20), 5, "outer", "test"),
        CircleContour("right_slug", Point(220, 20), 5, "outer", "test"),
    )
    obstacles = [TravelObstacle(80, -5, 120, 45, "center_clamp")]
    obstacles.extend(
        TravelObstacle(20 + index * 3, 70 + index, 21 + index * 3, 71 + index, f"slat_{index}")
        for index in range(40)
    )

    gcode = generate_gcode(
        contours,
        QtPlasmaCOptions(
            lead_in_mode="none",
            safe_travel=True,
            travel_clearance=0,
            travel_bounds=(0, 0, 280, 140),
            travel_obstacles=tuple(obstacles),
            optimize_cut_order=False,
        ),
    )

    assert_valid_gcode(gcode)
    assert "WARNING: safe travel route blocked" in gcode
    assert "using direct rapid" in gcode
    assert "right_slug outer pierce" in gcode


def test_safe_travel_many_obstacles_warns_without_route_search(monkeypatch: pytest.MonkeyPatch) -> None:
    contours = (
        CircleContour("left_slug", Point(20, 20), 5, "outer", "test"),
        CircleContour("right_slug", Point(220, 20), 5, "outer", "test"),
    )
    obstacles = tuple(
        TravelObstacle(40 + index, 0, 40.5 + index, 40, f"cutout_{index}")
        for index in range(205)
    )

    def fail_obstacle_expansion(*_args, **_kwargs):
        raise AssertionError("Many-obstacle safe travel should warn before expanding every obstacle")

    monkeypatch.setattr(travel_module, "_expanded_obstacles", fail_obstacle_expansion)

    gcode = generate_gcode(
        contours,
        QtPlasmaCOptions(
            lead_in_mode="none",
            safe_travel=True,
            travel_clearance=0,
            travel_bounds=(0, 0, 280, 140),
            travel_obstacles=obstacles,
            optimize_cut_order=False,
        ),
    )

    assert_valid_gcode(gcode)
    assert "WARNING: safe travel obstacle set too complex" in gcode
    assert "using direct rapid" in gcode


def test_safe_travel_blocked_is_reported_by_project_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    project = example_project()

    def blocked_safe_travel(_layout, _options):
        return "G0 X20 Y20 (WARNING: safe travel route blocked from X10 Y10 to X20 Y20; using direct rapid)\n"

    monkeypatch.setattr(web_api_module, "_generate_layout_gcode_warning_only", blocked_safe_travel)

    issues = validate_project(project)

    safe_issue = next(issue for issue in issues if issue["code"] == "safe_travel")
    assert "safe travel route blocked" in safe_issue["message"]
    assert safe_issue["blocking"] is False


def test_safe_travel_warning_is_visible_in_simulation_and_review_metrics() -> None:
    project = example_project()
    gcode = "\n".join(
        [
            "G21",
            "G90",
            "G0 X10 Y0 (WARNING: safe travel route blocked from X0 Y0 to X10 Y0; using direct rapid)",
            "G0 X20 Y0 (WARNING: safe travel obstacle set too complex (205 obstacles); using direct rapid from X10 Y0 to X20 Y0)",
        ]
    )

    simulation = simulation_from_gcode(project, gcode)
    warning_segments = [segment for segment in simulation["segments"] if segment.get("safe_travel_warning")]
    metrics = web_api_module._review_simulation_metrics(simulation)
    messages = web_api_module._safe_travel_warning_messages(gcode)

    assert len(warning_segments) == 2
    assert warning_segments[0]["safe_travel_warning_message"].startswith("WARNING: safe travel route blocked")
    assert metrics["safe_travel_warning_count"] == 2
    assert metrics["safe_travel_warning_length_mm"] == 20
    assert len(messages) == 2
    assert any("obstacle set too complex" in message for message in messages)


def test_safe_travel_warning_is_export_preflight_warning_not_blocker(monkeypatch: pytest.MonkeyPatch) -> None:
    project = example_project()

    def blocked_safe_travel(_layout, _options):
        return "\n".join(
            [
                "G21 (metric)",
                "G90 (absolute)",
                "G0 X20 Y20 (WARNING: safe travel route blocked from X10 Y10 to X20 Y20; using direct rapid)",
            ]
        )

    monkeypatch.setattr(web_api_module, "_generate_layout_gcode_warning_only", blocked_safe_travel)

    report = project_review_report(project)

    assert report["export_preflight"]["can_export"] is True
    assert report["export_preflight"]["blocking_issue_count"] == 0
    assert "safe_travel" in report["export_preflight"]["warning_codes"]
    assert report["simulation_metrics"]["safe_travel_warning_count"] == 1
    assert report["issue_summary"]["warning_codes"]["safe_travel"] == 1


def test_safe_travel_validation_skips_complex_layout(monkeypatch: pytest.MonkeyPatch) -> None:
    project = example_project()

    def fail_gcode_generation(*_args, **_kwargs):
        raise AssertionError("Safe-travel validation should skip complex layouts")

    monkeypatch.setattr(web_api_module, "_layout_segment_count", lambda _layout: 12_001)
    monkeypatch.setattr(web_api_module, "generate_layout_gcode", fail_gcode_generation)

    issues = validate_project(project)
    safe_issue = next(issue for issue in issues if issue["code"] == "safe_travel")

    assert "precheck skipped" in safe_issue["message"]
    assert safe_issue["blocking"] is False


def test_lead_validation_skips_complex_layout(monkeypatch: pytest.MonkeyPatch) -> None:
    project = example_project()

    def fail_lead_planning(*_args, **_kwargs):
        raise AssertionError("Lead validation should skip complex layouts")

    monkeypatch.setattr(web_api_module, "_layout_segment_count", lambda _layout: 12_001)
    monkeypatch.setattr(web_api_module, "planned_lead_moves", fail_lead_planning)

    issues = validate_project(project)
    lead_issue = next(issue for issue in issues if issue["code"] == "lead_geometry_complexity")

    assert "precheck skipped" in lead_issue["message"]
    assert lead_issue["blocking"] is False


def test_hole_filler_bridge_validation_skips_complex_layout(monkeypatch: pytest.MonkeyPatch) -> None:
    project = example_project()

    monkeypatch.setattr(web_api_module, "HOLE_FILLER_BRIDGE_VALIDATION_MAX_PARTS", 0)

    issues = validate_project(project)
    bridge_issue = next(issue for issue in issues if issue["code"] == "hole_filler_bridge_complexity")

    assert "precheck skipped" in bridge_issue["message"]
    assert bridge_issue["blocking"] is False


def test_safe_travel_can_be_explicitly_disabled_for_direct_rapids() -> None:
    project = example_project()
    project["sheet"] = {"width_mm": 180, "height_mm": 80, "margin_mm": 0}
    project["parts"] = [
        {"name": "left", "quantity": 1, "outer": {"type": "circle", "radius_mm": 5}, "holes": []},
        {"name": "right", "quantity": 1, "outer": {"type": "circle", "radius_mm": 5}, "holes": []},
    ]
    project["placements"] = [
        {"part_name": "left", "instance": 1, "dx": 20, "dy": 20, "rotation_deg": 0},
        {"part_name": "right", "instance": 1, "dx": 120, "dy": 20, "rotation_deg": 0},
    ]
    project["post"]["lead_in_mode"] = "none"
    project["post"]["travel_clearance_mm"] = 0
    project["post"]["safe_travel"] = False
    project["zones"] = [{"id": "clamp-1", "type": "clamp", "x_mm": 50, "y_mm": -1, "width_mm": 40, "height_mm": 82}]

    issue_codes = {issue["code"] for issue in validate_project(project)}

    assert "safe_travel" not in issue_codes
    assert_valid_gcode(export_project_gcode(project))


def test_tab_bridge_emits_torch_off_skip_and_restart() -> None:
    contour = rectangle_profile("tabbed", 80, 40).contours[0]

    gcode = generate_gcode(
        (contour,),
        QtPlasmaCOptions(
            lead_in_mode="line",
            lead_in=0,
            tabs=(CutTab("tabbed_outer", 0, -20, 12),),
        ),
    )

    assert_valid_gcode(gcode)
    assert "tab torch off" in gcode
    assert "tab bridge skip" in gcode
    assert "tab torch on" in gcode


def test_auto_tabs_generate_microjoints_for_large_outer_contours() -> None:
    contour = rectangle_profile("auto_tabbed", 100, 60).contours[0]

    gcode = generate_gcode(
        (contour,),
        QtPlasmaCOptions(
            lead_in_mode="none",
            auto_tabs=True,
            auto_tab_count=2,
            auto_tab_length=10,
            auto_tab_min_outer_diameter=40,
        ),
    )

    assert_valid_gcode(gcode)
    assert gcode.count("tab torch off") == 2
    assert gcode.count("tab bridge skip") == 2
    assert gcode.count("tab torch on") == 2


def test_project_auto_tabs_drive_export() -> None:
    project = example_project()
    project["parts"] = [rectangle_part_json("tabbed", 100, 60)]
    project["placements"] = [{"part_name": "tabbed", "instance": 1, "dx": 100, "dy": 100, "rotation_deg": 0}]
    project["post"]["lead_in_mode"] = "none"
    project["post"]["auto_tabs"] = True
    project["post"]["auto_tab_count"] = 2
    project["post"]["auto_tab_length_mm"] = 9
    project["post"]["auto_tab_min_outer_diameter_mm"] = 40

    gcode = export_project_gcode(project)

    assert_valid_gcode(gcode)
    assert gcode.count("tab torch off") == 2
    assert gcode.count("tab bridge skip") == 2
    assert gcode.count("tab torch on") == 2


def test_lead_override_changes_circle_start_point() -> None:
    contour = CircleContour("outer", Point(0, 0), 10, "outer", "test")

    gcode = generate_gcode(
        (contour,),
        QtPlasmaCOptions(
            lead_in_mode="line",
            lead_in=3,
            lead_overrides=(LeadOverride("outer", start_x=0, start_y=10),),
        ),
    )

    assert_valid_gcode(gcode)
    assert "G0 X0 Y13 (outer outer pierce)" in gcode
    assert "G1 X0 Y10 (lead in)" in gcode


def test_validator_rejects_z_motion_and_plain_torch_start() -> None:
    bad_gcode = "\n".join(
        [
            "G21",
            "G90",
            "G17",
            "G40",
            "G64 P0.1",
            "M52 P1",
            "M68 E3 Q0",
            "M3 S1",
            "G1 X1 Y2 Z3",
            "M5 $0",
            "M2",
        ]
    )

    issues = validate_gcode(bad_gcode)
    assert {issue.code for issue in issues} >= {"plain_m3", "z_motion", "torch_already_off"}
    with pytest.raises(GCodeValidationError):
        assert_valid_gcode(bad_gcode)


def test_validator_rejects_qtplasmac_cutter_compensation_mode() -> None:
    bad_gcode = "\n".join(
        [
            "G21",
            "G90",
            "G17",
            "G40",
            "G64 P0.1",
            "M52 P1",
            "M68 E3 Q0",
            "G41.1 D#<_hal[plasmac.kerf-width]>",
            "M2",
        ]
    )

    issues = validate_gcode(bad_gcode)
    assert "cutter_compensation" in {issue.code for issue in issues}


def test_array_nest_places_repeated_parts_and_checks_sheet_bounds() -> None:
    part = PartProfile("disk", demo_contours(hole_radius=50))
    nested = array_nest(
        part,
        ArraySpec(rows=1, columns=2, spacing_x=500, spacing_y=0, origin_x=250, origin_y=250),
    )

    assert len(nested) == 4
    assert sorted({contour.center.x for contour in nested}) == [250, 750]
    assert_within_sheet(nested, Sheet(width=1000, height=500, margin=25))

    with pytest.raises(ValueError):
        assert_within_sheet(nested, Sheet(width=900, height=500, margin=25))


def test_shelf_nest_duplicates_parts_and_manual_edits_are_validated() -> None:
    part = PartProfile("disk", demo_contours(hole_radius=50))
    layout = shelf_nest(
        "two_disks",
        (PartRequest(part, quantity=2, allowed_rotations=(0, 90)),),
        ShelfNestOptions(sheet=Sheet(width=1000, height=500, margin=25), spacing=20),
    )

    assert [item.instance_id for item in layout.placed_parts] == ["disk_1", "disk_2"]
    assert not validate_layout(layout)

    moved = move_part(layout, "disk_2", -420, 0)
    assert {issue.code for issue in validate_layout(moved)} == {"part_collision"}

    rotated = rotate_part(layout, "disk_1", 90)
    assert rotated.placed_parts[0].placement.rotation_deg == 90


def test_validate_layout_builds_polygons_only_for_overlapping_bboxes(monkeypatch: pytest.MonkeyPatch) -> None:
    part = rectangle_profile("plate", 50, 50)
    layout = NestedLayout(
        name="lazy_validation",
        sheet=Sheet(width=500, height=300, margin=10),
        spacing=5,
        placed_parts=(
            placed_profile_at(part, 1, 10, 10),
            placed_profile_at(part, 2, 200, 10),
        ),
    )

    def fail_polygon(_part: PlacedPart):
        raise AssertionError("polygon should not be built for separated bboxes")

    monkeypatch.setattr(PlacedPart, "polygon", fail_polygon)

    assert validate_layout(layout) == []


def test_candidate_auto_nest_uses_rotation_and_valid_compact_boxes() -> None:
    wide = rectangle_profile("wide", 300, 180)
    tall = rectangle_profile("tall", 180, 300)
    layout = shelf_nest(
        "mixed_rectangles",
        (
            PartRequest(wide, quantity=4, allowed_rotations=(0, 90, 180, 270)),
            PartRequest(tall, quantity=4, allowed_rotations=(0, 90, 180, 270)),
        ),
        ShelfNestOptions(sheet=Sheet(width=1000, height=700, margin=10), spacing=8),
    )

    assert not validate_layout(layout)
    assert len(layout.placed_parts) == 8
    assert any(abs(part.placement.rotation_deg - 90) < 0.001 for part in layout.placed_parts)
    xmin, ymin, xmax, ymax = layout.cut_plan().bbox()
    assert xmin >= 10
    assert ymin >= 10
    assert xmax <= 990
    assert ymax <= 690


def test_auto_nest_prefers_lower_left_strip_before_moving_up() -> None:
    part = rectangle_profile("plate", 90, 80)
    result = shelf_nest_result(
        "strip_rows",
        (PartRequest(part, quantity=3, allowed_rotations=(0,)),),
        ShelfNestOptions(
            sheet=Sheet(width=400, height=300, margin=10),
            spacing=5,
            allow_arbitrary_rotation=False,
            attempt_limit=4,
        ),
    )

    boxes = sorted(part.bbox() for part in result.layout.placed_parts)

    assert [box[0] for box in boxes] == pytest.approx([10, 105, 200])
    assert [box[1] for box in boxes] == pytest.approx([10, 10, 10])
    assert max(box[3] for box in boxes) == pytest.approx(90)
    assert result.summary.used_height_mm == pytest.approx(80)
    assert result.summary.top_free_height_mm == pytest.approx(200)


def test_auto_nest_final_compaction_pulls_parts_down_and_left() -> None:
    sheet = Sheet(width=300, height=200, margin=10)
    part = rectangle_profile("plate", 50, 50)
    layout = NestedLayout(
        name="loose",
        sheet=sheet,
        spacing=5,
        placed_parts=(
            placed_profile_at(part, 1, 10, 10),
            placed_profile_at(part, 2, 150, 80),
        ),
    )

    compacted = _compact_layout(layout, ShelfNestOptions(sheet=sheet, spacing=5))
    boxes = {part.instance_id: part.bbox() for part in compacted.placed_parts}

    assert boxes["plate_1"][:2] == pytest.approx((10, 10))
    assert boxes["plate_2"][:2] == pytest.approx((65, 10))
    assert validate_layout(compacted) == []


def test_auto_nest_score_prefers_lower_left_mass_for_same_envelope() -> None:
    loose = [(10.0, 10.0, 110.0, 90.0), (210.0, 10.0, 310.0, 90.0), (410.0, 10.0, 510.0, 90.0)]
    compact = [(10.0, 10.0, 110.0, 90.0), (115.0, 10.0, 215.0, 90.0), (410.0, 10.0, 510.0, 90.0)]

    assert autonest_module._nest_score(compact, 10, 10) < autonest_module._nest_score(loose, 10, 10)


def test_auto_nest_score_prefers_less_skyline_waste_for_same_envelope() -> None:
    gappy = [(10.0, 10.0, 110.0, 110.0), (110.0, 110.0, 310.0, 210.0)]
    tighter = [(10.0, 110.0, 110.0, 210.0), (110.0, 10.0, 310.0, 110.0)]

    assert autonest_module._skyline_waste_area(gappy, 10, 10) == pytest.approx(20000.0)
    assert autonest_module._skyline_waste_area(tighter, 10, 10) == pytest.approx(10000.0)
    assert autonest_module._nest_score(tighter, 10, 10) < autonest_module._nest_score(gappy, 10, 10)


def test_auto_nest_keeps_time_for_final_compaction(monkeypatch: pytest.MonkeyPatch) -> None:
    sheet = Sheet(width=300, height=200, margin=10)
    part = rectangle_profile("plate", 50, 50)
    loose = NestedLayout(
        name="loose",
        sheet=sheet,
        spacing=5,
        placed_parts=(
            placed_profile_at(part, 1, 10, 10),
            placed_profile_at(part, 2, 150, 80),
        ),
    )
    compacted = NestedLayout(
        name="loose",
        sheet=sheet,
        spacing=5,
        placed_parts=(
            placed_profile_at(part, 1, 10, 10),
            placed_profile_at(part, 2, 65, 10),
        ),
    )
    clock = {"now": 100.0}
    compact_deadlines: list[float | None] = []

    def fake_lattice(*_args, **_kwargs):
        clock["now"] = 109.0
        yield loose, (0.0,), "loose"

    def fake_compact(layout, options, *, deadline=None, stats=None, cache=None):
        compact_deadlines.append(deadline)
        assert layout is loose
        return compacted

    monkeypatch.setattr(autonest_module.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(autonest_module, "_build_attempts", lambda *_args, **_kwargs: ([], False))
    monkeypatch.setattr(autonest_module, "_pack_lattice_attempts", fake_lattice)
    monkeypatch.setattr(autonest_module, "_compact_layout", fake_compact)

    result = shelf_nest_result(
        "reserved_compaction",
        (PartRequest(part, quantity=2, allowed_rotations=(0,)),),
        ShelfNestOptions(sheet=sheet, spacing=5, max_runtime_s=10),
    )

    assert compact_deadlines == [pytest.approx(110.0)]
    assert [placed.bbox()[:2] for placed in result.layout.placed_parts] == pytest.approx([(10, 10), (65, 10)])
    assert result.summary.time_limited is True


def test_auto_nest_compaction_rejects_invalid_result(monkeypatch: pytest.MonkeyPatch) -> None:
    sheet = Sheet(width=300, height=200, margin=10)
    part = rectangle_profile("plate", 50, 50)
    layout = NestedLayout(
        name="unsafe_compaction",
        sheet=sheet,
        spacing=5,
        placed_parts=(
            placed_profile_at(part, 1, 10, 10),
            placed_profile_at(part, 2, 100, 10),
        ),
    )

    def unsafe_slide(part: PlacedPart, axis: str, _options: ShelfNestOptions, _obstacles: list, **_kwargs) -> PlacedPart:
        if part.placement.instance == 2 and axis == "x":
            return placed_profile_at(part.profile, 2, 10, 10)
        return part

    monkeypatch.setattr(autonest_module, "_slide_part_axis", unsafe_slide)

    compacted = autonest_module._compact_layout(layout, ShelfNestOptions(sheet=sheet, spacing=5))

    assert [part.bbox() for part in compacted.placed_parts] == [part.bbox() for part in layout.placed_parts]
    assert validate_layout(compacted) == []


def test_auto_nest_time_budget_applies_to_first_attempt() -> None:
    part = rectangle_profile("plate", 50, 50)

    with pytest.raises(ValueError, match="within the optimization budget"):
        shelf_nest_result(
            "timeout",
            (PartRequest(part, quantity=20, allowed_rotations=(0, 90, 180, 270)),),
            ShelfNestOptions(
                sheet=Sheet(width=1000, height=1000, margin=10),
                spacing=5,
                max_runtime_s=0.000001,
                attempt_limit=20,
            ),
        )


def test_auto_nest_lattice_checks_deadline_inside_grid(monkeypatch: pytest.MonkeyPatch) -> None:
    part = rectangle_profile("plate", 20, 20)
    instances = [(part, index, (0,)) for index in range(1, 20)]
    options = ShelfNestOptions(sheet=Sheet(width=500, height=500, margin=10), spacing=5)

    monkeypatch.setattr(autonest_module.time, "monotonic", lambda: 2.0)

    with pytest.raises(TimeoutError, match="Auto nest time budget reached"):
        autonest_module._pack_lattice_rotation("timeout", instances, options, 0, deadline=1.0)


def test_auto_nest_candidate_generation_checks_deadline_inside_occupied_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    occupied = [((10.0, 10.0, 20.0, 20.0), None)]

    monkeypatch.setattr(autonest_module.time, "monotonic", lambda: 2.0)

    with pytest.raises(TimeoutError, match="Auto nest time budget reached"):
        autonest_module._candidate_positions(
            10,
            10,
            occupied,
            0,
            0,
            100,
            100,
            5,
            deadline=1.0,
        )


def test_auto_nest_budget_includes_request_preparation(monkeypatch: pytest.MonkeyPatch) -> None:
    project = example_project()
    project["nesting"] = {"auto_nest_max_runtime_s": 1}
    timestamps = iter((100.0, 101.1))

    monkeypatch.setattr(web_api_module.time, "monotonic", lambda: next(timestamps))
    monkeypatch.setattr(
        web_api_module,
        "_requests_from_project",
        lambda _project: [PartRequest(rectangle_profile("plate", 50, 50), quantity=1, allowed_rotations=(0,))],
    )
    monkeypatch.setattr(
        web_api_module,
        "_auto_nest_with_spacing",
        lambda *_args, **_kwargs: pytest.fail("_auto_nest_with_spacing should not run after budget expired"),
    )

    with pytest.raises(ValueError, match="Auto nest exceeded time budget"):
        auto_nest_project(project)


def test_auto_lead_override_stops_when_deadline_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    project = example_project()
    layout = web_api_module.layout_from_project(project)
    part = layout.placed_parts[0]
    contour = part.profile.contours[0]
    options = web_api_module._post_options_from_project(project, layout)

    monkeypatch.setattr(web_api_module.time, "monotonic", lambda: 2.0)
    monkeypatch.setattr(
        web_api_module,
        "_contour_has_lead_issues",
        lambda *_args, **_kwargs: pytest.fail("expired deadline should stop before lead issue checks"),
    )

    assert (
        web_api_module._best_auto_lead_override(
            project,
            layout,
            part,
            contour,
            [],
            options,
            deadline=1.0,
        )
        is None
    )


def test_auto_nest_uses_lattice_for_repeated_identical_parts() -> None:
    part = rectangle_profile("plate", 105.000028, 115.001353)
    result = shelf_nest_result(
        "twenty_plates",
        (PartRequest(part, quantity=20, allowed_rotations=(0, 45, 90, 135, 180, 225, 270, 315)),),
        ShelfNestOptions(
            sheet=Sheet(width=1000, height=1500, margin=10),
            spacing=8,
            attempt_limit=1,
            angle_step_deg=45,
            max_runtime_s=5,
        ),
    )

    assert result.summary.best_attempt.startswith("lattice/")
    assert result.summary.used_height_mm <= 370
    assert len(result.layout.placed_parts) == 20
    assert validate_layout(result.layout) == []


def test_project_auto_nest_defaults_to_quarter_turn_rotations_when_missing() -> None:
    project = example_project()
    project["sheet"] = {"width_mm": 500, "height_mm": 800, "margin_mm": 10}
    project["parts"] = [rectangle_part_json("wide_only_fits_rotated", 700, 400)]
    project["placements"] = []
    project["auto_nest"] = True

    preview = preview_from_project(project)

    assert preview["issues"] == []
    assert preview["parts"][0]["placement"]["rotation_deg"] in (90.0, 270.0)


def test_project_auto_nest_honors_part_allowed_rotations_and_grain_lock() -> None:
    project = example_project()
    project["sheet"] = {"width_mm": 500, "height_mm": 800, "margin_mm": 10}
    project["post"]["lead_in_mode"] = "none"
    project["parts"] = [rectangle_part_json("wide_only_fits_rotated", 700, 400)]
    project["placements"] = []
    project["nesting"] = {"auto_nest_attempts": 1, "auto_nest_angle_step_deg": 90, "allow_arbitrary_rotation": True}
    project["parts"][0]["allowed_rotations"] = [90]

    nested = auto_nest_project(project)

    assert [placement["rotation_deg"] for placement in nested["placements"]] == [90.0]

    project["parts"][0]["grain_lock"] = True

    with pytest.raises(ValueError, match="Could not fit"):
        auto_nest_project(project)


def test_layout_export_rejects_colliding_manual_placements() -> None:
    part = PartProfile("disk", demo_contours(hole_radius=50))
    layout = shelf_nest(
        "two_disks",
        (PartRequest(part, quantity=2),),
        ShelfNestOptions(sheet=Sheet(width=1000, height=500, margin=25), spacing=20),
    )
    moved = move_part(layout, "disk_2", -420, 0)

    with pytest.raises(LayoutValidationError):
        assert_valid_layout(moved)


def test_project_exports_valid_qtplasmac_gcode() -> None:
    project = example_project()

    assert validate_project(project) == []
    preview = preview_from_project(project)
    assert preview["parts"][0]["instance_id"] == "disk_1"

    gcode = export_project_gcode(project)
    assert_valid_gcode(gcode)
    assert "fr=1300" in gcode
    assert "disk_1_disk_hole_1 hole pierce" in gcode
    assert "disk_1_disk_outer outer pierce" in gcode


def test_project_outline_export_traces_outer_contours_without_torch() -> None:
    project = example_project()

    gcode = export_project_outline_gcode(project)

    assert_valid_gcode(gcode)
    assert "Torch is never started" in gcode
    assert "M3" not in gcode
    assert "M5 $0" not in gcode
    assert "M5 $-1" in gcode
    assert "F3000" in gcode
    assert "disk_1_disk_outer outer dry outline" in gcode
    assert "disk_1_disk_hole" not in gcode


def test_project_outline_export_preserves_path_outer_shape() -> None:
    project = example_project()
    project["sheet"] = {"width_mm": 200, "height_mm": 100, "margin_mm": 10}
    project["parts"] = [rectangle_part_json("plate", 50, 50)]
    project["placements"] = [
        {"part_name": "plate", "instance": 1, "dx": 35, "dy": 35, "rotation_deg": 0},
    ]

    gcode = export_project_outline_gcode(project)

    assert_valid_gcode(gcode)
    assert "plate_1_plate_outer outer dry outline" in gcode
    assert "G0 X10 Y10" in gcode
    assert "G1 X60 Y10" in gcode
    assert "G1 X60 Y60" in gcode
    assert "M3" not in gcode


def test_project_review_dxf_exports_sheet_layers_and_native_arc_entities() -> None:
    project = example_project()
    project["sheet"] = {"width_mm": 220, "height_mm": 140, "margin_mm": 12}
    project["parts"] = [capsule_part_json("capsule")]
    project["placements"] = [
        {"part_name": "capsule", "instance": 1, "dx": 80, "dy": 70, "rotation_deg": 0},
    ]
    project["zones"] = [
        {
            "id": "clamp_1",
            "type": "clamp",
            "name": "front clamp",
            "x_mm": 5,
            "y_mm": 5,
            "width_mm": 30,
            "height_mm": 15,
            "enabled": True,
        }
    ]
    project["lead_overrides"] = [
        {
            "contour_name": "capsule_1_capsule_outer",
            "start_x_mm": 60,
            "start_y_mm": 60,
            "pierce_x_mm": 55,
            "pierce_y_mm": 55,
            "lead_in_mode": "line",
        }
    ]
    project["tabs"] = [{"contour_name": "capsule_1_capsule_outer", "x_mm": 80, "y_mm": 60, "length_mm": 8}]

    dxf = export_project_review_dxf(project)

    assert "SECTION\n2\nENTITIES" in dxf
    assert "0\nLINE\n8\nSHEET" in dxf
    assert "0\nLINE\n8\nMARGIN" in dxf
    assert "0\nARC\n8\nOUTER" in dxf
    assert "0\nCIRCLE\n8\nHOLE" in dxf
    assert "0\nLINE\n8\nZONES" in dxf
    assert "0\nLINE\n8\nLEAD" in dxf
    assert "0\nLINE\n8\nTABS" in dxf
    assert "capsule_1" in dxf
    assert dxf.endswith("0\nEOF\n")


def test_project_review_report_includes_metrics_settings_and_validation_warnings() -> None:
    project = example_project()
    project["post"]["cut_order_strategy"] = "lower_left"
    project["nesting"] = {
        "last_result": {"packing_utilization_percent": 55.5, "runtime_ms": 12.3},
        "run_history": [{"run_id": 1, "packing_utilization_percent": 55.5}],
    }
    project["import"] = {
        "source": "dxf",
        "safe_for_export": True,
        "blocking_issue_count": 0,
        "warning_count": 1,
        "issues": [
            {
                "code": "duplicate_segment_repaired",
                "message": "Duplicate segment ignored",
                "blocking": False,
            }
        ],
    }

    report = project_review_report(project)

    assert report["name"] == "circle_with_center_hole"
    assert report["parts"]["placed_instance_count"] == 1
    assert report["import_summary"]["warning_count"] == 1
    assert report["nesting"]["current_utilization"]["sheet_utilization_percent"] > 0
    assert report["nesting"]["last_result"]["packing_utilization_percent"] == 55.5
    assert report["cut_settings"]["row_id"] == "mild_steel-3mm-n0p9-starter"
    assert report["cut_settings"]["feed_rate_mm_min"] == 1300
    assert report["cut_order"]["available"] is True
    assert report["cut_order"]["strategy"] == "lower_left"
    assert report["cut_order"]["avoid_completed_contours"] is True
    assert [item["sequence"] for item in report["cut_order"]["sequence"]] == [1, 2]
    assert {item["kind"] for item in report["cut_order"]["sequence"]} == {"hole", "outer"}
    assert report["cam_geometry"]["total_count"] == 0
    assert report["cam_geometry"]["centerline_fallback_count"] == 0
    assert report["dxf_repair_plan"]["required"] is False
    assert report["dxf_repair_plan"]["completed_repair_warning_count"] == 1
    assert report["dxf_repair_plan"]["completed_repair_codes"] == {"import_duplicate_segment_repaired": 1}
    assert report["export_preflight"]["can_export"] is True
    assert report["export_preflight"]["blocking_issue_count"] == 0
    assert report["export_preflight"]["warning_count"] == 1
    assert report["export_preflight"]["warning_codes"] == ["import_duplicate_segment_repaired"]
    assert report["export_preflight"]["gcode_line_count"] > 0
    assert report["export_preflight"]["gcode_validation_issue_count"] == 0
    assert report["export_preflight"]["gcode_validation_codes"] == []
    assert report["issue_summary"]["total_count"] == 1
    assert report["issue_summary"]["blocking_count"] == 0
    assert report["issue_summary"]["warning_count"] == 1
    assert report["issue_summary"]["warning_codes"] == {"import_duplicate_segment_repaired": 1}
    assert report["issue_summary"]["warning_examples"][0]["message"] == "Duplicate segment ignored"
    assert report["simulation_metrics"]["pierce_count"] == 2
    assert report["simulation_metrics"]["cut_length_mm"] > 0
    assert report["simulation_metrics"]["rapid_length_mm"] > 0
    assert report["simulation_metrics"]["estimated_total_s"] > 0
    assert report["operator_checklist"]["status"] == "warnings"
    assert report["operator_checklist"]["ready_to_export"] is True
    assert report["operator_checklist"]["requires_warning_ack"] is True
    assert report["operator_checklist"]["blocking_count"] == 0
    assert {check["code"] for check in report["operator_checklist"]["checks"]} == {
        "placements",
        "blocking_issues",
        "cut_settings",
        "simulation",
        "cut_order",
        "gcode_preflight",
    }
    assert {warning["code"] for warning in report["operator_checklist"]["warnings"]} == {"validation_warnings"}
    assert {issue["code"] for issue in report["validation_issues"]} == {"import_duplicate_segment_repaired"}
    assert {warning["code"] for warning in report["warnings"]} == {"import_duplicate_segment_repaired"}


def test_project_review_report_export_preflight_warns_for_unsafe_project() -> None:
    project = example_project()
    project["parts"] = [rectangle_part_json("plate", 50, 50, quantity=2)]
    project["placements"] = [
        {"part_name": "plate", "instance": 1, "dx": 50, "dy": 50, "rotation_deg": 0},
        {"part_name": "plate", "instance": 2, "dx": 55, "dy": 50, "rotation_deg": 0},
    ]

    report = project_review_report(project)

    assert report["export_preflight"]["can_export"] is True
    assert report["export_preflight"]["blocking_issue_count"] == 0
    assert "part_collision" in report["export_preflight"]["warning_codes"]
    assert report["operator_checklist"]["status"] == "warnings"
    assert report["operator_checklist"]["ready_to_export"] is True
    assert report["operator_checklist"]["requires_warning_ack"] is True
    assert report["operator_checklist"]["blocking_count"] == 0
    assert not {
        check["code"] for check in report["operator_checklist"]["checks"] if check["status"] == "block"
    }
    assert report["issue_summary"]["blocking_count"] == 0
    assert report["issue_summary"]["warning_codes"]["part_collision"] >= 1


def test_project_review_report_includes_dxf_repair_plan_for_blocking_import_issues() -> None:
    project = example_project()
    project["import"] = {
        "source": "dxf",
        "safe_for_export": False,
        "issues": [
            {
                "code": "self_intersection",
                "message": "Self-intersection at X1 Y2",
                "blocking": True,
                "x": 1.0,
                "y": 2.0,
                "sheet_x": 11.0,
                "sheet_y": 12.0,
            },
            {
                "code": "collinear_overlap",
                "message": "Overlapping edge",
                "blocking": True,
                "x": 3.0,
                "y": 4.0,
                "target_x": 5.0,
                "target_y": 4.0,
                "sheet_x": 13.0,
                "sheet_y": 14.0,
                "target_sheet_x": 15.0,
                "target_sheet_y": 14.0,
            },
            {
                "code": "open_contour",
                "message": "Open contour",
                "blocking": True,
                "x": 7.0,
                "y": 8.0,
                "target_x": 9.0,
                "target_y": 8.0,
                "chain_length_mm": 42.0,
            },
        ],
    }

    report = project_review_report(project)
    repair_plan = report["dxf_repair_plan"]
    actions = {action["code"]: action for action in repair_plan["actions"]}

    assert report["export_preflight"]["can_export"] is True
    assert repair_plan["required"] is False
    assert repair_plan["review_required"] is False
    assert repair_plan["safe_for_export"] is True
    assert repair_plan["blocking_count"] == 0
    assert repair_plan["blocking_codes"] == {}
    assert repair_plan["review_required_count"] == 0
    assert repair_plan["review_required_codes"] == {}
    assert repair_plan["action_count"] == 0
    assert actions == {}
    assert repair_plan["completed_repair_warning_count"] == 0
    assert repair_plan["completed_repair_codes"] == {}
    assert report["issue_summary"]["blocking_count"] == 0
    assert report["issue_summary"]["warning_count"] == 3


def test_export_gcode_warns_for_legacy_blocking_import_issues_without_blocking() -> None:
    project = example_project()
    project["import"] = {
        "source": "dxf",
        "safe_for_export": False,
        "issues": [
            {
                "code": "open_contour",
                "message": "Open contour",
                "blocking": True,
            },
            {
                "code": "self_intersection",
                "message": "Self-intersection at X1 Y2",
                "blocking": True,
            },
        ],
    }

    gcode = export_project_gcode(project)

    assert "WARNING: import_open_contour" in gcode
    assert "WARNING: import_self_intersection" in gcode
    assert "M3" in gcode
    assert "M5" in gcode


def test_project_keepout_zone_blocks_validation_and_export() -> None:
    project = example_project()
    project["zones"] = [
        {
            "id": "keepout_1",
            "type": "keepout",
            "x_mm": 100,
            "y_mm": 100,
            "width_mm": 350,
            "height_mm": 250,
            "enabled": True,
        }
    ]

    issues = validate_project(project)

    assert "zone_collision" in {issue["code"] for issue in issues}
    gcode = export_project_gcode(project)
    assert "WARNING: zone_collision" in gcode


def test_pierce_keepout_zone_blocks_pierce_without_blocking_placement() -> None:
    project = example_project()
    layout = web_api_module.layout_from_project(project)
    options = web_api_module._post_options_from_project(project, layout)
    first_move = planned_lead_moves(layout.contours(), options)[0]
    project["zones"] = [
        {
            "id": "pierce_1",
            "type": "pierce_keepout",
            "name": "pierce test",
            "x_mm": first_move.pierce.x - 5,
            "y_mm": first_move.pierce.y - 5,
            "width_mm": 10,
            "height_mm": 10,
            "enabled": True,
        }
    ]

    issues = validate_project(project)
    issue_codes = {issue["code"] for issue in issues}

    assert "pierce_zone_collision" in issue_codes
    assert "zone_collision" not in issue_codes
    gcode = export_project_gcode(project)
    assert "WARNING: pierce_zone_collision" in gcode


def test_project_lead_crater_outside_sheet_blocks_export() -> None:
    project = example_project()
    project["sheet"] = {"width_mm": 100, "height_mm": 100, "margin_mm": 10}
    project["spacing_mm"] = 0
    project["parts"] = [circle_part_json("disk", 20)]
    project["placements"] = [{"part_name": "disk", "instance": 1, "dx": 70, "dy": 50, "rotation_deg": 0}]
    project["post"].update(
        {
            "lead_in_mode": "line",
            "lead_in_mm": 15,
            "lead_out_mm": 0,
            "pierce_crater_diameter_mm": 4,
            "lead_clearance_mm": 1,
        }
    )

    issues = validate_project(project)

    assert "lead_outside_sheet" in {issue["code"] for issue in issues}
    gcode = export_project_gcode(project)
    assert "WARNING: lead_outside_sheet" in gcode


def test_project_lead_collision_with_neighbor_blocks_export() -> None:
    project = example_project()
    project["sheet"] = {"width_mm": 150, "height_mm": 100, "margin_mm": 10}
    project["spacing_mm"] = 0
    project["parts"] = [
        circle_part_json("left", 20),
        circle_part_json("right", 10),
    ]
    project["placements"] = [
        {"part_name": "left", "instance": 1, "dx": 50, "dy": 50, "rotation_deg": 0},
        {"part_name": "right", "instance": 1, "dx": 88, "dy": 50, "rotation_deg": 0},
    ]
    project["post"].update(
        {
            "lead_in_mode": "line",
            "lead_in_mm": 10,
            "lead_out_mm": 0,
            "pierce_crater_diameter_mm": 2,
            "lead_clearance_mm": 0.5,
        }
    )

    issues = validate_project(project)

    assert "part_collision" not in {issue["code"] for issue in issues}
    assert "lead_collision" in {issue["code"] for issue in issues}
    gcode = export_project_gcode(project)
    assert "WARNING: lead_collision" in gcode


def test_project_tabs_and_lead_overrides_survive_export_and_simulation() -> None:
    project = example_project()
    project["post"]["lead_in_mode"] = "line"
    project["post"]["lead_in_mm"] = 4
    project["tabs"] = [
        {
            "contour_name": "disk_1_disk_outer",
            "x_mm": 450,
            "y_mm": 250,
            "length_mm": 10,
        }
    ]
    project["lead_overrides"] = [
        {
            "contour_name": "disk_1_disk_outer",
            "start_x_mm": 250,
            "start_y_mm": 450,
            "lead_in_mode": "line",
            "lead_in_mm": 4,
        }
    ]

    gcode = export_project_gcode(project)
    simulation = simulation_from_project(project)

    assert_valid_gcode(gcode)
    assert "tab bridge skip" in gcode
    assert "G1 X250 Y450.6 (lead in)" in gcode
    assert any(segment.get("tab_bridge") for segment in simulation["segments"])


def test_stale_leads_and_tabs_after_reimport_block_export() -> None:
    project = example_project()
    project["post"]["lead_in_mode"] = "line"
    project["lead_overrides"] = [
        {
            "contour_name": "disk_1_old_outer",
            "start_x_mm": 250,
            "start_y_mm": 450,
            "lead_in_mode": "line",
        }
    ]
    project["tabs"] = [{"contour_name": "disk_1_old_outer", "x_mm": 450, "y_mm": 250, "length_mm": 10}]

    issues = validate_project(project)

    assert {"stale_lead_override", "stale_tab"} <= {issue["code"] for issue in issues}
    gcode = export_project_gcode(project)
    assert "WARNING: stale_lead_override" in gcode
    assert "WARNING: stale_tab" in gcode


def test_auto_nest_api_avoids_keepout_zone() -> None:
    project = example_project()
    project["post"]["lead_in_mode"] = "none"
    project["post"]["safe_travel"] = False
    project["parts"] = [rectangle_part_json("plate", 120, 80, quantity=2)]
    project["placements"] = []
    project["nesting"] = {"auto_nest_attempts": 12, "auto_nest_angle_step_deg": 15, "allow_arbitrary_rotation": True}
    project["zones"] = [
        {
            "id": "clamp_1",
            "type": "clamp",
            "x_mm": 10,
            "y_mm": 10,
            "width_mm": 150,
            "height_mm": 120,
            "enabled": True,
        }
    ]

    nested = auto_nest_project(project)

    assert validate_project(nested) == []
    assert len(nested["placements"]) == 2
    assert all(placement["dx"] > 160 or placement["dy"] > 130 for placement in nested["placements"])


def test_common_line_project_allows_touching_parts_with_zero_effective_spacing() -> None:
    project = example_project()
    project["sheet"] = {"width_mm": 200, "height_mm": 100, "margin_mm": 10}
    project["spacing_mm"] = 8
    project["parts"] = [rectangle_part_json("plate", 50, 50, quantity=2)]
    project["placements"] = [
        {"part_name": "plate", "instance": 1, "dx": 35, "dy": 35, "rotation_deg": 0},
        {"part_name": "plate", "instance": 2, "dx": 85, "dy": 35, "rotation_deg": 0},
    ]

    assert "part_collision" in {issue["code"] for issue in validate_project(project)}

    project["nesting"] = {"common_line_cutting": True}
    project["post"]["lead_in_mode"] = "none"
    project["post"]["pierce_crater_diameter_mm"] = 0

    issues = validate_project(project)

    assert "part_collision" not in {issue["code"] for issue in issues}
    assert {issue["code"] for issue in issues} == {"common_line_kerf_offset"}
    gcode = export_project_gcode(project)
    assert "WARNING: common_line_kerf_offset" in gcode
    assert "common line skipped 1 shared segment" in gcode


def test_common_line_centerline_fallback_allows_export_and_simulation() -> None:
    project = example_project()
    project["sheet"] = {"width_mm": 200, "height_mm": 100, "margin_mm": 10}
    project["spacing_mm"] = 8
    project["parts"] = [rectangle_part_json("plate", 50, 50, quantity=2)]
    project["placements"] = [
        {"part_name": "plate", "instance": 1, "dx": 35, "dy": 35, "rotation_deg": 0},
        {"part_name": "plate", "instance": 2, "dx": 85, "dy": 35, "rotation_deg": 0},
    ]
    project["nesting"] = {"common_line_cutting": True}
    project["post"]["lead_in_mode"] = "none"
    project["post"]["lead_in_mm"] = 0
    project["post"]["lead_out_mm"] = 0
    project["post"]["pierce_crater_diameter_mm"] = 0
    project["post"]["lead_clearance_mm"] = 0
    project["post"]["safe_travel"] = False
    project["post"]["kerf_offset_fallback"] = "centerline"

    issues = validate_project(project)
    gcode = export_project_gcode(project)
    simulation = simulation_from_project(project)

    assert issues == [
        {
            "code": "common_line_centerline",
            "message": (
                "Common-line cutting found 1 shared straight edge(s); "
                "centerline fallback will cut without geometry kerf compensation."
            ),
            "instance_id": None,
            "blocking": False,
        }
    ]
    assert_valid_gcode(gcode)
    assert "WARNING: common_line_centerline: Common-line cutting found 1 shared straight edge" in gcode
    assert "common line skipped 1 shared segment" in gcode
    assert "common-line chain 1 pierce" in gcode
    assert simulation["segments"]
    assert any(segment["type"] == "cut" for segment in simulation["segments"])
    assert sum(1 for segment in simulation["segments"] if segment["type"] == "pierce") == 2


def test_common_line_project_without_shared_edges_keeps_regular_export_path() -> None:
    project = example_project()
    project["sheet"] = {"width_mm": 200, "height_mm": 100, "margin_mm": 10}
    project["parts"] = [rectangle_part_json("plate", 50, 50)]
    project["placements"] = [
        {"part_name": "plate", "instance": 1, "dx": 35, "dy": 35, "rotation_deg": 0},
    ]
    project["nesting"] = {"common_line_cutting": True}

    assert validate_project(project) == []
    assert_valid_gcode(export_project_gcode(project))


def test_auto_nest_reports_utilization_summary() -> None:
    project = example_project()
    project["parts"] = [rectangle_part_json("plate", 120, 80, quantity=3)]
    project["placements"] = []
    project["nesting"] = {"auto_nest_attempts": 16, "auto_nest_angle_step_deg": 15, "allow_arbitrary_rotation": True}

    nested = auto_nest_project(project)
    summary = nested["nesting"]["last_result"]

    assert summary["attempt_count"] >= 16
    assert summary["successful_attempt_count"] > 0
    assert summary["used_width_mm"] > 0
    assert summary["used_height_mm"] > 0
    assert summary["used_strip_area_mm2"] >= summary["used_bbox_area_mm2"]
    assert summary["top_free_height_mm"] >= 0
    assert summary["packing_utilization_percent"] > 0
    assert summary["bbox_utilization_percent"] > 0
    assert summary["sheet_utilization_percent"] > 0
    assert summary["time_limited"] is False
    assert summary["best_attempt"]
    assert summary["geometry_engine"] == "polygon-nfp-v1"
    assert summary["runtime_ms"] >= 0
    assert summary["parallel_worker_count"] >= 1
    assert summary["attempts_per_second"] >= 0
    assert summary["candidate_position_count"] > 0
    assert summary["exact_clearance_check_count"] >= 0
    assert summary["cache_hit_count"] >= 0
    assert summary["cache_miss_count"] > 0
    history = nested["nesting"]["run_history"]
    assert len(history) == 1
    assert history[0]["run_id"] == 1
    assert history[0]["part_instance_count"] == 3
    assert history[0]["best_attempt"] == summary["best_attempt"]
    assert history[0]["packing_utilization_percent"] == summary["packing_utilization_percent"]
    assert history[0]["created_at"].endswith("Z")


def test_auto_nest_falls_back_to_valid_current_layout(monkeypatch: pytest.MonkeyPatch) -> None:
    project = example_project()
    project["parts"] = [rectangle_part_json("plate", 120, 80, quantity=2)]
    project["placements"] = [
        {"part_name": "plate", "instance": 1, "dx": 70, "dy": 50, "rotation_deg": 0},
        {"part_name": "plate", "instance": 2, "dx": 210, "dy": 50, "rotation_deg": 0},
    ]

    def fail_auto_nest(*_args, **_kwargs):
        raise ValueError("forced search failure")

    monkeypatch.setattr(web_api_module, "_auto_nest_with_spacing", fail_auto_nest)

    nested = auto_nest_project(project)
    summary = nested["nesting"]["last_result"]

    assert [item["instance"] for item in nested["placements"]] == [1, 2]
    assert summary["best_attempt"] == "current_layout_fallback"
    assert summary["current_layout_fallback"] is True
    assert "forced search failure" in summary["parallel_fallback_reason"]
    assert nested["nesting"]["run_history"][-1]["current_layout_fallback"] is True


def test_auto_nest_current_layout_fallback_skips_lead_spacing_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    project = example_project()
    project["parts"] = [rectangle_part_json("plate", 120, 80, quantity=2)]
    project["placements"] = [
        {"part_name": "plate", "instance": 1, "dx": 70, "dy": 50, "rotation_deg": 0},
        {"part_name": "plate", "instance": 2, "dx": 210, "dy": 50, "rotation_deg": 0},
    ]

    def fail_auto_nest(*_args, **_kwargs):
        raise ValueError("forced timeout")

    def fail_lead_scan(*_args, **_kwargs):
        raise AssertionError("lead spacing scan should be skipped for current-layout fallback")

    monkeypatch.setattr(web_api_module, "_auto_nest_with_spacing", fail_auto_nest)
    monkeypatch.setattr(web_api_module, "_lead_issue_items", fail_lead_scan)

    nested = auto_nest_project(project)
    summary = nested["nesting"]["last_result"]

    assert summary["best_attempt"] == "current_layout_fallback"
    assert summary["lead_spacing_fallback_skipped"] == "current_layout_fallback"


def test_auto_nest_preserves_existing_layout_when_complexity_limit_is_exceeded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = example_project()
    project["parts"] = [rectangle_part_json("plate", 120, 80, quantity=2)]
    project["placements"] = [
        {"part_name": "plate", "instance": 1, "dx": 70, "dy": 50, "rotation_deg": 0},
        {"part_name": "plate", "instance": 2, "dx": 210, "dy": 50, "rotation_deg": 0},
    ]

    def fail_auto_nest(*_args, **_kwargs):
        raise AssertionError("search should not run after complexity fallback")

    monkeypatch.setattr(web_api_module, "AUTO_NEST_COMPLEXITY_FALLBACK_MAX_INSTANCES", 1)
    monkeypatch.setattr(web_api_module, "_auto_nest_with_spacing", fail_auto_nest)

    nested = auto_nest_project(project)
    summary = nested["nesting"]["last_result"]

    assert [item["dx"] for item in nested["placements"]] == [70, 210]
    assert summary["best_attempt"] == "current_layout_complexity_fallback"
    assert summary["complexity_fallback"] is True
    assert summary["complexity_instance_count"] == 2
    assert "complexity limit" in summary["complexity_fallback_reason"]
    assert nested["nesting"]["run_history"][-1]["complexity_fallback"] is True


def test_auto_nest_rotation_dedup_respects_expired_deadline() -> None:
    profile = rectangle_profile("plate", 100, 50)
    cache = autonest_module._GeometryCache()

    with pytest.raises(TimeoutError):
        autonest_module._unique_profile_rotations(
            profile,
            (0, 45, 90, 135),
            cache,
            deadline=autonest_module.time.monotonic() - 1.0,
        )


def test_validate_project_reports_warning_for_complex_layout_without_collision_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = example_project()
    project["parts"] = [rectangle_part_json("plate", 120, 80, quantity=2)]
    project["placements"] = [
        {"part_name": "plate", "instance": 1, "dx": 70, "dy": 50, "rotation_deg": 0},
        {"part_name": "plate", "instance": 2, "dx": 210, "dy": 50, "rotation_deg": 0},
    ]

    def fail_collision_scan(_layout):
        raise AssertionError("complex layouts should not run full layout collision precheck")

    monkeypatch.setattr(web_api_module, "LAYOUT_VALIDATION_MAX_PARTS", 1)
    monkeypatch.setattr(web_api_module, "validate_layout", fail_collision_scan)

    issues = validate_project(project)
    issue_codes = {issue["code"] for issue in issues}
    complexity_issue = next(issue for issue in issues if issue["code"] == "layout_complexity")

    assert "part_collision" not in issue_codes
    assert "precheck skipped" in complexity_issue["message"]
    assert complexity_issue["blocking"] is False


def test_auto_nest_uses_bbox_fallback_for_very_complex_profiles() -> None:
    part = segmented_rectangle_profile("complex_plate", 120, 80, segments_per_side=1300)

    result = shelf_nest_result(
        "complex",
        (PartRequest(part, quantity=1, allowed_rotations=(0,)),),
        ShelfNestOptions(
            sheet=Sheet(width=500, height=300, margin=10),
            spacing=5,
            allow_arbitrary_rotation=False,
            attempt_limit=1,
            max_runtime_s=1,
        ),
    )

    assert validate_layout(result.layout) == []
    assert result.summary.bbox_fallback_count > 0
    assert result.summary.runtime_ms < 1000


def test_auto_nest_run_history_is_bounded_and_incremental() -> None:
    project = example_project()
    project["parts"] = [rectangle_part_json("plate", 60, 40, quantity=1)]
    project["placements"] = []
    project["nesting"] = {
        "auto_nest_attempts": 1,
        "auto_nest_angle_step_deg": 90,
        "allow_arbitrary_rotation": False,
        "run_history": [{"run_id": index + 1, "best_attempt": f"old-{index + 1}"} for index in range(25)],
    }

    nested = auto_nest_project(project)
    history = nested["nesting"]["run_history"]

    assert len(history) == web_api_module.MAX_NEST_RUN_HISTORY
    assert history[-1]["run_id"] == 26
    assert history[0]["run_id"] == 7
    assert history[-1]["requested_attempts"] == 1
    assert history[-1]["requested_angle_step_deg"] == 90
    assert history[-1]["allow_arbitrary_rotation"] is False


def test_auto_nest_can_relocate_small_part_into_large_internal_cutout() -> None:
    project = example_project()
    project["sheet"] = {"width_mm": 220, "height_mm": 140, "margin_mm": 10}
    project["spacing_mm"] = 0
    project["parts"] = [
        rectangle_with_rect_hole_part_json("frame", 100, 100, 60, 60),
        rectangle_part_json("token", 40, 40),
    ]
    project["placements"] = []
    project["nesting"] = {
        "auto_nest_attempts": 1,
        "auto_nest_angle_step_deg": 90,
        "allow_arbitrary_rotation": False,
        "allow_hole_filler": True,
    }

    nested = auto_nest_project(project)
    placements = {item["part_name"]: item for item in nested["placements"]}
    token = placements["token"]
    frame = placements["frame"]
    token_box = (token["dx"] - 20, token["dy"] - 20, token["dx"] + 20, token["dy"] + 20)
    frame_hole = (frame["dx"] - 30, frame["dy"] - 30, frame["dx"] + 30, frame["dy"] + 30)

    assert token_box[0] >= frame_hole[0] - 0.001
    assert token_box[1] >= frame_hole[1] - 0.001
    assert token_box[2] <= frame_hole[2] + 0.001
    assert token_box[3] <= frame_hole[3] + 0.001
    assert nested["nesting"]["last_result"]["hole_filler_relocation_count"] == 1
    assert nested["nesting"]["run_history"][-1]["hole_filler_relocation_count"] == 1
    issues = validate_project(nested)

    assert "hole_filler_requires_bridge" in {issue["code"] for issue in issues}
    gcode_without_bridges = export_project_gcode(nested)
    simulation_without_bridges = simulation_from_project(nested)
    assert "WARNING: hole_filler_requires_bridge" in gcode_without_bridges
    assert any(segment["type"] == "cut" for segment in simulation_without_bridges["segments"])

    nested["tabs"] = [
        {
            "contour_name": "frame_1_frame_window",
            "x_mm": frame["dx"],
            "y_mm": frame["dy"] - 30,
            "length_mm": 8,
        },
        {
            "contour_name": "frame_1_frame_window",
            "x_mm": frame["dx"],
            "y_mm": frame["dy"] + 30,
            "length_mm": 8,
        },
    ]
    assert validate_project(nested) == []
    gcode = export_project_gcode(nested)
    simulation = simulation_from_project(nested)
    assert gcode.count("tab bridge skip") >= 2
    assert sum(1 for segment in simulation["segments"] if segment.get("tab_bridge")) >= 2
    assert gcode.index("token_1_token_outer outer pierce") < gcode.index("frame_1_frame_window hole pierce")


def test_auto_nest_keeps_internal_cutout_filler_disabled_by_default() -> None:
    project = example_project()
    project["sheet"] = {"width_mm": 220, "height_mm": 140, "margin_mm": 10}
    project["spacing_mm"] = 0
    project["parts"] = [
        rectangle_with_rect_hole_part_json("frame", 100, 100, 60, 60),
        rectangle_part_json("token", 40, 40),
    ]
    project["placements"] = []
    project["nesting"] = {
        "auto_nest_attempts": 1,
        "auto_nest_angle_step_deg": 90,
        "allow_arbitrary_rotation": False,
    }

    nested = auto_nest_project(project)

    assert nested["nesting"]["last_result"]["hole_filler_relocation_count"] == 0


def test_auto_nest_hole_filler_policy_can_forbid_child_relocation() -> None:
    project = example_project()
    project["sheet"] = {"width_mm": 220, "height_mm": 140, "margin_mm": 10}
    project["spacing_mm"] = 0
    token = rectangle_part_json("token", 40, 40)
    token["allow_hole_filler"] = False
    project["parts"] = [
        rectangle_with_rect_hole_part_json("frame", 100, 100, 60, 60),
        token,
    ]
    project["placements"] = []
    project["nesting"] = {
        "auto_nest_attempts": 1,
        "auto_nest_angle_step_deg": 90,
        "allow_arbitrary_rotation": False,
        "allow_hole_filler": True,
    }

    nested = auto_nest_project(project)

    assert nested["nesting"]["last_result"]["hole_filler_relocation_count"] == 0


def test_auto_nest_hole_parent_policy_can_forbid_container_cutouts() -> None:
    project = example_project()
    project["sheet"] = {"width_mm": 220, "height_mm": 140, "margin_mm": 10}
    project["spacing_mm"] = 0
    frame = rectangle_with_rect_hole_part_json("frame", 100, 100, 60, 60)
    frame["allow_hole_parent"] = False
    project["parts"] = [
        frame,
        rectangle_part_json("token", 40, 40),
    ]
    project["placements"] = []
    project["nesting"] = {
        "auto_nest_attempts": 1,
        "auto_nest_angle_step_deg": 90,
        "allow_arbitrary_rotation": False,
        "allow_hole_filler": True,
    }

    nested = auto_nest_project(project)

    assert nested["nesting"]["last_result"]["hole_filler_relocation_count"] == 0


def test_auto_nest_uses_polygon_nfp_for_curved_triangle_pack() -> None:
    project = example_project()
    project["post"]["lead_in_mode"] = "none"
    project["post"]["pierce_crater_diameter_mm"] = 0
    project["sheet"] = {"width_mm": 260, "height_mm": 207, "margin_mm": 10}
    project["spacing_mm"] = 0
    project["parts"] = [
        {
            "name": "round",
            "quantity": 3,
            "outer": {"type": "circle", "radius_mm": 50},
            "holes": [],
        }
    ]
    project["placements"] = []
    project["nesting"] = {"auto_nest_attempts": 1, "auto_nest_angle_step_deg": 30, "allow_arbitrary_rotation": True}

    nested = auto_nest_project(project)
    summary = nested["nesting"]["last_result"]

    assert validate_project(nested) == []
    assert len(nested["placements"]) == 3
    assert summary["nfp_candidate_count"] > 0
    assert summary["used_height_mm"] < 190


def test_auto_nest_generates_safe_lead_overrides_for_tight_round_parts() -> None:
    project = example_project()
    project["sheet"] = {"width_mm": 260, "height_mm": 207, "margin_mm": 10}
    project["spacing_mm"] = 0
    project["parts"] = [
        {
            "name": "round",
            "quantity": 3,
            "outer": {"type": "circle", "radius_mm": 50},
            "holes": [],
        }
    ]
    project["placements"] = []
    project["nesting"] = {"auto_nest_attempts": 1, "auto_nest_angle_step_deg": 30, "allow_arbitrary_rotation": True}
    project["post"].update(
        {
            "lead_in_mode": "line",
            "lead_in_mm": 5,
            "pierce_crater_diameter_mm": 4,
            "lead_clearance_mm": 1,
        }
    )

    nested = auto_nest_project(project)
    issues = validate_project(nested)

    assert issues == []
    assert nested["nesting"]["last_result"]["auto_lead_override_count"] > 0
    assert any(item.get("auto_generated") for item in nested["lead_overrides"])
    assert_valid_gcode(export_project_gcode(nested))


def test_auto_nest_lead_fallback_uses_one_runtime_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    project = example_project()
    project["spacing_mm"] = 1
    project["nesting"] = {"auto_nest_max_runtime_s": 30}
    project["post"]["lead_in_mode"] = "line"
    project["post"]["lead_in_mm"] = 5
    project["post"]["pierce_crater_diameter_mm"] = 4
    project["post"]["lead_clearance_mm"] = 1
    deadlines: list[float | None] = []
    lead_calls = 0

    def fake_auto_with_spacing(nested_project, sheet, requests, spacing, *, deadline=None):
        deadlines.append(deadline)
        nested_project.setdefault("nesting", {}).setdefault("last_result", {})
        return nested_project, web_api_module.layout_from_project(nested_project)

    def fake_lead_issues(_project, _layout, _options=None):
        nonlocal lead_calls
        lead_calls += 1
        if lead_calls == 1:
            return [{"code": "lead_clearance", "message": "needs fallback", "instance_id": None}]
        return []

    monkeypatch.setattr(web_api_module, "_auto_nest_with_spacing", fake_auto_with_spacing)
    monkeypatch.setattr(web_api_module, "_lead_issue_items", fake_lead_issues)

    nested = auto_nest_project(project)

    assert len(deadlines) == 2
    assert deadlines[0] is not None
    assert deadlines[0] == deadlines[1]
    assert nested["nesting"]["last_result"]["lead_spacing_fallback"] is True


def test_auto_nest_with_spacing_passes_remaining_runtime_to_core(monkeypatch: pytest.MonkeyPatch) -> None:
    project = example_project()
    project["nesting"] = {"auto_nest_max_runtime_s": 30}
    captured_runtime: list[float] = []

    def fake_shelf_nest_result(_name, _requests, options):
        captured_runtime.append(options.max_runtime_s)
        layout = web_api_module.layout_from_project(project)
        summary = autonest_module.NestSummary(
            attempt_count=1,
            successful_attempt_count=1,
            best_attempt="fake",
            geometry_engine="fake",
            runtime_ms=0,
            parallel_worker_count=1,
            attempts_per_second=1,
            candidate_position_count=0,
            nfp_candidate_count=0,
            exact_clearance_check_count=0,
            spatial_index_query_count=0,
            spatial_index_fallback_count=0,
            cache_hit_count=0,
            cache_miss_count=0,
            part_area_mm2=1,
            used_bbox_area_mm2=1,
            used_width_mm=1,
            used_height_mm=1,
            used_strip_area_mm2=1,
            top_free_height_mm=1,
            sheet_usable_area_mm2=1,
            packing_utilization_percent=1,
            bbox_utilization_percent=1,
            sheet_utilization_percent=1,
        )
        return autonest_module.NestResult(layout=layout, summary=summary)

    monkeypatch.setattr(web_api_module, "shelf_nest_result", fake_shelf_nest_result)
    monkeypatch.setattr(web_api_module.time, "monotonic", lambda: 100.0)

    deadline = 104.0
    web_api_module._auto_nest_with_spacing(
        project,
        web_api_module._sheet_from_project(project),
        tuple(web_api_module._requests_from_project(project)),
        spacing=8,
        deadline=deadline,
    )

    assert captured_runtime
    assert captured_runtime[0] == pytest.approx(web_api_module._auto_nest_search_budget_s(4.0))
    assert 0 < captured_runtime[0] < 4.0


def test_auto_nest_search_budget_reserves_web_post_processing_time() -> None:
    assert web_api_module._auto_nest_search_budget_s(4.0) == pytest.approx(3.0)
    assert web_api_module._auto_nest_search_budget_s(30.0) == pytest.approx(28.5)
    assert web_api_module._auto_nest_search_budget_s(0.2) == pytest.approx(0.2)
    assert web_api_module._auto_nest_search_budget_s(-1.0) == 0.0


def test_auto_nest_followup_deadline_bounds_auto_lead_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    project = example_project()
    captured_deadlines: list[float | None] = []

    def fake_apply_auto_leads(nested_project, _layout, *, deadline=None):
        captured_deadlines.append(deadline)
        return nested_project, 0

    monkeypatch.setattr(web_api_module, "_apply_auto_lead_overrides", fake_apply_auto_leads)
    monkeypatch.setattr(web_api_module.time, "monotonic", lambda: 100.0)

    web_api_module._auto_nest_with_spacing(
        project,
        web_api_module._sheet_from_project(project),
        tuple(web_api_module._requests_from_project(project)),
        spacing=8,
        deadline=104.0,
    )

    assert len(captured_deadlines) == 1
    assert captured_deadlines[0] == pytest.approx(100.0 + web_api_module.AUTO_NEST_AUTO_LEAD_MAX_RUNTIME_S)


def test_auto_nest_with_spacing_skips_auto_lead_for_complex_geometry(monkeypatch: pytest.MonkeyPatch) -> None:
    project = example_project()
    sheet = web_api_module._sheet_from_project(project)
    segments = tuple(
        LineSegment(Point(float(index), 0.0), Point(float(index + 1), 0.0))
        for index in range(2001)
    )
    profile = PartProfile("complex", (PathContour("complex_outer", segments, "outer", "test"),))
    layout = NestedLayout(
        name="complex",
        sheet=sheet,
        placed_parts=(PlacedPart(profile, Placement("complex", 1, 10, 10)),),
        spacing=8,
    )
    summary = autonest_module.NestSummary(
        attempt_count=1,
        successful_attempt_count=1,
        best_attempt="fake",
        geometry_engine="fake",
        runtime_ms=0,
        parallel_worker_count=1,
        attempts_per_second=1,
        candidate_position_count=0,
        nfp_candidate_count=0,
        exact_clearance_check_count=0,
        spatial_index_query_count=0,
        spatial_index_fallback_count=0,
        cache_hit_count=0,
        cache_miss_count=0,
        part_area_mm2=1,
        used_bbox_area_mm2=1,
        used_width_mm=1,
        used_height_mm=1,
        used_strip_area_mm2=1,
        top_free_height_mm=1,
        sheet_usable_area_mm2=1,
        packing_utilization_percent=1,
        bbox_utilization_percent=1,
        sheet_utilization_percent=1,
    )

    monkeypatch.setattr(
        web_api_module,
        "shelf_nest_result",
        lambda *_args, **_kwargs: autonest_module.NestResult(layout=layout, summary=summary),
    )
    monkeypatch.setattr(
        web_api_module,
        "_apply_auto_lead_overrides",
        lambda *_args, **_kwargs: pytest.fail("complex geometry should skip auto lead overrides"),
    )

    nested, _layout = web_api_module._auto_nest_with_spacing(
        project,
        sheet,
        (PartRequest(profile, quantity=1, allowed_rotations=(0,)),),
        spacing=8,
        deadline=web_api_module.time.monotonic() + 30,
    )

    assert nested["nesting"]["last_result"]["auto_lead_override_count"] == 0
    assert nested["nesting"]["last_result"]["auto_lead_override_skipped"] == "geometry_complexity"


def test_auto_nest_skips_lead_spacing_fallback_for_complex_geometry(monkeypatch: pytest.MonkeyPatch) -> None:
    project = example_project()
    project["spacing_mm"] = 1
    project["nesting"] = {"auto_nest_max_runtime_s": 30}
    project["post"]["lead_in_mode"] = "line"
    points = [
        Point(math.cos(math.tau * index / 2001) * 50.0, math.sin(math.tau * index / 2001) * 50.0)
        for index in range(2001)
    ]
    segments = tuple(LineSegment(start, end) for start, end in zip(points, [*points[1:], points[0]]))
    profile = PartProfile("complex", (PathContour("complex_outer", segments, "outer", "test"),))
    layout = NestedLayout(
        name="complex",
        sheet=web_api_module._sheet_from_project(project),
        placed_parts=(PlacedPart(profile, Placement("complex", 1, 100, 100)),),
        spacing=1,
    )

    def fake_auto_with_spacing(nested_project, _sheet, _requests, _spacing, *, deadline=None):
        nested_project.setdefault("nesting", {})["last_result"] = {
            "attempt_count": 1,
            "successful_attempt_count": 1,
            "best_attempt": "fake",
            "geometry_engine": "fake",
            "runtime_ms": 1,
        }
        return nested_project, layout

    monkeypatch.setattr(web_api_module, "_auto_nest_with_spacing", fake_auto_with_spacing)
    monkeypatch.setattr(
        web_api_module,
        "_lead_issue_items",
        lambda *_args, **_kwargs: pytest.fail("complex geometry should skip lead spacing fallback check"),
    )

    nested = auto_nest_project(project)

    assert nested["nesting"]["last_result"]["lead_spacing_fallback"] is False
    assert nested["nesting"]["last_result"]["lead_spacing_fallback_skipped"] == "geometry_complexity"
    assert nested["nesting"]["run_history"][-1]["lead_spacing_fallback_skipped"] == "geometry_complexity"


def test_auto_nest_parallel_workers_cache_and_spatial_index_summary() -> None:
    part = rectangle_profile("tile", 40, 30)
    result = shelf_nest_result(
        "parallel_tiles",
        (PartRequest(part, quantity=12, allowed_rotations=(0,)),),
        ShelfNestOptions(
            sheet=Sheet(width=500, height=300, margin=10),
            spacing=5,
            allow_arbitrary_rotation=False,
            attempt_limit=4,
            max_runtime_s=10,
            parallel_workers=2,
        ),
    )
    summary = result.summary

    assert validate_layout(result.layout) == []
    assert summary.parallel_worker_count in {1, 2}
    if summary.parallel_fallback_reason:
        assert summary.parallel_worker_count == 1
    else:
        assert summary.parallel_worker_count == 2
    assert summary.attempts_per_second > 0
    assert summary.cache_hit_count > summary.cache_miss_count
    assert summary.spatial_index_query_count > 0


def test_auto_nest_returns_fast_seed_when_optimization_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    part = rectangle_profile("tile", 120, 80)

    monkeypatch.setattr(autonest_module, "_pack_lattice_attempts", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(
        autonest_module,
        "_pack_attempts_serial",
        lambda *_args, **_kwargs: (None, 0, True),
    )

    result = shelf_nest_result(
        "seed_fallback",
        (PartRequest(part, quantity=4, allowed_rotations=(0, 90)),),
        ShelfNestOptions(
            sheet=Sheet(width=600, height=400, margin=10),
            spacing=8,
            attempt_limit=4,
            max_runtime_s=1,
            parallel_workers=1,
        ),
    )

    assert validate_layout(result.layout) == []
    assert len(result.layout.placed_parts) == 4
    assert result.summary.best_attempt == "shelf-seed"
    assert result.summary.successful_attempt_count == 1
    assert result.summary.time_limited is True


def test_auto_nest_worker_uses_parent_absolute_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    part = rectangle_profile("tile", 40, 30)
    attempt = autonest_module._AttemptSpec(
        label="seed",
        instances=[(part, 1, (0,))],
        rotation_pool=None,
        candidate_policy="compact",
    )
    options = ShelfNestOptions(sheet=Sheet(width=200, height=100, margin=10), spacing=5)
    captured: list[float | None] = []

    def fake_pack(name, _attempt, pack_options, *, deadline=None, stats=None, cache=None):
        captured.append(deadline)
        layout = NestedLayout(
            name=name,
            sheet=pack_options.sheet,
            placed_parts=(PlacedPart(part, Placement("tile", 1, 30, 25)),),
            spacing=pack_options.spacing,
        )
        return layout, (1.0,)

    monkeypatch.setattr(autonest_module, "_pack_attempt", fake_pack)
    deadline = autonest_module.time.monotonic() + 5

    result = autonest_module._pack_attempt_worker("deadline", attempt, options, deadline)

    assert result.error is None
    assert captured == [deadline]


def test_auto_nest_parallel_worker_permission_error_falls_back_to_serial(monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenExecutor:
        def __init__(self, *args, **kwargs):
            raise PermissionError("semaphore unavailable")

    monkeypatch.setattr(autonest_module.concurrent.futures, "ProcessPoolExecutor", BrokenExecutor)
    part = rectangle_profile("tile", 40, 30)
    result = shelf_nest_result(
        "parallel_tiles",
        (PartRequest(part, quantity=12, allowed_rotations=(0,)),),
        ShelfNestOptions(
            sheet=Sheet(width=500, height=300, margin=10),
            spacing=5,
            allow_arbitrary_rotation=False,
            attempt_limit=4,
            max_runtime_s=10,
            parallel_workers=2,
        ),
    )
    summary = result.summary

    assert validate_layout(result.layout) == []
    assert summary.parallel_worker_count == 1
    assert "PermissionError" in str(summary.parallel_fallback_reason)
    assert summary.successful_attempt_count >= 1


def test_auto_nest_does_not_fail_on_import_warnings() -> None:
    project = example_project()
    project["parts"] = [rectangle_part_json("plate", 120, 80, quantity=2)]
    project["placements"] = []
    project["import"] = {
        "issues": [
                {
                    "code": "open_contour",
                    "message": "Open DXF contour skipped near X0.000 Y0.000",
                    "instance_id": None,
                    "blocking": False,
                }
            ]
        }

    nested = auto_nest_project(project)

    assert len(nested["placements"]) == 2
    assert "import_open_contour" in {issue["code"] for issue in validate_project(nested)}


def test_effective_spacing_accepts_cut_section_value_when_top_level_missing() -> None:
    project = example_project()
    project.pop("spacing_mm", None)
    project["cut"] = {"spacing_mm": 8}

    assert web_api_module._effective_spacing_from_project(project) == pytest.approx(8.0)


def test_auto_nest_can_use_arbitrary_rotation_step() -> None:
    project = example_project()
    project["sheet"] = {"width_mm": 160, "height_mm": 160, "margin_mm": 10}
    project["spacing_mm"] = 0
    project["parts"] = [
        {
            **rectangle_part_json("diagonal_plate", 160, 20),
            "allowed_rotations": [0, 90],
        }
    ]
    project["placements"] = []
    project["nesting"] = {"auto_nest_attempts": 20, "auto_nest_angle_step_deg": 15, "allow_arbitrary_rotation": True}

    nested = auto_nest_project(project)
    rotation = nested["placements"][0]["rotation_deg"]

    assert validate_project(nested) == []
    assert rotation not in (0, 90)


def test_auto_nest_keeps_duplicate_placements_as_quantity() -> None:
    project = example_project()
    project["auto_nest"] = True
    project["placements"].append(
        {
            "part_name": "disk",
            "instance": 2,
            "dx": 280,
            "dy": 280,
            "rotation_deg": 0,
            "manual": True,
        }
    )

    preview = preview_from_project(project)
    assert [part["instance_id"] for part in preview["parts"]] == ["disk_1", "disk_2"]


def test_dxf_circle_import_builds_exportable_project() -> None:
    dxf_path = PROJECT_ROOT / "examples" / "circle-hole.dxf"
    base_project = example_project()
    project = import_dxf_project(
        {
            "filename": dxf_path.name,
            "content": dxf_path.read_text(encoding="utf-8"),
            "base_project": base_project,
        }
    )

    assert project["parts"][0]["outer"]["radius_mm"] == 200
    assert project["parts"][0]["holes"][0]["radius_mm"] == 50
    assert project["import"]["circle_count"] == 2
    assert validate_project(project) == []

    gcode = export_project_gcode(project)
    assert_valid_gcode(gcode)
    assert "circle_hole_1_circle_hole_hole_2 hole pierce" in gcode


def dxf_document(entities: str, *, units_code: int | None = 4) -> str:
    header = ""
    if units_code is not None:
        header = f"""
0
SECTION
2
HEADER
9
$INSUNITS
70
{units_code}
0
ENDSEC
"""
    return f"""{header}0
SECTION
2
ENTITIES
{entities}
0
ENDSEC
0
EOF
"""


def dxf_acis_region_rectangle_document() -> str:
    os.environ.setdefault("XDG_CACHE_HOME", str(Path(os.environ.get("TMPDIR") or "/tmp") / "ezdxf-cache"))
    import ezdxf
    from ezdxf.acis import api
    from ezdxf.render import MeshBuilder

    mesh = MeshBuilder()
    mesh.add_face([(0, 0, 0), (80, 0, 0), (80, 40, 0), (0, 40, 0)])
    body = api.body_from_mesh(mesh)
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 4
    region = doc.modelspace().add_region()
    region.sat = api.export_sat([body])
    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue()


def test_dxf_lwpolyline_and_circle_hole_import_export_and_simulate() -> None:
    dxf = dxf_document(
        """0
LWPOLYLINE
90
4
70
1
10
0
20
0
10
160
20
0
10
160
20
90
10
0
20
90
0
CIRCLE
10
80
20
45
40
12
"""
    )

    project = import_dxf_project(
        {
            "filename": "rect-hole.dxf",
            "content": dxf,
            "base_project": example_project(),
        }
    )

    contours = project["parts"][0]["contours"]
    assert project["import"]["units"]["name"] == "mm"
    assert project["import"]["entity_counts"]["LWPOLYLINE"] == 1
    assert {contour["kind"] for contour in contours} == {"outer", "hole"}
    assert any(contour["type"] == "path" and contour["kind"] == "outer" for contour in contours)
    assert any(contour["type"] == "circle" and contour["kind"] == "hole" for contour in contours)
    assert validate_project(project) == []

    gcode = export_project_gcode(project)
    assert_valid_gcode(gcode)
    assert "rect_hole_1_rect_hole_hole_2 hole pierce" in gcode
    assert "rect_hole_1_rect_hole_outer_1 outer pierce" in gcode
    assert "G1 X" in gcode

    simulation = simulation_from_project(project)
    assert simulation["segments"]
    assert any(segment["type"] == "cut" for segment in simulation["segments"])
    assert any(segment["type"] == "rapid" for segment in simulation["segments"])


def test_dxf_line_only_self_intersection_is_retained_for_centerline_cutting() -> None:
    dxf = dxf_document(
        """0
LWPOLYLINE
90
4
70
1
10
0
20
0
10
40
20
40
10
0
20
40
10
40
20
0
"""
    )

    project = import_dxf_project(
        {
            "filename": "bowtie.dxf",
            "content": dxf,
            "base_project": example_project(),
        }
    )

    assert len(project["parts"]) == 1
    assert project["import"]["safe_for_export"] is True
    issue = next(issue for issue in project["import"]["issues"] if issue["code"] == "self_intersection")
    assert issue["x"] == pytest.approx(20)
    assert issue["y"] == pytest.approx(20)
    validation_codes = {issue["code"] for issue in validate_project(project)}
    assert "import_self_intersection" in validation_codes
    assert "kerf_offset_centerline" in validation_codes
    assert_valid_gcode(export_project_gcode(project))
    assert any(segment["type"] == "cut" for segment in simulation_from_project(project)["segments"])


def test_dxf_arc_self_intersection_is_retained_for_centerline_cutting() -> None:
    dxf = dxf_document(
        """0
LWPOLYLINE
90
4
70
1
10
0
20
0
42
0.25
10
40
20
40
10
0
20
40
10
40
20
0
"""
    )

    project = import_dxf_project(
        {
            "filename": "arc-bowtie.dxf",
            "content": dxf,
            "base_project": example_project(),
        }
    )

    assert len(project["parts"]) == 1
    assert project["import"]["safe_for_export"] is True
    issue = next(issue for issue in project["import"]["issues"] if issue["code"] == "self_intersection")
    assert issue["entity_type"] == "PATH"
    assert issue["x"] == pytest.approx(25, abs=0.01)
    assert issue["y"] == pytest.approx(15, abs=0.01)
    validation_codes = {issue["code"] for issue in validate_project(project)}
    assert "import_self_intersection" in validation_codes
    assert "kerf_offset_centerline" in validation_codes
    assert_valid_gcode(export_project_gcode(project))
    assert any(segment["type"] == "cut" for segment in simulation_from_project(project)["segments"])


def test_dxf_ellipse_outer_and_hole_import_export_without_unsupported_issue() -> None:
    dxf = dxf_document(
        """0
ELLIPSE
10
0
20
0
11
120
21
0
40
0.5
41
0
42
6.283185307179586
0
ELLIPSE
10
0
20
0
11
30
21
0
40
0.5
41
0
42
6.283185307179586
"""
    )

    project = import_dxf_project(
        {
            "filename": "ellipse-hole.dxf",
            "content": dxf,
            "base_project": example_project(),
        }
    )

    contours = project["parts"][0]["contours"]
    issue_codes = {issue["code"] for issue in project["import"]["issues"]}

    assert project["import"]["entity_counts"]["ELLIPSE"] == 2
    assert "unsupported_entity" not in issue_codes
    assert {contour["kind"] for contour in contours} == {"outer", "hole"}
    assert all(contour["type"] == "path" for contour in contours)
    assert validate_project(project) == []
    assert_valid_gcode(export_project_gcode(project))


def test_dxf_solid_trace_and_3dface_import_as_closed_contours() -> None:
    dxf = dxf_document(
        """0
SOLID
10
0
20
0
11
70
21
0
12
0
22
40
13
70
23
40
0
TRACE
10
100
20
0
11
150
21
0
12
100
22
35
13
150
23
35
0
3DFACE
10
180
20
0
30
0
11
230
21
0
31
0
12
230
22
35
32
0
13
180
23
35
33
0
"""
    )

    base_project = example_project()
    base_project["spacing_mm"] = 80
    project = import_dxf_project(
        {
            "filename": "filled-faces.dxf",
            "content": dxf,
            "base_project": base_project,
        }
    )

    assert project["import"]["entity_counts"]["SOLID"] == 1
    assert project["import"]["entity_counts"]["TRACE"] == 1
    assert project["import"]["entity_counts"]["3DFACE"] == 1
    assert project["import"]["part_count"] == 3
    assert project["import"]["contour_count"] == 3
    assert all(part["contours"][0]["type"] == "path" for part in project["parts"])
    assert validate_project(project) == []
    assert_valid_gcode(export_project_gcode(project))


def test_dxf_hatch_polyline_and_edge_boundaries_import_as_cut_contours() -> None:
    dxf = dxf_document(
        """0
HATCH
91
2
92
3
72
0
73
1
93
4
10
0
20
0
10
100
20
0
10
100
20
60
10
0
20
60
92
0
93
1
72
2
10
50
20
30
40
12
50
0
51
360
73
1
"""
    )

    project = import_dxf_project(
        {
            "filename": "hatch-hole.dxf",
            "content": dxf,
            "base_project": example_project(),
        }
    )

    contours = project["parts"][0]["contours"]
    issue_codes = {issue["code"] for issue in project["import"]["issues"]}
    assert project["import"]["entity_counts"]["HATCH"] == 1
    assert "unsupported_entity" not in issue_codes
    assert project["import"]["contour_count"] == 2
    assert {contour["kind"] for contour in contours} == {"outer", "hole"}
    assert all(contour["type"] == "path" for contour in contours)
    assert validate_project(project) == []
    assert_valid_gcode(export_project_gcode(project))


def test_dxf_mpolygon_imports_with_hatch_boundary_parser() -> None:
    dxf = dxf_document(
        """0
MPOLYGON
91
1
92
3
72
0
73
1
93
4
10
0
20
0
10
90
20
0
10
90
20
45
10
0
20
45
"""
    )

    project = import_dxf_project(
        {
            "filename": "mpolygon-plate.dxf",
            "content": dxf,
            "base_project": example_project(),
        }
    )

    assert project["import"]["entity_counts"]["MPOLYGON"] == 1
    assert project["import"]["contour_count"] == 1
    assert project["parts"][0]["contours"][0]["type"] == "path"
    assert validate_project(project) == []
    assert_valid_gcode(export_project_gcode(project))


def test_dxf_non_cut_annotation_entities_do_not_block_export() -> None:
    dxf = dxf_document(
        """0
LWPOLYLINE
90
4
70
1
10
0
20
0
10
80
20
0
10
80
20
40
10
0
20
40
0
POINT
10
10
20
10
0
TEXT
10
5
20
5
40
3
1
SHOP NOTE
0
MTEXT
10
15
20
15
40
3
1
IGNORE
0
XLINE
10
0
20
0
11
1
21
0
0
RAY
10
0
20
0
11
0
21
1
0
DIMENSION
10
0
20
0
11
80
21
0
0
UNDERLAY
0
SECTION
0
SUN
0
MLEADERSTYLE
"""
    )

    project = import_dxf_project(
        {
            "filename": "annotated-plate.dxf",
            "content": dxf,
            "base_project": example_project(),
        }
    )

    issue_codes = {issue["code"] for issue in project["import"]["issues"]}
    assert project["import"]["entity_counts"]["POINT"] == 1
    assert project["import"]["entity_counts"]["TEXT"] == 1
    assert project["import"]["entity_counts"]["MTEXT"] == 1
    assert project["import"]["entity_counts"]["XLINE"] == 1
    assert project["import"]["entity_counts"]["RAY"] == 1
    assert project["import"]["entity_counts"]["DIMENSION"] == 1
    assert project["import"]["entity_counts"]["UNDERLAY"] == 1
    assert project["import"]["entity_counts"]["SECTION"] == 1
    assert project["import"]["entity_counts"]["SUN"] == 1
    assert project["import"]["entity_counts"]["MLEADERSTYLE"] == 1
    assert "unsupported_entity" not in issue_codes
    assert project["import"]["safe_for_export"] is True
    assert project["import"]["contour_count"] == 1
    assert validate_project(project) == []
    assert_valid_gcode(export_project_gcode(project))


def test_dxf_layer_heuristics_skip_construction_ignore_and_warn_for_mark_layers() -> None:
    dxf = dxf_document(
        """0
LWPOLYLINE
8
CUT
90
4
70
1
10
0
20
0
10
80
20
0
10
80
20
40
10
0
20
40
0
LWPOLYLINE
8
CONSTRUCTION_CENTER
90
4
70
1
10
120
20
0
10
180
20
0
10
180
20
30
10
120
20
30
0
CIRCLE
8
IGNORE_GUIDE
10
40
20
20
40
8
0
CIRCLE
8
ETCH_LABEL
10
20
20
20
40
5
"""
    )

    project = import_dxf_project(
        {
            "filename": "layer-heuristics.dxf",
            "content": dxf,
            "base_project": example_project(),
        }
    )

    contours = project["parts"][0]["contours"]
    issue = next(issue for issue in project["import"]["issues"] if issue["code"] == "mark_layer_skipped")
    assert project["import"]["entity_counts"]["LWPOLYLINE"] == 2
    assert project["import"]["entity_counts"]["CIRCLE"] == 2
    assert project["import"]["contour_count"] == 1
    assert {contour["kind"] for contour in contours} == {"outer"}
    assert issue["layer"] == "ETCH_LABEL"
    assert issue["process"] == "mark"
    assert issue["blocking"] is False
    assert project["import"]["safe_for_export"] is True
    validation_issues = validate_project(project)
    assert {issue["code"] for issue in validation_issues} == {"import_mark_layer_skipped"}
    assert {issue["blocking"] for issue in validation_issues} == {False}
    assert_valid_gcode(export_project_gcode(project))


def test_dxf_layer_heuristics_do_not_treat_sketch_as_etch() -> None:
    dxf = dxf_document(
        """0
LWPOLYLINE
8
plate_sketch
90
4
70
1
10
0
20
0
10
80
20
0
10
80
20
40
10
0
20
40
0
"""
    )

    project = import_dxf_project(
        {
            "filename": "plate-sketch.dxf",
            "content": dxf,
            "base_project": example_project(),
        }
    )

    issue_codes = {issue["code"] for issue in project["import"]["issues"]}
    assert "mark_layer_skipped" not in issue_codes
    assert project["import"]["contour_count"] == 1
    assert project["parts"][0]["contours"][0]["kind"] == "outer"


def test_dxf_import_options_layer_mapping_controls_cut_construction_and_mark_layers() -> None:
    dxf = dxf_document(
        """0
LWPOLYLINE
8
CNC_PROFILE
90
4
70
1
10
0
20
0
10
90
20
0
10
90
20
45
10
0
20
45
0
CIRCLE
8
AUX_GEOM
10
45
20
22.5
40
8
0
LINE
8
SCRATCH_PASS
10
5
20
5
11
85
21
5
"""
    )

    project = import_dxf_circles(
        dxf,
        name="mapped-layers.dxf",
        import_options={
            "layer_mapping": {
                "CNC_PROFILE": "cut",
                "AUX_GEOM": "construction",
                "SCRATCH_PASS": "mark",
            }
        },
    )

    issue = next(issue for issue in project["import"]["issues"] if issue["code"] == "mark_layer_skipped")
    assert project["import"]["layer_mapping"] == {
        "CNC_PROFILE": "cut",
        "AUX_GEOM": "construction",
        "SCRATCH_PASS": "mark",
    }
    assert project["import"]["contour_count"] == 1
    assert project["import"]["warning_count"] == 1
    assert project["import"]["blocking_issue_count"] == 0
    assert issue["entity_type"] == "LINE"
    assert issue["layer"] == "SCRATCH_PASS"
    validation_issues = validate_project(project)
    assert {issue["code"] for issue in validation_issues} == {"import_mark_layer_skipped"}
    assert {issue["blocking"] for issue in validation_issues} == {False}
    assert_valid_gcode(export_project_gcode(project))


def test_dxf_project_api_passes_layer_mapping_to_importer() -> None:
    dxf = dxf_document(
        """0
LWPOLYLINE
8
PROFILE
90
4
70
1
10
0
20
0
10
80
20
0
10
80
20
40
10
0
20
40
0
LWPOLYLINE
8
DECOR
90
4
70
1
10
100
20
0
10
160
20
0
10
160
20
30
10
100
20
30
"""
    )

    project = import_dxf_project(
        {
            "filename": "api-mapped-layers.dxf",
            "content": dxf,
            "base_project": example_project(),
            "import_options": {
                "layer_mapping": {
                    "PROFILE": "cut",
                    "DECOR": "ignore",
                }
            },
        }
    )

    assert project["import"]["layer_mapping"] == {
        "PROFILE": "cut",
        "DECOR": "ignore",
    }
    assert project["import"]["contour_count"] == 1
    assert len(project["parts"]) == 1
    assert validate_project(project) == []
    assert_valid_gcode(export_project_gcode(project))


def test_dxf_unsafe_non_contour_entities_are_explicit_blocking_issues() -> None:
    dxf = dxf_document(
        """0
LWPOLYLINE
90
4
70
1
10
0
20
0
10
80
20
0
10
80
20
40
10
0
20
40
0
REGION
0
3DSOLID
0
MLINE
"""
    )

    project = import_dxf_project(
        {
            "filename": "unsafe-region.dxf",
            "content": dxf,
            "base_project": example_project(),
        }
    )

    assert project["import"]["entity_counts"]["REGION"] == 1
    assert project["import"]["entity_counts"]["3DSOLID"] == 1
    assert project["import"]["entity_counts"]["MLINE"] == 1
    assert project["import"]["unsafe_entity_policy"] == "block"
    assert project["import"]["contour_count"] == 1
    assert project["import"]["safe_for_export"] is True
    assert project["import"]["blocking_issue_count"] == 0
    assert {issue["entity_type"] for issue in project["import"]["issues"]} == {"REGION", "3DSOLID", "MLINE"}
    assert {issue["code"] for issue in project["import"]["issues"]} == {"unsupported_unsafe_entity"}
    validation_issues = validate_project(project)
    import_validation_issues = [issue for issue in validation_issues if issue["code"] == "import_unsupported_unsafe_entity"]
    assert import_validation_issues
    assert all(issue.get("blocking") is False for issue in import_validation_issues)
    assert all(issue.get("review_required") is False for issue in import_validation_issues)
    gcode = export_project_gcode(project)
    assert "WARNING: import_unsupported_unsafe_entity" in gcode
    assert_valid_gcode(gcode)


def test_dxf_region_acis_rectangle_imports_as_cut_contour() -> None:
    project = import_dxf_project(
        {
            "filename": "region-rectangle.dxf",
            "content": dxf_acis_region_rectangle_document(),
            "base_project": example_project(),
        }
    )

    assert project["import"]["entity_counts"]["REGION"] == 1
    assert project["import"]["contour_count"] == 1
    assert project["import"]["warning_count"] == 0
    assert "unsupported_unsafe_entity" not in project["import"]["issue_counts"]
    assert len(project["parts"]) == 1
    assert validate_project(project) == []
    assert_valid_gcode(export_project_gcode(project))


def test_dxf_unsafe_non_contour_entities_can_be_explicit_warnings() -> None:
    dxf = dxf_document(
        """0
LWPOLYLINE
90
4
70
1
10
0
20
0
10
80
20
0
10
80
20
40
10
0
20
40
0
REGION
0
3DSOLID
"""
    )

    project = import_dxf_project(
        {
            "filename": "unsafe-region-warn.dxf",
            "content": dxf,
            "base_project": example_project(),
            "import_options": {"unsafe_entity_policy": "warn"},
        }
    )

    assert project["import"]["unsafe_entity_policy"] == "warn"
    assert project["import"]["safe_for_export"] is True
    assert project["import"]["blocking_issue_count"] == 0
    assert project["import"]["warning_count"] == 2
    assert {issue["entity_type"] for issue in project["import"]["issues"]} == {"REGION", "3DSOLID"}
    assert {issue["blocking"] for issue in project["import"]["issues"]} == {False}
    validation_issues = validate_project(project)
    assert "import_unsupported_unsafe_entity" in {issue["code"] for issue in validation_issues}
    assert all(issue.get("blocking") is False for issue in validation_issues if issue["code"] == "import_unsupported_unsafe_entity")
    assert_valid_gcode(export_project_gcode(project))


def test_dxf_import_splits_multiple_top_level_parts() -> None:
    dxf = dxf_document(
        """0
LWPOLYLINE
90
4
70
1
10
0
20
0
10
120
20
0
10
120
20
80
10
0
20
80
0
LWPOLYLINE
90
4
70
1
10
40
20
20
10
80
20
20
10
80
20
60
10
40
20
60
0
LWPOLYLINE
90
4
70
1
10
200
20
0
10
260
20
0
10
260
20
50
10
200
20
50
"""
    )

    base_project = example_project()
    base_project["spacing_mm"] = 30
    project = import_dxf_project(
        {
            "filename": "multi-part.dxf",
            "content": dxf,
            "base_project": base_project,
        }
    )

    assert [part["name"] for part in project["parts"]] == ["multi_part_1", "multi_part_2"]
    assert [placement["part_name"] for placement in project["placements"]] == ["multi_part_1", "multi_part_2"]
    assert project["import"]["part_count"] == 2
    assert project["import"]["contour_count"] == 3
    assert {contour["kind"] for contour in project["parts"][0]["contours"]} == {"outer", "hole"}
    assert {contour["kind"] for contour in project["parts"][1]["contours"]} == {"outer"}
    assert validate_project(project) == []

    gcode = export_project_gcode(project)
    assert_valid_gcode(gcode)
    assert "multi_part_1_1_multi_part_1_hole_2 hole pierce" in gcode
    assert "multi_part_2_1_multi_part_2_outer_1 outer pierce" in gcode


def test_dxf_old_polyline_vertex_import_export() -> None:
    dxf = dxf_document(
        """0
POLYLINE
70
1
0
VERTEX
10
0
20
0
0
VERTEX
10
100
20
0
0
VERTEX
10
100
20
80
0
VERTEX
10
0
20
80
0
SEQEND
"""
    )

    project = import_dxf_project(
        {
            "filename": "old-polyline.dxf",
            "content": dxf,
            "base_project": example_project(),
        }
    )

    assert project["import"]["entity_counts"]["POLYLINE"] == 1
    assert project["parts"][0]["contours"][0]["type"] == "path"
    assert validate_project(project) == []
    assert_valid_gcode(export_project_gcode(project))


def test_dxf_insert_block_import_export() -> None:
    dxf = """0
SECTION
2
HEADER
9
$INSUNITS
70
4
0
ENDSEC
0
SECTION
2
BLOCKS
0
BLOCK
2
PLATE
70
0
10
0
20
0
0
LWPOLYLINE
90
4
70
1
10
0
20
0
10
60
20
0
10
60
20
30
10
0
20
30
0
ENDBLK
0
ENDSEC
0
SECTION
2
ENTITIES
0
INSERT
2
PLATE
10
100
20
50
41
1
42
1
50
90
0
ENDSEC
0
EOF
"""

    project = import_dxf_project(
        {
            "filename": "insert-block.dxf",
            "content": dxf,
            "base_project": example_project(),
        }
    )

    assert project["import"]["entity_counts"]["INSERT"] == 1
    assert project["import"]["entity_counts"]["LWPOLYLINE"] == 1
    assert project["import"]["contour_count"] == 1
    assert project["parts"][0]["contours"][0]["type"] == "path"
    assert validate_project(project) == []
    assert_valid_gcode(export_project_gcode(project))


def test_dxf_minsert_block_array_imports_each_inserted_contour() -> None:
    dxf = """0
SECTION
2
HEADER
9
$INSUNITS
70
4
0
ENDSEC
0
SECTION
2
BLOCKS
0
BLOCK
2
TAB
70
0
10
0
20
0
0
LWPOLYLINE
90
4
70
1
10
0
20
0
10
30
20
0
10
30
20
20
10
0
20
20
0
ENDBLK
0
ENDSEC
0
SECTION
2
ENTITIES
0
MINSERT
2
TAB
10
0
20
0
41
1
42
1
50
0
70
2
71
2
44
60
45
50
0
ENDSEC
0
EOF
"""

    base_project = example_project()
    base_project["spacing_mm"] = 50
    project = import_dxf_project(
        {
            "filename": "minsert-array.dxf",
            "content": dxf,
            "base_project": base_project,
        }
    )

    assert project["import"]["entity_counts"]["MINSERT"] == 1
    assert project["import"]["entity_counts"]["LWPOLYLINE"] == 4
    assert project["import"]["part_count"] == 4
    assert project["import"]["contour_count"] == 4
    assert validate_project(project) == []
    assert_valid_gcode(export_project_gcode(project))


def test_dxf_line_arc_segments_chain_into_closed_slot() -> None:
    dxf = dxf_document(
        """0
LINE
10
0
20
10
11
80
21
10
0
ARC
10
80
20
0
40
10
50
270
51
90
0
LINE
10
80
20
-10
11
0
21
-10
0
ARC
10
0
20
0
40
10
50
270
51
90
"""
    )

    project = import_dxf_project(
        {
            "filename": "slot.dxf",
            "content": dxf,
            "base_project": example_project(),
        }
    )

    contours = project["parts"][0]["contours"]
    assert len(contours) == 1
    assert contours[0]["type"] == "path"
    assert contours[0]["kind"] == "outer"
    assert project["import"]["entity_counts"]["LINE"] == 2
    assert project["import"]["entity_counts"]["ARC"] == 2

    gcode = export_project_gcode(project)
    assert_valid_gcode(gcode)
    assert "slot_1_slot_outer_1 outer pierce" in gcode


def test_dxf_units_scale_inches_to_mm() -> None:
    dxf = dxf_document(
        """0
LWPOLYLINE
90
4
70
1
10
0
20
0
10
1
20
0
10
1
20
1
10
0
20
1
""",
        units_code=1,
    )

    project = import_dxf_project(
        {
            "filename": "inch-square.dxf",
            "content": dxf,
            "base_project": example_project(),
        }
    )

    contour = project["parts"][0]["contours"][0]
    xs = [segment["start"]["x"] for segment in contour["segments"]]
    assert project["import"]["units"]["name"] == "inch"
    assert max(xs) - min(xs) == pytest.approx(25.4)


def test_dxf_open_contours_export_as_warning_centerline() -> None:
    base = example_project()
    base["post"]["open_path_mode"] = "block"
    dxf = dxf_document(
        """0
LINE
10
0
20
0
11
100
21
0
"""
    )

    project = import_dxf_project(
        {
            "filename": "open.dxf",
            "content": dxf,
            "base_project": base,
        }
    )

    assert project["import"]["safe_for_export"] is True
    assert project["import"]["blocking_issue_count"] == 0
    assert project["import"]["contour_count"] == 1
    assert "review_only" not in project["parts"][0]
    assert project["parts"][0]["source_center"] == {"x": 50.0, "y": 0.0}
    assert project["parts"][0]["source_bbox"] == [0.0, 0.0, 100.0, 0.0]
    assert project["parts"][0]["contours"][0]["open"] is True
    import_issue = next(issue for issue in project["import"]["issues"] if issue["code"] == "open_contour")
    assert import_issue["x"] == pytest.approx(100)
    assert import_issue["y"] == pytest.approx(0)
    assert import_issue["target_x"] == pytest.approx(0)
    assert import_issue["target_y"] == pytest.approx(0)
    assert import_issue["chain_length_mm"] == pytest.approx(100)
    assert import_issue["sheet_x"] == pytest.approx(110)
    assert import_issue["sheet_y"] == pytest.approx(10)
    assert import_issue["target_sheet_x"] == pytest.approx(10)
    assert import_issue["target_sheet_y"] == pytest.approx(10)
    preview = preview_from_project(project)
    assert [part["part_name"] for part in preview["parts"]] == ["open"]
    validation_issue = next(issue for issue in validate_project(project) if issue["code"] == "import_open_contour")
    assert validation_issue["chain_length_mm"] == pytest.approx(100)
    assert validation_issue["target_sheet_x"] == pytest.approx(10)
    assert validation_issue["blocking"] is False
    assert validation_issue["review_required"] is False
    gcode = export_project_gcode(project)
    assert "WARNING: import_open_contour" in gcode
    assert "WARNING: open_path_centerline" in gcode
    assert "G1 X110 Y10" in gcode
    assert_valid_gcode(gcode)


def test_dxf_open_contours_can_export_as_centerline_open_cuts() -> None:
    base = example_project()
    base["post"]["open_path_mode"] = "centerline"
    dxf = dxf_document(
        """0
LINE
10
0
20
0
11
100
21
0
"""
    )

    project = import_dxf_project(
        {
            "filename": "open-centerline.dxf",
            "content": dxf,
            "base_project": base,
        }
    )

    assert project["import"]["safe_for_export"] is True
    assert project["import"]["blocking_issue_count"] == 0
    assert "review_only" not in project["parts"][0]
    issues = validate_project(project)
    open_issue = next(issue for issue in issues if issue["code"] == "import_open_contour")
    assert open_issue["blocking"] is False
    assert "centerline open cut" in open_issue["message"]
    gcode = export_project_gcode(project)
    assert "open centerline pierce" in gcode
    assert "G0 X10 Y10" in gcode
    assert "G1 X110 Y10" in gcode
    simulation = simulation_from_gcode(project, gcode)
    assert any(segment["type"] == "cut" for segment in simulation["segments"])


def test_dxf_loose_cycle_is_preserved_when_dangling_cut_branch_exists() -> None:
    dxf = dxf_document(
        """0
LINE
10
0
20
0
11
100
21
0
0
LINE
10
100
20
0
11
100
21
100
0
LINE
10
100
20
100
11
0
21
100
0
LINE
10
0
20
100
11
0
21
0
0
LINE
10
0
20
0
11
-50
21
0
"""
    )

    project = import_dxf_project(
        {
            "filename": "cycle-with-dangling-cut.dxf",
            "content": dxf,
            "base_project": example_project(),
        }
    )

    assert project["import"]["contour_count"] == 2
    assert project["import"]["safe_for_export"] is True
    assert project["import"]["blocking_issue_count"] == 0
    assert project["import"]["issue_counts"]["open_contour"] == 1
    assert all("review_only" not in part for part in project["parts"])
    gcode = export_project_gcode(project)
    assert "WARNING: import_open_contour" in gcode
    assert "open centerline pierce" in gcode


def test_dxf_loose_cycle_exports_when_dangling_branch_is_construction_layer() -> None:
    dxf = dxf_document(
        """0
LINE
10
0
20
0
11
100
21
0
0
LINE
10
100
20
0
11
100
21
100
0
LINE
10
100
20
100
11
0
21
100
0
LINE
10
0
20
100
11
0
21
0
0
LINE
8
CONSTRUCTION
10
0
20
0
11
-50
21
0
"""
    )

    project = import_dxf_project(
        {
            "filename": "cycle-with-construction-branch.dxf",
            "content": dxf,
            "base_project": example_project(),
        }
    )

    assert project["import"]["contour_count"] == 1
    assert project["import"]["safe_for_export"] is True
    assert validate_project(project) == []
    assert_valid_gcode(export_project_gcode(project))


def test_dxf_tiny_open_segment_is_preserved_and_exported() -> None:
    dxf = dxf_document(
        """0
LINE
10
10
20
20
11
10.01
21
20
"""
    )

    project = import_dxf_project(
        {
            "filename": "tiny-only.dxf",
            "content": dxf,
            "base_project": example_project(),
        }
    )

    assert project["import"]["safe_for_export"] is True
    assert project["import"]["blocking_issue_count"] == 0
    assert project["import"]["review_marker_count"] == 0
    assert project["import"]["review_only_part_count"] == 0
    assert not any(code.endswith("_repaired") for code in project["import"]["issue_counts"])
    assert len(project["parts"]) == 1
    assert len(project["placements"]) == 1
    assert len(project["parts"][0]["contours"][0]["segments"]) == 1
    assert {issue["code"] for issue in validate_project(project)} == {
        "import_gap_closure_suggestion",
        "import_open_contour",
    }
    gcode = export_project_gcode(project)
    assert "G1 X10.01 Y10" in gcode
    assert any(segment["type"] == "cut" for segment in simulation_from_project(project)["segments"])
    assert_valid_gcode(gcode)


def test_dxf_tiny_segments_inside_closed_lwpolyline_are_preserved() -> None:
    vertex_count = 160
    radius = 1.0
    vertex_lines = "\n".join(
        f"10\n{math.cos(math.tau * index / vertex_count) * radius:.6f}\n20\n{math.sin(math.tau * index / vertex_count) * radius:.6f}"
        for index in range(vertex_count)
    )
    dxf = dxf_document(
        f"""0
LWPOLYLINE
90
{vertex_count}
70
1
{vertex_lines}
"""
    )

    project = import_dxf_project(
        {
            "filename": "dense-closed-polyline.dxf",
            "content": dxf,
            "base_project": example_project(),
        }
    )

    assert project["import"]["safe_for_export"] is True
    assert project["import"]["blocking_issue_count"] == 0
    assert project["import"]["contour_count"] == 1
    assert "tiny_segment_repaired" not in project["import"]["issue_counts"]
    assert_valid_gcode(export_project_gcode(project))


def test_dxf_nonclosed_path_contours_are_review_required_warnings(monkeypatch: pytest.MonkeyPatch) -> None:
    contour = PathContour(
        "leaky_path",
        (
            LineSegment(Point(0, 0), Point(50, 0)),
            LineSegment(Point(50, 0), Point(50, 50)),
        ),
        "outer",
        "dxf",
    )

    monkeypatch.setattr(
        dxf_importer_module,
        "parse_dxf",
        lambda *_args, **_kwargs: dxf_importer_module.ParsedDxf(
            contours=(contour,),
            entity_counts={"LINE": 2},
            units=dxf_importer_module.DxfUnits(4, "mm", 1.0, True),
            issues=(),
        ),
    )

    project = import_dxf_circles("0\nEOF\n", name="leaky")

    assert project["import"]["safe_for_export"] is True
    assert project["import"]["blocking_issue_count"] == 0
    assert project["import"]["issue_counts"]["open_contour"] == 1
    assert "review_only" not in project["parts"][0]
    assert "import_open_contour" in {issue["code"] for issue in validate_project(project)}
    gcode = export_project_gcode(project)
    assert "WARNING: import_open_contour" in gcode
    assert_valid_gcode(gcode)


def test_dxf_initial_multi_part_placement_uses_clearance_above_requested_spacing() -> None:
    contour = rectangle_profile("part", 100, 50).contours[0]
    groups = (
        dxf_importer_module.DxfPartGroup("left", (contour,), (-50, -25, 50, 25)),
        dxf_importer_module.DxfPartGroup("right", (contour,), (-40, -25, 40, 25)),
        dxf_importer_module.DxfPartGroup("next_row", (contour,), (-60, -30, 60, 30)),
    )

    placements = dxf_importer_module._initial_placements_for_groups(
        groups,
        {"width_mm": 230, "height_mm": 500, "margin_mm": 10},
        spacing_mm=8,
    )

    first_right = placements[0]["dx"] + 50
    second_left = placements[1]["dx"] - 40
    first_top = placements[0]["dy"] + 25
    third_bottom = placements[2]["dy"] - 30

    assert second_left - first_right == pytest.approx(8 + dxf_importer_module.INITIAL_PLACEMENT_EXTRA_CLEARANCE_MM)
    assert third_bottom - first_top == pytest.approx(8 + dxf_importer_module.INITIAL_PLACEMENT_EXTRA_CLEARANCE_MM)


def test_dxf_partial_import_loads_closed_contours_and_warns_on_export() -> None:
    dxf = dxf_document(
        """0
LINE
10
0
20
0
11
30
21
0
0
LINE
10
30
20
0
11
30
21
30
0
LINE
10
30
20
30
11
0
21
30
0
LINE
10
0
20
30
11
0
21
0
0
LINE
10
60
20
0
11
90
21
0
"""
    )

    project = import_dxf_project(
        {
            "filename": "partial-open.dxf",
            "content": dxf,
            "base_project": example_project(),
        }
    )

    assert project["import"]["partial"] is True
    assert project["import"]["safe_for_export"] is True
    assert project["import"]["blocking_issue_count"] == 0
    assert project["import"]["contour_count"] == 2
    assert project["parts"][0]["contours"][0]["type"] == "path"
    assert all("review_only" not in part for part in project["parts"])
    issues = validate_project(project)
    assert "import_open_contour" in {issue["code"] for issue in issues}
    assert all(issue.get("blocking") is False for issue in issues)
    preview = preview_from_project(project)
    assert preview["parts"][0]["instance_id"].startswith("partial_open")

    gcode = export_project_gcode(project)
    simulation = simulation_from_project(project)
    assert "WARNING: import_open_contour" in gcode
    assert any(segment["type"] == "cut" for segment in simulation["segments"])


def test_dxf_gap_repair_reports_endpoints_and_sheet_segment_coordinates() -> None:
    dxf = dxf_document(
        """0
LWPOLYLINE
90
4
70
1
10
0
20
0
10
100
20
0
10
100
20
100
10
0
20
100
0
LINE
10
10
20
10
11
40
21
10
0
LINE
10
40
20
10
11
40
21
40
0
LINE
10
40
20
40
11
10
21
10.8
"""
    )

    project = import_dxf_project(
        {
            "filename": "gap-marker.dxf",
            "content": dxf,
            "base_project": example_project(),
            "import_options": {"auto_close_gaps": True},
        }
    )

    gap_issue = next(issue for issue in project["import"]["issues"] if issue["code"] == "gap_closed_repaired")
    assert project["import"]["safe_for_export"] is True
    assert gap_issue["blocking"] is False
    assert gap_issue["gap_mm"] == pytest.approx(0.8)
    assert gap_issue["x"] == pytest.approx(10)
    assert gap_issue["y"] == pytest.approx(10.8)
    assert gap_issue["target_x"] == pytest.approx(10)
    assert gap_issue["target_y"] == pytest.approx(10)
    assert gap_issue["sheet_x"] == pytest.approx(20)
    assert gap_issue["sheet_y"] == pytest.approx(20.8)
    assert gap_issue["target_sheet_x"] == pytest.approx(20)
    assert gap_issue["target_sheet_y"] == pytest.approx(20)

    validation_issue = next(issue for issue in validate_project(project) if issue["code"] == "import_gap_closed_repaired")
    assert validation_issue["gap_mm"] == pytest.approx(0.8)
    assert validation_issue["sheet_x"] == pytest.approx(20)
    assert validation_issue["blocking"] is False
    assert validation_issue["review_required"] is False
    gcode = export_project_gcode(project)
    assert "WARNING: import_gap_closed_repaired" in gcode


def test_dxf_auto_close_gaps_is_opt_in_and_preserves_repair_diagnostics() -> None:
    dxf = dxf_document(
        """0
LWPOLYLINE
90
4
70
1
10
0
20
0
10
100
20
0
10
100
20
100
10
0
20
100
0
LINE
10
20
20
20
11
80
21
20
0
LINE
10
80
20
20
11
80
21
80
0
LINE
10
80
20
80
11
20
21
80
0
LINE
10
20
20
80
11
20
21
20.6
"""
    )

    repaired = import_dxf_project(
        {
            "filename": "small-gap.dxf",
            "content": dxf,
            "base_project": example_project(),
            "import_options": {"auto_close_gaps": True},
        }
    )

    repair_issue = next(issue for issue in repaired["import"]["issues"] if issue["code"] == "gap_closed_repaired")
    assert repaired["import"]["auto_close_gaps"] is True
    assert repaired["import"]["safe_for_export"] is True
    assert repaired["import"]["blocking_issue_count"] == 0
    assert repair_issue["blocking"] is False
    assert repair_issue["gap_mm"] == pytest.approx(0.6)
    assert repair_issue["x"] == pytest.approx(20)
    assert repair_issue["y"] == pytest.approx(20.6)
    assert repair_issue["target_x"] == pytest.approx(20)
    assert repair_issue["target_y"] == pytest.approx(20)
    assert repair_issue["sheet_x"] == pytest.approx(30)
    assert repair_issue["sheet_y"] == pytest.approx(30.6)
    assert repair_issue["target_sheet_x"] == pytest.approx(30)
    assert repair_issue["target_sheet_y"] == pytest.approx(30)
    assert "import_gap_closed_repaired" in {issue["code"] for issue in validate_project(repaired)}
    assert_valid_gcode(export_project_gcode(repaired))


def test_dxf_import_does_not_retry_with_auto_close_enabled() -> None:
    path = Path("/Users/user/Documents/dxf/models/_extracted/Мангал_2.0/Мангал 2.0.dxf")
    if not path.exists():
        pytest.skip(f"real DXF fixture not found: {path}")

    base = example_project()
    base["import_options"] = {"auto_close_gaps": False}
    project = import_dxf_project(
        {
            "filename": path.name,
            "content": path.read_text(encoding="cp1251", errors="ignore"),
            "base_project": base,
        }
    )

    assert project["import"]["auto_close_gaps"] is False
    assert project["import"]["repair_geometry"] is False
    assert "auto_close_fallback_used" not in project["import"]
    assert project["import"]["part_count"] == len(project["parts"])
    assert project["import"]["part_count"] > 0
    assert project["import"]["review_only_part_count"] == 0
    assert len(project["placements"]) == len(project["parts"])
    assert not any(code.endswith("_repaired") for code in project["import"]["issue_counts"])


def test_dxf_watch_portable_is_preserved_and_cut_without_default_repair() -> None:
    path = Path("/Users/user/Documents/dxf/models/_extracted/часы_portable/часы_portable.dxf")
    if not path.exists():
        pytest.skip(f"real DXF fixture not found: {path}")

    project = import_dxf_project(
        {
            "filename": path.name,
            "content": path.read_text(encoding="cp1251", errors="ignore"),
            "import_options": {"auto_close_gaps": False, "repair_geometry": False},
        }
    )

    assert len(project["parts"]) == 1
    assert len(project["placements"]) == 1
    assert "review_only" not in project["parts"][0]
    assert len(project["parts"][0]["contours"]) >= 78
    assert project["import"]["issue_counts"]["open_contour"] >= 3
    assert project["import"]["issue_counts"]["self_intersection"] == 4
    assert project["import"]["review_only_part_count"] == 0
    assert project["import"]["auto_close_gaps"] is False
    assert project["import"]["repair_geometry"] is False
    assert not any(code.endswith("_repaired") for code in project["import"]["issue_counts"])
    preview = preview_from_project(project)
    assert len(preview["parts"]) == 1
    assert preview["parts"][0]["instance_id"] == "часы_portable_1"
    assert len(preview["parts"][0]["contours"]) == len(project["parts"][0]["contours"])
    simulation = simulation_from_project(project)
    assert len(simulation["segments"]) > 1000
    assert any(segment["type"] == "cut" for segment in simulation["segments"])
    gcode = export_project_gcode(project)
    assert "WARNING: import_open_contour" in gcode
    assert "WARNING: import_self_intersection" in gcode
    assert_valid_gcode(gcode)


def test_dxf_duplicate_and_tiny_loose_segments_are_repaired_without_blocking_export() -> None:
    dxf = dxf_document(
        """0
LINE
10
0
20
0
11
30
21
0
0
LINE
10
0
20
0
11
30
21
0
0
LINE
10
30
20
0
11
30
21
30
0
LINE
10
30
20
30
11
0
21
30
0
LINE
10
0
20
30
11
0
21
0
0
LINE
10
200
20
0
11
200.01
21
0
"""
    )

    project = import_dxf_project(
        {
            "filename": "repaired-segments.dxf",
            "content": dxf,
            "base_project": example_project(),
            "import_options": {"repair_geometry": True},
        }
    )

    import_issues = project["import"]["issues"]
    assert project["import"]["safe_for_export"] is True
    assert project["import"]["blocking_issue_count"] == 0
    assert {issue["code"] for issue in import_issues} == {
        "duplicate_segment_repaired",
        "tiny_segment_repaired",
    }
    assert {issue["blocking"] for issue in import_issues} == {False}
    assert any(issue["code"] == "import_duplicate_segment_repaired" for issue in validate_project(project))
    assert_valid_gcode(export_project_gcode(project))


def test_dxf_import_caps_repeated_issue_display_but_keeps_totals() -> None:
    duplicate_lines = "\n".join(
        """0
LINE
10
200
20
0
11
220
21
0"""
        for _index in range(80)
    )
    dxf = dxf_document(
        f"""0
LINE
10
0
20
0
11
30
21
0
0
LINE
10
30
20
0
11
30
21
30
0
LINE
10
30
20
30
11
0
21
30
0
LINE
10
0
20
30
11
0
21
0
{duplicate_lines}
"""
    )

    project = import_dxf_project(
        {
            "filename": "many-duplicate-issues.dxf",
            "content": dxf,
            "base_project": example_project(),
            "import_options": {"repair_geometry": True},
        }
    )

    assert project["import"]["issue_counts"]["duplicate_segment_repaired"] == 79
    assert project["import"]["issue_display_limit_reached"] is True
    assert len([issue for issue in project["import"]["issues"] if issue["code"] == "duplicate_segment_repaired"]) == 51
    assert any("additional DXF duplicate_segment_repaired" in issue["message"] for issue in project["import"]["issues"])


def test_validate_project_runs_cam_checks_for_review_required_import_issues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = example_project()
    project["import"] = {
        "safe_for_export": False,
        "issues": [
            {
                "code": "open_contour",
                "message": "Open DXF contour skipped near X0 Y0",
                "blocking": True,
            }
        ],
    }

    calls = {"cam": 0}

    def record_cam_checks(*_args, **_kwargs):
        calls["cam"] += 1
        return []

    monkeypatch.setattr(web_api_module, "_cam_geometry_issue_items", record_cam_checks)

    issues = validate_project(project)

    import_issue = next(issue for issue in issues if issue["code"] == "import_open_contour")
    assert import_issue["blocking"] is False
    assert import_issue["review_required"] is False
    assert calls["cam"] == 1


def test_dxf_isolated_duplicate_repair_uses_endpoint_index(monkeypatch: pytest.MonkeyPatch) -> None:
    grouped = {}
    for index in range(500):
        start = Point(index * 10.0, 0.0)
        end = Point(index * 10.0 + 4.0, 0.0)
        first = LineSegment(start, end)
        second = LineSegment(end, start)
        grouped[dxf_importer_module._segment_key(first)] = [first, second]

    calls = 0
    original = dxf_importer_module._point_key

    def counting_point_key(point: Point):
        nonlocal calls
        calls += 1
        return original(point)

    monkeypatch.setattr(dxf_importer_module, "_point_key", counting_point_key)

    repaired = dxf_importer_module._isolated_duplicate_pair_keys(grouped)

    assert len(repaired) == len(grouped)
    assert calls < 6000


def test_dxf_self_intersection_loads_for_review_and_exports_centerline_warning() -> None:
    dxf = dxf_document(
        """0
LWPOLYLINE
90
8
70
1
10
0
20
0
10
100
20
0
10
0
20
100
10
120
20
100
10
20
20
0
10
120
20
0
10
120
20
120
10
0
20
120
"""
    )

    project = import_dxf_project(
        {
            "filename": "self-crossing.dxf",
            "content": dxf,
            "base_project": example_project(),
        }
    )

    assert project["import"]["safe_for_export"] is True
    assert project["import"]["blocking_issue_count"] == 0
    self_issue = next(issue for issue in project["import"]["issues"] if issue["code"] == "self_intersection")
    assert self_issue["x"] == pytest.approx(60)
    assert self_issue["y"] == pytest.approx(40)
    assert "import_self_intersection" in {issue["code"] for issue in validate_project(project)}
    gcode = export_project_gcode(project)
    assert "WARNING: import_self_intersection" in gcode
    assert "WARNING: kerf_offset_centerline" in gcode
    assert_valid_gcode(gcode)


def test_dxf_ring_vertex_self_touch_is_retained_for_centerline_cutting() -> None:
    dxf = dxf_document(
        """0
LWPOLYLINE
90
7
70
1
10
0
20
0
10
40
20
0
10
40
20
40
10
20
20
20
10
0
20
40
10
0
20
20
10
20
20
20
"""
    )

    base = example_project()
    base["post"]["lead_in_mode"] = "none"
    base["post"]["lead_in_mm"] = 0
    base["post"]["pierce_crater_diameter_mm"] = 0
    project = import_dxf_project(
        {
            "filename": "ring-touch.dxf",
            "content": dxf,
            "base_project": base,
        }
    )

    assert project["import"]["safe_for_export"] is True
    assert project["import"]["blocking_issue_count"] == 0
    assert project["import"]["issue_counts"] == {"self_intersection": 1}
    assert len(project["parts"]) == 1
    issue = next(issue for issue in project["import"]["issues"] if issue["code"] == "self_intersection")
    assert issue["x"] == pytest.approx(20)
    assert issue["y"] == pytest.approx(20)
    validation_codes = {issue["code"] for issue in validate_project(project)}
    assert "import_self_intersection" in validation_codes
    assert "kerf_offset_centerline" in validation_codes
    assert_valid_gcode(export_project_gcode(project))


def test_dxf_self_intersection_detection_uses_edge_sweep(monkeypatch: pytest.MonkeyPatch) -> None:
    points = [Point(float(index), 0.0) for index in range(500)]
    points.extend(Point(499.0, float(index)) for index in range(1, 80))
    points.extend(Point(float(index), 79.0) for index in range(498, -1, -1))
    points.extend(Point(0.0, float(index)) for index in range(78, 0, -1))
    contour = PathContour(
        "long_clean_outline",
        tuple(LineSegment(start, end) for start, end in zip(points, [*points[1:], points[0]])),
        "outer",
        "test",
    )
    calls = 0
    original = dxf_importer_module._segment_intersection_point

    def counting_intersection(first_start: Point, first_end: Point, second_start: Point, second_end: Point):
        nonlocal calls
        calls += 1
        return original(first_start, first_end, second_start, second_end)

    monkeypatch.setattr(dxf_importer_module, "_segment_intersection_point", counting_intersection)

    assert dxf_importer_module._self_intersection_issue(contour) is None
    assert calls < 5000


def test_dxf_part_grouping_uses_bbox_prefilter(monkeypatch: pytest.MonkeyPatch) -> None:
    contours = tuple(
        rectangle_profile(f"part_{index}", 4, 4).contours[0].transformed(dx=index * 10.0)
        for index in range(200)
    )
    calls = 0
    original = dxf_importer_module._contains_point

    def counting_contains(contour, point, points=None):
        nonlocal calls
        calls += 1
        return original(contour, point, points)

    monkeypatch.setattr(dxf_importer_module, "_contains_point", counting_contains)

    groups = dxf_importer_module._part_groups_from_contours(contours, source="bulk")

    assert len(groups) == len(contours)
    assert calls == 0


def test_dxf_spline_parser_caches_identical_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    dxf_importer_module._parse_spline_cached.cache_clear()
    block = [
        ("70", "0"),
        ("71", "3"),
        ("40", "0"),
        ("40", "0"),
        ("40", "0"),
        ("40", "0"),
        ("40", "1"),
        ("40", "1"),
        ("40", "1"),
        ("40", "1"),
        ("10", "0"),
        ("20", "0"),
        ("10", "10"),
        ("20", "20"),
        ("10", "20"),
        ("20", "20"),
        ("10", "30"),
        ("20", "0"),
    ]
    calls = 0
    original = dxf_importer_module._de_boor

    def counting_de_boor(controls, knots, degree, t):
        nonlocal calls
        calls += 1
        return original(controls, knots, degree, t)

    monkeypatch.setattr(dxf_importer_module, "_de_boor", counting_de_boor)

    first = dxf_importer_module._parse_spline(block, 1.0)
    first_calls = calls
    second = dxf_importer_module._parse_spline(block, 1.0)

    assert first == second
    assert first_calls > 0
    assert calls == first_calls


def test_dxf_closed_path_backtrack_spur_is_repaired_without_blocking_export() -> None:
    dxf = dxf_document(
        """0
LWPOLYLINE
90
6
70
1
10
0
20
0
10
100
20
0
10
100
20
100
10
110
20
100
10
100
20
100
10
0
20
100
"""
    )

    project = import_dxf_project(
        {
            "filename": "backtrack-spur.dxf",
            "content": dxf,
            "base_project": example_project(),
            "import_options": {"repair_geometry": True},
        }
    )

    repair_issue = next(issue for issue in project["import"]["issues"] if issue["code"] == "backtrack_segment_repaired")
    assert project["import"]["safe_for_export"] is True
    assert project["import"]["blocking_issue_count"] == 0
    assert repair_issue["blocking"] is False
    assert repair_issue["x"] == pytest.approx(105)
    assert repair_issue["y"] == pytest.approx(100)
    assert "import_backtrack_segment_repaired" in {issue["code"] for issue in validate_project(project)}
    assert_valid_gcode(export_project_gcode(project))


def test_dxf_collinear_retrace_spike_is_repaired_when_shape_is_unchanged() -> None:
    dxf = dxf_document(
        """0
LWPOLYLINE
90
8
70
1
10
0
20
0
10
100
20
0
10
100
20
100
10
50
20
100
10
80
20
100
10
65
20
100
10
50
20
100
10
0
20
100
"""
    )

    project = import_dxf_project(
        {
            "filename": "collinear-retrace-spike.dxf",
            "content": dxf,
            "base_project": example_project(),
            "import_options": {"repair_geometry": True},
        }
    )

    repair_issue = next(issue for issue in project["import"]["issues"] if issue["code"] == "collinear_overlap_repaired")
    assert project["import"]["safe_for_export"] is True
    assert project["import"]["blocking_issue_count"] == 0
    assert repair_issue["blocking"] is False
    assert repair_issue["x"] == pytest.approx(65)
    assert repair_issue["y"] == pytest.approx(100)
    assert "collinear_overlap" not in project["import"]["issue_counts"]
    assert "import_collinear_overlap_repaired" in {issue["code"] for issue in validate_project(project)}
    assert_valid_gcode(export_project_gcode(project))


def test_dxf_loose_line_retrace_spike_repair_does_not_leave_stale_overlap_blocker() -> None:
    dxf = dxf_document(
        """0
LINE
10
0
20
0
11
100
21
0
0
LINE
10
100
20
0
11
100
21
100
0
LINE
10
100
20
100
11
50
21
100
0
LINE
10
50
20
100
11
80
21
100
0
LINE
10
80
20
100
11
65
21
100
0
LINE
10
65
20
100
11
50
21
100
0
LINE
10
50
20
100
11
0
21
100
0
LINE
10
0
20
100
11
0
21
0
"""
    )

    project = import_dxf_project(
        {
            "filename": "loose-line-retrace.dxf",
            "content": dxf,
            "base_project": example_project(),
            "import_options": {"repair_geometry": True},
        }
    )

    assert project["import"]["safe_for_export"] is True
    assert project["import"]["blocking_issue_count"] == 0
    assert project["import"]["issue_counts"] == {"collinear_overlap_repaired": 1}
    assert validate_project(project) == [
        {
            "code": "import_collinear_overlap_repaired",
            "message": "Collinear retrace DXF path spike removed near X65.000 Y100.000",
            "instance_id": None,
            "blocking": False,
            "review_required": False,
            "entity_type": "LINE/ARC/ELLIPSE/SPLINE/LWPOLYLINE/POLYLINE/HATCH",
            "x": 65.0,
            "y": 100.0,
            "sheet_x": 75.0,
            "sheet_y": 110.0,
        }
    ]
    assert_valid_gcode(export_project_gcode(project))


def test_dxf_collinear_self_overlap_reports_marker_and_exports_centerline_warning() -> None:
    dxf = dxf_document(
        """0
LWPOLYLINE
90
4
70
1
10
0
20
0
10
100
20
0
10
100
20
100
10
0
20
100
0
LWPOLYLINE
90
5
70
1
10
20
20
20
10
80
20
20
10
40
20
20
10
80
20
80
10
20
20
80
"""
    )

    project = import_dxf_project(
        {
            "filename": "collinear-overlap.dxf",
            "content": dxf,
            "base_project": example_project(),
        }
    )

    overlap_issue = next(issue for issue in project["import"]["issues"] if issue["code"] == "collinear_overlap")
    assert project["import"]["safe_for_export"] is True
    assert project["import"]["blocking_issue_count"] == 0
    assert overlap_issue["blocking"] is False
    assert overlap_issue["gap_mm"] is None
    assert overlap_issue["x"] == pytest.approx(40)
    assert overlap_issue["y"] == pytest.approx(20)
    assert overlap_issue["target_x"] == pytest.approx(80)
    assert overlap_issue["target_y"] == pytest.approx(20)
    assert overlap_issue["sheet_x"] == pytest.approx(50)
    assert overlap_issue["sheet_y"] == pytest.approx(30)
    assert overlap_issue["target_sheet_x"] == pytest.approx(90)
    assert overlap_issue["target_sheet_y"] == pytest.approx(30)

    validation_issue = next(issue for issue in validate_project(project) if issue["code"] == "import_collinear_overlap")
    assert validation_issue["target_sheet_x"] == pytest.approx(90)
    gcode = export_project_gcode(project)
    assert "WARNING: import_collinear_overlap" in gcode
    assert "WARNING: kerf_offset_centerline" in gcode
    assert_valid_gcode(gcode)


def test_dxf_micro_collinear_overlap_is_warning_but_does_not_hide_blocking_overlap() -> None:
    micro_only = [
        LineSegment(Point(0, 0), Point(10, 0)),
        LineSegment(Point(0.1, 0), Point(0.2, 0)),
    ]
    micro_issue = dxf_importer_module._collinear_overlap_issue(micro_only, "PATH")

    assert micro_issue is not None
    assert micro_issue.code == "micro_collinear_overlap"
    assert micro_issue.blocking is False
    assert "0.100 mm" in micro_issue.message

    mixed = [
        LineSegment(Point(0, 0), Point(10, 0)),
        LineSegment(Point(0.1, 0), Point(0.2, 0)),
        LineSegment(Point(2, 0), Point(4, 0)),
    ]
    blocking_issue = dxf_importer_module._collinear_overlap_issue(mixed, "PATH")

    assert blocking_issue is not None
    assert blocking_issue.code == "collinear_overlap"
    assert blocking_issue.blocking is True
    assert blocking_issue.x == pytest.approx(2)
    assert blocking_issue.target_x == pytest.approx(4)


def test_dxf_collinear_overlap_detection_uses_candidate_groups(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    original = dxf_importer_module._line_collinear_overlap

    def counting_overlap(first: LineSegment, second: LineSegment):
        nonlocal calls
        calls += 1
        return original(first, second)

    monkeypatch.setattr(dxf_importer_module, "_line_collinear_overlap", counting_overlap)

    segments = [
        LineSegment(Point(index * 10.0, 0.0), Point(index * 10.0 + 5.0, 0.0))
        for index in range(1000)
    ]
    segments.append(LineSegment(Point(1230.0, 0.0), Point(1238.0, 0.0)))

    issue = dxf_importer_module._collinear_overlap_issue(segments, "LINE")

    assert issue is not None
    assert issue.code == "collinear_overlap"
    assert issue.x == pytest.approx(1230.0)
    assert issue.target_x == pytest.approx(1235.0)
    assert calls < 20


def test_dxf_parser_preserves_blank_header_values_without_losing_entities() -> None:
    dxf = """0
SECTION
2
HEADER
9
$DIMBLK
1

9
$LIMMAX
10
30
20
30
0
ENDSEC
0
SECTION
2
ENTITIES
0
LINE
10
0
20
0
11
30
21
0
0
LINE
10
30
20
0
11
30
21
30
0
LINE
10
30
20
30
11
0
21
30
0
LINE
10
0
20
30
11
0
21
0
0
ENDSEC
0
EOF
"""

    project = import_dxf_project(
        {
            "filename": "blank-header-rect.dxf",
            "content": dxf,
            "base_project": example_project(),
        }
    )

    assert project["import"]["entity_counts"]["LINE"] == 4
    assert project["import"]["contour_count"] == 1
    assert project["parts"][0]["contours"][0]["type"] == "path"
    assert validate_project(project) == []


def test_dxf_spline_segments_can_chain_with_lines() -> None:
    dxf = dxf_document(
        """0
SPLINE
8
0
70
8
71
1
72
4
73
2
40
0
40
0
40
1
40
1
10
0
20
0
10
30
20
0
0
LINE
10
30
20
0
11
30
21
30
0
LINE
10
30
20
30
11
0
21
30
0
LINE
10
0
20
30
11
0
21
0
"""
    )

    project = import_dxf_project(
        {
            "filename": "spline-rect.dxf",
            "content": dxf,
            "base_project": example_project(),
        }
    )

    assert project["import"]["entity_counts"]["SPLINE"] == 1
    assert project["import"]["contour_count"] == 1
    assert validate_project(project) == []


def test_degenerate_closed_lwpolyline_is_preserved_and_exported() -> None:
    dxf = dxf_document(
        """0
LWPOLYLINE
90
2
70
1
10
5
20
5
10
10
20
5
0
LWPOLYLINE
90
4
70
1
10
0
20
0
10
30
20
0
10
30
20
30
10
0
20
30
"""
    )

    project = import_dxf_project(
        {
            "filename": "degenerate-plus-rect.dxf",
            "content": dxf,
            "base_project": example_project(),
        }
    )

    assert project["import"]["entity_counts"]["LWPOLYLINE"] == 2
    assert project["import"]["contour_count"] == 2
    assert not any(code.endswith("_repaired") for code in project["import"]["issue_counts"])
    assert all(issue.get("blocking") is False for issue in validate_project(project))
    assert_valid_gcode(export_project_gcode(project))


def test_degenerate_loose_line_chain_is_preserved_after_chaining() -> None:
    dxf = dxf_document(
        """0
LINE
10
5
20
5
11
10
21
5
0
LINE
10
10
20
5
11
5
21
5
0
LINE
10
0
20
0
11
30
21
0
0
LINE
10
30
20
0
11
30
21
30
0
LINE
10
30
20
30
11
0
21
30
0
LINE
10
0
20
30
11
0
21
0
"""
    )

    project = import_dxf_project(
        {
            "filename": "degenerate-lines-plus-rect.dxf",
            "content": dxf,
            "base_project": example_project(),
        }
    )

    assert project["import"]["entity_counts"]["LINE"] == 6
    assert project["import"]["contour_count"] == 2
    assert project["import"]["safe_for_export"] is True
    assert project["import"]["blocking_issue_count"] == 0
    assert not any(code.endswith("_repaired") for code in project["import"]["issue_counts"])
    assert all(issue.get("blocking") is False for issue in validate_project(project))
    assert_valid_gcode(export_project_gcode(project))


def test_path_kerf_offset_bevels_excessive_miter_instead_of_failing() -> None:
    points = [
        Point(0, 0),
        Point(100, 0),
        Point(100.01, 0.0001),
        Point(100, 0.0002),
        Point(200, 0.0002),
        Point(200, 120),
        Point(0, 120),
    ]
    contour = PathContour(
        "shallow_miter",
        tuple(LineSegment(start, end) for start, end in zip(points, [*points[1:], points[0]])),
        "outer",
        "test",
    )

    gcode = generate_gcode(
        (contour,),
        QtPlasmaCOptions(kerf_width=1.2, lead_in_mode="line", lead_in=3),
    )

    assert_valid_gcode(gcode)
    assert "shallow_miter outer pierce" in gcode


def test_path_kerf_offset_rejects_self_intersecting_source_path() -> None:
    points = [
        Point(0, 0),
        Point(40, 20),
        Point(0, 30),
        Point(30, 0),
    ]
    contour = PathContour(
        "bowtie",
        tuple(LineSegment(start, end) for start, end in zip(points, [*points[1:], points[0]])),
        "outer",
        "test",
    )

    with pytest.raises(ValueError, match="self-intersects"):
        generate_gcode(
            (contour,),
            QtPlasmaCOptions(kerf_width=1.2, lead_in_mode="line", lead_in=0, kerf_offset_fallback="block"),
        )


def test_path_kerf_offset_rejects_collapsed_inner_offset() -> None:
    points = [
        Point(0, 0),
        Point(2, 0),
        Point(2, 2),
        Point(0, 2),
    ]
    contour = PathContour(
        "tiny_square_hole",
        tuple(LineSegment(start, end) for start, end in zip(points, [*points[1:], points[0]])),
        "hole",
        "test",
    )

    with pytest.raises(ValueError, match="collapsed"):
        generate_gcode(
            (contour,),
            QtPlasmaCOptions(kerf_width=6.0, lead_in_mode="line", lead_in=0, kerf_offset_fallback="block"),
        )


def test_path_centerline_fallback_allows_collapsed_inner_offset() -> None:
    points = [
        Point(0, 0),
        Point(2, 0),
        Point(2, 2),
        Point(0, 2),
    ]
    contour = PathContour(
        "tiny_square_hole",
        tuple(LineSegment(start, end) for start, end in zip(points, [*points[1:], points[0]])),
        "hole",
        "test",
    )

    gcode = generate_gcode(
        (contour,),
        QtPlasmaCOptions(
            kerf_width=6.0,
            lead_in_mode="none",
            kerf_offset_fallback="centerline",
        ),
    )

    assert_valid_gcode(gcode)
    assert "tiny_square_hole hole pierce" in gcode
