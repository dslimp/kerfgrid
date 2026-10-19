# KerfGrid Work Log

## 2026-10-19 Viewport Zoom And Pan

User requests explicit scale entry and navigation around the drawing. Added
5–5000% input (Enter/blur), cursor-anchored wheel zoom, hand tool/H,
middle-button and Space+left panning. Arrows pan in hand mode. Numeric zoom and
pan are local browser preferences, separate from shared projects and Undo;
Sheet/Parts reset both. Fit uses the area below the toolbar, including wrapped
controls. Pan ends on release, lost button state or window blur; right drag
cannot select/move a part. Existing select-mode geometry drag remains available.

Verification: pytest 295 passed / 3 optional external-corpus skips. Required
Playwright smoke and visual smoke passed. New `tests/viewport_acceptance.js`
checks rendered contour size/position for exact 200% and arbitrary 137.5%,
all pan gestures, arrows/H, wheel anchoring, reload persistence, independent
browsers, limits/empty input, fit/reset and wrapped-toolbar clearance. Job JSON
and Undo remain unchanged during navigation; deliberate part drag after zoom/pan
moves exactly with the cursor and is undoable. Blur cancellation also passes.
Inspected `output/playwright/viewport-controls.png`; syntax/diff checks pass.

Narrow `kerfgrid_app` check on nh02 passed: 6 ok / 2 changed / zero failures.
Only the application is rolled out; no connected-controller operation is used.
Evidence: `output/viewport-2026-10-19/`, including `rollout.json` for the final
production asset readback and GitHub/CI receipt.

## 2026-10-19 Parts Controls And Clear Sheet

User requests Parts deletion without horizontal scrolling, a nearby clear-field
button and removal of duplicated lower sidebar controls. Parts now uses wrapped
filename rows with quantity/actions underneath; long names cannot displace Del.
Added “Очистить поле”: one undoable change clears parts, placements, zones,
leads, tabs and stale previews while retaining sheet/process settings and the
uploaded-file library. Empty shared state survives reload. Late simulation
responses are discarded after clear or another simulation reset.

Removed nine duplicate Job buttons and the duplicate visible import picker;
primary commands remain in the top toolbar. Unique Reload Demo, Stop Sim and
Review DXF moved to Templates, Sim and Code. The nest busy indicator now updates
the primary toolbar button without replacing its SVG icon.

Verification: full pytest 295 passed / 3 optional external-corpus skips;
Playwright smoke passed, including the new `tests/parts_controls_acceptance.js`.
The regression checks 1280/900/390 px widths, visible deletion, delete undo,
clear/undo/redo, shared persistence/reload, retained settings and a deliberately
delayed simulation response. Updated the existing reimport smoke to await actual
import completion before sending again, eliminating its event timing race.
Inspected `output/playwright/parts-controls-desktop.png`; evidence is under
`output/parts-controls-2026-10-19/`. JavaScript syntax and diff checks pass.

Production uses only the existing `kerfgrid_app` role scope on nh02; check passed
6 ok / 1 changed / zero failures. No live clear, CNC load or motion is performed.
Rollout and GitHub publication receipt:
`output/parts-controls-2026-10-19/rollout.json`.
Published as `9fb9f70`; CI run `39235806661` passed. Apply completed with
8 ok / 3 changed / zero failures; all three served web assets matched source.

## 2026-10-19 Completed-Part Travel And GitHub Review

User requests persistent safe/direct rapids, prioritizing avoidance of loose
cutouts over shortest travel, plus general review and update of the existing
`dslimp/kerfgrid` GitHub repository on `main`. The reviewed publication includes
accumulated shared-workspace, import, compact/strip/pair nesting, lead, process
and integration changes since `78f7791`. No CNC motion or ignition was issued.

Replaced the endpoint-exempt bounding-box router with conservative completed
outlines, short outward egress, rounded-coordinate clearance and bounded
visibility search. Unresolved routes insert M0 before a warned direct move,
even without optional comments. One Nest-tab checkbox persists the safe/direct
choice. Simulation uses exact export G-code and reports pauses. Cut ordering
uses actual pierce/exit points, routed cost and reachable outgoing cuts;
ungrouped order preserves own holes, hole fillers and manual part ranks.
Review also fixed unacknowledged transfer success/default direct NML loading,
reimport quantity loss, integer formatting at precision zero and inline-comment
sanitization. API/README contracts now describe actual behavior and loader needs.

Verification: full pytest 295 passed / 3 optional external-corpus tests skipped;
Playwright smoke passed including mode persistence/reload; independent two-browser
acceptance passed shared edits, stale-save protection, draft retention and
agent DXF upload/original preservation. Visual smoke passed after updating its
fixtures to shared server state and actual no-margin placement coordinates;
`output/playwright/visual-smoke-latest.png` inspected. `git diff --check` clean;
credential-pattern scan found no candidates among published source files.
Review findings and limits: `docs/reviews/2026-10-19.md`.

Independent exact-G-code check of the existing 18-tab job found 13 part-interior
crossings in direct mode (1672.49 mm rapid). Safe mode with the unchanged 8 mm
clearance uses 2282.00 mm rapid and 6 M0 stops; no crossing lacks a preceding
pause. At 2 mm it uses 2187.62 mm, no M0 and no part-interior crossings. The 2 mm
setting is only a comparison, not a recommendation or a project edit. Evidence:
`output/review-2026-10-19/travel-comparison.json` and corresponding NGC files.

Standard `nh02.yml --limit nh02 --tags kerfgrid_app --skip-tags always
-e ansible_port=22`: check 6 ok / 2 changed; apply 8 ok / 4 changed, both with
zero failed/unreachable. Only KerfGrid restarted. HTTP readback confirms the
single travel checkbox and pause explanation/count are served on nh02. Local
port 8765 remains managed by launchd. Workspace DB and transfer environment are
outside this application copy scope. Previously sent G-code must be regenerated
to use the new routing. Physical tip-up, torch envelope and real controller
loading were not replayed; native-transfer protocol tests use mocks.

Published application changes as `13cfa1c` to GitHub `main`. First Linux CI run
`39233635759` exposed a test that expected all 18 lead overrides inside the
fixture's two-second total budget; the runner correctly stopped after eight.
Separated clock-bounded layout acceptance from complete lead-quality checking
without a deadline. Existing deadline regression tests remain unchanged; no
production code, budget or geometric acceptance threshold changed in this fix.
Final review publication `3a5e947` passed GitHub CI run `39234076559`.

## 2026-10-15 Arc Stops Immediately After Ignition

User reports an actual arc lasting roughly 0.3 s, leaving a pierce on the sheet.
Read-only snapshot at 17:59 showed repeated `valid arc lost / program is paused`,
4 pierces, torch time 1.236 s, cut time/length zero. Arc loss occurs during
pierce delay before XY, not an early generated M5. The actual 18-part NGC has
M3 then the lead/contour and M5 after the complete contour. Arc OK is active-low
LPT12 through 5 ms dbounce; `plasmac.arc-lost-delay` was zero. Pin 12 was inactive
at inspection. Native loss handling confirms confirmation was received then
lost; signal dropout, external THC relay/wiring/noise and actual arc extinction
remain unproven physical causes. A separate realtime-delay warning occurred
17:50, before the torch-enabled failures 17:52–17:54. Do not conflate them.
Evidence: `output/linuxcnc/physical/2026-10-15-short-arc-snapshot.json` and PNG.

User forbade any replay/cut. Subsequently authorized applying the fix and a
restart with plasma power off and steppers powered. User explicitly requested
an Arc OK bypass preserving independent external THC, and raised the loss
threshold from proposed 100 to 400 ms. Native Ignore Arc OK inhibits THC, so
implemented a separate opt-in `kerfgrid_plasmac` based on upstream PlasmaC 1.238:
Mode 2 GUI bypass relaxes three THC gates; real Arc OK is not fabricated.
Default/native modes, M64 P1/Mesh, stops/sensors and Z limits remain unchanged.
System `plasmac.so` is preserved; `loadrt kerfgrid_plasmac names=plasmac` keeps
all native pin/function names. The main torch panel exposes the native checkbox
as `Без контроля Arc OK`, with an amber mode message and runtime capability
check. Physical HAL sets `arc-lost-delay 0.4` and enables the Mode 2 option.

Full standalone C component tests exercise startup/loss, up/down, independent
THC, Mesh/M64/other modes, pause, sensors and limits without HAL or hardware.
Combined component/import/lifecycle tests: 83 passed. Offscreen Qt layout tests
with the controller's actual stock UI/QSS: 10 passed. GUI load/controller-role
tests: 58 passed (real IPC test requires unsandboxed local Unix sockets).
Fixed read/lifecycle wrappers added with routing, target and stop-order guards.

Normal shutdown entered software E-stop before abort, verified empty queue and
torch off; XYZ stayed (84.8499996,4.9999997,44.9999999). Confirmed the visible
Shutdown dialog (YES on right), then installed through the standard
`linuxcnc_controller.yml --tags qtplasmac_screen,qtplasmac_keyboard,plasma_machine_arc`
with physical variable files and `.73` SSH key alias. Check: 12 ok / 5 changed /
0 failed; apply: 13 ok / 6 changed / 0 failed. Compilation succeeded on the
controller; no packages, axis settings, routing or LPT mapping changed.
Post-restart readback confirmed `arc-lost-delay=0.4`, the new opt-in pin true,
source hashes equal to the repo, normal Arc OK bindings and torch/motion outputs
off. Live E-stop GUI acceptance clicked the actual native bypass checkbox:
`ignore-arc-ok-1=true`, THC enable/enabled stayed true, real Arc OK in/out stayed
false, torch/LPT17 stayed false, position unchanged. Finally restored bypass off.
Evidence: `output/linuxcnc/physical/2026-10-15-arc-bypass-gui-test.json` and
`2026-10-15-arc-controls.png`, `2026-10-15-arc-controls-snapshot.json`. LinuxCNC remains in E-stop, unhomed, with no program loaded.
No HOME, jog, probe, Run, Resume or torch test was issued. Real cut behavior remains untested by the user's instruction. Final combined
local regression suite: 225 passed; layout was also rechecked against the
post-restart live QSS (10 passed). Test log:
`output/linuxcnc/physical/2026-10-15-arc-tests.txt`.

