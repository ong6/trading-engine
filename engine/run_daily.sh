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

  # rank universe + trend template, write screens/eod. --skip-if-done: on a
  # weekend/holiday run collect no-ops so MAX(date) is already screened — no-op
  # cleanly (exit 0) instead of aborting the nightly; real failures still exit 1.
  "${PY}" engine/screen.py --skip-if-done

  # Paper league (exec-design §1 nightly order: … → screen → league → report → sync).
  # --init is idempotent (creates only absent portfolios); the step writes
  # data/reports/league.md + league.csv itself. --skip-if-done keeps a weekend/
  # holiday re-run (MAX(date) unchanged) a clean exit 0; a real error still fails
  # the nightly loudly via set -e / PIPESTATUS below.
  "${PY}" -m sim.league --init --skip-if-done

  "${PY}" engine/sync.py      # commit (and push if a remote exists) data/ (incl. reports/)

  # --- Farm work: LOWEST priority (§12.7 — the nightly loop preempts the farm).
  # Runs AFTER sync so data collection + the committed screen/league are already
  # safe. A failure here is logged but must NOT fail the nightly: subshell pins
  # its own exit to 0 so set -e / PIPESTATUS never see it.
  (
    set +e
    echo "--- farm (post-sync, lowest priority §12.7): mining enqueue + drain ---"
    "${PY}" engine/queue_runner.py --enqueue intraday --priority 100
    eq=$?
    # Earnings calendar: daily (§12.2 — feeds the earnings risk gate).
    "${PY}" engine/queue_runner.py --enqueue earnings --priority 110
    ee=$?
    # Fundamentals snapshot: weekly (§12.2) — Fridays, so the point-in-time rows
    # land on week-close data. Resumable if the drain is interrupted.
    ef=0
    if [ "$(date -u +%u)" = "5" ]; then
      "${PY}" engine/queue_runner.py --enqueue fundamentals --priority 120
      ef=$?
    fi
    "${PY}" engine/queue_runner.py --run
    rn=$?
    if [ "${eq}" -ne 0 ] || [ "${ee}" -ne 0 ] || [ "${ef}" -ne 0 ] || [ "${rn}" -ne 0 ]; then
      echo "WARN: farm section had failures (intraday=${eq} earnings=${ee}" \
           "fundamentals=${ef} run=${rn}) — nightly NOT failed;" \
           "collect/screen/league/sync already succeeded"
    else
      echo "INFO: farm section OK (mining enqueued + queue drained)"
    fi
    exit 0
  )

  echo "=== done $(date -u +%FT%TZ) ==="
} 2>&1 | tee "${LOG}"

# Propagate failure of any piped stage and drop a breadcrumb.
status="${PIPESTATUS[0]}"
if [ "${status}" -ne 0 ]; then
  echo "TODO: run_daily failed $(date -u +%FT%TZ) (exit ${status}) — inspect ${LOG}" >> "${LOG}"
  exit "${status}"
fi
