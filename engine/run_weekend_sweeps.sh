#!/usr/bin/env bash
# Weekend parameter-sweep driver (design §12.3b — "weekend deep sweeps").
#
# Enqueues only grids explicitly listed in farm/sweep/sweep.py's
# OPEN_RECURRING_GRIDS and drains the queue. Intended cadence: SATURDAY, so it
# is clear of the Sunday 06:00 walk-forward grid and weekday 22:30 nightly.
#
# WHY THIS EXISTS. Until 2026-08-20 sweeps were enqueued by hand, which is why
# only four of six grids had ever run and why two of them sat pending for two
# days before a nightly happened to drain them. A search workload that costs
# CPU and zero tokens should not depend on someone remembering to start it.
#
# WHAT A SWEEP IS NOT. It never creates, promotes or modifies a league book. It
# writes candidates to data/reports/sweeps/<grid>/charters/<version>/ and stops. A candidate
# becomes a book only when a human pre-registers it with an expectation and a
# kill criterion. Completed grids are not rerun indefinitely: recurring search
# reuses the same history, compounds trial count, and does not create new
# out-of-sample evidence.
#
# Cron entry (owner action — this script does not install it):
#
#   0 6 * * 6 ~/trading-engine/engine/run_weekend_sweeps.sh \
#       >> ~/trading-engine/logs/sweeps-cron.log 2>&1
set -euo pipefail

# Shared preamble (engine/lib/driver.sh): resolve REPO_ROOT + cd, overlap guard
# (non-blocking flock on .sweeps.lock), PY=, PYTHONUNBUFFERED, LOG=, stage
# breadcrumb, and the errexit/pipefail-safe tee wrap in driver_main.
DRIVER_NAME=run_weekend_sweeps
DRIVER_LOCK=.sweeps.lock
DRIVER_LOCK_MSG="another sweep run is still going (lock held) — aborting"
DRIVER_LOG_PREFIX=sweeps
DRIVER_STAGE_FILE=logs/.last_stage_sweeps
source "$(dirname "${BASH_SOURCE[0]}")/lib/driver.sh"

# Saturday is completely free — the nightly is Mon-Fri 22:30 and the
# walk-forward is Sunday 06:00 — so the drain gets a 12 h window instead of the
# 4 h default. A grid that still does not finish is left pending and picked up
# by the next drain; jobs are resumable and nothing is killed mid-flight.
export TRADING_ENGINE_DRAIN_BUDGET_S="${TRADING_ENGINE_DRAIN_BUDGET_S:-43200}"

# Priority 900 keeps sweeps BELOW every other farm workload (nightly miners
# 100-130, historical backtests 140-165, walk-forward grid 170-176), so a sweep
# can never delay a stage that feeds the live league.
SWEEP_PRIORITY=900
# 8000 -> 4500 (2026-08-20): measured — the live meanrev 10-fold sweep
# worker's lifetime peak RSS (VmHWM) was 3,409 MB; 4500 = peak +32% headroom.
# Must match JOB_TYPES["sweep"]["mem_mb"] in engine/queue_runner.py.
SWEEP_MEM_MB=4500

body() {
  # A future hypothesis becomes recurring only after its charter is frozen and
  # its grid name is added to OPEN_RECURRING_GRIDS. Empty is the healthy state
  # when no new research question is registered.
  stage list-open-grids
  # Capture Python separately so its exit status cannot be hidden by a filter.
  # awk has a successful empty-output case, unlike grep's expected status 1,
  # and removes bracketed diagnostics without masking genuine command errors.
  GRID_OUTPUT="$("${PY}" -m farm.sweep.sweep --grid recurring)"
  OPEN_SWEEPS="$(printf '%s\n' "${GRID_OUTPUT}" | awk '!/^\[/ && NF')"
  if [ -z "${OPEN_SWEEPS}" ]; then
    echo "INFO: no open recurring sweep grids — nothing to enqueue"
    return 0
  fi
  echo "open sweeps: $(printf '%s\n' "${OPEN_SWEEPS}" | tr '\n' ' ')"

  RUN_ARGS=()
  stage enqueue
  while IFS=$'\t' read -r g charter extra; do
    case "${g}" in
      *[!a-zA-Z0-9_-]*) echo "ERROR: unsafe recurring grid name: ${g}"; return 1 ;;
    esac
    case "${charter}" in
      ""|*[!a-zA-Z0-9._-]*) echo "ERROR: unsafe charter version for ${g}: ${charter}"; return 1 ;;
    esac
    if [ -n "${extra}" ]; then
      echo "ERROR: malformed recurring sweep row for ${g}"; return 1
    fi
    params="{\"grid\": \"${g}\", \"charter_version\": \"${charter}\"}"
    # One-shot means a completed grid is not searched again on the same
    # history. Re-running requires an explicitly versioned params/charter.
    "${PY}" -m engine.queue_runner --enqueue sweep \
      --priority "${SWEEP_PRIORITY}" --mem-mb "${SWEEP_MEM_MB}" \
      --params "${params}" --once
    RUN_ARGS+=(--run-params "${params}")
  done <<< "${OPEN_SWEEPS}"

  # --jobs 8: `sweep` is parallel_safe (read-only on the store, writes only its
  # own pid-namespaced scratch), so grids batch and the parent RELEASES the
  # write lock for the batch — the API/UI stay up throughout. Width 4 -> 8
  # (2026-08-20, measured): 355 -> 523 jobs/h on a fixed 8-replay unit; worker
  # peak RSS 3.4 GB measured vs 4.5 GB declared, 8 x 4.5 = 36 GB in the 48 GB
  # budget; sustained load ~20-24 of 32 cores under LOAD_5MIN_MAX=28. There
  # Real width is min(8, the number of explicitly open grids).
  stage drain
  "${PY}" -m engine.queue_runner --run --jobs 8 \
    --run-kind sweep "${RUN_ARGS[@]}"

  stage sync
  "${PY}" -m engine.sync || echo "WARN: sync failed (exit $?) — reports are on disk; next nightly's sync will stage them"

}

driver_main body
