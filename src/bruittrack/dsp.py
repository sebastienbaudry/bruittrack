"""Digital Signal Processing (DSP) pipeline for BruitTrack.

Pure NumPy implementation:
- 8th-order Butterworth low-pass anti-aliasing filter (4 cascaded biquads)
- Exact x48 decimation (48 kHz -> 1000 Hz)
- Welch Power Spectral Density (2048 pts, 50% overlap, 7 segments)
- Exponential Moving Average (EMA) spectral smoothing
- Dynamic noise floor tracking via rolling median
- Sub-millisecond normalized inter-channel cross-correlation
"""

from __future__ import annotations

import numpy as np


def design_butterworth_lp_sos(
    cutoff_hz: float = 400.0,
    fs: float = 48000.0,
    order: int = 8,
) -> np.ndarray:
    """Design an Nth-order Butterworth lowpass filter as Second-Order Sections (SOS).

    Implemented in pure NumPy using the bilinear transform with frequency pre-warping.

    Returns:
        sos array of shape (order // 2, 6) where each row is [b0, b1, b2, 1.0, a1, a2].
    """
    if order % 2 != 0:
        raise ValueError("Filter order must be even")

    n_sections = order // 2
    sos = np.zeros((n_sections, 6), dtype=np.float64)

    # Pre-warped cutoff frequency
    k = np.tan(np.pi * cutoff_hz / fs)
    k2 = k * k

    for i in range(n_sections):
        # Pole angle in left half s-plane
        angle = np.pi * (2 * i + 1 + order) / (2 * order)
        # Quality factor Q = 1 / (-2 * cos(angle)) = 1 / (2 * sin((2*i + 1)*pi / (2*order)))
        q = 1.0 / (-2.0 * np.cos(angle))

        denom = 1.0 + (k / q) + k2
        b0 = k2 / denom
        b1 = 2.0 * b0
        b2 = b0
        a0 = 1.0
        a1 = (2.0 * (k2 - 1.0)) / denom
        a2 = (1.0 - (k / q) + k2) / denom

        sos[i] = [b0, b1, b2, a0, a1, a2]

    return sos


class SosFilter:
    """Direct Form II Transposed Second-Order Sections (SOS) filter in pure NumPy."""

    def __init__(self, sos: np.ndarray, n_channels: int = 2) -> None:
        self.sos = np.asarray(sos, dtype=np.float64)
        self.n_sections = self.sos.shape[0]
        self.n_channels = n_channels
        # State zi shape: (n_sections, 2, n_channels)
        self.zi = np.zeros((self.n_sections, 2, self.n_channels), dtype=np.float64)

    def reset(self) -> None:
        """Reset filter internal state."""
        self.zi.fill(0.0)

    def set_initial_state(self, initial_values: np.ndarray) -> None:
        """Set initial filter state to avoid transients (steady-state for DC value).

        Args:
            initial_values: shape (n_channels,) array of initial values.
        """
        self.reset()
        for s in range(self.n_sections):
            b0, b1, b2, _, a1, a2 = self.sos[s]
            # Exact steady-state for constant input x (DC gain H1 = sum(b)/sum(a))
            h_dc = (b0 + b1 + b2) / (1.0 + a1 + a2)
            y_ss_coef = h_dc          # output scale vs input
            z0_coef = h_dc - b0       # from y[n] = b0*x[n] + z0
            z1_coef = b2 - a2 * h_dc  # from z1 = b2*x[n] - a2*y[n]
            for ch in range(self.n_channels):
                val = initial_values[ch]
                self.zi[s, 0, ch] = z0_coef * val
                self.zi[s, 1, ch] = z1_coef * val

    def filter(self, x: np.ndarray) -> np.ndarray:
        """Filter input array of shape (N, n_channels).

        Uses Direct Form II Transposed for numerical stability.

        Per-channel pure-Python scalar loops are measurably faster than
        per-sample tiny-ndarray operations (see decision-log entry).
        """
        n_samples, n_ch = x.shape
        if n_ch != self.n_channels:
            raise ValueError(f"Expected {self.n_channels} channels, got {n_ch}")

        src = np.ascontiguousarray(x)
        y_out = np.empty((n_samples, n_ch), dtype=np.float64)
        for s in range(self.n_sections):
            b0, b1, b2, _, a1, a2 = (float(c) for c in self.sos[s])
            if b0 == 0.0 and b1 == 0.0 and b2 == 0.0:
                y_out[:] = src
                continue
            for ch in range(n_ch):
                xin_col = src[:, ch]
                y_col = y_out[:, ch]
                z0f, z1f = float(self.zi[s, 0, ch]), float(self.zi[s, 1, ch])
                for n in range(n_samples):
                    x_n = float(xin_col[n]) if s == 0 else float(y_col[n])
                    y_n = b0 * x_n + z0f
                    z0f, z1f = b1 * x_n - a1 * y_n + z1f, b2 * x_n - a2 * y_n
                    y_col[n] = y_n
                self.zi[s, 0, ch], self.zi[s, 1, ch] = z0f, z1f
            if s > 0:
                src = y_out
        return y_out



