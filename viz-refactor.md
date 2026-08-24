# Plan de refactoring — `src/bruittrack/viz.py`

**Date :** 25 août 2026 · **Cible :** v1.0.0 · **Effort total estimé :** 2–3 sessions de boucle (équivalent I5x)
**Prérequis :** gate verte (`bash tools/check.sh` + pytest 104 ✅ au jour de rédaction).

---

## 1. Constat

`viz.py` = **973 lignes**, dont :

| Bloc | Lignes | Contenu |
|---|---|---|
| Docstring + `create_wav_from_raw` | 1–40 | OK |
| `HTML_DASHBOARD` (string) | 42–832 | ~55 l. CSS, ~110 l. HTML, **~620 l. JavaScript** (fetch/fenêtrage I54-I55, timeline canvas Hi-DPI, brush/zoom 2 axes, tooltips, tables, triage) |
| `BruitTrackHandler` | 835–950 | routage GET/POST à base de `if path ==` |
| `run_viz_server` | 953–973 | OK |

Problèmes :
1. **Aucune séparation Python/JS** : chaque itération viz (I39→I55) édite une string Python ; pas de lint JS ni coloration syntaxique fiable ; risque élevé d'erreurs type I54 (`const fv` redéclaré, commis `bac8dca`).
2. **Routage en cascade d'ifs** dans le handler : difficile à tester route par route.
3. **Contrats fragiles** (voir §3) : `tools/zoom_check.sh` appelle `HTML_DASHBOARD(freq_max=…)` **comme une fonction** alors que c'est une string — le fallback silencieux grep tout `viz.py`, donc le check passe même si le HTML servi change.
4. Dette audit AUDIT2 §3 : pas de plafond `limit`/`Content-Length`, CORS `*` (hors périmètre strict du refactoring, traité en M4 option).

Non-objectifs : aucune dépendance JS externe, aucun build step, aucun framework — contrainte constitution `AGENTS.md` (stdlib + canvas pur). Le rendu servi doit rester **identique octet pour octet** (garantie par test doré, §5).

## 2. Structure cible

```
src/bruittrack/
├── viz.py                    # ~230 l. : serveur, handler, routage table, WAV
└── viz_assets/               # package data (importlib.resources)
    ├── __init__.py           # vide (marqueur package)
    ├── dashboard.html        # squelette HTML (~110 l.), <link>/<script> locaux
    ├── dashboard.css         # styles (~55 l.)
    └── js/
        ├── 01-api.js         # fetchJson, formatDate, refreshAll, fetchWindow, fenêtrage I54/I55
        ├── 02-table.js       # filtres, renderEventsTable, renderClustersTable, triage, sélection
        └── 03-timeline.js    # canvas : drawTimeline, brush, axZoom, panFreqBy, ticks, tooltips
```

