# Agent Notes — t-digest-agent-workspace

Conventions for agent loops hardening and optimizing **t-digest-c**.
Mirrors the M.O. of `hdr-agent-workspace` (immutable benchmark referee, git as the
experiment ledger, adversarial upstream review before any PR).

> **PUBLIC REPO.** No secrets, credentials, tokens, private IPs, internal hostnames,
> customer names, Slack, or ticket references. Describe machines generically (arch only).

> **Minimum model: Opus 4.8 (`claude-opus-4-8`)** for every agent in every phase.

---

## Goals

Two tracks against `t-digest-c/src/tdigest.c`:

1. **Security / robustness** (current focus). The library is reachable from untrusted input
   through RedisBloom's `TDIGEST.*` commands: compression, values, weights, quantiles, and
   merged digests all cross a trust boundary. Fuzz it, triage what falls out, fix it, PR it.
2. **Performance.** `td_add` on the write path; `td_compress`/`td_qsort` on every capacity
   overflow; `td_quantile`/`td_cdf`/`td_quantiles` on the read path.

---

## Validation

**Security changes** must pass, in order:

1. `ctest` green (unit suite + fuzz corpus replay).
2. The fuzz suite clean on the seed corpus **and** on `regressions/` — a fix that silences
   the oracle by weakening it is a regression, not a fix.
3. A fresh soak (≥ 15 min per target) surfacing no new finding in the same area.
4. The finding's entry in `security/FINDINGS.md` updated with the fix and the commit.

**Performance changes** must pass both:

1. **Benchmark** — same-session base vs patch, `tests/benchmark/histogram_benchmark.cpp`.
   ≥ +2% on the targeted path, no regression > 1% elsewhere.
2. **Profile** — confirm the expected bottleneck actually shifted.

Before any upstream PR: the adversarial review must return MERGE-READY.

---

## Workflow Rules

- Edit `t-digest-c/src/*.c` and `src/tdigest.h`. **Never** edit
  `tests/benchmark/histogram_benchmark.cpp` — the immutable referee.
- **Never weaken a fuzz oracle to make a target pass.** If an oracle is wrong, prove it with
  a standalone repro and say so in the commit; if it is right, fix the library.
- **Reproduce before reporting.** Every entry in `security/FINDINGS.md` must have a minimal
  standalone repro that was actually run — never one inferred from reading the source.
- Correctness first: `ctest` before benchmarking, never benchmark broken code.
- New fuzz findings get a **minimized** input in `t-digest-c/tests/fuzz/regressions/`
  (`-minimize_crash=1`), named for the bug, not the hash.
- Log every experiment in `experiments/EXPERIMENTS.md`, failures included.
- Commit accepted changes **in the submodule** (`git -C t-digest-c commit`); revert with
  `git -C t-digest-c checkout -- .`. The submodule tip = best accepted state.
- Bump the submodule pointer + log in the parent repo when a change is accepted.
- Never force-push.

---

## Fuzzing Gotchas

Learned the hard way; do not rediscover them.

- `export DEBUGINFOD_URLS=""`. Otherwise `llvm-symbolizer` fetches debuginfo over the
  network on every sanitizer report — each finding stalls ~20 s and reads as a hang.
- `export ASAN_OPTIONS=allocator_may_return_null=1`. A fuzzed compression legitimately
  requests enormous capacities; without this, ASan aborts on the allocation instead of
  letting the library's failure path run, and it masks every other finding.
- libFuzzer requires the **output corpus directory to already exist** — it exits immediately
  otherwise, which looks like a clean run.
- Build with `-DFUZZ_RECOVER=ON` for triage sweeps (keeps going past UBSan reports, so one
  pass enumerates every site) and the default halting build for CI.
- `-fork=2 -ignore_crashes=1` for soaks, so one known finding does not end the run.

---

## Persistent Memory — `.workspace-memory/`

All memory lives in `.workspace-memory/` so every agent backend shares context.
`MEMORY.md` is the index; one file per entry. Commit memory updates alongside results.
**Sanitize before committing** — public repo.

---

## Submodule & Upstream

- `t-digest-c/` → fork `redis-performance/t-digest-c` (`origin`), upstream
  `RedisBloom/t-digest-c` (`upstream`).
- Portable fixes → PR from the fork to upstream, **only after** the adversarial review
  passes. Track lineage in `.workspace-memory/tdigest-upstream-prs.md`.
- Baseline: `50edef3` (`MOD-13821 Fix compression with total_weight=1`).

---

## Build / Run Requirements

Runs locally; no remote runners.

- `cmake` ≥ 3.10, `make`, `clang` (libFuzzer + sanitizers), `gcc`
- `perf` for the performance track — `sudo apt install linux-tools-generic`
- `python3` ≥ 3.10

For perf counter access: `echo -1 | sudo tee /proc/sys/kernel/perf_event_paranoid`

Prefer a dedicated benchmark box for soaks and long benchmarks; pin to a core (`taskset`)
to cut variance.

## Required Secrets

None — fully OSS, runs locally.
