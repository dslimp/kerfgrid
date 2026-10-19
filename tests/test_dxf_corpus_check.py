from __future__ import annotations

import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from tools import dxf_corpus_check
from tools.dxf_corpus_check import discover_dxf_files, render_markdown_report, run_corpus


def test_dxf_corpus_check_runs_examples_through_simulation() -> None:
    paths = discover_dxf_files([PROJECT_ROOT / "examples"])
    report = run_corpus(paths, max_files=3, per_file_timeout_s=5)

    assert report["counts"]["files"] == 3
    assert report["counts"]["import_ok"] == 3
    assert report["counts"]["export_ok"] == 3
    assert report["counts"]["simulation_ok"] == 3
    assert report["counts"]["timed_out"] == 0
    assert all(item["simulation_segment_count"] > 0 for item in report["results"])
    assert report["diagnostics"]["top_slow_files"]
    assert report["diagnostics"]["top_slow_stages"]


def test_dxf_corpus_import_only_skips_export_and_simulation_without_failure() -> None:
    paths = [PROJECT_ROOT / "examples" / "circle-hole.dxf"]
    report = run_corpus(paths, export=False, per_file_timeout_s=5)
    entry = report["results"][0]

    assert report["export_enabled"] is False
    assert report["counts"]["import_ok"] == 1
    assert report["counts"]["export_ok"] == 0
    assert report["counts"]["simulation_ok"] == 0
    assert report["counts"]["export_skipped"] == 1
    assert report["counts"]["simulation_skipped"] == 1
    assert report["counts"]["export_failed"] == 0
    assert report["counts"]["simulation_failed"] == 0
    assert dxf_corpus_check.failure_stage(entry) == "ok"
    assert entry["export_skip_reason"] == "import_only"


def test_dxf_corpus_check_can_auto_nest_before_simulation() -> None:
    paths = discover_dxf_files([PROJECT_ROOT / "examples"])
    report = run_corpus(paths, max_files=1, auto_nest=True, auto_nest_timeout_s=1, per_file_timeout_s=8)
    entry = report["results"][0]

    assert report["counts"]["files"] == 1
    assert report["counts"]["auto_nest_ok"] == 1
    assert report["counts"]["auto_nest_placement_mismatch"] == 0
    assert report["counts"]["export_ok"] == 1
    assert report["counts"]["simulation_ok"] == 1
    assert entry["auto_nest_placement_count"] == entry["placement_count"]
    assert entry["auto_nest_runtime_s"] <= 2.0
    assert entry["auto_nest_summary"]["attempt_count"] >= 1
    assert entry["auto_nest_summary"]["successful_attempt_count"] >= 1
    assert entry["auto_nest_summary"]["packing_utilization_percent"] > 0
    assert report["max_auto_nest_runtime_s"] == report["diagnostics"]["max_auto_nest_runtime_s"]
    assert report["max_auto_nest_runtime_s"] == entry["auto_nest_runtime_s"]
    assert report["auto_nest_exportable_missed_count"] == 0
    assert report["auto_nest_exportable_misses"] == []


def test_dxf_corpus_records_auto_nest_runtime_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    paths = [PROJECT_ROOT / "examples" / "circle-hole.dxf"]

    def fail_auto_nest(_project):
        raise ValueError("forced auto nest failure")

    monkeypatch.setattr(dxf_corpus_check, "auto_nest_project", fail_auto_nest)

    report = run_corpus(paths, auto_nest=True, auto_nest_timeout_s=1)
    entry = report["results"][0]

    assert entry["auto_nest_ok"] is False
    assert entry["auto_nest_runtime_s"] >= 0
    assert entry["auto_nest_error"]["message"] == "forced auto nest failure"
    assert report["diagnostics"]["max_auto_nest_runtime_s"] == entry["auto_nest_runtime_s"]
    assert report["max_auto_nest_runtime_s"] == entry["auto_nest_runtime_s"]


