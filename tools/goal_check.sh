#!/usr/bin/env bash
# Verifie les items du backlog (I30, I35-I41) decrits dans GOAL.md.
# Usage : bash tools/goal_check.sh [--json]
# Score : CORE = 8 pts (C1..C8), bonus B1+B2 (+2) → MAX=10.
# Exit 0 si les 8 core sont atteints, sinon 1 ; erreur technique = 2.
set -uo pipefail
cd "$(dirname "$0")/.." || { printf 'ERROR: unable to locate repo root\n'; exit 2; }
PY="${PYTHON:-python}"
JSON=0
[ "${1:-}" = "--json" ] && JSON=1
CORE=8; MAX=10
RESULTS_FILE="$(mktemp)"; trap 'rm -f "$RESULTS_FILE"' EXIT

add() { # add <code> <passed 0|1> <detail...>
  local code="$1" passed="$2"; shift 2
  printf '%s\t%s\t%s\n' "$code" "$passed" "$*" >> "$RESULTS_FILE"
}
file_nonempty() { [ -f "$1" ] && [ -s "$1" ]; }
html_has_token() { # html_has_token <token...> : tous presents dans HTML_DASHBOARD
  "$PY" - "$@" <<'PYEOF'
import sys
sys.path.insert(0, "src")
from bruittrack.viz import HTML_DASHBOARD
sys.exit(0 if all(tok in HTML_DASHBOARD for tok in sys.argv[1:]) else 1)
PYEOF
}
passed_count() { # passed_count <kword...> : nb tests passes pour la selection pytest -k
  local kw="${*:-}"
  "${PY}" -m pytest -q -k "${kw}" --tb=no -p no:cacheprovider 2>/dev/null | tail -n 1 | grep -oE '[0-9]+ passed' | grep -oE '^[0-9]+' || echo 0
}

echo "=== BruitTrack goal check - $(date '+%F %T') ==="; echo

# --- C1 (I35) : bornes de frequence en config + tests ---------------------
C1_OK=0
if [ -f src/bruittrack/config.py ] \
  && grep -q 'min_event_hz' src/bruittrack/config.py \
  && grep -qE 'freq_max[[:space:]]*=[[:space:]]*150\.0' src/bruittrack/config.py; then
  C1N=$(passed_count "respects_min_event_hz or respects_freq_max")
  [ "${C1N:-0}" -ge 2 ] 2>/dev/null && C1_OK=1
fi
add C1 "$C1_OK" "I35 config min_event_hz + freq_max=150.0 par defaut + >=2 tests band"

# --- C2 (I36) : documentation ---------------------------------------------
C2_OK=0; N_DOC=0
for f in AGENTS.md docs/decision-log.md config.toml.example README.md; do
  [ -f "$f" ] && grep -q 'min_event_hz' "$f" && N_DOC=$((N_DOC+1))
done
[ "$N_DOC" -ge 4 ] && C2_OK=1
add C2 "$C2_OK" "I36 token min_event_hz present dans ${N_DOC}/4 fichiers docs"

# --- C3 (I37) : purge SQL + README ------------------------------------------
C3_OK=0
if file_nonempty scripts/purge_lowfreq.sql \
  && grep -q 'DELETE FROM events' scripts/purge_lowfreq.sql \
  && grep -q 'freq' scripts/purge_lowfreq.sql \
  && [ -f README.md ] && grep -qiE 'purge|lowfreq' README.md; then
  C3_OK=1
fi
add C3 "$C3_OK" "I37 scripts/purge_lowfreq.sql + mention README"

# --- C4 (I38) : boutons d'echelle temps ------------------------------------
C4_OK=0
html_has_token 'winBtn1h' 'winBtn6h' 'winBtn24h' 'winBtnTout' 'drawTimeTicks' && C4_OK=1
add C4 "$C4_OK" "I38 boutons 1h/6h/24h/Tout + drawTimeTicks dashboard"

