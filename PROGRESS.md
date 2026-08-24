# PROGRESS



## Current state

- I35-I52 done + deploie pi-t620 (health OK, freq_max 150 prod)

- I54 IN PROGRESS : boucle zoom 2 axes (GOAL.md + tools/zoom_check.sh)
  - [x] I58 sync tableau/graphe (92ab8d7) + I58c ancrage zoom exact (9f75210 : tgt tlMode||tlScale ; tlMode prioritaire vs branche vide ; repro 20 ticks |delta|<10 ms ; ruff propre, 106 tests, zoom_check 8/8)

  - [x] M0 gate verte : doublon test_store.py fusionne (+ asserts legacy), ruff OK, 101 tests

  - [x] M1 freqView/axZoom(  [x] M2 fenetrage since  [x] M3 Ctrl+drag/badge/grille  [x] M4 docs  [x] M5 deploy DEPLOY_OK (SCORE 8/8, RC=0)

- I53 open : bouton "Tout" 90 j + horodatage dernier fetch UI



- [2026-08-25] I55 (commis 874d463) — Correction zoom terminée : brush `toTime` employait `canvas.width` (px device HiDPI) au lieu des px CSS → décalé sur écran rétina. Suppression plafond 200 : fetch initial `?limit=20000` + `fetchWindow()` en fin de `refreshAll()` (boutons ET zoom), merge clampé dataSince/dataUntil, watermark `winCursorT` anti-relance. Gate : 104 tests passés, ruff OK, JS node --check OK, zoom_check 7/8 (core oui ; B2 = deploy à refaire sur pi-t620).

- [2026-08-25] I55+ deployé pi-t620 DEPLOY_OK (health ok, DB 1590 lignes > ancien plafond 200 ; markers live ok). zoom_check **SCORE 8/8** incl. B2.
- [2026-08-25] I53 (commis 2418242) — badge « MAJ hh:mm:ss » (`majBadge` + `updateMaj()` en fin de refreshAll réussi). Bouton « Tout » déjà présent. 104 tests passés.

## What was tried / failed

- write tool drops path key under heavy quoting -> use heredoc cat > f <<'EOF' (quote delimiter to avoid expansion) then wc -c + grep marker.

- WinOpenSSH: no VAR=val ssh prefix -> pass values as positional args via bash -s -- value.

- Python one-liner: prefer 2-arg str.replace or scp-ed script file; never cat big files in output.



## Next steps

1. Apply I52 test (tests/test_store.py): old event cluster=7 + new event; create exemplar ex_7.raw before retention; assert apply_retention(30, exemplars_dir) deletes old row AND ex_7.raw, keeps example of live cluster.

2. Run python -m pytest tests/test_store.py -q ; ruff check src/bruittrack ; commit I52 feat + doc.

3. I53: in viz.py HTML add MAJ hh:mm:ss fed by last successful fetch (event timestamp badge near title) and update on each poll; commit; redeploy via scripts/deploy_pi.sh (verify markers incl. new one).

- [2026-08-24] I54 (deploiement) — pi-t620 : freq_max 48.0 -> 150.0 dans /opt/bruittrack/config.toml, restart bruittrack + bruittrack-viz.
- [x] I58(2)/inf sync table-graphe : lastVisible unique (temps+freqView+canaux) dans drawTimeline ; syncEventsToTable() orchestre le tableau ; 106 tests verts ; commit 92ab8d7
