# BUGS.md — BruitTrack

Audit du code source (`src/bruittrack/`) à partir de la spécification
`AGENTS.md`. Chaque entrée : sévérité, localisation `fichier:ligne`,
description avec preuve, et proposition de correction.

Légende : **P0** = crash/panne immédiate, **P1** = perte de données ou
fonction majeure cassée, **P2** = comportement déviant de la spec,
**P3** = robustesse/nettoyage.

---

## P0

### BUG-01 — Serveur de visualisation : connexion SQLite partagée entre threads sans protection → crash dès le 1ᵉʳ affichage
- **Lieu** : `src/bruittrack/store.py` (`cursor()`, `_init_db`) ; `src/bruittrack/viz.py:340-343,441-444,454`
- **Statut** : corrigé par la refonte `cursor()` courte durée (commit dfd2d08) + test concurrent lecteur / rédacteur (`test_concurrent_writer_and_readers`, 1d01e28).
- **Description** : `run_viz_server` crée **une seule** `EventStore`, dont la
  connexion `sqlite3.connect(...)` n'est pas ouverte avec
  `check_same_thread=False`, et la classe du handler y accède depuis chaque
  requête. Le serveur est un `ThreadingHTTPServer` : une thread par requête.
  Le tableau de bord émet **3 `fetch` parallèles** (`/api/stats`,
  `/api/events`, `/api/clusters`) au chargement, puis toutes les 10 s
  (`setInterval(refreshAll, 1000)` → en fait 10 s). Dès la première
  seconde de page, deux threads opèrent sur une connexion `sqlite3`
  créée dans un thread différent.
- **Conséquence** : `sqlite3.ProgrammingError: SQLite objects created in a
  thread can only be used in that same thread` (reproduit en local). Toute
  charge concurrente — y compris le dashboard lui-même — fait planter ou
  répondre 500 aux requêtes. La visualisation est inutilisable.
- **Correction** : ouvrir la connexion avec `check_same_thread=False` **et**
  protéger chaque requête/transaction par un `threading.Lock` dans
  `EventStore` (ou, plus propre, maintenir une connexion par thread via
  `threading.local()` et centraliser les transactions). Ajouter un test
  d'intégration : 3 requêtes HTTP concurrentes sur `run_viz_server` avec
  un store partagé.

---

## P1

### BUG-02 — `bruittrack test` pollut la base de données de production
- **Lieu** : `src/bruittrack/__main__.py:55,85` ; `src/bruittrack/pipeline.py` (`Engine.__init__`) ; `src/bruittrack/store.py:29` (chemin par défaut)
- **Description** : `cmd_test` construit `Engine(config=config, capture=MockAudioCapture(...))`
  **sans injecter** `store`. `Engine.__init__` crée alors automatiquement
  `EventStore(db_path=config.storage.db_path)` — soit le fichier de
  production `data/bruittrack.db`. En mode `--synthetic`, les événements
  détectés (ton de 23,5 Hz au-dessus du seuil) sont donc **persémines**…
  persémines → **persistés** dans la base réelle, puis `engine.stop()` →
  `close()` → `flush()` les inscrit définitivement.
- **Conséquence** : toute session de test/simulation enfler… **injecte** des
  événements de test dans la base de production, créant de faux clusters et
  faussant les stats.
- **Correction** : `cmd_test` doit injecter un store dédié
  (`EventStore(db_path=":memory:")` ou un fichier temporaire sous `data/`),
  jamais le chemin de prod. À terme, `Engine` ne devrait jamais créer de
  store en silence (argument obligatoire ou mode explicite).

### BUG-03 — `EventStore.flush()` perd des événements en cas d'erreur SQLite
- **Statut** : ✅ corrigé — `_do_flush` ne vide le buffer qu'après `commit()` réussi, échec loggué et réessayé au flush suivant ; régresse testée (`TestFlushErrorPreservation`).
- **Lieu** : `src/bruittrack/store.py` — `EventStore.flush` (L195), `add_event` (L122)
- **Description** : avant l'insertion, le buffer est **transféré** vers une
  liste locale (`events_to_write = self._buffer; self._buffer = []`). Si
  `cursor.executemany(...)` ou `commit()` lève une exception (disk full,
  verrou WAL, erreur de schéma), les événements transférés ne sont pas
  re-ajoutés au buffer → **perdus sans trace**.
- **Conséquence** : perte de données silencieuse; sur thin client 24/7,
  un incident disque ponctuel perd tout le lot en cours (30 s ou 50
  événements), sans avertissement.
- **Correction** : ne vider `self._buffer` que **après** insertion réussie ;
  en cas d'exception, re-queue (`self._buffer = events_to_write + self._buffer`)
  et logger l'échec. Ajouter un test qui simule une erreur `executemany` et
  vérifie que les événements survivent.

