#!/bin/bash
# I64 : deploiement exemplaires desactivables → pi-t620 (wheel + record_exemplars=false + verifs)
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
if grep -q '^record_exemplars' config.toml; then
  echo "CONFIG_RECORD_EXEMPLARS_DEJA_PRESENT"
else
  sudo sed -i '/^\[storage\]/a record_exemplars = false' config.toml
  echo "CONFIG_RECORD_EXEMPLARS_AJOUTEE"
fi
grep -B1 -A1 'record_exemplars' config.toml || true
echo "$PASS" | sudo -S -p '' systemctl restart bruittrack bruittrack-viz
sleep 5
systemctl is-active bruittrack bruittrack-viz
echo RESTART_OK
EOR

echo "== verify : health, exemplaires desactives =="
ssh -o ControlPath=none "$HOST" <<'VEOF'
curl -sf http://127.0.0.1:8760/api/health || exit 2
HTML=$(curl -s http://127.0.0.1:8760/)
echo "$HTML" | grep -q 'EXEMPLARS_ENABLED = false' || { echo "FATAL: EXEMPLARS_ENABLED != false dans le HTML servi"; exit 5; }
/opt/bruittrack/.venv/bin/python3 -m pip check
/opt/bruittrack/.venv/bin/python3 - <<'PY'
import glob, os
d = '/opt/bruittrack/data/exemplars'
fs = sorted(glob.glob(d + '/ex_*.raw'), key=os.path.getmtime)
print('nb exemplaires:', len(fs))
for f in fs[-5:]:
    import time
    print(os.path.basename(f), os.path.getsize(f), 'o', time.strftime('%Y-%m-%d %H:%M', time.gmtime(os.path.getmtime(f))))
PY
echo VERIFY_OK
VEOF

echo "DEPLOY_OK_I64"
