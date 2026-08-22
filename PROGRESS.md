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

## M6 — blocs de capture lents (5020110)
- Telemetrie read-time par bloc (`last_read_us`, seuils nommes SLOW_READ_US=15 ms,
  SLOW_BLOCK_STREAK=3) ; warning `Engine.step()` apres 3 lents consecutifs,
  stall 20 ms injectable MockAudioCapture, 4 tests ; suite 45 pass.

Last updated: 2026-08-22

## M2/M3 — 2026-08-22
- check.sh SCORE 7/7 exit=0 ; docs commit 9950b7b ; IMPROVEMENTS prouvé (#b67eaeb, #9950b7b)

## M4 — events_last_24h
- get_stats() + SQL COUNT 24h, test pass (#817251e) ; suite 40 pass ; IMPROVEMENTS item [x] prouvé

## M5 � cap ClusterIndex prouv� (#6782d8c)

- `load_all_cluster_fingerprints(limit=100_000)` : SQL GROUP BY cluster + LIMIT, warning troncature.
- Test 200 k ev. synth�tiques < 8 s (test_cluster_fingerprints_cap_and_speed pass).
- Suite : 41 passed ; check.sh SCORE 7/7.

## 2026-08-22 — Batch #de15001
- CLI `test --verbose-floor` : ligne [floor] (warmup/OK, médiane dB G/D, ptp) toutes les FLOOR_HEALTH_EVERY_TICKS=100 ticks ; helper format_floor_health() testé + cmd_test synthétique rc=0 (tests/test_bugfixes.py).
- Fix racine : EventStore ":memory:" → 1 connexion persistante (_db()), close() la ferme ; BUG : flush échouait (no such table). Suite : 47 passed.

## 2026-08-22 — Batch 1b8842e / #53cbf67 / #9de8de4
- 1b8842e test(dsp) : benchmark SosFilter 48k échantillons × 2 ch < 50 ms (scipy fast path prouvé par la mesure, suite 48 pass).
- #53cbf67+#9de8de4 viz : tests/test_viz_api.py NOUVEAU (4 tests, ThreadingHTTPServer port éphémère sur store tmp seedé : /api/events expose lvl_g/lvl_d/bin_i/freq — acceptance tooltips ; /api/stats cohérent ; homepage ; dashboard JS).
- src/bruittrack/viz.py : boutons IN1/IN2 basculent canaux du timeline (règle dominance 2 dB) + tooltip clic/hover sur marker = cluster, bin_i, freq, lvl_g/lvl_d — JS seul, zéro dep ; ruff clean.
- Docs : IMPROVEMENTS item 6 [x] (item 5 benchmark prouvé), README phase dashboard interactif. Suite finale : 52 passed.
