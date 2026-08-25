---
name: kerfgrid-development
description: Implement and review KerfGrid DXF, nesting, CAM, QtPlasmaC, simulation, and browser UI changes without changing operator geometry or turning warnings into blockers.
---

# KerfGrid Development

## Workflow

1. Read `AGENTS.md` and the relevant contract in `docs/contracts/`.
2. Locate the owning layer before editing. Keep HTTP in `server.py`, API composition in `web_api.py`, orchestration in `application/`, geometry in `model.py` or `cam`, and browser concerns under `web/js`.
3. Reproduce the behavior with the smallest focused test or fixture.
4. Preserve imported paths. Never repair topology by guessing or silently drop geometry.
5. Keep normal import non-mutating. Any gap closure, duplicate removal, simplification, or topology repair requires an explicit repair operation and its own before/after review.
6. Return validation findings as warnings and include them in generated artifacts; export remains operator-controlled.
7. For nesting, create a valid seed first, optimize only while time remains, and always retain the best valid result.
8. Run focused tests, then the full unit suite. Restart the canonical server and run Playwright for UI/API work.

## Acceptance

- The project JSON contract remains internally consistent.
- Simulation consumes generated G-code.
- Export does not fail solely because warnings exist.
- Nesting never loses a valid result at timeout.
- New code is placed in the owning module rather than extending a transport or UI monolith.
