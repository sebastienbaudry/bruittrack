# DSP-REVIEW — Analyse en profondeur de `src/bruittrack/dsp.py`

**Date :** 25 août 2026 · **Périmètre :** `dsp.py` (368 lignes) + interactions aval (`events.py`)
**Méthode :** lecture statique complète + vérifications numériques exécutées contre références indépendantes (`scipy.signal.butter`, `sosfilt`, `numpy.median`, implémentation float64 du Welch).
**Verdict : ✅ pipeline mathématiquement correct — aucun défaut nécessitant une correction.**

---

## 1. Conception du filtre de Butterworth — `design_butterworth_lp_sos`

| Contrôle | Résultat |
|---|---|
| Valeurs Q des 4 paires de pôles (ordre 8) | ✅ 2.563 / 0.900 / 0.601 / 0.510 = valeurs canoniques |
| Transformation bilinéaire pré-déformée (dérivation refaite à la main : `a1 = 2(k²−1)/denom`, `a2 = (1−k/Q+k²)/denom`) | ✅ coefficients exacts |
| Réponse en fréquence vs `scipy.signal.butter(8, 400 Hz)` | ✅ écart max **1,5e-11 dB** sur toute la bande |
| Gain DC par section | ✅ exactement 1,0 |

## 2. `SosFilter` (Direct Form II Transposed)

- Voie scipy (rapide) et voie fallback scalaire **bit-identiques**, y compris à travers les frontières de blocs (continuité d'état `zi` vérifiée sur deux blocs enchaînés).
- **Adequation anti-repliement** : atténuation −63,7 dB à 1 kHz. Pour contaminer la bande d'analyse (≤150 Hz) après décimation ×48, il faudrait de l'énergie à ±150 Hz des multiples de 1 kHz → atténuée ≥ −52 dB dans le pire cas (850 Hz). Négligeable devant le seuil de détection de 10 dB.

## 3. Welch + décimation — `DspPipeline`

- 7 segments : `(8192−2048)/1024+1 = 7` ✓ conforme docs ; pic détecté au bon bin (sinus 40 Hz → bin 40,04 Hz) ✓ ; bins ≤150 Hz exacts (n_bins = 308, dernière bin 149,90 Hz).
- **Précision float32** (seul doute potentiel réel) : erreur médiane **1e-6 dB**, max ~0,0000 dB vs implémentation float64 de référence (100 blocs × 308 bins, filtrage identique, seul le stockage buffer/fenêtre/FFT diffère). Sans impact.
- Décimation `filtered[::48]` sans étage demi-bande supplémentaire : justifié par l'analyse anti-repliement ci-dessus.

## 4. `FloorTracker`

- Seed au tick 0 vérifié : historique complet rempli avec la 1ère frame → pas de plancher zéro transient.
- `_median_last` = *lower median* pour N pair — conforme au commentaire du code ; écart mesuré vs vraie médiane ≤ **0,29 dB** (choix documenté, déterministe).
- Layout mémoire (bins × temps) contigu comme affirmé en commentaire ✓.

## 5. `compute_channel_delay_ms`

- Convention de signe **vérifiée empiriquement** : gauche en avance de D échantillons → +D ms exactement (D = 1, 3, 5 testés sur signaux purs) ✓ cohérent avec docstring, tests unitaires (`test_left_leads_positive`…) et encodage fingerprint (classes ±20 ms).
- Note méthodologique : deux premiers harnais ad hoc donnaient des résultats faux par construction (bruits indépendants sans corrélation ; canal NaN via assignation de `None`) — le module est resté correct dans tous les cas propres.
- Bornes : clamp final redondant mais sûr ; résolution 1 ms @1 kHz cohérente avec la quantification fingerprint.

## 6. Cohérence aval

- Le détecteur exclut le bin DC et les bins < `min_event_hz` : `min_bin = max(1, ceil(2.0/0.488)) = 5` (`events.py:227`), fenêtre `[min_bin .. max_event_hz/bin+1]` ✓ conforme AGENTS.md.
- Couverture tests existante : design SOS, fast/scalar équivalents, identification fréquence, floor, délai (2 sens), benchmark < 50 ms, warning fallback (`tests/test_dsp.py`, 9 tests).

## 7. Observations mineures (non-bugs, aucune action requise)

1. **Échelle absolue arbitraire** : `p = |X|²/Σw²` omet les facteurs `1/fs` et de gain cohérent — les dB ne sont pas des unités physiques. Sans conséquence puisque tout l'aval n'utilise que des différences (émergence) ; à documenter avant toute calibration dB SPL.
2. **Hann symétrique** (`N−1` au dénominateur) au lieu de périodique (choix scipy.welch) : COLA non parfaitement satisfait au hop N/2 → ripple < 0,01 dB. Cosmétique.
3. **EMA sur les dB** (moyenne géométrique) : choix cohérent — le floor historise aussi les valeurs lissées en dB, les différences restent apples à apples.
4. `np.roll` copie les 64 Ko du buffer à chaque tick : largement dans le budget T620 (<15 % CPU / 150 Mo) ; indexation circulaire possible en micro-optimisation.
5. Voie fallback scalaire redondante (scipy est une dépendance dure dans `pyproject.toml`) : inoffensive, utile en environnement dégradé.
6. `freqs` stockées en float32 : précision largement suffisante pour une résolution de 0,49 Hz.

## 8. Récapitulatif des vérifications exécutées

```
design vs scipy.butter ............ écart max 1.5e-11 dB
gain DC par section ............... 1.0 exact (×4)
fast path vs scalar path .......... bit-identique (2 blocs enchaînés)
pic sinus 40 Hz ................... bin 40.04 Hz ✓
précision f32 vs f64 (Welch) ...... médiane 1e-6 dB
floor vs lower-median ............. allclose True
floor vs true-median (N pair) ..... ≤ 0.29 dB (documenté)
délai left-leads D=1/3/5 .......... +1/+3/+5 ms exact
min_bin détecteur ................. 5 (DC exclu)
```
