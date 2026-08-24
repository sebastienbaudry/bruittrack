# GOAL — I54 : zoom/dézoom interactif sur les 2 axes du chronogramme

Check fin de tour : `bash tools/zoom_check.sh` → affiche `SCORE: n/8`, exit 0 dès que
les 6 critères core (Z1–Z6) sont atteints.

## Objectif
Permettre de zoomer/dézoomer sur **les deux axes** (X = temps, Y = fréquence)
du graphique « Chronogramme des événements » du dashboard web
(`src/bruittrack/viz.py`, template HTML canvas :~830 lignes), sans aucune
dépendance JS externe (canvas pur + stdlib).
Contrainte utilisateur : **toutes les données de la plage temporelle visible
doivent être affichées** — la récupération des événements doit être dynamique
(fenêtrage `since`), jamais un `?limit=200` figé.

## État de départ (vérifié)
- Baseline : `pytest -q` → 101 passés ; **ruff ROUGE** : définition en double
du test `test_apply_retention_prunes_exemplars` (`tests/test_store.py`
~L377 et ~L404) → `bash tools/check.sh` retourne ≠ 0. M0 commence par réparer ça.
- Template JS actuel (`src/bruittrack/viz.py`) :
  - fetch statique : `fetchJson('/api/events?limit=200')` (~L234), polling
    `setInterval(refreshAll, 10000)` (~L685) ;
  - axe Y figé : `function yOfFreq(f)` (~L473) et `stepHz = niceHzStep(FREQ_MAX / 5)`
    (~L511) bornés à FREQ_MAX, `Math.min(f, FREQ_MAX)` en entrée ;
  - fenêtre temps : boutons winBtn* / `tlMode` + brush drag → `brushZoom(` (I39)
    — **contrat à préserver** ;
  - API dispo sans modif serveur : `/api/events?limit&offset&since&cluster`
    (`store.get_events(..., since=)` existe déjà).

## Périmètre / contrats (tokens EXACTS exigés dans le HTML servi)
| Marqueur | Rôle |
|----------|------|
| `let freqView = null;` | état vue fréquence : `null` → [0, FREQ_MAX] sinon `{fLo, fHi}` |
| `function axZoom(` | molette sur canvas : zoom/dézoom **les 2 axes** centré curseur (ancrage X = temps sous x-curseur, ancrage Y = fréquence sous y-curseur) |
| `function panFreqBy(` | Ctrl + glisser vertical → translate de l'axe fréquence seul |
| `function fetchWindow(` | rechargement dynamique `/api/events?since=<minT>&limit=20000` + merge dédupé par id, déclenché quand la vue X s'étend à gauche de `dataSince` |
| `function renderTableRow(` | lignes du tableau événement ; plafonné 500 lignes visible + note « (sur N) » si plus |
| `<span id="zoomBadge">` | badge visible dès que `freqView` ou une vue temps libre est active ; « ×k · f a–b Hz · t a → b » ; re-cliquable pour réinitialiser |

