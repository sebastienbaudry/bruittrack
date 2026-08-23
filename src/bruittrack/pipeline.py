"""Pipeline orchestration engine for BruitTrack.

Connects AudioCapture -> DspPipeline -> FloorTracker -> EventDetector -> EventStore.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

import numpy as np

from bruittrack.capture import SLOW_BLOCK_STREAK, AudioCapture, MockAudioCapture
from bruittrack.config import Config
from bruittrack.dsp import DspPipeline, FloorTracker, compute_channel_delay_ms
from bruittrack.events import EventDetector, SoundEvent
from bruittrack.store import EventStore

logger = logging.getLogger("bruittrack.pipeline")


class Engine:
    """Core BruitTrack capture and analysis engine."""

    def __init__(
        self,
        config: Config,
        capture: AudioCapture | MockAudioCapture | None = None,
        store: EventStore | None = None,
    ) -> None:
        self.config = config

        # Audio capture
        if capture is not None:
            self.capture = capture
        else:
            self.capture = AudioCapture(
                device=config.audio.device,
                sample_rate=config.audio.sample_rate,
                channels=config.audio.channels,
                block_size=config.audio.block_size,
            )

        # DSP Pipeline
        self.dsp = DspPipeline(
            sample_rate=config.audio.sample_rate,
            decimation=config.audio.decimation,
            n_seg=config.dsp.n_seg,
            noverlap=config.dsp.noverlap,
            n_buffer=config.dsp.n_buffer,
            freq_max=config.dsp.freq_max,
            ema_alpha=config.dsp.ema_alpha,
            lp_cutoff_hz=config.dsp.lp_cutoff_hz,
        )

        # Floor tracker
        self.floor_tracker = FloorTracker(
            n_bins=self.dsp.n_bins,
            history_len=config.dsp.floor_history_len,
            warmup_ticks=config.detector.warmup_ticks,
        )

        # Event detector
        self.detector = EventDetector(
            threshold_db=config.detector.threshold_db,
            hysteresis_db=config.detector.hysteresis_db,
            debounce_ticks=config.detector.debounce_ticks,
            max_duration_s=config.detector.max_duration_s,
            bin_resolution_hz=self.dsp.bin_resolution,
            tick_interval_s=config.audio.block_size / config.audio.sample_rate,
            exemplars_dir=config.storage.exemplars_dir,
            min_event_hz=config.dsp.min_event_hz,
            max_event_hz=config.dsp.freq_max,
        )

        # Storage
        if store is not None:
            self.store = store
        else:
            self.store = EventStore(
                db_path=config.storage.db_path,
                batch_size=config.storage.batch_size,
                batch_timeout_s=config.storage.batch_timeout_s,
            )

        # Load existing clusters into detector index
        self._load_cluster_index()

        # Retention: apply once at start, then daily during runtime
        self._last_retention_check = time.time()
        self._retention_interval_s = 86400.0
        if config.storage.retention_days is not None:
            self.store.apply_retention(config.storage.retention_days)

        self._is_running = False
        self._tick_count = 0

    def _load_cluster_index(self) -> None:
        """Reconstruct cluster index from SQLite at startup."""
        fps = self.store.load_all_cluster_fingerprints()
        for cluster_id, fp in fps.items():
            self.detector.cluster_index.add_existing(cluster_id, fp)
        logger.info(f"Rebuilt ClusterIndex with {len(fps)} known clusters.")

    def step(
        self, raw_block: np.ndarray | None = None
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[SoundEvent]]:
        """Process a single 100 ms audio block.

        Returns:
            (psd_smooth1, psd_smooth2, emergence1, emergence2, events_emitted)
        """
        if raw_block is None:
            raw_block = self.capture.get_block(timeout=1.0)
            if raw_block is None:
                zeros = np.zeros(self.dsp.n_bins, dtype=np.float32)
                return zeros, zeros, zeros, zeros, []
            self._check_capture_health()

        # 1. Process DSP
        psd1, psd2 = self.dsp.process_block(raw_block)

        # 2. Update floor tracker
        self.floor_tracker.update(psd1, psd2)
        em1, em2, _, _ = self.floor_tracker.compute_emergence(psd1, psd2)

        events: list[SoundEvent] = []
        # 3. Detect events once warmed up
        if self.floor_tracker.is_warmed_up:
            off_ms = compute_channel_delay_ms(self.dsp.audio_buffer_low, fs_low=self.dsp.fs_low)
            events = self.detector.update(
                emergence1=em1,
                emergence2=em2,
                audio_buffer_low=self.dsp.audio_buffer_low,
                off_ms=off_ms,
            )
            for ev in events:
                self.store.add_event(ev)

        # Periodic retention check (daily)
        now_wall = time.time()
        if (
            self.config.storage.retention_days is not None
            and now_wall - self._last_retention_check >= self._retention_interval_s
        ):
            self.store.apply_retention(self.config.storage.retention_days)
            self._last_retention_check = now_wall

        self.store.maybe_flush()
        self._tick_count += 1
        return psd1, psd2, em1, em2, events

    def _check_capture_health(self) -> None:
        """Warn sur SLOW_BLOCK_STREAK blocs de capture lents consecutifs."""
        if getattr(self.capture, "consecutive_slow", 0) >= SLOW_BLOCK_STREAK:
            streak = self.capture.consecutive_slow
            self.capture.consecutive_slow = 0  # evite les warnings dupliques par bloc
            logger.warning(
                "capture lente : %d blocs consecutifs > %.0f ms (dernier : %.1f ms)",
                streak,
                self.capture.slow_read_us / 1000.0,
                self.capture.last_read_us / 1000.0,
            )

    def start(self, on_tick: Callable[[dict[str, Any]], None] | None = None) -> None:
        """Start the live capture loop."""
        self._is_running = True
        self.capture.start()
        logger.info("BruitTrack capture engine started.")

        try:
            while self._is_running:
                raw_block = self.capture.get_block(timeout=0.5)
                if raw_block is None:
                    continue

                psd1, psd2, em1, em2, events = self.step(raw_block)

                if on_tick is not None:
                    on_tick(
                        {
                            "tick": self._tick_count,
                            "warmed_up": self.floor_tracker.is_warmed_up,
                            "psd1": psd1,
                            "psd2": psd2,
                            "em1": em1,
                            "em2": em2,
                            "events": events,
                        }
                    )
        finally:
            self.stop()

    def stop(self) -> None:
        """Stop capture and flush storage."""
        self._is_running = False
        self.capture.stop()
        self.store.close()
        logger.info("BruitTrack capture engine stopped and flushed.")
