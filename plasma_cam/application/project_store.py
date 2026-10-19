"""KerfGrid project file serialization."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_project(path: str | Path) -> dict[str, Any]:
    return normalize_project(json.loads(Path(path).read_text(encoding="utf-8")))


def normalize_project(project: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(project)
    normalized["format"] = "kerfgrid-project"
    normalized["format_version"] = 2
    normalized["sheet"] = dict(project.get("sheet", {}))
    normalized["sheet"].pop("margin_mm", None)
    return normalized


def dump_project(project: dict[str, Any]) -> str:
    return json.dumps(normalize_project(project), ensure_ascii=False, indent=2)
