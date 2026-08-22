# BruitTrack — Progress

## Goal
Corriger toutes les erreurs listées dans BUGS.md.

## Done
- Perfs DSP v2 (pi-t620, `tools/bench_ticks.py`) : process_block ≈ 4,4 ms,
  cross-corr FFT 1024 < 0,1 ms/tick (was 5,24 ms), floor partition axis=1
  0,58 ms → boucle totale ≈ 5,4 ms/100 ms ≈ 5,4 % CPU (< 10 % budget) —
  mesuré sur pi-t620 le 2026-07-08.
- FloorTracker : stock transposé (bins×temps) → partition par ligne (b67eaeb).
- compute_channel_delay_ms : cross-corrélation rfft/irfft f32 Nfft=1024, signe
  préservé (LEFT leads => ms > 0) (b3e7627).
- store.py: cursor() par opération, _init_db unique, Lock sur buffer → 26 tests OK (dfd2d08)
- BUG-11: set_initial_state supprimée + tests de signe compute_channel_delay_ms (4e36373)
- Notes statut BUGS.md (eb34d96), test concurrent writer/readers (1d01e28)
- BUG-02: `cmd_test` injecte `EventStore(db_path=":memory:")` → commit e8d591f
- BUG-03: flush() atomic (backup buffer sur échec) — voir store.py + tests
- BUG-04: apply_retention appelée au démarrage
- BUG-06: signe off_ms corrigé + tests
- BUG-07: normalisation Welch Σw² corrigée + test
- BUG-08: Lock sur EventStore._buffer + test concurrencé
- BUG-09: défaut retention_days 365 conservé (None = désactivé explicite)
- BUG-10: `Config.validate()` complète (block_size%dec, sample_rate%dec,
  freq_max ≤ Nyquist décimé, debounce_ticks ≥ 1, max_duration_s > 0)
  + tests TestConfigValidation → marquée ✅ dans BUGS.md

## Divergences documentées (M0 — 2026-07-09)
- README : "LP Butter (numpy)" → corrigé scipy ; budget 15 % →
  < 10 % CPU par AGENTS.md.
- IMPROVEMENTS : item SosFilter déjà vectorisé en pratique (sosfilt scipy,
  0,88 ms/tick mesuré) → à recaler au prochain passage.

## Next
- [ ] ruff check . && ruff format --check (à valider sur cible Debian/CI)
- [ ] IMPROVEMENTS.md: items restants (SosFilter vectorisation, viz tooltips,
      ClusterIndex cap, stats events_last_24h, --verbose-floor, decision-log)

## Statut bugs restants
- BUG-01, 05, 12 : voir BUGS.md pour statut détaillé.

Last updated: 2026-07-08

## M2/M3 — 2026-08-22
- check.sh SCORE 7/7 exit=0 ; docs commit 9950b7b ; IMPROVEMENTS prouvé (#b67eaeb, #9950b7b)

## M4 — events_last_24h
- get_stats() + SQL COUNT 24h, test pass (#817251e) ; suite 40 pass ; IMPROVEMENTS item [x] prouvé

## M5 � cap ClusterIndex prouv� (#6782d8c)

- `load_all_cluster_fingerprints(limit=100_000)` : SQL GROUP BY cluster + LIMIT, warning troncature.
- Test 200 k ev. synth�tiques < 8 s (test_cluster_fingerprints_cap_and_speed pass).
- Suite : 41 passed ; check.sh SCORE 7/7.
