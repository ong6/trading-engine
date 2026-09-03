#!/usr/bin/env bash
# Weekly liquidity-flag refresh: `collect.py --refresh-liquid`.
#
# WHY THIS EXISTS. `universe.liquid` had exactly one writer — the 2026-07-16
# bootstrap — so the 336 names listed since then sat at liquid=FALSE forever,
# 21 delisted names stayed liquid, and every universe_snapshot row repeated the
# 07-16 verdict. The forward record could never admit a newly liquid name
# (inverse survivorship). This re-pulls ~90d for active non-liquid names,
# recomputes the flag for everyone from the trailing 63-session median dollar
# volume under the SAME floor bootstrap used (close >= $3, median $vol >= $5M),
# admits + max-history-backfills new names, and demotes (flag only — never a
# row; held names are never demoted). Details: engine/collect.py docstring.
#
# WHY ITS OWN DRIVER, not a stage in run_weekly_verify.sh: this WRITES the store
# (prices, universe flags, a backfill job), while the Saturday 02:00 verify is
# documented read-only and its wall-clock cap (3 h) can run into the 06:00
# sweep drain. run_weekend_sweeps.sh and run_weekly_walkforward.sh hold the
# DuckDB writer for hours through the queue. The nightly is weekday-only.
#
# WHY SUNDAY 02:00 UTC: the only weekend hour with nothing else on the store —
# the Saturday sweep's 12 h drain budget ends 18:00 Sat, the Sunday walk-forward
# starts 06:00, and the ~90d pull of ~8k names plus a handful of backfills is
# minutes, not hours. Monday's 22:30 nightly is the first to collect the
# admitted names incrementally and to screen them. The lock wait is raised to
# 30 min in case a sweep worker is still draining (db.connect retries).
#
# Cron entry (owner action — this script does not install it):
#
#   0 2 * * 0 ~/trading-engine/engine/run_weekly_liquid.sh \
#       >> ~/trading-engine/logs/liquid-cron.log 2>&1
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

exec 9>"${REPO_ROOT}/.liquid.lock"
if ! flock -n 9; then
  echo "ERROR: another liquidity refresh is still going (lock held) — aborting"
  exit 1
fi

PY="${REPO_ROOT}/.venv/bin/python"
export PYTHONUNBUFFERED=1
export TRADING_ENGINE_LOCK_WAIT_S="${TRADING_ENGINE_LOCK_WAIT_S:-1800}"
mkdir -p "${REPO_ROOT}/logs"
LOG="${REPO_ROOT}/logs/liquid-$(date +%F).log"

# errexit is suspended around the tee pipeline and re-armed inside the block —
# otherwise a failing stage exits the script before the breadcrumb below runs
# (same fix as run_daily.sh, 2026-09-02; see the comment there).
set +e
{
  set -e
  echo "=== run_weekly_liquid $(date -u +%FT%TZ) ==="
  "${PY}" -m engine.collect --refresh-liquid
  echo "=== done $(date -u +%FT%TZ) ==="
} 2>&1 | tee -a "${LOG}"
status="${PIPESTATUS[0]}"
set -e
if [ "${status}" -ne 0 ]; then
  echo "TODO: run_weekly_liquid failed $(date -u +%FT%TZ) (exit ${status}) — inspect ${LOG}" | tee -a "${LOG}"
  exit "${status}"
fi
