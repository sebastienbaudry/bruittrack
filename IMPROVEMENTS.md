# IMPROVEMENTS — backlog BruitTrack

Chaque item : fichier(s) + critère d'acceptation en une ligne.

- [x] **I1** `bruittrack stats --json` : flag manquant promis par README (matrice M6 « rc=0 + JSON valide »).
      Fichiers : `src/bruittrack/__main__.py`, `tests/test_cli.py`.
      OK quand : `pytest tests/test_cli.py -k json` vert, sortie JSON parseable avec les compteurs events/clusters.
- [x] **I2** CI GitHub Actions : `ruff check . && ruff format --check . && pytest`.
      Fichier : `.github/workflows/ci.yml` (python 3.12/3.13).
      OK quand : le workflow YAML est présent et `bash tools/check.sh` locale reste verte.
- [ ] **I3** `config.toml.example` : documenter `storage.retention_days = 365` (défaut dataclass) avec commentaire.
      Fichier : `config.toml.example`.
      OK quand : `grep -c retention_days config.toml.example` ≥ 1 et `load_config(config.toml.example).validate()` OK.
