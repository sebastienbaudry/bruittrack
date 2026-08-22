# GOAL — Coherence doc ↔ code + amélioration continue

## Objectif refiné
1. Rendre `README.md`, `IMPROVEMENTS.md`, `PROGRESS.md` strictement
   cohérents avec l'état réel du code (tests, dépendances, performances).
2. Continuer l'amélioration : finir les items restants de `IMPROVEMENTS.md`
   un à un, chacun = 1 commit + tests verts.
3. Maintenir le budget HP T620 : boucle DSP < 10 % CPU / < 150 Mo RAM
   (mesuré via `tools/bench_ticks.py` : processus total ~< 50 ms/s),
   et l'état déployé sur `pi-t620` aligné sur `main` (si SSH dispo).

## Périmètre (IN)
- Docs repo racine : README.md, AGENTS.md, IMPROVEMENTS.md, PROGRESS.md,
  docs/decision-log.md, BUGS.md — faits seulement vérifiables dans le code/commits.
- Items IMPROVEMENTS.md non cochés : viz tooltips, cap ClusterIndex (LIMIT),
  read-time capture, leak stop() engine, stats `events_last_24h`,
  `--verbose-floor`, entry decision-log. Chacune : code + test minimal.
- Lint : `ruff check . && ruff format --check` (ruff non dispo localement →
  installer via venv ou linter disponible ; documenter sinon).

## Non-objectifs
- Pas de changements d'architecture DSP (spec AGENTS.md figée) ni de dépendance.
- Pas de travail Windows/macOS/GUI/cloud. Pas de refonte de tests existants
  sauf bug démontré.
- Pas de push/merge distant hors `origin` GitHub ; pas d'action destructive
  (reset, rebase publique).

## Critères de fin mesurables (check.sh, SCORE = nb critères OK /7)
1. `pytest -q` : 100 % pass (exit 0).
2. README.md ne contient pas "numpy" pour le filtre LP (scipy.signal.sosfilt)
   et mentionne budget < 10 % CPU.
3. IMPROVEMENTS.md : chaque item `[x]` a un commit de preuve ; chaque `[ ]`
   a une acceptance testable et est réalisable sans matériel.
4. PROGRESS.md : sections Done/Next reflètent les commits réels
   (dernier entry = dernier travail fait ; aucun item "Done" sans commit de preuve).
5. docs/decision-log.md existe avec une entrée par bug corrigé de BUGS.md
   et par fix DSP majeur (≥ 12 entrées datées/hashées).
6. `tools/bench_ticks.py` existe et son résultat documenté dans PROGRESS.md
   : process_block ≈ < 4,5 ms/tock sur cible (note "mesuré sur pi-t620").
7. Ruff : pas d'erreurs syntaxique/usage détectées par `python -m py_compile`
   sur tous les .py (+ ruff si dispo). Exit 0.

## Feuille de route (petites étapes, chacune = 1 commit)
- M0 Inspecter README/IMPROVEMENTS/PROGRESS, lister divergences → notes dans
  PROGRESS.md section "Divergences".
- M1 Corriger pipeline README (scipy, budget < 10 % CPU, commandes CLI réelles).
- M2 Recalibrer IMPROVEMENTS.md : cocher items faits avec preuve, laisser le reste
  avec acceptance non ambiguë.
- M3 docs/decision-log.md : +1 entrée par fix BUGS.md et par fix DSP
  (sosfilt, compute_channel_delay, FloorTracker)
- M4-10 Implementer dans l'ordre les items IMPROVEMENTS.md restants
  (items faciles d'abord : get_stats last_24h → ClusterIndex cap →
  --verbose-floor → stop() leak test → capture read-time → viz tooltips).
- M11 ruff check + format sur repo ; corriger findings triviaux.
- M12 Commit final "docs: coherence README/IMPROVEMENTS/PROGRESS" + push si
  état stable (tests verts).

## Normes de qualité
- Python : type hints + docstring ; messages CLI français, code anglais.
- 1 item = 1 commit en format `type(scope): sujet` ; commit après chaque état
  vérifié — jamais cumuler > 2 items sans test.
- Nouveau test par feature ; `pytest -q` vert avant chaque push.
- Zéro magic numbers : config via dataclasses (config.py) ou constants nommées.

## Hypothèses explicites
- Python local = `python` (Windows, numpy/scipy installés) ; pas de `python3`
  (alias Store). Pas de ruff local → step M11 peut laisser "non vérifié"
  documenté si impossible.
- État déployé pi-t620 (`/opt/bruittrack`) est hors périmètre du check si
  SSH indispo ; notes dans PROGRESS.md suffisent.
- SCORE maximum = 7 ; au-dessous de 7 → itérer les milestones restants.

## Check
`bash check.sh --check` → affiche `SCORE: <0..7>` ; exit 0 si 7/7, else 1.
