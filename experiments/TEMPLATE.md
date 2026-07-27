# EXP-NNN / SEC-NNN — <one-line title> (YYYY-MM-DD) · **ACCEPT | REJECT | PARK**

**Hypothesis.** One falsifiable sentence, written *before* touching code.

**Change.** What was modified, minimal diff summary. Files touched.

**Correctness.**
- `ctest` — pass/fail
- sanitizers (ASan/UBSan) — pass/fail
- fuzz corpus + regressions replay — pass/fail

**Step 1 — Benchmark.** Same-session base vs patch, both compilers. Table of numbers.
Accept signal: ≥ +2% on the targeted path, no regression > 1% elsewhere, stable over 3 runs.

**Step 2 — Profile.** Did the predicted bottleneck actually shift? Accept signal: target
symbol's CPU % dropped, or IPC up, or branch-miss rate down — and no surprising new
bottleneck.

**Verdict.** ACCEPT (committed as `<sha>` in the submodule) / REJECT (reverted) /
PARK (why, and what unblocks it).

**Notes.** Anything the next agent would otherwise have to rediscover. Negative results,
false starts, environment quirks.
