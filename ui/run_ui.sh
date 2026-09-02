#!/usr/bin/env bash
# M3 local mock-trading web UI. Run from anywhere.
#   ./ui/run_ui.sh
# Proxies /api/* to the FastAPI backend on 127.0.0.1:8000 (start that first via
# server/run_server.sh). Binds loopback only — mock system, no auth.
set -euo pipefail
cd "$(dirname "$0")"

# Node 24 is not on the default PATH on this box.
export PATH="${NODE_BIN:-$HOME/tools/node/bin}:$PATH"

# Dev server is fine for v1. Use `npm run build && npm run start -- ...` for prod.
exec npm run dev -- --hostname 127.0.0.1 --port 3000
