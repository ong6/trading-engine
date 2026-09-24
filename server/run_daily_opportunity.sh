#!/usr/bin/env bash
set -euo pipefail

.venv/bin/python -m server.daily_opportunity_runner
exec .venv/bin/python -m server.agent_evaluation_reporting
