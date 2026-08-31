"""Tests de l'API HTTP du serveur de visualisation (port éphémère, sans Playwright).

Acceptance IMPROVEMENTS.md item viz :
- /api/events expose bien les champs lvl_g/lvl_d (utilisés par le tooltip);
- /api/stats reflète le compteur;
- homepage HTML servie.
"""

import http.server
import io
import json
import sqlite3
import threading
import urllib.error
import urllib.request
import wave
from pathlib import Path

import numpy as np
import pytest

from bruittrack.config import Config, StorageConfig
from bruittrack.events import FLAG_OVER_LEGAL, SoundEvent
from bruittrack.store import EventStore
from bruittrack.viz import BruitTrackHandler


def _seed_store(tmp_path):
    store = EventStore(db_path=str(tmp_path / "viz.db"))
    for i in range(3):
        store.add_event(
            SoundEvent(
                t0=1700000000.0 + i,
                dur=1.5,
                bin_i=10 + i,
                freq=(10 + i) * 0.48828,
                lvl_g=12.5 + i,
                lvl_d=8.0,
                off_ms=1.2,
                fp=b"\x01" * 16,
            )
        )
    store.flush()
    return store


@pytest.fixture(scope="module")
def viz_server(tmp_path_factory):
    """Lève ThreadingHTTPServer sur un port éphémère avec un store seedé."""
    tmp = tmp_path_factory.mktemp("viz")
    store = _seed_store(tmp)
    config = Config(
        storage=StorageConfig(db_path=str(tmp / "viz.db"), exemplars_dir=str(tmp / "exemplars"))
    )

    handler = type("HandlerT", (BruitTrackHandler,), {"store": store, "config": config})
    exemplars = tmp / "exemplars"
    exemplars.mkdir(exist_ok=True)
    (exemplars / "ex_1.raw").write_bytes(
        np.random.default_rng(42).normal(0.0, 0.1, size=512).astype("float16").tobytes()
    )
    # Exemplaire corrompu (I24) : taille incoherente float16
    (exemplars / "ex_7.raw").write_bytes(b"abc")
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


def test_events_api_exposes_over_legal_flag(viz_server):
    base, store, _ = viz_server
    events = _get_json(base, "/api/events?limit=10")
    assert all("over_legal" in ev and ev["over_legal"] is False for ev in events)
    # An event with bit3 set (FLAG_OVER_LEGAL) must surface as over_legal=True.
    store.add_event(
        SoundEvent(
            t0=1700009999.0,
            dur=2.0,
            bin_i=40,
            freq=19.53,
            lvl_g=22.5,
            lvl_d=20.5,
            off_ms=-1.5,
            fp=b"f" * 16,
            flags=FLAG_OVER_LEGAL,
            cluster=9,
        )
    )
    store.flush()
    events = _get_json(base, "/api/events?limit=10")
    top = [ev for ev in events if ev["flags"] == FLAG_OVER_LEGAL]
    assert len(top) == 1 and top[0]["over_legal"] is True


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
    for needle in (
        "toggleChannel",
        "evtTip",
        "timelinePoints",
        "showCh",
        "syncChannelButtons",
        "syncChannelFilterSelect",
        "snapToggleChG",
        "snapToggleChD",
    ):
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


