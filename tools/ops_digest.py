#!/usr/bin/env python3
"""Hourly operations digest: collate the past hour's runs, log signals and probes.

Every hour (``trading-engine-ops-digest.timer``, :08 UTC) this reads what the scheduled work
left behind and writes two things under ``logs/ops/``:

- ``hourly/YYYY-MM-DD/HH.md``: one collated, human- and agent-readable digest per UTC hour
  (unit runs, nightly stages, API probes, new warning/error lines with samples, footprint).
  ``latest.md`` is a copy of the newest digest.
- ``ops.sqlite``: metrics only (run outcomes and durations, per-source line/byte/error counts,
  line signatures, probe latency, ``/meta`` section statuses, disk footprint). Raw log text
  stays in the digests and the source logs; SQLite never stores it.

Sources: the user journal of every timer-activated or running user service, new bytes of the
text logs in ``logs/`` (plus host-private globs listed in ``logs/ops/sources.txt``), the
nightly ``stage-timings.jsonl``, and the local API. It never opens the DuckDB store itself,
but its ``/meta`` probe makes the API hold a read-only connection for about a second, and
DuckDB refuses every writer meanwhile; the timer therefore fires outside every other timer's
start window (``tests/test_ops_digest.py``). Collection is best effort: a missing source is
noted in the digest, never fatal.

``python -m tools.ops_digest --report [--hours 24]`` prints a summary for an agent to start
from: hour statuses, failed, missing and slow runs, every scheduled job's runs checked against
the timers and crontab, each driver's stages, the loudest error signatures and log growth.
"""

from __future__ import annotations

import argparse
import fcntl
import glob
import json
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import time
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from engine.lib.resources import write_text_atomic
from engine.lib.settings import DEFAULT_DB, LOGS_DIR, REPO_ROOT
from tools.stage_timings import load_timings

OPS_DIR = LOGS_DIR / "ops"
DIGEST_RETENTION_DAYS = 30
METRIC_RETENTION_DAYS = 180
MAX_BACKFILL_HOURS = 48
MAX_READ_BYTES = 64 * 1024 * 1024
CLASSIFY_CHARS = 2000
SAMPLES_PER_LEVEL = 5
SLOW_FACTOR = 3.0
SLOW_PROBE_MS = 10_000
API_URL = os.environ.get("TRADING_ENGINE_API_URL", "http://127.0.0.1:8000")
USER_UNIT_DIR = Path.home() / ".config" / "systemd" / "user"
HEALTHY_META = {"ok", "current", "idle", "accumulating", "collecting"}

ERROR_RE = re.compile(
    r"\b(ERROR|CRITICAL|Traceback|Exception)\b|TODO:|\bFAILED\b"
    r'|"status":\s*"(failed|error)"'
)
WARN_RE = re.compile(
    r"\bWARN(ING)?\b|\bwithheld\b|\bnot_ready\b|\bretry(ing)?\b|\bstale\b"
    r'|"status":\s*"(degraded|skipped|partial|invalid)"',
    re.IGNORECASE,
)
IGNORED_UNIT_RE = re.compile(r"^(at-spi|dbus|gvfs|pulseaudio|xdg-|app-)")
SYSTEMD_START_RE = re.compile(r"^Starting .*\.\.\.$")
SYSTEMD_OK_RE = re.compile(r"^(?P<unit>\S+): Succeeded\.$")
SYSTEMD_EXIT_RE = re.compile(
    r"^(?P<unit>\S+): Main process exited, code=\w+, status=(?P<status>\d+)"
)
SYSTEMD_FAIL_RE = re.compile(r"^(?P<unit>\S+): Failed with result '(?P<result>[^']+)'")

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS hours (
  hour TEXT PRIMARY KEY, status TEXT, failed_runs INT, error_lines INT, warn_lines INT,
  collected_at TEXT, digest TEXT);
CREATE TABLE IF NOT EXISTS unit_runs (
  unit TEXT, started TEXT, ended TEXT, seconds REAL, exit_code INT, result TEXT,
  PRIMARY KEY (unit, started));
CREATE TABLE IF NOT EXISTS stage_runs (
  run_id TEXT, stage TEXT, driver TEXT, started TEXT, ended TEXT, seconds REAL,
  exit_code INT, PRIMARY KEY (run_id, stage, started));
CREATE TABLE IF NOT EXISTS log_counts (
  hour TEXT, source TEXT, lines INT, bytes INT, errors INT, warns INT,
  PRIMARY KEY (hour, source));
CREATE TABLE IF NOT EXISTS signatures (
  hour TEXT, source TEXT, level TEXT, signature TEXT, count INT,
  PRIMARY KEY (hour, source, level, signature));
CREATE TABLE IF NOT EXISTS probes (hour TEXT, target TEXT, http_status INT, ms INT,
  PRIMARY KEY (hour, target));
CREATE TABLE IF NOT EXISTS meta_status (hour TEXT, section TEXT, status TEXT,
  PRIMARY KEY (hour, section));
CREATE TABLE IF NOT EXISTS footprint (
  hour TEXT PRIMARY KEY, logs_bytes INT, db_bytes INT, disk_free_bytes INT,
  dirty_files INT, unpushed INT, store_bytes INT);
