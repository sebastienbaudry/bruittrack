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