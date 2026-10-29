#!/usr/bin/env bash
set -euo pipefail

# The P15/P11 evaluation report is published by run_p15_scoring.sh at 02:30 UTC. It used
# to run here as well, after the model call; by 2026-10-28 it took over ten minutes, past this
# unit's RuntimeMaxSec, and every timeout restarted the unit while it held the store's writer.
exec .venv/bin/python -m server.daily_opportunity_runner
