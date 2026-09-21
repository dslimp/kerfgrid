# QtPlasmaC Mode 2 Controller Process

Source checked on 2026-08-27:
`https://www.linuxcnc.org/docs/devel/html/ru/plasma/qtplasmac.html`.

The physical controller is now `192.168.88.73`, with GUI user `dslimp`, an
onboard LPT at `0x378` and QtPlasmaC Mode 2. Source configuration was extracted
from the working Mach3 installation into `tools/linuxcnc/plasma-machine-source.yml`;
physical deployment vars are in `tools/linuxcnc/physical-controller.yml`.
Do not replace source-derived mappings with guessed role defaults.

## Operating Mode

Use QtPlasmaC Mode 2.

- Arc OK comes from the plasma source or relay interface into
  `plasmac.arc-ok-in`.
- Torch height correction comes from the external THC physical controller:
  `plasmac.move-up` and `plasmac.move-down`.
- KerfGrid may still disable THC for small holes and problem geometry through
  QtPlasmaC-compatible G-code, but voltage regulation and up/down decisions stay
  in the external controller.

## Current Hardware Assumption

For the first physical controller setup, assume no Ethernet Mesa board is
available. Treat the machine as a parallel-port/software-stepping target unless
new hardware is introduced.

Install the official LinuxCNC PREEMPT-RT image first because it is the current
straightforward fresh-install path, but accept it only if latency is good enough
for software step generation on the real PC. If base-thread latency is not good
enough, switch to the RTAI path for LPT or add Mesa hardware later instead of
tuning around an unsuitable PREEMPT-RT software-stepping setup.

## Required Signal Contract

Minimum plasma signals for this machine family:

- `plasmac.torch-on`: controller output to torch start relay.
- `plasmac.arc-ok-in`: controller input from Arc OK/transfer.
- `plasmac.float-switch` or `plasmac.ohmic-probe`: probing input.
- `plasmac.move-up`: input from external THC up signal.
- `plasmac.move-down`: input from external THC down signal.

Machine safety signals are separate from QtPlasmaC mode selection. The source
had no valid physical E-stop pin, no enabled home/limit inputs and soft limits
disabled. Those facts do not prove that the physical machine has no safety
circuit; its wiring and behavior must be checked. Source motor-enable outputs
are implemented, but remain electrically unverified while disconnected.

## KerfGrid G-code Contract

KerfGrid output for this controller must keep these properties:

- No CAM-generated Z cutting motion by default.
- Metric `G21`, path tolerance, adaptive feed enable, and QtPlasmaC torch
  control with `M3 $0 S1` and `M5 $0`.
- Material strategy is either temporary material comments or fixed material
  selection with `M190 Pn`, `M66 P3 L3 Q...`, and
  `F#<_hal[plasmac.cut-feed-rate]>`.
- Small holes and small shapes may use reduced feed, THC disable/enable, overcut,
  and early torch-off where the generated path supports it.
- Warnings from import, geometry, safe travel, and offset fallback are operator
  warnings; they must not silently disappear from review, simulation, or G-code
  comments.

## Commissioning Steps

Computer preparation completed on 2026-09-11: realtime load/SSD checks, actual
parport HAL, software XYZ motion, reboot/autostart, native KerfGrid job loading
and the complete torch-off OUTLINE cycle passed. LPT was disconnected throughout.
No physical motion, sensor response or relay operation is claimed by these tests.

1. With equipment powered off, reconnect the controller and inspect the wiring.
   Keep the plasma torch-start circuit physically disconnected for initial tests.
2. Verify the physical E-stop chain and motor enables before commanded motion.
   Check probe, Arc OK and external THC up/down input states and polarity.
3. Jog each axis over short distances at low speed; verify direction, measured
   travel per command, actual usable limits and homing/reference procedure.
   In particular, establish the Z reference and stroke before automatic IHS.
4. Test probing and retract at low speed, still without torch ignition. Verify
   the source-derived floating-head offset against measured switch travel.
5. With the plasma source isolated from ignition, verify the torch relay and
   Arc OK/THC signal response. Restore the normal circuit only after these checks.
6. Run a real torch-off OUTLINE with clear travel before the first cut.
7. Run supervised coupons to calibrate feed, kerf, pierce delay, cut height and
   external THC behavior for the installed Fubag Plasma 40 consumables. The
   current starter cut chart is not a measured calibration.

## Current UTM Autostart

The local UTM VM should autologin to Openbox and start QtPlasmaC from
`/home/linuxcnc/.config/openbox/autostart`. The role starts `dunst` before
QtPlasmaC because QtVCP notification handling needs a notification daemon in this
session.
