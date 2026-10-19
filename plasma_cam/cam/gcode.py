"""Shared G-code formatting helpers."""

from __future__ import annotations

from .options import QtPlasmaCOptions


def format_number(value: float, precision: int) -> str:
    text = f"{value:.{precision}f}"
    if precision > 0:
        text = text.rstrip("0").rstrip(".")
    if text == "-0":
        return "0"
    return text or "0"


def gcode_line(code: str, comment: str | None, options: QtPlasmaCOptions) -> str:
    if comment and options.include_comments:
        return f"{code} ({comment_text(comment)})"
    return code


def comment_text(value: object) -> str:
    return " ".join(str(value).replace("(", " ").replace(")", " ").split())