## 2026-10-15 Pierce Damage And Nesting Modes

User supplied a cut photo with a large crater at the notch and requested
Fubag pressure guidance. Read-only controller inspection found the current
4 mm / nozzle 0.9 / 40 A / F900 job, PH=CH=8, PD=0.5. Its outer pierce
at (94.85,9.35) is inside the retained tab; the 5 mm tangent lead enters
the concave corner at (89.85,9.35). The planner extends the outgoing tangent
backward and validation excluded the part being cut. Corrected closed-path
lead-in/out direction to the waste-side corner bisector; manual pierce points
remain operator-owned and get visible own-part collision warnings. Preview
and export use the same direction. On the original single-part project, the corrected
pierce is (86.314,5.814), the contour is unchanged, the old lead crosses
4.35 mm of retained material and the new lead/crater have zero intersection.
No motion or torch commands were issued; the old loaded NGC needs re-export.

Manufacturer sources: PLASMA 40 manual section 5.1 gives 3.5–6 bar and SET
for airflow adjustment; Fubag 2018 catalogue p53 specifies FB P40 4.5–5 bar.
Recommended 5 bar while flowing. Manual section 5.2 specifies 3–4 mm nozzle
distance; current 8 mm derives from old Mach3 macro, actual clearance unmeasured.
Standard cut profile and missing-value defaults now use 5 bar, version
`2026-10-15-air5` / `starter-r3-air5`; saved custom tables are preserved.
User confirmed THC enabled on the photographed cut. Uneven bevel/dross does
not prove a feed error: torch squareness, nozzle/electrode condition and actual
clearance remain physical checks. No blind height/feed change was made.
https://cdn.vseinstrumenti.ru/instruction/nomenclaturecontent/202006/3224747.pdf/fubag-plasma-40-790396.pdf
https://www.illeon.ru/images/katalog_fubag_2018.pdf
https://www.hypertherm.com/resources/system-support/maintenance-and-use/cut-quality/cut-angularity/

User additionally requested manual compact/line packing and optimizer review.
Added `nesting.layout_mode` selector under Nest → Размещение. `compact`
forms a compact block by minimizing squared diagonal, then rectangle area;
`strip` prioritizes height and extends along X (legacy default). User clarified
that the first area-only implementation still produced an unwanted vertical
column, so both the contract and directory guidance were corrected.
The objective reaches packing, lattice scoring, final selection, compaction,
and hole filling; it is recorded in results/history and persists after reload.
Identical outputs are valid when the same arrangement wins both objectives.

Review fixes: compare a valid shelf seed with successful attempts instead of
discarding it whenever any attempt succeeds; interleave part orders, placement
policies and rotation pools so a short attempt budget explores all dimensions.
Added bounded block seeds. Compaction now considers aligned nearby edges with
small perpendicular moves: on the 4-tab staircase, width reduces 124.78→120 mm
while height grows 217.21→217.87 mm and the 8 mm gap remains valid. Locked
placements are preserved. The local HTTP API with the current 8-tab project,
original 6 mm spacing and allowed rotations returns 241.601×246 mm in 3.09 s,
8 workers, no parallel fallback. All 8 leads/craters stay inside its rectangle
with no validation findings. Auto leads now prefer internal waste pockets and
edge midpoints; manual overrides remain unchanged.

Follow-up assessment used a read-only snapshot of shared workspace revision 20:
18 tabs, 6 mm spacing, current 311.8003×437.8003 mm and 62.51% rectangle
utilization. A local search of opposing 0°/180° pairs found nine pairs in a
3×3 array, 372.0002×292.6841 mm, 78.37% utilization and 20.24% less enclosing
rectangle area. Exact polygon checks retain at least 6.0001 mm spacing;
regenerated 5 mm auto leads with 4 mm pierce craters and 1 mm clearance pass
the complete project validator with no findings. This proves an improvement,
not the global optimum. Source/candidate projects and comparison evidence:
`output/2026-10-15-nest18-{source,paired}.project.json` and
`output/2026-10-15-nest18-comparison.json`; local G-code export is
`output/2026-10-15-nest18-paired.ngc`. The production workspace and controller
were not modified. The useful optimizer extension is repeatable pair seeds;
no application change or deployment was part of this assessment.
Same-scale visual comparison was rendered and inspected at
`output/playwright/2026-10-15-nest18-comparison.png`.

User then requested trying this through automatic nesting. Added generic early
opposed-pair seeds in `plasma_cam/autonest.py` for repeated instances of one
profile. Search compares explicitly allowed opposite rotations, transverse
offsets and grid column counts, checks each placed polygon against spacing,
sheet and blocked boxes, supports odd quantities and preserves the best valid
result on timeout. It uses at most 15% of the nesting search time, capped at
one second, and competes with ordinary seeds/attempts under the selected
compact/strip score. No part geometry or manual lead override is changed.
A cold 18-part API regression with no placements returns 372×292.684 mm,
78.373% utilization, all 18 automatic leads and no validator findings.
Added six regression cases; full suite passes 273 tests / 3 optional corpus
skips. The scoped `kerfgrid_app` deployment preview passes (ok6/changed1/failed0).
Full browser smoke passed. The original 18-part project with its 12 s budget
and automatic workers returned the pair seed through local HTTP in 9.74 s,
8 workers, no parallel fallback and no validator findings. Standard scoped
apply completed ok8/changed3/failed0, restarting only KerfGrid. The real
toolbar Auto Nest button on nh02 then returned the same 372×292.684 mm in
10.49 s with 4 workers; shared workspace revision 33 contains that result.
Readback proves original parts, sheet, cut settings and post settings unchanged.
Evidence: `output/2026-10-15-nest18-auto.project.json`,
`output/2026-10-15-nest18-live-{before,auto}.project.json`,
`output/2026-10-15-nest18-auto-proof.json`, local export
`output/2026-10-15-nest18-auto.ngc`. No controller request was made.

Live inspection exposed an existing selected-part hint that reported bounding
box overlap as collision even while exact validation showed No issues.
The hint now uses current exact collision validation to clear that provisional
warning and invalidates the result on geometry changes. Stale validation
responses cannot clear warnings for a changed layout. Added a browser regression
with opposing triangles whose bounds overlap while their contours retain the
6 mm gap. Final full browser rerun passed. Scoped UI check/apply passed
(ok8/changed3/failed0); live app.js exactly matches local bytes. Reloading
the live saved 18-part layout shows Valid / No issues and clears the false
selected-part hint. Screenshot:
`output/playwright/2026-10-15-nest18-auto-live.png`.

The user's long red diagonals were G0 moves. Simulation's completed-path overlay
incorrectly joined all segment types into one solid red polyline. Split completed
cuts at rapid/pierce segments, preserving types during partial interpolation;
rapid traverses remain dashed after playback (`web/js/simulation.js`).
At 2 s / 12 attempts / allowed rotations, all 6 circles, 8 rectangles and 9
mixed parts fit without validation issues. Mixed strip uses 658×191 mm and
compact 384×308.994 mm. This is a bounded heuristic search.

Validation: 267 pytest tests passed, 3 optional corpus gates skipped. Full
Playwright smoke passed including both mode changes, selector width and
cut/rapid separation. A fresh
backend/reload additionally confirmed compact mode persisted on the server.
Standard `kerfgrid_app` check and apply from Mac succeeded on nh02
(`ok=8 changed=3 failed=0`); only KerfGrid restarted. Live HTML, app.js and the
new simulation module match local
bytes and `/api/cut-chart` serves the new profile with all rows at 5 bar.
Current shared production project was read, not replaced by benchmark data.

Evidence: `output/2026-10-15-nesting-review.json`,
`output/2026-10-15-block-review.project.json`, real 4/8-tab fixtures in
`tests/fixtures/eave-tabs-{staircase,block}.project.json`,
`output/2026-10-15-block-verification.json`,
`output/playwright/2026-10-15-nesting-block.png` (actual project copy, simulation
complete with dashed rapids), `output/playwright/2026-10-15-nesting-modes.png`, and under
`output/linuxcnc/physical/`: `2026-10-15-first-cut-a.png`,
`2026-10-15-first-cut-b.png`, `2026-10-15-pierce-source.project.json`,
`2026-10-15-pierce-corrected.ngc`, `2026-10-15-pierce-verification.json`.
The final 8-part export is `2026-10-15-block-corrected.ngc` in the same directory;
it was validated locally, not loaded into the controller. The original UI
failure screenshots are `output/playwright/2026-10-15-user-{staircase,external-leads,vertical-strip}.png`.
Physical cut after the CAM fix remains for the operator to verify.

## 2026-10-15 Ignition Indicators And Main Layout

User requested identification of the actual arc indicator and a main-screen
layout review/fix. Explained Torch Enable permission, Torch On command output
and Arc OK confirmation separately. Fresh read found idle E-stop, no torch or
motion, original 4 mm job loaded, display 1280x1024. The old screen put DRO at
the bottom, reserved empty user-button rows and separated the arc/torch controls.

