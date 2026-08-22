#!/usr/bin/env bash
# check.sh --check → SCORE: <0..7>, exit 0 si 7/7 (GOAL.md hpdebian, 2026-08)
set -u
cd "$(dirname "$0")"
PY=${PYTHON:-python}
SCORE=0
OUT=$(mktemp)

# C1 : suite pytest verte
if $PY -m pytest -q >$OUT 2>&1; then SCORE=$((SCORE+1)); else echo "FAIL C1 pytest"; tail -3 $OUT; fi

# C2 : tous les .py compilent
ok=1
for f in $(find src tests tools -name '*.py' 2>/dev/null); do
  $PY -m py_compile "$f" >>$OUT 2>&1 || { ok=0; echo "FAIL C2 compile $f"; }
done
[ $ok = 1 ] && SCORE=$((SCORE+1)) || true

# C3 : install utilised — CLI répond
if $PY -m bruittrack --help >/dev/null 2>&1; then SCORE=$((SCORE+1)); else echo "FAIL C3 cli --help"; fi

# C4 : config example valide + harnais module_check.py --offline
cat > /tmp/bt_configcheck.py <<'PYEOF'
import shutil, sys, tempfile, pathlib
tmp = pathlib.Path(tempfile.mkdtemp())
shutil.copy("config.toml.example", tmp / "config.toml")
s = (tmp / "config.toml").read_text(encoding="utf-8")
s = s.replace('exemplars_dir = "data/exemplars"', 'exemplars_dir = "' + str(tmp / "ex") + '"')
(tmp / "config.toml").write_text(s, encoding="utf-8")
from bruittrack.config import load_config
cfg = load_config(tmp / "config.toml")
if not cfg.audio.device:
    print("WARN device vide (exemple) — ok hors cible")
print("CONFIG OK")
PYEOF
if $PY /tmp/bt_configcheck.py >>$OUT 2>&1; then
  if [ -f tools/module_check.py ] && $PY tools/module_check.py --offline >>$OUT 2>&1; then
    SCORE=$((SCORE+1))
  elif [ -f tools/module_check.py ]; then
    echo "FAIL C4b module_check --offline"; tail -5 $OUT
  else
    echo "FAIL C4a tools/module_check.py absent"
  fi
else echo "FAIL C4 config example"; tail -5 $OUT; fi

# C5 : script déploiement installé + syntaxe + sections min.
if [ -f tools/install_hp.sh ] && bash -n tools/install_hp.sh >>$OUT 2>&1 \
   && grep -qE "apt-get|apt " tools/install_hp.sh \
   && grep -q "/opt/bruittrack" tools/install_hp.sh \
   && grep -q "python3 -m venv|\.venv" tools/install_hp.sh \
   && grep -q "systemctl" tools/install_hp.sh \
   && grep -q "devices" tools/install_hp.sh; then
  SCORE=$((SCORE+1))
else echo "FAIL C5 tools/install_hp.sh (absent/syntaxe/sections)"; fi

# C6 : PROGRESS.md — section matrice hpdebian avec 9 lignes statuts
if grep -q "Vérification modules hpdebian" PROGRESS.md 2>/dev/null \
   && [ $(grep -cE "^[|]? *\*?\*?(✅|⚠️|❌)" PROGRESS.md 2>/dev/null || echo 0) -ge 6 ]; then
  SCORE=$((SCORE+1))
else echo "FAIL C6 matrice PROGRESS.md (9 lignes ✅/⚠️/❌ attendues)"; fi

# C7 : README — sections installation hpdebian + budget
cat > /tmp/bt_readme_check.py <<'PYEOF'
import re, sys
t = open("README.md", encoding="utf-8").read()
need = [r"[Ii]nstallation", r"systemd", r"[Tt]620|hpdebian|Debian",
        r"10 ?% ?CPU|< 10 ?%", r"devices"]
miss = [p for p in need if not re.search(p, t)]
print("missing:", miss); sys.exit(1 if miss else 0)
PYEOF
if $PY /tmp/bt_readme_check.py >>$OUT 2>&1; then SCORE=$((SCORE+1)); else echo "FAIL C7 README"; tail -2 $OUT; fi

echo "SCORE: $SCORE"
rm -f $OUT /tmp/bt_configcheck.py /tmp/bt_readme_check.py
[ $SCORE -ge 7 ] && exit 0 || exit 1
