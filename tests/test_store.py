"""Tests for SQLite EventStore."""

from pathlib import Path
import tempfile
import time
import pytest

from bruittrack.events import SoundEvent
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
                    SoundEvent(t0=t0 + i, dur=1.0, bin_i=i % 20, freq=float(i),
                               lvl_g=5.0, lvl_d=4.0, off_ms=0.0, fp=b"\x01" * 16)
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

    threads = [_t.Thread(target=writer), _t.Thread(target=reader, args=(1,)),
               _t.Thread(target=reader, args=(2,))]
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
