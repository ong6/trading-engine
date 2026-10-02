#!/usr/bin/env bash
set -euo pipefail

.venv/bin/python -m server.daily_opportunity_runner
report_status=0
.venv/bin/python -m server.agent_evaluation_reporting || report_status=$?
if [ "${report_status}" -eq 75 ]; then
  echo "WARN: P15 evidence validation failed; daily opportunity run remains complete; restart suppressed"
fi
exit "${report_status}"
