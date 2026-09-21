"""LinuxCNC transfer service."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence


_SAFE_ENDPOINT_RE = re.compile(r"^[A-Za-z0-9_.:@-]+$")
_UPLOAD_OK_MARKER = "__KERFGRID_UPLOAD_OK__"
_OWNER_WARN_MARKER = "__KERFGRID_OWNER_WARN__"
_REMOTE_UPLOAD_SCRIPT = r"""
import json
import os
import sys

remote_dir = sys.argv[1]
payload = json.load(sys.stdin)
os.makedirs(remote_dir, exist_ok=True)
for item in payload["files"]:
    filename = item["filename"]
    if not filename or "/" in filename or filename in {".", ".."}:
        raise SystemExit(f"bad filename: {filename}")
    path = os.path.join(remote_dir, filename)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(item["gcode"])
print("__KERFGRID_UPLOAD_OK__")
"""


@dataclass(frozen=True)
class LinuxCNCTransferConfig:
    host: str = "192.168.64.5"
    port: int = 22
    user: str = "root"
    remote_dir: str = "/home/linuxcnc/linuxcnc/nc_files/kerfgrid"
    key_path: str = "~/.ssh/id_rsa"
    owner: str = "linuxcnc:linuxcnc"
    timeout_s: float = 30.0
    control_persist_s: int = 300
    control_path: str = "/tmp/kerfgrid-linuxcnc-%r@%h:%p"
    load_command: str = (
        "runuser -u linuxcnc -- python3 -c "
        "'import linuxcnc,sys; path=sys.argv[1]; c=linuxcnc.command(); "
        "c.program_open(path); c.wait_complete(); s=linuxcnc.stat(); s.poll(); "
        "print(s.file); raise SystemExit(0 if s.file == path else 1)' {remote_path}"
    )


@dataclass(frozen=True)
class LinuxCNCGCodeFile:
    filename: str
    gcode: str


def config_from_env(env: dict[str, str] | None = None) -> LinuxCNCTransferConfig:
    source = os.environ if env is None else env
    return LinuxCNCTransferConfig(
        host=source.get("KERFGRID_LINUXCNC_HOST", LinuxCNCTransferConfig.host),
        port=_positive_int(source.get("KERFGRID_LINUXCNC_PORT"), LinuxCNCTransferConfig.port),
        user=source.get("KERFGRID_LINUXCNC_USER", LinuxCNCTransferConfig.user),
        remote_dir=source.get("KERFGRID_LINUXCNC_REMOTE_DIR", LinuxCNCTransferConfig.remote_dir),
        key_path=source.get("KERFGRID_LINUXCNC_KEY", LinuxCNCTransferConfig.key_path),
        owner=source.get("KERFGRID_LINUXCNC_OWNER", LinuxCNCTransferConfig.owner),
        timeout_s=_positive_float(source.get("KERFGRID_LINUXCNC_TIMEOUT_S"), LinuxCNCTransferConfig.timeout_s),
        control_persist_s=_non_negative_int(
            source.get("KERFGRID_LINUXCNC_CONTROL_PERSIST_S"),
            LinuxCNCTransferConfig.control_persist_s,
        ),
        control_path=source.get("KERFGRID_LINUXCNC_CONTROL_PATH", LinuxCNCTransferConfig.control_path),
        load_command=source.get("KERFGRID_LINUXCNC_LOAD_COMMAND", LinuxCNCTransferConfig.load_command),
    )


def send_gcode_to_linuxcnc(
    *,
    filename: str,
    gcode: str,
    config: LinuxCNCTransferConfig | None = None,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
) -> dict[str, object]:
    result = send_gcode_bundle_to_linuxcnc(
        files=(LinuxCNCGCodeFile(filename=filename, gcode=gcode),),
        load_filename=filename,
        config=config,
        run=run,
        which=which,
    )
    uploaded_file = result["files"][0]
    return {
        "remote_path": uploaded_file["remote_path"],
        "byte_count": uploaded_file["byte_count"],
        "warnings": result["warnings"],
        "uploaded": result["uploaded"],
        "loaded": result["loaded"],
        "load_error": result["load_error"],
        "host": result["host"],
        "port": result["port"],
        "user": result["user"],
    }


def send_gcode_bundle_to_linuxcnc(
    *,
    files: Sequence[LinuxCNCGCodeFile],
    load_filename: str,
    config: LinuxCNCTransferConfig | None = None,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
) -> dict[str, object]:
    transfer_config = config or config_from_env()
    _validate_config(transfer_config)
    ssh_bin = which("ssh")
    if ssh_bin is None:
        raise RuntimeError("LinuxCNC transfer requires `ssh` in PATH")

    prepared_files = _prepare_gcode_files(files, transfer_config.remote_dir)
    safe_load_filename = _safe_ngc_filename(load_filename)
    remote_path = f"{transfer_config.remote_dir.rstrip('/')}/{safe_load_filename}"
    if safe_load_filename not in {item["filename"] for item in prepared_files}:
        raise ValueError("LinuxCNC load filename must match an uploaded file")
    warnings: list[str] = []
    load_error: str | None = None
    payload = json.dumps({"files": prepared_files}, ensure_ascii=False)
    key_path = str(Path(transfer_config.key_path).expanduser())

    completed = _run_transfer_command(
        _ssh_command(
            ssh_bin,
            transfer_config,
            key_path,
            _upload_bundle_and_load_command(transfer_config, remote_path, prepared_files),
        ),
        payload=payload,
        run=run,
        timeout_s=transfer_config.timeout_s,
    )
    output = f"{completed.stdout or ''}\n{completed.stderr or ''}"
    uploaded = _UPLOAD_OK_MARKER in output
    if _OWNER_WARN_MARKER in output:
        warnings.append("Uploaded, but owner change failed")
    if completed.returncode == 0:
        loaded = True
    elif uploaded:
        loaded = False
        load_error = _completed_detail(completed) or "LinuxCNC load command failed"
    else:
        raise RuntimeError(_completed_detail(completed) or "LinuxCNC upload command failed")

    return {
        "remote_path": remote_path,
        "byte_count": sum(item["byte_count"] for item in prepared_files),
        "files": [
            {
                "filename": item["filename"],
                "remote_path": item["remote_path"],
                "byte_count": item["byte_count"],
            }
            for item in prepared_files
        ],
        "warnings": warnings,
        "uploaded": uploaded,
        "loaded": loaded,
        "load_error": load_error,
        "host": transfer_config.host,
        "port": transfer_config.port,
        "user": transfer_config.user,
    }


def _ssh_command(ssh_bin: str, config: LinuxCNCTransferConfig, key_path: str, remote_command: str) -> list[str]:
    command = [
        ssh_bin,
        "-p",
        str(config.port),
        "-i",
        key_path,
        "-o",
        "BatchMode=yes",
        "-o",
        "IdentitiesOnly=yes",
    ]
    if config.control_persist_s > 0:
        command.extend(
            [
                "-o",
                "ControlMaster=auto",
                "-o",
                f"ControlPersist={config.control_persist_s}",
                "-o",
                f"ControlPath={config.control_path}",
            ]
        )
    command.extend([f"{config.user}@{config.host}", remote_command])
    return command


def _run_transfer_command(
    command: Sequence[str],
    *,
    payload: str,
    run: Callable[..., subprocess.CompletedProcess],
    timeout_s: float,
) -> subprocess.CompletedProcess:
    try:
        return run(command, input=payload, capture_output=True, text=True, timeout=timeout_s)
    except FileNotFoundError as exc:
        raise RuntimeError(f"LinuxCNC transfer command not found: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"LinuxCNC transfer command timed out: {command[0]}") from exc


def _completed_detail(completed: subprocess.CompletedProcess) -> str:
    return (completed.stderr or completed.stdout or "").strip()


def _prepare_gcode_files(files: Sequence[LinuxCNCGCodeFile], remote_dir: str) -> list[dict[str, object]]:
    if not files:
        raise ValueError("LinuxCNC transfer requires at least one G-code file")
    prepared: list[dict[str, object]] = []
    seen: set[str] = set()
    for file in files:
        safe_filename = _safe_ngc_filename(file.filename)
        if safe_filename in seen:
            raise ValueError(f"Duplicate LinuxCNC upload filename: {safe_filename}")
        seen.add(safe_filename)
        encoded = file.gcode.encode("utf-8")
        prepared.append(
            {
                "filename": safe_filename,
                "gcode": file.gcode,
                "remote_path": f"{remote_dir.rstrip('/')}/{safe_filename}",
                "byte_count": len(encoded),
            }
        )
    return prepared


def _upload_bundle_and_load_command(
    config: LinuxCNCTransferConfig,
    remote_path: str,
    prepared_files: Sequence[dict[str, object]],
) -> str:
    chown_command = ":"
    if config.user == "root" and config.owner:
        remote_paths = " ".join(shlex.quote(str(item["remote_path"])) for item in prepared_files)
        chown_command = (
            f"chown {shlex.quote(config.owner)} -- {remote_paths} "
            f"|| printf '%s\\n' {_OWNER_WARN_MARKER!r}"
        )
    upload_command = f"python3 -c {shlex.quote(_REMOTE_UPLOAD_SCRIPT)} {shlex.quote(config.remote_dir)}"
    return "\n".join(
        [
            "set -eu",
            "umask 022",
            f"mkdir -p -- {shlex.quote(config.remote_dir)}",
            upload_command,
            chown_command,
            _load_command(config, remote_path),
        ]
    )


def _load_command(config: LinuxCNCTransferConfig, remote_path: str) -> str:
    if not config.load_command.strip():
        raise RuntimeError("LinuxCNC load command is empty")
    return config.load_command.format(remote_path=shlex.quote(remote_path))


def _safe_ngc_filename(filename: str) -> str:
    stem = Path(filename or "kerfgrid_job.ngc").name
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._")
    if not safe:
        safe = "kerfgrid_job.ngc"
    if not safe.lower().endswith(".ngc"):
        safe = f"{safe}.ngc"
    return safe


def _positive_int(value: str | None, default: int) -> int:
    if value is None or value == "":
        return default
    parsed = int(value)
    if parsed <= 0:
        raise ValueError("LinuxCNC port must be positive")
    return parsed


def _non_negative_int(value: str | None, default: int) -> int:
    if value is None or value == "":
        return default
    parsed = int(value)
    if parsed < 0:
        raise ValueError("LinuxCNC ControlPersist must be non-negative")
    return parsed


def _positive_float(value: str | None, default: float) -> float:
    if value is None or value == "":
        return default
    parsed = float(value)
    if parsed <= 0:
        raise ValueError("LinuxCNC timeout must be positive")
    return parsed


def _validate_config(config: LinuxCNCTransferConfig) -> None:
    if not _SAFE_ENDPOINT_RE.match(config.host):
        raise ValueError("LinuxCNC host contains unsupported characters")
    if not _SAFE_ENDPOINT_RE.match(config.user):
        raise ValueError("LinuxCNC user contains unsupported characters")
    if not config.remote_dir.startswith("/"):
        raise ValueError("LinuxCNC remote directory must be an absolute path")