# --- C5 (I39) : fenetre glissante + brush ----------------------------------
C5_OK=0
html_has_token 'tlMode' 'brushZoom(' && C5_OK=1
add C5 "$C5_OK" "I39 tlMode + brushZoom()"

# --- C6 (I40) : liaison scatter ↔ table --------------------------------------
C6_OK=0
html_has_token 'selectEvent' 'data-evt=' 'evt-hl' 'scrollIntoView' && C6_OK=1
add C6 "$C6_OK" "I40 selectEvent + data-evt + evt-hl + scrollIntoView"

# --- C7 (I41) : filtres rapides --------------------------------------------
C7_OK=0
html_has_token 'fChannel' 'fMinLvl' 'fCluster' 'applyFilters' && C7_OK=1
add C7 "$C7_OK" "I41 fChannel/fMinLvl/fCluster/applyFilters"

# --- C8 (I30) : artefact release + tag ---------------------------------------
C8_OK=0; ART="-"
file_nonempty .github/release.md && ART=.github/release.md
[ -s scripts/create_release.py ] 2>/dev/null && [ "${ART}" = "-" ] && ART=scripts/create_release.py
if [ "$ART" != "-" ] && git tag -l | grep -qE '^v1\.0\.0$'; then C8_OK=1; fi
add C8 "$C8_OK" "I30 artefact release ${ART} + tag v1.0.0"

# --- B1 (bonus I41) : test API chan/min_lvl ----------------------------------
B1_OK=0
B1N=$(passed_count 'events_api_chan_and_minlvl')
[ "${B1N:-0}" -ge 1 ] 2>/dev/null && B1_OK=1
add B1 "$B1_OK" "B1 test events_api_chan_and_minlvl qui passe"

# --- B2 (bonus I30) : release publiee sur GitHub ------------------------------
B2_OK=0
if command -v curl >/dev/null 2>&1; then
  B2_JSON=$(curl -sf --max-time 5 "https://api.github.com/repos/sebastienbaudry/bruittrack/releases" 2>/dev/null | "${PY}" -c '
import json,sys
data=json.load(sys.stdin)
print(sum(1 for r in data if r.get("tag_name")=="v1.0.0"))
' 2>/dev/null || echo 0)
  [ "${B2_JSON:-0}" -ge 1 ] 2>/dev/null && B2_OK=1
fi
add B2 "$B2_OK" "B2 release v1.0.0 visible sur l'API GitHub (bonus reseau)"

# --- rapport ------------------------------------------------------------------
SCORE=0; CORE_OK=0
while IFS=$'\t' read -r code passed detail; do
  [ -n "$code" ] || continue
  case "$code" in C*) [ "$passed" = 1 ] && CORE_OK=$((CORE_OK+1)) ;; esac
  [ "$passed" = 1 ] && SCORE=$((SCORE+1))
done < "$RESULTS_FILE"

if [ "$JSON" = 1 ]; then
  "${PY}" - "$RESULTS_FILE" <<'PYEOF'
import json, sys
rows = []
for line in open(sys.argv[1], encoding="utf-8"):
    parts = line.rstrip("\n").split("\t", 2)
    if len(parts) == 3:
        rows.append({"check": parts[0], "passed": parts[1] == "1", "detail": parts[2]})
print(json.dumps([r for r in dict((r["check"], r) for r in reversed(rows)).values()], ensure_ascii=False, indent=2))
PYEOF
else
  while IFS=$'\t' read -r code passed detail; do
    [ -n "$code" ] || continue
    printf '  [%s] %s : %s\n' "$( [ "$passed" = 1 ] && printf '\u2713' || printf '\u2717' )" "$code" "$detail"
done < "$RESULTS_FILE"
  echo
fi
echo "SCORE: ${SCORE}/${MAX} (core: ${CORE_OK}/${CORE})"
[ "$CORE_OK" -ge "$CORE" ]
