# KerfGrid Engineering Contract

## Scope

These rules apply to this repository.

## Product Rules

- Imported geometry is operator-owned. Preserve open, self-touching, and self-intersecting paths and cut the visible centerline when compensated geometry cannot be produced.
- Normal DXF import is read-only with respect to geometry. It must not close gaps, remove duplicate/tiny/retraced segments, simplify paths, or retry with repair enabled.
- Geometry repair is a separate, explicit operator command. Until that UI exists, the normal browser and FreeCAD flows keep `auto_close_gaps` and `repair_geometry` disabled.
- Validation findings are warnings. They must be visible in review, simulation, and G-code comments, but must not block export.
- Simulation is generated from the exact G-code that will be exported.
- Auto nest must return the best valid layout found before its optimization deadline. The deadline is not a minimum runtime and expiry must not discard a valid seed.
- Prefer lower-left, compact layouts and leave unused stock above the packed region.
- Use `http://127.0.0.1:8765/` for local UI work. Restart the server on that port after backend or frontend changes.
- A server that must remain available after the Codex task ends must run under the user `launchd` session; a tool-owned foreground or background process is only suitable for checks during the current task.

## Architecture

- `plasma_cam/model.py` and `project.py`: geometry and job-domain types; no HTTP or browser concerns.
- `plasma_cam/importers/`: source-format parsing and explicit import diagnostics.
- `plasma_cam/autonest.py` and `nesting.py`: placement search, scoring, spatial indexing, and caches.
- `plasma_cam/cam/`: kerf, leads, cut order, travel, and toolpath planning.
- `plasma_cam/post.py`: QtPlasmaC orchestration and controller-specific output.
- `plasma_cam/application/`: project orchestration and JSON-boundary services.
- `plasma_cam/web_api.py`: application composition for the HTTP boundary.
- `server.py`: HTTP transport and static-file serving only.
- `web/`: browser UI; API, project state, canvas rendering, and interaction live in separate modules.

Do not add domain logic to `server.py` or UI-only geometry that disagrees with backend output. Keep public contracts in `docs/contracts/` updated with behavior changes.

## Verification

- Run focused tests while editing and `python -m pytest -q` from the configured development environment before delivery.
- For UI or API changes, restart port `8765` and run `bash tests/playwright_smoke.sh`.
- Add a regression test for every fixed geometry, nesting, G-code, or browser-flow bug.
