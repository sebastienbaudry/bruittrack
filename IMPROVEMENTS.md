# IMPROVEMENTS — backlog BruitTrack

Chaque item : fichier(s) + critère d'acceptation en une ligne.

- [x] **I1** `bruittrack stats --json` : flag manquant promis par README (matrice M6 « rc=0 + JSON valide »).
      Fichiers : `src/bruittrack/__main__.py`, `tests/test_cli.py`.
      OK quand : `pytest tests/test_cli.py -k json` vert, sortie JSON parseable avec les compteurs events/clusters.
- [x] **I2** CI GitHub Actions : `ruff check . && ruff format --check . && pytest`.
      Fichier : `.github/workflows/ci.yml` (python 3.12/3.13).
      OK quand : le workflow YAML est présent et `bash tools/check.sh` locale reste verte.
- [x] **I3** `config.toml.example` : documenter `storage.retention_days = 365` (défaut dataclass) avec commentaire.
      Fichier : `config.toml.example`.
      OK quand : `grep -c retention_days config.toml.example` ≥ 1 et `load_config(config.toml.example).validate()` OK.
- [x] **I4** Garantir la commande de v�rification locale `tools/check.sh` (ruff + pytest) cit�e dans I2.
      Fichier : `tools/check.sh`.
      OK quand : `bash tools/check.sh` rc=0 avec 55 tests verts (15/15 � �tendre).

- [x] **I5** Tests unitaires `cmd_perf` (M9) : budget CPU/RSS, PID mort.
      Fichiers : `tests/test_perf.py`, `src/bruittrack/__main__.py`.
      OK quand : `pytest tests/test_perf.py -q` vert (4 tests).
- [x] **I6* Corriger le docstring de `tools/module_check.py` L3 (« rows 1..7 » obsolète → sous-ensemble offline réel).
      Fichiers : `tools/module_check.py`.
      OK quand : `python -c "import ast; ..."` n/a ; grep du docstring cohérent et `check.sh` verte.
- [x] **I7* Entry decision-log : commande `bruittrack perf` + budgets (CPU_MAX_PCT, RSS_MAX_KB) et codes sortie 0/1/2.
      Fichiers : `docs/decision-log.md`.
      OK quand : `grep -ci "cmd_perf\|bruittrack perf" docs/decision-log.md` ≥ 1.
- [x] **I8** Ajouter la ligne M9 (perf sur MainPID, RC attendu 0) à la matrice de smoke en fin d'install.
      Fichiers : `tools/install_hp.sh`.
      OK quand : `grep -c "bruittrack perf" tools/install_hp.sh` ≥ 1 et `bash -n tools/install_hp.sh` sans erreur.

- [x] **I9** Validation de `lp_cutoff_hz` dans la configuration : 0 < lp_cutoff_hz < sample_rate/2 strict (config.py validate + test test_lp_cutoff_hz_must_be_below_nyquist).      Fichiers : `src/bruittrack/config.py`, `tests/test_config.py`.
      OK quand : `Config.validate()` lève un `ValueError` si `lp_cutoff_hz <= 0` ou `>= sample_rate / 2`, et `pytest tests/test_config.py` vert.
- [x] **I10** Cast numérique explicite du filtre 24h dans `EventStore.get_stats()` : cut-off calculé en Python (`time.time() - 86_400.0`) et passé en paramètre, comparaison `REAL t0 >= ?` plutôt que `strftime` string (test `tests/test_store.py::test_get_stats_events_last_24h`).      Fichiers : `src/bruittrack/store.py`, `tests/test_store.py`.
      OK quand : `get_stats()` utilise `CAST(strftime('%s', 'now', '-1 day') AS REAL)` et `pytest tests/test_store.py` vert.
- [x] **I11** Nettoyage des extraits audio exemplaires orphelins (`prune_orphaned_exemplars`).
      Fichiers : `src/bruittrack/store.py`, `tests/test_store.py`.
      OK quand : une méthode `prune_orphaned_exemplars()` supprime les fichiers `ex_<id>.raw` orphelins dans `exemplars_dir` et `pytest tests/test_store.py` vert.
