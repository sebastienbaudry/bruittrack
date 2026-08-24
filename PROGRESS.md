# PROGRESS — BruitTrack

## But
Tolerance de frequence de clustering parametrable (`cluster_freq_tolerance_hz`,
defaut 0.5 Hz) pour remplacer le seuil dure "±2 bins" de `fingerprints_match`.
Propagation: config.toml → DetectorConfig → EventDetector (Hz→bins) → ClusterIndex.

## Fait avant pause (sur disque)
- FIX I43 VIZ DEJA DEPLOYE SUR PI: `continue`→`return` dans drawTimeline, commit 35ae96e,
  wheel installee, services actives, page servie verifiee.
- `src/bruittrack/config.py` — EN PLACE (verifie grep) :
      - L49: champ `cluster_freq_tolerance_hz: float = 0.5` dans DetectorConfig
      - L117-121: validation (> 0)
      - L201-203: lecture TOML `[detector]` avec defaut 0.5
      - NB: verifier que le champ porte bien le nom exact attendU (grep a montre `cluster_max_bin_delta` sur une ligne — a confirmer).
- `src/bruittrack/events.py` — `fingerprints_match(fp1, fp2, max_bin_delta: int = 1)`
  (L130-169): signature + docstring OK, check `> max_bin_delta` ligne 152.

## ETAT A REPARER EN PREMIER (au reprise)
1. `events.py` L154-156: SUPPRIMER le bloc residuel duplique :
       # Bin peak distance
       if abs(d1.bin_peak - d2.bin_peak) > 2:
           return False
   (reste de l'ancienne impl ; re-impose silencieusement ±2 bins → toute tolerance
   > 1 bin serait faussement re-restreinte). Ensuite normaliser EOL :
       sed -i 's/\r$//' src/bruittrack/events.py
   (fichier partiellement CRLF), puis:
       venv\Scripts\python.exe -m py_compile src/bruittrack/events.py
       python -m pytest tests/test_events.py -x -q
   NB: pas de python3 dans le PATH Windows — toujours la venv du projet.
2. `events.py` — POURSUIVRE l'impl :
      - `ClusterIndex.__init__(max_bin_delta: int = 1)` ; `match_or_create` appelle
        `fingerprints_match(fp, ref_fp, self.max_bin_delta)` (~L180-200).
      - `EventDetector.__init__`: nouveau param `cluster_freq_tolerance_hz: float`,
        convertir: `self.cluster_max_bin_delta = max(0, round(tol / bin_resolution_hz))`,
        le passer a `ClusterIndex(...)`. Defaut 0.5 Hz / 0.48828125 Hz/bin ≈ 1 bin.
3. `pipeline.py`: passer `cluster_freq_tolerance_hz=config.detector.cluster_freq_tolerance_hz`
   a la construction de l'`EventDetector` (~L142-152).
