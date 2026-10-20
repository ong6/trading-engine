#!/usr/bin/env bash
set -euo pipefail

.venv/bin/python -m server.p15_scoring_runner --run
market_date="$(.venv/bin/python -m engine.market_date)"
.venv/bin/python -m sim.league --date "${market_date}" --skip-if-done
.venv/bin/python -m farm.p15_event_runner --mature-labels
report_status=0
.venv/bin/python -m server.agent_evaluation_reporting || report_status=$?
# Commit the re-rendered league and evaluation reports under this driver's name
# (engine/sync.py --driver), whatever the report status: the league re-render
# precedes validation, and reports are written atomically, so data/ never holds
# a half-written file. Before the snapshot, so its manifest cites this commit.
.venv/bin/python -m engine.sync --driver run_p15_scoring \
  || echo "WARN: sync failed (exit $?); reports are on disk and the next sync will stage them"
if [ "${report_status}" -eq 75 ]; then
  echo "WARN: P15 evidence validation failed; league re-render completed; restart suppressed"
elif [ "${report_status}" -ne 0 ]; then
  exit "${report_status}"
fi
.venv/bin/python -m tools.publish_snapshot \
  || echo "WARN: read-only snapshot publication failed; P15 scoring remains complete"
exit "${report_status}"
