"""Lightweight web visualization server for BruitTrack.

Uses Python stdlib ThreadingHTTPServer and serves a zero-dependency HTML5/Canvas UI.
"""

from __future__ import annotations

import http.server
import io
import json
import urllib.parse
import wave
from pathlib import Path
from typing import Any

import numpy as np

from bruittrack.config import Config
from bruittrack.store import EventStore


def create_wav_from_raw(raw_path: Path, sample_rate: int = 1000) -> bytes:
    """Convert raw float16 2-ch exemplar audio to standard 16-bit PCM WAV in memory."""
    with open(raw_path, "rb") as f:
        raw_data = f.read()

    # Unpack float16 audio (256 samples, 2 channels)
    samples = np.frombuffer(raw_data, dtype=np.float16).astype(np.float32)
    # Clip and convert to int16 PCM
    pcm16 = np.clip(samples * 32767.0, -32768, 32767).astype(np.int16)

    bio = io.BytesIO()
    with wave.open(bio, "wb") as wav_file:
        wav_file.setnchannels(2)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm16.tobytes())

    return bio.getvalue()


HTML_DASHBOARD = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BruitTrack — Traqueur d'Événements Sonores</title>
<style>
  :root {
    --bg-dark: #0f141c;
    --bg-card: #18202c;
    --bg-card-hover: #222d3d;
    --border: #2a384c;
    --primary: #38bdf8;
    --accent: #f59e0b;
    --danger: #ef4444;
    --success: #10b981;
    --text: #f1f5f9;
    --text-muted: #94a3b8;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace; }
  body { background: var(--bg-dark); color: var(--text); padding: 16px; font-size: 14px; }
  header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border); padding-bottom: 12px; margin-bottom: 16px; }
  h1 { font-size: 20px; color: var(--primary); display: flex; align-items: center; gap: 8px; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: bold; }
  .badge-live { background: rgba(16, 185, 129, 0.2); color: var(--success); border: 1px solid var(--success); }
  .badge-cluster { background: rgba(56, 189, 248, 0.2); color: var(--primary); }
  .badge-over { background: rgba(239, 68, 68, 0.2); color: #fca5a5; }
  .badge-ch-l { background: #3b82f6; color: white; }
  .badge-ch-r { background: #ec4899; color: white; }
  .badge-ch-b { background: #8b5cf6; color: white; }
  
  .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 16px; }
  .stat-card { background: var(--bg-card); border: 1px solid var(--border); border-radius: 6px; padding: 12px; }
  .stat-val { font-size: 22px; font-weight: bold; color: var(--primary); margin-top: 4px; }
  .stat-lbl { color: var(--text-muted); font-size: 12px; }

  .card { background: var(--bg-card); border: 1px solid var(--border); border-radius: 6px; padding: 16px; margin-bottom: 16px; }
  .card-title { font-size: 15px; font-weight: bold; margin-bottom: 12px; color: var(--text); display: flex; justify-content: space-between; }

  #timelineCanvas { width: 100%; height: 260px; background: #080c12; border-radius: 4px; border: 1px solid var(--border); cursor: crosshair; }
  #specCanvas { width: 100%; height: 150px; background: #080c12; border-radius: 4px; border: 1px solid var(--border); margin-top: 6px; display: none; }

  table { width: 100%; border-collapse: collapse; text-align: left; }
  tr[data-ev-id] { cursor: pointer; }
  tr.ev-row-selected { background: #312e8155; outline: 1px solid #6366f1; }
  .flt { background: #0f172a; color: #e2e8f0; border: 1px solid #334155; border-radius: 4px; padding: 2px 6px; font-size: 13px; }
  th, td { padding: 8px 10px; border-bottom: 1px solid var(--border); }
  th { color: var(--text-muted); font-size: 12px; text-transform: uppercase; background: rgba(0,0,0,0.15); }
  tr:hover { background: var(--bg-card-hover); }

  .btn { background: var(--border); color: var(--text); border: none; padding: 4px 10px; border-radius: 4px; cursor: pointer; font-size: 12px; transition: 0.15s; }
  .btn:hover { background: var(--primary); color: #000; }
  .btn-sm { padding: 2px 6px; font-size: 11px; }
  .btn-active { background: rgba(59, 130, 246, 0.25); color: #93c5fd; }
  .btn-danger { background: rgba(239, 68, 68, 0.2); color: var(--danger); }
  .btn-danger:hover { background: var(--danger); color: white; }
  .btn-success { background: rgba(16, 185, 129, 0.2); color: var(--success); }
  .btn-success:hover { background: var(--success); color: white; }
  
  .layout-2col { display: grid; grid-template-columns: 2fr 1fr; gap: 16px; }
  @media (max-width: 900px) { .layout-2col { grid-template-columns: 1fr; } }
  
  audio { height: 28px; vertical-align: middle; max-width: 140px; }
</style>
</head>
<body>

<header>
  <h1>🔊 BruitTrack <span class="badge badge-live">24/7 ACTIF</span></h1>
  <div>
    <button class="btn" onclick="refreshAll()">🔄 Rafraîchir</button>
  </div>
</header>

<div class="stats-grid">
  <div class="stat-card">
    <div class="stat-lbl">Événements enregistrés</div>
    <div class="stat-val" id="statEvents">--</div>
  </div>
  <div class="stat-card">
    <div class="stat-lbl">Clusters détectés</div>
    <div class="stat-val" id="statClusters">--</div>
  </div>
  <div class="stat-card">
    <div class="stat-lbl">Taille Base SQLite</div>
    <div class="stat-val" id="statDbSize">--</div>
  </div>
  <div class="stat-card">
    <div class="stat-lbl">Durée moy. / émergence</div>
    <div class="stat-val" id="statAvgDur">--</div>
  </div>
</div>

<div class="card">
  <div class="card-title">
    <span>Timeline Fréquence / Temps (0 – __FREQ_MAX__ Hz)</span>
    <span id="canvasTooltip" style="font-size:12px; color:var(--accent);">Survolez un point</span>
  </div>
  <div style="display:flex; gap:8px; margin-bottom:8px; align-items:center;">
    <button id="toggleChG" class="btn btn-sm" onclick="toggleChannel(0)">IN1 (Air)</button>
    <button id="toggleChD" class="btn btn-sm" onclick="toggleChannel(1)">IN2 (Struct)</button>
    <button id="toggleSpec" class="btn btn-sm" onclick="toggleSpectrum()" title="I63 : heatmap de l'historique spectre (signaux quasi permanents, invisibles dans les événements)">Spectre</button>
    <span style="opacity:.4">|</span>
    <button id="winBtn1h" class="btn btn-sm" onclick="setTimeWin(3600,this)">1h</button>
    <button id="winBtn6h" class="btn btn-sm" onclick="setTimeWin(21600,this)">6h</button>
    <button id="winBtn24h" class="btn btn-sm btn-active" onclick="setTimeWin(86400,this)">24h</button>
    <button id="winBtnTout" class="btn btn-sm" onclick="setTimeWin(null,this)">Tout</button>
    <span style="opacity:.4; font-size:12px; font-family:monospace">glisser = zoom temps · double-clic / Échap = réinit</span>
    <span id="evtTip" style="font-family:monospace; font-size:12px; color:#e2e8f0; background:#1e293b; border-radius:4px; padding:2px 8px; display:none;"></span>
    <span id="freqTip" title="I49 : fréquence sous le curseur" style="font-family:monospace; font-size:12px; color:#93c5fd; background:#1e293b; border-radius:4px; padding:2px 8px; display:none;"></span>
    <span id="zoomBadge" onclick="resetFviews()" title="I54 : reset zoom X+Y (double-clic ou Échap)" style="display:none; cursor:pointer; color:#94a3b8; font-size:12px;"></span>
  </div>
  <canvas id="timelineCanvas" width="1000" height="260"></canvas>
  <div id="specBar" style="display:none; text-align:right; font-size:11px; color:#64748b; margin:4px 2px 0 0;">Spectre — contraste auto par bande (p5–p95), niveau relatif par bande</div>
  <canvas id="specCanvas"></canvas>
</div>

<div class="layout-2col">
  <div class="card">
    <div class="card-title">Derniers Événements</div>
    <div style="max-height: 480px; overflow-y: auto;">
      <div style="margin: 0 0 8px 0; display: flex; gap: 6px; align-items: center; flex-wrap: wrap;">
        <input type="checkbox" id="onlyLegal" style="accent-color: #ef4444;" onchange="applyFilters()" />
        <label for="onlyLegal" style="font-size: 13px; cursor: pointer; color: #fca5a5;">Légaux uniquement (▲)</label>
        <select id="chanFilter" class="flt" onchange="applyFilters()"><option value="">Tous canaux</option><option value="l">IN1 (Air)</option><option value="d">IN2 (Struct)</option><option value="b">Les 2</option></select>
        <label for="minLvlFilter" style="font-size: 13px; color:#94a3b8;">Ém. ≥</label>
        <input type="number" id="minLvlFilter" class="flt" value="0" min="0" step="1" onchange="applyFilters()" /><span style="font-size:12px;color:#94a3b8;">dB</span>
        <select id="clusterFilter" class="flt" onchange="applyFilters()"><option value="">Tous clusters</option></select>
      </div>
      <table>
        <thead>
          <tr>
            <th>Date / Heure</th>
            <th>Fréq (Hz)</th>
            <th>Canal</th>
            <th>Émergence G / D</th>
            <th>Durée</th>
            <th>Cluster</th>
          </tr>
        </thead>
        <tbody id="eventsTableBody">
          <tr><td colspan="6" style="text-align:center;">Chargement...</td></tr>
        </tbody>
      </table>
    </div>
  </div>

  <div class="card">
    <div class="card-title">Groupes Récurrents (Clusters)</div>
    <div style="max-height: 480px; overflow-y: auto;">
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>Occurrences</th>
            <th>Fréq moy</th>
            <th id="audioTh">Audio</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody id="clustersTableBody">
          <tr><td colspan="5" style="text-align:center;">Chargement...</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</div>

<script>
let eventsData = [];
let clustersData = [];

async function fetchJson(url) {
  try {
    const res = await fetch(url);
    return await res.json();
  } catch(e) {
    console.error("API error", e);
    return null;
  }
}

function formatDate(unixSec) { // I62 : horodatage Paris 24 h explicite (l'heure machine cliente peut être en 12 h / autre fuseau)
  if (!unixSec) return "--";
  const d = new Date(unixSec * 1000);
  return d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23', timeZone: TZ_VIZ }) + " " + d.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric', timeZone: TZ_VIZ });
}

function getClusterColor(clusterId) {
  if (!clusterId) return "#94a3b8";
  const hue = (clusterId * 137.5) % 360;
  return `hsl(${hue}, 80%, 60%)`;
}

// ===== I54 : fenêtrage de données, pan fréquence, badge, reset des 2 axes =====
let dataSince = null; // t0 le plus ancien chargé localement (I54)
let dataUntil = null; // t0 le plus récent chargé localement (I54)
let fetchingWin = false;

let winCursorT = null; // I55 : t0 le plus ancien effectivement chargé via fetchWindow (anti-relance à bornes fixes)
async function fetchWindow() { // I54/I55 : fenêtre ?since= dynamique — charge TOUS les événements de la vue temps (boutons ET zoom)
  if (!tlScale || fetchingWin) return;
  const lo = tlScale.minT - 300, hi = tlScale.minT + tlScale.span + 300;
  if ((dataSince === null || lo >= dataSince || (winCursorT !== null && lo >= winCursorT))
      && (dataUntil === null || hi <= dataUntil)) return;
  fetchingWin = true;
  try {
    const sinceT = dataSince !== null ? Math.min(dataSince, Math.floor(lo)) : Math.floor(lo);
    // I59 : order=asc → serveur renvoie les PLUS ANCIENS ≥ sinceT d'abord : chargement continu
    // depuis sinceT (pas de trou si > 20000 événements plus récents existent, cas du tri DESC).
    // winCursorT reste ainsi un plancher fiable de « données garanties chargées ».
    const got = await fetchJson(`/api/events?since=${sinceT}&limit=20000&order=asc`);
    if (!got || !Array.isArray(got)) return;
    const map = new Map();
    (eventsData || []).forEach((e) => { if (e.id !== undefined) map.set(e.id, e); });
    got.forEach((e) => { if (e.id !== undefined) map.set(e.id, e); }); // merge/dédup par id
    eventsData = Array.from(map.values());
    const t0s = eventsData.map((e) => e.t0);
    if (t0s.length) { dataSince = Math.min(dataSince ?? Infinity, ...t0s); dataUntil = Math.max(dataUntil ?? -Infinity, ...t0s); } // I55 : clamp, jamais de replacement
    winCursorT = sinceT; // serveur répondu sur tout t0 >= winCursorT → plus de relance tant que la vue est stable
  } finally { fetchingWin = false; }
}

function refreshWindowed() { // I54 : vue zoomée → fetch de la fenêtre puis dessin
  if (tlMode) return Promise.resolve().then(fetchWindow).then(() => drawTimelineFull());
  drawTimelineFull();
}

function panFreqBy(dyPx, curLo, curHi) { // I54 : décale l'axe fréquence (ΔHz issu de Δpx)
  const dhz = -(dyPx / (TL_CKVH - 40)) * (curHi - curLo);
  let nLo = curLo + dhz, nHi = curHi + dhz;
  if (nLo < 0) { nHi -= nLo; nLo = 0; }
  if (nHi > FREQ_MAX) { nLo -= nHi - FREQ_MAX; nHi = FREQ_MAX; }
  freqView = (nLo > 1e-9 || nHi < FREQ_MAX - 1e-9) ? {fLo: nLo, fHi: nHi} : null;
}

function updateZoomBadge() { // I54 : badge si des vues libres ; clic dessus = reset
  const b = document.getElementById('zoomBadge');
  if (!b) return;
  if (!tlMode && !freqView) { b.style.display = 'none'; return; }
  const ts = tlScale ? new Date(tlScale.minT * 1000).toLocaleString('fr-FR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZone: TZ_VIZ }) : '';
  const dh = tlScale ? (tlScale.span / 3600).toFixed(1) : '0.0';
  const f = freqView ? freqView.fLo.toFixed(1) + '-' + freqView.fHi.toFixed(1) : '0-' + FREQ_MAX;
  b.textContent = '⌕ zoom · f ' + f + ' Hz · t ' + ts + ' → +' + dh + ' h — clic pour réinitialiser';
  b.style.display = 'inline';
}

function resetFviews() { // I54 : double-clic / Échap / badge → vues par défaut (X + Y)
  if (!tlMode && !freqView) return;
  tlMode = null; freqView = null;
  syncTlButtons(); updateZoomBadge(); drawTimelineFull();
}

(function () { // I54 : Ctrl+glisser vertical = translate axe fréquence uniquement
  const cv = document.getElementById('timelineCanvas');
  if (!cv) return;
  let startY = null, startFB = null;
  cv.addEventListener('mousedown', (e) => { if (!e.ctrlKey || e.button !== 0) return; startY = e.clientY; startFB = freqBounds(); });
  document.addEventListener('mousemove', (e) => {
    if (startY === null || !startFB) return;
    panFreqBy(e.clientY - startY, startFB[0], startFB[1]);
    drawTimelineFull(false); // I59 : pendant le pan, pas de rebuild tableau (jank) — synchronisé au relâchement
  });
  document.addEventListener('mouseup', () => { if (startY !== null) { startY = null; startFB = null; updateZoomBadge(); refreshWindowed(); } }); // I59 : sync finale graphe+tableau
})();

async function refreshAll() {
  const [stats, events, clusters] = await Promise.all([
    fetchJson('/api/stats'),
    fetchJson('/api/events?limit=20000'), // I55: plus de plafond 200 — fenêtre ?since= déleste le éventail complet
    fetchJson('/api/clusters')
  ]);
  fetchSpectrum(); // I63 : heatmap spectre (async, non bloquant)

  if (stats) {
    document.getElementById('statEvents').innerText = stats.total_events || 0;
    document.getElementById('statClusters').innerText = stats.total_clusters || 0;
    document.getElementById('statDbSize').innerText = stats.db_size_bytes ? (stats.db_size_bytes / 1024).toFixed(1) + ' Ko' : '0 Ko';
    document.getElementById('statAvgDur').innerText = stats.avg_dur ? stats.avg_dur.toFixed(2) + ' s' : '--';
  }

  if (events) {
    eventsData = events;
    { // I54 : bornes des données chargées, déclenche fetchWindow() si besoin
      const t0s = events.map((e) => e.t0);
      dataSince = t0s.length ? Math.min.apply(null, t0s) : null;
      dataUntil = t0s.length ? Math.max.apply(null, t0s) : null;
    }
  } // I58 : rendu unifie plus bas — drawTimelineFull() synchronise graphe ET tableau

  if (clusters) {
    clustersData = clusters;
    renderClustersTable(clusters);
    fillClusterFilter(clusters); // liste déroulante I41
  }
  await fetchWindow(); // I55 : tous les événements de la plage sélectionnée (plus de plafond figé)
  drawTimelineFull();
}

function chanOf(e) { // canal dominant, cohérent avec les badges du tableau
  return e.lvl_d > e.lvl_g + 2 ? 'd' : (Math.abs(e.lvl_g - e.lvl_d) <= 2 ? 'b' : 'l');
}

function filterEvents(list) {
  const only = document.getElementById('onlyLegal').checked;
  const chan = document.getElementById('chanFilter').value;
  const minLvl = parseFloat(document.getElementById('minLvlFilter').value || '0');
  const clu = document.getElementById('clusterFilter').value;
  return (list || []).filter(e =>
    (!only || e.over_legal) &&
    (chan === '' || chanOf(e) === chan) &&
    (Math.max(e.lvl_g, e.lvl_d) >= minLvl) &&
    (clu === '' || String(e.cluster) === clu));
}

function applyFilters() {
  drawTimelineFull(); // I58 : filtres → graphe + tableau synchronisés
}

function fillClusterFilter(clusters) {
  const sel = document.getElementById('clusterFilter');
  const prev = sel.value;
  sel.innerHTML = '<option value="">Tous clusters</option>' +
    (clusters || []).map(c => `<option value="${c.cluster_id}">#${c.cluster_id}</option>`).join('');
  if (prev !== '' && (clusters || []).some(c => String(c.cluster_id) === prev)) sel.value = prev;
}

function renderEventsTable(events) {
  const tbody = document.getElementById('eventsTableBody');
  if (!events || events.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; color:#94a3b8;">Aucun événement enregistré.</td></tr>';
    return;
  }
  const MAX_ROWS = 500; // I54 : plafond de lignes affichées dans le tableau
  let html = events.slice(0, MAX_ROWS).map((e) => renderTableRow(e)).join('');
  if (events.length > MAX_ROWS) {
    html += `<tr><td colspan="6" style="text-align:center; color:#94a3b8;">… + ${events.length - MAX_ROWS} événement(s) — filtrez ou zoomez pour restreindre</td></tr>`;
  }
  tbody.innerHTML = html;
}

function renderTableRow(e) { // I54 : une ligne d'événement (plafond 500 lignes affichées)
    let chBadge = '<span class="badge badge-ch-l">IN1 (Air)</span>';
    if (e.lvl_d > e.lvl_g + 2) chBadge = '<span class="badge badge-ch-r">IN2 (Struct)</span>';
    else if (Math.abs(e.lvl_g - e.lvl_d) <= 2) chBadge = '<span class="badge badge-ch-b">Les 2</span>';

    const olBadge = e.over_legal ? ' <span class="badge badge-over">▲ legal</span>' : '';
    return `<tr data-ev-id="${e.id}"${e.id === selectedEvId ? ' class="ev-row-selected"' : ''} onclick="selectEv(${e.id})">
      <td>${formatDate(e.t0)}</td>
      <td><strong>${e.freq.toFixed(1)} Hz</strong></td>
      <td>${chBadge}</td>
      <td>+${e.lvl_g.toFixed(1)} / +${e.lvl_d.toFixed(1)} dB</td>${olBadge}
      <td>${e.dur.toFixed(1)} s</td>
      <td><span class="badge badge-cluster" style="background:${getClusterColor(e.cluster)}22; color:${getClusterColor(e.cluster)}">#${e.cluster || '-'}</span></td>
    </tr>`;
}

function renderClustersTable(clusters) {
  const tbody = document.getElementById('clustersTableBody');
  if (!clusters || clusters.length === 0) {
    tbody.innerHTML = `<tr><td colspan="${EXEMPLARS_ENABLED ? 5 : 4}" style="text-align:center; color:#94a3b8;">Aucun cluster.</td></tr>`;
    return;
  }
  tbody.innerHTML = clusters.map(c => `<tr>
    <td><strong style="color:${getClusterColor(c.cluster_id)}">#${c.cluster_id}</strong></td>
    <td><strong>${c.event_count}</strong> ×</td>
    <td>${c.avg_freq} Hz</td>
    ${EXEMPLARS_ENABLED ? `<td><audio controls src="/api/exemplar/${c.cluster_id}"></audio></td>` : ''}
    <td>
      <button class="btn btn-sm btn-danger" onclick="triageCluster(${c.cluster_id}, 2)">Ignorer</button>
    </td>
  </tr>`).join('');
}

async function triageCluster(clusterId, flags) {
  const label = prompt("Label du cluster (optionnel)", "") ?? "";
  await fetch(`/api/clusters/${clusterId}/triage`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ flags, label })
  });
  refreshAll();
}

// Bornes de fréquence injectées côté serveur depuis la configuration DSP
// (placeholders __FREQ_MAX__ / __MIN_EVENT_HZ__ remplacés par BruitTrackHandler)
// — zéro magic number, axe Y couvre exactement 0..freq_max.
let FREQ_MAX = __FREQ_MAX__;
let MIN_EVENT_HZ = __MIN_EVENT_HZ__;
let showCh = { l: true, d: true };
let timelinePoints = []; // {x, y, ev} pour tooltips/clic
let timeWindow = 86400; // secondes affichées; null = Tout (plage calée sur les données)
let tlMode = null;     // null = fenêtre boutons; else {minT, span} en s (zoom brushing, I39)
let freqView = null;    // I54 : null = vue Y complète [0,FREQ_MAX]; sinon {fLo, fHi} en Hz
let tlScale = null;    // plage active {minT, span} pour conversion px→temps du brushing
let tlBrushPx = null;  // {x0, x1} rect de sélection pendant glisser (coords canvas)
let hoverYpx = null;   // I50 : Y du curseur (px logique) → fil horizontal de repère
let tlLastEvts = null; // I50 : dernières données dessinées (redraw crosshair sans refetch)
let lastVisible = []; // dernier jeu d'événements visibles (refilterable sans refetch)
let selectedEvId = null; // événement sélectionné : lien scatter ↔ tableau (I40)

function selectEv(id) {
  if (selectedEvId === id) id = null; // re-clic = désélection
  document.querySelectorAll('tr.ev-row-selected').forEach(r => r.classList.remove('ev-row-selected'));
  selectedEvId = id;
  if (selectedEvId != null) {
    const row = document.querySelector(`tr[data-ev-id="${selectedEvId}"]`);
    if (row) { row.classList.add('ev-row-selected'); row.scrollIntoView({block: 'nearest', behavior: 'smooth'}); }
  }
  drawTimelineFull(); // retrace le scatter + anneau de sélection
}

// I58 : SYNCHRONISATION graphe <-> tableau — lastVisible (dernier rendu du graphe) devient la source unique
function syncEventsToTable() {
  const rows = Array.prototype.slice.call(lastVisible).sort((a, b) => b.t0 - a.t0);
  renderEventsTable(rows);
}
function drawTimelineFull(shouldSyncTable = true) { // I59 : la source est TOUJOURS eventsData (brut) — lastVisible n'est qu'une SORTIE de vue ;
  drawTimeline(filterEvents(eventsData)); // le réutiliser en entrée amputait définitivement les points hors de la vue précédente (zoom → dézoom vide)
  if (shouldSyncTable) syncEventsToTable(); // false pour redraws cosmetiques (survol, pan, brush en cours) sans rebuild du tableau
}

function setTimeWin(seconds) {
  timeWindow = seconds;
  tlMode = null; // les boutons de fenêtre annulent le zoom au pinceau
  syncTlButtons();
  drawTimelineFull();
}

// Synchronise la mise en surbrillance des boutons avec la plage active (I39)
function syncTlButtons() {
  ['winBtn1h', 'winBtn6h', 'winBtn24h', 'winBtnTout'].forEach(id =>
    document.getElementById(id).classList.remove('btn-active'));
  if (tlMode) return; // zoom au pinceau actif : aucun bouton de fenêtre
  const active = {3600:'winBtn1h', 21600:'winBtn6h', 86400:'winBtn24h'}[timeWindow] || 'winBtnTout';
  document.getElementById(active).classList.add('btn-active');
}

const TZ_VIZ = 'Europe/Paris'; // I62 : fuseau horaire d'affichage (échelle X + badge), indépendant de la machine cliente

function parisMidnightBefore(tSec) { // UTC (s) du dernier minuit de Paris ≤ tSec (sans dépendance)
  const p = new Date(tSec * 1000).toLocaleString('sv-SE', { timeZone: TZ_VIZ }); // "AAAA-MM-JJ HH:MM:SS"
  const secs = Number(p.slice(11, 13)) * 3600 + Number(p.slice(14, 16)) * 60 + Number(p.slice(17, 19));
  return Math.round(tSec) - secs; // I62b : instant UTC du minuit local = t - temps de mur écoulé depuis ce minuit
}

function drawTimeTicks(ctx, w, h, minT, span) {
  // graduation axe X horodatée ; pas adaptatif pour ~90 px entre marqueurs
  let lastTickDay = null; // I62 : jour courant pour l'étiquette date
  const steps = [900, 1800, 3600, 7200, 21600, 86400]; // I62 : 144000 (40 h !) -> 86400 (24 h)
  let step = span / Math.max(3, Math.floor((w - 50) / 90));
  for (const s of steps) { if (step <= s) { step = s; break; } }
  if (step > span) step = Math.min(86400, Math.max(900, span / 4));
  const x0 = 40, x1 = w - 10;
  ctx.strokeStyle = '#334155';
  ctx.fillStyle = '#64748b';
  ctx.font = '12px monospace';
  ctx.textAlign = 'center';
  // I62 : pas ≥ 6 h ancré sur minuit PARIS (sinon multiples UTC -> changement de jour à 02:00 à l'écran)
  let t;
  if (step >= 21600) {
    const m0 = parisMidnightBefore(minT);
    t = m0 + Math.ceil((minT - m0) / step) * step;
    if (t === m0 && minT > m0) t = m0 + step; // crant strictement dans la fenêtre
  } else {
    t = Math.ceil(minT / step) * step;
  }
  for (; t <= minT + span; t += step) {
    const x = x0 + ((t - minT) / span) * (x1 - x0);
    if (x > x1) break;
    const xt = Math.round(x) + 0.5;   // graduation alignée half-pixel : net en HiDPI comme en QVGA
    ctx.strokeStyle = '#1e293b';      // I48 : grille verticale temps (alignée, subtile)
    sharpLine(ctx, xt, 20, xt, h - 20);
    ctx.strokeStyle = '#334155';
    ctx.beginPath(); ctx.moveTo(xt, h); ctx.lineTo(xt, h - 5); ctx.stroke();
    const d = new Date(t * 1000);
    // I62b : heure de PARIS 24 h ; le jour est INLINÉ sur la ligne des heures
    // (l'ancienne rangée date à h-21 empiétait sur le tracé et était masquée par les points)
    const time = d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZone: TZ_VIZ });
    const day = d.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', timeZone: TZ_VIZ });
    if (day !== lastTickDay) {
      ctx.fillStyle = '#94a3b8';
      ctx.fillText(day + ' ' + time, x, h - 9);
      ctx.fillStyle = '#64748b';
      lastTickDay = day;
    } else {
      ctx.fillText(time, x, h - 9);
    }
  }
  ctx.textAlign = 'left';
}

function toggleChannel(idx) {
  if (idx === 0) showCh.l = !showCh.l; else showCh.d = !showCh.d;
  document.getElementById('toggleChG').style.opacity = showCh.l ? '1' : '.4';
  document.getElementById('toggleChD').style.opacity = showCh.d ? '1' : '.4';
  drawTimelineFull(); // I58 : toggle de canal → graphe + tableau synchronisés
}

function hideEvtTip() {
  document.getElementById('evtTip').style.display = 'none';
  const ft = document.getElementById('freqTip'); if (ft) ft.style.display = 'none';
  // I50 : nettoyage du fil de repère sans boucle (redraw seulement si le fil était actif)
  if (hoverYpx !== null && tlLastEvts !== null) { hoverYpx = null; drawTimelineFull(false); } // I59 : idem, cosmétique uniquement
}

// Click/hover sur marker → tooltip bin_i + freq + lvl_g/d (acceptance IMPROVEMENTS)
(function attachTips() {
  const canvas = document.getElementById('timelineCanvas');
  let raf = null, hoverRaf = 0;
  function showTip(e) {
    const rect = canvas.getBoundingClientRect();
    // Espace logique = pixels CSS (le backing store hi-DPI est mis à l'échelle
    // via setTransform dans drawTimeline), donc mapping direct client→logique.
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;

    // I49 : repère de fréquence exact sous le curseur (lecture directe de l'échelle, sans zoom)
    const ft = document.getElementById('freqTip');
    const hCSS = TL_CSS_H;
    if (mx >= 40 && mx <= TL_CKWW - 10 && my >= 20 && my <= hCSS - 20) {
      const fUnder = yToFreq(my); // I54 : la lecture Hz suit la vue Y zoomée (sinon 0..FREQ_MAX)
      ft.textContent = '≈ ' + fUnder.toFixed(1) + ' Hz';
      ft.style.display = 'inline';
    } else { ft.style.display = 'none'; }

    // I50 : fil horizontal à la hauteur du curseur (redraw throttle rAF, saut si inchangé)
    const ly = my >= 20 && my <= TL_CSS_H - 20 ? Math.round(my) : null;
    if (ly !== hoverYpx) { hoverYpx = ly; if (!hoverRaf) hoverRaf = requestAnimationFrame(() => { hoverRaf = 0; drawTimelineFull(false); }); } // I59 : survol = pas de rebuild tableau

    let best = null, bd = 10 * 10; // rayon 10 px
    for (const p of timelinePoints) {
      const dx = p.x - mx, dy = p.y - my;
      const dd = dx * dx + dy * dy;
      if (dd < bd) { bd = dd; best = p; }
    }
    const tip = document.getElementById('evtTip');
    if (!best) { hideEvtTip(); return; }
    const ev = best.ev;
    tip.textContent = `#${ev.cluster || '-'} · bin ${ev.bin_i} (${ev.freq.toFixed(2)} Hz) · G +${ev.lvl_g.toFixed(1)} / D +${ev.lvl_d.toFixed(1)} dB` + (ev.over_legal ? ' · ▲ legal' : '');
    tip.style.display = 'inline';
    return ev; // I40 : point cliquable → lien avec le tableau
  }
  canvas.addEventListener('mousemove', showTip);
  canvas.addEventListener('click', function (e) {
    // clic = détail conservé 6 s après le mouvement de souris
    const selEv = showTip(e); // I40 : clic sur un point → surbrillance ligne
    if (selEv) selectEv(selEv.id);
    const tip2 = document.getElementById('evtTip');
    if (tip2.textContent) { tip2.dataset.sticky = '1'; setTimeout(function () { if (tip2.dataset.sticky === '1') hideEvtTip(); }, 6000); }
  });
  canvas.addEventListener('mouseleave', hideEvtTip);
})();

function freqBounds() { // I54 : limites de la vue Y courante [fLo, fHi]
  return freqView ? [freqView.fLo, freqView.fHi] : [0, FREQ_MAX];
}
function yOfFreq(f) { // Hz → px logique Y ; l'axe couvre [fLo, fHi] de la vue courante
  const h = TL_CKVH;
  const fb = freqBounds();
  const fc = Math.max(fb[0], Math.min(fb[1], f));
  return h - 20 - ((fc - fb[0]) / (fb[1] - fb[0])) * (h - 40);
}
function yToFreq(y) { // px logique Y → Hz (inverse exact de yOfFreq, borné à la vue courante) — I61c : l'ancienne formule était le miroir vertical (ancre molette inversée)
  const h = TL_CKVH;
  const fb = freqBounds();
  return Math.max(fb[0], Math.min(fb[1], fb[0] + ((h - 20 - y) / (h - 40)) * (fb[1] - fb[0])));
}

// 'Nice step' : ~5-6 divisions lisibles quel que soit FREQ_MAX (1,2,5 × 10^n)
function niceHzStep(rough) {
  const p = Math.pow(10, Math.floor(Math.log10(Math.max(rough, 1e-9))));
  for (const m of [1, 2, 5, 10]) { if (m * p >= rough) return m * p; }
  return 10 * p;
}

// Ligne crête : alignement half-pixel pour des traits de 1 px nets (pas flous)
function sharpLine(ctx, x0, y0, x1, y1) {
  ctx.beginPath();
  ctx.moveTo(Math.round(x0) + 0.5, Math.round(y0) + 0.5);
  ctx.lineTo(Math.round(x1) + 0.5, Math.round(y1) + 0.5);
  ctx.stroke();
}

function axZoom(ev) { // I61 : molette = zoom/dézoom sur l'axe Y SEUL, centré sur la fréquence sous le curseur
  const r = ev.currentTarget.getBoundingClientRect();
  const mx = ev.clientX - r.left, my = ev.clientY - r.top;
  if (my < 20 || my > TL_CKVH - 20 || mx < 40) return; // zone utile uniquement
  ev.preventDefault(); // I59 : la molette zoome, elle ne doit ni scroller la page ni zoomer le navigateur (listener non-passif)
  const k = ev.deltaY < 0 ? 1 / 1.3 : 1.3;              // facteur fixe par crant ±1.3
  // ---- Axe Y seul : ancrage = fréquence sous le curseur ; span ≥ 2 Hz ; [fLo,fHi] ⊂ [0, FREQ_MAX]
  const fb0 = freqBounds();
  const anchF = yToFreq(my);
  let nLo = anchF - (anchF - fb0[0]) * k;
  let nHi = anchF + (fb0[1] - anchF) * k;
  // I61b : clamp span min RÉPARTI autour de l'ancre (l'ancien recentrage sur le centre
  // géométrique faisait dériver la vue d'un crant à chaque fois une fois le plancher atteint)
  if (nHi - nLo < 2) {
    const frac = fb0[1] > fb0[0] ? Math.min(1, Math.max(0, (anchF - fb0[0]) / (fb0[1] - fb0[0]))) : 0.5;
    nLo = anchF - 2 * frac;
    nHi = anchF + 2 * (1 - frac);
  }
  if (nLo < 0) { nHi -= nLo; nLo = 0; }
  if (nHi > FREQ_MAX) { nLo -= nHi - FREQ_MAX; nHi = FREQ_MAX; }
  if (nLo < 0) nLo = 0;
  const EPSF = 0.01; // I59 : tolérance float large (0,01 Hz, invisible à l'écran) — sinon drift accumulé ≠ reset de la vue pleine
  freqView = (Math.abs(nHi - fb0[1]) > EPSF && Math.abs(nLo - fb0[0]) > EPSF) ? {fLo: nLo, fHi: nHi}
             : (Math.abs(nHi - FREQ_MAX) < EPSF && Math.abs(nLo) < EPSF ? null : {fLo: nLo, fHi: nHi});
  drawTimelineFull(false); // I61 : redraw cosmétique (survol/pan Y) sans rebuild tableau ; sync au prochain cycle complet
}
function drawTimeline(events) {
  updateZoomBadge(); // I54 : badge toujours en phase avec les vues courantes

  const canvas = document.getElementById('timelineCanvas');
  const ctx = canvas.getContext('2d');
  // I63f : PAS de hideEvtTip() ici — appelé à chaque redraw de survol (rAF du fil
  // de repère), il masquait le tooltip ~16 ms après chaque mousemove (bug préexistant,
  // démontré identique sur le HTML pré-I63 en headless). Le masquage est géré par
  // mouseleave et par showTip(!best) quand le curseur quitte les points.
  timelinePoints.length = 0;
  lastVisible = Array.isArray(events) ? events : [];

  // Hi-DPI : le backing store est dimensionné sur (taille CSS × devicePixelRatio)
  // et tout est dessiné en pixels CSS via setTransform → échelles/netteté fines.
  const dpr = window.devicePixelRatio || 1;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const w = TL_CKWW;      // largeur logique en px CSS
  const h = TL_CKVH;      // hauteur logique fixe (px CSS)

  ctx.clearRect(0, 0, w, h);

  // Grille d'arrière-plan + échelle Y dynamique bornée à FREQ_MAX
  ctx.lineWidth = 1;
  const fv = freqBounds();
  const stepHz = niceHzStep((fv[1] - fv[0]) / 5);
  for (let f = fv[0]; f <= fv[1] + 1e-9; f += stepHz) {
    const y = yOfFreq(Math.max(fv[0], Math.min(f, fv[1]))); // graduations sur la vue Y (I54)
    ctx.strokeStyle = '#1e293b';
    sharpLine(ctx, 40, y, w - 10, y);
    ctx.fillStyle = '#94a3b8';
    ctx.font = '12px monospace';
    ctx.textAlign = 'right';
    ctx.fillText(Math.round(f) + ' Hz', 36, y + 4);
  }
  ctx.textAlign = 'left';

  // Seuil Min fiable (Paramètre min_event_hz) : ligne pointillée de repéraison
  if (MIN_EVENT_HZ > 0 && MIN_EVENT_HZ < FREQ_MAX) {
    const ym = yOfFreq(MIN_EVENT_HZ);
    ctx.strokeStyle = 'rgba(245,158,11,.35)';
    ctx.setLineDash([4, 4]);
    sharpLine(ctx, 40, ym, w - 10, ym);
    ctx.setLineDash([]);
    ctx.fillStyle = 'rgba(245,158,11,.6)';
    ctx.font = '11px monospace';
    ctx.textAlign = 'right';
    ctx.fillText('f_min ' + MIN_EVENT_HZ + ' Hz', 36, ym - 4);
    ctx.textAlign = 'left';
  }

  // I50 : fil horizontal pointillé à la hauteur du curseur = comparaison immédiate avec l'échelle
  if (hoverYpx != null && hoverYpx >= 20 && hoverYpx <= h - 20) {
    ctx.strokeStyle = 'rgba(147,197,253,.45)';
    ctx.setLineDash([3, 3]);
    sharpLine(ctx, 40, hoverYpx, w - 10, hoverYpx);
    ctx.setLineDash([]);
  }

  if (!events || events.length === 0) { lastVisible = []; } // état vide affiché au centre (I48)

  const evs = Array.isArray(events) ? events : [];

  const now = Date.now() / 1000;
  let timeSpan, minT;
  if (tlMode) { // zoom/brushing : plage fixe choisie par l'utilisateur (I39/I58b) — prioritaire
    // même si la fenêtre contient zéro événement : l'ancrage du zoom doit rester stable,
    // sinon chaque redraw recentre sur Date.now() et le point sous le curseur dérive.
    timeSpan = tlMode.span; minT = tlMode.minT;
  } else if (evs.length === 0) { // I48 : graphe vide → horizon 6 h (bootstrap uniquement)
    timeSpan = 21600; minT = now - timeSpan;
  } else if (timeWindow) { // fenêtre glissante 1h/6h/24h
    timeSpan = timeWindow; minT = now - timeWindow;
  } else { // Tout : plage recouvrant tous les événements + horizon présent
    const ts = evs.map(e => e.t0);
    const maxT = Math.max(now, ...ts);
    const minTAll = Math.min(...ts);
    minT = minTAll; timeSpan = Math.max(3600, maxT - minT);
  }
  tlScale = {minT, span: timeSpan}; // conversion px→temps pour le zoom (I39)
  const fvw = freqBounds(); // I54 : vue Y courante [fLo, fHi]
  tlLastEvts = evs;
  // I58 SELECTION UNIQUE : le graphe et le tableau affichent strictement le meme ensemble (temps ∩ freqView ∩ canaux)
  const chOk = (e) => {
    const onL = !(e.lvl_d > e.lvl_g + 2), onD = !(e.lvl_g > e.lvl_d + 2);
    return (showCh.l && onL) || (showCh.d && onD);
  };
  lastVisible = evs.filter(e =>
    e.t0 >= minT - 1e-9 && e.t0 <= minT + timeSpan + 1e-9 &&
    e.freq >= fvw[0] && e.freq <= fvw[1] && chOk(e));
  const visId = new Set(lastVisible.map(e => e.id));
  drawTimeTicks(ctx, w, h, minT, timeSpan);

  evs.forEach(e => {
    if (!visId.has(e.id)) return; // I58 : seul le set synchronise avec le tableau est dessine
    const x = 40 + ((e.t0 - minT) / timeSpan) * (w - 50);
    const y = yOfFreq(e.freq);

    // toggles de canal: canal caché si l'autre domine de > 2 dB sur celui-ci
    const onL = !(e.lvl_d > e.lvl_g + 2);
    const onD = !(e.lvl_g > e.lvl_d + 2);
    if (!(showCh.l && onL) && !(showCh.d && onD)) return; // 'return' (pas 'continue') : on est dans un callback forEach

    if (x >= 40 && x <= w) {
      timelinePoints.push({x, y, ev: e});
      const radius = Math.max(3, Math.min(10, (e.lvl_g + e.lvl_d) / 6));
      ctx.beginPath();
      ctx.arc(x, y, radius, 0, Math.PI * 2);
      ctx.fillStyle = getClusterColor(e.cluster);
      ctx.globalAlpha = 0.85;
      ctx.fill();
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 0.5;
      ctx.stroke();
      ctx.globalAlpha = 1.0;
    }
  });

  if (selectedEvId != null) { // anneau sur le point sélectionné (I40)
    const sp = timelinePoints.find(p => p.ev.id === selectedEvId);
    if (sp) {
      ctx.beginPath();
      ctx.arc(sp.x, sp.y, 12, 0, Math.PI * 2);
      ctx.strokeStyle = '#f59e0b';
      ctx.lineWidth = 2;
      ctx.setLineDash([4, 3]);
      ctx.stroke();
      ctx.setLineDash([]);
    }
  }

  if (tlBrushPx) { // rect de sélection du brushing → relâcher verrouille la plage
    const bx0 = Math.max(40, tlBrushPx.x0);
    const bx1 = Math.min(w - 10, tlBrushPx.x1);
    if (bx1 > bx0) {
      ctx.fillStyle = 'rgba(59,130,246,0.25)';
      ctx.fillRect(bx0, 20, bx1 - bx0, h - 40);
      ctx.strokeStyle = '#3b82f6';
      ctx.lineWidth = 1;
      ctx.strokeRect(Math.round(bx0) + 0.5, 20.5, Math.round(bx1 - bx0), h - 41);
    }
  }
  if (timelinePoints.length === 0) { // I48 : état vide lisible au centre du graphe
    ctx.fillStyle = '#64748b';
    ctx.font = '13px monospace';
    ctx.textAlign = 'center';
    ctx.fillText('Aucun événement visible sur la plage affichée', w / 2, h / 2 - 10);
    ctx.textAlign = 'left';
  }

  drawSpecPanel(); // I63 : heatmap spectre alignée sur la même échelle temps (tlScale à jour)
}

// ===== I63 : historique spectre — heatmap bandes log sous la timeline =====
// Config injectée côté serveur (placeholders remplacés par BruitTrackHandler).
const SPEC = { enabled: __SPEC_ENABLED__, bands: __SPEC_BANDS__, dbMin: __SPEC_DB_MIN__, dbRange: __SPEC_DB_RANGE__ };
const EXEMPLARS_ENABLED = __EXEMPLARS_ENABLED__;
let specRows = [];
let specShow = true;
let specEdges = null;

function toggleSpectrum() {
  if (!SPEC.enabled) return;
  specShow = !specShow;
  document.getElementById('toggleSpec').classList.toggle('btn-active', specShow);
  document.getElementById('specCanvas').style.display = specShow ? 'block' : 'none';
  drawTimelineFull();
}

async function fetchSpectrum() {
  if (!SPEC.enabled) return;
  // Plafond 20000 lignes ≈ 14 jours à 1 ligne/min (au-delà : zoomer puis recharger)
  const got = await fetchJson('/api/spectrum?limit=20000');
  if (got && Array.isArray(got.rows)) specRows = got.rows;
}

function specBandEdge(i) { // bords linéaires identiques au serveur (SpectrumAggregator.band_edges)
  return MIN_EVENT_HZ + (FREQ_MAX - MIN_EVENT_HZ) * (i / SPEC.bands);
}

function specColor(t) { // noir -> bleu -> cyan -> jaune
  if (t < 1 / 3) { const k = t * 3; return 'rgb(' + Math.round(8 + k * 30) + ',' + Math.round(12 + k * 60) + ',' + Math.round(18 + k * 140) + ')'; }
  if (t < 2 / 3) { const k = t * 3 - 1; return 'rgb(' + Math.round(38 + k * 40) + ',' + Math.round(72 + k * 110) + ',' + Math.round(158 + k * 90) + ')'; }
  const k = t * 3 - 2; return 'rgb(' + Math.round(78 + k * 177) + ',' + Math.round(182 + k * 73) + ',' + Math.round(248 - k * 184) + ')';
}

// Cache du rendu heatmap : le redraw de survol de la timeline (rAF par mousemove)
// appelle drawSpecPanel à chaque frame — décoder des milliers de blobs + retracer
// ~500k rects par frame rendait le tooltip d'événement inutilisable (I63e).
// Cellules peintes UNE fois hors-écran, blittées en 1 drawImage tant que
// (vue, données, canaux, dpr) ne changent pas ; seuls labels/dash redessinent.
let specCache = { key: null, cv: null };

function drawSpecPanel() { // dessinée après drawTimeline : réutilise tlScale (même axe X)
  const cv = document.getElementById('specCanvas');
  if (!cv || !SPEC.enabled || !tlScale) return;
  cv.style.display = specShow ? 'block' : 'none';
  const bar = document.getElementById('specBar');
  if (bar) bar.style.display = specShow ? 'block' : 'none';
  if (!specShow) return;
  const dpr = window.devicePixelRatio || 1;
  const wCss = TL_CKWW, hCss = 150;
  const bw = Math.round(wCss * dpr), bh = Math.round(hCss * dpr);
  if (cv.width !== bw || cv.height !== bh) { cv.width = bw; cv.height = bh; }
  const ctx = cv.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  const minT = tlScale.minT, span = tlScale.span;
  const lastT = specRows.length ? specRows[specRows.length - 1].t0 : 0;
  const key = [minT, span, wCss, hCss, dpr, specRows.length, lastT, showCh.l, showCh.d].join('|');

  if (specCache.key !== key) { // recompute complet UNIQUEMENT sur changement réel
    if (!specCache.cv) specCache.cv = document.createElement('canvas');
    const off = specCache.cv;
    if (off.width !== bw || off.height !== bh) { off.width = bw; off.height = bh; }
    const octx = off.getContext('2d');
    octx.setTransform(dpr, 0, 0, dpr, 0, 0);
    octx.clearRect(0, 0, wCss, hCss);
    octx.fillStyle = '#080c12'; octx.fillRect(0, 0, wCss, hCss);

    const x0 = 40, x1 = wCss - 10;
    // I64c : axe Y linéaire, même échelle que la timeline
    const yOfHz = (f) => 4 + (FREQ_MAX - Math.min(Math.max(f, MIN_EVENT_HZ), FREQ_MAX)) / (FREQ_MAX - MIN_EVENT_HZ) * (hCss - 8);

    if (!specRows.length) { // état vide
      octx.fillStyle = '#64748b'; octx.font = '12px monospace'; octx.textAlign = 'center';
      octx.fillText("Pas encore d'historique spectre", wCss / 2, hCss / 2);
      octx.textAlign = 'left';
    }

  const qOf = (raw, b) => { // max des canaux visibles pour la bande b
    if (showCh.l && showCh.d) return Math.max(raw.charCodeAt(b * 4 + 1), raw.charCodeAt(b * 4 + 3));
    if (showCh.l) return raw.charCodeAt(b * 4 + 1);
    return raw.charCodeAt(b * 4 + 3);
  };

  // Contraste AUTO PAR BANDE : chaque bande est étirée sur sa propre plage
  // p5..p95 visibles. Une normalisation globale écrase les bandes calmes au noir
  // (pente spectrale naturelle ~20 dB entre bandes — retour terrain I63d).
  const vis = [];
  const qsPerBand = Array.from({ length: SPEC.bands }, () => []);
  for (const r of specRows) {
    const tEnd = r.t0 + r.dur;
    if (tEnd < minT || r.t0 > minT + span) continue;
    if (!r._raw) r._raw = atob(r.data); // décodage mémoïsé par ligne
    vis.push(r);
    for (let b = 0; b < r.n_bands; b++) { const q = qOf(r._raw, b); if (q > 0) qsPerBand[b].push(q); }
  }
  const bandRange = qsPerBand.map(function (qs) {
    if (!qs.length) return null;
    qs.sort(function (a, b) { return a - b; });
    const pk = function (k) { return qs[Math.min(qs.length - 1, Math.floor(k * qs.length))]; };
    let lo = Math.max(1, pk(0.05)), hi = pk(0.95);
    if (hi <= lo + 2) { lo = Math.max(0, hi - 8); } // bande plate : garde minimale
    return [lo, hi];
  });

  // Bords Y précalculés (indépendants des données)
  const yEdges = [];
  for (let b = 0; b <= SPEC.bands; b++) yEdges.push(Math.round(yOfHz(specBandEdge(b))));

  for (const r of vis) {
    const tEnd = r.t0 + r.dur;
    let xa = Math.max(x0, x0 + ((r.t0 - minT) / span) * (x1 - x0));
    const xb = Math.min(x1, x0 + ((tEnd - minT) / span) * (x1 - x0));
    if (xb <= xa) continue;
    const colW = Math.max(1, xb - xa);
    for (let b = 0; b < r.n_bands; b++) {
      const q = qOf(r._raw, b);
      const yT = Math.min(yEdges[b], yEdges[b + 1]), hh = Math.max(1, Math.abs(yEdges[b + 1] - yEdges[b]));
      const rng = bandRange[b];
      // Bande sans donnée ou plate : teinte neutre discrète (pas de faux signal)
      const t = !rng ? 0 : Math.max(0, Math.min(1, (q - rng[0]) / (rng[1] - rng[0])));
      octx.fillStyle = specColor(t);
      octx.fillRect(xa, yT, colW, hh);
    }
  }
  specCache.key = key;
  }

  // Blit 1:1 du cache + habillage léger (labels, dash) à chaque frame
  ctx.clearRect(0, 0, wCss, hCss);
  ctx.drawImage(specCache.cv, 0, 0, wCss, hCss);

  // I64c : idem yOfHz mais hors du bloc cache (portée différente)
  const yOfHz2 = (f) => 4 + (FREQ_MAX - Math.min(Math.max(f, MIN_EVENT_HZ), FREQ_MAX)) / (FREQ_MAX - MIN_EVENT_HZ) * (hCss - 8);

  // Limite f_min (même repère pointillé que la timeline) — au-dessus des cellules
  const yMin = Math.round(yOfHz2(MIN_EVENT_HZ));
  ctx.strokeStyle = 'rgba(245,158,11,.5)';
  ctx.setLineDash([4, 4]);
  ctx.beginPath(); ctx.moveTo(40, yMin + 0.5); ctx.lineTo(wCss - 10, yMin + 0.5); ctx.stroke();
  ctx.setLineDash([]);

  // Étiquettes Hz sur pas « nice » (échelle linéaire I64c) — y borné au canvas
  ctx.fillStyle = '#94a3b8'; ctx.font = '11px monospace'; ctx.textAlign = 'right';
  const hzStep = niceHzStep((FREQ_MAX - MIN_EVENT_HZ) / 4);
  for (let f = Math.ceil(MIN_EVENT_HZ / hzStep) * hzStep; f <= FREQ_MAX + 1e-6; f += hzStep)
    ctx.fillText(f + ' Hz', 36, Math.min(hCss - 2, yOfHz2(f) + 4));
  ctx.textAlign = 'left';
}

// ===== Zoom par brushing sur la timeline (I39) : glisser = plage temps, double-clic/Esc = réinit =====
(function () {
  const canvas = document.getElementById('timelineCanvas');
  if (!canvas) return;
  let dragX0 = null;
  let raf = 0;
  const drawSoon = () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(() => drawTimelineFull(false)); }; // I59 : brush en cours = dessin seul ; sync au mouseup (refreshWindowed)
  const toCanvasX = (e) => { // espace logique = px CSS (setTransform hi-DPI actif)
    const r = canvas.getBoundingClientRect();
    return e.clientX - r.left;
  };
  canvas.addEventListener('mousedown', (e) => { // I59 : Ctrl+glisser = pan fréquence, boutons droit/milieu = rien — jamais un brush temps parasite
    if (e.ctrlKey || e.button !== 0) return;
    dragX0 = toCanvasX(e); tlBrushPx = null;
  });
  canvas.addEventListener('mousemove', (e) => {
    if (dragX0 === null) return;
    const x1 = toCanvasX(e);
    if (Math.abs(x1 - dragX0) > 6) { // seuil px pour distinguer glisser de clic
      tlBrushPx = {x0: Math.min(dragX0, x1), x1: Math.max(dragX0, x1)};
      drawSoon();
    }
  });
  document.addEventListener('mouseup', () => {
    if (dragX0 === null) return;
    dragX0 = null;
    if (tlBrushPx && tlScale) {
      const toTime = (xp) => tlScale.minT + ((xp - 40) / (TL_CKWW - 50)) * tlScale.span; // I55 fix: canvas.width = px device (HiDPI), brush en px CSS
      const t0 = toTime(tlBrushPx.x0), t1 = toTime(tlBrushPx.x1);
      if (t1 - t0 >= 60) { tlMode = {minT: t0, span: Math.max(120, (t1 - t0) * 1.1)}; syncTlButtons(); }
    }
    tlBrushPx = null;
    refreshWindowed(); // I54 : fenêtre dynamique si le zoom brushing est actif
  });
  canvas.addEventListener('dblclick', resetFviews); // I54 : double-clic réinitialise X + Y
  window.addEventListener('keydown', (e) => { // Échap : réinitialise les vues I54
    if (e.key === 'Escape') resetFviews();
  });
})();

