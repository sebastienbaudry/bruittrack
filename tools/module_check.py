"""Harness pre-vol BruitTrack -- GOAL.md M1 (criterium check.sh C4).

Mode --offline: 5 checks hors materiel (CLI --help, config exemple,
fingerprint/cluster, store :memory:, viz API + exemplar WAV).
No system network access; usable on dev post / CI before any
hpdebian deploy.

Usage: python tools/module_check.py --offline
Exit 0 if all the checks pass; else 1.
"""

from __future__ import annotations

import argparse
import http.server
import io
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request
import wave

# --- Named thresholds (zero magic number) -------------------------------
EXEMPLAR_FLOAT16_BYTES: int = 512   # 256 frames x 2 ch x float16
SEED_EVENTS: int = 3                # events seeded inside the store
EXEMPT_TIMEOUT_S: float = 5.0       # timeout HTTP of probes


class CheckResult:
    """Registry of checks (name, success, detail)."""

    def __init__(self) -> None:
        self.rows: list[tuple[str, bool, str]] = []

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        mark = "OK  " if ok else "FAIL"
        suffix = f" -- {detail}" if detail else ""
        print(f"[{mark}] {name}{suffix}")
        self.rows.append((name, ok, detail))

    @property
    def passed(self) -> bool:
        return all(ok for _, ok, _ in self.rows)


def check_cli(res: CheckResult) -> None:
    """L1: installed CLI, all subcommands visible."""
    out = subprocess.run([sys.executable, "-m", "bruittrack", "--help"],
                         capture_output=True, text=True, timeout=10, check=False)
    text = out.stdout + out.stderr
    cmd_ok = all(c in text for c in ("devices", "test", "start", "viz",
                                     "stats", "perf"))
    res.add("cli --help", out.returncode == 0 and cmd_ok,
            f"rc={out.returncode} cmds={cmd_ok}")


def check_config(res: CheckResult) -> None:
    """L2: config.toml.example loadable + validate() (tmpdir)."""

    from bruittrack.config import load_config

    ok, detail = True, ""
    try:
        src = pathlib.Path(__file__).resolve().parent.parent / \
            "config.toml.example"
        with tempfile.TemporaryDirectory(prefix="bt_offline_") as tmp:
            dest = pathlib.Path(tmp) / "config.toml"
            shutil.copy(src, dest)
            cfg = load_config(dest)
            if hasattr(cfg, "validate"):
                cfg.validate()
            detail = f"sample_rate={cfg.audio.sample_rate}"
    except Exception as e:  # noqa: BLE001
        ok, detail = False, str(e)
    res.add("config example load+validate", ok, detail)


def check_fingerprint_cluster(res: CheckResult) -> None:
    """offline L6: fingerprint encode/decode + ClusterIndex."""

    import numpy as np

    from bruittrack.events import (
        ClusterIndex,
        decode_fingerprint,
        encode_fingerprint,
        fingerprints_match,
    )

    ok, detail = True, ""
    try:
        spec = np.zeros(99, dtype="float64")
        spec[40] = 12.0
        spec[38:43] += (1.0, 4.0, 20.0, 5.0, 2.0)
        fp1 = encode_fingerprint(40, spec, dominant_ch=0, off_ms=1.0)
        spec2 = spec.copy()
        spec2[39] += 0.5
        fp2 = encode_fingerprint(40, spec2, dominant_ch=0, off_ms=-1.0)
        spec_diff = np.zeros(99, dtype="float64")
        spec_diff[80] = 35.0
        fp_diff = encode_fingerprint(80, spec_diff, dominant_ch=1, off_ms=15.0)
        d1 = decode_fingerprint(fp1)
        idx = ClusterIndex()
        c1, new1 = idx.match_or_create(fp1)
        c2, new2 = idx.match_or_create(fp2)
        c3, _ = idx.match_or_create(fp_diff)
        ok = (
            len(fp1) == 16
            and fingerprints_match(fp1, fp2)
            and not fingerprints_match(fp1, fp_diff)
            and new1 is True
            and new2 is False
            and c1 == c2
            and c3 != c1
            and d1.bin_peak == 40
        )
        detail = f"len={len(fp1)} clusters=({c1}, {c2}, {c3})"
    except Exception as e:  # noqa: BLE001
        ok, detail = False, str(e)
    res.add("fingerprint + ClusterIndex", ok, detail)


