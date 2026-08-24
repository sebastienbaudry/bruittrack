# AUDIT2 — Audit du projet BruitTrack

**Date :** 25 août 2026
**Périmètre :** `src/bruittrack/` (~3 470 lignes Python), `tests/`, `tools/`, `scripts/`, `systemd/`, packaging (`pyproject.toml`), hygiène Git, documentation projet.
**Méthode :** audit en lecture seule (aucune modification du code). Vérifications exécutées : suite de tests, lint, inspection statique des modules, état Git.
**Note :** complète l'audit existant [`AUDIT.md`](AUDIT.md) (23/08/2026) ; se concentre sur l'état courant et les points non couverts ou apparus depuis.

---

## 1. Santé du projet (vérifié à la date de l'audit)

| Contrôle | Résultat |
|---|---|
| Suite de tests | ✅ **104 passed** en ~16 s (déterministes, sans matériel) |
| Ruff (lint) | ✅ vert |
| Gate `tools/check.sh` | ✅ `CHECK OK` (pytest + compile + CLI) |
| Dernier commit | `874d463` feat(viz): I55 — correction zoom HiDPI + suppression plafond 200 |
| Arbre Git | ⚠️ `PROGRESS.md` modifié non committé |

## 2. Architecture — synthèse

Pipeline conforme à la constitution `AGENTS.md` :

```
ALSA 48 kHz / 2 ch float32 (blocs 100 ms)
  → LP Butterworth fc=400 Hz (sosfilt, SosFilter DF2T)      [dsp.py]
  → décimation ×48 exacte → 1000 Hz
  → Welch 2048 pts, overlap 50 %, EMA α=0.5                 [dsp.py]
  → FloorTracker (médiane glissante 300 ticks)              [dsp.py]
  → EventDetector (seuil 10 dB, hystérésis 3 dB, debounce)  [events.py]
  → fingerprint 16 o versionné + ClusterIndex               [events.py]
  → EventStore SQLite WAL, lots 50 evt / 30 s               [store.py]
  → dashboard HTTP stdlib (ThreadingHTTPServer + canvas)    [viz.py]
```

Séparation des responsabilités propre : aucune dépendance cyclique capture/DSP/détection/stockage/présentation. Le module `legal.py` implémente les règles d'émergence CSP Art. R1336-7 (seuil diurne 5 dB / nocturne 3 dB + correctifs durée) avec tests dédiés (`tests/test_legal.py`).

### Points forts confirmés

- **Stockage** (`store.py`) : connexions SQLite éphémères par opération (jamais partagées entre threads), WAL + `synchronous=NORMAL` adaptés au SSD 16 Go, buffer d'écriture sous `RLock` avec justification du choix récursif documentée en commentaire, mode `:memory:` géré séparément pour les tests.
- **Fingerprint** : format struct versionné big-endian (`>BH5BBb6x`), classes de retard bornées ±20 ms, tolérance de matching explicite — évolutif sans casser le décodage ancien.
- **Observabilité embarquée** : métriques de lecture par bloc (`update_read_metrics`, blocs lents > 15 ms), sous-commandes `perf` et `stats --json`.
- **Tests** : 14 modules couvrant DSP, store, pipeline, API viz, zoom canvas, bugfixes régressifs ; harnais mock audio reproductible ; zéro dépendance matériel en CI.
- **Gate automatisée** : `tools/check.sh` (7 critères) + `zoom_check.sh` (8 critères I54/I55) — discipline de boucle efficace.

## 3. Constats et risques

### 🔴 Moyen — Hygiène du dépôt Git

- **`deploy.tar` (952 Ko) est tracké dans Git** alors que son contenu (build/deploy) n'a rien à faire dans l'historique source. Chaque clone paie ce poids, et toute mise à jour du tar double l'histoire.
- `output/pdf/*.pdf` (~180 Ko, audits PDF) également trackés : artefacts générés, pas des sources.
- Fichiers résidus dans l'arbre de travail : fichier vide `f`, dossier `~/`, `tmp/`, `dist/` (ignoré mais présent localement).
- **Recommandation** : `git rm --cached deploy.tar output/pdf/*.pdf` + ajout dans `.gitignore` ; supprimer `f` et `~/`.

### 🟠 Moyen — Posture réseau du serveur viz

- `VizConfig.host = "0.0.0.0"` par défaut : le dashboard (lecture DB + écriture triage) est exposé sur toutes les interfaces **sans aucune authentification**, avec `Access-Control-Allow-Origin: *` sur toutes les réponses JSON. Sur un LAN domestique c'est acceptable ; dès que la box expose le port ou en réseau partagé, n'importe qui peut re-trier les clusters (`POST /api/clusters/<id>/triage`).
- `do_POST` lit `Content-Length` **sans plafond** → un client peut demander une allocation mémoire arbitraire (DoS trivial). Idem `/api/events?limit=` accepte n'importe quelle valeur (le front demande désormais `limit=20000`, mais rien n'empêche `limit=10^9`).
- `ThreadingHTTPServer` sans limite de threads.
- **Recommandation** : défaut `host=127.0.0.1` (opt-in LAN via config), plafond `limit` (ex. ≤ 50 000) et `Content-Length` (ex. 64 Ko), voire un token simple en variable d'environnement.