Added opt-in `Workshop main layout` for the physical Mode 2 target. The supported
custom extension loads `qtplasmac_layout.py` after native signal setup and
reparents existing widgets: controls/DRO/actions/sliders left, resizable
preview/code split centre, ignition/THC/sensors/options/jog right. Explicit
Russian labels distinguish ignition permission, amber command LED and green
arc confirmation. Empty slots are hidden and refresh when native button
settings are saved. Existing HAL objects, signals, callback behavior, checkbox
values and cut-recovery pages are preserved. Package UI files are untouched.

Validation: 111 existing regressions passed; 14 role checks passed after adding
the opt-in deployment check. Seven Qt tests ran in an isolated offscreen
process using a standard-widget copy of the installed UI: layout 1280x1024,
label fit, independent toggles, retained callbacks, empty-slot visibility,
settings-save refresh, idempotence/cut-recovery and other-mode fallback.
Initial style/widget-fixture issues were fixed before deployment. Scoped
standard playbook check/apply succeeded; final correction selected only the
layout module. Normal GUI restart and native reload restored the user's
original source drawing, with the live preview checked visually. HAL Tcl hash,
software XYZ 89.85/9.35/45 and work offsets remained unchanged; PH=CH=8.

No jog, HOME, probe or cut cycle was issued. Left E-stop, idle, queue 0,
torch/probe/motion disabled. Restart clears homing; HOME ALL is required
before operation. Backup:
`/home/dslimp/linuxcnc/configs/kerfgrid-plasma-before-main-layout-20261015`.
Evidence under `output/linuxcnc/physical/`: `2026-10-15-main-before.png`,
`2026-10-15-main-workshop.png`, `2026-10-15-main-layout-verification.json`.
Updated role README and the controller process guide. Actual arc ignition
and electrical Arc OK remain outside this UI-only verification.

## 2026-10-14 THC Disable During Cutting

User reported Arc Lost / No Arc after 3 starts and clarified the required
behavior: unchecking GUI THC ENABLE during a cut must stop height correction
while cutting continues. Read the current GUI, NML/HAL and MACHINE LOG without
starting motion. Logged cycles began with Torch disabled; native Arc Lost
requires Torch Enable during cutting, so exact subsequent torch-toggle timing
is not established by the cycle-start log. Current Torch/THC and Arc OK were
false. Live nets show separate GUI THC, Torch and physical Arc OK signals;
the custom extension contains no THC/torch/arc overrides. PlasmaC 1.238 and
official QtPlasmaC docs already implement the requested height-only toggle.

After fresh explicit confirmation that stepper power was disconnected and
tests were authorized, ran the actual loaded 4 mm job with LPT torch output
isolated and FLOAT/Arc OK/Up/Down simulated. THC on moved Z up/down; unchecking
it while Up remained asserted held Z29.30606, with XY moving 51.70 mm over
433 samples. The Down case held Z27.96092, XY32.50 mm over 435 samples. No
pause, torch logic and virtual Arc OK remained active, physical output stayed
false; full job completed in 22.69 s. No production configuration change needed.

Finally aborted/stopped, restored original software XYZ 89.85/9.35/45 within
0.001 mm and all five physical HAL links, preserving G54/G92 offsets, homing
and loaded file. Fresh read verified E-stop, idle, empty queue, no active
torch/THC/sensors/motion. The UTM simulator was unavailable; live test used the
explicit disconnected authorization. Actual arc ignition/physical Arc OK
remain unverified. Added the operating distinction to the process guide.
Evidence under `output/linuxcnc/physical/`: `2026-10-14-arc-error.png`,
`2026-10-14-arc-machine-log.png`, `2026-10-14-thc-toggle-verification.json`.
Remote detailed samples: `/home/dslimp/linuxcnc/bench-thc-toggle-20261014.json`.
Reference: https://linuxcnc.org/docs/2.9/html/plasma/qtplasmac.html (2026-10-14).

## 2026-10-13 Float Switch Pause During Initial Z Move

User reported a surface-test touch followed by Operator Error and requested
direct inspection. Initial read-only SSH inspection of the workshop controller
`.68` captured the GUI and LinuxCNC/HAL state without machine commands or settings
changes.
GUI reports `float switch activated, program is paused` twice and a separate
`Unexpected realtime delay on task 0 with period 40000` warning. Screenshot:
`output/linuxcnc/physical/2026-10-13-operator-error.png`.

NML: AUTO, paused, current line 29 / motion line 28, queue 3, XYZ homed,
position `(0,0,37.4446624)`, G54/G92 offsets zero. Loaded job remains
`kerfgrid_job_live-axiqbgv1.ngc`; line 28 is the native filter's initial
`G53 G0 Z[MAX_LIMIT-5]`, i.e. Z45 with current MAX_LIMIT=50. This snapshot is
before M3/IHS; `plasmac.probe-test=false`, torch enable/on false, float input
and debounced float true, ohmic/breakaway false, Z external offset zero.
No PROBE TEST custom button is configured (FRAME/OUTLINE/JOB only).

Existing probe parameters: speed 642 mm/min, start height 25, float travel 3.
Z manual HOME still assigns the current position to zero, limits 0..50.
If the reported downward motion happened during this positive Z45 move,
physical Z direction is opposite QtPlasmaC's expectation; physical direction,
repeatable Z reference and float release still require operator-side proof.
Do not infer direction from commanded/software-feedback position alone.

Realtime base period 40 us, thread execution maximum 191416 CPU clocks, servo
maximum 341096 CPU clocks on this x86 controller. The earlier interpretation
as nanoseconds was incorrect; do not convert without proving the clock scale.
These are accumulated execution maxima, not measured latency-test jitter or
timestamps of the float fault. PREEMPT_RT, CPU1 isolation, nosmt and
performance governors remain enabled; realtime threads run on CPU1 and all
observed device IRQs on CPU0, including USB/Radeon. Delay cause remains unknown;
no stress test was started on the connected machine. The running session has
been up nearly three days; popup chronology is not established.

User then explicitly instructed the agent to press the controls. Issued NML
`abort()` (CYCLE STOP) and independently verified INTERP_IDLE, paused=false,
queue=0, inpos=true and the exact unchanged XYZ position. HAL confirms torch
on=false, probe-test=false and state-out=0; float remains true. Closed the
Operator Error notification using its visible Close button and verified the
fresh screenshot: `output/linuxcnc/physical/2026-10-13-after-cycle-stop.png`.
The user confirmed that the nozzle was touching the table. An initial bounded
Z- jog was blocked by the active float input and displayed `Float Switch has
disabled jogging`. Used the documented SETTINGS `Override Jog` checkbox for
one incremental Z- move of 0.25 mm at 30 mm/min, then restored the checkbox to
false. Software feedback changed Z from 37.4446624 to 37.1946627, X/Y unchanged;
float remained true. Physical movement and direction were not verified.
This recovery step was premature because the physical upward direction had
not been proven; no further motion is allowed on that assumption.

After the user questioned the movement, issued abort and Z jog-stop only.
Fresh readback: manual/teleop, interpreter idle, queue=0, inpos=true, unchanged
XYZ `(0,0,37.1946627)`, state-out=0, override-jog=false, jog-inhibit=true,
float=true and torch enable/on=false. No homing, resume, torch command,
controller configuration change, restart or latency stress test was issued.
Physical Z direction and safe retraction remain unverified; active realtime
warning prevents declaring the machine ready.

Unbounded AT-SPI traversal stalled; screenshot and bounded NML/halcmd reads
provided evidence, and the verified diagnostic process alone was terminated.

User clarified the observed sequence: the nozzle touched the table, the sensor
activated, then the error appeared. Accepted that physical sequence; neither
the NML snapshot nor a presumed axis sign replaces it. Subsequent inspection
of STATISTICS → MACHINE LOG found `Cycle started - Torch disabled`, followed
by cycle pause and the float-switch error, then a resume and repeated float
pause. Probe time is zero, rapid time four seconds, torch starts zero. The log
contains no `Probe test started` event. Its controller-local timestamps put
the contact/pause at Sat10 16:45 and the separate realtime delay at Sun11 18:35,
so the realtime notification was not generated at the same recorded contact.
The probe test control is absent from the active user-button configuration.
QtPlasmaC treats float input as a protective stop outside probing; normal
PROBE_DOWN contact instead transitions to PROBE_UP. This explains the observed
pause classification; the physical Z direction and cause of the unintended
contact still require proof. No further motion or settings changes made.
Screenshot: `output/linuxcnc/physical/2026-10-13-machine-log.png`.
Corrected the LinuxCNC diagnosis workflow to require physical direction before
contact recovery, and x86 thread tmax units in the access reference.

Further read-only proof: raw HAL probe-time=0 exactly (not a rounded GUI
display), rapid-time=3.722, pierce-count=0 and cut-time=0. The GUI process uses
`qtplasmac_s_metric.ini.expanded`; LinuxCNC's own INI parser confirms effective
JOINT_2 HOME/HOME_OFFSET=0, SEARCH/LATCH/FINAL velocities=0, STEP_SCALE=1000 and
Z limits 0..50. NML confirms the same active joint limits. Source Mach3 had
soft limits disabled, with its M3 macro using G31 Z-50, G92 Z-3 and G0 Z8;
copying its ranges/home number does not establish the native QtPlasmaC Z basis.
The active STEP/DIR pin mapping matches the imported indexed fields, but this
does not prove electrical or physical direction equivalence on the new PC.

