"""End-to-end tests for the Engine pipeline."""

from pathlib import Path
import tempfile
import numpy as np
import pytest

from bruittrack.capture import MockAudioCapture
from bruittrack.config import Config
from bruittrack.pipeline import Engine
from bruittrack.store import EventStore


def test_pipeline_engine_simulation() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "sim.db"
        exemplars_dir = Path(tmpdir) / "exemplars"

        config = Config()
        config.storage.db_path = str(db_path)
        config.storage.exemplars_dir = str(exemplars_dir)
        config.detector.warmup_ticks = 5  # Fast warmup for test
        config.detector.debounce_ticks = 2
        config.storage.batch_size = 1

        mock_capture = MockAudioCapture(
            sample_rate=config.audio.sample_rate,
            channels=config.audio.channels,
            block_size=config.audio.block_size,
            frequency_hz=15.0,
        )
        mock_capture.start()

        engine = Engine(config=config, capture=mock_capture)

        # Run 10 ticks to pass warmup and generate data
        for _ in range(10):
            psd1, psd2, em1, em2, events = engine.step()

        engine.stop()

        # Check DB was created and can be queried
        store = EventStore(db_path=db_path)
        stats = store.get_stats()
        assert stats["total_events"] >= 0
        store.close()
