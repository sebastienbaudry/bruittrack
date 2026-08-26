"""Tests for SQLite EventStore."""

import tempfile
import time
from pathlib import Path

import pytest

from bruittrack.events import FLAG_OVER_LEGAL, SoundEvent
from bruittrack.store import EventStore


def test_store_crud_and_batching() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        store = EventStore(db_path=db_path, batch_size=3, batch_timeout_s=100.0)

        ev1 = SoundEvent(
            t0=1700000000.0,
            dur=1.5,
            bin_i=20,
            freq=9.76,
            lvl_g=15.2,
            lvl_d=12.1,
            off_ms=0.0,
            fp=b"1" * 16,
            flags=0,
            cluster=1,
        )
        ev2 = SoundEvent(
            t0=1700000010.0,
            dur=2.0,
            bin_i=20,
            freq=9.76,
            lvl_g=14.0,
            lvl_d=11.5,
            off_ms=0.0,
            fp=b"1" * 16,
            flags=0,
            cluster=1,
        )

        store.add_event(ev1)
        store.add_event(ev2)

        # Buffer has 2 items (batch_size is 3), so not yet in DB unless flushed
        assert len(store._buffer) == 2

        # Adding 3rd event should trigger auto-flush
        ev3 = SoundEvent(
            t0=1700000020.0,
            dur=0.8,
            bin_i=40,
            freq=19.53,
            lvl_g=18.0,
            lvl_d=20.0,
            off_ms=-2.0,
            fp=b"2" * 16,
            flags=0,
            cluster=2,
        )
        store.add_event(ev3)
        assert len(store._buffer) == 0

        # Query events
        events = store.get_events(limit=10)
        assert len(events) == 3

        # Stats
        stats = store.get_stats()
        assert stats["total_events"] == 3
        assert stats["total_clusters"] == 2

        # Clusters summary
        clusters = store.get_clusters_summary()
        assert len(clusters) == 2
        # Cluster 1 should have 2 events
        c1 = next(c for c in clusters if c["cluster_id"] == 1)
        assert c1["event_count"] == 2

        # Triage update
        store.set_cluster_triage(cluster_id=1, flags=2, label="VMC Cuisine")
        clusters_updated = store.get_clusters_summary()
        c1_up = next(c for c in clusters_updated if c["cluster_id"] == 1)
        assert c1_up["flags"] == 2
        assert c1_up["label"] == "VMC Cuisine"

        # Retention pruning
        # ev1 and ev2 are from past timestamp
        deleted = store.apply_retention(retention_days=1)
        assert deleted == 3

        events_after = store.get_events()
        assert len(events_after) == 0

        store.close()


def test_concurrent_writer_and_readers(tmp_path: Path) -> None:
    """One writer + two readers must not corrupt the DB or deadlock (BUG-08)."""
    n_events = 120
    n_batch = 7
    store = EventStore(db_path=str(tmp_path / "cc.db"), batch_size=n_batch)
    errors: list[BaseException] = []
    results: list[int] = []
    import threading as _t

    def writer() -> None:
        try:
            t0 = time.time()
            for i in range(n_events):
                store.add_event(
                    SoundEvent(
                        t0=t0 + i,
                        dur=1.0,
                        bin_i=i % 20,
                        freq=float(i),
                        lvl_g=5.0,
                        lvl_d=4.0,
                        off_ms=0.0,
                        fp=b"\x01" * 16,
                    )
                )
            store.flush()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    def reader(tag: int) -> None:
        try:
            for _ in range(150):
                results.append(store.get_stats()["total_events"])
                store.get_events(limit=10)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [
        _t.Thread(target=writer),
        _t.Thread(target=reader, args=(1,)),
        _t.Thread(target=reader, args=(2,)),
    ]
    for t in threads:
        t.start()
    deadline = time.time() + 30
    for t in threads:
        t.join(timeout=max(0.1, deadline - time.time()))
        if t.is_alive():
            pytest.fail(f"thread {t.name} deadlocked")

    assert not errors, f"exceptions during concurrent access: {errors}"
    assert store.get_stats()["total_events"] == n_events
    assert results == sorted(results)  # counters monotonic


