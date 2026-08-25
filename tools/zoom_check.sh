#!/usr/bin/env bash
# I54 — check de la boucle « zoom 2 axes + fenêtrage des données ».
# Utilise le template local (tests) ; B2 optionnel via pi-t620 si joignable.
# Print « SCORE: n/8 » ; exit 0 dès que les 6 critères core sont atteints.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." 2>/dev/null && pwd || pwd)"
cd "$ROOT"
score=0
report() { printf '  [%s] %s\n' "$1" "$2"; }

html="$(python -c "
import sys
sys.path.insert(0, 'src')
from bruittrack.viz import HTML_DASHBOARD
print(HTML_DASHBOARD(freq_max=150.0, min_event_hz=2.0))
" 2>/dev/null)"
if [ -z "$html" ]; then
  html="$(cat src/bruittrack/viz.py)"
fi
has() { case "$html" in *"$1"*) return 0 ;; *) return 1 ;; esac; }

# Z1 — état vue fréquence + zoom molette axe Y
if has 'let freqView' && has 'axZoom('; then
  score=$((score+1)); report '+' 'Z1 tokens vue/zoom (let freqView, axZoom('
else
  report x 'Z1 tokens vue/zoom'
fi

# Z2 — fenêtrage dynamique des données
if has 'fetchWindow(' && printf '%s' "$html" | grep -q 'since='; then
  score=$((score+1)); report '+' 'Z2 fetchWindow( + since='
else
  report x 'Z2 fetchWindow( + since='
fi

# Z3 — pan fréquence (Ctrl+drag)
if has 'panFreqBy('; then
  score=$((score+1)); report '+' 'Z3 panFreqBy('
else
  report x 'Z3 panFreqBy('
fi

# Z4 — régression marqueurs existants + suites vertes
reg_ok=1
for m in 'toggleChannel' 'evtTip' 'timelinePoints' 'showCh'; do
  has "$m" || { reg_ok=0; break; }
done
if [ "$reg_ok" = 1 ] && python -m ruff check . >/dev/null 2>&1 && \
   python -m pytest tests -q --no-header >/dev/null 2>&1; then
  score=$((score+1)); report '+' 'Z4 marqueurs existants + ruff + pytest verts'
else
  report x 'Z4 régression (marqueurs / ruff / pytest)'
fi

# Z5 — tableau plafonné 500 + badge vue
if has 'renderTableRow(' && has 'zoomBadge'; then
  score=$((score+1)); report '+' 'Z5 renderTableRow( + zoomBadge'
else
  report x 'Z5 renderTableRow( + zoomBadge'
fi

# Z6 — tests dédiés zoom
if python -m pytest tests -q --no-header -k 'viz_zoom_markers' 2>/dev/null | grep -q 'passed'; then
  score=$((score+1)); report '+' 'Z6 tests -k viz_zoom_markers passent'
else
  report x 'Z6 tests -k viz_zoom_markers'
fi

core=$([ "$score" -ge 6 ] && echo oui || echo non)

# B1 — docs (bonus)
if grep -q 'axZoom\|molette' docs/decision-log.md 2>/dev/null && \
   grep -qi 'zoom' README.md 2>/dev/null; then
  score=$((score+1)); report '+' 'B1 docs (decision-log + README)'
else
  report '~' 'B1 bonus docs pas encore'
fi

# B2 — pi-t620 (bonus, optionnel réseau)
b2cmd='curl -s localhost:8760 2>/dev/null'
if command -v ssh >/dev/null 2>&1 && \
   ssh -o BatchMode=yes -o ConnectTimeout=4 pi-t620 "$b2cmd" | grep -q 'axZoom('; then
  score=$((score+1)); report '+' 'B2 pi-t620 sert axZoom('
else
  report '~' 'B2 bonus pi-t620 (injoignable ou pas déployé)'
fi

echo "SCORE: $score/8 (core: $core)"
[ "$score" -ge 6 ] && exit 0 || exit 1
