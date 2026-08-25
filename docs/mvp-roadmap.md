# MVP Roadmap

## Stage 0: Working Baseline

Status: done in this folder.

- Standalone local server.
- Browser UI.
- Project persistence.
- Circle DXF import.
- Placement editing and simple nesting.
- Fubag Plasma 40 cut chart.
- QtPlasmaC post.
- G-code validation.
- G-code simulation.
- Review DXF and JSON review report exports.
- Regression tests.

## Stage 1: Real DXF Geometry

Goal: import practical flat plasma parts exported from CAD.

Status: first MVP implemented.

- Parse ASCII DXF `LINE`, `ARC`, `CIRCLE`, `ELLIPSE`, `LWPOLYLINE`,
  old `POLYLINE`, sampled `SPLINE`, `SOLID`, `TRACE`, `3DFACE`, `HATCH`,
  `MPOLYGON`, `INSERT`, and `MINSERT` block arrays.
- Count and ignore common non-cut annotations, dimensions, text, construction
  rays, tables, images, viewports, and underlays.
- Preserve source units and reject unknown/ambiguous units.
- Chain connected entities into contours.
- Extract simple closed cycles from loose segment graphs before reporting
  dangling cut branches as review-required open contours.
- Report open contours with endpoint coordinates.
- Classify outer contours and holes by containment.
- Split multiple top-level DXF parts into separate part definitions while
  keeping contained contours as holes of the owning part.
- Repair/report loose tiny segments, duplicate loose segments, and local
  closed-path backtrack/retrace spurs as non-blocking warnings, and report
  self-intersecting closed paths as review-required issues with coordinates.
- Report collinear overlap/self-overlap line edges as review-required issues
  with overlap endpoint coordinates and sheet marker coordinates.
- Report small open-contour gaps with endpoint coordinates and sheet marker
  coordinates; show import issue markers in the canvas.
- Optionally auto-close small gaps during DXF import, keeping the repair visible
  as a non-blocking warning with source and sheet endpoint coordinates.
- Decode planar ACIS `REGION` boundaries with straight/ellipse edges as cut
  contours, chaining each REGION body independently.
- Keep ambiguous 3D/proxy/ACIS and style-dependent entities such as `3DSOLID`,
  `BODY`, unsupported `REGION`, `SURFACE`, `MESH`, `HELIX`, `MLINE`, and
  `ACAD_PROXY_ENTITY` as review-required import issues.
- Allow the operator to explicitly downgrade unsafe non-contour entities to
  warnings when cutting only supported explicit 2D geometry from a dirty DXF.

Exit criteria:

- A rectangular plate with round holes imports from DXF.
- A slot made from two lines and two arcs imports from DXF.
- A CAD file containing several separate parts becomes a multi-part job.
- Repaired CAD noise stays visible in diagnostics without blocking export.
- Self-intersecting contours are visible for review but cannot be exported.
- Collinear overlapping/self-overlap edges are visible for review but cannot be
  exported.
- Small gaps identify both endpoints and draw a marker/line on the sheet.
- Open contour diagnostics identify both chain endpoints, sheet coordinates, and
  chain length for CAD repair.
- Opt-in gap repair turns simple small gaps into exportable contours while
  preserving a visible repair warning.
- Import reports exact blocking issues instead of silently dropping geometry.
- Non-cut annotations do not block export when valid closed cut contours are
  present.

## Stage 2: Arbitrary Contour CAM

Goal: produce safe QtPlasmaC G-code for line/arc contours.

Status: first MVP implemented with sampled path offsets.

- Geometry offset for inside/outside kerf.
- Direction rules: holes and outer profiles can be reversed intentionally.
- Lead-in placement for straight and curved contours.
- Lead-in/out and pierce crater validation against physical sheet bounds,
  neighboring parts, and blocked zones.
- Small-hole rules remain active for round holes.
- Post line and arc moves without Z.

Exit criteria:

- Golden DXF fixtures export valid G-code.
- Simulation path matches generated G-code.
- Validator blocks impossible offsets and gouging lead-ins.
- Explicit centerline fallback downgrades failed/split/collapsed offsets to
  warning-only output only when the operator enables that fallback.

