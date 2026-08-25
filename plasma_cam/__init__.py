"""Standalone plasma CAM helpers for LinuxCNC QtPlasmaC."""

from .autonest import ShelfNestOptions, shelf_nest
from .cut_settings import CutSettings, format_qtplasmac_material_comment, select_cut_settings
from .model import ArcSegment, CircleContour, CutPlan, LineSegment, PartProfile, PathContour, Point
from .nesting import ArraySpec, Sheet, array_nest, assert_within_sheet
from .post import QtPlasmaCOptions, generate_gcode, write_gcode
from .project import (
    LayoutValidationError,
    NestedLayout,
    PartRequest,
    Placement,
    PlacedPart,
    assert_valid_layout,
    generate_layout_gcode,
    move_part,
    rotate_part,
    validate_layout,
)
from .validation import GCodeValidationError, assert_valid_gcode, validate_gcode

__all__ = [
    "ArraySpec",
    "ArcSegment",
    "CircleContour",
    "CutPlan",
    "CutSettings",
    "GCodeValidationError",
    "LineSegment",
    "LayoutValidationError",
    "NestedLayout",
    "PartProfile",
    "PartRequest",
    "PathContour",
    "PlacedPart",
    "Placement",
    "Point",
    "QtPlasmaCOptions",
    "ShelfNestOptions",
    "Sheet",
    "array_nest",
    "assert_valid_layout",
    "assert_valid_gcode",
    "assert_within_sheet",
    "format_qtplasmac_material_comment",
    "generate_layout_gcode",
    "generate_gcode",
    "move_part",
    "rotate_part",
    "select_cut_settings",
    "shelf_nest",
    "validate_layout",
    "validate_gcode",
    "write_gcode",
]
