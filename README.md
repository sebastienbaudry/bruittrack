# BruitTrack

Traqueur de **bruits récurrents** : 2 capteurs (micro air + micro/piézo
structure) → détection d'événements par émergence au-dessus du bruit de fond →
une ligne SQLite par événement → visualisation interactive dans le temps.

Conçu pour tourner **24/7 sur un thin client HP T620** (Debian 13, 1.5 GHz,
4 Go RAM, 16 Go SSD) avec un budget < 15 % CPU / < 150 Mo RAM.

## Démarrage rapide

```bash
git clone <repo> && cd bruittrack
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

cp config.toml.example config.toml        # puis renseigner `device` (voir ci-dessous)
python -m bruittrack devices              # trouver le nom ALSA de la M-Track Plus
python -m bruittrack test --seconds 60    # écouter 60 s en terminal
# options test : --synthetic (pas de carte son), --verbose-floor (état du FloorTracker /10 s)
python -m bruittrack start &              # capture daemonisée → data/bruittrack.db
python -m bruittrack perf --pid \u003cPID>     # M9 : %CPU + RSS sur 15 s vs budget 15%/150 Mo
python -m bruittrack viz                  # http://localhost:8760
                                                              # clic sur un événement = détail bin/freq/niveaux ; boutons IN1/IN2 = bascule des canaux
```

Service systemd : [systemd/bruittrack.service](systemd/bruittrack.service)
(adapteur `User=`, `WorkingDirectory=`).
## Utilisation

`python -m bruittrack [-c CONFIG] <sous-commande>` — config unique source : `config.toml`.

| Sous-commande | Options | Rôle |
|---|---|---|
| `devices` | — | Liste les paires in/out ALSA (M-Track Plus, 48 kHz) |
| `test` | `-s/--seconds`, `--synthetic`, `--verbose-floor` | Test court sans persistance (synthétique si pas de carte) |
| `start` | — | Boucle temps réel 24/7 (Démarrage rapide) |
| `viz` | `-p/--port` (8760), `--host` (0.0.0.0) | Serveur HTTP stdlib : dashboards + API JSON |
| `stats` | `--play ID`, `--json` | Top clusters + exemplaires (replay SoX) ; JSON pour scripts |
| `perf` | `--pid` | CPU/RAM via /proc, ou attach à un PID systemd |
| `prune` | — | Supprime les exemplaires orphelins + VACUUM (opt) |

### API du dashboard

`GET /` · `GET /api/events[?since&limit&offset&cluster]` · `GET /api/clusters[?limit]` · `GET /api/stats` · `GET /api/health` · `GET /api/exemplar/\<id\>.wav` · `POST /api/clusters/\<id\>/triage {flags, label}` (bit 0 connue, bit 1 ignorée) — cf. section Triage plus bas.

La timeline du dashboard propose des fenêtres glissantes (1h/6h/24h/Tout) et un **zoom par brushing** : glisser sur la timeline sélectionne une plage temporelle qui verrouille l'axe ; double-clic ou Échap rétablit la fenêtre de boutons.
  **Zoom/dézoom 2 axes (I54)** : molette sur le chronogramme = zoom synchronisé temps + fréquence ancré au curseur ; Ctrl+glisser vertical = translate fréquence ; double-clic, Échap ou clic sur le badge réinitialisent.

La rétention (`retention_days`) s'applique automatiquement au démarrage et quotidiennement via le pipeline ; `prune` nettoie orphelins quand l'exemplaire n'a plus que 0 événement rattaché sur la vue clusters.


## Architecture (résumé)

```
ALSA 48 kHz ─ LP Butter fc=400 Hz (scipy.signal.sosfilt, 4 biquads)
   ─ décim ×48 ─ 1000 Hz
   └ Welch 2 s ─ EMA ─ floor (médiane 30 s) ─ émergence dB
       └ détecteur (seuil 10 dB, debounce 0,5 s) → événements SQLite
```

Stockage minimal : **aucun PCM** — 1 ligne par événement (~64 octets) +
fingerprint 16 octets → clustering des bruits récurrents. Extrait audio
optionnel **un seul** par cluster (256 ms basse fréquence).

## Documentation

