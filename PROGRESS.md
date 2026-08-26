# PROGRESS — I68 (hover tip précision) après I67 + déploiement

## État
- Loop « précision texte survol points » : diagnostic = hit-test 10 px fixe du centre + deux bulles proches disputant le tooltip. Correction I68.
- Gate verte : ruff OK, **145 tests passés**, check.sh OK.

## Fait (essais/échecs)
- I68 : `timelinePoints` porte désormais `r` (rayon visuel) ; hit-test par point `max(12, r+3)` px ; verrou `hoverLockId` (change seulement en sortant du rayon) → texte stable sur des bulles voisines.

## Prochaines étapes
1. **[FAIT]** Déploiement I68 sur pi-t620 : DEPLOY_OK — services actives, health `ok` (3271 lignes), markers HTML vérifiés y compris `hoverLockId`, pip check OK.
2. Suite loop : I56 badge MAJ relatif ou I59 clustering alignement.


## I69 (après déploiement I68)
- evtTip repassé en position:fixed, centré au-dessus de la bulle survolée (clamp écran, repli dessous).
- 146 tests verts, DEPLOY_OK pi-t620. Voir IMPROVEMENTS.md I69.

## I71 M3 (ce tour de loop)
- Gate tools/cluster_color_check.sh REPARÉ et opérationnel : bloc ROOT aplati (D=$(dirname "$0"), ROOT="$D/..", cd) ; doublon corrompu supprimé ; CRLF normalisés en LF.
- Sortie attendue avant M2 : SCORE 6/10 (C2/C3/C6 KO tant que le canvas est coloré par bin ; C7/C8 verts car baseline 147 tests + ruff propres). Exit code : 0 seulement à 10/10.
- Commit : b20e042 I71 M3. Prochain : M1 (palette par cluster + test numérique T1/T2) puis M2 (draw par cluster, retrait de getBinColor).


## I71 M2 (ce tour — DONE, d1a802a + 550ddc4 M1)
- Palette par cluster : hue angle d'or (id*137.5)%360, sat 85%, clarte [45,68] par bloc de 6 ids ; fallback #94a3b8.
- Draw chronogramme : ctx.fillStyle = getClusterColor(e.cluster) ; getBinColor RETIRE de viz.py.
- tests : test_i71_bubbles_colored_per_cluster + test_gray_fallback remplacent les 2 tests I67 bin ; test_i71_clustercolor_palette_distinct_nearby_ids (port colorsys, adj ≥0.13 / fen |Δid|≤6 ≥0.05).
- tools/color_check.py retargete palette cluster ; gate +C9 → SCORE 10/10 exit 0 ; tools/check.sh CHECK OK (149 tests).
- NEXT : deploy pi-t620 puis GOAL I71 DONE.

## I71 M5 (ce tour — DONE, commit 32afe89)
- Gate LOCAL : SCORE 10/10 exit 0 (C1-C9) — goal « draw par cluster » verifiable et vert.
- Deploy pi-t620 via scripts/deploy_pi.sh : wheel refabrique, pip install force, services active, VERIFY_OK + DEPLOY_OK, health ok (3390 lignes), getClusterColor dans le HTML servi.
- Site distant verifie : /opt/bruittrack/src/bruittrack/viz.py → getClusterColor ×4, getBinColor ×0.
- GOAL I71 DONE.
## I73 (it. 18) — I56 badge MAJ temps relatif (rétablit I53)
- Découverte : le commit I53 (2418242) n'avait rien porté à viz.py (doc-only) ; `majBadge`/`updateMaj()` absents du code.
- Fait : span `#majBadge` + `renderMaj()` (« MAJ il y a Xs » < 60 s, sinon hh:mm:ss TZ_VIZ) + tick 1 s léger `startMajTick()` ; `lastMajTs` posé en fin de `refreshAll()`. Test marqueurs `test_i56_maj_badge_relative_time`.
- Gate : check.sh CHECK OK, 150 tests verts. PROCHAIN : deploy pi-t620 (marker majBadge), sinon I59 fragmentation clustering.
## I74 (it. 20-23) — I59 invariant fingerprint à la dérive du pic
- `fingerprints_match` (events.py) : Δbin=0 strict L1≤2 sur les 5 briques ; Δ≠0 meilleur alignement de profil (δ ∈ {−1,0,+1}) ≥3 briques, distance normalisée |a−b|/max(1,max(a,b)) cumulée ≤ 2 — corrige la fragmentation quand le pic saute d'un bin (saturation du ratio relatif).
- `tools/clusters_check.py --demo` : cas pic+1bin → cluster 1 (match) ; étiquette mise à jour.
- Test régression `test_i59_peak_wobble_shift_invariance` (tests/test_events.py).
- Gate : check.sh CHECK OK, 151 tests verts. PROCHAIN : fusion post-hoc quasi-doublons dans store.py (partie restante I59) ou déployer + scanner la base pi-t620.
## I75 (it. 24) — I59b fusion post-hoc quasi-doublons
- `store.merge_quasi_duplicate_clusters(max_bin_delta, exemplars_dir)` : compare les fp representatives par paire croissante, UPDATE minimum-id canonique, commit explicite, renommage exemplaires ex_<fusi>_* → ex_<canon>_* (flags & FLAG_EXEMPLAR). Retour nb paires.
- pipeline.Engine init : fusion AVANT _load_cluster_index() avec detector.cluster_max_bin_delta ; log nb paires.
- Test regression test_i59_merge_quasi_duplicate_clusters. Gate CHECK OK, 152 tests.
## I76 (it.27) — I59b exemplaire : double schéma de renommage
- _rename_merged_exemplars gère à la fois ex_<c>.raw (nom réel écrit par le détecteur) et ex_<c>_<id>.raw (doc) ; corrige un renommage jamais effectif.
- test_i59b_merge_renames_exemplars vert ; suite store 13/13. Commit suivant gate complète.
## I76 (it.30) — Test de wiring I59b : merge avant reconstitution d'index au démarrage
- test_engine_startup_merges_before_cluster_index (tests/test_pipeline.py) : DB seedée avec 2 clusters quasi-doublons ; après Engine.__init__, l'index n'a plus que le cluster 1.
## I76 (it.31) — Entry decision-log I59b + verifications
- `docs/decision-log.md` : 2 nouvelles entries (invariance de pic — match ; I59b — post-hoc fusion avant rebuild de l'index).
- Commit 14ef902. PROCHAIN : deploy via tools/deploy_pi.sh (marker `merge_quasi_duplicate_clusters`) + smoke M6/M9 pi-t620.
