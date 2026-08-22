"""Decisive per-subpart tick benchmark for HP T620 (run inside /opt/bruittrack)."""
import numpy as np
import time
from scipy.signal import sosfilt
from bruittrack.dsp import design_butterworth_lp_sos, DspPipeline, FloorTracker

N = 300
x = (np.random.rand(4800, 2) - 0.5) * 10
ramp = np.sin(2 * np.pi * 30 * np.arange(4800) / 48000)
x[:, 0] += ramp
x[:, 1] += 0.9 * ramp
x = x.astype(np.float32)

sos = design_butterworth_lp_sos(cutoff_hz=400.0, fs=48000.0, order=8)
hann = (0.5 * (1 - np.cos(2 * np.pi * np.arange(2048) / 2047))).astype(np.float32)
fs_low, step, n_seg = 1000.0, 1024, 2048
mask = (np.fft.rfftfreq(n_seg, 1.0 / fs_low) <= 48).astype(int)
buf = np.random.randn(8192, 2).astype(np.float32) * 0.1
wsum = float(hann @ hann)
pipe = DspPipeline()
ft = FloorTracker(n_bins=pipe.n_bins, history_len=300, warmup_ticks=1)
for _ in range(5):
    pipe.process_block(x)


def bench(label, fn):
    fn()
    t0 = time.perf_counter()
    for _ in range(N):
        fn()
    dt = (time.perf_counter() - t0) / N * 1e3
    print(f"{label:34s} {dt:8.3f} ms/tick   ~{dt:5.2f}% CPU")


def f_sosfilt_only():
    src = np.ascontiguousarray(x, dtype=np.float64)
    y = np.empty((4800, 2))
    for ch in range(2):
        yy, _ = sosfilt(sos, src[:, ch])
        y[:, ch] = yy


def f_welch_only():
    b = buf.copy()
    acc1 = np.zeros(pipe.n_bins)
    acc2 = np.zeros(pipe.n_bins)
    for i in range(pipe.n_welch_segments):
        s = b[i * step : i * step + n_seg, :]
        a = np.fft.rfft(s[:, 0] * hann)
        c = np.fft.rfft(s[:, 1] * hann)
        acc1 += (a[mask].abs() ** 2).astype(np.float32)
        acc2 += (c[mask].abs() ** 2).astype(np.float32)
    db1 = 10 * np.log10(acc1 / pipe.n_welch_segments + 1e-12)
    db2 = 10 * np.log10(acc2 / pipe.n_welch_segments + 1e-12)


def f_process_block():
    pipe.process_block(x)


def f_floor_300():
    ft.tick_count = 300
    return ft.get_floor()


def f_delay_only():
    s1 = buf[-512:, 0].astype(np.float64)
    s2 = buf[-512:, 1].astype(np.float64)
    s1 -= s1.mean()
    s2 -= s2.mean()
    for _ in range(17):
        np.correlate(s1, s2, "full")


def f_ema_copy():
    p = np.log10(np.abs((0.5 * np.random.rand(pipe.n_bins)) + 1e-9))
    sm = 0.5 * p + 0.5 * np.ones_like(p)
    return sm.copy(), sm.copy()


bench("sosfilt x2ch scipy", f_sosfilt_only)
bench("welch 7seg x2ch rfft2048", f_welch_only)
bench("process_block (total)", f_process_block)
bench("floor get_floor partition L=300 x2", f_floor_300)
bench("channel_delay 17x correlate512", f_delay_only)
bench("ema + double .copy() return", f_ema_copy)
print(f"rfft-2048 cost basis: n_welch_segments={pipe.n_welch_segments}")