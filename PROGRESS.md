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