## Stage 3: Production Nesting MVP

Goal: reduce manual layout time while keeping manual control.

Status: first MVP implemented with exact layout validation when `shapely` is
available, iterative shelf/lattice attempts, zones, lower-left strip scoring,
post-placement lead/crater safety validation, auto-generated lead start points,
accept/clear controls for generated lead points, and fallback lead-aware
spacing. Interior-hole filler relocation has a first opt-in MVP for moving
smaller parts into large internal cutouts when the resulting layout still
passes exact validation, with per-part controls for whether a part may fill
holes or host fillers. Manual placement now has snap/nudge controls,
mirror-selected-part support, and per-part rotation/grain constraints for
auto-nest. Cut-order preview, unsafe rapid warning visualization, and CAM kerf
geometry review metrics are available for operator acceptance.

- Exact contour collision checks.
- Part-to-part and part-to-sheet spacing.
- Manual drag/rotate, arrow-key nudge, snap options, selected-part mirror,
  drag-copy placement from the Parts table onto the sheet, and live bbox
  collision/sheet/zone preview for the selected placement, aligned with backend
  sheet/margin validation instead of adding stricter UI-only margin failures.
- Multi-part job list with quantities.
- Per-part allowed rotations and grain lock for auto-nest.
- Preserve locked placements during auto-nest.
- Keepouts for clamps, slats, damaged zones, and remnants.
- Pierce keepout zones block pierce point/crater placement without blocking
  ordinary part placement.
- Visual tab and lead point editing.
- Lead/crater warnings after placement, visible in validation, report, and
  G-code warning header without blocking export.
- Auto-generated safe lead points during auto-nest when the default start point
  conflicts with adjacent parts, zones, or sheet bounds.
- Lead-spacing fallback checks honor runtime and geometry-complexity guards and
  record skipped reasons in nest summary/history.
- Safe rapid routing around zones and completed contour obstacles, with direct
  fallback rapid segments flagged as warnings in simulation/report instead of
  blocking export.
- Configurable cut-order strategies for nearest, lower-left, and heat-spread
  sequencing, with planned sequence metadata in the review report.
- Canvas preview overlay for the planned cut sequence, including numbered
  entry/pierce points and travel order.
- Optional interior-hole filler relocation for large internal cutouts, gated by
  per-part filler/parent permissions.
- Hole-filler bridge/tab safety is review-required until parent internal
  cutouts holding nested parts have at least two positive-length tabs.
- Planned multi-sheet project model: ordered sheet list, active sheet selector,
  per-sheet placements and utilization, unplaced queue, auto-added sheets when
  parts do not fit, and active-sheet-only machine-code export.
- Review DXF exports placed geometry, zones, lead markers, tabs, sheet bounds,
  and margin for visual verification before cutting.
- Manual tab points and export-time auto tabs/microjoints can be configured
  from the Cut tab and are covered by G-code and browser smoke tests.
- JSON review report summarizes validation/import/nesting state, cut chart row
  metadata, CAM kerf geometry review counts, grouped DXF repair actions for
  review-required import issues, and simulation-derived pierce/cut/rapid/unsafe-rapid
  metrics without costing.
- JSON review report includes an operator checklist that reduces placements,
  validation warnings, cut settings, simulation, cut order, and G-code preflight
  to `ready`, `warnings`, or `blocked`; safe-travel fallback remains
  warning-only.
- Optional open-path centerline export supports intentional DXF slots and
  decorative cuts while keeping open-contour import diagnostics visible.
- Browser smoke covers common-line centerline fallback through the actual
  simulation button, so UI regressions where API simulation works but `Play Sim`
  does not are caught.
- Reimporting the same DXF part updates the part definition by source file and
  original part name while preserving existing placements, locks, rotation
  policies, and quantities.
- Dedicated `Open Project` loads saved `.kerfgrid.json` jobs separately from
  DXF geometry import; the browser smoke covers project round-trip through that
  path.
- Explicit unsafe-entity warning import policy supports reviewed dirty DXF files
  where unsupported ACIS/proxy entities are not part of the cut job.
