#!/usr/bin/env bash
# Nightly driver: refresh the universe, then collect the day's EOD bars.
# Calendar-gating lives inside collect.py (incremental mode exits 0 on holidays).
set -euo pipefail

# Resolve repo root from this script's location (path-independent).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

PY="${REPO_ROOT}/.venv/bin/python"
mkdir -p "${REPO_ROOT}/logs"
LOG="${REPO_ROOT}/logs/run-$(date +%F).log"

# Everything below is teed into the daily log.
{
  echo "=== run_daily $(date -u +%FT%TZ) ==="

  # Pull latest if a git remote exists; tolerate failure (local-only is fine).
  if git remote | grep -q .; then
    git pull --rebase || echo "WARN: git pull --rebase failed; continuing with local state"
  else
    echo "INFO: no git remote configured; skipping pull"
  fi

  "${PY}" engine/universe.py
  "${PY}" engine/collect.py   # incremental daily (calendar-gated)

  "${PY}" engine/screen.py    # rank universe + trend template, write screens/eod
  "${PY}" engine/sync.py      # commit (and push if a remote exists) data/

  echo "=== done $(date -u +%FT%TZ) ==="
} 2>&1 | tee "${LOG}"

# Propagate failure of any piped stage and drop a breadcrumb.
status="${PIPESTATUS[0]}"
if [ "${status}" -ne 0 ]; then
  echo "TODO: run_daily failed $(date -u +%FT%TZ) (exit ${status}) — inspect ${LOG}" >> "${LOG}"
  exit "${status}"
fi
