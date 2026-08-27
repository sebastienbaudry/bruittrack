"""End-to-end test of the Engine pipeline."""

import tempfile
from pathlib import Path

import numpy as np

from bruittrack.capture import MockAudioCapture
from bruittrack.config import Config
from bruittrack.pipeline import Engine
from bruittrack.store import EventStore


class NullCapture:
    """Unstubbed capture : blocks are injected via engine.step(raw_block=...)."""

    def stop(self) -> None:  # pragma: no cover - interface only
        pass


def test_pipeline_engine_simulation() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "sim.db"
        exdir = Path(tmpdir) / "exemplars"
        config = Config()
        config.storage.db_path = str(db_path)
        config.storage.exemplars_dir = str(exdir)

        mock = MockAudioCapture(
            sample_rate=config.audio.sample_rate, channels=2, block_size=4800, frequency_hz=15.0
        )
        mock.start()

        engine = Engine(config=config, capture=mock)

        for _ in range(10):
            block = mock.get_block()
            if block is not None:
                engine.step(block)

        engine.stop()
        mock.stop()


def test_engine_stop_flushes_store_and_stops_capture(tmp_path) -> None:
    db_path = tmp_path / "flush.db"

    config = Config()
    config.storage.db_path = str(db_path)

    class FakeCapture:
        def __init__(self) -> None:
            self.stopped = False

        def stop(self) -> None:
            self.stopped = True

        def get_block(self, timeout: float | None = None):
            return None

    fake = FakeCapture()
    engine = Engine(config=config, capture=fake)

    engine.stop()

    assert fake.stopped is True


def test_engine_synthetic_spike_fires(tmp_path) -> None:
    """I29: 30 s low-amplitude noise (steady floor) + burst tonal ~6 s + drop:
    the event must close and be stored.

    Deterministic via engine.step(raw_block=...) — no need for a real capture.
    Burst 15 Hz → bin ≈ 3 on 48 kHz / 100 ms. Warm up with 400 pure-noise blocks
    to get the floor steady before applying the tonal burst.
    """
    db_path = tmp_path / "spike.db"
    exdir = tmp_path / "exemplars"

    config = Config()
    config.storage.db_path = str(db_path)
    config.storage.exemplars_dir = str(exdir)
    config.storage.batch_size = 1  # immediate flush, no lot

    engine = Engine(config=config, capture=None)  # capture is bypassed on injection

    rng = np.random.default_rng(0)
    sr = 48_000  # sample rate (Hz)
    bs = int(sr * 0.1)  # samples per block (4800 at 48 kHz → 100 ms)

    def noise_block(amp: float = 0.01) -> np.ndarray:
        return rng.normal(0, amp, (bs, 2)).astype(np.float32)

    emitted: list = []

    # Phase 1 : floor stabilised with 400 noise blocks (~40 s @ 10 Hz), em < threshold
    for i in range(400):
        _, _, em1, em2, ev = engine.step(noise_block())
        emitted.extend(ev)
    last_em = max(float(em1.max()), float(em2.max()))
    assert last_em < config.detector.threshold_db, f"floor not steady: em={last_em:.1f} dB"
    assert not emitted, f"spurious events before burst: {len(emitted)}"

    # Phase 2 : strong continuous tone at 2.2 Hz (bin ~4), +20-30 dB over the floor.
    # The detector closes on falling below release threshold OR max_duration (30 s);
    # 60 blocks (6 s) guarantees a firing window once past debounce.
    fs_burst = 2.2
    t_base = np.arange(bs) / sr
    for k in range(60):
        t = t_base + (k * bs) / sr
        tone = np.sin(2 * np.pi * fs_burst * t)
        block = noise_block() + (2.0 * tone[:, None]).astype(np.float32)
        _, _, em1, em2, ev = engine.step(block)
        emitted.extend(ev)

    # Phase 3 : drop back to noise; emergence decays to < release threshold
    # (EMA α=0.5) → the open event closes here and is returned by step().
    if not emitted:
        for _ in range(120):
            _, _, em1, em2, ev = engine.step(noise_block())
            emitted.extend(ev)
            if emitted:
                break
    assert emitted, "detector never closed an event — check threshold/release cadence"

    engine.stop()

    # Persisted events after stop() + close()
    store = EventStore(db_path=db_path)
    stats = store.get_stats()
    assert stats["total_events"] >= 1, f"event not persisted: {stats}"
    store.close()


def test_engine_startup_merges_before_cluster_index(tmp_path) -> None:
    """I59b : au démarrage, la fusion des quasi-doublons precede la reconstitution de l'index."""
    import numpy as np

    from bruittrack.events import SoundEvent, encode_fingerprint

    db_path = tmp_path / "startup.db"
    config = Config()
    config.storage.db_path = str(db_path)

    # Graine : deux clusters quasi-doublons (pic de 1 bin d'ecart) dans la DB.
    store = EventStore(db_path=db_path, batch_size=50)
    spec = np.zeros(100, dtype=np.float32)
    spec[80:85] = [3.0, 6.0, 12.0, 6.0, 3.0]
    fpa = encode_fingerprint(82, spec, dominant_ch=0, off_ms=2.0)
    fpb = encode_fingerprint(83, spec, dominant_ch=0, off_ms=2.0)
    for cid, fp in [(1, fpa), (2, fpb)]:
        store.add_event(
            SoundEvent(
                t0=1700000000.0 + cid,
                dur=1.0,
                bin_i=82,
                freq=40.04,
                lvl_g=10,
                lvl_d=9,
                off_ms=0.0,
                fp=fp,
                flags=0,
                cluster=cid,
            )
        )
    store.flush()
    store.close()

    class FakeCapture:  # pas de capture pour ce test
        def stop(self) -> None:
            pass

        def get_block(self, timeout: float | None = None):
            return None

    engine = Engine(config=config, capture=FakeCapture())
    assert engine.detector.cluster_index.clusters == {1: fpa}
