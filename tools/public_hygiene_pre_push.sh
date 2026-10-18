#!/bin/sh
set -eu

repo_root=$(git rev-parse --show-toplevel)
if [ -x "$repo_root/.venv/bin/python" ]; then
    python="$repo_root/.venv/bin/python"
else
    python=python3
fi
PYTHONPATH="$repo_root${PYTHONPATH:+:$PYTHONPATH}" \
    exec "$python" -m tools.public_hygiene --repo-root "$repo_root" \
    --pre-push --remote-name "${1:-origin}"
