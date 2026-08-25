#!/usr/bin/env python3
"""Run KerfGrid shop acceptance gates."""

from __future__ import annotations

import argparse
import contextlib
import os
import shlex
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT
DEFAULT_DXF_ROOT = Path(os.environ.get("PLASMA_CAM_REAL_DXF_CORPUS_ROOT", "/Users/user/Documents/dxf"))
DEFAULT_URL = "http://127.0.0.1:8765/"

FOCUSED_DXF_RELATIVE_PATHS = (
    "2/Malenkiy_mangal.dxf",
    "2/medved_kamin.dxf",
    "models/_extracted/mangal_bear/2mm_2.dxf",
    "models/_extracted/mangal_bear/4mm.dxf",
    "models/_extracted/Jedi__ornament5.1/Jedi  ornament5.1.dxf",
    "models/_extracted/Новая_папка/Новая папка/Kugeln novyj God.dxf",
    "models/_extracted/Новая_папка/Новая папка/Жирафы.dxf",
    "models/_extracted/Новая_папка/Новая папка/картина мишка в лесу.dxf",
)


@dataclass(frozen=True)
class AcceptanceStep:
    name: str
    command: tuple[str, ...]
    env: tuple[tuple[str, str], ...] = ()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run KerfGrid shop acceptance gates")
    parser.add_argument("--focused-root", type=Path, default=DEFAULT_DXF_ROOT)
    parser.add_argument("--full-corpus-root", type=Path, default=DEFAULT_DXF_ROOT)
    parser.add_argument("--auto-nest-timeout", type=float, default=2.0)
    parser.add_argument("--per-file-timeout", type=float, default=15.0)
    parser.add_argument("--max-auto-nest-runtime", type=float, default=5.0)
    parser.add_argument("--full-auto-nest-timeout", type=float, default=4.0)
    parser.add_argument("--full-per-file-timeout", type=float, default=30.0)
    parser.add_argument("--full-max-auto-nest-runtime", type=float, default=4.0)
    parser.add_argument("--full-min-files", type=int, default=121)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--full-corpus", action="store_true", help="also run the long full local DXF corpus gate")
    parser.add_argument("--browser", action="store_true", help="also run Playwright UI smoke against --url")
    parser.add_argument("--visual", action="store_true", help="also run visual Playwright smoke against --url")
    parser.add_argument("--real-dxf-ui", action="store_true", help="also run real DXF Playwright UI smoke against --url")
    parser.add_argument("--managed-server", action="store_true", help="start a fresh local server for browser smoke steps")
    parser.add_argument("--managed-server-host", default="127.0.0.1")
    parser.add_argument("--managed-server-port", type=int, default=0)
    parser.add_argument("--managed-server-timeout", type=float, default=10.0)
    parser.add_argument("--skip-unit", action="store_true")
    parser.add_argument("--skip-focused-pytest", action="store_true")
    parser.add_argument("--skip-focused-artifact", action="store_true")
    parser.add_argument("--list", action="store_true", help="print commands without running them")
    return parser.parse_args(argv)


def build_steps(args: argparse.Namespace) -> list[AcceptanceStep]:
    steps: list[AcceptanceStep] = []
    if not args.skip_unit:
        steps.append(
            AcceptanceStep(
                "unit",
                (sys.executable, "-m", "pytest", "-q", "tests"),
            )
        )
    if not args.skip_focused_pytest:
        steps.append(
            AcceptanceStep(
                "focused-real-dxf-pytest",
                (sys.executable, "-m", "pytest", "-q", "tests/test_focused_real_dxf_acceptance.py"),
                (("PLASMA_CAM_RUN_FOCUSED_DXF_CORPUS", "1"),),
            )
        )
    if not args.skip_focused_artifact:
        steps.append(focused_artifact_step(args))
    if args.full_corpus:
        steps.append(full_corpus_step(args))
    if args.browser:
        steps.append(
            AcceptanceStep(
                "browser-smoke",
                ("tests/playwright_smoke.sh",),
                (("PLASMA_CAM_URL", str(args.url)),),
            )
        )
    if args.visual:
        steps.append(
            AcceptanceStep(
                "visual-smoke",
                ("tests/playwright_visual_smoke.sh",),
                (("PLASMA_CAM_URL", str(args.url)),),
            )
        )
    if args.real_dxf_ui:
        steps.append(
            AcceptanceStep(
                "real-dxf-ui-smoke",
                ("tests/playwright_real_dxf_smoke.sh",),
                (("PLASMA_CAM_URL", str(args.url)),),
            )
        )
    return steps


def browser_steps_requested(args: argparse.Namespace) -> bool:
    return bool(args.browser or args.visual or args.real_dxf_ui)


