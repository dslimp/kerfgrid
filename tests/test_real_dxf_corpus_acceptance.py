from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from tools.dxf_corpus_check import discover_dxf_files, run_corpus, validate_corpus_acceptance


REAL_CORPUS_ROOT = Path(os.environ.get("PLASMA_CAM_REAL_DXF_CORPUS_ROOT", "/Users/user/Documents/dxf"))


@pytest.mark.skipif(
    os.environ.get("PLASMA_CAM_RUN_REAL_DXF_CORPUS") != "1",
    reason="set PLASMA_CAM_RUN_REAL_DXF_CORPUS=1 to run the local real DXF corpus gate",
)
@pytest.mark.skipif(not REAL_CORPUS_ROOT.exists(), reason=f"real DXF corpus root not found: {REAL_CORPUS_ROOT}")
def test_real_dxf_corpus_warning_only_autonest_acceptance() -> None:
    paths = discover_dxf_files([REAL_CORPUS_ROOT])
    assert paths, f"no DXF files found under {REAL_CORPUS_ROOT}"

    report = run_corpus(
        paths,
        auto_close_gaps=True,
        auto_nest=True,
        auto_nest_timeout_s=float(os.environ.get("PLASMA_CAM_REAL_DXF_AUTO_NEST_TIMEOUT", "4")),
        centerline_fallback=True,
        open_path_centerline=True,
        unsafe_entity_policy=os.environ.get("PLASMA_CAM_REAL_DXF_UNSAFE_ENTITY_POLICY", "warn"),
        per_file_timeout_s=float(os.environ.get("PLASMA_CAM_REAL_DXF_PER_FILE_TIMEOUT", "30")),
        diagnostic_top_n=30,
        progress=bool(os.environ.get("PLASMA_CAM_REAL_DXF_PROGRESS")),
    )
    failures = validate_corpus_acceptance(
        report,
        require_complete=True,
        min_files=int(os.environ.get("PLASMA_CAM_REAL_DXF_MIN_FILES", "100")),
        min_completed_files=len(paths),
        min_import_ok=len(paths),
        min_auto_nest_ok=len(paths),
        max_auto_nest_runtime_s=float(os.environ.get("PLASMA_CAM_REAL_DXF_MAX_AUTO_NEST_RUNTIME", "4")),
        min_export_ok=len(paths),
        min_simulation_ok=len(paths),
        require_auto_nest_placements=True,
        require_auto_nest_for_exportable=True,
        max_timeouts=0,
        forbid_validation_blocking_codes=["import_open_contour", "small_feature_below_kerf"],
    )

    assert failures == []
