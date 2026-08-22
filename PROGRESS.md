# BruitTrack — Progress

## Goal
Corriger toutes les erreurs listées dans BUGS.md.

## Done
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

## Next
- [ ] ruff check . && ruff format --check (à valider sur cible Debian/CI)
- [ ] IMPROVEMENTS.md: items restants (SosFilter vectorisation, viz tooltips,
      ClusterIndex cap, stats events_last_24h, --verbose-floor, decision-log)

## Statut bugs restants
- BUG-01, 05, 12 : voir BUGS.md pour statut détaillé.

Last updated: 2026-07-08
