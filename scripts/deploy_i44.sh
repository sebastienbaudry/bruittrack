#!/bin/bash
# I44 deploy : wheel → pi-t620, services restart, verifs
set -e
WHL=dist/bruittrack-1.0.0-py3-none-any.whl

ssh -o ControlPath=none pi-t620 hostname
echo "== upload =="
szp=$(date +%s)
scp -o ControlPath=none "$WHL" pi-t620:/tmp/bruittrack-$szp-py3-none-any.whl \
  || { echo "UPLOAD FAIL — re-run"; exit 4; }
REMOTE_WHL="/tmp/bruittrack-$szp-py3-none-any.whl"

echo "== remote install + config + restart (wheel=$REMOTE_WHL) =="
ssh -o ControlPath=none pi-t620 bash -s "$REMOTE_WHL" <<'REMOTE_EOF'
set -e
WHL="$1"
cd /opt/bruittrack
echo "== install wheel dans /opt/bruittrack/.venv =="
./.venv/bin/python3 -m pip install --force-reinstall --no-deps "$WHL" 2>&1 | tail -3
rm -f "$WHL"
echo "== config.toml cle I44 =="
if ! grep -q cluster_freq_tolerance_hz config.toml; then
  python3 - <<'PYEOF'
text = open("config.toml", encoding="utf-8").read()
anchor = "cluster_freq_tolerance_hz = 0.5\n"
if anchor not in text:
    if "[detector]" not in text:
        raise SystemExit("SECTION [detector] absente — abort")
    text = text.replace("[detector]",
                        "[detector]\n# I44 : tolerance de clustering sur le bin dominant (Hz)\ncluster_freq_tolerance_hz = 0.5", 1)
    open("config.toml", "w", encoding="utf-8").write(text)
PYEOF
fi
grep -A2 -B1 cluster_freq config.toml || true
echo "== restart services =="
systemctl daemon-reload
systemctl restart bruittrack-start bruittrack-viz
sleep 4
systemctl is-active bruittrack-start bruittrack-viz
echo "== verify =="
curl -s http://127.0.0.1:8080/api/health && echo
curl -s -o /dev/null -w "viz HTTP %{http_code}\n" http://127.0.0.1:8080/
REMOTE_EOF
echo "DEPLOY OK"
