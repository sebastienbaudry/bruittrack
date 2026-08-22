"""Audio capture module for BruitTrack.

Encapsulates all interaction with sounddevice and PortAudio/ALSA.
Provides AudioCapture for live capture and MockAudioCapture for testing/simulation.
"""

from __future__ import annotations

import queue
import time
from typing import Any

import numpy as np


def list_audio_devices() -> list[dict[str, Any]]:
    """List all available PortAudio/ALSA audio input devices."""
    try:
        import sounddevice as sd  # type: ignore[import-untyped]
    except ImportError as e:
        raise RuntimeError("sounddevice is not installed. Run `pip install sounddevice`.") from e

    devices = sd.query_devices()
    input_devices = []
    default_input = sd.default.device[0]

    for idx, dev in enumerate(devices):
        if dev.get("max_input_channels", 0) > 0:
            input_devices.append(
                {
                    "id": idx,
                    "name": dev.get("name", "Unknown"),
                    "hostapi": dev.get("hostapi", 0),
                    "max_input_channels": dev.get("max_input_channels", 0),
                    "default_samplerate": dev.get("default_samplerate", 48000.0),
                    "is_default": (idx == default_input),
                }
            )
    return input_devices


class AudioCapture:
    """Live audio stream capture using sounddevice."""

    def __init__(
        self,
        device: str | int | None = None,
        sample_rate: int = 48000,
        channels: int = 2,
        block_size: int = 4800,
    ) -> None:
        self.device = device
        self.sample_rate = sample_rate
        self.channels = channels
        self.block_size = block_size

        self._queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=100)
        self._stream: Any = None
        self._is_running = False

    def _audio_callback(self, indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        """PortAudio thread callback."""
        if self._is_running:
            try:
                self._queue.put_nowait(indata.copy())
            except queue.Full:
                # Queue full under severe CPU starvation: drop oldest to prevent lag
                try:
                    self._queue.get_nowait()
                    self._queue.put_nowait(indata.copy())
                except queue.Empty:
                    pass

    def start(self) -> None:
        """Start the audio input stream."""
        if self._is_running:
            return

        try:
            import sounddevice as sd
        except ImportError as e:
            raise RuntimeError(
                "sounddevice is required for audio capture. Run `pip install sounddevice`."
            ) from e

        self._is_running = True
        self._stream = sd.InputStream(
            device=self.device,
            channels=self.channels,
            samplerate=self.sample_rate,
            blocksize=self.block_size,
            dtype="float32",
            latency="high",
            callback=self._audio_callback,
        )
        self._stream.start()

    def stop(self) -> None:
        """Stop the audio input stream."""
        self._is_running = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def get_block(self, timeout: float = 0.5) -> np.ndarray | None:
        """Fetch next captured audio block. Returns None if timed out."""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def is_active(self) -> bool:
        """Check if stream is actively capturing."""
        return self._is_running and self._stream is not None and self._stream.active


class MockAudioCapture:
    """Synthetic audio stream generator for tests and simulation without hardware."""

    def __init__(
        self,
        sample_rate: int = 48000,
        channels: int = 2,
        block_size: int = 4800,
        frequency_hz: float = 23.5,
        noise_level: float = 0.01,
        seed: int | None = 42,
    ) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self.block_size = block_size
        self.frequency_hz = frequency_hz
        self.noise_level = noise_level

        self._is_running = False
        self._sample_idx = 0
        self._last_time = time.monotonic()
        rng_kwargs: dict[str, Any] = {}
        if seed is not None:
            rng_kwargs["seed"] = seed
        self._rng = np.random.default_rng(**rng_kwargs)

    def start(self) -> None:
        self._is_running = True
        self._sample_idx = 0
        self._last_time = time.monotonic()

    def stop(self) -> None:
        self._is_running = False

    def get_block(self, timeout: float = 0.5) -> np.ndarray | None:
        if not self._is_running:
            return None

        # Simulate block timing (100 ms)
        t = np.arange(self._sample_idx, self._sample_idx + self.block_size) / self.sample_rate
        self._sample_idx += self.block_size

        # Synthetic signal: 23.5 Hz tone + Gaussian noise (deterministic if seed given)
        tone = 0.1 * np.sin(2.0 * np.pi * self.frequency_hz * t)
        noise = self._rng.normal(0, self.noise_level, (self.block_size, self.channels)).astype(
            np.float32
        )

        block = np.zeros((self.block_size, self.channels), dtype=np.float32)
        block[:, 0] = tone + noise[:, 0]
        block[:, 1] = tone + noise[:, 1]

        # Real-time pacing: align to monotonic clock so the mock runs at 1× speed
        expected_next = self._last_time + self.block_size / self.sample_rate
        lag = expected_next - time.monotonic()
        if lag > 0:
            time.sleep(lag)
        self._last_time = max(self._last_time + self.block_size / self.sample_rate, time.monotonic())

        return block

    def is_active(self) -> bool:
        return self._is_running