Matched the installed QtPlasmaC 2.9-238.315 component to upstream plasmac 1.238:
IDLE + active float + running program generates the exact observed pause text,
whereas PROBE_DOWN contact transitions to PROBE_UP. Initial line 28 requests
Z45 before XY line 29 and M3 line 30; no probe offset or probe time was present
at the fault. The stop is the expected protection for contact outside probing;
the unintended contact during this startup move points to Z direction/basis
commissioning, not a Float Travel adjustment. Physical upward direction is
still pending; no additional motion, homing or configuration changes issued.

Corrected a separate process-document error discovered during this trace:
Torch Enable=false does not suppress IHS in JOB. HAL connects spindle.0.on
directly to plasmac.cutting-start, and component 1.238 starts probing regardless
of torch-enable; that input prevents ignition later at pierce height. Thus JOB
dry runs require proven Z direction/reference and Probe Test first. FRAME and
OUTLINE do not establish probe calibration. The original fault occurred before
M3; the disabled torch itself was not the reason probing had not begun.
Physical direction observation remains the required missing proof for choosing
a live recovery direction or accepting the Z configuration as physically proven.

User then confirmed motor power is disconnected and authorized configuration
preparation for later operator testing, also requesting one-button XYZ work
zero after keyboard positioning. Applied the standard LinuxCNC playbook from
Mac under the documented disconnected preparation exception, with only
`qtplasmac_controls,plasma_machine_motion`; check/diff showed exactly the new
controls/speeds and three Z settings. Explicit candidate physical axis overrides
set Z STEP_SCALE=-1000 and manual HOME/HOME_OFFSET=45, leaving the imported
source and UTM defaults unchanged. This follows the observed contact during
the positive startup move; physical upward direction and usable 0..50 travel
are still unproven. HOME is for an established upper machine reference, not
the current table contact point. Search/latch/final homing speeds remain zero.

Added native button 4 `PROBE TEST` (`probe-test 10`) and button 5 `Ноль XYZ`
(`G10 L20 P0 X0 Y0 Z0`, active work coordinates, no movement). Native handler
requires idle/homed status and reloads the preview after G10 L20. Set setup
and probe speeds to 100 mm/min and startup jog to 100 mm/min. Maintained
Float Travel=3 pending measurement. Added per-target calibration overrides,
validation and scoped update tags; rendered motion references and pin map
reflect effective calibration while source metadata stays immutable.

Before apply, set Machine OFF and E-stop, verified unchanged XYZ/empty queue,
closed QtPlasmaC normally and backed up the config to
`/home/dslimp/linuxcnc/config-backups/kerfgrid-plasma-before-z-controls-20261013`.
Apply completed: ok=13, changed=6, failed/unreachable=0. Synced the motion
README/pin-map through the reference-only tag: ok=5, changed=1, failed=0.
Restarted the standard user launcher. Fixed the clipped Probe Test label via
native SETTINGS user-button Save to `PROBE\TEST`, matching the updated role
default; command codes remained unchanged. Screenshot:
`output/linuxcnc/physical/2026-10-13-z-controls.png`.

Live native parser confirms the new values in the actual `.expanded` INI;
HAL confirms probe/setup rates=100 and stepgen.2.position-scale=-1000.
Final state: E-stop, Manual, interpreter idle, queue=0, inpos=true, XYZ unhomed,
actual software position still `(0,0,37.1946627)`, no loaded file. Torch enable,
torch on, probe test, override jog, motion enabled and P1.14/P1.9 enables are
all false. FLOAT is still true, so the nozzle/contact must be released before
physical testing. Source-import and active parport Tcl SHA256 remain identical.
No further axis motion, HOME, zeroing or probe cycle was issued during this
preparation. Targeted role/import tests: 66 passed; YAML lint and diff checks
passed. Updated the process note with keyboard/work-zero usage and staged
operator checks. Physical direction, reference/stroke, float travel and the
separate historical realtime delay remain first-cut blockers to verify.

Follow-up: user requested fixing the main window. Live screen is 1280x1024;
the stock 4:3 UI fixes `main_middle_frame` at 136 px, clipping button labels.
Added an opt-in 208 px main control column through the supported
`qtplasmac_custom.qss`, 11 pt button labels and no outlines on unconfigured
buttons. Applied only `qtplasmac_screen` (display selection unchanged,
stylesheet added); normal restart loaded it and MAIN visibly fits all controls,
including the complete `Ноль XYZ` label and Probe Test. Preserved a config copy
at `/home/dslimp/linuxcnc/config-backups/kerfgrid-plasma-before-main-screen-20261013`.
Native stylesheet generation includes the extension without parse errors.
Final NML/HAL remains E-stop, idle, queue zero, XYZ unhomed at the identical
position, torch/probe/override/motion enabled false. No motion or HOME issued.
Role tests: 12 passed; YAML lint/check diff passed. Screenshot:
`output/linuxcnc/physical/2026-10-13-main-screen-fixed.png`.

Further follow-up: user again confirmed stepper power is off, authorized all
bench controls and clarified that FLOAT is the only physical switch. Replaced
the earlier fixed upper-reference workflow with HOME at the selected sheet
origin: X/Y HOME=0, Z HOME=35, no search/latch/final homing movement. X limits
are -1300..1300 and Y -2250..2250, using the original travel extents; Z remains
0..50. The unchanged native initial Z45 move now gives a 10 mm software lift.
Actual HOME ALL and Ноль XYZ GUI tests changed coordinates without changing
step counts. Config backup: `before-sheet-origin-20261013` inside the machine
config directory. A broader unbounded-range/filter-change proposal was rejected
by automatic review and was not applied; the narrower native-filter solution
was subsequently accepted and deployed through the standard motion role.

Fixed native delayed startup signal subscription: replay current sensor and
jog-inhibit values after connection, so startup FLOAT no longer leaves Override
Jog disabled. Merely setting the preference True had not proved the fix.
PgUp with simulated FLOAT now sustains Z+ and clears override after release.
Probe Test uses 30 seconds total, including search/retract; the previous
10-second total could expire before a slow search reached pierce height.
At the user's request restored Mach3 manual XY=7998 and Z=642 mm/min,
setup/probe=642. The old macro's F800 remains bounded by the original Z642
motor limit. XY acceleration=1000 and Z=143 mm/s² are unchanged.

Found the remaining premature-stop cause through native ABORT call stacks and
raw evdev proof: wired `USB usb keyboard` `/dev/input/event2` continuously holds
KEY_ESC, with 151 repeat events in six seconds and the held bit True. The
separate 2.4 GHz keyboard did not emit Esc. Native Esc/STOP remains enabled;
user-side release or unplugging of the faulty wired keyboard is pending. A
temporary EVIOCGRAB only during authorized bench tests isolated this device;
it was released afterwards. Optional private jog tracing is off in the final
normal session. Strengthened the canonical live-jog proof to require sustained
nonzero HAL velocity throughout the hold, because changed endpoint positions
had hidden an early stop.

With faulty input temporarily isolated, all 12 GUI keyboard/mouse direction
holds sustained XY133.3/Z10.7 mm/s and stopped on release; intentional Esc also
stopped a held jog. Simulated FLOAT Probe Test completed down/contact/up/pierce
and returned to start. The actual KerfGrid circle/hole job completed in 90.22 s
with two IHS contacts, initial lift 10 mm, virtual pierce gap 3.009..3.021 mm
and cut gap 1.516..1.531 mm. Torch enable/on stayed false throughout. FLOAT's
real parport net was restored; its Tcl hash matches the pre-change backup.
These are software bench proofs, not physical movement/direction calibration.

Final normal restart and native loader verified the circle/hole preview.
Left E-stop, idle, queue zero, XYZ unhomed, torch/probe/override/motion disabled,
real FLOAT false. Regression suite: 110 passed; YAML lint and diff checks pass.
Evidence: `output/linuxcnc/physical/2026-10-13-bench-verification.json` and
`output/linuxcnc/physical/2026-10-13-final-sheet-origin.png`. Before physical
cutting, release faulty Esc, prove PgUp raises the torch, measure Z clearance
and float travel, perform a real torch-off Probe Test, and resolve the separate
historical realtime warning. Physical Z direction/stroke remain unverified.

Follow-up: user reported insufficient retraction and nozzle scraping, requested
the old Mach3 height and a visible GOTO HOME, and freshly confirmed the stepper
PSU is off. Read the actual `Mach3/macros/plasma/m3.m1s`: after touch-off Z-3 it
uses G0 Z8 and has no separate lowering before cutting. The earlier bench had
only proved its then-configured PH3/CH1.5, not physical clearance. Restored
PH=CH=8 in controller material 0 and all 13 Fubag starter rows in KerfGrid;
kept feed, acceleration, delay, kerf, amperage and external THC behavior.
This is the historical initial height, not a manufacturer cut-height claim.
Deployed through the standard scoped controller and nh02 playbooks, restarted
the existing local KerfGrid service, regenerated and sent the circle/hole job
through `/api/send-linuxcnc`; upload, native load and preview succeeded.

Added MAIN button 6 GOTO HOME beside Ноль XYZ: raise to machine Z45 first,
then active work X/Y0, leaving Z raised and offsets/HOME unchanged. Native
multi-block user-button MDI could return to Manual before XY completed;
replaced it with one O subroutine and asynchronous completion tracking.
STOP/Esc cancels the whole program, including during the lift, with no later
motion callback. The standard controls update also refreshes the stylesheet
so the new button retains its border instead of inheriting empty-button styling.

