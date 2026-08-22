# BruitTrack — traqueur de bruits récurrents

## Objectif
Python (Debian 13) : capture stéréo 2 capteurs, détection/indexation
d'événements sonores récurrents (1 ligne SQLite/événement), visualisation
temporelle interactive.

## Contrainte majeure : HP T620
x86 ~1,5 GHz, 4 Go RAM, 16 Go SSD, pas de GPU, 24/7 fanless → tous les
choix d'architecture en découlent.
- M-Track Plus (USB/ALSA) : IN1 = micro A (air), IN2 = piézo B (structure).
  Canaux complémentaires → **toujours analyser les deux ensemble**.
  Device forcé dans `config.toml` (`python -m bruittrack devices`), jamais en dur.
- Flux 48 kHz / 2 ch / float32 → décimation ×48 → **1000 Hz exact**.

## Budget (chaque PR)
CPU < 10 %, RAM < 150 Mo, 1 process Python DSP (~48k it/s).
- Pas de matplotlib/Tk/Qt. Viz = HTTP stdlib lisant SQLite, process séparé
  (navigateur ou `curl` JSON).
- Aucun dump PCM brut ; extrait 256 ms BF **seulement** pour le 1er exemplaire
  d'un cluster (flag `exemplar`, ~512 B).
- SQLite : WAL, synchronous=NORMAL, lots (30 s ou 50), index (t0),(cluster).
  ~7 Mo/an ; `retention_days` optionnel.

## Pipeline (cadence 100 ms) — porté de docs/reference/gemini-waterfall.py
ALSA 48k → LP 4 biquads Butter fc=400 Hz via `scipy.signal.sosfilt`
(1er ajout autorisé, activé — entry decision-log) → décim ×48 → 1000 Hz
(ring 33k) → blocs 100 ms → Welch 2048 pts (2 s), overlap 50 %, 7 seg →
EMA α=0.5 → floor = médiane glissante 300 ticks/bin → émergence (dB),
bins 0..98 (0–48 Hz, 0,49 Hz/bin) → seuil 10 dB, debounce 5 ticks (0,5 s),
hystérésis 3 dB, découpe à 30 s → 1 ligne DB + fp 16 o.
- 1er tick = seed (floor = 1er PSD) ; aucun événement avant 300 ticks (~30 s).
- Résolutions 100 ms / 0,49 Hz ; > 48 Hz hors périmètre.

## Détection / fingerprint / clustering
- Par bin et par canal ; tag canal dominant (`both` si émergence > seuil sur
  les 2 dans ±2 bins).
- Événement : t0, dur, bin_i, freq, lvl_g/lvl_d (dB au-dessus floor),
  off_ms (cross-corr G/D ±8 ms), fp, cluster, flags.
- fp 16 o, indépendant de l'heure : version(1)|bin_peak(2)|5 briques voisines
  quantifiées 3 bits(5)|canal dominant(1)|classe délai ±20 ms(1).
- Cluster : |Δbin|≤2, Σ|Δbriques quant.|≤2, |Δclasse délai|≤2 ;
  ClusterIndex reconstruit depuis la DB au démarrage.
- flags : bit0 connue, bit1 ignorée, bit2 exemplaire → triage via API web.

## DB data/bruittrack.db — table events
id PK | t0 REAL unix | dur REAL (≤30) | bin_i INT 0..98 | freq REAL
(bin_i×0,48828) | lvl_g,lvl_d REAL | off_ms REAL (−8..+8) | fp BLOB(16) |
flags INT | cluster INT NULL.
Exemplars : `exemplars/ex_<cluster>_<id>.raw` (256 ms @1 kHz 2ch float16),
1 seul/cluster ; replay `stats --play <id>` (sox).

## Fichiers
src/bruittrack/ : __main__.py (CLI) | config.py (dataclass+toml) |
dsp.py (LP, décim, Welch, EMA, FloorTracker ; numpy pur) | events.py
(détecteur, fp, ClusterIndex) | pipeline.py (Engine) | capture.py
(sounddevice+queue, import différé) | store.py (SQLite WAL/lots) |
viz.py (HTTP stdlib) ; tests/ pytest sans matériel ; config.toml.example ;
systemd/bruittrack.service ; docs/decision-log.md ; docs/reference/…

## Commandes
venv + `pip install -e ".[dev]"` ; `pytest` ; `ruff check . && ruff format .` ;
`python -m bruittrack devices|test --seconds 60|start|viz --port 8080|stats`

## Conventions
- Type hints + docstrings ; code anglais, messages/CLI français.
- Deps : numpy + scipy + sounddevice + stdlib **uniquement** (scipy
  documenté au decision-log). Dep ou table nouvelle → entry decision-log.md.
- Tests déterministes sans matériel (synthèse, DB :memory:) ; `sounddevice`
  importé seulement dans capture.py.
- `time.time()` (DB) vs `time.monotonic()` (interne), jamais mélanger.
- config.toml = unique source de vérité ; zéro magic number.

## Hors périmètre
ML/classif auto ; cloud/réseau ; Windows/macOS ; GUI native ; > 30 s sans
découpe ; multi-cartes.