- DXF corpus reports include scoped blocking/warning counts, concrete
  blocking-file lists, example files per issue code, compact per-file issue
  details with coordinates for repair triage, and explicit acceptance
  thresholds that fail the CLI or opt-in pytest gate on regression. JSON review
  reports now expose the same blocking DXF issues as grouped operator repair
  actions. Large-file issue coordinate mapping is indexed by group bbox so
  repair diagnostics do not scan thousands of imported parts for every displayed
  issue.
- DXF corpus acceptance can enforce auto-nest success count and maximum
  per-file auto-nest runtime, so hangs and dropped placements are caught before
  manual UI testing.
- Self-touching and self-intersecting paths stay as imported visible
  trajectories. The importer reports coordinates, validation stays warning-only,
  and export uses centerline fallback instead of guessing repaired topology.
- Focused real-DXF acceptance covers known shop/problem files with
  import/auto-nest/export/simulation and placement-retention checks in a
  shorter opt-in pytest gate. This is the current per-feature real-DXF gate;
  full local corpus runs are broader optional regression checks, not a
  requirement to make every discovered DXF production-ready immediately.
- `tools/shop_acceptance.py` is the one-command focused shop
  gate: unit tests, focused real-DXF pytest, and the saved focused corpus
  artifact. The focused pytest also includes a 25 MB heavy repair-diagnostic
  fixture with a larger non-interactive timeout. Browser smoke can be added
  explicitly with `--browser --visual`, run against a fresh wrapper-managed
  backend with `--managed-server`, and the long broad corpus gate can be added
  explicitly with `--full-corpus`.
- Latest focused real-DXF auto-nest artifact baseline, 2026-08-24T11:28:54Z:
  8 files imported, nested, exported, and simulated; no dropped placements, no
  exportable auto-nest misses, no timeouts, max auto-nest runtime 1.909s,
  `acceptance.ok=true`.
- Latest full warning-only DXF corpus baseline, 2026-08-24T11:42:19Z with
  `--auto-nest --open-path-centerline --unsafe-entity-policy warn`: 121 DXF
  files imported, auto-nested, exported, and simulated; no dropped placements,
  no exportable auto-nest misses, no blocking files, max auto-nest runtime
  3.738s, zero timeouts, `acceptance.ok=true`, runtime 277.213s. Open
  contours, self-intersections, collinear overlaps, unsafe unsupported entities,
  kerf centerline fallback, and safe-travel fallback are warning-only.

Exit criteria:

- Auto-nest never drops duplicated parts.
- Locked parts remain fixed.
- Collision warnings are reproducible and tested.
- Unsafe lead-in/out and pierce crater warnings are reproducible and tested.
- Auto-nest worker fallback is reproducible and reported when multiprocessing is
  unavailable.
- Auto-nest lead-spacing fallback skip reasons are reproducible and reported
  when time budget or geometry complexity would make the check too expensive.
- Auto-nest runtime limits are checked inside lattice packing, candidate/NFP
  generation, compaction, and auto-lead candidate selection rather than only
  between high-level attempts.
- Real DXF corpus acceptance is reproducible with minimum import/export/sim
  thresholds, zero-timeout enforcement, and forbidden closed-regression issue
  codes.
- Fast example DXF auto-nest acceptance enforces placement retention,
  export/simulation success, and a bounded runtime budget.
- Complex open-path jobs do not time out in cut-order generation because
  contour entry/exit points are cached during sequence optimization.

## Stage 4: Shop Calibration

Goal: stop treating starter cut settings as truth.

Status: started with versioned/revisioned JSON starter profile storage,
editable project-level chart overrides, measured-row preference, cut-chart
small-feature rules, active cut-chart profile export/import, and a backend
coupon-test project generator.

- Persist calibrated profile files outside Python code.
- Import measured coupon results back into cut chart rows.
- Export/import the active starter/project/measured profile as standalone JSON
  for reuse after coupon calibration.
- Imported cut-chart profiles are checked against backend cut-setting selection
  immediately and rejected with rollback if they do not cover the current cut
  material, thickness, and nozzle.
- Versioned machine profile for the actual table.
- Per-contour lead/process strategy for future multi-parameter coupon jobs.
- Export report includes chart row source: starter vs measured.
- Small-hole/small-shape thresholds, reduced feed, overburn, and early torch-off
  can come from the selected cut-chart row or be manually overridden.
