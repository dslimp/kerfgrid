# KerfGrid

Local-first plasma nesting, CAM, simulation, and QtPlasmaC G-code generation.

KerfGrid runs locally, keeps projects as JSON files, imports DXF geometry, and
uses the same generated G-code for export and simulation. Product invariants
are documented in `docs/contracts/`; repository workflow rules live in
`AGENTS.md`.

## Run

Install Python geometry dependencies into the Python used to run the app:

```sh
python3 -m pip install -e '.[dev]'
```

```sh
python3 server.py
```

Open:

```text
http://127.0.0.1:8765/
```

When backend code changes, restart the existing `127.0.0.1:8765` server before
browser acceptance. Do not switch to an alternate port unless the operator asks
for it.

Run the browser smoke acceptance after the server is up:

```sh
tests/playwright_smoke.sh
tests/playwright_visual_smoke.sh
```

Optional FreeCAD sidecar integration lives in `freecad/`. It
adds a FreeCAD workbench/macro button that exports the selected Sketch or planar
2D objects to DXF, posts them to `/api/import-dxf`, saves the returned
`.kerfgrid.json` backup, publishes the project to `/api/pending-project`, and
opens the local UI so the browser loads the project automatically.

Run the focused shop acceptance gate for the current known problem-file set
without requiring every local DXF to import:

```sh
python3 tools/shop_acceptance.py
```

Add browser checks when the canonical server is already running on
`127.0.0.1:8765`:

```sh
python3 tools/shop_acceptance.py --browser --visual
```

Or let the acceptance wrapper start a fresh local server on a free port for the
browser checks:

```sh
python3 tools/shop_acceptance.py --managed-server --browser --visual --real-dxf-ui
```

Run the long full local DXF corpus gate through the same acceptance wrapper:

```sh
python3 tools/shop_acceptance.py --full-corpus
```

Run the short auto-nest quality/time benchmark:

```sh
python3 tools/benchmark_autonest.py
```

Run the small DXF auto-nest acceptance gate for fast regression checks:

```sh
python3 tools/dxf_corpus_check.py examples \
  --auto-nest \
  --auto-nest-timeout 1 \
  --per-file-timeout 8 \
  --diagnostic-top 10 \
  --quiet \
  --require-complete \
  --min-files 3 \
  --min-completed-files 3 \
  --min-import-ok 3 \
  --min-auto-nest-ok 3 \
  --max-auto-nest-runtime 2 \
  --min-export-ok 3 \
  --min-simulation-ok 3 \
  --max-timeouts 0
```

Run the focused real-DXF gate for known shop/problem files without running the
full local corpus. It has a strict import/auto-nest/export/simulation subset
and a heavy-file import/repair diagnostics subset. The heavy repair diagnostic
uses explicit import-only mode because the current fixture is a 25 MB DXF with
thousands of parts; it is intended to prove import stability and repair
diagnostics, not to generate a shop-ready NGC for every nested object.

```sh
PLASMA_CAM_RUN_FOCUSED_DXF_CORPUS=1 pytest -q tests/test_focused_real_dxf_acceptance.py
```

Run the same focused real-DXF auto-nest gate as a saved corpus artifact:

```sh
python3 tools/dxf_corpus_check.py \
  /Users/user/Documents/dxf/2/Malenkiy_mangal.dxf \
  /Users/user/Documents/dxf/2/medved_kamin.dxf \
  /Users/user/Documents/dxf/models/_extracted/mangal_bear/2mm_2.dxf \
  /Users/user/Documents/dxf/models/_extracted/mangal_bear/4mm.dxf \
  "/Users/user/Documents/dxf/models/_extracted/Jedi__ornament5.1/Jedi  ornament5.1.dxf" \
  "/Users/user/Documents/dxf/models/_extracted/Новая_папка/Новая папка/Kugeln novyj God.dxf" \
  "/Users/user/Documents/dxf/models/_extracted/Новая_папка/Новая папка/Жирафы.dxf" \
  "/Users/user/Documents/dxf/models/_extracted/Новая_папка/Новая папка/картина мишка в лесу.dxf" \
  --auto-close-gaps \
  --auto-nest \
  --auto-nest-timeout 2 \
  --centerline-fallback \
  --open-path-centerline \
  --per-file-timeout 15 \
  --diagnostic-top 20 \
  --quiet \
  --output output/dxf-corpus/latest-focused-auto-nest.json \
  --markdown-output output/dxf-corpus/latest-focused-auto-nest.md \
  --require-complete \
  --min-files 8 \
  --min-completed-files 8 \
  --min-import-ok 8 \
  --min-auto-nest-ok 8 \
  --min-export-ok 8 \
  --min-simulation-ok 8 \
  --max-auto-nest-runtime 5 \
  --require-auto-nest-placements \
  --require-auto-nest-for-exportable \
  --max-timeouts 0 \
  --forbid-validation-blocking-code import_open_contour \
  --forbid-validation-blocking-code small_feature_below_kerf
```

