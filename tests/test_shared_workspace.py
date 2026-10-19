from __future__ import annotations

import importlib.util
import io
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import ezdxf
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
spec = importlib.util.spec_from_file_location("workspace_api_server", PROJECT_ROOT / "server.py")
server = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = server
spec.loader.exec_module(server)

from plasma_cam.application.workspace import WorkspaceConflict, WorkspaceStore
from plasma_cam.web_api import import_dxf_project
from kerfgrid_client import upload_dxf


def dxf_content(width=120, close=True):
    doc = ezdxf.new()
    doc.modelspace().add_lwpolyline([(0, 0), (width, 0), (width, 40), (0, 60)], close=close)
    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue()


def payload(filename="eave.dxf", request_id="first", **extra):
    return {"filename": filename, "content": dxf_content(), "quantity": 1, "request_id": request_id, **extra}


def demo():
    return json.loads((PROJECT_ROOT / "examples/circle-hole.project.json").read_text())


@pytest.fixture
def store(tmp_path):
    return WorkspaceStore(tmp_path / "workspace.sqlite3")


@pytest.fixture
def api(tmp_path):
    instance = server.create_server("127.0.0.1", 0, tmp_path)
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{instance.server_port}"
    instance.shutdown()
    instance.server_close()
    thread.join()


def request(api, path, data=None):
    req = Request(api + path, data=json.dumps(data).encode() if data is not None else None,
                  headers={"Content-Type": "application/json"})
    try:
        with urlopen(req) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, json.load(error)


def test_workspace_survives_process_restart_and_repeated_reads(store):
    saved = store.save(demo(), 0)
    restarted = WorkspaceStore(store.path)
    assert restarted.snapshot() == saved
    assert restarted.snapshot()["project"] == saved["project"]
    assert restarted.snapshot(saved["revision"])["unchanged"] is True
    assert "project" not in restarted.snapshot(saved["revision"])


def test_stale_browser_cannot_overwrite_new_state(store):
    first = store.save(demo(), 0)
    changed = {**first["project"], "name": "second computer"}
    latest = store.save(changed, first["revision"])
    with pytest.raises(WorkspaceConflict) as error:
        store.save(first["project"], first["revision"])
    assert error.value.workspace == latest
    assert store.snapshot()["project"]["name"] == "second computer"


def test_simultaneous_saves_only_accept_one_revision(store):
    first = store.save(demo(), 0)
    def save(name):
        try:
            return store.save({**first["project"], "name": name}, first["revision"])
        except WorkspaceConflict:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, ["left", "right"]))
    assert sum(r is not None for r in results) == 1
    assert store.snapshot()["revision"] == 2


def test_agent_upload_persists_original_and_retries_without_duplicates(store):
    data = payload(thickness_mm=4)
    imported = store.import_dxf(data, import_dxf_project)
    assert len(imported["project"]["parts"]) == len(imported["project"]["placements"]) == 1
    assert imported["project"]["parts"][0]["quantity"] == 1
    assert imported["project"]["cut"]["thickness_mm"] == 4
    assert store.file(imported["file_id"])["content"] == data["content"]
    repeated = WorkspaceStore(store.path).import_dxf(data, import_dxf_project)
    assert repeated["replayed"] is True
    assert repeated["revision"] == imported["revision"]
    with pytest.raises(ValueError, match="request_id"):
        store.import_dxf({**data, "quantity": 2}, import_dxf_project)


def test_agent_append_preserves_manual_placement_tabs_and_settings(store):
    first = store.import_dxf(payload(), import_dxf_project)
    edited = first["project"]
    edited["placements"][0].update(dx=400, dy=100, rotation_deg=90, locked=True)
    edited["tabs"] = [{"contour_name": "manual", "length_mm": 2, "x": 2, "y": 4}]
    edited["cut"]["nozzle_mm"] = 1.2
    saved = store.save(edited, first["revision"])
    appended = store.import_dxf(payload(filename="other.dxf", request_id="other", quantity=2), import_dxf_project)
    project = appended["project"]
    assert len(project["parts"]) == 2
    assert len(project["placements"]) == 3
    assert project["placements"][0] == saved["project"]["placements"][0]
    assert project["tabs"] == edited["tabs"]
    assert project["cut"]["nozzle_mm"] == 1.2
    assert len(appended["files"]) == 2


