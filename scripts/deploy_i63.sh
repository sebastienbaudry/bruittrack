#!/bin/bash
# I63 : deploiement historique spectre → pi-t620 (wheel + config idempotente + verifs)
set -euo pipefail
cd "$(dirname "$0")/.."
HOST=pi-t620
WHL=dist/bruittrack-1.0.0-py3-none-any.whl
TS=$(date +%s)
REMOTE="/tmp/bruittrack-$TS-py3-none-any.whl"

echo "== gate locale : tests + ruff =="
python -m pytest -q 2>&1 | tail -n 1
python -m ruff check . >/dev/null && echo RUFF_OK

echo "== build wheel locale =="
python -m pip wheel . --no-deps -w dist -q
[ -f "$WHL" ] || { echo "FATAL: $WHL absent"; exit 1; }

echo "== upload =="
ssh -o ControlPath=none -o ConnectTimeout=15 "$HOST" hostname
scp -o ControlPath=none "$WHL" "$HOST:$REMOTE" || { echo "FATAL: upload echoue"; exit 4; }

echo "== install + config + restart =="
ssh -o ControlPath=none "$HOST" bash -s -- "$REMOTE" <<'EOR'
set -euo pipefail
PASS='passLinux1!'
cd /opt/bruittrack
echo "$PASS" | sudo -S -p '' ./.venv/bin/python3 -m pip install --force-reinstall --no-deps "$1" 2>&1 | tail -n 2
rm -f "$1"
# [spectrum] : injection idempotente si absente du config.toml distant
if ! grep -q '^\[spectrum\]' config.toml; then
  echo "$PASS" | sudo -S -p '' tee -a config.toml > /dev/null <<'CFG'

[spectrum]
enabled = true
interval_s = 60.0
n_bands = 24
db_min = -140.0
db_range = 160.0
retention_days = 0
CFG
  echo "CONFIG_SPECTRUM_AJOUTEE"
else
  echo "CONFIG_SPECTRUM_DEJA_PRESENTE"
fi
grep -A3 '^\[spectrum\]' config.toml | head -n 5
echo "$PASS" | sudo -S -p '' systemctl restart bruittrack bruittrack-viz
sleep 5
systemctl is-active bruittrack bruittrack-viz
echo RESTART_OK
EOR

echo "== verify : health, table spectrum, API, HTML markers =="
ssh -o ControlPath=none "$HOST" <<'VEOF'
curl -sf http://127.0.0.1:8760/api/health || exit 2
# table migrée dans la DB ?
/opt/bruittrack/.venv/bin/python3 -c "import sqlite3,sys; c=sqlite3.connect('/opt/bruittrack/data/bruittrack.db'); n=c.execute(\"SELECT count(*) FROM sqlite_master WHERE type='table' AND name='spectrum'\").fetchone()[0]; sys.exit(0 if n==1 else 3)" \
  || { echo "FATAL: table spectrum absente"; exit 3; }
# API répond avec la clé rows ?
curl -sf http://127.0.0.1:8760/api/spectrum | grep -q '"rows"' || { echo "FATAL: /api/spectrum KO"; exit 4; }
HTML=$(curl -s http://127.0.0.1:8760/)
for tok in toggleSpec drawSpecPanel specCanvas SPEC.enabled; do
  echo "$HTML" | grep -q "$tok" || { echo "FATAL: marker $tok absent du HTML servi"; exit 5; }
done
/opt/bruittrack/.venv/bin/python3 -m pip check
echo VERIFY_OK
VEOF

echo "DEPLOY_OK_I63"