- [x] **I12** Avertissement au démarrage si fallback SOS pure-Python actif (`scipy` absent).
      Fichiers : `src/bruittrack/dsp.py`, `src/bruittrack/pipeline.py`, `tests/test_dsp.py`.
      OK quand : un warning de log est émis à l'initialisation si `scipy.signal.sosfilt` est indisponible et `pytest tests/test_dsp.py` vert.
- [x] **I13** Test HTTP du triage : POST /api/clusters/1/triage (flags+label) persisté dans la table clusters ; réponse JSON success=true.
      Fichiers : `tests/test_viz_api.py`, `src/bruittrack/viz.py` (pas de modif attendue — brique existante).
      OK quand : `pytest tests/test_viz_api.py -k triage -q` vert (1+ test) et `bash tools/check.sh` verte.
- [x] **I14** Documenter le triage par API HTTP (exemple curl `/api/clusters/1/triage`) dans la section Commandes du README.
      Fichier : `README.md`.
      OK quand : `grep -c triage README.md >= 1` et l'exemple JSON correspond au handler `do_POST` (keys flags/label).
- [x] **I15** Test store : `set_cluster_triage()` sur un cluster inexistant crée la ligne (id, label, flags) sans erreur.
      Fichier : `tests/test_store.py`.
      OK quand : `pytest tests/test_store.py -k fresh -q` vert (1 test) et les 68+ tests globaux restent verts.
- [x] **I16** Coverage du triage POST dans `tools/module_check.py --offline` : sonde HTTP `POST /api/clusters/0/triage` (flags=1, label="preflight") + verification SQLite de la ligne creee ; resultat 5/5 OK.
      Fichier : `tools/module_check.py`.
      OK quand : `python tools/module_check.py --offline` affiche `triage=True`.
- [x] **I17** `/api/clusters` : un cluster triage cree avant le 1er event (ligne orpheline dans `clusters`) etait invisible ; `get_clusters_summary` merge maintenant les lignes sans event (event_count=0, stats NULL) + test regresion.
      Fichiers : `src/bruittrack/store.py`, `tests/test_store.py`.
      OK quand : `pytest tests/test_store.py -k orphans` passe et `python tools/module_check.py --offline` reste 5/5.

- [x] **I18** CI : passer `actions/setup-python@v5` → `@v6` (Node 24 natif) pour supprimer définitivement le warning deprecation Node.js 20 checkout/setup.
      Fichier : `.github/workflows/ci.yml`.
      OK quand : `grep -c "setup-python@v6" .github/workflows/ci.yml` = 1 et le YAML reste valide.
- [x] **I19** UI web : `triageCluster()` envoie seulement `flags` — ajouter un label (prompt) au triage dans le dashboard, corps JSON `{flags, label}`.
      Fichier : `src/bruittrack/viz.py` (bloc JS ~ligne 278).
      OK quand : le body du fetch triage contient `label` et le README section Triage reste cohérement.
- [x] **I20** Test HTTP I17 : `GET /api/clusters` inclut un cluster orphelin (event_count=0) via viz_server + set_cluster_triage avant lecture.
      Fichier : `tests/test_viz_api.py`.
      OK quand : `pytest tests/test_viz_api.py -k orphan -q` vert.

- [x] **I21** `EventStore.get_events()` (src/bruittrack/store.py:296) : aucun test des filtres `since`/`offset`/`cluster`. Ajouter `test_get_events_filters_and_pagination` dans tests/test_store.py (3 events t0 consécutifs ; since=mi → sous-ensemble exact ; limit+offset + desc ; cluster=5 isole un event).
      OK quand : `pytest tests/test_store.py -k filters_and_pagination -q` vert.
- [x] **I22** (déjà implémenté : apply_retention store.py + wiring pipeline.py)  `retention_days` (config.py:54) validé mais jamais consommé. Ajouter `EventStore.purge_old(now)` (src/bruittrack/store.py) supprimant events avec t0 < now − N jours (+ exemplaires orphelins), appelé au démarrage (src/bruittrack/__main__.py, cmd_start) + test tests/test_store.py.
      OK quand : `pytest -k retention -q` vert et purge visible dans `bash tools/check.sh`.
- [x] **I23** Smoke CLI : tests/test_bugfixes.py — subprocess `python -m bruittrack <cmd> --help` (devices|test|start|viz|stats) s' exécute en 0, garantissant l'appontage argparse.
      OK quand : `pytest -k cli_help -q` vert.