Authorized software bench: full GOTO ended X/Y within 0.001 mm of zero at
Z45; Esc during its lift stopped Z38.515 with X/Y unchanged. Probe Test
completed in 30.86 s with virtual gap 8.018..8.021 mm. The complete job ran
88.91 s with two IHS contacts and initial pierce/cut gap 8.004..8.021 mm.
Torch enable/on stayed false; the simulated FLOAT sink was restored to
`parport.0.pin-15-in => db_float.in`. The earlier event2 keyboard was absent
and these runs used no temporary keyboard isolation. Controller regression
suite: 111 passed; KerfGrid: 237 passed, 3 optional corpus skips; browser smoke,
YAML lint and diff checks passed. The later stylesheet tag check: 13 passed.

Normal GUI verified PH8/CH8, the loaded circle/hole, and matching deployed
custom-extension/subroutine hashes. Left E-stop, idle, empty queue, in position,
XYZ unhomed, torch/probe/motion disabled and real FLOAT false. Backup:
`/home/dslimp/linuxcnc/configs/kerfgrid-plasma-before-height-return-20261013`.
Evidence: `output/linuxcnc/physical/2026-10-13-height8-return-verification.json`,
`2026-10-13-height8-transfer.json` and `2026-10-13-height8-goto-home.png` in
the same directory. Actual nozzle gap/Float Travel still need a physical
torch-off Probe Test; software feedback does not establish the measured gap.

## 2026-10-10 Remove Sheet Edge Margin

User requested removal of the sheet edge margin, keeping spacing between parts.
Remove the UI control and inset boundary, use the full sheet for import,
placement, validation and auto nesting, and omit the margin from new projects
and review exports. Existing placements retain their coordinates; legacy
version 1 margin fields are ignored. Project format is now version 2; browser
local storage and Python file round-trips preserve placements and spacing while
dropping the legacy field. Removed the UI's additional 0.25 mm placement inset.
Existing lead/crater warnings remain visible when a toolpath extends past the
declared sheet bounds; exports remain warning-only.

Validation: 237 KerfGrid pytest tests passed, 3 optional local DXF corpus tests
skipped; full `tests/playwright_smoke.sh` passed, including import of a version 1
project with margin 99 and save as version 2. Visual inspection confirms no
Margin control/inset rectangle and a nested circle touches X0/Y0. Screenshot:
`tools/plasma-cam/output/playwright/no-sheet-margin-2026-10-10.png`.
Local launchd service `com.kerfgrid.local` restarted on port 8765.

Prepared `kerfgrid_app` tags on the existing source-copy/bytecode cleanup tasks
for application-only rollout. All 15 `tests/test_kerfgrid_role.py` tests passed;
local Ansible `--list-tasks` selects exactly those 6 tasks and excludes nginx,
packages, runtime and transfer setup. User explicitly approved the one-task Mac
execution exception because the documented remote worker is not configured.
Canonical `agent-read ansible-check` passed: 4 ok, 2 changed, 0 failed. Applied
`nh02.yml --limit nh02 --tags kerfgrid_app --skip-tags always
-e ansible_port=22`: 6 ok, 4 changed, 0 failed; only KerfGrid restarted.

Live browser/API acceptance at `http://192.168.88.61/kerfgrid/` passed: Margin
control absent, Spacing retained, browser project version 2 has no legacy margin.
Two 47x40 mm rectangles with 6 mm spacing fit a 100x40 mm sheet at
`(0,0,47,40)` and `(53,0,100,40)` even with a legacy 25 mm margin in the input.
Outline export reaches X0/Y0 and X100/Y40; shrinking the spacing by 0.5 mm
correctly reports `part_collision`. Live UI screenshot:
`output/playwright/no-sheet-margin-live-2026-10-10.png`.
No controller load/motion/output operation was part of this update.

## 2026-10-10 KerfGrid Send Over Workshop Wi-Fi

User requested end-to-end verification of KerfGrid-to-controller delivery.
Live UI at `http://192.168.88.61/kerfgrid/` returned HTTP 200. The normal
`POST /api/send-linuxcnc` with `examples/circle-hole.project.json` initially
returned HTTP 400 / `No route to host`: nh02 still targeted Ethernet `.73`.
Controller identity at Wi-Fi `.68` was verified against the existing `.73`
ED25519 key; controller was idle, inpos, queue 0, torch FALSE, no loaded file.

Updated nh02 transfer host and verified known_hosts name to `.68`; unchanged
key and native `/usr/local/bin/linuxcnc-load` override retained. Updated role
tests and README to reflect current endpoint and native GUI filtering.
All 14 transfer-role tests passed. Narrow Ansible check-mode showed only the
known_hosts addition and environment address change. No configured remote
worker was found; user explicitly approved one-task local apply plus DHCP
reservation. `agent-write mikrotik pin-dhcp-lease` made exact Wi-Fi MAC
`A0:47:D7:63:57:B6` / `192.168.88.68` static on mk01/dhcp1 and verified bound
readback. Applied only `nh02.yml --limit nh02 --tags kerfgrid_transfer
--skip-tags always -e ansible_port=22`: 11 ok, 3 changed, 0 failed; only
KerfGrid restarted. Reservation recorded in nh02 host inventory; physical
controller README now names the reserved Wi-Fi endpoint.

Preserved previous two live NGC files on the controller in
`/home/dslimp/linuxcnc/nc_files/kerfgrid/before-wifi-send-20261010-blsxhwlk`.
Repeat native API send returned HTTP 200, uploaded=true, loaded=true,
warnings=[], load_error=null, host `.68`; job 1024 bytes and outline 337 bytes,
both owned by dslimp (uid/gid 1000). NML reported
`/tmp/emcflt-t_r_57ho.d/kerfgrid_job_live-axiqbgv1.ngc`, with the native
QtPlasmaC filter marker. Actual GUI showed outer circle and central hole,
temporary material 1000000 and no load warning. Final interpreter idle,
queue 0, inpos true, torch FALSE; actual XYZ remained exactly
`116.738999872352, 3.9872247726e-7, 9.444355965e-8`, equal to the pre-send
snapshot. No motion, power, torch or cycle commands sent. Test job is left
loaded in MAIN for operator inspection; physical cutting was not tested.
Evidence: `output/linuxcnc/physical/2026-10-10-kerfgrid-send-result.json` and
`output/linuxcnc/physical/2026-10-10-kerfgrid-send-preview.png`.

## 2026-10-10 Keyboard Jog After Workshop Move

User moved the physical LinuxCNC PC to the workshop and connected it through
Wi-Fi. LPT is connected; user reports stepper power is currently off and mouse
jog had moved the axes earlier. No motion, power, torch or restart commands sent.
Old Ethernet address `192.168.88.73` timed out. Canonical mk01 DHCP read found
`linuxcnc`, Wi-Fi MAC `A0:47:D7:63:57:B6`, bound dynamic address `192.168.88.68`.
An explicitly approved one-file SSH read verified the old SSH host key through
`HostKeyAlias=192.168.88.73` and read the existing `kerfgrid-plasma.prefs`:
`[GUI_OPTIONS] Use keyboard shortcuts = False`. User then explicitly requested
live enablement. Selected SETTINGS and toggled the unique KB Shortcuts checkbox
through AT-SPI; live CHECKED and saved `Use keyboard shortcuts = True` verified
in a fresh uncached accessibility session. Backed up the previous preferences
as `kerfgrid-plasma.prefs.before-keyboard-20261010` in the same controller config
directory; compared all parsed preference keys to prove only the requested
boolean changed. Returned MAIN and verified SETTINGS controls were hidden.
QtPlasmaC PID remained 1266; no restart or machine commands. AT-SPI traversal
initially encountered stale object paths; `Atspi.Cache.NONE` plus immediate
target lookup allowed the final independent GUI check to pass. One SSH timeout
was followed by fresh same-MAC DHCP confirmation and successful reconnect.
Stock XY arrow and Z Page Up/Down bindings are now enabled. Added
`Use keyboard shortcuts: "True"` to `tools/linuxcnc/physical-controller.yml`;
YAML parse passed. Physical keyboard jog remains unverified because motion was
outside this change. KerfGrid's old `.73` transfer target was fixed and Wi-Fi
delivery verified in the subsequent task recorded above. Source: LinuxCNC 2.9 QtPlasmaC manual,
https://linuxcnc.org/docs/2.9/html/plasma/qtplasmac.html#_keyboard_shortcuts.

## 2026-09-10 Physical Plasma Computer Preparation

User explicitly set the goal to prepare the entire physical controller, migrate
working Mach3 settings, and run required tests. PC is disconnected from the
machine and nothing is attached to LPT. Plan: bounded CPU/memory/disk/OpenGL
latency load and SSD diagnostics; source-profile audit; reproducible deployment
of QtPlasmaC Mode 2 on the existing XFCE desktop; offline motion and G-code/UI
acceptance; KerfGrid transfer. Do not claim physical polarity, wiring or torch
function verified while disconnected. Keep direct SSH and avoid enrolling the
controller in the main inventory solely for access.

Corrected grossly wrong system date and installed stress-ng, smartmontools and
systemd-timesyncd (no kernel upgrade). Started a bounded 300-second stress run
with four CPU workers, 512 MiB memory, limited file I/O and glxgears. SSD short
self-test started; initial SMART health passed with no reallocated, pending or
uncorrectable sectors. Under initial load jitter increased to base 30538 ns,
servo 27587 ns; baseline idle result is not acceptance under load.

Completed first 300-second load: base jitter 41990 ns, servo 56401 ns; all
stress workers passed. SMART short self-test completed without error. Applied
existing controller role to physical PC with inline inventory and explicit vars
in `tools/linuxcnc/physical-controller.yml`, preserving XFCE and official ISO
APT repositories. Fixed prefs filename to follow `[EMC]MACHINE`, set Mode 2,
installed English launch shortcut and notification/runtime dependencies, kept
autostart off during acceptance. No physical HAL or motion started yet.