CREATE TABLE IF NOT EXISTS file_offsets (path TEXT PRIMARY KEY, inode INT, offset INT);
"""

Runner = Callable[[list[str], float], str | None]
Fetch = Callable[[str, float], tuple[int, int, bytes]]


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hour_key(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H")


def floor_hour(moment: datetime) -> datetime:
    return moment.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def classify(line: str) -> str | None:
    head = line[:CLASSIFY_CHARS]
    if ERROR_RE.search(head):
        return "error"
    if WARN_RE.search(head):
        return "warn"
    return None


def signature(line: str) -> str:
    text = re.sub(r"\b[0-9a-f]{8,}\b", "<hex>", line[:CLASSIFY_CHARS].strip())
    text = re.sub(r"\d+", "#", text)
    return re.sub(r"\s+", " ", text)[:160]


@dataclass
class SourceSignals:
    lines: int = 0
    bytes: int = 0
    counts: dict[str, int] = field(default_factory=lambda: {"error": 0, "warn": 0})
    signatures: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int))
    samples: dict[str, list[tuple[str, str]]] = field(
        default_factory=lambda: defaultdict(list))

    def add(self, line: str, *, nbytes: int | None = None) -> None:
        self.lines += 1
        self.bytes += len(line) + 1 if nbytes is None else nbytes
        level = classify(line)
        if level is None:
            return
        self.counts[level] += 1
        sig = signature(line)
        if self.signatures[(level, sig)] == 0 and len(self.samples[level]) < SAMPLES_PER_LEVEL:
            self.samples[level].append((sig, line.strip()[:300]))
        self.signatures[(level, sig)] += 1


@dataclass
class UnitRun:
    unit: str
    started: str | None
    ended: str | None = None
    exit_code: int | None = None
    result: str | None = None


def _run(args: list[str], timeout: float) -> str | None:
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def _fetch(url: str, timeout: float) -> tuple[int, int, bytes]:
    start = time.monotonic()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - loopback
            body = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        body, status = b"", exc.code
    except (OSError, urllib.error.URLError):
        body, status = b"", 0
    return status, int((time.monotonic() - start) * 1000), body


def discover_units(run: Runner) -> list[str]:
    """This user's installed, timer-activated and running services."""
    units: set[str] = {path.name for path in USER_UNIT_DIR.glob("*.service")
                       if "@" not in path.name}
    timers = run(["systemctl", "--user", "list-timers", "--all", "--no-legend"], 30) or ""
    for line in timers.splitlines():
        parts = line.split()
        if parts and parts[-1].endswith(".service"):
            units.add(parts[-1])
    running = run(
        ["systemctl", "--user", "list-units", "--type=service", "--state=running",
         "--no-legend", "--plain"], 30) or ""
    for line in running.splitlines():
        parts = line.split()
        if parts and parts[0].endswith(".service"):
            units.add(parts[0])
    return sorted(unit for unit in units if not IGNORED_UNIT_RE.match(unit))


def parse_journal(
    unit: str, raw: str, signals: SourceSignals
) -> list[UnitRun]:
    """Pair systemd start/finish messages into runs; classify the unit's own output."""
    runs: list[UnitRun] = []
    current: UnitRun | None = None
    for line in raw.splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = entry.get("MESSAGE")
        if not isinstance(message, str):
            continue
        stamp = _iso(datetime.fromtimestamp(int(entry["__REALTIME_TIMESTAMP"]) / 1e6, UTC))
        if entry.get("SYSLOG_IDENTIFIER") != "systemd":
            signals.add(message)
            continue
        if SYSTEMD_START_RE.match(message):
            if current is not None:
                runs.append(current)
            current = UnitRun(unit, stamp)
            continue
        exited = SYSTEMD_EXIT_RE.match(message)
        failed = SYSTEMD_FAIL_RE.match(message)
        if not (exited or failed or SYSTEMD_OK_RE.match(message)):
            continue
        if current is None:
            current = UnitRun(unit, None)
        if exited:
            current.exit_code = int(exited["status"])
            continue
        current.result = failed["result"] if failed else "success"
        if current.exit_code is None and not failed:
            current.exit_code = 0
        current.ended = stamp
        runs.append(current)
        current = None
    if current is not None:
        runs.append(current)
    return runs


def journal_runs(
    run: Runner, units: list[str], start: datetime, end: datetime,
    signals: dict[str, SourceSignals],
) -> tuple[list[UnitRun], list[str]]:
    runs: list[UnitRun] = []
    gaps: list[str] = []
    for unit in units:
        raw = run(
            ["journalctl", "--user", "-u", unit, "--since", f"@{int(start.timestamp())}",
             "--until", f"@{int(end.timestamp())}", "-o", "json", "--no-pager",
             "--output-fields=MESSAGE,SYSLOG_IDENTIFIER"], 60)
        if raw is None:
            gaps.append(f"journal unreadable for {unit}")
            continue
        runs.extend(parse_journal(unit, raw, signals[f"unit:{unit}"]))
    return runs, gaps


def _log_sources(logs_dir: Path, ops_dir: Path) -> list[Path]:
    paths = [
        path for path in sorted(logs_dir.iterdir())
        if path.is_file() and path.suffix in {".log", ".jsonl"}
        and path.name != "stage-timings.jsonl"
    ] if logs_dir.is_dir() else []
    extra = ops_dir / "sources.txt"
    if extra.is_file():
        for line in extra.read_text().splitlines():
            pattern = line.strip()
            if pattern and not pattern.startswith("#"):
                paths.extend(Path(item) for item in sorted(glob.glob(os.path.expanduser(pattern))))
    return paths


def read_new_lines(
    db: sqlite3.Connection, path: Path
) -> tuple[list[str], int] | None:
    """Return the lines appended since the stored offset, and the bytes consumed.

    A file seen for the first time starts at its end, so history is never re-ingested. A
    replaced or truncated file restarts from zero. Reads are capped; skipped bytes are
    still counted.
    """
    try:
        info = path.stat()
    except OSError:
        return None
    key = str(path)
    row = db.execute("SELECT inode, offset FROM file_offsets WHERE path=?", (key,)).fetchone()
    if row is None:
        db.execute("INSERT INTO file_offsets VALUES (?,?,?)", (key, info.st_ino, info.st_size))
        return [], 0
    inode, offset = row
    if inode != info.st_ino or info.st_size < offset:
        offset = 0
    start = max(offset, info.st_size - MAX_READ_BYTES)
    with path.open("rb") as handle:
        handle.seek(start)
        data = handle.read(info.st_size - start)
    cut = data.rfind(b"\n") + 1
    new_offset = start + cut if cut else offset
    db.execute(
        "UPDATE file_offsets SET inode=?, offset=? WHERE path=?",
        (info.st_ino, new_offset, key),
    )
    return data[:cut].decode("utf-8", "replace").splitlines(), new_offset - offset


