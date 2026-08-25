from __future__ import annotations

import importlib.util
import json
import sys
import urllib.error
from types import SimpleNamespace
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = PROJECT_ROOT / "freecad" / "PlasmaCamBridge" / "plasma_cam_bridge_core.py"
COMMAND_PATH = PROJECT_ROOT / "freecad" / "PlasmaCamBridge" / "plasma_cam_bridge_command.py"
INITGUI_PATH = PROJECT_ROOT / "freecad" / "PlasmaCamBridge" / "InitGui.py"

spec = importlib.util.spec_from_file_location("plasma_cam_bridge_core", CORE_PATH)
assert spec is not None
core = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = core
spec.loader.exec_module(core)


def load_command_module():
    sys.modules["plasma_cam_bridge_core"] = core
    spec = importlib.util.spec_from_file_location("plasma_cam_bridge_command", COMMAND_PATH)
    assert spec is not None
    command = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = command
    spec.loader.exec_module(command)
    return command


class Response:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_freecad_bridge_builds_warning_only_import_payload() -> None:
    payload = core.make_import_payload("0\nEOF\n", "part.dxf")

    assert payload["filename"] == "part.dxf"
    assert payload["content"] == "0\nEOF\n"
    assert payload["import_options"]["auto_close_gaps"] is False
    assert payload["import_options"]["repair_geometry"] is False
    assert payload["import_options"]["unsafe_entity_policy"] == "warn"
    assert payload["base_project"]["import_options"]["unsafe_entity_policy"] == "warn"
    assert payload["base_project"]["post"]["kerf_offset_fallback"] == "centerline"
    assert payload["base_project"]["post"]["open_path_mode"] == "centerline"


def test_freecad_bridge_preserves_base_project_options() -> None:
    payload = core.make_import_payload(
        "dxf",
        "part.dxf",
        base_project={"post": {"precision": 4}, "import_options": {"auto_close_gaps": False}},
        import_options={"unsafe_entity_policy": "warn"},
        layer_mapping={"CUT": "cut"},
    )

    assert payload["base_project"]["post"]["precision"] == 4
    assert payload["base_project"]["post"]["open_path_mode"] == "centerline"
    assert payload["base_project"]["import_options"]["auto_close_gaps"] is False
    assert payload["base_project"]["import_options"]["repair_geometry"] is False
    assert payload["base_project"]["import_options"]["layer_mapping"] == {"CUT": "cut"}
    assert payload["layer_mapping"] == {"CUT": "cut"}


def test_freecad_bridge_output_paths_are_safe_and_stable(tmp_path: Path) -> None:
    paths = core.build_output_paths("Sketch: flange/левый", root=tmp_path, timestamp="20260824-120000")

    assert paths.dxf_path == tmp_path / "Sketch__flange_левый-20260824-120000.dxf"
    assert paths.project_path == tmp_path / "Sketch__flange_левый-20260824-120000.kerfgrid.json"


