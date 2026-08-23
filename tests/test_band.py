"""Tests for detection band limits: min_event_hz / freq_max (I35)."""

from __future__ import annotations

import numpy as np
import pytest

from bruittrack.config import Config
from bruittrack.events import EventDetector

RES = 0.48828125  # 48000 / (2 * 2048): resolution per bin in Hz
N_BINS = 303  # enough bins to reach ~148 Hz (freq_max default territory)
START = 1_720_000_000.0

AUDIO = np.zeros((8192, 2), dtype=np.float32)


def _zero_spectrum() -> np.ndarray:
    return np.zeros(N_BINS, dtype=np.float32)


def _run_ticks(
    det: EventDetector,
    frames: list[np.ndarray],
    unix_start: float = START,
) -> list:
    """Feed one tick per emergence frame; return every emitted event."""
    events: list = []
    for k, em in enumerate(frames):
        t = unix_start + 0.1 * k
        events.extend(det.update(em, _zero_spectrum(), AUDIO.copy(), off_ms=0.0, unix_time=t))
    return events


def test_detection_respects_min_event_hz(tmp_path) -> None:
    """A bin below min_event_hz never creates an event; a bin in band does."""
    low_pin = 1  # ~0.5 Hz: below min_event_hz = 2.0 Hz
    hi_pin = 6  # ~2.93 Hz: inside default band
    quiet = _zero_spectrum()

    det_low = EventDetector(
        threshold_db=10.0,
        hysteresis_db=3.0,
        debounce_ticks=2,
        exemplars_dir=tmp_path,
        min_event_hz=2.0,
    )
    low_frames = []
    for _ in range(4):
        s = _zero_spectrum()
        s[low_pin] = 25.0
        low_frames.append(s)
    low_frames.append(quiet)  # closing frame releases the detector
    assert _run_ticks(det_low, low_frames) == []
    assert not det_low.is_active

    det_hi = EventDetector(
        threshold_db=10.0,
        hysteresis_db=3.0,
        debounce_ticks=2,
        exemplars_dir=tmp_path,
        min_event_hz=2.0,
    )
    hi_frames = []
    for _ in range(4):
        s = _zero_spectrum()
        s[hi_pin] = 25.0
        hi_frames.append(s)
    hi_frames.append(quiet)
    events = _run_ticks(det_hi, hi_frames)
    assert len(events) == 1
    assert events[-1].bin_i == hi_pin


def test_detection_respects_freq_max(tmp_path) -> None:
    """A ~120 Hz bin is detected with max_event_hz=150, not with 100."""
    peak_pin = int(120 / RES)  # ~246 Hz; N_BINS must exceed this
    assert peak_pin < N_BINS, "test constant drifts out of range - update N_BINS"

    def frame() -> np.ndarray:
        s = _zero_spectrum()
        s[peak_pin] = 25.0
        return s

    frames = [frame() for _ in range(4)] + [_zero_spectrum()]

    det150 = EventDetector(
        threshold_db=10.0,
        hysteresis_db=3.0,
        debounce_ticks=2,
        exemplars_dir=tmp_path,
        min_event_hz=2.0,
        max_event_hz=150.0,  # 120 Hz inside the band
    )
    evs = _run_ticks(det150, frames)
    assert len(evs) == 1 and evs[-1].bin_i == peak_pin

    det100 = EventDetector(
        threshold_db=10.0,
        hysteresis_db=3.0,
        debounce_ticks=2,
        exemplars_dir=tmp_path,
        min_event_hz=2.0,
        max_event_hz=100.0,  # 120 Hz above the band
    )
    evs = _run_ticks(det100, [s.copy() for s in frames])
    assert evs == []


def test_config_default_frequency_values_and_validation() -> None:
    cfg = Config()
    assert cfg.dsp.min_event_hz == pytest.approx(2.0)
    assert cfg.dsp.freq_max == pytest.approx(150.0)
    with pytest.raises(ValueError):
        bad = Config()
        bad.dsp.min_event_hz = 48.0 if False else 0.5  # under the floor
        bad.validate()
    with pytest.raises(ValueError):
        bad2 = Config()
        bad2.dsp.min_event_hz = 150.0  # must be strictly inferior to freq_max
        bad2.validate()
