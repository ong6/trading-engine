#!/usr/bin/env python3
"""Create, audit, and release exact-base engine worktrees safely."""

from __future__ import annotations

import argparse
import fcntl
import fnmatch
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable

from tools.public_hygiene import public_identity_error

SCHEMA_VERSION = 1
CLAIMS_START = "<!-- tools.lane:claims:v1:start -->"
CLAIMS_END = "<!-- tools.lane:claims:v1:end -->"
HOOK_TEMPLATE = Path(__file__).with_name("public_hygiene_pre_push.sh")
LANE_NAME_RE = re.compile(r"[a-z0-9][a-z0-9._-]*\Z")
FULL_SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
STATUS_FIELDS = frozenset({"lane", "branch", "base", "head"})
GLOB_MAGIC = frozenset("*?[")


class LaneError(RuntimeError):
    """A lane operation was unsafe or inconsistent."""


def _run(
    cwd: Path,
    command: list[str],
    *,
    allowed: tuple[int, ...] = (0,),
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise LaneError(f"command failed to start: {exc}") from exc
    if result.returncode not in allowed:
        reason = result.stderr.strip() or f"exit {result.returncode}"
        raise LaneError(f"{command[0]} {command[1] if len(command) > 1 else ''} failed: {reason}")
    return result


def _git(
    repo: Path,
    *args: str,
    allowed: tuple[int, ...] = (0,),
) -> subprocess.CompletedProcess[str]:
    return _run(repo, ["git", *args], allowed=allowed)


def _git_value(repo: Path, *args: str) -> str:
    return _git(repo, *args).stdout.strip()


def _now() -> datetime:
    return datetime.now(UTC)


def _timestamp(clock: Callable[[], datetime]) -> str:
    value = clock().astimezone(UTC).replace(microsecond=0)
    return value.isoformat().replace("+00:00", "Z")


def _under(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _validated_root(lanes_root: Path, home: Path) -> Path:
    root = lanes_root.resolve()
    expected = (home.resolve() / "engine-lanes").resolve()
    if root != expected or not root.is_dir():
        raise LaneError("lane root must be the current user's engine-lanes directory")
    return root


def _target(root: Path, lane: str, home: Path) -> Path:
    if not LANE_NAME_RE.fullmatch(lane):
        raise LaneError("lane name must be a lowercase path-safe identifier")
    target = root / lane
    if target.parent.resolve() != root:
        raise LaneError("lane target escapes the lane root")
    live = (home.resolve() / "trading-engine").resolve()
    if target.resolve(strict=False) == live:
        raise LaneError("the live checkout is never a lane target")
    return target


def _source(root: Path, source: Path, home: Path) -> Path:
    resolved = source.resolve()
    if not _under(resolved, root):
        raise LaneError("source repository must be inside the lane root")
    if resolved == (home.resolve() / "trading-engine").resolve():
        raise LaneError("the live checkout is never a lane source")
    if not resolved.is_dir():
        raise LaneError("source repository does not exist")
    _git(resolved, "rev-parse", "--git-dir")
    return resolved


def _full_base(source: Path, base: str) -> str:
    if not FULL_SHA_RE.fullmatch(base):
        raise LaneError("base must be a full lowercase commit identity")
    resolved = _git_value(source, "rev-parse", f"{base}^{{commit}}")
    if resolved != base:
        raise LaneError("base does not resolve to the requested exact commit")
    return base


def _valid_branch(source: Path, branch: str) -> None:
    if branch.startswith("-") or not branch:
        raise LaneError("unsafe branch name")
    _git(source, "check-ref-format", "--branch", branch)
    exists = _git(
        source,
        "show-ref",
        "--verify",
        "--quiet",
        f"refs/heads/{branch}",
        allowed=(0, 1),
    ).returncode
    if exists == 0:
        raise LaneError("branch already exists")


def _normalize_claim(value: str) -> str:
    if not value or value.startswith("-") or "\\" in value or any(c in value for c in "\r\n\0"):
        raise LaneError("claim glob is empty or unsafe")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise LaneError("claim glob must be a normalized repository-relative path")
    return path.as_posix()


def _segment_has_magic(segment: str) -> bool:
    return any(character in segment for character in GLOB_MAGIC)


def _segment_disjoint(left: str, right: str) -> bool:
    left_magic = _segment_has_magic(left)
    right_magic = _segment_has_magic(right)
    if not left_magic and not right_magic:
        return left != right
    if not left_magic:
        return not fnmatch.fnmatchcase(left, right)
    if not right_magic:
        return not fnmatch.fnmatchcase(right, left)
    return False


def _exact_matches(pattern: str, exact: str) -> bool:
    pattern_parts = pattern.split("/")
    exact_parts = exact.split("/")
    cache: dict[tuple[int, int], bool] = {}

    def matches(pattern_index: int, exact_index: int) -> bool:
        key = (pattern_index, exact_index)
        if key in cache:
            return cache[key]
        if pattern_index == len(pattern_parts):
            result = exact_index == len(exact_parts)
        elif pattern_parts[pattern_index] == "**":
            result = matches(pattern_index + 1, exact_index) or (
                exact_index < len(exact_parts) and matches(pattern_index, exact_index + 1)
            )
        else:
            result = exact_index < len(exact_parts) and fnmatch.fnmatchcase(
                exact_parts[exact_index], pattern_parts[pattern_index]
            ) and matches(pattern_index + 1, exact_index + 1)
        cache[key] = result
        return result

    return matches(0, 0)


def claims_overlap(left: str, right: str) -> bool:
    """Conservatively decide whether two repository globs can claim one path."""
    if left == right:
        return True
    left_magic = any(character in left for character in GLOB_MAGIC)
    right_magic = any(character in right for character in GLOB_MAGIC)
    if not left_magic and not right_magic:
        return False
    if not left_magic:
        return _exact_matches(right, left)
    if not right_magic:
        return _exact_matches(left, right)
    left_parts = left.split("/")
    right_parts = right.split("/")
    if "**" not in left_parts and "**" not in right_parts:
        if len(left_parts) != len(right_parts):
            return False
        return not any(
            _segment_disjoint(left_part, right_part)
            for left_part, right_part in zip(left_parts, right_parts, strict=True)
        )
    prefix_pairs = zip(left_parts, right_parts, strict=False)
    for left_part, right_part in prefix_pairs:
        if left_part == "**" or right_part == "**":
            break
        if _segment_disjoint(left_part, right_part):
            return False
    suffix_pairs = zip(reversed(left_parts), reversed(right_parts), strict=False)
    for left_part, right_part in suffix_pairs:
        if left_part == "**" or right_part == "**":
            break
        if _segment_disjoint(left_part, right_part):
            return False
    if not left_parts or not right_parts:
        return False
    return True


def _claim_block(rows: Iterable[dict], migration: dict | None = None) -> str:
    lines = [CLAIMS_START, "```jsonl"]
    if migration is not None:
        lines.append(json.dumps(migration, sort_keys=True, separators=(",", ":")))
    lines.extend(
        json.dumps(row, sort_keys=True, separators=(",", ":"))
        for row in sorted(rows, key=lambda item: (item["claimed_at"], item["lane"]))
    )
    lines.extend(("```", CLAIMS_END))
    return "\n".join(lines)


def _parse_claim_document(content: str) -> tuple[list[dict], dict | None]:
    starts = content.count(CLAIMS_START)
    ends = content.count(CLAIMS_END)
    if starts == ends == 0:
        return [], None
    if starts != 1 or ends != 1 or content.index(CLAIMS_START) > content.index(CLAIMS_END):
        raise LaneError("CLAIMS.md has a malformed structured claims block")
    body = content.split(CLAIMS_START, 1)[1].split(CLAIMS_END, 1)[0]
    rows = []
    migration = None
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("```"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise LaneError("CLAIMS.md contains malformed structured JSON") from exc
        if not isinstance(row, dict) or row.get("schema_version") != SCHEMA_VERSION:
            raise LaneError("CLAIMS.md contains an unsupported claim row")
        if row.get("record_type") == "legacy-migration":
            if migration is not None:
                raise LaneError("CLAIMS.md contains duplicate legacy migration records")
            migration = row
            continue
        required = {
            "base_sha",
            "branch",
            "claim_globs",
            "claimed_at",
            "lane",
            "owner",
            "session",
            "state",
        }
        if not required <= row.keys() or row["state"] not in {"active", "released"}:
            raise LaneError("CLAIMS.md contains an incomplete claim row")
        rows.append(row)
    lanes = [row["lane"] for row in rows]
    if len(lanes) != len(set(lanes)):
        raise LaneError("CLAIMS.md contains duplicate structured lanes")
    return rows, migration


def _parse_claims(content: str) -> list[dict]:
    rows, _migration = _parse_claim_document(content)
    return rows


def _legacy_content(content: str) -> str:
    if CLAIMS_START not in content:
        return content
    before, remainder = content.split(CLAIMS_START, 1)
    _block, after = remainder.split(CLAIMS_END, 1)
    heading = "## Structured lane claims"
    stripped = before.rstrip()
    if stripped.endswith(heading):
        stripped = stripped[: -len(heading)].rstrip()
    return f"{stripped}\n{after.lstrip()}"


def _legacy_claim_rows(content: str) -> dict[str, str]:
    result = {}
    for raw in _legacy_content(content).splitlines():
        line = raw.strip()
        if not (line.startswith("|") and line.endswith("|")):
            continue
        cells = [cell.strip() for cell in line[1:-1].split("|")]
        if len(cells) < 3 or cells[0].casefold() == "lane":
            continue
        if all(not cell.strip(":- ") for cell in cells):
            continue
        digest = hashlib.sha256(line.encode()).hexdigest()
        result[digest] = cells[0]
    return result


def _legacy_digest(content: str) -> str:
    return hashlib.sha256(_legacy_content(content).encode()).hexdigest()


def _validate_legacy_migration(
    content: str, rows: list[dict], migration: dict | None
) -> None:
    legacy_rows = _legacy_claim_rows(content)
    if not legacy_rows:
        return
    if migration is None:
        raise LaneError("legacy claims require a reviewed structured migration")
    if (
        migration.get("state") != "complete"
        or migration.get("legacy_sha256") != _legacy_digest(content)
        or not isinstance(migration.get("reviewed_rows"), list)
    ):
        raise LaneError("legacy migration record is incomplete or stale")
    reviewed = migration["reviewed_rows"]
    reviewed_by_digest = {}
    for item in reviewed:
        if (
            not isinstance(item, dict)
            or item.get("state") not in {"active", "released"}
            or not isinstance(item.get("row_sha256"), str)
        ):
            raise LaneError("legacy migration review entry is invalid")
        reviewed_by_digest[item["row_sha256"]] = item["state"]
    if set(reviewed_by_digest) != set(legacy_rows):
        raise LaneError("legacy migration does not review every table row")
    represented = {
        row.get("legacy_row_sha256")
        for row in rows
        if row.get("state") == "active" and row.get("legacy_row_sha256")
    }
    active = {
        digest for digest, state in reviewed_by_digest.items() if state == "active"
    }
    if represented != active:
        raise LaneError("legacy active rows are not exactly represented by structured claims")


def _render_claims(
    content: str, rows: list[dict], migration: dict | None = None
) -> str:
    block = _claim_block(rows, migration)
    if CLAIMS_START not in content:
        prefix = content.rstrip()
        return f"{prefix}\n\n## Structured lane claims\n\n{block}\n" if prefix else f"{block}\n"
    before, remainder = content.split(CLAIMS_START, 1)
    _old, after = remainder.split(CLAIMS_END, 1)
    return f"{before}{block}{after}"


def _atomic_text(path: Path, content: str, mode: int = 0o600) -> None:
    temporary = path.parent / f".{path.name}.tools-lane-{os.getpid()}"
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
            mode,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        raise LaneError(f"could not atomically write {path.name}: {exc}") from exc
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


@contextmanager
def _claims_lock(root: Path):
    path = root / ".CLAIMS.md.lock"
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise LaneError(f"cannot open claims lock: {exc}") from exc
    try:
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode) or details.st_uid != os.getuid():
            raise LaneError("claims lock is not a user-owned regular file")
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def _claims(root: Path) -> tuple[Path, str, list[dict], dict | None]:
    path = root / "CLAIMS.md"
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise LaneError(f"cannot read CLAIMS.md: {exc}") from exc
    rows, migration = _parse_claim_document(content)
    _validate_legacy_migration(content, rows, migration)
    return path, content, rows, migration


def _refuse_overlap(rows: list[dict], claims: tuple[str, ...]) -> None:
    for row in rows:
        if row["state"] != "active":
            continue
        for existing in row["claim_globs"]:
            for requested in claims:
                if claims_overlap(existing, requested):
                    raise LaneError(f"claim overlaps active lane {row['lane']}")


def _admin_dir(target: Path) -> Path:
    config = Path(_git_value(target, "rev-parse", "--git-path", "config.worktree"))
    if not config.is_absolute():
        config = target / config
    return config.resolve(strict=False).parent


def _install_hook(target: Path, template: Path = HOOK_TEMPLATE) -> dict[str, str]:
    try:
        content = template.read_text(encoding="utf-8")
    except OSError as exc:
        raise LaneError(f"cannot read hook template: {exc}") from exc
    _git(target, "config", "extensions.worktreeConfig", "true")
    admin = _admin_dir(target)
    hooks = admin / "hooks"
    hooks.mkdir(mode=0o700, parents=True, exist_ok=True)
    hook = hooks / "pre-push"
    _atomic_text(hook, content, 0o700)
    hook.chmod(0o700)
    _git(target, "config", "--worktree", "core.hooksPath", str(hooks))
    return {
        "path": str(hook),
        "sha256": hashlib.sha256(content.encode()).hexdigest(),
    }


def _install_excludes(target: Path) -> Path:
    excludes = _admin_dir(target) / "lane-excludes"
    _atomic_text(excludes, ".venv\n")
    _git(target, "config", "--worktree", "core.excludesFile", str(excludes))
    return excludes


def _lock_hash(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise LaneError(f"cannot read dependency lock: {exc}") from exc


def _environment_record(target: Path) -> Path:
    return _admin_dir(target) / "lane-environment.json"


def _select_environment(
    root: Path,
    source: Path,
    target: Path,
    *,
    uv: str,
) -> dict:
    target_lock = target / "uv.lock"
    target_hash = _lock_hash(target_lock)
    registry = root / ".shared-venvs"
    registry.mkdir(mode=0o700, exist_ok=True)
    shared_key = registry / target_hash
    source_lock = source / "uv.lock"
    source_venv = source / ".venv"

    if not shared_key.exists() and not shared_key.is_symlink():
        if source_lock.is_file() and _lock_hash(source_lock) == target_hash:
            resolved_venv = source_venv.resolve()
            if (resolved_venv / "bin" / "python").is_file():
                shared_key.symlink_to(resolved_venv, target_is_directory=True)
    if shared_key.is_symlink() and (shared_key.resolve() / "bin" / "python").is_file():
        (target / ".venv").symlink_to(shared_key, target_is_directory=True)
        record = {
            "kind": "shared-read-only",
            "lock_sha256": target_hash,
            "registry_key": str(shared_key),
            "venv": str(shared_key.resolve()),
        }
    else:
        environment = {**os.environ, "UV_PROJECT_ENVIRONMENT": str(target / ".venv")}
        _run(target, [uv, "sync", "--extra", "dev", "--frozen"], env=environment)
        private = target / ".venv"
        if private.is_symlink() or not (private / "bin" / "python").is_file():
            raise LaneError("frozen private environment was not created")
        record = {
            "kind": "private-frozen",
            "lock_sha256": target_hash,
            "registry_key": None,
            "venv": str(private.resolve()),
        }
    _atomic_text(
        _environment_record(target),
        json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n",
    )
    return record


def _public_identity(source: Path, name: str | None, email: str | None) -> tuple[str, str]:
    selected_name = name or _git_value(source, "config", "--get", "user.name")
    selected_email = email or _git_value(source, "config", "--get", "user.email")
    if issue := public_identity_error(selected_name, selected_email):
        raise LaneError(f"public identity rejected by {issue}")
    return selected_name, selected_email


def _protected_stores(target: Path) -> list[str]:
    store = target / "store"
    if not store.is_dir():
        return []
    return sorted(
        path.relative_to(target).as_posix()
        for path in store.rglob("*")
        if path.is_file() and (path.suffix == ".duckdb" or path.name.endswith(".duckdb.wal"))
    )


def _ancestor_pids() -> set[int]:
    result = {os.getpid()}
    current = os.getppid()
    while current > 1 and current not in result:
        result.add(current)
        try:
            raw = Path(f"/proc/{current}/stat").read_text()
            current = int(raw.rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            break
    return result


def _running_pids(target: Path) -> list[int]:
    if not Path("/proc").is_dir():
        return []
    excluded = _ancestor_pids()
    running = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) in excluded:
            continue
        paths = []
        for name in ("cwd", "exe"):
            try:
                paths.append((entry / name).resolve(strict=True))
            except (OSError, RuntimeError):
                pass
        try:
            arguments = (entry / "cmdline").read_bytes().split(b"\0")
        except OSError:
            arguments = []
        for argument in arguments:
            if argument.startswith(b"/"):
                try:
                    paths.append(Path(os.fsdecode(argument)).resolve(strict=True))
                except (OSError, RuntimeError):
                    pass
        try:
            descriptors = (entry / "fd").iterdir()
            for descriptor in descriptors:
                try:
                    paths.append(descriptor.resolve(strict=True))
                except (OSError, RuntimeError):
                    pass
        except OSError:
            pass
        if any(path == target or _under(path, target) for path in paths):
            running.append(int(entry.name))
    return sorted(running)


def _worktree_state(target: Path) -> dict:
    status = _git_value(target, "status", "--porcelain=v1", "--untracked-files=all")
    branch = _git_value(target, "symbolic-ref", "--quiet", "--short", "HEAD")
    stash_lines = _git(target, "stash", "list", "--format=%gs").stdout.splitlines()
    stashes = [line for line in stash_lines if f" {branch}:" in line or line.startswith(f"On {branch}:")]
    unpushed_raw = _git_value(target, "rev-list", "--count", "HEAD", "--not", "--remotes")
    return {
        "branch": branch,
        "dirty": bool(status),
        "stash_count": len(stashes),
        "unpushed_commit_count": int(unpushed_raw or "0"),
    }


def _refuse_existing(target: Path) -> None:
    if not target.exists() and not target.is_symlink():
        return
    details = []
    try:
        state = _worktree_state(target)
        details.extend(key for key in ("dirty",) if state[key])
        if state["stash_count"]:
            details.append("stash")
        if state["unpushed_commit_count"]:
            details.append("unpushed")
    except LaneError:
        details.append("not-a-worktree")
    suffix = f" ({', '.join(details)})" if details else ""
    raise LaneError(f"lane target already exists{suffix}")


def create_lane(
    *,
    lanes_root: Path,
    home: Path,
    lane: str,
    source: Path,
    branch: str,
    base: str,
    claim_globs: Iterable[str],
    owner: str,
    session: str,
    name: str | None = None,
    email: str | None = None,
    uv: str = "uv",
    clock: Callable[[], datetime] = _now,
) -> dict:
    root = _validated_root(lanes_root, home)
    target = _target(root, lane, home)
    source = _source(root, source, home)
    _refuse_existing(target)
    base = _full_base(source, base)
    _valid_branch(source, branch)
    claims = tuple(dict.fromkeys(_normalize_claim(value) for value in claim_globs))
    if not claims:
        raise LaneError("at least one claim glob is required")
    if not owner.strip() or not session.strip():
        raise LaneError("owner and session are required")
    public_name, public_email = _public_identity(source, name, email)

    with _claims_lock(root):
        claims_path, content, rows, migration = _claims(root)
        _refuse_overlap(rows, claims)
        _git(source, "worktree", "add", "-b", branch, str(target), base)
        try:
            _git(target, "config", "--worktree", "user.name", public_name)
        except LaneError:
            _git(target, "config", "extensions.worktreeConfig", "true")
            _git(target, "config", "--worktree", "user.name", public_name)
        _git(target, "config", "--worktree", "user.email", public_email)
        hook = _install_hook(target)
        _install_excludes(target)
        environment = _select_environment(root, source, target, uv=uv)
        if _protected_stores(target):
            raise LaneError("new lane contains a protected store; partial lane retained")
        if _running_pids(target):
            raise LaneError("new lane has a running process; partial lane retained")
        if _worktree_state(target)["dirty"]:
            raise LaneError("new lane is dirty after bootstrap; partial lane retained")
        row = {
            "base_sha": base,
            "branch": branch,
            "claim_globs": list(claims),
            "claimed_at": _timestamp(clock),
            "lane": lane,
            "owner": owner,
            "schema_version": SCHEMA_VERSION,
            "session": session,
            "state": "active",
        }
        rows.append(row)
        _atomic_text(
            claims_path,
            _render_claims(content, rows, migration),
            claims_path.stat().st_mode & 0o777,
        )
    return {"claim": row, "environment": environment, "hook": hook, "target": str(target)}


def _status_fields(path: Path) -> tuple[bool, dict[str, str]]:
    try:
        details = path.lstat()
        content = path.read_text(encoding="utf-8")
    except OSError:
        return False, {}
    if not stat.S_ISREG(details.st_mode) or stat.S_ISLNK(details.st_mode):
        return False, {}
    lines = content.splitlines()
    fields = {}
    for line in lines[1:]:
        key, separator, value = line.partition(":")
        normalized = key.strip().casefold()
        if separator and normalized in STATUS_FIELDS:
            fields[normalized] = value.strip()
    return bool(lines and lines[0].strip() == "done"), fields


def _read_environment(target: Path) -> dict | None:
    try:
        return json.loads(_environment_record(target).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _audit_unlocked(
    root: Path,
    home: Path,
    lane: str,
    status_path: Path,
    rows: list[dict],
    template: Path = HOOK_TEMPLATE,
) -> dict:
    target = _target(root, lane, home)
    matching = [row for row in rows if row["lane"] == lane]
    claim = matching[0] if matching else None
    checks: dict[str, bool] = {"claim_exists": claim is not None}
    if claim is None or not target.is_dir():
        checks["target_exists"] = target.is_dir()
        return {"checks": checks, "ok": False}
    checks["target_exists"] = True
    try:
        state = _worktree_state(target)
        head = _git_value(target, "rev-parse", "HEAD")
        base_is_ancestor = (
            _git(
                target,
                "merge-base",
                "--is-ancestor",
                claim["base_sha"],
                head,
                allowed=(0, 1),
            ).returncode
            == 0
        )
        identity_name = _git_value(target, "config", "--worktree", "--get", "user.name")
        identity_email = _git_value(target, "config", "--worktree", "--get", "user.email")
        hook_path = Path(_git_value(target, "config", "--worktree", "--get", "core.hooksPath"))
        excludes_path = Path(
            _git_value(target, "config", "--worktree", "--get", "core.excludesFile")
        )
        expected_hook = template.read_bytes()
        actual_hook = (hook_path / "pre-push").read_bytes()
        actual_excludes = excludes_path.read_text(encoding="utf-8")
        environment = _read_environment(target)
        current_lock = _lock_hash(target / "uv.lock")
    except (LaneError, OSError):
        checks["git_private_state_readable"] = False
        return {"checks": checks, "ok": False}
    checks.update(
        {
            "active_claim": claim["state"] == "active",
            "base_is_ancestor": base_is_ancestor,
            "branch_matches": state["branch"] == claim["branch"],
            "hook_matches": actual_hook == expected_hook and os.access(hook_path / "pre-push", os.X_OK),
            "private_excludes": actual_excludes == ".venv\n",
            "public_identity": public_identity_error(identity_name, identity_email) is None,
            "stash_free": state["stash_count"] == 0,
            "store_free": not _protected_stores(target),
            "worktree_clean": not state["dirty"],
            "running_process_free": not _running_pids(target),
        }
    )
    environment_ok = bool(environment and environment.get("lock_sha256") == current_lock)
    if environment_ok and environment["kind"] == "shared-read-only":
        venv = target / ".venv"
        environment_ok = (
            venv.is_symlink()
            and venv.resolve() == Path(environment["venv"]).resolve()
            and Path(environment["registry_key"]) == root / ".shared-venvs" / current_lock
        )
    elif environment_ok and environment["kind"] == "private-frozen":
        venv = target / ".venv"
        environment_ok = not venv.is_symlink() and (venv / "bin" / "python").is_file()
    else:
        environment_ok = False
    checks["environment_matches"] = environment_ok

    status_done, fields = _status_fields(status_path)
    checks.update(
        {
            "status_done": status_done,
            "status_lane_matches": fields.get("lane") == lane,
            "status_branch_matches": fields.get("branch") == claim["branch"],
            "status_base_matches": fields.get("base") == claim["base_sha"],
            "status_head_matches": fields.get("head") == head,
        }
    )
    return {
        "base_sha": claim["base_sha"],
        "branch": state["branch"],
        "checks": checks,
        "head_sha": head,
        "lane": lane,
        "ok": all(checks.values()),
        "unpushed_commit_count": state["unpushed_commit_count"],
    }


def audit_lane(
    *, lanes_root: Path, home: Path, lane: str, status_path: Path | None = None
) -> dict:
    root = _validated_root(lanes_root, home)
    status = status_path or home / ".tae" / "out" / lane / "STATUS"
    with _claims_lock(root):
        _path, _content, rows, _migration = _claims(root)
        return _audit_unlocked(root, home, lane, status, rows)


def release_lane(
    *,
    lanes_root: Path,
    home: Path,
    lane: str,
    status_path: Path | None = None,
    clock: Callable[[], datetime] = _now,
) -> dict:
    root = _validated_root(lanes_root, home)
    status = status_path or home / ".tae" / "out" / lane / "STATUS"
    with _claims_lock(root):
        path, content, rows, migration = _claims(root)
        report = _audit_unlocked(root, home, lane, status, rows)
        if not report["ok"]:
            failed = sorted(key for key, passed in report["checks"].items() if not passed)
            raise LaneError(f"handoff audit failed: {', '.join(failed)}")
        row = next(item for item in rows if item["lane"] == lane)
        row["head_sha"] = report["head_sha"]
        row["released_at"] = _timestamp(clock)
        row["state"] = "released"
        _atomic_text(
            path,
            _render_claims(content, rows, migration),
            path.stat().st_mode & 0o777,
        )
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("lane")
    create.add_argument("--source", type=Path, required=True)
    create.add_argument("--branch", required=True)
    create.add_argument("--base", required=True)
    create.add_argument("--claim", action="append", required=True)
    create.add_argument("--owner", required=True)
    create.add_argument("--session", required=True)
    create.add_argument("--name")
    create.add_argument("--email")
    create.add_argument("--uv", default="uv")
    for command in (subparsers.add_parser("audit"), subparsers.add_parser("release")):
        command.add_argument("lane")
        command.add_argument("--status", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    home = Path.home()
    lanes_root = home / "engine-lanes"
    try:
        if args.command == "create":
            result = create_lane(
                lanes_root=lanes_root,
                home=home,
                lane=args.lane,
                source=args.source,
                branch=args.branch,
                base=args.base,
                claim_globs=args.claim,
                owner=args.owner,
                session=args.session,
                name=args.name,
                email=args.email,
                uv=args.uv,
            )
        elif args.command == "audit":
            result = audit_lane(
                lanes_root=lanes_root,
                home=home,
                lane=args.lane,
                status_path=args.status,
            )
        else:
            result = release_lane(
                lanes_root=lanes_root,
                home=home,
                lane=args.lane,
                status_path=args.status,
            )
    except LaneError as exc:
        print(f"lane: ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
