#!/usr/bin/env bash
# Run one or all t-digest fuzz targets.
#
#   scripts/run-fuzz.sh                          # all targets, 60s each
#   scripts/run-fuzz.sh fuzz_td_api              # one target, 60s
#   DURATION=3600 JOBS=8 scripts/run-fuzz.sh     # 1h soak, 8 workers per target
#   scripts/run-fuzz.sh fuzz_td_api -runs=100000 # extra libFuzzer flags pass through
#
# Corpora live in t-digest-c/tests/fuzz/corpus (seeds, committed) and
# build/corpus/<target> (grown, not committed). Crashes are copied into
# security/crashes/<target>/ and must be triaged before the tree is pushed.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SEEDS="$ROOT/t-digest-c/tests/fuzz/corpus"
DURATION="${DURATION:-60}"
JOBS="${JOBS:-1}"

BUILD="${BUILD:-}"
if [[ -z "$BUILD" ]]; then
    if [[ -f "$ROOT/build/.last-fuzz-build" ]]; then
        BUILD="$(cat "$ROOT/build/.last-fuzz-build")"
    else
        echo "no fuzz build found -- run scripts/build-fuzz.sh first" >&2
        exit 1
    fi
fi

# A capacity request derived from a fuzzed compression can legitimately be
# enormous. We want the library's allocation-failure path exercised, not an
# allocator abort that masks every other finding.
export ASAN_OPTIONS="${ASAN_OPTIONS:-allocator_may_return_null=1:detect_leaks=1:abort_on_error=0}"
export UBSAN_OPTIONS="${UBSAN_OPTIONS:-print_stacktrace=1:halt_on_error=1}"
# llvm-symbolizer will otherwise try to fetch debuginfo over the network on
# every sanitizer report, stalling each finding for ~20s and looking like a hang.
export DEBUGINFOD_URLS=""

TARGET="${1:-}"
if [[ -n "$TARGET" ]]; then
    shift
    TARGETS=("$TARGET")
else
    TARGETS=(fuzz_td_api fuzz_td_quantile fuzz_td_merge fuzz_td_init)
fi

status=0
for t in "${TARGETS[@]}"; do
    bin="$BUILD/tests/fuzz/$t"
    if [[ ! -x "$bin" ]]; then
        echo "missing target $bin" >&2
        exit 1
    fi

    corpus="$ROOT/build/corpus/$t"
    artifacts="$ROOT/security/crashes/$t"
    mkdir -p "$corpus" "$artifacts"

    echo "=== $t (${DURATION}s, $JOBS job(s)) ==="
    set +e
    "$bin" "$corpus" "$SEEDS" \
        -max_total_time="$DURATION" \
        -jobs="$JOBS" -workers="$JOBS" \
        -print_final_stats=1 \
        -rss_limit_mb=4096 \
        -malloc_limit_mb=2048 \
        -timeout=25 \
        -artifact_prefix="$artifacts/" \
        "$@"
    rc=$?
    set -e
    if [[ $rc -ne 0 ]]; then
        echo "!!! $t exited $rc -- see $artifacts" >&2
        status=$rc
    fi
done

exit $status
