#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
collection_state="$(.venv/bin/python -m engine.tradingview_history_archive --collection-state)"
case "${collection_state}" in
  paused)
    .venv/bin/python -m engine.tradingview_history_archive --publish-paused
    exit 0
    ;;
  enabled) ;;
  *)
    printf 'invalid TradingView collection state: %s\n' "${collection_state}" >&2
    exit 2
    ;;
esac
params='{"cohort_id":"liquid-current-v1","start":"2022-01-01","max_chunks":50}'
.venv/bin/python -m engine.queue_runner --enqueue tradingview_history \
  --priority 130 --params "${params}"
.venv/bin/python -m engine.queue_runner --run --run-kind tradingview_history \
  --run-params "${params}"
# The archive only appends its own progress rows, and each snapshot is a full
# copy of the database, so this run publishes at most once a day (a younger
# generation is reused and the command exits 0 as "skipped"). The nightly and
# P15 publishers keep market-latest current for the API's busy-lock fallback;
# snapshot as_of remains the original capture time. A publication failure
# reaches the scheduler.
.venv/bin/python -m tools.publish_snapshot --min-age-minutes 1440
