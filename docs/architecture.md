# Architecture

KerfGrid is a local-first application with one authoritative Python geometry
pipeline. The browser edits project state and displays backend results; it does
not own a second CAM implementation.

## Dependency Direction

```text
web -> HTTP -> application -> domain/importers/nesting/cam -> post
```

Lower layers do not import `server.py`, browser code, or application services.

## Python Packages

```text
plasma_cam/
  model.py                 geometry value objects
  project.py               requests, placements, layouts
  autonest.py              nesting search and scoring
  cut_settings.py          versioned cut-chart selection
  importers/dxf.py         DXF reader and import diagnostics
  application/
    project_store.py       project JSON files
    project_codec.py       JSON/domain conversion
    gcode_simulation.py    G-code event parser
  cam/
    geometry.py            shared predicates
    kerf.py                closed-contour compensation
    options.py             immutable CAM settings and records
  post.py                  QtPlasmaC orchestration and output
  validation.py            G-code structural checks
```

`web_api.py` currently remains the application composition root for nesting,
validation, review, and export. New behavior must go into an owning service or
CAM module first; the adapter should only compose those calls. The remaining
large DXF, nesting, post, and UI modules are migration targets, not templates
for new code.

## Browser Modules

```text
web/
  index.html               UI structure
  styles.css               visual system
  app.js                   application controller during migration
  js/http.js               HTTP and download boundary
  js/geometry.js           pure canvas-side geometry helpers
```

The next UI extractions are project state/history, canvas rendering, and pointer
interaction. Modules stay browser-native ES modules; no bundler is required.

## Contracts

- `contracts/project.md`: persisted JSON and units.
- `contracts/api.md`: HTTP behavior and error boundary.
- `contracts/geometry.md`: source-geometry preservation.
- `contracts/nesting.md`: deadline and best-result semantics.

## Non-Negotiable Behavior

- Open, self-touching, and self-intersecting source paths remain visible and
  exportable as centerline cuts.
- Normal DXF import never closes gaps, drops segments, removes retraces, or
  simplifies source paths. Repair requires an explicit operator action.
- Findings are warnings, not export blockers.
- Simulation parses generated export G-code.
- Auto nest returns the best valid result already found when its optimization
  deadline expires.
- Cut chart data lives in versioned JSON under `data/cut_profiles/`.
- LinuxCNC probing and Z control remain in QtPlasmaC.
