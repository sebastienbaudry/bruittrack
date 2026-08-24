# PROGRESS

## Current state
- I35-I51 closed + deployed pi-t620 (wheel bruteinstall, services active, health OK, 1385 rows).
- I52 IN PROGRESS: apply_retention(retention_days, exemplars_dir=None) wired in store.py + pipeline.py call sites L96/L149; test planned.
- I53 open: UI timestamp refresh (last-fetch visible in header/badge).

## What was tried / failed
- write tool drops path key under heavy quoting -> use heredoc cat > f <<'EOF' (quote delimiter to avoid expansion) then wc -c + grep marker.
- WinOpenSSH: no VAR=val ssh prefix -> pass values as positional args via bash -s -- value.
- Python one-liner: prefer 2-arg str.replace or scp-ed script file; never cat big files in output.

## Next steps
1. Apply I52 test (tests/test_store.py): old event cluster=7 + new event; create exemplar ex_7.raw before retention; assert apply_retention(30, exemplars_dir) deletes old row AND ex_7.raw, keeps example of live cluster.
2. Run python -m pytest tests/test_store.py -q ; ruff check src/bruittrack ; commit I52 feat + doc.
3. I53: in viz.py HTML add MAJ hh:mm:ss fed by last successful fetch (event timestamp badge near title) and update on each poll; commit; redeploy via scripts/deploy_pi.sh (verify markers incl. new one).
- [2026-08-24] I54 (deploiement) — pi-t620 : freq_max 48.0 -> 150.0 dans /opt/bruittrack/config.toml, restart bruittrack + bruittrack-viz.