Run the full local DXF corpus acceptance gate as an optional broader regression
check when changing import, export, simulation, or validation behavior. This is
not the normal per-feature gate; the focused real-DXF gate above is the current
shop/problem-file acceptance set.

```sh
python3 tools/dxf_corpus_check.py /Users/user/Documents/dxf \
  --auto-close-gaps \
  --auto-nest \
  --auto-nest-timeout 4 \
  --centerline-fallback \
  --open-path-centerline \
  --unsafe-entity-policy warn \
  --per-file-timeout 30 \
  --diagnostic-top 50 \
  --quiet \
  --output output/dxf-corpus/latest-current-warning-only.json \
  --markdown-output output/dxf-corpus/latest-current-warning-only.md \
  --require-complete \
  --min-files 121 \
  --min-completed-files 121 \
  --min-import-ok 121 \
  --min-auto-nest-ok 121 \
  --min-export-ok 121 \
  --min-simulation-ok 121 \
  --max-auto-nest-runtime 4 \
  --require-auto-nest-placements \
  --require-auto-nest-for-exportable \
  --max-timeouts 0 \
  --forbid-validation-blocking-code import_open_contour \
  --forbid-validation-blocking-code small_feature_below_kerf
```

Run the same real-corpus gate from pytest explicitly when local DXF files are
available:

```sh
PLASMA_CAM_RUN_REAL_DXF_CORPUS=1 pytest -q tests/test_real_dxf_corpus_acceptance.py
```

When the operator wants a narrower import/export/simulation-only sweep without
auto-nest, run the separate warning-policy corpus check:

```sh
python3 tools/dxf_corpus_check.py /Users/user/Documents/dxf \
  --auto-close-gaps \
  --centerline-fallback \
  --open-path-centerline \
  --unsafe-entity-policy warn \
  --per-file-timeout 30 \
  --diagnostic-top 50 \
  --quiet \
  --output output/dxf-corpus/latest-open-path-centerline-unsafe-warn.json \
  --markdown-output output/dxf-corpus/latest-open-path-centerline-unsafe-warn.md \
  --require-complete \
  --min-files 121 \
  --min-completed-files 121 \
  --min-import-ok 121 \
  --min-export-ok 121 \
  --min-simulation-ok 121 \
  --max-timeouts 0 \
  --forbid-validation-blocking-code import_open_contour \
  --forbid-validation-blocking-code small_feature_below_kerf
```

## Current Working Scope

- Local browser UI with sheet view.
- Browser-local project persistence.
- Versioned project JSON save/load with a dedicated `Open Project` path for
  `.kerfgrid.json` files; `Import` remains available for DXF geometry.
- Manual placement, duplicate, delete, keyboard Delete/Backspace, arrow-key
  nudge with Shift/Alt step modifiers, lock, snap grid, mirror-selected-part
  MVP, arbitrary rotation handle, and live bbox collision/sheet/zone preview
  for the selected placement. The preview uses the same sheet/margin bounds as
  backend validation, so a valid placement exactly on the configured margin is
  not shown as a false sheet warning.
- Parts table supports drag-copy placement onto the sheet as a manual nesting
  workflow.
- Built-in starter templates for disk-with-hole, bolt-hole plate, and flange
  parts with persisted size/bolt defaults; generated templates are normal
  project parts and go through the same validate/export/simulate path as
  imported DXF geometry.
- Iterative shelf/lattice auto-nest with arbitrary rotation candidates,
  polygon/NFP-assisted curved contact candidates, lower-left strip scoring,
  multi-strategy final compaction, and benchmark counters for runtime and
  candidate quality.