### BUG-04 — `retention_days` n'a aucun effet : `apply_retention` n'est jamais appelé
- **Statut** : ✅ corrigé — appliqué au démarrage du daemon puis quotidiennement dans la boucle `step()` (`pipeline.py` L89-92, L138-145) ; test `TestRetentionWiring`.
- **Lieu** : `src/bruittrack/store.py` — `EventStore.apply_retention` (L330) ; aucune occurrence d'appel
  dans `src/bruittrack/pipeline.py`, `src/bruittrack/__main__.py`,
  `src/bruittrack/viz.py` (grep confirmé). La valeur est lue dans
  `src/bruittrack/config.py:167,178` mais jamais consommée.
- **Conséquence** : la croissance de `data/bruittrack.db` est **illimitée**.
  Estimée ~7 Mo/an c'est confortable, mais sur SSD 16 Go d'un thin client
  24/7 multi-années, l'absence de purge est un risque concret de
  saturation. La config expose une promesse non tenue.
- **Correction** : appeler `store.apply_retention(config.storage.retention_days)`
  périodiquement — au démarrage du daemon de capture et au moins une fois
  par jour pendant `start` (par ex. dans la boucle de l'engine ou via un
  timer dédié). Documenter dans `docs/decision-log.md`.

### BUG-05 — `cmd_stats --play` : format de régression… **regression** SoX → exemplaire illisible
- **Lieu** : écriture `src/bruittrack/events.py:394` ; lecture `src/bruittrack/__main__.py:174-198`
- **Description** : l'extrait est sauvegardé en **float16 IEEE 754 half**
  (`audio_data.astype(np.float16).tobytes()`). La CLI rejoue avec
  `sox ... -r 1000 -c 2 -e floating-point -b 16` : le format
  « floating-point 16 bits » de SoX est un fixed-point interne 16:16, **pas**
  du IEEE 754 half. Les octets sont donc interprétés à tort.
- **Conséquence** : `stats --play <cluster_id>` produit de l'audio hachée…
  hachée **ou du silence** (bit de signe/normalisation erronée) plutôt que
  l'extrait. Le chemin web (`viz.py` → `create_wav_from_raw`) est correct car
  il convertit explicitement en WAV 16 bits — seule la CLI SoX est cassée.
- **Correction** : dans `cmd_stats --play`, lire l'extrait, le convertir en
  `int16` WAV via `struct`/`wave` (ou réutiliser la logique de
  `create_wav_from_raw` de `viz.py` factorisée), écrire un `.wav` temporaire
  et rejouer **cet** fichier sans les options `-b`/`-e` ambiguës.

---

## P2

### BUG-06 — `compute_channel_delay_ms` : signe opposé à la docstring (`off_ms` inversé)
- **Lieu** : `src/bruittrack/dsp.py` — `compute_channel_delay_ms` : docstring L296 vs `best_lag_samples = -int(lag_range[best_idx])` L325
- **Description** : en mode `"full"`, si le canal 0 (Left) est en avance de
  `t` échantillons, le pic de corrélation est en index `mid + t`.
  `int(lag_range[best_idx]) = +t`, puis la négation renvoie `−t` : **négatif
  quand Left est en avance**, contradicant… contradictant la docstring
  (vérifié empiriquement avec deux sinus à 23,5 Hz décalés). La valeur
  écrite dans `events.off_ms` (et la classe de délai à ±20 ms du
  fingerprint) a donc le signe **opposé** au contrat documenté.
- **Statut** : non confirmé — vérifié numériquement (burst déterministe L→R
  et R→L, `tests/test_dsp.py::TestChannelDelaySign`, commit 4e36373) ; le code
  est conforme à la docstring, aucune correction requise.
- **Conséquence** : l'utilisateur/la dashboard voit « Right leads » quand
  c'est Left ; le clustering par classe de délai reste cohérent (symétrie)
  mais la valeur affichée est trompeuse.
- **Correction** : soit retirer la négation (si `left leads ⇒ +`), soit
  corriger la docstring ; choisir **et** ajouter un test déterministe avec
  un décalage connu (L→R et R→L). Attention : changement de sémantique de
  `off_ms` déjà en base → documenter la migration éventuelle.

