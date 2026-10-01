#!/usr/bin/env bash
set -euo pipefail

.venv/bin/python -m server.p15_scoring_runner --run
.venv/bin/python -m server.agent_evaluation_reporting
market_date="$(.venv/bin/python -m engine.market_date)"
exec .venv/bin/python -m sim.league --date "${market_date}" --skip-if-done
