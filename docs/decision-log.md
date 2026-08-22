# Journal des Décisions d'Architecture (Decision Log)

## [2026-08-21] Initialisation de l'architecture BruitTrack (v0.1.0)

### Contexte & Contraintes
- **Matériel cible** : Thin client HP T620 (x86 ~1.5 GHz, 4 Go RAM, 16 Go SSD, Debian 13).
- **Objectif** : Surveillance 24/7 de bruits et infrasons récurrents (0–48 Hz) sur 2 canaux complémentaires (micro aérien IN1 + capteur structurel/piézo IN2).
- **Budget** : CPU stable < 10 %, RAM < 150 Mo, stockage minimal (~7 Mo/an).

### Décisions Validées

1. **Pipeline DSP et Fréquences d'échantillonnage** :
   - Capture ALSA à 48 000 Hz stéréo.
   - Filtre passe-bas anti-repliement Butterworth d'ordre 8 (4 biquads en cascade, $f_c = 400\text{ Hz}$).
   - Implémentation du filtre IIR en NumPy pur sans dépendance externe obligatoire (`scipy`).
   - Décimation exacte d'un facteur 48 ($\frac{48000}{48} = 1000\text{ Hz}$).
   - Cadence temporelle de 100 ms par bloc (4800 échantillons bruts $\to$ 100 échantillons basse fréquence).

2. **Analyse Spectrale & Estimation du Plancher de Bruit** :
   - Méthode de Welch sur tampon glissant de 8192 points (7 sous-segments de 2048 points avec recouvrement de 50 %, fenêtre de Hann).
   - Résolution spectrale : $\Delta f = \frac{1000}{2048} \approx 0.48828\text{ Hz/bin}$. Bins 0 à 98 pour couvrir la bande 0–48 Hz.
   - Lissage exponentiel (EMA avec $\alpha = 0.5$) inter-blocs.
   - Estimation dynamique du plancher de bruit par médiane glissante sur 300 blocs (30 s).
   - Période d'échauffement initial (warmup) de 300 blocs avant émission d'événements.

3. **Détection & Modèle d'Empreinte (Fingerprint)** :
   - Détection par émergence ($PSD_{\text{ema}} - Floor \ge 10\text{ dB}$) avec hystérésis de 3 dB et anti-rebond (debounce) de 5 blocs (0.5 s).
   - Découpage automatique des événements continus à 30 s maximum.
   - Empreinte acoustique compacte de 16 octets (`version: 1o | bin_peak: 2o | 5x voisines quantifiées: 5o | canal dominant: 1o | classe délai: 1o | rés.: 6o`).
   - Calcul du décalage temporel inter-canaux (cross-correlation $\pm 8\text{ ms}$).
   - Stockage audio exemplaire (256 ms @ 1 kHz en `float16`, ~1 Ko) uniquement pour la première occurrence d'un nouveau cluster.

4. **Persistance & Rétention** :
   - SQLite unique (`data/bruittrack.db`) configuré en `journal_mode = WAL` et `synchronous = NORMAL`.
   - Écriture des événements groupée par lots en mémoire (tampon de 50 événements ou 30 secondes).
   - Indexation B-tree sur `(t0)` et `(cluster)`.
   - Politique de rétention configurable (`retention_days`).

5. **Visualisation & Interface Web** :
   - Mini-serveur web intégré en Python standard (`http.server.ThreadingHTTPServer`).
   - Aucune dépendance frontend externe ni CDN (HTML5 Canvas + Vanilla JS).
   - Séparation stricte des processus de capture et de consultation.

## [2026-08-22] Filtre LP : voie rapide `scipy.signal.sosfilt` (1er ajout autorisé)

- **Contexte** : sur la cible HP T620 (x86 ~1,5 GHz), la boucle scalaire pure-Python de `SosFilter.filter()` (48 000 échantillons/s × 2 ch × 4 sections ≈ 384 000 itérations/s) consomme ~55–60 % d'un noyau en régime permanent, au lieu du budget < 10 %. Le reste du chemin (décimation, Welch 2048 pts × 7 × 2) est négligeable (< 1 ms/s localement).
- **Décision** : passage par `scipy.signal.sosfilt` (C vectorisée), un appel par canal/bloc de 4800 échantillons, avec transfert d'état `zi → zf` entre blocs pour préserver la continuité du filtre. Éligible directement au budget « 1er ajout autorisé » défini en amont, car c'est l'unique dépendance additionnelle.
- **Comportement** : si `scipy` est absent, fallback transparent sur la boucle scalaire numpy (testable sans scipy).
- **Validation** : benchmarks blocs synthétiques (20 warmups + 15 mesures) : LP seul ≈ 9,3 ms/bloc avant / < 0,5 ms/bloc après. 38 tests pytest avant/après ; ruff clean.
