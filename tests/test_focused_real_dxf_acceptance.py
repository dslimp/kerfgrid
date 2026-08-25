from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from tools.dxf_corpus_check import run_corpus, validate_corpus_acceptance


FOCUSED_CORPUS_ROOT = Path(os.environ.get("PLASMA_CAM_REAL_DXF_CORPUS_ROOT", "/Users/user/Documents/dxf"))
FOCUSED_DXF_RELATIVE_PATHS = (
    "2/Malenkiy_mangal.dxf",
    "2/medved_kamin.dxf",
    "models/_extracted/mangal_bear/2mm_2.dxf",
    "models/_extracted/mangal_bear/4mm.dxf",
    "models/_extracted/Jedi__ornament5.1/Jedi  ornament5.1.dxf",
    "models/_extracted/Новая_папка/Новая папка/Kugeln novyj God.dxf",
    "models/_extracted/Новая_папка/Новая папка/Жирафы.dxf",
    "models/_extracted/Новая_папка/Новая папка/картина мишка в лесу.dxf",
)
HEAVY_REPAIR_DXF_RELATIVE_PATHS = (
    "models/Mangal_-_raskroy.dxf",
)


def focused_dxf_paths() -> list[Path]:
    return [FOCUSED_CORPUS_ROOT / relative for relative in FOCUSED_DXF_RELATIVE_PATHS]


def heavy_repair_dxf_paths() -> list[Path]:
    return [FOCUSED_CORPUS_ROOT / relative for relative in HEAVY_REPAIR_DXF_RELATIVE_PATHS]


@pytest.mark.skipif(
    os.environ.get("PLASMA_CAM_RUN_FOCUSED_DXF_CORPUS") != "1",
    reason="set PLASMA_CAM_RUN_FOCUSED_DXF_CORPUS=1 to run the focused local real DXF gate",
)
def test_focused_real_dxf_corpus_import_nest_export_simulate() -> None:
    paths = focused_dxf_paths()
    missing = [path for path in paths if not path.exists()]
    if missing:
        pytest.skip(f"focused DXF fixture(s) not found: {', '.join(str(path) for path in missing)}")

    report = run_corpus(
        paths,
        auto_close_gaps=True,
        auto_nest=True,
        auto_nest_timeout_s=float(os.environ.get("PLASMA_CAM_FOCUSED_DXF_AUTO_NEST_TIMEOUT", "2")),
        centerline_fallback=True,
        open_path_centerline=True,
        per_file_timeout_s=float(os.environ.get("PLASMA_CAM_FOCUSED_DXF_PER_FILE_TIMEOUT", "15")),
        diagnostic_top_n=20,
        progress=bool(os.environ.get("PLASMA_CAM_FOCUSED_DXF_PROGRESS")),
    )
    failures = validate_corpus_acceptance(
        report,
        require_complete=True,
        min_files=len(paths),
        min_completed_files=len(paths),
        min_import_ok=len(paths),
        min_auto_nest_ok=len(paths),
        max_auto_nest_runtime_s=float(os.environ.get("PLASMA_CAM_FOCUSED_DXF_MAX_AUTO_NEST_RUNTIME", "5")),
        min_export_ok=len(paths),
        min_simulation_ok=len(paths),
        require_auto_nest_for_exportable=True,
        max_timeouts=0,
        forbid_validation_blocking_codes=["import_open_contour", "small_feature_below_kerf"],
    )

    for entry in report["results"]:
        assert entry["auto_nest_placement_count"] == entry["placement_count"], entry["name"]
        assert "safe_travel" not in entry["validation_blocking_issue_codes"], entry["name"]
    assert failures == []


@pytest.mark.skipif(
    os.environ.get("PLASMA_CAM_RUN_FOCUSED_DXF_CORPUS") != "1",
    reason="set PLASMA_CAM_RUN_FOCUSED_DXF_CORPUS=1 to run the focused local real DXF gate",
)
def test_focused_heavy_real_dxf_import_reports_repair_blockers_without_timeout() -> None:
    paths = heavy_repair_dxf_paths()
    missing = [path for path in paths if not path.exists()]
    if missing:
        pytest.skip(f"heavy DXF fixture(s) not found: {', '.join(str(path) for path in missing)}")

    report = run_corpus(
        paths,
        auto_close_gaps=True,
        centerline_fallback=True,
        open_path_centerline=True,
        export=False,
        per_file_timeout_s=float(os.environ.get("PLASMA_CAM_FOCUSED_HEAVY_DXF_PER_FILE_TIMEOUT", "45")),
        diagnostic_top_n=20,
        progress=bool(os.environ.get("PLASMA_CAM_FOCUSED_DXF_PROGRESS")),
    )
    failures = validate_corpus_acceptance(
        report,
        require_complete=True,
        min_files=len(paths),
        min_completed_files=len(paths),
        min_import_ok=len(paths),
        max_timeouts=0,
    )

    assert failures == []
    for entry in report["results"]:
        assert entry["import_ok"] is True, entry["name"]
        assert entry["export_skipped"] is True, entry["name"]
        assert entry["simulation_skipped"] is True, entry["name"]
        assert entry.get("timed_out") is not True, entry["name"]
