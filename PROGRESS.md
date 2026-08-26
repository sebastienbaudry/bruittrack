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