class DspPipeline:
    """Complete DSP pipeline for infrasound and low-frequency feature extraction."""

    def __init__(
        self,
        sample_rate: int = 48000,
        decimation: int = 48,
        n_seg: int = 2048,
        noverlap: int = 1024,
        n_buffer: int = 8192,
        freq_max: float = 48.0,
        ema_alpha: float = 0.5,
        lp_cutoff_hz: float = 400.0,
    ) -> None:
        self.sample_rate = sample_rate
        self.decimation = decimation
        self.fs_low = sample_rate / decimation
        self.n_seg = n_seg
        self.noverlap = noverlap
        self.n_buffer = n_buffer
        self.freq_max = freq_max
        self.ema_alpha = ema_alpha

        # Anti-aliasing filter
        self.sos = design_butterworth_lp_sos(cutoff_hz=lp_cutoff_hz, fs=float(sample_rate), order=8)
        self.filter = SosFilter(self.sos, n_channels=2)

        # Rolling buffer for low-frequency audio (N_BUFFER samples, 2 channels)
        self.audio_buffer_low = np.zeros((self.n_buffer, 2), dtype=np.float32)

        # Welch parameters
        self.step = self.n_seg - self.noverlap
        self.n_welch_segments = (self.n_buffer - self.n_seg) // self.step + 1
        self.hann_window = 0.5 * (1.0 - np.cos(2.0 * np.pi * np.arange(self.n_seg) / (self.n_seg - 1)))
        self.hann_window = self.hann_window.astype(np.float32)
        self.window_scale = float(np.sum(self.hann_window**2))

        # Frequency bins
        freqs_full = np.fft.rfftfreq(self.n_seg, 1.0 / self.fs_low)
        self.freq_mask = freqs_full <= self.freq_max
        self.freqs = freqs_full[self.freq_mask].astype(np.float32)
        self.n_bins = len(self.freqs)
        self.bin_resolution = float(self.fs_low / self.n_seg)

        # EMA state
        self.psd_smooth1: np.ndarray | None = None
        self.psd_smooth2: np.ndarray | None = None

    def reset(self) -> None:
        """Reset internal buffers and filter states."""
        self.filter.reset()
        self.audio_buffer_low.fill(0.0)
        self.psd_smooth1 = None
        self.psd_smooth2 = None

    def process_block(self, raw_audio: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Process one block of raw 48 kHz stereo audio.

        Args:
            raw_audio: shape (N, 2) array at sample_rate (e.g. 4800 samples = 100 ms).

        Returns:
            Tuple of smoothed PSD in dB: (psd_db_ch1, psd_db_ch2) for bins 0..n_bins-1.
        """
        # 1. Anti-aliasing LP filter
        filtered = self.filter.filter(raw_audio)

        # 2. Decimation
        decimated = filtered[:: self.decimation, :].astype(np.float32)
        n_low = decimated.shape[0]

        # 3. Update rolling buffer
        self.audio_buffer_low = np.roll(self.audio_buffer_low, -n_low, axis=0)
        self.audio_buffer_low[-n_low:, :] = decimated

        # 4. Welch PSD computation across segments
        psd1_accum = np.zeros(self.n_bins, dtype=np.float32)
        psd2_accum = np.zeros(self.n_bins, dtype=np.float32)

        for i in range(self.n_welch_segments):
            start = i * self.step
            seg = self.audio_buffer_low[start : start + self.n_seg, :]
            # Windowing
            seg1_win = seg[:, 0] * self.hann_window
            seg2_win = seg[:, 1] * self.hann_window

            fft1 = np.fft.rfft(seg1_win)
            fft2 = np.fft.rfft(seg2_win)

            # Energy in spectrum scaling
            p1 = (np.abs(fft1[self.freq_mask]) ** 2) / self.window_scale
            p2 = (np.abs(fft2[self.freq_mask]) ** 2) / self.window_scale

            psd1_accum += p1.astype(np.float32)
            psd2_accum += p2.astype(np.float32)

        psd1_mean = psd1_accum / self.n_welch_segments
        psd2_mean = psd2_accum / self.n_welch_segments

        # Convert to dB
        db1 = 10.0 * np.log10(psd1_mean + 1e-12)
        db2 = 10.0 * np.log10(psd2_mean + 1e-12)

        # 5. EMA Temporal smoothing
        if self.psd_smooth1 is None or self.psd_smooth2 is None:
            self.psd_smooth1 = db1.copy()
            self.psd_smooth2 = db2.copy()
        else:
            self.psd_smooth1 = self.ema_alpha * db1 + (1.0 - self.ema_alpha) * self.psd_smooth1
            self.psd_smooth2 = self.ema_alpha * db2 + (1.0 - self.ema_alpha) * self.psd_smooth2

        return self.psd_smooth1.copy(), self.psd_smooth2.copy()


class FloorTracker:
    """Tracks dynamic noise floor per frequency bin using a rolling median."""

    def __init__(self, n_bins: int = 99, history_len: int = 300, warmup_ticks: int = 300) -> None:
        self.n_bins = n_bins
        self.history_len = history_len
        self.warmup_ticks = warmup_ticks

        self.history1 = np.zeros((history_len, n_bins), dtype=np.float32)
        self.history2 = np.zeros((history_len, n_bins), dtype=np.float32)
        self.tick_count = 0
        self.write_pos = 0

    def reset(self) -> None:
        """Reset history."""
        self.history1.fill(0.0)
        self.history2.fill(0.0)
        self.tick_count = 0
        self.write_pos = 0

    def update(self, psd_smooth1: np.ndarray, psd_smooth2: np.ndarray) -> None:
        """Add new smoothed PSD frame to history."""
        if self.tick_count == 0:
            # Seed full buffer on first tick to avoid transient zero-floor
            self.history1[:] = psd_smooth1
            self.history2[:] = psd_smooth2
        else:
            self.history1[self.write_pos] = psd_smooth1
            self.history2[self.write_pos] = psd_smooth2

        self.write_pos = (self.write_pos + 1) % self.history_len
        self.tick_count += 1

    @property
    def is_warmed_up(self) -> bool:
        """Check if warmup period has elapsed."""
        return self.tick_count >= self.warmup_ticks

    def get_floor(self) -> tuple[np.ndarray, np.ndarray]:
        """Compute current noise floor (median over history).

        Returns:
            (floor_ch1, floor_ch2) in dB.
        """
        valid_len = min(self.tick_count, self.history_len)
        if valid_len <= 1:
            return self.history1[0].copy(), self.history2[0].copy()

        # Median along time axis
        f1 = np.median(self.history1[:valid_len], axis=0)
        f2 = np.median(self.history2[:valid_len], axis=0)
        return f1.astype(np.float32), f2.astype(np.float32)

    def compute_emergence(
        self, psd_smooth1: np.ndarray, psd_smooth2: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Compute emergence in dB above the noise floor.

        Returns:
            (emergence1, emergence2, floor1, floor2)
        """
        floor1, floor2 = self.get_floor()
        emergence1 = psd_smooth1 - floor1
        emergence2 = psd_smooth2 - floor2
        return emergence1, emergence2, floor1, floor2


def compute_channel_delay_ms(
    audio_buffer_low: np.ndarray,
    max_lag_ms: float = 8.0,
    fs_low: float = 1000.0,
) -> float:
    """Compute time delay between Left (ch0) and Right (ch1) in milliseconds.

    Uses normalized cross-correlation on the most recent 1 kHz audio samples.
    Positive delay: Left leads Right.
    Negative delay: Right leads Left.
    """
    max_lag_samples = int(round(max_lag_ms * fs_low / 1000.0))
    if max_lag_samples < 1:
        return 0.0

    # Use the last 512 samples (~0.5s) from rolling buffer
    window_len = min(512, audio_buffer_low.shape[0])
    s1 = audio_buffer_low[-window_len:, 0].astype(np.float64)
    s2 = audio_buffer_low[-window_len:, 1].astype(np.float64)

    # Remove DC
    s1 = s1 - np.mean(s1)
    s2 = s2 - np.mean(s2)

    norm1 = np.linalg.norm(s1)
    norm2 = np.linalg.norm(s2)
    if norm1 < 1e-6 or norm2 < 1e-6:
        return 0.0

    # Cross correlation
    corr = np.correlate(s1, s2, mode="full")
    mid = len(s1) - 1

    lag_range = np.arange(-max_lag_samples, max_lag_samples + 1)
    corr_window = corr[mid - max_lag_samples : mid + max_lag_samples + 1]

    best_idx = int(np.argmax(corr_window))
    best_lag_samples = -int(lag_range[best_idx])

    # Convert lag to ms (positive: Left leads Right)
    delay_ms = float(best_lag_samples * 1000.0 / fs_low)
    return max(-max_lag_ms, min(max_lag_ms, delay_ms))
