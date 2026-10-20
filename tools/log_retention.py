#!/usr/bin/env python3
"""Bounded log retention: rotate cumulative ``*cron.log`` files and expire dated run logs.

``logs/`` holds two kinds of driver output. Cron appends every run of a driver to one
cumulative file (``cron.log``, ``verify-cron.log`` ...), and each run also tees itself into a
dated log (``run-YYYY-MM-DD.log``). The cumulative copy only exists so the monitors can read the
latest run's markers (``server/driver_log.py``), so it is safe to shrink:

- **Rotate** a cumulative log over ``cap_bytes``: the whole file is compressed to
  ``logs/rotated/<stem>-<UTC stamp>.log.gz``, then the live file is rewritten *in place* (same
  inode, so cron's ``>>`` writer and the scheduler monitor's identity check are unaffected) to a
  one-line rotation note, every run-marker line (``=== <driver> <at> ===``, ``=== done <at> ===``,
  ``TODO: ...`` breadcrumbs, ``STAGE driver=...``) and the last ``tail_bytes`` of output. The
  monitors' newest-start and terminal markers therefore parse exactly as before. A log whose
  driver lock is held, or that was written in the last ``IDLE_SECONDS``, is left alone.
- **Expire** dated logs (a ``YYYY-MM-DD`` in the name) whose date and modification time are both
  older than ``days``, plus rotated archives older than ``days``. A log named in tracked
  repository text (``git grep``: build logs, audits and other evidence cite run logs by name) or
  matching a ``keep`` glob is never deleted. If the evidence scan cannot run, nothing expires.

Nothing changes without ``--apply``; the default prints the candidates. The hourly ops digest
(``tools/ops_digest.py``) runs this once a UTC day, as a dry run unless the host-private
``logs/ops/retention.json`` sets ``"apply": true`` (optional keys: ``days``, ``cap_mb``,
``tail_kb``, ``keep``). Its report goes to ``logs/ops/retention.md``.
"""

from __future__ import annotations

import argparse
import fnmatch
import gzip
import json
import os
import re
import stat
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable

from engine.lib.settings import LOGS_DIR

DEFAULT_DAYS = 60
DEFAULT_CAP_BYTES = 8 * 1024 * 1024
DEFAULT_TAIL_BYTES = 256 * 1024
IDLE_SECONDS = 15 * 60
ROTATED_DIR = "rotated"
CONFIG_NAME = "retention.json"
MARKER_PREFIXES = (b"=== ", b"TODO: ", b"STAGE driver=")
DATED_RE = re.compile(r"(?P<date>\d{4}-\d{2}-\d{2})")
ROTATED_RE = re.compile(r"-(?P<stamp>\d{8}T\d{6}Z)\.log\.gz$")
EVIDENCE_RE = r"[A-Za-z0-9_.-]*[0-9]{4}-[0-9]{2}-[0-9]{2}[A-Za-z0-9_.-]*\.log"

Runner = Callable[[list[str], float], str | None]


def _run(args: list[str], timeout: float) -> str | None:
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    # git grep exits 1 when nothing matches: an empty, successful scan.
    return done.stdout if done.returncode in (0, 1) and not done.stderr.strip() else None


@dataclass
class Config:
    apply: bool = False
    days: int = DEFAULT_DAYS
    cap_bytes: int = DEFAULT_CAP_BYTES
    tail_bytes: int = DEFAULT_TAIL_BYTES
    keep: tuple[str, ...] = ()


@dataclass
class Result:
    applied: bool
    rotate: list[dict] = field(default_factory=list)
    delete: list[dict] = field(default_factory=list)
    kept: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def load_config(ops_dir: Path) -> Config:
    """Host-private settings; a missing or malformed file means the safe defaults."""
    try:
        raw = json.loads((ops_dir / CONFIG_NAME).read_text())
    except (OSError, json.JSONDecodeError):
        return Config()
    if not isinstance(raw, dict):
        return Config()
    config = Config(apply=raw.get("apply") is True)
    try:
        if "days" in raw:
            config.days = max(1, int(raw["days"]))
        if "cap_mb" in raw:
            config.cap_bytes = max(1, int(float(raw["cap_mb"]) * 1024 * 1024))
        if "tail_kb" in raw:
            config.tail_bytes = max(0, int(float(raw["tail_kb"]) * 1024))
    except (TypeError, ValueError):
        return Config()
    keep = raw.get("keep", [])
    config.keep = tuple(item for item in keep if isinstance(item, str)) if isinstance(
        keep, list) else ()
    return config


def is_cumulative(name: str) -> bool:
    return name == "cron.log" or name.endswith("-cron.log")


