#!/usr/bin/env bash
set -euo pipefail

variant=${1:?variant id required}
env_file=${HOME}/.config/trading-engine/market-data.env
.venv/bin/python -m tools.market_data_source --preflight "${env_file}"
exec .venv/bin/python -m tools.market_data_source --run-observer "${variant}"
