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
# Sunday 06:00 UTC is clear of everything: the nightly is 22:30 Mon-Fri, the
# news analyst is 11:00 Mon-Fri, and the full grid measures at roughly 3-4 h,
# so it lands long before Monday's nightly. It can also be run by hand on any
# day — it re-anchors to the latest session in the store, so an off-day run is
# simply a re-validation as of that day.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

# Overlap guard, same shape as the nightly's. Two queue drains cannot run at
# once anyway (DuckDB is single-writer), but failing fast with a clear message
# beats a lock-retry timeout deep inside a job.
exec 9>"${REPO_ROOT}/.walkforward.lock"
if ! flock -n 9; then
  echo "ERROR: another walk-forward run is still going (lock held) — aborting"
  exit 1
fi

PY="${REPO_ROOT}/.venv/bin/python"
export PYTHONUNBUFFERED=1
mkdir -p "${REPO_ROOT}/logs"
LOG="${REPO_ROOT}/logs/walkforward-$(date +%F).log"

# errexit is suspended around the tee pipeline and re-armed inside the block —
# otherwise a failing stage exits the script before the breadcrumb below runs
# (same fix as run_daily.sh, 2026-09-02; see the comment there).
STAGE_FILE="${REPO_ROOT}/logs/.last_stage_walkforward"
stage() { echo "$1" > "${STAGE_FILE}"; }
: > "${STAGE_FILE}"
set +e
{
  set -e
  echo "=== run_weekly_walkforward $(date -u +%FT%TZ) ==="

  # Enqueue is idempotent: queue_runner dedups an identical pending
  # (kind, params), so a re-run after a partial drain adds nothing.
  stage enqueue
  "${PY}" -m farm.walkforward.grid --enqueue

  # The drain honours every §12.7 cap (nice 19 + ionice idle, load/RAM guard,
  # per-job memory budget, wall-clock drain budget). Jobs left pending by the
  # budget are picked up by the next drain — including the nightly's.
  # --jobs 8: walkforward is `parallel_safe` (read-only on the store, writes only
  # its own scratch), so the per-book jobs batch. Width 4 -> 8 (2026-08-20,
  # measured on a fixed unit of 8 identical 1-fold replays): 355 jobs/h at
  # 4 workers x 4 DuckDB threads vs 523 at 8x4 — width, not threads, is the
  # lever. Peak RSS per worker measured 3.4 GB (VmHWM, 10-fold sweep worker),
  # so 8 x 4.5 GB declared = 36 GB inside the 48 GB engine budget, and
  # sustained load ~20-24 of 32 cores stays under LOAD_5MIN_MAX=28. A batch is
  # still bounded by its SLOWEST member.
  stage drain
  "${PY}" -m engine.queue_runner --run --jobs 8

  # Commit the regenerated reports. Best-effort: the results JSON and the
  # markdown are already on disk, and the next nightly's sync stages data/
  # wholesale, so a failure here costs a day of visibility, not evidence.
  stage sync
  "${PY}" -m engine.sync || echo "WARN: sync failed (exit $?) — reports are on disk; next nightly's sync will stage them"

  echo "=== done $(date -u +%FT%TZ) ==="
} 2>&1 | tee -a "${LOG}"
status="${PIPESTATUS[0]}"
set -e
if [ "${status}" -ne 0 ]; then
  failed_stage="$(cat "${STAGE_FILE}" 2>/dev/null)"
  echo "TODO: run_weekly_walkforward failed $(date -u +%FT%TZ) (stage=${failed_stage:-unknown} exit ${status}) — inspect ${LOG}" | tee -a "${LOG}"
  exit "${status}"
fi
