"""Local KerfGrid HTTP server."""

from __future__ import annotations

import argparse
import json
import threading
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

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
    project_review_report,
    preview_from_project,
    simulation_from_project,
    validate_project,
)


APP_DIR = Path(__file__).resolve().parent
WEB_DIR = APP_DIR / "web"
EXAMPLE_PATH = APP_DIR / "examples" / "circle-hole.project.json"
_PENDING_PROJECT_LOCK = threading.Lock()
_PENDING_PROJECT: dict | None = None


class KerfGridHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/example":
            self._send_json(json.loads(EXAMPLE_PATH.read_text(encoding="utf-8")))
            return
        if path == "/api/pending-project":
            self._send_json({"project": _take_pending_project()})
            return
        if path == "/api/cut-chart":
            self._send_json({"profile": cut_chart_profile_metadata(), "rows": cut_chart_table()})
            return
        if path == "/":
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            project = self._read_json_body()
            if path == "/api/pending-project":
                _set_pending_project(project.get("project", project))
                self._send_json({"ok": True})
                return
            if path == "/api/validate":
                self._send_json({"issues": validate_project(project)})
                return
            if path == "/api/auto-nest":
                self._send_json(auto_nest_project(project))
                return
            if path == "/api/preview":
                self._send_json(preview_from_project(project))
                return
            if path == "/api/export":
                gcode = export_project_gcode(project)
                self._send_json(
                    {
                        "filename": f"{project.get('name', 'kerfgrid_job')}.ngc",
                        "gcode": gcode,
                        "line_count": len(gcode.splitlines()),
                    }
                )
                return
            if path == "/api/export-outline":
                gcode = export_project_outline_gcode(project)
                self._send_json(
                    {
                        "filename": f"{project.get('name', 'kerfgrid_job')}-outline.ngc",
                        "gcode": gcode,
                        "line_count": len(gcode.splitlines()),
                    }
                )
                return
            if path == "/api/export-dxf":
                dxf = export_project_review_dxf(project)
                self._send_json(
                    {
                        "filename": f"{project.get('name', 'kerfgrid_job')}-review.dxf",
                        "dxf": dxf,
                        "line_count": len(dxf.splitlines()),
                    }
                )
                return
            if path == "/api/review-report":
                self._send_json(
                    {
                        "filename": f"{project.get('name', 'kerfgrid_job')}-review.json",
                        "report": project_review_report(project),
                    }
                )
                return
            if path == "/api/cut-settings":
                self._send_json(cut_settings_preview(project))
                return
            if path == "/api/coupon-test":
                self._send_json(generate_coupon_test_project(project))
                return
            if path == "/api/import-coupon-results":
                self._send_json(import_coupon_results(project))
                return
            if path == "/api/simulate":
                self._send_json(simulation_from_project(project))
                return
            if path == "/api/import-dxf":
                self._send_json(import_dxf_project(project))
                return
            self.send_error(HTTPStatus.NOT_FOUND, f"Unknown API path: {path}")
        except Exception as exc:
            self._send_json(
                {"error": str(exc), "type": type(exc).__name__},
                status=HTTPStatus.BAD_REQUEST,
            )

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def _send_json(self, payload, *, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except BrokenPipeError:
            return


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the KerfGrid UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), KerfGridHandler)
    print(f"KerfGrid UI: http://{args.host}:{args.port}/")
    server.serve_forever()


def _set_pending_project(project: dict) -> None:
    global _PENDING_PROJECT
    with _PENDING_PROJECT_LOCK:
        _PENDING_PROJECT = project


def _take_pending_project() -> dict | None:
    global _PENDING_PROJECT
    with _PENDING_PROJECT_LOCK:
        project = _PENDING_PROJECT
        _PENDING_PROJECT = None
    return project


if __name__ == "__main__":
    main()