After `nosmt isolcpus=1` and performance governor, the second five-minute CPU,
memory and uncapped Radeon load initially looked good, but final maxima were
base 979528 ns and servo 108130 ns: failed realtime acceptance. `/proc/interrupts`
proved USB and Radeon IRQs were on the isolated realtime CPU1. Added
`irqaffinity=0` through the same role, rebooted and verified all device IRQs on
CPU0. Third equivalent bounded load passed: final base jitter 12271 ns, servo
20780 ns, all stress workers passed, GPU sustained about 2300-2700 FPS.
Stopped the latency test before starting LinuxCNC. Never use a partial early
latency snapshot as the completed test result.

Source audit confirmed indexed Mach3 inputs using the official SDK enum:
Probe P1.15 active-high, ArcOK P1.12 active-low, THC up/down P1.10/P1.11
active-low. Enabled emergency input points to P0.0, not a physical pin. Legacy
named P2 fields are stale; P2 is disabled. Enable outputs are P1.14/P1.9,
torch P1.17. Source Y axis has a separate reversal in addition to DIR polarity.
Role corrections and executable Tcl tests passed before hardware deployment.

Applied the physical profile successfully and started the actual parport HAL:
Mode 2, X/Y/Z step scales 160/-160/1000, 40000 ns base period and double-step
reset 5000 ns. Bounded offline XYZ moves reached (100,100,10), (800,1500,30)
and returned to zero; corresponding counts matched (16000,-16000,10000),
(128000,-240000,30000), (0,0,0). Maximum observed software following error
was about 0.184 mm during motion, not a physical positioning measurement.
Torch output remained false. Temporarily disconnected only the high empty-LPT
float input during the test, then restored its physical connection and E-stop.
Initial test harness incorrectly treated NML acknowledgement/short timeout as
motion completion; corrected acceptance to actual target plus idle/inpos/empty
queue. No source geometry or cut-validation behavior changed.

Full apply exposed an obsolete QtPyVCP signing key in the installer ISO.
Opt-in ISO repair uses the official current key with fingerprint
50F874571F20C5B0BA225E2F0CDFCCE0388CFA48, retains signature checks and backs up
deduplicated sources. Fixed package refresh passed. The desktop screenshot
was initially obscured by an already-active screensaver; deactivation in the
GUI user's DBus session revealed QtPlasmaC. Its remembered widescreen geometry
clipped controls on 1024x768, so the physical profile now requests native 4:3
fullscreen. Native GUI load integration was then installed and accepted below.
Local controller/import/load tests: 97 passed, including real IPC reconnect.

Final nominal axis tests passed after allowing the stock GUI's return from MDI
to MANUAL between commands: peak software step rates X 21928 Hz, Y 21728 Hz,
Z 10878.75 Hz, below double-step capacity 25000 Hz. JOB was clicked in the real
GUI and loaded its canonical file. First automated attempts raced the GUI's
post-homing mode changes; these were test-driver errors, not successful tests.
Actual loaded preview showed the outer circle and central hole. A separate
native OUTLINE load exposed a material-feed warning for literal F3000; changed
only dry-outline feed to a named parameter. KerfGrid full tests: 230 passed,
3 optional external-DXF audits skipped; Playwright smoke passed.

Closed QtPlasmaC using its actual shutdown dialog, without the segfault seen
when an earlier transient unit stopped GUI and RT processes simultaneously.
Reboot acceptance passed: XFCE automatically starts fullscreen QtPlasmaC,
Mode 2, E-stop active, power/torch off, no homed axes or auto-running file.
Boot args, CPU1 isolation, all IRQs on CPU0, performance governor and NTP
synchronization persisted. Current-startup session log has no RTAPI/GUI fault.
Ansible/interface/import/load tests: 111 passed; scoped YAML lint passed.
Full KerfGrid deployment to nh02 passed check-mode and apply (32 ok, 4 changed,
0 failed). After controller reboot, the live send API returned HTTP 200 with
uploaded=true, loaded=true and no warnings; the native QtPlasmaC filter and
preview loaded the normal job. Corrected OUTLINE feed was deployed too.

Applied narrow `kerfgrid_transfer` tag on nh02 after successful check-mode:
destination is 192.168.88.73, verified SSH host key installed, service ED25519
key generated without replacing existing keys. Only public key is captured in
physical vars; private key remains on nh02. Live filter/UI acceptance completed,
not merely SCP or a direct NML request.

Final acceptance completed on 2026-09-11. Actual GUI OUTLINE loaded only the
outer circle, without the hole or a material-feed warning. CYCLE START completed
the dry path in 33.52 seconds with no interpreter errors; 1108 sampled torch
states were all false. Final position was (450,250,45): native QtPlasmaC filtering
adds the safe Z retract. An initial GUI test clicked POWER before the widget
updated after E-stop release; waiting for the GUI update resolved it, without
configuration changes. Final controller state: E-stop active, power and torch
off, physical float input reconnected. Cleared all three test homed flags before
handoff; no test signal override remains.

Durable screenshots: `output/linuxcnc/physical/2026-09-11-job-preview.png` and
`output/linuxcnc/physical/2026-09-11-outline-preview.png`. Offline preparation is
complete. Physical commissioning remains: wiring and E-stop chain, axes/direction
and measured scale, actual travel and Z reference, IHS/Arc OK/external THC, then
calibration coupons. Source soft limits were disabled and no valid physical
E-stop input was mapped, so source ranges and manual zeroing are not proof of
safe physical travel. Updated controller README, commissioning process and
`nh-repo-access` workflow; standing SSH exception is recorded in `AGENTS.md`.

## 2026-09-10 Live Physical Latency Readout

Read the running test directly over SSH as root, using
`runuser -u dslimp -- halcmd show pin` and `halcmd show thread`.
At process elapsed time 12:28, GUI-connected pins showed maximum base jitter
`lat.bj=11487` ns and servo jitter `lat.sj=15406` ns. Periods: base 25000 ns,
servo 1000000 ns. Verified the pin-to-GUI labels in `/usr/bin/latency-test`;
these are jitter measurements, not the thread execution-time `tmax` values.
No statistics reset, test restart, stress load, or machine output was performed.

Host has Intel i3-3220, LinuxCNC uspace 2.9.10, kernel
`6.12.95+deb13-rt-amd64` PREEMPT_RT. Kernel log and `/proc/ioports` confirm
onboard `parport0` at `0x378`, IRQ 5, PCSPP. This establishes the detected
port, not external wiring or machine readiness. `lp` currently uses that port;
resolve printer-driver ownership during commissioning, not during this test.
The machine journal clock shows April 13, unlike this task's September 10 date;
wall-clock timestamps need verification later. Elapsed runtime is from `ps`.

Current base jitter is below the official 15-20 us software-stepping guideline,
but load conditions and longer-run worst case remain unverified. Source read:
https://www.linuxcnc.org/docs/2.9/html/install/latency-test.html .
Learning: documented direct HAL GUI readout in the repo access skill. No extra
artifact needed beyond this log and the skill; BIOS and runtime unchanged.

## 2026-09-10 LinuxCNC Direct SSH Exception

User installed the root public key themselves and explicitly authorized a
standing LinuxCNC SSH exception after automated review blocked the login check.
Updated `AGENTS.md` to allow direct workstation SSH for physical controller
`192.168.88.73` and UTM `192.168.64.5`, without wrapper/inventory enrollment.
Scope now: verify root key authentication only; leave latency testing running.
Verified: `ssh -p 22 -o BatchMode=yes -o ConnectTimeout=10
root@192.168.88.73 id` succeeded with `uid=0(root) gid=0(root)`.
The active target is the physical computer with an LPT port, not the older
UTM VM. No services, machine settings, or test processes were changed.

## 2026-09-10 Physical Controller Network Handoff

User supplied the physical controller address `192.168.88.73`, login `dslimp`,
and a login password, and reports that the baseline latency test is running.
Initial read-only connection attempt through `linux-incident` returned an
unclassified `invalid remote JSON`; this did not prove SSH reachability.
User then explicitly narrowed the task: no inventory enrollment, install the
supplied RSA public key for root only. Removed the newly added inventory host
and its vars/SOPS files. Do not interrupt latency testing, restart services,
install packages, or apply the machine profile. UTM remains separate.

## 2026-09-10 Physical Controller First Latency Test

User reports completing the USB installation on the new SSD and reaching the
graphical desktop on the physical controller PC. BIOS settings, running kernel,
IP address, and measured jitter have not yet been inspected. The initial target
remains LPT/software stepping without Ethernet Mesa.

Next: leave BIOS settings unchanged for the baseline, close LinuxCNC/StepConf,
run `latency-test`, exercise graphics and disk activity for an initial 20-30
minutes, and capture both threads' maximum jitter in nanoseconds. This first
measurement is not final hardware acceptance. Change BIOS options individually
only when measured jitter calls for tuning; compare subsequent measurements.
Source: official LinuxCNC 2.9 latency-test documentation, read on 2026-09-10:
`https://www.linuxcnc.org/docs/2.9/html/install/latency-test.html`.
This is a commissioning state update; no new repository-wide guardrail or
additional artifact is needed, and no machine configuration was changed.

## 2026-09-10 LinuxCNC Controller OS Install Plan

User brought the physical plasma-control PC with a new SSD that can be wiped and
asked which OS to install and how to proceed. Scope: use prior QtPlasmaC/Mach3
migration context, confirm current official LinuxCNC install guidance, and give
a practical installation plan for the physical controller without changing live
machine state. No additional artifact beyond this log entry is needed unless the
user proceeds to the install/config application step.

