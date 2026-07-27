# t-digest-agent-workspace — Agent Instructions

You harden and optimize **t-digest-c**, the C implementation of t-digest behind RedisBloom's
`TDIGEST.*` commands. Two tracks: **security/robustness** (current focus) and
**performance**. Every change is validated by evidence and pre-cleared for upstream merge by
an adversarial review.

The fuzz oracles and the google-benchmark driver are the **referee**. The library source is
the mutable target.

> **Minimum model: Opus 4.8 (`claude-opus-4-8`).** Every agent in every phase.
> **This repo is PUBLIC.** Never commit secrets, credentials, tokens, private IPs, customer
> names, internal hostnames, Slack, or ticket references.

---

## Codebase Map

| Path | Purpose |
|------|---------|
| `t-digest-c/src/tdigest.c` | **Primary target** — 686 lines, the entire implementation |
| `t-digest-c/src/tdigest.h` | Public struct + API. `td_histogram_t` fields are public, so fuzz oracles can read them |
| `t-digest-c/tests/unit/td_test.c` | minunit correctness suite — must stay green |
| `t-digest-c/tests/benchmark/histogram_benchmark.cpp` | **Immutable** google-benchmark referee |
| `t-digest-c/tests/fuzz/` | The fuzz suite — 4 targets, seed corpus, regressions |
| `security/FINDINGS.md` | Triaged findings, each with a reproduced repro |
| `.workspace-memory/` | Persistent memory (not `~/.claude/projects/`) |

Hot paths worth knowing before touching anything:

- `td_add` → `should_td_compress` → (`td_compress`) → append to `nodes_mean`/`nodes_weight`
- `td_compress` → `td_qsort` (hand-rolled, central pivot, parallel arrays) → k-scale merge loop
- `td_quantile`/`td_quantiles` → `td_internal_iterate_centroids_to_index` (linear scan)
- `td_cdf` → its own linear scan with singleton-centroid special cases

---

## Security Workflow

1. **Pick a surface.** Anything crossing a trust boundary: compression, values, weights,
   quantile arrays, merged digests.
2. **Fuzz it.** `scripts/build-fuzz.sh && scripts/run-fuzz.sh`. For triage sweeps build with
   `-DFUZZ_RECOVER=ON` so one pass enumerates every UB site instead of stopping at the first.
3. **Reproduce standalone.** Before anything goes in `security/FINDINGS.md`, write a minimal
   C program that triggers it and *run it*. A finding inferred from reading the source is not
   a finding. Record the exact sanitizer output.
4. **Minimize.** `-minimize_crash=1 -exact_artifact_path=t-digest-c/tests/fuzz/regressions/<bug-name>.bin`.
   Name it for the bug, not the hash.
5. **Fix** in `t-digest-c/src/`, minimal diff, one issue per commit.
6. **Verify:** `ctest` green → seed corpus clean → `regressions/` clean → fresh soak
   (≥ 15 min/target) with no new finding in the same area.
7. **Log** — update `security/FINDINGS.md` with the fix and commit hash.
8. **PR** the fix upstream once the adversarial review returns MERGE-READY.

**Never weaken an oracle to make a target pass.** If you believe an oracle is wrong, prove it
with a standalone repro and say so explicitly in the commit message. The rank-accuracy bound
in `fuzz_td_quantile` is calibrated against measured worst-case error — if you change it,
re-run the calibration and record the numbers.

---

## Performance Workflow

0. **Pick a path** — write (`td_add`) or read (`td_quantile`/`td_cdf`) or compress
   (`td_compress`/`td_qsort`).
1. **Profile** first. Never optimize on a hunch.
2. **Hypothesize** — one falsifiable sentence before touching code.
3. **Implement** one technique, minimal diff.
4. **Correctness** — `ctest`, then sanitizers, then the fuzz corpus. Never benchmark broken
   code.
5. **Benchmark** — same-session base vs patch. A cross-session baseline fabricates fake wins;
   the box drifts a few % between sessions.
6. **Profile again** — confirm the bottleneck moved where you predicted.
7. **Accept** → commit in the submodule. **Reject** → `git -C t-digest-c checkout -- .`.
8. **Log** in `experiments/EXPERIMENTS.md`, rejections included.

Accept: ≥ +2% on the targeted path, no regression > 1% elsewhere, stable across 3 runs.
Reject: < 1% (noise), any regression, any correctness failure.
Park: real but < 2%, needs a prerequisite, or architecture-specific.

---

## Fuzzing Environment

These are not optional — each one has already cost a debugging session:

```bash
export DEBUGINFOD_URLS=""                        # else every report stalls ~20s on a network fetch
export ASAN_OPTIONS=allocator_may_return_null=1  # else ASan aborts on huge capacity requests
export UBSAN_OPTIONS=print_stacktrace=1
```

libFuzzer exits immediately if the output corpus directory does not exist — that looks like a
clean run. `scripts/run-fuzz.sh` handles all of this; prefer it over calling the binaries
directly.

---

## Rules

- Edit `t-digest-c/src/*` — never `tests/benchmark/histogram_benchmark.cpp`.
- One experiment = one technique. Log everything, including rejections.
- Commit on accept / `git checkout -- .` on reject, **in the submodule**.
- Bump the submodule pointer in the parent repo when a change is accepted.
- Never force-push.
- Workspace memory lives in `.workspace-memory/` — commit updates alongside results.
- Sanitize everything before committing. Public repo.
