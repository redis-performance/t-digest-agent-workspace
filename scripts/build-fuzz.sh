#!/usr/bin/env bash
# Build the t-digest fuzz targets.
#
#   scripts/build-fuzz.sh                    # clang + libFuzzer + ASan/UBSan
#   ENGINE=standalone CC=gcc scripts/build-fuzz.sh
#   SANITIZERS=memory scripts/build-fuzz.sh  # MSan (needs an MSan-instrumented libc++)
#   SANITIZERS= scripts/build-fuzz.sh        # no sanitizer (fast, for long soak runs)
#
# Output: build/fuzz-<engine>-<sanitizers>/tests/fuzz/fuzz_td_*
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/t-digest-c"

ENGINE="${ENGINE:-libfuzzer}"
SANITIZERS="${SANITIZERS-address;undefined}"
CC_BIN="${CC:-clang}"
CXX_BIN="${CXX:-clang++}"

if [[ "$ENGINE" == "libfuzzer" && "$CC_BIN" != *clang* ]]; then
    echo "libFuzzer needs clang; set CC=clang or ENGINE=standalone" >&2
    exit 1
fi

san_tag="${SANITIZERS//;/+}"
[[ -z "$san_tag" ]] && san_tag="nosan"
BUILD="$ROOT/build/fuzz-${ENGINE}-${san_tag}"

cmake -S "$SRC" -B "$BUILD" \
    -DCMAKE_C_COMPILER="$CC_BIN" \
    -DCMAKE_CXX_COMPILER="$CXX_BIN" \
    -DCMAKE_BUILD_TYPE=Debug \
    -DBUILD_FUZZERS=ON \
    -DBUILD_TESTS=OFF \
    -DBUILD_BENCHMARK=OFF \
    -DBUILD_EXAMPLES=OFF \
    -DBUILD_SHARED=OFF \
    -DFUZZ_ENGINE="$ENGINE" \
    -DFUZZ_SANITIZERS="$SANITIZERS" \
    >/dev/null

cmake --build "$BUILD" -j "$(nproc)" >/dev/null

echo "built ($ENGINE, sanitizers=${SANITIZERS:-none}):"
ls -1 "$BUILD"/tests/fuzz/fuzz_td_* | sed 's/^/  /'
echo "$BUILD" > "$ROOT/build/.last-fuzz-build"
