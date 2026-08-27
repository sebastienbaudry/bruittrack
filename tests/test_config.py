"""Tests for configuration parsing and validation."""

import os
import tempfile
from pathlib import Path

import pytest

from bruittrack.config import Config, load_config


def test_default_config() -> None:
    cfg = Config()
    cfg.validate()
    assert cfg.audio.sample_rate == 48000
    assert cfg.audio.decimation == 48
    assert cfg.audio.fs_low == 1000.0
    assert cfg.dsp.n_seg == 2048
    assert cfg.dsp.freq_max == 150.0
    assert cfg.dsp.min_event_hz == 2.0
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


def test_storage_relative_paths_resolved_against_config_dir() -> None:
    """db_path/exemplars_dir relatifs sont resolus par rapport au dossier du config.toml."""

    (Path("data").resolve()).mkdir(parents=True, exist_ok=True)
    rel_toml = "[storage]\ndb_path = 'data/proj.db'\nexemplars_dir = 'projsnap'\n"
    with tempfile.TemporaryDirectory() as td:
        cfg_dir = Path(td) / "projroot"
        cfg_dir.mkdir()
        toml_file = cfg_dir / "config.toml"
        toml_file.write_text(rel_toml, encoding="utf-8")
        prev_cwd = Path.cwd()
        os.chdir(Path(tempfile.gettempdir()))
        try:
            loaded = load_config(toml_file)
            assert loaded.storage.db_path == str(cfg_dir / "data" / "proj.db")
            assert loaded.storage.exemplars_dir == str(cfg_dir / "projsnap")
        finally:
            os.chdir(prev_cwd)


def test_lp_cutoff_hz_must_be_below_nyquist() -> None:
    """I9 : lp_cutoff_hz doit être strictement dans (0, sample_rate/2)."""
    import pytest

    cfg = load_config()
    original = cfg.dsp.lp_cutoff_hz
    nyquist = cfg.audio.sample_rate / 2.0
    try:
        for bad in (0.0, -10.0, nyquist, 100000.0):
            cfg.dsp.lp_cutoff_hz = bad
            with pytest.raises(ValueError):
                cfg.validate()
        cfg.dsp.lp_cutoff_hz = 400.0
        cfg.validate()  # valeur valide par défaut
    finally:
        cfg.dsp.lp_cutoff_hz = original


def test_retention_days_validation_error() -> None:
    """I27 : retention_days negative doit lever une erreur lisible."""
    cfg = Config()
    cfg.storage.retention_days = -1
    with pytest.raises(ValueError, match="retention_days must be > 0"):
        cfg.validate()

    cfg.storage.retention_days = None
    cfg.validate()  # None est valide (desactive)


def test_load_config_invalid_threshold_raises(tmp_path) -> None:
    """I27 : une TOML invalide doit echouer proprement au chargement."""
    toml_body = "[detector]" + chr(10) + "threshold_db = -5.0" + chr(10)
    bad_path = tmp_path / "config_bad.toml"
    bad_path.write_text(toml_body, encoding="utf-8")
    with pytest.raises(ValueError, match="threshold_db must be > 0"):
        load_config(bad_path)


def test_viz_config_defaults_and_auth(tmp_path) -> None:
    """P0-3 : VizConfig a pour host 127.0.0.1 par défaut et charge auth_token."""
    cfg = Config()
    cfg.validate()
    assert cfg.viz.host == "127.0.0.1"
    assert cfg.viz.port == 8760
    assert cfg.viz.auth_token is None

    toml_body = """
    [viz]
    host = "0.0.0.0"
    port = 9000
    auth_token = "mon_secret"
    """
    p = tmp_path / "viz_cfg.toml"
    p.write_text(toml_body, encoding="utf-8")
    loaded = load_config(p)
    assert loaded.viz.host == "0.0.0.0"
    assert loaded.viz.port == 9000
    assert loaded.viz.auth_token == "mon_secret"
