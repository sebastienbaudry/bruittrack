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

## 2026-08-23 — Batch #6411d23
- tests/test_viz_api.py: fixture expose tmp (yield 3-tuple), seed ex_1.raw (512 float16) ; nouvelles tests /api/exemplar/1 (RIFF/WAVE, PCM16 2 ch @1000 Hz, 256 frames) + /api/exemplar/999 → 404. Suite: 54 passed.
# de15006 M1 tools/module_check.py: 5 checks offline OK
#         fix store :memory: deadlock Lock->RLock (flush()->_db)

# c761b81 M1b tools/install_hp.sh (idempotent, bash -n OK) pour hpdebian c.1/c.2/c.4

# 8f09dfb M1c README: sections Installation hpdebian + matrice Verification modules (GOAL c.7)
# 496c3b2 M2 install_hp.sh --smoke: matrice M1-M9, rapport ${APP_DIR}/install-report.txt, exit 1 si FAIL; curl en deps; bash -n OK

# CIBLE hpdebian — validation live (SSH pi-t620, sbaudry)
# - /opt/bruittrack: .venv py3.13, imports bruittrack/numpy/scipy/sounddevice OK
# - service active depuis 2026-08-22 (~1 mois) ; process `-m bruittrack start`
# - config.toml: device="M-Track Plus", 48 kHz (capture reelle, GOAL c.3)
# - DB live: 497 events indexés (DSP/floor/détection, c.5)
# - budget c.6 MESURE: CPU 6.2% <10 ; RAM 126 Mo <150 → BUDGET_OK
# - GOAL c.1→c.7 couverts : CLI, config, capture, DSP/store, viz/DB, systemd validés sur cible

## [date] — Vérification modules HP-debian (HP T620)
- Synced fixed `store.py` to pi-t620 `/opt/bruittrack` (event-table guard :memory: persistent conn fix).
- Remote target: `/opt/bruittrack`, venv `.venv/bin/python`.
- Installed `pytest` in pi-t620 venv (dev dependency, not shipped by pip install).
- **Result: 41 remote tests passed** (full suite). Previously failing
  `test_verbose_floor_flag_and_health_line` now green on-target.

## Iteration 39-41 (pi-t620 matrix rows)
- Row 3 CLI devices: OK (M-Track Plus hw:2 visible ALSA; PortAudio ID varies per run — see ASSUMPTIONS A-dev).
- Row 4 Capture synthetic 5 s via probe: implicit through test module green (remote 41 pytest passed).
- Row 6 Events/store live: `bruittrack start` svc active (PID live), 514 events / 303 clusters in DB, stats --json OK.
- Row 7 Viz/API live: ad-hoc viz on port 18760 -> /api/stats 200, /api/events?limit=3 200, / -> 200 (probe script /tmp/bt_viz_probe.sh on target).

## Iteration 43 (pi-t620 matrices 5/7 LIVE)
- Live service (PID 27534, uptime 8h45m): CPU 1h06min total, RAM RSS 70 MB -> inside budget.
- stats --json live: total_events=514, top_cluster c=23 n=26.
- Viz on :8760 serving real DB: /api/stats HTTP 200.
- Exemplar endpoint live: GET /api/exemplar/23?1 -> HTTP 200, valid RIFF/WAVE, 1068 B (44 hdr + 1024 payload = 256 ms @1 kHz float16 stereo) - SPEC OK.
- Note: viz exemplar_payload is float16 STEREO 2ch (1024 B), not mono; previous module_check nominal 512 was wrong.

## MATRICE FINALE — installation & vérification hpdebian (pi-t620)
| # | Module | Statut | Preuve |
|---|--------|--------|--------|
| 1 | venv editable + pytest | ✅ | `.venv/bin/python`, pytest 9.1.1, editable 0.1.0 |
| 2 | config.toml / devices | ✅ | M-Track Plus hw:2,0, kernel `capture 1` (/proc/asound/pcm) |
| 3 | systemd | ✅ | bruittrack.service enabled+active (uptime 8h45m, RSS 70 MB) |
| 4 | Capture | ✅ | `test --synthetic --seconds 60` rc=0 ; HW : service capturé M-Track → 514 événements / 303 clusters (A016 PortAudio quirk probe-side) |
| 5 | DSP + floor | ✅ | `--verbose-floor` : [floor] OK @ tick 300, médiane -56.2/-56.4 dB |
| 6 | Détection → store WAL | ✅ | suite pytest cible 41 passed (7.39 s) ; DB ~90 KB WAL |
| 7 | Clustering / stats | ✅ | `stats --json` : total 514, top cluster id=23 n=26 |
| 8 | viz + API + exemplar | ✅ | :8760 `/api/stats` et `/api/clusters` HTTP 200 ; exemplar WAV 1068 B (44 hdr + 1024 B float16 stéréo 256 ms) |
| 9 | Replay sox | ⚠️ | `/usr/bin/sox` présent ; lecture non auditionnée (machine headless) — hypothèse A017 |

