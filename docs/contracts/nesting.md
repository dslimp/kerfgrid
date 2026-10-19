# Nesting Contract

Auto nest has two phases:

1. Build a valid lower-left seed quickly.
2. Improve it with rotations, exact clearance checks, caches, spatial indexes,
   and parallel attempts until the optimization deadline.

The deadline is a ceiling for optional improvement. A valid seed or better
candidate must always be returned even if the deadline expires. The seed is
compared against successful optimization attempts, rather than used only when
all of them fail.

`nesting.layout_mode` is selected manually and preserved with the project:

- `compact`: form a compact block from the origin by minimizing the squared
  diagonal of its used rectangle (`width² + height²`), then rectangle area.
  Area alone incorrectly rewarded long narrow columns. Both dimensions count,
  so this mode may use more area than a strip while producing a shorter block.
- `strip`: minimize occupied height first, extending along X and preserving
  stock above the layout. Wrap when the sheet width is exhausted. This remains
  the default for existing projects without an explicit mode.

The same objective is used for candidate placement, attempt selection,
compaction and optional hole filling. Both modes respect spacing and zones.
Short attempt budgets interleave placement policies, part orders and rotations,
so the first part order cannot exhaust the whole search budget.
Compact search also tries bounded block seeds. Compaction may align nearby
row/column edges by making a small move on the other axis when the selected
objective improves. Locked placements, clearances and sheet bounds remain valid.
For repeated instances of one profile, early pair seeds compare opposing
explicitly allowed rotations, transverse offsets and row/column counts. Exact
polygon checks validate each pair and its repetitions against spacing, sheet
bounds and blocked zones. Odd quantities keep the final unpaired instance.
Pair search gets at most 15% of the search budget, capped at one second, and
retains its best completed layout when time expires. The same compact/strip
objective selects between pair seeds and ordinary single-part attempts;
pairing is optional and does not change the imported geometry or manual leads.
After exact validation clears part collisions, the selected-part panel must not
report a collision solely because enclosing rectangles overlap. A changed
layout uses provisional bounds checks until its exact validation completes;
late responses from an older geometry state are ignored.
The optimizer searches for a good feasible layout within the limit, without promising a
global optimum.

Automatic leads prefer safe waste pockets inside the occupied part rectangle,
including edge midpoints. They may use external waste when no valid internal
candidate exists. Operator overrides remain unchanged. The lead and crater
are checked against the retained material, neighbors, sheet and zones.

The run report records runtime, attempt counts, engine, utilization, cache and
spatial-index metrics, and whether optimization was time-limited.

Safe travel is selected separately from the packing objective. Its cut-order
optimizer compares real pierce/exit points, routed distances and a reachable
next cut after completion. Manual group ranks remain authoritative. Disabling
part grouping still preserves own internal cuts before the outer contour and
filler parts before their surrounding hole is released. A failed safe route
inserts an explicit M0 before the warned direct rapid; it never silently
claims that transition has an available collision-free route.