Chargement : `importlib.resources.files("bruittrack.viz_assets")` lu **une fois** au démarrage de `run_viz_server` (pas d'I/O par requête). Substitution `__FREQ_MAX__`/`__MIN_EVENT_HZ__` appliquée au HTML uniquement (inchangée), puis concaténation `<style>`/scripts ? **Non** : le HTML référence `static/dashboard.css` + les 3 `.js` servis comme fichiers séparés avec `Cache-Control: max-age=0` (le dashboard est un outil de dev local, rechargé souvent).

Routes ajoutées : `/static/dashboard.css`, `/static/js/01-api.js`, `/static/js/02-table.js`, `/static/js/03-timeline.js` (lecture disque bornée à `viz_assets`, chemin validé contre traversée).

## 3. Contrats à préserver (inventaire exhaustif)

| Contrat | Source | Exigence |
|---|---|---|
| Placeholders substitués côté serveur | `tests/test_viz_api.py:249-259,277` | `let FREQ_MAX = 150;` présent, `__FREQ_MAX__` absent du HTML final |
| Aiguilles JS dans le corps servi | `tests/test_viz_api.py:126-137` | `"bin ${ev.bin_i}"`, `lvl_g.toFixed`, liste de needles |
| Import `from bruittrack.viz import HTML_DASHBOARD` + tokens | `tools/goal_check.sh:19-24` | garder un symbole `HTML_DASHBOARD` importable (rendu complet) |
| Tokens Z1-Z6 (`let freqView`, `axZoom(`, `fetchWindow(`, `since=`, `panFreqBy(`…) | `tools/zoom_check.sh` | idem ; **corriger au passage** l'appel fantaisiste `HTML_DASHBOARD(freq_max=…)` → `render_dashboard(150.0, 2.0)` |
| API JSON inchangée | README | `/api/events\|clusters\|stats\|health\|exemplar`, POST triage |

Décision clé : `HTML_DASHBOARD` devient **une fonction** `render_dashboard(freq_max: float, min_event_hz: float) -> str` ; pour compat `goal_check.sh` on expose aussi le rendu par défaut sous le nom `HTML_DASHBOARD` (string calculée à l'import avec les valeurs de config par défaut). Les deux scripts `tools/*_check.sh` sont mis à jour dans le même lot que le déplacement (M4), jamais avant.

## 4. Jalons (discipline boucle : 1 jalon = 1 commit + gate verte)

### M0 — Filet de sécurité (½ h)
- Test doré : capturer le HTML servi actuel (`render` actuel avec freq_max=150/min_event_hz=2) dans `tests/fixtures/dashboard_golden.html`.
- Nouveau test : le rendu post-refactoring == fixture (normalisation whitespace en tête si besoin).
- `node --check` sur extraction JS ajouté au gate plus tard ; à ce stade juste vérifier `node` disponible.
- **Sortie :** pytest vert incluant le test doré sur le code NON encore déplacé.

### M1 — Extraction CSS (¼ h)
- Créer `viz_assets/`, déplacer le bloc `<style>` vers `dashboard.css`, lier via `<link rel="stylesheet" href="/static/dashboard.css">`.
- Servir `/static/*` depuis `viz_assets` (Content-Type `text/css`).
- Gate : test doré adapté (il ne compare plus le monolithe mais : HTML sans `<style>` inline + CSS servi == bloc extrait). Commit.

### M2 — Extraction JS en 1 fichier (½ h)
- Déplacer tout le `<script>` vers `js/dashboard.js` (un seul fichier, ordre d'exécution identique, aucun comportement touché).
- Route `/static/js/dashboard.js` (Content-Type `text/javascript`).
- `node --check src/bruittrack/viz_assets/js/dashboard.js` ajouté à `tools/check.sh` (nouveau critère ou intégré à C2).
- Gate : test doré + 18 tests viz existants. Commit.

### M3 — Découpage JS en 3 modules (1 h)
- Éclatement en `01-api.js` / `02-table.js` / `03-timeline.js` chargés **dans cet ordre** (pas d'ES modules : variables globales partagées `eventsData`, `tlScale`, `tlMode`… documentées en tête de `01-api.js` comme contrat inter-fichiers).
- Interdits pendant ce jalon : renommage, réindention, changement de logique — couper/coller purs.
- `node --check` sur chacun ; test doré devient : concaténation des 3 fichiers == ancien `dashboard.js` (à saut de ligne près).
- Commit.

### M4 — Serveur : routage en table + symboles de compat (¾ h)
- `ROUTES: dict[str, Callable[[Handler, qs], None]]` remplaçant la cascade d'ifs ; handlers `_get_events`, `_get_clusters`… testables unitairement avec un fake handler (déjà partiellement fait via `run_viz_server(config, store=...)` des tests).
- Exposer `render_dashboard()` + `HTML_DASHBOARD` (compat) ; mettre à jour `tools/goal_check.sh` et `tools/zoom_check.sh` (supprimer le fallback `cat viz.py` qui masque les régressions).
- Optionnel (reportable, issu AUDIT2) : plafond `limit ≤ 50000`, `Content-Length ≤ 64 Ko`.
- Gate complet : pytest + ruff + `zoom_check.sh` SCORE ≥ 7/8 (B2 déploiement exclu). Commit.

### M5 — Packaging + doc (¼ h)
- Vérifier inclusion des assets dans l'instabilité flit : `pip install -e .` puis import depuis un répertoire neutre ; si besoin `[tool.flit.sdist]/[tool.flit.wheel] include`.
- README (section Architecture/Viz), `docs/decision-log.md` (entrée « extraction assets viz »), AGENTS.md si convention nouvelle.
- Commit + déploiement pi-t620 (B2 façon I54/I55) si matériel joignable.

## 5. Stratégie de test

| Niveau | Outil | Ce que ça garantit |
|---|---|---|
| Doré | `dashboard_golden.html` comparé au rendu assemblé | zéro régression fonctionnelle du DOM/JS servi |
| Syntaxe JS | `node --check` ×3 dans `tools/check.sh` | plus jamais d'erreur `const` redéclaré (I54) en gate |
| API | `tests/test_viz_api.py` (13 tests) inchangés | contrats REST intacts |
| Zoom | `tests/test_viz_zoom.py` + `tools/zoom_check.sh` | tokens I54/I55 préservés |

## 6. Risques et mitigations

| Risque | Impact | Mitigation |
|---|---|---|
| Ordre d'exécution JS cassé au découpage | dashboard muet | M3 = couper/coller pur, concat == original testé |
| Assets absents du wheel/déploiement | viz 500 en prod pi-t620 | M5 install test hors repo + smoke curl après deploy |
| `zoom_check.sh` fallback masque une casse | faux vert | suppression du fallback dès M4 |
| Cache navigateur sert vieux JS | confusion debug | `Cache-Control: no-cache` sur `/static/*` |
| Dérive de périmètre (réécriture du JS au passage) | jalon interminable | règle : toute amélioration JS → ticket séparé, pas dans cette boucle |

## 7. Ordre de merge et rollback

Chaque jalon est un commit autonome, gate verte, `git revert`-able individuellement. En cas d'échec M3 (découpage), M2 (JS mono-fichier) est déjà un état livrable satisfaisant — le découpage fin peut être abandonné sans perdre les bénéfices M0-M2.
