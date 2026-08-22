"""Tests for configuration parsing and validation."""

from pathlib import Path
import tempfile
import pytest

from bruittrack.config import Config, load_config


def test_default_config() -> None:
    cfg = Config()
    cfg.validate()
    assert cfg.audio.sample_rate == 48000
    assert cfg.audio.decimation == 48
    assert cfg.audio.fs_low == 1000.0
    assert cfg.dsp.n_seg == 2048
    assert cfg.dsp.freq_max == 48.0
    assert cfg.detector.threshold_db == 10.0


def test_config_validation_errors() -> None:
    cfg = Config()
    cfg.audio.channels = 1
    with pytest.raises(ValueError, match="channels must be 2"):
        cfg.validate()

    cfg = Config()
    cfg.audio.sample_rate = -100
    with pytest.raises(ValueError, match="sample_rate must be > 0"):
        cfg.validate()

    cfg = Config()
    cfg.dsp.n_seg = 1000  # Not power of 2
    with pytest.raises(ValueError, match="power of 2"):
        cfg.validate()

    cfg = Config()
    cfg.detector.threshold_db = 5.0
    cfg.detector.hysteresis_db = 6.0
    with pytest.raises(ValueError, match="hysteresis_db must be < threshold_db"):
        cfg.validate()


def test_load_config_from_file() -> None:
    toml_content = b"""
    [audio]
    device = "M-Track"
    sample_rate = 48000
    decimation = 48

    [detector]
    threshold_db = 12.5
    debounce_ticks = 7
    """
    with tempfile.NamedTemporaryFile(suffix=".toml", delete=False) as f:
        f.write(toml_content)
        temp_path = f.name

    try:
        cfg = load_config(temp_path)
        assert cfg.audio.device == "M-Track"
        assert cfg.detector.threshold_db == 12.5
        assert cfg.detector.debounce_ticks == 7
        assert cfg.dsp.n_seg == 2048  # Default preserved
    finally:
        Path(temp_path).unlink(missing_ok=True)