Current recommendation after checking official LinuxCNC docs on 2026-09-10:
install the official LinuxCNC 2.9.x Debian 13 Trixie PREEMPT-RT amd64
Live/Install image on the new SSD, using an English UI, then run latency testing
before applying the hardware profile. Rationale: LinuxCNC's download page lists
2.9.10 as current and presents Debian 13 Trixie PREEMPT-RT as the PC install
image; official docs state fresh installs should use the Live/Install image,
machine control needs a realtime kernel, and PREEMPT-RT/linuxcnc-uspace is the
Mesa Ethernet-compatible path. If this old controller PC will use only a
parallel port with software stepping and latency is poor, evaluate the RTAI
variant after the initial PREEMPT-RT test; do not choose RTAI for Mesa Ethernet.
Follow-up correction: user clarified there will be no Ethernet Mesa board for
the initial physical machine. Treat the first physical-controller setup as
parallel-port/software-stepping unless new hardware is introduced. PREEMPT-RT
is still a reasonable first official ISO to install and test, but acceptance now
depends on base-thread latency for software step generation. If the real PC
shows poor latency, switch the plan to LinuxCNC RTAI for LPT or add Mesa later,
rather than spending time tuning an unsuitable PREEMPT-RT LPT setup.
Sources: `https://www.linuxcnc.org/downloads/`,
`https://www.linuxcnc.org/docs/2.9/html/getting-started/getting-linuxcnc.html`,
`https://www.linuxcnc.org/docs/stable/html/getting-started/system-requirements.html`,
`https://www.linuxcnc.org/docs/stable/html/install/latency-test.html`, and
`tools/plasma-cam/docs/linuxcnc-qtplasmac-mode2-process.md`.

## 2026-09-03 FreeCAD Bridge Remote KerfGrid Target

User clarified that FreeCAD export should publish into the deployed KerfGrid
service on `nh02`, not the old workstation-local `127.0.0.1:8765` server. Scope:
inspect the existing FreeCAD bridge endpoint handling, switch the default target
to the `nh02` deployment while preserving manual override capability, validate
with focused tests, and record the exact endpoint behavior.

Result: changed the FreeCAD bridge default API root to `http://192.168.88.61`
and default UI root to `http://192.168.88.61/kerfgrid`, while preserving
`PLASMA_CAM_URL` and adding split overrides `PLASMA_CAM_API_URL` and
`PLASMA_CAM_UI_URL`. The button now posts DXF import and pending-project API
calls to `nh02`, then opens `/kerfgrid/?pending_project=1`. Updated source docs
and synchronized the installed bridge copies under both FreeCAD `v1-1` and
legacy `Mod`/`Macro` directories. Validation: `python3 -m pytest -q
tools/plasma-cam/tests/test_freecad_bridge.py` passed with 17 tests; the
installed `v1-1/Mod` bridge module reports
`http://192.168.88.61/api/import-dxf` and
`http://192.168.88.61/kerfgrid/?pending_project=1`; a live
`POST /api/pending-project` against `192.168.88.61` returned `{"ok": true}`,
and the test pending project was consumed afterward so the slot is empty.

## 2026-09-03 KerfGrid Deploy To nh02

User asked to deploy the KerfGrid service to `192.168.88.61` (`nh02`). Scope:
inspect the existing repo service/playbook shape, add or reuse the narrow
Ansible deployment path, validate it, and apply it to `nh02` without ad hoc SSH
or alternate deployment flows. Initial target is the local KerfGrid service from
`tools/plasma-cam`.

Result: added the `kerfgrid` Ansible role, wired it into `nh02.yml`, enabled
the `nginx` role under the same `kerfgrid` tag, and exposed the service at
`http://192.168.88.61/kerfgrid/` through nginx while the Python backend binds
only to `127.0.0.1:8765` on `nh02`. The role installs a dedicated system user,
copies the current `tools/plasma-cam` application source, builds
`/opt/kerfgrid-venv`, installs `/etc/systemd/system/kerfgrid.service`, and
templates `/etc/kerfgrid/kerfgrid.env` for LinuxCNC transfer settings.
Validation: `python3 -m pytest -q tests/test_kerfgrid_role.py` passed;
`./bin/agent-read ansible-check --inventory inventory/hosts.yml --playbook
nh02.yml --limit nh02 --tags kerfgrid` passed; the live playbook apply
`/Users/user/.venvs/ansible-global/bin/ansible-playbook -i inventory/hosts.yml
nh02.yml --limit nh02 --tags kerfgrid` completed with no failures. Runtime
proof: `./bin/agent-read http-probe ... --url http://127.0.0.1:8765/` returned
HTTP 200 from `nh02`; Mac-side `curl` returned HTTP 200 for `/kerfgrid/`,
`/app.js`, `/styles.css`, `/js/http.js`, `/api/cut-chart`, and POST
`/api/validate` on the demo project returned `{"issues": []}`. `yamllint`
passed for the new role, `nh02.yml`, and nginx defaults; the full `nh02` host
vars lint still has pre-existing line-length warnings in Kodi/mount settings
outside this KerfGrid change.

## 2026-09-01 Plasma Machine Config Transfer

User asked to take the working Mach3 plasma cutter configuration from
`/Users/user/Documents/plasma/Mach3`, create an Ansible role, and transfer the
configuration into the LinuxCNC controller. Inspected the Mach3 `Plasma.xml`,
profile macros under `macros/plasma`, and the existing `linuxcnc_controller`
role. Important extracted facts: X/Y/Z are active; table travel is X 0..1300 mm,
Y 0..2250 mm, Z 0..50 mm; X/Y scale is 160 steps/mm, Z scale is 1000 steps/mm;
X/Y max velocity is 133.3 mm/s, Z max velocity is 10.7 mm/s; X/Y acceleration is
1000 mm/s2, Z acceleration is 143 mm/s2. The active torch relay is
`DoSpinCW()` -> `SpinCW=7` -> Mach3 `Output7` at port 1 pin 17, not the separate
`TorchOnPin` status field at port 2 pin 10. QtPlasmaC Mode 2 inputs from Mach3
are Arc OK candidate P2.11 active-low, THC up P2.12 active-low, THC down P2.13
active-low, and float/digitize P2.15 active-low. The Mach3 M3/M5 macros show a
probe move to Z-50 at F800, touch-off G92 Z-3, M3 retract to Z8, and M5 retract
to Z10. The role keeps the imported port/pin numbers as source-controller facts,
renders LinuxCNC reference files into the QtPlasmaC config directory, and applies
the axis/motion overlay to the active QtPlasmaC profile.

Result: renamed the target implementation from the legacy source-system wording
to neutral `linuxcnc_plasma_machine` / `plasma_machine` and set the UTM target
profile to `kerfgrid-plasma`. Added `tools/linuxcnc/extract_plasma_machine.py`,
`inventory/host_vars/linuxcnc_utm/plasma_machine.yml`,
`roles/linuxcnc_plasma_machine/`, and tests in
`tests/test_plasma_machine_import.py`. The controller role now templates a
neutral desktop shortcut title from vars and copies the QtPlasmaC sample profile
only when the target INI is absent, so it does not overwrite the configured
profile on repeated runs. Applied `linuxcnc_controller.yml --limit linuxcnc_utm
--tags qtplasmac,plasma_machine` successfully to the local LinuxCNC VM. Validation
passed: `python3 -m pytest -q tests/test_plasma_machine_import.py
tests/test_linuxcnc_controller_role.py`; `./bin/agent-read yamllint ...`;
post-apply `./bin/agent-read ansible-check --inventory inventory/hosts.yml
--playbook linuxcnc_controller.yml --limit linuxcnc_utm --tags
qtplasmac,plasma_machine` completed with `changed=0`. Captured a durable naming
guardrail in `AGENTS.md`: future LinuxCNC target roles, tags, config names, and
UI labels must remain neutral, with legacy controller names used only as source
metadata.

Follow-up after review: the first transfer was incomplete as a working hardware
profile because it only applied top-level INI values and installed reference
HAL snippets; the active QtPlasmaC HAL remained simulator-only. Updated
`roles/linuxcnc_plasma_machine` so the active machine overlay is applied to
`qtplasmac_metric_ini.inc`, explicitly sets `trivkins coordinates=XYZ`,
`JOINTS=3`, `STEP_SCALE`, pulse timing, and imported axis limits/velocities, and
renders `plasma-machine-parport.tcl` as the actual QtPlasmaC Mode 2 parport HAL
with stepgen, torch output P1.17, Arc OK P2.11, THC up/down P2.12/P2.13, and
float switch P2.15. The UTM host remains explicitly in
`linuxcnc_plasma_machine_hardware_mode: sim`; a real LPT-compatible controller
can switch to `parport` after physical wiring is verified. Validation repeated:
`python3 -m pytest -q tests/test_plasma_machine_import.py
tests/test_linuxcnc_controller_role.py` passed with 10 tests; `./bin/agent-read
yamllint ...` passed; the standard playbook was applied to `linuxcnc_utm`; final
`./bin/agent-read ansible-check --inventory inventory/hosts.yml --playbook
linuxcnc_controller.yml --limit linuxcnc_utm --tags qtplasmac,plasma_machine`
reported `changed=0`.

## 2026-08-31 EP-DPTR_M2.01 Suitability Check

