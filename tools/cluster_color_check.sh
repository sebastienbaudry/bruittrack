#!/usr/bin/env bash
# Fonction objectif — GOAL « chronogramme : couleur des bulles par cluster ».
# Usage : bash tools/cluster_color_check.sh   (depuis la racine du repo)
# Sort : "SCORE: n/10" ; exit 0 uniquement si 10/10 (C1-C8 tous verts).
set -u
D=$(dirname "$0")
ROOT="$D/.."
cd "$ROOT"

VIZ=src/bruittrack/viz.py
TST=tests/test_viz_api.py
score=0
ok()  { echo "  [ok] $1"; score=$((score + 1)); }
okw() { echo "  [ok] $1 (+$2)"; score=$((score + $2)); }
ko()  { echo "  [KO] $1"; }
echo "== cluster-color check (GOAL.md I71) =="

# C1 — la fonction palette par cluster est servie dans le dashboard [1]
if grep -qF 'function getClusterColor(clusterId)' "$VIZ"; then
  ok "C1 getClusterColor presente"
else ko "C1 getClusterColor absente de viz.py"; fi

# C2 — le draw canvas colore par cluster [1]
if grep -qF 'ctx.fillStyle = getClusterColor(e.cluster)' "$VIZ"; then
  ok "C2 draw canvas par cluster"
else ko "C2 draw n'utilise pas getClusterColor(e.cluster)"; fi

# C3 — aucun residu du coloriage par bin dans viz.py [1]
if grep -qF 'getBinColor' "$VIZ"; then
  ko "C3 getBinColor toujours presente dans viz.py"
else ok "C3 getBinColor retiree"; fi

# C4 — fallback neutre pour cluster NULL [1]
if grep -qF '#94a3b8' "$VIZ" && grep -qF 'if (!clusterId)' "$VIZ"; then
  ok "C4 fallback gris + garde !clusterId"
else ko "C4 fallback cluster NULL manquant"; fi

# C5 — cohérence dashboard : >= 3 consommateurs getClusterColor( [1]
n=$(grep -oF 'getClusterColor(' "$VIZ" | wc -l)
if [ "$n" -ge 3 ]; then
  ok "C5 cohérence ($n usages getClusterColor)"
else ko "C5 seulement $n usage(s) de getClusterColor (< 3)"; fi

# C6 — les tests verrouillent le coloriage par cluster [1]
if grep -qF 'ctx.fillStyle = getClusterColor(e.cluster)' "$TST" && ! grep -qF 'ctx.fillStyle = getBinColor' "$TST"; then
  ok "C6 tests alignés sur le coloriage par cluster"
else ko "C6 tests pas (encore) alignés sur le coloriage par cluster"; fi

# C7 — suite pytest complete verte [2]
if [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY=python; fi
if "$PY" -m pytest -q --no-header >/tmp/cluster_color_pytest.log 2>&1; then
  okw "C7 suite pytest complete verte" 2
else ko "C7 suite pytest rouge (details : /tmp/cluster_color_pytest.log)"; fi

# C8 — ruff propre sur les fichiers du goal [1]
if "$PY" -m ruff check "$VIZ" "$TST" >/dev/null 2>&1; then
  ok "C8 ruff clean"
else ko "C8 ruff non conforme sur viz.py / test_viz_api.py"; fi

# C9 — proprietes numeriques palette : ids adjacents >= 0.13, fenetre |Δid|<=6 >= 0.05 [1]
if "$PY" tools/color_check.py --max-id 29 --min-adjacent 0.13 >/tmp/cluster_color_c9.log 2>&1; then
  ok "C9 proprietes numeriques palette (T1)"
else ko "C9 palette non discriminante (details : /tmp/cluster_color_c9.log)"; fi

echo "SCORE: $score/10"
[ "$score" -eq 10 ] && exit 0 || exit 1
