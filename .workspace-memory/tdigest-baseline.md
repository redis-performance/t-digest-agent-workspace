---
name: tdigest-baseline
description: t-digest-c fork/upstream layout, baseline commit, and what the repo did and did not have before this workspace
metadata:
  type: project
---

`t-digest-c/` is a submodule pointing at the fork **`redis-performance/t-digest-c`**
(`origin`), with **`RedisBloom/t-digest-c`** as `upstream`. The fork was created
2026-07-27; the account has read-only access to the RedisBloom repo, so every change lands
upstream as a PR from the fork.

Baseline: **`50edef3`** — `MOD-13821 Fix compression with total_weight=1 (#39)`.

What the repo had at baseline:
- one minunit correctness suite (`tests/unit/td_test.c`)
- one google-benchmark driver (`tests/benchmark/histogram_benchmark.cpp`) — the immutable
  performance referee
- CircleCI + a release-drafter workflow
- **no fuzzing of any kind**, and no sanitizer job

The whole implementation is 686 lines in `src/tdigest.c`. `td_histogram_t` is declared in the
public header with all fields exposed, which is why the fuzz oracles can assert structural
invariants (`merged_nodes + unmerged_nodes <= cap`) directly rather than inferring them.

Unmerged upstream branches worth knowing about: `fix-td-free-null-check` (addresses the
`td_free(NULL)` SEGV, finding F2) and `fix-cmake-version-requirement`.

See [[fuzzing-environment]] and [[rank-accuracy-calibration]].