- Optional multi-process auto-nest attempts, cached rotated footprints, and
  STRtree-backed spatial filtering for candidate collision checks. If the local
  runtime cannot create process workers, auto-nest falls back to serial search
  and records the fallback reason in the nest summary/history.
- Auto-nest runtime budgets are enforced inside lattice packing, candidate/NFP
  generation, compaction, and auto-lead selection; the browser adds only a
  short network grace before aborting the request.
- Next multi-sheet model: project JSON should carry an ordered sheet list,
  active sheet id, per-sheet placements, per-sheet utilization/review summary,
  and unplaced queue. Auto-nest should add a new sheet when remaining parts do
  not fit, while machine-code export targets the active sheet only.
- Persisted auto-nest run history with quality/runtime counters for comparing
  placement settings, including skipped lead-spacing fallback reasons when a
  run hits the time budget or geometry complexity guard.
- Reproducible auto-nest benchmark CLI emits JSON quality/time/counter summaries
  for circles, rectangles, and mixed shape cases.
- Per-part auto-nest rotation constraints and grain lock are stored in project
  JSON and honored by auto-nest requests.
- Optional interior-hole filler relocation during auto-nest for placing smaller
  parts inside large internal cutouts when the final layout remains valid;
  per-part filler/parent permissions are stored in project JSON and honored by
  auto-nest.
- Hole-filler bridge safety is reported as a review-required warning; export
  remains available and writes the warning into the G-code header.
- Manual tab points and export-time auto tabs/microjoints are configurable from
  the Cut tab and emitted as torch-off bridge skips in QtPlasmaC G-code.
- JSON project import.
- Reimporting the same DXF part updates the stored part geometry by source file
  and original part name while preserving existing placements, locks, rotation
  policies, and quantities.
- Stale manual lead points and tab references left after geometry reimport are
  reported as review-required validation warnings and written into the G-code
  header until recreated.
- Safe ASCII DXF import for `LINE`, `ARC`, `CIRCLE`, `ELLIPSE`,
  `LWPOLYLINE`, `POLYLINE`, `SPLINE`, `SOLID`, `TRACE`, `3DFACE`,
  `HATCH`, `MPOLYGON`, planar ACIS `REGION` boundaries with straight/ellipse
  edges, `INSERT`, and `MINSERT` block arrays.
- Common non-cut DXF annotations, dimensions, text, construction rays, images,
  tables, and underlays are counted but ignored for cut geometry instead of
  blocking export.
- Ambiguous 3D/proxy/ACIS and style-dependent entities such as `3DSOLID`,
  `BODY`, non-planar or unsupported `REGION`, `SURFACE`, `MESH`, `HELIX`,
  `MLINE`, and `ACAD_PROXY_ENTITY` are review-required warnings; supported
  explicit 2D contours can still be exported while those entities stay visible
  in reports.
- Explicit `import_options.unsafe_entity_policy=warn` can downgrade those
  unsafe non-contour entities to visible warnings when the operator wants to
  cut only the supported explicit 2D geometry from the file.
- `$INSUNITS` unit detection with mm scaling for common DXF units.
- DXF layer-to-process mapping reads entity group code `8`; explicit
  `import_options.layer_mapping` plus name heuristics keep ignore/construction
  layers out of cut geometry and report mark/etch/bend layers as non-blocking
  warnings.
- The web import panel exposes DXF layer mode and `LAYER=process` rules for
  `cut`, `ignore`, `construction`, and `mark`, and persists them in project
  JSON before import.
- Contour chaining, closure validation, outer/hole classification, and
  splitting multiple top-level DXF parts into separate part definitions.
- Loose LINE/ARC segment chaining first extracts bounded simple closed cycles
  from the segment graph, while dangling cut branches remain review-only
  open contours.
- DXF repair diagnostics for loose tiny segments, duplicate loose segments,
  local closed-path backtrack spurs, and zero-area collinear retrace spikes.
  Self-touch and self-intersecting source paths are retained as imported,
  reported with issue coordinates, and exported by centerline fallback instead
  of being split or polygonized into guessed loops.
- DXF collinear overlap/self-overlap diagnostics with source and sheet endpoint
  coordinates; ambiguous overlapping cut paths are review-required warnings.
