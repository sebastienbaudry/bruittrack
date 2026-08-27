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
## [2026-08-24] Conformite legale sur les events: flag bit3 + legal.py (CSP R1336-7)

- Contexte : la spec exige de ne considerer que les events depassant l emergence autorisee par la loi ; aucun event n etait marqua de ce critere, store/viz ne pouvaient pas filter.
- Decision : module bruittrack/legal.py (periode diurne 07h00-21h59 base 5 dB, nocturne base 3 dB, correctif de duree +6 au plus fort) et EventDetector._compute_flags() : bit3 = FLAG_OVER_LEGAL pose si max(lvl_g, lvl_d) depasse emergence_limit(evaluee a l heure locale du t0 ; tz naive volontaire, noqa DTZ006).
- Justification : evaluation au close de l event (1 comparaison), zero nouvelle table ; bit3 complete les bits 0-2 sans changer le schema. Limitation documentee : duree_cumulee approximee par la duree de l event (au plus court, donc au correctif maximal +6, choix conservateur). Tests : tests/test_legal.py (6) + TestComputeFlags (2).

## [2026-08-25] Bornes de detection min_event_hz / freq_max parametriques (I35)

- Contexte : la spec fixe les bornes de detection des events aux bins freq >= 2 Hz (le materiel ne resout pas de facon fiable sous 2 Hz ; le bin DC reste exclu) jusqu a freq_max = 150 Hz (> 150 Hz hors perimetre d analyse T620). Avant, freq_max etait un parametre DSP (bins calcules) decoupe du threshold de detection.
- Decision : DspConfig min_event_hz = 2.0 (inferieure borne) et freq_max = 150.0 (superieure), propagation via pipeline.py vers EventDetector (min_bin = ceil(min_event_hz / df) ; fen etre de recherche tronquee a max_event_hz / df + 1). Validation ValueError si min_event_hz < 1 ou >= freq_max. Exemple config met a jour.
- Justification : un seul fichier source de verite (config.toml), zero magic numbers dans events.py ; le calcul des bins Welch reste borne par freq_max pour le budget (n_bins ~ 304). Tests : tests/test_band.py (3, synthetiques).
## [2026-08-26] Tolerance de clustering parametrable cluster_freq_tolerance_hz (I44)

- Contexte : la regle du clustering imposait un seuil dur |Δbin peak| ≤ 1 (defaut fingerprints_match) ; la spec mentionnait ±2 bins. En dessous d un demi-bin la resolution est ~0,49 Hz/bin (48 kHz / 2^16), donc une tolerance expresse en bins etait opaque et non ajustable au terrain.
- Decision : nouvelle cle TOML [detector] cluster_freq_tolerance_hz (defaut 0.5 Hz) dans DetectorConfig ; EventDetector la convertit en bins : max_bin_delta = max(0, round(tol / bin_resolution_hz)) et la transmet a ClusterIndex, qui l applique dans fingerprints_match(). Zero magic number : le seul entier reste le parametre d API.
- Effet retour : les clusters existants ne sont PAS re-fusionnes (representants charges en memoire au demarrage ; seule la creation/matching des NOUVEAUX events suit la tolerance configuree). Des clusters proches crees avec l ancienne regle resteront separes jusqu a retiage manuel via l API.
- Justification : operator ajuste la sensibilite (ex. sources mecaniques qui chandent le pic de ±0,5 a 1 Hz) sans recompilation ; defaut 0.5 Hz ≈ 1 bin preserve le comportement existant. Tests : tests/test_events.py (match_max_bin_delta, detector_cluster_tolerance_hz, cluster_index_max_bin_delta) + config.toml.example.

## [2026-08-24] Lecture web net et axe Y dynamique : I47-I50 (viz)

