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
    <span style="opacity:.4">|</span>
    <button id="winBtn1h" class="btn btn-sm" onclick="setTimeWin(3600,this)">1h</button>
    <button id="winBtn6h" class="btn btn-sm" onclick="setTimeWin(21600,this)">6h</button>
    <button id="winBtn24h" class="btn btn-sm btn-active" onclick="setTimeWin(86400,this)">24h</button>
    <button id="winBtnTout" class="btn btn-sm" onclick="setTimeWin(null,this)">Tout</button>
    <span style="opacity:.4; font-size:12px; font-family:monospace">glisser = zoom temps · double-clic / Échap = réinit</span>
    <span id="evtTip" style="font-family:monospace; font-size:12px; color:#e2e8f0; background:#1e293b; border-radius:4px; padding:2px 8px; display:none;"></span>
  </div>
  <canvas id="timelineCanvas" width="1000" height="260"></canvas>
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
            <th>Audio</th>
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

function formatDate(unixSec) {
  if (!unixSec) return "--";
  const d = new Date(unixSec * 1000);
  return d.toLocaleTimeString() + " " + d.toLocaleDateString();
}

function getClusterColor(clusterId) {
  if (!clusterId) return "#94a3b8";
  const hue = (clusterId * 137.5) % 360;
  return `hsl(${hue}, 80%, 60%)`;
}

async function refreshAll() {
  const [stats, events, clusters] = await Promise.all([
    fetchJson('/api/stats'),
    fetchJson('/api/events?limit=200'),
    fetchJson('/api/clusters')
  ]);

  if (stats) {
    document.getElementById('statEvents').innerText = stats.total_events || 0;
    document.getElementById('statClusters').innerText = stats.total_clusters || 0;
    document.getElementById('statDbSize').innerText = stats.db_size_bytes ? (stats.db_size_bytes / 1024).toFixed(1) + ' Ko' : '0 Ko';
    document.getElementById('statAvgDur').innerText = stats.avg_dur ? stats.avg_dur.toFixed(2) + ' s' : '--';
  }

  if (events) {
    eventsData = events;
    const visible = filterEvents(events); // filtres rapides I41 + légal
    renderEventsTable(visible);
    drawTimeline(visible);
  }

  if (clusters) {
    clustersData = clusters;
    renderClustersTable(clusters);
    fillClusterFilter(clusters); // liste déroulante I41
  }
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
  const visible = filterEvents(eventsData);
  renderEventsTable(visible);
  drawTimeline(visible);
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
  tbody.innerHTML = events.map(e => {
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
  }).join('');
}

