# PROGRESS



## Current state

- I35-I52 done + deploie pi-t620 (health OK, freq_max 150 prod)

- I54 IN PROGRESS : boucle zoom 2 axes (GOAL.md + tools/zoom_check.sh)

  - [x] M0 gate verte : doublon test_store.py fusionne (+ asserts legacy), ruff OK, 101 tests

  - [x] M1 freqView/axZoom(  [x] M2 fenetrage since  [x] M3 Ctrl+drag/badge/grille  [x] M4 docs  [x] M5 deploy DEPLOY_OK (SCORE 8/8, RC=0)

- I53 open : bouton "Tout" 90 j + horodatage dernier fetch UI



## What was tried / failed

- write tool drops path key under heavy quoting -> use heredoc cat > f <<'EOF' (quote delimiter to avoid expansion) then wc -c + grep marker.

- WinOpenSSH: no VAR=val ssh prefix -> pass values as positional args via bash -s -- value.

- Python one-liner: prefer 2-arg str.replace or scp-ed script file; never cat big files in output.



## Next steps

1. Apply I52 test (tests/test_store.py): old event cluster=7 + new event; create exemplar ex_7.raw before retention; assert apply_retention(30, exemplars_dir) deletes old row AND ex_7.raw, keeps example of live cluster.

2. Run python -m pytest tests/test_store.py -q ; ruff check src/bruittrack ; commit I52 feat + doc.

3. I53: in viz.py HTML add MAJ hh:mm:ss fed by last successful fetch (event timestamp badge near title) and update on each poll; commit; redeploy via scripts/deploy_pi.sh (verify markers incl. new one).

- [2026-08-24] I54 (deploiement) — pi-t620 : freq_max 48.0 -> 150.0 dans /opt/bruittrack/config.toml, restart bruittrack + bruittrack-viz.