- Contexte : echelle Y du chronogramme inlisible (pixels physiques 1:1, canvas 260 px CSS rendus flous sur ecrans HiDPI) ; axe borne a une constante de 200 Hz independante des bornes de configuration (min_event_hz / freq_max) et des filtres client.
- Decision : le canvas est dessine en pixels physiques via ctx.setTransform(dpr,0,0,dpr,0,0) (TL_CKVW = CSS 1000 x dpr, largeur hors ratio 48 kHz), les coordonnees JS restent en px CSS ; l echelle Y va de 0 a _fyMax() = max(freq_max du filtres client ou 175 ou freq_max DSP), plafonnee a 200 et reglee sur un step arrondi (nice steps 0.5/1/2/5/10/20, ~5-6 divisions) via newHzStep (I47-I48). Ajouts d ergonomie : zoom brush horizontal persistant (I39), chip de frequence sous le curseur #freqTip via inverse de yOfFreq (I49, separe du tooltip I40 pour ne pas rompre son mode sticky) et crosshair horizontal pointille en rAF sur les dernieres donnees dessinees (I50, variable hoverYpx + cache tlLastEvts ; guard anti-reentrance dans hideEvtTip()).
- Justification : zero dependance (JS stdlib), budget CPU preserve (redraw throttle par requestAnimationFrame, pas de refetch) ; la dynamique de l axe suit les parametres reels du systeme au lieu d une valeur duree. Verifie : ruff + node --check + 100 tests ; deploy pi-t620 (bruittrack.service + bruittrack-viz.service port 8760, wheel PEP427).

## [2026-08-27] Zoom/dézoom interactif sur les 2 axes du chronogramme (I54)
- Decision : molette sur le canvas = zoom synchronisé des deux axes centré curseur (`axZoom(`, facteur ±1.3/arret, temps ancré au t sous le curseur et fréquence ancrée sous le curseur Y) ; Ctrl+glisser vertical translate l'axe fréquence seul (`panFreqBy(`), drag normal horizontal = brush I39 inchangé ; fenêtrage des données par rechargement `/api/events?since=&limit=20000` + merge dédup par id dès que la vue X s'étend avant `dataSince` (`fetchWindow(`) — plus de `?limit=200` figé ; reset double-clic / Échap / badge re-cliquable `zoomBadge` (re-passe aux fenêtres boutons + [0, FREQ_MAX]) ; graduations Y recalculées sur `[fLo,fHi]` via niceHzStep ; tableau plafonné 500 lignes affichées (`renderTableRow(`). Clamps : temps span ∈ [10 s, 90 j] borné par l'étendue chargée, fréquence span ≥ 2 Hz et [fLo,fHi] ⊂ [0, FREQ_MAX], indépendants par axe.
- Justification : zero dépendance (JS stdlib), aucune nouvelle route API (`store.get_events(since=)` préexistant) ; contrat brushing I39 et marqueurs `test_viz_api.py` préservés en l'état. Vérifié : `tools/zoom_check.sh` exit 0 (Z1–Z6), `tools/check.sh` verte 104 tests, ruff propre.

- I58 (2026-07-21) Synchronisation stricte tableau / graphe : derniere passe drawTimeline() calcule `lastVisible` = t0 dans la fenetre ∩ freqView ∩ canaux affiches (chOk) ; le dessin ne montre que ce set (visId). drawTimelineFull() = drawTimeline(filterEvents(...)) + syncEventsToTable() (tri t0 desc, plafond 500 deja en place) ; applyFilters, toggleChannel et refreshAll convergent vers ce chemin. Une modification de fenetre (brush, wheel, boutons, filtres, canaux) met automatiquement le tableau a jour avec le meme ensemble que le chronogramme.

