from __future__ import annotations

import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


DEFAULT_SERVER_URL = "http://192.168.88.61"
DEFAULT_UI_URL = "http://192.168.88.61/kerfgrid"
DEFAULT_TIMEOUT_S = 20
DEFAULT_IMPORT_OPTIONS = {
    "auto_close_gaps": False,
    "repair_geometry": False,
    "unsafe_entity_policy": "warn",
}
DEFAULT_POST_OPTIONS = {
    "kerf_offset_fallback": "centerline",
    "open_path_mode": "centerline",
}


class PlasmaCamBridgeError(RuntimeError):
    pass


@dataclass(frozen=True)
class PlasmaCamImportFiles:
    dxf_path: Path
    project_path: Path


@dataclass(frozen=True)
class PlasmaCamImportSummary:
    project_name: str
    part_count: int
    placement_count: int
    warning_count: int
    blocking_issue_count: int
    safe_for_export: bool


def normalize_server_url(value: str | None = None) -> str:
    raw = value or os.environ.get("PLASMA_CAM_API_URL") or os.environ.get("PLASMA_CAM_URL") or DEFAULT_SERVER_URL
    return raw.rstrip("/")


def normalize_ui_url(value: str | None = None) -> str:
    raw = value or os.environ.get("PLASMA_CAM_UI_URL") or os.environ.get("PLASMA_CAM_URL") or DEFAULT_UI_URL
    return raw.rstrip("/")


def import_endpoint(server_url: str | None = None) -> str:
    return f"{normalize_server_url(server_url)}/api/import-dxf"


def pending_project_endpoint(server_url: str | None = None) -> str:
    return f"{normalize_server_url(server_url)}/api/pending-project"


def pending_project_url(server_url: str | None = None) -> str:
    return f"{normalize_ui_url(server_url)}/?pending_project=1"


def output_root(value: str | os.PathLike[str] | None = None) -> Path:
    raw = value or os.environ.get("PLASMA_CAM_FREECAD_OUTPUT_DIR")
    if raw:
        return Path(raw).expanduser()
    return Path(tempfile.gettempdir()) / "plasma-cam-freecad"


def safe_file_stem(value: str | None, *, fallback: str = "freecad-selection") -> str:
    raw = str(value or "").strip()
    raw = raw.replace("\\", "_").replace("/", "_").replace(":", "_")
    raw = re.sub(r"\s+", "_", raw)
    raw = re.sub(r"[^\w.\-а-яА-ЯёЁ]+", "_", raw, flags=re.UNICODE)
    raw = raw.strip("._-")
    return raw or fallback


def build_output_paths(
    selection_name: str | None,
    *,
    root: str | os.PathLike[str] | None = None,
    timestamp: str | None = None,
) -> PlasmaCamImportFiles:
    stamp = timestamp or time.strftime("%Y%m%d-%H%M%S")
    stem = safe_file_stem(selection_name)
    base = output_root(root)
    return PlasmaCamImportFiles(
        dxf_path=base / f"{stem}-{stamp}.dxf",
        project_path=base / f"{stem}-{stamp}.kerfgrid.json",
    )


def make_import_payload(
    dxf_content: str,
    filename: str,
    *,
    base_project: dict[str, Any] | None = None,
    import_options: dict[str, Any] | None = None,
    layer_mapping: dict[str, Any] | None = None,
) -> dict[str, Any]:
    merged_import_options = {**DEFAULT_IMPORT_OPTIONS, **(import_options or {})}
    if layer_mapping is not None:
        merged_import_options["layer_mapping"] = layer_mapping

    base = dict(base_project or {})
    base["import_options"] = {
        **DEFAULT_IMPORT_OPTIONS,
        **(base.get("import_options") if isinstance(base.get("import_options"), dict) else {}),
        **merged_import_options,
    }
    base["post"] = {
        **DEFAULT_POST_OPTIONS,
        **(base.get("post") if isinstance(base.get("post"), dict) else {}),
    }

    payload = {
        "filename": filename,
        "content": dxf_content,
        "base_project": base,
        "import_options": merged_import_options,
    }
    if layer_mapping is not None:
        payload["layer_mapping"] = layer_mapping
    return payload


