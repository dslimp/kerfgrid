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


def test_server_uses_durable_shared_workspace(tmp_path) -> None:
    instance = server.create_server('127.0.0.1', 0, tmp_path)
    try:
        instance.workspace.publish_legacy({'name': 'from_freecad', 'parts': [], 'placements': []})
        assert instance.workspace.snapshot()['project']['name'] == 'from_freecad'
        assert instance.workspace.snapshot()['project']['name'] == 'from_freecad'
    finally:
        instance.server_close()
