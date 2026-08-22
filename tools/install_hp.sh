#!/usr/bin/env bash
# BruitTrack — installation reproductible sur hpdebian (Debian 13, HP T620).
# Idempotent : re-executable sans effet de bord.
set -euo pipefail

TARGET_USER="bruittrack"
APP_DIR="/opt/bruittrack"
REPO_URL="${BRUITTRACK_REPO_URL:-file:///$(cd "$(dirname "$0")/.." && pwd)}"
PYTHON_BIN="python3"

step() { printf '\n== %s\n' "$1"; }

# --- c.1 : pré-requis système (root requis pour apt/useradd/policykit) ----
if [ "$(id -u)" -ne 0 ]; then echo "ERREUR : execution root requise (sudo $0)"; exit 1; fi

step "apt pré-requis"
DEBIAN_FRONTEND=noninteractive apt-get update -y
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  python3-venv python3-dev portaudio19-dev sox alsa-utils git

step "systemd + utilisateur ${TARGET_USER} (groupe audio)"
systemctl enable --now alsa-utils || true  # alsa-utils n'a pas de service ; noop
useradd --system --no-create-home --shell /usr/sbin/nologin \
  --gid audio --description "BruitTrack daemon" "${TARGET_USER}" 2>/dev/null || \
usermod --gid audio --shell /usr/sbin/nologin "${TARGET_USER}"

# --- c.2 : depot + venv ---------------------------------------------------
step "depot ${APP_DIR}"
mkdir -p "${APP_DIR}"
if [ ! -d "${APP_DIR}/git/.git" ]; then
  git clone "${REPO_URL}" "${APP_DIR}/git"
fi
git -C "${APP_DIR}/git" fetch --all --prune || true
git -C "${APP_DIR}/git" checkout main
git -C "${APP_DIR}/git" pull --ff-only || echo "ATTENTION : non-FF ; re-execution manuelle"
cd "${APP_DIR}/git"

step "venv .venv + install editable"
[ -d .venv ] || ${PYTHON_BIN} -m venv .venv
. .venv/bin/activate  # noqa: shellcheck
pip install --upgrade pip --no-cache-dir
pip install -e .

# --- c.2 : config.toml depuis l'exemple ----------------------------------
step "config"
if [ ! -f "${APP_DIR}/config.toml" ]; then
  cp config.toml.example "${APP_DIR}/config.toml"
  echo "ATTENTION : device audio a remplir via 'python -m bruittrack devices'."
fi
chown -R ${TARGET_USER}:audio "${APP_DIR}"

# --- c.4 : service systemd ----------------------------------------------
step "service systemd"
cd "${APP_DIR}/git"
sed -e "s|WorkingDirectory=.*|WorkingDirectory=${APP_DIR}|" \
    -e "s|ExecStart=.*|ExecStart=${APP_DIR}/git/.venv/bin/python -m bruittrack start --config ${APP_DIR}/config.toml|" \
    systemd/bruittrack.service | sudo tee /etc/systemd/system/bruittrack.service >/dev/null
systemctl daemon-reload
systemctl enable --now bruittrack

step "verification de premiere marche (module_check hors ligne)"
.venv/bin/python tools/module_check.py --offline || true  # bonus, non bloquant

echo "INSTALL_OK — 'journalctl -u bruittrack -e' pour l'inspection.
Dispositif a configurer : sudo-edit ${APP_DIR}/config.toml (audio.device via 'python -m bruittrack devices')."
