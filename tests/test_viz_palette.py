"""I77 : separation du palette de clusters (coquille Py du JS getClusterColor)."""

from __future__ import annotations

import colorsys


def _cluster_color(cluster_id: int) -> tuple[float, float, float] | str:
    """Replica strict du JS viz.py : (r,g,b) e [0,1], ou '#94a3b8' si NULL."""
    if not cluster_id:
        return "#94a3b8"
    hue = (cluster_id * 137.5) % 360
    lightness = (45, 68)[int(cluster_id // 6) % 2]
    r, g, b = colorsys.hls_to_rgb(hue / 360.0, lightness / 100.0, 0.85)
    return (r, g, b)


def _rgb_dist(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def test_cluster_color_null():
    assert _cluster_color(0) == "#94a3b8"


def test_cluster_color_determinisme():
    assert _cluster_color(42) == _cluster_color(42)
    assert _cluster_color(42) != _cluster_color(43)


def test_palette_separation_100_ids():
    """|Did|=1 : distance RGB >= 0.13 ; |Dide|<=6 : >= 0.05 (verifie le choix angulaire)."""
    ids = range(1, 101)
    for i in ids:
        c_i = _cluster_color(i)
        assert isinstance(c_i, tuple), f"cluster {i} NULL ?"
        for j in ids:
            if not (j > i):
                continue
            d = _rgb_dist(c_i, _cluster_color(j))
            if abs(i - j) == 1:
                assert d >= 0.13, f"id {i} vs {j} : dist {d:.3f} < 0.13"
            elif abs(i - j) <= 6:
                assert d >= 0.05, f"id {i} vs {j} : dist {d:.3f} < 0.05"
