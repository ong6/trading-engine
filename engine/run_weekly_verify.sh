#!/usr/bin/env bash
# Weekly FULL-UNIVERSE price cross-validation.
#
# The nightly stage samples ~40 names plus the core ETFs plus everything held —
# enough to catch a systemic break, not enough to catch one silently wrong name.
# This is the wide pass, and it exists because of the 2026-08-20 evidence-ceiling
# finding: with the fold count structurally capped by survivorship, the return on
# more parameter search is ~zero while the return on better data is not. The box
# sits near load 2 for roughly 150 h/week; this fills ~2 h of it with the one
# kind of work that raises the quality of evidence we already have.
#
# Measured cost: the nightly's 175-name pass took 422 s (~2.4 s/name, dominated
# by engine/earnings.py's PER_NAME_SLEEP politeness discipline, which is
# deliberate and must not be removed — yfinance is the sole price source). A
# ~2,900-name liquid universe is therefore ~2 h.
#
# SATURDAY 02:00 UTC, four hours ahead of the sweep grid at 06:00 and a full day
# clear of the Sunday walk-forward. Read-only on the store and fail-soft by
# construction, so an overlap degrades to a breadcrumb rather than a failure.
#
# Cron entry (owner action — this script does not install it):
#
#   0 2 * * 6 ~/trading-engine/engine/run_weekly_verify.sh \
#       >> ~/trading-engine/logs/verify-cron.log 2>&1
set -euo pipefail

# Shared preamble (engine/lib/driver.sh): resolve REPO_ROOT + cd, overlap guard
# (non-blocking flock on .verify.lock), PY=, PYTHONUNBUFFERED, LOG=, stage
# breadcrumb, and the errexit/pipefail-safe tee wrap in driver_main.
DRIVER_NAME=run_weekly_verify
DRIVER_LOCK=.verify.lock
DRIVER_LOCK_MSG="another verification run is still going (lock held) — aborting"
DRIVER_LOG_PREFIX=verify-full
source "$(dirname "${BASH_SOURCE[0]}")/lib/driver.sh"

body() {
  # --sample large enough to reach the whole liquid universe; --max-names is the
  # hard ceiling and --max-secs the wall-clock stop. Both are deliberate: a run
  # that cannot finish must stop and SAY it checked fewer names, never silently
  # report the subset it managed as if it were the universe.
  "${PY}" -m engine.verify_prices \
    --sample 5000 --max-names 5000 --max-secs 10800 --sessions 5 \
    || echo "WARN: verification exited non-zero — it is fail-soft by design; see the log"
}

driver_main body
