# GOAL — Chronogramme : couleur des bulles par cluster (reprend I67)

## Fallback rapide (si perdu)
1. `cat PROGRESS.md | tail -30` ; `git log --oneline -5` ; `git status --short`
2. Critère objectif : `bash tools/cluster_color_check.sh` → exit 0 et `SCORE: 10`.

## Objectif
Recolor les bulles du chronogramme (canvas du dashboard, `src/bruittrack/viz.py`)
**par cluster plutôt que par bin** (décision opérateur : même couleur = même
famille de bruit récurrent, cohérent avec le tableau clusters/badges qui
utilisent déjà `getClusterColor`). I67 avait basculé le draw sur `getBinColor` :
cette itération inverse ce choix ET corrige la palette par cluster, trop
faible en l'état (hue angulaire d'or seul → ids éloignés confondus, ex. des
clusters qui partagent une teinte quasi identique).

## État de départ (vérifié, HEAD 00f9564 + WIP incommité I70 — NE PAS ROLLBACK)
- `viz.py:~230` : `getClusterColor(clusterId)` = `hue = (id*137.5)%360`,
  fallback `#94a3b8` ; consommateurs existants : badge du tableau d'événements
  (`getClusterColor(e.cluster)`) et tableau clusters (`getClusterColor(c.cluster_id)`, ×2 sur la ligne).
- `viz.py:~236` : `getBinColor(binI)` (palette discrète I67c, 12 teintes × clarté). Usage UNIQUE :
  ligne de draw `ctx.fillStyle = getBinColor(e.bin_i);` (~L796 du bloc chronogramme).
- `viz.py:~605` : tooltip affiche déjà `#${ev.cluster}` — les lignes `/api/events`
  exposent bien `cluster` (peut être null) : rien à changer côté serveur.
- Tests à mettre en conformité (`tests/test_viz_api.py`) :
  `test_i67_bubbles_colored_per_bin` (marqueurs par bin) et
  `test_i67_bincolor_palette_distinct_nearby_bins` (+ `tools/color_check.py`
  qui porte le port numérique de getBinColor).
- Travail incommité I70 déjà vert dans le WIP : renommage `lx/ly → tipLx/tipLy`
  + `test_served_js_is_valid_syntax`. L'accepter tel quel ; le committer en M0
  avec un message du type « I70 : » s'il est propre (pytest + ruff vert).
- Gate baseline à reconstruire : `bash tools/check.sh` vert (pytest complet).

## Périmètre / contrats exacts (tokens EXACTS attendus dans le HTML servi)
| Marqueur | État exigé |
|---|---|
| `function getClusterColor(clusterId)` | présent (palette améliorée) |
| `ctx.fillStyle = getClusterColor(e.cluster)` | présent (draw canvas — substitut de I68) |
| littéral `getBinColor` n'importe où dans `viz.py` | ABSENT (fonction retirée, aucun usage restant) |
| `#94a3b8` dans le corps de `getClusterColor` | présent (fallback cluster NULL) |

**Contrat palette (testable numériquement, style I67c avec `colorsys.hls_to_rgb`) :**
reproduction Python exakte du JS servi. Propriétés exigées sur les ids 1..29 :
1. couleur(id=0/absent) = gris neutre ; marker : le corps de la fonction
   contient `#94a3b8` et `if (!clusterId)`.
2. ids adjacents (|Δid| = 1) : distance Euclidienne RGB ≥ 0.13.
3. aucune quasi-identique dans une fenêtre compacte |Δid ≤ 6 : distance ≥ 0.05.
Cible de formulation (ajuster les constantes SEULEMENT si un des tests
numériques échoue, sinon gardez-la) :
```js
function getClusterColor(clusterId) {
  if (!clusterId) return "#94a3b8"; // cluster NULL / inconnu
  const h = (clusterId * 137.5) % 360; // angle d'or : ids proches => teintes eloignees
  const l = [45, 68][Math.floor(clusterId / 6) % 2]; // clarte alternee par bloc de 6 ids
  return `hsl(${h}, 85%, ${l}%)`;
}
```
Cette teinte alimente UNIQUEMENT la couleur des bulles ; taille/opacité/anneau
de sélection/invisibilité (I40, I48, I58) inchangés.

## Non-périmètre
- Zéro changement serveur/API/SQLite/pipeline/dsp/events (`store`, `/api/*` intact).
- Pas de dépendance nouvelle ni de bibliothèque JS externe (stdlib + canvas pur).
- Pas de légende cluster/couleur dans le dashboard (→ IMPROVEMENTS, option 16+).
- Pas de changement de zoom/brush/fenêtre/filtre/tooltip (contrats I39–I69 conservés).
- Pas de déploiement HP obligatoire pour valider le goal (deploy = amélioration, pas critère).