def post_json(
    url: str,
    payload: dict[str, Any],
    *,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    open_func = opener or urllib.request.urlopen
    try:
        with open_func(request, timeout=timeout_s) as response:
            response_body = response.read()
    except urllib.error.HTTPError as exc:
        response_body = exc.read()
        try:
            error_payload = json.loads(response_body.decode("utf-8"))
        except Exception as decode_exc:
            raise PlasmaCamBridgeError(f"KerfGrid HTTP {exc.code}: {exc.reason}") from decode_exc
        message = error_payload.get("error") or exc.reason
        raise PlasmaCamBridgeError(f"KerfGrid HTTP {exc.code}: {message}") from exc
    except urllib.error.URLError as exc:
        raise PlasmaCamBridgeError(f"Cannot connect to KerfGrid at {url}: {exc.reason}") from exc

    try:
        result = json.loads(response_body.decode("utf-8"))
    except Exception as exc:
        raise PlasmaCamBridgeError("KerfGrid returned non-JSON response") from exc
    if isinstance(result, dict) and result.get("error"):
        raise PlasmaCamBridgeError(f"{result.get('type', 'Error')}: {result.get('error')}")
    if not isinstance(result, dict):
        raise PlasmaCamBridgeError("KerfGrid returned unexpected JSON response")
    return result


def import_dxf_text(
    dxf_content: str,
    filename: str,
    *,
    server_url: str | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    base_project: dict[str, Any] | None = None,
    import_options: dict[str, Any] | None = None,
    layer_mapping: dict[str, Any] | None = None,
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    payload = make_import_payload(
        dxf_content,
        filename,
        base_project=base_project,
        import_options=import_options,
        layer_mapping=layer_mapping,
    )
    return post_json(import_endpoint(server_url), payload, timeout_s=timeout_s, opener=opener)


def import_dxf_file(
    dxf_path: str | os.PathLike[str],
    *,
    server_url: str | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    base_project: dict[str, Any] | None = None,
    import_options: dict[str, Any] | None = None,
    layer_mapping: dict[str, Any] | None = None,
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    path = Path(dxf_path)
    return import_dxf_text(
        path.read_text(encoding="utf-8", errors="ignore"),
        path.name,
        server_url=server_url,
        timeout_s=timeout_s,
        base_project=base_project,
        import_options=import_options,
        layer_mapping=layer_mapping,
        opener=opener,
    )


def publish_pending_project(
    project: dict[str, Any],
    *,
    server_url: str | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    opener: Callable[..., Any] | None = None,
) -> None:
    post_json(pending_project_endpoint(server_url), {"project": project}, timeout_s=timeout_s, opener=opener)


def write_json(path: str | os.PathLike[str], payload: dict[str, Any]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def import_summary(project: dict[str, Any]) -> PlasmaCamImportSummary:
    import_data = project.get("import") if isinstance(project.get("import"), dict) else {}
    return PlasmaCamImportSummary(
        project_name=str(project.get("name") or "kerfgrid_job"),
        part_count=len(project.get("parts") if isinstance(project.get("parts"), list) else []),
        placement_count=len(project.get("placements") if isinstance(project.get("placements"), list) else []),
        warning_count=int(import_data.get("warning_count", 0) or 0),
        blocking_issue_count=int(import_data.get("blocking_issue_count", 0) or 0),
        safe_for_export=bool(import_data.get("safe_for_export", False)),
    )


def summary_text(project: dict[str, Any]) -> str:
    summary = import_summary(project)
    return (
        f"{summary.project_name}: parts={summary.part_count}, placements={summary.placement_count}, "
        f"warnings={summary.warning_count}, blocking={summary.blocking_issue_count}, "
        f"safe_for_export={summary.safe_for_export}"
    )


def open_plasma_cam(server_url: str | None = None) -> None:
    webbrowser.open(normalize_ui_url(server_url))


def open_plasma_cam_pending_project(server_url: str | None = None) -> None:
    webbrowser.open(pending_project_url(server_url))
