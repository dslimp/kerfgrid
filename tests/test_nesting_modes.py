from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import plasma_cam.autonest as nesting
from plasma_cam.nesting import Sheet
from plasma_cam.project import NestedLayout, PartRequest, PlacedPart, Placement, validate_layout
from plasma_cam.application.project_codec import requests_from_project
from plasma_cam.web_api import auto_nest_project, layout_from_project, load_project, validate_project
from tools.benchmark_autonest import build_benchmark_cases, rectangle_profile


def test_compact_mode_balances_extents_while_strip_preserves_top():
    case = build_benchmark_cases()[2]
    options = nesting.ShelfNestOptions(sheet=case.sheet, spacing=case.spacing, attempt_limit=12, allow_arbitrary_rotation=False, max_runtime_s=2)
    strip = nesting.shelf_nest_result("strip", case.requests, options)
    compact = nesting.shelf_nest_result("compact", case.requests, replace(options, layout_mode="compact"))
    assert validate_layout(strip.layout) == validate_layout(compact.layout) == []
    assert max(compact.summary.used_width_mm, compact.summary.used_height_mm) < max(strip.summary.used_width_mm, strip.summary.used_height_mm)
    assert strip.summary.used_height_mm < compact.summary.used_height_mm


def test_short_attempt_budget_explores_orders_policies_and_rotations():
    requests = tuple(PartRequest(rectangle_profile(name, w, h)) for name, w, h in [("wide", 100, 10), ("tall", 20, 80), ("square", 45, 45)])
    options = nesting.ShelfNestOptions(Sheet(500, 500), attempt_limit=12, angle_step_deg=30)
    attempts, limited = nesting._build_attempts(nesting._expand_instances(requests), options, nesting._GeometryCache())
    assert not limited
    assert len(attempts) == 12
    assert len({a.label.split('/')[0] for a in attempts}) > 1
    assert len({a.candidate_policy for a in attempts}) > 1
    assert len({a.rotation_pool for a in attempts}) > 1


def test_better_seed_survives_successful_worse_attempt(monkeypatch):
    profile = rectangle_profile("plate", 20, 20)
    sheet = Sheet(200, 200)
    seed = NestedLayout("seed", sheet, (PlacedPart(profile, Placement("plate", 1, 10, 10)),))
    worse = NestedLayout("worse", sheet, (PlacedPart(profile, Placement("plate", 1, 40, 40)),))
    options = nesting.ShelfNestOptions(sheet, allow_arbitrary_rotation=False)
    cache = nesting._GeometryCache()
    seed_score = nesting._layout_score(seed, options, cache)
    worse_score = nesting._layout_score(worse, options, cache)
    monkeypatch.setattr(nesting, "_pack_shelf_seed", lambda *a, **k: (seed, seed_score))
    monkeypatch.setattr(nesting, "_pack_lattice_attempts", lambda *a, **k: [])
    monkeypatch.setattr(nesting, "_pack_attempts_serial", lambda *a, **k: ((worse_score, worse, "worse"), 1, False))
    monkeypatch.setattr(nesting, "_compact_layout", lambda layout, *a, **k: layout)
    result = nesting.shelf_nest_result("test", (PartRequest(profile),), options)
    assert result.layout is seed
    assert result.summary.best_attempt == "shelf-seed"


@pytest.mark.parametrize("mode", ["compact", "strip"])
def test_project_result_and_history_preserve_selected_mode(mode):
    project = load_project(Path(__file__).resolve().parents[1] / "examples/circle-hole.project.json")
    project["nesting"] = {"layout_mode": mode, "auto_nest_attempts": 1, "allow_arbitrary_rotation": False}
    result = auto_nest_project(project)
    assert result["nesting"]["layout_mode"] == mode
    assert result["nesting"]["last_result"]["layout_mode"] == mode
    assert result["nesting"]["run_history"][-1]["layout_mode"] == mode


def test_eight_tabs_form_block_instead_of_vertical_column():
    project = load_project(Path(__file__).parent / "fixtures/eave-tabs-block.project.json")
    project["parts"][0]["allowed_rotations"] = [0, 180]
    result = auto_nest_project(project)
    layout = layout_from_project(result)
    summary = result["nesting"]["last_result"]
    assert len(layout.placed_parts) == 8
    assert validate_layout(layout) == []
    assert summary["used_width_mm"] < 280
    assert summary["used_height_mm"] < 280
    assert len({round(part.bbox()[0]) for part in layout.placed_parts}) == 2


def test_compaction_trades_small_upward_move_for_aligned_edges():
    project = load_project(Path(__file__).parent / "fixtures/eave-tabs-staircase.project.json")
    layout = layout_from_project(project)
    assert validate_layout(layout) == []
    options = nesting.ShelfNestOptions(layout.sheet, spacing=layout.spacing, layout_mode="compact")
    compacted = nesting._compact_layout(layout, options)
    assert validate_layout(compacted) == []
    assert max(part.bbox()[0] for part in compacted.placed_parts) < 0.001
    assert max(part.bbox()[2] for part in compacted.placed_parts) <= 120.001
    assert max(part.bbox()[3] for part in compacted.placed_parts) < 219


def test_compaction_preserves_locked_placement():
    project = load_project(Path(__file__).parent / "fixtures/eave-tabs-staircase.project.json")
    for placement in project["placements"]:
        placement["locked"] = True
    layout = layout_from_project(project)
    options = nesting.ShelfNestOptions(layout.sheet, spacing=layout.spacing, layout_mode="compact")
    assert nesting._compact_layout(layout, options).placed_parts == layout.placed_parts