4. Tests :
      - `tests/test_events.py` L40-55 (`test_fingerprints_match`): les appels existants
        `fingerprints_match(fp1, fp2)` restent valides (defaut de param).
      - NOUVEAUX tests: tol 1.47 Hz (~3 bins) → Δ=3 ok, Δ=4 refu ;
        tol 0.5 Hz → Δ=1 ok, Δ=2 refu.
      - Test config: parse + validation (`tests/test_config.py` s'il existe).
5. `config.toml.example`: ajouter `cluster_freq_tolerance_hz = 0.5` sous [detector]
   (zero magic number ; LIRE le fichier avant ecrire, see skill file-write-guard).
   Ne PAS toucher `/opt/bruittrack/config.toml` sur Pi sans decision operateU.
6. `docs/decision-log.md`: entry I44 — nouvelle cle de config + note effet retou:
   clusters existants non re-fusionnes (seul le matching des NOUVEAUX evenements
   suit la tolerance configuree).

## DB / PI — STATUT A VERIFIER au reprise
Via `ssh pi-t620` (mots de passe passLinux1!) : vérifier:
      sqlite3 /opt/bruittrack/data/bruittrack.db "SELECT COUNT(*), MIN(freq) FROM events"
- Supp. lignes freq ≤ 2.0 Hz: IDENTIFIEE (520 lines sur 903 a la mesure, min 0.49 Hz)
  mais EXECUTION NON CONFIRMEE sur la cible.
- Si non faite: `DELETE WHERE freq <= 2.0` + purge clusters orphelins + VACUUM
  (WAL → faisable service en course).

## Deploiement final (apres tests verts + ruff)
- Wheel `pip wheel` nom canonique PEP427 (5 parties): `bruittrack-X-py3-none-any.whl`
  → scp pi-t620:/tmp/ → install force dans /opt/bruittrack/.venv →
  `systemctl restart` de bruittrack-start ET bruittrack-viz (memes wheel !)
  → verifier curl /api/health + grep la page servie.
- Piste: scripts Python pour SSH = fichier .py uploade, JAMAIS en inline
  avec guillemets imbroiques (fragilite Git Bash).

## ORDRE DE REPRISE
1. Reparer events.py (point 1) + tests de base verts.
2. Finir impl (points 2-3), tests (point 4), config.example, decision-log (5-6).
3. `ruff check . && ruff format .`, pytest complet.
4. Build wheel → deploy Pi → verifs (API + page + stats DB).

Commit par etape: `git add -A && git commit -m "..."`.

## I44 — TERMINE (local, $(date +%Y-%m-%d)), deployment en cours
- events.py reparate + CRLF normalise ; ClusterIndex(max_bin_delta) + EventDetector(
  cluster_freq_tolerance_hz) + pipeline propagation ; ruff check/format OK ; 98 tests verts.
- commit 04017c6 I44 + chore format test_viz_api.py.
- Wheel dist/bruittrack-1.0.0-py3-none-any.whl (pep427 OK).
- Pi DB : 0 ligne freq <= 2 Hz pending (cleanup deja fait), total 952 events.

## I44 — DEPLOYE sur pi-t620 $(date +%Y-%m-%d %H:%M)
- Wheel dist/bruittrack-1.0.0-py3-none-any.whl : scp (nom date +%s pour eviter "Received 0 bytes") +
  pip force-reinstall --no-deps dans /opt/bruittrack/.venv. max_bin_delta confirme en remote.
- config.toml pi : cle cluster_freq_tolerance_hz = 0.5 ajoutee sous [detector] (idempotent grep).
- UNITS REELS : bruittrack.service (pipeline) + bruittrack-viz.service. "bruittrack-start" N EXISTE PAS
  (erreur de nommage script deploy). Restart via echo passLinux1! | sudo -S systemctl restart.
- VIS : port **8760** (pas 8080 — probe initiale fausse alarme).
- Verifs APRES deploy : bruittrack active (nouveau PID), viz active, /api/health ok (956 lignes),
  GET / HTTP 200, 0 lignes error/traceback dans le journal.
- TODO eventuel : `bruittrack perf` apres quelques heures de stabilite (confirmation CPU post-reboot
  I31 ; baseline I43 : 12.1% CPU / 87.8 Mo OK). Pas de cleanup DB a faire : 0 ligne freq <= 2.0 Hz.

## Re-clustering one-shot (scripts/recluster.py) — dry-run synthetique OK
- Regle : rejoue les N events persistes par id croissant (ordre live) avec ClusterIndex(max_bin_delta) vierge ;
  max_bin_delta derive du config target comme au live (tol = 0.5 Hz -> 1 bin)
- Rewrite events.cluster en 1..N canonique + reattribuexemplaires (flags bit2) + migration fichiers ex_*
- Dry-run locale base synthetique : A(50),A,B(51),C(class -3) -> {1:A,A,B}+{2:C} ; exemplaires migres proprement
- A appliquer sur pi-t620 (956 events) apres confirmation operateur

## [RECLUSTER APPLIQUE SUR PI] 2026-07-14 ~09:40
- Sauvegarde : /tmp/bruittrack.db.backup-recluster (pi-t620)
- Resultat : 562 -> 623 clusters (regles d'entrainement) ; 980 lignes reassignees ; 539 exemplaires migres
- Coherence : 539 flags exemplaire =\u003c=> 539 fichiers ex_*.raw ; sans file orpheline / tmp residue
- Services redemarres (bruittrack.service PID recent, viz port 8760) ; /api/health ok ; API /events correct
- Note : events continues d'entrer en live avec les nouveaux numéros de cluster (id ~1897+)