### 🟠 Faible—Moyen — systemd vs budget temps réel

`systemd/bruittrack.service` : `Nice=-5`, `LimitRTPRIO=50`, `Restart=always` — bien. Mais **aucune garde-fou ressources** alors que le contrat projet est « CPU < 15 %, RAM < 150 Mo » :
- **Recommandation** : ajouter `MemoryMax=200M`, `CPUQuota=20 %`, et idéalement `WatchdogSec=` + notification sd_notify pour redémarrer un pipeline bloqué (aujourd'hui seul un crash déclenche le restart, pas un hang).

### 🟡 Faible — Maintenabilité de `viz.py`

973 lignes dont ~830 lignes de template HTML/JS embarqué dans une string Python. Les itérations I54/I55 (zoom) montrent la friction : chaque retouche JS passe par du Python, sans lint JS ni test hors navigateur (contourné via `node --check` et `zoom_repro.js`).
- **Recommandation** : extraire le template vers `src/bruittrack/static/dashboard.html` chargé au démarrage (toujours zéro dépendance), garder les substitutions `__FREQ_MAX__`/`__MIN_EVENT_HZ__`.

### 🟡 Faible — Silences d'exceptions assumés

`per-file-ignores = ["BLE001", "S110"]` sur tout `src/bruittrack/` : `except Exception` silencieux autorisés partout (et `log_message` neutralisé côté HTTP). Plusieurs handlers API renvoient `str(e)` brut au client (fuite de chemins internes potentielle, ex. `/api/exemplar`). Acceptable pour un outil mono-utilisateur, mais à restreindre si exposition réseau élargie.

### 🟡 Faible — Dérive documentation / gate

- `check.sh` (racine) critère C7 cherche `10 %CPU` dans le README, alors que `AGENTS.md` fixe le budget à **< 15 % CPU** — l'un des deux est obsolète.
- `PROGRESS.md` modifié non committé au moment de l'audit (I55 : déploiement pi-t620 restant, `zoom_check.sh` 7/8).
- README : exemple `--pid \u003cPID>` mal échappé dans le rendu Markdown (tableau Utilisation).

## 4. Couverture des exigences projet

| Exigence (AGENTS.md) | État |
|---|---|
| 2 canaux analysés ensemble (IN1 air / IN2 piézo) | ✅ pipeline stéréo + delay inter-canal dans le fingerprint |
| Device jamais codé en dur, forcé via config | ✅ `resolve_device_input` + `devices` CLI + tests dédiés |
| Aucun PCM brut persisté ; 1 extrait 256 ms par cluster | ✅ `_save_exemplar` (1er événement du cluster uniquement) |
| SQLite WAL, lots, index (t0)/(cluster), ~7 Mo/an | ✅ + rétention quotidienne + `prune` orphelins |
| Zéro GUI lourde ; viz = stdlib HTTP + canvas | ✅ (aux réserves §3 sur la posture réseau) |
| Budget CPU/RAM mesurable | ✅ `perf --pid` + `test_perf.py` ; garde-fous systemd absents (§3) |
| Conformité légale émergence R1336-7 | ✅ `legal.py` + tests (durées, correctifs, relevés invalides) |

## 5. Priorités recommandées

1. **Nettoyage Git** : retirer `deploy.tar` et les PDF de l'index ; purger `f`, `~/`, `tmp/` (30 min, risque nul).
2. **Durcissement viz** : host par défaut `127.0.0.1`, plafonds `limit`/`Content-Length` (2 h, faible risque).
3. **systemd** : `MemoryMax`/`CPUQuota` (+ watchdog si souhaité) pour aligner l'exécution sur le contrat budgétaire (30 min).
4. **Extraction du template HTML** de `viz.py` (à planifier entre deux itérations viz).
5. **Committer `PROGRESS.md`** après le redéploiement pi-t620 (fin de boucle I55).

## 6. Verdict global

Projet **sain et bien discipliné** : gate verte (104 tests + lint), architecture respectant strictement la constitution matérielle (T620, zéro dépendance UI, stockage minimal), historique de commits propre et incrémental. Les risques identifiés sont périphériques (hygiène dépôt, exposition réseau du dashboard, garde-fous systemd) et ne touchent ni la justesse DSP ni l'intégrité des données. Aucune anomalie bloquante.