def collect_files(
    db: sqlite3.Connection, logs_dir: Path, ops_dir: Path, signals: dict[str, SourceSignals]
) -> None:
    """Read new log lines; ``*cron.log`` copies only count lines no dated log already had."""
    seen: set[str] = set()
    sources = sorted(_log_sources(logs_dir, ops_dir), key=lambda p: p.name.endswith("cron.log"))
    for path in sources:
        result = read_new_lines(db, path)
        if result is None:
            continue
        lines, consumed = result
        name = path.name if path.parent == logs_dir else str(path).replace(str(Path.home()), "~")
        target = signals[f"file:{name}"]
        duplicate_copy = path.name.endswith("cron.log")
        for line in lines:
            if duplicate_copy and line in seen:
                target.lines += 1
                continue
            seen.add(line)
            target.add(line, nbytes=0)
        target.bytes += consumed


def collect_stages(db: sqlite3.Connection, logs_dir: Path, start: datetime) -> list[dict]:
    """Store every stage row; return the newly stored ones that ended at or after ``start``."""
    fresh = []
    for row in load_timings(logs_dir / "stage-timings.jsonl"):
        cursor = db.execute(
            "INSERT OR IGNORE INTO stage_runs VALUES (?,?,?,?,?,?,?)",
            (row["run_id"], row["stage"], row["driver"], row.get("started", ""),
             row["ended"], float(row["seconds"]), row["exit"]),
        )
        if cursor.rowcount and row["ended"][:19] >= _iso(start)[:19]:
            fresh.append(row)
    return fresh


def store_runs(db: sqlite3.Connection, runs: list[UnitRun]) -> list[dict]:
    """Insert runs, closing a run that started in an earlier hour. Return stored rows."""
    stored = []
    for item in runs:
        started = item.started
        if started is None:
            open_row = db.execute(
                "SELECT started FROM unit_runs WHERE unit=? AND ended IS NULL "
                "ORDER BY started DESC LIMIT 1", (item.unit,)).fetchone()
            started = open_row[0] if open_row else item.ended
        seconds = None
        if started and item.ended:
            seconds = (
                datetime.fromisoformat(item.ended) - datetime.fromisoformat(started)
            ).total_seconds()
        result = item.result or ("running" if item.ended is None else "unknown")
        db.execute(
            "INSERT INTO unit_runs VALUES (?,?,?,?,?,?) ON CONFLICT(unit, started) DO UPDATE "
            "SET ended=excluded.ended, seconds=excluded.seconds, "
            "exit_code=excluded.exit_code, result=excluded.result",
            (item.unit, started, item.ended, seconds, item.exit_code, result),
        )
        stored.append({"unit": item.unit, "started": started, "ended": item.ended,
                       "seconds": seconds, "exit_code": item.exit_code, "result": result})
    return stored


def typical_seconds(db: sqlite3.Connection, unit: str, before: str) -> float | None:
    rows = [
        row[0] for row in db.execute(
            "SELECT seconds FROM unit_runs WHERE unit=? AND result='success' AND started<? "
            "AND started>=? AND seconds IS NOT NULL",
            (unit, before, _iso(datetime.fromisoformat(before) - timedelta(days=14))),
        )
    ]
    return median(rows) if len(rows) >= 3 else None


def probe(fetch: Fetch) -> tuple[list[dict], dict[str, str]]:
    probes, sections = [], {}
    for target, timeout in (("/health", 5), ("/meta", 30)):
        status, ms, body = fetch(API_URL + target, timeout)
        probes.append({"target": target, "http_status": status, "ms": ms})
        if target == "/meta" and status == 200:
            try:
                meta = json.loads(body)
            except json.JSONDecodeError:
                meta = {}
            for key, value in meta.items() if isinstance(meta, dict) else ():
                if isinstance(value, dict) and isinstance(value.get("status"), str):
                    sections[key] = value["status"]
    return probes, sections


def _tree_bytes(root: Path) -> int:
    """Apparent size of the regular files under ``root``; symlinks are not followed."""
    total = 0
    for base, _dirs, names in os.walk(root):
        for name in names:
            try:
                info = (Path(base) / name).lstat()
            except OSError:  # removed while walking (snapshot pruning)
                continue
            if stat.S_ISREG(info.st_mode):
                total += info.st_size
    return total


def footprint(run: Runner, logs_dir: Path, db_path: Path) -> dict:
    logs_bytes = _tree_bytes(logs_dir)
    db_bytes = db_path.stat().st_size if db_path.exists() else 0
    store_bytes = _tree_bytes(db_path.parent)
    free = shutil.disk_usage(db_path.parent if db_path.parent.exists() else logs_dir).free
    dirty = run(["git", "-C", str(REPO_ROOT), "status", "--porcelain"], 30)
    ahead = run(["git", "-C", str(REPO_ROOT), "rev-list", "--count", "@{u}..HEAD"], 30)
    return {
        "logs_bytes": logs_bytes, "db_bytes": db_bytes, "db_name": db_path.name,
        "store_bytes": store_bytes, "disk_free_bytes": free,
        "dirty_files": len(dirty.splitlines()) if dirty is not None else None,
        "unpushed": int(ahead.strip()) if ahead and ahead.strip().isdigit() else None,
    }


def _mb(value: int | None) -> str:
    return "?" if value is None else f"{value / 1_048_576:,.1f} MB"


def _clock(stamp: str | None) -> str:
    return stamp[11:19] if stamp else "—"


def _duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    minutes, secs = divmod(int(round(seconds)), 60)
    return f"{minutes}m{secs:02d}s" if minutes else f"{secs}s"


