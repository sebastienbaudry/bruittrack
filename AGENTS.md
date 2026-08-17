# BruitTrack — traqueur de bruits récurrents

## Objectif
Logiciel Python (Debian 13) qui capture le flux stéréo de 2 capteurs,
détecte et indexe les **événements sonores récurrents**, avec un stockage
**minimal** (une ligne SQLite par événement) et une **visualisation
interactive dans le temps**.

## Matériel cible (CONTRAINTE MAJEURE)
- **HP T620 Flexible Thin Client** : x86 ~1,5 GHz, **4 Go RAM**, **16 Go SSD**,
  pas de GPU, fonctionnement **24/7** (sans ventilateur).
  → Tous les choix d'architecture découlent de ceci : faible CPU, RAM limitée,
  SSD modeste, **pas de GUI lourde**.
- Carte son **M-Track Plus** (USB, classe audio = ALSA/PortAudio) :
  - **IN1 = micro A** (air), **IN2 = micro/piézo B** (structure — cf. script de
    référence, « Piézo »). Les 2 canaux portent des **informations
    complémentaires** → **toujours les analyser ensemble**, jamais un seul.
  - Nom/préfixe du device à **forcer dans `config.toml`** (vérifier avec
    `python -m bruittrack devices`), jamais codé en dur.
- Flux : **48 kHz / 2 ch / float32**. Décimation 48 → stream basse fréquence
  **exactement 1000 Hz**.

## Budget ressourçes thin client (à respecter dans chaque PR)
- CPU stable < 10 %, RAM < 150 Mo, **1 seul process Python** DSP (≈ 48k it/s).
- **Pas de matplotlib/Tk/Qt**. Visualisation = mini-serveur HTTP **stdlib**
  qui lit SQLite (process séparé de la capture, arrêt indépendant). Navigateur
  local OU simple `curl` JSON.
- **Aucun dump PCM brut**. Stockage = 1 ligne d'événement + (optionnel)
  extrait 256 ms basse fréquence **uniquement pour un premier exemplaire de
  cluster** (flag `exemplar`, ~512 B).
- SSD : SQLite `journal_mode=WAL`, `synchronous=NORMAL`, insertion **par lots**
  (lot de 30 s ou 50 événements), index `(t0)`, `(cluster)`.
- Volume estimé : 1 événement / 10 s ≈ **7 Mo/an** → 16 Go plus que suffisants,
  mais garder un `retention_days` optionnel dans la config.

## Pipeline signal (cadence 100 ms)
```
ALSA 48 kHz ── LP anti-repliement (4 biquads Butter fc=400 Hz, numpy pur)
         ── décimation ×48 ──> stream 1000 Hz  (rolling buffer 33 k échantillons)
blocs 100 ms ── Welch (fenêtre 2048 pts = 2 s, 50 % overlap, 7 segments)
         ── EMA α=0.5 ──> floor (médiane glissante 300 ticks, par brique)
         ── émergence = PSD_ema − floor (dB), briques 0..98 (0–48 Hz, 0.49 Hz/brique)
         ── détecteur : seuil 10 dB, debounce 5 ticks (0,5 s), hystérésis 3 dB,
                 30 s max par segment (au-delà on découpe)
         ──> événement = 1 ligne DB + fingerprint 16 octets
```
- Pipeline DSP **porté du script de référence** `docs/reference/gemini-waterfall.py`
  (Welch + floor médiane + EMA, queue de capture, calibration). Migration à
  48 kHz/48 (décimation exacte) et au cas **2 capteurs complémentaires**
  (air + structure) plutôt que 2 micros équivalents.
- La LP est en **numpy pur** (boucle scalaire, ~1 % CPU). Si un jour c'est un
  goulot : basculer sur `scipy.signal.sosfilt` (premier ajout autorisé).
- Résolution temporelle des événements : 100 ms. Résolution fréquentielle :
  0.49 Hz (bins 0..48 Hz). Au-delà de 48 Hz : hors périmètre infrasons.
- Le **premier tick** après démarrage est le seed (floor = premier PSD), ne pas
  y générer d'événements avant 300 ticks de stabilisation (~30 s).

## Détection, fingerprint, clustering
- Détection **par bin et par canal** ; un événement tagge le **canal dominant**
  (ou `both` si émergence > seuil sur les 2 dans la même fenêtre binaire ±2 bins).
- Champs d'un événement : `t0`, `dur`, `bin_i`, `freq`, `lvl_g`, `lvl_d`
  (émergence au-dessus floor, dB), `off_ms` (cross-correlation G/D sur le ring,
  ±8 ms), `fp` (16 octets), `cluster`, `flags`.
