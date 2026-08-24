"""Patch I54 batch M3: fenêtrage ?since=, panFreqBy, badge+reset, plafond table."""
import sys

p = 'src/bruittrack/viz.py'
s = open(p, encoding='utf-8', newline='').read().replace('\r', '')

def rep(old: str, new: str) -> None:
    global s
    if old not in s:
        sys.exit('MISSING: ' + old[:80].replace('\n', ' | '))
    if s.count(old) != 1:
        sys.exit(f'count {s.count(old)}: {old[:60]}')
    s = s.replace(old, new)

blob = r"""// ===== I54 : fenêtrage de données, pan fréquence, badge, reset des 2 axes =====
let dataSince = null; // t0 le plus ancien chargé localement (I54)
let dataUntil = null; // t0 le plus récent chargé localement (I54)
let fetchingWin = false;

async function fetchWindow() { // I54 : fenêtre ?since= dynamique — le limit fixe ne suffit pas au zoom
  if (!tlMode || !tlScale || fetchingWin) return;
  const lo = tlScale.minT - 300, hi = tlScale.minT + tlScale.span + 300;
  if ((dataSince === null || lo >= dataSince) && (dataUntil === null || hi <= dataUntil)) return;
  fetchingWin = true;
  try {
    const sinceT = dataSince !== null ? Math.min(dataSince, Math.floor(lo)) : Math.floor(lo);
    const got = await fetchJson(`/api/events?since=${sinceT}&limit=20000`);
    if (!got || !Array.isArray(got)) return;
    const map = new Map();
    (eventsData || []).forEach((e) => { if (e.id !== undefined) map.set(e.id, e); });
    got.forEach((e) => { if (e.id !== undefined) map.set(e.id, e); }); // merge/dédup par id
    eventsData = Array.from(map.values());
    const t0s = eventsData.map((e) => e.t0);
    dataSince = t0s.length ? Math.min.apply(null, t0s) : null;
    dataUntil = t0s.length ? Math.max.apply(null, t0s) : null;
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
  const ts = tlScale ? new Date(tlScale.minT * 1000).toISOString().slice(5, 16).replace('T', ' ') : '';
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
    drawTimelineFull();
  });
  document.addEventListener('mouseup', () => { if (startY !== null) { startY = null; startFB = null; updateZoomBadge(); } });
})();

async function refreshAll() {"""
rep("async function refreshAll() {", blob)

rep("""  if (events) {
    eventsData = events;
""",
    """  if (events) {
    eventsData = events;
    { // I54 : bornes des données chargées, déclenche fetchWindow() si besoin
      const t0s = events.map((e) => e.t0);
      dataSince = t0s.length ? Math.min.apply(null, t0s) : null;
      dataUntil = t0s.length ? Math.max.apply(null, t0s) : null;
    }
""")

rep("""  zoomTimeAt(mx, k);
  drawTimelineFull();
}""",
    """  zoomTimeAt(mx, k);
  refreshWindowed(); // I54 : fenêtre ?since= si la vue s'étend avant les données chargées
}""")

rep("""    tlBrushPx = null;
    drawTimelineFull();""",
    """    tlBrushPx = null;
    refreshWindowed(); // I54 : fenêtre dynamique si le zoom brushing est actif""")

rep("""  canvas.addEventListener('dblclick', () => { // double-clic : retour à la fenêtre boutons
    if (tlMode) { tlMode = null; syncTlButtons(); drawTimelineFull(); }
  });""",
    """  canvas.addEventListener('dblclick', resetFviews); // I54 : double-clic réinitialise X + Y""")

rep("""  window.addEventListener('keydown', (e) => { // Échap : annule le zoom brushing
    if (e.key === 'Escape' && tlMode) { tlMode = null; syncTlButtons(); drawTimelineFull(); }
  });""",
    """  window.addEventListener('keydown', (e) => { // Échap : réinitialise les vues I54
    if (e.key === 'Escape') resetFviews();
  });""")

rep("function drawTimeline(events) {\n",
    """function drawTimeline(events) {
  updateZoomBadge(); // I54 : badge toujours en phase avec les vues courantes
""")

old_tbl = r"""  tbody.innerHTML = events.map(e => {
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
}"""
new_table = """  const MAX_ROWS = 500; // I54 : plafond de lignes affichées dans le tableau
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
"""
new_table_tail = r"""    return `<tr data-ev-id="${e.id}"${e.id === selectedEvId ? ' class="ev-row-selected"' : ''} onclick="selectEv(${e.id})">
      <td>${formatDate(e.t0)}</td>
      <td><strong>${e.freq.toFixed(1)} Hz</strong></td>
      <td>${chBadge}</td>
      <td>+${e.lvl_g.toFixed(1)} / +${e.lvl_d.toFixed(1)} dB</td>${olBadge}
      <td>${e.dur.toFixed(1)} s</td>
      <td><span class="badge badge-cluster" style="background:${getClusterColor(e.cluster)}22; color:${getClusterColor(e.cluster)}">#${e.cluster || '-'}</span></td>
    </tr>`;
}"""
new_table = new_table + new_table_tail
rep(old_tbl, new_table)

rep("""        <span class="evt-tip" id="freqTip">Fréq. : ≈ XX.X Hz</span>""",
    """        <span class="evt-tip" id="freqTip">Fréq. : ≈ XX.X Hz</span>
        <span id="zoomBadge" onclick="resetFviews()" style="display:none; cursor:pointer; color:#94a3b8; font-size:12px;"></span>""")

open(p, 'w', encoding='utf-8', newline='\r\n').write(s)
print('all M3 edits applied')
