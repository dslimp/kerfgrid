from __future__ import annotations

import subprocess
import sys
import threading
import json
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import plasma_cam.web_api as web_api_module
import server as server_module
from plasma_cam.application.linuxcnc_transfer import (
    LinuxCNCGCodeFile,
    LinuxCNCTransferConfig,
    config_from_env,
    send_gcode_bundle_to_linuxcnc,
    send_gcode_to_linuxcnc,
)


def _ok(_command, **_kwargs):
    return subprocess.CompletedProcess(_command, 0, "__KERFGRID_UPLOAD_OK__\n", "")


def test_linuxcnc_transfer_config_reads_env() -> None:
    config = config_from_env(
        {
            "KERFGRID_LINUXCNC_HOST": "linuxcnc.local",
            "KERFGRID_LINUXCNC_PORT": "2222",
            "KERFGRID_LINUXCNC_USER": "linuxcnc",
            "KERFGRID_LINUXCNC_REMOTE_DIR": "/tmp/jobs",
            "KERFGRID_LINUXCNC_KEY": "/tmp/key",
            "KERFGRID_LINUXCNC_OWNER": "",
            "KERFGRID_LINUXCNC_TIMEOUT_S": "7.5",
            "KERFGRID_LINUXCNC_CONTROL_PERSIST_S": "45",
            "KERFGRID_LINUXCNC_CONTROL_PATH": "/tmp/kerfgrid-test.sock",
            "KERFGRID_LINUXCNC_LOAD_COMMAND": "linuxcncrsh open {remote_path}",
        }
    )

    assert config == LinuxCNCTransferConfig(
        host="linuxcnc.local",
        port=2222,
        user="linuxcnc",
        remote_dir="/tmp/jobs",
        key_path="/tmp/key",
        owner="",
        timeout_s=7.5,
        control_persist_s=45,
        control_path="/tmp/kerfgrid-test.sock",
        load_command="linuxcncrsh open {remote_path}",
    )


def test_send_gcode_builds_single_ssh_upload_and_load_command() -> None:
    commands: list[list[str]] = []

    def run(command, **_kwargs):
        commands.append(list(command))
        payload = json.loads(_kwargs["input"])
        assert payload["files"] == [
            {
                "filename": "bad_name.ngc",
                "gcode": "G21\nM2\n",
                "remote_path": "/home/linuxcnc/linuxcnc/nc_files/kerfgrid/bad_name.ngc",
                "byte_count": len("G21\nM2\n".encode("utf-8")),
            }
        ]
        return subprocess.CompletedProcess(command, 0, "__KERFGRID_UPLOAD_OK__\n", "")

    result = send_gcode_to_linuxcnc(
        filename="../bad name.ngc",
        gcode="G21\nM2\n",
        config=LinuxCNCTransferConfig(
            host="192.168.64.5",
            user="root",
            remote_dir="/home/linuxcnc/linuxcnc/nc_files/kerfgrid",
            key_path="/tmp/id_rsa",
        ),
        run=run,
        which=lambda name: f"/usr/bin/{name}",
    )

    assert result["remote_path"] == "/home/linuxcnc/linuxcnc/nc_files/kerfgrid/bad_name.ngc"
    assert result["byte_count"] == len("G21\nM2\n".encode("utf-8"))
    assert result["uploaded"] is True
    assert result["loaded"] is True
    assert result["load_error"] is None
    assert len(commands) == 1
    assert commands[0][:2] == ["/usr/bin/ssh", "-p"]
    remote_command = commands[0][-1]
    assert "ControlMaster=auto" in commands[0]
    assert "ControlPersist=300" in commands[0]
    assert "mkdir -p -- /home/linuxcnc/linuxcnc/nc_files/kerfgrid" in remote_command
    assert "python3 -c" in remote_command
    assert "__KERFGRID_UPLOAD_OK__" in remote_command
    assert "chown linuxcnc:linuxcnc -- /home/linuxcnc/linuxcnc/nc_files/kerfgrid/bad_name.ngc" in remote_command
    assert "runuser -u linuxcnc -- python3 -c" in remote_command
    assert "/home/linuxcnc/linuxcnc/nc_files/kerfgrid/bad_name.ngc" in remote_command


