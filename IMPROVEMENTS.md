# Backlog des Améliorations — BruitTrack

Analyse globale du projet réalisée le **27 août 2026**.
- **État courant du projet** : 159 tests unitaires et d'intégration validés (`pytest`), architecture modulaire respectant les contraintes matérielles du thin client HP T620 (1.5 GHz, 4 Go RAM, 16 Go SSD, fanless 24/7).
- Les améliorations ci-dessous sont classées par **ordre d'importance décroissant** (de P0 Critique à P7 Hygiène).

---

## Sommaire des Priorités

1. [P0 — Sécurité, Stabilité & Garde-fous Réseau / DoS](#p0--sécurité-stabilité--garde-fous-réseau--dos)
2. [P1 — Métier & Conformité Réglementaire CSP Art. R1336-7](#p1--métier--conformité-réglementaire-csp-art-r1336-7)
3. [P2 — Architecture & Refactoring (Découpage de `viz.py`)](#p2--architecture--refactoring-découpage-de-vizpy)
4. [P3 — Résilience 24/7 & Exploitation HP T620 / Systemd](#p3--résilience-247--exploitation-hp-t620--systemd)
5. [P4 — Optimisation Base de Données SQLite & Gestion Disque](#p4--optimisation-base-de-données-sqlite--gestion-disque)
6. [P5 — Qualité de Code, Typage Statique & Pipeline CI](#p5--qualité-de-code-typage-statique--pipeline-ci)
7. [P6 — Fonctionnalités Dashboard UI & Télémétrie](#p6--fonctionnalités-dashboard-ui--télémétrie)
8. [P7 — Hygiène du Dépôt Git & Documentation](#p7--hygiène-du-dépôt-git--documentation)

---

## P0 — Sécurité, Stabilité & Garde-fous Réseau / DoS

### - [x] [P0-1] Plafonnement de `Content-Length` et protection anti-DoS sur l'API POST
- **Fichiers** : `src/bruittrack/viz.py` (`BruitTrackHandler.do_POST`), `tests/test_viz_api.py`.
- **Statut** : ✅ Réalisé — `MAX_POST_BODY = 64 * 1024` (64 Ko), rejet HTTP 413 (*Payload Too Large*), HTTP 411 si header absent, test `test_p0_triage_payload_too_large_returns_413`.

### - [x] [P0-2] Plafonnement strict des paramètres de pagination `limit`
- **Fichiers** : `src/bruittrack/viz.py`, `src/bruittrack/store.py`, `tests/test_viz_api.py`.
- **Statut** : ✅ Réalisé — `MAX_API_LIMIT = 50_000`, bornage automatique dans `viz.py` et `store.py` (`get_events`, `get_spectrum`), tests `test_p0_events_limit_clamped_to_max_api_limit` et `test_p0_spectrum_limit_clamped_to_max_api_limit`.

### - [x] [P0-3] Restriction d'écoute réseau (`host`) et sécurisation des actions d'écriture
- **Fichiers** : `src/bruittrack/config.py`, `src/bruittrack/viz.py`, `config.toml.example`, `tests/test_config.py`, `tests/test_viz_api.py`.
- **Statut** : ✅ Réalisé — Défaut `host = "127.0.0.1"` (sécurité locale), support de `auth_token` dans `[viz]` / variable `BRUITTRACK_AUTH_TOKEN` avec vérification des en-têtes `Authorization: Bearer` ou `X-API-Key` sur `/triage` (HTTP 401 si non autorisé), tests `test_viz_config_defaults_and_auth` et `test_p0_triage_auth_token_protection`.

### - [x] [P0-4] Assainissement des messages d'erreur HTTP (Fuite de chemins internes)
- **Fichiers** : `src/bruittrack/viz.py`, `src/bruittrack/__main__.py`, `tests/test_viz_api.py`.
- **Statut** : ✅ Réalisé — Messages génériques sécurisés, journalisation serveur `logger.error`, résolution de l'avertissement Ruff `PLW1510` avec `check=False`, test `test_p0_error_responses_sanitized`.

---

## P1 — Métier & Conformité Réglementaire CSP Art. R1336-7

### - [x] [P1-1] Correction du libellé et de la sémantique du filtre légal dans l'interface web
- **Fichiers** : `src/bruittrack/viz.py` (HTML & JS), `tests/test_viz_api.py`.
- **Statut** : ✅ Réalisé — Libellé explicite `"Infractions / Dépassements légaux (▲)"` avec tooltip CSP, badge inline `▲ Infraction` et badge `? Invalide`, test `test_p1_legal_filter_ui_markers`.

### - [x] [P1-2] Intégration de la validation de mesure minimale (Règle des 10 secondes)
- **Fichiers** : `src/bruittrack/events.py`, `src/bruittrack/legal.py`, `src/bruittrack/store.py`, `tests/test_events.py`, `tests/test_legal.py`.
- **Statut** : ✅ Réalisé — Flag `FLAG_INVALID = 1 << 4`, intégration de `evaluate_conformity` dans `_compute_flags`, exposition de `is_invalid` dans `store.get_events`, tests `test_conformite_et_invalidite` et `test_flag_invalid_for_short_recording`.

### - [x] [P1-3] Générateur de procès-verbal / rapport acoustique légal (CLI et API)
- **Fichiers** : `src/bruittrack/legal.py`, `src/bruittrack/__main__.py`, `src/bruittrack/viz.py`, `tests/test_legal.py`, `tests/test_viz_api.py`, `tests/test_bugfixes.py`.
- **Statut** : ✅ Réalisé — Fonction `generate_legal_report()` avec ventilation diurne/nocturne et liste détaillée des infractions, commande CLI `bruittrack report [--since ...] [--json] [--output ...]`, route API `GET /api/reports/legal`, tests unitaires et intégration CLI complets.

---

## P2 — Architecture & Refactoring (Découpage de `viz.py`)

### [P2-1] Extraction des assets frontend statiques (`dashboard.html`, `.css`, `.js`)
- **Fichiers** : `src/bruittrack/viz.py`, création de `src/bruittrack/viz_assets/` (`dashboard.html`, `dashboard.css`, `01-api.js`, `02-table.js`, `03-timeline.js`).
- **Problème** : `viz.py` dépasse 1 250 lignes avec ~830 lignes de HTML/CSS/JS imbriquées dans des chaînes de caractères Python. Impossible de linter le JavaScript, coloration syntaxique absente, risque élevé de régression à chaque retouche UI.
- **Solution** : Exécuter le plan documenté dans `viz-refactor.md` en utilisant `importlib.resources.files("bruittrack.viz_assets")`.
- **Critère d'acceptation** : `viz.py` réduit à ~250 lignes de code Python pur ; vérification `node --check` sur tous les fichiers JS dans `tools/check.sh` ; tous les tests viz passent sans modification du comportement client.

### [P2-2] Table de routage déclarative dans le serveur HTTP
- **Fichiers** : `src/bruittrack/viz.py`, `tests/test_viz_api.py`.
- **Problème** : Le routage dans `BruitTrackHandler` utilise une suite de blocs `if path == ...: elif path.startswith(...):` difficile à maintenir et à tester isolément.
- **Solution** : Implémenter un routeur déclaratif avec un dictionnaire de handlers (`ROUTES_GET`, `ROUTES_POST`) séparant parsing d'URL, validation des arguments et logique métier.
- **Critère d'acceptation** : Chaque endpoint dispose de sa fonction handler dédiée, testable unitairement sans instancier de socket réseau.

---

## P3 — Résilience 24/7 & Exploitation HP T620 / Systemd

### [P3-1] Garde-fous de ressources Systemd (Cgroups CPU & Mémoire)
- **Fichiers** : `systemd/bruittrack.service`, `systemd/bruittrack-viz.service`.
- **Problème** : Les services n'ont aucune limite de ressources déclarée. En cas de fuite mémoire ou d'emballement CPU imprévu, le thin client fanless HP T620 (sans swap rapide sur SSD 16 Go) risque de geler totalement.
- **Solution** : Ajouter dans les fichiers d'unité systemd :
  - `bruittrack.service` : `MemoryMax=200M`, `MemoryHigh=150M`, `CPUQuota=20%`.
  - `bruittrack-viz.service` : `MemoryMax=100M`, `MemoryHigh=80M`, `CPUQuota=10%`.
- **Critère d'acceptation** : `systemd-analyze verify` valide les unités et systemd tue/recharge proprement le service si un quota est franchi.

### [P3-2] Watchdog Systemd (`sd_notify` / `WatchdogSec`)
- **Fichiers** : `systemd/bruittrack.service`, `src/bruittrack/pipeline.py`, `src/bruittrack/__main__.py`.
- **Problème** : Si le thread de capture ALSA ou le flux audio se bloque sans lever d'exception (blocage matériel ou driver USB), le service reste actif en apparence mais ne traite plus rien.
- **Solution** : Configurer `WatchdogSec=30s` dans le service systemd et envoyer périodiquement un ping watchdog (`systemd-notify` ou socket sd_notify via stdlib) à chaque cycle de rétention / toutes les 15 s dans la boucle principale.
- **Critère d'acceptation** : Un gel simulé de la boucle entraîne le redémarrage automatique du service par systemd sous 30 secondes.

### [P3-3] Reconnexion automatique et tolérance aux déconnexions USB (Hotplug Audio)
- **Fichiers** : `src/bruittrack/capture.py`, `src/bruittrack/pipeline.py`, `tests/test_capture_slowblock.py`.
- **Problème** : Une micro-coupure USB sur la carte son M-Track Plus provoque une exception PortAudio/ALSA non rattrapée qui arrête définitivement le service.
- **Solution** : Ajouter une boucle de réessai avec backoff exponentiel (1 s, 2 s, 5 s, max 30 s) dans `AudioCapture` lors de la perte du flux audio avant d'abandonner.
- **Critère d'acceptation** : Le redémarrage ou le rebranchement de la carte son n'interrompt pas le processus démon, qui reprend la capture dès que le périphérique réapparaît.

---

## P4 — Optimisation Base de Données SQLite & Gestion Disque

### [P4-1] Récupération d'espace disque physique (`incremental_vacuum`)
- **Fichiers** : `src/bruittrack/store.py`, `tests/test_store.py`.
- **Problème** : Lors de la purge des vieux événements (`apply_retention`), SQLite supprime les lignes mais conserve les pages allouées dans le fichier `.db`. Sur un SSD de 16 Go, l'espace n'est jamais restitué au système de fichiers sans vacuum.
- **Solution** :
  - Activer `PRAGMA auto_vacuum = INCREMENTAL;` lors de l'initialisation de la base.
  - Exécuter `PRAGMA incremental_vacuum(100);` lors de la passe quotidienne de rétention.
- **Critère d'acceptation** : La taille du fichier `bruittrack.db` diminue effectivement sur disque après une purge massive d'événements.

### [P4-2] Rétention automatique par défaut sur la table `spectrum`
- **Fichiers** : `src/bruittrack/config.py`, `config.toml.example`, `src/bruittrack/pipeline.py`.
- **Problème** : La table `spectrum` enregistre 1 ligne par minute (~525 600 lignes/an). Contrairement aux événements dont la rétention est à 365 jours par défaut, `SpectrumConfig.retention_days` est initialisé à `None` (rétention infinie).
- **Solution** : Définir `SpectrumConfig.retention_days = 90` par défaut (3 mois de heatmap spectrale, amplement suffisant et économique pour le SSD).
- **Critère d'acceptation** : La purge quotidienne nettoie automatiquement les entrées `spectrum` plus vieilles que le seuil configuré.

### [P4-3] Intégrité et nettoyage des extraits audio exemplaires orphelins
- **Fichiers** : `src/bruittrack/store.py`, `tests/test_store.py`.
- **Problème** : Lors des fusions de clusters quasi-doublons (I59b) ou de purges manuelles en base, des fichiers `exemplars/ex_<id>.raw` peuvent subsister sans correspondance dans la table `clusters`.
- **Solution** : Systématiser la vérification de cohérence orpheline au démarrage dans `store.apply_retention` ou `prune_orphaned_exemplars`.
- **Critère d'acceptation** : Aucun fichier `.raw` ne subsiste sur disque s'il n'est pas référencé par un cluster valide en base.

---

## P5 — Qualité de Code, Typage Statique & Pipeline CI

### [P5-1] Résolution de l'avertissement Ruff dans `__main__.py`
- **Fichiers** : `src/bruittrack/__main__.py:307`.
- **Problème** : `ruff check .` remonte `PLW1510 subprocess.run without explicit check argument`.
- **Solution** : Ajouter explicitement `check=False` à l'appel `_sp.run(...)`.
- **Critère d'acceptation** : `ruff check .` sort avec le code 0 (zéro erreur, zéro avertissement).

### [P5-2] Intégration du vérificateur de types statiques `mypy` en mode strict
- **Fichiers** : `pyproject.toml`, `.github/workflows/ci.yml`, `tools/check.sh`.
- **Problème** : Le code utilise des annotations de types Python mais aucun contrôle statique formel n'est exécuté en CI, laissant passer de potentielles incohérences de signature.
- **Solution** : Ajouter `mypy` aux dépendances `[project.optional-dependencies] dev` et intégrer `mypy src/` dans `tools/check.sh` et le workflow GitHub Actions.
- **Critère d'acceptation** : `mypy src/` passe à 100% vert sans `type: ignore` injustifié.

### [P5-3] Couverture de code automatisée (`pytest-cov`)
- **Fichiers** : `pyproject.toml`, `.github/workflows/ci.yml`.
- **Solution** : Configurer la mesure de couverture avec un seuil minimal de 90% sur `src/bruittrack/` (hors `capture.py` matériel).
- **Critère d'acceptation** : Le rapport de couverture est généré en CI et garantit qu'aucune régression de test n'est introduite.

---

## P6 — Fonctionnalités Dashboard UI & Télémétrie

### [P6-1] Export direct des données filtrées en CSV et JSON depuis le web
- **Fichiers** : `src/bruittrack/viz.py` (UI + API).
- **Besoin** : Permettre à l'utilisateur d'extraire rapidement les événements filtrés (par canal, niveau ou cluster) pour une analyse tableur ou un partage d'expertise.
- **Solution** : Ajouter un bouton « Exporter CSV » et « Exporter JSON » au-dessus du tableau « Derniers Événements ».
- **Critère d'acceptation** : Le clic télécharge instantanément un fichier `.csv` ou `.json` contenant les événements actuellement affichés.

### [P6-2] Indicateur en temps réel du plancher de bruit et du niveau d'émergence
- **Fichiers** : `src/bruittrack/viz.py`.
- **Besoin** : L'utilisateur n'a pas de visibilité directe sur le niveau sonore instantané (bruit ambiant / bruit résiduel en dB) mesuré lors des périodes calmes sans événement.
- **Solution** : Afficher dans l'en-tête de la page le dernier niveau plancher estimé (Canal Gauche / Canal Droit) retourné par `/api/stats`.
- **Critère d'acceptation** : Le bandeau de statistiques affiche les niveaux ambiants récents mis à jour à chaque cycle de rafraîchissement.

### [P6-3] Amélioration de l'accessibilité et contraste visuel des graphiques
- **Fichiers** : `src/bruittrack/viz.py` (CSS et Canvas rendering).
- **Solution** : Améliorer le contraste des graduations d'axes, ajouter un mode d'accentuation des contrastes pour la heatmap du spectre et supporter la navigation clavier sur les filtres.
- **Critère d'acceptation** : Lisibilité accrue sur écrans basse résolution ou mobiles sans dégradation des performances canvas.

---

## P7 — Hygiène du Dépôt Git & Documentation

### [P7-1] Nettoyage des fichiers parasites trackés dans l'historique Git
- **Fichiers** : Index Git (`.pi/user-decisions/...`, `f`, `manifest.csv`).
- **Problème** : Des fichiers résiduels d'anciennes sessions ou créés par inadvertance sont suivis par Git.
- **Solution** : Exécuter `git rm --cached f manifest.csv .pi/user-decisions/sessions/*`, s'assurer que `.gitignore` les exclut formellement.
- **Critère d'acceptation** : `git ls-files` ne contient que les fichiers sources, tests, documentation et scripts de déploiement légitimes.

### [P7-2] Unification des scripts de vérification (`check.sh` vs `tools/check.sh`)
- **Fichiers** : `check.sh` (racine) et `tools/check.sh`.
- **Problème** : Deux scripts de vérification coexistent avec des critères légèrement divergents (recherche d'anciennes mentions dans le README).
- **Solution** : Conserver `tools/check.sh` comme point d'entrée unique et remplacer `check.sh` à la racine par un lien ou un appel délégataire direct vers `tools/check.sh`.
- **Critère d'acceptation** : Une seule commande canonique `bash tools/check.sh` pour valider l'intégrité du projet.

### [P7-3] Synchronisation des budgets de performance dans la documentation
- **Fichiers** : `README.md`, `AGENTS.md`, `docs/decision-log.md`.
- **Problème** : Certaines mentions citent « < 10% CPU » tandis que les règles constitutionnelles `AGENTS.md` et `decision-log.md` fixent la contrainte cible à « < 15% CPU » sur le matériel HP T620.
- **Solution** : Aligner tous les documents sur la spécification officielle : CPU < 15%, RAM < 150 Mo.
- **Critère d'acceptation** : Cohérence parfaite des chiffres cités dans toute la documentation.
