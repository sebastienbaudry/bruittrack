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

import warnings

import numpy as np

try:  # optional fast path — see docs/decision-log.md
    from scipy.signal import sosfilt

    _HAS_SCIPY = True
except Exception:  # pragma: no cover - environment dependent
    _HAS_SCIPY = False


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
        if not _HAS_SCIPY:
            warnings.warn(
                "scipy indisponible : filtre SOS en fallback pure-Python "
                "(plus lent que scipy.signal.sosfilt) — installer scipy pour la voie rapide.",
                RuntimeWarning,
                stacklevel=2,
            )
        self.sos = np.asarray(sos, dtype=np.float64)
        self.n_sections = self.sos.shape[0]
        self.n_channels = n_channels
        # State zi shape: (n_sections, 2, n_channels)
        self.zi = np.zeros((self.n_sections, 2, self.n_channels), dtype=np.float64)

    def reset(self) -> None:
        """Reset filter internal state."""
        self.zi.fill(0.0)

    def filter(self, x: np.ndarray) -> np.ndarray:
        """Filter input array of shape (N, n_channels).

        Uses Direct Form II Transposed for numerical stability.

        Per-channel pure-Python scalar loops are measurably faster than
        per-sample tiny-ndarray operations (see decision-log entry).
        """
        n_samples, n_ch = x.shape
        if n_ch != self.n_channels:
            raise ValueError(f"Expected {self.n_channels} channels, got {n_ch}")

        if _HAS_SCIPY:
            src = np.ascontiguousarray(x, dtype=np.float64)
            y_out = np.empty((n_samples, n_ch), dtype=np.float64)
            for ch in range(n_ch):
                y, zf = sosfilt(self.sos, src[:, ch], zi=self.zi[:, :, ch].copy())
                y_out[:, ch] = y
                self.zi[:, :, ch] = zf
            return y_out

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
        freq_max: float = 150.0,
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
        self.hann_window = 0.5 * (
            1.0 - np.cos(2.0 * np.pi * np.arange(self.n_seg) / (self.n_seg - 1))
        )
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


class SpectrumAggregator:
    """Agrège le PSD lissé par bandes log-spacées pour l'historique « spectrum ».

    Un signal quasi permanent est absorbé par le plancher (médiane glissante)
    et ne génère donc jamais d'événement ; cet agrégateur capture le PSD brut
    lissé pour visualisation (heatmap), indépendamment de la détection.

    Bandes : ``n_bands`` intervalles log-spacés sur [min_hz, max_hz] (bords
    e_i = min_hz * (max_hz/min_hz)^(i/n_bands)). Chaque bin FFT est affecté à
    une seule bande (affectation par bords) ; les bandes sans bin (possibles
    en bas de bande quand la largeur log < résolution bin) restent au niveau
    de quantification 0.

    Niveau par bande : énergie agrégée 10·log10(Σ 10^(dB/10)) sur les bins de
    la bande. Accumulation min/max par bande et par canal sur toute la
    fenêtre ``interval_s``, puis quantification uint8 :
    q = clip(round((db - db_min)/db_range * 255), 0, 255).

    Format BLOB produit : n_bands × [min_g, max_g, min_d, max_d] uint8
    (4 octets/bande, little-endian natif numpy).
    """

    def __init__(
        self,
        freqs_hz: np.ndarray,
        n_bands: int = 24,
        min_hz: float = 2.0,
        max_hz: float = 150.0,
        db_min: float = -140.0,
        db_range: float = 160.0,
        interval_s: float = 60.0,
    ) -> None:
        if n_bands < 1:
            raise ValueError(f"n_bands must be >= 1 (got {n_bands})")
        if not 0.0 < min_hz < max_hz:
            raise ValueError(f"band range must be 0 < min_hz < max_hz (got {min_hz}, {max_hz})")
        if db_range <= 0:
            raise ValueError(f"db_range must be > 0 (got {db_range})")
        if interval_s <= 0:
            raise ValueError(f"interval_s must be > 0 (got {interval_s})")

        self.n_bands = n_bands
        self.min_hz = float(min_hz)
        self.max_hz = float(max_hz)
        self.db_min = float(db_min)
        self.db_range = float(db_range)
        self.interval_s = float(interval_s)

        freqs = np.asarray(freqs_hz, dtype=np.float64)
        edges = self.band_edges()
        # Affectation statique de chaque bin à sa bande (bords supérieurs inclus)
        band_of_bin = np.clip(np.searchsorted(edges, freqs, side="right") - 1, 0, n_bands - 1)
        in_range = (freqs >= edges[0]) & (freqs <= edges[-1])
        sorted_band = np.where(
            in_range, band_of_bin, n_bands
        )  # hors plage -> bande n_bands (ignorée)
        self._perm = np.argsort(sorted_band, kind="stable")
        sorted_bands = sorted_band[self._perm]
        unique_bands, starts = np.unique(sorted_bands, return_index=True)
        keep = unique_bands < n_bands
        # Bandes présentes et découpage contigu après tri (pour np.add.reduceat)
        self._present_bands = unique_bands[keep]
        starts_kept = starts[keep].astype(np.intp)
        self._starts = starts_kept
        n_kept = int((sorted_bands < n_bands).sum())
        self._counts = (
            np.diff(np.append(starts_kept, n_kept))
            if len(starts_kept)
            else np.zeros(0, dtype=np.intp)
        )
        self._n_kept = n_kept

        self._reset_window(0.0)
        self._started = False

    def band_edges(self) -> np.ndarray:
        """Bords des n_bands+1 bandes log-spacées [min_hz .. max_hz]."""
        ratio = self.max_hz / self.min_hz
        return self.min_hz * ratio ** (np.arange(self.n_bands + 1) / self.n_bands)

    def _reset_window(self, t0: float) -> None:
        self._win_t0 = t0
        self._min_g = np.full(self.n_bands, np.inf)
        self._max_g = np.full(self.n_bands, -np.inf)
        self._min_d = np.full(self.n_bands, np.inf)
        self._max_d = np.full(self.n_bands, -np.inf)

    def _band_energy_db(self, psd_db: np.ndarray) -> np.ndarray:
        """Énergie agrégée par bande (dB) ; bandes vides = -inf."""
        out = np.full(self.n_bands, -np.inf)
        if len(self._starts) == 0:
            return out
        p = np.power(10.0, psd_db[self._perm[: self._n_kept]] / 10.0)
        sums = np.add.reduceat(p, self._starts)
        out[self._present_bands] = 10.0 * np.log10(sums + 1e-12)
        return out

    @staticmethod
    def _aminmax(acc_min: np.ndarray, acc_max: np.ndarray, vals: np.ndarray) -> None:
        """Accumule min/max en ignorant les -inf (bandes vides)."""
        valid = vals > -np.inf
        np.minimum(acc_min, vals, out=acc_min, where=valid)
        np.maximum(acc_max, vals, out=acc_max, where=valid)

    def _quantize(self, arr: np.ndarray) -> np.ndarray:
        q = np.round((arr - self.db_min) / self.db_range * 255.0)
        return np.clip(q, 0, 255).astype(np.uint8)

    def update(
        self, t_wall: float, psd1_db: np.ndarray, psd2_db: np.ndarray
    ) -> tuple[float, float, bytes] | None:
        """Ajoute un tick ; retourne (t0, dur, blob) quand la fenêtre se referme.

        t_wall : horodatage mur du tick (time.time(), cohérent DB).
        """
        if not self._started:
            self._win_t0 = t_wall
            self._started = True
        bg = self._band_energy_db(psd1_db)
        bd = self._band_energy_db(psd2_db)
        self._aminmax(self._min_g, self._max_g, bg)
        self._aminmax(self._min_d, self._max_d, bd)

        if t_wall - self._win_t0 < self.interval_s:
            return None
        t0, dur = self._win_t0, t_wall - self._win_t0
        # Quantifier AVANT le reset : les accumulateurs sont remis à ±inf sinon
        blob = np.empty((self.n_bands, 4), dtype=np.uint8)
        blob[:, 0] = self._quantize(self._min_g)
        blob[:, 1] = self._quantize(self._max_g)
        blob[:, 2] = self._quantize(self._min_d)
        blob[:, 3] = self._quantize(self._max_d)
        self._reset_window(t_wall)
        return t0, dur, blob.tobytes()


