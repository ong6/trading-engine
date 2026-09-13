#!/usr/bin/env python3
"""Inventory every working-tree change by ownership without modifying Git."""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
from collections import Counter
from contextlib import ExitStack, contextmanager
from pathlib import Path

from engine.lib.settings import REPO_ROOT
from tools.release_manifest import REQUIRED_FILES, research_runtime_identity

SCHEMA_VERSION = 3
PROTECTED_ROOTS = frozenset({"engine", "farm", "sim"})
ROOT_CONFIGURATION_FILES = frozenset(
    {
        ".gitignore",
        "BUILDLOG.md",
        "CONTRIBUTING.md",
        "LICENSE",
        "README.md",
        "SECURITY.md",
        "pyproject.toml",
        "uv.lock",
    }
)


class AuditError(RuntimeError):
    """The worktree could not be inventoried reliably."""


def _git(repo_root: Path, *args: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise AuditError(f"git invocation failed: {exc}") from exc
    if result.returncode != 0:
        reason = os.fsdecode(result.stderr).strip() or f"exit {result.returncode}"
        raise AuditError(f"git {' '.join(args)} failed: {reason}")
    return result.stdout


def _ownership(path: str) -> str:
    top = path.split("/", 1)[0]
    if top in PROTECTED_ROOTS or path == "pyproject.toml":
        return "protected-research"
    if top in {"server", "tools"}:
        return "support-api"
    if top == "ui":
        return "ui"
    if top == "tests":
        return "tests"
    if top == "data":
        return "generated-evidence"
    if top == "archive":
        return "historical-archive"
    if top in {"docs", ".github"} or path in ROOT_CONFIGURATION_FILES:
        return "docs-configuration"
    return "unknown"


def _parse_status(raw: bytes) -> list[dict]:
    fields = raw.split(b"\0")
    rows = []
    index = 0
    while index < len(fields):
        field = fields[index]
        index += 1
        if not field:
            continue
        if len(field) < 4 or field[2:3] != b" ":
            raise AuditError("unexpected porcelain status record")
        status = os.fsdecode(field[:2])
        path = os.fsdecode(field[3:])
        original_path = None
        if status[0] in "RC" or status[1] in "RC":
            if index >= len(fields) or not fields[index]:
                raise AuditError(f"rename/copy record lacks origin: {path}")
            original_path = os.fsdecode(fields[index])
            index += 1
        ownership = _ownership(path)
        untracked = status == "??"
        rows.append(
            {
                "path": path,
                "status": status,
                "original_path": original_path,
                "ownership": ownership,
                "release_required": path in REQUIRED_FILES,
                "staged": not untracked and status[0] not in {" ", "?"},
                "untracked": untracked,
                "working_tree_changed": untracked or status[1] not in {" ", "?"},
            }
        )
    return sorted(rows, key=lambda row: row["path"])


def _text_value(repo_root: Path, *args: str) -> str | None:
    value = os.fsdecode(_git(repo_root, *args)).strip()
    return value or None


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


@contextmanager
def _open_relative_parent(repo_root: Path, parts: tuple[str, ...]):
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None:
        raise OSError("secure worktree traversal is unavailable")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | directory | nofollow
    with ExitStack() as stack:
        current = os.open(repo_root, flags)
        stack.callback(os.close, current)
        identities = [(os.fstat(current).st_dev, os.fstat(current).st_ino)]
        for part in parts:
            current = os.open(part, flags, dir_fd=current)
            stack.callback(os.close, current)
            opened = os.fstat(current)
            identities.append((opened.st_dev, opened.st_ino))
        yield current, tuple(identities)


def _untracked_path_state(repo_root: Path, relative: str) -> str:
    """Classify one Git-reported path without following a changing path component."""
    path = Path(relative)
    parts = path.parts
    if not parts or path.is_absolute() or any(part in {"", ".", ".."} for part in parts):
        return "unstable"
    try:
        with _open_relative_parent(repo_root, parts[:-1]) as (parent_fd, parent_chain):
            before = os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
        with _open_relative_parent(repo_root, parts[:-1]) as (
            visible_parent_fd,
            visible_chain,
        ):
            visible = os.stat(
                parts[-1], dir_fd=visible_parent_fd, follow_symlinks=False
            )
    except OSError:
        return "unstable"
    if parent_chain != visible_chain or _stat_identity(before) != _stat_identity(visible):
        return "unstable"
    if stat.S_ISLNK(before.st_mode):
        return "symlink"
    if not stat.S_ISREG(before.st_mode):
        return "special"
    return "empty-regular" if before.st_size == 0 else "regular"


def _change_groups(repo_root: Path, rows: list[dict]) -> dict:
    untracked = [row["path"] for row in rows if row["untracked"]]
    untracked_states = {
        path: _untracked_path_state(repo_root, path) for path in untracked
    }
    unsafe_untracked = [
        path
        for path, state in untracked_states.items()
        if state in {"symlink", "special", "unstable"}
    ]
    return {
        "ownership_counts": Counter(row["ownership"] for row in rows),
        "status_counts": Counter(row["status"] for row in rows),
        "untracked": untracked,
        "untracked_symlinks": [
            path for path, state in untracked_states.items() if state == "symlink"
        ],
        "untracked_special": [
            path for path, state in untracked_states.items() if state == "special"
        ],
        "unstable_untracked": [
            path for path, state in untracked_states.items() if state == "unstable"
        ],
        "unsafe_untracked": unsafe_untracked,
        "empty_untracked_files": [
            path for path, state in untracked_states.items() if state == "empty-regular"
        ],
        "staged": [row["path"] for row in rows if row["staged"]],
        "unknown": [row["path"] for row in rows if row["ownership"] == "unknown"],
        "required_untracked": [
            row["path"] for row in rows if row["untracked"] and row["release_required"]
        ],
        "protected_changed": [
            row["path"] for row in rows if row["ownership"] == "protected-research"
        ],
    }


def _summary(rows: list[dict], groups: dict) -> dict:
    return {
        "changed_path_count": len(rows),
        "tracked_changed_count": len(rows) - len(groups["untracked"]),
        "untracked_count": len(groups["untracked"]),
        "staged_count": len(groups["staged"]),
        "status_counts": dict(sorted(groups["status_counts"].items())),
        "ownership_counts": dict(sorted(groups["ownership_counts"].items())),
    }


def build_audit(repo_root: Path = REPO_ROOT) -> dict:
    """Return a complete recursive inventory of the current Git worktree."""
    repo_root = repo_root.resolve()
    status_args = ("status", "--porcelain=v1", "-z", "--untracked-files=all")
    raw_status = _git(repo_root, *status_args)
    rows = _parse_status(raw_status)
    groups = _change_groups(repo_root, rows)
    research_runtime = research_runtime_identity(repo_root)
    if _git(repo_root, *status_args) != raw_status:
        raise AuditError("working tree changed during audit")
    return {
        "schema_version": SCHEMA_VERSION,
        "repo_root": str(repo_root),
        "git": {
            "head": _text_value(repo_root, "rev-parse", "HEAD"),
            "branch": _text_value(repo_root, "symbolic-ref", "--quiet", "--short", "HEAD"),
        },
        "summary": _summary(rows, groups),
        "review_gates": {
            "index_empty": not groups["staged"],
            "ownership_complete": not groups["unknown"],
            "untracked_files_safe": not groups["unsafe_untracked"],
            "staged_paths": groups["staged"],
            "unknown_paths": groups["unknown"],
            "untracked_symlink_paths": groups["untracked_symlinks"],
            "untracked_special_paths": groups["untracked_special"],
            "unstable_untracked_paths": groups["unstable_untracked"],
            "unsafe_untracked_paths": groups["unsafe_untracked"],
            "empty_untracked_file_paths": groups["empty_untracked_files"],
            "required_untracked_paths": groups["required_untracked"],
        },
        "protected_research": {
            **research_runtime,
            "identity_complete": research_runtime["sha256"] is not None,
            "changed_paths": groups["protected_changed"],
        },
        "paths": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "fail if the index is nonempty, a changed path has unknown ownership, "
            "an untracked path is unsafe or unstable, or protected research identity is incomplete"
        ),
    )
    args = parser.parse_args(argv)
    try:
        audit = build_audit(args.repo_root)
    except AuditError as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(audit, indent=2, sort_keys=True))
    gates = audit["review_gates"]
    protected = audit["protected_research"]
    if args.strict and (
        not gates["index_empty"]
        or not gates["ownership_complete"]
        or not gates["untracked_files_safe"]
        or not protected["identity_complete"]
    ):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