def test_freecad_bridge_posts_import_request() -> None:
    captured = {}

    def opener(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return Response({"name": "part", "parts": [], "placements": []})

    result = core.import_dxf_text("dxf", "part.dxf", opener=opener, server_url="http://127.0.0.1:8765/")

    assert captured["url"] == "http://127.0.0.1:8765/api/import-dxf"
    assert captured["timeout"] == core.DEFAULT_TIMEOUT_S
    assert captured["body"]["filename"] == "part.dxf"
    assert result["name"] == "part"


def test_freecad_bridge_publishes_pending_project() -> None:
    captured = {}

    def opener(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return Response({"ok": True})

    core.publish_pending_project({"name": "part"}, opener=opener, server_url="http://127.0.0.1:8765/")

    assert captured["url"] == "http://127.0.0.1:8765/api/pending-project"
    assert captured["timeout"] == core.DEFAULT_TIMEOUT_S
    assert captured["body"] == {"project": {"name": "part"}}


def test_freecad_bridge_pending_project_url() -> None:
    assert core.pending_project_url("http://127.0.0.1:8765/") == "http://127.0.0.1:8765/?pending_project=1"


def test_freecad_bridge_raises_clear_error_for_api_error() -> None:
    def opener(request, timeout):
        return Response({"error": "bad dxf", "type": "ValueError"})

    with pytest.raises(core.PlasmaCamBridgeError, match="ValueError: bad dxf"):
        core.import_dxf_text("bad", "part.dxf", opener=opener)


def test_freecad_bridge_raises_clear_error_for_http_error() -> None:
    class FailingHttpError(urllib.error.HTTPError):
        def read(self):
            return json.dumps({"error": "server failed"}).encode("utf-8")

    def opener(request, timeout):
        raise FailingHttpError(request.full_url, 400, "Bad Request", {}, None)

    with pytest.raises(core.PlasmaCamBridgeError, match="KerfGrid HTTP 400: server failed"):
        core.import_dxf_text("bad", "part.dxf", opener=opener)


def test_freecad_bridge_writes_project_json(tmp_path: Path) -> None:
    target = core.write_json(tmp_path / "part.kerfgrid.json", {"name": "part"})

    assert json.loads(target.read_text(encoding="utf-8")) == {"name": "part"}


def test_freecad_bridge_summary_text() -> None:
    text = core.summary_text(
        {
            "name": "part",
            "parts": [{}, {}],
            "placements": [{}],
            "import": {"warning_count": 3, "blocking_issue_count": 0, "safe_for_export": True},
        }
    )

    assert text == "part: parts=2, placements=1, warnings=3, blocking=0, safe_for_export=True"


def test_freecad_bridge_command_has_visible_toolbar_resources(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "FreeCAD", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "FreeCADGui", SimpleNamespace())

    command = load_command_module()
    resources = command.SendSelectionCommand().GetResources()

    assert resources["MenuText"] == "To Nest"
    assert "Sketch" in resources["ToolTip"]
    assert Path(resources["Pixmap"]).exists()


def test_freecad_bridge_installs_sketcher_toolbar_and_menu_entrypoints() -> None:
    init_gui_source = INITGUI_PATH.read_text(encoding="utf-8")

    assert 'SKETCHER_EDIT_TOOLBAR_OBJECT_NAME = "Edit Mode"' in init_gui_source
    assert 'SKETCHER_TOOLBAR_OBJECT_NAME = "PlasmaCamBridgeSketcherToolbar"' in init_gui_source
    assert 'SKETCHER_EDIT_ACTION_OBJECT_NAME = "PlasmaCamBridgeSketcherEditAction"' in init_gui_source
    assert 'GLOBAL_MENU_ACTION_OBJECT_NAME = "PlasmaCamBridgeMenuSendSelectionAction"' in init_gui_source
    assert "def _new_bridge_button_action(" in init_gui_source
    assert "edit_toolbar.insertAction(actions[0], bridge_action)" in init_gui_source
    assert "main_window.addToolBar(_top_toolbar_area(QtCore), toolbar)" in init_gui_source
    assert "_install_sketcher_edit_action(QtCore, QtGui, QtWidgets, main_window)" in init_gui_source
    assert "_install_global_menu(QtGui, QtWidgets, main_window)" in init_gui_source


def test_freecad_bridge_uses_active_sketch_when_selection_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    sketch = SimpleNamespace(Label="Sketch")
    fake_gui = SimpleNamespace(
        Selection=SimpleNamespace(getSelection=lambda: []),
        ActiveDocument=SimpleNamespace(getInEdit=lambda: sketch),
    )
    monkeypatch.setitem(sys.modules, "FreeCAD", SimpleNamespace(ActiveDocument=None))
    monkeypatch.setitem(sys.modules, "FreeCADGui", fake_gui)

    command = load_command_module()

    assert command.selection_objects() == [sketch]


def test_freecad_bridge_uses_tuple_active_sketch_when_selection_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    sketch = SimpleNamespace(Label="Sketch")
    fake_gui = SimpleNamespace(
        Selection=SimpleNamespace(getSelection=lambda: []),
        ActiveDocument=SimpleNamespace(getInEdit=lambda: (sketch, "Edit")),
    )
    monkeypatch.setitem(sys.modules, "FreeCAD", SimpleNamespace(ActiveDocument=None))
    monkeypatch.setitem(sys.modules, "FreeCADGui", fake_gui)

    command = load_command_module()

    assert command.selection_objects() == [sketch]


def test_freecad_bridge_unwraps_active_sketch_view_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    sketch = SimpleNamespace(Label="Sketch")
    view_provider = SimpleNamespace(Object=sketch)
    fake_gui = SimpleNamespace(
        Selection=SimpleNamespace(getSelection=lambda: []),
        ActiveDocument=SimpleNamespace(getInEdit=lambda: view_provider),
    )
    monkeypatch.setitem(sys.modules, "FreeCAD", SimpleNamespace(ActiveDocument=None))
    monkeypatch.setitem(sys.modules, "FreeCADGui", fake_gui)

    command = load_command_module()

    assert command.selection_objects() == [sketch]
