"""Basic placement and sheet-bound checks for plasma parts."""

from __future__ import annotations

from dataclasses import dataclass

from .model import CircleContour, PartProfile, bbox_for_contours


@dataclass(frozen=True)
class Sheet:
    width: float
    height: float
    margin: float = 0.0


@dataclass(frozen=True)
class ArraySpec:
    rows: int
    columns: int
    spacing_x: float
    spacing_y: float
    origin_x: float = 0.0
    origin_y: float = 0.0
    rotation_deg: float = 0.0


def array_nest(part: PartProfile, spec: ArraySpec) -> tuple[CircleContour, ...]:
    if spec.rows < 1 or spec.columns < 1:
        raise ValueError("Array rows and columns must be positive")

    contours = []
    for row in range(spec.rows):
        for column in range(spec.columns):
            prefix = f"{part.name}_r{row + 1}_c{column + 1}_"
            dx = spec.origin_x + column * spec.spacing_x
            dy = spec.origin_y + row * spec.spacing_y
            for contour in part.contours:
                contours.append(
                    contour.transformed(
                        dx=dx,
                        dy=dy,
                        rotation_deg=spec.rotation_deg,
                        name_prefix=prefix,
                    )
                )
    return tuple(contours)


def assert_within_sheet(contours: tuple[CircleContour, ...], sheet: Sheet) -> None:
    xmin, ymin, xmax, ymax = bbox_for_contours(contours)
    min_x = sheet.margin
    min_y = sheet.margin
    max_x = sheet.width - sheet.margin
    max_y = sheet.height - sheet.margin

    errors = []
    if xmin < min_x:
        errors.append(f"xmin {xmin:.3f} < sheet margin {min_x:.3f}")
    if ymin < min_y:
        errors.append(f"ymin {ymin:.3f} < sheet margin {min_y:.3f}")
    if xmax > max_x:
        errors.append(f"xmax {xmax:.3f} > sheet usable width {max_x:.3f}")
    if ymax > max_y:
        errors.append(f"ymax {ymax:.3f} > sheet usable height {max_y:.3f}")
    if errors:
        raise ValueError("; ".join(errors))
