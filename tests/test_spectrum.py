"""Tests de l'historique spectre (I63) : SpectrumAggregator, store, config, API.

Un signal quasi permanent est absorbé par le floor (médiane glissante) et ne
génère jamais d'événement ; l'agrégateur capture le PSD pour visualisation.
"""

import base64
from unittest import mock

import numpy as np
import pytest

from bruittrack.config import Config, SpectrumConfig, load_config
from bruittrack.dsp import SpectrumAggregator
from bruittrack.store import EventStore


def _flat_psd(db_level: float = -80.0, n_bins: int = 308) -> np.ndarray:
    return np.full(n_bins, db_level, dtype=np.float64)


def _freqs(n_bins: int = 308, bin_hz: float = 0.48828125) -> np.ndarray:
    return np.arange(n_bins) * bin_hz


class TestSpectrumAggregator:
    def test_no_row_before_interval(self):
        agg = SpectrumAggregator(_freqs(), interval_s=60.0)
        t0 = 1_700_000_000.0
        assert agg.update(t0 + 0.1, _flat_psd(), _flat_psd()) is None
        assert agg.update(t0 + 30.0, _flat_psd(), _flat_psd()) is None

    def test_row_emitted_after_interval_and_window_resets(self):
        agg = SpectrumAggregator(_freqs(), interval_s=60.0)
        t0 = 1_700_000_000.0
        assert agg.update(t0, _flat_psd(), _flat_psd()) is None  # 1er tick = ouverture fenêtre
        row = agg.update(t0 + 60.5, _flat_psd(), _flat_psd())
        assert row is not None
        rt0, dur, blob = row
        assert rt0 == pytest.approx(t0)
        assert 59.0 <= dur <= 61.0
        assert isinstance(blob, bytes)
        assert len(blob) == agg.n_bands * 4
        # fenêtre suivante : nouveau tick → pas de ligne immédiate
        assert agg.update(t0 + 61.0, _flat_psd(), _flat_psd()) is None
        row2 = agg.update(t0 + 121.5, _flat_psd(), _flat_psd())
        assert row2 is not None and row2[0] == pytest.approx(t0 + 60.5)

    def test_tone_band_higher_than_neighbors(self):
        """Une sinusoïde ~50 Hz domine sa bande vs les bandes voisines."""
        freqs = _freqs()
        psd_g = _flat_psd(-90.0)
        psd_d = _flat_psd(-95.0)
        # boost étroit autour du bin le plus proche de 50 Hz (canal G uniquement)
        i50 = int(np.argmin(np.abs(freqs - 50.0)))
        psd_g[i50] += 60.0  # -30 dB au lieu de -90 dB
        agg = SpectrumAggregator(freqs, n_bands=24, min_hz=2.0, max_hz=150.0)
        t0 = 1_700_000_000.0
        agg.update(t0, psd_g, psd_d)
        _, _, blob = agg.update(t0 + 60.5, psd_g, psd_d)
        arr = np.frombuffer(blob, dtype=np.uint8).reshape(agg.n_bands, 4)
        edges = agg.band_edges()
        band50 = int(np.searchsorted(edges, 50.0, side="right") - 1)
        max_g = arr[:, 1].astype(int)
        assert max_g[band50] >= max_g[max(0, band50 - 2)] + 10
        # canal D sans tonalité : nettement plus bas sur cette bande
        assert arr[band50, 3] < arr[band50, 1] - 10

    def test_quantization_bounds(self):
        """Niveaux extrêmes clampés dans [0, 255]."""
        agg = SpectrumAggregator(
            _freqs(), db_min=-100.0, db_range=100.0
        )  # -140 dB -> sous le plancher -> 0 ; +80 dB -> >255 -> 255
        hi = np.full(len(_freqs()), 200.0)
        lo = np.full(len(_freqs()), -300.0)
        t0 = 1_700_000_000.0
        agg.update(t0, hi, lo)
        _, _, blob = agg.update(t0 + 60.5, hi, lo)
        arr = np.frombuffer(blob, dtype=np.uint8)
        assert arr.max() <= 255 and arr.min() >= 0
        assert (arr.reshape(-1, 4)[:, 1] == 255).any()  # max canal G saturé haut

    def test_band_edges_linear_spaced(self):
        agg = SpectrumAggregator(_freqs(), n_bands=24, min_hz=2.0, max_hz=150.0)
        e = agg.band_edges()
        assert e[0] == pytest.approx(2.0) and e[-1] == pytest.approx(150.0)
        diffs = np.diff(e)
        assert np.allclose(diffs, diffs[0])  # progression arithmétique constante (I64c)

    def test_empty_band_no_saturation_artifact(self):
        """Bande sans bin (ex. sous la résolution FFT) → min=max=q=0, jamais 255."""
        agg = SpectrumAggregator(_freqs(), n_bands=24, min_hz=2.0, max_hz=150.0)
        psd = _flat_psd(-80.0)
        t0 = 1_700_000_000.0
        agg.update(t0, psd, psd)
        _, _, blob = agg.update(t0 + 60.5, psd, psd)
        arr = np.frombuffer(blob, dtype=np.uint8).reshape(agg.n_bands, 4)
        edges = agg.band_edges()
        fq = _freqs()
        for b in range(agg.n_bands):
            has_bin = ((fq >= edges[b]) & (fq <= edges[b + 1])).any()
            if not has_bin:
                assert arr[b, 0] == 0 and arr[b, 1] == 0, f"bande vide {b}: {arr[b]}"

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"n_bands": 0},
            {"min_hz": 0.0},
            {"max_hz": 1.0, "min_hz": 5.0},
            {"db_range": 0.0},
            {"interval_s": -1.0},
        ],
    )
    def test_invalid_params_raise(self, kwargs):
        with pytest.raises(ValueError):
            SpectrumAggregator(_freqs(), **kwargs)


