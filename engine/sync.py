#!/usr/bin/env python
"""Commit (and push, if an upstream exists) the day's screen outputs.

Stages data/ from the repo root, commits with a message summarising the run
(passing / new counts read from data/_meta.json), and pushes only when the
current branch has an upstream — otherwise it says so and leaves the commit
local. A stale remote name is not enough: ``git push`` cannot target it safely.
The command refuses to run when the index already contains staged work, and
the commit is path-limited to ``data/`` as a second containment boundary.

  --dry-run   print the staged files + the would-be message; commit nothing.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from typing import NamedTuple

from engine.lib.log import get_logger
from engine.lib.settings import META_PATH, REPO_ROOT

log = get_logger("sync")


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True)


def _rebase_in_progress() -> str | None:
    """Return a marker name if a rebase/merge is mid-flight, else None.

    Committing on top of a half-finished rebase/merge would bury the conflict —
    refuse and let the operator resolve it first.
    """
    git_dir = REPO_ROOT / ".git"
    for marker in ("rebase-merge", "rebase-apply", "MERGE_HEAD"):
        if (git_dir / marker).exists():
            return marker
    return None


class Upstream(NamedTuple):
    remote: str
    branch: str
    tracking_ref: str


def _upstream() -> Upstream | None:
    """Return a configured, locally resolvable upstream and its push target."""
    current = _git("symbolic-ref", "--quiet", "--short", "HEAD")
    branch_name = current.stdout.strip()
    if current.returncode != 0 or not branch_name:
        return None
    remote_result = _git("config", "--get", f"branch.{branch_name}.remote")
    merge_result = _git("config", "--get", f"branch.{branch_name}.merge")
    remote = remote_result.stdout.strip()
    merge_ref = merge_result.stdout.strip()
    if (
        remote_result.returncode != 0
        or merge_result.returncode != 0
        or not remote
        or not merge_ref.startswith("refs/heads/")
    ):
        return None
    target_branch = merge_ref.removeprefix("refs/heads/")
    if remote != ".":
        remote_url = _git("remote", "get-url", "--push", remote)
        if remote_url.returncode != 0 or not remote_url.stdout.strip():
            return None
    upstream_result = _git(
        "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"
    )
    tracking_ref = upstream_result.stdout.strip()
    if upstream_result.returncode != 0 or not tracking_ref:
        return None
    return Upstream(remote, target_branch, tracking_ref)


def _commit_message() -> str:
    n = m = 0
    run_date = datetime.now(timezone.utc).date().isoformat()
    if META_PATH.exists():
        try:
            meta = json.loads(META_PATH.read_text())
            n = meta.get("passing_count", 0)
            m = meta.get("new_today_count", 0)
            run_date = (meta.get("screen_date") or meta.get("last_screen") or run_date)[:10]
        except json.JSONDecodeError:
            pass
    return f"screen: {run_date} ({n} passing, {m} new)"


def _unstage_data() -> subprocess.CompletedProcess:
    """Restore our path in the index; working-tree data remains untouched."""
    return _git("reset", "--quiet", "--", "data/")


def main() -> int:
    ap = argparse.ArgumentParser(description="Commit/push the day's screen outputs.")
    ap.add_argument(
        "--dry-run", action="store_true", help="show staged files + message without committing"
    )
    args = ap.parse_args()

    # Never commit mid-rebase/merge — that would silently bury an unresolved
    # conflict. Bail loudly and leave it for the operator.
    marker = _rebase_in_progress()
    if marker is not None:
        log.error(
            f"[sync] ABORT: a git {marker} is in progress "
            f"({REPO_ROOT / '.git' / marker}) — resolve it "
            f"(git rebase --continue/--abort or resolve the merge) then re-run sync"
        )
        return 1

    # The index belongs to the operator unless it is clean when this process
    # starts. Never fold an unrelated staged code/doc change into an unattended
    # generated-data commit.
    before = _git("diff", "--cached", "--name-only")
    if before.returncode != 0:
        log.error(f"[sync] cannot inspect the Git index:\n{before.stderr.strip()}")
        return 1
    pre_staged = before.stdout.strip()
    if pre_staged:
        log.error(
            "[sync] REFUSING: the Git index already contains staged work; "
            "generated data remains in the working tree for the next run:\n"
            + pre_staged
        )
        return 1

    # Stage data/ (idempotent — no-op if nothing changed).
    added = _git("add", "--", "data/")
    if added.returncode != 0:
        log.error(f"[sync] could not stage data/:\n{added.stderr.strip()}")
        return 1

    staged_result = _git("diff", "--cached", "--name-only", "--", "data/")
    if staged_result.returncode != 0:
        _unstage_data()
        log.error(f"[sync] cannot inspect staged data/:\n{staged_result.stderr.strip()}")
        return 1
    staged = staged_result.stdout.strip()
    message = _commit_message()

    if not staged:
        log.info("[sync] nothing staged — data/ is clean; nothing to commit")
        return 0

    files = staged.splitlines()
    log.info(f"[sync] {len(files)} staged file(s):")
    for f in files:
        log.info(f"    {f}")

    if args.dry_run:
        # The index was clean above; unstage only our path so a dry-run cannot
        # disturb anything outside its ownership boundary.
        reset = _unstage_data()
        if reset.returncode != 0:
            log.error(f"[sync] could not restore the index after dry-run:\n{reset.stderr.strip()}")
            return 1
        log.info(f"[sync] --dry-run: would commit with message: {message!r}")
        return 0

    commit = _git("commit", "--only", "-m", message, "--", "data/")
    if commit.returncode != 0:
        reset = _unstage_data()
        log.error(f"[sync] commit failed:\n{commit.stderr.strip()}")
        if reset.returncode != 0:
            log.error(f"[sync] also failed to restore the index:\n{reset.stderr.strip()}")
        return 1
    log.info(f"[sync] committed: {message}")

    upstream = _upstream()
    if upstream is None:
        log.info(
            "[sync] no upstream configured — commit local only; after creating the "
            "remote repository, run `git push -u origin main`"
        )
        return 0

    # Pin both destination remote and ref. A repository-level pushRemote or
    # remote.pushDefault must never redirect unattended data publication.
    push = _git("push", upstream.remote, f"HEAD:refs/heads/{upstream.branch}")
    if push.returncode != 0:
        log.error(f"[sync] push failed:\n{push.stderr.strip()}")
        return 1
    log.info(f"[sync] pushed to {upstream.remote}/{upstream.branch}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