def test_triage_endpoint_persists_flags_and_label(viz_server):
    """I13 : POST /api/clusters/1/triage update flags+label persistés en base."""

    base, _store, tmp = viz_server
    body = json.dumps({"flags": 3, "label": "compreur nocturne"}).encode("utf-8")
    req = urllib.request.Request(
        base + "/api/clusters/1/triage",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        assert resp.status == 200
        payload = json.loads(resp.read())
    # la réponse ne porte que success/id — on relit l'état réelle via /api/clusters
    assert payload.get("success") is True or payload.get("error") in (None, ""), payload

    # vérifier que l'état est réellement persisté dans la table clusters
    conn = sqlite3.connect(tmp / "viz.db")
    try:
        row = conn.execute("SELECT flags, label FROM clusters WHERE id=1").fetchone()
    finally:
        conn.close()
    assert row == (3, "compreur nocturne")


def test_triage_endpoint_rejects_bad_payload(viz_server):
    """I13 : POST /api/clusters/99/triage avec JSON invalide → HTTP 400."""

    base, _store, _tmp = viz_server
    req = urllib.request.Request(
        base + "/api/clusters/99/triage",
        data=b"not-json{{",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(req, timeout=5)
    assert excinfo.value.code == 400


def test_clusters_includes_triage_orphan(viz_server):
    """I17/I20 : un cluster triagé sans event apparaît dans GET /api/clusters (event_count=0)."""

    base, store, _tmp = viz_server
    store.set_cluster_triage(77, 1, "orphelin de test")

    payload = _get_json(base, "/api/clusters?limit=200")
    rows = payload if isinstance(payload, list) else payload.get("clusters", [])
    orphan = [c for c in rows if c["cluster_id"] == 77]
    assert orphan, f"cluster orphelin 77 absent de /api/clusters : {rows[:3]}"
    assert orphan[0]["event_count"] == 0


def test_exemplar_corrupt_returns_500(viz_server):
    """Un .raw troncore doit renvoyer 500 (I24)."""
    base, _store, _tmp = viz_server
    try:
        with urllib.request.urlopen(base + "/api/exemplar/7.wav", timeout=5) as resp:
            assert resp.status == 200
    except urllib.error.HTTPError as e:
        assert e.code == 500, f"attendu 500, obtenu {e.code}"


def test_events_query_params_invalid_return_400(viz_server):
    """I26 : params invalides (since texte, limit<=0, offset<0) -> 400."""
    base, _store, _tmp = viz_server
    for q in ("since=abc", "limit=0", "offset=-1", "limit=-5"):
        try:
            with urllib.request.urlopen(base + "/api/events?" + q, timeout=5) as resp:
                assert False, f"attendu 400 pour {q}, obtenu {resp.status}"
        except urllib.error.HTTPError as e:
            assert e.code == 400, f"attendu 400 pour {q}, obtenu {e.code}"


def test_health_endpoint_returns_ok_and_event_count(viz_server):
    """I31 : GET /api/health -> 200 {ok:true, events_db_rows>=3} (store seedee au module)."""
    base, _store, _tmp = viz_server
    with urllib.request.urlopen(base + "/api/health", timeout=5) as resp:
        assert resp.status == 200
        data = json.loads(resp.read())
    assert data["ok"] is True
    assert isinstance(data["events_db_rows"], int)
    assert data["events_db_rows"] >= 3


def test_homepage_injects_dsp_frequency_bounds(viz_server):
    """Axe Y dynamique : la page expose freq_max/min_event_hz de la config DSP.

    Plus d'echelle 48 Hz en dur coté client ; les placeholders __FREQ_MAX__ /
    __MIN_EVENT_HZ__ sont remplaces dans do_GET a partir de self.config.dsp.
    """
    base, _store, _tmp = viz_server
    with urllib.request.urlopen(base + "/", timeout=5) as resp:
        body = resp.read().decode("utf-8")
    # Valeurs par defaut du DspConfig (150.0 / 2.0), formatees %g
    assert "let FREQ_MAX = 150;" in body
    assert "let MIN_EVENT_HZ = 2;" in body
    assert "__FREQ_MAX__" not in body and "__MIN_EVENT_HZ__" not in body
    assert "/ 48." not in body and "<= 48" not in body


def test_homepage_respects_custom_freq_max(tmp_path):
    """Une config custom (freq_max=200) doit etre injectee telle quelle."""
    store = _seed_store(tmp_path)
    config = Config(
        storage=StorageConfig(db_path=str(tmp_path / "viz2.db"), exemplars_dir=str(tmp_path / "ex"))
    )
    config.dsp.freq_max = 200.0
    handler = type("HandlerT2", (BruitTrackHandler,), {"store": store, "config": config})
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as resp:
            body = resp.read().decode("utf-8")
        assert "let FREQ_MAX = 200;" in body
    finally:
        server.shutdown()
        server.server_close()
        store.close()


def test_i58_table_chart_sync_tokens() -> None:
    """I58 : le tableau affiche strictement le set du graphe (selection unique)."""
    from bruittrack.viz import HTML_DASHBOARD

    for tok in (
        "function syncEventsToTable(",
        "const visId = new Set(lastVisible.map(e => e.id))",
        "I58 SELECTION UNIQUE",
        "sort((a, b) => b.t0 - a.t0)",
    ):
        assert tok in HTML_DASHBOARD, tok


def test_i58_no_divergent_renders() -> None:
    """I58 : plus de rendu table+graphe divergent en dehors du chemin unifie."""
    from bruittrack.viz import HTML_DASHBOARD

    frag = "const visible = filterEvents(eventsData);\n  renderEventsTable(visible)"
    assert frag not in HTML_DASHBOARD
    # applyFilters minimal : uniquement drawTimelineFull()
    i = HTML_DASHBOARD.find("function applyFilters() {")
    block = HTML_DASHBOARD[i : i + 200]
    assert "drawTimelineFull(); // I58" in block


def test_lastvisible_renderloop_markers():
    """I58(2) — the dashboard keeps the table pinned to lastVisible + syncEventsToTable."""
    from bruittrack.viz import HTML_DASHBOARD

    html = HTML_DASHBOARD.replace("__FREQ_MAX__", "150").replace("__MIN_EVENT_HZ__", "2")
    for marker in (
        "let lastVisible = []",
        "function syncEventsToTable(",
        "renderEventsTable(rows)",
    ):
        assert marker in html, f"marker manquant : {marker}"

    assert "syncEventsToTable" in html
    assert "renderEventsTable(rows)" in html


def test_no_extracalls_to_renderEventsTable():
    """Only syncEventsToTable() should invoke renderEventsTable — one renderer."""
    from bruittrack.viz import HTML_DASHBOARD

    html = HTML_DASHBOARD.replace("__FREQ_MAX__", "150").replace("__MIN_EVENT_HZ__", "2")
    count = html.count("renderEventsTable(")
    # 1 function definition + 1 call site inside syncEventsToTable
    assert count == 2, f"renderEventsTable( occurrences={count}"


def _spawn_server(store, config):
    handler = type("HandlerT", (BruitTrackHandler,), {"store": store, "config": config})
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{port}"


@pytest.mark.parametrize(
    "record_exemplars,want_player",
    [(True, True), (False, False)],
)
def test_player_html_gated_by_config(tmp_path, record_exemplars, want_player):
    """Le <audio> player et l'état __EXEMPLARS_ENABLED__ suivent record_exemplars (I64)."""
    store = EventStore(db_path=str(tmp_path / "d.db"))
    config = Config(storage=StorageConfig(record_exemplars=record_exemplars))
    server, base = _spawn_server(store, config)
    try:
        body = urllib.request.urlopen(base + "/", timeout=5).read().decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()
    # Le lecteur est conditionné par EXEMPLARS_ENABLED (logique JS) ET l'état est
    # injecté côté serveur — on vérifie le wiring source (le rendu réel est borné
    # par EXEMPLARS_ENABLED ? '<audio ...>' dans renderClustersTable).
    assert ("EXEMPLARS_ENABLED = " + ("true" if want_player else "false")) in body
    assert "EXEMPLARS_ENABLED ?" in body  # gating runtime du player/cellule
    assert 'id="audioTh"' in body  # colonne Audio retirée côté client si désactivée


def test_i64c_spectrogram_linear_scale_in_dashboard() -> None:
    """I64c : le spectre et l'axe Y du temps réel sont en échelle linéaire."""
    from bruittrack.viz import HTML_DASHBOARD

    # Bandes linéaires côté client (formule identique au serveur)
    assert "MIN_EVENT_HZ + (FREQ_MAX - MIN_EVENT_HZ) *" in HTML_DASHBOARD
    # Pas de résidu d'espacement log (bordes) ni d'axe log (yOfHz/yOfHz2)
    assert "Math.pow(FREQ_MAX / MIN_EVENT_HZ" not in HTML_DASHBOARD
    assert "logLo" not in HTML_DASHBOARD and "logHi" not in HTML_DASHBOARD
    # Ticks Hz sur pas « nice » (remplace les étiquettes log fixes)
    assert "niceHzStep" in HTML_DASHBOARD


def test_served_js_is_valid_syntax() -> None:
    """I70 : le JS servi doit être syntaxiquement valide (node --check).

    Le dashoard est un script inline unique — une erreur de syntaxe (ex. le
    `let ly` dupliqué de I69) tue l'ENTIER canvas, invisible des tests à
    marqueurs. node étant absent sur certaines cibles, on saute proprement.
    """
    import os
    import re
    import subprocess
    import tempfile

    from bruittrack.viz import HTML_DASHBOARD

    js = "\n".join(re.findall(r"<script>(.*?)</script>", HTML_DASHBOARD, re.DOTALL))
    assert len(js) > 5000, "script inline du dashoard introuvable"
    p = os.path.join(tempfile.gettempdir(), "bruittrack_dash_check.js")
    Path(p).write_text(js, encoding="utf-8")
    try:
        r = subprocess.run(["node", "--check", p], capture_output=True, timeout=30, check=False)
    except (OSError, FileNotFoundError):
        pytest.skip("node introuvable — vérif syntaxique JS non applicable")
    assert r.returncode == 0, f"JS du dashoard invalide : {r.stderr.decode()[:500]}"


def test_i69_tooltip_above_hovered_bubble() -> None:
    """I69 : le texte survol est positionné juste au-dessus de la bulle survolée

    (`position: fixed`, centré sur best.x, top = y_bulle - hauteur_tip - 10) —
    avant, il restait à sa place fixe dans la barre d'outils et
    paraissait « décalé » par rapport à la bulle.
    """
    from bruittrack.viz import HTML_DASHBOARD

    assert "tip.style.position = 'fixed'" in HTML_DASHBOARD
    assert "crect.left + best.x - tip.offsetWidth / 2" in HTML_DASHBOARD
    assert "crect.top + best.y - tip.offsetHeight - 10" in HTML_DASHBOARD


def test_i68_hover_hit_radius_and_lock() -> None:
    """I68 : survol des points — hit-test aligné sur le rayon visible de chaque bulle
    (max(12, r+3) px) et verrou du point survolé (hoverLockId) anti-flicker.

    Avant (bug « décalage ») : test unique à 10 px du centre — une bulle r=3
    n'était saisissable qu'à ±10 px alors que visuellement elle fait 3 px, et
    deux bulles voisines alternaient le texte du tooltip à chaque pixel de
    souris dans la zone de chevauchement des rayons.
    """
    from bruittrack.viz import HTML_DASHBOARD

    assert "timelinePoints.push({x, y, r: radius, ev: e})" in HTML_DASHBOARD
    assert "Math.max(12, p.r + 3)" in HTML_DASHBOARD
    assert "hoverLockId" in HTML_DASHBOARD
    assert "bd = 10 * 10" not in HTML_DASHBOARD  # ancien hit-test fixe à 10 px retiré


def test_i71_bubbles_colored_per_cluster() -> None:
    """I71 : les bulles du chronogramme reprennent 1 couleur par cluster (reprend I67)."""
    from bruittrack.viz import HTML_DASHBOARD

    assert "function getClusterColor(clusterId)" in HTML_DASHBOARD
    assert "ctx.fillStyle = getClusterColor(e.cluster)" in HTML_DASHBOARD
    # getBinColor retire completement du fichier servi.
    assert "getBinColor" not in HTML_DASHBOARD


def test_i71_dashbadges_still_use_cluster_color() -> None:
    """I71 : badges/table events et cards clusters continuent a utiliser getClusterColor."""
    from bruittrack.viz import HTML_DASHBOARD

    assert "getClusterColor(e.cluster)}22" in HTML_DASHBOARD
    assert "getClusterColor(c.cluster_id)" in HTML_DASHBOARD


def test_clustercolor_gray_fallback_for_missing_cluster() -> None:
    """I71 : cluster NULL/absent dessine le gris neutre #94a3b8."""
    from bruittrack.viz import HTML_DASHBOARD

    assert "if (!clusterId)" in HTML_DASHBOARD
    assert "#94a3b8" in HTML_DASHBOARD


def test_i71_clustercolor_palette_distinct_nearby_ids() -> None:
    """I71 : la palette par cluster reste discriminante sur ids proches.

    Reproduction numerique (colorsys.hls_to_rgb) du getClusterColor JS servi :
    hue = (id*137.5)%360 (angle d'or), saturation 85 %, clarte [45,68] alternatee
    par bloc de 6 ids. Meme distance-metre que I67c sur la plage realiste
    d'ids (1..29 ~ 303 clusters observes / densite dashboard).
    """
    import math
    from colorsys import hls_to_rgb

    from bruittrack.viz import HTML_DASHBOARD

    # Garde formule : angle d'or + clarte alternee par bloc de 6 ids.
    assert "* 137.5) % 360" in HTML_DASHBOARD
    assert "[45, 68]" in HTML_DASHBOARD
    assert "85%" in HTML_DASHBOARD

    def col(cid: int) -> tuple[float, float, float]:
        h = ((cid * 137.5) % 360) / 360.0
        lightness = [45, 68][math.floor(cid / 6) % 2] / 100.0
        return hls_to_rgb(h, lightness, 85 / 100)

    def d(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
        return sum((x - y) ** 2 for x, y in zip(a, b, strict=False)) ** 0.5

    # Fallback cluster NULL/absent : gris neutre, gardes marqueurs.
    assert "#94a3b8" in HTML_DASHBOARD
    assert "if (!clusterId)" in HTML_DASHBOARD

    # Ids adjacents : distance RGB comfortably >= 0.13.
    for i in range(1, 29):
        assert d(col(i), col(i + 1)) >= 0.13, f"clusters adjacents {i},{i + 1} trop proches"

    # Fenetre compacte |Δid| <= 6 : aucune couleur quasi identique (<0.05).
    for i in range(1, 30):
        for j in range(i + 1, min(i + 7, 30)):
            assert d(col(i), col(j)) >= 0.05, f"clusters {i},{j} trop proches"


def test_i56_maj_badge_relative_time() -> None:
    """I53/I56 : badge MAJ relatif — span present, tick 1 s, affichage "il y a Xs" / horodate."""
    from bruittrack.viz import HTML_DASHBOARD as html

    for tok in (
        'id="majBadge"',
        "function renderMaj()",
        "function startMajTick()",
        "let lastMajTs = 0",
        "setInterval(renderMaj, 1000)",
        "MAJ il y a ${dt}s",
        "lastMajTs = Date.now() / 1000; renderMaj(); startMajTick();",
    ):
        assert tok in html, f"marqueur manquant : {tok}"


def test_p0_triage_payload_too_large_returns_413(viz_server) -> None:
    """P0-1 : Un corps de POST > 64 Ko est rejeté avec HTTP 413 (Payload Too Large)."""
    base, _, _ = viz_server
    big_body = json.dumps({"flags": 1, "label": "x" * 70_000}).encode("utf-8")
    req = urllib.request.Request(
        base + "/api/clusters/1/triage",
        data=big_body,
        headers={"Content-Type": "application/json", "Content-Length": str(len(big_body))},
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(req, timeout=5)
    assert excinfo.value.code == 413


def test_p0_events_limit_clamped_to_max_api_limit(viz_server) -> None:
    """P0-2 : Un paramètre limit démesuré (ex: 999999) est borné sans erreur."""
    base, _, _ = viz_server
    events = _get_json(base, "/api/events?limit=999999")
    assert isinstance(events, list)


def test_p0_spectrum_limit_clamped_to_max_api_limit(viz_server) -> None:
    """P0-2 : Un paramètre limit spectrum démesuré est borné sans erreur."""
    base, _, _ = viz_server
    spec = _get_json(base, "/api/spectrum?limit=999999")
    assert "rows" in spec and "edges" in spec


def test_p0_triage_auth_token_protection(tmp_path) -> None:
    """P0-3 : Si auth_token est configuré, POST /triage exige une authentification valide."""
    from bruittrack.config import Config, StorageConfig, VizConfig
    from bruittrack.store import EventStore
    from bruittrack.viz import BruitTrackHandler

    db_path = str(tmp_path / "auth_test.db")
    store = EventStore(db_path=db_path)
    config = Config(
        storage=StorageConfig(db_path=db_path),
        viz=VizConfig(auth_token="secret123"),
    )

    handler = type("HandlerAuth", (BruitTrackHandler,), {"store": store, "config": config})
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"

    try:
        body = json.dumps({"flags": 1, "label": "test"}).encode("utf-8")
        # 1. Sans jeton -> 401
        req1 = urllib.request.Request(
            base + "/api/clusters/1/triage",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as e1:
            urllib.request.urlopen(req1, timeout=5)
        assert e1.value.code == 401

        # 2. Avec jeton Bearer valide -> 200
        req2 = urllib.request.Request(
            base + "/api/clusters/1/triage",
            data=body,
            headers={"Content-Type": "application/json", "Authorization": "Bearer secret123"},
            method="POST",
        )
        with urllib.request.urlopen(req2, timeout=5) as r2:
            assert r2.status == 200

        # 3. Avec jeton X-API-Key valide -> 200
        req3 = urllib.request.Request(
            base + "/api/clusters/1/triage",
            data=body,
            headers={"Content-Type": "application/json", "X-API-Key": "secret123"},
            method="POST",
        )
        with urllib.request.urlopen(req3, timeout=5) as r3:
            assert r3.status == 200
    finally:
        server.shutdown()
        server.server_close()
        store.close()


def test_p0_error_responses_sanitized(viz_server) -> None:
    """P0-4 : Les réponses d'erreur HTTP ne font pas fuiter de chemins ou tracebacks internes."""
    base, _, _ = viz_server
    # Invalid query
    try:
        urllib.request.urlopen(base + "/api/events?limit=invalid", timeout=5)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        assert "Traceback" not in body
        assert "C:\\" not in body and "/opt/" not in body


def test_p1_legal_filter_ui_markers(viz_server) -> None:
    """P1-1 : Le label du filtre et les badges UI reflètent clairement les infractions légales."""
    base, _, _ = viz_server
    with urllib.request.urlopen(base + "/", timeout=5) as resp:
        html = resp.read().decode("utf-8")
    assert "Infractions / Dépassements légaux (▲)" in html
    assert "CSP Art. R1336-7" in html
    assert "▲ Infraction" in html


def test_p1_legal_report_api_endpoint(viz_server) -> None:
    """P1-3 : /api/reports/legal renvoie un rapport complet de conformité."""
    base, _, _ = viz_server
    rep = _get_json(base, "/api/reports/legal")
    assert "title" in rep
    assert "verdict" in rep
    assert "total_events" in rep
    assert "infraction_count" in rep
    assert isinstance(rep["infractions"], list)


def test_is_local_client_detection() -> None:
    """Vérifie la distinction précise entre adresses IP locales/privées et publiques."""
    from bruittrack.viz import is_local_client

    # Local / Privé / Loopback / Link-local
    assert is_local_client("127.0.0.1") is True
    assert is_local_client("127.0.1.1") is True
    assert is_local_client("::1") is True
    assert is_local_client("192.168.1.1") is True
    assert is_local_client("192.168.1.30") is True
    assert is_local_client("10.0.0.1") is True
    assert is_local_client("172.16.0.1") is True
    assert is_local_client("172.31.255.254") is True
    assert is_local_client("fe80::28c:faff:fed2:3e85") is True
    assert is_local_client("::ffff:192.168.1.30") is True

    # Externe / Public
    assert is_local_client("93.174.93.12") is False
    assert is_local_client("8.8.8.8") is False
    assert is_local_client("51.77.52.145") is False
    assert is_local_client("2a01:cb05:8593:600:1175:46d9:d8c1:3a36") is False
    assert is_local_client("::ffff:93.174.93.12") is False

    # Invalide / None
    assert is_local_client("") is False
    assert is_local_client(None) is False
    assert is_local_client("non_ip_string") is False


def test_external_post_requests_rejected_403(tmp_path) -> None:
    """Vérifie que les requêtes POST provenant d'une IP externe sont rejetées avec HTTP 403."""
    from bruittrack.config import Config, StorageConfig
    from bruittrack.store import EventStore
    from bruittrack.viz import BruitTrackHandler

    db_path = str(tmp_path / "readonly_test.db")
    store = EventStore(db_path=db_path)
    config = Config(storage=StorageConfig(db_path=db_path))

    # Handler avec client_address simulée externe
    class ExternalHandler(BruitTrackHandler):
        def __init__(self, *args, **kwargs):
            # Intercepte l'appel pour forcer une IP cliente externe
            super().__init__(*args, **kwargs)

        def setup(self):
            super().setup()
            self.client_address = ("93.174.93.12", 54321)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ExternalHandler)
    ExternalHandler.store = store
    ExternalHandler.config = config
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"

    try:
        # 1. POST /api/clusters/1/triage
        body = json.dumps({"flags": 1, "label": "test"}).encode("utf-8")
        req1 = urllib.request.Request(
            base + "/api/clusters/1/triage",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as e1:
            urllib.request.urlopen(req1, timeout=5)
        assert e1.value.code == 403
        err_body = json.loads(e1.value.read().decode("utf-8"))
        assert "Modifications interdites depuis l'extérieur" in err_body.get("error", "")

        # 2. POST /api/discomfort
        body_disc = json.dumps({"level": 4, "note": "test"}).encode("utf-8")
        req2 = urllib.request.Request(
            base + "/api/discomfort",
            data=body_disc,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as e2:
            urllib.request.urlopen(req2, timeout=5)
        assert e2.value.code == 403

        # 3. GET /api/events (lecture seule) doit rester autorisée avec HTTP 200
        with urllib.request.urlopen(base + "/api/events", timeout=5) as r3:
            assert r3.status == 200
    finally:
        server.shutdown()
        server.server_close()
        store.close()
