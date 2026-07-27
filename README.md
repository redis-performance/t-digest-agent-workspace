# t-digest-agent-workspace

Performance- and security-hardening workspace for
[t-digest-c](https://github.com/RedisBloom/t-digest-c) — the C implementation of Ted
Dunning's t-digest used by RedisBloom's `TDIGEST.*` commands.

Two tracks, same method: profiled, evidence-based changes, every one pre-cleared for
upstream merge by an adversarial review. Every experiment is logged; failures are as
valuable as wins.

> **Minimum model: Opus 4.8** for every agent in every phase.
> **Public repo:** no secrets, credentials, tokens, private IPs, customer names, Slack, or
> ticket references anywhere in this tree.

---

## Status

| Track | State |
|-------|-------|
| **Security — fuzzing** | 4 targets live; **9 findings** in round 1 (2 memory-safety, 3 UB) |
| **Security — fixes** | not started (findings triaged, not yet patched) |
| **Performance** | not started |

---

## Security: fuzzing

The repository had **no fuzzing** at the baseline commit (`50edef3`). This workspace adds a
four-target suite under [`t-digest-c/tests/fuzz/`](t-digest-c/tests/fuzz/) — placed inside
the library tree so it is upstreamable as-is.

| Target | What it drives |
|--------|----------------|
| `fuzz_td_api` | the whole API as an opcode program over two histograms |
| `fuzz_td_quantile` | the read path against a sorted reference copy of the samples |
| `fuzz_td_merge` | `td_merge` — digests arriving from elsewhere |
| `fuzz_td_init` | the compression parameter, the value most often taken from user input |

The targets are not crash-only. Each carries a shadow model and asserts the contracts
`tdigest.h` documents: capacity bounds, weight accounting, failure atomicity, centroid
ordering, quantile monotonicity and range, cdf range, and batch-vs-scalar agreement. Value
oracles disable themselves automatically when the input voids the numeric contract (NaN
means, negative weights, weights past 2^53), so adversarial input hunts for crashes without
manufacturing false positives.

### Round 1 findings — 9 issues

Full write-up with repros: **[`security/FINDINGS.md`](security/FINDINGS.md)**.

| # | Severity | Where | What |
|---|----------|-------|------|
| F1 | **High** | `td_centroids_weight_at` | unbounded index → heap OOB read (ASan-confirmed) |
| F2 | **High** | `td_free` | `td_free(NULL)` dereferences NULL (SEGV) |
| F3 | **High** | `_tdigest_long_long_add_safe` | signed overflow *inside the overflow guard*; negative weights accepted |
| F4 | **High** | `td_compress` | `double`→`long long` out-of-range conversion corrupts `merged_weight` |
| F5 | Medium | `cap_from_compression` | float-cast-overflow on NaN / negative / huge compression |
| F6 | Medium | `td_init` | `size_t` capacity truncated into `int cap` → multi-GB alloc, unusable digest |
| F7 | Medium | `td_quantiles` | no range validation; disagrees with `td_quantile` on invalid `q` |
| F8 | Low | `td_quantile` | `q = NaN` returns a value instead of NaN |
| F9 | Medium | `td_cdf` | multiply-before-divide overflows the interpolation → `cdf` returns `inf` |

Three of the four targets fired on the **seed corpus alone**, before any mutation. F9 needed
a soak: it returns `inf` for a wide band of `q`, but the endpoints `q=0` and `q=1` are
correct, so nothing short of a dense sweep over a wide-dynamic-range digest finds it.

All nine reproduce with **no sanitizer at all**, under the gcc `standalone` build — they are
logic bugs the oracles catch, not sanitizer-only artifacts.

### Running it

```bash
scripts/build-fuzz.sh          # clang + libFuzzer + ASan/UBSan
scripts/run-fuzz.sh            # all four targets, 60s each
DURATION=3600 JOBS=8 scripts/run-fuzz.sh fuzz_td_api      # soak one target
ENGINE=standalone CC=gcc scripts/build-fuzz.sh            # no-clang fallback
```

Crashes land in `security/crashes/<target>/`. `scripts/triage-crashes.sh` buckets a soak's
artifacts by failure signature (a 15-minute run produced 1473 artifacts for 5 distinct bugs),
and minimized repros are promoted into `t-digest-c/tests/fuzz/regressions/`, which `ctest`
replays on every build.

> **`ctest -R fuzz` is red at the baseline commit, on purpose** — the corpus and regressions
> reproduce the open findings above. It goes green as they are fixed. Never make it pass by
> deleting inputs or relaxing an oracle.

---

## Performance

Not started. The intended targets, in the order the profile is expected to rank them:

- `td_add` — runs on every sample; the `should_td_compress` check plus the overflow guards
  are on the hot path.
- `td_compress` → `td_qsort` — a hand-rolled quicksort over two parallel arrays, run on
  every capacity overflow and before every read. Central-pivot partitioning degrades badly
  on duplicate-heavy input.
- `td_quantile` / `td_cdf` — linear scans over the centroid arrays.
- `td_quantiles` — already single-pass; the natural comparison point for the batch work
  done in `hdr-agent-workspace`.

The benchmark referee is `tests/benchmark/histogram_benchmark.cpp` (google-benchmark) and is
**immutable** — never edited to make a change look better.

---

## Layout

| Path | Purpose |
|------|---------|
| `t-digest-c/` | submodule → fork `redis-performance/t-digest-c`, `upstream` = `RedisBloom/t-digest-c` |
| `t-digest-c/tests/fuzz/` | the fuzz suite (upstreamable in place) |
| `security/FINDINGS.md` | triaged findings with repros |
| `security/crashes/` | raw fuzzer artifacts, not committed |
| `scripts/` | build / run / seed-generation |
| `experiments/` | performance experiment ledger |
| `.workspace-memory/` | persistent agent memory, backend-agnostic |
| `.claude/` | agent instructions and skills |

## Requirements

- `clang` (libFuzzer + ASan/UBSan) — `gcc` works via `ENGINE=standalone`
- `cmake` ≥ 3.10, `make`, `python3` ≥ 3.10
- `perf` for the performance track

Fully OSS, runs locally, no secrets required.
