"""Tests for DSP filters, Welch PSD, floor tracking, and cross-correlation."""

import numpy as np
import pytest

import bruittrack.dsp as dsp_mod
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


def test_sos_filter_fastpath_matches_scalar() -> None:
    """Voie rapide scipy et fallback scalaire doivent produire la même sortie."""
    if not dsp_mod._HAS_SCIPY:
        pytest.skip("scipy absent")
    sos = design_butterworth_lp_sos(cutoff_hz=400.0, fs=48000.0, order=8)
    x = np.random.default_rng(0).normal(0, 1e-3, size=(1000, 2))
    fast = SosFilter(sos, n_channels=2)
    slow = SosFilter(sos, n_channels=2)
    old_flag = dsp_mod._HAS_SCIPY
    dsp_mod._HAS_SCIPY = False
    try:
        y_slow = slow.filter(x)
    finally:
        dsp_mod._HAS_SCIPY = old_flag
    y_fast = fast.filter(x)
    assert np.allclose(y_fast, y_slow, atol=1e-9)
    # continuité d'état entre blocs (pas d'impulsion au jointure)
    fast.reset()
    a = fast.filter(x[:500])
    b = fast.filter(x[500:])
    slow2 = SosFilter(sos, n_channels=2)
    ref = slow2.filter(x)
    assert np.allclose(a, ref[:500], atol=1e-9)
    assert np.allclose(b, ref[500:], atol=1e-9)


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
    expected_bin = round(target_freq / dsp.bin_resolution)

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

    em1, em2, _, _ = ft.compute_emergence(psd_spike, psd_spike)
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


def test_sos_filter_benchmark_48k_under_50ms() -> None:
    """48 000 échantillons × 2 ch (1 s audio) doivent passer en < 50 ms.

    Acceptance IMPROVEMENTS.md: SosFilter.filter() vectorisé via scipy
    reste bien au-dessous du budget CPU de l'HP T620 (~1 % / bloc 100 ms).
    """
    if not dsp_mod._HAS_SCIPY:
        pytest.skip("scipy absent → pas de mesure fast-path")
    sos = design_butterworth_lp_sos(cutoff_hz=400.0, fs=48000.0, order=8)
    x = np.random.default_rng(1).normal(0, 1e-3, size=(48_000, 2))
    filt = SosFilter(sos, n_channels=2)
    import time

    t0 = time.perf_counter()
    y = filt.filter(x)
    elapsed = time.perf_counter() - t0
    assert y.shape == (48_000, 2)
    assert elapsed < 0.050, f"SosFilter trop lent: {elapsed*1000:.1f} ms > 50 ms"
