#!/usr/bin/env bash
# Manual local API launcher for development. Run from the repo root.
#   TRADING_ENGINE_DB=store/market.duckdb ./server/run_server.sh
# Binds loopback only — no auth, paper system. The persistent production path
# is trading-engine-api.service; stop it first because both bind port 8000.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/uvicorn ]; then
  echo "ERROR: .venv/bin/uvicorn not found; create/install the project environment" >&2
  exit 127
fi
exec .venv/bin/uvicorn server.main:app --host 127.0.0.1 --port 8000