def test_dxf_corpus_runs_auto_nest_when_import_has_review_required_issues(monkeypatch: pytest.MonkeyPatch) -> None:
    paths = [PROJECT_ROOT / "examples" / "circle-hole.dxf"]
    original_import = dxf_corpus_check.import_dxf_project
    calls = {"auto_nest": 0}

    def record_auto_nest(project):
        calls["auto_nest"] += 1
        return project

    def unsafe_import(payload):
        project = original_import(payload)
        project.setdefault("import", {})["issues"] = [
            {"code": "open_contour", "message": "Open contour", "blocking": True}
        ]
        project["import"]["blocking_issue_count"] = 1
        project["import"]["safe_for_export"] = False
        return project

    monkeypatch.setattr(dxf_corpus_check, "auto_nest_project", record_auto_nest)
    monkeypatch.setattr(dxf_corpus_check, "import_dxf_project", unsafe_import)

    report = run_corpus(paths, auto_nest=True, auto_nest_timeout_s=1)
    entry = report["results"][0]

    assert entry["auto_nest_ok"] is True
    assert entry["import_policy_safe_for_auto_nest"] is True
    assert entry["import_policy_blocking_issue_count"] == 0
    assert calls["auto_nest"] == 1
    assert report["counts"]["auto_nest_skipped"] == 0
    assert report["counts"]["auto_nest_failed"] == 0


def test_dxf_corpus_does_not_count_auto_nest_misses_when_auto_nest_is_disabled() -> None:
    paths = [PROJECT_ROOT / "examples" / "circle-hole.dxf"]

    report = run_corpus(paths, auto_nest=False)

    assert report["counts"]["auto_nest_exportable_missed"] == 0
    assert report["diagnostics"]["auto_nest_exportable_missed_count"] == 0
    assert report["auto_nest_exportable_missed_count"] == 0
    assert report["auto_nest_exportable_misses"] == []


def test_dxf_corpus_timeout_reports_last_worker_stage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "slow.dxf"
    path.write_text("0\nEOF\n", encoding="utf-8")

    def fake_run(*args, **kwargs):
        raise dxf_corpus_check.subprocess.TimeoutExpired(
            args[0],
            kwargs["timeout"],
            output="",
            stderr="DXF_CORPUS_STAGE import\nDXF_CORPUS_STAGE auto_nest\n",
        )

    monkeypatch.setattr(dxf_corpus_check.subprocess, "run", fake_run)

    entry = dxf_corpus_check.check_dxf_file_subprocess(path, auto_nest=True, timeout_s=0.1)

    assert entry["timed_out"] is True
    assert entry["import_ok"] is True
    assert entry["auto_nest_ok"] is False
    assert entry["stage"] == "auto_nest"
    assert entry["timeout_stage"] == "auto_nest"
    assert entry["timeout_error"]["message"] == "DXF corpus check exceeded 0.1 s during auto_nest"
    assert entry["auto_nest_error"]["type"] == "TimeoutExpired"