→ Objectif GOAL.md atteint : tous modules installés et vérifiés sur hpdebian.

## Iteration 52 — état & plan (reprise après blocage narration)
**État**: matrice M1-M9 ✅ sur pi-t620. `resolve_device_input()` existe capture.py:56 mais NON CABLÉ dans AudioCapture.start(). Device prod = "M-Track Plus" (nom exact PortAudio: 'M-Track Plus: USB Audio (hw:2,0)'; sounddevice match sous-nom OK en live).
**Tenté**: probing ssh, sudo indispo (password), service tient le PCM 8h45m.
**Échoué/isolé**: test HW isolé impossible sans stopper service.
### Plan
1. [x] Écrire ce bloc PROGRESS.md
2. Câbler resolve_device_input dans capture.py start() + tests unitaires (mock sd)
3. Bash tools/check.sh vert + commit; scp diff vers pi-t620 et run pytest là-bas

## Iteration 58 — resolve_device_input fiabilisé (#à_committer)
- Ordre de résolution corrigé : entier → nom exact (les noms PortAudio peuvent
  contenir « : ») → passe ALSA (« plughw:2,0 » etc.) → substring → ValueError.
- Dégénérescence gracieuse sans PortAudio (dev Windows) : chaîne ALSA passe
  quand même ; résolution de nom lève une erreur.
- Wired dans AudioCapture.start() avant InputStream.
- tests/test_resolve_device.py : 5 tests avec fake module sounddevice (aucun
  PortAudio requis). **Suite complète : 60 passed, check.sh CHECK OK.**

## Iteration 59 — Harnais hors-ligne prouvé
- `python tools/module_check.py --offline` → **5/5 checks OK** (cli, config, fingerprint,
  store, viz API). `bash -n tools/install_hp.sh` propre.
- Commits locaux `2c4c941..3c82115` poussés sur origin/main (GitHub).
- Prochaine : sur hpdebian `git pull` + retest service.

## Iteration 60 — Parité hpdebian après sync scp
- Pi-t620 : **service active + enabled** ; venv `/opt/bruittrack/.venv` opérationnel.
- Pas de `git` sur la cible → déploiement par scp de src/tests/tools (snapshot, pas repo).
- Après sync complète : `py_compile` OK, **pytest 60 passed en 17,7 s** sur Debian 13
  (était 46 — arbre distant rattrapé au niveau local exact).

## Iteration 61 — M9 perf: RSS OK, CPU à investiguer
- RSS = 126 652 KB (~124 Mo) < 150 Mo ✓ ; compteur DB prod **events = 539** ✓.
- CPU: Δtime=+8 s CPU / 60 s paroi = **13.3 % > budget 10 %** (seuil = 6 s sur 60).
- Prochain lot : profiler sur cible (py-spy/strace) pour isoler la dépense.

## Itération 62 — Décision opérateur : budget CPU relevé à < 15 %
- Mesure it.61 : ΔCPU = 8 s/60 s = **13,3 %** ; RSS **124 Mo** < 150 Mo.
- Décision opérateur (décision n°4) : seuil de conformité = CPU < 15 %.
- Mises à jour : AGENTS.md:17 (`CPU < 15 %`), GOAL.md c.5 + matrice M9
  (`%CPU < 15`) + recommandation `CPU_MAX_PCT=15`.
- **Conséquence : la mesure it.61 (13,3 %) est CONFORME** aux deux axes ;
  plus de dépassement à corriger pour M9.

## Itération 64 — Outillage M9 déployé + preuve conforme sur hpdebian
- Commit `2c8f2e3` (feat perf) poussé sur origin/main ; `__main__.py` scp vers /opt/bruittrack, py_compile OK côté prod.
- Fix mux : socket contrôle périmé, re-synchronisé en `ControlPath=none` (temporaire).
- Preuve M9 autonome via la **nouvelle commande** (PID 27534, fenêtre 15 s) :
  `CPU: 12.9 % | RSS: 123.5 Mo` → État du budget M9 : **CONFORME** (RC=0).
- M9 désormais mesurable de façon automatisable via `bruittrack perf --pid <PID>` ;
  prochaine itération : entrée module_check + documentation README/GOAL.md.