def test_eighteen_tabs_find_opposing_pairs_without_existing_placements():
    project = load_project(Path(__file__).parent / "fixtures/eave-tabs-block.project.json")
    project["parts"][0].update(quantity=18, allowed_rotations=[0, 180])
    project["placements"] = []
    result = auto_nest_project(project)
    summary = result["nesting"]["last_result"]
    assert len(result["placements"]) == 18
    assert summary["best_attempt"].startswith("paired/")
    assert summary["used_width_mm"] <= 372.001
    assert summary["used_height_mm"] < 293
    assert summary["used_bbox_area_mm2"] < 109000
    assert summary["packing_utilization_percent"] > 78
    assert summary["auto_lead_override_count"] == 18
    assert all(issue["code"] == "safe_travel" and not issue["blocking"] for issue in validate_project(result))
    result["post"]["travel_clearance_mm"] = 2
    assert validate_project(result) == []
    from plasma_cam.web_api import export_project_gcode
    assert "M0 " not in export_project_gcode(result)


@pytest.mark.parametrize("quantity,rotations", [(17, [0, 180]), (18, [90, 270])])
def test_pair_seeds_handle_odd_counts_and_rotated_profiles(quantity, rotations):
    project = load_project(Path(__file__).parent / "fixtures/eave-tabs-block.project.json")
    project["parts"][0].update(quantity=quantity, allowed_rotations=rotations)
    project["placements"] = []
    instances = nesting._expand_instances(tuple(requests_from_project(project)))
    options = nesting.ShelfNestOptions(Sheet(600, 600, 7), spacing=6, start_x=20, start_y=25, layout_mode="compact")
    results = nesting._pack_paired_seeds("pairs", instances, options, deadline=nesting.time.monotonic() + 0.3, stats=None, cache=nesting._GeometryCache())
    assert results
    layout = results[0][0]
    assert len(layout.placed_parts) == quantity
    assert {part.placement.rotation_deg for part in layout.placed_parts} == set(rotations)
    assert {part.placement.instance for part in layout.placed_parts} == set(range(1, quantity + 1))
    assert min(part.bbox()[0] for part in layout.placed_parts) >= 20
    assert min(part.bbox()[1] for part in layout.placed_parts) >= 25
    assert validate_layout(layout) == []


def test_pair_seeds_respect_rotation_restrictions_and_blocked_zones():
    project = load_project(Path(__file__).parent / "fixtures/eave-tabs-block.project.json")
    project["parts"][0]["allowed_rotations"] = [0]
    instances = nesting._expand_instances(tuple(requests_from_project(project)))
    options = nesting.ShelfNestOptions(Sheet(500, 500), spacing=6, layout_mode="compact")
    assert nesting._pack_paired_seeds("restricted", instances, options, deadline=None, stats=None, cache=nesting._GeometryCache()) == []
    project["parts"][0]["allowed_rotations"] = [0, 180]
    instances = nesting._expand_instances(tuple(requests_from_project(project)))
    blocked = replace(options, blocked_boxes=((0, 0, 500, 500),))
    assert nesting._pack_paired_seeds("blocked", instances, blocked, deadline=nesting.time.monotonic() + 0.2, stats=None, cache=nesting._GeometryCache()) == []


def test_pair_seed_retains_valid_result_when_search_times_out(monkeypatch):
    project = load_project(Path(__file__).parent / "fixtures/eave-tabs-block.project.json")
    instances = nesting._expand_instances(tuple(requests_from_project(project)))
    options = nesting.ShelfNestOptions(Sheet(500, 500), spacing=6, layout_mode="compact")
    original = nesting._paired_grid_layout
    completed = []

    def stop_after_first(*args, **kwargs):
        if completed:
            raise TimeoutError
        result = original(*args, **kwargs)
        if result is not None:
            completed.append(result)
        return result

    monkeypatch.setattr(nesting, "_paired_grid_layout", stop_after_first)
    result = nesting._pack_paired_seeds("timeout", instances, options, deadline=None, stats=None, cache=nesting._GeometryCache())
    assert result[0][0] is completed[0]
    assert validate_layout(result[0][0]) == []
    assert nesting._pack_paired_seeds("expired", instances, options, deadline=nesting.time.monotonic() - 1, stats=None, cache=nesting._GeometryCache()) == []


def test_pair_seeds_use_compact_or_strip_objective():
    project = load_project(Path(__file__).parent / "fixtures/eave-tabs-block.project.json")
    project["parts"][0].update(quantity=18, allowed_rotations=[0, 180])
    instances = nesting._expand_instances(tuple(requests_from_project(project)))
    layouts = {}
    for mode in ("compact", "strip"):
        options = nesting.ShelfNestOptions(Sheet(1000, 500), spacing=6, layout_mode=mode)
        layouts[mode] = nesting._pack_paired_seeds(mode, instances, options, deadline=nesting.time.monotonic() + 0.2, stats=None, cache=nesting._GeometryCache())[0][0]
        assert validate_layout(layouts[mode]) == []
    compact_width = max(part.bbox()[2] for part in layouts["compact"].placed_parts)
    compact_height = max(part.bbox()[3] for part in layouts["compact"].placed_parts)
    strip_width = max(part.bbox()[2] for part in layouts["strip"].placed_parts)
    strip_height = max(part.bbox()[3] for part in layouts["strip"].placed_parts)
    assert strip_height < compact_height
    assert compact_width**2 + compact_height**2 < strip_width**2 + strip_height**2