- [AGENTS.md](AGENTS.md) — constitution du projet (matériel, budget, conventions)
- [docs/decision-log.md](docs/decision-log.md) — décisions de conception
- [docs/reference/gemini-waterfall.py](docs/reference/gemini-waterfall.py) —
  script de référence (waterfall infrasons) dont est porté le pipeline DSP

## État

Version initiale complète (v0.1.0) :
- Pipeline DSP pur NumPy (Butterworth 400 Hz, décimation x48, Welch, EMA, FloorTracker).
- Détection d'émergence, empreintes acoustiques 16 octets et clustering (`ClusterIndex`).
- Persistance SQLite WAL avec insertion par lots et politique de rétention.
- Interface de visualisation Web légère autonome (HTML5 Canvas + API REST).
- CLI complète (`devices`, `test`, `start`, `viz`, `stats`).
- Suite de tests unitaires 100 % déterministe sans matériel.

## Installation (hpdebian)
Cible HP T620 (Debian 13, x86 ~1,5 GHz, 4 Go RAM) pour l'exécution continue :
```bash
sudo bash tools/install_hp.sh   # apt deps → /opt/bruittrack/git + .venv → config.toml → systemd enable --now
```
Idempotent. Post-install : identifier le périphérique `M-Track Plus` dans
`${APP_DIR}/config.toml` via `python -m bruittrack devices` (jamais en dur),
puis `sudo systemctl restart bruittrack`.
Pre-flight hors ligne avant déploiement : `tools/module_check.py --offline`
(marge C4) — CLI, config load+validate, fingerprint+ClusterIndex, store
`:memory:`, viz API (stats/events/exemplar WAV 2ch @1 kHz).

### Triage via API
Mise à jour du triage d'un cluster (`flags` : bit0=connue / bit1=ignorée + libellé), puis lecture :
```bash

curl -sX POST http://localhost:8080/api/clusters/1/triage \r
  -H 'Content-Type: application/json' \r
  -d '{"flags": 1, "label": "condensateur compresseur (nuit)"}'

curl -s 'http://localhost:8080/api/clusters?limit=20'

> `GET /api/clusters` liste aussi les clusters etiquetes *avant* le 1er event (`event_count=0`, ajout I17).

```

### Purge post-rangement (une seule commande)
Apres la correction 80dbfe9, purger les evenements non-significatifs en base :
artefacts DC (`freq=0.0`) dont emergence max(lvl_g,lvl_d) < 10 dB.
Depuis I35, aucune detection sous `min_event_hz` (defaut 2.0 Hz) ;
les evenements entre 0 et `min_event_hz` existants se purgent de la meme facon.
```bash
systemctl stop bruittrack
sqlite3 data/bruittrack.db < scripts/purge_noise.sql
systemctl start bruittrack
```
Depuis I35 une purge de rattrapage `scripts/purge_lowfreq.sql` supprime les events avec `freq < min_event_hz` (defaut 2.0 Hz) existants en base.
Le script affiche un apercu (COUNT) AVANT, execute DELETE + VACUUM et
reporte le nombre de lignes supprimees.

## Vérification des modules
Matrice cible 1:1 avec GOAL.md c.3–c.5 + lignes M1/M2 locales : chaque
module est validé isolément sur la cible avec une preuve commandée
(`output.txt` de PROGRESS.md) et un critère mesurables :
| # | Module | Check clé (cible) | Pass |
|---|--------|-----------------|------|
| 1 | CLI | `--help rc=0`, sous-commandes visibles | ✅ |
| 2 | Config | load_config()+validate() sans exception | ✅ |
| 3 | Capture | `test --seconds 60 [--synthetic]` rc=0, no ALSA stall | ❔ (hardware) |
| 4 | DSP + floor | `--verbose-floor` : les `[floor]` lignes sont OK après ≈10 s | ❔ (hardware) |
| 5 | Events/store | `stats --json` : DB WAL init, compteur plausible | ✅ (offline store) |
| 6 | Viz/API | `curl /api/stats` 200 JSON ; `/api/exemplar/<c>` WAV 2ch@1 kHz | ✅ (harness) |
| 7 | systemd | `active (running)`, enabled, journal sans exception | ❔ (host) |
| 8 | Budget M9 | `bruittrack perf --pid $MAINPID` (≥10 min) : %CPU < 15, RSS < 150 Mo, RC=0 | ✅ prod (it.64 : 12.9 %) |
❔ = à valider sur cible après l’installation ; ✅ via harness/py tests.
