---
name: rank-accuracy-calibration
description: Measured worst-case t-digest rank error per compression, and the fuzz-oracle bound derived from it
metadata:
  type: project
---

The rank-accuracy oracle in `fuzz_td_quantile` needs a bound that catches gross breakage
without firing on t-digest's ordinary approximation error. A fixed bound cannot do both:
t-digest's rank error scales as ~1/compression, so anything tight enough for compression
1000 is a false-positive factory at compression 1.

Measured on 2026-07-27 (baseline `50edef3`), worst rank error over 20 trials × 6 adversarial
distributions (sorted ascending, sorted descending, uniform-with-ties, heavy-tailed
`exp(U(0,20))`, bimodal at 1e9/1e-9, and 3-distinct-values), 200–5200 unit-weight samples:

| compression | worst observed | oracle bound |
|------------:|---------------:|-------------:|
| 50 | 0.250 | *check skipped* |
| 100 | 0.134 | 0.40 |
| 300 | 0.051 | 0.13 |
| 1000 | 0.013 | 0.06 |

Bound is `max(0.06, 40/compression)`, roughly 3× the measured worst case, and the check is
skipped entirely below compression 100 where the digest holds too few centroids for any
useful bound. The bimodal and 3-distinct-values distributions dominate the worst case — ties
and extreme dynamic range, not tail heaviness.

The oracle compares against the **rank interval** `[#(<v), #(<=v)]/n`, not a single rank.
That matters: with 400 identical samples, 0.0 is a correct answer for every `q`, and a
single-rank formulation reports every answer as wrong. The first version of this oracle did
exactly that and produced a false positive on the `q-tight-cluster` seed.

If you change the bound, re-run the calibration and update this table.

See [[fuzzing-environment]].