## [2026-08-27] Correctifs zoom viz — source brute, tri asc, interactions (I59)
- Contexte : le zoom ne se comporte pas correctement en usage réel. Diagnostic : (1) drawTimelineFull() réinjectait lastVisible (vue filtrée I58) comme ENTRÉE du rendu → après un zoom avant, tout dézoom/changement de fenêtre/filtre laissait définitivement les points hors de la vue précédente hors graphe ET tableau, polls 10 s compris ; (2) hiSpan du dézoom calculé sur lastVisible au lieu des données brutes → dézoom saccadé/bloqué à ~1 h autour d'un groupe dense ; (3) fetchWindow en tri DESC + watermark winCursorT posé même sans extension → trous de données si > 20000 événements plus récents que la zone visée ; (4) Ctrl+glisser (pan fréquence) déclenchait aussi le brush temps ; (5) wheel passive:true sans preventDefault → scroll page / zoom navigateur concurrents.
- Decision : drawTimelineFull(shouldSyncTable=true) filtre TOUJOURS depuis eventsData (lastVisible redevient une sortie, utilisée pour tooltips/table uniquement) ; redraws cosmétiques (survol I50, pan Y, brush en cours) passent shouldSyncTable=false pour supprimer le rebuild 500 lignes par mousemove, sync complète au relâchement ; store.get_events(order="asc"|"desc", ValueError sinon) exposé via /api/events?order= et utilisé par fetchWindow (?order=asc → chargement continu depuis sinceT, winCursorT redevient un plancher fiable) ; brush mousedown ignore Ctrl+glisser et boutons ≠ 0 ; wheel listener passive:false + ev.preventDefault() dans la zone utile ; tolérance float EPSF=0,01 Hz pour le retour propre de freqView à null.
- Justification : zéro dépendance nouvelle, pas de route ajoutée (paramètre order sur route existante) ; contrat brushing I39 et sync I58 préservés (le tableau affiche toujours strictement le set rendu). Vérifié : node --check, tools/zoom_repro.js (ancrage molette OK + nouveau check I59 « SOURCE BRUTE » qui échoue sur HEAD^), tools/zoom_check.sh 7/8 core (B2 déploiement pi-t620 reporté), tools/check.sh verte 113 tests, ruff propre.

## [2026-08-27] Molette = zoom axe Y seul, centré curseur (I61)
- Contexte : depuis I54 la molette zoomait les 2 axes simultanément ; l'usage réel demande un zoom fréquence dédié (le temps se règle déjà par brushing I39 et boutons de fenêtre).
- Decision : axZoom() ne touche plus que l'axe Y — ancrage = fréquence sous le curseur (yToFreq), facteur ±1.3/crant, span ≥ 2 Hz, [fLo,fHi] ⊂ [0, FREQ_MAX], retour vue pleine via EPSF inchangé ; suppression du zoom temps ancré (zoomTimeAt/yToAnchorTime devenus morts) et du refreshWindowed() dans la molette (plus aucun changement temporel → pas de refetch) ; redraw cosmétique drawTimelineFull(false) immédiat (pattern I59, sync tableau au cycle complet). preventDefault non-passif I59 conservé.
- Justification : zéro dépendance, contrats I58 (sync tableau) et I59 (source brute) préservés. Vérifié : node --check, tools/zoom_repro.js réécrit I61 (span X strictement constant + |Δf curseur| < 0,1 Hz sur 6 zoom + 14 dézoom + retour vue pleine [0,150]), gate check.sh verte.

## [2026-08-27] I61b — dérive d'ancrage molette au plancher 2 Hz
- Contexte : retour terrain « la molette zoom toujours vers le haut, zoom non centré sur le curseur ». Repro sandbox MY=200/230 : à chaque crant de zoom-in une fois le span minimal atteint, le clamp `nLo=c-1; nHi=c+1` recentrait sur le centre GÉOMÉTRIQUE de la fenêtre au lieu de l'ancre → dérive cumulative de la vue vers le centre (donc vers le haut quand le curseur est bas).
- Decision : clamp span min réparti autour de l'ancre — frac = position relative du curseur dans la vue courante, nLo = anchF − 2·frac, nHi = anchF + 2·(1−frac). L'ancre reste exacte à tous les crants ; seuls les bords [0, FREQ_MAX] peuvent encore décaler (nécessaire).
- Justification : un seul point de calcul, zéro dépendance. Vérifié : repro sandbox ancres exactes sur MY∈{40,60,130,200,230} ×10 crants ; tools/zoom_repro.js section I61b (ancre 143,2 Hz conservée au plancher) qui échoue sur le code précédent.

