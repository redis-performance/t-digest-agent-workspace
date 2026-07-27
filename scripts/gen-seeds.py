#!/usr/bin/env python3
"""Generate the seed corpus for the t-digest fuzz targets.

The targets read a byte stream as an opcode program, so a random seed spends
most of its budget on no-ops. These seeds hand-encode the shapes that matter:
a deep uniform digest, a heavy-tailed one, all-equal values, overflow-sized
weights, merge sequences, and the degenerate compressions.

    scripts/gen-seeds.py               # write into tests/fuzz/corpus/
    scripts/gen-seeds.py --out DIR
"""
from __future__ import annotations

import argparse
import pathlib
import struct

# --- fuzz_td_api opcodes (must match fuzz_td_api.c) ---
ADD_TAME = 0
ADD_TAME_W = 1
ADD_RAW = 2
COMPRESS = 3
QUANTILE_PROBE = 4
CDF_PROBE = 5
QUANTILES_BATCH = 6
TRIMMED_MEAN = 7
QUANTILE_SINGLE = 8
CDF_SINGLE = 9
RESET = 10
MERGE_0_1 = 11
MERGE_1_0 = 12
ACCESSORS = 13
BURST = 14
SWITCH = 15

COMPRESSIONS = [1.0, 2.0, 5.0, 10.0, 50.0, 100.0, 300.0, 1000.0]


def f64(x: float) -> bytes:
    return struct.pack(">d", x)


def i64(x: int) -> bytes:
    return struct.pack(">q", x)


def tame(mag: int, sel: int) -> bytes:
    """A td_fuzz_f64_tame operand: magnitude byte + scale/sign selector."""
    return bytes([mag & 0xFF, sel & 0xFF])


def weight(w: int) -> bytes:
    """A td_fuzz_weight_tame operand (little-endian pair, value w-1)."""
    v = max(0, min(0xFFFF, w - 1))
    return bytes([v & 0xFF, (v >> 8) & 0xFF])


def api_seeds() -> dict[str, bytes]:
    seeds: dict[str, bytes] = {}

    # Two mid-size digests, uniform fill, full read sweep.
    body = bytes([5, 5])  # compression 100 for both histograms
    for i in range(200):
        body += bytes([ADD_TAME]) + tame(i % 256, 0)
    body += bytes([COMPRESS, QUANTILE_PROBE, CDF_PROBE, QUANTILES_BATCH, ACCESSORS])
    seeds["api-uniform-200"] = body

    # Deep digest via bursts: forces the implicit compress inside td_add.
    body = bytes([7, 7])  # compression 1000
    body += bytes([BURST, 200]) + tame(1, 0) + tame(1, 1)
    body += bytes([BURST, 200]) + tame(50, 2) + tame(3, 0)
    body += bytes([COMPRESS, QUANTILE_PROBE, CDF_PROBE])
    seeds["api-burst-deep"] = body

    # Smallest possible digest: compression 1 -> cap 16, overflows constantly.
    body = bytes([0, 0])
    body += bytes([BURST, 60]) + tame(3, 0) + tame(1, 0)
    body += bytes([QUANTILE_PROBE, CDF_PROBE, ACCESSORS, COMPRESS, QUANTILE_PROBE])
    seeds["api-tiny-cap"] = body

    # All values identical: min == max, the interpolation degenerate case.
    body = bytes([5, 5])
    for _ in range(120):
        body += bytes([ADD_TAME]) + tame(42, 0)
    body += bytes([COMPRESS, QUANTILE_PROBE, CDF_PROBE, TRIMMED_MEAN]) + f64(0.1) + f64(0.9)
    seeds["api-all-equal"] = body

    # Heavy weights: drives the double/long long accounting boundary.
    body = bytes([5, 5])
    for _ in range(40):
        body += bytes([ADD_TAME_W]) + tame(7, 0) + weight(65535)
    body += bytes([COMPRESS, QUANTILE_PROBE, ACCESSORS])
    seeds["api-heavy-weights"] = body

    # Overflow probes: LLONG_MAX and friends through the raw add path.
    body = bytes([5, 5])
    body += bytes([ADD_RAW]) + f64(1.0) + i64(2**63 - 1)
    body += bytes([COMPRESS, ACCESSORS])
    body += bytes([ADD_RAW]) + f64(2.0) + i64(2**63 - 1)
    body += bytes([COMPRESS, QUANTILE_PROBE])
    seeds["api-weight-overflow"] = body

    # Non-finite means and zero/negative weights: crash-only territory.
    body = bytes([5, 5])
    for v, w in ((float("nan"), 1), (float("inf"), 1), (-float("inf"), 1),
                 (1.0, 0), (1.0, -5), (0.0, 1)):
        body += bytes([ADD_RAW]) + f64(v) + i64(w)
    body += bytes([COMPRESS, QUANTILE_PROBE, CDF_PROBE, ACCESSORS])
    seeds["api-nonfinite"] = body

    # Merge traffic in both directions, with a reset in the middle.
    body = bytes([5, 3])
    body += bytes([BURST, 40]) + tame(10, 0) + tame(1, 0)
    body += bytes([SWITCH])
    body += bytes([BURST, 40]) + tame(200, 1) + tame(1, 4)
    body += bytes([MERGE_0_1, QUANTILE_PROBE, MERGE_1_0, QUANTILE_PROBE])
    body += bytes([RESET, MERGE_0_1, QUANTILE_PROBE, ACCESSORS])
    seeds["api-merge-both-ways"] = body

    # Out-of-range single-point queries.
    body = bytes([5, 5])
    body += bytes([BURST, 20]) + tame(9, 0) + tame(1, 0)
    for q in (-1.0, 0.0, 1.0, 2.0, float("nan"), float("inf")):
        body += bytes([QUANTILE_SINGLE]) + f64(q)
        body += bytes([CDF_SINGLE]) + f64(q)
    seeds["api-oob-queries"] = body

    # Unsorted / out-of-range batch quantiles.
    body = bytes([5, 5])
    body += bytes([BURST, 30]) + tame(11, 0) + tame(2, 0)
    body += bytes([QUANTILES_BATCH, 6]) + b"".join(
        f64(q) for q in (0.9, 0.1, 0.5, -0.2, 1.5, float("nan"))
    )
    seeds["api-unsorted-batch"] = body

    return seeds


