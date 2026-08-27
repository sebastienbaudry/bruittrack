"""Numeric check of getClusterColor() : adjacent ids distinct, no dups in window.

Usage: python tools/color_check.py [--max-id 29] [--min-adjacent 0.13] [--min-window 6]
Exit 0 if every consecutive pair is at least --min-adjacent apart in RGB
(euclidean), and no near-duplicate (<0.05) within |Δid| <= --min-window.
"""

from __future__ import annotations

import argparse
import math
import sys
from colorsys import hls_to_rgb


def cluster_color(cid: int) -> tuple[float, float, float] | None:
    """Python port of getClusterColor() (hsl(id*137.5%360, 85%, L alt par bloc de 6))."""
    if not cid:
        return None  # grey sentinel (#94a3b8), checked separately in tests
    h = ((cid * 137.5) % 360) / 360.0
    lightness = [45, 68][math.floor(cid / 6) % 2] / 100.0
    return hls_to_rgb(h, lightness, 85 / 100)


def euclid(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-id", type=int, default=29)
    ap.add_argument("--min-adjacent", type=float, default=0.13)
    args = ap.parse_args()

    max_id = args.max_id if 1 <= args.max_id <= 304 else 29
    min_adj = max(0.01, min(args.min_adjacent, 1.8))

    worst_d, worst_pair = float("inf"), (None, None)
    dups: list[tuple[int, int]] = []
    cols = {i: cluster_color(i) for i in range(1, max_id + 1)}
    for i in range(1, max_id):
        d = euclid(cols[i], cols[i + 1])
        if d < worst_d:
            worst_d, worst_pair = d, (i, i + 1)
    # near-duplicates inside the |Δid| <= 6 visual window
    for i in range(1, max_id + 1):
        for j in range(i + 1, min(i + 7, max_id + 1)):
            if euclid(cols[i], cols[j]) < 0.05:
                dups.append((i, j))

    print(f"max-id={max_id} min-adjacent-dist={worst_d:.3f} (pair {worst_pair})")
    if worst_d < min_adj:
        print("FAIL: adjacent cluster ids too close", file=sys.stderr)
        return 1
    if dups:
        print(f"FAIL: near-duplicate colors within 6 ids: {dups}", file=sys.stderr)
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
