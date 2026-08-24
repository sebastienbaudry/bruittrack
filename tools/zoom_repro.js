const fs = require('fs');
// Reproduit la page servie (script de viz.py) dans node avec DOM stub,
// puis simule la molette sur l'axe temps : invariance du point sous le curseur.
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
if (typeof g.axZoom !== 'function' || typeof g.yToAnchorTime !== 'function') {
  console.error('fonctions attendues absentes du global', Object.keys(gObj).filter((k) => k.startsWith('y') || k.includes('ax')));
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
for (let tick = 0; tick < 6; tick++) {
  // avant la molette : temps sous LE curseur selon le dessin précédent (vérité terrain)
  const before = tAt({ m: state.lastDrawMinT, s: state.lastDrawSpan, w: state.lastW }, MX);
  const ev = { clientX: MX, clientY: MY, deltaY: -1, currentTarget: els['timelineCanvas'] };
  g.axZoom(ev);
  await new Promise((r) => setTimeout(r, 30)); // laisse le then(drawTimelineFull)
  await new Promise((r) => setTimeout(r, 30));
  const after = tAt({ m: state.lastDrawMinT, s: state.lastDrawSpan, w: state.lastW }, MX);
  const delta = Math.abs(after - before);
  console.log(`tick ${tick}: avant=${before.toFixed(3)} après=${after.toFixed(3)} |Δ|=${delta.toFixed(4)} s; ` +
    `dessin [minT,span]=[${state.lastDrawMinT? state.lastDrawMinT.toFixed(1):null}, ${state.lastDrawSpan}]`);
  if (!(delta < 0.01)) { ok = false; console.log('  !! ANCRAGE TEMPS NON CONSERVÉ'); }
}
// test dézoom complet
for (let tick = 0; tick < 14; tick++) {
  const before = tAt({ m: state.lastDrawMinT, s: state.lastDrawSpan, w: state.lastW }, MX);
  const ev = { clientX: MX, clientY: MY, deltaY: 1, currentTarget: els['timelineCanvas'] };
  g.axZoom(ev);
  await new Promise((r) => setTimeout(r, 30));
  const after = tAt({ m: state.lastDrawMinT, s: state.lastDrawSpan, w: state.lastW }, MX);
  const delta = Math.abs(after - before);
  if (!(delta < 0.01)) { ok = false; console.log(`dézoom tick ${tick} !! |Δ|=${delta.toFixed(4)}s avant=${before} après=${after} minT=${state.lastDrawMinT}`); }
}
console.log(ok ? 'ROUND-TRIP OK : le temps sous le curseur est conservé' : 'ECHEC ANCRAGE');
process.exit(ok ? 0 : 1);
})();
