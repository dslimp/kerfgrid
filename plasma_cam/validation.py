"""QtPlasmaC G-code validation before a file reaches the table."""

from __future__ import annotations

import re
from dataclasses import dataclass


_MOTION_RE = re.compile(r"(^|\s)G0?[0123](\s|$)")
_Z_WORD_RE = re.compile(r"(^|\s)Z[-+0-9.]")
_PLAIN_M3_RE = re.compile(r"(^|\s)M0?3(\s|$)")
_QTPLASMAC_M3_RE = re.compile(r"(^|\s)M0?3\s+\$0\s+S1(\s|$)")
_QTPLASMAC_M5_RE = re.compile(r"(^|\s)M0?5\s+\$0(\s|$)")
_CUTTER_COMP_RE = re.compile(r"(^|\s)G4[12]\.1(\s|$)")
_QTPLASMAC_MAGIC_COMMENT_MAX_LEN = 80


@dataclass(frozen=True)
class GCodeIssue:
    code: str
    message: str
    line_number: int | None = None
    line: str = ""


class GCodeValidationError(ValueError):
    def __init__(self, issues: list[GCodeIssue]):
        self.issues = issues
        message = "; ".join(issue.message for issue in issues)
        super().__init__(message)


def _strip_comment(line: str) -> str:
    return re.sub(r"\([^)]*\)", "", line).strip()


def validate_gcode(gcode: str, *, allow_z: bool = False) -> list[GCodeIssue]:
    lines = gcode.splitlines()
    issues: list[GCodeIssue] = []
    torch_on = False
    torch_starts = 0
    torch_stops = 0
    speed_reduction_active = False

    body = [_strip_comment(line) for line in lines]
    nonempty = [line for line in body if line]

    required = ["G90", "G17", "G40", "G64", "M52 P1", "M68 E3 Q0"]
    for token in required:
        if not any(token in line for line in nonempty):
            issues.append(GCodeIssue("missing_required_code", f"Missing required code: {token}"))

    if not any(line in ("G21", "G20") for line in nonempty):
        issues.append(GCodeIssue("missing_units", "Missing G20/G21 units declaration"))
    if nonempty and nonempty[-1] != "M2":
        issues.append(GCodeIssue("missing_program_end", "Program must end with M2"))

    for index, raw_line in enumerate(lines, start=1):
        if raw_line.lstrip().startswith("(o=") and len(raw_line) > _QTPLASMAC_MAGIC_COMMENT_MAX_LEN:
            issues.append(
                GCodeIssue(
                    "qtplasmac_magic_comment_too_long",
                    "QtPlasmaC magic comment must stay short enough for the LinuxCNC G-code filter",
                    index,
                    raw_line,
                )
            )

        line = _strip_comment(raw_line)
        if not line:
            continue

        if not allow_z and _MOTION_RE.search(line) and _Z_WORD_RE.search(line):
            issues.append(GCodeIssue("z_motion", "QtPlasmaC export must not contain Z motion", index, raw_line))

        if _CUTTER_COMP_RE.search(line):
            issues.append(
                GCodeIssue(
                    "cutter_compensation",
                    "QtPlasmaC export must use geometry kerf offsets instead of G41.1/G42.1",
                    index,
                    raw_line,
                )
            )

        if _PLAIN_M3_RE.search(line) and not _QTPLASMAC_M3_RE.search(line):
            issues.append(GCodeIssue("plain_m3", "Torch start must be M3 $0 S1", index, raw_line))

        if _QTPLASMAC_M3_RE.search(line):
            if torch_on:
                issues.append(GCodeIssue("torch_already_on", "Torch starts while already on", index, raw_line))
            torch_on = True
            torch_starts += 1

        if _QTPLASMAC_M5_RE.search(line):
            if not torch_on:
                issues.append(GCodeIssue("torch_already_off", "Torch stop occurs while torch is off", index, raw_line))
            torch_on = False
            torch_stops += 1

        if line.startswith("M67 E3 Q") and not line.endswith("Q0"):
            speed_reduction_active = True
        if line == "M68 E3 Q0":
            speed_reduction_active = False

    if torch_on:
        issues.append(GCodeIssue("torch_left_on", "Program ends with torch on"))
    if torch_starts != torch_stops:
        issues.append(
            GCodeIssue(
                "torch_balance",
                f"Torch starts/stops are unbalanced: {torch_starts}/{torch_stops}",
            )
        )
    if speed_reduction_active:
        issues.append(GCodeIssue("speed_reduction_left_on", "Program ends with velocity reduction active"))

    return issues


def assert_valid_gcode(gcode: str, *, allow_z: bool = False) -> None:
    issues = validate_gcode(gcode, allow_z=allow_z)
    if issues:
        raise GCodeValidationError(issues)
