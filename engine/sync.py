#!/usr/bin/env python
"""Commit (and push, if a remote exists) the day's screen outputs.

Stages data/ from the repo root, commits with a message summarising the run
(passing / new counts read from data/_meta.json), and pushes only when a git
remote is configured — otherwise it says so and leaves the commit local.

  --dry-run   print the staged files + the would-be message; commit nothing.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
META_PATH = REPO_ROOT / "data" / "_meta.json"


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True
    )


def _commit_message() -> str:
    n = m = 0
    run_date = datetime.now(timezone.utc).date().isoformat()
    if META_PATH.exists():
        try:
            meta = json.loads(META_PATH.read_text())
            n = meta.get("passing_count", 0)
            m = meta.get("new_today_count", 0)
            run_date = (meta.get("last_screen") or run_date)[:10]
        except json.JSONDecodeError:
            pass
    return f"screen: {run_date} ({n} passing, {m} new)"


def main() -> int:
    ap = argparse.ArgumentParser(description="Commit/push the day's screen outputs.")
    ap.add_argument("--dry-run", action="store_true",
                    help="show staged files + message without committing")
    args = ap.parse_args()

    # Stage data/ (idempotent — no-op if nothing changed).
    _git("add", "data/")

    staged = _git("diff", "--cached", "--name-only").stdout.strip()
    message = _commit_message()

    if not staged:
        print("[sync] nothing staged — data/ is clean; nothing to commit")
        return 0

    files = staged.splitlines()
    print(f"[sync] {len(files)} staged file(s):")
    for f in files:
        print(f"    {f}")

    if args.dry_run:
        # Unstage so a dry-run leaves the working tree exactly as it found it.
        _git("reset", "--quiet")
        print(f"[sync] --dry-run: would commit with message: {message!r}")
        return 0

    commit = _git("commit", "-m", message)
    if commit.returncode != 0:
        print(f"[sync] commit failed:\n{commit.stderr.strip()}")
        return 1
    print(f"[sync] committed: {message}")

    has_remote = bool(_git("remote").stdout.strip())
    if not has_remote:
        print("[sync] no remote — commit local only")
        return 0

    push = _git("push")
    if push.returncode != 0:
        print(f"[sync] push failed:\n{push.stderr.strip()}")
        return 1
    print("[sync] pushed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
