from __future__ import annotations

import sys
from pathlib import Path

import pytest
from shapely.geometry import LineString, Point as ShapelyPoint, Polygon

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plasma_cam.model import LineSegment, PathContour, Point
from plasma_cam.cam.gcode import format_number
from plasma_cam.post import LeadOverride, QtPlasmaCOptions, generate_gcode, planned_lead_moves
from plasma_cam.web_api import _apply_auto_lead_overrides, _post_options_from_project, export_project_gcode, layout_from_project, load_project, validate_project


def tab_contour(kind="outer", reverse=False):
    points = [Point(90, 10), Point(0, 10), Point(0, 60), Point(120, 34.5), Point(120, 0), Point(90, 0)]
    if reverse:
        points.reverse()
    return PathContour("tab", tuple(LineSegment(a, b) for a, b in zip(points, [*points[1:], points[0]])), kind)


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("kind", ["outer", "inner"])
def test_concave_path_lead_stays_in_waste_and_matches_export(kind, reverse):
    contour = tab_contour(kind, reverse)
    options = QtPlasmaCOptions(kerf_width=1.3, lead_in_mode="line", lead_in=5, safe_travel=False, lead_overrides=(LeadOverride("tab", start_x=90, start_y=10),))
    move = planned_lead_moves((contour,), options)[0]
    polygon = Polygon([(p.x, p.y) for p in contour.points()])
    line = LineString([(p.x, p.y) for p in move.lead_in_points])
    crater = ShapelyPoint(move.pierce.x, move.pierce.y).buffer(2)
    if kind == "outer":
        assert line.intersection(polygon).length < 1e-6
        assert crater.intersection(polygon).area < 1e-6
    else:
        assert polygon.covers(line)
        assert polygon.covers(crater)
    gcode = generate_gcode((contour,), options)
    assert f"G0 X{format_number(move.pierce.x, 3)} Y{format_number(move.pierce.y, 3)} (tab {kind} pierce)" in gcode
    assert f"G1 X{format_number(move.start.x, 3)} Y{format_number(move.start.y, 3)} (lead in)" in gcode


def test_manual_pierce_is_preserved():
    contour = tab_contour()
    options = QtPlasmaCOptions(lead_in_mode="line", lead_overrides=(LeadOverride("tab", start_x=90, start_y=10, pierce_x=95, pierce_y=10),))
    move = planned_lead_moves((contour,), options)[0]
    assert move.start == Point(90, 10)
    assert move.pierce == Point(95, 10)


def test_manual_lead_cutting_retained_material_is_visible_warning():
    root = Path(__file__).resolve().parents[1]
    project = load_project(root / "examples/circle-hole.project.json")
    contour = tab_contour()
    project["parts"] = [{"name": "tab", "quantity": 1, "contours": [{
        "type": "path", "name": "tab", "kind": "outer", "segments": [
            {"type": "line", "start": {"x": s.start.x, "y": s.start.y}, "end": {"x": s.end.x, "y": s.end.y}}
            for s in contour.segments
        ]
    }]}]
    project["placements"] = [{"part_name": "tab", "instance": 1, "dx": 20, "dy": 20, "rotation_deg": 0}]
    project["lead_overrides"] = [{"contour_name": "tab_1_tab", "start_x_mm": 110, "start_y_mm": 30, "pierce_x_mm": 115, "pierce_y_mm": 30, "lead_in_mode": "line"}]
    assert "lead_own_part_collision" in {i["code"] for i in validate_project(project)}
    assert "WARNING: lead_own_part_collision" in export_project_gcode(project)
    project["lead_overrides"][0].update(pierce_x_mm=None, pierce_y_mm=None)
    assert "lead_own_part_collision" not in {i["code"] for i in validate_project(project)}


def test_auto_leads_use_existing_waste_inside_layout_rectangle():
    from shapely.geometry import box

    project = load_project(Path(__file__).parent / "fixtures/eave-tabs-block.project.json")
    layout = layout_from_project(project)
    updated, count = _apply_auto_lead_overrides(project, layout)
    assert count > 0
    bounds = [part.bbox() for part in layout.placed_parts]
    envelope = box(min(b[0] for b in bounds), min(b[1] for b in bounds), max(b[2] for b in bounds), max(b[3] for b in bounds))
    for move in planned_lead_moves(layout.contours(), _post_options_from_project(updated, layout)):
        assert envelope.buffer(1e-6).covers(ShapelyPoint(move.pierce.x, move.pierce.y).buffer(2))
    assert not any(i["code"].startswith("lead_") for i in validate_project(updated))


def test_operator_pierce_override_is_not_optimized_away():
    project = load_project(Path(__file__).parent / "fixtures/eave-tabs-block.project.json")
    layout = layout_from_project(project)
    name = layout.contours()[0].name
    manual = {"id": "operator", "contour_name": name, "start_x_mm": 120, "start_y_mm": 0, "pierce_x_mm": 125, "pierce_y_mm": 0, "lead_in_mode": "line"}
    project["lead_overrides"] = [manual]
    updated, _count = _apply_auto_lead_overrides(project, layout)
    assert manual in updated["lead_overrides"]
