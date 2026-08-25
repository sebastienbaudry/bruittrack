const fs = require('fs');
// Reproduit la page servie (script de viz.py) dans node avec DOM stub,
// puis simule la molette (I61 : axe Y SEUL) : invariance de la fréquence sous
// le curseur ET de l'axe temps (la molette ne touche plus X).
const vm = require('vm');

const src = fs.readFileSync(process.argv[2] || 'src/bruittrack/viz.py', 'utf8');
const m = src.match(/<script>\s*([\s\S]*?)<\/script>/);
if (!m) { console.error('script non trouvé'); process.exit(2); }
let js = m[1].replace(/__FREQ_MAX__/g, '150').replace(/__MIN_EVENT_HZ__/g, '2');

const W = 987; // largeur CSS simulée (user retina)
function makeEl(id) {
  const el = {
    id, style: {}, dataset: {}, textContent: '', innerHTML: '', selected: false,
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    addEventListener() {}, removeEventListener() {},
    getBoundingClientRect: () => ({ left: 0, top: 0, width: W, height: 260 }),
    getContext: () => ctxProxy(),
    width: 1000, height: 260,
  };
  return el;
}
function ctxProxy() {
  const anyFn = new Proxy(function () { return anyFn; }, { get: (t, p) => anyFn });
  return new Proxy({}, {
    get: (t, p) => (p in t ? t[p] : anyFn),
    set: (t, p, v) => { t[p] = v; return true; },
  });
}

const els = {};
const tickCalls = []; // (minT, span) réellement dessinées par drawTimeTicks
const state = { events: [], lastDrawMinT: null, lastDrawSpan: null, points: [] };

// Jeu de données injecté via le stub fetch ci-dessous (12 evt / 11 h).
// NB : on ne peut PAS passer par g.lastVisible = [...] — lastVisible est déclaré
// avec let dans le script embarqué (liaison lexicale qui masque la propriété
// globale du sandbox) ; seules les données chargées par refreshAll() comptent.
const EVS = [];
for (let i = 0; i < 12; i++) {
  EVS.push({ id: i + 1, t0: 1_700_000_000 + i * 3600, freq: 20 + i * 9, lvl_g: 12, lvl_d: 12, dur: 8, cluster: (i % 4) + 1, off_ms: 0 });
}

// Captures : patch de drawTimeTicks + comptage des arcs dessinés
function sandbox() {
  const g = {
    console,
    window: null, // défini plus bas (self-référence)
    document: {
      getElementById: (id) => (els[id] ||= makeEl(id)),
      createElement: () => makeEl('x'),
      addEventListener: () => {},
      querySelectorAll: () => [],
      querySelector: () => null,
    },
    setInterval: () => 0, clearInterval: () => {},
    setTimeout: (fn) => 0, clearTimeout: () => {},
    // requestAnimationFrame : exécuté immédiatement mais une seule fois
    requestAnimationFrame: makeRAF(), cancelAnimationFrame: () => {},
    // Stub fetch : répond aux 3 endpoints consommés par refreshAll/fetchWindow.
    // Sans lui, eventsData reste vide et drawTimeline recale minT sur
    // Date.now() à chaque redraw (branche état vide) → fausse dérive d'ancrage.
    fetch: async (url) => ({
      ok: true,
      json: async () => {
        if (String(url).includes('/api/clusters')) return [];
        if (String(url).includes('/api/stats')) return { total_events: EVS.length };
        if (String(url).includes('/api/events')) return EVS;
        return null;
      },
    }),
    Date, Math, JSON, Map, Set, Promise, Object, Array, Number, Infinity, isNaN, parseFloat,
  };
  g.window = { devicePixelRatio: 2, addEventListener: () => {} };
  globalAny(g);
  return g;
}
let rafQueue = [];
function makeRAF() {
  return (fn) => { rafQueue.push(fn); return rafQueue.length; };
}
function globalAny(g) {
  // certains scripts référencent des valeurs du host window globales
  const a = Object.create(null);
  new Proxy(a, {});
}

const gObj = sandbox();
gObj.location = { search: '', hash: '' };
gObj.addEventListener = () => {}; // au cas où attaché sur globalThis

