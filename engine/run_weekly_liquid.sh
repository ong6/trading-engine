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
#   0 2 * * 0 /data00/home/jun.ong/trading-engine/engine/run_weekly_liquid.sh \
#       >> /data00/home/jun.ong/trading-engine/logs/liquid-cron.log 2>&1
set -euo pipefail

# Shared preamble (engine/lib/driver.sh): resolve REPO_ROOT + cd, overlap guard
# (non-blocking flock on .liquid.lock), PY=, PYTHONUNBUFFERED, LOG=, stage
# breadcrumb, and the errexit/pipefail-safe tee wrap in driver_main.
DRIVER_NAME=run_weekly_liquid
DRIVER_LOCK=.liquid.lock
DRIVER_LOCK_MSG="another liquidity refresh is still going (lock held) — aborting"
DRIVER_LOG_PREFIX=liquid
source "$(dirname "${BASH_SOURCE[0]}")/lib/driver.sh"

export TRADING_ENGINE_LOCK_WAIT_S="${TRADING_ENGINE_LOCK_WAIT_S:-1800}"

body() {
  "${PY}" -m engine.collect --refresh-liquid
}

driver_main body
