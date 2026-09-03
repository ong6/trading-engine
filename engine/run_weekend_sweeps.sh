#!/usr/bin/env bash
# Weekend parameter-sweep driver (design §12.3b — "weekend deep sweeps").
#
# Enqueues one `sweep` job per grid in farm/sweep/sweep.py's GRIDS and drains
# the queue. Intended cadence: SATURDAY, so it is clear of the Sunday 06:00
# walk-forward grid and of the weekday 22:30 nightly.
#
# WHY THIS EXISTS. Until 2026-08-20 sweeps were enqueued by hand, which is why
# only four of six grids had ever run and why two of them sat pending for two
# days before a nightly happened to drain them. A search workload that costs
# CPU and zero tokens should not depend on someone remembering to start it.
#
# WHAT A SWEEP IS NOT. It never creates, promotes or modifies a league book. It
# writes candidates to data/reports/sweeps/<grid>/ and stops. A candidate
# becomes a book only when a human pre-registers it with an expectation and a
# kill criterion. This script widens the search; it never acts on the result.
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
  # Grid names come from the module itself, so a grid added to GRIDS is swept
  # from the next Saturday with no edit here. `--grid list` also prints
  # bracketed diagnostics (e.g. infeasible cells being skipped); those are
  # filtered out rather than parsed. `grep -v` exits 1 when it selects NOTHING
  # (every line was a diagnostic), which under pipefail failed the `$(...)`
  # assignment and aborted the script before the "no grids" message — hence
  # the `|| true` guard; the emptiness check below is the real gate.
  stage list-grids
  GRIDS="$("${PY}" -m farm.sweep.sweep --grid list | { grep -v '^\[' || true; } | awk 'NF {print $1}')"
  if [ -z "${GRIDS}" ]; then
    echo "ERROR: no grids enumerated — refusing to drain an empty plan"
    exit 1
  fi
  echo "grids: $(echo "${GRIDS}" | tr '\n' ' ')"

  # Enqueue is idempotent: queue_runner dedups an identical pending
  # (kind, params), so a re-run after a partial drain adds nothing.
  stage enqueue
  for g in ${GRIDS}; do
    "${PY}" -m engine.queue_runner --enqueue sweep \
      --priority "${SWEEP_PRIORITY}" --mem-mb "${SWEEP_MEM_MB}" \
      --params "{\"grid\": \"${g}\"}"
  done

  # --jobs 8: `sweep` is parallel_safe (read-only on the store, writes only its
  # own pid-namespaced scratch), so grids batch and the parent RELEASES the
  # write lock for the batch — the API/UI stay up throughout. Width 4 -> 8
  # (2026-08-20, measured): 355 -> 523 jobs/h on a fixed 8-replay unit; worker
  # peak RSS 3.4 GB measured vs 4.5 GB declared, 8 x 4.5 = 36 GB in the 48 GB
  # budget; sustained load ~20-24 of 32 cores under LOAD_5MIN_MAX=28. There
  # are only 6 grids today, so real width is min(8, pending grids).
  stage drain
  "${PY}" -m engine.queue_runner --run --jobs 8

  stage sync
  "${PY}" -m engine.sync || echo "WARN: sync failed (exit $?) — reports are on disk; next nightly's sync will stage them"

}

driver_main body
