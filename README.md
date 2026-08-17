# BruitTrack

Traqueur de **bruits récurrents** : 2 capteurs (micro air + micro/piézo
structure) → détection d'événements par émergence au-dessus du bruit de fond →
une ligne SQLite par événement → visualisation interactive dans le temps.

Conçu pour tourner **24/7 sur un thin client HP T620** (Debian 13, 1.5 GHz,
4 Go RAM, 16 Go SSD) avec un budget < 10 % CPU / < 150 Mo RAM.

## Démarrage rapide

```bash
git clone <repo> && cd bruittrack
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

cp config.toml.example config.toml        # puis renseigner `device` (voir ci-dessous)
python -m bruittrack devices              # trouver le nom ALSA de la M-Track Plus
python -m bruittrack test --seconds 60    # écouter 60 s en terminal
python -m bruittrack start &              # capture daemonisée → data/bruittrack.db
python -m bruittrack viz                  # http://localhost:8760
```

Service systemd : [systemd/bruittrack.service](systemd/bruittrack.service)
(adapteur `User=`, `WorkingDirectory=`).

## Architecture (résumé)

```
ALSA 48 kHz ─ LP Butter fc=400 Hz (numpy) ─ décim ×48 ─ 1000 Hz
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

Squelette fonctionnel (v0.1) : pipeline DSP et détection implémentés et testés
sans matériel ; capture, store et viz à compléter. Voir `TODO` dans le code.
