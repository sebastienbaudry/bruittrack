"""Tests for DSP filters, Welch PSD, floor tracking, and cross-correlation."""

import numpy as np
import pytest

from bruittrack.dsp import (
    DspPipeline,
    FloorTracker,
    SosFilter,
    compute_channel_delay_ms,
    design_butterworth_lp_sos,
)


def test_butterworth_sos_design() -> None:
    sos = design_butterworth_lp_sos(cutoff_hz=400.0, fs=48000.0, order=8)
    assert sos.shape == (4, 6)

    # Check DC gain is approximately 1.0 (0 dB)
    # At DC (z = 1), H(1) = prod(sum(b) / sum(a))
    dc_gain = 1.0
    for section in sos:
        b_sum = np.sum(section[:3])
        a_sum = np.sum(section[3:])
        dc_gain *= b_sum / a_sum
    assert np.isclose(dc_gain, 1.0, rtol=1e-3)


def test_sos_filter_filtering() -> None:
    sos = design_butterworth_lp_sos(cutoff_hz=400.0, fs=48000.0, order=8)
    filt = SosFilter(sos, n_channels=2)

    # 1000 samples DC step
    x = np.ones((1000, 2), dtype=np.float64)
    y = filt.filter(x)
    assert y.shape == (1000, 2)
    assert not np.isnan(y).any()
    # Steady state should converge to 1.0
    assert np.isclose(y[-1, 0], 1.0, atol=1e-2)
    assert np.isclose(y[-1, 1], 1.0, atol=1e-2)


def test_dsp_pipeline_frequency_identification() -> None:
    dsp = DspPipeline(
        sample_rate=48000,
        decimation=48,
        n_seg=2048,
        noverlap=1024,
        n_buffer=8192,
        freq_max=48.0,
        ema_alpha=0.5,
    )
    assert dsp.fs_low == 1000.0
    assert dsp.n_bins == 99  # 0 to ~47.85 Hz

    # Target test tone: 20 Hz
    target_freq = 20.0
    # Expected peak bin: round(20 / (1000 / 2048)) = round(20 / 0.48828) = 41
    expected_bin = int(round(target_freq / dsp.bin_resolution))

    # Feed enough blocks (~85 blocks = 8.5s) to fill the 8192 buffer
    n_blocks = 90
    block_size_48k = 4800
    t_global = 0.0

    psd1: np.ndarray = np.zeros(dsp.n_bins)
    psd2: np.ndarray = np.zeros(dsp.n_bins)

    for _ in range(n_blocks):
        t = t_global + np.arange(block_size_48k) / 48000.0
        t_global += block_size_48k / 48000.0

        # Sine tone on both channels
        signal_block = np.zeros((block_size_48k, 2), dtype=np.float32)
        signal_block[:, 0] = 0.5 * np.sin(2.0 * np.pi * target_freq * t)
        signal_block[:, 1] = 0.5 * np.sin(2.0 * np.pi * target_freq * t)

        psd1, psd2 = dsp.process_block(signal_block)

    # Peak in PSD should match 20 Hz bin
    peak_bin1 = int(np.argmax(psd1))
    peak_bin2 = int(np.argmax(psd2))
    assert abs(peak_bin1 - expected_bin) <= 1
    assert abs(peak_bin2 - expected_bin) <= 1


def test_floor_tracker() -> None:
    n_bins = 99
    ft = FloorTracker(n_bins=n_bins, history_len=10, warmup_ticks=5)

    psd_base = np.full(n_bins, -50.0, dtype=np.float32)
    ft.update(psd_base, psd_base)
    assert not ft.is_warmed_up

    # Add ticks
    for _ in range(4):
        ft.update(psd_base, psd_base)

    assert ft.is_warmed_up

    # Introduce a transient peak of +20 dB on bin 10
    psd_spike = psd_base.copy()
    psd_spike[10] = -30.0

    em1, em2, f1, f2 = ft.compute_emergence(psd_spike, psd_spike)
    assert np.isclose(em1[10], 20.0, atol=1.0)
    assert np.isclose(em2[10], 20.0, atol=1.0)


def test_channel_delay_cross_correlation() -> None:
    # Generate 1000 Hz signal with 3 ms delay between Left and Right
    fs_low = 1000.0
    n_samples = 512
    t = np.arange(n_samples) / fs_low

    s = np.sin(2.0 * np.pi * 30.0 * t)
    delay_samples = 3  # 3 ms at 1000 Hz

    buf = np.zeros((n_samples, 2), dtype=np.float32)
    buf[:, 0] = s
    buf[delay_samples:, 1] = s[:-delay_samples]

    delay_ms = compute_channel_delay_ms(buf, max_lag_ms=8.0, fs_low=fs_low)
    assert np.isclose(delay_ms, 3.0, atol=1.0)


class TestChannelDelaySign:
    """BUG-06: explicit sign convention — ch0 leading ch1 returns +ms."""

    @staticmethod
    def _pulse_buf(n: int, shift: int, fs_low: float = 500.0) -> np.ndarray:
        pulse = (np.arange(128) % 37 == 7).astype(np.float32)
        buf = np.zeros((n, 2), dtype=np.float32)
        if shift >= 0:  # ch0 leads by `shift` samples
            buf[:, 0] = np.tile(pulse, n // len(pulse) + 1)[:n]
            buf[shift:, 1] = buf[: n - shift, 0]
        else:  # ch1 leads
            d = -shift
            buf[:, 1] = np.tile(pulse, n // len(pulse) + 1)[:n]
            buf[d:, 0] = buf[: n - d, 1]
        return buf

    def test_left_leads_positive(self) -> None:
        delay = compute_channel_delay_ms(
            self._pulse_buf(256, shift=4), max_lag_ms=8.0, fs_low=500.0
        )
        assert delay > 0, f"expected positive (Left leads Right), got {delay}"
        assert np.isclose(delay, 4 / 500 * 1000, atol=2.5)

    def test_right_leads_negative(self) -> None:
        delay = compute_channel_delay_ms(
            self._pulse_buf(256, shift=-3), max_lag_ms=8.0, fs_low=500.0
        )
        assert delay < 0, f"expected negative (Right leads Left), got {delay}"
        assert np.isclose(delay, -3 / 500 * 1000, atol=2.5)
