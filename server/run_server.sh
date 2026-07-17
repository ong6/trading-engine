#!/usr/bin/env bash
# M3 local mock-trading backend. Run from the repo root.
#   TRADING_ENGINE_DB=store/market.duckdb ./server/run_server.sh
# Binds loopback only — no auth, mock system.
set -euo pipefail
cd "$(dirname "$0")/.."
exec .venv/bin/uvicorn server.main:app --host 127.0.0.1 --port 8000
