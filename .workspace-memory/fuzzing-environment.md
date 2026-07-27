---
name: fuzzing-environment
description: Environment variables and libFuzzer quirks required to run the t-digest fuzz suite without false hangs or masked findings
metadata:
  type: project
---

Three settings are mandatory when running the t-digest fuzz targets. Each was diagnosed the
hard way on 2026-07-27.

**`export DEBUGINFOD_URLS=""`** — Ubuntu ships `/etc/profile.d/debuginfod.sh` setting this to
`https://debuginfod.ubuntu.com`. `llvm-symbolizer` then tries to fetch debuginfo over the
network for *every* sanitizer report, stalling ~20 s each. Four seed inputs looked like
infinite loops in `td_qsort` for this reason; they were symbolizer network stalls.

**`export ASAN_OPTIONS=allocator_may_return_null=1`** — a fuzzed compression legitimately
requests capacities in the tens of GB (`cap = 6*compression+10` nodes). Without this, ASan
hard-aborts on the allocation, which both hides the library's own allocation-failure path
and terminates the run before any other finding surfaces.

**libFuzzer needs the output corpus directory to already exist.** It exits immediately
otherwise — with a low-key message that reads like a completed clean run. A triage sweep that
"found nothing" in a few seconds is almost always this.

Build knobs that matter:
- `-DFUZZ_RECOVER=ON` for triage sweeps: adds `-fsanitize-recover=all` so one pass enumerates
  every distinct UB site instead of halting at the first. Default halts, so CI fails loudly.
- `-fork=2 -ignore_crashes=1` for soaks, so one known finding does not end a 15-minute run.

`scripts/run-fuzz.sh` sets all of this. Prefer it over invoking the binaries directly.

See [[tdigest-baseline]].