def test_dxf_corpus_timeout_stage_updates_successful_prior_stages(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "slow-export.dxf"
    path.write_text("0\nEOF\n", encoding="utf-8")

    def fake_run(*args, **kwargs):
        raise dxf_corpus_check.subprocess.TimeoutExpired(
            args[0],
            kwargs["timeout"],
            output="",
            stderr="DXF_CORPUS_STAGE import\nDXF_CORPUS_STAGE auto_nest\nDXF_CORPUS_STAGE validation\nDXF_CORPUS_STAGE export\n",
        )

    monkeypatch.setattr(dxf_corpus_check.subprocess, "run", fake_run)

    report = run_corpus([path], auto_nest=True, per_file_timeout_s=0.1)
    entry = report["results"][0]

    assert entry["timed_out"] is True
    assert entry["import_ok"] is True
    assert entry["auto_nest_ok"] is True
    assert entry["export_ok"] is False
    assert entry["timeout_stage"] == "export"
    assert entry["export_error"]["type"] == "TimeoutExpired"
    assert report["counts"]["import_failed"] == 0
    assert report["counts"]["export_failed"] == 1


def test_dxf_corpus_markdown_report_summarizes_slow_files_and_stages() -> None:
    report = {
        "generated_at": "2026-08-23T00:00:00Z",
        "runtime_s": 3.5,
        "auto_nest": True,
        "counts": {
            "files": 2,
            "import_ok": 1,
            "auto_nest_ok": 1,
            "auto_nest_skipped": 0,
            "auto_nest_failed": 1,
            "auto_nest_placement_mismatch": 1,
            "auto_nest_exportable_missed": 1,
            "export_ok": 1,
            "simulation_ok": 1,
            "timed_out": 1,
        },
        "results": [
            {"name": "ok.dxf", "auto_nest_runtime_s": 1.5},
        ],
        "acceptance": {
            "ok": False,
            "failures": ["timed_out 1 > 0"],
            "criteria": {"max_timeouts": 0},
        },
        "diagnostics": {
            "failure_stage_counts": {"auto_nest": 1},
            "issue_code_counts": {"import_open_contour": 3, "safe_travel": 2},
            "validation_issue_code_counts": {"import_open_contour": 3},
            "import_issue_code_counts": {"open_contour": 3},
            "validation_blocking_issue_code_counts": {"import_open_contour": 3},
            "validation_warning_issue_code_counts": {"safe_travel": 2},
            "import_blocking_issue_code_counts": {"open_contour": 3},
            "import_warning_issue_code_counts": {"tiny_segment_repaired": 1},
            "issue_examples": {
                "validation_blocking": {
                    "import_open_contour": [
                        {
                            "name": "open.dxf",
                            "path": "/tmp/open.dxf",
                            "failure_stage": "validation",
                            "stage": "done",
                            "runtime_s": 1.0,
                            "error_types": ["ValueError"],
                        }
                    ]
                }
            },
            "blocking_file_count": 2,
            "blocking_files": [
                {
                    "name": "open.dxf",
                    "path": "/tmp/open.dxf",
                    "failure_stage": "validation",
                    "import_blocking_issue_codes": ["open_contour"],
                    "validation_blocking_issue_codes": ["import_open_contour"],
                }
            ],
            "auto_nest_placement_mismatches": [
                {
                    "name": "lost-placement.dxf",
                    "placement_count": 2,
                    "auto_nest_placement_count": 1,
                }
            ],
            "auto_nest_exportable_misses": [
                {
                    "name": "missed.dxf",
                    "auto_nest_ok": False,
                    "error_message": "Auto nest exceeded time budget",
                }
            ],
            "top_slow_files": [
                {
                    "name": "slow.dxf",
                    "runtime_s": 20.0,
                    "failure_stage": "auto_nest",
                    "timeout_stage": "auto_nest",
                    "error_types": ["TimeoutExpired"],
                }
            ],
            "top_slow_stages": [
                {
                    "name": "ok.dxf",
                    "stage": "import",
                    "runtime_s": 7.0,
                    "failure_stage": "ok",
                }
            ],
            "timeouts": [
                {
                    "name": "slow.dxf",
                    "runtime_s": 20.0,
                    "auto_nest_runtime_s": 1.5,
                    "timeout_s": 20.0,
                    "timeout_stage": "auto_nest",
                }
            ],
        },
    }

    markdown = render_markdown_report(report)

    assert "# DXF Corpus Report" in markdown
    assert "## Acceptance" in markdown
    assert "timed_out 1 > 0" in markdown
    assert "## Top Slow Files" in markdown
    assert "slow.dxf" in markdown
    assert "auto_nest" in markdown
    assert "## Issue Codes" in markdown
    assert "import_open_contour" in markdown
    assert "open_contour" in markdown
    assert "validation" in markdown
    assert "validation blocking" in markdown
    assert "validation warning" in markdown
    assert "## Issue Examples" in markdown
    assert "open.dxf" in markdown
    assert "## Blocking Files" in markdown
    assert "Showing 1 of 2 blocking files." in markdown
    assert "import_open_contour" in markdown
    assert "## Auto Nest" in markdown
    assert "auto_nest_ok" in markdown
    assert "max_auto_nest_runtime" in markdown
    assert "placement_mismatch" in markdown
    assert "exportable_missed" in markdown
    assert "### Exportable Auto Nest Misses" in markdown
    assert "missed.dxf" in markdown
    assert "### Placement Mismatches" in markdown
    assert "lost-placement.dxf" in markdown
    assert "## Top Slow Stages" in markdown


def test_dxf_corpus_diagnostics_keep_issue_examples() -> None:
    diagnostics = dxf_corpus_check.build_diagnostics(
        [
            {
                "name": "open.dxf",
                "path": "/tmp/open.dxf",
                "runtime_s": 1.0,
                "stage": "done",
                "import_ok": True,
                "export_ok": False,
                "simulation_ok": False,
                "validation_blocking_issue_count": 1,
                "validation_blocking_issue_codes": ["import_open_contour"],
                "validation_warning_issue_codes": ["safe_travel"],
                "import_blocking_issue_codes": ["open_contour"],
                "import_warning_issue_codes": ["tiny_segment_repaired"],
                "export_error": {"type": "ValueError", "message": "Project has unresolved DXF import issues"},
            },
            {
                "name": "allowed-open.dxf",
                "path": "/tmp/allowed-open.dxf",
                "runtime_s": 0.5,
                "stage": "done",
                "import_ok": True,
                "export_ok": True,
                "simulation_ok": True,
                "validation_blocking_issue_count": 0,
                "validation_blocking_issue_codes": [],
                "validation_warning_issue_codes": ["import_open_contour"],
                "import_blocking_issue_codes": ["open_contour"],
            }
        ]
    )

    examples = diagnostics["issue_examples"]

    assert examples["validation_blocking"]["import_open_contour"][0]["name"] == "open.dxf"
    assert examples["validation_warning"]["safe_travel"][0]["failure_stage"] == "validation"
    assert examples["import_blocking"]["open_contour"][0]["error_types"] == ["ValueError"]
    assert examples["import_warning"]["tiny_segment_repaired"][0]["path"] == "/tmp/open.dxf"
    assert examples["validation_blocking"]["import_open_contour"][0]["validation_blocking_issue_codes"] == [
        "import_open_contour"
    ]
    assert diagnostics["blocking_files"][0]["name"] == "open.dxf"
    assert diagnostics["blocking_files"][0]["import_blocking_issue_codes"] == ["open_contour"]
    assert diagnostics["blocking_files"][0]["validation_blocking_issue_codes"] == ["import_open_contour"]
    assert diagnostics["blocking_file_count"] == 1
    assert all(item["name"] != "allowed-open.dxf" for item in diagnostics["blocking_files"])


def test_dxf_corpus_main_writes_json_and_markdown_report(tmp_path: Path) -> None:
    json_path = tmp_path / "report.json"
    markdown_path = tmp_path / "report.md"

    rc = dxf_corpus_check.main(
        [
            str(PROJECT_ROOT / "examples"),
            "--max-files",
            "1",
            "--per-file-timeout",
            "5",
            "--output",
            str(json_path),
            "--markdown-output",
            str(markdown_path),
            "--quiet",
        ]
    )

    assert rc == 0
    assert "\"diagnostics\"" in json_path.read_text(encoding="utf-8")
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "DXF Corpus Report" in markdown
    assert "Top Slow Files" in markdown


def test_dxf_corpus_main_can_write_incremental_reports(tmp_path: Path) -> None:
    json_path = tmp_path / "report.json"
    markdown_path = tmp_path / "report.md"

    rc = dxf_corpus_check.main(
        [
            str(PROJECT_ROOT / "examples"),
            "--max-files",
            "1",
            "--per-file-timeout",
            "5",
            "--output",
            str(json_path),
            "--markdown-output",
            str(markdown_path),
            "--incremental-output",
            "--quiet",
        ]
    )

    assert rc == 0
    report = dxf_corpus_check.json.loads(json_path.read_text(encoding="utf-8"))
    assert report["complete"] is True
    assert report["completed_files"] == 1
    assert report["selected_files"] == 1
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "Complete: true" in markdown
    assert "Completed: 1 / 1" in markdown


def test_dxf_corpus_acceptance_passes_current_thresholds() -> None:
    report = {
        "complete": True,
        "completed_files": 3,
        "counts": {
            "files": 3,
            "import_ok": 3,
            "auto_nest_ok": 2,
            "auto_nest_placement_mismatch": 0,
            "auto_nest_exportable_missed": 0,
            "export_ok": 2,
            "simulation_ok": 2,
            "timed_out": 0,
        },
        "results": [
            {"auto_nest_runtime_s": 0.25},
            {"auto_nest_runtime_s": 0.75},
        ],
        "diagnostics": {
            "validation_blocking_issue_code_counts": {"import_open_contour": 1},
            "validation_warning_issue_code_counts": {"safe_travel": 1},
        },
    }

    failures = dxf_corpus_check.validate_corpus_acceptance(
        report,
        require_complete=True,
        min_files=3,
        min_completed_files=3,
        min_import_ok=3,
        min_auto_nest_ok=2,
        min_export_ok=2,
        min_simulation_ok=2,
        max_auto_nest_runtime_s=1.0,
        require_auto_nest_placements=True,
        require_auto_nest_for_exportable=True,
        max_timeouts=0,
        forbid_validation_blocking_codes=["small_feature_below_kerf"],
    )

    assert failures == []


def test_dxf_corpus_base_project_can_enable_open_path_centerline() -> None:
    project = dxf_corpus_check.base_project(open_path_centerline=True)

    assert project["post"]["open_path_mode"] == "centerline"


def test_dxf_corpus_can_downgrade_unsafe_entities_to_warnings(tmp_path: Path) -> None:
    path = tmp_path / "region-with-profile.dxf"
    path.write_text(
        """0
SECTION
2
ENTITIES
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
ENDSEC
0
EOF
""",
        encoding="utf-8",
    )

    report = run_corpus([path], unsafe_entity_policy="warn")
    entry = report["results"][0]

    assert entry["import_ok"] is True
    assert entry["export_ok"] is True
    assert entry["simulation_ok"] is True
    assert entry["import_warning_issue_codes"] == ["unsupported_unsafe_entity"]
    assert entry["validation_warning_issue_codes"] == ["import_unsupported_unsafe_entity"]
    assert report["unsafe_entity_policy"] == "warn"


def test_dxf_corpus_entries_keep_compact_issue_details(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "overlap.dxf"
    path.write_text(
        """0
SECTION
2
ENTITIES
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
0
ENDSEC
0
EOF
""",
        encoding="utf-8",
    )

    report = run_corpus([path])
    entry = report["results"][0]

    assert entry["export_ok"] is True
    assert entry["import_blocking_issue_codes"] == []
    assert entry["import_warning_issue_codes"] == ["collinear_overlap"]
    assert entry["validation_blocking_issue_codes"] == []
    assert entry["validation_warning_issue_codes"] == ["import_collinear_overlap", "kerf_offset_centerline"]
    assert entry["import_warning_issues"][0]["code"] == "collinear_overlap"
    assert entry["import_warning_issues"][0]["x"] == pytest.approx(40)
    assert entry["import_warning_issues"][0]["target_x"] == pytest.approx(80)
    assert "Collinear overlapping DXF line edges" in entry["import_warning_issues"][0]["message"]
    validation_overlap = next(issue for issue in entry["validation_warning_issues"] if issue["code"] == "import_collinear_overlap")
    assert validation_overlap["sheet_x"] == pytest.approx(40)
    assert report["diagnostics"]["blocking_file_count"] == 0

    monkeypatch.setattr(dxf_corpus_check, "ISSUE_SHEET_POINTS_MAX_BYTES", 0)
    fast_report = run_corpus([path])
    fast_entry = fast_report["results"][0]
    fast_validation_overlap = next(
        issue for issue in fast_entry["validation_warning_issues"] if issue["code"] == "import_collinear_overlap"
    )
    assert "sheet_x" not in fast_validation_overlap


def test_dxf_corpus_acceptance_reports_regressions() -> None:
    report = {
        "complete": False,
        "completed_files": 2,
        "counts": {
            "files": 2,
            "import_ok": 1,
            "auto_nest_ok": 1,
            "auto_nest_placement_mismatch": 1,
            "auto_nest_exportable_missed": 1,
            "export_ok": 0,
            "simulation_ok": 0,
            "timed_out": 1,
        },
        "results": [
            {"auto_nest_runtime_s": 1.75},
        ],
        "diagnostics": {
            "validation_blocking_issue_code_counts": {"small_feature_below_kerf": 2},
            "validation_warning_issue_code_counts": {"safe_travel": 3},
        },
    }

    failures = dxf_corpus_check.validate_corpus_acceptance(
        report,
        require_complete=True,
        min_files=3,
        min_completed_files=3,
        min_import_ok=3,
        min_auto_nest_ok=2,
        min_export_ok=2,
        min_simulation_ok=2,
        max_auto_nest_runtime_s=1.0,
        require_auto_nest_placements=True,
        require_auto_nest_for_exportable=True,
        max_timeouts=0,
        forbid_validation_blocking_codes=["small_feature_below_kerf"],
        forbid_validation_warning_codes=["safe_travel"],
    )

    assert "report is incomplete" in failures
    assert "files 2 < 3" in failures
    assert "completed_files 2 < 3" in failures
    assert "import_ok 1 < 3" in failures
    assert "auto_nest_ok 1 < 2" in failures
    assert "export_ok 0 < 2" in failures
    assert "simulation_ok 0 < 2" in failures
    assert "auto_nest_runtime_s 1.750 > 1" in failures
    assert "auto_nest_placement_mismatch 1 > 0" in failures
    assert "auto_nest_exportable_missed 1 > 0" in failures
    assert "timed_out 1 > 0" in failures
    assert "validation_blocking code 'small_feature_below_kerf' present 2 time(s)" in failures
    assert "validation_warning code 'safe_travel' present 3 time(s)" in failures


def test_dxf_corpus_main_returns_nonzero_when_acceptance_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    json_path = tmp_path / "report.json"
    markdown_path = tmp_path / "report.md"

    rc = dxf_corpus_check.main(
        [
            str(PROJECT_ROOT / "examples"),
            "--max-files",
            "1",
            "--per-file-timeout",
            "5",
            "--output",
            str(json_path),
            "--markdown-output",
            str(markdown_path),
            "--min-export-ok",
            "99",
            "--max-timeouts",
            "0",
            "--quiet",
        ]
    )

    captured = capsys.readouterr()
    report = dxf_corpus_check.json.loads(json_path.read_text(encoding="utf-8"))

    assert rc == 1
    assert report["acceptance"]["ok"] is False
    assert "export_ok 1 < 99" in report["acceptance"]["failures"]
    assert report["acceptance"]["criteria"]["max_timeouts"] == 0
    assert "DXF corpus acceptance failed: export_ok 1 < 99" in captured.err
    assert "## Acceptance" in markdown_path.read_text(encoding="utf-8")