- **Fingerprint** (identifiant de réccurrence, **indépendant de l'heure** —
  « même bruit » = même fp quel que soit le jour de survenue) :
  `version(1) | bin_peak(2) | 5×briques voisines quantifiées 3 bits (5) |
  canal dominant(1) | classe de délai ±20 ms (1)` → 16 octets.
- **Cluster** = même famille de fp : `|Δbin| ≤ 2`, `Σ|Δbricoles| ≤ 2` (dans la
  quantification), `|Δclasse délai| ≤ 2`. Attribué par le
  `ClusterIndex` (reconstruit depuis la DB au démarrage).
- `flags` : bit0 = connue, bit1 = ignorée, bit2 = exemplaire audio stocké.
  Ces bits supportent la boucle de *triage* (valider/ignorer un cluster) via
  l'API web.

## Modèle de données minimal (`data/bruittrack.db`)
Table `events` :

| Colonne   | Type      | Contenu                                            |
|-----------|-----------|----------------------------------------------------|
| id        | INTEGER PK|                                                    |
| t0        | REAL      | Unix time (s) du 1er sample ≥ seuil                |
| dur       | REAL      | durée en s (≤ 30 par segment)                      |
| bin_i     | INT       | 0..98                                              |
| freq      | REAL      | bin_i × 0.48828 Hz                                 |
| lvl_g / lvl_d | REAL  | émergence (dB au-dessus floor), par canal          |
| off_ms    | REAL      | décalage G/D (cross-corr), −8..+8 ms               |
| fp        | BLOB (16) | fingerprint v0                                     |
| flags     | INT       | bits ci-dessus                                     |
| cluster   | INT NULL  | groupe de réccurrence (NULL = sans cluster)        |

Extrait audio optionnel : `exemplars/ex_<cluster>_<id>.raw` (256 ms à 1 kHz,
2 ch, float16) — **un seul** par cluster (flag `exemplar`). À rejouer via CLI
`stats --play <cluster_id>` en `sox`.

## Architecture des fichiers
```
src/bruittrack/
  __main__.py     CLI (devices / test / start / viz / stats)
  config.py       dataclass + chargement config.toml
  dsp.py          LP, décimation, Welch, EMA, FloorTracker   (numpy pur, testé)
  events.py       détecteur d'événements, fingerprint, ClusterIndex
  pipeline.py     Engine : capture → dsp → detector → store (glue)
  capture.py      InputStream sounddevice + queue thread-safe (import lourd, différé)
  store.py        SQLite (WAL, lots, requêtes, clusters)
  viz.py          serveur HTTP stdlib (timeline canvas + API JSON)
  tests/          pytest, 100 % sans matériel (synthesis)
config.toml.example
systemd/bruittrack.service
docs/
  decision-log.md
  reference/gemini-waterfall.py   (script source du pipeline DSP)
```

## Commandes
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

pytest                                   # aucun matériel requis
ruff check . && ruff format .

python -m bruittrack devices             # liste des périphériques PortAudio
python -m bruittrack test --seconds 60   # monitoring live en terminal (pas de X)
python -m bruittrack start               # daemon de capture (systemd conseillé)
python -m bruittrack viz --port 8080     # visualisation navigateur
python -m bruittrack stats               # compteurs, top clusters, santé floor
```

## Conventions
- Type hints partout, docstrings ; **code en anglais**, **messages/CLI en français**.
- Dépendances strictement : `numpy` + `sounddevice` + stdlib. **S'en tenir à ça**
  sauf justification documentée (scipy = premier candidat si CPU).
- Tests **déterministes sans matériel** : tout passer par des fonctions pures
  (blocs synthétiques sin + bruit, emergence injectés, DB en `:memory:`).
  Interdiction d'import `sounddevice` en dehors de `capture.py`.
- Horodatage : `time.time()` Unix dans la DB, `time.monotonic()` en interne ;
  ne jamais mélanger les deux.
- `config.toml` = **unique source de vérité** (device, seuils, cadence, limites),
  jamais de magics numbers dans le code.
- Tout ajout de dépendance ou de table DB = entry dans `docs/decision-log.md`.

## Hors périmètre (pour l'instant)
- Classification automatique par ML (le fingerprint + clustering en prend la
  relâche à la main) ; réseau/cloud ; Windows/macOS ; GUI native ;
  enregistrements > 30 s sans découpage ; multi-cartes-son.

## Fichiers de référence
- `docs/decision-log.md` — décisions de conception (garder à jour)
- `docs/reference/gemini-waterfall.py` — script dont est porté le pipeline DSP
  (gardé tel quel comme oracle de comportement)