class TestStoreSpectrum:
    def test_roundtrip_memory(self):
        store = EventStore(db_path=":memory:")
        store.add_spectrum(1000.0, 60.0, 3, b"\x01\x02\x03\x04" * 3)
        store.add_spectrum(1060.0, 60.0, 3, b"\x05\x06\x07\x08" * 3)
        rows = store.get_spectrum()
        assert len(rows) == 2
        assert rows[0]["t0"] == pytest.approx(1000.0)
        assert rows[0]["dur"] == pytest.approx(60.0)
        assert rows[0]["n_bands"] == 3
        assert base64.b64decode(rows[0]["data"]) == b"\x01\x02\x03\x04" * 3

    def test_filters_since_until_limit(self):
        store = EventStore(db_path=":memory:")
        for i in range(5):
            store.add_spectrum(1000.0 + i * 60.0, 60.0, 1, b"\x00\x01\x02\x03")
        store.flush()
        assert len(store.get_spectrum(since=1120.0)) == 3
        assert len(store.get_spectrum(until=1060.0)) == 2
        assert len(store.get_spectrum(limit=3)) == 3

    def test_retention_spectrum_only(self):
        store = EventStore(db_path=":memory:")
        store.add_spectrum(1000.0, 60.0, 1, b"\x00" * 4)
        now = 1_700_000_000.0
        store.add_spectrum(now, 60.0, 1, b"\x00" * 4)
        store.flush()
        # purge spectre : coupe à 5000 s avant now -> la ligne de 1000 s disparaît
        with mock.patch("bruittrack.store.time.time", return_value=now):
            store.apply_retention(365, spectrum_days=0.05)
        rows = store.get_spectrum()
        assert len(rows) == 1
        assert rows[0]["t0"] == pytest.approx(now)

    def test_events_flush_still_works_alongside(self):
        from bruittrack.events import SoundEvent

        store = EventStore(db_path=":memory:")
        store.add_event(
            SoundEvent(
                t0=1.0,
                dur=1.0,
                bin_i=5,
                freq=2.44,
                lvl_g=11.0,
                lvl_d=12.0,
                off_ms=0.0,
                fp=b"\x01" * 16,
            )
        )
        store.add_spectrum(1.0, 60.0, 2, b"\x07" * 8)
        store.flush()
        assert len(store.get_events()) == 1
        assert len(store.get_spectrum()) == 1


class TestConfigSpectrum:
    def test_defaults(self):
        cfg = Config()
        assert cfg.spectrum.enabled is True
        assert cfg.spectrum.interval_s == 60.0
        assert cfg.spectrum.n_bands == 24
        assert cfg.spectrum.retention_days is None

    def test_load_from_toml(self, tmp_path):
        p = tmp_path / "config.toml"
        p.write_text(
            "[dsp]\nfreq_max = 150.0\n\n"
            "[spectrum]\nenabled = false\ninterval_s = 120.0\nn_bands = 12\ndb_min = -120.0\ndb_range = 140.0\nretention_days = 30\n"
        )
        cfg = load_config(p)
        assert cfg.spectrum.enabled is False
        assert cfg.spectrum.interval_s == 120.0
        assert cfg.spectrum.n_bands == 12
        assert cfg.spectrum.db_min == -120.0
        assert cfg.spectrum.db_range == 140.0
        assert cfg.spectrum.retention_days == 30

    def test_retention_zero_means_disabled(self, tmp_path):
        p = tmp_path / "config.toml"
        p.write_text("[spectrum]\nretention_days = 0\n")
        assert load_config(p).spectrum.retention_days is None

    @pytest.mark.parametrize(
        "key,val",
        [("interval_s", 0.0), ("interval_s", -5.0), ("n_bands", 0), ("db_range", 0.0)],
    )
    def test_invalid_raises(self, tmp_path, key, val):
        p = tmp_path / "config.toml"
        p.write_text(f"[spectrum]\n{key} = {val!r}\n")
        with pytest.raises(ValueError):
            load_config(p)

    def test_dataclass_validation_direct(self):
        with pytest.raises(ValueError):
            Config(spectrum=SpectrumConfig(n_bands=0)).validate()


class TestVizApiSpectrum:
    def test_endpoint_returns_rows(self, tmp_path):
        import json as _json
        import threading
        import urllib.request

        import bruittrack.viz as viz_mod

        store = EventStore(db_path=str(tmp_path / "viz.db"))
        store.add_spectrum(1700000000.0, 60.0, 2, b"\x09" * 8)
        store.flush()

        config = Config()
        handler = type("H", (viz_mod.BruitTrackHandler,), {"store": store, "config": config})
        server = __import__("http.server", fromlist=["ThreadingHTTPServer"]).ThreadingHTTPServer(
            ("127.0.0.1", 0), handler
        )
        port = server.server_address[1]
        th = threading.Thread(target=server.serve_forever, daemon=True)
        th.start()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/spectrum") as resp:
                payload = _json.loads(resp.read())
            assert payload["rows"][0]["t0"] == 1700000000.0
            assert base64.b64decode(payload["rows"][0]["data"]) == b"\x09" * 8
        finally:
            server.shutdown()
            server.server_close()
