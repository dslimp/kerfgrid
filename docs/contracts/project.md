# Project Contract

KerfGrid stores one JSON document with `format: "kerfgrid-project"` and
`format_version: 1`.

KerfGrid has no pre-release compatibility promise. A contract change updates
`format_version` and may intentionally reject older project files; no migration
adapter is required until the product explicitly adopts that policy.

Required top-level data:

- `name`: job name.
- `sheet`: `width_mm`, `height_mm`, and `margin_mm`.
- `spacing_mm`: requested spacing between parts.
- `parts`: reusable part definitions with explicit contours.
- `placements`: instances on the active sheet.
- `cut`: material, thickness, nozzle, and feed selection.
- `post`: QtPlasmaC and toolpath settings.
- `simulation`: playback and rapid-rate settings.

Each contour is either a `circle` or a `path`. A path owns ordered `line` and
`arc` segments. Open and self-intersecting paths are valid source data and are
not silently rewritten. Import diagnostics live with the project and remain
warnings.

Coordinates and all dimensions are millimetres. Angles are degrees. Instance
identity is the pair `(part_name, instance)`.
