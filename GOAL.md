# GOAL — Épuiser le backlog IMPROVEMENTS.md (I30, I35–I41)

Check fin de tour : `bash tools/goal_check.sh` → affiche `SCORE: <n>`,
exit 0 quand les 10 pts core sont atteints.

## Objectif
Traiter dans l'ordre les items non cochés d'IMPROVEMENTS.md sans jamais
dégrader les gates existantes (`bash tools/check.sh`), puis ouvrir la boucle
continue : audits courts + 3 nouveaux items backlog par tour.
Ordre : I35 → I36 → I37 → I38–I41 (dashboard) → I30 (release).

## Périmètre — tokens contractuels (noms EXACTS, vérifiés par goal_check)
| Item | Contrainte |
|------|-------------------------------------------------------------|
| I35  | `DspConfig.min_event_hz: float = 2.0` ; défaut `freq_max` **150.0** (actuel 48.0) ; `ValueError` si `min_event_hz < 1.0` ou `min_event_hz >= freq_max` ; détection bornée bins `[ceil(min_event_hz/df), floor(freq_max/df)]` ; section `[dsp]` commentée dans config.toml.example |
| I36  | Token `min_event_hz` ≥1× dans AGENTS.md, docs/decision-log.md, config.toml.example, README |
| I37  | `scripts/purge_lowfreq.sql` non vide (`DELETE FROM events WHERE freq > 0 AND freq < 2.0;`) + mention README ; SSH hpdebian optionnel (A2) |
| I38  | Boutons `winBtn1h`/`winBtn6h`/`winBtn24h`/`winBtnTout` + fonction `drawTimeTicks(` |
| I39  | `let tlMode = '24h';` (fenêtre = 24 h se terminant au dernier événement, JAMAIS epoch) + fonction `brushZoom(` (drag → recentrage) |
| I40  | Lignes `<tr>` du corps `eventsTableBody` avec `data-evt="${id}"` ; fonction `selectEvent(` ; classe CSS `evt-hl` sur ligne ET point canvas ; `.scrollIntoView({ block: 'center', behavior: 'smooth' })` |
| I41  | `fChannel` (both/in1/in2, labels « Tous / IN1 Air / IN2 Struct »), `fMinLvl` (number min=0), `fCluster` (fetch `/api/clusters`) ; fonction `applyFilters(` (filtrage client) ; BONUS : params API `?chan=&min_lvl=` + test `test_events_api_chan_and_minlvl` |
| I30  | Artefact non vide citant `/releases` (`.github/release.md` ou `scripts/create_release.py`) + git tag local `v1.0.0` ; API GET 200 = bonus B2 |

Non-objectifs : nouvelle dépendance (numpy/scipy/sounddevice + stdlib),
changements de seuils hors I35, écriture dans `data/` du repo
(tests :memory:/tmp_path seulement), refonte pipeline, Windows GUI.

## Roadmap (1 commit par milestone : `feat|fix|docs(chap): (Ix) …`)
- **M1 I35** — [ ]1.1 champ+validation config.py  [ ]1.2 bin_bounds + pipeline  [ ]1.3 exemple toml  [ ]1.4 tests/test_band.py  [ ]1.5 cocher I35
- **M2 I36** — docs (decision-log, README) ; gate : grep 4 fichiers
- **M3 I37** — scripts/purge_lowfreq.sql + README ; si SSH ok appliquer sur /opt/bruittrack/data et PROGRESS.md `[I37] Purge HP appliquée count=0`, sinon `[I37] Artefact local prêt` (A2)
- **M4 I38** — boutons échelles + graduations X horaires (1 commit, gate C4)
- **M5 I39** — fenêtre 24h par défaut + brush zoom (1 commit, gate C5)
- **M6 I40** — liaison scatter ↔ tableau deux sens (1 commit, gate C6)
- **M7 I41** — filtres client (+ bonus B1) ; optionnel params API /api/events?chan&min_lvl + store.get_events + test B1
- **M8 I30** — artefact release v1.0.0 (README/scripts), tag local, PROGRESS.md `[I30] Release publiée` ou `[I30] Artefact prêt` ; B2 si API 200 atteignable
- **M9 boucle continue** — après score=10 : à chaque tour, +3 items IMPROVEMENTS.md (nouveau numérotage), tests ruff/pytest/docs, commits, PROGRESS.md. Ne jamais faire reculer le score.