def render(hour: datetime, data: dict) -> str:
    end = hour + timedelta(hours=1)
    lines = [
        f"# Ops digest {hour:%Y-%m-%d %H:00}–{end:%H:00} UTC — {data['status']}",
        "",
        f"Collected {data['collected_at']}. {data['failed_runs']} failed run(s), "
        f"{data['error_lines']} error line(s), {data['warn_lines']} warning line(s).",
    ]
    if data["gaps"]:
        lines += ["", "**Collection gaps:** " + "; ".join(data["gaps"])]
    if data["runs"]:
        lines += ["", "## Unit runs", "", "| unit | start | end | duration | typical | result |",
                  "|---|---|---|---|---|---|"]
        for item in data["runs"]:
            typical = _duration(item.get("typical"))
            flag = " ⚠ slow" if item.get("slow") else ""
            result = item["result"] + (
                f" (exit {item['exit_code']})" if item["exit_code"] not in (None, 0) else "")
            lines.append(
                f"| {item['unit'].removesuffix('.service')} | {_clock(item['started'])} | "
                f"{_clock(item['ended'])} | {_duration(item['seconds'])}{flag} | {typical} | "
                f"{result} |")
    if data["stages"]:
        lines += ["", "## Driver stages", "", "| driver | stage | end | duration | exit |",
                  "|---|---|---|---|---|"]
        for row in data["stages"]:
            lines.append(
                f"| {row['driver']} | {row['stage']} | {_clock(row['ended'])} | "
                f"{_duration(float(row['seconds']))} | {row['exit']} |")
    if data["probes"]:
        lines += ["", "## API", ""]
        lines.append(", ".join(
            f"`{p['target']}` {p['http_status'] or 'down'} in {p['ms']} ms"
            for p in data["probes"]))
        unhealthy = {k: v for k, v in data["sections"].items()
                     if v.lower() not in HEALTHY_META}
        if unhealthy:
            lines.append("")
            lines.append("`/meta` sections not ok: " + ", ".join(
                f"{key}={value}" + (" (changed)" if key in data["section_changes"] else "")
                for key, value in sorted(unhealthy.items())))
    noisy = [(name, sig) for name, sig in sorted(data["signals"].items())
             if sig.counts["error"] or sig.counts["warn"]]
    if noisy:
        lines += ["", "## Log signals"]
        for name, sig in noisy:
            lines += ["", f"### {name} — {sig.counts['error']} error, {sig.counts['warn']} warn "
                      f"({sig.lines:,} lines, {_mb(sig.bytes)})", ""]
            for level in ("error", "warn"):
                for sig_text, sample in sig.samples.get(level, []):
                    count = sig.signatures.get((level, sig_text), 0)
                    text = sample.replace("`", "'")
                    lines.append(f"- [{level}] ×{count} `{text}`")
    volume = sorted(data["signals"].items(), key=lambda item: item[1].bytes, reverse=True)
    if volume and volume[0][1].bytes:
        lines += ["", "## Log volume", ""]
        lines.append(", ".join(f"{name} +{_mb(sig.bytes)}"
                               for name, sig in volume[:5] if sig.bytes))
    if data["footprint"]:
        fp = data["footprint"]
        lines += ["", "## Footprint", "",
                  f"logs {_mb(fp['logs_bytes'])}, store {_mb(fp.get('store_bytes'))} "
                  f"({fp.get('db_name', 'database')} {_mb(fp['db_bytes'])}), disk free "
                  f"{_mb(fp['disk_free_bytes'])}, repo {fp['dirty_files']} dirty / "
                  f"{fp['unpushed']} unpushed"]
    return "\n".join(lines) + "\n"


def collect_hour(
    db: sqlite3.Connection, hour: datetime, *, since: datetime | None, run: Runner,
    fetch: Fetch, logs_dir: Path, ops_dir: Path, db_path: Path, now: datetime,
) -> dict:
    """Collect one UTC hour.

    ``since`` is set only for the last hour of a batch: files, stages, probes and footprint
    are read once, attributed to that hour, and stages back to ``since`` are shown.
    """
    last = since is not None
    end = hour + timedelta(hours=1)
    key = _hour_key(hour)
    signals: dict[str, SourceSignals] = defaultdict(SourceSignals)
    units = discover_units(run)
    raw_runs, gaps = journal_runs(run, units, hour, end, signals)
    if not units:
        gaps.append("no user units discovered")
    runs = store_runs(db, raw_runs)
    for item in runs:
        if item["started"] and item["seconds"] is not None:
            item["typical"] = typical_seconds(db, item["unit"], item["started"])
            item["slow"] = bool(item["typical"] and item["seconds"] > SLOW_FACTOR * item["typical"])
    stages = collect_stages(db, logs_dir, since) if since is not None else []
    probes, sections, fp = [], {}, {}
    if last:
        collect_files(db, logs_dir, ops_dir, signals)
        probes, sections = probe(fetch)
        fp = footprint(run, logs_dir, db_path)
    previous = dict(db.execute(
        "SELECT section, status FROM meta_status WHERE hour=("
        "SELECT MAX(hour) FROM meta_status WHERE hour<?)", (key,)).fetchall())
    changes = {k for k, v in sections.items() if previous and previous.get(k) != v}
    failed = [r for r in runs if r["result"] not in ("success", "running")
              or r["exit_code"] not in (None, 0)]
    failed_stages = [row for row in stages if row["exit"] != 0]
    errors = sum(sig.counts["error"] for sig in signals.values())
    warns = sum(sig.counts["warn"] for sig in signals.values())
    health = next((p for p in probes if p["target"] == "/health"), None)
    if failed or failed_stages or (health and health["http_status"] != 200):
        status = "FAIL"
    elif errors or any(r.get("slow") for r in runs) or any(
            p["ms"] > SLOW_PROBE_MS for p in probes):
        status = "WARN"
    else:
        status = "OK"
    data = {
        "status": status, "collected_at": _iso(now), "failed_runs": len(failed) + len(
            failed_stages), "error_lines": errors, "warn_lines": warns, "gaps": gaps,
        "runs": runs, "stages": stages, "probes": probes, "sections": sections,
        "section_changes": changes, "signals": signals, "footprint": fp,
    }
    digest = ops_dir / "hourly" / f"{hour:%Y-%m-%d}" / f"{hour:%H}.md"
    text = render(hour, data)
    write_text_atomic(digest, text)
    for name, sig in signals.items():
        db.execute("INSERT OR REPLACE INTO log_counts VALUES (?,?,?,?,?,?)",
                   (key, name, sig.lines, sig.bytes, sig.counts["error"], sig.counts["warn"]))
        for (level, sig_text), count in sig.signatures.items():
            db.execute("INSERT OR REPLACE INTO signatures VALUES (?,?,?,?,?)",
                       (key, name, level, sig_text, count))
    for item in probes:
        db.execute("INSERT OR REPLACE INTO probes VALUES (?,?,?,?)",
                   (key, item["target"], item["http_status"], item["ms"]))
    for section, value in sections.items():
        db.execute("INSERT OR REPLACE INTO meta_status VALUES (?,?,?)", (key, section, value))
    if fp:
        db.execute("INSERT OR REPLACE INTO footprint (hour, logs_bytes, db_bytes, "
                   "disk_free_bytes, dirty_files, unpushed, store_bytes) VALUES (?,?,?,?,?,?,?)",
                   (key, fp["logs_bytes"], fp["db_bytes"], fp["disk_free_bytes"],
                    fp["dirty_files"], fp["unpushed"], fp["store_bytes"]))
    db.execute("INSERT OR REPLACE INTO hours VALUES (?,?,?,?,?,?,?)",
               (key, status, data["failed_runs"], errors, warns, _iso(now),
                str(digest.relative_to(ops_dir))))
    return {"hour": key, "status": status, "digest": digest, "text": text}