def focused_artifact_step(args: argparse.Namespace) -> AcceptanceStep:
    focused_paths = [str(args.focused_root / relative) for relative in FOCUSED_DXF_RELATIVE_PATHS]
    focused_count = str(len(focused_paths))
    command = (
        sys.executable,
        "tools/dxf_corpus_check.py",
        *focused_paths,
        "--auto-close-gaps",
        "--auto-nest",
        "--auto-nest-timeout",
        str(args.auto_nest_timeout),
        "--centerline-fallback",
        "--open-path-centerline",
        "--per-file-timeout",
        str(args.per_file_timeout),
        "--diagnostic-top",
        "20",
        "--quiet",
        "--output",
        "output/dxf-corpus/latest-focused-auto-nest.json",
        "--markdown-output",
        "output/dxf-corpus/latest-focused-auto-nest.md",
        "--require-complete",
        "--min-files",
        focused_count,
        "--min-completed-files",
        focused_count,
        "--min-import-ok",
        focused_count,
        "--min-auto-nest-ok",
        focused_count,
        "--min-export-ok",
        focused_count,
        "--min-simulation-ok",
        focused_count,
        "--max-auto-nest-runtime",
        str(args.max_auto_nest_runtime),
        "--require-auto-nest-placements",
        "--require-auto-nest-for-exportable",
        "--max-timeouts",
        "0",
        "--forbid-validation-blocking-code",
        "import_open_contour",
        "--forbid-validation-blocking-code",
        "small_feature_below_kerf",
    )
    return AcceptanceStep("focused-real-dxf-artifact", command)


def full_corpus_step(args: argparse.Namespace) -> AcceptanceStep:
    full_count = str(args.full_min_files)
    command = (
        sys.executable,
        "tools/dxf_corpus_check.py",
        str(args.full_corpus_root),
        "--auto-close-gaps",
        "--auto-nest",
        "--auto-nest-timeout",
        str(args.full_auto_nest_timeout),
        "--centerline-fallback",
        "--open-path-centerline",
        "--unsafe-entity-policy",
        "warn",
        "--per-file-timeout",
        str(args.full_per_file_timeout),
        "--diagnostic-top",
        "50",
        "--quiet",
        "--output",
        "output/dxf-corpus/latest-current-warning-only.json",
        "--markdown-output",
        "output/dxf-corpus/latest-current-warning-only.md",
        "--require-complete",
        "--min-files",
        full_count,
        "--min-completed-files",
        full_count,
        "--min-import-ok",
        full_count,
        "--min-auto-nest-ok",
        full_count,
        "--min-export-ok",
        full_count,
        "--min-simulation-ok",
        full_count,
        "--max-auto-nest-runtime",
        str(args.full_max_auto_nest_runtime),
        "--require-auto-nest-placements",
        "--require-auto-nest-for-exportable",
        "--max-timeouts",
        "0",
        "--forbid-validation-blocking-code",
        "import_open_contour",
        "--forbid-validation-blocking-code",
        "small_feature_below_kerf",
    )
    return AcceptanceStep("full-real-dxf-corpus", command)


def run_step(step: AcceptanceStep) -> int:
    env = os.environ.copy()
    env.update(dict(step.env))
    print(f"==> {step.name}")
    print(command_text(step))
    completed = subprocess.run(step.command, cwd=REPO_ROOT, env=env)
    return completed.returncode


@contextlib.contextmanager
def managed_server(args: argparse.Namespace):
    if not args.managed_server or not browser_steps_requested(args):
        yield str(args.url)
        return
    url, host, port = managed_server_url(args)
    process, log_handle = start_server_process(host, port)
    try:
        wait_for_server(url, timeout_s=float(args.managed_server_timeout))
        yield url
    finally:
        stop_server_process(process)
        log_handle.close()


def managed_server_url(args: argparse.Namespace, *, allocate_port: bool = True) -> tuple[str, str, int]:
    host = str(args.managed_server_host)
    port = int(args.managed_server_port)
    if port <= 0 and allocate_port:
        port = free_local_port(host)
    port_text = str(port) if port > 0 else "<auto>"
    return f"http://{host}:{port_text}/", host, port


def free_local_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def start_server_process(host: str, port: int):
    log_dir = PROJECT_ROOT / "output"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"server-managed-{port}.log"
    log_handle = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        (sys.executable, "server.py", "--host", host, "--port", str(port)),
        cwd=REPO_ROOT,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return process, log_handle


def wait_for_server(url: str, *, timeout_s: float) -> None:
    deadline = time.monotonic() + max(0.1, timeout_s)
    readiness_url = f"{url.rstrip('/')}/api/example"
    last_error = ""
    while time.monotonic() < deadline:
        try:
            with urlopen(readiness_url, timeout=0.5) as response:
                if int(response.status) == 200:
                    return
        except URLError as exc:
            last_error = str(exc)
        except TimeoutError as exc:
            last_error = str(exc)
        time.sleep(0.1)
    raise RuntimeError(f"Managed KerfGrid server did not become ready at {readiness_url}: {last_error}")


def stop_server_process(process) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def command_text(step: AcceptanceStep) -> str:
    prefix = " ".join(f"{key}={shlex.quote(value)}" for key, value in step.env)
    command = shlex.join(step.command)
    return f"{prefix} {command}".strip()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.list and args.managed_server and browser_steps_requested(args):
        args.url = managed_server_url(args, allocate_port=False)[0]
    steps = build_steps(args)
    if args.list:
        for step in steps:
            print(f"{step.name}: {command_text(step)}")
        return 0
    with managed_server(args) as url:
        args.url = url
        steps = build_steps(args)
        for step in steps:
            rc = run_step(step)
            if rc:
                print(f"Acceptance failed at {step.name} with exit code {rc}", file=sys.stderr)
                return rc
    print("KerfGrid shop acceptance passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
