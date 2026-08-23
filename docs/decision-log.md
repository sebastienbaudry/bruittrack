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
- **Validation** : benchmarks blocs synthétiques : LP seul ≈ 9.0 ms/bloc avant → 0,13 ms/bloc après ; process_block ≈ 9,4 → 0,5 ms/bloc. 38 tests pytest après changement ; ruff absent de l'env locale (à refaire en CI).

## [2026-08-22] Corrections d'audit P1 — mémoire/DB (BUG-02, 03, 04, 07, 09)

- **Contexte** : audit BUGS.md ; cinq corrections mémoire/DB validées en une passe.
- **Décisions** : BUG-02 — `cmd_test` injecte `EventStore(db_path=":memory:")`, la base de production n'est plus pollué par les tests CLI. BUG-03 — `flush()` atomique : en cas d'exception SQLite, le tampon est restauré intégralement, aucun événement perdu (test 86166cf). BUG-04/07/09 — wiring vérifié et tests à jour : `apply_retention()` appelé au démarrage du service, normalisation Welch `Σw²` (et non `(Σw)²`), défaut `retention_days=365` conservé si `config=None` (évent. 03c32aa).
- **Validation** : 38 pytest pass ; statuts BUGS.md mis à jour.

## [2026-08-22] Concurrency SQLite — connexion par opération + verrou (BUG-01, 08)

- **Contexte** : `ThreadingHTTPServer` viz partageant la connexion SQLite du process capture potentiellement de façon non thread-safe ; `EventStore._buffer` en accès partagé.
- **Décision** : `EventStore` ouvre un `sqlite3.connect()` par opération (pas cher : WAL + NFS-free) au lieu d'une connexion partagée ; `_init_db` unique au démarrage ; `threading.Lock` sur `_buffer` et sur la queue d'écriture.
- **Validation** : test régression écrivants/lecteurs concurrents (1d01e28) ; suite complète pass (dfd2d08).

## [2026-08-22] Signe de corrélation croisée inter-canaux (BUG-06)

- **Décision** : convention `off_ms > 0` = canal G (air) précède canal D (piézo), aligne la docstring avec l'implémentation ; tests de signe ajoutés (4e36373).
- **Pourquoi** : l'anomalie détectée par le piézo B *après* qu'elle a franchi l'air est le cas physique dominant avec cette géométrie.

## [2026-08-22] Refactor filtre LP — suppression `set_initial_state`, tests d'équivalence (BUG-11)

- **Décision** : méthode morte du fallback scalaire supprimée ; l'état inter-blocs est porté uniquement par `scipy` (`zi→zf`), testé contre la voie scalaire référence pour garantir l'équivalence numérique et la continuité d'état entre blocs (b3e7627).

## [2026-08-22] Format exemplaire — WAV int16 (BUG-05)

- **Contexte** : `stats --play` renvoyait un dump float16 brut → régression son/sox illisible.
- **Décision** : helper de conversion float32→int16 PCM 16 bits stéréo dans un WAV header minimum (44 o) ; exemplaire rejoué directe par `aplay`/`sox` (d498a5f).

## [2026-08-22] MockAudioCapture déterministe et synchronisé temps réel (BUG-12)

- **Décision** : seed fixe par défaut + cadence d'injection `time.sleep` sur une horloge monotone réaliste au lieu du temps wall ; les tests E2E ne dépendent plus de l'ordre d'arrivée des données (db15b01).

## [2026-08-22] Validation complète config (BUG-10)

- **Décision** : `Config.validate()` après chargement du TOML : intervalle [0..98], seuil/hystérésis strictement posés, device chiffrable, etc. ; erreurs CLI lisibles en français au lieu d'un échec tardif opaque (7eb3d88).

## [2026-08-22] Détection de décalage inter-canaux par FFT (perf)

- **Contexte** : la corrélation croisée directe G/D dans le domaine temporel coûtait ≈ 5,2 ms/événement sur T620.
- **Décision** : `compute_channel_delay_ms` passe par `rfft` float32 N=1024 et produit de convolutions spectrales ; fenêtre de lags ± 8 conservée. Gain mesuré < 0,1 ms/événement ; convention de signe inchangé (b3e7627).

## [2026-08-22] FloorTracker transposé (bins × temps) — perf

- **Contexte** : médiane mobile par bin sur 300 ticks ; l'ancienne disposition `(temps × bins)` rendait la sélect par ligne discontinue en mémoire et coûteuse.
- **Décision** : storage `float32[99, 300]`, glissement par réécriture de décalage vectorisé, `np.partition(..., k)[:, k]` pour la médiane (≈ 3x vs `np.median`) ; seed du 1er tick par `[:, :] = psd[:, None]`. Mesuré T620 : 0,61 → 0,58 ms/tick — seuil franchi, chemin fermé (47191c6).

