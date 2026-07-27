# t-digest-c — Fuzzing Findings

Findings from the fuzz suite in [`t-digest-c/tests/fuzz/`](../t-digest-c/tests/fuzz/).
Baseline commit: `50edef3` (`MOD-13821 Fix compression with total_weight=1`, upstream `master`).

Every entry below was reproduced with a minimal standalone program before being written
down — none is inferred from reading the source. Repro steps are exact.

**Round 1** (initial suite bring-up) found **9 issues** — 8 within the first two minutes of
fuzzing, of which **2 are memory-safety bugs** and **3 are undefined behaviour** flagged by
UBSan. F9 came out of the subsequent soak.

Severity is from the perspective of a server (e.g. a Redis module) that exposes t-digest
to untrusted input: the *compression* parameter, the *values and weights* being added, the
*quantiles* being queried, and *digests merged in from elsewhere*.

| # | Severity | Where | What |
|---|----------|-------|------|
| [F1](#f1) | **High** | `td_centroids_weight_at` | Unbounded index → heap OOB read |
| [F2](#f2) | **High** | `td_free` | `td_free(NULL)` dereferences NULL |
| [F3](#f3) | **High** | `_tdigest_long_long_add_safe` | Signed overflow *inside the overflow guard*; negative weights accepted |
| [F4](#f4) | **High** | `td_compress` | `double`→`long long` out-of-range conversion corrupts `merged_weight` |
| [F5](#f5) | **Medium** | `cap_from_compression` | Float-cast-overflow on NaN / negative / huge compression |
| [F6](#f6) | **Medium** | `td_init` | `size_t` capacity truncated into `int cap` → multi-GB alloc, unusable digest |
| [F7](#f7) | **Medium** | `td_quantiles` | No range validation; disagrees with `td_quantile` on invalid `q` |
| [F8](#f8) | **Low** | `td_quantile` | `q = NaN` returns a value instead of NaN |
| [F9](#f9) | **Medium** | `td_cdf` | Multiply-before-divide overflows the interpolation → `cdf` returns `inf` |

---

<a name="f1"></a>
## F1 — heap-buffer-overflow in `td_centroids_weight_at` (High)

`src/tdigest.c:678`

```c
long long td_centroids_weight_at(td_histogram_t *h, int pos) { return h->nodes_weight[pos]; }
```

No bounds check at all. Its sibling `td_centroids_mean_at` *does* check, which sets the
caller's expectation that the accessor validates — so a caller that trusts the pair will
read out of bounds through the weight one.

`td_centroids_mean_at` is itself off by one: `if (pos < 0 || pos > h->merged_nodes)` admits
`pos == merged_nodes`, one past the last valid centroid. It also validates against
`merged_nodes` while unmerged centroids live at `[merged_nodes, merged_nodes+unmerged_nodes)`,
so the two accessors do not even agree on what "valid" means.

**Repro** (ASan):
```c
td_histogram_t *h = td_new(1);              /* cap = 16 */
for (int i = 0; i < 20; i++) td_add(h, i, 1);
td_compress(h);
td_centroids_weight_at(h, h->cap + 1000);   /* reads 8128 bytes past a 128-byte allocation */
```
```
ERROR: AddressSanitizer: heap-buffer-overflow on address 0x50c0000020c0
READ of size 8 at 0x50c0000020c0 thread T0
    #0 in td_centroids_weight_at src/tdigest.c:678:71
```

**Fix:** bound both accessors against `merged_nodes + unmerged_nodes`, return a documented
sentinel (`0` / `NAN`) out of range, and make the `mean_at` comparison `>=`.

---

<a name="f2"></a>
## F2 — `td_free(NULL)` dereferences NULL (High)

`src/tdigest.c:195`

```c
void td_free(td_histogram_t *histogram) {
    if (histogram->nodes_mean) { ... }     /* no NULL check on `histogram` */
```

`td_new()` returns NULL on failure, and `free(NULL)` is well-defined in C, so
`td_free(td_new(c))` on an allocation failure is an entirely natural call shape that
segfaults. Under memory pressure — exactly when an attacker wants a crash — this is the
path that runs.

**Repro** (ASan): `td_free(NULL);`
```
ERROR: AddressSanitizer: SEGV on unknown address 0x000000000040
SUMMARY: AddressSanitizer: SEGV src/tdigest.c:196:9 in td_free
```

Upstream has an unmerged branch `fix-td-free-null-check` that appears to address this; it is
not on `master` at the baseline commit.

**Fix:** early-return on NULL, matching `td_reset`, which already does.

---

<a name="f3"></a>
## F3 — signed overflow inside the overflow guard; negative weights accepted (High)

`src/tdigest.c:23-29`

```c
static inline bool _tdigest_long_long_add_safe(long long a, long long b) {
    if (b < 0) {
        return (a >= __LONG_LONG_MAX__ - b);   /* LLONG_MAX - b overflows for b < 0 */
```

The function whose entire job is to prevent overflow performs the overflowing subtraction
itself. `LLONG_MAX - (-1)` is UB. With `-O2` the compiler is entitled to assume it cannot
happen and fold the guard away.

The guard is also checking the wrong condition for negative `b`: the real risk there is
*underflow*, and the expression as written lets negative weights through. The result is a
digest with negative total weight, which then divides through the quantile interpolation.

**Repro** (UBSan):
```c
td_histogram_t *h = td_new(100);
td_add(h, 1.0, -1);        /* returns 0 -- success */
td_size(h);                /* -1 */
```
```
src/tdigest.c:25:40: runtime error: signed integer overflow:
    9223372036854775807 - -1 cannot be represented in type 'long long'
```

**Fix:** for `b < 0` test `a >= LLONG_MIN - b`, and reject `weight < 1` in `td_add` outright —
a negative-weight centroid has no meaning in a t-digest. (The Go port took the same route:
`RecordValues` rejecting a negative count.)

---

<a name="f4"></a>
## F4 — out-of-range `double`→`long long` conversion in `td_compress` (High)

`src/tdigest.c:661`

```c
const double total_weight = (double)h->merged_weight + (double)h->unmerged_weight;
...
h->merged_weight = total_weight;    /* long long <- double, unchecked */
```

`_check_td_overflow` only rejects `INFINITY`. A total weight of `LLONG_MAX` converts to the
double `2^63`, which is *one greater* than `LLONG_MAX` and therefore not representable —
the conversion is UB, and in practice yields `LLONG_MIN`.

**Repro** (UBSan):
```c
td_histogram_t *h = td_new(100);
td_add(h, 1.0, LLONG_MAX);   /* accepted, rc = 0 */
td_compress(h);              /* rc = 0 */
td_size(h);                  /* -9223372036854775808 */
```
```
src/tdigest.c:661:24: runtime error: 9.22337e+18 is outside the range of
    representable values of type 'long long'
```

Note `td_add` accepted `LLONG_MAX` — `_tdigest_long_long_add_safe(0, LLONG_MAX)` is true —
so a single call reaches the corrupt state. After it, `td_size()` reports a negative count
and every quantile is computed against a negative `merged_weight`.

**Fix:** keep the running total in `long long` (it already is, in `merged_weight` /
`unmerged_weight`) rather than round-tripping through `double`, or bound the conversion
against `LLONG_MAX` explicitly before assigning.

---

<a name="f5"></a>
## F5 — float-cast-overflow in `cap_from_compression` (Medium)

`src/tdigest.c:102-108`

```c
static inline size_t cap_from_compression(double compression) {
    if ((size_t)compression > ((SIZE_MAX / sizeof(double) / 6) - 10)) return 0;
    return (6 * (size_t)(compression)) + 10;
}
```

`(size_t)compression` is UB whenever the value is NaN, negative, or larger than `SIZE_MAX`
— and the guard is written *in terms of that same UB cast*, so it cannot protect against it.

Compression is the one t-digest parameter routinely taken straight from user input
(`TDIGEST.CREATE key COMPRESSION n`), which makes this the most exposed of the UB findings.

**Repro** (UBSan): `td_new(NAN)`, `td_new(-1.0)`, `td_new(1e300)`, `td_new(INFINITY)`
```
src/tdigest.c:103:9: runtime error: nan is outside the range of
    representable values of type 'unsigned long'
```

On x86-64 the cast happens to saturate in a direction that makes every one of these return
NULL, so the *observed* behaviour today is safe. That is a property of the target, not of
the code: on AArch64 and under an optimizer that exploits the UB, the guard can be bypassed.

**Fix:** validate the double *before* casting —
`if (!(compression >= 1.0) || compression > (double)SOME_MAX) return 0;`
(the `!(x >= 1.0)` form rejects NaN too).

---

<a name="f6"></a>
## F6 — capacity truncated from `size_t` into `int` (Medium)

`src/tdigest.c:171` — `histogram->cap = capacity;` assigns a `size_t` to `int cap`.

For compressions above ~`3.6e8` the capacity exceeds `INT_MAX` and wraps negative, while
the two `calloc`s still request the full untruncated size. The result is a histogram that
*successfully allocates tens of gigabytes* and is then permanently unusable, because every
bounds check runs against a negative `cap`.

**Repro:**
```c
td_histogram_t *h = td_new(482262595.7431832);
/* h != NULL, cap = -1401391716, ~23 GB of mapped anonymous memory */
td_add(h, 1.0, 1);   /* 33 (EDOM) -- and always will be */
```

This is a memory-exhaustion vector whenever compression is caller-controlled: the allocation
is accepted, the object looks valid, and nothing reports an error until the first add.

**Fix:** make `cap` a `size_t` (or bound compression so the capacity provably fits an `int`
and reject above that).

---

<a name="f7"></a>
## F7 — `td_quantiles` does not validate `q`, and disagrees with `td_quantile` (Medium)

`src/tdigest.c:448-494`

`td_quantile` rejects out-of-range `q` up front:
```c
if (q < 0.0 || q > 1.0 || h->merged_nodes == 0) return NAN;
```
`td_quantiles` performs that check *only* on the `merged_nodes == 1` path. With two or more
centroids — the normal case — it multiplies straight through:
```c
const double index = quantiles[qpos] * (double)h->merged_weight;
```

**Repro** (50 samples, values 0..49, compression 100):

| `q` | `td_quantile` | `td_quantiles` |
|-----|---------------|----------------|
| `-5.0` | `NaN` | `0` |
| `2.0` | `NaN` | `49` |
| `NaN` | `49` (see F8) | `49` |

Two APIs documented to compute the same thing return different answers for the same input.
A caller that validates by checking for NaN gets no signal at all from the batch API.

The fuzzer also reaches a case where the two disagree on *in-range* `q` once the total
weight is large enough that `q * merged_weight` saturates — pinned as
`regressions/quantile-batch-scalar-mismatch.bin` (13 bytes).

**Fix:** hoist the same range check into the `td_quantiles` loop and write `NAN` for
out-of-range entries.

---

<a name="f8"></a>
## F8 — `td_quantile(h, NaN)` returns a value (Low)

`q < 0.0 || q > 1.0` is false for NaN, so NaN falls through the validation and out the far
side of the interpolation as an ordinary-looking number.

**Repro:** 50 samples 0..49 → `td_quantile(h, NAN)` returns `49`, not `NaN`.

**Fix:** `if (!(q >= 0.0 && q <= 1.0) || h->merged_nodes == 0) return NAN;`

---

<a name="f9"></a>
## F9 — `td_cdf` returns `inf` from an overflowing interpolation (Medium)

`src/tdigest.c:333`

```c
return (base + dwNoSingleton * (val - node_mean) / (node_mean_next - node_mean)) /
       merged_weight_d;
```

C evaluates this left to right: `(dwNoSingleton * (val - node_mean)) / (node_mean_next - node_mean)`.
The product is formed **before** the division that would bring it back into range. When a
centroid holds a large weight and the digest spans a wide dynamic range, that intermediate
overflows `DBL_MAX` and the whole expression collapses to `inf` — `td_cdf` returns a
probability of infinity.

The mathematics is fine; only the ordering is wrong. Computing the ratio first keeps every
intermediate small.

**Repro** — the exact state the fuzzer reached, reconstructed field by field:

```c
td_histogram_t *h = td_new(5);
h->merged_nodes = 5;  h->merged_weight = 16778020;
h->min = -5.4861240738980503e+303;  h->max = 13300;
double    m[5] = {-5.4861240738980503e+303, -255000000000.0, -6.5017667844522977,
                  2241.166666666667, 13300};
long long w[5] = {16712194, 65536, 283, 6, 1};
/* ... copy into h->nodes_mean / h->nodes_weight ... */

td_cdf(h, -5.4312628331590698e+303);   /* inf */
```

The arithmetic, step by step:

```
dwNoSingleton                  = 8388865
val - node_mean                = 5.4861240738980454e+301
node_mean_next - node_mean     = 5.4861240738980503e+303

as written (multiply first):
  8388865 * 5.4861e301         = inf          <-- exceeds DBL_MAX = 1.797e308
  result                       = inf

ratio first (divide first):
  ratio                        = 0.0099999999999999915
  result                       = 0.50303823991150332   <-- correct
```

`inf` is returned for a wide band of query values, not a single point — every `q` from 0.01
through 0.9999 over this digest. The endpoints (`q=0`, `q=1`) return correct values, so a
spot check at the extremes will not catch it.

**Fix:** form the ratio before scaling:
```c
const double ratio = (val - node_mean) / (node_mean_next - node_mean);
return (base + dwNoSingleton * ratio) / merged_weight_d;
```

Pinned as `regressions/api-cdf-interp-overflow.bin`.

The sibling interpolations in `td_internal_iterate_centroids_to_index` already divide before
multiplying, so this is an inconsistency within the file rather than a house style.

---

## Not findings

Checked and cleared, recorded so they are not re-litigated:

- **`td_merge` min/max preservation.** Merging `A=[0,499]` into `B=[1000,1499]` preserves
  `[0,1499]` and the exact total weight. The leftmost/rightmost centroids keep unit weight
  in the cases tested, so the true extremes survive. Not asserted in the fuzzer, because
  t-digest gives no guarantee here in general.
- **`td_qsort` on all-equal input.** The central-pivot partition degrades to one recursion
  level per element, but for `cap`-bounded arrays (≤ 6·compression+10) the depth stayed
  well inside the stack. Worth revisiting for very large compressions.
- **Rank accuracy.** Measured worst-case rank error over adversarial distributions:
  0.134 at compression 100, 0.051 at 300, 0.013 at 1000. Consistent with the ~1/compression
  scaling t-digest promises; the fuzzer's bound is set at ~3× these.

## Reproducing

```bash
scripts/build-fuzz.sh                    # clang + libFuzzer + ASan/UBSan
scripts/run-fuzz.sh                      # all four targets, 60s each
```

Every finding above is pinned in `t-digest-c/tests/fuzz/regressions/` or reachable from the
seed corpus, and `ctest` replays both.
