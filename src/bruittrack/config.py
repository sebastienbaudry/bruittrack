"""Configuration management for BruitTrack."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AudioConfig:
    device: str | int | None = None
    sample_rate: int = 48000
    decimation: int = 48
    block_size: int = 4800
    channels: int = 2

    @property
    def fs_low(self) -> float:
        return self.sample_rate / self.decimation

    @property
    def block_size_low(self) -> int:
        return self.block_size // self.decimation


@dataclass
class DspConfig:
    """DSP params — defaults cf. config.toml.example (freq_max = 150.0, min_event_hz = 2.0 Hz)."""

    n_seg: int = 2048
    noverlap: int = 1024
    n_buffer: int = 8192
    freq_max: float = 150.0
    min_event_hz: float = 2.0
    ema_alpha: float = 0.5
    floor_history_len: int = 300
    lp_cutoff_hz: float = 400.0


@dataclass
class DetectorConfig:
    threshold_db: float = 10.0
    hysteresis_db: float = 3.0
    debounce_ticks: int = 5
    max_duration_s: float = 30.0
    warmup_ticks: int = 300
    cluster_freq_tolerance_hz: float = 0.5


@dataclass
class StorageConfig:
    db_path: str = "data/bruittrack.db"
    exemplars_dir: str = "exemplars"
    batch_size: int = 50
    batch_timeout_s: float = 30.0
    retention_days: int | None = 365


@dataclass
class VizConfig:
    host: str = "0.0.0.0"
    port: int = 8760


@dataclass
class Config:
    audio: AudioConfig = field(default_factory=AudioConfig)
    dsp: DspConfig = field(default_factory=DspConfig)
    detector: DetectorConfig = field(default_factory=DetectorConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    viz: VizConfig = field(default_factory=VizConfig)

    def validate(self) -> None:
        """Validate configuration parameters."""
        if self.audio.channels != 2:
            raise ValueError(f"Audio channels must be 2 (got {self.audio.channels})")
        if self.audio.sample_rate <= 0:
            raise ValueError("Audio sample_rate must be > 0")
        if self.audio.decimation <= 0:
            raise ValueError(f"Audio decimation must be > 0 (got {self.audio.decimation})")
        if self.audio.sample_rate % self.audio.decimation != 0:
            raise ValueError(
                f"Sample rate {self.audio.sample_rate} must be an exact multiple of decimation {self.audio.decimation}"
            )
        if self.audio.block_size % self.audio.decimation != 0:
            raise ValueError(
                f"Audio block_size ({self.audio.block_size}) must be an exact multiple of decimation ({self.audio.decimation})"
            )
        fs_low = self.audio.sample_rate / self.audio.decimation
        if not 0 < self.dsp.freq_max <= fs_low / 2.0:
            raise ValueError(
                f"DSP freq_max ({self.dsp.freq_max} Hz) must be in (0, {fs_low / 2:.1f} Hz]"
            )
        if self.dsp.min_event_hz < 1.0 or self.dsp.min_event_hz >= self.dsp.freq_max:
            raise ValueError(
                f"DSP min_event_hz ({self.dsp.min_event_hz} Hz) must be in "
                f"[1.0, freq_max={self.dsp.freq_max}) — le matériel n'est pas fiable sous 1 Hz"
            )
        if self.detector.debounce_ticks < 1:
            raise ValueError("Detector debounce_ticks must be >= 1")
        if self.detector.max_duration_s <= 0:
            raise ValueError("Detector max_duration_s must be > 0")
        if self.dsp.n_seg <= 0 or (self.dsp.n_seg & (self.dsp.n_seg - 1)) != 0:
            raise ValueError(f"DSP n_seg must be a power of 2 (got {self.dsp.n_seg})")
        if self.dsp.noverlap >= self.dsp.n_seg:
            raise ValueError("DSP noverlap must be < n_seg")
        if self.dsp.n_buffer < self.dsp.n_seg:
            raise ValueError("DSP n_buffer must be >= n_seg")
        if not 0.0 < self.dsp.ema_alpha <= 1.0:
            raise ValueError("DSP ema_alpha must be in (0, 1]")
        if self.detector.threshold_db <= 0:
            raise ValueError("Detector threshold_db must be > 0")
        if self.detector.hysteresis_db >= self.detector.threshold_db:
            raise ValueError("Detector hysteresis_db must be < threshold_db")
        if self.detector.cluster_freq_tolerance_hz <= 0:
            raise ValueError(
                f"Detector cluster_freq_tolerance_hz ({self.detector.cluster_freq_tolerance_hz}) "
                "must be > 0"
            )
        if self.storage.batch_size <= 0:
            raise ValueError(f"Storage batch_size must be > 0 (got {self.storage.batch_size})")
        if self.storage.batch_timeout_s <= 0:
            raise ValueError("Storage batch_timeout_s must be > 0")
        if self.storage.retention_days is not None and self.storage.retention_days <= 0:
            raise ValueError("Storage retention_days must be > 0 (or None to disable)")
        nyquist = self.audio.sample_rate / 2.0
        if not 0 < self.dsp.lp_cutoff_hz < nyquist:
            raise ValueError(
                f"DSP lp_cutoff_hz ({self.dsp.lp_cutoff_hz} Hz) must be in (0, {nyquist:.1f} Hz)"
            )

        if not 1024 <= self.viz.port <= 65535:
            raise ValueError(f"Viz port must be in [1024, 65535] (got {self.viz.port})")


def load_config(config_path: str | Path | None = None) -> Config:
    """Load configuration from a TOML file or return defaults.

    Args:
        config_path: Path to config.toml. If None, looks for config.toml then config.toml.example.

    Returns:
        Validated Config instance.
    """
    raw_data: dict[str, Any] = {}
    cfg_dir: Path | None = None  # dossier du config.toml resolu

    target_path: Path | None = None
    if config_path is not None:
        target_path = Path(config_path)
    else:
        for candidate in (Path("config.toml"), Path("config.toml.example")):
            if candidate.is_file():
                target_path = candidate
                break

    if target_path is not None and target_path.is_file():
        cfg_dir = target_path.parent
        with open(target_path, "rb") as f:
            raw_data = tomllib.load(f)

    # Audio
    audio_dict = raw_data.get("audio", {})
    dev_val = audio_dict.get("device")
    if dev_val == "" or dev_val is None:
        dev_val = None
    elif isinstance(dev_val, str) and dev_val.isdigit():
        dev_val = int(dev_val)

    audio_cfg = AudioConfig(
        device=dev_val,
        sample_rate=int(audio_dict.get("sample_rate", 48000)),
        decimation=int(audio_dict.get("decimation", 48)),
        block_size=int(audio_dict.get("block_size", 4800)),
        channels=int(audio_dict.get("channels", 2)),
    )

    # DSP
    dsp_dict = raw_data.get("dsp", {})
    dsp_cfg = DspConfig(
        n_seg=int(dsp_dict.get("n_seg", 2048)),
        noverlap=int(dsp_dict.get("noverlap", 1024)),
        n_buffer=int(dsp_dict.get("n_buffer", 8192)),
        freq_max=float(dsp_dict.get("freq_max", 150.0)),
        min_event_hz=float(dsp_dict.get("min_event_hz", 2.0)),
        ema_alpha=float(dsp_dict.get("ema_alpha", 0.5)),
        floor_history_len=int(dsp_dict.get("floor_history_len", 300)),
        lp_cutoff_hz=float(dsp_dict.get("lp_cutoff_hz", 400.0)),
    )

    # Detector
    det_dict = raw_data.get("detector", {})
    det_cfg = DetectorConfig(
        threshold_db=float(det_dict.get("threshold_db", 10.0)),
        hysteresis_db=float(det_dict.get("hysteresis_db", 3.0)),
        debounce_ticks=int(det_dict.get("debounce_ticks", 5)),
        max_duration_s=float(det_dict.get("max_duration_s", 30.0)),
        warmup_ticks=int(det_dict.get("warmup_ticks", 300)),
        cluster_freq_tolerance_hz=float(
            det_dict.get("cluster_freq_tolerance_hz", 0.5)
        ),
    )

    def resolve_rel(p: Any) -> str:
        """Resout un chemin relatif de storage par rapport au dossier du config.toml."""
        pp = Path(str(p))
        if pp.is_absolute() or cfg_dir is None:
            return str(pp)
        return str(cfg_dir / pp)

    # Storage
    store_dict = raw_data.get("storage", {})
    store_cfg = StorageConfig(
        db_path=resolve_rel(store_dict.get("db_path", "data/bruittrack.db")),
        exemplars_dir=resolve_rel(store_dict.get("exemplars_dir", "exemplars")),
        batch_size=int(store_dict.get("batch_size", 50)),
        batch_timeout_s=float(store_dict.get("batch_timeout_s", 30.0)),
    )
    # retention_days: dataclass default 365 applies unless explicitly set
    if "retention_days" in store_dict:
        rd = int(store_dict["retention_days"])
        store_cfg.retention_days = None if rd <= 0 else rd

    # Viz
    viz_dict = raw_data.get("viz", {})
    viz_cfg = VizConfig(
        host=str(viz_dict.get("host", "0.0.0.0")),
        port=int(viz_dict.get("port", 8760)),
    )

    config = Config(
        audio=audio_cfg,
        dsp=dsp_cfg,
        detector=det_cfg,
        storage=store_cfg,
        viz=viz_cfg,
    )
    config.validate()
    return config
