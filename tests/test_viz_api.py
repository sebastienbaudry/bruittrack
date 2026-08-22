"""Tests de l'API HTTP du serveur de visualisation (port éphémère, sans Playwright).

Acceptance IMPROVEMENTS.md item viz :
- /api/events expose bien les champs lvl_g/lvl_d (utilisés par le tooltip);
- /api/stats reflète le compteur;
- homepage HTML servie.
"""

import io
import json
import http.server
import threading
import urllib.request
import wave

import numpy as np
import pytest

from bruittrack.config import Config, StorageConfig
from bruittrack.events import SoundEvent
from bruittrack.store import EventStore
from bruittrack.viz import BruitTrackHandler


def _seed_store(tmp_path):
    store = EventStore(db_path=str(tmp_path / "viz.db"))
    for i in range(3):
        store.add_event(
            SoundEvent(t0=1700000000.0 + i, dur=1.5, bin_i=10 + i,
                       freq=(10 + i) * 0.48828, lvl_g=12.5 + i, lvl_d=8.0,
                       off_ms=1.2, fp=b"\x01" * 16)
        )
    store.flush()
    return store


@pytest.fixture(scope="module")
def viz_server(tmp_path_factory):
    """Lève ThreadingHTTPServer sur un port éphémère avec un store seedé."""
    tmp = tmp_path_factory.mktemp("viz")
    store = _seed_store(tmp)
    config = Config(storage=StorageConfig(db_path=str(tmp / "viz.db"),
                                          exemplars_dir=str(tmp / "exemplars")))

    handler = type("HandlerT", (BruitTrackHandler,), {"store": store, "config": config})
    exemplars = tmp / "exemplars"
    exemplars.mkdir(exist_ok=True)
    (exemplars / "ex_1.raw").write_bytes(np.random.default_rng(42).normal(0.0, 0.1,
                                                                          size=512).astype("float16").tobytes())
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}", store, tmp
    server.shutdown()
    server.server_close()
    store.close()


def _get_json(base, path):
    with urllib.request.urlopen(base + path, timeout=5) as resp:
        assert resp.status == 200
        return json.loads(resp.read().decode("utf-8"))


def test_events_api_contains_tooltip_fields(viz_server):
    base, _, _ = viz_server
    events = _get_json(base, "/api/events?limit=10")
    assert isinstance(events, list) and len(events) == 3
    for ev in events:
        for key in ("lvl_g", "lvl_d", "bin_i", "freq", "t0", "dur", "off_ms", "cluster"):
            assert key in ev, f"champ manquant: {key}"
    levels = sorted(ev["lvl_g"] for ev in events)
    assert levels == pytest.approx([12.5, 13.5, 14.5])


def test_stats_api_reflects_counted_events(viz_server):
    base, _, _ = viz_server
    stats = _get_json(base, "/api/stats")
    assert "total_events" in stats
    assert stats["total_events"] >= 3


def test_homepage_served(viz_server):
    base, _, _ = viz_server
    with urllib.request.urlopen(base + "/", timeout=5) as resp:
        body = resp.read().decode("utf-8")
    assert "BruitTrack" in body


def test_dashboard_has_channel_toggles_and_tooltip(viz_server):
    base, _, _ = viz_server
    with urllib.request.urlopen(base + "/", timeout=5) as resp:
        body = resp.read().decode("utf-8")
    # Item 6 : toggles de canal + tooltip bin/freq/niveaux dans le dashboard JS
    for needle in ("toggleChannel", "evtTip", "timelinePoints", "showCh"):
        assert needle in body, f"élément JS manquant: {needle}"
    # Le tooltip expose bien les champs requis
    assert "bin ${ev.bin_i}" in body and "lvl_g.toFixed" in body


def test_exemplar_wav_endpoint_viz(viz_server):
    """/api/exemplar/<cid> sert un WAV float16-512 -> PCM16 valide (AGENTS: 256 ms, 2 ch)."""
    base, _, _ = viz_server
    with urllib.request.urlopen(base + "/api/exemplar/1", timeout=5) as resp:
        assert resp.status == 200
        assert resp.headers["Content-Type"] == "audio/wav"
        body = resp.read()
    assert body[:4] == b"RIFF" and b"WAVE" in body[:16]
    with wave.open(io.BytesIO(body)) as w:
        assert (w.getnchannels(), w.getframerate()) == (2, 1000)
        assert w.getnframes() == 256


def test_exemplar_missing_returns_404(viz_server):
    base, _, _ = viz_server
    with pytest.raises(urllib.error.HTTPError) as ei:
        urllib.request.urlopen(base + "/api/exemplar/999", timeout=5)
    assert ei.value.code == 404
