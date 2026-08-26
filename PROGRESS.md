# PROGRESS — couleur par bin (getBinColor) + déploiement

## État
- I67b commit `edac3da` : palette discontinue 12 teintes × 30°, L alternée [50,67] — bins adjacents distincts.
- I67c commit `699fa35` : test regression palette (`tests/test_viz_api.py`) + `tools/color_check.py`. Gate verte : 144 tests, ruff OK, check.sh OK.
- Arbo worked tree clean. Déploiement pi-t620 demandé (it. 14).

## Fait (essais/échecs)
- Vérif numérique HSL→RGB bins 1..75 : min dist RGB adjacents = 0.264 (paires 15/16) ; doublons exacts seulement à 24 bins d'écart (~11.7 Hz, non adjacents visuellement).
- I53 majBadge/updateMaj absent de src malgré commit doc 2418242 → item I56 reste ouvert (re-faire si temps).

## Prochaines étapes
1. Déployer sur pi-t620 : `bash scripts/deploy_pi.sh` (vérifier marker I67 getBinColor après déploiement ; DEPLOY_OK attendu). «
2. Après OK : noter it. 14 + commit si artefacts modifs (PROGRESS/IMPROVEMENTS).
3. Suite loop : I56 badge MAJ relatif (relMaj) ou I59 clustering meilleur alignement.
