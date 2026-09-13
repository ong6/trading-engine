#!/usr/bin/env bash
# Local hot-reload UI for development. Run from anywhere.
#   ./ui/run_ui.sh
# Proxies /api/* to the FastAPI backend on 127.0.0.1:8000 (start that first via
# server/run_server.sh). Stop trading-engine-ui.service first: both bind port
# 3000. This script is not the persistent production launcher.
set -euo pipefail
cd "$(dirname "$0")"

# Node 24 is not on the default PATH on this box.
export PATH="${NODE_BIN:-$HOME/tools/node/bin}:$PATH"
if ! command -v npm >/dev/null 2>&1; then
  echo "ERROR: npm not found; set NODE_BIN to the directory containing npm" >&2
  exit 127
fi

exec npm run dev -- --hostname 127.0.0.1 --port 3000
