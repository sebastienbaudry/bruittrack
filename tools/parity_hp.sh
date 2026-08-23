#!/usr/bin/env bash
# Parity check: local repo files vs /opt/bruittrack on hpdebian (sha256 per file).
set -u
cd "$(git rev-parse --show-toplevel)"
files=$(find src/bruittrack pyproject.toml config.toml.example -type f 2>/dev/null | sort)
diff=0
for rel in $files; do
  remote_sum=$(printf 'cd /opt/bruittrack && sha256sum "%s" 2>/dev/null\n' "$rel" | ssh pi-t620 2>/dev/null | awk '{print $1}')
  local_sum=$(sha256sum "$rel" 2>/dev/null | awk '{print $1}')
  if [ -z "$remote_sum" ] || [ ! -f "$rel" ]; then
    echo "DIFF $rel (one side missing)"
    diff=1
  elif [ "$local_sum" != "$remote_sum" ]; then
    echo "DIFF $rel"
    diff=1
  fi
done
[ "$diff" -eq 0 ] && echo "ALL_MATCH (no differing files among src/bruittrack, pyproject.toml, config.toml.example)"
echo PARITY_CHECK_DONE
