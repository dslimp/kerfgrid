# Geometry Contract

- DXF entities are converted to explicit millimetre geometry without changing
  the visible path.
- Normal import never edits source topology: no automatic gap closure, duplicate
  removal, tiny-segment removal, retrace cleanup, simplification, or repair retry.
- Repair is a separate opt-in operation and must present the operator with a
  before/after result. The browser and FreeCAD import paths do not enable it.
- Closed contours may receive kerf compensation. If compensation collapses or
  splits, the configured centerline fallback keeps the original visible path.
- Open, self-touching, and self-intersecting paths are centerline cuts.
- Diagnostics identify the affected path segment in the UI; they do not replace
  the contour with marker noise or hide the contour.
- Holes are rendered as holes in the part fill, while source contour strokes
  remain visible.
- The backend is authoritative for export and simulation geometry.
