# GOAL — Installation et vérification module par module sur hpdebian

## Objectif raffiné
Déployer bruittrack de production sur **hpdebian** (thin client HP T620,
Debian 13, x86 ~1,5 GHz, 4 Go RAM) et prouver que **chaque module**
tourne correctement côté cible :
capture → dsp → events → store → viz → CLI/pipeline, avec preuves
écrites (sorties de commandes, métriques) consignées dans PROGRESS.md.

## Périmètre (IN)
c.1. Pré-requis côté cible : paquetages apt (`python3-venv`, `python3-dev`,
    `portaudio19-dev`, `sox`, `alsa-utils`), utilisateur système `bruittrack`
    (groupe `audio`), répertoire `/opt/bruittrack/snapshot/git + venv`.
c.2. Installation : dépôt dans /opt/bruittrack (`git clone/copy + checkout main`),
    `.venv`, `pip install -e .` (deps numpy/scipy/sounddevice strictes, budget AGENTS.md),
    `config.toml` généré depuis `config.toml.example` avec la `audio.device` réel
    détectée via `python -m bruittrack devices` (jamais en dur).
c.3. Vérification fonctionnelle module par module sur cible (matrice ci-dessous),
    chacune avec critère de succès mesurable + preuve (sortie commande) dans PROGRESS.md.
c.4. Service systemd `systemd/bruittrack.service` installé, enabled, healthy
    (`systemctl is-active/enable/is-active bruittrack` OK après démarrage).
c.5. Vérification budget perf 24/7 : CPU < 15 % et RSS < 150 Mo sur le
    processus DSP (mesures `top`/`ps` après ≥ 10 min de `start`).
c.6. Script d'installation reproductible `tools/install_hp.sh` (idempotent,
    `bash -n` propre) et harnais local de pré-vol `tools/module_check.py`
    (même matrice en mode hors ligne : config/store/viz/tests sans matériel).
c.7. Docs : section « Installation (hpdebian) » + « Vérification des modules »
    dans README.md ; `ASSUMPTIONS.md` à jour ; PROGRESS.md avec une entrée par
    étape réalisée (hash commit, sortie clé).

## Non-objectifs
- Pas d'ajout de dépendance DSP (numpy/scipy/sounddevice + stdlib uniquement).
- Pas de changement du pipeline ou des seuils (spec AGENTS.md figée) sauf bug.
- Pas de travail Windows/macOS ; hpdebian = Debian 13 uniquement.
- Pas de multi-carte, cloud, GUI native. Si le matériel audio (M-Track Plus)
  est absent/désconnecté : on documente et on passe en `test --synthetic`
        hypothèse (voir Hypothèses) ; le but reste « installation OK »,
        la validation audio live est un bonus mesurable, non bloquant.

## Matrice de vérification des modules (chacune = preuve dans PROGRESS.md)
| #  | Module / surface      | Commande (sur cible, venv activé)                              | Critère de succès                                                                 |
|----|-----------------------|-----------------------------------------------------------------|-----------------------------------------------------------------------------------|
| 1  | Packaging/install     | `python -m bruittrack --help`                                    | exit 0, sous-commandes devices/test/start/viz/stats visibles                     |
| 2  | Config                | `python -m py_compile src/bruittrack/*.py`; load+validate config.toml | exit 0 ; validate() n'élève aucune erreur ; device non vide si audio présent      |
| 3  | CLI devices           | `python -m bruittrack devices`                                    | liste ≥ 1 périphérique ; M-Track Plus identifiée OU hypothèse « no hardware »     |
| 4  | Capture               | `timeout 70 python -m bruittrack test --seconds 60 [--synthetic]`  | rc=0 ; blocs lus sans stall ALSA continu (warnings OK)                            |
| 5  | DSP + floor           | idem avec `--verbose-floor`                                       | lignes [floor] apparaissent après ~10 s et médiane finit en état « OK »           |
| 6  | Events/store          | `python -m bruittrack stats --json` (ou sortie équivalente)      | DB créée (WAL), compteur plausible ; un événement synthétique présent si stimulusé |
| 7  | Viz/API               | `python -m bruittrack viz --port 8760 & sleep 2; curl -s localhost:8760/api/stats; kill %1` | HTTP 200 JSON ; dashboard HTML contient timeline + toggles IN1/IN2 + tooltip |
| 8  | systemd               | `sudo systemctl daemon-reload; sudo systemctl enable --now bruittrack; sleep 30; systemctl status bruittrack` | active (running), enabled, journal sans exception Python répétée                   |
| 9  | Budget CPU/RAM        | `ps -o pct=,rss= -C python \| tail -1` (ou proc du service) après ≥ 10 min | %CPU < 15 ; RSS < ~150 000 Ko                                                     |