def test_get_stats_events_last_24h(tmp_path: Path) -> None:
    """get_stats() expose events_last_24h; 1 for recent event, none for stale."""
    store = EventStore(db_path=tmp_path / "stats.db", batch_size=3)
    now = time.time()
    ev = SoundEvent(
        t0=now - 60.0,
        dur=1.0,
        bin_i=10,
        freq=4.9,
        lvl_g=8.0,
        lvl_d=7.0,
        off_ms=0.5,
        fp=b"f" * 16,
        flags=0,
        cluster=2,
    )
    store.add_event(ev)
    stale = SoundEvent(
        t0=now - 3 * 86_400.0,
        dur=1.0,
        bin_i=12,
        freq=5.9,
        lvl_g=8.0,
        lvl_d=1.5,
        off_ms=-0.4,
        fp=b"s" * 16,
        flags=0,
        cluster=3,
    )
    store.add_event(stale)
    stats = store.get_stats()
    assert "events_last_24h" in stats
    assert stats["events_last_24h"] == 1  # recent only; stale (>24h) excluded
    assert stats["total_events"] == 2


def test_prune_orphaned_exemplars(tmp_path: Path) -> None:
    """prune_orphaned_exemplars deletes only ex_<cluster>.raw absent from DB."""
    ex_dir = tmp_path / "exemplars"
    ex_dir.mkdir()
    (ex_dir / "ex_7.raw").write_bytes(b"x" * 8)
    (ex_dir / "ex_2.raw").write_bytes(b"y" * 8)
    (ex_dir / "nope.raw").write_text("x")
    store = EventStore(db_path=tmp_path / "e.db", batch_size=3)

    # Empty DB: both ex_*.raw are orphans; non-conforming name untouched.
    removed = store.prune_orphaned_exemplars(ex_dir)
    assert removed == 2
    assert (ex_dir / "nope.raw").is_file()

    # Once cluster 2 exists in DB, its exemplar survives; unknown ones die.
    ev = SoundEvent(
        t0=time.time(),
        dur=1.0,
        bin_i=5,
        freq=2.5,
        lvl_g=8.0,
        lvl_d=7.0,
        off_ms=0.0,
        fp=b"k" * 16,
        flags=0,
        cluster=2,
    )
    store.add_event(ev)
    store.flush()
    (ex_dir / "ex_2.raw").write_bytes(b"y" * 8)  # known exemplar restored
    (ex_dir / "ex_5.raw").write_bytes(b"z" * 8)  # cluster 5 unknown -> orphan

    removed = store.prune_orphaned_exemplars(ex_dir)
    assert removed == 1  # only ex_5.raw removed
    assert (ex_dir / "ex_2.raw").is_file()
    assert not (ex_dir / "ex_5.raw").exists()


def test_cluster_fingerprints_cap_and_speed(tmp_path: Path) -> None:
    """Cap 100k groups + rebuild of 200k synthetic events stays < 8 s."""
    import time as _time

    from bruittrack.store import cursor

    db_path = tmp_path / "cap.db"
    store = EventStore(db_path=db_path, batch_size=10)

    n = 200_000
    t_start = _time.perf_counter()
    with cursor(db_path) as conn:
        conn.executemany(
            "INSERT INTO events (t0, dur, bin_i, freq, lvl_g, lvl_d, off_ms, fp, flags, cluster) VALUES (?,?,?,?,?,?,?, ?, 0, ?)",
            [
                (
                    1.7e9 + i * 0.36,
                    1.0,
                    i % 99,
                    4.0,
                    5.0,
                    4.0,
                    0.0,
                    bytes([(i >> j) & 1 for j in range(8, -1, -1)]),
                    i % 20_000,
                )
                for i in range(n)
            ],
        )
        conn.commit()
    fps = store.load_all_cluster_fingerprints()
    from bruittrack.events import ClusterIndex

    idx = ClusterIndex()
    for cid, fp in fps.items():
        idx.add_existing(cid, fp)
    assert len(idx.clusters) == 20_000
    elapsed = _time.perf_counter() - t_start
    assert elapsed < 8.0