def open_db(ops_dir: Path) -> sqlite3.Connection:
    ops_dir.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(ops_dir / "ops.sqlite", timeout=30)
    db.executescript(SCHEMA)
    if "store_bytes" not in {row[1] for row in db.execute("PRAGMA table_info(footprint)")}:
        db.execute("ALTER TABLE footprint ADD COLUMN store_bytes INT")
    return db


def prune(db: sqlite3.Connection, ops_dir: Path, now: datetime) -> None:
    cutoff = now - timedelta(days=DIGEST_RETENTION_DAYS)
    hourly = ops_dir / "hourly"
    if hourly.is_dir():
        for day in hourly.iterdir():
            if day.is_dir() and day.name < f"{cutoff:%Y-%m-%d}":
                shutil.rmtree(day)
    metric_cutoff = _hour_key(now - timedelta(days=METRIC_RETENTION_DAYS))
    for table in ("hours", "log_counts", "signatures", "probes", "meta_status", "footprint"):
        db.execute(f"DELETE FROM {table} WHERE hour < ?", (metric_cutoff,))  # noqa: S608
    started_cutoff = _iso(now - timedelta(days=METRIC_RETENTION_DAYS))
    db.execute("DELETE FROM unit_runs WHERE started < ?", (started_cutoff,))
    db.execute("DELETE FROM stage_runs WHERE ended < ?", (started_cutoff,))


