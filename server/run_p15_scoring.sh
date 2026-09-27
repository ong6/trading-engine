#!/usr/bin/env bash
set -euo pipefail

.venv/bin/python -m server.p15_scoring_runner --run
exec .venv/bin/python -m server.agent_evaluation_reporting
