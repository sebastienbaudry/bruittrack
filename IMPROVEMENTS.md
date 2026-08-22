# IMPROVEMENTS â€” backlog BruitTrack

Chaque item : fichier(s) + critÃ¨re d'acceptation en une ligne.

- [x] **I1** `bruittrack stats --json` : flag manquant promis par README (matrice M6 Â« rc=0 + JSON valide Â»).
      Fichiers : `src/bruittrack/__main__.py`, `tests/test_cli.py`.
      OK quand : `pytest tests/test_cli.py -k json` vert, sortie JSON parseable avec les compteurs events/clusters.
- [x] **I2** CI GitHub Actions : `ruff check . && ruff format --check . && pytest`.
      Fichier : `.github/workflows/ci.yml` (python 3.12/3.13).
      OK quand : le workflow YAML est prÃ©sent et `bash tools/check.sh` locale reste verte.
- [x] **I3** `config.toml.example` : documenter `storage.retention_days = 365` (dÃ©faut dataclass) avec commentaire.
      Fichier : `config.toml.example`.
      OK quand : `grep -c retention_days config.toml.example` â‰¥ 1 et `load_config(config.toml.example).validate()` OK.
- [x] **I4** Garantir la commande de vérification locale `tools/check.sh` (ruff + pytest) citée dans I2.
      Fichier : `tools/check.sh`.
      OK quand : `bash tools/check.sh` rc=0 avec 55 tests verts (15/15 à étendre).
