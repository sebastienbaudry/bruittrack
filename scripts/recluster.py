#!/usr/bin/env python3
"""One-shot re-clustering of existing events with the configured tolerance (I44).

Replay all persisted events in live insertion order (id, AUTOINCREMENT) with a
fresh ClusterIndex using the exact parameters of the running service. Rewrites
events.cluster canonically (1..N) and makes exemplar files/flags consistent.

Usage (on target host):  python scripts/recluster.py [BASE_DIR]
Idempotent: re-running yields the same assignment. Take a DB backup first:
    cp data/bruittrack.db data/bruittrack.db.bak  (or rely on WAL + backup here)
"""

from __future__ import annotations

import sqlite3
import sys
import tomllib
from pathlib import Path

from bruittrack.events import FLAG_EXEMPLAR, ClusterIndex


def main(base: str | None = None) -> None:
    base_dir = Path(base) if base else Path("/opt/bruittrack")
    cfg_path = base_dir / "config.toml"
    db_path = base_dir / "data" / "bruittrack.db"
    if not cfg_path.exists():
        sys.exit(f"config manquant: {cfg_path}")
    with open(cfg_path, "rb") as fh:
        cfg = tomllib.load(fh)
    aud, dsp_c = cfg["audio"], cfg["dsp"]

    # Derive the same max_bin_delta as pipeline.py/EventDetector (I44)
    fs_low = int(aud["sample_rate"]) / int(aud.get("decimation", 48))
    tol_hz = float(cfg["detector"].get("cluster_freq_tolerance_hz", 0.5))
    bin_res = fs_low / int(dsp_c.get("n_seg", 2048))
    max_bin_delta = max(0, round(tol_hz / bin_res))

    ex_dir_cfg = cfg["storage"].get("exemplars_dir", "exemplars")
    exdir = Path(ex_dir_cfg)
    if not exdir.is_absolute():
        exdir = base_dir / ex_dir_cfg

    print(
        f"[recluster] tol={tol_hz} Hz  bin_res={bin_res:.6f} Hz"
        f"  -> max_bin_delta={max_bin_delta} bin(s)"
    )

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT id, fp, cluster, flags FROM events ORDER BY id").fetchall()
    n_rows = len(rows)
    old_clusters = {r["cluster"] for r in rows if r["cluster"] is not None}
    n_null = sum(1 for r in rows if r["cluster"] is None)
    print(
        f"[recluster] events={n_rows}  clusters_actuels={len(old_clusters)}"
        f"  sans_cluster={n_null}  exemplaires_disque="
        f"{len(list(exdir.glob('ex_*.raw'))) if exdir.is_dir() else 0}"
    )

    # Old exemplar rows: event holding FLAG_EXEMPLAR whose file exists on disk.
    old_ex_file: dict[int, Path] = {}
    for r in rows:
        if (r["flags"] or 0) & FLAG_EXEMPLAR and r["cluster"] is not None:
            p = exdir / f"ex_{r['cluster']}.raw"
            if p.exists():
                old_ex_file[r["id"]] = p

    # 1) Chronological replay with a fresh index == live sequence semantics.
    idx = ClusterIndex(max_bin_delta=max_bin_delta)
    new_cluster: dict[int, int] = {}
    for r in rows:
        c, _is_new = idx.match_or_create(r["fp"])
        new_cluster[r["id"]] = c
    n_clusters_new = len(set(new_cluster.values()))

    # 2) Per final cluster: exemplar = first (min id) row; audio source is its
    #    old exemplar file if present, else the earliest exemplar file among its
    #    rows. Rebuild flags accordingly.
    first_of: dict[int, int] = {}
    for r in rows:
        c = new_cluster[r["id"]]
        if c not in first_of or r["id"] < first_of[c]:
            first_of[c] = r["id"]

    move_map: dict[Path, Path] = {}
    new_flags: dict[int, int] = {r["id"]: (r["flags"] or 0) & ~FLAG_EXEMPLAR for r in rows}
    used_sources: set[Path] = set()
    for c in sorted(first_of):
        src_row = first_of[c]
        src = old_ex_file.get(src_row)
        if src is None:
            best = min(
                (rr["id"] for rr in rows if new_cluster[rr["id"]] == c and rr["id"] in old_ex_file),
                default=None,
            )
            if best is not None:
                src_row, src = best, old_ex_file[best]
        if src is None or src in used_sources:
            continue
        used_sources.add(src)
        dst = exdir / f"ex_{c}.raw"
        move_map[src] = dst
        new_flags[src_row] |= FLAG_EXEMPLAR

    # 3) Apply DB updates in one transaction.
    cur = con.cursor()
    n_upd_cluster = 0
    for r in rows:
        nc = new_cluster[r["id"]]
        if r["cluster"] != nc:
            cur.execute("UPDATE events SET cluster=? WHERE id=?", (nc, r["id"]))
            n_upd_cluster += 1
    n_upd_flags = 0
    for r in rows:
        nf, oldf = new_flags[r["id"]], (r["flags"] or 0)
        if nf != oldf:
            cur.execute("UPDATE events SET flags=? WHERE id=?", (nf, r["id"]))
            n_upd_flags += 1
    con.commit()

    # 4) Move exemplar files in two phases (avoid name collisions).
    exdir.mkdir(parents=True, exist_ok=True)
    tmp_map: dict[Path, Path] = {}
    for src, dst in move_map.items():
        tmp = src.with_suffix(src.suffix + ".tmp")
        if tmp.exists():
            tmp.unlink()
        src.rename(tmp)
        tmp_map[tmp] = dst
    orphans = [p for p in exdir.glob("ex_*.raw") if p not in move_map.values()]
    for p in orphans:
        print(f"[recluster] orphelin supprime: {p.name}")
        p.unlink()
    for tmp, dst in tmp_map.items():
        if dst.exists():
            dst.unlink()  # same target already claimed (defensive)
        tmp.rename(dst)

    print(
        f"[recluster] OK: clusters {len(old_clusters)} -> {n_clusters_new}"
        f"  (nouvelles regles, tol={tol_hz} Hz)"
    )
    print(f"[recluster] lignes cluster modifiees = {n_upd_cluster}")
    print(f"[recluster] flags modifiees = {n_upd_flags}")
    print(f"[recluster] exemplaires deplaces = {len(move_map)}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
