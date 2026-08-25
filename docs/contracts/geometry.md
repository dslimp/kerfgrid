# Geometry Contract

- DXF entities are converted to explicit millimetre geometry without changing
  the visible path.
- Closed contours may receive kerf compensation. If compensation collapses or
  splits, the configured centerline fallback keeps the original visible path.
- Open, self-touching, and self-intersecting paths are centerline cuts.
- Diagnostics identify the affected path segment in the UI; they do not replace
  the contour with marker noise or hide the contour.
- Holes are rendered as holes in the part fill, while source contour strokes
  remain visible.
- The backend is authoritative for export and simulation geometry.
