#!/usr/bin/env bash
# Vérification locale rapide : syntaxe scripts, style, tests.
# Usage : bash tools/check.sh   (depuis la racine du repo)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> Syntaxe des scripts bash"
for f in tools/*.sh; do
  bash -n "$f"
done

echo "==> Ruff (si disponible)"
if command -v ruff >/dev/null 2>&1 || python -m ruff --version >/dev/null 2>&1; then
  if command -v ruff >/dev/null 2>&1; then
    ruff check .
  else
    python -m ruff check .
  fi
else
  echo "ruff absent — étape style passée (pip install -e '.[dev]')"
fi

echo "==> Test unitaire"
if [ -x .venv/bin/python ]; then
  PY=.venv/bin/python
else
  PY=python
fi
"$PY" -m pytest tests -q --no-header

echo "CHECK OK"
