# LinuxCNC Plasma Primer Gap List

Source: https://www.linuxcnc.org/docs/stable/html/plasma/plasma-cnc-primer.html

This document tracks implementation gaps for the local plasma CAM/nesting app.
It intentionally separates CAM responsibilities from machine integration work
that belongs in LinuxCNC/QtPlasmaC HAL and INI configuration.

## Already Covered In The App

- QtPlasmaC-oriented output with no CAM-generated Z motion.
- Geometry kerf offset before posting; cutter compensation is blocked by
  validation.
- Temporary QtPlasmaC material comments and material-feed mode using
  `F#<_hal[plasmac.cut-feed-rate]>`.
- Fixed QtPlasmaC material mode with `M190 Pn` and `M66 P3 L3 Q...`.
- `M3 $0 S1` / `M5 $0` torch control validation.
- Starter cut chart keyed by material thickness and nozzle size.
- Cut-chart small-hole/small-shape rules can drive threshold, reduced feed,
  overburn, and early torch-off values, with manual override still available.
- Small-hole/small-shape velocity reduction through `M67/M68`.
- THC lock for small holes and small shapes through `M64/M65 P2`.
- Overburn and early torch-off states for small path features.
- Hole-before-outer contour ordering.
- G-code simulation based on generated G-code.
- Keepout, clamp, damaged, slat, and remnant zones.
- Pierce keepout zones that block pierce crater/point placement without
  blocking ordinary part placement.
- Visual lead point and tab point editing.
- Safe rapid routing around configured zones and completed contour obstacles.
- Nested filler parts inside large internal cutouts are ordered before the
  parent cutout boundary.
- Common-line MVP for repeated straight shared edges, with export blocked when
  active geometry kerf offset would make the result unsafe.

## CAM/Nesting Work Still Needed

1. Production cut-chart library:
   - Store cut height, pierce height, pierce delay, arc voltage target,
     amperage, feed, kerf, THC enable, and notes per material/thickness/nozzle.
   - Mark Fubag Plasma 40 rows as starter values until calibrated by coupons.
   - Add coupon/test-cut generator for feed, kerf, pierce delay, and voltage.

2. QtPlasmaC material integration:
   - Add machine profile presets for material numbers and HAL pin mappings.
   - Persist measured material tables outside code.
   - Validate that generated feed strategy matches selected material strategy.

3. Small holes and small shapes:
   - Block lead-in geometry that cannot physically fit inside a small feature.
   - Add coupon tests that tune reduced feed, THC lock, overburn, and early
     torch-off per material.

4. Lead-in/out editing:
   - Per-contour lead-in type, length, angle, side, start point, overburn, and
     torch-off-before-end settings.
   - Visualize pierce crater clearance before export.
   - Validate pierce and lead paths against holes, neighboring parts, and sheet
     bounds.

5. Robust offset engine:
   - Replace the MVP sampled polygon offset with a true polygon clipping/offset
     engine.
   - Detect self-intersections, collapsed features, and gouging before posting.
   - Preserve arcs where practical instead of always sampling paths.

6. Cut order and heat control:
   - Optimize hole/inner/outer order within and across parts.
   - Add bridge/tab strategy for parts nested inside cutout slugs.
   - Prefer orderings that reduce heat distortion, avoid tipped-up parts, and
     minimize travel.
   - Keep locked/manual order overrides for shop-critical jobs.

7. Nesting quality:
   - Improve exact nesting for mixed curved parts and common-line candidates.
   - Add bridge chains, skeleton cut-up, and remnant inventory workflows.

8. Simulation and safety visibility:
   - Show THC-off sections, reduced-feed sections, pierces, overburn, lead-in,
     lead-out, and torch-off-before-end separately.
   - Estimate pierce count, cut length, rapid length, and consumable wear.
   - Keep export blocked on unresolved import issues, collisions, out-of-sheet
     geometry, invalid offsets, unsupported G-code, and unsafe small-hole rules.

## Machine/QtPlasmaC Work Outside The Nesting App

- ArcOK input, torch-on output, ohmic/float sensing, breakaway sensor, and E-stop
  behavior belong in LinuxCNC HAL wiring and machine commissioning.
- THC delay, voltage sampling, corner lock/anti-dive, void/kerf crossing
  response, and external offsets are QtPlasmaC/LinuxCNC configuration and HAL
  behavior. The CAM app can emit compatible feed/material/THC commands but
  should not replace controller-side THC logic.
- THCAD selection, voltage divider scaling, EMI grounding, water table,
  downdraft, and machine acceleration are build/configuration topics. Keep them
  in a machine commissioning checklist, not in G-code generation.
