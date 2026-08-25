"""Parse generated G-code into deterministic simulation events."""

from __future__ import annotations

import math
import re
from typing import Any


_WORD_RE = re.compile(r"([A-Z])([-+]?(?:\d+(?:\.\d*)?|\.\d+))")


def build_gcode_simulation(
    project: dict[str, Any],
    gcode: str,
    *,
    cut_feed_rate_mm_min: float,
    pierce_delay_s: float,
) -> dict[str, Any]:
    simulation = project.get("simulation", {})
    rapid_rate = float(simulation.get("rapid_rate_mm_min", 8000))
    if rapid_rate <= 0:
        raise ValueError("Simulation rapid rate must be positive")
    segments = segments_from_gcode(
        gcode,
        cut_feed_rate_mm_min=cut_feed_rate_mm_min,
        rapid_rate_mm_min=rapid_rate,
        pierce_delay_s=pierce_delay_s,
    )
    cut_s = sum(segment["duration_s"] for segment in segments if segment["type"] == "cut")
    rapid_s = sum(segment["duration_s"] for segment in segments if segment["type"] == "rapid")
    pierce_s = sum(segment["duration_s"] for segment in segments if segment["type"] == "pierce")
    return {
        "feed_rate_mm_min": cut_feed_rate_mm_min,
        "rapid_rate_mm_min": rapid_rate,
        "estimated_cut_s": round(cut_s, 3),
        "estimated_rapid_s": round(rapid_s, 3),
        "estimated_pierce_s": round(pierce_s, 3),
        "estimated_total_s": round(cut_s + rapid_s + pierce_s, 3),
        "segments": segments,
    }


def segments_from_gcode(
    gcode: str,
    *,
    cut_feed_rate_mm_min: float,
    rapid_rate_mm_min: float,
    pierce_delay_s: float = 0.0,
) -> list[dict[str, Any]]:
    current = {"x": 0.0, "y": 0.0}
    torch_on = False
    speed_percent = 100.0
    thc_disabled = False
    segments: list[dict[str, Any]] = []
    for raw_line in gcode.splitlines():
        code = _strip_comments(raw_line).strip().upper()
        if not code:
            continue
        words = _words(code)
        if "M" in words:
            m_code = int(words["M"])
            if m_code == 3:
                torch_on = True
                segments.append(
                    {
                        "type": "pierce",
                        "motion": "pierce",
                        "feed_rate_mm_min": 0,
                        "length_mm": 0,
                        "duration_s": round(max(0.0, pierce_delay_s), 4),
                        "speed_percent": round(speed_percent, 3),
                        "reduced_feed": speed_percent < 99.999,
                        "thc_disabled": thc_disabled,
                        "points": [{"x": round(current["x"], 4), "y": round(current["y"], 4)}],
                    }
                )
            elif m_code == 5:
                torch_on = False
            elif m_code == 64 and int(words.get("P", -1)) == 2:
                thc_disabled = True
            elif m_code == 65 and int(words.get("P", -1)) == 2:
                thc_disabled = False
            elif m_code == 67 and "Q" in words:
                speed_percent = float(words["Q"])
            elif m_code == 68 and "Q" in words:
                speed_percent = 100.0
        if "G" not in words:
            continue
        g_code = int(words["G"])
        if g_code not in (0, 1, 2, 3):
            continue
        target = {
            "x": float(words.get("X", current["x"])),
            "y": float(words.get("Y", current["y"])),
        }
        if g_code in (2, 3):
            center = {
                "x": current["x"] + float(words.get("I", 0.0)),
                "y": current["y"] + float(words.get("J", 0.0)),
            }
            points, length = _arc_points(current, target, center, clockwise=g_code == 2)
            motion = "arc_cw" if g_code == 2 else "arc_ccw"
        else:
            points = [current, target]
            length = _distance(current, target)
            motion = "line"
        segment_type = "cut" if torch_on and g_code != 0 else "rapid"
        feed_rate = cut_feed_rate_mm_min * speed_percent / 100.0 if segment_type == "cut" else rapid_rate_mm_min
        if length > 0:
            raw_lower = raw_line.lower()
            safe_travel_warning = segment_type == "rapid" and "warning: safe travel " in raw_lower
            segments.append(
                {
                    "type": segment_type,
                    "motion": motion,
                    "feed_rate_mm_min": round(feed_rate, 3),
                    "length_mm": round(length, 3),
                    "duration_s": round(length / feed_rate * 60.0, 4),
                    "speed_percent": round(speed_percent, 3),
                    "reduced_feed": segment_type == "cut" and speed_percent < 99.999,
                    "thc_disabled": thc_disabled,
                    "safe_travel": segment_type == "rapid" and "safe rapid" in raw_lower,
                    "safe_travel_warning": safe_travel_warning,
                    "safe_travel_warning_message": _extract_comment(raw_line) if safe_travel_warning else None,
                    "tab_bridge": segment_type == "rapid" and "tab bridge skip" in raw_lower,
                    "points": [{"x": round(point["x"], 4), "y": round(point["y"], 4)} for point in points],
                }
            )
        current = target
    return segments


def _extract_comment(line: str) -> str | None:
    start = line.find("(")
    end = line.rfind(")")
    return line[start + 1 : end].strip() if start >= 0 and end > start else None


def _strip_comments(line: str) -> str:
    return re.sub(r"\([^)]*\)", "", line)


def _words(code: str) -> dict[str, float]:
    return {match.group(1): float(match.group(2)) for match in _WORD_RE.finditer(code)}


def _arc_points(
    start: dict[str, float],
    end: dict[str, float],
    center: dict[str, float],
    *,
    clockwise: bool,
) -> tuple[list[dict[str, float]], float]:
    radius = _distance(start, center)
    if radius <= 0:
        return ([start, end], _distance(start, end))
    start_angle = math.atan2(start["y"] - center["y"], start["x"] - center["x"])
    end_angle = math.atan2(end["y"] - center["y"], end["x"] - center["x"])
    if clockwise:
        if end_angle >= start_angle:
            end_angle -= math.tau
    elif end_angle <= start_angle:
        end_angle += math.tau
    sweep = end_angle - start_angle
    length = abs(sweep) * radius
    steps = max(8, min(240, math.ceil(length / 4.0)))
    points = []
    for index in range(steps + 1):
        angle = start_angle + sweep * index / steps
        points.append(
            {
                "x": center["x"] + math.cos(angle) * radius,
                "y": center["y"] + math.sin(angle) * radius,
            }
        )
    return points, length


def _distance(left: dict[str, float], right: dict[str, float]) -> float:
    return math.hypot(left["x"] - right["x"], left["y"] - right["y"])
