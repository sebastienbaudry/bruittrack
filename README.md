# BruitTrack

**BruitTrack** est un système autonome de surveillance, de caractérisation et de qualification juridique des **nuisances sonores répétitives, bruits sourds et infrasons** (0 à 150 Hz). 

Conçu pour fonctionner **24 h / 24 et 7 j / 7 sur un mini-PC silencieux basse consommation (HP T620)**, il enregistre les caractéristiques physiques et temporelles objectives des perturbations sans stocker de flux audio continu (respect strict de la vie privée et empreinte disque minimale).

---

## 🎯 À quoi sert BruitTrack ? (Description fonctionnelle)

Dans un logement ou un local professionnel, objectiver et faire cesser une nuisance sonore intermittente est un défi majeur :
* **Bruits sourds et infrasons nocturnes** : Les vibrations de pompes à chaleur (PAC), VMC industrielles, compresseurs frigorifiques, chaudières, ascenseurs ou transformateurs électriques se propagent souvent la nuit par voie solidienne (murs, planchers). Ces basses fréquences sont difficilement audibles sur un smartphone classique mais provoquent des sensations physiques réelles (vibrations corporelles, réveils en sursaut, acouphènes, nausées).
* **Preuve juridique et aléas des mesures** : Les mesures ponctuelles d'experts ou constats d'huissier arrivent rarement au moment de la crise.
* **Respect de la vie privée** : L'enregistrement audio continu est exclu dans un espace privé.

