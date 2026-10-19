# Project Contract

KerfGrid stores one JSON document with `format: "kerfgrid-project"` and
`format_version: 2`.

The active document is shared server state. SQLite stores its revision and
original DXF files. Browser caches never replace a newer server project
automatically. Up to 50 previous snapshots remain in the database; JSON
download/open is still available for portable backups.

KerfGrid has no pre-release compatibility promise. A contract change updates
`format_version` and may intentionally reject older project files; no migration
adapter is required until the product explicitly adopts that policy.

Required top-level data:

- `name`: job name.
- `sheet`: `width_mm` and `height_mm`. The full sheet is available for placement;
  there is no edge margin. Version 1 files still open: legacy `margin_mm` is
  ignored and removed on save, while existing placements keep their coordinates.
- `spacing_mm`: requested spacing between parts.
- `parts`: reusable part definitions with explicit contours.
- `placements`: instances on the active sheet.
- `cut`: material, thickness, nozzle, and feed selection.
- `post`: QtPlasmaC and toolpath settings.
- `simulation`: playback and rapid-rate settings.
- `nesting.layout_mode`: manual choice of `compact` (compact block from origin)
  or `strip` (minimum occupied height along X); omitted values retain `strip`.
- `import_options.auto_close_gaps` and `import_options.repair_geometry` default
  to `false`; normal import must not enable either option implicitly.

Each contour is either a `circle` or a `path`. A path owns ordered `line` and
`arc` segments. Open and self-intersecting paths are valid source data and are
not silently rewritten. Import diagnostics live with the project and remain
warnings.

Coordinates and all dimensions are millimetres. Angles are degrees. Instance
identity is the pair `(part_name, instance)`.

The Parts panel keeps quantity and deletion controls within the sidebar width.
“Очистить поле” clears parts, placements, zones, tabs, leads and derived job
previews in one undoable change. Sheet dimensions, cut settings and the server's
original-upload library are retained. The empty project persists in the shared
workspace; a late simulation response cannot restore a cleared preview.

Viewport zoom and pan are browser-local preferences, stored separately from the
shared project. Numeric zoom accepts 5–5000%; 100% fits the active Sheet or Parts
view. Wheel zoom keeps the world point under the cursor fixed. Hand mode (H),
middle-button drag and Space+left drag pan without changing placements or Undo.
Arrow keys pan while hand mode is active. Sheet/Parts reset scale and position;
fitting keeps geometry below the toolbar even when its controls wrap.