## Critères de fin mesurables (check.sh, `SCORE: <n>/7`, exit 0 si 7/7)
note : check.sh s'exécute sur la poste dev (Windows) et mesure ce qui y est
vérifiable ; les lignes « sur cible » sont prouvées via PROGRESS.md.
1. C pytest : `python -m pytest -q` → 100 % pass.
2. C compilation : `py_compile` ok sur tous les .py de src/ et tests/.
3. C install locale : `python -m bruittrack --help` exit 0 (editable install fonctionnant).
4. C config : script Python charge `config.toml.example` via load_config() +
   validate() dans un tmpdir — aucune exception ; harnais `tools/module_check.py
   --offline` exit 0 (matrice hors ligne : store :memory:, viz API port éphémère,
   events synthétiques, exemplar WAV).
5. C deployment prêt : `tools/install_hp.sh` existe, `bash -n` propre, contient
   les 7 sections minimales (apt users venv config systemd smoke matrix docs).
6. C matrice PROGRESS.md : une section « Vérification modules hpdebian » recense
   les 9 lignes de la matrice avec statut ✅/⚠️/❌ et preuve (ou ASSUMPTIONS liés
   pour le HW manquante).
7. C docs README : sections présentes — install HP Debian (venv + apt + systemd),
   tableau/checklist matrice, budget CPU/RAM ; aucun « À faire » contradictoire.

## Feuille de route (petites étapes, chacune = 1 commit si possible)
- M0 Audit local : état branch main, pytest vert, diffs config/example ↔ code
  → notes PROGRESS.md § « Phase hpdebian — M0 ».
- M1 Harnais `tools/module_check.py` : mode `--offline` (critère C4) — tests du
  chemin d'installation sans matériel ; commit.
- M2 `tools/install_hp.sh` idempotent (apt/user/clone/venv/pip/config/systemd)
  + option `--smoke` lançant la matrice 1-9 sur cible et sortant rapport
  `install-report.txt` ; `bash -n` local ; commit.
- M3 SSH → hpdebian : exécuter le script de la configuration, capturer les
  sorties, réconcilier config.toml (device via `devices`) ; commit docs/PROGRESS
  avec preuves (§ « Phase hpdebian »).
- M4 Matrice complète sur cible : lignes 1→9 dans l'ordres, chaque ligne
  consignée ✅/⚠️/❌ + preuve ; si HW absent → hypothèse no-hardware (voir
  Hypothèses) et bascule `--synthetic` ; commits de preuves + docs.
- M5 systemd : installer le service, daemon-reload, enable + start, vérifier
  after-boot persistentia (`systemctl is-enabled`) ; journal scan exception
  (grep -iE "Traceback|Error"); commit proof.
- M6 Budget perf ≥ 10 min de run : mesures CPU/RMS du processus DSP ; si hors
  budget → entry decision-log + remediation ; commit preuve.
- M7 README section « Installation (hpdebian) » + matrice copiée + liens vers
  scripts ; ASSUMPTIONS.md réconcilié ; final check.sh = SCORE 7/7, dernier
  commit « feats goal : instal hpdebian validé (SCORE 7/7) ».

## Normes de qualité
- Chaque étape = 1 commit `type(scope): sujet` (type : feat/docs/test/chore),
  message avec preuve (sortie clé hachée ou citée) quand possible.
- `python -m pytest -q` vert avant chaque push ; ruff/py_compile propres.
- Zero magic number : seuils dans `module_check.py` / `install_hp.sh` comme
  constantes nommées au top du fichier (CPU_MAX_PCT=15, RSS_MAX_KB=153600…).
- Français pour messages/proves ; code en anglais type-hinté + docstrings.
- Tout échec SSH/hardware → hypothèse documentée dans ASSUMPTIONS.md avant
  de poursuivre ; jamais casser main au passage.

## Hypothèses explicites
- **H1** « hpdebian » = la machine HP T620 (Debian 13) visée par AGENTS.md,
  accessible en SSH depuis la poste dev après `ssh hpdebian` (alias ~/.ssh/config)
  ou `ssh <user>@<ip>` ; si non atteignable → LOOP_BLOCKED provisoire sur M3-M6
  uniquement, poursuite M1/M2/M7 locales.
- **H2** Comptes cibles : utilisateur système dédié `bruittrack` (service)
  + utilisateur dev ayant sudo (apt/usermgmt) ; user déjà existant par défaut,
  sinon le script le crée.
- **H3** Réseau cible : apt + pip fonctionnent (internet direct ou proxy
  système déjà configuré). Pas de pin de version au-delà de pyproject.
- **H4** Si M-Track Plus non branchée en M4 : matrice passe auto en mode
  `--synthetic` pour les lignes 4/5/6, marquées ⚠️(no-hardware), l'objectif
  « installation opérationnelle » reste atteint si le service tourne avec la
  config et un device valide absent est accepté OU par défaut système.
- **H5** Le check.sh local note seulement ce qu'il peut exécuter sur poste dev ;
  une 7/7 locale n'implique pas le matériel — la preuve HW vient de PROGRESS.md
  (critère C6 en vérifie la présence/la conformité formelle).

## Check
`bash check.sh --check` → affiche `SCORE: <0..7>` ; exit 0 si 7/7 sinon 1.
Les lignes C4/C5/C6/C7 sont les vrais jalons du but ; C1-C3 gardent la base saine.
