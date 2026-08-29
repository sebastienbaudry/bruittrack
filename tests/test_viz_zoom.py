"""I54 : zoom/dézoom 2 axes — marqueurs JS + sémantique du fenêtrage ?since=."""

import http.server
import json
import threading
import urllib.error
import urllib.request

import pytest

from bruittrack.config import Config, StorageConfig
from bruittrack.events import SoundEvent
from bruittrack.store import EventStore
from bruittrack.viz import BruitTrackHandler


def _seed_zoom_store(tmp_path):
    """10 événements espacés d'une heure sur ~10 jours."""
    store = EventStore(db_path=str(tmp_path / "zoom.db"))
    for i in range(10):
        store.add_event(
            SoundEvent(
                t0=1_700_000_000.0 + i * 86_400.0,
                dur=1.5,
                bin_i=10,
                freq=10.0 * 0.48828,
                lvl_g=12.5,
                lvl_d=8.0,
                off_ms=1.2,
                fp=b"\x01" * 16,
            )
        )
    store.flush()
    return store


@pytest.fixture(scope="module")
def zoom_server(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("viz_zoom")
    store = _seed_zoom_store(tmp)
    config = Config(storage=StorageConfig(db_path=str(tmp / "zoom.db")))
    handler = type("ZoomHandler", (BruitTrackHandler,), {"store": store, "config": config})
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    store.close()


def _get(url: str) -> bytes:
    with urllib.request.urlopen(url) as r:
        return r.read()


def test_viz_zoom_markers_homepage(zoom_server):
    """Le HTML servi contient tous les piliers du zoom 2 axes."""
    html = _get(f"{zoom_server}/").decode("utf-8")
    tokens = [
        "let freqView",
        "function axZoom(",
        "panFreqBy(",
        "function fetchWindow(",
        "/api/events?since=",
        "renderTableRow(",
        'id="zoomBadge"',
        "updateZoomBadge",
        "resetFviews",
        "refreshWindowed",
    ]
    for tok in tokens:
        assert tok in html, f"manquant : {tok}"


def test_viz_zoom_since_window(zoom_server):
    """?since= ne renvoie que les événements postérieurs (fenêtrage)."""
    all_data = json.loads(_get(f"{zoom_server}/api/events?limit=100"))
    assert len(all_data) == 10
    cut = all_data[4]["t0"]  # t0 de l'événement #5 (index 4)
    sub = json.loads(_get(f"{zoom_server}/api/events?since={cut}&limit=100"))
    assert len(sub) == 5  # DESC : les 5 plus recents partent de cut
    assert all(e["t0"] >= cut for e in sub)


def test_viz_zoom_full_range_request(zoom_server):
    """?since= très ancien = tout l'historique (limit levé)."""
    got = json.loads(_get(f"{zoom_server}/api/events?since=0&limit=20000"))
    assert len(got) == 10


def test_viz_zoom_order_asc(zoom_server):
    """I59 : ?order=asc renvoie les plus ANCIENS d'abord (chargement continu depuis since)."""
    got = json.loads(_get(f"{zoom_server}/api/events?limit=100&order=asc"))
    t0s = [e["t0"] for e in got]
    assert len(got) == 10
    assert t0s == sorted(t0s)
    cut = t0s[4]
    sub = json.loads(_get(f"{zoom_server}/api/events?since={cut}&limit=3&order=asc"))
    # ASC : les 3 plus anciens >= cut, pas les 3 plus récents (comportement DESC)
    assert [e["t0"] for e in sub] == sorted(e for e in t0s if e >= cut)[:3]


def test_viz_zoom_order_invalid(zoom_server):
    """I59 : order invalide → 400 explicite."""
    with urllib.request.urlopen(f"{zoom_server}/") as r:  # sanity: serveur vivant
        assert r.status == 200
    try:
        urllib.request.urlopen(f"{zoom_server}/api/events?order=sideways")
        raised = False
    except urllib.error.HTTPError as exc:
        raised = exc.code == 400
    assert raised, "order invalide doit renvoyer 400"


def test_viz_calendar_popup_markers(zoom_server):
    """Vérifie la présence des éléments de calendrier popup et des filtres améliorés."""
    html = _get(f"{zoom_server}/").decode("utf-8")
    tokens = [
        'id="calendarModal"',
        'id="calBtn"',
        'id="calDateInput"',
        'id="calDateEnd"',
        'id="calTimeStart"',
        'id="calTimeEnd"',
        "openCalendarModal",
        "closeCalendarModal",
        "applyCalShortcut",
        "applyCalendarSelection",
        "resetCalToLive",
        "last30d",
        'id="eventsFilterCount"',
    ]
    for tok in tokens:
        assert tok in html, f"manquant : {tok}"


def test_viz_auto_refresh_selector_markers(zoom_server):
    """Vérifie la présence du sélecteur de cadence de rafraîchissement."""
    html = _get(f"{zoom_server}/").decode("utf-8")
    tokens = [
        'id="autoRefreshSelect"',
        "changeAutoRefresh",
        "initAutoRefresh",
        'value="1"',
        'value="2"',
        'value="5"',
        'value="10"',
        'value="30"',
        'value="60"',
        'value="0"',
        "bruittrack_refresh_interval",
    ]
    for tok in tokens:
        assert tok in html, f"manquant : {tok}"


def test_viz_frequency_focus_markers(zoom_server):
    """Vérifie la présence des boutons de focus fréquence et de la fonction setFreqFocus."""
    html = _get(f"{zoom_server}/").decode("utf-8")
    tokens = [
        'id="fFocusAll"',
        'id="fFocusInfra"',
        'id="fFocusHum"',
        'id="fFocusHigh"',
        "setFreqFocus",
        "syncFreqButtons",
    ]
    for tok in tokens:
        assert tok in html, f"manquant : {tok}"