def test_set_cluster_triage_creates_fresh_row(tmp_path):
    """set_cluster_triage on a non-existent cluster id must create the row."""
    store = EventStore(db_path=tmp_path / "triage.db", batch_size=3)
    try:
        import time

        ok = store.set_cluster_triage(99, flags=1, label="compreur nocturne")
        assert ok is True
        with store._db() as conn:
            row = conn.execute(
                "SELECT flags, label, created_at FROM clusters WHERE id = 99"
            ).fetchone()
        assert row is not None
        assert row[0] == 1
        assert row[1] == "compreur nocturne"
        assert time.time() - 3600 < float(row[2]) <= time.time() + 1
        # without label: existing row updated, not duplicated
        ok = store.set_cluster_triage(99, flags=3)
        assert ok is True
        with store._db() as conn:
            rows = conn.execute("SELECT flags, label FROM clusters WHERE id = 99").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == 3
        assert rows[0][1] == "compreur nocturne"
    finally:
        store.close()


def test_clusters_summary_includes_triage_orphans(tmp_path):
    """A triaged cluster with no event yet must remain visible in the summary."""
    store = EventStore(db_path=tmp_path / "orphans.db", batch_size=3)
    try:
        store.set_cluster_triage(cluster_id=42, flags=1, label="a venir")
        summary = store.get_clusters_summary()
        assert any(c["cluster_id"] == 42 for c in summary), summary
        orphan = next(c for c in summary if c["cluster_id"] == 42)
        assert orphan["event_count"] == 0
        assert orphan["flags"] == 1
        assert orphan["label"] == "a venir"
    finally:
        store.close()


