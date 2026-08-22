# IMPROVEMENTS

- [x] Fixs BUGS.md batch 1 : BUG-02/10 validation config [:memory:]/`Config.validate()` (#7eb3d88) ; BUG-03 flush atomique (#86166cf) ; BUG-04/07/09 wiring retention+Σw²+défaut 365 (#03c32aa) ; BUG-05 exemplaire WAV int16 (#d498a5f) ; BUG-06/11 signe corrélation + mort `set_initial_state` (#4e36373, #eb34d96) ; BUG-08 Lock `_buffer` + test concurrencé (#1d01e28) ; BUG-12 MockCapture déterministe (#db15b01) ; store cursor/Lock per-op (#dfd2d08)
- [x] SosFilter vectorisé — voie `scipy.signal.sosfilt` (4 biquads), 0,88 ms/tick mesuré T620, test d'équivalence scalaire (#b67eaeb)
- [ ] `src/bruittrack/dsp.py` SosFilter.filter(): replace per-sample Python loop with vectorised stride slicing (acceptance: identical output, <50 ms for 48 k samples × 2 ch; add benchmark test in tests/test_dsp.py)
- [ ] `src/bruittrack/viz.py` dashboard HTML: add channel-toggles and hover-tooltip with bin/freq (acceptance: clicking a event marker shows bin_i + lvl_g/dl, JS-only in src/bruittrack/viz.py, no new deps; add Playwright-free check that JSON fields `lvl_g`, `lvl_d` present in /api/events response — extend tests/test_viz_api.py)
- [ ] `src/bruittrack/events.py` ClusterIndex rebuild: rebuild on daemon start should be O(n·k); currently loads all events — cap with `LIMIT 100_000` and log warning when truncated; add test in tests/test_events.py that 200 k synthetic events build in < 8 s
- [ ] `src/bruittrack/capture.py` InputStream: emit per-block read-time (µs) to RingBuffer metadata so pipeline logs slow ALSA blocks > 15 ms (acceptance: engine.step() logs warning >= 3 consecutive slow blocks; add test with MockAudioCapture injecting 20 ms stall)
- [ ] `tests/test_pipeline.py` Engine stop() leaks check: assert store buffer flushed and capture._is_running False after engine.stop(); extend existing test_engine_run_stops cleanly (acceptance: no "buffer had events" on exit)
- [ ] `src/bruittrack/store.py` get_stats(): add `events_last_24h` counter as simple SQL COUNT (acceptance: field present in JSON response, test asserts it > 0 after inserting recent event; update tests/test_store.py and tests/test_bugfixes.py TestRetentionWiring)
- [x] `docs/decision-log.md` : 13 entrées datées (init v0.1.0, sosfilt, fixes BUG-02..12, FFT delay, FloorTracker transposé, budget persistance) (#9950b7b)
- [ ] `src/bruittrack/__main__.py` cmd_test: add `--verbose-floor` flag that prints floor tracker health each 10 s (acceptance: new argparse flag, test in tests/test_bugfixes.py asserting no exception when flag passed with mock capture)

Last updated: 2026-07-08