def test_send_gcode_bundle_uploads_outline_and_loads_job_in_one_ssh_command() -> None:
    commands: list[list[str]] = []

    def run(command, **_kwargs):
        commands.append(list(command))
        payload = json.loads(_kwargs["input"])
        assert [item["filename"] for item in payload["files"]] == [
            "kerfgrid_job_live.ngc",
            "kerfgrid_outline_live.ngc",
        ]
        return subprocess.CompletedProcess(command, 0, "__KERFGRID_UPLOAD_OK__\n", "")

    result = send_gcode_bundle_to_linuxcnc(
        files=(
            LinuxCNCGCodeFile(filename="kerfgrid_job_live.ngc", gcode="G21\nM2\n"),
            LinuxCNCGCodeFile(filename="kerfgrid_outline_live.ngc", gcode="G21\nG0 X0 Y0\nM2\n"),
        ),
        load_filename="kerfgrid_job_live.ngc",
        config=LinuxCNCTransferConfig(key_path="/tmp/id_rsa"),
        run=run,
        which=lambda name: f"/usr/bin/{name}",
    )

    assert result["remote_path"] == "/home/linuxcnc/linuxcnc/nc_files/kerfgrid/kerfgrid_job_live.ngc"
    assert result["loaded"] is True
    assert len(result["files"]) == 2
    assert len(commands) == 1
    remote_command = commands[0][-1]
    assert "kerfgrid_job_live.ngc" in remote_command
    assert "kerfgrid_outline_live.ngc" in remote_command


def test_send_gcode_reports_upload_success_and_load_failure() -> None:
    commands: list[list[str]] = []

    def run(command, **_kwargs):
        commands.append(list(command))
        return subprocess.CompletedProcess(command, 1, "__KERFGRID_UPLOAD_OK__\n", "LinuxCNC is not running")

    result = send_gcode_to_linuxcnc(
        filename="job.ngc",
        gcode="G21\nM2\n",
        config=LinuxCNCTransferConfig(key_path="/tmp/id_rsa"),
        run=run,
        which=lambda name: f"/usr/bin/{name}",
    )

    assert result["uploaded"] is True
    assert result["loaded"] is False
    assert result["load_error"] == "LinuxCNC is not running"
    assert result["remote_path"] == "/home/linuxcnc/linuxcnc/nc_files/kerfgrid/job.ngc"
    assert len(commands) == 1
    assert commands[0][0] == "/usr/bin/ssh"


def test_send_gcode_reports_missing_ssh() -> None:
    try:
        send_gcode_to_linuxcnc(
            filename="job.ngc",
            gcode="M2\n",
            config=LinuxCNCTransferConfig(),
            run=_ok,
            which=lambda _name: None,
        )
    except RuntimeError as exc:
        assert "requires `ssh`" in str(exc)
    else:
        raise AssertionError("missing ssh must fail")


def test_web_api_send_uploads_job_and_outline_live_files(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_export(_project):
        return "G21\nM2\n"

    def fake_outline(_project):
        return "G21\nG0 X0 Y0\nM2\n"

    def fake_send(*, files, load_filename):
        captured["files"] = files
        captured["load_filename"] = load_filename
        return {
            "remote_path": "/tmp/kerfgrid_job_live.ngc",
            "byte_count": sum(len(file.gcode) for file in files),
            "files": [
                {"filename": file.filename, "remote_path": f"/tmp/{file.filename}", "byte_count": len(file.gcode)}
                for file in files
            ],
            "warnings": [],
            "uploaded": True,
            "loaded": True,
            "load_error": None,
        }

    monkeypatch.setattr(web_api_module, "export_project_gcode", fake_export)
    monkeypatch.setattr(web_api_module, "export_project_outline_gcode", fake_outline)
    monkeypatch.setattr(web_api_module, "send_gcode_bundle_to_linuxcnc", fake_send)

    result = web_api_module.send_project_to_linuxcnc({"name": "demo"})

    sent_files = captured["files"]
    assert tuple(file.filename for file in sent_files) == ("kerfgrid_job_live.ngc", "kerfgrid_outline_live.ngc")
    assert tuple(file.gcode for file in sent_files) == ("G21\nM2\n", "G21\nG0 X0 Y0\nM2\n")
    assert captured["load_filename"] == "kerfgrid_job_live.ngc"
    assert result["filename"] == "kerfgrid_job_live.ngc"
    assert result["outline_filename"] == "kerfgrid_outline_live.ngc"
    assert result["remote_path"] == "/tmp/kerfgrid_job_live.ngc"
    assert result["line_count"] == 2
    assert result["outline_line_count"] == 3


def test_server_send_linuxcnc_endpoint_returns_transfer_payload(monkeypatch) -> None:
    monkeypatch.setattr(
        server_module,
        "send_project_to_linuxcnc",
        lambda project: {
            "filename": f"{project['name']}.ngc",
            "remote_path": "/home/linuxcnc/job.ngc",
            "byte_count": 12,
            "warnings": [],
            "uploaded": True,
            "loaded": True,
        },
    )
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server_module.KerfGridHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        body = json.dumps({"name": "demo"}).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{httpd.server_port}/api/send-linuxcnc",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
    finally:
        httpd.shutdown()
        thread.join(timeout=3)

    assert payload == {
        "filename": "demo.ngc",
        "remote_path": "/home/linuxcnc/job.ngc",
        "byte_count": 12,
        "warnings": [],
        "uploaded": True,
        "loaded": True,
    }
