#!/usr/bin/env python3
"""Run import/export/simulation checks over a DXF corpus."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from plasma_cam.web_api import (
    _profile_from_part_json,
    _import_issue_items,
    auto_nest_project,
    export_project_gcode,
    import_dxf_project,
    simulation_from_gcode,
    simulation_from_project,
    validate_project,
)
from plasma_cam.project import PlacedPart, Placement

STAGE_TRACE_PREFIX = "DXF_CORPUS_STAGE "
STAGE_DURATION_FIELDS = (
    ("import", "import_runtime_s"),
    ("auto_nest", "auto_nest_runtime_s"),
    ("validation", "validation_runtime_s"),
    ("export", "export_runtime_s"),
    ("simulation", "simulation_runtime_s"),
)
ISSUE_EXAMPLE_LIMIT = 5
ENTRY_ISSUE_DETAIL_LIMIT = 12
ISSUE_SHEET_POINTS_MAX_BYTES = 5_000_000
ACCEPTANCE_SCOPE_KEYS = {
    "import_blocking": "import_blocking_issue_code_counts",
    "import_warning": "import_warning_issue_code_counts",
    "validation_blocking": "validation_blocking_issue_code_counts",
    "validation_warning": "validation_warning_issue_code_counts",
}


def discover_dxf_files(roots: Iterable[Path]) -> list[Path]:
    files: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        if root.is_file() and root.suffix.lower() == ".dxf":
            candidates = [root]
        elif root.is_dir():
            candidates = [path for path in root.rglob("*") if path.is_file() and path.suffix.lower() == ".dxf"]
        else:
            candidates = []
        for path in candidates:
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            files.append(resolved)
    return sorted(files, key=lambda item: str(item).casefold())


def run_corpus(
    paths: Iterable[Path],
    *,
    auto_close_gaps: bool = False,
    auto_nest: bool = False,
    auto_nest_timeout_s: float = 2.0,
    centerline_fallback: bool = False,
    open_path_centerline: bool = False,
    unsafe_entity_policy: str = "block",
    export: bool = True,
    max_files: int | None = None,
    per_file_timeout_s: float | None = None,
    diagnostic_top_n: int = 10,
    incremental_output: Path | None = None,
    incremental_markdown_output: Path | None = None,
    progress: bool = False,
) -> dict[str, Any]:
    started = time.monotonic()
    results = []
    selected_paths = list(paths)
    if max_files is not None:
        selected_paths = selected_paths[:max_files]
    total_files = len(selected_paths)
    for index, path in enumerate(selected_paths, start=1):
        if progress:
            print(f"[{index}/{total_files}] {path}", file=sys.stderr, flush=True)
        if per_file_timeout_s is None:
            results.append(
                check_dxf_file(
                    path,
                    auto_close_gaps=auto_close_gaps,
                    auto_nest=auto_nest,
                    auto_nest_timeout_s=auto_nest_timeout_s,
                    centerline_fallback=centerline_fallback,
                    open_path_centerline=open_path_centerline,
                    unsafe_entity_policy=unsafe_entity_policy,
                    export=export,
                )
            )
        else:
            results.append(
                check_dxf_file_subprocess(
                    path,
                    auto_close_gaps=auto_close_gaps,
                    auto_nest=auto_nest,
                    auto_nest_timeout_s=auto_nest_timeout_s,
                    centerline_fallback=centerline_fallback,
                    open_path_centerline=open_path_centerline,
                    unsafe_entity_policy=unsafe_entity_policy,
                    export=export,
                    timeout_s=per_file_timeout_s,
                )
            )
        if incremental_output is not None:
            partial = build_report(
                results,
                started=started,
                auto_close_gaps=auto_close_gaps,
                auto_nest=auto_nest,
                auto_nest_timeout_s=auto_nest_timeout_s,
                centerline_fallback=centerline_fallback,
                open_path_centerline=open_path_centerline,
                unsafe_entity_policy=unsafe_entity_policy,
                export=export,
                per_file_timeout_s=per_file_timeout_s,
                diagnostic_top_n=diagnostic_top_n,
                selected_files=total_files,
                complete=len(results) == total_files,
            )
            write_report_outputs(partial, incremental_output, incremental_markdown_output, diagnostic_top_n=diagnostic_top_n)
    return build_report(
        results,
        started=started,
        auto_close_gaps=auto_close_gaps,
        auto_nest=auto_nest,
        auto_nest_timeout_s=auto_nest_timeout_s,
        centerline_fallback=centerline_fallback,
        open_path_centerline=open_path_centerline,
        unsafe_entity_policy=unsafe_entity_policy,
        export=export,
        per_file_timeout_s=per_file_timeout_s,
        diagnostic_top_n=diagnostic_top_n,
        selected_files=total_files,
        complete=True,
    )


def build_report(
    results: list[dict[str, Any]],
    *,
    started: float,
    auto_close_gaps: bool,
    auto_nest: bool,
    auto_nest_timeout_s: float,
    centerline_fallback: bool,
    open_path_centerline: bool,
    unsafe_entity_policy: str,
    export: bool,
    per_file_timeout_s: float | None,
    diagnostic_top_n: int,
    selected_files: int,
    complete: bool,
) -> dict[str, Any]:
    counts: dict[str, int] = {
        "files": len(results),
        "import_ok": sum(1 for item in results if item["import_ok"]),
        "export_ok": sum(1 for item in results if item["export_ok"]),
        "simulation_ok": sum(1 for item in results if item["simulation_ok"]),
        "timed_out": sum(1 for item in results if item.get("timed_out")),
        "auto_nest_ok": sum(1 for item in results if item.get("auto_nest_ok")),
        "auto_nest_skipped": sum(1 for item in results if item.get("auto_nest_skipped")),
        "auto_nest_failed": sum(
            1
            for item in results
            if item["import_ok"] and auto_nest and not item.get("auto_nest_ok") and not item.get("auto_nest_skipped")
        ),
        "auto_nest_placement_mismatch": sum(1 for item in results if auto_nest_placement_mismatch(item)),
        "auto_nest_exportable_missed": sum(1 for item in results if auto_nest_exportable_missed(item)),
        "import_failed": sum(1 for item in results if not item["import_ok"]),
        "export_skipped": sum(1 for item in results if item.get("export_skipped")),
        "simulation_skipped": sum(1 for item in results if item.get("simulation_skipped")),
        "export_failed": sum(
            1
            for item in results
            if item["import_ok"] and not item["export_ok"] and not item.get("export_skipped")
        ),
        "simulation_failed": sum(
            1
            for item in results
            if item["import_ok"] and not item["simulation_ok"] and not item.get("simulation_skipped")
        ),
    }
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "runtime_s": round(time.monotonic() - started, 3),
        "complete": complete,
        "selected_files": selected_files,
        "completed_files": len(results),
        "auto_close_gaps": auto_close_gaps,
        "auto_nest": auto_nest,
        "auto_nest_timeout_s": auto_nest_timeout_s if auto_nest else None,
        "centerline_fallback": centerline_fallback,
        "open_path_centerline": open_path_centerline,
        "unsafe_entity_policy": unsafe_entity_policy,
        "export_enabled": export,
        "per_file_timeout_s": per_file_timeout_s,
        "counts": counts,
        "results": results,
    }
    diagnostics = build_diagnostics(results, top_n=diagnostic_top_n)
    report.update(report_diagnostic_summary(diagnostics))
    report["diagnostics"] = diagnostics
    return report


def report_diagnostic_summary(diagnostics: dict[str, Any]) -> dict[str, Any]:
    return {
        "max_auto_nest_runtime_s": diagnostics.get("max_auto_nest_runtime_s"),
        "blocking_file_count": diagnostics.get("blocking_file_count", 0),
        "auto_nest_placement_mismatch_count": diagnostics.get("auto_nest_placement_mismatch_count", 0),
        "auto_nest_placement_mismatches": diagnostics.get("auto_nest_placement_mismatches", []),
        "auto_nest_exportable_missed_count": diagnostics.get("auto_nest_exportable_missed_count", 0),
        "auto_nest_exportable_misses": diagnostics.get("auto_nest_exportable_misses", []),
        "timeout_count": len(diagnostics.get("timeouts", []) or []),
        "timeouts": diagnostics.get("timeouts", []),
    }


def check_dxf_file(
    path: Path,
    *,
    auto_close_gaps: bool = False,
    auto_nest: bool = False,
    auto_nest_timeout_s: float = 2.0,
    centerline_fallback: bool = False,
    open_path_centerline: bool = False,
    unsafe_entity_policy: str = "block",
    export: bool = True,
) -> dict[str, Any]:
    entry = initial_entry(path)
    try:
        set_stage(entry, "import")
        import_started = time.monotonic()
        content = path.read_text(encoding="utf-8", errors="replace")
        include_issue_sheet_points = path.stat().st_size <= ISSUE_SHEET_POINTS_MAX_BYTES
        project = import_dxf_project(
            {
                "filename": path.name,
                "content": content,
                "base_project": base_project(
                    centerline_fallback=centerline_fallback,
                    open_path_centerline=open_path_centerline,
                ),
                "import_options": {
                    "auto_close_gaps": auto_close_gaps,
                    "unsafe_entity_policy": unsafe_entity_policy,
                    "include_issue_sheet_points": include_issue_sheet_points,
                },
            }
        )
        project = fit_sheet_to_project(project)
        entry["import_runtime_s"] = round(time.monotonic() - import_started, 3)
        entry["import_ok"] = True
        import_info = project.get("import", {}) or {}
        import_issues = import_info.get("issues", []) or []
        entry["part_count"] = len(project.get("parts", []) or [])
        entry["placement_count"] = len(project.get("placements", []) or [])
        entry["contour_count"] = import_info.get("contour_count", 0)
        entry["import_safe_for_export"] = bool(import_info.get("safe_for_export", False))
        entry["import_issue_codes"] = sorted({str(issue.get("code", "unknown")) for issue in import_issues})
        entry["import_blocking_issue_codes"] = sorted(
            {str(issue.get("code", "unknown")) for issue in import_issues if issue.get("blocking", True) is not False}
        )
        entry["import_warning_issue_codes"] = sorted(
            {str(issue.get("code", "unknown")) for issue in import_issues if issue.get("blocking", True) is False}
        )
        entry["import_blocking_issues"] = compact_issues(
            [issue for issue in import_issues if issue.get("blocking", True) is not False]
        )
        entry["import_warning_issues"] = compact_issues(
            [issue for issue in import_issues if issue.get("blocking", True) is False]
        )
        entry["import_blocking_issue_count"] = int(import_info.get("blocking_issue_count", 0) or 0)
        policy_blocking_import_issues = _import_issue_items(project, blocking_only=True)
        entry["import_policy_safe_for_auto_nest"] = not bool(policy_blocking_import_issues)
        entry["import_policy_blocking_issue_count"] = len(policy_blocking_import_issues)
        if auto_nest and not entry["import_policy_safe_for_auto_nest"]:
            entry["auto_nest_ok"] = None
            entry["auto_nest_skipped"] = True
            entry["auto_nest_skip_reason"] = "import_not_safe_for_export"
        elif auto_nest:
            project = project_with_corpus_nesting_options(project, max_runtime_s=auto_nest_timeout_s)
            try:
                set_stage(entry, "auto_nest")
                auto_nest_started = time.monotonic()
                project = auto_nest_project(project)
                entry["auto_nest_runtime_s"] = round(time.monotonic() - auto_nest_started, 3)
                entry["auto_nest_ok"] = True
                entry["auto_nest_placement_count"] = len(project.get("placements", []) or [])
                entry["auto_nest_summary"] = compact_auto_nest_summary(project)
            except Exception as exc:
                entry["auto_nest_runtime_s"] = round(time.monotonic() - auto_nest_started, 3)
                entry["auto_nest_ok"] = False
                entry["auto_nest_error"] = error_dict(exc)
                entry["auto_nest_failed_stage"] = "auto_nest"
        set_stage(entry, "validation")
        validation_started = time.monotonic()
        validation = validate_project(project)
        entry["validation_runtime_s"] = round(time.monotonic() - validation_started, 3)
        entry["validation_issue_codes"] = sorted({str(issue.get("code", "unknown")) for issue in validation})
        entry["validation_blocking_issue_codes"] = sorted(
            {str(issue.get("code", "unknown")) for issue in validation if issue.get("blocking", True) is not False}
        )
        entry["validation_warning_issue_codes"] = sorted(
            {str(issue.get("code", "unknown")) for issue in validation if issue.get("blocking", True) is False}
        )
        entry["validation_blocking_issue_count"] = sum(1 for issue in validation if issue.get("blocking", True) is not False)
        entry["validation_blocking_issues"] = compact_issues(
            [issue for issue in validation if issue.get("blocking", True) is not False]
        )
        entry["validation_warning_issues"] = compact_issues(
            [issue for issue in validation if issue.get("blocking", True) is False]
        )
        if export:
            try:
                set_stage(entry, "export")
                export_started = time.monotonic()
                gcode = export_project_gcode(project, validation_issues=validation)
                entry["export_ok"] = True
                entry["export_runtime_s"] = round(time.monotonic() - export_started, 3)
                entry["gcode_line_count"] = len(gcode.splitlines())
            except Exception as exc:
                gcode = None
                entry["export_error"] = error_dict(exc)
                entry["export_failed_stage"] = "export"
            try:
                set_stage(entry, "simulation")
                simulation_started = time.monotonic()
                simulation = (
                    simulation_from_gcode(project, gcode)
                    if gcode is not None
                    else simulation_from_project(project)
                )
                entry["simulation_ok"] = True
                entry["simulation_runtime_s"] = round(time.monotonic() - simulation_started, 3)
                entry["simulation_segment_count"] = len(simulation.get("segments", []) or [])
                entry["estimated_total_s"] = simulation.get("estimated_total_s", 0)
            except Exception as exc:
                entry["simulation_error"] = error_dict(exc)
                entry["simulation_failed_stage"] = "simulation"
        else:
            entry["export_skipped"] = True
            entry["simulation_skipped"] = True
            entry["export_skip_reason"] = "import_only"
            entry["simulation_skip_reason"] = "import_only"
        set_stage(entry, "done")
    except Exception as exc:
        entry["import_error"] = error_dict(exc)
        entry["failed_stage"] = str(entry.get("stage") or "import")
    return entry


def check_dxf_file_subprocess(
    path: Path,
    *,
    auto_close_gaps: bool = False,
    auto_nest: bool = False,
    auto_nest_timeout_s: float = 2.0,
    centerline_fallback: bool = False,
    open_path_centerline: bool = False,
    unsafe_entity_policy: str = "block",
    export: bool = True,
    timeout_s: float = 20.0,
) -> dict[str, Any]:
    started = time.monotonic()
    command = [sys.executable, str(Path(__file__).resolve()), "--check-file", str(path), "--quiet"]
    if auto_close_gaps:
        command.append("--auto-close-gaps")
    if auto_nest:
        command.extend(["--auto-nest", "--auto-nest-timeout", str(auto_nest_timeout_s)])
    if centerline_fallback:
        command.append("--centerline-fallback")
    if open_path_centerline:
        command.append("--open-path-centerline")
    if unsafe_entity_policy != "block":
        command.extend(["--unsafe-entity-policy", unsafe_entity_policy])
    if not export:
        command.append("--import-only")
    env = os.environ.copy()
    env["DXF_CORPUS_STAGE_TRACE"] = "1"
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout_s, check=False, env=env)
    except subprocess.TimeoutExpired as exc:
        entry = initial_entry(path)
        stdout = text_tail(exc.stdout)
        stderr = text_tail(exc.stderr)
        timeout_stage = latest_traced_stage(stderr) or "unknown"
        apply_timeout_stage_state(entry, timeout_stage, auto_nest=auto_nest)
        entry["timed_out"] = True
        entry["timeout_s"] = timeout_s
        entry["runtime_s"] = round(time.monotonic() - started, 3)
        entry["stage"] = timeout_stage
        entry["timeout_stage"] = timeout_stage
        entry["failed_stage"] = timeout_stage
        entry["timeout_error"] = {
            "type": "TimeoutExpired",
            "message": f"DXF corpus check exceeded {timeout_s:g} s during {timeout_stage}",
        }
        entry[f"{timeout_stage}_error" if timeout_stage in {"import", "auto_nest", "validation", "export", "simulation"} else "import_error"] = {
            "type": "TimeoutExpired",
            "message": f"DXF corpus check exceeded {timeout_s:g} s during {timeout_stage}",
        }
        if stdout:
            entry["stdout"] = stdout
        if stderr:
            entry["stderr"] = stderr
        return entry
    if completed.returncode != 0:
        entry = initial_entry(path)
        entry["runtime_s"] = round(time.monotonic() - started, 3)
        entry["import_error"] = {
            "type": "CorpusWorkerError",
            "message": f"worker exited with {completed.returncode}",
        }
        if completed.stdout:
            entry["stdout"] = completed.stdout[-1000:]
        if completed.stderr:
            entry["stderr"] = completed.stderr[-1000:]
        return entry
    try:
        entry = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        entry = initial_entry(path)
        entry["runtime_s"] = round(time.monotonic() - started, 3)
        entry["import_error"] = {
            "type": "JSONDecodeError",
            "message": str(exc),
        }
        entry["stdout"] = completed.stdout[-1000:]
        entry["stderr"] = completed.stderr[-1000:]
        return entry
    entry["runtime_s"] = round(time.monotonic() - started, 3)
    return entry


def apply_timeout_stage_state(entry: dict[str, Any], timeout_stage: str, *, auto_nest: bool) -> None:
    if timeout_stage in {"auto_nest", "validation", "export", "simulation", "done"}:
        entry["import_ok"] = True
    if auto_nest and timeout_stage in {"validation", "export", "simulation", "done"}:
        entry["auto_nest_ok"] = True
    elif auto_nest and timeout_stage == "auto_nest":
        entry["auto_nest_ok"] = False
    if timeout_stage in {"simulation", "done"}:
        entry["export_ok"] = True
    if timeout_stage == "done":
        entry["simulation_ok"] = True


def initial_entry(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "name": path.name,
        "size_bytes": path.stat().st_size if path.exists() else 0,
        "import_ok": False,
        "export_ok": False,
        "simulation_ok": False,
        "import_issue_codes": [],
        "validation_issue_codes": [],
        "stage": "pending",
    }


def compact_issues(issues: list[dict[str, Any]], *, limit: int = ENTRY_ISSUE_DETAIL_LIMIT) -> list[dict[str, Any]]:
    output = [compact_issue(issue) for issue in issues[:limit]]
    omitted = len(issues) - len(output)
    if omitted > 0:
        output.append({"code": "_omitted", "message": f"{omitted} additional issue(s) omitted"})
    return output


def compact_issue(issue: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "code",
        "message",
        "entity_type",
        "x",
        "y",
        "target_x",
        "target_y",
        "gap_mm",
        "chain_length_mm",
        "layer",
        "process",
        "blocking",
        "instance_id",
        "sheet_x",
        "sheet_y",
        "target_sheet_x",
        "target_sheet_y",
    )
    return {key: issue[key] for key in keys if key in issue and issue[key] is not None}


def compact_auto_nest_summary(project: dict[str, Any]) -> dict[str, Any]:
    nesting = project.get("nesting", {}) or {}
    summary = nesting.get("last_result", {}) or {}
    keys = (
        "attempt_count",
        "successful_attempt_count",
        "best_attempt",
        "geometry_engine",
        "runtime_ms",
        "parallel_worker_count",
        "attempts_per_second",
        "candidate_position_count",
        "nfp_candidate_count",
        "exact_clearance_check_count",
        "spatial_index_query_count",
        "spatial_index_fallback_count",
        "cache_hit_count",
        "cache_miss_count",
        "used_width_mm",
        "used_height_mm",
        "top_free_height_mm",
        "packing_utilization_percent",
        "bbox_utilization_percent",
        "sheet_utilization_percent",
        "hole_filler_relocation_count",
        "time_limited",
        "parallel_fallback_reason",
        "bbox_fallback_count",
        "current_layout_fallback",
        "complexity_fallback",
        "complexity_fallback_reason",
        "complexity_instance_count",
        "complexity_contour_count",
        "lead_spacing_fallback",
        "lead_spacing_fallback_skipped",
        "auto_lead_override_count",
        "auto_lead_override_skipped",
    )
    return {key: summary[key] for key in keys if key in summary and summary[key] is not None}


def set_stage(entry: dict[str, Any], stage: str) -> None:
    entry["stage"] = stage
    if os.environ.get("DXF_CORPUS_STAGE_TRACE"):
        print(f"{STAGE_TRACE_PREFIX}{stage}", file=sys.stderr, flush=True)


def text_tail(value: Any, *, limit: int = 1000) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    else:
        text = str(value)
    return text[-limit:]


def latest_traced_stage(stderr: str) -> str | None:
    latest = None
    for line in stderr.splitlines():
        if line.startswith(STAGE_TRACE_PREFIX):
            latest = line[len(STAGE_TRACE_PREFIX) :].strip()
    return latest or None


def build_diagnostics(results: list[dict[str, Any]], *, top_n: int = 10) -> dict[str, Any]:
    failure_stage_counts: Counter[str] = Counter()
    error_type_counts: Counter[str] = Counter()
    import_issue_code_counts: Counter[str] = Counter()
    import_blocking_issue_code_counts: Counter[str] = Counter()
    import_warning_issue_code_counts: Counter[str] = Counter()
    validation_issue_code_counts: Counter[str] = Counter()
    validation_blocking_issue_code_counts: Counter[str] = Counter()
    validation_warning_issue_code_counts: Counter[str] = Counter()
    issue_code_counts: Counter[str] = Counter()
    issue_examples: dict[str, defaultdict[str, list[dict[str, Any]]]] = {
        "validation_blocking": defaultdict(list),
        "validation_warning": defaultdict(list),
        "import_blocking": defaultdict(list),
        "import_warning": defaultdict(list),
    }
    timeouts = []

    for entry in results:
        stage = failure_stage(entry)
        if stage != "ok":
            failure_stage_counts[stage] += 1
        for key, value in entry.items():
            if key.endswith("_error") and isinstance(value, dict):
                error_type_counts[str(value.get("type", "unknown"))] += 1
        for code in entry.get("import_issue_codes", []) or []:
            normalized_code = str(code)
            import_issue_code_counts[normalized_code] += 1
            issue_code_counts[normalized_code] += 1
        for code in entry.get("import_blocking_issue_codes", []) or []:
            import_blocking_issue_code_counts[str(code)] += 1
        record_issue_examples(issue_examples["import_blocking"], entry.get("import_blocking_issue_codes", []) or [], entry)
        for code in entry.get("import_warning_issue_codes", []) or []:
            import_warning_issue_code_counts[str(code)] += 1
        record_issue_examples(issue_examples["import_warning"], entry.get("import_warning_issue_codes", []) or [], entry)
        for code in entry.get("validation_issue_codes", []) or []:
            normalized_code = str(code)
            validation_issue_code_counts[normalized_code] += 1
            issue_code_counts[normalized_code] += 1
        for code in entry.get("validation_blocking_issue_codes", []) or []:
            validation_blocking_issue_code_counts[str(code)] += 1
        record_issue_examples(issue_examples["validation_blocking"], entry.get("validation_blocking_issue_codes", []) or [], entry)
        for code in entry.get("validation_warning_issue_codes", []) or []:
            validation_warning_issue_code_counts[str(code)] += 1
        record_issue_examples(issue_examples["validation_warning"], entry.get("validation_warning_issue_codes", []) or [], entry)
        if entry.get("timed_out"):
            timeouts.append(timeout_diagnostic(entry))

    blocking_file_items = blocking_files(results, top_n=max(top_n, len(results)))
    auto_nest_mismatch_count = sum(1 for entry in results if auto_nest_placement_mismatch(entry))
    auto_nest_mismatches = auto_nest_placement_mismatches(results, top_n=top_n)
    auto_nest_exportable_missed_count = sum(1 for entry in results if auto_nest_exportable_missed(entry))
    auto_nest_exportable_misses = auto_nest_exportable_misses_for(results, top_n=top_n)
    return {
        "top_slow_files": top_slow_files(results, top_n=top_n),
        "top_slow_stages": top_slow_stages(results, top_n=top_n),
        "max_auto_nest_runtime_s": max_entry_runtime(results, "auto_nest_runtime_s"),
        "blocking_file_count": len(blocking_file_items),
        "blocking_files": blocking_file_items[:top_n],
        "auto_nest_placement_mismatch_count": auto_nest_mismatch_count,
        "auto_nest_placement_mismatches": auto_nest_mismatches,
        "auto_nest_exportable_missed_count": auto_nest_exportable_missed_count,
        "auto_nest_exportable_misses": auto_nest_exportable_misses,
        "timeouts": timeouts,
        "failure_stage_counts": dict(sorted(failure_stage_counts.items())),
        "error_type_counts": dict(sorted(error_type_counts.items())),
        "import_issue_code_counts": dict(import_issue_code_counts.most_common(top_n)),
        "import_blocking_issue_code_counts": dict(import_blocking_issue_code_counts.most_common(top_n)),
        "import_warning_issue_code_counts": dict(import_warning_issue_code_counts.most_common(top_n)),
        "validation_issue_code_counts": dict(validation_issue_code_counts.most_common(top_n)),
        "validation_blocking_issue_code_counts": dict(validation_blocking_issue_code_counts.most_common(top_n)),
        "validation_warning_issue_code_counts": dict(validation_warning_issue_code_counts.most_common(top_n)),
        "issue_code_counts": dict(issue_code_counts.most_common(top_n)),
        "issue_examples": issue_examples_to_dict(issue_examples),
    }


def record_issue_examples(
    examples_by_code: defaultdict[str, list[dict[str, Any]]],
    codes: list[str],
    entry: dict[str, Any],
) -> None:
    for code in codes:
        normalized_code = str(code)
        examples = examples_by_code[normalized_code]
        if len(examples) < ISSUE_EXAMPLE_LIMIT:
            examples.append(issue_example(entry))


def issue_example(entry: dict[str, Any]) -> dict[str, Any]:
    example: dict[str, Any] = {
        "name": entry.get("name"),
        "path": entry.get("path"),
        "failure_stage": failure_stage(entry),
        "stage": entry.get("stage"),
        "runtime_s": entry.get("runtime_s"),
    }
    import_blocking = list(entry.get("import_blocking_issue_codes", []) or [])
    validation_blocking = list(entry.get("validation_blocking_issue_codes", []) or [])
    if import_blocking:
        example["import_blocking_issue_codes"] = import_blocking
    if validation_blocking:
        example["validation_blocking_issue_codes"] = validation_blocking
    errors = error_types_for(entry)
    if errors:
        example["error_types"] = errors
    message = first_error_message(entry)
    if message:
        example["error_message"] = message
    return example


def first_error_message(entry: dict[str, Any]) -> str:
    for key in ("import_error", "auto_nest_error", "export_error", "simulation_error", "timeout_error"):
        value = entry.get(key)
        if isinstance(value, dict) and value.get("message"):
            return str(value["message"])
    return ""


def issue_examples_to_dict(
    issue_examples: dict[str, defaultdict[str, list[dict[str, Any]]]],
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    return {
        scope: {code: examples for code, examples in sorted(examples_by_code.items())}
        for scope, examples_by_code in issue_examples.items()
        if examples_by_code
    }


def max_entry_runtime(results: list[dict[str, Any]], key: str) -> float | None:
    values = [
        float(value)
        for entry in results
        if isinstance((value := entry.get(key)), int | float)
    ]
    return max(values) if values else None


def failure_stage(entry: dict[str, Any]) -> str:
    if entry.get("timed_out"):
        return str(entry.get("timeout_stage") or entry.get("stage") or "timeout")
    if not entry.get("import_ok"):
        return "import"
    if entry.get("auto_nest_ok") is False:
        return "auto_nest"
    if int(entry.get("validation_blocking_issue_count", 0) or 0) > 0:
        return "validation"
    if not entry.get("export_ok") and not entry.get("export_skipped"):
        return "export"
    if not entry.get("simulation_ok") and not entry.get("simulation_skipped"):
        return "simulation"
    return "ok"


def blocking_files(results: list[dict[str, Any]], *, top_n: int = 10) -> list[dict[str, Any]]:
    blocked = []
    for entry in results:
        stage = failure_stage(entry)
        import_codes = sorted({str(code) for code in (entry.get("import_blocking_issue_codes", []) or [])})
        validation_codes = sorted({str(code) for code in (entry.get("validation_blocking_issue_codes", []) or [])})
        if stage == "ok" and not validation_codes:
            continue
        if not import_codes and not validation_codes and stage == "validation":
            continue
        blocked.append(
            {
                "name": entry.get("name"),
                "path": entry.get("path"),
                "failure_stage": stage,
                "import_blocking_issue_codes": import_codes,
                "validation_blocking_issue_codes": validation_codes,
                "runtime_s": entry.get("runtime_s"),
                "error_message": first_error_message(entry),
            }
        )
    return sorted(
        blocked,
        key=lambda item: (
            str(item.get("failure_stage") or ""),
            str(item.get("path") or item.get("name") or "").casefold(),
        ),
    )[:top_n]


def auto_nest_placement_mismatch(entry: dict[str, Any]) -> bool:
    if entry.get("auto_nest_ok") is not True:
        return False
    before = entry.get("placement_count")
    after = entry.get("auto_nest_placement_count")
    return isinstance(before, int) and isinstance(after, int) and before != after


def auto_nest_placement_mismatches(results: list[dict[str, Any]], *, top_n: int = 10) -> list[dict[str, Any]]:
    mismatches = []
    for entry in results:
        if not auto_nest_placement_mismatch(entry):
            continue
        mismatches.append(
            {
                "name": entry.get("name"),
                "path": entry.get("path"),
                "placement_count": entry.get("placement_count"),
                "auto_nest_placement_count": entry.get("auto_nest_placement_count"),
                "runtime_s": entry.get("runtime_s"),
            }
        )
    return sorted(mismatches, key=lambda item: str(item.get("path") or item.get("name") or "").casefold())[:top_n]


def auto_nest_exportable_missed(entry: dict[str, Any]) -> bool:
    if not any(key in entry for key in ("auto_nest_ok", "auto_nest_skipped", "auto_nest_error", "auto_nest_runtime_s")):
        return False
    exportable = entry.get("import_policy_safe_for_auto_nest")
    if exportable is None:
        exportable = entry.get("import_safe_for_export")
    return bool(exportable) and entry.get("auto_nest_ok") is not True


def auto_nest_exportable_misses_for(results: list[dict[str, Any]], *, top_n: int = 10) -> list[dict[str, Any]]:
    misses = []
    for entry in results:
        if not auto_nest_exportable_missed(entry):
            continue
        misses.append(
            {
                "name": entry.get("name"),
                "path": entry.get("path"),
                "auto_nest_ok": entry.get("auto_nest_ok"),
                "auto_nest_skipped": entry.get("auto_nest_skipped"),
                "auto_nest_skip_reason": entry.get("auto_nest_skip_reason"),
                "error_message": first_error_message(entry),
                "runtime_s": entry.get("runtime_s"),
            }
        )
    return sorted(misses, key=lambda item: str(item.get("path") or item.get("name") or "").casefold())[:top_n]


def top_slow_files(results: list[dict[str, Any]], *, top_n: int = 10) -> list[dict[str, Any]]:
    ordered = sorted(results, key=lambda entry: float(entry.get("runtime_s", 0.0) or 0.0), reverse=True)
    return [file_diagnostic(entry) for entry in ordered[:top_n]]


def file_diagnostic(entry: dict[str, Any]) -> dict[str, Any]:
    stage_runtimes = stage_runtimes_for(entry)
    slowest_stage = max(stage_runtimes.items(), key=lambda item: item[1])[0] if stage_runtimes else None
    diagnostic: dict[str, Any] = {
        "name": entry.get("name"),
        "path": entry.get("path"),
        "runtime_s": entry.get("runtime_s"),
        "stage": entry.get("stage"),
        "failure_stage": failure_stage(entry),
        "timed_out": bool(entry.get("timed_out", False)),
        "stage_runtimes_s": stage_runtimes,
        "error_types": error_types_for(entry),
    }
    if slowest_stage:
        diagnostic["slowest_stage"] = slowest_stage
        diagnostic["slowest_stage_runtime_s"] = stage_runtimes[slowest_stage]
    if entry.get("timeout_stage"):
        diagnostic["timeout_stage"] = entry.get("timeout_stage")
    return diagnostic


def top_slow_stages(results: list[dict[str, Any]], *, top_n: int = 10) -> list[dict[str, Any]]:
    stages = []
    for entry in results:
        for stage, runtime_s in stage_runtimes_for(entry).items():
            stages.append(
                {
                    "name": entry.get("name"),
                    "path": entry.get("path"),
                    "stage": stage,
                    "runtime_s": runtime_s,
                    "failure_stage": failure_stage(entry),
                }
            )
    return sorted(stages, key=lambda item: float(item["runtime_s"]), reverse=True)[:top_n]


def timeout_diagnostic(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": entry.get("name"),
        "path": entry.get("path"),
        "runtime_s": entry.get("runtime_s"),
        "timeout_s": entry.get("timeout_s"),
        "timeout_stage": entry.get("timeout_stage") or entry.get("stage"),
        "error": entry.get("timeout_error") or entry.get("import_error"),
    }


def stage_runtimes_for(entry: dict[str, Any]) -> dict[str, float]:
    runtimes = {}
    for stage, key in STAGE_DURATION_FIELDS:
        value = entry.get(key)
        if isinstance(value, int | float):
            runtimes[stage] = float(value)
    return runtimes


def error_types_for(entry: dict[str, Any]) -> list[str]:
    error_types = []
    for key, value in entry.items():
        if key.endswith("_error") and isinstance(value, dict):
            error_types.append(str(value.get("type", "unknown")))
    return sorted(set(error_types))


def render_markdown_report(report: dict[str, Any], *, top_n: int = 10) -> str:
    diagnostics = report.get("diagnostics", {}) or {}
    counts = report.get("counts", {}) or {}
    lines = [
        "# DXF Corpus Report",
        "",
        f"- Generated: {report.get('generated_at', '-')}",
        f"- Runtime: {format_seconds(report.get('runtime_s'))}",
        f"- Files: {counts.get('files', 0)}",
        f"- Completed: {report.get('completed_files', counts.get('files', 0))} / {report.get('selected_files', counts.get('files', 0))}",
        f"- Complete: {str(bool(report.get('complete', True))).lower()}",
        f"- Import ok: {counts.get('import_ok', 0)}",
        f"- Export enabled: {str(bool(report.get('export_enabled', True))).lower()}",
        f"- Export ok: {counts.get('export_ok', 0)}",
        f"- Export skipped: {counts.get('export_skipped', 0)}",
        f"- Simulation ok: {counts.get('simulation_ok', 0)}",
        f"- Simulation skipped: {counts.get('simulation_skipped', 0)}",
        f"- Timed out: {counts.get('timed_out', 0)}",
        "",
        "## Acceptance",
        "",
    ]
    acceptance = report.get("acceptance")
    if isinstance(acceptance, dict):
        lines.append(f"- OK: {str(bool(acceptance.get('ok'))).lower()}")
        failures = acceptance.get("failures", []) or []
        if failures:
            lines.extend(["", *[f"- {failure}" for failure in failures]])
    else:
        lines.append("No acceptance criteria configured.")
    lines.extend([
        "",
        "## Failure Stages",
        "",
    ])
    failure_stage_counts = diagnostics.get("failure_stage_counts", {}) or {}
    if failure_stage_counts:
        lines.extend(markdown_table(["stage", "count"], [[stage, count] for stage, count in failure_stage_counts.items()]))
    else:
        lines.append("No failures.")
    lines.extend(["", "## Issue Codes", ""])
    scoped_issue_rows = []
    for scope, counts_by_code in (
        ("validation blocking", diagnostics.get("validation_blocking_issue_code_counts", {}) or {}),
        ("validation warning", diagnostics.get("validation_warning_issue_code_counts", {}) or {}),
        ("import review", diagnostics.get("import_blocking_issue_code_counts", {}) or {}),
        ("import warning", diagnostics.get("import_warning_issue_code_counts", {}) or {}),
    ):
        scoped_issue_rows.extend([[scope, code, count] for code, count in counts_by_code.items()])
    if scoped_issue_rows:
        lines.extend(markdown_table(["scope", "code", "count"], scoped_issue_rows))
    else:
        for scope, counts_by_code in (
            ("validation", diagnostics.get("validation_issue_code_counts", {}) or {}),
            ("import", diagnostics.get("import_issue_code_counts", {}) or {}),
        ):
            scoped_issue_rows.extend([[scope, code, count] for code, count in counts_by_code.items()])
        if scoped_issue_rows:
            lines.extend(markdown_table(["scope", "code", "count"], scoped_issue_rows))
        elif diagnostics.get("issue_code_counts", {}):
            lines.extend(markdown_table(["code", "count"], [[code, count] for code, count in diagnostics["issue_code_counts"].items()]))
        else:
            lines.append("No issue codes.")
    lines.extend(["", "## Issue Examples", ""])
    issue_example_rows = []
    for scope, examples_by_code in (diagnostics.get("issue_examples", {}) or {}).items():
        for code, examples in (examples_by_code or {}).items():
            for example in examples[:ISSUE_EXAMPLE_LIMIT]:
                issue_example_rows.append(
                    [
                        markdown_scope_label(scope),
                        code,
                        example.get("name", "-"),
                        example.get("failure_stage", "-"),
                        ", ".join(example.get("error_types", []) or []) or "-",
                    ]
                )
    if issue_example_rows:
        lines.extend(markdown_table(["scope", "code", "file", "failure", "errors"], issue_example_rows))
    else:
        lines.append("No issue examples.")
    lines.extend(["", "## Blocking Files", ""])
    blocking_rows = []
    for item in (diagnostics.get("blocking_files", []) or [])[:top_n]:
        blocking_rows.append(
            [
                item.get("name", "-"),
                item.get("failure_stage", "-"),
                ", ".join(item.get("import_blocking_issue_codes", []) or []) or "-",
                ", ".join(item.get("validation_blocking_issue_codes", []) or []) or "-",
            ]
        )
    if blocking_rows:
        total_blocking = int(diagnostics.get("blocking_file_count", len(blocking_rows)) or 0)
        if total_blocking > len(blocking_rows):
            lines.append(f"Showing {len(blocking_rows)} of {total_blocking} blocking files.")
            lines.append("")
        lines.extend(markdown_table(["file", "failure", "import review", "validation blocking"], blocking_rows))
    else:
        lines.append("No blocking files.")
    if report.get("auto_nest"):
        lines.extend(["", "## Auto Nest", ""])
        auto_rows = [
            ["auto_nest_ok", counts.get("auto_nest_ok", 0)],
            ["auto_nest_skipped", counts.get("auto_nest_skipped", 0)],
            ["auto_nest_failed", counts.get("auto_nest_failed", 0)],
            ["placement_mismatch", counts.get("auto_nest_placement_mismatch", 0)],
            ["exportable_missed", counts.get("auto_nest_exportable_missed", 0)],
            ["max_auto_nest_runtime", format_seconds(max_stage_runtime(report, "auto_nest_runtime_s"))],
        ]
        lines.extend(markdown_table(["metric", "value"], auto_rows))
        exportable_misses = diagnostics.get("auto_nest_exportable_misses", []) or []
        if exportable_misses:
            lines.extend(["", "### Exportable Auto Nest Misses", ""])
            lines.extend(
                markdown_table(
                    ["file", "skip", "error"],
                    [
                        [
                            item.get("name", "-"),
                            item.get("auto_nest_skip_reason") or "-",
                            item.get("error_message") or "-",
                        ]
                        for item in exportable_misses[:top_n]
                    ],
                )
            )
        mismatches = diagnostics.get("auto_nest_placement_mismatches", []) or []
        if mismatches:
            lines.extend(["", "### Placement Mismatches", ""])
            lines.extend(
                markdown_table(
                    ["file", "before", "after"],
                    [
                        [
                            item.get("name", "-"),
                            item.get("placement_count", "-"),
                            item.get("auto_nest_placement_count", "-"),
                        ]
                        for item in mismatches[:top_n]
                    ],
                )
            )
    lines.extend(["", "## Top Slow Files", ""])
    lines.extend(
        markdown_table(
            ["file", "runtime", "slowest stage", "failure", "errors"],
            [
                [
                    item.get("name", "-"),
                    format_seconds(item.get("runtime_s")),
                    slowest_stage_text(item),
                    item.get("failure_stage", "-"),
                    ", ".join(item.get("error_types", []) or []) or "-",
                ]
                for item in (diagnostics.get("top_slow_files", []) or [])[:top_n]
            ],
        )
    )
    lines.extend(["", "## Top Slow Stages", ""])
    lines.extend(
        markdown_table(
            ["file", "stage", "runtime", "failure"],
            [
                [
                    item.get("name", "-"),
                    item.get("stage", "-"),
                    format_seconds(item.get("runtime_s")),
                    item.get("failure_stage", "-"),
                ]
                for item in (diagnostics.get("top_slow_stages", []) or [])[:top_n]
            ],
        )
    )
    lines.extend(["", "## Timeouts", ""])
    timeouts = diagnostics.get("timeouts", []) or []
    if timeouts:
        lines.extend(
            markdown_table(
                ["file", "stage", "runtime", "timeout"],
                [
                    [
                        item.get("name", "-"),
                        item.get("timeout_stage", "-"),
                        format_seconds(item.get("runtime_s")),
                        format_seconds(item.get("timeout_s")),
                    ]
                    for item in timeouts[:top_n]
                ],
            )
        )
    else:
        lines.append("No timeouts.")
    return "\n".join(lines).rstrip() + "\n"


def write_report_outputs(
    report: dict[str, Any],
    output: Path | None,
    markdown_output: Path | None,
    *,
    diagnostic_top_n: int,
    indent: int = 2,
) -> str:
    text = json.dumps(report, ensure_ascii=False, indent=indent, sort_keys=True)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    if markdown_output:
        markdown_output.parent.mkdir(parents=True, exist_ok=True)
        markdown_output.write_text(render_markdown_report(report, top_n=diagnostic_top_n), encoding="utf-8")
    return text


def validate_corpus_acceptance(
    report: dict[str, Any],
    *,
    require_complete: bool = False,
    min_files: int | None = None,
    min_completed_files: int | None = None,
    min_import_ok: int | None = None,
    min_auto_nest_ok: int | None = None,
    min_export_ok: int | None = None,
    min_simulation_ok: int | None = None,
    max_auto_nest_runtime_s: float | None = None,
    require_auto_nest_placements: bool = False,
    require_auto_nest_for_exportable: bool = False,
    max_timeouts: int | None = None,
    forbid_import_blocking_codes: Iterable[str] = (),
    forbid_import_warning_codes: Iterable[str] = (),
    forbid_validation_blocking_codes: Iterable[str] = (),
    forbid_validation_warning_codes: Iterable[str] = (),
) -> list[str]:
    counts = report.get("counts", {}) or {}
    failures: list[str] = []
    if require_complete and not bool(report.get("complete", True)):
        failures.append("report is incomplete")
    check_minimum(failures, "files", counts.get("files", 0), min_files)
    check_minimum(failures, "completed_files", report.get("completed_files", 0), min_completed_files)
    check_minimum(failures, "import_ok", counts.get("import_ok", 0), min_import_ok)
    check_minimum(failures, "auto_nest_ok", counts.get("auto_nest_ok", 0), min_auto_nest_ok)
    check_minimum(failures, "export_ok", counts.get("export_ok", 0), min_export_ok)
    check_minimum(failures, "simulation_ok", counts.get("simulation_ok", 0), min_simulation_ok)
    check_maximum_float(failures, "auto_nest_runtime_s", max_stage_runtime(report, "auto_nest_runtime_s"), max_auto_nest_runtime_s)
    if require_auto_nest_placements:
        check_maximum(failures, "auto_nest_placement_mismatch", counts.get("auto_nest_placement_mismatch", 0), 0)
    if require_auto_nest_for_exportable:
        check_maximum(failures, "auto_nest_exportable_missed", counts.get("auto_nest_exportable_missed", 0), 0)
    check_maximum(failures, "timed_out", counts.get("timed_out", 0), max_timeouts)
    diagnostics = report.get("diagnostics", {}) or {}
    forbidden_by_scope = {
        "import_blocking": forbid_import_blocking_codes,
        "import_warning": forbid_import_warning_codes,
        "validation_blocking": forbid_validation_blocking_codes,
        "validation_warning": forbid_validation_warning_codes,
    }
    for scope, codes in forbidden_by_scope.items():
        counts_by_code = diagnostics.get(ACCEPTANCE_SCOPE_KEYS[scope], {}) or {}
        for code in sorted({str(item) for item in codes if str(item)}):
            count = int(counts_by_code.get(code, 0) or 0)
            if count > 0:
                failures.append(f"{scope} code {code!r} present {count} time(s)")
    return failures


def check_minimum(failures: list[str], name: str, actual: Any, expected: int | None) -> None:
    if expected is None:
        return
    actual_int = int(actual or 0)
    if actual_int < expected:
        failures.append(f"{name} {actual_int} < {expected}")


def check_maximum(failures: list[str], name: str, actual: Any, expected: int | None) -> None:
    if expected is None:
        return
    actual_int = int(actual or 0)
    if actual_int > expected:
        failures.append(f"{name} {actual_int} > {expected}")


def check_maximum_float(failures: list[str], name: str, actual: float | None, expected: float | None) -> None:
    if expected is None or actual is None:
        return
    if actual > expected:
        failures.append(f"{name} {actual:.3f} > {expected:g}")


def max_stage_runtime(report: dict[str, Any], key: str) -> float | None:
    values = [
        float(value)
        for item in report.get("results", []) or []
        if isinstance((value := item.get(key)), int | float)
    ]
    return max(values) if values else None


def acceptance_criteria_from_args(args: argparse.Namespace) -> dict[str, Any]:
    criteria = {
        "require_complete": bool(args.require_complete),
        "min_files": args.min_files,
        "min_completed_files": args.min_completed_files,
        "min_import_ok": args.min_import_ok,
        "min_auto_nest_ok": args.min_auto_nest_ok,
        "min_export_ok": args.min_export_ok,
        "min_simulation_ok": args.min_simulation_ok,
        "max_auto_nest_runtime_s": args.max_auto_nest_runtime,
        "require_auto_nest_placements": bool(args.require_auto_nest_placements),
        "require_auto_nest_for_exportable": bool(args.require_auto_nest_for_exportable),
        "max_timeouts": args.max_timeouts,
        "forbid_import_blocking_codes": args.forbid_import_blocking_code,
        "forbid_import_warning_codes": args.forbid_import_warning_code,
        "forbid_validation_blocking_codes": args.forbid_validation_blocking_code,
        "forbid_validation_warning_codes": args.forbid_validation_warning_code,
    }
    return {key: value for key, value in criteria.items() if acceptance_criterion_is_set(value)}


def acceptance_criterion_is_set(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, list):
        return bool(value)
    return True


def add_acceptance_result(report: dict[str, Any], criteria: dict[str, Any]) -> list[str]:
    if not criteria:
        return []
    failures = validate_corpus_acceptance(report, **criteria)
    report["acceptance"] = {
        "ok": not failures,
        "criteria": criteria,
        "failures": failures,
    }
    return failures


def markdown_table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    if not rows:
        return ["No entries."]
    lines = [
        "| " + " | ".join(markdown_cell(header) for header in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(markdown_cell(cell) for cell in row) + " |")
    return lines


def markdown_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def markdown_scope_label(scope: str) -> str:
    if scope == "import_blocking":
        return "import review"
    return scope.replace("_", " ")


def format_seconds(value: Any) -> str:
    if isinstance(value, int | float):
        return f"{float(value):.3f}s"
    return "-"


def slowest_stage_text(item: dict[str, Any]) -> str:
    stage = item.get("slowest_stage")
    runtime_s = item.get("slowest_stage_runtime_s")
    if not stage:
        return item.get("timeout_stage") or item.get("stage") or "-"
    return f"{stage} {format_seconds(runtime_s)}"


def base_project(*, centerline_fallback: bool = False, open_path_centerline: bool = False) -> dict[str, Any]:
    project = {
        "name": "dxf-corpus",
        "sheet": {"width_mm": 5000, "height_mm": 3000, "margin_mm": 10},
        "spacing_mm": 8,
        "cut": {"material": "mild_steel", "thickness_mm": 3, "nozzle_mm": 0.9, "feed_rate_mode": "auto"},
        "post": {
            "lead_in_mode": "none",
            "lead_in_mm": 0,
            "lead_out_mm": 0,
            "pierce_crater_diameter_mm": 0,
            "lead_clearance_mm": 0,
            "safe_travel": True,
            "travel_clearance_mm": 8,
        },
        "parts": [],
        "placements": [],
        "zones": [],
        "tabs": [],
        "lead_overrides": [],
    }
    if centerline_fallback:
        project["post"]["kerf_offset_fallback"] = "centerline"
    if open_path_centerline:
        project["post"]["open_path_mode"] = "centerline"
    return project


def project_with_corpus_nesting_options(project: dict[str, Any], *, max_runtime_s: float) -> dict[str, Any]:
    nesting = project.setdefault("nesting", {})
    nesting["auto_nest_attempts"] = min(6, max(2, int(nesting.get("auto_nest_attempts", 4))))
    nesting["auto_nest_angle_step_deg"] = float(nesting.get("auto_nest_angle_step_deg", 90.0))
    nesting["auto_nest_max_runtime_s"] = max(1.0, max_runtime_s)
    nesting["auto_nest_parallel_workers"] = int(nesting.get("auto_nest_parallel_workers", 1) or 1)
    return project


def fit_sheet_to_project(project: dict[str, Any], *, margin: float = 10.0) -> dict[str, Any]:
    profiles = {str(part["name"]): _profile_from_part_json(part) for part in project.get("parts", []) or []}
    bboxes = []
    for placement_data in project.get("placements", []) or []:
        profile = profiles.get(str(placement_data.get("part_name", "")))
        if profile is None:
            continue
        placement = Placement(
            part_name=str(placement_data.get("part_name", "")),
            instance=int(placement_data.get("instance", 1)),
            dx=float(placement_data.get("dx", 0.0)),
            dy=float(placement_data.get("dy", 0.0)),
            rotation_deg=float(placement_data.get("rotation_deg", 0.0)),
            locked=bool(placement_data.get("locked", False)),
            manual=bool(placement_data.get("manual", False)),
        )
        bboxes.append(PlacedPart(profile=profile, placement=placement).bbox())
    if not bboxes:
        return project
    min_x = min(float(box[0]) for box in bboxes)
    min_y = min(float(box[1]) for box in bboxes)
    max_x = max(float(box[2]) for box in bboxes)
    max_y = max(float(box[3]) for box in bboxes)
    shift_x = margin - min_x
    shift_y = margin - min_y
    for placement in project.get("placements", []) or []:
        placement["dx"] = float(placement.get("dx", 0.0)) + shift_x
        placement["dy"] = float(placement.get("dy", 0.0)) + shift_y
    project["sheet"] = {
        "width_mm": max(100.0, max_x - min_x + margin * 2.0),
        "height_mm": max(100.0, max_y - min_y + margin * 2.0),
        "margin_mm": margin,
    }
    return project


def error_dict(exc: Exception) -> dict[str, str]:
    return {"type": type(exc).__name__, "message": str(exc)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check DXF import/export/simulation corpus")
    parser.add_argument("roots", nargs="*", type=Path, default=[Path.home() / "Documents"])
    parser.add_argument("--auto-close-gaps", action="store_true")
    parser.add_argument("--auto-nest", action="store_true")
    parser.add_argument("--auto-nest-timeout", type=float, default=2.0)
    parser.add_argument("--centerline-fallback", action="store_true")
    parser.add_argument("--open-path-centerline", action="store_true")
    parser.add_argument("--unsafe-entity-policy", choices=("block", "warn"), default="block")
    parser.add_argument("--import-only", action="store_true", help="Stop after import and validation diagnostics")
    parser.add_argument("--max-files", type=int)
    parser.add_argument("--per-file-timeout", type=float, default=20.0)
    parser.add_argument("--diagnostic-top", type=int, default=10)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    parser.add_argument("--incremental-output", action="store_true")
    parser.add_argument("--progress", action="store_true")
    parser.add_argument("--indent", type=int, default=2)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--require-complete", action="store_true")
    parser.add_argument("--min-files", type=int)
    parser.add_argument("--min-completed-files", type=int)
    parser.add_argument("--min-import-ok", type=int)
    parser.add_argument("--min-auto-nest-ok", type=int)
    parser.add_argument("--min-export-ok", type=int)
    parser.add_argument("--min-simulation-ok", type=int)
    parser.add_argument("--max-auto-nest-runtime", type=float)
    parser.add_argument("--require-auto-nest-placements", action="store_true")
    parser.add_argument("--require-auto-nest-for-exportable", action="store_true")
    parser.add_argument("--max-timeouts", type=int)
    parser.add_argument("--forbid-import-blocking-code", action="append", default=[])
    parser.add_argument("--forbid-import-warning-code", action="append", default=[])
    parser.add_argument("--forbid-validation-blocking-code", action="append", default=[])
    parser.add_argument("--forbid-validation-warning-code", action="append", default=[])
    parser.add_argument("--check-file", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.check_file:
        print(
            json.dumps(
                check_dxf_file(
                    args.check_file,
                    auto_close_gaps=args.auto_close_gaps,
                    auto_nest=args.auto_nest,
                    auto_nest_timeout_s=args.auto_nest_timeout,
                    centerline_fallback=args.centerline_fallback,
                    open_path_centerline=args.open_path_centerline,
                    unsafe_entity_policy=args.unsafe_entity_policy,
                    export=not args.import_only,
                ),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0

    paths = discover_dxf_files(args.roots)
    report = run_corpus(
        paths,
        auto_close_gaps=args.auto_close_gaps,
        auto_nest=args.auto_nest,
        auto_nest_timeout_s=args.auto_nest_timeout,
        centerline_fallback=args.centerline_fallback,
        open_path_centerline=args.open_path_centerline,
        unsafe_entity_policy=args.unsafe_entity_policy,
        export=not args.import_only,
        max_files=args.max_files,
        per_file_timeout_s=args.per_file_timeout,
        diagnostic_top_n=args.diagnostic_top,
        incremental_output=args.output if args.incremental_output else None,
        incremental_markdown_output=args.markdown_output if args.incremental_output else None,
        progress=args.progress,
    )
    acceptance_failures = add_acceptance_result(report, acceptance_criteria_from_args(args))
    text = write_report_outputs(
        report,
        args.output,
        args.markdown_output,
        diagnostic_top_n=args.diagnostic_top,
        indent=args.indent,
    )
    if not args.quiet:
        print(text)
    if acceptance_failures:
        for failure in acceptance_failures:
            print(f"DXF corpus acceptance failed: {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
