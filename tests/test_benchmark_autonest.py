from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from tools.benchmark_autonest import run_benchmark


def test_autonest_benchmark_summary_shape_and_utilization() -> None:
    summary = run_benchmark(max_runtime_s=2.0, attempt_limit=3, angle_step_deg=90.0)

    assert [item["case"] for item in summary] == ["circles", "rectangles", "mixed"]
    for item in summary:
        assert set(item) >= {
            "case",
            "requested_count",
            "placed_count",
            "sheet_utilization_percent",
            "packing_utilization_percent",
            "runtime_ms",
            "attempt_count",
            "parallel_worker_count",
            "parallel_fallback_reason",
            "candidate_position_count",
            "nfp_candidate_count",
            "exact_clearance_check_count",
        }
        assert item["placed_count"] == item["requested_count"]
        assert item["sheet_utilization_percent"] > 0
        assert item["packing_utilization_percent"] > 0
        assert item["runtime_ms"] >= 0
        assert item["attempt_count"] >= 1
        assert item["successful_attempt_count"] >= 1
        assert item["candidate_position_count"] >= 0
        assert item["nfp_candidate_count"] >= 0
        assert item["exact_clearance_check_count"] >= 0


def test_autonest_benchmark_defaults_complete() -> None:
    summary = run_benchmark()

    assert [item["case"] for item in summary] == ["circles", "rectangles", "mixed"]
    assert all(item["placed_count"] == item["requested_count"] for item in summary)