- DXF gap closure suggestions with source and sheet coordinates, plus visible
  canvas issue markers for review-required import issues and repaired warnings.
- DXF open-contour diagnostics include both open-chain endpoints, source/sheet
  coordinates, and chain length so CAD repair work can target the actual break.
- Open DXF paths are preserved for review; export automatically falls back to
  centerline open cuts with no kerf offset or lead-in/out and keeps the import
  issue visible as a warning.
- Opt-in DXF small-gap auto-close for import, recorded as a non-blocking repair
  warning with original and sheet endpoint coordinates.
- Versioned/revisioned JSON Fubag Plasma 40 starter cut chart for mild steel
  and 0.8/0.9 mm nozzles.
- Starter vs measured cut chart row metadata is preserved into preview and
  G-code headers; measured rows override starter rows for the same material,
  thickness, and nozzle.
- Backend coupon-test project generator creates simple Fubag 40 calibration
  coupons with candidate rows and `coupon_plan` metadata for shop measurement.
- Cut tab coupon-result import accepts pasted or file-loaded measured JSON,
  updates the project cut chart, and persists it with the project.
- The active starter/project/measured cut chart can be exported/imported as a
  standalone `.cut-chart.json` profile for reuse outside the current project
  file; import runs backend cut-settings preflight and rolls back the prior
  project chart if the profile cannot serve the current material/thickness/nozzle.
- Editable project-level cut chart overrides stored in the project JSON and
  used by backend feed/kerf/pierce selection.
- Cut-chart small-hole/small-shape rules can drive threshold, reduced feed,
  overburn, and early torch-off values; the Cut tab can switch back to manual
  overrides.
- The cut-chart table can edit small-hole diameter, small-shape diameter,
  reduced-feed percent, overburn, and early torch-off per row.
- Auto chart feed or manual feed override.
- Configurable lead-in mode, lead-in length, minimum hole diameter for lead-in.
- Configurable pierce crater diameter and lead clearance validation.
- Configurable lead-out length, small-shape thresholds, overburn, and early
  torch-off.
- Auto-nest generated lead start points, accept/clear controls, and fallback
  technological spacing when start-point selection cannot clear lead/crater
  issues; expensive lead-spacing fallback checks are skipped and reported for
  complex layouts or exhausted runtime budgets.
- Small-hole/small-shape speed reduction and THC lock.
- Visual lead point and tab point editing.
- Keepout, clamp, damaged, slat, remnant, and pierce keepout zones.
- Safe rapid routing around configured zones and already completed contour
  bounding obstacles.
- Safe-travel route failures and very large obstacle sets emit direct-rapid
  warnings instead of blocking export; the warning is visible in validation,
  simulation, G-code comments, and the operator checklist.
- Configurable cut order policy with nearest, lower-left, heat-spread, and
  optional manual group-order overrides; review reports include the planned
  contour sequence for checking heat and tip-up risk before export.
- Cut-order preview overlay draws the planned pierce/entry sequence directly on
  the sheet for operator review before simulation/export.
- The Cut tab exposes cut-order strategy, heat-spread tuning, completed-cutout
  avoidance, grouping, and manual group order controls in project JSON.
- Optional common-line nesting/export guard for shared straight edges.
- Geometry kerf offset before posting through `pyclipper`, with `shapely`
  validity checks for self-intersections, split offsets, and collapsed offsets;
  `G41.1/G42.1` is not emitted.
- Explicit `kerf_offset_fallback=centerline` can downgrade failed/split/collapsed
  geometry offsets, including tiny circle-hole radius collapse, to a visible
  non-blocking warning and cut that contour on the source centerline.
- QtPlasmaC temporary material comments or fixed `M190 Pn` material mode with
  `M66 P3 L3 Q...` and HAL material feed.
- QtPlasmaC G-code generation and validation, including lead-in/out and pierce
  crater checks against the physical sheet, neighboring parts, and blocked
  zones.
- Dry outline NGC export for tracing placed outer contours without torch start.
- Review DXF export for sheet/margin, placed outer/hole geometry, zones, lead
  markers, tabs, and annotations in sheet coordinates.
