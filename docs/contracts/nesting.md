# Nesting Contract

Auto nest has two phases:

1. Build a valid lower-left seed quickly.
2. Improve it with rotations, exact clearance checks, caches, spatial indexes,
   and parallel attempts until the optimization deadline.

The deadline is a ceiling for optional improvement. A valid seed or better
candidate must always be returned even if the deadline expires. Candidate
ranking prioritizes validity, lower used height, lower used width, compactness,
and utilization. Remaining stock should form one useful region above the packed
parts where possible.

The run report records runtime, attempt counts, engine, utilization, cache and
spatial-index metrics, and whether optimization was time-limited.