Contraintes mécaniques :
- Zoom molette : facteur ±1.3/arret ; clamp temps span ∈ [10 s, 90 j] borné par
  l'étendue des données chargées ; clamp fréquence span ≥ 2 Hz, [fLo,fHi] ⊂ [0, FREQ_MAX] ;
  clamp indépendant par axe (peut ne bouger qu'un axe en bout de course).
- Reset : double-clic sur canvas ET touche Échap → `freqView = null`, vue temps
  de retour au mode bouton actif par défaut (24 h), `fetchWindow` repris, badge caché.
- Drag **normal** horizontal : brush time I39 inchangé. Ctrl+drag ne touche que freqView.
- HiDPI, filtres actuels (canal/lvl/cluster/onlyLegal), tooltip `evtTip`, crosshair
  (I50) et lecture fréquence sous curseur (I49) restent fonctionnels sur la vue zoomée ;
  les graduations Y re-calculées avec `niceHzStep((hi-lo)/5)` sur `[fLo,fHi]` ;
  graduations temps recalculées sur la fenêtre visible (grille I48 conservée).

## Hors périmètre
pas de gestures tactile/pinch, pas de box-zoom (drag = brush I39), pas de nouvelle
route API ni de modif du pipeline DSP/détection, pas de bibliothèque JS, pas de
persistance du zoom (URL hash) — c'est du backlog de suite.

## Critères de fin mesurables (core = Z1–Z6 via tools/zoom_check.sh)
1. `bash tools/check.sh` exit 0 (ruff vert + **≥ 103 tests passés**).
2. Z-tokens : HTML servi / template contient `axZoom(`, `let freqView`, `panFreqBy(`,
   `fetchWindow(` + `?since=`, `renderTableRow(`, `id="zoomBadge"`.
3. Régression **zéro** : tous les marqueurs existants de `tests/test_viz_api.py`
   passent sans modification (`toggleChannel`, `evtTip`, `timelinePoints`, `showCh`,
   `let FREQ_MAX = 150;`, crosshair I50, I49...). Nouvelle démo `test_viz_zoom_markers`.
4. Complétude de données : fenêtre « Tout » sans zoom → fetch via `since` (plus le
   `?limit=200` unique) ; scénario testé en local : ~3 h de données synthétiques > 500
   événements ⇒ le tableau affiche la note plafonnée, le canvas tous les points visibles.
5. Docs : entrée decision-log (molette 2 axes + fenêtrage since), README §Viz une
   ligne usage, IMPROVEMENTS.md : I54 ajouté+coché à M4 ; PROGRESS.md à jour à chaque M.
6. Déploiement pi-t620 : `bash scripts/deploy_pi.sh` → DEPLOY_OK rc=0, puis
   `curl -s localhost:8760 | grep -c 'axZoom('` ≥ 1 (B2).

## Feuille de route
- **M0 — Réparer la baseline** : fusionner les deux tests en double de
tests/test_store.py (conserver le corps du 1er, ajouter l'assertion legacy du 2nd :
au 2e appel `apply_retention` sans `exemplars_dir` → aucun fichier écrasé/purge),
ruff + check.sh verts. Commit « test(store): M0 fusion doublon I52 ».
- **M1 — Générer les axes** : `let freqView = null;`, vue dérivée par frame
  `fy={lo,hi}` ; généraliser `yOfFreq`, `stepHz`, garde-fou Y des points et frt
  fréquence (I49) sur `[fLo,fHi]`. Sans zoom, rendu identique au comportement actuel.
- **M2 — Fenêtrage de données** : `fetchWindow(sinceUnix, cap=20000)` + `dataSince` ;
déplacer le chargement initial et le polling 1 s par là ; merge dédupé par id ;
tableau via `renderTableRow(` plafonné 500 + note. Plus de `?limit=200`.
- **M3 — Interactions** : `axZoom(` molette (preventDefault, dual-axis clampées),
`panFreqBy(` Ctrl+drag, reset dblclick+Échap, badge zoomBadge (+ ré-init au clic),
désync des boutons winBtn* quand vue temps libre (re-sync au reset).
- **M4 — Docs** : decision-log + README + IMPROVEMENTS I54 (non cochée→cochée) + PROGRESS.
  Commit doc.
- **M5 — Déployer pi-t620** : `bash scripts/deploy_pi.sh` (DEPLOY_OK), vifs marqueurs
  sur :8760, santé OK, commit final + push local→origin si possible.

## Normes de qualité
- Un commit conventional par milestone (`feat(viz):`, `test(viz):`, `docs:` ...)
  ; jamais dégrader les gates existantes entre deux checkpoints ; numpy/scipy/
sounddevice+stdlib uniquement (zéro nouvelle dépendance côté backend ni JS tiers) ;
pas de magic number non nommé (facteur 1.3, clamps → constantes nommées en tête du script JS).

## Hypothèses explicites
- Le endpoint `/api/events?since=` suffit (pas de pagination serveur ajoutée) ;
  cap client 20 000 lignes ≫ density max attendue (~1 400 lignes totales sur 30 j).
- Les tests frontend restent des assertions par marqueur token dans
  `tests/test_viz_api.py` (« test » sans navigateur de l'existant ; le canvas est
  dans une chaîne template Python).
- Le badge « dernier refresh » d'I53 éventuel est indépendant ; ici on n'ajoute
  que le badge zoom.

## Suite post-core (amélioration continue, enchaînement si l'opérateur continue)
- I55 : persistance du zoom (hash URL `#t=..&f=..`) + raccourcis clavier (+/−/0).
- I56 : double-clic sur un point = centrage fin (zoom ×10 sur ce point) + défilement
  auto du tableau au point le plus récent visible.
- Boucle : après M5, audits courts (perf rAF sur T620 à zoom extrême, mémoisation
  des lignes triées) + 3 nouveaux items backlog par tour, sans jamais dégrader Z1–Z6.