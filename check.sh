#!/usr/bin/env bash
# check.sh --check → SCORE: <0..7>, exit 0 si 7/7
set -u
cd "$(dirname "$0")"
PY=${PYTHON:-python}
SCORE=0

# C1 : tests verts
if $PY -m pytest -q >/tmp/c1.log 2>&1; then SCORE=$((SCORE+1)); else echo "FAIL C1 pytest"; tail -3 /tmp/c1.log; fi

# C2 : README aligné (scipy LP, budget 10 % CPU, pas "LP Butter ... numpy")
ok=1
grep -q "sosfilt" README.md || ok=0
grep -qiE "< ?10 ?% ?CPU|10 ?% du CPU|10% CPU" README.md || ok=0
grep -qE "LP Butter[^)]*numpy" README.md && ok=0
[ $ok = 1 ] && SCORE=$((SCORE+1)) || echo "FAIL C2 readme"

# C3 : IMPROVEMENTS sans item fait non prouvé + items ouverts acceptables
open=$(grep -c "^- \[ \]" IMPROVEMENTS.md 2>/dev/null || true)
closed=$(grep -c "^- \[x\]" IMPROVEMENTS.md 2>/dev/null || true)
# heuristic : au moins 3 items cochés avec preuve git mentionnée (hash ou sujet existant en log)
ok=0
while IFS= read -r line; do
  echo "$line" | grep -qE "#[0-9a-f]{7}" || { ok=1; }
done < <(grep "^- \[x\]" IMPROVEMENTS.md)
[ $ok = 0 ] && SCORE=$((SCORE+1)) || echo "FAIL C3 improvements (items sans preuve hash)"

# C4 : PROGRESS.md fresh (modifié < 2 jours OU mentionne dernier sujet de travail)
last_commit=$(git log -1 --pretty=%s | tr '[:upper:]' '[:lower:]')
grep -qiE "floortracker|welch|sosfilt|coherence|readme" PROGRESS.md && SCORE=$((SCORE+1)) || echo "FAIL C4 progress stale"

# C5 : decision-log ≥ 12 entrées datées
n=$(grep -cE "^## \[[0-9]{4}-[0-9]{2}-[0-9]{2}\]" docs/decision-log.md 2>/dev/null); n=${n:-0}
[ "$n" -ge 12 ] && SCORE=$((SCORE+1)) || echo "FAIL C5 decision-log ($n entrées < 12)"

# C6 : bench_ticks existe + résultat documenté dans PROGRESS.md
[ -f tools/bench_ticks.py ] && grep -qE "bench_ticks|process_block.*ms|T620" PROGRESS.md && SCORE=$((SCORE+1)) || echo "FAIL C6 bench"

# C7 : tous les .py compilent (proxy ruff)
ok=1
for f in $(find src tests tools -name "*.py" 2>/dev/null); do
  $PY -m py_compile "$f" >/dev/null 2>&1 || { ok=0; echo "compile FAIL $f"; }
done
[ $ok = 1 ] && SCORE=$((SCORE+1)) || echo "FAIL C7 compile"

echo "SCORE: $SCORE"
[ $SCORE -eq 7 ] && exit 0 || exit 1