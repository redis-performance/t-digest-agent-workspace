# Experiment Ledger

One entry per experiment, appended in order. **Rejections are logged too** — a documented
dead end is worth as much as a win, and it stops the next agent from re-running it.

Template: [`TEMPLATE.md`](TEMPLATE.md).

---

## SEC-001 — Bring up a fuzz suite (2026-07-27) · **ACCEPT**

**Hypothesis.** `t-digest-c` has no fuzzing at all. A contract-checking suite over the public
API will find memory-safety and UB issues quickly, because every input path
(compression, values, weights, quantiles, merged digests) crosses a trust boundary in
RedisBloom with no validation layer in front of it.

**What was built.** Four libFuzzer targets in `t-digest-c/tests/fuzz/`, carrying shadow
models rather than being crash-only: `fuzz_td_api` (opcode program over two histograms),
`fuzz_td_quantile` (read path vs a sorted reference), `fuzz_td_merge`, `fuzz_td_init`.
30 hand-encoded seeds, a standalone driver so the corpus replays under gcc without libFuzzer,
CMake wiring behind `-DBUILD_FUZZERS=ON`, and a GitHub Actions workflow.

**Result. 9 findings** — see [`../security/FINDINGS.md`](../security/FINDINGS.md).
2 memory-safety (heap OOB read, NULL deref), 3 UB (signed overflow inside the overflow guard,
`double`→`long long` out of range, float-cast-overflow), 4 logic/contract.
Three of four targets fired on the **seed corpus alone**, before any mutation.

**Cost.** ~2 min of fuzzing for 8 of the 9. F9 needed a 6-minute soak plus signature-bucketed
triage over 1473 artifacts.

**Notes.**
- Two harness false positives were found and fixed before any finding was believed: the
  rank oracle compared against a single rank instead of a rank *interval* (breaks on ties),
  and the accuracy bound was a fixed constant instead of scaling with compression. Both are
  now calibrated against measured error — see
  [`../.workspace-memory/rank-accuracy-calibration.md`](../.workspace-memory/rank-accuracy-calibration.md).
- Four seeds appeared to hang. They were `llvm-symbolizer` stalling on network debuginfod
  fetches, not the library. See
  [`../.workspace-memory/fuzzing-environment.md`](../.workspace-memory/fuzzing-environment.md).
- Crash minimization drifts between bugs when several oracles can fire on one input.
  `scripts/triage-crashes.sh` buckets by signature first; minimize within a bucket.

**Next.** SEC-002: fix F1–F4 (the high-severity set) and open the upstream PRs.

---

## Performance

Nothing run yet. Baseline capture is the first step — `tests/benchmark/histogram_benchmark.cpp`
is the immutable referee.
