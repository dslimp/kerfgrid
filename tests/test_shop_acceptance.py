from __future__ import annotations

import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from tools import shop_acceptance


def test_shop_acceptance_default_steps_are_focused_gate() -> None:
    args = shop_acceptance.parse_args([])
    steps = shop_acceptance.build_steps(args)

    assert [step.name for step in steps] == [
        "unit",
        "focused-real-dxf-pytest",
        "focused-real-dxf-artifact",
    ]
    assert ("PLASMA_CAM_RUN_FOCUSED_DXF_CORPUS", "1") in steps[1].env

    artifact_command = " ".join(steps[2].command)
    assert "tools/dxf_corpus_check.py" in artifact_command
    assert "--require-auto-nest-for-exportable" in steps[2].command
    assert "--max-auto-nest-runtime" in steps[2].command
    assert "5.0" in steps[2].command
    focused_count = str(len(shop_acceptance.FOCUSED_DXF_RELATIVE_PATHS))
    assert "models/_extracted/Jedi__ornament5.1/Jedi  ornament5.1.dxf" in artifact_command
    for option in (
        "--min-files",
        "--min-completed-files",
        "--min-import-ok",
        "--min-auto-nest-ok",
        "--min-export-ok",
        "--min-simulation-ok",
    ):
        assert steps[2].command[steps[2].command.index(option) + 1] == focused_count
    assert "output/dxf-corpus/latest-focused-auto-nest.json" in steps[2].command
    assert "output/dxf-corpus/latest-focused-auto-nest.md" in steps[2].command
    assert not any("playwright" in " ".join(step.command) for step in steps)


def test_shop_acceptance_can_add_browser_and_visual_smoke() -> None:
    args = shop_acceptance.parse_args(["--browser", "--visual", "--real-dxf-ui", "--url", "http://127.0.0.1:8765/"])
    steps = shop_acceptance.build_steps(args)

    assert [step.name for step in steps[-3:]] == ["browser-smoke", "visual-smoke", "real-dxf-ui-smoke"]
    assert steps[-3].command == ("tests/playwright_smoke.sh",)
    assert steps[-2].command == ("tests/playwright_visual_smoke.sh",)
    assert steps[-1].command == ("tests/playwright_real_dxf_smoke.sh",)
    assert ("PLASMA_CAM_URL", "http://127.0.0.1:8765/") in steps[-3].env
    assert ("PLASMA_CAM_URL", "http://127.0.0.1:8765/") in steps[-2].env
    assert ("PLASMA_CAM_URL", "http://127.0.0.1:8765/") in steps[-1].env


def test_shop_acceptance_can_add_full_warning_only_corpus_gate() -> None:
    args = shop_acceptance.parse_args(["--full-corpus"])
    steps = shop_acceptance.build_steps(args)

    assert [step.name for step in steps] == [
        "unit",
        "focused-real-dxf-pytest",
        "focused-real-dxf-artifact",
        "full-real-dxf-corpus",
    ]
    command = steps[-1].command
    command_text = " ".join(command)
    assert "tools/dxf_corpus_check.py" in command_text
    assert "/Users/user/Documents/dxf" in command
    assert "--unsafe-entity-policy" in command
    assert command[command.index("--unsafe-entity-policy") + 1] == "warn"
    assert "--auto-nest" in command
    assert "--open-path-centerline" in command
    assert "--centerline-fallback" in command
    assert "--require-auto-nest-placements" in command
    assert "--require-auto-nest-for-exportable" in command
    assert command[command.index("--min-files") + 1] == "121"
    assert command[command.index("--min-auto-nest-ok") + 1] == "121"
    assert command[command.index("--min-export-ok") + 1] == "121"
    assert command[command.index("--min-simulation-ok") + 1] == "121"
    assert command[command.index("--max-auto-nest-runtime") + 1] == "4.0"
    assert "output/dxf-corpus/latest-current-warning-only.json" in command
    assert "output/dxf-corpus/latest-current-warning-only.md" in command


