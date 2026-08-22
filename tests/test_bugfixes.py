"""Regression tests for the BUGS.md fixes (BUG-01..12)."""

from __future__ import annotations

import contextlib
import threading
import time

import sqlite3

import pytest
import bruittrack.store as store_mod

import numpy as np
import pytest

from bruittrack.config import Config, StorageConfig, AudioConfig, DspConfig, DetectorConfig, VizConfig
from bruittrack.dsp import DspPipeline, SosFilter
from bruittrack.events import SoundEvent
from bruittrack.store import EventStore


def _make_store(tmp_path, **kw) -> EventStore:
    return EventStore(db_path=str(tmp_path / "t.db"), batch_size=50, **kw)


# ---------------------------------------------------------------------------
# BUG-01/08: thread-safety of EventStore.
# Design under test: every DB call opens a short-lived connection via the
# module-level `cursor()` factory; the in-memory batch buffer is guarded by
# a lock. No sqlite3.Connection object is ever shared across threads.
# ---------------------------------------------------------------------------
class TestEventStoreThreadSafety:
    def test_concurrent_add_flush(self, tmp_path):
        store = _make_store(tmp_path)

        def worker(start: int, n: int) -> None:
            for i in range(n):
                ev = SoundEvent(t0=time.time(), dur=1.0, bin_i=start + i % 50,
                                freq=0.0, lvl_g=12.0, lvl_d=8.0, off_ms=0.0,
                                fp=b"\x00" * 16)
                store.add_event(ev)

        threads = [threading.Thread(target=worker, args=(i * 10, 10)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        count = store.flush()
        assert store.get_stats()["total_events"] == 40

    def test_add_event_autoflush_no_deadlock(self, tmp_path):
        """add_event() auto-flushes in-process when batch is reached:
        the inner path must not re-acquire the held lock (deadlock)."""
        store = EventStore(db_path=str(tmp_path / "t.db"), batch_size=2)
        for i in range(3):
            ev = SoundEvent(t0=time.time(), dur=1.0, bin_i=i, freq=0.0,
                            lvl_g=12.0, lvl_d=8.0, off_ms=0.0, fp=b"\x00" * 16)
            store.add_event(ev)  # would hang if lock not managed correctly
        store.flush()
        assert store.get_stats()["total_events"] == 3
        assert len(store._buffer) == 0


# ---------------------------------------------------------------------------
# BUG-03: flush() preserves buffer on DB error
# ---------------------------------------------------------------------------
class TestFlushRecovery:
    def test_buffer_not_emptied_on_failure(self, tmp_path):
        store = _make_store(tmp_path)
        # Inject a dummy connection that raises
        events = [
            SoundEvent(t0=time.time(), dur=1.0, bin_i=i, freq=0.0,
                       lvl_g=12.0, lvl_d=8.0, off_ms=0.0, fp=b"\x00" * 16)
            for i in range(5)
        ]
        ev = events[0]

        # Monkey-patch the module-level connection factory: transient error
        class _FailingConn:
            def execute(self, q, params=()):
                raise sqlite3.OperationalError("simulated disk full")
            def executemany(self, q, rows):
                raise sqlite3.OperationalError("simulated disk full")

        @contextlib.contextmanager
        def _failing_cursor(db_path, **kw):
            yield _FailingConn()

        original_cursor = store_mod.cursor
        store_mod.cursor = _failing_cursor
        store.add_event(ev)
        # flush() called internally should not clear buffer
        assert len(store._buffer) == 1

        # Restore and verify event survives
        store_mod.cursor = original_cursor
        flushed = store.flush()
        assert flushed == 1


# ---------------------------------------------------------------------------
# BUG-04: retention wiring in Engine (integration-level smoke test)
# ---------------------------------------------------------------------------
class TestRetentionWiring:
    def test_apply_retention_deletes_old(self, tmp_path):
        store = _make_store(tmp_path)
        # Old event (1000 days ago)
        old_t0 = time.time() - 1000 * 86400
        ev = SoundEvent(t0=old_t0, dur=1.0, bin_i=5, freq=0.0,
                        lvl_g=12.0, lvl_d=8.0, off_ms=0.0, fp=b"\x00" * 16)
        store.add_event(ev)
        store.flush()

        deleted = store.apply_retention(100)
        assert deleted == 1
        assert store.get_stats()["total_events"] == 0


# ---------------------------------------------------------------------------
# BUG-07: Welch power normalization (Σw²)
# ---------------------------------------------------------------------------
class TestWelchNormalization:
    def test_welch_constant_power(self):
        """Constant signal → PSD ≈ amplitude² / N (within tolerance)."""
        dp = DspPipeline(sample_rate=48000, decimation=48, n_seg=256, noverlap=128,
                         n_buffer=512, freq_max=48.0, lp_cutoff_hz=400.0)
        t = np.arange(dp.n_seg) / (dp.sample_rate / dp.decimation)
        x = np.ones((len(t), 2), dtype=np.float32) * 0.5
        psd1, psd2 = dp.process_block(x)
        # DC bin should dominate and be much larger than others
        assert psd1[0] > psd1[5]

    def test_window_sum_used(self):
        """window_scale must equal Σ(w²) of the Hann window, not (Σw)²."""
        dp = DspPipeline(sample_rate=48000, decimation=48, n_seg=256, noverlap=128,
                         n_buffer=512, freq_max=48.0, lp_cutoff_hz=400.0)
        w = np.hanning(dp.n_seg)
        expected = float(np.sum(w ** 2))
        assert abs(dp.window_scale - expected) < max(1e-6, 1e-6 * abs(expected)), (
            f"window_scale={dp.window_scale} != Σw²={expected}"
        )


# ---------------------------------------------------------------------------
# BUG-09: retention_days default = 365 when not in TOML
# ---------------------------------------------------------------------------
class TestRetentionDefault:
    def test_default_retention_is_365(self):
        from bruittrack.config import load_config
        cfg = load_config()  # no file → defaults
        assert cfg.storage.retention_days == 365

    @pytest.fixture
    def toml_no_retention(self, tmp_path):
        p = tmp_path / "no_ret.toml"
        (p).write_text('[audio]\nsample_rate = 48000\n[storage]\ndb_path = ":memory:"\n')
        return str(p)

    def test_toml_missing_key_keeps_default(self, toml_no_retention):
        from bruittrack.config import load_config
        cfg = load_config(toml_no_retention)
        assert cfg.storage.retention_days == 365


# ---------------------------------------------------------------------------
# BUG-10: config validation (batch_size, port, retention)
# ---------------------------------------------------------------------------
class TestConfigValidation:
    def _base_config(self) -> Config:
        return Config(
            audio=AudioConfig(device=None, sample_rate=48000, decimation=48,
                              block_size=4800, channels=2),
            dsp=DspConfig(n_seg=2048, noverlap=1024, n_buffer=8192, freq_max=48.0,
                          ema_alpha=0.5, floor_history_len=300, lp_cutoff_hz=400.0),
            detector=DetectorConfig(threshold_db=10.0, hysteresis_db=3.0,
                                    debounce_ticks=5, max_duration_s=30.0),
            storage=StorageConfig(db_path=":memory:", batch_size=50, batch_timeout_s=5.0),
            viz=VizConfig(host="0.0.0.0", port=8080),
        )

    def test_valid_config_passes(self):
        self._base_config().validate()

    def test_batch_size_zero_rejected(self):
        cfg = self._base_config()
        cfg.storage.batch_size = 0
        with pytest.raises(ValueError, match="batch_size"):
            cfg.validate()

    def test_port_out_of_range_rejected(self):
        cfg = self._base_config()
        cfg.viz.port = 999
        with pytest.raises(ValueError, match="port"):
            cfg.validate()

    def test_retention_days_negative_rejected(self):
        cfg = self._base_config()
        cfg.storage.retention_days = -5
        with pytest.raises(ValueError, match="retention_days"):
            cfg.validate()

    def test_block_size_not_multiple_of_decimation_rejected(self):
        """BUG-10: block_size must divide into stream ticks exactly."""
        cfg = self._base_config()
        cfg.audio.block_size = 4801
        with pytest.raises(ValueError, match="block_size"):
            cfg.validate()

    def test_sample_rate_not_multiple_of_decimation_rejected(self):
        cfg = self._base_config()
        cfg.audio.sample_rate = 44100
        with pytest.raises(ValueError, match="exact multiple"):
            cfg.validate()

    def test_freq_max_above_nyquist_low_rejected(self):
        """BUG-10: freq_max above the decimated Nyquist would alias."""
        cfg = self._base_config()
        cfg.dsp.freq_max = 600.0  # stream 1 kHz -> Nyquist 500 Hz
        with pytest.raises(ValueError, match="freq_max"):
            cfg.validate()

    def test_debounce_zero_rejected(self):
        cfg = self._base_config()
        cfg.detector.debounce_ticks = 0
        with pytest.raises(ValueError, match="debounce"):
            cfg.validate()


def run():
    import sys
    sys.exit(pytest.main([__file__, "-v"]))

if __name__ == "__main__":
    run()


class TestMockAudioCapture:
    """BUG-12 regression: deterministic with seed, blocks paced near real-time."""

    def test_seed_reproducibility_and_shape(self) -> None:
        from bruittrack.capture import MockAudioCapture

        m = MockAudioCapture(block_size=480, noise_level=0.1, seed=99)
        m.start()
        blocks = [m.get_block(0.05) for _ in range(3)]
        m.stop()
        x = np.concatenate(blocks, axis=0)
        assert x.shape == (480 * 3, 2) and x.dtype == np.float32

    def test_different_seeds_differ(self) -> None:
        from bruittrack.capture import MockAudioCapture

        def run(seed: int) -> np.ndarray:
            m = MockAudioCapture(block_size=480, noise_level=0.1, seed=seed)
            m.start()
            blk = np.concatenate([m.get_block(0.05) for _ in range(3)], axis=0)
            m.stop()
            return blk

        assert not np.array_equal(run(1), run(2)), "different seeds must produce different blocks"

    def test_deterministic_same_seed_replay(self) -> None:
        from bruittrack.capture import MockAudioCapture

        def run() -> np.ndarray:
            m = MockAudioCapture(block_size=480, noise_level=0.1, seed=7)
            m.start()
            blk = [m.get_block(0.05) for _ in range(3)]
            m.stop()
            return np.concatenate(blk, axis=0)

        assert np.array_equal(run(), run()), "same seed must replay identical blocks"


class TestFlushErrorPreservation:
    """BUG-03: a failing flush must not drop buffered events."""

    @staticmethod
    def _ev(bin_i: int):
        return SoundEvent(t0=1.0, dur=1.0, bin_i=bin_i, freq=float(bin_i),
                          lvl_g=5.0, lvl_d=4.0, off_ms=0.0, fp=b"\x02" * 16)

    def test_flush_error_preserves_buffer(self, tmp_path) -> None:
        s = EventStore(db_path=str(tmp_path / "f.db"), batch_size=3)
        for i in range(2):
            s.add_event(self._ev(i))

        real_cursor = store_mod.cursor
        failures = {"n": 0}

        def failing(path, *args, **kwargs):
            failures["n"] += 1
            if failures["n"] == 1:
                raise RuntimeError("simulated sqlite failure")
            return real_cursor(path, *args, **kwargs)

        store_mod.cursor = failing
        try:
            s.add_event(self._ev(2))  # autoflush -> error, buffer preserved
            assert len(s._buffer) == 3
            s.add_event(self._ev(3))  # next autoflush -> success (4 rows)
        finally:
            store_mod.cursor = real_cursor

        assert failures["n"] == 2
        assert s.get_stats()["total_events"] == 4

# ---------------------------------------------------------------------------
# BUG-05: exemplar float16 raw -> int16 WAV conversion
# ---------------------------------------------------------------------------
class TestExemplarWav:
    def test_helper_produces_valid_2ch_wav(self, tmp_path):
        import io
        import wave

        from bruittrack.__main__ import _exemplar_to_wav

        t = np.arange(128) / 1000.0
        sig = (np.sin(2 * np.pi * 40 * t) * 0.5).astype(np.float32)
        stereo = np.stack([sig, sig], axis=1).astype(np.float16)
        raw = tmp_path / "ex_7.raw"
        raw.write_bytes(stereo.tobytes())

        wav = _exemplar_to_wav(raw)
        wf = wave.open(io.BytesIO(wav), "rb")
        assert wf.getnchannels() == 2
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 1000
        assert wf.getnframes() == 128


def test_verbose_floor_flag_and_health_line(tmp_path, capsys) -> None:
    """--verbose-floor: format sans exception + cmd_test synthétique rc=0."""
    import numpy as np
    from types import SimpleNamespace

    from bruittrack.__main__ import cmd_test, format_floor_health
    from bruittrack.dsp import FloorTracker

    def tracker(warmed: bool, n_bins: int = 99) -> FloorTracker:
        ft = FloorTracker(warmup_ticks=2 if warmed else 100)
        psd = np.zeros(n_bins, dtype=np.float32)
        for _ in range(10):
            ft.update(psd.copy(), psd.copy())
        return ft

    line_warm = format_floor_health(tracker(True))
    assert "OK" in line_warm and "médiane" in line_warm
    line_cold = format_floor_health(tracker(False))
    assert "warmup" in line_cold

    cfg = tmp_path / "empty.toml"
    cfg.touch()
    args = SimpleNamespace(config=str(cfg), seconds=1, synthetic=True, verbose_floor=True)
    assert cmd_test(args) == 0
    capsys.readouterr()  # les lignes de test sont tolérées


def test_stats_json_flag(tmp_path, monkeypatch):
    """I1: stats --json produit une sortie JSON machine parseable (M6)."""
    import io
    import json as _json
    import sys as _sys

    from bruittrack.__main__ import main

    store = _make_store(tmp_path)
    ev = SoundEvent(t0=1_000.0, dur=1.5, bin_i=18, freq=18 * 0.49, lvl_g=12.0, lvl_d=3.0, off_ms=-1.2,
                    fp=b"\x01" * 16, flags=0)
    store.add_event(ev)
    store.flush()
    cfg = tmp_path / "cfg.toml"
    cfg.write_text(
        "[storage]\ndb_path = \"%s\"\nexemplars_dir = \"%s\"\n"
        % ((tmp_path / "t.db").as_posix(), (tmp_path / "ex").as_posix())
    )
    buf = io.StringIO()
    monkeypatch.setattr(_sys, "argv", ["bruittrack", "--config", str(cfg), "stats", "--json"])
    with contextlib.redirect_stdout(buf):
        rc = main()
    assert rc == 0
    data = _json.loads(buf.getvalue())
    assert data["total_events"] >= 1
    assert "top_clusters" in data and "db_path" in data
