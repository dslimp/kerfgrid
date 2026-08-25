"""KerfGrid project file serialization."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_project(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def dump_project(project: dict[str, Any]) -> str:
    return json.dumps(project, ensure_ascii=False, indent=2)
