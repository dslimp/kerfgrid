from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
SERVER_PATH = PROJECT_ROOT / "server.py"

spec = importlib.util.spec_from_file_location("plasma_cam_server", SERVER_PATH)
assert spec is not None
server = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = server
spec.loader.exec_module(server)


def test_pending_project_slot_is_single_use() -> None:
    server._set_pending_project({"name": "from_freecad"})

    assert server._take_pending_project() == {"name": "from_freecad"}
    assert server._take_pending_project() is None