- The browser cut-chart editor exposes those small-feature fields per row.

Exit criteria:

- Fubag Plasma 40 settings can be calibrated without editing code.
- G-code header clearly states the chosen measured/starter row.

## Stage 5: Later Pro Features

Out of MVP until Stages 1-4 are stable:

- Production common-line cutting for arbitrary curved parts and kerf-aware
  shared edges.
- Production interior-hole/filler nesting: upgrade the current opt-in,
  per-part-policy relocation MVP with stronger cut-order guarantees,
  bridge/tab strategy, and safe-travel routing around the cutout slug.
- Per-part nesting policies: rotation override, filler/main priority, grain/up
  direction, and lock/manual constraints in the parts table.
- Advanced NFP optimizer controls inspired by FreeCAD nesting workbenches:
  curve approximation quality, simplification tolerance, packing direction,
  randomized/seeded runs, explicit NFP cache clearing, and GA-style generations
  and population size.
- Visual diff/review workflow for auto-generated lead points.
- Chain and bridge cutting.
- Skeleton cut-up.
- Remnant inventory.
- Costing and reports.
- Multi-machine post library.

## ProNest-Derived Priorities

Useful product ideas to copy in spirit, excluding estimating/quoting, customer
databases, and enterprise reporting.

### Keep High Priority

- CAD import repair and diagnostics: report/fix gaps, collinear overlaps,
  duplicates, tiny segments, self-intersections, wrong units, mixed contours,
  and unsupported entities with exact locations.
- Split multiple parts from one CAD file into separate part definitions
  (first implementation done; keep improving CAD repair and per-part metadata).
- Layer-to-process mapping for cut, mark/etch, ignore, construction, and
  centerline operations.
- Automatic redraw of an existing nest when an imported part version changes,
  preserving manual/locked placements where possible (first same-file/same-part
  reimport workflow done; stale lead/tab references now require review).
- Material/process database keyed by material, grade, thickness, nozzle,
  amperage, feed, kerf, pierce delay, cut height, THC, and lead strategy.
- Per-part and per-contour lead-in/out editing with physical fit validation.
- Manual and automatic cut sequence editing with heat/tip-up/safe-travel
  constraints.
- Microjoints/bridges/tabs generated automatically from part size and geometry
  (first implementation done; keep improving strategy and per-part policy).
- Remnants and irregular sheets as first-class nest containers.
- Part library and assemblies/jobs: reusable part definitions with quantities,
  revision metadata, and allowed material/thickness.
- Built-in starter templates for disk, plate, and flange are implemented as
  normal project parts; next step is parametric editing and more shop shapes.
- Grain/up-direction constraints and per-part rotation/mirror permissions.
- Interactive manual nesting ergonomics: cluster/group, nudge/snap, mirror,
  and rotate handle.
- Dynamic simulation of cut sequence with pierce/cut/rapid/reduced-feed/THC
  states.
- Output DXF for nest review, JSON review report, and dry-outline export for
  checking sheet fit.

### Keep Medium Priority

- Extend template parts to common brackets, slots, gussets, tabs, and parameter
  editing. Keep this simple; do not build a full CAD clone.
- PDF import only for vector PDFs first; raster-to-vector is later and should
  be treated as inspection/reconstruction, not trusted CAM geometry.
- Automatic smoothing/simplification with user-visible tolerance and before/after
  validation.
- Automatic corner rounding only as an explicit process option for suitable
  machines/materials; it must never silently change part geometry.
- One-click job presets for repeated shop flows once the safe manual workflow is
  stable.

### Deprioritize Or Skip

- Customer database, quoting, costing, and management reports.
- Full multi-vendor machine database. Keep a clean post/profile boundary, but
  prioritize LinuxCNC QtPlasmaC and the actual Fubag/table setup.
- Multi-head cutting, bevel, waterjet, oxyfuel preheat, laser film vaporization,
  and proprietary Hypertherm SureCut features unless the machine hardware later
  requires them.
- Full integrated CAD replacement. The app should repair/import/edit CAM-facing
  geometry, while serious design remains in CAD.