### BUG-07 — Normalisation Welch non conforme : `(Σw)²` au lieu de `Σw²`
- **Statut** : ✅ corrigé — `DspPipeline.window_scale = Σ(hann²)` (`dsp.py` L142), utilisé dans les deux PSD ; test `TestWelchNormalization::test_window_sum_used`.
- **Lieu** : `src/bruittrack/dsp.py` — `SpectraEstimator.__init__`, `window_scale = ...hann_window**2` (L142)
- **Description** : la densité spectrale de puissance standard (Welch) est
  mise à l'échelle par `sum(w**2)`, pas `(sum(w))**2`. Pour une fenêtre de
  Hann de 2048, ces deux factor… **facteurs** ne sont pas égaux (~2.5× la
  différence… exactement : `(2048·n_côtés)²` vs `(5/8·2048)`-forme — dans
  tous les cas, le facteur n'est **pas** de 1). Tout le pipeline est
  auto-cohérent : le facteur constant se compense dans la soustraction dB
  `emergence = PSD_ema − floor`, donc **aucune fausse détection**.
- **Conséquence** : les **niveaux absolus** (PSD en dB, `lvl_g`/`lvl_d` en
  `events`) ne correspondent pas à l'échelle physique standard ; si des
  seuils ou seuils d'excellence… d'excellence absolue basées sur un calage…
  **calage** externe (niveau dB known, sensibilité capteur) sont ajoutés
  plus tard, la base est fausse ; le `floor` médian est calculé sur des
  valeurs à l'échelle erronée.
- **Correction** : `self.window_scale = float(np.sum(self.hann_window ** 2))`.
  Si le facteur actuel a été **calibré** empiriquement (seuil 10 dB, hystérésis
  3 dB), tout est relatif → le changement est quasi neutre, mais documenter
  dans le decision-log.

### BUG-08 — `EventStore._buffer` sans verrou : race condition potentiel avec le futur threading
- **Lieu** : `src/bruittrack/store.py` — `EventStore.__init__` `_buffer` (L76), `add_event` (L122), `_do_flush` (L137), `flush` (L195)
- **Statut** : corrigé — verrou `threading.Lock()` sur le buffer + tests de régression 24/08 (`test_add_event_autoflush_no_deadlock`, `test_concurrent_writer_and_readers`).
- **Description** : aucune synchronisation sur `self._buffer`. Actuellement
  le chemin capture est **mono-threads** (une seule boucle `Engine.step`)
  et `add_event`/`maybe_flush`/`flush` s'appellent séquentiellement → pas
  de course en production **aujourd'hui**. Mais la même instance de store
  est également exposée au serveur web (threading) et à `cmd_stats`/`cmd_viz` ;
  toute évolution vers plusieurs threads appelant `maybe_flush` ou
  `flush` (p. ex. un endpoint d'API d'écriture, un flush périodique
  déporté) créera des pertes corrompues… **corruptions** de tableau.
- **Conséquence** : défaut latent ; le même pattern que BUG-01 mais du côté
  de la file mémoire plutôt que de la connexion SQLite.
- **Correction** : ajouter un `threading.Lock` dans `EventStore` et le tenir
  pour `add_event`, `maybe_flush`, `flush`, `close` (indispensable si on
  bascule sur une connexion par thread). Ajouter un test concurrent
  (threads écrivants en parallèle).

### BUG-09 — Défaut `retention_days` écrasé par `None` : la retenue est désactivée silencieusement par défaut
- **Statut** : ✅ corrigé — défaut dataclass 365 jours, conservé si le TOML omet la clé (`config.py` L181-183) ; validation `> 0 ou None` ; test `TestRetentionDefault`.
- **Lieu** : `src/bruittrack/config.py:62` (défaut dataclass `= 365`) vs `src/bruittrack/config.py:167,178` (`store_dict.get("retention_days")` → `None` si la clé est absente)
- **Description** : l'absence de la clé `retention_days` dans `config.toml`
  donne `None`, pas le défaut du dataclass (365). Le dataclass présente
  `365` comme valeur par défaut ; en pratique la retenue est **désactivée**
  pour tout utilisateur qui n'a pas écrit la clé dans son config.
- **Conséquence** : incohérence config/code ; combinée à BUG-04, le
  comportement réel est « aucune retenue » alors que le défaut affiché
  est 365 jours.
- **Correction** : `store_dict.get("retention_days", 365)` — ou mieux,
  retirer le `retention_days` du constructeur et laisser le défaut dataclass
  s'appliquer ; `None` devient l'unique « désactiver » explicite.

### BUG-10 — `load_config` sans validation de cohérence des valeurs
- **Lieu** : `src/bruittrack/config.py` (`load_config`) ; consommés en `src/bruittrack/dsp.py`, `pipeline.py`, `events.py`
- **Description** : plusieurs combinaisons possibles laissent le pipeline
  démarrer dans un état invalide ou absurde : `block_size % decimation != 0`
  (cadence du stream « bas » non plus 1000 Hz), `noverlap >= n_seg…` ou
  `freq_max * fs_low/2` > Nyquist, `debounce_ticks < 1`, `max_duration_s <= 0`,
  `threshold_db < 0`, etc. Aucune vérification de ces invariants au chargement.
- **Conséquence** : erreurs silencieuses ou crash tardifs et obscurs sur la
  cible ; sur thin client 24/7, détecté **très tard** (parce que le floor se
  décale ou la cadence est faussée) sans message utile.
- **Correction** : lever `ValueError` dès `load_config` sur violation des
  invariants ; message d'erreur explicite au démarrage (fail fast).

### BUG-11 — `SosFilter.set_initial_state` : code mort + approximation grossière
- **Lieu** : (supprimée — méthode `SosFilter.set_initial_state`, anciennement `src/bruittrack/dsp.py:73-89`)
- **Description** : méthode jamais appelée (`DspPipeline` ne l'utilise pas ;
  les filtres démarrent toujours de l'état nul). De plus, la formule
  `zi[0] = (b[1] - a[1]*b[0]) * val`, `zi[1] = (b[2] - a[2]*b[0]) * val` ne
  correspond pas à la **solution station**… **stationnaire exacte** de
  `y[n] - Σa·y[n-k] = Σb·x[n-k]` sous constante d'entrée : les états dits
  « steady-state » ne sont en général pas l'état d'équilibre. Le transient
  au démarrage est **en partie** masqué par le warmup de 300 ticks (30 s),
  d'où P3.
- **Conséquence** : si on l'active demain, comportement incohérent ; code
  mort qui risque d'induire en erreur.
- **Correction** : soit supprimer, soit réécrire en résolvant le système
  `z_ss = A z_ss + b·x` (linéaire 2×2 par section) et ajouter un test —
- **Statut** : corrigé — méthode supprimée (code mort, jamais appelée ;
  commit 4e36373).

### BUG-12 — `MockAudioCapture` : non déterministe + cadence déconnectée du temps réel
- **Statut** : ✅ corrigé — `seed=42` par défaut (L131), pacing `time.monotonic()` + `sleep` dans `get_block` (capture.py L170-175) ; régresse testée (`TestMockAudioCapture`, 3 tests).
- **Lieu** : `src/bruittrack/capture.py` (classe `MockAudioCapture`)
- **Description** :
  - `np.random.normal(...)` sans seed → bruit différent à chaque run ;
    impossible de re-produire un run de `--synthetic` pour débogage ;
  - `get_block` produit des blocs **sans temporisation** : le champ
    `_last_time` est stocké mais ne sert pas à faire respecter l'écart
    `block_size / sample_rate` → `bruittrack test --synthetic` tourne à la
    vitesse CPU (bien plus vite que le temps réel), sur-consomme le thin
    client et raccourcit **immensément**… **totalement** la période de
    test réelle.
- **Conséquence** : flag `test --synthetic` peu utile pour diagnostic ;
  consommation CPU erratique ; le « 60 s » de `--seconds` correspond à bien
  plus de ticks réels que le temps demandé.
- **Correction** : ajouter un `seed` (défaut fixé) aux bruit stochastiques ;
  dans `get_block`, aligner sur `time.monotonic()` et `sleep` la différence
  minimale pour rester au temps réel. Ajouter un test déterministe sur les
  formes d'onde synthétiques.

---

## Points vérifiés corrects (pour mémoire de l'audit)

- `FloorTracker` : médiane glissante sur anneau avec `valid_len = min(tick_count, history_len)`,
  correcte, pas d'artefact de wrap-around, ordonne non pertinent.
- Machine à états du détecteur (`EventDetector`) : seuil, debounce 5 ticks,
  hystérésis 3 dB, max 30 s par segment → conforme la spec.
- Fingerprint v0 : layout `>BH5BBb6x` = 16 octets exacts (version, bin_peak,
  5 briques 3 bits, canal, classe délai, padding) → conforme AGENTS.md.
- Logique `both_active` / canal dominant : émergence > seuil sur les deux
  canaux dans ±2 bins → cohérent.
- `audio_buffer_low` : rotation stricte de `decimation` échantillons par bloc
  de `4800` → stream basse fréquence parfaitement continu, pas de dérive
  inter-blocs.
- Seed `tick_count == 0` : premier tick, remplissage de l'historique complet,
  pas d'événements avant `is_warmed_up` (300 ticks) → conforme.

---

## Ordre de correction recommandé

1. **BUG-01** (crash serveur web) + **BUG-08** (verrous sur le store) —
   en un seul commit, avec test de concurrence.
2. **BUG-03** (perte d'événements en cas d'erreur) — intégrité des données
   d'abord ; puis **BUG-02** (tests contaminant la base de production).
3. **BUG-04** + **BUG-09** (politique de retenue réellement active et cohérente
   entre code et config).
4. **BUG-05** (format du playbook) — correction utilisateur directe.
5. **BUG-06** + **BUG-07** (signe et échelle des valeurs mesurées ;
   récalibrer si nécessaire).
6. **BUG-10** à **BUG-12** (robustesse/config/tests) en lot.

Chaque correction doit s'accompagner d'au moins un test déterministe sans
matériel (synthèse, base `:memory:`) conformément aux conventions `AGENTS.md`.