## Poursuite

- [x] **I24** Test HTTP : exemplaire .raw corrompu -> GET /api/exemplars/<c> renvoie 500 (test_exemplar_corrupt_returns_500).
      Fichier : tests/test_viz_api.py. OK quand : pytest -k corrupt vert.
- [x] **I25** CI matrix 3.12/3.13 mais pyproject.toml declare requires-python >=3.11 : ajouter un job 3.11 (planchier declaree) dans .github/workflows/ci.yml.
      Fichier : .github/workflows/ci.yml. OK quand : le matrix porte 3 versions et le YAML reste valide.
- [x] **I26** viz.py : valider les params GET /api/events (since=abc, limit<=0, offset<0 -> HTTP 400 au lieu d'errno/traceback) + tests test_viz_api.py.
      Fichier : src/bruittrack/viz.py. OK quand : des requests de test avec since=abc et limit=0 recoivent 400, gate verte.
- [x] **I27** config.py : retenir les erreurs de validation (retention_days >= 0, seuils > 0) - levees au chargement avec un message lisible + tests test_config.py.
      Fichier : src/bruittrack/config.py. OK quand : pytest -k config vert et une config invalide echoue proprement en CLI.


## Release

- [x] **I28** Version stable : tag/v1.0.0 + déploiement sur le HP T620 (systemd/bruittrack.service), puis purge DB serveur des événements non significatifs (freq=0.0 pré-fix 80dbfe9, événements <<seuil noise>). Fichier : scripts/purge_noise.sql (nouveau) + README. OK quand : la purge est scriptable en une commande déclarée dans le README, après un état de CI vert et gates locales passer.

## Post-v1.0.0
- [x] **I29** test_pipeline.py : seule 2 tests Engine — ajouter simulation synthetique de pic > seuil (floor + 12 dB) produisant >=1 event via Engine.step + flush store tmp_path. OK quand : pytest vert, nouveau test test_engine_synthetic_spike_fires.
- [ ] **I30** .github/release.md ou script/creer_release.py : publier la release GitHub v1.0.0 (POST /repos/{o}/{r}/releases via token) ; descriptif = notes ci-jointes CI 3.11-3.13, budget HP T620, commande purge. OK quand : `gh release view v1.0.0` (ou GET API) reponse 200.
- [x] **I31** src/bruittrack/viz.py do_GET : verifier les routes existantes + ajouter /api/health (200 JSON {ok: true, events_db_rows}) avec test test_health_returns_200 dans tests/test_viz_api.py. OK quand : pytest vert.
## Post-v1.0.0 — Ops HP T620 & contrainte bande

- [x] **I32** Audit hpdebian : tous les modules en 1.0.0 (`src/bruittrack/__init__.py`, `pyproject.toml`, métadonnées pip), service `systemctl restart` effectués (réponse active), purge DB des lignes `freq=0.0` → 0 ligne restante et 1263 événements conservés.
      Fichiers : PROGRESS.md (log), SSH pi-t620. OK quand : vérifié par SSH le 2026-08-23 (PID 38648, `SELECT count(*) … WHERE freq=0` = 0).
- [x] **I33** Robustesse normalisation CRLF→LF de `tools/install_hp.sh` : détection par `od -An -c | grep '\r'` (portable MSYS/GNU ; le `grep $'\r'` seul est faux négatif sous MSYS), bloc `if/fi` (pas de `&&` sous errexit), layout plat `/opt/bruittrack`.
      Fichier : tools/install_hp.sh. OK quand : `bash -n tools/install_hp.sh` rc=0, zéro CR (`grep -c` od = 0), find prune `.git/.venv/data/example` intact.
- [x] **I34** Outiling ops : `tools/parity_hp.sh` (sha256 local vs /opt/bruittrack engagé), `.pi-loop-log.jsonl` dé-tracké de l'index git.
      Fichiers : tools/parity_hp.sh, .gitignore. OK quand : commit 10da285 vert et `git status` propre sur ce log.
- [x] **I35** Contraintes bande **utilisateurs paramétrables** : `freq_max = 150.0` (Hz analysés au maximum) et `min_event_hz = 2.0` (aucun événement en dessous — matériel non fiable sous 2 Hz), ajoutées à `DspConfig` avec validation, pas de magic number, propagées dans le pipeline d'émergence/Détection.
      Fichiers : src/bruittrack/config.py, src/bruittrack/dsp.py (borne des émergences bin < min_event_hz ; Welch/bins jusqu'à freq_max), src/bruittrack/pipeline.py, config.toml.example, tests/test_config.py + tests/test_dsp.py.
      OK quand : `pytest -q` vert avec tests synthétiques « 1 Hz jamais détecté » / « pic ~120 Hz détecté avec freq_max=150 » et validation ValueError si values incohérentes (min_event_hz < 1 ou ≥ freq_max).
- [x] **I36** Mettre à jour fichiers de référence pour les 2 nouvelles contraintes : section Pipeline + Schéma DB d'AGENTS.md (bins utiles, bornes min/max avec note config), entrée `docs/decision-log.md` documentant l'origine matériel des bornes et leur paramétrabilité.
      Fichiers : AGENTS.md, docs/decision-log.md, README.md (section Configuration).
      OK quand : `grep -c "min_event_hz\|freq_max" AGENTS.md docs/decision-log.md config.toml.example` retourne ≥1 occurrences dans les 3 fichiers et le texte décrit la raison matériel (« non fiable sous 2 Hz ») + portée configurable.
- [x] **I37** Purge hpdebian des événements `0 < freq < min_event_hz` (conséquence I35, même règle que purge 0 Hz I32 mais étendue) + note dans le README de la commande de purge.
      Cible : SSH pi-t620 SQL ; Fichier : README.md. OK quand : `SELECT count(*) FROM events WHERE freq < 2.0` = 0 sur /opt/bruittrack et la commande SQL est réutilisable via scripts/purge_lowfreq.sql à la suite.
- [x] **I38** UI Timeline « Fréquence / Temps » : graduations visibles sur l'axe X (repères HH:MM clairs, ex. 19:00/19:30/20:00) + sélecteur d'échelle ajustable (Boutons 1h / 6h / 24h / Tout).
      Fichiers : src/bruittrack/viz.py (HTML/canvas de la timeline ; le JSON des events porte déjà t0), README.md (section dashboard).
      OK quand : le HTML servi contient les 4 boutons d'échelle et des labels HH:MM calculés côté client sur l'axe, et `bash tools/check.sh` verte.
- [x] **I39** UI Timeline : supprimer le tassement des points à droite — fenêtre temporelle glissante dynamique (affichage centré sur les N dernières heures d'événements, pas depuis epoch) + option zoom type brushing (sélection d'une plage qui zoom l'axe).
      Fichiers : src/bruittrack/viz.py ; acceptation testée via `tools/module_check.py`/pytest endpoint si lisible.
      OK quand : un flux avec événements récents montre les points étalés sur la largeur et une sélection de plage recentre l'échelle (vérifiable par curl du HTML + comportement client documenté dans README).
- [x] **I40** Lien bidirectionnel scatter ↔ tableau : clic sur un point du Frequency/Time chart → surbrillance de la ligne correspondante dans « Derniers Événements » (et clic sur une ligne → surbrillance du point) ; scroll automatique à la ligne.
      Fichier : src/bruittrack/viz.py (mapping id d'événement ↔ élément DOM, classes CSS actives).
      OK quand : les deux directions de highlight existent dans le HTML servi et testent le wiring (`pytest -k crosshair -q` ajouté ou `module_check.py` vérifie la présence du handler + de l'attr id par évènement).
- [ ] **I41** Filtres rapides au-dessus du tableau « Derniers Événements » : par canal (IN1 Air / IN2 Structural / Tous), par émergence minimale (sliders/sélecteur, ex. >+10 dB), par cluster (list déroulante alimentée par /api/clusters).
      Fichiers : src/bruittrack/viz.py (+ option: GET /api/events?chan=&min_lvl=&cluster= si backend) ; tests/test_viz_api.py si endpoint ajouté.
      OK quand : les 3 filtres sont rendus au-dessus du tableau, appliquent le filtre côté client par défaut et la commande curl documentée renvoie la liste filtrée ; `bash tools/check.sh` verte.
