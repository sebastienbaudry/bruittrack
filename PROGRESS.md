# PROGRESS — I68 (hover tip précision) après I67 + déploiement

## État
- Loop « précision texte survol points » : diagnostic = hit-test 10 px fixe du centre + deux bulles proches disputant le tooltip. Correction I68.
- Gate verte : ruff OK, **145 tests passés**, check.sh OK.

## Fait (essais/échecs)
- I68 : `timelinePoints` porte désormais `r` (rayon visuel) ; hit-test par point `max(12, r+3)` px ; verrou `hoverLockId` (change seulement en sortant du rayon) → texte stable sur des bulles voisines.

## Prochaines étapes
1. Commit I68 (le cas échéant) puis `bash scripts/deploy_pi.sh` si déploiement demandé ; markers attendus : hoverLockId, r: radius.
2. Suite loop : I56 badge MAJ relatif ou I59 clustering alignement.