### Ce que fait le système :
1. **Surveillance continue 24/7 & Détection en temps réel** : Analyse le spectre sonore basse fréquence 10 fois par seconde (blocs de 100 ms) et calcule en temps réel le niveau de fond habituel. Tout événement dépassant le plancher de bruit de plus de 10 dB est automatiquement détecté et chronométré.
2. **Double écoute synchronisée (Air + Structure)** : En couplant un microphone aérien et un capteur de vibration piézoélectrique de contact, BruitTrack détermine si le bruit provient de l'air ou de la structure du bâtiment et calcule le décalage temporel d'arrivée.
3. **Identification et regroupement des sources (Clustering)** : Chaque événement reçoit une empreinte spectrale compacte de 16 octets. Le système regroupe automatiquement les bruits récurrents par signature identique (ex. *Cluster #1 : Compresseur s'enclenchant toutes les 45 min*, *Cluster #3 : Résonance à 41 Hz*).
4. **Journal des gênes ressenties & Clichés HD** : En cas de nuisance ressentie, l'habitant consigne l'instant en 1 clic. Le système capture immédiatement 30 secondes d'audio HD non compressé pour analyse détaillée et corrèle le ressenti avec les clusters sonores actifs.
5. **Qualification légale automatique (CSP Art. R1336-7)** : Évalue automatiquement chaque émergence selon les critères officiels du Code de la santé publique (période diurne/nocturne, durée cumulée, correctifs légaux) et génère des rapports d'infraction.
6. **Tableau de bord web interactif** : Visualisation en direct sans installation client (chronogramme par bulles colorées, spectrogramme continu 24h, zoom fréquentiel et temporel, écoute d'extraits audio représentatifs).

---

## 🎙️ Chaîne d'acquisition et matériel

Le système s'articule autour d'une station de mesure autonome, économique et silencieuse :

| Composant | Matériel utilisé | Rôle et caractéristiques |
|---|---|---|
| **Station de calcul 24/7** | Thin client **HP T620** (ou mini-PC x86 / Raspberry Pi)<br>*(Debian 13, x86 ~1,5 GHz, 4 Go RAM, 16 Go SSD)* | Fonctionnement fanless 100 % silencieux, basse consommation (< 10 W), assurant le traitement DSP continu sans surchauffe. Budget strict : **CPU < 15 %** et **RAM < 150 Mo**. |
| **Interface audio (Carte son)** | **M-Audio M-Track Plus** (USB)<br>*(ou toute interface audio USB stéréo 24-bit / 48 kHz supportée par ALSA)* | Numérisation haute fidélité à 48 kHz / 2 canaux synchronisés, préamplis à faible bruit, entrées combo XLR / Jack 6.35 mm indépendantes et gain réglable. |
| **Canal 1 (IN1 / Gauche) — Voie Aérienne** | **Behringer ECM8000** (branché en **XLR** avec alimentation fantôme +48V)<br>*(Microphone de mesure à condensateur à réponse en fréquence linéaire)* | Capture fidèle de la pression acoustique dans l'air ambiant de la pièce (courbe de réponse ultra-plate pour une mesure objective des émergences audibles et basses fréquences). |
| **Canal 2 (IN2 / Droite) — Voie Solidienne** | **Micro Piezo sans marque** (branché en **Jack 6.35 mm**)<br>*(Transducteur / pastille piézoélectrique de contact)* | Plaqué ou collé contre une paroi (mur porteur, plancher, tuyauterie, cadre de fenêtre) pour capter directement les vibrations mécaniques et bruits d'impact transmis par la structure du bâtiment. |

> [!NOTE]
> **Pourquoi analyser systématiquement les deux canaux ensemble ?**
> La corrélation croisée inter-canaux (calculée à $\pm 8\text{ ms}$) et le ratio d'énergie Air vs Structure permettent de localiser l'origine de la gêne :
> * Émergence dominante sur **IN1 (Air)** $\to$ Bruit transmis par voie aérienne (rue, fenêtre, voisinage direct).
> * Émergence dominante sur **IN2 (Piézo)** $\to$ Bruit transmis par voie solidienne (moteur/pompe fixé au bâtiment, tuyauterie, dalle).
> * Émergence sur les deux canaux $\to$ Phénomène combiné ou couplage mécano-acoustique fort.

---

## Sommaire

1. [À quoi sert BruitTrack ? (Description fonctionnelle)](#-à-quoi-sert-bruittrack--description-fonctionnelle)
2. [Chaîne d'acquisition et matériel](#️-chaîne-dacquisition-et-matériel)
3. [Démarrage rapide](#démarrage-rapide)
4. [Conformité légale (CSP Art. R1336-7)](#conformité-légale-csp-art-r1336-7)
5. [Architecture et pipeline DSP](#architecture-et-pipeline-dsp)
6. [Référence des commandes CLI](#référence-des-commandes-cli)
7. [Interface web et API REST](#interface-web-et-api-rest)
8. [Journal des gênes et clichés HD](#journal-des-gênes-et-clichés-hd)
9. [Installation et déploiement (HP T620)](#installation-et-déploiement-hp-t620)
10. [Configuration (`config.toml`)](#configuration-configtoml)
11. [Tests et qualité](#tests-et-qualité)

---

## Démarrage rapide

```bash
git clone <repo> && cd bruittrack
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[audio,dev]"

# 1. Configuration initiale
cp config.toml.example config.toml
python -m bruittrack devices               # Repérer l'ID ou le nom ALSA (ex: "M-Track Plus")
# Éditer config.toml pour renseigner le champ `device`

# 2. Test direct en terminal
python -m bruittrack test --seconds 60     # Test en direct 60 s
# Options test : --synthetic (sans carte son), --verbose-floor (état du plancher dynamique)

# 3. Lancement du démon 24/7
python -m bruittrack start &               # Capture & détection en arrière-plan -> data/bruittrack.db

# 4. Tableau de bord web interactif
python -m bruittrack viz --port 8760       # Accessible sur http://localhost:8760

# 5. Vérification du budget de performance
python -m bruittrack perf                  # Mesure CPU/RSS sur 15 s vs budget 15 % / 150 Mo
```

---

## Conformité légale (CSP Art. R1336-7)

BruitTrack intègre les règles officielles de calcul de l'**émergence acoustique** définies par le Code de la santé publique (Article R1336-7) pour qualifier objectivement les infractions et nuisances.

### 1. Variables et calculs
* **Émergence mesurée** : $E_{\text{mesurée}} = \text{bruit ambiant} - \text{bruit résiduel}$ (en dB).
* **Période temporelle (seuil de base)** :
  * **Période Diurne** (07:00 à 21:59) : `seuil_base` = **5 dB(A)**.
  * **Période Nocturne** (22:00 à 06:59) : `seuil_base` = **3 dB(A)**.
* **Terme correctif** selon la durée cumulée d'apparition de la nuisance :
  * $\le 1\text{ min}$ : **+6 dB(A)**
  * $1\text{ min} < T \le 5\text{ min}$ : **+5 dB(A)**
  * $5\text{ min} < T \le 20\text{ min}$ : **+4 dB(A)**
  * $20\text{ min} < T \le 2\text{ h}$ : **+3 dB(A)**
  * $2\text{ h} < T \le 4\text{ h}$ : **+2 dB(A)**
  * $4\text{ h} < T \le 8\text{ h}$ : **+1 dB(A)**
  * $> 8\text{ h}$ : **+0 dB(A)**
* **Émergence limite autorisée** : $E_{\text{limite}} = \text{seuil de base} + \text{correctif}$.
* **Contrainte de contrôle** : Si la durée cumulée est $< 10\text{ s}$, la durée d'enregistrement du bruit ambiant doit obligatoirement être $\ge 10\text{ s}$ sous peine d'invalidation du relevé.

### 2. Rapports de conformité
Génération directe depuis la CLI ou via l'API Web :
```bash
# Rapport texte synthétique complet
python -m bruittrack report --since 1700000000

# Export au format JSON pour intégration légale ou analyse
python -m bruittrack report --json --output rapport_acoustique.json
```

---

## Architecture et pipeline DSP

```
Flux audio 48 kHz / 2 canaux (Air + Structure)
   │
   ▼
Filtre passe-bas Butterworth 400 Hz (scipy.signal.sosfilt, 4 biquads SOS)
   │
   ▼
Décimation exacte ×48 ──► Flux 1000 Hz (Ring buffer 33k pts)
   │
   ├─► Spectrogramme continu (Table `spectrum`, agrégation 5 s, 150 bandes [2..150 Hz])
   │
   └─► Analyse spectrale Welch (2048 pts, recouvrement 50 %, 7 segments)
         │
         ▼
       Lissage EMA (α = 0.5)
         │
         ▼
       Plancher dynamique FloorTracker (médiane glissante 300 ticks = 30 s)
         │
         ▼
       Calcul de l'émergence (dB) sur [min_event_hz (2 Hz) .. freq_max (150 Hz)] (DC exclu)
         │
         ▼
       Détecteur à hystérésis (seuil 10 dB, hystérésis 3 dB, debounce 0.5 s, découpe 30 s)
         │
         ├─► Empreinte acoustique 16 octets (wobble-invariant) & Clustering temps réel
         ├─► Extrait audio exemplaire float16 (256 ms @ 1 kHz, 1 seul par cluster)
         └─► Insertion par lots (50 evts / 30 s) ──► SQLite WAL (`data/bruittrack.db`)
```

### Principes clés
- **Zéro dump PCM continu** : Seuls les métadonnées (durée, fréquences, niveaux d'émergence G/D, délai inter-canal) et les empreintes 16 octets sont stockés (~64 octets / événement).
- **Invariance à la dérive du pic (wobble)** : L'algorithme de comparaison d'empreintes tolère les légères oscillations de fréquence sans fragmenter les clusters.
- **Fusion post-hoc (Union-Find)** : Fusionne au démarrage les quasi-doublons de clusters historiques et renomme proprement les exemplaires associés.
- **Exemplaires audio minimaux** : 256 ms @ 1 kHz en float16 (~512 octets) enregistrés uniquement pour le premier événement représentatif d'un cluster.

---

## Référence des commandes CLI

Syntaxe générale : `python -m bruittrack [-c CONFIG] <sous-commande> [options]`

| Sous-commande | Arguments et options | Description |
|---|---|---|
| `devices` | — | Liste les périphériques d'entrée audio ALSA / PortAudio disponibles. |
| `test` | `-s/--seconds`, `--synthetic`, `--verbose-floor` | Test en direct dans le terminal sans interface graphique ni écriture en base. |
| `start` | — | Démarre le démon 24/7 de capture, DSP, détection et persistance continue. |
| `viz` | `-p/--port` (8760), `--host` (127.0.0.1) | Lance le serveur web HTTP stdlib autonome (dashboard Canvas + API REST). |
| `stats` | `--play ID`, `--json` | Affiche le top des clusters et l'état de la base ; réécoute un exemplaire (SoX). |
| `report` | `--since`, `--json`, `-o/--output` | Génère un rapport de conformité acoustique légale (CSP Art. R1336-7). |
| `log-discomfort` | `-l/--level` (1-5), `-n/--note`, `-t/--time` | Enregistre un signalement de gêne / crise avec déclenchement de cliché HD. |
| `discomfort-logs` | `--since`, `--limit`, `--json` | Liste l'historique des signalements de gêne enregistrés. |
| `purge-spectrum` | `-d/--days` | Purge manuelle des trames du spectrogramme plus anciennes que *N* jours. |
| `perf` | `--pid` | Vérifie la consommation CPU et mémoire RSS sur 15 s vs les budgets M9. |
| `prune` | — | Supprime les extraits audio exemplaires orphelins (clusters absents de la base). |

---

## Interface web et API REST

Le serveur de visualisation (`python -m bruittrack viz`) fournit un tableau de bord complet en HTML5 Canvas pur, sans framework JavaScript externe ni dépendance tierce.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│  BruitTrack — Tableau de Bord                     [● En direct]  [MAJ il y a 2s]       │
├────────────────────────────────────────────────────────────────────────────────────────┤
│  [Statistiques] Total Événements : 3 420 | Clusters : 42 | Infractions Légales : 3    │
├────────────────────────────────────────────────────────────────────────────────────────┤
│  [Filtres] Canaux: [Tous][IN1 Air][IN2 Piézo]  Fréq: [Infra][20-50Hz][50Hz][HF]       │
│  [Chronogramme] Bulles colorées par cluster (palette harmonique dorée)                 │
│                 Zoom temporel par brossage (brushing) | Zoom Fréq Y molette / Ctrl+drag │
├────────────────────────────────────────────────────────────────────────────────────────┤
│  [Spectrogramme continu] Rendu raster HD synchronisé (table spectrum)                 │
├────────────────────────────────────────────────────────────────────────────────────────┤
│  [Tableau des Événements] Pagination, tri, audio WAV 1 kHz, triage cluster             │
│  [Journal des Gênes] Déclaration en direct, analyse psychoacoustique, profil FFT 1D    │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

### Points d'accès API REST

| Méthode | Route | Description |
|---|---|---|
| `GET` | `/` | Tableau de bord web interactif complet (HTML5 / Canvas). |
| `GET` | `/api/health` | Vérification de l'état du serveur et comptage des événements. |
| `GET` | `/api/stats` | Statistiques globales (total événements, clusters, taille DB, durée moyenne). |
| `GET` | `/api/events` | Liste paginée des événements (`?since=`, `?limit=`, `?offset=`, `?cluster=`, `?order=`). |
| `GET` | `/api/clusters` | Résumé des clusters acoustiques et métadonnées de triage. |
| `POST` | `/api/clusters/<id>/triage` | Triage d'un cluster : `{flags: 1|2, label: "nom"}` (bit 0=connue, bit 1=ignorée). |
| `GET` | `/api/exemplar/<id>.wav` | Flux audio WAV 16-bit 2 canaux @ 1 kHz de l'extrait exemplaire. |
| `GET` | `/api/reports/legal` | Rapport d'émergence légale JSON (`?since=`, `?until=`). |
| `GET` | `/api/spectrum` | Données brutes du spectrogramme continu (`?since=`, `?until=`, `?step=`). |
| `GET` | `/api/spectrum.png` | Rendu graphique PNG haute définition du spectrogramme (`?width=`, `?ch=`, `?f_lo=`, `?f_hi=`). |
| `GET` | `/api/discomfort` | Historique des signalements de gêne ressentie. |
| `POST` | `/api/discomfort` | Déclaration d'une gêne `{level: 1-5, note: "...", t0: ...}` + capture de cliché HD. |
| `POST` | `/api/discomfort/<id>/delete` | Suppression d'un signalement et de son cliché HD associé. |
| `GET` | `/api/discomfort/<id>/snapshot` | Données spectrales et psychoacoustiques du cliché HD (profil FFT 1D). |
| `GET` | `/api/discomfort/<id>/audio` | Écoute audio WAV du cliché HD haute résolution. |

---

## Journal des gênes et clichés HD

Pour corréler les ressentis physiques (nausées, vibrations, acouphènes, réveils nocturnes) avec les signatures acoustiques :
1. **Signalement instantané** : En 1 clic depuis le tableau de bord ou par `python -m bruittrack log-discomfort --level 4 --note "Vibration lit"`.
2. **Déclenchement IPC de cliché HD** : Le démon de capture sauvegarde immédiatement 30 secondes d'audio haute résolution non compressé (`snapshots/snap_<id>.npz` et `.wav`).
3. **Analyse spectrale dédiée** :
   - Profil spectral FFT 1D détaillé.
   - Diagnostic psychoacoustique automatique.
   - Exclusion systématique de l'artefact 50 Hz secteur sur le capteur piézo.

---

## Installation et déploiement (HP T620)

### 1. Installation automatisée Debian 13
```bash
sudo bash tools/install_hp.sh
```
Ce script idempotent installe les dépendances système (`python3-venv`, `libportaudio2`, `sox`, `sqlite3`), configure l'environnement `/opt/bruittrack`, génère le `config.toml` et active le service systemd.

### 2. Service systemd
Le fichier de service fourni dans [systemd/bruittrack.service](systemd/bruittrack.service) assure l'exécution continue et le redémarrage automatique en cas d'anomalie :
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now bruittrack
sudo systemctl status bruittrack
```

### 3. Maintenance et purge
- Rétention automatique : appliquée quotidiennement par le pipeline (événements et spectrogramme).
- Scripts SQL de nettoyage :
  ```bash
  # Purge des artefacts DC historiques
  sqlite3 data/bruittrack.db < scripts/purge_noise.sql

  # Purge des fréquences inférieures à min_event_hz
  sqlite3 data/bruittrack.db < scripts/purge_lowfreq.sql
  ```

---

## Configuration (`config.toml`)

Le fichier `config.toml` est l'**unique source de vérité** de l'application (zéro constante magique) :

```toml
[audio]
device = "M-Track Plus"     # Nom ou index ALSA
sample_rate = 48000
decimation = 48             # 48000 / 48 = 1000 Hz exact
block_size = 4800           # Blocs de 100 ms
channels = 2                # IN1: Micro Air, IN2: Piézo Structure

[dsp]
n_seg = 2048                # Résolution ~0.488 Hz / bin
noverlap = 1024             # 50 % de recouvrement Welch
n_buffer = 8192             # Tampon glissant 8.192 s
freq_max = 150.0            # Fréquence maximale d'analyse (Hz)
min_event_hz = 2.0          # Borne minimale fiable (Hz)
ema_alpha = 0.5             # Lissage exponentiel temporel
floor_history_len = 300     # 30 s de calcul du plancher médian
lp_cutoff_hz = 400.0        # Coupure filtre Butterworth anti-repliement

[detector]
threshold_db = 10.0         # Seuil d'émergence minimale
hysteresis_db = 3.0         # Marge de relâchement
debounce_ticks = 5          # Durée minimale de 0.5 s requise
max_duration_s = 30.0       # Découpe maximale d'un événement
warmup_ticks = 300          # 30 s d'échauffement initial
cluster_freq_tolerance_hz = 2.0

[storage]
db_path = "data/bruittrack.db"
exemplars_dir = "exemplars"
snapshots_dir = "snapshots"
batch_size = 50
batch_timeout_s = 30.0
record_exemplars = true
retention_days = 365

[spectrum]
enabled = true              # Spectrogramme continu
interval_s = 5.0            # Résolution temporelle
n_bands = 150               # Bandes de 1.0 Hz
retention_days = 365

[viz]
host = "127.0.0.1"
port = 8760
# auth_token = "secret"     # Protection optionnelle du triage
```

---

## Tests et qualité

Le projet dispose d'une suite de tests complète, 100 % déterministe et exécutable sans aucun matériel audio connecté (signaux synthétiques et SQLite `:memory:`) :

```bash
# Exécution de la suite complète pytest (185+ tests)
pytest

# Vérification du typage et linting ruff
ruff check .
ruff format --check .

# Vérification globale de la release
bash check.sh
```

---

## Documentation complémentaire

- [AGENTS.md](AGENTS.md) — Constitution du projet, budgets matériels et règles d'implémentation.
- [docs/decision-log.md](docs/decision-log.md) — Journal des décisions d'architecture et de conception.
- [docs/reference/gemini-waterfall.py](docs/reference/gemini-waterfall.py) — Script de référence initial du pipeline DSP.
- [systemd/bruittrack.service](systemd/bruittrack.service) — Configuration systemd pour exécution en démon 24/7.