## [2026-08-27] I61c — yToFreq était le miroir vertical de yOfFreq
- Contexte : retour terrain « curseur en haut → la zone basse s'étire, curseur en bas → la zone haute s'étire ». Diagnostic : l'inverse px→Hz de yOfFreq est f = fb[0] + ((h−20−y)/(h−40))·span ; le code calculait fb[1] − (...)·span → ancre molette systématiquement réfléchie verticalement (curseur haut = ancre basse). Le repro I61b dupliquait la même formule fausse et validait donc l'erreur.
- Decision : yToFreq corrigé en inverse exact de yOfFreq ; zoom_repro.js recalculé via l'inverse exact (fUnderCursor/fStar/fCur) au lieu de dupliquer la formule du code.
- Justification : lecture Hz du survol (I54) et ancre molette partagent la fonction corrigée. Vérifié : zoom_repro.js passe sur le fix et ÉCHOUE (11 violations) sur le code précédent ; ruff, 113 tests, zoom_check core verts.

## [2026-08-27] I62 — échelle X : heure de Paris, jour affiché, format 24 h
- Contexte : la graduation X était formatée avec timeZone:'UTC' explicite (décalage vs Paris), sans le jour ; le badge de zoom utilisait toISOString() (UTC) et formatDate() l'heure machine cliente (12 h possible).
- Decision : constante TZ_VIZ='Europe/Paris' partagée ; crants horaires en 24 h explicite (hourCycle:'h23') + étiquette date (jj/mm) au-dessus de l'heure dès que le jour calendaire du crant change ; pas max corrigé 144000 s (40 h !) -> 86400 s (24 h) ; pas >= 6 h ancré sur minuit PARIS via parisMidnightBefore (t - secondes écoulées depuis minuit local, zéro dépendance) sinon le changement de jour tomberait à 02:00 à l'écran ; badge de vue et formatDate(tableau/tooltips) alignés Paris 24 h.
- Justification : Intl stdlib (zéro dépendance), lecture directe des relevés pour l'exploitation. Vérifié en sandbox : pas 2 h (14 h de span), pas 24 h ancré minuit Paris sur 3 jours, fenêtre démarrant pile à minuit (pas 6 h), formatDate 24 h.
- I62b (2026-08-27) : l'étiquette date en rangée séparée (h-21) empiétait sur le tracé et était masquée par les points ; elle est INLINÉE sur la ligne des heures (« jj/mm hh:mm ») uniquement au changement de jour — plus aucun texte dans la zone du graphe.