def test_get_events_filters_and_pagination() -> None:
    """I21 : filtres since/cluster + pagination limit/offset (tri t0 DESC) de get_events()."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "filters.db"
        store = EventStore(db_path=db_path, batch_size=10, batch_timeout_s=10.0)

        for i, cluster in enumerate([5, 5, 9]):
            store.add_event(
                SoundEvent(
                    t0=1700000000.0 + i * 10,
                    dur=1.0,
                    bin_i=30,
                    freq=14.65,
                    lvl_g=10.0,
                    lvl_d=9.0,
                    off_ms=0.0,
                    fp=b"\x02" * 16,
                    cluster=cluster,
                )
            )
        store.flush()

        # Tri t0 DESC : event le plus récent d'abord
        first = store.get_events(limit=1)[0]
        assert first["t0"] == pytest.approx(1700000020.0)

        # since= mi-fenêtre → 2 events les plus récents conservés
        since = 1700000009.5
        got = store.get_events(limit=10, since=since)
        assert [round(e["t0"]) for e in got] == [1700000020, 1700000010]

        # Filtre cluster
        c5 = store.get_events(limit=10, cluster=5)
        assert len(c5) == 2 and all(e["cluster"] == 5 for e in c5)

        # Pagination : page de 2 → le plus ancien reste à l'offset 2
        page2 = store.get_events(limit=1, offset=2)[0]
        assert page2["t0"] == pytest.approx(1700000000.0)
        store.close()


def test_get_events_exposes_over_legal_flag() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        store = EventStore(db_path=Path(tmpdir) / "test.db", batch_size=1, batch_timeout_s=1.0)
        for t0, fl in ((1700000020.0, FLAG_OVER_LEGAL), (1700000030.0, 0)):
            store.add_event(
                SoundEvent(
                    t0=t0,
                    dur=1.0,
                    bin_i=5,
                    freq=2.44,
                    lvl_g=5.0,
                    lvl_d=3.0,
                    off_ms=0.0,
                    fp=b"2" * 16,
                    flags=fl,
                    cluster=None,
                )
            )
        store.flush()
        rows = {int(r["flags"]): r for r in store.get_events(limit=10)}
        assert rows[FLAG_OVER_LEGAL]["over_legal"] is True
        assert rows[0]["over_legal"] is False


def test_apply_retention_prunes_exemplars(tmp_path: Path) -> None:
    """I52: apply_retention(exemplars_dir=...) prunes exemplars orphaned by the purge."""
    ex_dir = tmp_path / "ex"
    ex_dir.mkdir()
    store = EventStore(db_path=tmp_path / "r.db", batch_size=3)
    now = time.time()

    def ev(t0: float, cluster: int) -> SoundEvent:
        return SoundEvent(
            t0=t0, dur=1.0, bin_i=5, freq=2.5, lvl_g=8.0, lvl_d=7.0,
            off_ms=0.0, fp=b"a" * 16, flags=0, cluster=cluster,
        )

    store.add_event(ev(now - 90 * 86400, 7))   # will be purged (30 d)
    store.add_event(ev(now - 3600.0, 8))       # kept
    store.flush()
    (ex_dir / "ex_7.raw").write_bytes(b"old")
    (ex_dir / "ex_8.raw").write_bytes(b"new")

    deleted = store.apply_retention(retention_days=30, exemplars_dir=ex_dir)

    assert deleted == 1
    assert not (ex_dir / "ex_7.raw").exists()   # orphaned by purge -> removed
    assert (ex_dir / "ex_8.raw").is_file()      # still referenced -> kept

    # Legacy: sans exemplars_dir aucun effacement d’exemplaires.
    deleted2 = store.apply_retention(retention_days=30)
    assert deleted2 == 0
    assert (ex_dir / "ex_8.raw").is_file()      # intacts sans exemplars_dir

    store.close()




def test_get_events_order_asc_and_validation(tmp_path):
    """I59 : order='asc' inverse le tri ; order invalide lève ValueError."""
    store = EventStore(db_path=str(tmp_path / "order.db"))
    try:
        for i in range(5):
            store.add_event(
                SoundEvent(
                    t0=1_700_000_000.0 + i * 60.0,
                    dur=1.0,
                    bin_i=10,
                    freq=5.0,
                    lvl_g=10.0,
                    lvl_d=10.0,
                    off_ms=0.0,
                    fp=b"\x03" * 16,
                )
            )
        store.flush()
        desc = [e["t0"] for e in store.get_events(limit=10)]
        asc = [e["t0"] for e in store.get_events(limit=10, order="asc")]
        assert desc == sorted(desc, reverse=True)
        assert asc == sorted(asc)
        with pytest.raises(ValueError):
            store.get_events(order="sideways")
    finally:
        store.close()


def test_i59_merge_quasi_duplicate_clusters() -> None:
    """I59 : deux clusters dont la fp differe d'un bin (pic wobble) sont fusionnes."""
    import numpy as np

    from bruittrack.events import encode_fingerprint

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        store = EventStore(db_path=db_path, batch_size=50)
        spec = np.zeros(100, dtype=np.float32)
        spec[80:85] = [3.0, 6.0, 12.0, 6.0, 3.0]
        fp_a = encode_fingerprint(82, spec, dominant_ch=0, off_ms=2.0)
        fp_b = encode_fingerprint(83, spec, dominant_ch=0, off_ms=2.0)  # delayer le pic
        fp_c = encode_fingerprint(70, np.full(100, 5.0, dtype=np.float32), dominant_ch=1, off_ms=-4.0)
        for cid, fp in [(1, fp_a), (2, fp_b), (3, fp_c)]:
            store.add_event(
                SoundEvent(
                    t0=1700000000.0 + cid,
                    dur=1.0,
                    bin_i=82,
                    freq=40.04,
                    lvl_g=10, lvl_d=9, off_ms=0.0, fp=fp, flags=0, cluster=cid,
                )
            )
            store.add_event(
                SoundEvent(
                    t0=1700000100.0 + cid,
                    dur=1.0,
                    bin_i=82,
                    freq=40.04,
                    lvl_g=10, lvl_d=9, off_ms=0.0, fp=fp, flags=0, cluster=cid,
                )
            )
        store.flush()
        merged = store.merge_quasi_duplicate_clusters(max_bin_delta=1)
        assert merged == 1
        events = store.get_events(limit=10)
        clusters_present = sorted({e["cluster"] for e in events})
        assert clusters_present == [1, 3]
        assert len(store.get_events(limit=10, cluster=1)) == 4