def quantile_seeds() -> dict[str, bytes]:
    seeds: dict[str, bytes] = {}
    # mode bit 0 = tame values, bit 1 = weighted
    for name, comp_idx, mode, n, step in (
        ("q-uniform-1000", 7, 1, 1000, 1),
        ("q-tight-cluster", 5, 1, 400, 0),
        ("q-two-modes", 5, 1, 600, 2),
        ("q-small-cap", 0, 1, 300, 1),
    ):
        body = bytes([comp_idx, mode])
        for i in range(n):
            body += tame((i * step) % 256, 0)
        seeds[name] = body

    # Raw doubles, unweighted: NaN / Inf / subnormal soup.
    body = bytes([5, 0])
    for x in (0.0, -0.0, 1e-308, 5e-324, 1e308, -1e308, float("nan"), float("inf"),
              -float("inf"), 1.0, -1.0, 0.5):
        body += f64(x)
    seeds["q-raw-extremes"] = body

    # Weighted raw path.
    body = bytes([6, 2])
    for i in range(200):
        body += f64(float(i)) + weight(i + 1)
    seeds["q-weighted"] = body
    return seeds


def merge_seeds() -> dict[str, bytes]:
    seeds: dict[str, bytes] = {}
    # header: comp_a, comp_b, flags, budget_a, budget_b
    def header(ca: int, cb: int, flags: int, ba: int, bb: int) -> bytes:
        return bytes([ca, cb, flags, ba, bb])

    body = header(5, 5, 0, 20, 20)
    for i in range(400):
        body += tame(i % 256, 0) + weight(1)
    seeds["m-equal-compression"] = body

    body = header(0, 7, 0, 40, 40)
    for i in range(600):
        body += tame((i * 7) % 256, i % 8) + weight((i % 32) + 1)
    seeds["m-mismatched-compression"] = body

    body = header(5, 5, 3, 10, 10)  # raw on both sides
    for x, w in ((1.0, 1), (float("nan"), 1), (1e308, 2), (2.0, 2**62), (3.0, -1)):
        body += f64(x) + i64(w)
    seeds["m-raw-overflow"] = body

    body = header(7, 0, 0, 200, 1)
    for i in range(3000):
        body += tame(i % 256, 0) + weight(1)
    seeds["m-big-into-small"] = body
    return seeds


def init_seeds() -> dict[str, bytes]:
    seeds: dict[str, bytes] = {}
    for i in range(9):
        seeds[f"i-edge-{i}"] = bytes([i])
    body = bytes([0])
    for c in (100.0, 0.0, -1.0, float("nan"), float("inf"), -float("inf"),
              1e-320, 1e18, 2.0**63, 1.0):
        body += f64(c)
    seeds["i-raw-compressions"] = body
    return seeds


def main() -> None:
    here = pathlib.Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=pathlib.Path,
                    default=here / "t-digest-c" / "tests" / "fuzz" / "corpus")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    written = 0
    for prefix, gen in (("api", api_seeds), ("quantile", quantile_seeds),
                        ("merge", merge_seeds), ("init", init_seeds)):
        for name, blob in gen().items():
            (args.out / f"{name}.bin").write_bytes(blob)
            written += 1
    print(f"wrote {written} seeds to {args.out}")


if __name__ == "__main__":
    main()
