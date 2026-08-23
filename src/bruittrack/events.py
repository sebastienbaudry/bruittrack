"""Event detection, acoustic fingerprinting, and clustering for BruitTrack.

Fingerprint layout (16 bytes):
- Byte 0: Version (uint8 = 1)
- Bytes 1-2: Peak frequency bin index (uint16 BE)
- Bytes 3-7: Quantized neighbor bins (5 x uint8, relative emergence 0..7)
- Byte 8: Dominant channel (0 = Left/Air, 1 = Right/Structure, 2 = Both)
- Byte 9: Delay class (int8, Â±20 ms discretized)
- Bytes 10-15: Reserved (6 x 0x00)
"""

from __future__ import annotations

import struct
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

import numpy as np

from .legal import emergence_limit

# Flags
FLAG_KNOWN = 1 << 0  # bit 0: validÃ© / connu
FLAG_IGNORED = 1 << 1  # bit 1: ignorÃ© (triage)
FLAG_EXEMPLAR = 1 << 2  # bit 2: extrait audio stockÃ©
FLAG_OVER_LEGAL = 1 << 3  # bit 3: exceeds legal emergence (CSP R1336-7)


@dataclass
class SoundEvent:
    """A detected sound event."""

    t0: float  # Unix timestamp of start
    dur: float  # Duration in seconds
    bin_i: int  # Peak bin index (0..98)
    freq: float  # Frequency in Hz
    lvl_g: float  # Emergence Left (dB)
    lvl_d: float  # Emergence Right (dB)
    off_ms: float  # Left/Right delay (ms)
    fp: bytes  # 16-byte acoustic fingerprint
    flags: int = 0  # Bitmask flags
    cluster: int | None = None  # Assigned cluster ID
    id: int | None = None  # DB primary key (when persisted)
    dominant_ch: Literal["L", "R", "B"] = "L"


@dataclass
class DecodedFingerprint:
    """Decoded fields of a 16-byte acoustic fingerprint."""

    version: int
    bin_peak: int
    neighbors: tuple[int, int, int, int, int]
    dominant_ch: int  # 0=L, 1=R, 2=B
    delay_class: int  # int8 (-20..20)


def encode_fingerprint(
    bin_peak: int,
    emergence_spectrum: np.ndarray,
    dominant_ch: int,
    off_ms: float,
    version: int = 1,
) -> bytes:
    """Encode spectral and temporal features into a 16-byte fingerprint.

    Args:
        bin_peak: Index of peak bin (0..98).
        emergence_spectrum: Emergence array (in dB) across bins.
        dominant_ch: 0 (Left), 1 (Right), or 2 (Both).
        off_ms: Channel delay in milliseconds (-8..+8 ms).
        version: Fingerprint format version.

    Returns:
        16-byte binary fingerprint.
    """
    n_bins = len(emergence_spectrum)
    peak_val = max(1e-3, float(emergence_spectrum[bin_peak]))

    # Quantize 5 neighbor bins around peak: [peak-2, peak-1, peak, peak+1, peak+2]
    neighbors = []
    for offset in (-2, -1, 0, 1, 2):
        idx = bin_peak + offset
        if 0 <= idx < n_bins:
            val = max(0.0, float(emergence_spectrum[idx]))
            # Relative quantization on 3 bits (0..7)
            ratio = min(1.0, val / peak_val)
            q = round(ratio * 7.0)
        else:
            q = 0
        neighbors.append(q)

    # Delay class (-20 to +20 ms, clamped)
    delay_class = round(off_ms)
    delay_class = max(-20, min(20, delay_class))

    return struct.pack(
        ">BH5BBb6x",
        version,
        bin_peak,
        neighbors[0],
        neighbors[1],
        neighbors[2],
        neighbors[3],
        neighbors[4],
        dominant_ch,
        delay_class,
    )


def decode_fingerprint(fp: bytes) -> DecodedFingerprint:
    """Decode a 16-byte acoustic fingerprint."""
    if len(fp) != 16:
        raise ValueError(f"Fingerprint must be 16 bytes, got {len(fp)}")

    version, bin_peak, n0, n1, n2, n3, n4, dom_ch, delay_class = struct.unpack(">BH5BBb6x", fp)
    return DecodedFingerprint(
        version=version,
        bin_peak=bin_peak,
        neighbors=(n0, n1, n2, n3, n4),
        dominant_ch=dom_ch,
        delay_class=delay_class,
    )


def fingerprints_match(fp1: bytes, fp2: bytes) -> bool:
    """Check if two fingerprints match according to clustering tolerance rules:

    - |Î”bin_peak| <= 2
    - Î£|Î”neighbors| <= 2
    - |Î”delay_class| <= 2
    - Compatible dominant channel (identical or at least one is 'Both')
    """
    d1 = decode_fingerprint(fp1)
    d2 = decode_fingerprint(fp2)

    # Bin peak distance
    if abs(d1.bin_peak - d2.bin_peak) > 2:
        return False

    # Channel compatibility
    if d1.dominant_ch != d2.dominant_ch and d1.dominant_ch != 2 and d2.dominant_ch != 2:
        return False

    # Delay class distance
    if abs(d1.delay_class - d2.delay_class) > 2:
        return False

    # Manhattan distance on quantized neighbors
    dist_neighbors = sum(abs(a - b) for a, b in zip(d1.neighbors, d2.neighbors))

    return dist_neighbors <= 2