## [2026-02] I63 — Historique spectre : table `spectrum` + heatmap viz
- Contexte : un signal infra quasi permanent est absorbé par le floor (médiane glissante 300 ticks) → émergence ≈ 0 → jamais d'événement → invisible dans la viz qui ne lit que `events`. Besoin : rendre visible la présence continue (ex. hum ~50 Hz).
- Decision : nouvelle table `spectrum` (t0, dur, n_bands, data BLOB) alimentée par `SpectrumAggregator` (dsp.py) : bandes log-spacées sur [min_event_hz..freq_max] (bords e_i = min·(max/min)^(i/n), formule dupliquée côté client JS pour l'échelle Y), niveau par bande = énergie agrégée 10·log10(Σ10^(dB/10)) via np.add.reduceat sur bins triés (bande sans bin → -inf → q=0), accumulation min/max par bande et canal sur interval_s (défaut 60 s), quantification uint8 q=clip(round((db−db_min)/db_range·255)) ; blob = n_bands×[min_g,max_g,min_d,max_d] (96 o pour 24 bandes). Bin DC exclu (affecté hors plage, cf. décision DC 2026-08-24). Écriture dans le lot existant (buffer dédié, flush même transaction/condition). Rétention dédiée `spectrum.retention_days` indépendante des événements, appliquée au même cycle quotidien. Viz : endpoint `/api/spectrum?since&until&limit` (data base64), canvas heatmap sous la timeline partageant tlScale (même axe X), colormap noir→bleu→cyan→jaune, respect des toggles de canaux, bouton « Spectre ». Config `[spectrum]` (enabled/interval_s/n_bands/db_min/db_range/retention_days).
- Coût mesuré : CPU ≈ qq µs/tick (reduceat 308 bins ×2 ch) ; RAM buffer 24×4 float64 ×3000 ticks < 200 ko ; disque 1 ligne/min ≈ 70 o ≈ 37 Mo/an — levée d'écriture validée contre terrain réel : 5,9 Go libres sur /dev/sda2 (df hpdebian, marge ×100) ; `retention_days` conservé en garde-fou embarqué.
- Justification : zéro dépendance nouvelle (numpy pur, stdlib HTTP) ; la détection/clustering restent inchangés — c'est de la visualisation complémentaire, pas une voie de détection. Tests : tests/test_spectrum.py (23 cas : agrégateur, store roundtrip/rétention/filtres, config, API) + intégration pipeline→store vérifiée.
- I63b (retour terrain 1re ligne réelle) : bande log vide (sous la résolution bin, bas de bande) produisait min=255/max=0 (±inf quantifiés) → `_quantize` mappe maintenant tout non-fini vers q=0. Défauts `db_min/db_range` recalés −140/160 → **−60/120** : les niveaux PSD mesurés sur hpdebian (ambiant ≈ −35..−15 dB par bande d'énergie) tombaient à q≈170-215 avec l'ancienne fenêtre (contraste écrasé en haut de l'échelle) ; la nouvelle fenêtre [−60,+60] centre l'ambiant au tiers bas et garde la tête pour les événements. Config distante pi-t620 mise à jour en conséquence.

## [2026-02] I64 — Enregistrement des exemplaires optionnel ([storage].record_exemplars)
- Contexte : chaque nouveau cluster stocke un exemplaire ex_<cluster>.raw (~512 o, 256 ms @1 kHz f16) ; sur le T620 l'opérateur veut pouvoir les désactiver et nettoyer l'affichage (audio player).
- Décision : record_exemplars = true sous [storage] (source unique de vérité, zéro nouvelle section), plumbé via pipeline vers EventDetector.__init__(record_exemplars=...). Si false : aucun fichier écrit ET bit 2 FLAG_EXEMPLAR non posé — cohérence plateau/DB : le flag implique l'existence du fichier. prune_orphaned_exemplars() et replay CLI invariants (tolèrent l'absence de fichier).
- Viz : placeholder __EXEMPLARS_ENABLED__ remplacé côté serveur dans HTML_DASHBOARD (const EXEMPLARS_ENABLED = true/false) ; la colonne Audio affiche un tiret quand désactivé. L'endpoint /api/exemplar/ est conservé (404 si fichier absent) : réactiver le flag restaure le player sans code. Alternative rejetée : suppression inconditionnelle du player (perte de la reversibilité par config).
- Tests : test_record_exemplars_toggle (fichier + bit FLAG_EXEMPLAR selon flag, 2 cas) et test_player_html_gated_by_config (const injectée true/false + gating runtime present, 2 cas) ; suite complète 141 verte.
- I64b (supplement) : quand record_exemplars=false, pas seulement la cellule mais toute la colonne Audio est masquee : th id=audioTh est retire par le JS demarrage (aucune variable serveur supplementaire), la cellule td player est supprimee du template de ligne et l'etat vide du tableau bascule sur un colspan dynamique. Raison : une colonne entierement a tirets n'apportait rien visuellement dans l'etat desactive.
## I64c : spectre / heatmap — axe Y et bandes en échelle linéaire

**Contexte.** Le panneau temps réel utilisait des bandes log-spacées côté serveur
(`SpectrumAggregator.band_edges`, progression géométrique) et un axe Y log en JS
(`yOfHz`/`yOfHz2`/`specBandEdge`) : les basses fréquences dominaient visuellement
tandis que la timeline voisine (I57f) est linéaire.
Décision : uniformité en linéaire des deux côtés du serveur.

**Impact.**
- `dsp.py` : `band_edges` retourne `min_hz + i*(max_hz-min_hz)/n_bands` ; docstring actualisées.
  L'affectation bin→bande par `searchsorted` est inchangée.
- JS dashboard : `specBandEdge(i)`, `yOfHz`, `yOfHz2` en linéaire avec clamp
  à [min_event_hz, freq_max] (formule identique au serveur) ; étiquettes Hz par
  pas « nice » (`niceHzStep((freq_max-min)/4)` → ticks 50/100/150 par défaut).
- À défaut, ~12,7 bins par bande sur [2 ; 150] Hz — pas de bande vide.
- `tests/test_spectrum.py` : `test_band_edges_log_spaced` → `test_band_edges_linear_spaced`
  (diffs constants). Gate : 141 pass, ruff net.
 I64d — `/api/spectrum` sert `edges` : les n_bands+1 bords lineaires (min_event_hz + i*step, arrondis 1 mHz), meme formule que SpectrumAggregator.band_edges ; le client peut consommer l'echelle serveur sans recalcul. Test API : diffs constantes > 0 + bornes exactes.

### I71 — Chronogramme : bulles colorées par cluster (inversion de I67)
- Décision : le draw du timeline canvas repasse sur `getClusterColor(e.cluster)` ;
  `getBinColor` et toute référence sont retirés de viz.py. Motif opérateur :
  même couleur = même famille de bruit récurrent, cohérent avec les badges
  events/clusters qui utilisaient déjà la palette par cluster.
- Palette (JS servi, vérifiée numériquement `tools/color_check.py` +
  `tests/test_viz_api.py`) : hue angle d'or `(id*137.5)%360`, sat 85 %, clarté
  [45,68] alternée par bloc de 6 ids ; props numériques ids 1..29 : adjacents
  |Δid|=1 dist RGB ≥ 0.13, fenêtre |Δid|≤6 dist ≥ 0.05 ; cluster NULL → #94a3b8.
- Vérification cible : `tools/install_verify_marker.sh <id>` ou sur pi-t620 :
  `grep -c getClusterColor /opt/bruittrack/src/bruittrack/viz.py` ≥ 4 ET
  `grep -c getBinColor .../viz.py` = 0 ; `bash tools/cluster_color_check.sh`
  → SCORE 10/10 exit 0 ; suite locale 149 tests verts.

## [2026-09-14] Invariance au décalage de pic dans le matching de fingerprint

- Contexte : le matching imposait Δbin(peak)=0 strict avec distance L1 ≤ 2 sur les 5 briques. Quand un pic saturé saute d'un bin, la distance des briques voisines dépasse le seuil → fragmentation en clusters quasi-doublons (constatée sur la base pi-t620).
- Décision : `fingerprints_match(fp_a, fp_b, max_bin_delta, l1_max=2)` — Δbin=0 : L1(briques) ≤ 2 ; Δbin ∈ 1..max_bin_delta : meilleur alignement de profil sur δ ∈ {−1,0,+1} sur ≥ 3/5 briokes non nulles, distance normalisée |a−b|/max(1,max(a,b)) cumulée ≤ l1_max (insensible à la saturation d'échelle).
- Justification : corrige la fragmentation sans élargir l'espace des clusters stables ; delta strict conservé en Δbin=0. Preuves : `tools/clusters_check.py --demo` (pic+1 bin → 1 cluster), `tests/test_events.py::test_i59_peak_wobble_shift_invariance`, check.sh verte 151 tests.

## [2026-09-14] Fusion post-hoc des quasi-doublons de clusters (I59b)

- Contexte : les clusters créés avant l'invariance de pic restaient séparés ; la recoloration par cluster exige un ID unique par famille (exemplaires indexés ex_<cluster>_*.raw, filtre et légende du dashboard).
- Décision : `EventStore.merge_quasi_duplicate_clusters(max_bin_delta, exemplars_dir)` — comparaison par paires des fp representatives à chargement (seul coût de démarrage), canonical = plus petit ID survivant (stable entre redémarrages), UPDATE cluster en COMMIT unique `merge_clusters`, consolidation exemplaires `ex_<fusi>_<eid>.raw` → `canonical` avec vérification intégrité DB (`flags & FLAG_EXEMPLAR`). Appelée dans `Engine.__init__` AVANT `_load_cluster_index()`.
- Justification : id canonical unique, zéro dépendance, coût N² sur le nb de clusters négligeable à démarrage. Preuves : `tests/test_store.py::test_i59b_merge_quasi_duplicate_clusters`, `tests/test_pipeline.py::test_engine_startup_merges_before_cluster_index` (ordonnancement), check.sh 154 tests verts.

## I59b (it.6) — Fusion de clusters en chaines transitives (union-find)
merge_quasi_duplicate_clusters comportait deux defauts : (1) la liste des pairs cids
etait figee avant les UPDATE, si bien qu'un cluster deja absorbe reintervenait comme
canonique et re-marquait les restants sous son propre id ; (2) le comparateur n'utilisait
que l'empreinte de la racine de classe, ce qui cassait les chaines a~b~c (fingerprints_match
non transitive). Correction : union-find dont la racine reste l'id minimal ; chaque membre
a (absorbe ou pas) compare son propre fp aux candidats plus grands ; une seule passe d'UPDATE
par id absorbe en fin de boucle. Garantit : le cluster canonique final est l'id minimal.

## [2026-08-27] Durcissement Sécurité & Robustesse Viz (P0-1 à P0-4)
- **P0-1 (Anti-DoS Content-Length)** : Plafonnement des requêtes POST à `MAX_POST_BODY = 64 Ko` avec rejet HTTP 413 (*Payload Too Large*) et 411 si absent.
- **P0-2 (Plafonnement pagination)** : Limitation stricte de `limit` à `MAX_API_LIMIT = 50 000` sur `/api/events` et `/api/spectrum` (dans `viz.py` et `store.py`) pour préserver la RAM du thin client HP T620.
- **P0-3 (Écoute réseau et auth)** : `VizConfig.host = "127.0.0.1"` par défaut ; support de `auth_token` dans `config.toml` ou variable `BRUITTRACK_AUTH_TOKEN` protégeant les actions de modification (`POST /triage`) via en-têtes `Authorization: Bearer` ou `X-API-Key` (HTTP 401 si non autorisé).
- **P0-4 (Assainissement des erreurs)** : Masquage des exceptions internes et chemins système dans les réponses HTTP, journalisation sécurisée via `logging`. Validation Ruff `PLW1510` avec `check=False` explicite. Suite locale étendue à 165 tests verts.

## [2026-08-27] Conformité Réglementaire CSP Art. R1336-7 & Rapport Légal (P1-1 à P1-3)
- **P1-1 (Sémantique du filtre UI)** : Renommage du filtre en `"Infractions / Dépassements légaux (▲)"` avec rappel de la formule légale en infobulle et badge inline explicite `▲ Infraction` / `? Invalide`.
- **P1-2 (Règle des 10 secondes)** : Ajout de `FLAG_INVALID = 1 << 4` (bit 4) ; intégration de `evaluate_conformity` dans `EventDetector._compute_flags` pour qualifier et marquer invalides les mesures transitoires < 10 s sans historique ambiant suffisant.
- **P1-3 (Rapport acoustique légal)** : Ajout de `generate_legal_report()` dans `legal.py`, de la commande CLI `bruittrack report [--since ...] [--json] [--output ...]` et de l'endpoint `GET /api/reports/legal`. Suite étendue à 171 tests verts.

## [2026-08-27] Zoom Spectrographique Haute Définition & Journal de Gêne Psychoacoustique
- **Contexte & Objectif** : Investigation des nuisances sonores récurrentes à composante tonale / infrasonore (bruits sourds, battements lents 0.5–3 s, vibrations crâniennes, nausées). Nécessité de corréler précisément l'instant du ressenti subjectif de l'habitant avec les mesures physiques (spectrogramme, timeline d'émergence) et d'isoler visuellement les bandes spectrales cibles.
- **Journal de Gêne (`discomfort_log`)** :
  - Table SQLite `discomfort_log` (`id`, `t0`, `level` 1–5, `note`, `created_at`) avec index `idx_discomfort_t0`.
  - API Web : `GET /api/discomfort`, `POST /api/discomfort`, `POST /api/discomfort/<id>/delete`.
  - CLI : `bruittrack log-discomfort --level 1..5 --note "..."` et `bruittrack discomfort-logs [--since ...] [--limit ...] [--json]`.
  - Dashboard UI : Modal d'enregistrement rapide avec tags de symptômes prédéfinis (*Nausées*, *Cerveau qui vibre*, *Bourdonnement*, *Battements 0.5–3s*, *Pression oreilles*, *Stress*), tableau des signalements avec bouton de zoom direct `[🔍 Zoomer ±5 min]` sur l'instant de crise, et tracé de marqueurs verticaux pointillés + badges sur la timeline et le spectrogramme.
- **Zoom Spectrographique HD (Focus Fréquentiel)** :
  - Ajout de boutons de focus 1-clic : `[Tout (0–150 Hz)]`, `[🔍 Infrasons (2–35 Hz)]`, `[🔍 Hum (35–70 Hz)]`, `[🔍 Haut (70–150 Hz)]`.
  - Synchronisation stricte de l'axe Y du spectrogramme (`drawSpecPanel`) avec les bornes `freqBounds()` : étirement dynamique des bandes visibles sur toute la hauteur du canvas avec étiquettes de pas « nice » recalculées.
  - Tests unitaires et d'intégration dédiés (`tests/test_discomfort.py`). Suite complète à 174 tests 100% verts.

## [2026-08-27] Résolution Haute Définition (A), Clichés de Crise 100ms/0.49Hz (B) et Détection de Battements AM (C)
- **Option A (Spectrogramme Continu 24/7 HD Ultra)** :
  - Configuration passée à `n_bands = 150` (résolution exacte de 1.0 Hz / bande au lieu de 3.08 Hz) et `interval_s = 5.0 s` (tranches temporelles de 5 secondes au lieu de 60 s).
  - Élargissement vertical du canvas à `hCss = 220 px` dans l'interface web pour une lisibilité accrue des lignes de résonance.
  - Normalisation globale en dB basée sur l'énergie physique au lieu d'un contraste par bande artificiel.
  - Empreinte disque maîtrisée : ~10 Mo/jour sur SSD T620 (supportée avec la politique de rétention).
- **Option B (Cliché HD / Crisis Snapshot)** :
  - Tampon tournant circulaire de 30 secondes en RAM : 30 000 échantillons audio 1000 Hz stéréo + 300 trames de PSD à résolution FFT native (0.49 Hz / 100 ms).
  - Persistance dans `snapshots/snap_<id>.npz` (matrices) et `snapshots/snap_<id>.wav` (audio stéréo 1 kHz 16 bits).
  - Endpoints d'API : `GET /api/discomfort/<id>/snapshot` et `GET /api/discomfort/<id>/audio`.
  - Modalité d'affichage UI : Modal d'analyse HD avec spectrogramme matriciel complet, sélecteur de vitesse de lecture (0.5x, 1x) et zoom fréquentiel 1-clic.
- **Option C (Détecteur de Battements & Modulation AM)** :
  - Mesure continue de l'instabilité d'amplitude (0.5–3 s) dans les sous-bandes Infrasons (2–35 Hz) et Hum (35–70 Hz).
  - Calcul de la profondeur de modulation relative (%) et estimation de la période de battement dominante via autocorrélation d'enveloppe.
  - Affichage instantané dans le bandeau de métriques du cliché HD.
  - Suite de tests complète portée à 176 tests 100% verts.