## Scoring (répliqué dans tools/goal_check.sh)
| Check | Critère mesurable | Pts |
|-------|-------------------|-----|
| C1 I35 | `pytest -q -k "respects_min_event_hz or respects_freq_max"` ≥ 2 passed ET défauts `min_event_hz = 2.0`, `freq_max = 150.0` visibles dans src/bruittrack/config.py | 1 |
| C2 I36 | grep `min_event_hz` matché dans AGENTS.md + docs/decision-log.md + config.toml.example + README.md (4/4 fichiers) | 1 |
| C3 I37 | scripts/purge_lowfreq.sql existe, non vide, contient `DELETE FROM events WHERE freq > 0 AND freq < 2.0` ; mentionné dans README | 1 |
| C4 I38 | HTML_DASHBOARD contient `winBtn1h`,`winBtn6h`,`winBtn24h`,`winBtnTout`,`drawTimeTicks` | 1 |
| C5 I39 | contient `tlMode` ET `brushZoom(` | 1 |
| C6 I40 | contient `selectEvent`, `data-evt=`, `evt-hl`, `scrollIntoView` | 1 |
| C7 I41 | contient `fChannel`, `fMinLvl`, `fCluster`, `applyFilters` | 1 |
| C8 I30 | .github/release.md OU scripts/create_release.py non vide (+ tag local v1.0.0 présent) | 1 |
| B1 | test B1 passe (bonus) | 1 |
| B2 | GET https://api.github.com/repos/sebastienbaudry/bruittrack/releases/ → JSON `tag_name: "v1.0.0"` (bonus, tolère échec réseau → 0) | 1 |

Core = C1..C8 = **8 pts** ; max 10. **Exit 0 ⇔ score ≥ 8.**
Test de référence I35 (M1), nouveaux : `tests/test_band.py` avec `test_detection_respects_min_event_hz` (pic 1 Hz → 0 événement) et `test_detection_respects_freq_max` (pic ~120 Hz détecté si freq_max=150, absent si freq_max=100).

## Barre de qualité
Type hints + docstrings ; tokens CI-dessus EXACTS ; code anglais / messages FR ;
zéro magic number ; `ruff check .` + `ruff format --check .` clean à chaque commit ;
`bash tools/check.sh` verte avant FIN de chaque milestone ; PROGRESS.md : ligne au
début ET à la fin de chaque item, `git add -A && git commit` par item.

## Hypothèses (assumptions)
- A1 Dev = Windows/git-bash, venv présent ; SSH pi-t620 : si timeout → marquer `[I37] artefact local, appliquer en tâche manuelle` (non bloquant pour C3).
- A2 Publication I30 nécessite un token GitHub ; sinon M8 produit l'artefact `.github/release.md` + `scripts/create_release.py`, et PROGRESS.md note `[I30] Artefact release v1.0.0 prét, publication GitHub manuelle (token requis)`.
- A3 `import bruittrack.viz` fonctionne depuis la racine (vérifié) — check UI fait sur module, pas sur serveur vivant.
- A4 Défauts existants : seuil=10.0, debounce=5, hysteresis_db=3.0, freq_max actuel 48.0 → le remplacer par 150.0 par DEFAULT uniquement.

## Commande de vérification (à épingler dans PROGRESS.md)
`bash tools/goal_check.sh` — doit afficher `SCORE: <n>/10` et exit 0 quand ≥ 8.
