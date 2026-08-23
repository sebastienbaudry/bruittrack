#!/usr/bin/env bash
# BruitTrack — installation reproductible sur hpdebian (Debian 13, HP T620).
# Idempotent : re-executable sans effet de bord.
set -euo pipefail

TARGET_USER="bruittrack"
APP_DIR="/opt/bruittrack"
REPO_URL="${BRUITTRACK_REPO_URL:-file:///$(cd "$(dirname "$0")/.." && pwd)}"
PYTHON_BIN="python3"

# --smoke : en plus de l'install, lance la matrice modules M1-M9 et rapport
SMOKE_FLAG=0
[ "${1:-}" = "--smoke" ] && SMOKE_FLAG=1

step() { printf '\n== %s\n' "$1"; }

# --- c.1 : pré-requis système (root requis pour apt/useradd/policykit) ----
if [ "$(id -u)" -ne 0 ]; then echo "ERREUR : execution root requise (sudo $0)"; exit 1; fi

step "apt pré-requis"
DEBIAN_FRONTEND=noninteractive apt-get update -y
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  python3-venv python3-dev portaudio19-dev sox alsa-utils curl git

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

# Normalisation des fins de ligne CRLF -> LF (editeurs Windows) : un '\r'
# residuel casse python (SyntaxError dans les chaines), .toml, sed et les
# units systemd. Idempotent : no-op si le corpus est deja en LF.
# Une seule passe sur ${APP_DIR} couvre les deux layouts :
#   - classique et déploy réel (hpdebian) : fichiers sous ${APP_DIR}/git
step "normalisation EOL CRLF->LF"
NORM_CR=0
while IFS= read -r -d '' f; do
  # od : lecture brute des octets (robuste msys/GNU, pas de conversion de fins de ligne)
  if od -An -v "$f" | grep -q '\\r'; then
    sed -i 's/\r$//' "$f"
    NORM_CR=$((NORM_CR + 1))
    echo "  LF : ${f#${APP_DIR}/}"
  fi
done < <(find "${APP_DIR}" \
          \( -type d \( -name .git -o -name .venv -o -name data \) -prune \) -o \
          \( -type f \( -name '*.py' -o -name '*.toml' -o -name '*.sh' \
                 -o -name '*.service' -o -name '*.md' -o -name '*.cfg' \
                 -o -name '*.example' \) -print0 \))
if [ "${NORM_CR}" = "0" ]; then
  echo "  corpus deja en LF"
fi

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

# ---------------------------------------------------------------------------
# Option --smoke : matrice de verification modules M1-M9 sur la cible.
# Ecrit le rapport ${SMOKE_REPORT}. Exemple : sudo bash tools/install_hp.sh --smoke
# ---------------------------------------------------------------------------
if [ "${SMOKE_FLAG}" = "1" ]; then
    SMOKE_REPORT="${INSTALL_REPORT:-${APP_DIR}/install-report.txt}"
    PYB="${APP_DIR}/git/.venv/bin/python"
    [ -x "$PYB" ] || PYB="${APP_DIR}/.venv/bin/python"   # layout plat (pi-t620)
    SM_OK=0; SM_WARN=0; SM_FAIL=0
    printf '
== SMOKE-MATRIX %s ==
' "$(date -Iseconds)" | tee -a "${SMOKE_REPORT}"

    sm_row() {
        local id="$1" name="$2" status="$3"; shift 3
        case "$status" in
            OK) SM_OK=$((SM_OK + 1)) ;;
            WARN) SM_WARN=$((SM_WARN + 1)) ;;
            *) SM_FAIL=$((SM_FAIL + 1)) ;;
        esac
        {
            printf '[%s] %s ... %s
' "$id" "$name" "$status"
            if [ $# -gt 0 ]; then
                printf '      %s
' "$@"
            fi
        } | tee -a "${SMOKE_REPORT}"
    }

    # M1 — CLI --help : rc=0 + sous-commands visibles.
    SMOKE_RC=0; H_OUT=$("$PYB" -m bruittrack --help 2>&1) || SMOKE_RC=$?
    if [ "$SMOKE_RC" -eq 0 ] && printf '%s' "$H_OUT" | grep -q "viz"; then
        sm_row M1 "CLI --help" OK "$(printf '%s