@pytest.mark.parametrize("requested_quantity", [0, 7])
def test_reimport_preserves_requested_quantity_when_placements_differ(store, requested_quantity):
    first = store.import_dxf(payload(quantity=2), import_dxf_project)
    edited = first["project"]
    edited["parts"][0]["quantity"] = requested_quantity
    store.save(edited, first["revision"])
    result = store.import_dxf(payload(request_id="new-geometry", content=dxf_content(width=125)), import_dxf_project)
    assert result["project"]["parts"][0]["quantity"] == requested_quantity
    assert result["project"]["placements"] == edited["placements"]


def test_reimport_updates_geometry_preserves_quantity_and_manual_leads(store):
    first = store.import_dxf(payload(quantity=2), import_dxf_project)
    name = first["project"]["parts"][0]["name"]
    edited = first["project"]
    edited["parts"][0]["allowed_rotations"] = [0, 180]
    edited["lead_overrides"] = [
        {"contour_name": f"{name}_1_outer", "auto_generated": True},
        {"contour_name": f"{name}_2_outer", "auto_generated": False},
    ]
    store.save(edited, first["revision"])
    result = store.import_dxf(payload(request_id="update", content=dxf_content(180)), import_dxf_project)
    assert len(result["project"]["parts"]) == 1
    assert result["project"]["parts"][0]["quantity"] == 2
    assert result["project"]["parts"][0]["allowed_rotations"] == [0, 180]
    assert result["project"]["placements"] == edited["placements"]
    assert result["project"]["lead_overrides"] == [edited["lead_overrides"][1]]
    assert result["import_summary"] == {"added": 0, "updated": 1, "auto_leads_cleared": 1}


def test_import_never_enables_geometry_repair(store):
    data = payload(content=dxf_content(close=False), import_options={"repair_geometry": True, "auto_close_gaps": True})
    result = store.import_dxf(data, import_dxf_project)
    assert result["project"]["import_options"]["repair_geometry"] is False
    assert result["project"]["import_options"]["auto_close_gaps"] is False
    assert store.file(result["file_id"])["content"] == data["content"]
    contours = result["project"]["parts"][0]["contours"]
    assert len(contours[0]["segments"]) == 3
    assert result["project"]["import"]["warning_count"] > 0


@pytest.mark.parametrize("extra", [{"quantity": 0}, {"quantity": 1.5}, {"thickness_mm": -1},
                                  {"mode": "replace"}, {"expected_revision": 1}])
def test_invalid_upload_does_not_change_workspace(store, extra):
    with pytest.raises((ValueError, WorkspaceConflict)):
        store.import_dxf(payload(**extra), import_dxf_project)
    assert store.snapshot()["revision"] == 0
    assert store.snapshot()["files"] == []


def test_http_api_shares_state_files_and_conflicts(api, tmp_path):
    path = tmp_path / "test.dxf"
    path.write_text(dxf_content())
    result = upload_dxf(path, api, quantity=1, thickness_mm=4, request_id="client")
    status, browser = request(api, "/api/workspace")
    assert status == 200 and browser["revision"] == result["revision"]
    assert browser["project"] == result["project"]
    with urlopen(api + "/api/workspace/files/" + result["file_id"]) as response:
        assert response.read().decode() == path.read_text()
    assert request(api, "/api/workspace/files")[1]["files"] == browser["files"]
    assert request(api, "/api/workspace", {"project": demo(), "expected_revision": 0})[0] == 409
    assert request(api, "/api/workspace?after_revision=1")[1]["unchanged"] is True
    assert request(api, "/api/workspace", {"project": demo()})[0] == 400


def test_legacy_pending_endpoint_is_durable_not_consumed(api):
    assert request(api, "/api/pending-project", {"project": demo()})[0] == 200
    first = request(api, "/api/pending-project")[1]
    second = request(api, "/api/pending-project")[1]
    assert first == second
    assert request(api, "/api/workspace")[1] == first