def test_shop_acceptance_list_mode_prints_commands(capsys) -> None:
    rc = shop_acceptance.main(
        [
            "--skip-unit",
            "--skip-focused-pytest",
            "--skip-focused-artifact",
            "--browser",
            "--url",
            "http://x/",
            "--list",
        ]
    )

    assert rc == 0
    captured = capsys.readouterr()
    assert "browser-smoke:" in captured.out
    assert "PLASMA_CAM_URL=http://x/" in captured.out
    assert "playwright_smoke.sh" in captured.out


def test_shop_acceptance_managed_server_list_mode_does_not_bind_auto_port(monkeypatch, capsys) -> None:
    def fail_free_port(host):  # type: ignore[no-untyped-def]
        raise AssertionError("list mode must not bind a port")

    monkeypatch.setattr(shop_acceptance, "free_local_port", fail_free_port)
    rc = shop_acceptance.main(
        [
            "--skip-unit",
            "--skip-focused-pytest",
            "--skip-focused-artifact",
            "--managed-server",
            "--browser",
            "--list",
        ]
    )

    assert rc == 0
    captured = capsys.readouterr()
    assert "browser-smoke:" in captured.out
    assert "PLASMA_CAM_URL='http://127.0.0.1:<auto>/'" in captured.out


def test_shop_acceptance_managed_server_runs_browser_steps_against_fresh_backend(monkeypatch, capsys) -> None:
    events = []

    class FakeLog:
        def close(self):
            events.append(("close-log",))

    class FakeProcess:
        pass

    process = FakeProcess()

    def fake_start(host, port):  # type: ignore[no-untyped-def]
        events.append(("start", host, port))
        return process, FakeLog()

    def fake_wait(url, timeout_s):  # type: ignore[no-untyped-def]
        events.append(("wait", url, timeout_s))

    def fake_stop(received_process):  # type: ignore[no-untyped-def]
        events.append(("stop", received_process is process))

    def fake_run(command, cwd, env):  # type: ignore[no-untyped-def]
        events.append(("run", command, env.get("PLASMA_CAM_URL")))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(shop_acceptance, "free_local_port", lambda host: 8877)
    monkeypatch.setattr(shop_acceptance, "start_server_process", fake_start)
    monkeypatch.setattr(shop_acceptance, "wait_for_server", fake_wait)
    monkeypatch.setattr(shop_acceptance, "stop_server_process", fake_stop)
    monkeypatch.setattr(shop_acceptance.subprocess, "run", fake_run)

    rc = shop_acceptance.main(
        [
            "--skip-unit",
            "--skip-focused-pytest",
            "--skip-focused-artifact",
            "--managed-server",
            "--browser",
        ]
    )

    assert rc == 0
    captured = capsys.readouterr()
    assert "KerfGrid shop acceptance passed." in captured.out
    assert events[0] == ("start", "127.0.0.1", 8877)
    assert events[1] == ("wait", "http://127.0.0.1:8877/", 10.0)
    assert events[2] == (("run", ("tests/playwright_smoke.sh",), "http://127.0.0.1:8877/"))
    assert events[3] == ("stop", True)
    assert events[4] == ("close-log",)


def test_shop_acceptance_stops_on_first_failure(monkeypatch, capsys) -> None:
    def fail_run(command, cwd, env):  # type: ignore[no-untyped-def]
        assert command == (sys.executable, "-m", "pytest", "-q", "tests")
        assert cwd == shop_acceptance.REPO_ROOT
        assert env["PATH"]
        return subprocess.CompletedProcess(command, 42)

    monkeypatch.setattr(shop_acceptance.subprocess, "run", fail_run)

    rc = shop_acceptance.main(["--skip-focused-pytest", "--skip-focused-artifact"])

    assert rc == 42
    captured = capsys.readouterr()
    assert "Acceptance failed at unit with exit code 42" in captured.err