def collect(
    *, now: datetime | None = None, run: Runner = _run, fetch: Fetch = _fetch,
    logs_dir: Path = LOGS_DIR, ops_dir: Path = OPS_DIR, db_path: Path = DEFAULT_DB,
) -> list[dict]:
    """Collect every closed hour since the last run (at most ``MAX_BACKFILL_HOURS``)."""
    now = now or datetime.now(UTC)
    current = floor_hour(now)
    ops_dir.mkdir(parents=True, exist_ok=True)
    with (ops_dir / ".lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return []
        db = open_db(ops_dir)
        try:
            row = db.execute("SELECT value FROM meta WHERE key='next_hour'").fetchone()
            first = datetime.fromisoformat(row[0]) if row else current - timedelta(hours=1)
            first = max(first, current - timedelta(hours=MAX_BACKFILL_HOURS))
            hours = []
            hour = first
            while hour < current:
                hours.append(hour)
                hour += timedelta(hours=1)
            results = []
            for index, hour in enumerate(hours):
                results.append(collect_hour(
                    db, hour, since=hours[0] if index == len(hours) - 1 else None,
                    run=run, fetch=fetch,
                    logs_dir=logs_dir, ops_dir=ops_dir, db_path=db_path, now=now))
                db.execute("INSERT OR REPLACE INTO meta VALUES ('next_hour', ?)",
                           ((hour + timedelta(hours=1)).isoformat(),))
                db.commit()
            if results:
                write_text_atomic(ops_dir / "latest.md", results[-1]["text"])
            prune(db, ops_dir, now)
            db.commit()
            return results
        finally:
            db.close()


# --------------------------------------------------------------------------- #
# scheduled runs: what the timers and crontab expected versus what ran
# --------------------------------------------------------------------------- #
CRON_TZ = UTC  # cron uses the host zone, which install_automation requires to be UTC
RUN_GRACE_S = 300
LISTED_RUNS = 4
_WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_CRON_WEEKDAYS = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")
_SPAN_RE = re.compile(r"(\d+)\s*(us|ms|min|s|h|d)")
_SPAN_S = {"us": 1e-6, "ms": 1e-3, "s": 1.0, "min": 60.0, "h": 3600.0, "d": 86400.0}
CRON_LINE_RE = re.compile(r"^(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(.+)$")
DRIVER_RE = re.compile(r"/engine/(run_\w+)\.sh\b")
REDIRECT_RE = re.compile(r"(?<![0-9&])>>?\s*(\S+)")
RUN_ID_TIME_RE = re.compile(r"-(\d{8}T\d{6})")
Matcher = Callable[[datetime], bool]


@dataclass
class Schedule:
    job: str
    spec: str
    matcher: Matcher | None  # None: interval timer or unsupported expression
    slack_s: float = 60.0
    unit: str | None = None
    driver: str | None = None
    output: Path | None = None
    appends: bool = False  # ``>>`` output: a silent run leaves no trace, so absence is unknown


@dataclass
class JobRun:
    start: datetime
    seconds: float | None
    ok: bool | None
    label: str


def _span_seconds(text: str) -> float:
    return sum(int(number) * _SPAN_S[unit] for number, unit in _SPAN_RE.findall(text))


def _field(text: str, low: int, high: int,
           names: tuple[str, ...] = ()) -> frozenset[int] | None:
    """Values a cron or systemd calendar field allows; ``None`` means any."""
    if text == "*":
        return None

    def value(token: str) -> int:
        token = token.lower()[:3]
        return names.index(token) if token in names else int(token)

    allowed: set[int] = set()
    for item in text.split(","):
        part, _, step = item.partition("/")
        bounds = [low, high] if part == "*" else [value(b) for b in re.split(r"\.\.|-", part)]
        last = high if step and len(bounds) == 1 else bounds[-1]
        allowed.update(range(bounds[0], last + 1, int(step or 1)))
    return frozenset(allowed)


def _allows(allowed: frozenset[int] | None, value: int) -> bool:
    return allowed is None or value in allowed


def calendar_matcher(spec: str) -> Matcher:
    """Match minutes against a normalized ``OnCalendar`` spec: ``[DOW] Y-M-D H:M:S [TZ]``."""
    tokens = spec.split()
    at = next(index for index, token in enumerate(tokens) if ":" in token)
    if at not in (1, 2) or len(tokens) > at + 2:
        raise ValueError(f"unsupported calendar {spec!r}")
    weekdays = _field(tokens[0], 0, 6, _WEEKDAYS) if at == 2 else None
    year, month, day = (_field(text, low, high) for text, low, high in zip(
        tokens[at - 1].split("-"), (1970, 1, 1), (2199, 12, 31), strict=True))
    hour, minute = (_field(text, low, high) for text, low, high in zip(
        tokens[at].split(":")[:2], (0, 0), (23, 59), strict=True))
    zone = ZoneInfo(tokens[at + 1]) if len(tokens) == at + 2 else UTC

    def matcher(moment: datetime) -> bool:
        local = moment.astimezone(zone)
        return (_allows(weekdays, local.weekday()) and _allows(year, local.year)
                and _allows(month, local.month) and _allows(day, local.day)
                and _allows(hour, local.hour) and _allows(minute, local.minute))
    return matcher


def cron_matcher(fields: list[str]) -> Matcher:
    minute, hour = _field(fields[0], 0, 59), _field(fields[1], 0, 23)
    day, month = _field(fields[2], 1, 31), _field(fields[3], 1, 12)
    cron_days = _field(fields[4], 0, 7, _CRON_WEEKDAYS)
    weekdays = None if cron_days is None else frozenset((d + 6) % 7 for d in cron_days)

    def matcher(moment: datetime) -> bool:
        local = moment.astimezone(CRON_TZ)
        if not (_allows(minute, local.minute) and _allows(hour, local.hour)
                and _allows(month, local.month)):
            return False
        on_day, on_weekday = _allows(day, local.day), _allows(weekdays, local.weekday())
        if day is not None and weekdays is not None:  # cron ORs two restricted day fields
            return on_day or on_weekday
        return on_day and on_weekday
    return matcher


def _any_of(matchers: list[Matcher]) -> Matcher:
    return lambda moment: any(matcher(moment) for matcher in matchers)


def _show_blocks(text: str) -> list[dict[str, list[str]]]:
    blocks: list[dict[str, list[str]]] = []
    current: dict[str, list[str]] = {}
    for line in [*text.splitlines(), ""]:
        if not line.strip():
            if current:
                blocks.append(current)
            current = {}
            continue
        key, _, value = line.partition("=")
        current.setdefault(key, []).append(value)
    return blocks


def _timer_schedule(block: dict[str, list[str]]) -> Schedule | None:
    unit = (block.get("Unit") or [""])[0]
    if not unit or IGNORED_UNIT_RE.match(unit):
        return None
    specs = [spec for value in block.get("TimersCalendar", [])
             for spec in re.findall(r"OnCalendar=(.+?) ;", value)]
    intervals = [spec for value in block.get("TimersMonotonic", [])
                 for spec in re.findall(r"(On\w+=\S+)", value)]
    slack = (_span_seconds((block.get("AccuracyUSec") or ["1min"])[0])
             + _span_seconds((block.get("RandomizedDelayUSec") or ["0"])[0]))
    matcher = None
    if specs and not intervals:
        try:
            matcher = _any_of([calendar_matcher(spec) for spec in specs])
        except (StopIteration, ValueError, ZoneInfoNotFoundError):
            matcher = None
    return Schedule(unit.removesuffix(".service"), "timer " + "; ".join(specs + intervals),
                    matcher, slack, unit=unit)


def timer_schedules(run: Runner) -> list[Schedule]:
    listed = run(["systemctl", "--user", "list-timers", "--no-legend"], 30) or ""
    timers = sorted({part for line in listed.splitlines() for part in line.split()
                     if part.endswith(".timer")})
    if not timers:
        return []
    shown = run(["systemctl", "--user", "show", *timers, "-p", "Unit", "-p", "TimersCalendar",
                 "-p", "TimersMonotonic", "-p", "AccuracyUSec", "-p", "RandomizedDelayUSec"],
                30) or ""
    return [item for item in map(_timer_schedule, _show_blocks(shown)) if item is not None]


def cron_schedules(run: Runner) -> list[Schedule]:
    schedules = []
    for raw in (run(["crontab", "-l"], 30) or "").splitlines():
        line = raw.strip()
        match = CRON_LINE_RE.match(line)
        if match is None or line.startswith(("#", "@")) or "=" in line.split()[0]:
            continue
        *fields, command = match.groups()
        driver = DRIVER_RE.search(command)
        output = REDIRECT_RE.search(command)
        try:
            matcher = cron_matcher(fields)
        except ValueError:
            matcher = None
        job = (driver[1] if driver else Path(output[1]).stem if output
               else Path(command.split()[0]).name)
        schedules.append(Schedule(
            job, "cron " + " ".join(fields), matcher, 60.0, driver=driver[1] if driver else None,
            output=Path(output[1]) if output and not driver else None,
            appends=bool(output and output[0].startswith(">>"))))
    return schedules


def expected_times(matcher: Matcher, start: datetime, end: datetime) -> list[datetime]:
    moment = start.replace(second=0, microsecond=0)
    if moment < start:
        moment += timedelta(minutes=1)
    found = []
    while moment < end:
        if matcher(moment):
            found.append(moment)
        moment += timedelta(minutes=1)
    return found


def _utc(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp[:19]).replace(tzinfo=UTC)


def _driver_runs(db: sqlite3.Connection, since: str, until: str) -> dict[str, list[tuple]]:
    """Driver runs started in the window: ``driver -> [(start, end, stages)]``."""
    grouped: dict[tuple[str, str], list[tuple]] = defaultdict(list)
    for run_id, driver, stage, started, ended, seconds, code in db.execute(
            "SELECT run_id, driver, stage, started, ended, seconds, exit_code FROM stage_runs "
            "WHERE ended>=? ORDER BY started, ended", (since,)):
        grouped[(driver, run_id)].append((stage, started, ended, seconds, code))
    runs: dict[str, list[tuple]] = defaultdict(list)
    for (driver, run_id), stages in grouped.items():
        stamp = RUN_ID_TIME_RE.search(run_id)
        start = (datetime.strptime(stamp[1], "%Y%m%dT%H%M%S").replace(tzinfo=UTC) if stamp
                 else min(_utc(row[1] or row[2]) for row in stages))
        if _iso(start) < since or _iso(start) >= until:
            continue
        runs[driver].append((start, max(_utc(row[2]) for row in stages), stages))
    return runs


def _job_runs(db: sqlite3.Connection, schedule: Schedule, drivers: dict[str, list[tuple]],
              since: str, until: str) -> list[JobRun]:
    if schedule.driver:
        return [JobRun(start, (end - start).total_seconds(),
                       all(row[4] == 0 for row in stages),
                       "ok" if all(row[4] == 0 for row in stages) else "failed")
                for start, end, stages in drivers.get(schedule.driver, [])]
    if schedule.output:
        try:
            written = datetime.fromtimestamp(schedule.output.stat().st_mtime, UTC)
        except OSError:
            return []
        inside = since <= _iso(written) < until
        return [JobRun(written, None, None, "output written")] if inside else []
    rows = db.execute("SELECT started, seconds, result, exit_code FROM unit_runs WHERE unit=? "
                      "AND started>=? AND started<? ORDER BY started",
                      (schedule.unit, since, until)).fetchall()
    return [JobRun(_utc(started), seconds,
                   None if result == "running" else (result == "success" and code in (0, None)),
                   result)
            for started, seconds, result, code in rows]


def _due(schedule: Schedule, start: datetime, end: datetime) -> list[datetime] | None:
    """Scheduled starts whose latest allowed start is before ``end``; None if unknown."""
    if schedule.matcher is None:
        return None
    due = expected_times(schedule.matcher, start,
                         end - timedelta(seconds=schedule.slack_s + RUN_GRACE_S))
    return due[-1:] if schedule.output else due  # one output file proves only the latest run


def _unmatched(schedule: Schedule, due: list[datetime], runs: list[JobRun]) -> list[datetime]:
    late = timedelta(seconds=schedule.slack_s + RUN_GRACE_S)
    return [moment for moment in due if not any(
        moment - timedelta(minutes=1) <= item.start <= moment + late for item in runs)]


def _stamp(moment: datetime) -> str:
    return f"{moment:%m-%d %H:%M}Z"


def _runs_cell(runs: list[JobRun]) -> str:
    def one(item: JobRun) -> str:
        return f"{_stamp(item.start)} {item.label} {_duration(item.seconds)}".rstrip(" —")
    if len(runs) <= LISTED_RUNS:
        return "; ".join(map(one, runs)) or "—"
    timed = [item.seconds for item in runs if item.seconds is not None]
    spread = f"; median {_duration(median(timed))}, max {_duration(max(timed))}" if timed else ""
    return f"last {one(runs[-1])}{spread}"


def runs_lines(db: sqlite3.Connection, run: Runner, start: datetime,
               end: datetime) -> tuple[list[str], list[str]]:
    """Missing-run bullets, then the per-job run table and every driver's stages."""
    since, until = _iso(start), _iso(end)
    schedules = timer_schedules(run) + cron_schedules(run)
    known = {item.unit for item in schedules if item.unit}
    schedules += [Schedule(unit.removesuffix(".service"), "—", None, unit=unit) for (unit,) in
                  db.execute("SELECT DISTINCT unit FROM unit_runs WHERE started>=? AND "
                             "started<?", (since, until)) if unit not in known]
    drivers = _driver_runs(db, since, until)
    missing, table = [], []
    for schedule in sorted(schedules, key=lambda item: item.job):
        runs = _job_runs(db, schedule, drivers, since, until)
        due = _due(schedule, start, end)
        if not runs and due == []:
            continue
        absent = None if due is None else _unmatched(schedule, due, runs)
        if absent and schedule.output and schedule.appends:
            absent = None
        missing += [f"- {schedule.job}: due {_stamp(moment)} (`{schedule.spec}`), no run"
                    for moment in absent or []]
        failed = sum(item.ok is False for item in runs)
        due_cell = "?" if due is None else len(due)
        absent_cell = "?" if absent is None else len(absent)
        table.append(f"| {schedule.job} | `{schedule.spec}` | {due_cell} | {len(runs)} | "
                     f"{failed} | {absent_cell} | {_runs_cell(runs)} |")
    lines = ["", "## Runs", "", f"Current timers and crontab checked against collected runs through "
             f"{until}; a start may lag its schedule by the timer's accuracy and delay plus "
             f"{RUN_GRACE_S // 60} minutes.", "",
             "| job | schedule | due | ran | failed | missing | runs |",
             "|---|---|---|---|---|---|---|", *table]
    stage_lines = [
        f"- {driver} {_stamp(begin)}, {_duration((finish - begin).total_seconds())}: " + " · ".join(
            f"{stage} {_duration(seconds)}" + (f" exit {code}" if code else "")
            for stage, _s, _e, seconds, code in stages)
        for driver, items in sorted(drivers.items()) for begin, finish, stages in items]
    if stage_lines:
        lines += ["", "## Driver stages", "", *stage_lines]
    return missing, lines


def _collected_until(db: sqlite3.Connection, now: datetime, start: datetime) -> datetime:
    latest = db.execute("SELECT MAX(hour) FROM hours").fetchone()[0]
    if latest is None:
        return start
    return min(now, datetime.strptime(latest, "%Y-%m-%dT%H").replace(tzinfo=UTC)
               + timedelta(hours=1))


def report(hours: int, ops_dir: Path = OPS_DIR, now: datetime | None = None,
           run: Runner = _run) -> str:
    """Summarise the last ``hours`` of collected metrics as Markdown."""
    path = ops_dir / "ops.sqlite"
    if not path.exists():
        return "no ops digest collected yet\n"
    now = now or datetime.now(UTC)
    since = _hour_key(floor_hour(now) - timedelta(hours=hours))
    since_iso = _iso(floor_hour(now) - timedelta(hours=hours))
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = db.execute("SELECT hour, status, failed_runs, error_lines, warn_lines, digest "
                          "FROM hours WHERE hour>=? ORDER BY hour", (since,)).fetchall()
        out = [f"# Ops report: last {hours} h (from {since}:00Z)", ""]
        tally = defaultdict(int)
        for row in rows:
            tally[row[1]] += 1
        out.append(f"{len(rows)} hour(s) collected: " + ", ".join(
            f"{count} {status}" for status, count in sorted(tally.items())) + ".")
        bad = [row for row in rows if row[1] != "OK"]
        if bad:
            out += ["", "| hour | status | failed | errors | warns | digest |",
                    "|---|---|---|---|---|---|"]
            out += [f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} | {r[5]} |" for r in bad]
        failed = db.execute(
            "SELECT unit, started, seconds, exit_code, result FROM unit_runs WHERE started>=? "
            "AND (result NOT IN ('success','running') OR exit_code NOT IN (0)) ORDER BY started",
            (since_iso,)).fetchall()
        failed += db.execute(
            "SELECT driver || ':' || stage, started, seconds, exit_code, 'failed' FROM stage_runs "
            "WHERE ended>=? AND exit_code<>0", (since_iso,)).fetchall()
        if failed:
            out += ["", "## Failed runs", ""]
            out += [f"- {u} at {s} ({_duration(sec)}): {res}, exit {code}"
                    for u, s, sec, code, res in failed]
        start = floor_hour(now) - timedelta(hours=hours)
        missing, run_lines = runs_lines(db, run, start, _collected_until(db, now, start))
        if missing:
            out += ["", "## Missing runs", "", *missing]
        out += run_lines
        runs = db.execute("SELECT unit, started, seconds FROM unit_runs WHERE started>=? "
                          "AND result='success' AND seconds IS NOT NULL", (since_iso,)).fetchall()
        slow = []
        for unit, started, seconds in runs:
            typical = typical_seconds(db, unit, started)
            if typical and seconds > SLOW_FACTOR * typical:
                slow.append(f"- {unit} at {started}: {_duration(seconds)} vs typical "
                            f"{_duration(typical)}")
        if slow:
            out += ["", "## Slow runs (over 3× the 14-day median)", "", *slow]
        sigs = db.execute(
            "SELECT source, level, signature, SUM(count) AS n FROM signatures WHERE hour>=? "
            "GROUP BY source, level, signature ORDER BY level='warn', n DESC LIMIT 15",
            (since,)).fetchall()
        if sigs:
            out += ["", "## Loudest signals", ""]
            out += [f"- [{lvl}] ×{n} {src}: `{sig}`" for src, lvl, sig, n in sigs]
        volume = db.execute(
            "SELECT source, SUM(bytes) AS b, SUM(lines) FROM log_counts WHERE hour>=? "
            "GROUP BY source ORDER BY b DESC LIMIT 5", (since,)).fetchall()
        if volume and volume[0][1]:
            out += ["", "## Log growth", ""]
            out += [f"- {src}: +{_mb(b)}, {n:,} lines" for src, b, n in volume if b]
        sections = db.execute(
            "SELECT section, status FROM meta_status WHERE hour=(SELECT MAX(hour) FROM "
            "meta_status)").fetchall()
        unhealthy = [f"{k}={v}" for k, v in sections if v.lower() not in HEALTHY_META]
        if unhealthy:
            out += ["", "Latest `/meta` sections not ok: " + ", ".join(sorted(unhealthy))]
        out += ["", f"Digests: {ops_dir / 'hourly'}/<date>/<HH>.md; metrics: {path}"]
        return "\n".join(out) + "\n"
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--report", action="store_true", help="print a summary and exit")
    parser.add_argument("--hours", type=int, default=24, help="report window in hours")
    args = parser.parse_args(argv)
    if args.report:
        print(report(args.hours), end="")
        return 0
    results = collect()
    for item in results:
        print(f"[ops-digest] {item['hour']} {item['status']} -> {item['digest']}")
    if not results:
        print("[ops-digest] nothing to collect (another run holds the lock or hour not closed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