try {
  vm.runInNewContext(js, gObj, { filename: 'viz-embedded.js' });
} catch (e) {
  console.error('ERREUR EXEC DU SCRIPT EMBARQUE :', e.message);
  process.exit(3);
}

// exécute les rAF initiaux (fitCanvas + refreshAll)
while (rafQueue.length) { const q = rafQueue; rafQueue = []; q.forEach((f) => f()); }
(async () => {
const g = gObj;
if (typeof g.axZoom !== 'function' || typeof g.freqBounds !== 'function' || typeof g.yToFreq !== 'function') {
  console.error('fonctions attendues absentes du global', Object.keys(gObj).filter((k) => k.startsWith('y') || k.includes('ax') || k.includes('req')));
  process.exit(4);
}

// Instrument : capture des appels drawTimeTicks (le vrai dessin de l'axe).
// Posé AVANT toute attente : le premier draw (post-fetch, microtasks de
// refreshAll) doit être capturé, sinon tick 0 n'a pas de vérité terrain.
const origTicks = g.drawTimeTicks;
g.drawTimeTicks = function (ctx, w, h, minT, span) {
  state.lastDrawMinT = minT; state.lastDrawSpan = span; state.lastW = w;
  tickCalls.push([minT, span]);
  return origTicks && origTicks(ctx, w, h, minT, span);
};

await new Promise((r) => setTimeout(r, 50));

// Données déjà chargées via le stub fetch (EVS, étendue 11 h) — voir note sandbox.

const MX = 400, MY = 130; // pile du curseur (px CSS)
function drawX(m) { return 40 + ((m - state.lastDrawMinT) / state.lastDrawSpan) * (state.lastW - 50); }
function tAt(drawObj, px) { return drawObj.minTmin ? 0 : drawObj.m + ((px - 40) / (drawObj.w - 50)) * drawObj.s; }

let ok = true;
let prevDrawMinT = null, prevDrawSpan = null;
// I61 : la molette zoome l'axe Y SEUL — deux invariants :
//   (a) l'axe temps n'est PAS touché par la molette : span strictement constant ;
//       (en vue pleine tlMode=null, minT suit l'horloge courante à chaque redraw —
//       dérive attendue = temps mur écoulé, tolérée ci-dessous) ;
//   (b) la fréquence sous le curseur Y est conservée (zoom centré curseur).
const H = 260; // TL_CKVH du sandbox (getBoundingClientRect height)
function fUnderCursor() { // fréquence sous MY = inverse EXACT de yOfFreq (I61c : ne pas dupliquer une formule fausse)
  const fb = g.freqBounds();
  return fb[0] + ((H - 20 - MY) / (H - 40)) * (fb[1] - fb[0]);
}
for (let tick = 0; tick < 6; tick++) {
  const tBefore = [state.lastDrawMinT, state.lastDrawSpan];
  const fBefore = fUnderCursor();
  const wall0 = Date.now();
  const ev = { clientX: MX, clientY: MY, deltaY: -1, preventDefault() {}, currentTarget: els['timelineCanvas'] };
  g.axZoom(ev);
  await new Promise((r) => setTimeout(r, 30)); // laisse le rAF drawTimelineFull(false)
  await new Promise((r) => setTimeout(r, 30));
  const dSpan = Math.abs(state.lastDrawSpan - tBefore[1]);
  const dMinT = Math.abs(state.lastDrawMinT - tBefore[0]);
  const allowed = (Date.now() - wall0) / 1000 + 0.05; // dérive horloge tolérée uniquement
  const df = Math.abs(fUnderCursor() - fBefore);
  console.log(`zoom tick ${tick}: Δspan=${dSpan} ΔminT=${dMinT.toFixed(3)}s (tol ${allowed.toFixed(3)}); f Curseur ${fBefore.toFixed(2)}→${fUnderCursor().toFixed(2)} Hz (|Δ|=${df.toFixed(3)})`);
  if (!(dSpan < 1e-9)) { ok = false; console.log('  !! SPAN TEMPS MODIFIÉ PAR LA MOLETTE (I61 violé)'); }
  if (!(dMinT < allowed)) { ok = false; console.log('  !! MINT DÉCALÉ AU-DELÀ DE LA DÉRIVE HORLOGE (I61 violé)'); }
  if (!(df < 0.1)) { ok = false; console.log('  !! ANCRAGE FRÉQUENCE NON CONSERVÉ'); }
}
// test dézoom complet (retour vue pleine [0, FREQ_MAX] inclus)
for (let tick = 0; tick < 14; tick++) {
  const tBefore = [state.lastDrawMinT, state.lastDrawSpan];
  const fBefore = fUnderCursor();
  const ev = { clientX: MX, clientY: MY, deltaY: 1, preventDefault() {}, currentTarget: els['timelineCanvas'] };
  g.axZoom(ev);
  await new Promise((r) => setTimeout(r, 30));
  const dSpan = Math.abs(state.lastDrawSpan - tBefore[1]);
  const df = Math.abs(fUnderCursor() - fBefore);
  if (!(dSpan < 1e-9)) { ok = false; console.log(`dézoom tick ${tick} !! span temps modifié (Δ=${dSpan})`); }
  if (!(df < 0.1)) { ok = false; console.log(`dézoom tick ${tick} !! |Δf|=${df.toFixed(3)} Hz avant=${fBefore} après=${fUnderCursor()}`); }
}
if (!(g.freqBounds()[0] === 0 && g.freqBounds()[1] === 150)) {
  ok = false; console.log(`!! dézoom ne retombe pas sur la vue pleine : [${g.freqBounds()}]`);
} else { console.log('DÉZOOM COMPLET OK : retour vue pleine [0, 150]'); }
// — I61b ANCRAGE BAS : curseur près du bas (MY=230) → une fois le plancher 2 Hz atteint,
//   le clamp doit rester RÉPARTI autour du curseur (l'ancien recentrage sur le centre
//   géométrique faisait dériver la vue vers le haut d'un crant à l'autre) —
{
  vm.runInContext('freqView = null;', gObj, { filename: 'i61b-reset.js' });
  const MYB = 230;
  const fbFull = g.freqBounds();
  const fStar = fbFull[0] + ((H - 20 - MYB) / (H - 40)) * (fbFull[1] - fbFull[0]); // fréquence visée, figée (inverse exact de yOfFreq)
  let okB = true;
  for (let tick = 0; tick < 10; tick++) {
    const ev = { clientX: MX, clientY: MYB, deltaY: -1, preventDefault() {}, currentTarget: els['timelineCanvas'] };
    g.axZoom(ev);
    await new Promise((r) => setTimeout(r, 20));
    const fb = g.freqBounds();
    const fCur = fb[0] + ((H - 20 - MYB) / (H - 40)) * (fb[1] - fb[0]);
    if (!(Math.abs(fCur - fStar) < 0.15)) { okB = false; console.log(`I61b tick ${tick} !! f curseur ${fCur.toFixed(2)} ≠ ancre ${fStar.toFixed(2)} (vue [${fb.map((x) => x.toFixed(1))}])`); }
  }
  if (!okB) { ok = false; console.log('!! I61b : clamp span min non ancré curseur'); }
  else { console.log(`I61b OK : plancher 2 Hz atteint sans dérive (ancre ${fStar.toFixed(1)} Hz conservée)`); }
  vm.runInContext('freqView = null;', gObj, { filename: 'i61b-reset2.js' }); // état propre pour les checks suivants
}
// — I60 NON-VIDE : fenêtre couvrant les 12 EVS → le tableau doit afficher EXACTEMENT ces ids —
{
  vm.runInContext('try { tlMode = null; if (typeof timeWindow !== "undefined") timeWindow = null; } catch (e) {}', gObj, { filename: 'i60-reset-window.js' });
  g.drawTimeline(EVS); g.syncEventsToTable();
  const shown2 = ((els['eventsTableBody'].innerHTML || '').match(/data-ev-id="(\d+)"/g) || [])
    .map((x) => Number(x.replace(/\D/g, '')));
  if (shown2.length !== EVS.length || !EVS.every((e) => shown2.includes(e.id))) {
    ok = false; console.log(`!! SYNC NON-VIDE : ${shown2.length} lignes (attendu ${EVS.length})`);
  } else { console.log(`SYNC NON-VIDE OK : ${shown2.length} lignes == 12 EVS`); }
}
// — I60 CHECK SYNC : le tableau affiche STRICTEMENT le set rendu dans la fenêtre [minT, minT+span] —
{
  const winMin = state.lastDrawMinT, winSpan = state.lastDrawSpan;
  const expect = EVS.filter((e) => e.t0 >= winMin - 1e-9 && e.t0 <= winMin + winSpan + 1e-9)
    .map((e) => e.id).sort((a, b) => b - a);
  const html = els['eventsTableBody'].innerHTML || '';
  const shown = (html.match(/data-ev-id="(\d+)"/g) || []).map((x) => Number(x.replace(/\D/g, '')));
  if (JSON.stringify(shown) !== JSON.stringify(expect)) {
    ok = false; console.log(`!! SYNCHRO TABLEAU: affiché [${shown}] attendu [${expect}]`);
  } else { console.log(`SYNC TABLEAU OK : ${shown.length} ligne(s) == set de la fenêtre visible`); }
  const big = Array.from({ length: 3000 }, (_, i) => ({ id: 9000 + i, t0: winMin + i, freq: 10, lvl_g: 5, lvl_d: 5, dur: 1, cluster: null }));
  g.renderEventsTable(big);
  const capHtml = els['eventsTableBody'].innerHTML;
  const capRows = (capHtml.match(/data-ev-id="/g) || []).length;
  if (capRows !== 500 || capHtml.indexOf('… + 2500') < 0) {
    ok = false; console.log(`!! PLAFOND 500: ${capRows} lignes, compteur trouvé=${capHtml.includes('… + 2500')}`);
  } else { console.log('PLAFOND 500 OK : 500 lignes + compteur'); }
}
// — FIN I60 —
// — I59 B1 SOURCE BRUTE : après une vue restreinte, drawTimelineFull repart de eventsData —
//   l'ancien code réinjectait lastVisible (vue filtrée) en entrée : le dézoom laissait
//   définitivement les points hors de la vue précédente hors du graphe ET du tableau.
{
  // filtres DOM du sandbox : valeurs neutres (sinon filterEvents vide tout artificiellement)
  for (const [id, v] of [['chanFilter', ''], ['clusterFilter', ''], ['minLvlFilter', '0']]) {
    const el2 = els[id] || makeEl(id); els[id] = el2; el2.value = v;
  }
  vm.runInContext('tlMode = null;', gObj, { filename: 'i59-prep.js' }); // état propre
  g.drawTimelineFull();
  vm.runInContext(`tlMode = {minT: ${EVS[3].t0 - 10}, span: 30};`, gObj, { filename: 'i59-narrow.js' }); // fenêtre ~1 evt
  g.drawTimelineFull();
  const shrunkRows = ((els['eventsTableBody'].innerHTML || '').match(/data-ev-id="(\d+)"/g) || []).length;
  vm.runInContext('tlMode = null; timeWindow = null;', gObj, { filename: 'i59-reset.js' });
  g.drawTimelineFull(); // retour "Tout" : les 12 EVS doivent REAPPARAITRE
  const back = ((els['eventsTableBody'].innerHTML || '').match(/data-ev-id="(\d+)"/g) || [])
    .map((x) => Number(x.replace(/\D/g, '')));
  if (back.length !== EVS.length || !EVS.every((e) => back.includes(e.id))) {
    ok = false;
    console.log(`!! I59 AMPUTATION : vue restreinte=${shrunkRows} ligne(s), dézoom restaure ${back.length}/${EVS.length} — lastVisible réutilisé comme source ?`);
  } else {
    console.log(`I59 SOURCE BRUTE OK : dézoom restaure les ${EVS.length} événements (vue restreinte avait ${shrunkRows} ligne(s))`);
  }
}
console.log(ok ? 'ROUND-TRIP OK : axe X intact + fréquence sous le curseur conservée' : 'ECHEC ANCRAGE I61');
process.exit(ok ? 0 : 1);
})();
