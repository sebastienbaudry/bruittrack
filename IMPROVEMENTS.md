# IMPROVEMENTS

- [x] BUGS.
- [ ] `src/bruittrack/dsp.py` SosFilter.filter(): replace per-sample Python loop with vectorised stride slicing (acceptance: identical output, <50 ms for 48 k samples × 2 ch; add benchmark test in tests/test_dsp.py)
- [ ] `src/bruittrack/viz.py` dashboard HTML: add channel-toggles and hover-tooltip with bin/freq (acceptance: clicking a event marker shows bin_i + lvl_g/dl, JS-only in src/bruittrack/viz.py, no new deps; add Playwright-free check that JSON fields `lvl_g`, `lvl_d` present in /api/events response — extend tests/test_viz_api.py)
- [ ] `src/bruittrack/events.py` ClusterIndex rebuild: rebuild on daemon start should be O(n·k); currently loads all events — cap with `LIMIT 100_000` and log warning when truncated; add test in tests/test_events.py that 200 k synthetic events build in < 8 s
- [ ] `src/bruittrack/capture.py` InputStream: emit per-block read-time (µs) to RingBuffer metadata so pipeline logs slow ALSA blocks > 15 ms (acceptance: engine.step() logs warning >= 3 consecutive slow blocks; add test with MockAudioCapture injecting 20 ms stall)
- [ ] `tests/test_pipeline.py` Engine stop() leaks check: assert store buffer flushed and capture._is_running False after engine.stop(); extend existing test_engine_run_stops cleanly (acceptance: no "buffer had events" on exit)
- [ ] `src/bruittrack/store.py` get_stats(): add `events_last_24h` counter as simple SQL COUNT (acceptance: field present in JSON response, test asserts it > 0 after inserting recent event; update tests/test_store.py and tests/test_bugfixes.py TestRetentionWiring)
- [ ] `docs/decision-log.md`: append entries for BUGS.md fixes 20/05/2026 (acceptance: file exists in repo root or docs/, one sentence per bug fixed, commit hash placeholder OK)
- [ ] `src/bruittrack/__main__.py` cmd_test: add `--verbose-floor` flag that prints floor tracker health each 10 s (acceptance: new argparse flag, test in tests/test_bugfixes.py asserting no exception when flag passed with mock capture)

Last updated: 2026-07-08
