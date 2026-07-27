#!/usr/bin/env bash
# Bucket raw fuzzer artifacts by failure signature.
#
# A soak produces thousands of artifacts for a handful of distinct bugs. This
# replays each one, extracts the signature (sanitizer error + source line, or
# the oracle expression that fired), and prints one bucket per distinct bug with
# the smallest reproducing input in each -- the candidate to minimize and
# promote into tests/fuzz/regressions/.
#
#   scripts/triage-crashes.sh                 # every target
#   scripts/triage-crashes.sh fuzz_td_api     # one target
#   BUILD=build/triage scripts/triage-crashes.sh   # use the UB-recovering build
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD="${BUILD:-}"
if [[ -z "$BUILD" ]]; then
    BUILD="$([[ -f "$ROOT/build/.last-fuzz-build" ]] && cat "$ROOT/build/.last-fuzz-build")"
fi
[[ -x "$BUILD/tests/fuzz/fuzz_td_api" ]] || { echo "no usable build at '$BUILD'" >&2; exit 1; }

export ASAN_OPTIONS="${ASAN_OPTIONS:-allocator_may_return_null=1}"
export UBSAN_OPTIONS="${UBSAN_OPTIONS:-halt_on_error=0:print_stacktrace=0}"
export DEBUGINFOD_URLS=""

TARGETS=("${1:-}")
[[ -z "${TARGETS[0]}" ]] && TARGETS=(fuzz_td_api fuzz_td_quantile fuzz_td_merge fuzz_td_init)

for t in "${TARGETS[@]}"; do
    dir="$ROOT/security/crashes/$t"
    bin="$BUILD/tests/fuzz/$t"
    shopt -s nullglob
    files=("$dir"/*)
    shopt -u nullglob
    if [[ ${#files[@]} -eq 0 ]]; then
        echo "=== $t: no artifacts ==="
        continue
    fi

    echo "=== $t: ${#files[@]} artifacts ==="
    tmp="$(mktemp)"
    for f in "${files[@]}"; do
        sig="$(timeout 20 "$bin" "$f" 2>&1 |
               grep -m1 -E 'runtime error|oracle violated:|AddressSanitizer: [a-z-]+' |
               sed -e 's|.*/src/tdigest.c|tdigest.c|' \
                   -e 's|: signed integer overflow.*|: signed integer overflow|' \
                   -e 's|runtime error: .* is outside the range|runtime error: value outside the range|' \
                   -e 's|^ *||' || true)"
        [[ -z "$sig" ]] && sig="<no signature -- passes on replay>"
        printf '%s\t%s\t%s\n' "$sig" "$(stat -c%s "$f")" "$f" >> "$tmp"
    done

    cut -f1 "$tmp" | sort | uniq -c | sort -rn | while read -r count sig; do
        smallest="$(awk -F'\t' -v s="$sig" '$1==s {print $2"\t"$3}' "$tmp" | sort -n | head -1)"
        printf '  %5d  %s\n' "$count" "$sig"
        printf '         smallest: %s bytes  %s\n' "${smallest%%$'\t'*}" "${smallest##*$'\t'}"
    done
    rm -f "$tmp"
done