## [2026-08-22] Budget persistance — WAL, lots 30 s / 50 événements, index (t0, cluster)

- **Décision** : `journal_mode=WAL` + `synchronous=NORMAL`, écriture groupée mémoire avant INSERT batch, index b-tree `(t0)` et `(cluster)` ; projection ≈ 7 Mo/an à 1 événement/mn, bien sous le budget SSD de la T620 (dfdfd — convention reprise du design v0.1.0, formalisée après l'audit BUG-03/04).

## [2026-08-22] Telemetrie de lecture capture — blocs lents ALSA (M6)

- **Contexte** : un bloc PortAudio en retard (surcharge CPU, I/O USB) demeurait invisible ; la seule consequence etait un silence DSP progressif.
- **Decision** : temps de lecture par bloc mesure en µs (`last_read_us`) par `update_read_metrics()` — callback PortAudio pour `AudioCapture`, generation simulée (+ `stall_s` injectable) pour `MockAudioCapture`. Seuils nommes `SLOW_READ_US = 15_000` et `SLOW_BLOCK_STREAK = 3` ; `Engine._check_capture_health()` emet un warning apres 3 blocs lents consecutifs puis remet le compteur a zero (anti-spam). Pas de dependance, ~0 cout CPU (2 `time.monotonic()` par bloc) — budget T620 preserve (5020110).

## [2026-08-23] Commande `bruittrack perf` — gate de budget M9 en CLI

- **Contexte** : le respect des budgets T620 (M9, GOAL.md) exigeait une preuve automatisée et machine-readable ; jusqu'ici elle passait par `ps` manuel + comparaison à la main.
- **Décision** : sous-commande `perf --pid <PID>` (défaut : processus courant). Deux lectures de `/proc/<pid>/stat` espacées de `PERF_SAMPLE_SECONDS = 15 s` → %CPU (diff utime+stime / CLOCK_TICKS) et RSS (field 24, × page size). Seuils nommés `CPU_MAX_PCT = 15`, `RSS_MAX_KB = 153_600` — zéro magic number. Codes sortie machine : **0** « CONFORME », **1** PID illisible / non-Linux (compteur gelé), **2** « NON-CONFORME ». Sur prod, PID canonique = `systemctl show -p MainPID --value bruittrack`.
- **Justification** : 15 s de fenêtre lisse la variabilité DSP sans allonger le gate ; % dérivés d'entiers /proc (pas de `psutil`, pas de dépendance). Conformes au budget process unique (~48k it/s). Preuves prod : it.64 CPU 12.9 % RC=0 ; it.67 CPU 12.6 % / RSS 123.5 Mo RC=0 (uptime > 10 h) ; couvert par 4 tests unitaires fake-/proc (`tests/test_perf.py`, I5).

## [2026-08-24] Clusters triage sans event visibles dans /api/clusters (I17)

- **Contexte** : `set_cluster_triage()` (`store.py`) cree la ligne `clusters` via UPSERT, meme avant le 1er event du cluster ; mais `get_clusters_summary()` agregait depuis `events` (JOIN gauche), donc un cluster etiquete "a venir" etait invisible dans `GET /api/clusters` et la CLI.
- **Decision** : 2eme requete en union logique dans Python — clusters sans aucun event renvoyes avec `event_count=0`, `first_seen`/`last_seen=NULL`, stats a zero ; pas de schema ni d'ordre change.
- **Justification** : coherence triage/affichage sans nouvelle table (regle budget) ; cout = 1 `NOT EXISTS` par lecture (WAL, table faible volume ~lignes/an) — negligeable T620. Test : `tests/test_store.py::test_clusters_summary_includes_triage_orphans`.

## [2026-08-24] Événements fantômes à 0 Hz (DC)

- Contexte : beaucoup d'événements `bin_i=0` (0 Hz) en base sur le serveur, l'affichage web étant fidèle. Cause : `argmax` de la détection porte sur les bins 0..98 ; le bin 0 (moyenne DC) monte au-dessus du floor à tout transient de niveau et claque un pseudo-événement.
- Décision : la recherche du pic est bornée aux bins 1..98 (`events.py`, `on_tick`) ; le bin DC ne déclenche plus jamais.
- Justification : 0 Hz correspond à une dérive de niveau, pas à un bruit périodique ; spec : bins utiles 0–48 Hz mais le pic DC n'apporte aucune info discriminante. Test regression `test_event_detector_ignores_dc_bin`.
