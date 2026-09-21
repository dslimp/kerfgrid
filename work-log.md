# KerfGrid Work Log

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
