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

{
  echo "=== run_weekly_walkforward $(date -u +%FT%TZ) ==="

  # Enqueue is idempotent: queue_runner dedups an identical pending
  # (kind, params), so a re-run after a partial drain adds nothing.
  "${PY}" farm/walkforward/grid.py --enqueue

  # The drain honours every §12.7 cap (nice 19 + ionice idle, load/RAM guard,
  # per-job memory budget, wall-clock drain budget). Jobs left pending by the
  # budget are picked up by the next drain — including the nightly's.
  # --jobs 4: walkforward is `parallel_safe` (read-only on the store, writes only
  # its own scratch), so the per-book jobs batch. Measured ~2.3x on a mixed
  # 4-job batch; a batch is bounded by its SLOWEST member. Width 4 keeps peak
  # declared RAM at 32 GB inside the 48 GB engine budget.
  "${PY}" engine/queue_runner.py --run --jobs 4

  # Commit the regenerated reports. Best-effort: the results JSON and the
  # markdown are already on disk, and the next nightly's sync stages data/
  # wholesale, so a failure here costs a day of visibility, not evidence.
  "${PY}" engine/sync.py || echo "WARN: sync failed (exit $?) — reports are on disk; next nightly's sync will stage them"

  echo "=== done $(date -u +%FT%TZ) ==="
} 2>&1 | tee -a "${LOG}"
