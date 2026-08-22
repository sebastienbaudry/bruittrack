# IMPROVEMENTS

- [x] Fixs BUGS.md batch 1 : BUG-02/10 validation config [:memory:]/`Config.validate()` (#7eb3d88) ; BUG-03 flush atomique (#86166cf) ; BUG-04/07/09 wiring retention+Σw²+défaut 365 (#03c32aa) ; BUG-05 exemplaire WAV int16 (#d498a5f) ; BUG-06/11 signe corrélation + mort `set_initial_state` (#4e36373, #eb34d96) ; BUG-08 Lock `_buffer` + test concurrencé (#1d01e28) ; BUG-12 MockCapture déterministe (#db15b01) ; store cursor/Lock per-op (#dfd2d08)
- [x] SosFilter vectorisé — voie `scipy.signal.sosfilt` (4 biquads), 0,88 ms/tick mesuré T620, test d'équivalence scalaire (#b67eaeb)
- [x] ``src/bruittrack/dsp.py` SosFilter.filter(): replace per-sample Python loop with vectorised stride slicing` — fast path scipy.signal.sosfilt déjà vectorisée (fichier d'origine : boucle 6 480 it/s remplacée) ; preuve par tests/test_dsp.py::test_sos_filter_fastpath_matches_scalar + benchmark 48k×2ch < 50 ms (#1b8842e)
- [x] `src/bruittrack/viz.py` dashboard HTML: add channel-toggles and hover-tooltip with bin/freq ; tests/test_viz_api.py (4 tests port ephémère: champs lvl_g/lvl_d, stats, dashboard, toggles+tooltip) ; src/bruittrack/viz.py
- [x] `src/bruittrack/events.py` ClusterIndex rebuild: cap `load_all_cluster_fingerprints(limit=100_000)` via SQL GROUP BY + LIMIT, warning troncature ; test 200 k ev. reconstruits < 8 s � tests/test_store.py::test_cluster_fingerprints_cap_and_speed pass (#6782d8c)
- [x] `src/bruittrack/capture.py` InputStream: emit per-block read-time (µs) to RingBuffer metadata so pipeline logs slow ALSA blocks > 15 ms — `last_read_us` + `consecutive_slow` par bloc, warning `Engine.step()` après 3 lents consécutifs ; stall 20 ms MockAudioCapture testé (#5020110)
- [x] `tests/test_pipeline.py` Engine stop() leaks check: assert store buffer flushed and capture._is_running False after engine.stop() — test_engine_stop_flushes_store_and_stops_capture (#03cf9f7)
- [x] `src/bruittrack/store.py` get_stats(): add `events_last_24h` counter — SQL CASE strftime('%s','now','-1 day'), test test_get_stats_events_last_24h pass (#817251e)
- [x] `docs/decision-log.md` : 13 entrées datées (init v0.1.0, sosfilt, fixes BUG-02..12, FFT delay, FloorTracker transposé, budget persistance) (#9950b7b)
- [x] `src/bruittrack/__main__.py` cmd_test: add `--verbose-floor` flag that prints floor tracker health each 10 s — constant FLOOR_HEALTH_EVERY_TICKS=100, format_floor_health() unit-testé (#de15001)
  - fix lié : EventStore(:memory:) utilisait une connexion éphémère par opération → schéma absent au flush ; connexion persistante + lock (#de15001)

Last updated: #de15001 (--verbose-floor + fix store :memory:)
