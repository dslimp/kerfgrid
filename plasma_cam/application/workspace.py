"""Durable shared workspace and original DXF files."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .project_store import normalize_project
from .project_codec import profile_from_part_json


class WorkspaceConflict(Exception):
    def __init__(self, workspace: dict[str, Any]) -> None:
        super().__init__("Workspace changed on another computer")
        self.workspace = workspace


def checked_project(project: Any) -> dict[str, Any]:
    if not isinstance(project, dict):
        raise ValueError("project must be an object")
    if project.get("format", "kerfgrid-project") != "kerfgrid-project":
        raise ValueError("Unsupported project format")
    if int(project.get("format_version", 2)) > 2:
        raise ValueError("Unsupported project version")
    for field in ("parts", "placements"):
        if not isinstance(project.get(field), list):
            raise ValueError(f"project.{field} must be an array")
    return normalize_project(json.loads(json.dumps(project, allow_nan=False)))


class WorkspaceStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS workspace (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    revision INTEGER NOT NULL,
                    project TEXT,
                    updated_at TEXT NOT NULL
                );
                INSERT OR IGNORE INTO workspace VALUES (1, 0, NULL, '');
                CREATE TABLE IF NOT EXISTS files (
                    id TEXT PRIMARY KEY, filename TEXT NOT NULL,
                    content TEXT NOT NULL, created_at TEXT NOT NULL,
                    byte_count INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS requests (
                    id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS history (
                    revision INTEGER PRIMARY KEY, project TEXT,
                    updated_at TEXT NOT NULL
                );
                """
            )

    @contextmanager
    def _connection(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def _snapshot(self, db, after_revision: int | None = None) -> dict[str, Any]:
        if not db.in_transaction:
            db.execute("BEGIN")
        row = db.execute("SELECT * FROM workspace WHERE id = 1").fetchone()
        unchanged = after_revision is not None and row["revision"] == after_revision
        result = {
            "revision": row["revision"],
            "updated_at": row["updated_at"],
            "unchanged": unchanged,
        }
        if not unchanged:
            result["project"] = json.loads(row["project"]) if row["project"] else None
            result["files"] = [dict(item) for item in db.execute(
                "SELECT id, filename, created_at, byte_count FROM files ORDER BY created_at, id"
            )]
        return result

    def snapshot(self, after_revision: int | None = None) -> dict[str, Any]:
        with self._connection() as db:
            return self._snapshot(db, after_revision)

    def _check_revision(self, db, expected_revision: int) -> None:
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("expected_revision must be a non-negative integer")
        revision = db.execute("SELECT revision FROM workspace WHERE id = 1").fetchone()[0]
        if revision != expected_revision:
            raise WorkspaceConflict(self._snapshot(db))

    def _write(self, db, project: dict[str, Any]) -> dict[str, Any]:
        encoded = json.dumps(checked_project(project), ensure_ascii=False, allow_nan=False)
        previous = db.execute("SELECT * FROM workspace WHERE id = 1").fetchone()
        if previous["project"] == encoded:
            return self._snapshot(db)
        now = datetime.now(timezone.utc).isoformat()
        db.execute("INSERT OR REPLACE INTO history VALUES (?, ?, ?)",
                   (previous["revision"], previous["project"], previous["updated_at"]))
        db.execute("DELETE FROM history WHERE revision < ?", (previous["revision"] - 49,))
        db.execute("UPDATE workspace SET revision = revision + 1, project = ?, updated_at = ? WHERE id = 1",
                   (encoded, now))
        return self._snapshot(db)

    def save(self, project: dict[str, Any], expected_revision: int) -> dict[str, Any]:
        project = checked_project(project)
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._check_revision(db, expected_revision)
            return self._write(db, project)

    def publish_legacy(self, project: dict[str, Any]) -> dict[str, Any]:
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            return self._write(db, project)

    def file(self, file_id: str) -> dict[str, Any] | None:
        with self._connection() as db:
            row = db.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
            return dict(row) if row else None

    def import_dxf(self, payload: dict[str, Any], importer) -> dict[str, Any]:
        filename = str(payload.get("filename", "")).replace("\\", "/").rsplit("/", 1)[-1]
        content = payload.get("content")
        if not filename.lower().endswith(".dxf") or not isinstance(content, str) or not content.strip():
            raise ValueError("filename ending in .dxf and non-empty content are required")
        quantity = payload.get("quantity", 1)
        if type(quantity) is not int or not 1 <= quantity <= 10000:
            raise ValueError("quantity must be an integer from 1 to 10000")
        thickness = payload.get("thickness_mm")
        if thickness is not None and (isinstance(thickness, bool) or not math.isfinite(float(thickness)) or float(thickness) <= 0):
            raise ValueError("thickness_mm must be positive")
        mode = payload.get("mode", "append")
        if mode not in ("append", "replace"):
            raise ValueError("mode must be append or replace")
        if mode == "replace" and "expected_revision" not in payload:
            raise ValueError("replace requires expected_revision")
        request_id = payload.get("request_id")
        if request_id is not None and (not isinstance(request_id, str) or not 1 <= len(request_id) <= 200):
            raise ValueError("request_id must be a non-empty string up to 200 characters")
        fingerprint = hashlib.sha256(json.dumps(
            {k: v for k, v in payload.items() if k != "expected_revision"}, sort_keys=True,
            ensure_ascii=False, allow_nan=False,
        ).encode()).hexdigest()
        options = dict(payload.get("import_options") or {})
        options.update(auto_close_gaps=False, repair_geometry=False)
        current = self.snapshot()["project"]
        base = copy.deepcopy(current or payload.get("base_project") or {})
        if thickness is not None:
            base.setdefault("cut", {})["thickness_mm"] = float(thickness)
        imported = importer({"filename": filename, "content": content,
                             "base_project": base, "import_options": options,
                             "layer_mapping": payload.get("layer_mapping")})
        file_id = hashlib.sha256((filename + "\0" + content).encode()).hexdigest()
        for part in imported["parts"]:
            part["source_file_id"] = file_id
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if request_id:
                previous = db.execute("SELECT fingerprint FROM requests WHERE id = ?", (request_id,)).fetchone()
                if previous:
                    if previous[0] != fingerprint:
                        raise ValueError("request_id was already used with different content or options")
                    return {**self._snapshot(db), "replayed": True}
            if "expected_revision" in payload:
                self._check_revision(db, payload["expected_revision"])
            current = self._snapshot(db)["project"]
            merged, summary = merge_dxf_project(current, imported, filename, quantity, mode)
            if thickness is not None:
                merged.setdefault("cut", {})["thickness_mm"] = float(thickness)
            now = datetime.now(timezone.utc).isoformat()
            db.execute("INSERT OR IGNORE INTO files VALUES (?, ?, ?, ?, ?)",
                       (file_id, filename, content, now, len(content.encode())))
            result = self._write(db, merged)
            if request_id:
                db.execute("INSERT INTO requests VALUES (?, ?)", (request_id, fingerprint))
            return {**result, "file_id": file_id, "import_summary": summary}


def merge_dxf_project(current, imported, filename: str, quantity: int, mode: str):
    imported = copy.deepcopy(imported)
    for part in imported["parts"]:
        part.update(source_file=filename, source_part_name=part.get("source_part_name", part["name"]),
                    import_source="dxf", import_issues=imported.get("import", {}).get("issues", []),
                    quantity=quantity)
    is_demo = (current and current.get("name") == "circle_with_center_hole"
               and len(current.get("parts", [])) == 1 and current["parts"][0]["name"] == "disk")
    replace = current is None or mode == "replace" or is_demo
    result = copy.deepcopy(imported if replace else current)
    if replace:
        result["parts"] = []
        result["placements"] = []
    used = {p["name"] for p in result["parts"]}
    added, updated, cleared = 0, 0, 0
    for part in imported["parts"]:
        existing = next((p for p in result["parts"] if p.get("source_file") == filename
                         and p.get("source_part_name", p["name"]) == part["source_part_name"]), None)
        if existing:
            name = existing["name"]
            replacements = [p for p in result["placements"] if p["part_name"] == name]
            part.update(name=name, quantity=existing.get("quantity", len(replacements)),
                        allowed_rotations=existing.get("allowed_rotations", [0, 90, 180, 270]),
                        grain_lock=existing.get("grain_lock", False))
            result["parts"][result["parts"].index(existing)] = part
            prefixes = [f"{name}_{p['instance']}_" for p in replacements]
            leads = result.get("lead_overrides", [])
            kept = [lead for lead in leads if not (lead.get("auto_generated") and any(
                str(lead.get("contour_name", "")).startswith(prefix) for prefix in prefixes))]
            cleared += len(leads) - len(kept)
            result["lead_overrides"] = kept
            updated += 1
            continue
        base_name, suffix = part["name"], 2
        while part["name"] in used:
            part["name"] = f"{base_name}_{suffix}"
            suffix += 1
        used.add(part["name"])
        result["parts"].append(part)
        added += 1
        if part.get("cuttable", True):
            for instance in range(1, quantity + 1):
                result["placements"].append(initial_placement(result, part, instance))
    result["import_options"] = {**result.get("import_options", {}), "auto_close_gaps": False, "repair_geometry": False}
    issues = []
    for part in result["parts"]:
        for issue in part.get("import_issues", []):
            issues.append({**issue, "message": f"{part.get('source_file', part['name'])}: {issue.get('message', issue.get('code', 'DXF issue'))}"})
    result["import"] = {**result.get("import", {}), "source": "mixed", "safe_for_export": True,
                        "partial": bool(issues), "blocking_issue_count": 0, "warning_count": len(issues), "issues": issues}
    return result, {"added": added, "updated": updated, "auto_leads_cleared": cleared}


def initial_placement(project, part, instance):
    bounds = profile_from_part_json(part).bbox()
    width, height = bounds[2] - bounds[0], bounds[3] - bounds[1]
    spacing = max(0, float(project.get("spacing_mm", 5))) + 0.05
    definitions = {p["name"]: p for p in project["parts"]}
    occupied = []
    for p in project["placements"]:
        b = profile_from_part_json(definitions[p["part_name"]]).bbox()
        angle = math.radians(float(p.get("rotation_deg", 0)))
        corners = [(x * math.cos(angle) - y * math.sin(angle) + p["dx"],
                    x * math.sin(angle) + y * math.cos(angle) + p["dy"])
                   for x in (b[0], b[2]) for y in (b[1], b[3])]
        occupied.append((min(x for x, y in corners), min(y for x, y in corners),
                         max(x for x, y in corners), max(y for x, y in corners)))
    sheet = project.get("sheet", {})
    x, y = 0.0, 0.0
    for yi in range(max(1, int(float(sheet.get("height_mm", 500)) / max(10, height + spacing)) + 1)):
        y = yi * max(10, height + spacing)
        if y + height > float(sheet.get("height_mm", 500)) + 0.001:
            break
        for xi in range(max(1, int(float(sheet.get("width_mm", 1000)) / max(10, min(width + spacing, 80))) + 1)):
            x = xi * max(10, min(width + spacing, 80))
            if x + width > float(sheet.get("width_mm", 1000)) + 0.001:
                break
            if all(x + width + spacing <= a or c + spacing <= x or y + height + spacing <= b or d + spacing <= y
                   for a, b, c, d in occupied):
                return {"part_name": part["name"], "instance": instance, "dx": x - bounds[0],
                        "dy": y - bounds[1], "rotation_deg": 0, "manual": False}
    return {"part_name": part["name"], "instance": instance, "dx": -bounds[0],
            "dy": -bounds[1], "rotation_deg": 0, "manual": False}
