"""Audio capture module for BruitTrack.

Encapsulates all interaction with sounddevice and PortAudio/ALSA.
Provides AudioCapture for live capture and MockAudioCapture for testing/simulation.
"""

from __future__ import annotations

import queue
import time
from typing import Any

import numpy as np

# Un bloc de capture est "lent" si sa lecture dure plus de 15 ms ;
# le pipeline avertit apres SLOW_BLOCK_STREAK blocs lents consecutifs (M6).
SLOW_READ_US = 15_000
SLOW_BLOCK_STREAK = 3


def update_read_metrics(cap: Any, read_us: int) -> None:
    """Metriques de lecture par bloc : dernier temps (µs) + serie de blocs lents."""
    cap.last_read_us = read_us
    if read_us >= cap.slow_read_us:
        cap.consecutive_slow += 1
    else:
        cap.consecutive_slow = 0


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


def resolve_device_input(device_spec: str) -> int | str:
    """Resolves a device specification to a sounddevice-usable identifier.

    Accepts an explicit ALSA path (string containing ':') or integer index,
    returning them as-is. Otherwise, performs exact name match on sd.query_devices(),
    falling back to case-insensitive substring if that fails. Raises ValueError
    if no audio input device is found matching the spec.
    """

    spec = device_spec.strip()

    # Explicit numeric index
    if spec.isdigit():
        return int(spec)

    try:
        import sounddevice as sd  # type: ignore[import-untyped]
    except ModuleNotFoundError:
        # Headless (no PortAudio): only explicit ALSA paths can pass through.
        if ":" in spec:
            return spec
        raise

    devices = sd.query_devices()

    # 1. Exact name match (PortAudio names may contain ':', e.g.
    # "M-Track Plus: USB Audio (hw:2,0)"), so check before ALSA passthrough.
    for idx, dev in enumerate(devices):
        if dev.get("name", "") == spec:
            return idx

    # 2. Explicit ALSA path (e.g., "hw:2", "plughw:2,0") that has no exact
    # matching device name — pass through as an ALSA string.
    if ":" in spec:
        return spec

    # 3. Substring match
    for idx, dev in enumerate(devices):
        if spec.lower() in dev.get("name", "").lower():
            return idx

    raise ValueError(f"No audio input device matching: {spec!r}")


class AudioCapture:
    """Live audio stream capture using sounddevice."""

    def __init__(
        self,
        device: str | int | None = None,
        sample_rate: int = 48000,
        channels: int = 2,
        block_size: int = 4800,
        slow_read_us: int = SLOW_READ_US,
    ) -> None:
        self.device = device
        self.sample_rate = sample_rate
        self.channels = channels
        self.block_size = block_size
        self.slow_read_us = slow_read_us
        self.last_read_us = 0
        self.consecutive_slow = 0

        self._queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=100)
        self._stream: Any = None
        self._is_running = False

    def _audio_callback(self, indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        """PortAudio thread callback."""
        if self._is_running:
            t0 = time.monotonic()
            try:
                self._queue.put_nowait(indata.copy())
            except queue.Full:
                # Queue full under severe CPU starvation: drop oldest to prevent lag
                try:
                    self._queue.get_nowait()
                    self._queue.put_nowait(indata.copy())
                except queue.Empty:
                    pass
            read_us = int((time.monotonic() - t0) * 1_000_000)
            update_read_metrics(self, read_us)

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

        if isinstance(self.device, str):
            resolved_device = resolve_device_input(self.device)
        else:
            resolved_device = self.device

        self._is_running = True
        self._stream = sd.InputStream(
            device=resolved_device,
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
        slow_read_us: int = SLOW_READ_US,
    ) -> None:
        self.slow_read_us = slow_read_us
        self.last_read_us = 0
        self.consecutive_slow = 0
        # Stall simule injecte dans get_block() pour tester la detection de blocs lents.
        self.stall_s = 0.0

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

        # Time the block production (excluu l'attente de cadencement) ; le stall
        # simule un bloc ALSA lent, la mesure resulte dans last_read_us.
        t_produce = time.monotonic()
        if self.stall_s > 0.0:
            time.sleep(self.stall_s)

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

        update_read_metrics(self, int((time.monotonic() - t_produce) * 1_000_000))

        # Real-time pacing: align to monotonic clock so the mock runs at 1× speed
        expected_next = self._last_time + self.block_size / self.sample_rate
        lag = expected_next - time.monotonic()
        if lag > 0:
            time.sleep(lag)
        self._last_time = max(
            self._last_time + self.block_size / self.sample_rate, time.monotonic()
        )

        return block

    def is_active(self) -> bool:
        return self._is_running