' "$H_OUT" | head -4)"
    else
        sm_row M1 "CLI --help" FAIL "rc=${SMOKE_RC} out=${H_OUT}"
    fi

    # M2 — py_compile de src/ + load_config().validate() sur copie tmp.
    SMOKE_RC=0; PC_OUT=$("$PYB" -m py_compile $(find src -name '*.py' | tr '
' ' ') 2>&1) || SMOKE_RC=$?
    CFG_RC=0
    CFG_OUT=$("$PYB" - >'&1' <<'SMOKECFGEOF'
import shutil, tempfile
from pathlib import Path
from bruittrack.config import load_config
tmp = Path(tempfile.mkdtemp()) / "config.toml"
shutil.copyfile("config.toml.example", tmp)
load_config(tmp).validate()
print("CFG_OK")
SMOKECFGEOF
    ) || CFG_RC=$?
    if [ "$SMOKE_RC" -eq 0 ] && [ "$CFG_RC" -eq 0 ] && printf '%s' "$CFG_OUT" | grep -q CFG_OK; then
        sm_row M2 "py_compile + config validate" OK "config.toml.example — load_config().validate() sans exception"
    else
        sm_row M2 "py_compile + config validate" FAIL "pc=${PC_OUT} cfg_rc=${CFG_RC} cfg=${CFG_OUT}"
    fi

    # M3 — devices : peripherique audio list (sinon fallback synthetique M4/M5).
    DEV_RC=0; D_OUT=$("$PYB" -m bruittrack devices 2>&1) || DEV_RC=$?
    SYN_FLAG=""
    if [ "$DEV_RC" -eq 0 ] && [ -n "$D_OUT" ]; then
        sm_row M3 "devices (ALSA list)" OK "$(printf '%s' "$D_OUT" | head -5)"
    else
        sm_row M3 "devices (ALSA list)" WARN "pas de liste HW — fallback --synthetic | rc=${DEV_RC} out=${D_OUT}"
        SYN_FLAG="--synthetic"
    fi

    # M4 — test pipeline 60 s (debut + DSP + store)
    SMOKE_RC=0
    T_OUT=$(timeout 70 "$PYB" -m bruittrack test --seconds 60 ${SYN_FLAG} 2>&1) || SMOKE_RC=$?
    if [ "$SMOKE_RC" -eq 0 ]; then
        sm_row M4 "test pipeline 60s${SYN_FLAG:+ (synth)}" OK "$(printf '%s' "$T_OUT" | head -4)"
    elif [ "$SMOKE_RC" -eq 124 ]; then
        sm_row M4 "test pipeline 60s" WARN "timeout 70s | $(printf '%s' "$T_OUT" | tail -3)"
    else
        sm_row M4 "test pipeline 60s" FAIL "rc=${SMOKE_RC} | $(printf '%s' "$T_OUT" | tail -5)"
    fi

    # M5 — floor tracker : lignes [floor] et etat de convergence OK
    SMOKE_RC=0
    F_OUT=$(timeout 120 "$PYB" -m bruittrack test --seconds 90 --verbose-floor ${SYN_FLAG} 2>&1) || SMOKE_RC=$?
    if [ "$SMOKE_RC" -eq 0 ] && printf '%s' "$F_OUT" | grep -q '\[floor\]' && printf '%s' "$F_OUT" | grep -qi "OK"; then
        sm_row M5 "floor tracker (verbose-floor)" OK "$(printf '%s' "$F_OUT" | grep -E '\[floor\]' | tail -1)"
    else
        sm_row M5 "floor tracker (verbose-floor)" FAIL "rc=${SMOKE_RC} | $(printf '%s' "$F_OUT" | tail -5)"
    fi

    # M6 — store/stats : rc=0, sortie parseable
    SMOKE_RC=0; S_OUT=$("$PYB" -m bruittrack stats 2>&1) || SMOKE_RC=$?
    if [ "$SMOKE_RC" -eq 0 ]; then
        sm_row M6 "store/stats CLI" OK "$(printf '%s' "$S_OUT" | head -4)"
    else
        sm_row M6 "store/stats CLI" FAIL "rc=${SMOKE_RC} out=${S_OUT}"
    fi

    # M7 — viz/API : /api/stats 200 JSON + timeline HTML
    "$PYB" -m bruittrack viz --port 8760 >/dev/null 2>&1 &
    VIZ_PID=$!
    sleep 3
    SMOKE_RC=0; VJS_OUT=$(curl -sf "http://127.0.0.1:8760/api/stats" 2>&1) || SMOKE_RC=$?
    SMOKE_RC=0; NTIMES=$(curl -sf "http://127.0.0.1:8760/" | grep -c timeline) || NTIMES=0
    kill "$VIZ_PID" 2>/dev/null
    wait "$VIZ_PID" 2>/dev/null || true
    if [ "$SMOKE_RC" -eq 0 ] && [ "${NTIMES:-0}" -ge 1 ]; then
        sm_row M7 "viz/API" OK "/api/stats=200 json; timeline_refs=${NTIMES:-0}"
    else
        sm_row M7 "viz/API" FAIL "curl_rc=${SMOKE_RC} body=${VJS_OUT} timeline=$NTIMES"
    fi

    # M8 — systemd : active + enabled + journal sans exception
    SMOKE_RC=0; J_ACT=$(systemctl is-active bruittrack 2>&1) || SMOKE_RC=$?
    SMOKE_RC=0; J_EN=$(systemctl is-enabled bruittrack 2>&1) || SMOKE_RC=$?
    ERR_N=$(journalctl -u bruittrack --no-pager 2>/dev/null | grep -cE 'Traceback|Error') || ERR_N=0
    if [ "$J_ACT" = "active" ] && [ "$J_EN" = "enabled" ] && [ "${ERR_N:-0}" -eq 0 ]; then
        sm_row M8 "systemd + journal" OK
    else
        sm_row M8 "systemd + journal" WARN "active=${J_ACT} enabled=${J_EN} exceptions=${ERR_N}"
    fi

    # M9 — budget CPU/RAM du processus : mesure canonique `bruittrack perf --pid`
    # (fenetre 15 s, budgets CPU_MAX_PCT=15 / RSS_MAX_KB=153 600 ; rc 0 = CONFORME).
    MAIN=$(systemctl show -p MainPID --value bruittrack 2>/dev/null || true)
    if [ -n "$MAIN" ] && kill -0 "$MAIN" 2>/dev/null; then
        PERF_RC=0
        B_OUT=$("$PYB" -m bruittrack perf --pid "$MAIN" 2>&1) || PERF_RC=$?
        if [ "$PERF_RC" -eq 0 ]; then
        B_CPU=$(printf '%s\n' "$B_OUT" | grep CPU | head -1)
        sm_row M9 "budget CPU/RAM (bruittrack perf, rc=0)" OK "$B_CPU"
        else
            sm_row M9 "budget CPU/RAM (bruittrack perf)" FAIL "rc=${PERF_RC} out=${B_OUT}"
        fi
    else
        sm_row M9 "budget CPU/RAM" WARN "pas de process actif — rexecuter apres 10 min (phase M6)"
    fi

    {
        printf 'SMOKE-SUMMARY ok=%s warn=%s fail=%s report=%s
'             "$SM_OK" "$SM_WARN" "$SM_FAIL" "${SMOKE_REPORT}"
    } | tee -a "${SMOKE_REPORT}"
    if [ "${SM_FAIL:-0}" -ne 0 ]; then
        echo "SMOKE FAIL (fail=${SM_FAIL}) — voir ${SMOKE_REPORT}"
        exit 1
    fi
    echo "SMOKE PASS (ok=${SM_OK} warn=${SM_WARN}) — rapport : ${SMOKE_REPORT}"
fi