User asked whether the EP-DPTR_M2.01 expansion/commutation board is suitable for
the planned LinuxCNC/QtPlasmaC plasma conversion. Read local tool inventory and
checked current public product pages from CNC Technology/SPB CNC plus LinuxCNC
Mesa Ethernet documentation. Verified facts: EP-DPTR-M 2.01 is advertised as an
isolated commutation board compatible with LinuxCNC/Mach3 depending on board
configuration, intended to carry an EP7i92 mounted above it; published specs list
4 axes / 5 motor outputs X, Y1, Y2, Z, A with PULL/DIR/EN, five home inputs, three
relay outputs, 0-10V spindle output, and split ALM/E-stop inputs. For the user's
QtPlasmaC Mode 2 plasma setup, the critical signals are external Arc OK, THC
move-up, THC move-down, torch-on, probe/float/ohmic, limits/home, and E-stop.
Conclusion: EP-DPTR_M2.01 can be considered only as an EP7i92 breakout stack if a
pinout proves enough spare isolated digital inputs; it is not preferable over a
known Mesa 7I98/7I96S-style path unless the vendor supplies a LinuxCNC/QtPlasmaC
pin map. No files other than this log were changed.

## 2026-08-31 Mesa 7I98 Suitability Check

User asked whether a Mesa 7I98 is suitable for the planned LinuxCNC/QtPlasmaC
plasma conversion. Read the local tool inventory and checked current official
LinuxCNC and Mesa documentation. Relevant verified facts: LinuxCNC `hm2_eth`
supports the 7I98; the 7I98 is a 100BaseT HostMot2 Ethernet FPGA card with
three parallel-port-compatible I/O connectors and 51 total 5V-tolerant I/O bits;
QtPlasmaC Mode 2 needs external `plasmac.arc-ok-in`, external THC
`plasmac.move-up`/`plasmac.move-down`, `plasmac.torch-on`, and a probing input
such as `plasmac.float-switch` or `plasmac.ohmic-probe`, plus the normal machine
home/limit/E-stop wiring. Conclusion: 7I98 can fit the user's LPT-style plasma
retrofit, especially if reusing parallel-port breakout wiring, but a screw
terminal Mesa board such as 7I96S/7I95-style hardware may be simpler if buying
new and rewiring from scratch. No files other than this log were changed.

## 2026-08-27 QtPlasmaC Mode 2 Process And UTM Autostart

User confirmed the intended QtPlasmaC hardware mode is Mode 2: external Arc OK
input plus external THC up/down inputs. Read the official QtPlasmaC development
manual at `https://www.linuxcnc.org/docs/devel/html/ru/plasma/qtplasmac.html`
and inspected `roles/linuxcnc_controller`, `inventory/host_vars/linuxcnc_utm`,
and `tools/plasma-cam/docs`. Found the UTM VM did not autostart QtPlasmaC
because `inventory/host_vars/linuxcnc_utm/vars.yml` explicitly set
`linuxcnc_controller_autostart_qtplasmac: false`; the Openbox autostart template
only launches LinuxCNC when that variable is true. Scope for this task: document
the Mode 2 commissioning process without hardcoding future LPT/Mach3 pins, enable
UTM QtPlasmaC autostart, add regression coverage, validate Ansible role changes,
and verify VM state without bringing the UTM window to the foreground.

Result: added `tools/plasma-cam/docs/linuxcnc-qtplasmac-mode2-process.md`,
changed `inventory/host_vars/linuxcnc_utm/vars.yml` to enable UTM QtPlasmaC
autostart, and added regression coverage in `tests/test_linuxcnc_controller_role.py`.
Validation: `python -m pytest -q tests/test_linuxcnc_controller_role.py` passed
with 4 tests; `./bin/agent-read yamllint linuxcnc_controller.yml inventory/hosts.yml
inventory/host_vars/linuxcnc_utm/vars.yml roles/linuxcnc_controller/defaults/main.yml
roles/linuxcnc_controller/tasks/main.yml` passed; `./bin/agent-read ansible-check
--inventory inventory/hosts.yml --playbook linuxcnc_controller.yml --limit
linuxcnc_utm --tags qtplasmac` passed; the standard `linuxcnc_controller.yml`
playbook was applied to `linuxcnc_utm`. VM evidence: both UTM VMs were initially
`stopped`; the QEMU VM was started, role-applied, then stopped by ACPI request
and started again. SSH later succeeded on `192.168.64.5:22`, and QEMU HMP
`screendump bootcheck2.ppm` showed QtPlasmaC v2.9 running. HMP screenshots must
be written to QEMU's current directory because the QEMU sandbox cannot write to
`/private/tmp`, and paths with spaces need avoiding or quoting.

## 2026-08-25 Feedrate Visibility Check

User asked where feedrate is displayed. Inspected `tools/plasma-cam/web/index.html`,
`tools/plasma-cam/web/app.js`, and `tools/plasma-cam/plasma_cam/post.py`.
Verified feed is currently visible in the Cut tab readout, editable through the
Cut tab manual feed mode, listed in the cut chart table, included in simulation
summary, and emitted into QtPlasmaC G-code as cut-setting comments plus either
`F#<_hal[plasmac.cut-feed-rate]>` or a numeric `F` when material feed is not
used. No code change was made for this task.
# 2026-10-10 Mach3 comparison and first-cut review

User requested a full comparison with the long-working Mach3 installation and
an ordered commissioning plan. LPT is connected; stepper PSU is off. Review
scope is source/live configuration and non-actuating software checks. No motion,
homing, output toggles, ignition, restart or stress test on the physical machine.
Original XML/M3/M5 were read directly and regenerated extraction exactly matches
`tools/linuxcnc/plasma-machine-source.yml`. Active physical INI/HAL/preferences,
signals, realtime parameters, IRQ affinity and idle NML status captured in
`output/linuxcnc/physical/2026-10-10-mach3-review-snapshot.json`; source hashes and
extraction in `output/linuxcnc/physical/2026-10-10-mach3-source-review.json`.
Result: source import on the PC also matches, rendered active physical HAL
matches, and all 39 selected INI fields agree. Focused controller/import/load
tests passed (97 total; the one real IPC bind test was rerun outside sandbox).
Full KerfGrid suite passed: 230 passed / 3 optional DXF corpus gates skipped.
Confirmed by user: same Fubag Plasma 40 and external up/down THC, plasma and
stepper power off; first-coupon thickness remains unspecified.

Actionable commissioning findings: all axes unhomed with immediate HOME=0
and provisional Z 0..50; no physical E-stop/home/limit HAL inputs, hardware
chain unknown; old macro Z8 / explicit 0.602 s dwell differs from current
PH3 / accepted PD0.3 / CH1.5; Mode2 THC speed is 64.2 rather than old 128.4
mm/min (PID-P10 vs THCSpeed20); float 3 mm and probe642 need physical
verification; starter materials are not the old measured chart and default
material0 is generic 45 A. No live settings were changed for this review.
Updated `docs/linuxcnc-qtplasmac-mode2-process.md` with the comparison, exact
pin map, current-state limitations and staged first-start/cut instructions.

RT governor, boot args, CPU1 FIFO98/97 and IRQs on CPU0 remain correct. The
completed September latency acceptance predates Wi-Fi; no concurrent latency
test was started with the active HAL. A temporary Wi-Fi loss was independently
confirmed (no association/ARP failed), then SSH recovered; final read was
IDLE/inpos/queue0, unchanged software position, torch false, axes unhomed.
Supplemental live evidence is in
`output/linuxcnc/physical/2026-10-10-mach3-review-extra.json`; comparison and
test counts in `output/linuxcnc/physical/2026-10-10-mach3-comparison.json`.
Next physical step: verify sensor/safety response with only control powered,
then controlled low-speed direction/scale/reference checks with torch ignition
isolated; use the documented sequence before any first cut.

## 2026-10-14 - Shared workspace and agent DXF upload

Replaced browser-local authority and the one-use pending slot with a durable SQLite shared workspace, revision conflict protection, 1.5-second cross-browser synchronization, stored original DXFs and publishing `POST /api/workspace/import-dxf`. Added `kerfgrid_client.py` for direct uploads and updated the FreeCAD bridge source to use that API. Normal import forces geometry repair/gap closing off; existing positions, quantities and manual settings survive reimport. First browser on an empty server migrates its old local project; each browser keeps its previous local data as a downloadable backup. Reload the computer with the current job first, then the other computers.

Fixed an asynchronous cut-settings preview feedback race: applying remote projects no longer queues a stale automatic save. Acceptance with two isolated browser contexts passed shared edits, stale-write rejection with retained local draft, conflict resolution and API DXF upload appearing in both windows (quantity 1, thickness 4 mm, original download unchanged). Full suite: 251 passed / 3 optional corpus gates skipped; final focused workspace/server/bridge tests: 32 passed; role tests: 15 passed; complete Playwright smoke passed after the race fix. Screenshot: `output/playwright/shared-workspace-2026-10-14.png`.

Scoped nh02 preview passed, then applied `nh02.yml --limit nh02 --tags kerfgrid_app --skip-tags always -e ansible_port=22`: ok8 / changed6 / failed0 / unreachable0. Only KerfGrid application, state directory, service state-path setting and restart were selected. Persistent database: `/var/lib/kerfgrid/workspace.sqlite3`; source updates preserve it. Live reads returned HTTP200 from backend `/api/workspace`, nginx `/api/workspace` and `/kerfgrid/js/workspace.js`. Server was still empty revision0 after read-only checks, ready to migrate the user's current browser project. No production test geometry or LinuxCNC operations were sent. UI: `http://192.168.88.61/kerfgrid/`; API root: `http://192.168.88.61/api/workspace`. Evidence: `output/playwright/shared-workspace-proof-2026-10-14.json`.