## Roadmap jalonnée (1 commit par étape terminée : `git add -A && git commit`)
- **M0 — Baseline** : accepter/committer le WIP I70 tel quel s'il est vert
  (`pytest -q`, `ruff check`) ; noter baseline `bash tools/check.sh` dans
  PROGRESS.md.
- **M1 — Palette par cluster** : remplacer `getClusterColor` par la formule du
  contrat (ou sa variante ajustée) ; test unitaire `test_i71_cluster_color_*`
  dans `tests/test_viz_api.py` : marqueurs de fonction + fallback `#94a3b8` +
  port numérique (colorsys) des propriétés 2 et 3 du contrat, exactement comme
  le test I67c pour bins. Commit.
- **M2 — Basculer le draw** : dans le bloc chronogramme, `
  ctx.fillStyle = getClusterColor(e.cluster)` remplace `getBinColor(e.bin_i)` ;
  RETIRER la fonction `getBinColor` de viz.py (usage unique vérifié en amont
  par grep) ; réécrire/supprimer les tests I67 qui verrouillent le coloriage
  par bin ; mettre à jour `tools/color_check.py` (ou le remplacer par une vérif
  de la palette cluster) — aucune référence orpheline : `rg getBinColor` vide.
  Commit.
- **M3 — Guardes & cohérence** : test de régression : tous les consommateurs
  du dashboard (canvas, badge événements, tableau clusters) passent par
  `getClusterColor` (nombre d'occurrences `getClusterColor(` ≥ 3 dans viz.py)
  ; script `tools/cluster_color_check.sh` est le contract objectif (ci-dessous).
  Commit.
- **M4 — Gate finale** : `bash tools/check.sh` vert (pytest complet + ruff) ;
  `bash tools/cluster_color_check.sh` → « SCORE: 10 » exit 0 ; PROGRESS.md
  mis à jour avec la décision (« couleur par cluster, I71 ») et l'entrée de la
  légende dans IMPROVEMENTS.md. Commit.

## Critères de complétion (objectifs, vérifiés par `bash tools/cluster_color_check.sh`)
« Exit 0 uniquement si « SCORE: 10 » : 5/5 markers + guards + suite + style.
| # | Point(s) | Critère |
|---|---|---|
| C1 | 1 | `function getClusterColor(clusterId)` servi dans le dashoard |
| C2 | 1 | draw canvas : `ctx.fillStyle = getClusterColor(e.cluster)` servi |
| C3 | 1 | zéro occurrence du littéral `getBinColor` dans viz.py |
| C4 | 1 | fallback gris `#94a3b8` + garde `if (!clusterId)` dans la fonction |
| C5 | 1 | cohérence : ≥ 3 occurrences de `getClusterColor(` dans viz.py |
| C6 | 1 | tests verrouillent le coloriage par cluster (marker C2 présent dans
  `tests/test_viz_api.py` ET marqueur d'assertion par bin absent des tests) |
| C7 | 2 | suite pytest complète verte (`pytest -q`) |
| C8 | 1 | `ruff check src/bruittrack/viz.py tests/test_viz_api.py` exit 0 |

## Normes de qualité (maisons)
- Tests déterministes sans matériel : assertions sur `HTML_DASHBOARD`
  (import static depuis `bruittrack.viz`) — style existant I39–I70. Pas de
  snapshot, pas de navigateur.
- Code anglais, messages/CLI français ; docstrings courtes ; aucun nombre
  magique non commenté.
- 1 commit par milestone avec message français qui raconte le WHY (« I71 : »).
- PROGRESS.md mis à jour à chaque changement d'état (état / fait / prochaines étapes).
- Si un test numériquement impossible : relâcher la constante la PLUS proche
  du contrat, NOTER l'écart exact dans PROGRESS.md + ASSUMPTIONS.md.

## Hypothèses explicites (à consigner si contredites en cours de route)
1. `event.cluster` peut être NULL sur des lignes orphelines → bulles gris
   `#94a3b8` plutôt qu'inchangé ; l'écrasement de couleur ne change rien aux
   autres propriétés du draw.
2. ≤ ~27 clusters simultanés en pratique : la palette à cycle 13+6 (ou
   équivalent de formulation) suffit ; au-delà, une répétition de teinte à > 26
   ids d'écart est ACCEPTÈE (propriété 3 reste vraie).
3. WIP I70 incommité est validé ET accepté tel quel : le goal ne le refait pas.
4. `tools/color_check.py` devient caduque s'il vérifie uniquement la palette
   bin : le supprimer ou le rebrancher sur la palette cluster est autorisé,
   mais ne PAS laisser un script mort qui échoue/silencieusement diverge.
5. Le check du goal ne nécessite PAS de serveur démarré (markers + pytest seule
   + ruff) ; le dashboard continue de se valider manuellement via `viz --port`.
