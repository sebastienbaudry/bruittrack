"""M6 : temps de lecture par bloc + warning blocs de capture lents."""

from __future__ import annotations

from bruittrack.capture import (
    SLOW_BLOCK_STREAK,
    SLOW_READ_US,
    AudioCapture,
    MockAudioCapture,
)
from bruittrack.config import Config, StorageConfig, AudioConfig, DspConfig, DetectorConfig, VizConfig
from bruittrack.pipeline import Engine
from bruittrack.store import EventStore


def _make_engine(tmp_path) -> tuple[Engine, MockAudioCapture]:
    cfg = Config(
        audio=AudioConfig(device=None, sample_rate=48000, decimation=48,
                          block_size=4800, channels=2),
        dsp=DspConfig(n_seg=2048, noverlap=1024, n_buffer=8192, freq_max=48.0,
                      ema_alpha=0.5, floor_history_len=300, lp_cutoff_hz=400.0),
        detector=DetectorConfig(threshold_db=10.0, hysteresis_db=3.0,
                                debounce_ticks=5, max_duration_s=30.0),
        storage=StorageConfig(db_path=str(tmp_path / "m6.db"), batch_size=50,
                              batch_timeout_s=5.0),
        viz=VizConfig(host="127.0.0.1", port=8080),
    )
    mock = MockAudioCapture(block_size=4800, noise_level=0.01, seed=1)
    store = EventStore(db_path=str(tmp_path / "m6.db"), batch_size=50)
    return Engine(cfg, capture=mock, store=store), mock


class TestSlowBlockMetrics:
    def test_mock_no_stall_below_threshold(self):
        mock = MockAudioCapture(block_size=4800, seed=1)
        mock.start()
        blk = mock.get_block(0.5)
        assert blk is not None
        assert mock.last_read_us < SLOW_READ_US
        assert mock.consecutive_slow == 0
        mock.stop()

    def test_mock_injected_stall_flags_slow(self):
        mock = MockAudioCapture(block_size=4800, seed=1)
        mock.start()
        mock.stall_s = 0.02  # stall ALSA simule (20 ms > seuil 15 ms)
        for _ in range(SLOW_BLOCK_STREAK):
            assert mock.get_block(0.5) is not None
        assert mock.last_read_us >= SLOW_READ_US
        assert mock.consecutive_slow == SLOW_BLOCK_STREAK
        mock.stop()

    def test_audio_capture_default_metrics(self):
        cap = AudioCapture()
        assert cap.slow_read_us == SLOW_READ_US
        assert cap.last_read_us == 0
        assert cap.consecutive_slow == 0


class TestEngineSlowBlockWarning:
    def test_warning_after_three_consecutive_slow_blocks(self, tmp_path, caplog):
        """engine.step() emet un warning sur 3 blocs lents consecutifs."""
        engine, mock = _make_engine(tmp_path)
        mock.start()
        mock.stall_s = 0.02  # chaque bloc rapporte un read-time > 15 ms

        with caplog.at_level("WARNING", logger="bruittrack.pipeline"):
            for _ in range(SLOW_BLOCK_STREAK):
                engine.step()

        assert any("capture lente" in rec.getMessage() for rec in caplog.records)
        # Compteur remis a zero pour eviter les warnings dupliques.
        assert mock.consecutive_slow == 0
        engine.stop()