def _driver_locks() -> dict[str, str]:
    from server.driver_monitor import DRIVER_SCHEDULES

    return {schedule[2]: schedule[3] for schedule in DRIVER_SCHEDULES}


def _lock_held(lock_path: Path) -> bool | None:
    from server import driver_log

    return driver_log._lock_held(lock_path)  # observes /proc/locks; never takes the lock


def referenced_logs(repo_root: Path, run: Runner | None = None) -> set[str] | None:
    """Dated log names cited anywhere in tracked repository text; None if git cannot tell."""
    out = (run or _run)(["git", "-C", str(repo_root), "grep", "-h", "-o", "-I", "-E", EVIDENCE_RE], 120)
    if out is None:
        return None
    return {Path(token).name for token in out.split()}


def _regular(path: Path) -> os.stat_result | None:
    try:
        info = path.lstat()
    except OSError:
        return None
    return info if stat.S_ISREG(info.st_mode) else None


def _file_date(name: str) -> datetime | None:
    match = DATED_RE.search(name)
    if match is None:
        return None
    try:
        return datetime.strptime(match["date"], "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return None


def plan(
    logs_dir: Path, *, repo_root: Path, now: datetime, config: Config,
    run: Runner | None = None,
) -> Result:
    """List what retention would rotate and delete; touches nothing."""
    result = Result(applied=False)
    cutoff = now - timedelta(days=config.days)
    locks = _driver_locks()
    referenced = referenced_logs(repo_root, run)
    if referenced is None:
        result.errors.append("evidence scan (git grep) unavailable: no dated log expires")
    entries = sorted(logs_dir.iterdir()) if logs_dir.is_dir() else []
    for path in entries:
        info = _regular(path)
        if info is None or path.suffix != ".log":
            continue
        name = path.name
        if is_cumulative(name):
            if info.st_size <= config.cap_bytes:
                continue
            item = {"path": path, "bytes": info.st_size}
            lock = locks.get(name)
            if lock is not None and _lock_held(repo_root / lock) is True:
                result.kept.append({**item, "reason": "driver running (lock held)"})
            elif now.timestamp() - info.st_mtime < IDLE_SECONDS:
                result.kept.append({**item, "reason": "written in the last 15 minutes"})
            else:
                result.rotate.append(item)
            continue
        dated = _file_date(name)
        if dated is None or dated >= cutoff:
            continue
        item = {"path": path, "bytes": info.st_size}
        if datetime.fromtimestamp(info.st_mtime, UTC) >= cutoff:
            result.kept.append({**item, "reason": "modified within the retention window"})
        elif any(fnmatch.fnmatch(name, pattern) for pattern in config.keep):
            result.kept.append({**item, "reason": "keep pattern"})
        elif referenced is None:
            result.kept.append({**item, "reason": "evidence scan unavailable"})
        elif name in referenced:
            result.kept.append({**item, "reason": "referenced by tracked evidence"})
        else:
            result.delete.append(item)
    rotated = logs_dir / ROTATED_DIR
    for path in sorted(rotated.iterdir()) if rotated.is_dir() else []:
        info = _regular(path)
        match = ROTATED_RE.search(path.name)
        if info is None or match is None:
            continue
        stamp = datetime.strptime(match["stamp"], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        if stamp < cutoff:
            result.delete.append({"path": path, "bytes": info.st_size})
    return result


def _signature(info: os.stat_result) -> tuple[int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def rotate(path: Path, *, now: datetime, tail_bytes: int) -> dict:
    """Compress ``path`` aside, then rewrite it in place to its markers and recent tail."""
    stamp = now.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    archive_dir = path.parent / ROTATED_DIR
    archive_dir.mkdir(mode=0o700, exist_ok=True)
    archive = archive_dir / f"{path.name.removesuffix('.log')}-{stamp}.log.gz"
    partial = archive.with_name(archive.name + ".tmp")
    fd = os.open(path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
    with os.fdopen(fd, "r+b") as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(f"{path.name} is not a regular file")
        size = before.st_size
        tail_start = max(0, size - tail_bytes)
        if tail_start:
            handle.seek(tail_start - 1)
            if handle.read(1) != b"\n":
                handle.readline()  # start the tail on a whole line
            tail_start = handle.tell()
        markers: list[bytes] = []
        handle.seek(0)
        position = 0
        with gzip.open(partial, "wb") as packed:
            while position < size:
                line = handle.readline(min(1024 * 1024, size - position))
                if not line:
                    break
                packed.write(line)
                if position < tail_start and line.startswith(MARKER_PREFIXES):
                    markers.append(line if line.endswith(b"\n") else line + b"\n")
                position += len(line)
            handle.seek(tail_start)
            tail = handle.read(size - tail_start)
        if position != size or _signature(os.fstat(handle.fileno())) != _signature(before):
            partial.unlink(missing_ok=True)
            raise RuntimeError(f"{path.name} changed while rotating; left as it was")
        os.replace(partial, archive)
        note = (f"--- log-retention {stamp}: {size} bytes rotated to {ROTATED_DIR}/{archive.name};"
                f" kept {len(markers)} earlier run-marker lines and the last {len(tail)} bytes"
                " ---\n").encode()
        body = note + b"".join(markers) + tail
        if _signature(os.fstat(handle.fileno())) != _signature(before):
            raise RuntimeError(f"{path.name} changed while rotating; left as it was")
        handle.seek(0)
        handle.write(body)
        handle.truncate(len(body))
        handle.flush()
        os.fsync(handle.fileno())
        after = os.fstat(handle.fileno())
    return {"path": path, "bytes": size, "kept_bytes": len(body), "archive": archive,
            "inode": after.st_ino}


def apply(result: Result, *, now: datetime, config: Config) -> Result:
    """Carry out a plan. Each file is handled on its own; a failure is recorded, not raised."""
    done = Result(applied=True, kept=list(result.kept), errors=list(result.errors))
    for item in result.rotate:
        try:
            done.rotate.append(rotate(item["path"], now=now, tail_bytes=config.tail_bytes))
        except (OSError, ValueError, RuntimeError) as exc:
            done.errors.append(f"rotate {item['path'].name}: {exc}")
    for item in result.delete:
        try:
            item["path"].unlink()
            done.delete.append(item)
        except OSError as exc:
            done.errors.append(f"delete {item['path'].name}: {exc}")
    return done


def run_retention(
    logs_dir: Path = LOGS_DIR, *, repo_root: Path | None = None, now: datetime | None = None,
    config: Config | None = None, run: Runner | None = None,
) -> Result:
    now = now or datetime.now(UTC)
    config = config or Config()
    result = plan(logs_dir, repo_root=repo_root or logs_dir.parent, now=now, config=config,
                  run=run)
    return apply(result, now=now, config=config) if config.apply else result


def _mb(value: int) -> str:
    return f"{value / 1_048_576:,.1f} MB"


def _label(path: Path) -> str:
    return f"{ROTATED_DIR}/{path.name}" if path.parent.name == ROTATED_DIR else path.name


def render(result: Result, *, now: datetime, config: Config) -> str:
    verb = ("rotated", "deleted") if result.applied else ("would rotate", "would delete")
    mode = "applied" if result.applied else "dry run (nothing changed)"
    lines = [f"# Log retention {now.astimezone(UTC):%Y-%m-%dT%H:%M:%SZ} — {mode}", "",
             f"Cumulative logs over {_mb(config.cap_bytes)} rotate; dated logs older than "
             f"{config.days} days expire unless cited by tracked evidence."]
    if result.errors:
        lines += ["", "**Errors:** " + "; ".join(result.errors)]
    lines += ["", f"## {verb[0].capitalize()} ({len(result.rotate)})", ""]
    lines += [f"- {item['path'].name} {_mb(item['bytes'])}"
              + (f" -> {_mb(item['kept_bytes'])}, archive {ROTATED_DIR}/{item['archive'].name}"
                 if "archive" in item else "") for item in result.rotate] or ["- none"]
    freed = sum(item["bytes"] for item in result.delete)
    lines += ["", f"## {verb[1].capitalize()} ({len(result.delete)}, {_mb(freed)})", ""]
    lines += [f"- {_label(item['path'])} {_mb(item['bytes'])}"
              for item in result.delete] or ["- none"]
    if result.kept:
        lines += ["", f"## Kept ({len(result.kept)})", ""]
        lines += [f"- {item['path'].name}: {item['reason']}" for item in result.kept]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--logs-dir", type=Path, default=LOGS_DIR)
    parser.add_argument("--repo-root", type=Path, default=None,
                        help="checkout whose tracked text is scanned for cited logs")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--cap-mb", type=float, default=DEFAULT_CAP_BYTES / 1024 / 1024)
    parser.add_argument("--tail-kb", type=float, default=DEFAULT_TAIL_BYTES / 1024)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="rotate and delete")
    mode.add_argument("--dry-run", action="store_true", help="list candidates only (default)")
    args = parser.parse_args(argv)
    config = Config(apply=args.apply, days=max(1, args.days),
                    cap_bytes=max(1, int(args.cap_mb * 1024 * 1024)),
                    tail_bytes=max(0, int(args.tail_kb * 1024)))
    now = datetime.now(UTC)
    result = run_retention(args.logs_dir, repo_root=args.repo_root, now=now, config=config)
    print(render(result, now=now, config=config), end="")
    return 1 if result.errors and result.applied else 0


if __name__ == "__main__":
    raise SystemExit(main())
