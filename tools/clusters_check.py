#!/usr/bin/env python
"""clusters_check.py — diagnostic du clustering (backlog I59).

Deux modes :

  # Démo synthétique : fragmentation des sources tonales par le critère de forme
  python tools/clusters_check.py --demo

  # Scan d'une base réelle : paires de clusters quasi-doublons + critère séparateur
  python tools/clusters_check.py [data/bruittrack.db]

Le scan décrit les représentants de chaque cluster (empreinte du 1er événement),
identifie les paires |Δfreq_moy| <= 1 Hz et indique quel critère les sépare
(bin, forme spectrale, canal, délai) — à exécuter sur la base du pi-t620 pour
mesurer l'ampleur réelle de la fragmentation avant d'implémenter I59.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from bruittrack.events import ClusterIndex, decode_fingerprint, encode_fingerprint


def demo() -> int:
    """Reproduit la démonstration : source tonale identique, pic décalé d'1 bin."""
    spec = np.zeros(308)
    spec[80:85] = [3.0, 6.0, 12.0, 6.0, 3.0]
    idx = ClusterIndex(max_bin_delta=4)
    cases = [
        ("air,    delai +2ms", {"bin_peak": 82, "dominant_ch": 0, "off_ms": 2}, "(1er cluster, normal)"),
        ("piezo,  delai +2ms (canal !=)", {"bin_peak": 82, "dominant_ch": 1, "off_ms": 2}, "(separation legitime)"),
        ("air,    delai -5ms (delai !=)", {"bin_peak": 82, "dominant_ch": 0, "off_ms": -5}, "(separation legitime)"),
        ("air,    delai +2ms, pic bin 83", {"bin_peak": 83, "dominant_ch": 0, "off_ms": 2}, "(I59 : expectation = match)"),
    ]
    print("Demo fragmentation (spectre identique, tolerance ±4 bins) :")
    for label, kw, verdict in cases:
        cid, new = idx.match_or_create(encode_fingerprint(emergence_spectrum=spec, **kw))
        print(f"  {label:40s} -> cluster {cid} {verdict if new else '(match)'}")
    return 0


def _separation_reason(fp_a: bytes, fp_b: bytes, max_bin_delta: int) -> str:
    """Retourne le (ou les) critère(s) qui séparent deux empreintes."""
    d1, d2 = decode_fingerprint(fp_a), decode_fingerprint(fp_b)
    reasons = []
    if abs(d1.bin_peak - d2.bin_peak) > max_bin_delta:
        reasons.append(f"bin({d1.bin_peak}vs{d2.bin_peak})")
    if d1.dominant_ch != d2.dominant_ch and d1.dominant_ch != 2 and d2.dominant_ch != 2:
        reasons.append(f"canal({d1.dominant_ch}vs{d2.dominant_ch})")
    if abs(d1.delay_class - d2.delay_class) > 2:
        reasons.append(f"delai({d1.delay_class}vs{d2.delay_class})")
    dist = sum(abs(a - b) for a, b in zip(d1.neighbors, d2.neighbors))
    if dist > 2:
        reasons.append(f"forme(dist={dist})")
    return ", ".join(reasons) if reasons else "aucun (match)"


def scan(db_path: str, freq_tol_hz: float = 1.0) -> int:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT cluster, COUNT(*) AS n, ROUND(AVG(freq),2) AS avg_freq,
                  MIN(t0) AS t_first, fp
           FROM events WHERE cluster IS NOT NULL AND fp IS NOT NULL
           GROUP BY cluster ORDER BY n DESC"""
    ).fetchall()
    if len(rows) < 2:
        print(f"{db_path}: {len(rows)} cluster(s) — rien à comparer.")
        return 0
    max_bin_delta = 4  # round(cluster_freq_tolerance_hz / bin_resolution_hz), défauts config
    pairs = 0
    print(f"{len(rows)} clusters — paires |Δavg_freq| <= {freq_tol_hz} Hz :\n")
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            if abs(a["avg_freq"] - b["avg_freq"]) > freq_tol_hz:
                continue
            pairs += 1
            reason = _separation_reason(a["fp"], b["fp"], max_bin_delta)
            print(f"  #{a['cluster']} ({a['n']} evt, {a['avg_freq']} Hz) <-> "
                  f"#{b['cluster']} ({b['n']} evt, {b['avg_freq']} Hz) : séparés par {reason}")
    if pairs == 0:
        print("  aucune — pas de fragmentation visible sur cette base.")
    else:
        print(f"\n{pairs} paire(s) de quasi-doublons potentiels (candidats fusion I59).")
    return 0


def main() -> int:
    argv = sys.argv[1:]
    if argv and argv[0] == "--demo":
        return demo()
    db = argv[0] if argv else "data/bruittrack.db"
    if not Path(db).is_file():
        print(f"base introuvable : {db}", file=sys.stderr)
        return 2
    return scan(db)


if __name__ == "__main__":
    raise SystemExit(main())