class ClusterIndex:
    """In-memory index of sound clusters for fast matching."""

    def __init__(self) -> None:
        # Map cluster_id -> representative fingerprint
        self.clusters: dict[int, bytes] = {}
        self._next_id = 1

    def add_existing(self, cluster_id: int, fp: bytes) -> None:
        """Register an existing cluster from persistent storage."""
        self.clusters[cluster_id] = fp
        if cluster_id >= self._next_id:
            self._next_id = cluster_id + 1

    def match_or_create(self, fp: bytes) -> tuple[int, bool]:
        """Match fingerprint against existing clusters or create a new one.

        Returns:
            (cluster_id, is_new)
        """
        for c_id, ref_fp in self.clusters.items():
            if fingerprints_match(fp, ref_fp):
                return c_id, False

        # Create new cluster
        new_id = self._next_id
        self._next_id += 1
        self.clusters[new_id] = fp
        return new_id, True


class EventDetector:
    """Real-time sound emergence event detector with hysteresis and debounce."""

    def __init__(
        self,
        threshold_db: float = 10.0,
        hysteresis_db: float = 3.0,
        debounce_ticks: int = 5,
        max_duration_s: float = 30.0,
        bin_resolution_hz: float = 0.48828125,
        tick_interval_s: float = 0.1,
        exemplars_dir: str | Path = "exemplars",
    ) -> None:
        self.threshold_db = threshold_db
        self.release_threshold_db = max(0.0, threshold_db - hysteresis_db)
        self.debounce_ticks = debounce_ticks
        self.max_duration_s = max_duration_s
        self.bin_resolution_hz = bin_resolution_hz
        self.tick_interval_s = tick_interval_s
        self.exemplars_dir = Path(exemplars_dir)

        # Cluster index
        self.cluster_index = ClusterIndex()

        # State tracking
        self.is_active = False
        self.candidate_ticks = 0
        self.active_ticks = 0

        # Event metrics during active detection
        self.t0_unix: float = 0.0
        self.peak_bin: int = 0
        self.peak_lvl_g: float = 0.0
        self.peak_lvl_d: float = 0.0
        self.spectrum_at_peak: np.ndarray | None = None
        self.delay_at_peak: float = 0.0
        self.audio_sample_at_peak: np.ndarray | None = None

    def update(
        self,
        emergence1: np.ndarray,
        emergence2: np.ndarray,
        audio_buffer_low: np.ndarray,
        off_ms: float,
        unix_time: float | None = None,
    ) -> list[SoundEvent]:
        """Update detector with one 100 ms frame.

        Args:
            emergence1: Emergence in dB on Channel 0 (Left).
            emergence2: Emergence in dB on Channel 1 (Right).
            audio_buffer_low: Current rolling 1 kHz audio buffer.
            off_ms: Cross-correlation delay.
            unix_time: Current Unix time (seconds).

        Returns:
            List of completed SoundEvent objects (empty if no event completed this tick).
        """
        now = time.time() if unix_time is None else unix_time
        events_emitted: list[SoundEvent] = []

        # Combined max emergence per bin
        max_emergence = np.maximum(emergence1, emergence2)
        # Le bin 0 (DC) capte les transients de niveau, pas des bruits :
        # on ne le prend jamais comme pic Ã©vÃ©nement.
        search = max_emergence[1:]
        if search.size == 0:
            return events_emitted
        current_peak_bin = int(np.argmax(search)) + 1
        current_max_em = float(max_emergence[current_peak_bin])
        current_em1 = float(emergence1[current_peak_bin])
        current_em2 = float(emergence2[current_peak_bin])

        if not self.is_active:
            # Check if threshold is exceeded
            if current_max_em >= self.threshold_db:
                if self.candidate_ticks == 0:
                    self.t0_unix = now
                    self.peak_bin = current_peak_bin
                    self.peak_lvl_g = current_em1
                    self.peak_lvl_d = current_em2
                    self.spectrum_at_peak = max_emergence.copy()
                    self.delay_at_peak = off_ms
                    self._capture_audio_slice(audio_buffer_low)

                self.candidate_ticks += 1

                # Update peak values during candidate phase
                if current_max_em > max(self.peak_lvl_g, self.peak_lvl_d):
                    self.peak_bin = current_peak_bin
                    self.peak_lvl_g = max(self.peak_lvl_g, current_em1)
                    self.peak_lvl_d = max(self.peak_lvl_d, current_em2)
                    self.spectrum_at_peak = max_emergence.copy()
                    self.delay_at_peak = off_ms
                    self._capture_audio_slice(audio_buffer_low)

                if self.candidate_ticks >= self.debounce_ticks:
                    # Validated event!
                    self.is_active = True
                    self.active_ticks = self.candidate_ticks
            else:
                # Reset candidate if signal drops before debounce
                self.candidate_ticks = 0
        else:
            # Event is active
            self.active_ticks += 1
            duration_s = self.active_ticks * self.tick_interval_s

            # Track peak
            if current_max_em > max(self.peak_lvl_g, self.peak_lvl_d):
                self.peak_bin = current_peak_bin
                self.peak_lvl_g = max(self.peak_lvl_g, current_em1)
                self.peak_lvl_d = max(self.peak_lvl_d, current_em2)
                self.spectrum_at_peak = max_emergence.copy()
                self.delay_at_peak = off_ms
                self._capture_audio_slice(audio_buffer_low)

            # Check termination conditions: hysteresis drop or max duration
            should_close = False
            if current_max_em < self.release_threshold_db or duration_s >= self.max_duration_s:
                should_close = True

            if should_close:
                event = self._build_and_emit_event(duration_s)
                events_emitted.append(event)
                # If closed due to max duration and still above threshold, start next segment immediately
                if duration_s >= self.max_duration_s and current_max_em >= self.threshold_db:
                    self.is_active = True
                    self.candidate_ticks = self.debounce_ticks
                    self.active_ticks = 1
                    self.t0_unix = now
                    self.peak_bin = current_peak_bin
                    self.peak_lvl_g = current_em1
                    self.peak_lvl_d = current_em2
                    self.spectrum_at_peak = max_emergence.copy()
                    self.delay_at_peak = off_ms
                    self._capture_audio_slice(audio_buffer_low)
                else:
                    self.is_active = False
                    self.candidate_ticks = 0
                    self.active_ticks = 0

        return events_emitted

    def _capture_audio_slice(self, audio_buffer_low: np.ndarray) -> None:
        """Capture 256 ms (256 samples @ 1 kHz, 2 ch) around peak."""
        window_size = 256
        if audio_buffer_low.shape[0] >= window_size:
            self.audio_sample_at_peak = audio_buffer_low[-window_size:, :].copy()

    def _compute_flags(self, duration_s: float) -> int:
        """FLAGS_EXEMPLAR si 1e exemplaire; bit3 exceeds legal limit (CSP R1336-7)."""
        # Détection : limites légales évaluées sur l'heure locale de début d'événement.
        # legal limit uses local civil time (intentionally tz-naive)
        t = datetime.fromtimestamp(self.t0_unix)  # noqa: DTZ006
        peak_db = max(self.peak_lvl_g, self.peak_lvl_d)
        limite = emergence_limit(t.hour, t.minute, duration_s)
        # Le bit exemplar est ajouté ensuite si cluster neuf.
        return FLAG_OVER_LEGAL if peak_db > limite else 0

    def _build_and_emit_event(self, duration_s: float) -> SoundEvent:
        """Construct SoundEvent with fingerprint, cluster assignment, and exemplar saving."""
        # Determine dominant channel
        # Check if both channels exceed threshold near peak
        both_active = (self.peak_lvl_g >= self.threshold_db) and (
            self.peak_lvl_d >= self.threshold_db
        )
        if both_active:
            dom_int = 2
            dom_str: Literal["L", "R", "B"] = "B"
        elif self.peak_lvl_g >= self.peak_lvl_d:
            dom_int = 0
            dom_str = "L"
        else:
            dom_int = 1
            dom_str = "R"

        spectrum = (
            self.spectrum_at_peak
            if self.spectrum_at_peak is not None
            else np.zeros(99, dtype=np.float32)
        )

        fp = encode_fingerprint(
            bin_peak=self.peak_bin,
            emergence_spectrum=spectrum,
            dominant_ch=dom_int,
            off_ms=self.delay_at_peak,
        )

        cluster_id, is_new_cluster = self.cluster_index.match_or_create(fp)
        flags = self._compute_flags(duration_s)

        # If first exemplar of a cluster, write raw audio exemplar
        if is_new_cluster and self.audio_sample_at_peak is not None:
            flags |= FLAG_EXEMPLAR
            self._save_exemplar(cluster_id, self.audio_sample_at_peak)

        return SoundEvent(
            t0=self.t0_unix,
            dur=round(duration_s, 2),
            bin_i=self.peak_bin,
            freq=round(self.peak_bin * self.bin_resolution_hz, 2),
            lvl_g=round(self.peak_lvl_g, 1),
            lvl_d=round(self.peak_lvl_d, 1),
            off_ms=round(self.delay_at_peak, 2),
            fp=fp,
            flags=flags,
            cluster=cluster_id,
            dominant_ch=dom_str,
        )

    def _save_exemplar(self, cluster_id: int, audio_data: np.ndarray) -> None:
        """Save 256 ms audio slice as float16 raw bytes in exemplars_dir."""
        try:
            self.exemplars_dir.mkdir(parents=True, exist_ok=True)
            filename = self.exemplars_dir / f"ex_{cluster_id}.raw"
            # audio_data shape: (256, 2) in float32 -> convert to float16 (1024 bytes)
            raw_bytes = audio_data.astype(np.float16).tobytes()
            with open(filename, "wb") as f:
                f.write(raw_bytes)
        except Exception:
            # Audio exemplar saving failure should never crash the detector
            pass
