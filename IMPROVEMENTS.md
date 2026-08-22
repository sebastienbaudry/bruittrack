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
