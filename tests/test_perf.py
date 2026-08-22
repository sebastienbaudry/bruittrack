"""Unit tests for the `bruittrack perf` command (M9)."""

from __future__ import annotations

import argparse
import io
from contextlib import redirect_stdout
from pathlib import Path


import pytest

from bruittrack import __main__ as cli


def _stat_text(utime: int, stime: int, rss_pages: int) -> str:
    """fake /proc/<pid>/stat line, fields after the comm closing paren.

    After `rsplit(")", 1)[1].split()`, utime is idx 11, stime idx 12,
    rss (field 24 of /proc) is idx 21.
    """
    fields = [0] * 22
    fields[0] = "S"  # state
    fields[11] = utime
    fields[12] = stime
    fields[21] = rss_pages
    return "42 (dummy) " + " ".join(str(f) for f in fields)


class _FakeProc:
    def __init__(self, samples: list[str]):
        self._samples = list(samples)

    def read_text(self, encoding=None, errors=None):  # type: ignore[no-untyped-def]
        assert self._samples, "sample exhausted"
        return self._samples.pop(0)


def _run_perf(monkeypatch, samples, pid=42):
    fake = _FakeProc(samples)

    def fake_read_text(self, encoding=None, errors=None):  # type: ignore[no-untyped-def]
        if "proc" not in str(self):
            raise AssertionError(f"unexpected read: {self}")
        return fake.read_text()

    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr(Path, "read_text", fake_read_text)
    buf = io.StringIO()
    ns = argparse.Namespace(pid=pid)
    with redirect_stdout(buf):
        rc = cli.cmd_perf(ns)
    return rc, buf.getvalue()


def test_perf_conforme_within_budget(monkeypatch):
    rss_pages = 30_000  # 120 Mo < 150 Mo
    # delta=100 jiffies over a 15 s window (CLOCK_TICKS≈100) -> ~6-7 %
    rc, out = _run_perf(
        monkeypatch, [_stat_text(100, 0, rss_pages), _stat_text(200, 0, rss_pages)]
    )
    assert rc == 0
    assert "CONFORME" in out


def test_perf_non_conforme_cpu(monkeypatch):
    # delta=500 jiffies over ~15 s -> ~33 % > 15 %
    rc, out = _run_perf(
        monkeypatch, [_stat_text(100, 0, 30_000), _stat_text(500, 200, 30_000)]
    )
    assert rc == 2
    assert "NON-CONFORME" in out


def test_perf_non_conforme_rss(monkeypatch):
    rss_pages = 40_000  # 160 Mo > 150 Mo, CPU within budget
    rc, out = _run_perf(
        monkeypatch, [_stat_text(100, 0, rss_pages), _stat_text(150, 0, rss_pages)]
    )
    assert rc == 2
    assert "NON-CONFORME" in out


def test_perf_pid_gone_returns_1(monkeypatch):
    # utime/stime frozen between samples -> PID absent or /proc refused
    rc, out = _run_perf(
        monkeypatch, [_stat_text(100, 5, 30_000), _stat_text(100, 5, 31_000)]
    )
    assert rc == 1
    assert "Impossible de mesurer" in out