- JSON review report with export preflight, G-code validation result,
  validation issues, import/nest summary, cut chart row metadata, part counts,
  aggregated warning issue summary, grouped DXF repair plan for
  review-required import geometry, and simulation-derived pierce/cut/rapid metrics,
  unsafe rapid warning metrics, and CAM kerf geometry review counts for offset
  collapse/split and centerline fallback.
- The review report also carries an operator checklist with `ready`,
  `warnings`, or `blocked` status across placements, cut settings, simulation,
  cut order, G-code preflight, and validation warnings.
- Export NGC runs the same preflight first; validation/import/safe-travel/CAM
  issues are warning-only and require a second unchanged click before download.
  The exported G-code includes warning comments at the top for operator review.
- G-code based simulation with rapid, safe-travel fallback warning, pierce, cut,
  reduced-feed, THC-disabled, overburn, and torch-off-before-end states.
- Playwright browser smoke plus visual canvas/layout smoke with a saved
  screenshot artifact under `output/playwright/`; the browser
  smoke covers common-line centerline fallback through the actual `Play Sim`
  button, not only direct API simulation.
- DXF corpus checker writes JSON and Markdown reports with scoped blocking vs
  warning issue counts, concrete blocking-file lists, and example files for
  each issue code. Per-file JSON entries keep compact import/validation issue
  details with coordinates for real-DXF repair triage. The checker can enforce
  explicit acceptance thresholds with a non-zero CLI exit on regression.
- DXF import issue-to-sheet coordinate mapping uses a bbox index for large
  multi-part files, avoiding linear scans across thousands of imported groups
  for every displayed repair issue.
- Self-touching and self-intersecting closed paths stay as one imported cut
  path; warnings and centerline fallback preserve what the operator sees
  instead of guessing a repaired topology.
- Current full warning-only DXF corpus baseline (`/Users/user/Documents/dxf`,
  121 files, `--auto-nest --open-path-centerline --unsafe-entity-policy warn`,
  2026-08-24T11:42:19Z, 277.213s):
  121 import, 121 auto-nest, 121 export/simulate, no dropped placements, no
  exportable auto-nest misses, no blocking files, max auto-nest runtime 3.738s,
  no timeouts; open contours, self-intersections, collinear overlaps, unsafe
  unsupported entities, kerf centerline fallback, and safe-travel fallbacks are
  warning-only; `acceptance.ok=true`.
- Current focused real-DXF auto-nest baseline
  (`latest-focused-auto-nest`, 2026-08-24T11:28:54Z, 20.347s):
  8 import, 8 auto-nest, 8 export/simulate, no dropped placements, no
  exportable auto-nest misses, max auto-nest runtime 1.909s, no timeouts;
  `acceptance.ok=true`.
- The older import/export-only unsafe-warning corpus command is kept as a faster
  diagnostic sweep, but the full warning-only auto-nest baseline above is the
  current broad production regression check.

## Safety Contract

- CAM output must not contain Z motion; QtPlasmaC owns probing and THC.
- Torch on/off must use `M3 $0 S1` and `M5 $0`.
- Feed should come from QtPlasmaC material data:
  `F#<_hal[plasmac.cut-feed-rate]>`.
- The generated G-code is validated before export.
- Cutter compensation `G41.1/G42.1` is rejected; kerf is handled in geometry.
- Export should be blocked on layout collisions, out-of-sheet geometry, unsafe
  lead-in/out or pierce crater clearance, blocked zones, or invalid G-code.
- Safe-travel fallback is warning-only: it must be reviewed because the torch
  may rapid over a raised slug, but it does not block the job.

## Next Immediate Stages

1. CAD import repair: carefully reviewed automatic repair options for simple
   overlap/open-contour cases and richer before/after diagnostics without
   converting incomplete DXF geometry into cut paths silently.
2. Production nesting safety: cut-order editing, heat/tip-up constraints,
   filler-in-hole bridge placement ergonomics, and regression benchmarks.
3. Process database: profile library/version management and per-contour
   lead/process strategy.
4. Manual nesting ergonomics: clusters/groups and richer per-part policy
   controls.
5. Review outputs: visual/screenshot regression tests and richer shop review
   workflows on top of the current review DXF and JSON report.

See `docs/architecture.md`, `docs/mvp-roadmap.md`, and
`docs/linuxcnc-primer-gap.md`.
