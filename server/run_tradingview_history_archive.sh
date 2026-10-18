#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
if ! .venv/bin/python -c 'import sys; from engine.tradingview_history_archive import COLLECTION_ENABLED; sys.exit(0 if COLLECTION_ENABLED else 1)'; then
  printf '%s\n' '{"status":"paused","reason":"no_registered_reader"}'
  exit 0
fi
params='{"cohort_id":"liquid-current-v1","start":"2022-01-01","max_chunks":50}'
.venv/bin/python -m engine.queue_runner --enqueue tradingview_history \
  --priority 130 --params "${params}"
.venv/bin/python -m engine.queue_runner --run --run-kind tradingview_history \
  --run-params "${params}"
# A history slice may reuse a generation younger than two hours. The regular
# four-hour cadence therefore publishes each slice; closely spaced history,
# nightly and scoring publications share one generation. Snapshot as_of remains
# the original capture time. At successful slice completion the reused
# generation is <2h old; between slices the existing schedule/4h timeout gives
# a conservative 16h20m history-fallback budget. Failure reaches the scheduler.
.venv/bin/python -m tools.publish_snapshot --min-age-minutes 120
