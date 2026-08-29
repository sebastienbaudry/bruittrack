"""Lightweight web visualization server for BruitTrack.

Uses Python stdlib ThreadingHTTPServer and serves a zero-dependency HTML5/Canvas UI.
"""

from __future__ import annotations

import http.server
import io
import json
import logging
import time
import urllib.parse
import wave
from pathlib import Path
from typing import Any

import numpy as np

from bruittrack.config import Config
from bruittrack.store import EventStore

logger = logging.getLogger("bruittrack.viz")

# Garde-fous réseau et mémoire (P0)
MAX_POST_BODY = 64 * 1024  # 64 Ko max pour les corps de requêtes POST
MAX_API_LIMIT = 50_000  # Plafond strict pour les requêtes paginées


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
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no, viewport-fit=cover">
<title>BruitTrack — Traqueur d'Événements Sonores</title>
<style>
  :root {
    --bg-dark: #0b0f17;
    --bg-card: #151d2a;
    --bg-card-hover: #1e293b;
    --border: #233144;
    --primary: #38bdf8;
    --accent: #f59e0b;
    --danger: #ef4444;
    --success: #10b981;
    --text: #f1f5f9;
    --text-muted: #94a3b8;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace; }
  body { background: var(--bg-dark); color: var(--text); padding: 12px; font-size: 13px; max-width: 1440px; margin: 0 auto; min-height: 100vh; }
  
  header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border); padding-bottom: 10px; margin-bottom: 12px; flex-wrap: wrap; gap: 10px; }
  h1 { font-size: 18px; color: var(--primary); display: flex; align-items: center; gap: 8px; font-weight: 700; }
  .header-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  
  .badge { display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: bold; }
  .badge-live { background: rgba(16, 185, 129, 0.2); color: var(--success); border: 1px solid var(--success); }
  .badge-cluster { background: rgba(56, 189, 248, 0.2); color: var(--primary); }
  .badge-over { background: rgba(239, 68, 68, 0.2); color: #fca5a5; }
  .badge-ch-l { background: #3b82f6; color: white; }
  .badge-ch-r { background: #ec4899; color: white; }
  .badge-ch-b { background: #8b5cf6; color: white; }
  
  .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; margin-bottom: 12px; }
  .stat-card { background: var(--bg-card); border: 1px solid var(--border); border-radius: 6px; padding: 10px 12px; }
  .stat-val { font-size: 20px; font-weight: bold; color: var(--primary); margin-top: 2px; }
  .stat-lbl { color: var(--text-muted); font-size: 11px; }

  .card { background: var(--bg-card); border: 1px solid var(--border); border-radius: 6px; padding: 12px; margin-bottom: 12px; }
  .card-title { font-size: 14px; font-weight: bold; margin-bottom: 10px; color: var(--text); display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 6px; }

  .toolbar { display: flex; gap: 6px; margin-bottom: 8px; align-items: center; flex-wrap: wrap; }
  .btn-group { display: inline-flex; background: rgba(0,0,0,0.25); border: 1px solid var(--border); border-radius: 4px; padding: 2px; gap: 2px; }

  #timelineCanvas { width: 100%; height: 260px; background: #080c12; border-radius: 4px; border: 1px solid var(--border); cursor: crosshair; touch-action: none; display: block; }
  #specCanvas { width: 100%; height: 220px; background: #080c12; border-radius: 4px; border: 1px solid var(--border); margin-top: 6px; display: none; touch-action: none; }

  .table-container { width: 100%; overflow-x: auto; -webkit-overflow-scrolling: touch; }
  table { width: 100%; border-collapse: collapse; text-align: left; min-width: 460px; }
  tr[data-ev-id] { cursor: pointer; }
  tr.ev-row-selected { background: #312e8155; outline: 1px solid #6366f1; }
  .flt { background: #0f172a; color: #e2e8f0; border: 1px solid #334155; border-radius: 4px; padding: 3px 6px; font-size: 12px; }
  th, td { padding: 6px 8px; border-bottom: 1px solid var(--border); }
  th { color: var(--text-muted); font-size: 11px; text-transform: uppercase; background: rgba(0,0,0,0.2); white-space: nowrap; }
  tr:hover { background: var(--bg-card-hover); }

  .btn { background: var(--border); color: var(--text); border: none; padding: 4px 8px; border-radius: 4px; cursor: pointer; font-size: 12px; transition: 0.15s; touch-action: manipulation; }
  .btn:hover { background: var(--primary); color: #000; }
  .btn-sm { padding: 2px 6px; font-size: 11px; }
  .btn-active { background: rgba(59, 130, 246, 0.3); color: #93c5fd; font-weight: bold; border: 1px solid #3b82f6; }
  .btn-danger { background: rgba(239, 68, 68, 0.2); color: var(--danger); }
  .btn-danger:hover { background: var(--danger); color: white; }
  .btn-success { background: rgba(16, 185, 129, 0.2); color: var(--success); }
  .btn-success:hover { background: var(--success); color: white; }
  
  .layout-2col { display: grid; grid-template-columns: 3fr 2fr; gap: 12px; }
  
  audio { height: 28px; vertical-align: middle; max-width: 130px; }

  @media (max-width: 880px) {
    .layout-2col { grid-template-columns: 1fr; }
    .header-actions { width: 100%; justify-content: space-between; }
    .header-actions button { flex: 1; }
  }
  @media (max-width: 580px) {
    body { padding: 6px; font-size: 12px; }
    .stats-grid { grid-template-columns: 1fr 1fr; gap: 6px; }
    .stat-val { font-size: 17px; }
    .stat-lbl { font-size: 10px; }
    #timelineCanvas { height: 200px; }
    #specCanvas { height: 160px; }
    table { min-width: 380px; }
    .btn { padding: 5px 8px; }
  }
</style>
</head>
<body>

<header>
  <h1>🔊 BruitTrack <span class="badge badge-live">24/7 ACTIF</span></h1>
  <div class="header-actions">
    <button class="btn btn-danger" style="font-weight:bold; background:rgba(239,68,68,0.25); border:1px solid #ef4444; color:#fca5a5;" onclick="openDiscomfortModal()">🚨 Signaler une Gêne / Crise</button>
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
  <div class="toolbar">
    <div class="btn-group">
      <button id="toggleChG" class="btn btn-sm" onclick="toggleChannel(0)">IN1 (Air)</button>
      <button id="toggleChD" class="btn btn-sm" onclick="toggleChannel(1)">IN2 (Struct)</button>
      <button id="toggleSpec" class="btn btn-sm" onclick="toggleSpectrum()" title="I63 : heatmap de l'historique spectre (signaux quasi permanents, invisibles dans les événements)">Spectre</button>
    </div>
    <div class="btn-group">
      <button id="fFocusAll" class="btn btn-sm btn-active" onclick="setFreqFocus(null,null,this)" title="Bande complète 2–150 Hz">Tout (0-150Hz)</button>
      <button id="fFocusInfra" class="btn btn-sm" onclick="setFreqFocus(2.0,35.0,this)" title="Focus Infrasons & Battements lents 2-35 Hz">🔍 Infrasons (2–35 Hz)</button>
      <button id="fFocusHum" class="btn btn-sm" onclick="setFreqFocus(35.0,70.0,this)" title="Focus Hum / 50Hz & Résonance 53.7Hz">🔍 Hum (35–70 Hz)</button>
      <button id="fFocusHigh" class="btn btn-sm" onclick="setFreqFocus(70.0,150.0,this)" title="Focus Harmoniques & Machines 70-150Hz">🔍 Haut (70–150 Hz)</button>
    </div>
    <div class="btn-group">
      <button id="winBtn1h" class="btn btn-sm" onclick="setTimeWin(3600,this)">1h</button>
      <button id="winBtn6h" class="btn btn-sm" onclick="setTimeWin(21600,this)">6h</button>
      <button id="winBtn24h" class="btn btn-sm btn-active" onclick="setTimeWin(86400,this)">24h</button>
      <button id="winBtnTout" class="btn btn-sm" onclick="setTimeWin(null,this)">Tout</button>
    </div>
    <span style="opacity:.4; font-size:11px; font-family:monospace">glisser = zoom temps · Échap = réinit</span>
    <span id="evtTip" style="font-family:monospace; font-size:12px; color:#e2e8f0; background:#1e293b; border-radius:4px; padding:2px 8px; display:none;"></span>
    <span id="freqTip" title="I49 : fréquence sous le curseur" style="font-family:monospace; font-size:12px; color:#93c5fd; background:#1e293b; border-radius:4px; padding:2px 8px; display:none;"></span>
    <span id="zoomBadge" onclick="resetFviews()" title="I54 : reset zoom X+Y (double-clic ou Échap)" style="display:none; cursor:pointer; color:#94a3b8; font-size:12px;"></span>
    <span id="majBadge" title="I53/I56 : dernière MAJ réussie" style="margin-left:10px; font-family:monospace; font-size:12px; color:#94a3b8;"></span>
  </div>
  <canvas id="timelineCanvas" width="1000" height="260"></canvas>
  <div id="specBar" style="display:none; text-align:right; font-size:11px; color:#64748b; margin:4px 2px 0 0;">Spectre Continu — Échelle globale calibrée en énergie (foncé = plancher calme, clair/jaune = fortes énergies)</div>
  <canvas id="specCanvas"></canvas>
</div>

<div class="layout-2col">
  <div class="card">
    <div class="card-title">Derniers Événements</div>
    <div style="margin: 0 0 8px 0; display: flex; gap: 6px; align-items: center; flex-wrap: wrap;">
      <input type="checkbox" id="onlyLegal" style="accent-color: #ef4444;" onchange="applyFilters()" />
      <label for="onlyLegal" style="font-size: 12px; cursor: pointer; color: #fca5a5;" title="Filtrer uniquement les événements dépassant le seuil d'émergence légal autorisé (CSP Art. R1336-7)">Infractions / Dépassements légaux (▲)</label>
      <select id="chanFilter" class="flt" onchange="applyFilters()"><option value="">Tous canaux</option><option value="l">IN1 (Air)</option><option value="d">IN2 (Struct)</option><option value="b">Les 2</option></select>
      <label for="minLvlFilter" style="font-size: 12px; color:#94a3b8;">Ém. ≥</label>
      <input type="number" id="minLvlFilter" class="flt" style="width:48px;" value="0" min="0" step="1" onchange="applyFilters()" /><span style="font-size:11px;color:#94a3b8;">dB</span>
      <select id="clusterFilter" class="flt" onchange="applyFilters()"><option value="">Tous clusters</option></select>
    </div>
    <div class="table-container" style="max-height: 480px; overflow-y: auto;">
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
    <div class="table-container" style="max-height: 480px; overflow-y: auto;">
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

<div class="card" style="margin-top: 12px;">
  <div class="card-title" style="display:flex; justify-content:space-between; align-items:center;">
    <span>🚨 Journal des Gênes & Corrélations Psychoacoustiques</span>
    <button class="btn btn-danger btn-sm" onclick="openDiscomfortModal()">+ Nouvelle Gêne</button>
  </div>
  <div class="table-container" style="max-height: 240px; overflow-y: auto;">
    <table>
      <thead>
        <tr>
          <th>Horodatage</th>
          <th>Intensité</th>
          <th>Symptômes / Notes</th>
          <th>Action</th>
        </tr>
      </thead>
      <tbody id="discomfortTableBody">
        <tr><td colspan="4" style="text-align:center; color:#64748b;">Aucun signalement de gêne enregistré.</td></tr>
      </tbody>
    </table>
  </div>
</div>

<div id="discomfortModal" style="display:none; position:fixed; z-index:9999; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.75); backdrop-filter:blur(3px); align-items:center; justify-content:center; padding:12px;">
  <div style="background:#18202c; border:1px solid #ef4444; border-radius:8px; width:480px; max-width:100%; max-height:90vh; overflow-y:auto; padding:16px; box-shadow:0 10px 30px rgba(0,0,0,0.6);">
    <h3 style="color:#fca5a5; font-size:15px; margin-bottom:8px; display:flex; align-items:center; gap:8px;">🚨 Enregistrer une Gêne / Crise Ressentie</h3>
    <p style="color:#94a3b8; font-size:11px; margin-bottom:12px;">Marque l'instant précis sur la timeline et le spectrogramme pour corréler votre ressenti avec les relevés acoustiques.</p>
    
    <label style="display:block; font-size:11px; color:#cbd5e1; margin-bottom:6px; font-weight:bold;">Niveau d'intensité :</label>
    <div style="display:flex; gap:4px; margin-bottom:12px; flex-wrap:wrap;">
      <label style="flex:1; min-width:60px; background:#0f172a; border:1px solid #334155; padding:6px 2px; border-radius:4px; text-align:center; cursor:pointer; font-size:11px;"><input type="radio" name="discLevel" value="1"> 1 Légère</label>
      <label style="flex:1; min-width:36px; background:#0f172a; border:1px solid #334155; padding:6px 2px; border-radius:4px; text-align:center; cursor:pointer; font-size:11px;"><input type="radio" name="discLevel" value="2"> 2</label>
      <label style="flex:1; min-width:60px; background:#0f172a; border:1px solid #38bdf8; padding:6px 2px; border-radius:4px; text-align:center; cursor:pointer; font-size:11px;"><input type="radio" name="discLevel" value="3" checked> 3 Gênant</label>
      <label style="flex:1; min-width:36px; background:#0f172a; border:1px solid #334155; padding:6px 2px; border-radius:4px; text-align:center; cursor:pointer; font-size:11px;"><input type="radio" name="discLevel" value="4"> 4</label>
      <label style="flex:1; min-width:60px; background:#0f172a; border:1px solid #ef4444; padding:6px 2px; border-radius:4px; text-align:center; cursor:pointer; font-size:11px; color:#fca5a5;"><input type="radio" name="discLevel" value="5"> 5 Crise</label>
    </div>
    
    <label style="display:block; font-size:11px; color:#cbd5e1; margin-bottom:6px; font-weight:bold;">Symptômes rapides :</label>
    <div style="display:flex; gap:4px; flex-wrap:wrap; margin-bottom:12px;">
      <button type="button" class="btn btn-sm" onclick="addDiscTag('Nausées')">+ Nausées</button>
      <button type="button" class="btn btn-sm" onclick="addDiscTag('Cerveau qui vibre')">+ Cerveau qui vibre</button>
      <button type="button" class="btn btn-sm" onclick="addDiscTag('Bourdonnement / Hum')">+ Bourdonnement</button>
      <button type="button" class="btn btn-sm" onclick="addDiscTag('Battements 0.5-3s')">+ Battements 0.5-3s</button>
      <button type="button" class="btn btn-sm" onclick="addDiscTag('Pression tympans')">+ Pression oreilles</button>
      <button type="button" class="btn btn-sm" onclick="addDiscTag('Stress / Oppression')">+ Stress / Oppression</button>
    </div>

    <label style="display:block; font-size:11px; color:#cbd5e1; margin-bottom:6px; font-weight:bold;">Description / Notes :</label>
    <input type="text" id="discNote" class="flt" style="width:100%; padding:6px 8px; margin-bottom:14px;" placeholder="Ex: Vrombissement sourd intermittent avec nausées..." />

    <div style="display:flex; justify-content:flex-end; gap:8px;">
      <button type="button" class="btn" onclick="closeDiscomfortModal()">Annuler</button>
      <button type="button" class="btn btn-danger" style="font-weight:bold;" onclick="submitDiscomfort()">✅ Enregistrer</button>
    </div>
  </div>
</div>

<div id="snapshotModal" style="display:none; position:fixed; z-index:9999; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.8); backdrop-filter:blur(4px); align-items:center; justify-content:center; padding:12px;">
  <div style="background:#131b26; border:1px solid #38bdf8; border-radius:8px; width:920px; max-width:100%; max-height:90vh; overflow-y:auto; padding:16px; box-shadow:0 12px 40px rgba(0,0,0,0.8);">
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; flex-wrap:wrap; gap:8px;">
      <h3 id="snapModalTitle" style="color:#38bdf8; font-size:15px; display:flex; align-items:center; gap:8px;">🔬 Cliché Haute Définition (30 s / 100 ms / 0.49 Hz)</h3>
      <button class="btn btn-sm" onclick="closeSnapshotModal()">✕ Fermer</button>
    </div>
    
    <div id="snapMetricsBar" style="background:#0b1118; border:1px solid #1e293b; border-radius:6px; padding:8px 12px; margin-bottom:10px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:6px; font-size:11px; font-family:monospace;">
      <div><span style="color:#94a3b8;">Battements Infrasons (2–35 Hz) :</span> <span id="snapModInfra" style="color:#38bdf8; font-weight:bold;">--</span></div>
      <div><span style="color:#94a3b8;">Battements Hum (35–70 Hz) :</span> <span id="snapModHum" style="color:#f59e0b; font-weight:bold;">--</span></div>
      <div><span style="color:#94a3b8;">Période dominante :</span> <span id="snapModPeriod" style="color:#4ade80; font-weight:bold;">--</span></div>
    </div>

    <div style="display:flex; gap:6px; margin-bottom:8px; align-items:center; flex-wrap:wrap;">
      <span style="font-size:11px; color:#94a3b8;">Zoom Fréq :</span>
      <button id="snapFocusAll" class="btn btn-sm btn-active" onclick="setSnapFocus(null,null,this)">Tout (0-150Hz)</button>
      <button id="snapFocusInfra" class="btn btn-sm" onclick="setSnapFocus(2.0,35.0,this)">🔍 Infrasons (2–35 Hz)</button>
      <button id="snapFocusHum" class="btn btn-sm" onclick="setSnapFocus(35.0,70.0,this)">🔍 Hum (35–70 Hz)</button>
    </div>

    <canvas id="snapCanvas" width="880" height="240" style="width:100%; height:220px; background:#080c12; border-radius:4px; display:block;"></canvas>

    <div style="margin-top:10px; display:flex; align-items:center; gap:8px; background:#0b1118; padding:8px 10px; border-radius:6px; border:1px solid #1e293b; flex-wrap:wrap;">
      <span style="font-size:11px; color:#cbd5e1; white-space:nowrap;">🎧 Écoute 1 kHz :</span>
      <audio id="snapAudioPlayer" controls style="flex:1; min-width:140px; height:32px;"></audio>
      <div style="display:flex; gap:4px;">
        <button class="btn btn-sm" onclick="setAudioSpeed(0.5)">0.5x</button>
        <button class="btn btn-sm" onclick="setAudioSpeed(1.0)">1x</button>
      </div>
    </div>
  </div>
</div>

<script>
let eventsData = [];
let clustersData = [];
let discomfortLogs = [];
let currentSnapshotData = null;
let currentSnapFreqView = null;

function openDiscomfortModal() {
  const m = document.getElementById('discomfortModal');
  if (m) m.style.display = 'flex';
}

function closeDiscomfortModal() {
  const m = document.getElementById('discomfortModal');
  if (m) m.style.display = 'none';
}

async function openSnapshotModal(discomfortId) {
  const m = document.getElementById('snapshotModal');
  if (m) m.style.display = 'flex';
  const title = document.getElementById('snapModalTitle');
  if (title) title.textContent = `🔬 Cliché Haute Définition — Signalement #${discomfortId} (30s / 100ms / 0.49Hz)`;
  
  const audio = document.getElementById('snapAudioPlayer');
  if (audio) {
    audio.src = `/api/discomfort/${discomfortId}/audio`;
    audio.load();
  }

  const data = await fetchJson(`/api/discomfort/${discomfortId}/snapshot`);
  if (data) {
    currentSnapshotData = data;
    document.getElementById('snapModInfra').textContent = (data.mod_infra_pct || 0) + '%';
    document.getElementById('snapModHum').textContent = (data.mod_hum_pct || 0) + '%';
    document.getElementById('snapModPeriod').textContent = (data.mod_period_s ? data.mod_period_s + ' s' : 'Non périodique');
    currentSnapFreqView = null;
    requestAnimationFrame(drawSnapshotSpectrogram);
  }
}

function closeSnapshotModal() {
  const m = document.getElementById('snapshotModal');
  if (m) m.style.display = 'none';
  const audio = document.getElementById('snapAudioPlayer');
  if (audio) { audio.pause(); audio.src = ''; }
  currentSnapshotData = null;
}

function setAudioSpeed(rate) {
  const audio = document.getElementById('snapAudioPlayer');
  if (audio) audio.playbackRate = rate;
}

function setSnapFocus(fLo, fHi, btn) {
  document.querySelectorAll('#snapFocusAll, #snapFocusInfra, #snapFocusHum').forEach(b => b.classList.remove('btn-active'));
  if (btn) btn.classList.add('btn-active');
  if (fLo === null || fHi === null) currentSnapFreqView = null;
  else currentSnapFreqView = { fLo, fHi };
  drawSnapshotSpectrogram();
}

function drawSnapshotSpectrogram() {
  const cv = document.getElementById('snapCanvas');
  if (!cv || !currentSnapshotData) return;
  const dpr = window.devicePixelRatio || 1;
  const rect = cv.getBoundingClientRect();
  const wCss = Math.max(320, rect.width || 880);
  const hCss = 240;
  cv.width = Math.round(wCss * dpr);
  cv.height = Math.round(hCss * dpr);
  const ctx = cv.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, wCss, hCss);
  ctx.fillStyle = '#080c12';
  ctx.fillRect(0, 0, wCss, hCss);

  const psd1 = currentSnapshotData.psd_ch1;
  const psd2 = currentSnapshotData.psd_ch2;
  const freqs = currentSnapshotData.freqs;
  const nTicks = psd1 ? psd1.length : 0;
  const nBins = freqs ? freqs.length : 0;
  if (!nTicks || !nBins) return;

  const fLo = currentSnapFreqView ? currentSnapFreqView.fLo : freqs[0];
  const fHi = currentSnapFreqView ? currentSnapFreqView.fHi : freqs[nBins - 1];
  const x0 = 40, x1 = wCss - 10;
  const yOfHz = (f) => 4 + (fHi - Math.min(Math.max(f, fLo), fHi)) / Math.max(0.1, fHi - fLo) * (hCss - 8);

  const colW = Math.max(1, (x1 - x0) / nTicks);
  const binStep = freqs.length > 1 ? freqs[1] - freqs[0] : 0.488;

  for (let t = 0; t < nTicks; t++) {
    const xa = x0 + (t / nTicks) * (x1 - x0);
    const r1 = psd1[t], r2 = psd2[t];
    for (let b = 0; b < nBins; b++) {
      const f = freqs[b];
      if (f + binStep < fLo || f > fHi) continue;
      const v1 = r1 ? r1[b] : -100, v2 = r2 ? r2[b] : -100;
      let val = showCh.l && showCh.d ? Math.max(v1, v2) : (showCh.l ? v1 : v2);
      const tNorm = Math.max(0, Math.min(1, (val - (-40)) / 70));
      ctx.fillStyle = specColor(tNorm);
      const yA = yOfHz(f), yB = yOfHz(f + binStep);
      const yT = Math.min(yA, yB), hh = Math.max(1, Math.abs(yB - yA));
      ctx.fillRect(xa, yT, Math.ceil(colW), hh);
    }
  }

  ctx.fillStyle = '#94a3b8';
  ctx.font = '11px monospace';
  ctx.textAlign = 'right';
  const hzStep = niceHzStep((fHi - fLo) / 4);
  for (let f = Math.ceil(fLo / hzStep) * hzStep; f <= fHi + 1e-6; f += hzStep)
    ctx.fillText(Math.round(f) + ' Hz', 36, Math.min(hCss - 2, yOfHz(f) + 4));

  ctx.textAlign = 'center';
  for (let sec = -30; sec <= 0; sec += 5) {
    const xp = x0 + ((sec + 30) / 30) * (x1 - x0);
    ctx.fillText(sec + 's', xp, hCss - 2);
  }
  ctx.textAlign = 'left';
}

function addDiscTag(tag) {
  const input = document.getElementById('discNote');
  if (!input) return;
  const cur = input.value.trim();
  if (cur.length === 0) input.value = tag;
  else if (!cur.includes(tag)) input.value = cur + ', ' + tag;
  input.focus();
}

async function submitDiscomfort() {
  const radios = document.getElementsByName('discLevel');
  let level = 3;
  for (const r of radios) { if (r.checked) { level = parseInt(r.value, 10); break; } }
  const note = (document.getElementById('discNote').value || '').trim();
  
  try {
    const res = await fetch('/api/discomfort', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ level: level, note: note, t0: Date.now() / 1000 })
    });
    if (res.ok) {
      closeDiscomfortModal();
      document.getElementById('discNote').value = '';
      await fetchDiscomfortLogs();
      drawTimelineFull(false);
    } else {
      alert('Erreur lors de l’enregistrement de la gêne');
    }
  } catch (e) {
    console.error('Erreur submitDiscomfort', e);
    alert('Erreur réseau');
  }
}

async function deleteDiscomfort(id) {
  if (!confirm('Supprimer ce signalement de gêne ?')) return;
  try {
    const res = await fetch('/api/discomfort/' + id + '/delete', { method: 'POST' });
    if (res.ok) {
      await fetchDiscomfortLogs();
      drawTimelineFull(false);
    }
  } catch(e) {
    console.error('Erreur deleteDiscomfort', e);
  }
}

function zoomOnDiscomfort(t0) {
  tlMode = { minT: t0 - 300, span: 600 }; // 10 min window around the event
  syncTlButtons();
  refreshWindowed();
}

async function fetchDiscomfortLogs() {
  const got = await fetchJson('/api/discomfort?limit=500');
  if (Array.isArray(got)) {
    discomfortLogs = got;
    renderDiscomfortTable();
  }
}

function renderDiscomfortTable() {
  const tbody = document.getElementById('discomfortTableBody');
  if (!tbody) return;
  if (!discomfortLogs.length) {
    tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; color:#64748b;">Aucun signalement de gêne enregistré.</td></tr>';
    return;
  }
  const levelBadges = {
    1: '<span class="badge" style="background:#0284c7; color:white;">1 Légère</span>',
    2: '<span class="badge" style="background:#3b82f6; color:white;">2 Modérée</span>',
    3: '<span class="badge" style="background:#eab308; color:black; font-weight:bold;">3 Gênant</span>',
    4: '<span class="badge" style="background:#f97316; color:white; font-weight:bold;">4 Pénible</span>',
    5: '<span class="badge" style="background:#ef4444; color:white; font-weight:bold;">5 Crise</span>'
  };
  tbody.innerHTML = discomfortLogs.map(l => {
    const dt = formatDate(l.t0);
    const b = levelBadges[l.level] || ('Niv. ' + l.level);
    const noteEsc = (l.note || '').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    const snapBtn = l.has_snapshot
      ? `<button class="btn btn-sm" style="background:#0284c7; color:white; font-weight:bold;" onclick="openSnapshotModal(${l.id})" title="Ouvrir le Cliché Spectrogramme HD (100ms / 0.49Hz)">🔬 Cliché HD</button>`
      : '';
    return `<tr>
      <td style="font-family:monospace;">${dt}</td>
      <td>${b}</td>
      <td>${noteEsc || '<em style="color:#64748b;">Sans note</em>'}</td>
      <td style="display:flex; gap:4px; flex-wrap:wrap;">
        <button class="btn btn-sm" onclick="zoomOnDiscomfort(${l.t0})" title="Zoomer sur cet instant (±5 min)">🔍 Zoomer</button>
        ${snapBtn}
        <button class="btn btn-danger btn-sm" onclick="deleteDiscomfort(${l.id})" title="Supprimer">🗑️</button>
      </td>
    </tr>`;
  }).join('');
}

function setFreqFocus(fLo, fHi, btn) {
  document.querySelectorAll('#fFocusAll, #fFocusInfra, #fFocusHum, #fFocusHigh').forEach(b => b.classList.remove('btn-active'));
  if (btn) btn.classList.add('btn-active');
  if (fLo === null || fHi === null) {
    freqView = null;
  } else {
    freqView = { fLo: Math.max(0, fLo), fHi: Math.min(FREQ_MAX, fHi) };
  }
  specCache.key = null;
  drawTimelineFull(false);
}

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
  if (!clusterId) return "#94a3b8"; // cluster NULL / inconnu
  const hue = (clusterId * 137.5) % 360; // angle d'or : ids proches => teintes eloignees
  const l = [45, 68][Math.floor(clusterId / 6) % 2]; // clarte alternee par bloc de 6 ids
  return `hsl(${hue}, 85%, ${l}%)`;
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
  if (tlMode) return Promise.resolve().then(fetchWindow).then(fetchSpectrum).then(() => drawTimelineFull());
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

let lastMajTs = 0; // I56 : horodatage (epoch s) de la dernière MAJ réussie
function renderMaj() { // I53/I56 : « il y a Xs » si < 60 s, sinon horodaté hh:mm:ss (TZ_VIZ)
  const b = document.getElementById('majBadge');
  if (!b || !lastMajTs) return;
  const dt = Math.floor(Date.now() / 1000 - lastMajTs);
  const abs = new Date(lastMajTs * 1000).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23', timeZone: TZ_VIZ });
  b.textContent = dt < 60 ? `MAJ il y a ${dt}s` : `MAJ ${abs}`;
}
function startMajTick() { // I56 : tick 1 s léger (texte seul, pas de refetch)
  if (window.__majTick) return;
  window.__majTick = setInterval(renderMaj, 1000);
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
  const specPromise = fetchSpectrum(); // Démarrage immédiat en parallèle
  const discPromise = fetchDiscomfortLogs();
  const [stats, events, clusters] = await Promise.all([
    fetchJson('/api/stats'),
    fetchJson('/api/events?limit=20000'), // I55: plus de plafond 200 — fenêtre ?since= déleste le éventail complet
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
  await Promise.all([fetchWindow(), specPromise, discPromise]); // Attente sans blocage sérialisé
  drawTimelineFull();
  lastMajTs = Date.now() / 1000; renderMaj(); startMajTick(); // I53/I56 : badge MAJ après chargement réussi
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

    let olBadge = '';
    if (e.over_legal) {
      olBadge = ' <span class="badge badge-over" title="Dépassement de l&#39;émergence maximale autorisée (CSP Art. R1336-7)">▲ Infraction</span>';
    } else if (e.is_invalid) {
      olBadge = ' <span class="badge" style="background:#64748b;color:#f8fafc;" title="Relevé non conforme aux contraintes de mesure (< 10s)">? Invalide</span>';
    }
    return `<tr data-ev-id="${e.id}"${e.id === selectedEvId ? ' class="ev-row-selected"' : ''} onclick="selectEv(${e.id})">
      <td>${formatDate(e.t0)}</td>
      <td><strong>${e.freq.toFixed(1)} Hz</strong></td>
      <td>${chBadge}</td>
      <td>+${e.lvl_g.toFixed(1)} / +${e.lvl_d.toFixed(1)} dB${olBadge}</td>
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
  if (SPEC && SPEC.enabled && specShow) fetchSpectrum();
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
  // I68 : point survolé en cours — VERROUILLÉ tant que le curseur reste dans son
  // rayon de hit, sinon deux bulles proches (<=24 px entre centres) se disputent
  // le tooltip et le texte change à chaque léger mouvement de souris (« décalage »).
  let hoverLockId = null;
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

    // I68 : rayon de hit par point = max(12, rayon visuel + 3 px) au lieu du
    // test unique à 10 px du centre qui ratait les bulles fines (r=3) et
    // délimitait mal les grosses — texte au survol aligné sur la bulle visible.
    const fit = (p) => { const dx = p.x - mx, dy = p.y - my; const rr = Math.max(12, p.r + 3); return dx * dx + dy * dy <= rr * rr; };
    let best = null;
    if (hoverLockId !== null) {
      const lk = timelinePoints.find(p => p.ev.id === hoverLockId);
      if (lk && fit(lk)) { best = lk; }
    }
    if (!best) {
      let bd = Infinity;
      for (const p of timelinePoints) {
        if (!fit(p)) continue;
        const dx = p.x - mx, dy = p.y - my;
        const dd = dx * dx + dy * dy;
        if (dd < bd) { bd = dd; best = p; }
      }
      hoverLockId = best ? best.ev.id : null; // le verrou change en sortant du rayon
    }
    const tip = document.getElementById('evtTip');
    if (!best) { hideEvtTip(); return; }
    const ev = best.ev;
    tip.textContent = `#${ev.cluster || '-'} · bin ${ev.bin_i} (${ev.freq.toFixed(2)} Hz) · G +${ev.lvl_g.toFixed(1)} / D +${ev.lvl_d.toFixed(1)} dB` + (ev.over_legal ? ' · ▲ legal' : '');
    tip.style.display = 'inline';
    // I69 : le texte suit la bulle — centré au-dessus d'elle (plus jamais ancré
    // dans la barre d'outils, qui était perçu comme un « décalage »).
    tip.style.position = 'fixed';
    tip.style.zIndex = '50';
    tip.style.pointerEvents = 'none';
    const crect = canvas.getBoundingClientRect();
    let tipLx = crect.left + best.x - tip.offsetWidth / 2;
    tipLx = Math.max(4, Math.min(tipLx, window.innerWidth - tip.offsetWidth - 4));
    let tipLy = crect.top + best.y - tip.offsetHeight - 10;
    if (tipLy < 4) tipLy = crect.top + best.y + best.r + 6; // sous la bulle si trop haut
    tip.style.left = tipLx + 'px';
    tip.style.top = tipLy + 'px';
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
  } else if (timeWindow) { // fenêtre glissante 1h/6h/24h (prioritaire sur graphe vide pour éviter le saut 6h -> 24h)
    timeSpan = timeWindow; minT = now - timeWindow;
  } else if (evs.length === 0) { // Tout sans événement : horizon 24 h
    timeSpan = 86400; minT = now - timeSpan;
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
      // I68 : rayon visuel calculé avant le push — stocké sur le point pour le hit-test.
      const radius = Math.max(3, Math.min(10, (e.lvl_g + e.lvl_d) / 6));
      timelinePoints.push({x, y, r: radius, ev: e});
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

  // Lignes verticales et badges des signalements de gêne (Journal de gêne)
  discomfortLogs.forEach(dl => {
    if (dl.t0 >= minT - 1e-9 && dl.t0 <= minT + timeSpan + 1e-9) {
      const x = 40 + ((dl.t0 - minT) / timeSpan) * (w - 50);
      if (x >= 40 && x <= w - 10) {
        ctx.save();
        ctx.strokeStyle = dl.level >= 4 ? '#ef4444' : '#f59e0b';
        ctx.lineWidth = 1.5;
        ctx.setLineDash([4, 3]);
        ctx.beginPath();
        ctx.moveTo(x, 20);
        ctx.lineTo(x, h - 20);
        ctx.stroke();
        ctx.setLineDash([]);
        
        ctx.fillStyle = dl.level >= 4 ? '#ef4444' : '#f59e0b';
        ctx.font = 'bold 10px monospace';
        ctx.fillText('🚨 Niv.' + dl.level, Math.min(w - 95, x + 3), 32);
        ctx.restore();
      }
    }
  });

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

// ===== I63 : historique spectre — heatmap PNG générée côté serveur =====
// Config injectée côté serveur (placeholders remplacés par BruitTrackHandler).
const SPEC = { enabled: __SPEC_ENABLED__, bands: __SPEC_BANDS__, dbMin: __SPEC_DB_MIN__, dbRange: __SPEC_DB_RANGE__ };
const EXEMPLARS_ENABLED = __EXEMPLARS_ENABLED__;
let specImg = null;
let specImgKey = null;
let fetchingSpec = false;
let specShow = true;

function toggleSpectrum() {
  if (!SPEC.enabled) return;
  specShow = !specShow;
  document.getElementById('toggleSpec').classList.toggle('btn-active', specShow);
  document.getElementById('specCanvas').style.display = specShow ? 'block' : 'none';
  if (specShow) fetchSpectrum(true);
  drawTimelineFull();
}

async function fetchSpectrum(force = false) {
  if (!SPEC.enabled || !specShow) return;
  const now = Date.now() / 1000;
  let minT, span;
  if (tlScale) {
    minT = tlScale.minT; span = tlScale.span;
  } else if (tlMode) {
    minT = tlMode.minT; span = tlMode.span;
  } else if (timeWindow) {
    minT = now - timeWindow; span = timeWindow;
  } else {
    minT = (dataSince !== null ? dataSince : now - 86400);
    span = Math.max(3600, now - minT);
  }
  const fb = freqBounds();
  let ch = 'both';
  if (showCh.l && !showCh.d) ch = 'l';
  else if (!showCh.l && showCh.d) ch = 'd';

  const wCss = TL_CKWW || 1000;
  const specW = Math.max(100, Math.round(wCss - 50));
  const key = [Math.round(minT), Math.round(span), specW, fb[0].toFixed(1), fb[1].toFixed(1), ch].join('|');

  if (!force && specImgKey === key) return;
  if (fetchingSpec) return;

  fetchingSpec = true;
  const specBtn = document.getElementById('toggleSpec');
  if (specBtn) specBtn.innerText = 'Spectre ⏳';
  drawSpecPanel();

  const url = `/api/spectrum.png?since=${minT}&until=${minT + span}&width=${specW}&f_lo=${fb[0]}&f_hi=${fb[1]}&ch=${ch}&_t=${Date.now()}`;
  const img = new Image();
  img.onload = () => {
    specImg = img;
    specImgKey = key;
    fetchingSpec = false;
    if (specBtn) specBtn.innerText = 'Spectre';
    drawSpecPanel();
  };
  img.onerror = () => {
    fetchingSpec = false;
    if (specBtn) specBtn.innerText = 'Spectre';
    drawSpecPanel();
  };
  img.src = url;
}

function specBandEdge(i, nb) { // bords linéaires identiques au serveur (SpectrumAggregator.band_edges)
  return MIN_EVENT_HZ + (FREQ_MAX - MIN_EVENT_HZ) * (i / (nb || SPEC.bands));
}

function drawSpecPanel() { // dessinée après drawTimeline : réutilise tlScale (même axe X)
  const cv = document.getElementById('specCanvas');
  if (!cv || !SPEC.enabled || !tlScale) return;
  cv.style.display = specShow ? 'block' : 'none';
  const bar = document.getElementById('specBar');
  if (bar) bar.style.display = specShow ? 'block' : 'none';
  if (!specShow) return;
  const dpr = window.devicePixelRatio || 1;
  const isSmall = window.innerWidth <= 580;
  const wCss = TL_CKWW, hCss = isSmall ? 160 : 220;
  const bw = Math.round(wCss * dpr), bh = Math.round(hCss * dpr);
  if (cv.width !== bw || cv.height !== bh) { cv.width = bw; cv.height = bh; }
  const ctx = cv.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  ctx.clearRect(0, 0, wCss, hCss);
  ctx.fillStyle = '#080c12';
  ctx.fillRect(0, 0, wCss, hCss);

  const x0 = 40, x1 = wCss - 10;
  const y0 = 4, y1 = hCss - 4;
  const fb = freqBounds();

  if (specImg && specImg.complete && specImg.naturalWidth > 0) {
    if (fetchingSpec) ctx.globalAlpha = 0.55;
    ctx.drawImage(specImg, x0, y0, x1 - x0, y1 - y0);
    ctx.globalAlpha = 1.0;
  } else {
    ctx.fillStyle = '#94a3b8'; ctx.font = '13px monospace'; ctx.textAlign = 'center';
    ctx.fillText("⏳ Chargement du spectrogramme...", wCss / 2, hCss / 2);
    ctx.textAlign = 'left';
  }

  if (fetchingSpec && specImg && specImg.complete && specImg.naturalWidth > 0) {
    ctx.save();
    ctx.fillStyle = 'rgba(15, 23, 42, 0.85)';
    ctx.strokeStyle = '#38bdf8';
    ctx.lineWidth = 1;
    const badgeW = 180, badgeH = 22, bx = x1 - badgeW - 6, by = y0 + 6;
    ctx.fillRect(bx, by, badgeW, badgeH);
    ctx.strokeRect(bx, by, badgeW, badgeH);
    ctx.fillStyle = '#38bdf8';
    ctx.font = '11px monospace';
    ctx.textAlign = 'left';
    ctx.fillText('⏳ Chargement spectre...', bx + 8, by + 15);
    ctx.restore();
  }

  const yOfHz2 = (f) => y0 + (fb[1] - Math.min(Math.max(f, fb[0]), fb[1])) / Math.max(0.1, fb[1] - fb[0]) * (y1 - y0);

  // Fil horizontal sous le curseur (repérage de fréquence instantané)
  if (hoverYpx != null && hoverYpx >= 20 && hoverYpx <= TL_CKVH - 20) {
    const fHover = yToFreq(hoverYpx);
    const ys = yOfHz2(fHover);
    if (ys >= y0 && ys <= y1) {
      ctx.strokeStyle = 'rgba(147,197,253,.65)'; ctx.lineWidth = 1;
      ctx.setLineDash([3, 3]); sharpLine(ctx, x0, ys, x1, ys); ctx.setLineDash([]);
      ctx.fillStyle = '#93c5fd'; ctx.font = '11px monospace'; ctx.textAlign = 'right';
      ctx.fillText(fHover.toFixed(1) + ' Hz', 36, ys + 4); ctx.textAlign = 'left';
    }
  }

  // Marqueurs de gêne sur le spectrogramme
  const minT = tlScale.minT, span = tlScale.span;
  if (discomfortLogs && discomfortLogs.length > 0) {
    discomfortLogs.forEach(dl => {
      if (dl.t0 >= minT - 1e-9 && dl.t0 <= minT + span + 1e-9) {
        const x = x0 + ((dl.t0 - minT) / span) * (x1 - x0);
        if (x >= x0 && x <= x1) {
          ctx.save();
          ctx.strokeStyle = dl.level >= 4 ? '#ef4444' : '#f59e0b';
          ctx.lineWidth = 1.5;
          ctx.setLineDash([4, 3]);
          ctx.beginPath();
          ctx.moveTo(x, y0);
          ctx.lineTo(x, y1);
          ctx.stroke();
          ctx.restore();
        }
      }
    });
  }

  // Limite f_min (si dans la vue)
  if (MIN_EVENT_HZ >= fb[0] && MIN_EVENT_HZ <= fb[1]) {
    const yMin = Math.round(yOfHz2(MIN_EVENT_HZ));
    ctx.strokeStyle = 'rgba(245,158,11,.5)';
    ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.moveTo(x0, yMin + 0.5); ctx.lineTo(x1, yMin + 0.5); ctx.stroke();
    ctx.setLineDash([]);
  }

  // Étiquettes Hz sur pas « nice »
  ctx.fillStyle = '#94a3b8'; ctx.font = '11px monospace'; ctx.textAlign = 'right';
  const hzStep = niceHzStep((fb[1] - fb[0]) / 4);
  for (let f = Math.ceil(fb[0] / hzStep) * hzStep; f <= fb[1] + 1e-6; f += hzStep)
    ctx.fillText(Math.round(f) + ' Hz', 36, Math.min(hCss - 2, yOfHz2(f) + 4));
  ctx.textAlign = 'left';

  // Label d'axe vertical en haut à gauche
  ctx.fillStyle = '#64748b'; ctx.font = '11px monospace';
  ctx.fillText('Spectre ' + fb[0].toFixed(0) + '..' + fb[1].toFixed(0) + ' Hz', x0 + 4, y0 + 12);
}

// ===== Zoom par brushing sur la timeline (I39) : glisser / touch = plage temps, double-clic/Esc = réinit =====
(function () {
  const canvas = document.getElementById('timelineCanvas');
  if (!canvas) return;
  let dragX0 = null;
  let raf = 0;
  const drawSoon = () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(() => drawTimelineFull(false)); };
  const toCanvasX = (e) => {
    const r = canvas.getBoundingClientRect();
    return (e.clientX || (e.touches && e.touches[0] ? e.touches[0].clientX : 0)) - r.left;
  };
  canvas.addEventListener('mousedown', (e) => {
    if (e.ctrlKey || e.button !== 0) return;
    dragX0 = toCanvasX(e); tlBrushPx = null;
  });
  canvas.addEventListener('mousemove', (e) => {
    if (dragX0 === null) return;
    const x1 = toCanvasX(e);
    if (Math.abs(x1 - dragX0) > 6) {
      tlBrushPx = {x0: Math.min(dragX0, x1), x1: Math.max(dragX0, x1)};
      drawSoon();
    }
  });
  const finishDrag = () => {
    if (dragX0 === null) return;
    dragX0 = null;
    if (tlBrushPx && tlScale) {
      const toTime = (xp) => tlScale.minT + ((xp - 40) / (TL_CKWW - 50)) * tlScale.span;
      const t0 = toTime(tlBrushPx.x0), t1 = toTime(tlBrushPx.x1);
      if (t1 - t0 >= 60) { tlMode = {minT: t0, span: Math.max(120, (t1 - t0) * 1.1)}; syncTlButtons(); }
    }
    tlBrushPx = null;
    refreshWindowed();
  };
  document.addEventListener('mouseup', finishDrag);

  // Support tactile mobile / tablette
  canvas.addEventListener('touchstart', (e) => {
    if (e.touches.length !== 1) return;
    dragX0 = toCanvasX(e);
    tlBrushPx = null;
  }, { passive: true });
  canvas.addEventListener('touchmove', (e) => {
    if (dragX0 === null || e.touches.length !== 1) return;
    const x1 = toCanvasX(e);
    if (Math.abs(x1 - dragX0) > 8) {
      tlBrushPx = {x0: Math.min(dragX0, x1), x1: Math.max(dragX0, x1)};
      drawSoon();
    }
  }, { passive: true });
  canvas.addEventListener('touchend', finishDrag, { passive: true });

  canvas.addEventListener('dblclick', resetFviews);
  window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') resetFviews();
  });
})();

// ===== Molette : zoom axe Y ancré curseur (I61) ; double-clic/Echap réinitialisent =====
(function () {
  const canvas = document.getElementById('timelineCanvas');
  if (!canvas) return;
  canvas.addEventListener('wheel', axZoom, { passive: false });
})();

// ===== Hi-DPI & Responsive : le backing store suit la largeur réelle et devicePixelRatio =====
let TL_CSS_H = 260;
let TL_CKWW = 1000;
let TL_CKVH = 260;

function fitCanvas() {
  const canvas = document.getElementById('timelineCanvas');
  if (!canvas) return;
  const dpr = window.devicePixelRatio || 1;
  const r = canvas.getBoundingClientRect();
  const cw = Math.max(300, r.width || 0);
  const isSmall = window.innerWidth <= 580;
  TL_CSS_H = isSmall ? 200 : 260;
  canvas.width = Math.round(cw * dpr);
  canvas.height = Math.round(TL_CSS_H * dpr);
  TL_CKWW = cw;
  TL_CKVH = TL_CSS_H;
  drawTimelineFull();
}
window.addEventListener('resize', () => requestAnimationFrame(fitCanvas));
window.addEventListener('orientationchange', () => setTimeout(fitCanvas, 150));

(function () {
  const canvas = document.getElementById('specCanvas');
  if (!canvas) return;
  const tip = document.getElementById('freqTip');
  const updateSpecTip = (clientX, clientY) => {
    if (!tlScale || !tip) return;
    const r = canvas.getBoundingClientRect();
    const x = clientX - r.left;
    const y = clientY - r.top;
    const fb = freqBounds();
    const h = r.height || 220;
    const f = fb[1] - ((y - 4) / Math.max(1, h - 8)) * (fb[1] - fb[0]);
    const fClamped = Math.max(fb[0], Math.min(fb[1], f));
    const t = tlScale.minT + ((x - 40) / Math.max(1, (TL_CKWW - 50))) * tlScale.span;
    const tStr = new Date(t * 1000).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23', timeZone: TZ_VIZ });
    tip.textContent = `Spectre · ${fClamped.toFixed(1)} Hz · ${tStr}`;
    tip.style.display = 'inline';
  };
  canvas.addEventListener('mousemove', (e) => updateSpecTip(e.clientX, e.clientY));
  canvas.addEventListener('mouseleave', () => { if (tip) tip.style.display = 'none'; });

  // Touch sur le spectrogramme
  canvas.addEventListener('touchmove', (e) => {
    if (e.touches && e.touches[0]) updateSpecTip(e.touches[0].clientX, e.touches[0].clientY);
  }, { passive: true });
  canvas.addEventListener('touchend', () => { if (tip) tip.style.display = 'none'; }, { passive: true });
})();

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

    def _check_auth(self) -> bool:
        """Vérifie le jeton d'authentification si configuré pour les actions d'écriture."""
        expected_token = (
            getattr(self.config.viz, "auth_token", None)
            if hasattr(self, "config") and self.config
            else None
        )
        if not expected_token:
            return True
        # Check Authorization: Bearer <token>
        auth_header = self.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
            if token == expected_token:
                return True
        # Check X-API-Key: <token>
        api_key_header = self.headers.get("X-API-Key", "").strip()
        if api_key_header == expected_token:
            return True
        self._send_json({"error": "Non autorisé (authentification requise)"}, status=401)
        return False

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
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if path == "/api/health":
            try:
                total = self.store.get_stats()["total_events"]
                self._send_json({"ok": True, "events_db_rows": total})
            except Exception as e:
                logger.error("Health check failed: %s", e)
                self._send_json({"ok": False, "error": "Erreur interne"}, status=500)
            return

        if path == "/api/stats":
            stats = self.store.get_stats()
            self._send_json(stats)
            return

        if path == "/api/events":
            try:
                raw_limit = int(qs.get("limit", [100])[0])
                offset = int(qs.get("offset", [0])[0])
                since = float(qs["since"][0]) if "since" in qs else None
                cluster = int(qs["cluster"][0]) if "cluster" in qs else None
                order = qs.get("order", ["desc"])[0]
            except (ValueError, IndexError):
                self.send_error(400, "Paramètre de requête invalide")
                return
            if raw_limit <= 0 or offset < 0:
                self.send_error(400, "limit doit > 0 et offset >= 0")
                return
            if order not in ("asc", "desc"):
                self.send_error(400, "order doit valoir 'asc' ou 'desc'")
                return
            limit = min(raw_limit, MAX_API_LIMIT)
            events = self.store.get_events(
                limit=limit, offset=offset, since=since, cluster=cluster, order=order
            )
            self._send_json(events)
            return

        if path == "/api/clusters":
            clusters = self.store.get_clusters_summary()
            self._send_json(clusters)
            return

        if path == "/api/reports/legal":
            try:
                since_rep = float(qs["since"][0]) if "since" in qs else None
                until_rep = float(qs["until"][0]) if "until" in qs else None
            except (ValueError, IndexError):
                self.send_error(400, "Paramètre de date invalide")
                return
            from bruittrack.legal import generate_legal_report

            events = self.store.get_events(since=since_rep, limit=MAX_API_LIMIT, order="asc")
            report = generate_legal_report(events, start_time=since_rep, end_time=until_rep)
            self._send_json(report)
            return

        if path == "/api/spectrum":
            try:
                since_spec = float(qs["since"][0]) if "since" in qs else None
                until_spec = float(qs["until"][0]) if "until" in qs else None
                raw_limit_spec = int(qs.get("limit", [20000])[0])
                order_spec = qs.get("order", ["asc"])[0].lower()
                step_spec = max(1, int(qs.get("step", [1])[0]))
            except (ValueError, IndexError):
                self.send_error(400, "Paramètre de requête invalide")
                return
            if order_spec not in ("asc", "desc"):
                self.send_error(400, "order doit valoir 'asc' ou 'desc'")
                return
            if raw_limit_spec <= 0:
                self.send_error(400, "limit doit > 0")
                return
            limit_spec = min(raw_limit_spec, MAX_API_LIMIT)
            # Bords linéaires identiques à SpectrumAggregator.band_edges (I64c)
            min_hz_f = self.config.dsp.min_event_hz
            max_hz_f = self.config.dsp.freq_max
            n_bands = self.config.spectrum.n_bands
            step_hz = (max_hz_f - min_hz_f) / n_bands
            edges = [round(min_hz_f + i * step_hz, 3) for i in range(n_bands + 1)]
            self._send_json(
                {
                    "rows": self.store.get_spectrum(
                        since=since_spec,
                        until=until_spec,
                        limit=limit_spec,
                        order=order_spec,
                        step=step_spec,
                    ),
                    "edges": edges,
                }
            )
            return

        if path == "/api/spectrum.png":
            try:
                since_spec = float(qs["since"][0]) if "since" in qs else None
                until_spec = float(qs["until"][0]) if "until" in qs else None
                width_spec = int(qs.get("width", [1000])[0])
                f_lo_spec = float(qs["f_lo"][0]) if "f_lo" in qs else None
                f_hi_spec = float(qs["f_hi"][0]) if "f_hi" in qs else None
                ch_spec = qs.get("ch", ["both"])[0].lower()
            except (ValueError, IndexError):
                self.send_error(400, "Paramètre de requête invalide")
                return

            if ch_spec not in ("both", "l", "d"):
                ch_spec = "both"

            png_bytes = self.store.get_spectrum_png(
                since=since_spec,
                until=until_spec,
                target_width=width_spec,
                n_bands=self.config.spectrum.n_bands,
                min_hz=self.config.dsp.min_event_hz,
                max_hz=self.config.dsp.freq_max,
                f_lo=f_lo_spec,
                f_hi=f_hi_spec,
                channel=ch_spec,
            )
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Content-Length", str(len(png_bytes)))
            self.end_headers()
            self.wfile.write(png_bytes)
            return

        if path == "/api/discomfort":
            try:
                since_disc = float(qs["since"][0]) if "since" in qs else None
                until_disc = float(qs["until"][0]) if "until" in qs else None
                raw_limit_disc = int(qs.get("limit", [1000])[0])
            except (ValueError, IndexError):
                self.send_error(400, "Paramètre de requête invalide")
                return
            limit_disc = min(max(1, raw_limit_disc), MAX_API_LIMIT)
            logs = self.store.get_discomfort_logs(
                since=since_disc,
                until=until_disc,
                limit=limit_disc,
                snapshots_dir=self.config.storage.snapshots_dir,
            )
            self._send_json(logs)
            return

        if path.startswith("/api/discomfort/") and path.endswith("/snapshot"):
            try:
                parts = path.strip("/").split("/")
                log_id = int(parts[2])
                snap = self.store.get_discomfort_snapshot(
                    log_id, snapshots_dir=self.config.storage.snapshots_dir
                )
                if snap is None:
                    self.send_error(404, "Snapshot not found")
                    return
                self._send_json(snap)
                return
            except Exception as e:
                logger.error("Error retrieving snapshot for %s: %s", path, e)
                self.send_error(500, "Error retrieving snapshot")
                return

        if path.startswith("/api/discomfort/") and path.endswith("/audio"):
            try:
                parts = path.strip("/").split("/")
                log_id = int(parts[2])
                wav_path = Path(self.config.storage.snapshots_dir) / f"snap_{log_id}.wav"
                if wav_path.is_file():
                    with open(wav_path, "rb") as wf:
                        wav_bytes = wf.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "audio/wav")
                    self.send_header("Content-Length", str(len(wav_bytes)))
                    self.end_headers()
                    self.wfile.write(wav_bytes)
                    return
                else:
                    self.send_error(404, "Snapshot audio not found")
                    return
            except Exception as e:
                logger.error("Error serving audio snapshot %s: %s", path, e)
                self.send_error(500, "Error serving audio")
                return

        if path.startswith("/api/exemplar/"):
            # Format: /api/exemplar/<cluster_id>
            raw_id = path.split("/")[-1].split(".")[0]
            try:
                cluster_id = int(raw_id)
            except (ValueError, IndexError):
                self.send_error(400, "Identifiant d'exemplaire invalide")
                return

            try:
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
                logger.error("Error generating WAV for exemplar %s: %s", cluster_id, e)
                self.send_error(500, "Error generating WAV")
                return

        self.send_error(404, "Not Found")

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/api/discomfort":
            content_length_hdr = self.headers.get("Content-Length")
            if content_length_hdr is None:
                self.send_error(411, "Length Required")
                return
            try:
                content_length = int(content_length_hdr)
                if content_length < 0 or content_length > MAX_POST_BODY:
                    self.send_error(400, "Invalid Content-Length")
                    return
                body = self.rfile.read(content_length).decode("utf-8-sig")
                payload = json.loads(body)
                level = int(payload.get("level", 3))
                note = str(payload.get("note", ""))
                t0 = float(payload.get("t0", time.time()))
                log_id = self.store.log_discomfort(t0=t0, level=level, note=note)

                # Capture snapshot if engine is attached or payload has snapshot
                snapshot_data = payload.get("snapshot")
                if snapshot_data:
                    self.store.save_discomfort_snapshot(
                        log_id, snapshot_data, snapshots_dir=self.config.storage.snapshots_dir
                    )
                elif hasattr(self.server, "engine") and getattr(self.server, "engine", None):
                    try:
                        self.server.engine.capture_discomfort_snapshot(log_id)
                    except Exception as e:
                        logger.warning(
                            "Could not capture live snapshot for discomfort %s: %s", log_id, e
                        )

                has_snap = (
                    Path(self.config.storage.snapshots_dir) / f"snap_{log_id}.npz"
                ).is_file()
                self._send_json({"ok": True, "id": log_id, "has_snapshot": has_snap})
                return
            except Exception as e:
                logger.error("Error creating discomfort log: %s", e)
                self._send_json({"error": "Erreur enregistrement gêne"}, status=400)
                return

        if path.startswith("/api/discomfort/") and path.endswith("/delete"):
            try:
                parts = path.strip("/").split("/")
                log_id = int(parts[2])
                ok = self.store.delete_discomfort_log(
                    log_id, snapshots_dir=self.config.storage.snapshots_dir
                )
                self._send_json({"ok": ok})
                return
            except Exception as e:
                logger.error("Error deleting discomfort log: %s", e)
                self._send_json({"error": "Erreur suppression gêne"}, status=400)
                return

        if path.startswith("/api/clusters/") and path.endswith("/triage"):
            if not self._check_auth():
                return
            try:
                parts = path.strip("/").split("/")
                if (
                    len(parts) != 4
                    or parts[0] != "api"
                    or parts[1] != "clusters"
                    or parts[3] != "triage"
                ):
                    self.send_error(404, "Not Found")
                    return
                cluster_id = int(parts[2])
                content_length_hdr = self.headers.get("Content-Length")
                if content_length_hdr is None:
                    self.send_error(411, "Length Required")
                    return
                try:
                    content_length = int(content_length_hdr)
                except (ValueError, TypeError):
                    self.send_error(400, "Invalid Content-Length")
                    return
                if content_length < 0:
                    self.send_error(400, "Invalid Content-Length")
                    return
                if content_length > MAX_POST_BODY:
                    self.send_error(413, "Payload Too Large")
                    return

                body = self.rfile.read(content_length).decode("utf-8-sig")
                payload = json.loads(body)

                flags = int(payload.get("flags", 0))
                label = payload.get("label")

                success = self.store.set_cluster_triage(cluster_id, flags, label)
                self._send_json({"success": success, "cluster_id": cluster_id})
                return
            except (json.JSONDecodeError, ValueError, KeyError):
                self._send_json({"error": "Corps de requête invalide"}, status=400)
                return
            except Exception as e:
                logger.error("Error processing triage for cluster %s: %s", cluster_id, e)
                self._send_json({"error": "Erreur interne du serveur"}, status=500)
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
