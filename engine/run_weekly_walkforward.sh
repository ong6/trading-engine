#!/usr/bin/env bash
# Weekly walk-forward re-validation driver (design §12.3; execution design §6).
#
# Enqueues one `walkforward` job per ACTIVE league book and drains the queue.
# Intended cadence: SUNDAY, ahead of the weekly review.
#
# Why this is a separate script and not a stage in run_daily.sh: the nightly is
# a weekday-only cron (`30 22 * * 1-5`) and never fires on a Sunday, so a
# `date -u +%u = 7` gate inside it — the pattern the Friday fundamentals stage
# uses — would be dead code that never runs. This is the honest alternative.
#
# INSTALLED IN CRON (owner, 2026-08-09) as:
#
#   0 6 * * 0 ~/trading-engine/engine/run_weekly_walkforward.sh \
#       >> ~/trading-engine/logs/walkforward-cron.log 2>&1
#
# Its Saturday sibling is engine/run_weekend_sweeps.sh (parameter grids).
#
# Sunday 06:00 UTC: the nightly is 22:30 Mon-Fri and the P15 timers run
# Tue-Sat. TradingView history still runs on Sunday (03/07/11/15/19/23:40) and
# writes the live store, so the children read the published snapshot instead
# (engine/queue_runner.py _research_connection). The pre-v2 grid took 2.8 h.
# It can also be run by hand, but on a weekday only outside 22:30-13:05 UTC (the
# guard below enforces it): the drain holds the queue-drain lock, so an
# overlapping nightly skips its mining drain. It re-anchors to the latest session in the store, so an off-day run is
# simply a re-validation as of that day.
set -euo pipefail

# Shared preamble (engine/lib/driver.sh): resolve REPO_ROOT + cd, overlap guard
# (non-blocking flock on .walkforward.lock), PY=, PYTHONUNBUFFERED, LOG=, stage
# breadcrumb, and the errexit/pipefail-safe tee wrap in driver_main.
DRIVER_NAME=run_weekly_walkforward
DRIVER_LOCK=.walkforward.lock
DRIVER_LOCK_MSG="another walk-forward run is still going (lock held) — aborting"
DRIVER_LOG_PREFIX=walkforward
DRIVER_STAGE_FILE=logs/.last_stage_walkforward
source "$(dirname "${BASH_SOURCE[0]}")/lib/driver.sh"

# Weekday window guard (2026-10-21). Manual Monday runs at 02:53, 07:31 and 11:41
# UTC on 2026-10-19 held the drain lock and the store through the producers'
# window: five TradingView archive runs and the P15 pre-open failed on the store
# lock and both backups skipped. Refuse a weekday start inside 22:30-13:05 UTC;
# a supervised run sets TRADING_ENGINE_WALKFORWARD_OVERRIDE to its reason, which
# is logged. TRADING_ENGINE_WALKFORWARD_CLOCK (a `date -d` string) is for tests.
_wf_clock="${TRADING_ENGINE_WALKFORWARD_CLOCK:-now}"
_wf_dow="$(date -u -d "${_wf_clock}" +%u)"
_wf_hm="$(date -u -d "${_wf_clock}" +%H%M)"
WALKFORWARD_OVERRIDE_NOTE=""
if [ "${_wf_dow}" -le 5 ] && (( 10#${_wf_hm} >= 2230 || 10#${_wf_hm} < 1305 )); then
  if [ -z "${TRADING_ENGINE_WALKFORWARD_OVERRIDE:-}" ]; then
    echo "ERROR: run_weekly_walkforward refuses a weekday start inside 22:30-13:05 UTC" \
         "($(date -u -d "${_wf_clock}" '+%a %H:%M') UTC): it would hold the store and drain lock" \
         "through the nightly, P15 and backup window. Set" \
         "TRADING_ENGINE_WALKFORWARD_OVERRIDE=<reason> for a supervised run." >&2
    exit 1
  fi
  WALKFORWARD_OVERRIDE_NOTE="WARN: weekday-window override at $(date -u -d "${_wf_clock}" '+%a %H:%M') UTC: ${TRADING_ENGINE_WALKFORWARD_OVERRIDE}"
fi

# Launch window 8 h (default 4 h): the budget only stops NEW launches, and each
# walkforward job is killed at its 7 h timeout_s, so the drain ends by about
# 06:00 + 8 h + 7 h = 21:00 UTC Sunday, clear of Monday's 22:30 nightly.
export TRADING_ENGINE_DRAIN_BUDGET_S="${TRADING_ENGINE_DRAIN_BUDGET_S:-28800}"

body() {
  if [ -n "${WALKFORWARD_OVERRIDE_NOTE}" ]; then echo "${WALKFORWARD_OVERRIDE_NOTE}"; fi

  # Enqueue is idempotent within a day: queue_runner dedups an identical
  # pending (kind, params), so a re-run after a partial drain adds nothing.
  # Pending rows older than 24 h (last week's leftovers) are superseded.
  stage enqueue
  "${PY}" -m farm.walkforward.grid --enqueue

  # The drain honours every §12.7 cap (nice 19 + ionice idle, load/RAM guard,
  # per-job memory budget, wall-clock drain budget). --kinds walkforward: this
  # driver runs only its own grid. Jobs left pending stay for the next Sunday
  # (the nightly skips research kinds), when this week's enqueue supersedes
  # them. --report-partial: a drain that left jobs pending, timed out or
  # failed prints a PARTIAL: line, and /meta reports the run 'partial'.
  # --jobs 8: walkforward is `parallel_safe` (read-only on the store, writes only
  # its own scratch), so the per-book jobs batch. Width 4 -> 8 (2026-08-20,
  # measured on a fixed unit of 8 identical 1-fold replays): 355 jobs/h at
  # 4 workers x 4 DuckDB threads vs 523 at 8x4 — width, not threads, is the
  # lever. Peak RSS per worker measured 3.4 GB (VmHWM, 10-fold sweep worker),
  # so 8 x 4.5 GB declared = 36 GB inside the 48 GB engine budget, and
  # sustained load ~20-24 of 32 cores stays under LOAD_5MIN_MAX=28. A batch is
  # still bounded by its SLOWEST member.
  stage drain
  "${PY}" -m engine.queue_runner --run --jobs 8 --kinds walkforward --report-partial

  # Compose the read-only one-page operator view from the evidence now on disk.
  stage operator_digest
  "${PY}" -m farm.p16_operator_digest || echo "operator_digest failed (non-fatal)" >&2

  # Commit the regenerated reports under this driver's name, not the nightly
  # screen's. Best-effort: the results JSON and the markdown are already on
  # disk, and the next nightly's sync stages data/ wholesale, so a failure
  # here costs a day of visibility, not evidence.
  stage sync
  "${PY}" -m engine.sync --driver "${DRIVER_NAME}" || echo "WARN: sync failed (exit $?) — reports are on disk; next nightly's sync will stage them"

}

driver_main body
