"""Numeric check of getBinColor() : adjacent bins distinct, no dups in range.

Usage: python tools/color_check.py [--max-bin 75] [--min-dist 0.2]
Exit 0 if every consecutive pair is at least --min-dist apart in RGB
each pair (Euclidean) and distance-<=1 duplicates are absent.
"""
from __future__ import annotations

import argparse
import math
import sys
from colorsys import hls_to_rgb


def bin_color(bin_i: int) -> tuple[float, float, float]:
    """Python port of getBinColor() (hsl(h*30, 80%, L)) for numeric checks."""
    if not bin_i:
        return None  # grey sentinel, checked separately
    h = ((bin_i - 1) % 12 * 30) / 360.0
    l = [50, 67][math.floor((bin_i - 1) // 12) % 2] / 100.0
    return hls_to_rgb(h, l, 80 / 100)


def euclid(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-bin", type=int, default=75)
    ap.add_argument("--min-dist", type=float, default=0.2)
    args = ap.parse_args()

    max_bin = args.max_bin if 1 <= args.max_bin <= 304 else 75
    min_dist = max(0.01, min(args.min_dist, 1.8))

    worst_d, worst_pair = float("inf"), (None, None)
    dups: list[tuple[int, int]] = []
    for b in range(2, max_bin + 1):
        d = euclid(bin_color(b - 1), bin_color(b))
        if d < worst_d:
            worst_d, worst_pair = d, (b - 1, b)
    # exact duplicates within +/-6 bins of each other (visual proximity risk)
    cols = {b: bin_color(b) for b in range(1, max_bin + 1)}
    for i in range(1, max_bin + 1):
        for j in range(i + 2, min(i + 7, max_bin + 1)):
            if euclid(cols[i], cols[j]) < 0.05:
                dups.append((i, j))

    print(f"max-bin={max_bin} min-adjacent-dist={worst_d:.3f} (pair {worst_pair})")
    if worst_d < min_dist:
        print("FAIL: adjacent bins too close", file=sys.stderr)
        return 1
    if dups:
        print(f"FAIL: near-duplicate colors within 6 bins: {dups}", file=sys.stderr)
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())