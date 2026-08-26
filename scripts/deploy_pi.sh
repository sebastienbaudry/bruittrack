#!/bin/bash
# I51 : deploiement pi-t620 idempotent (wheel PEP427 + sudo install + verifs)
set -euo pipefail
cd "$(dirname "$0")/.."
HOST=pi-t620
WHL=dist/bruittrack-1.0.0-py3-none-any.whl
TS=$(date +%s)
REMOTE="/tmp/bruittrack-$TS-py3-none-any.whl"
echo "== build wheel locale =="
python -m pip wheel . --no-deps -w dist -q
[ -f "$WHL" ] || { echo "FATAL: $WHL absent"; exit 1; }
echo "== upload (nom PEP427 conforme) =="
ssh -o ControlPath=none -o ConnectTimeout=15 "$HOST" hostname
scp -o ControlPath=none "$WHL" "$HOST:$REMOTE" || { echo "FATAL: upload echoue — relancer"; exit 4; }
echo "== install + restart (sudo) =="
SSH_OPTS='-o ControlPath=none'
ssh $SSH_OPTS "$HOST" bash -s -- "$REMOTE" <<'EOR'
set -euo pipefail
PASS='passLinux1!'
cd /opt/bruittrack
echo "$PASS" | sudo -S -p '' ./.venv/bin/python3 -m pip install --force-reinstall --no-deps "$1" 2>&1 | tail -n 2
rm -f "$1"
echo "$PASS" | sudo -S -p '' systemctl restart bruittrack bruittrack-viz
sleep 5
systemctl is-active bruittrack bruittrack-viz
echo RESTART_OK
EOR
echo "== verify (health + markers I48-I50) =="
ssh -o ControlPath=none "$HOST" <<'VEOF'
curl -sf http://127.0.0.1:8760/api/health || exit 2
HTML=$(curl -s http://127.0.0.1:8760/) || exit 3
for tok in freqTip hoverYpx TL_CKVH getClusterColor hoverLockId; do
  echo "$HTML" | grep -q "$tok" || { echo "FATAL: marker $tok absent du HTML servi"; exit 4; }
done
curl -sf http://127.0.0.1:8760/api/events?limit=1 >/dev/null
/opt/bruittrack/.venv/bin/python3 -m pip check
ls /opt/bruittrack/.venv/lib/python3.13/site-packages/bruittrack/viz.py >/dev/null
# I74/I75 : invariance pic + fusion quasi-doublons presentes sur le site distant
D=/opt/bruittrack/.venv/lib/python3.13/site-packages/bruittrack
grep -q "def merge_quasi_duplicate_clusters" $D/store.py || exit 6
grep -q "merge_quasi_duplicate_clusters" $D/pipeline.py || exit 7
grep -q "max_bin_delta" $D/events.py || exit 8
echo VERIFY_OK
VEOF
echo "DEPLOY_OK"
