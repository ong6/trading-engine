#!/usr/bin/env python3
"""Local retention: keep the newest two deploy and rollback copies, and remove finished lane clones.

``python -m tools.prune_local [--apply]`` prints one JSON plan (dry run, the default) or result
(``--apply``): every entry it would remove or removed, and every entry it kept with the reason.
The GitHub ``trading-data`` repository is the backup of record; local copies are short-lived.

Backups:
  * ``~/.local/state/trading-engine/auto-deploy/backups/*`` and the live checkout's
    ``store/backups`` keep their newest two entries (by modification time). The deployer's
    in-flight backup is always kept.
  * ``recovery/`` of a release transaction (``~/.local/state/trading-engine/releases/<name>/``,
    or the older ``~/.local/state/<name>-deploy/``) is removed only when that
    transaction's ``state.json`` records a final phase (``verified``, ``rolled-back``, ``aborted``,
    ``resumed``) and the release is not one of the newest two (by ``created_at``).
  * ``~/trading-data``, the published snapshots (``publish_snapshot`` has its own retention),
    the point-in-time stores and the live store are never touched.

Lane clones under ``~/engine-lanes/*`` are removed only when every rule holds: a git clone (not
a linked worktree) whose ``origin`` is the engine repository; not named on a ``CLAIMS.md`` line
that contains "stay claimed"; nothing outside ``.git`` and dependency caches, and no commit or
checkout, changed in the last 24 hours; no merge, rebase or cherry-pick in progress; no tracked
changes and no untracked files outside ``.gitignore``; no stash entries; ``git fetch origin`` and
``git ls-remote`` succeed; and every commit of every local branch and of ``HEAD`` is on
origin (reachable from a branch ``git ls-remote`` lists now) or patch-equivalent in
``origin/main`` (``git cherry``; an unpushed merge commit always keeps the clone). Non-git
directories, linked worktrees and symlinks are reported, never removed.

The CLAIMS.md convention: a lane stays claimed when its directory name appears as a whole word
on any line containing "stay claimed" (case-insensitive), for example
``stay claimed: p25-docs, p25-retention`` or a ledger row ending "... r25-api stay claimed".
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path

KEEP = 2
STATE_ROOT = Path.home() / ".local/state/trading-engine"
ENGINE_ROOT = Path.home() / "trading-engine"
LANES_ROOT = Path.home() / "engine-lanes"
FINAL_PHASES = frozenset({"verified", "rolled-back", "aborted", "resumed"})
QUIET = timedelta(hours=24)
ENGINE_ORIGIN = re.compile(r"[:/]ong6/trading-engine(?:\.git)?/?$")
STAY_CLAIMED = re.compile(r"stay claimed", re.IGNORECASE)
# Rebuildable caches: skipped by the recent-change scan (they change on any test run).
SCAN_SKIP = frozenset({".git", ".venv", "node_modules", "__pycache__", ".pytest_cache",
                       ".ruff_cache", ".mypy_cache", ".next"})
IN_PROGRESS = ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply")
GIT_ENV = {"GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0",
           "GIT_SSH_COMMAND": os.environ.get("GIT_SSH_COMMAND", "ssh -o BatchMode=yes")}


def _item(path: Path, action: str, reason: str, **detail) -> dict:
    return {"path": str(path), "action": action, "reason": reason, **detail}


def _remove(path: Path) -> None:
    """Delete a file or tree, making read-only directories writable on the way."""
    if path.is_symlink() or not path.is_dir():
        path.unlink()
        return

    def retry(function, failed, _exc):
        os.chmod(os.path.dirname(failed), stat.S_IRWXU)
        if os.path.isdir(failed) and not os.path.islink(failed):
            os.chmod(failed, stat.S_IRWXU)
        function(failed)

    shutil.rmtree(path, onexc=retry)


def _act(path: Path, reason: str, apply: bool, **detail) -> dict:
    if not apply:
        return _item(path, "remove", reason, **detail)
    try:
        _remove(path)
    except OSError as exc:
        return _item(path, "remove-failed", reason, error=str(exc)[:300], **detail)
    return _item(path, "removed", reason, **detail)


def prune_entries(root: Path, *, keep: int = KEEP, apply: bool = False,
                  protect: Iterable[Path] = ()) -> list[dict]:
    """Keep the newest ``keep`` entries of ``root`` (and anything in ``protect``); drop the rest."""
    try:
        entries = [entry for entry in root.iterdir() if not entry.name.startswith(".")]
    except FileNotFoundError:
        return []
    entries.sort(key=lambda entry: (entry.lstat().st_mtime, entry.name), reverse=True)
    protected = {Path(path).absolute() for path in protect}
    items = []
    for rank, entry in enumerate(entries):
        if rank < keep:
            items.append(_item(entry, "keep", f"newest-{keep}"))
        elif entry.absolute() in protected:
            items.append(_item(entry, "keep", "in-flight"))
        else:
            items.append(_act(entry, f"older-than-newest-{keep}", apply))
    return items


def _read_json(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def release_dirs(state_root: Path) -> list[Path]:
    """Release transaction state directories: ``<state_root>/releases/*`` and the older
    ``~/.local/state/*-deploy`` spelling. Directories without ``recovery/`` are skipped later."""
    candidates = [*(state_root / "releases").glob("*"), *state_root.parent.glob("*-deploy")]
    return sorted({path for path in candidates if path.is_dir() and not path.is_symlink()})


def prune_releases(releases: list[Path], *, keep: int = KEEP, apply: bool = False) -> list[dict]:
    """Remove ``recovery/`` of finished release transactions older than the newest ``keep``."""
    releases = list(releases)
    states = {path: _read_json(path / "state.json") for path in releases}

    def created(path: Path) -> tuple[str, float]:
        stamp = (states[path] or {}).get("created_at")
        return (stamp if isinstance(stamp, str) else "", path.stat().st_mtime)

    releases.sort(key=created, reverse=True)
    items = []
    for rank, release in enumerate(releases):
        recovery = release / "recovery"
        if not os.path.lexists(recovery):
            continue
        phase = (states[release] or {}).get("phase")
        if rank < keep:
            items.append(_item(recovery, "keep", f"newest-{keep}-releases", phase=phase))
        elif not isinstance(phase, str):
            items.append(_item(recovery, "keep", "state-unreadable"))
        elif phase not in FINAL_PHASES:
            items.append(_item(recovery, "keep", "phase-not-final", phase=phase))
        else:
            items.append(_act(recovery, "final-release", apply, phase=phase))
    return items


def stay_claimed(claims: Path, names: Iterable[str]) -> set[str]:
    """Lane names that appear as a whole word on a CLAIMS.md line containing "stay claimed"."""
    try:
        lines = [line for line in claims.read_text().splitlines() if STAY_CLAIMED.search(line)]
    except OSError:
        return set()
    return {name for name in names if any(
        re.search(rf"(?<![\w.-]){re.escape(name)}(?![\w-])", line) for line in lines)}


def changed_since(clone: Path, cutoff: float) -> bool:
    """Whether a file outside ``.git`` and the caches, or the last commit/checkout, is newer."""
    for marker in (clone / ".git/HEAD", clone / ".git/logs/HEAD"):
        try:
            if marker.stat().st_mtime > cutoff:
                return True
        except OSError:
            pass
    stack = [clone]
    while stack:
        try:
            with os.scandir(stack.pop()) as entries:
                for entry in entries:
                    if entry.name in SCAN_SKIP:
                        continue
                    try:
                        if entry.stat(follow_symlinks=False).st_mtime > cutoff:
                            return True
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                    except OSError:
                        continue
        except OSError:
            continue
    return False


def _git(clone: Path, *args: str, timeout: float = 120) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(["git", "-C", str(clone), *args], capture_output=True, text=True,
                              timeout=timeout, check=False, stdin=subprocess.DEVNULL,
                              env={**os.environ, **GIT_ENV})
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(args, 124, "", str(exc))


def unpushed(clone: Path, origin_heads: list[str]) -> dict[str, list[str]]:
    """Per local branch (and ``HEAD``): commits neither on origin nor patch-equivalent in main.

    "On origin" means reachable from a branch ``git ls-remote`` lists now, so a remote-tracking
    ref left behind by a branch deleted upstream does not count (and nothing is pruned).
    """
    refs = _git(clone, "for-each-ref", "--format=%(refname)", "refs/heads").stdout.split()
    lost: dict[str, list[str]] = {}
    for ref in [*refs, "HEAD"]:
        listed = _git(clone, "rev-list", ref, "--not", *origin_heads)
        if listed.returncode:
            lost[ref] = ["unreadable"]
            continue
        local = set(listed.stdout.split())
        if not local:
            continue
        cherry = _git(clone, "cherry", "origin/main", ref)
        if cherry.returncode:
            lost[ref] = ["cherry-failed"]
            continue
        unique = {line.split()[1] for line in cherry.stdout.splitlines()
                  if line.startswith("+ ")}
        merges = set(_git(clone, "rev-list", "--merges", ref, "--not",
                          *origin_heads).stdout.split())
        missing = sorted((local & unique) | merges)
        if missing:
            lost[ref.removeprefix("refs/heads/")] = [sha[:12] for sha in missing]
    return lost


def lane_verdict(clone: Path, *, claimed: set[str], cutoff: float) -> tuple[str, dict]:
    """``("remove", {})`` or the first rule that keeps the clone, with detail."""
    if clone.is_symlink():
        return "symlink", {}
    git = clone / ".git"
    if git.is_file():
        return "linked-worktree", {}
    if not git.is_dir():
        return "not-git", {}
    origin = _git(clone, "config", "--get", "remote.origin.url").stdout.strip()
    if not ENGINE_ORIGIN.search(origin):
        return "other-origin", {"origin": origin}
    if clone.name in claimed:
        return "stay-claimed", {}
    if changed_since(clone, cutoff):
        return "recent-change", {}
    if any(os.path.lexists(git / name) for name in IN_PROGRESS):
        return "operation-in-progress", {}
    status = _git(clone, "status", "--porcelain", "--untracked-files=all")
    if status.returncode:
        return "status-failed", {}
    if status.stdout.strip():
        return "dirty", {"changes": len(status.stdout.splitlines())}
    if _git(clone, "stash", "list").stdout.strip():
        return "stash", {}
    # Only the unpushed-commit rule needs origin: fetch the clones that got this far.
    fetched = _git(clone, "fetch", "-q", "origin", timeout=300)
    heads = _git(clone, "ls-remote", "--heads", "origin") if not fetched.returncode else fetched
    if heads.returncode:
        return "fetch-failed", {"error": (heads.stderr or heads.stdout).strip()[-200:]}
    origin_heads = sorted({line.split()[0] for line in heads.stdout.splitlines() if line.strip()})
    if _git(clone, "rev-parse", "--verify", "-q", "origin/main").returncode:
        return "no-origin-main", {}
    lost = unpushed(clone, origin_heads)
    if lost:
        return "unpushed-commits", {"branches": lost}
    return "remove", {}


def prune_lanes(root: Path, claims: Path, *, apply: bool = False,
                now: datetime | None = None) -> list[dict]:
    try:
        clones = sorted(path for path in root.iterdir()
                        if path.is_dir() or path.is_symlink() and path.resolve().is_dir())
    except FileNotFoundError:
        return []
    claimed = stay_claimed(claims, [clone.name for clone in clones])
    cutoff = ((now or datetime.now(UTC)) - QUIET).timestamp()
    items = []
    for clone in clones:
        verdict, detail = lane_verdict(clone, claimed=claimed, cutoff=cutoff)
        if verdict == "remove":
            items.append(_act(clone, "merged-clean-idle", apply))
        else:
            items.append(_item(clone, "keep", verdict, **detail))
    return items


def plan(*, state_root: Path = STATE_ROOT, engine_root: Path = ENGINE_ROOT,
         lanes_root: Path = LANES_ROOT, claims: Path | None = None, apply: bool = False,
         now: datetime | None = None) -> dict:
    deploy_state = _read_json(state_root / "auto-deploy/state.json") or {}
    in_flight = (deploy_state.get("in_flight") or {}).get("backup")
    sections = {
        "auto_deploy_backups": prune_entries(state_root / "auto-deploy/backups", apply=apply,
                                             protect=[Path(in_flight)] if in_flight else []),
        "store_backups": prune_entries(engine_root / "store/backups", apply=apply),
        "release_recovery": prune_releases(release_dirs(state_root), apply=apply),
        "lanes": prune_lanes(lanes_root, claims or lanes_root / "CLAIMS.md", apply=apply, now=now),
    }
    items = [item for section in sections.values() for item in section]
    acted = Counter(item["action"] for item in items if item["action"] != "keep")
    kept = Counter(item["reason"] for item in items if item["action"] == "keep")
    return {"mode": "apply" if apply else "dry-run", **sections,
            "summary": {**dict(sorted(acted.items())), "kept_by_reason": dict(sorted(kept.items()))}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="remove; the default only plans")
    parser.add_argument("--state-root", type=Path, default=STATE_ROOT)
    parser.add_argument("--engine-root", type=Path, default=ENGINE_ROOT)
    parser.add_argument("--lanes-root", type=Path, default=LANES_ROOT)
    parser.add_argument("--claims", type=Path, help="default LANES_ROOT/CLAIMS.md")
    args = parser.parse_args(argv)
    result = plan(state_root=args.state_root.expanduser(), engine_root=args.engine_root.expanduser(),
                  lanes_root=args.lanes_root.expanduser(),
                  claims=args.claims.expanduser() if args.claims else None, apply=args.apply)
    print(json.dumps(result, indent=1))
    return 1 if result["summary"].get("remove-failed") else 0


if __name__ == "__main__":
    sys.exit(main())