class FloorTracker:
    """Tracks dynamic noise floor per frequency bin using a rolling median."""

    def __init__(self, n_bins: int = 99, history_len: int = 300, warmup_ticks: int = 300) -> None:
        self.n_bins = n_bins
        self.history_len = history_len
        self.warmup_ticks = warmup_ticks

        # Transposed layouts (bins x time) so the per-row median selection runs
        # over contiguous memory (much faster than axis=0 partition on weak CPU).
        self.history1 = np.zeros((n_bins, history_len), dtype=np.float32)
        self.history2 = np.zeros((n_bins, history_len), dtype=np.float32)
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
            self.history1[:, :] = psd_smooth1[:, None]
            self.history2[:, :] = psd_smooth2[:, None]
        else:
            self.history1[:, self.write_pos] = psd_smooth1
            self.history2[:, self.write_pos] = psd_smooth2

        self.write_pos = (self.write_pos + 1) % self.history_len
        self.tick_count += 1

    @property
    def is_warmed_up(self) -> bool:
        """Check if warmup period has elapsed."""
        return self.tick_count >= self.warmup_ticks

    @staticmethod
    def _median_last(w: np.ndarray) -> np.ndarray:
        """Median along the time (last) axis via O(n) selection.

        For an even number of columns this returns the lower median, a valid
        sample-median that keeps a single O(n) C call per bin row (~3x faster
        than ``numpy.median`` on weak x86 hardware).
        """
        k = (w.shape[1] - 1) // 2
        return np.partition(w, k, axis=1)[:, k].astype(np.float32)

    def get_floor(self) -> tuple[np.ndarray, np.ndarray]:
        """Compute current noise floor (median over history).

        Returns:
            (floor_ch1, floor_ch2) in dB.
        """
        valid_len = min(self.tick_count, self.history_len)
        if valid_len <= 1:
            return self.history1[:, 0].copy(), self.history2[:, 0].copy()

        # Median along time axis (fast per-row selection; lower median if even L)
        f1 = self._median_last(self.history1[:, :valid_len])
        f2 = self._median_last(self.history2[:, :valid_len])
        return f1, f2

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
    max_lag_samples = round(max_lag_ms * fs_low / 1000.0)
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