function renderClustersTable(clusters) {
  const tbody = document.getElementById('clustersTableBody');
  if (!clusters || clusters.length === 0) {
    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; color:#94a3b8;">Aucun cluster.</td></tr>';
    return;
  }
  tbody.innerHTML = clusters.map(c => `<tr>
    <td><strong style="color:${getClusterColor(c.cluster_id)}">#${c.cluster_id}</strong></td>
    <td><strong>${c.event_count}</strong> ×</td>
    <td>${c.avg_freq} Hz</td>
    <td>
      <audio controls src="/api/exemplar/${c.cluster_id}" preload="none"></audio>
    </td>
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
let tlScale = null;    // plage active {minT, span} pour conversion px→temps du brushing
let tlBrushPx = null;  // {x0, x1} rect de sélection pendant glisser (coords canvas)
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

function drawTimelineFull() { return drawTimeline(lastVisible.length ? lastVisible : eventsData); }

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

function drawTimeTicks(ctx, w, h, minT, span) {
  // graduation axe X horodatée ; pas adaptatif pour ~90 px entre marqueurs
  const steps = [900, 1800, 3600, 7200, 21600, 144000];
  let step = span / Math.max(3, Math.floor((w - 50) / 90));
  for (const s of steps) { if (step <= s) { step = s; break; } }
  if (step > span) step = Math.min(144000, Math.max(900, span / 4));
  const x0 = 40, x1 = w - 10;
  ctx.strokeStyle = '#334155';
  ctx.fillStyle = '#64748b';
  ctx.font = '10px monospace';
  ctx.textAlign = 'center';
  for (let t = Math.ceil(minT / step) * step; t <= minT + span; t += step) {
    const x = x0 + ((t - minT) / span) * (x1 - x0);
    if (x > x1) break;
    ctx.beginPath(); ctx.moveTo(x, h); ctx.lineTo(x, h - 5); ctx.stroke();
    const d = new Date(t * 1000);
    ctx.fillText(d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit', timeZone: 'UTC' }), x, h - 9);
  }
  ctx.textAlign = 'left';
}

function toggleChannel(idx) {
  if (idx === 0) showCh.l = !showCh.l; else showCh.d = !showCh.d;
  document.getElementById('toggleChG').style.opacity = showCh.l ? '1' : '.4';
  document.getElementById('toggleChD').style.opacity = showCh.d ? '1' : '.4';
  drawTimeline(eventsData);
}

function hideEvtTip() { document.getElementById('evtTip').style.display = 'none'; }

// Click/hover sur marker → tooltip bin_i + freq + lvl_g/d (acceptance IMPROVEMENTS)
(function attachTips() {
  const canvas = document.getElementById('timelineCanvas');
  let raf = null;
  function showTip(e) {
    const rect = canvas.getBoundingClientRect();
    // Espace logique = pixels CSS (le backing store hi-DPI est mis à l'échelle
    // via setTransform dans drawTimeline), donc mapping direct client→logique.
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
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

function yOfFreq(f) { // Hz → px logique Y ; l'axe couvre exactement 0..FREQ_MAX
  const h = TL_CKVH;
  return h - 20 - (f / FREQ_MAX) * (h - 40);
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

function drawTimeline(events) {
  const canvas = document.getElementById('timelineCanvas');
  const ctx = canvas.getContext('2d');
  hideEvtTip();
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
  const stepHz = niceHzStep(FREQ_MAX / 5);
  for (let f = 0; f <= FREQ_MAX + 1e-9; f += stepHz) {
    const y = yOfFreq(Math.min(f, FREQ_MAX));
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

  if (!events || events.length === 0) return;

  const now = Date.now() / 1000;
  let timeSpan, minT;
  if (tlMode) { // zoom par brushing : plage fixe choisie par l'utilisateur (I39)
    timeSpan = tlMode.span; minT = tlMode.minT;
  } else if (timeWindow) { // fenêtre glissante 1h/6h/24h
    timeSpan = timeWindow; minT = now - timeWindow;
  } else { // Tout : plage recouvrant tous les événements + horizon présent
    const ts = events.map(e => e.t0);
    const maxT = Math.max(now, ...ts);
    const minTAll = Math.min(...ts);
    minT = minTAll; timeSpan = Math.max(3600, maxT - minT);
  }
  tlScale = {minT, span: timeSpan}; // conversion px→temps pour le zoom (I39)
  drawTimeTicks(ctx, w, h, minT, timeSpan);

  events.forEach(e => {
    if (e.freq < 0 || e.freq > FREQ_MAX) return; // hors bande du graphique
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
}

// ===== Zoom par brushing sur la timeline (I39) : glisser = plage temps, double-clic/Esc = réinit =====
(function () {
  const canvas = document.getElementById('timelineCanvas');
  if (!canvas) return;
  let dragX0 = null;
  let raf = 0;
  const drawSoon = () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(() => drawTimelineFull()); };
  const toCanvasX = (e) => { // espace logique = px CSS (setTransform hi-DPI actif)
    const r = canvas.getBoundingClientRect();
    return e.clientX - r.left;
  };
  canvas.addEventListener('mousedown', (e) => { dragX0 = toCanvasX(e); tlBrushPx = null; });
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
      const toTime = (xp) => tlScale.minT + ((xp - 40) / (canvas.width - 50)) * tlScale.span;
      const t0 = toTime(tlBrushPx.x0), t1 = toTime(tlBrushPx.x1);
      if (t1 - t0 >= 60) { tlMode = {minT: t0, span: Math.max(120, (t1 - t0) * 1.1)}; syncTlButtons(); }
    }
    tlBrushPx = null;
    drawTimelineFull();
  });
  canvas.addEventListener('dblclick', () => { // double-clic : retour à la fenêtre de boutons
    if (tlMode) { tlMode = null; syncTlButtons(); drawTimelineFull(); }
  });
  window.addEventListener('keydown', (e) => { // Échap : annule le zoom au pinceau
    if (e.key === 'Escape' && tlMode) { tlMode = null; syncTlButtons(); drawTimelineFull(); }
  });
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
            except (ValueError, IndexError):
                self.send_error(400, "Paramètre de requête invalide")
                return
            if limit <= 0 or offset < 0:
                self.send_error(400, "limit doit > 0 et offset >= 0")
                return
            events = self.store.get_events(limit=limit, offset=offset, since=since, cluster=cluster)
            self._send_json(events)
            return

        if path == "/api/clusters":
            clusters = self.store.get_clusters_summary()
            self._send_json(clusters)
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