def check_store(res: CheckResult) -> None:
    """L6: EventStore :memory:, add + flush + coherent stats."""

    from bruittrack.events import SoundEvent
    from bruittrack.store import EventStore

    ok, detail = True, "total=-1"
    try:
        store = EventStore(db_path=":memory:", batch_size=5)
        now = 1_750_000_000.0
        for i in range(SEED_EVENTS):
            store.add_event(SoundEvent(
                t0=now + i * 3.0, dur=1.2 + i * 0.1, bin_i=12 + i,
                freq=(12 + i) * 0.48828, lvl_g=9.5 + i * 0.7, lvl_d=6.5,
                off_ms=1.0, fp=b"\x0a" * 16))
        n = store.flush()
        stats = store.get_stats()
        total = int(stats.get("total_events", -1))
        ok = (n == SEED_EVENTS) and (total >= SEED_EVENTS)
        detail = f"flush={n} total={total}"
        store.close()
    except Exception as e:  # noqa: BLE001
        ok, detail = False, str(e)
    res.add("store :memory: add/flush/stats", ok, detail)


def _seeded_store_for_viz(db_path: str, exemplars_dir: str):
    """Seed a temporary store + cluster 0 exemplar for the viz test."""

    import numpy as np

    from bruittrack.events import SoundEvent
    from bruittrack.store import EventStore

    store = EventStore(db_path=db_path, batch_size=5)
    base = 1_750_000_000.0
    for i in range(SEED_EVENTS):
        store.add_event(SoundEvent(
            t0=base + i * 2.0, dur=1.5, bin_i=10 + i,
            freq=(10 + i) * 0.48828, lvl_g=12.0 + i, lvl_d=8.0, off_ms=1.1,
            fp=b"\x11" * 16))
    store.flush()
    ex_dir = pathlib.Path(exemplars_dir)
    ex_dir.mkdir(parents=True, exist_ok=True)
    (ex_dir / "ex_0.raw").write_bytes(
        np.random.default_rng(7).normal(0.0, 0.1,
                                         size=EXEMPLAR_FLOAT16_BYTES // 2).astype("float16").tobytes())
    return store


def check_viz_api(res: CheckResult) -> None:
    """L7: viz API -- stats, events (off_ms), exemplar WAV."""

    from bruittrack.config import Config, StorageConfig
    from bruittrack.viz import BruitTrackHandler

    ok, detail = True, ""
    tmpdir = tempfile.TemporaryDirectory(prefix="bt_viz_")
    server: http.server.ThreadingHTTPServer | None = None
    try:
        p = pathlib.Path(tmpdir.name)
        store = _seeded_store_for_viz(str(p / "viz.db"),
                                      str(p / "exemplars"))
        config = Config(storage=StorageConfig(db_path=str(p / "viz.db"),
                                              exemplars_dir=str(p /
                                                               "exemplars")))
        handler = type("_H", (BruitTrackHandler,), {"store": store,
                                                     "config": config})
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()

        base_url = f"http://127.0.0.1:{port}"
        with urllib.request.urlopen(base_url + "/api/stats",
                                    timeout=EXEMPT_TIMEOUT_S) as r:
            payload = json.loads(r.read().decode("utf-8"))
            stats_ok = int(payload.get("total_events", -1)) >= SEED_EVENTS

        ev_query = f"/api/events?limit={SEED_EVENTS}"
        with urllib.request.urlopen(base_url + ev_query,
                                    timeout=EXEMPT_TIMEOUT_S) as r:
            ev_payload = json.loads(r.read().decode("utf-8"))
        # /api/events renvoie une liste nue (ou {"events": [...]}) selon version.
        if isinstance(ev_payload, dict):
            ev_list = ev_payload.get("events", [])
        else:
            ev_list = ev_payload
        ev_ok = (
            isinstance(ev_list, list)
            and len(ev_list) >= SEED_EVENTS
            and all(isinstance(e, dict) and "off_ms" in e for e in ev_list)
        )

        req_url = base_url + "/api/exemplar/0"
        with (
            urllib.request.urlopen(req_url, timeout=EXEMPT_TIMEOUT_S) as r,
            wave.open(io.BytesIO(r.read())) as w,
        ):
            w_ok = (w.getnchannels() == 2 and w.getframerate() == 1000)

        ok = stats_ok and ev_ok and w_ok
        detail = f"stats={stats_ok} events={ev_ok} wav={w_ok}"
    except Exception as e:  # noqa: BLE001
        ok, detail = False, str(e)
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        tmpdir.cleanup()
    res.add("viz API (stats/events/exemplar)", ok, detail)


def run_offline(res: CheckResult) -> bool:
    check_cli(res)
    check_config(res)
    check_fingerprint_cluster(res)
    check_store(res)
    check_viz_api(res)
    return res.passed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Harness verification modules BruitTrack.")
    parser.add_argument("--offline", action="store_true",
                        help="matrice hors materiel (poste dev / CI)")
    args = parser.parse_args()

    res = CheckResult()
    if not args.offline:
        print("Usage : module_check.py --offline", file=sys.stderr)
        return 2

    ok = run_offline(res)
    n_ok = sum(1 for _, o, _ in res.rows if o)
    print(f"RESULTAT : {n_ok}/{len(res.rows)} checks OK")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