// ===== Molette : zoom axe Y ancré curseur (I61) ; double-clic/Echap réinitialisent =====
(function () {
  const canvas = document.getElementById('timelineCanvas');
  if (!canvas) return;
  canvas.addEventListener('wheel', axZoom, { passive: false }); // I59 : preventDefault possible dans axZoom (pas de scroll/zoom page concurrent)
})();

// ===== Hi-DPI : le backing store suit la largeur réelle et devicePixelRatio =====
const TL_CSS_H = 260;
let TL_CKWW = 1000;      // largeur logique (px CSS), init = fallback canvas
let TL_CKVH = 260;

function fitCanvas() {
  const canvas = document.getElementById('timelineCanvas');
  if (!canvas) return;
  const dpr = window.devicePixelRatio || 1;
  const r = canvas.getBoundingClientRect();
  const cw = Math.max(320, r.width || 0);
  canvas.width = Math.round(cw * dpr);   // backing store natif (net sur écrans rétina)
  canvas.height = Math.round(TL_CSS_H * dpr);
  TL_CKWW = cw;
  TL_CKVH = TL_CSS_H;
  drawTimelineFull();
}
window.addEventListener('resize', () => requestAnimationFrame(fitCanvas));

// Initial : fit hi-DPI puis fetch + poll every 10s
// Exemplaires désactivés : on retire aussi la colonne Audio du tableau
if (!EXEMPLARS_ENABLED) { const th = document.getElementById('audioTh'); if (th) th.remove(); }
requestAnimationFrame(() => { fitCanvas(); refreshAll(); });
setInterval(refreshAll, 10000);
</script>
</body>
</html>
"""


class BruitTrackHandler(http.server.BaseHTTPRequestHandler):
    """HTTP Request Handler for BruitTrack."""

    store: EventStore
    config: Config

    def _send_json(self, data: Any, status: int = 200) -> None:
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        if path in ("/", "/index.html"):
            # Injection des bornes DSP configurées (zéro magic number client)
            payload = (
                HTML_DASHBOARD.replace("__FREQ_MAX__", f"{self.config.dsp.freq_max:g}")
                .replace("__MIN_EVENT_HZ__", f"{self.config.dsp.min_event_hz:g}")
                .replace("__SPEC_ENABLED__", "true" if self.config.spectrum.enabled else "false")
                .replace("__SPEC_BANDS__", str(self.config.spectrum.n_bands))
                .replace("__SPEC_DB_MIN__", f"{self.config.spectrum.db_min:g}")
                .replace("__SPEC_DB_RANGE__", f"{self.config.spectrum.db_range:g}")
                .replace(
                    "__EXEMPLARS_ENABLED__",
                    "true" if self.config.storage.record_exemplars else "false",
                )
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if path == "/api/health":
            try:
                total = self.store.get_stats()["total_events"]
                self._send_json({"ok": True, "events_db_rows": total})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, status=500)
            return

        if path == "/api/stats":
            stats = self.store.get_stats()
            self._send_json(stats)
            return

        if path == "/api/events":
            try:
                limit = int(qs.get("limit", [100])[0])
                offset = int(qs.get("offset", [0])[0])
                since = float(qs["since"][0]) if "since" in qs else None
                cluster = int(qs["cluster"][0]) if "cluster" in qs else None
                order = qs.get("order", ["desc"])[0]
            except (ValueError, IndexError):
                self.send_error(400, "Paramètre de requête invalide")
                return
            if limit <= 0 or offset < 0:
                self.send_error(400, "limit doit > 0 et offset >= 0")
                return
            if order not in ("asc", "desc"):
                self.send_error(400, "order doit valoir 'asc' ou 'desc'")
                return
            events = self.store.get_events(
                limit=limit, offset=offset, since=since, cluster=cluster, order=order
            )
            self._send_json(events)
            return

        if path == "/api/clusters":
            clusters = self.store.get_clusters_summary()
            self._send_json(clusters)
            return

        if path == "/api/spectrum":
            try:
                since_spec = float(qs["since"][0]) if "since" in qs else None
                until_spec = float(qs["until"][0]) if "until" in qs else None
                limit_spec = int(qs.get("limit", [20000])[0])
            except (ValueError, IndexError):
                self.send_error(400, "Paramètre de requête invalide")
                return
            if limit_spec <= 0:
                self.send_error(400, "limit doit > 0")
                return
            self._send_json(
                {
                    "rows": self.store.get_spectrum(
                        since=since_spec, until=until_spec, limit=limit_spec
                    )
                }
            )
            return

        if path.startswith("/api/exemplar/"):
            # Format: /api/exemplar/<cluster_id>
            try:
                cluster_id = int(path.split("/")[-1])
                raw_file = Path(self.config.storage.exemplars_dir) / f"ex_{cluster_id}.raw"
                if raw_file.is_file():
                    wav_bytes = create_wav_from_raw(raw_file, sample_rate=1000)
                    self.send_response(200)
                    self.send_header("Content-Type", "audio/wav")
                    self.send_header("Content-Length", str(len(wav_bytes)))
                    self.end_headers()
                    self.wfile.write(wav_bytes)
                    return
                else:
                    self.send_error(404, "Exemplar audio not found")
                    return
            except Exception as e:
                self.send_error(500, f"Error generating WAV: {e}")
                return

        self.send_error(404, "Not Found")

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path.startswith("/api/clusters/") and path.endswith("/triage"):
            try:
                parts = path.strip("/").split("/")
                cluster_id = int(parts[2])
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8")
                payload = json.loads(body)

                flags = int(payload.get("flags", 0))
                label = payload.get("label")

                success = self.store.set_cluster_triage(cluster_id, flags, label)
                self._send_json({"success": success, "cluster_id": cluster_id})
                return
            except Exception as e:
                self._send_json({"error": str(e)}, status=400)
                return

        self.send_error(404, "Not Found")

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress noisy HTTP request logs to keep terminal clean
        pass


def run_viz_server(config: Config, store: EventStore | None = None) -> None:
    """Start the standalone web visualization server."""
    if store is None:
        store = EventStore(
            db_path=config.storage.db_path,
            batch_size=config.storage.batch_size,
            batch_timeout_s=config.storage.batch_timeout_s,
        )

    handler = BruitTrackHandler
    handler.store = store
    handler.config = config

    server = http.server.ThreadingHTTPServer((config.viz.host, config.viz.port), handler)
    print(f"Serveur de visualisation BruitTrack actif : http://{config.viz.host}:{config.viz.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt du serveur de visualisation.")
    finally:
        server.server_close()
