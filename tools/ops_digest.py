#!/usr/bin/env python3
"""Hourly operations digest: collate the past hour's runs, log signals and probes.

Every hour (``trading-engine-ops-digest.timer``, :08 UTC) this reads what the scheduled work
left behind and writes two things under ``logs/ops/``:

- ``hourly/YYYY-MM-DD/HH.md``: one collated, human- and agent-readable digest per UTC hour
  (unit runs, nightly stages, API probes, the GET-only model gateway preflight from
  ``tools.model_gateway_check``, new warning/error lines with samples, footprint).
  ``latest.md`` is a copy of the newest digest.
- ``ops.sqlite``: metrics only (run outcomes and durations, per-source line/byte/error counts,
  line signatures, probe latency, ``/meta`` section statuses, disk footprint). Raw log text
  stays in the digests and the source logs; SQLite never stores it.

Sources: the user journal of every timer-activated or running user service, new bytes of the
text logs in ``logs/`` (plus host-private globs listed in ``logs/ops/sources.txt``), the
nightly ``stage-timings.jsonl``, dated work receipts from one immutable published snapshot and
observer JSONL files, and the local API. It never opens the primary DuckDB store,
but its ``/meta`` probe makes the API hold a read-only connection for about a second, and
DuckDB refuses every writer meanwhile; the timer therefore fires outside every other timer's
start window (``tests/test_ops_digest.py``). Collection is best effort: a missing source is
noted in the digest, never fatal.

Once a UTC day, at the first collection from ``LOG_RETENTION_HOUR``, it also runs
``tools/log_retention.py`` over ``logs/`` (rotate oversized ``*cron.log``, expire old dated logs)
and writes ``logs/ops/retention.md``; that is a dry run unless the host-private
``logs/ops/retention.json`` sets ``"apply": true``.

``python -m tools.ops_digest --report [--hours 24]`` prints a summary for an agent to start
from: hour statuses, failed, degraded, missing, unknown and slow runs, scheduled work checked
only against observed installed schedule intervals, each driver's stages, log signals and growth.

Each run also checks the host and schedule contract (``server/schedule_contract.py``, read-only)
and writes the result to ``logs/ops/schedule-contract.json``, which ``/meta`` projects as
``schedule_contract``; any violation makes the hour WARN.

When the published snapshot's sha256 differs from the last invariant result, the run also checks
the snapshot invariants in shadow mode (``python -m tools.check_invariants``, read-only on the
snapshot, never the live store) into ``logs/ops/invariants.json``, projected as ``/meta``
``invariants``. Shadow regressions are listed but never change the hour's status.
"""

from __future__ import annotations

import argparse
import fcntl
import glob
import json
import math
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Callable, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import duckdb

from engine import job_contract
from engine.lib import db
from engine.lib.resources import write_text_atomic
from engine.lib.settings import DEFAULT_DB, LOGS_DIR, REPO_ROOT
from engine.lib.snapshots import latest_snapshot
from server import agent_model_client, schedule_contract
from server.json_utils import loads_object
from tools import log_retention, model_gateway_check
from tools.stage_timings import FLOW_FIELDS, load_timings

OPS_DIR = LOGS_DIR / "ops"
DIGEST_RETENTION_DAYS = 30
METRIC_RETENTION_DAYS = 180
MAX_BACKFILL_HOURS = 48
LOG_RETENTION_HOUR = 10  # UTC: clear of the nightly, the weekend verify and the live windows
MAX_READ_BYTES = 64 * 1024 * 1024
CLASSIFY_CHARS = 2000
SAMPLES_PER_LEVEL = 5
SLOW_FACTOR = 3.0
SLOW_PROBE_MS = 10_000
API_URL = os.environ.get("TRADING_ENGINE_API_URL", "http://127.0.0.1:8000")
GATEWAY_URL = f"http://{agent_model_client.PROXY_HOST}:{agent_model_client.PROXY_PORT}"
USER_UNIT_DIR = Path.home() / ".config" / "systemd" / "user"
HEALTHY_META = {"ok", "current", "idle", "accumulating", "collecting"}

ERROR_RE = re.compile(
    r"\b(ERROR|CRITICAL|Traceback|Exception)\b|TODO:|\bFAILED\b"
    r'|"status":\s*"(failed|error)"'
)
WARN_RE = re.compile(
    r"\bWARN(ING)?\b|\bwithheld\b|\bnot_ready\b|\bretry(ing)?\b|\bstale\b"
    r'|"status":\s*"(degraded|skipped|partial|invalid|unavailable|late)"'
    r"|\bstatus=(unavailable|late|partial|degraded)\b"
    r"|\brebase conflict\b|\brefus(ed|ing|al)\b"
    r"|\b(drain budget exhausted|resource guard tripped)\b"
    r"|active process holds .*backup not started",
    re.IGNORECASE,
)
HOST_FAILURE_RE = re.compile(
    r"\b(fetch|push) failed\b|\b\w+ failed \(non-fatal\)"
    r"|\bstatus=(failed|error)\b|\bfatal:|\bTIMEOUT\b"
    r"|\[queue[^]]*\].*\bfailed\b", re.IGNORECASE)
DRAIN_OUTCOME_RE = re.compile(
    r"\[queue\] drain outcome: \d+ done, (\d+) timed out, (\d+) failed, (\d+) left pending")
FAILED_COUNT_RE = re.compile(
    r'\b(failed(?:_this_run)?|unavailable_count)["\s]*[:=]\s*([1-9]\d*)\b')
HOST_LOG_GLOBS = (
    "~/.local/state/te-autopush.log", "~/.local/state/store-sync.log",
    "~/news-scraper/logs/ensure_scraper.log", "~/news-scraper/logs/*.log",
)
IGNORED_UNIT_RE = re.compile(r"^(at-spi|dbus|gvfs|pulseaudio|xdg-|app-)")
SYSTEMD_START_RE = re.compile(r"^Starting .*\.\.\.$")
SYSTEMD_OK_RE = re.compile(r"^(?P<unit>\S+): Succeeded\.$")
SYSTEMD_EXIT_RE = re.compile(
    r"^(?P<unit>\S+): Main process exited, code=(?P<kind>\w+), status=(?P<status>\d+)"
)
SYSTEMD_FAIL_RE = re.compile(r"^(?P<unit>\S+): Failed with result '(?P<result>[^']+)'")
# The data backup exits 75 when engine locks are busy and its unit maps 75 to success
# (SuccessExitStatus=75), so systemd logs "Succeeded." for a run that backed up nothing.
SKIPPED_RESULT = "skipped/retry"
SKIPPED_RUN_RE = {
    "trading-data-backup.service": re.compile(
        r"\b(engine|research) locks busy: |\banother backup is running\b"
    ),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS hours (
  hour TEXT PRIMARY KEY, status TEXT, failed_runs INT, error_lines INT, warn_lines INT,
  collected_at TEXT, digest TEXT);
CREATE TABLE IF NOT EXISTS unit_runs (
  unit TEXT, started TEXT, ended TEXT, seconds REAL, exit_code INT, result TEXT,
  termination_kind TEXT,
  PRIMARY KEY (unit, started));
CREATE TABLE IF NOT EXISTS stage_runs (
  run_id TEXT, stage TEXT, driver TEXT, started TEXT, ended TEXT, seconds REAL,
  exit_code INT, input_rows REAL, output_rows REAL, input_bytes REAL, output_bytes REAL,
  writer_hold_seconds REAL, lock_wait_seconds REAL,
  PRIMARY KEY (run_id, stage, started));
CREATE TABLE IF NOT EXISTS job_runs (
  run_id TEXT, attempt INT, job_id TEXT, spec_version INT, spec_sha256 TEXT,
  idempotency_key TEXT, scheduled_for TEXT, started TEXT, ended TEXT, seconds REAL,
  process_exit INT, work_status TEXT, reason TEXT, retry_disposition TEXT,
  catch_up_disposition TEXT, receipt_path TEXT, alert_state TEXT, alert_after TEXT,
  PRIMARY KEY (run_id, attempt));
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
ContractProbe = Callable[[datetime], dict]
CONTRACT_RESULT = "schedule-contract.json"
InvariantsProbe = Callable[[Path], dict]
INVARIANTS_RESULT = "invariants.json"
INVARIANTS_TIMEOUT_S = 300
INVARIANTS_LISTED = 3


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hour_key(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H")


def floor_hour(moment: datetime) -> datetime:
    return moment.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def classify(line: str) -> str | None:
    head = line[:CLASSIFY_CHARS]
    # These producers print a structured, justified skip for a fresh snapshot, same-day
    # successful backup or a non-session tick. They are completed no-ops.
    try:
        payload = json.loads(head)
    except (ValueError, TypeError):
        payload = None
    if isinstance(payload, dict) and payload.get("status") == "skipped" and any(
            phrase in str(payload.get("reason", "")).lower() for phrase in (
                "latest snapshot is", "already successfully", "already successful",
                "not a trading session", "no session")):
        return None
    # The queue's drain summary names every outcome, so classify it by its counts:
    # "0 timed out, 0 failed" is a clean drain, not a failure.
    if outcome := DRAIN_OUTCOME_RE.search(head):
        timed_out, failed, pending = (int(value) for value in outcome.groups())
        return "error" if timed_out or failed else ("warn" if pending else None)
    if ERROR_RE.search(head) or HOST_FAILURE_RE.search(head):
        return "error"
    if WARN_RE.search(head) or FAILED_COUNT_RE.search(head):
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
    termination_kind: str | None = None


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
    skipped_re = SKIPPED_RUN_RE.get(unit)
    skipped = False
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
            skipped = skipped or bool(skipped_re and skipped_re.search(message))
            continue
        if SYSTEMD_START_RE.match(message):
            if current is not None:
                runs.append(current)
            current = UnitRun(unit, stamp)
            skipped = False
            continue
        exited = SYSTEMD_EXIT_RE.match(message)
        failed = SYSTEMD_FAIL_RE.match(message)
        if not (exited or failed or SYSTEMD_OK_RE.match(message)):
            continue
        if current is None:
            current = UnitRun(unit, None)
        if exited:
            current.exit_code = int(exited["status"])
            current.termination_kind = exited["kind"]
            continue
        current.result = failed["result"] if failed else (
            SKIPPED_RESULT if skipped else "success")
        if current.exit_code is None and not failed:
            current.exit_code = 75 if skipped else 0
        current.ended = stamp
        runs.append(current)
        current = None
        skipped = False
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
    patterns = list(HOST_LOG_GLOBS)
    if extra.is_file():
        for line in extra.read_text().splitlines():
            pattern = line.strip()
            if pattern and not pattern.startswith("#"):
                patterns.append(pattern)
    for pattern in patterns:
        # sources.txt accepts both common home forms, and relative globs mean logs/ops/.
        expanded = os.path.expandvars(os.path.expanduser(pattern))
        if not Path(expanded).is_absolute():
            expanded = str(ops_dir / expanded)
        paths.extend(Path(item) for item in sorted(glob.glob(expanded)))
    return list(dict.fromkeys(path.resolve() for path in paths if path.is_file()))


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
        flow = {
            field: (
                float(row[field])
                if field in row
                and not isinstance(row[field], bool)
                and isinstance(row[field], (int, float))
                and math.isfinite(row[field])
                and row[field] >= 0
                else None
            )
            for field in FLOW_FIELDS
        }
        cursor = db.execute(
            "INSERT OR IGNORE INTO stage_runs (run_id, stage, driver, started, ended, seconds, "
            "exit_code, input_rows, output_rows, input_bytes, output_bytes, "
            "writer_hold_seconds, lock_wait_seconds) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (row["run_id"], row["stage"], row["driver"], row.get("started", ""),
             row["ended"], float(row["seconds"]), row["exit"],
             *(flow[field] for field in FLOW_FIELDS)),
        )
        row = {**row, **flow}
        if cursor.rowcount and row["ended"][:19] >= _iso(start)[:19]:
            fresh.append(row)
    return fresh


def _job_receipt_row(receipt: Mapping[str, object], receipt_path: str = "") -> tuple:
    statuses = {
        "success", "noop", "degraded", "retryable_failure", "terminal_failure",
        "interrupted", "superseded",
    }
    required = ("run_id", "job_id", "spec_sha256", "idempotency_key", "scheduled_for",
                "started_at", "ended_at", "work_status", "reason")
    if receipt.get("schema_version") != 1 or any(
        not isinstance(receipt.get(field), str) or not receipt[field] for field in required
    ):
        raise ValueError("malformed registered job receipt")
    if receipt["work_status"] not in statuses:
        raise ValueError("unknown registered job status")
    attempt = receipt.get("attempt")
    version = receipt.get("spec_version")
    process_exit = receipt.get("process_exit")
    if (isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1
            or isinstance(version, bool) or not isinstance(version, int) or version < 1
            or process_exit is not None
            and (isinstance(process_exit, bool) or not isinstance(process_exit, int))):
        raise ValueError("malformed registered job receipt numbers")
    began = datetime.fromisoformat(str(receipt["started_at"]).replace("Z", "+00:00"))
    ended = datetime.fromisoformat(str(receipt["ended_at"]).replace("Z", "+00:00"))
    seconds = max(0.0, (ended - began).total_seconds())
    reason = str(receipt["reason"])
    if len(reason) > 2000:
        raise ValueError("registered job reason is too long")
    return (
        receipt["run_id"], attempt, receipt["job_id"], version, receipt["spec_sha256"],
        receipt["idempotency_key"], receipt["scheduled_for"], receipt["started_at"],
        receipt["ended_at"], seconds, process_exit, receipt["work_status"], reason,
        str(receipt.get("retry_disposition", "none")),
        str(receipt.get("catch_up_disposition", "scheduled")), receipt_path,
    )


def store_job_receipt(
    db: sqlite3.Connection, receipt: Mapping[str, object], receipt_path: str = ""
) -> bool:
    row = _job_receipt_row(receipt, receipt_path)
    cursor = db.execute(
        "INSERT OR IGNORE INTO job_runs (run_id, attempt, job_id, spec_version, spec_sha256, "
        "idempotency_key, scheduled_for, started, ended, seconds, process_exit, work_status, "
        "reason, retry_disposition, catch_up_disposition, receipt_path) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        row,
    )
    inserted = bool(cursor.rowcount)
    if not inserted and receipt_path:
        db.execute(
            "UPDATE job_runs SET receipt_path=? WHERE run_id=? AND attempt=? "
            "AND COALESCE(receipt_path, '')=''",
            (receipt_path, row[0], row[1]),
        )
    return inserted


def project_job_receipt(receipt: Mapping[str, object], ops_dir: Path = OPS_DIR) -> None:
    """Project one immutable runner receipt into the existing operations database."""
    db = open_db(ops_dir)
    try:
        store_job_receipt(db, receipt)
        db.commit()
    finally:
        db.close()


def collect_job_receipts(
    db: sqlite3.Connection, logs_dir: Path, start: datetime
) -> tuple[list[dict], list[str]]:
    fresh, gaps = [], []
    root = logs_dir / "job-runs"
    if not root.is_dir():
        return fresh, gaps
    for path in sorted(root.glob("**/*.json")):
        if path.name.endswith(".running.json"):
            continue
        try:
            if path.stat().st_size > 1_048_576:
                raise ValueError("receipt exceeds size bound")
            receipt = json.loads(path.read_text())
            if not isinstance(receipt, dict):
                raise ValueError("receipt is not an object")
            store_job_receipt(db, receipt, str(path.relative_to(logs_dir)))
            ended = datetime.fromisoformat(receipt["ended_at"].replace("Z", "+00:00"))
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            gaps.append(f"malformed registered job receipt: {path.name}")
            continue
        if ended >= start:
            fresh.append(receipt)
    return fresh, gaps


def registered_receipt_alerts(
    receipts: list[dict], now: datetime, repo_root: Path = REPO_ROOT,
    db: sqlite3.Connection | None = None,
) -> tuple[list[dict], list[dict], list[str]]:
    """Apply the exact registered alert policy to immutable generic receipts."""
    try:
        registry = job_contract.load_registry(repo_root)
    except job_contract.JobContractError as exc:
        return [], [], [f"invalid-registry-for-receipts:{exc}"]
    failures, warnings, errors = [], [], []
    for receipt in receipts:
        identity = f"{receipt.get('run_id', '?')}:{receipt.get('attempt', '?')}"
        key = (receipt.get("run_id"), receipt.get("attempt"))

        def disposition(
            state: str, after: str | None = None, receipt_key: tuple = key
        ) -> None:
            if db is not None:
                db.execute(
                    "UPDATE job_runs SET alert_state=?, alert_after=? "
                    "WHERE run_id=? AND attempt=?",
                    (state, after, *receipt_key),
                )

        spec = registry.by_id.get(str(receipt.get("job_id", "")))
        if spec is None:
            errors.append(f"unknown-job-receipt:{receipt.get('job_id', '?')}:{identity}")
            continue
        if (receipt.get("spec_version") != spec.version
                or receipt.get("spec_sha256") != spec.spec_sha256):
            errors.append(f"job-receipt-spec-mismatch:{spec.job_id}:{identity}")
            continue
        status = receipt.get("work_status")
        if status in {"success", "noop"}:
            disposition("resolved")
            continue
        if receipt.get("retry_disposition") == "retry" and db is not None:
            later = db.execute(
                "SELECT 1 FROM job_runs WHERE run_id=? AND attempt>? "
                "AND work_status IN ('success','noop') LIMIT 1",
                (receipt["run_id"], receipt["attempt"]),
            ).fetchone()
            if later:
                disposition("resolved")
                continue
        ended = datetime.fromisoformat(str(receipt["ended_at"]).replace("Z", "+00:00"))
        grace = timedelta(seconds=float(spec.alert["grace_seconds"]))
        alert_after = ended.astimezone(UTC) + grace
        if now.astimezone(UTC) < alert_after:
            disposition("pending", _iso(alert_after))
            continue
        severity = spec.alert["severity"]
        if severity == "ignore":
            disposition("ignored")
            continue
        transient = (
            status in {"degraded", "superseded"}
            or receipt.get("retry_disposition") == "retry"
        )
        if severity == "WARN" or transient:
            warnings.append(receipt)
            disposition("warned", _iso(alert_after))
        else:
            failures.append(receipt)
            disposition("failed", _iso(alert_after))
    return failures, warnings, errors


def pending_job_receipts(db: sqlite3.Connection) -> list[dict]:
    rows = db.execute(
        "SELECT run_id, attempt, job_id, spec_version, spec_sha256, idempotency_key, "
        "scheduled_for, started, ended, process_exit, work_status, reason, retry_disposition, "
        "catch_up_disposition FROM job_runs WHERE work_status NOT IN ('success','noop') "
        "AND COALESCE(alert_state, 'pending')='pending' ORDER BY ended, attempt"
    ).fetchall()
    fields = (
        "run_id", "attempt", "job_id", "spec_version", "spec_sha256", "idempotency_key",
        "scheduled_for", "started_at", "ended_at", "process_exit", "work_status", "reason",
        "retry_disposition", "catch_up_disposition",
    )
    return [dict(zip(fields, row, strict=True)) for row in rows]


def store_runs(db: sqlite3.Connection, runs: list[UnitRun]) -> list[dict]:
    """Insert runs, closing a run that started in an earlier hour. Return stored rows."""
    stored = []
    for item in runs:
        started = item.started
        if started is None:
            open_row = db.execute(
                "SELECT started FROM unit_runs WHERE unit=? AND ended IS NULL "
                "ORDER BY started DESC LIMIT 1", (item.unit,)).fetchone()
            started = open_row[0] if open_row else None
        seconds = None
        if started and item.ended:
            seconds = (
                datetime.fromisoformat(item.ended) - datetime.fromisoformat(started)
            ).total_seconds()
        result = item.result or ("running" if item.ended is None else "unknown")
        # SQLite permits duplicate NULL keys: match completion-only rows by their end.
        prior = db.execute(
            "SELECT rowid, exit_code, termination_kind FROM unit_runs WHERE unit=? "
            "AND started IS ? AND (started IS NOT NULL OR ended IS ?)",
            (item.unit, started, item.ended)).fetchone()
        # A bare Succeeded message has a synthetic zero; don't replace the actual termination
        # stored in the preceding hour with that zero.
        exit_code = (prior[1] if prior and prior[1] is not None and
                     item.termination_kind is None else item.exit_code)
        kind = item.termination_kind or (prior[2] if prior else None)
        values = (item.unit, started, item.ended, seconds, exit_code, result, kind)
        if prior:
            db.execute("UPDATE unit_runs SET unit=?, started=?, ended=?, seconds=?, "
                       "exit_code=?, result=?, termination_kind=? WHERE rowid=?",
                       (*values, prior[0]))
        else:
            db.execute("INSERT INTO unit_runs VALUES (?,?,?,?,?,?,?)", values)
        stored.append({"unit": item.unit, "started": started, "ended": item.ended,
                       "seconds": seconds, "exit_code": exit_code, "result": result,
                       "termination_kind": kind})
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


def contract_probe(now: datetime) -> dict:
    """Static and live schedule-contract check; read-only, it never opens a database."""
    try:
        return schedule_contract.check(static=True, live=True, repo_root=REPO_ROOT, now=now)
    except Exception as exc:  # noqa: BLE001 - a probe defect must not stop the digest
        return {"status": "error", "checked_at": _iso(now).replace("Z", "+00:00"),
                "modes": ["static", "live"], "violations": [], "exceptions": [],
                "errors": [f"probe crashed: {type(exc).__name__}"], "counts": {}}


def invariants_probe(ops_dir: Path) -> dict:
    """Shadow invariant check, run only when the published snapshot changed since the last."""
    path = ops_dir / INVARIANTS_RESULT
    current = latest_snapshot(REPO_ROOT / "store" / "market.duckdb")
    if current is None:
        return {"ran": False, "reason": "no published snapshot", "result": None, "error": None}
    try:
        previous = json.loads(path.read_text())
    except (OSError, ValueError):
        previous = None
    if isinstance(previous, dict) and previous.get("status") != "error" and (
            previous.get("snapshot") or {}).get("sha256") == current.sha256:
        return {"ran": False, "reason": "snapshot unchanged", "result": previous, "error": None}
    args = [sys.executable, "-m", "tools.check_invariants", "--snapshot", "latest",
            "--engine-root", str(REPO_ROOT), "--publish", str(path)]
    try:
        done = subprocess.run(args, cwd=REPO_ROOT, capture_output=True, text=True,
                              timeout=INVARIANTS_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return {"ran": True, "reason": None, "result": None,
                "error": f"timed out after {INVARIANTS_TIMEOUT_S}s"}
    except OSError as exc:
        return {"ran": True, "reason": None, "result": None,
                "error": f"could not start: {type(exc).__name__}"}
    try:
        result = json.loads(path.read_text())
    except (OSError, ValueError):
        result = None
    error = None if done.returncode in (0, 3) and result is not None else (
        f"exit {done.returncode}")
    return {"ran": True, "reason": None, "result": result, "error": error}


def gateway(fetch: Fetch, run: Runner) -> dict:
    """The model gateway preflight, read through this digest's own GET and runner."""
    def get(path: str) -> dict:
        status, _ms, body = fetch(GATEWAY_URL + path, agent_model_client.STATUS_TIMEOUT_SECONDS)
        if status != 200:
            raise agent_model_client.ConnectorError(f"Trae proxy returned HTTP {status}")
        try:
            return loads_object(body)
        except (TypeError, ValueError, UnicodeDecodeError) as exc:
            raise agent_model_client.ConnectorError("Trae proxy returned invalid JSON") from exc
    return model_gateway_check.check(fetch=get, run=run)


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


def _flow_value(value: float | int | None, field: str) -> str:
    if value is None:
        return "—"
    value = float(value)
    if field.endswith("_seconds"):
        return "0s" if value == 0 else f"{value:.3f}s"
    if field.endswith("_bytes"):
        for divisor, suffix in ((1_073_741_824, "GiB"), (1_048_576, "MiB"), (1024, "KiB")):
            if value >= divisor:
                return f"{value / divisor:,.1f}{suffix}"
        return f"{value:,.0f}B"
    return f"{value:,.0f}" if value.is_integer() else f"{value:,.3f}"


def _flow_pair(row: Mapping[str, object], first: str, second: str) -> str:
    return f"{_flow_value(row.get(first), first)} → {_flow_value(row.get(second), second)}"


def _receipt_seconds(row: Mapping[str, object]) -> float:
    began = datetime.fromisoformat(str(row["started_at"]).replace("Z", "+00:00"))
    ended = datetime.fromisoformat(str(row["ended_at"]).replace("Z", "+00:00"))
    return max(0.0, (ended - began).total_seconds())


def _markdown_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _clock(stamp: str | None) -> str:
    return stamp[11:19] if stamp else "—"


def _duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    minutes, secs = divmod(int(round(seconds)), 60)
    return f"{minutes}m{secs:02d}s" if minutes else f"{secs}s"


def _contract_detail(detail: dict) -> str:
    keys = ("pid", "database", "mode", "cmdline", "cgroup")
    shown = {key: detail[key] for key in keys if key in detail}
    text = ", ".join(f"{key} {value}" for key, value in shown.items())
    return f" ({text.replace(str(Path.home()), '~')[:400]})".replace("`", "'") if text else ""


def _invariants_lines(probe: dict | None) -> list[str]:
    result = (probe or {}).get("result")
    if not result:
        return []
    snapshot = result.get("snapshot") or {}
    checked = str(result.get("checked_at", ""))[:16].replace("T", " ")
    when = "checked this hour" if probe["ran"] else f"snapshot unchanged since {checked} UTC"
    lines = ["", "## Invariants (shadow)", "",
             f"{result['status']}: {result.get('regression_count', 0)} regression(s) on "
             f"{snapshot.get('name', 'no snapshot')}, {when} "
             f"(`python -m tools.check_invariants --snapshot latest`)."]
    if result.get("error"):
        lines += ["", f"- cannot evaluate: {result['error']}"]
    failing = [(name, item) for name, item in (result.get("invariants") or {}).items()
               if item["status"] != "pass"]
    if failing:
        lines.append("")
    for name, item in failing:
        shown = ", ".join(f"{entry['class']} {entry['subject']}"
                          for entry in item["regressions"][:INVARIANTS_LISTED])
        more = item["regression_count"] - min(len(item["regressions"]), INVARIANTS_LISTED)
        lines.append(f"- {name}: {item['status']}"
                     + (f", {item['regression_count']} regression(s): {shown}" if shown else "")
                     + (f" and {more} more" if more > 0 else "")
                     + (f" ({item['error']})" if item.get("error") else ""))
    return lines


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
            if item.get("termination_kind"):
                result += f" [{item['termination_kind']}]"
            lines.append(
                f"| {item['unit'].removesuffix('.service')} | {_clock(item['started'])} | "
                f"{_clock(item['ended'])} | {_duration(item['seconds'])}{flag} | {typical} | "
                f"{result} |")
    if data["stages"]:
        lines += [
            "", "## Driver stages", "",
            "| driver | stage | end | duration | exit | rows in → out | bytes in → out | "
            "writer hold / lock wait |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for row in data["stages"]:
            lines.append(
                f"| {row['driver']} | {row['stage']} | {_clock(row['ended'])} | "
                f"{_duration(float(row['seconds']))} | {row['exit']} | "
                f"{_flow_pair(row, 'input_rows', 'output_rows')} | "
                f"{_flow_pair(row, 'input_bytes', 'output_bytes')} | "
                f"{_flow_pair(row, 'writer_hold_seconds', 'lock_wait_seconds')} |"
            )
    if data.get("job_receipts"):
        lines += [
            "", "## Registered job receipts", "",
            "| job | scheduled | attempt | duration | work status | process exit | reason |",
            "|---|---|---|---|---|---|---|",
        ]
        for row in data["job_receipts"]:
            lines.append(
                f"| {row['job_id']} | {row['scheduled_for']} | {row['attempt']} | "
                f"{_duration(_receipt_seconds(row))} | {row['work_status']} | "
                f"{row.get('process_exit')} | {_markdown_cell(row['reason'])} |"
            )
    if data.get("work"):
        lines += ["", "## Degraded work receipts", ""]
        for job, receipt in data["work"]:
            lines.append(f"- {job} at {_iso(receipt.start)}: {receipt.label}")
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
    contract = data.get("contract")
    if contract:
        lines += ["", "## Schedule contract", "",
                  f"{contract['status']}: {len(contract['violations'])} violation(s), "
                  f"{len(contract['exceptions'])} excepted, {len(contract['errors'])} probe "
                  f"error(s) (`python -m tools.schedule_contract_check --live`)."]
        if contract["violations"] or contract["errors"]:
            lines.append("")
        lines += [f"- {item['rule']}: {item['subject']}" + _contract_detail(item["detail"])
                  for item in contract["violations"]]
        lines += [f"- probe error: {error}" for error in contract["errors"]]
    lines += _invariants_lines(data.get("invariants"))
    if data.get("gateway"):
        lines += ["", "## Model gateway", "", *model_gateway_check.summary_lines(data["gateway"])]
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
    contract_check: ContractProbe | None = None,
    invariants_check: InvariantsProbe | None = None,
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
    retained = journal_start(run)
    if retained is None:
        gaps.append("journal retention boundary unknown; absence cannot prove a missed run")
    else:
        for unit in units:
            if f"journal unreadable for {unit}" not in gaps and max(hour, retained) < end:
                record_coverage(db, unit, max(hour, retained), end)
    for item in runs:
        if item["started"] and item["seconds"] is not None:
            item["typical"] = typical_seconds(db, item["unit"], item["started"])
            item["slow"] = bool(item["typical"] and item["seconds"] > SLOW_FACTOR * item["typical"])
    stages = collect_stages(db, logs_dir, since) if since is not None else []
    probes, sections, fp, degraded, contract, invariants, gateway_report = (
        [], {}, {}, [], None, None, None)
    job_receipts, config_errors = [], []
    failed_job_receipts: list[dict] = []
    warned_job_receipts: list[dict] = []
    receipt_projection_gaps: list[str] = []
    if last:
        collect_files(db, logs_dir, ops_dir, signals)
        job_receipts, receipt_projection_gaps = collect_job_receipts(db, logs_dir, since)
        gaps.extend(receipt_projection_gaps)
        config_errors = registry_schedule_audit(run, repo_root=REPO_ROOT)
        alert_receipts = pending_job_receipts(db)
        (failed_job_receipts, warned_job_receipts,
         receipt_policy_errors) = registered_receipt_alerts(
            alert_receipts, now, repo_root=REPO_ROOT, db=db
        )
        config_errors.extend(receipt_policy_errors)
        gaps.extend(f"job registry config error: {item}" for item in config_errors)
        first_seen = db.execute("SELECT value FROM meta WHERE key='stages_seen'").fetchone()
        if first_seen and (logs_dir / "stage-timings.jsonl").is_file():
            record_coverage(db, "stages", _utc(first_seen[0]), now)
        db.execute("INSERT OR REPLACE INTO meta VALUES ('stages_seen', ?)", (_iso(now),))
        receipts, receipt_gaps = work_receipts(db_path, since, end, logs_dir)
        gaps.extend(receipt_gaps)
        degraded = [(job, r) for job, rows in receipts.items() for r in rows if r.degraded]
        # Before the /meta probe, so this hour's /meta shows this hour's contract.
        contract = (contract_check or contract_probe)(now)
        write_text_atomic(ops_dir / CONTRACT_RESULT,
                          json.dumps(contract, indent=1, sort_keys=True) + "\n")
        if contract["errors"]:
            gaps.append("schedule contract probe: " + "; ".join(contract["errors"]))
        invariants = (invariants_check or invariants_probe)(ops_dir)
        if invariants["error"]:
            gaps.append("invariants probe: " + invariants["error"])
        probes, sections = probe(fetch)
        gateway_report = gateway(fetch, run)
        fp = footprint(run, logs_dir, db_path)
    previous = dict(db.execute(
        "SELECT section, status FROM meta_status WHERE hour=("
        "SELECT MAX(hour) FROM meta_status WHERE hour<?)", (key,)).fetchall())
    changes = {k for k, v in sections.items() if previous and previous.get(k) != v}
    # systemd's result decides, not the exit status: a SIGTERM stop logs status=15, then
    # "Succeeded.", and a failure's result follows its exit line even across an hour.
    failed = [r for r in runs if r["result"] not in ("success", "running", SKIPPED_RESULT)]
    failed_stages = [row for row in stages if row["exit"] != 0]
    errors = sum(sig.counts["error"] for sig in signals.values())
    warns = sum(sig.counts["warn"] for sig in signals.values())
    health = next((p for p in probes if p["target"] == "/health"), None)
    gateway_status = gateway_report["status"] if gateway_report else "ok"
    if (failed or failed_stages or failed_job_receipts or config_errors
            or (health and health["http_status"] != 200) or gateway_status == "fail"):
        status = "FAIL"
    elif errors or warns or degraded or warned_job_receipts or receipt_projection_gaps or (
            gateway_status == "warn") or any(
            r.get("slow") or r["result"] == SKIPPED_RESULT for r in runs) or any(
            p["ms"] > SLOW_PROBE_MS for p in probes) or (
            contract is not None and contract["status"] != "ok"):
        status = "WARN"
    else:
        status = "OK"
    data = {
        "status": status, "collected_at": _iso(now), "failed_runs": len(failed) + len(
            failed_stages) + len(failed_job_receipts) + len(config_errors),
        "error_lines": errors, "warn_lines": warns, "gaps": gaps,
        "runs": runs, "stages": stages, "probes": probes, "sections": sections,
        "section_changes": changes, "signals": signals, "footprint": fp, "work": degraded,
        "contract": contract, "invariants": invariants, "gateway": gateway_report,
        "job_receipts": job_receipts,
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
    if "termination_kind" not in {row[1] for row in db.execute("PRAGMA table_info(unit_runs)")}:
        db.execute("ALTER TABLE unit_runs ADD COLUMN termination_kind TEXT")
    stage_columns = {row[1] for row in db.execute("PRAGMA table_info(stage_runs)")}
    for column in FLOW_FIELDS:
        if column not in stage_columns:
            db.execute(f"ALTER TABLE stage_runs ADD COLUMN {column} REAL")  # noqa: S608
    job_columns = {row[1] for row in db.execute("PRAGMA table_info(job_runs)")}
    for column in ("alert_state", "alert_after"):
        if column not in job_columns:
            db.execute(f"ALTER TABLE job_runs ADD COLUMN {column} TEXT")  # noqa: S608
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
    db.execute("DELETE FROM unit_runs WHERE COALESCE(started, ended) < ?", (started_cutoff,))
    db.execute("DELETE FROM stage_runs WHERE ended < ?", (started_cutoff,))
    db.execute("DELETE FROM job_runs WHERE ended < ?", (started_cutoff,))


def daily_log_retention(
    db: sqlite3.Connection, logs_dir: Path, ops_dir: Path, now: datetime,
) -> log_retention.Result | None:
    """Run log retention once a UTC day; a rotated log's read offset moves to its new end."""
    moment = now.astimezone(UTC)
    day = f"{moment:%Y-%m-%d}"
    row = db.execute("SELECT value FROM meta WHERE key='log_retention_day'").fetchone()
    if moment.hour < LOG_RETENTION_HOUR or (row is not None and row[0] == day):
        return None
    config = log_retention.load_config(ops_dir)
    result = log_retention.run_retention(logs_dir, repo_root=logs_dir.parent, now=now,
                                         config=config)
    for item in result.rotate if result.applied else ():
        db.execute("UPDATE file_offsets SET inode=?, offset=? WHERE path=?",
                   (item["inode"], item["kept_bytes"], str(item["path"])))
    write_text_atomic(ops_dir / "retention.md",
                      log_retention.render(result, now=now, config=config))
    db.execute("INSERT OR REPLACE INTO meta VALUES ('log_retention_day', ?)", (day,))
    return result


def collect(
    *, now: datetime | None = None, run: Runner = _run, fetch: Fetch = _fetch,
    logs_dir: Path = LOGS_DIR, ops_dir: Path = OPS_DIR, db_path: Path = DEFAULT_DB,
    contract_check: ContractProbe | None = None,
    invariants_check: InvariantsProbe | None = None,
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
            sample_schedules(db, run, now)
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
                    run=run, fetch=fetch, logs_dir=logs_dir, ops_dir=ops_dir,
                    db_path=db_path, now=now, contract_check=contract_check,
                    invariants_check=invariants_check))
                db.execute("INSERT OR REPLACE INTO meta VALUES ('next_hour', ?)",
                           ((hour + timedelta(hours=1)).isoformat(),))
                db.commit()
            if results:
                write_text_atomic(ops_dir / "latest.md", results[-1]["text"])
            prune(db, ops_dir, now)
            db.commit()
            try:
                daily_log_retention(db, logs_dir, ops_dir, now)
            except OSError as exc:  # best effort, like every other source
                print(f"[ops-digest] log retention failed: {exc}")
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
    start: datetime | None
    seconds: float | None
    ok: bool | None
    label: str
    degraded: bool = False


def journal_start(run: Runner) -> datetime | None:
    """Retained coverage starts at the latest boot; earlier reboot gaps stay unknown."""
    raw = run(["journalctl", "--user", "--list-boots", "--utc", "--no-pager"], 30) or ""
    stamps = re.findall(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC", raw)
    return max(_utc(s) for s in stamps[::2]) if stamps else None


def _meta_json(db: sqlite3.Connection, key: str, default):
    row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def record_coverage(db: sqlite3.Connection, source: str, start: datetime, end: datetime) -> None:
    key = "coverage:" + source
    ranges = sorted([*_meta_json(db, key, []), [_iso(start), _iso(end)]])
    merged: list[list[str]] = []
    for begin, finish in ranges:
        if merged and begin <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], finish)
        else:
            merged.append([begin, finish])
    db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, json.dumps(merged)))


def _schedule_data(item: Schedule) -> dict:
    return {"job": item.job, "spec": item.spec, "slack_s": item.slack_s,
            "unit": item.unit, "driver": item.driver,
            "output": str(item.output) if item.output else None, "appends": item.appends}


def _saved_schedule(item: dict) -> Schedule:
    matcher = None
    try:
        if item["spec"].startswith("timer "):
            matcher = _any_of([calendar_matcher(s) for s in item["spec"][6:].split("; ")])
        elif item["spec"].startswith("cron "):
            matcher = cron_matcher(item["spec"][5:].split())
    except (StopIteration, ValueError, ZoneInfoNotFoundError):
        pass
    return Schedule(**{**item, "output": Path(item["output"]) if item["output"] else None},
                    matcher=matcher)


def sample_schedules(db: sqlite3.Connection, run: Runner, now: datetime) -> None:
    samples = _meta_json(db, "schedule_samples", [])
    items = [_schedule_data(s) for s in timer_schedules(run) + cron_schedules(run)]
    samples.append({"at": _iso(now), "items": items})
    cutoff = _iso(now - timedelta(days=METRIC_RETENTION_DAYS))
    db.execute("INSERT OR REPLACE INTO meta VALUES ('schedule_samples', ?)",
               (json.dumps([s for s in samples if s["at"] >= cutoff]),))


def _schedule_intervals(db: sqlite3.Connection, schedule: Schedule,
                        start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """Only intervals bracketed by matching installed observations are known.

    A changed schedule has an unknown transition interval. The current schedule is never
    backdated into history before collection began.
    """
    samples = _meta_json(db, "schedule_samples", [])
    expected = _schedule_data(schedule)
    intervals = []
    for first, second in zip(samples, samples[1:], strict=False):
        if expected in first["items"] and expected in second["items"]:
            begin, finish = max(start, _utc(first["at"])), min(end, _utc(second["at"]))
            if begin < finish:
                if intervals and begin <= intervals[-1][1]:
                    intervals[-1] = (intervals[-1][0], max(finish, intervals[-1][1]))
                else:
                    intervals.append((begin, finish))
    return intervals


def work_receipts(database: Path, start: datetime, end: datetime, logs_dir: Path = LOGS_DIR
                  ) -> tuple[dict[str, list[JobRun]], list[str]]:
    """Read dated work from one resolved immutable snapshot; never infer a process exit."""
    snapshot = latest_snapshot(database)
    receipts: dict[str, list[JobRun]] = defaultdict(list)
    gaps = []
    # These are dated producer receipts, read independently of text-log tail offsets.
    for job, name in (("trading-engine-hourly-opportunity", "hourly_market_watch_v5.jsonl"),
                      ("trading-engine-four-hour-opportunity", "four_hour_opportunity_review_v5.jsonl")):
        path = logs_dir / name
        try:
            with path.open("rb") as handle:
                size = path.stat().st_size
                if size > MAX_READ_BYTES:
                    handle.seek(size - MAX_READ_BYTES)
                    handle.readline()  # discard a partial first row
                    gaps.append(f"older work receipts outside read limit for {job}")
                lines = handle.read().decode("utf-8", "replace").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                row = json.loads(line)
                began = datetime.fromisoformat(row["observed_at"]).astimezone(UTC)
                count = int(row.get("unavailable_count", 0))
            except (ValueError, TypeError, KeyError):
                gaps.append(f"malformed work receipt for {job}")
                continue
            if start <= began < end:
                receipts[job].append(JobRun(began, None, None,
                    f"receipt observation; unavailable={count}; exit unknown", count > 0))
    if snapshot is None:
        return receipts, [*gaps, "work receipts unavailable: no published snapshot"]
    sources = {
        "trading-engine-p15-events": ("p15_event_windows", "observed_at"),
        "trading-engine-p15-preopen": ("p15_preopen_runs", "started_at"),
        "trading-engine-p15-scoring": ("p15_scoring_runs", "started_at"),
        "trading-engine-daily-opportunity": ("daily_opportunity_runs", "started_at"),
    }
    try:
        with db.connect(snapshot.path, read_only=True, wait_s=0) as con:
            for job, (table, stamp) in sources.items():
                try:
                    rows = con.execute(
                        f"SELECT {stamp}, completed_at, status, reason FROM {table} "
                        f"WHERE {stamp}>=? AND {stamp}<? ORDER BY {stamp}",  # noqa: S608
                        [start.replace(tzinfo=None), end.replace(tzinfo=None)]).fetchall()
                except duckdb.Error:
                    gaps.append(f"work receipts unavailable for {job}")
                    continue
                for began, _finished, status, reason in rows:
                    label = f"receipt {status}; exit unknown"
                    if reason:
                        label += f" ({reason})"
                    degraded = status in {"unavailable", "late", "partial", "degraded",
                                          "failed", "error", "invalid"}
                    receipts[job].append(JobRun(began.replace(tzinfo=UTC), None, None, label,
                                               degraded))
    except duckdb.Error:
        gaps.append("work receipts unreadable: published snapshot could not be opened")
    return receipts, gaps


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


def _timer_spec_key(spec: str) -> frozenset[str]:
    """One timer's calendars as systemd reports them: any order, seconds ``:00`` explicit.

    systemd 241 lists several ``OnCalendar`` values newest-first and adds the seconds field,
    so ``10..15:05,20 X`` in a unit file reads back as ``10..15:05,20:00 X``.
    """
    calendars = spec.removeprefix("timer ").split("; ")
    normalized = set()
    for calendar in calendars:
        tokens = calendar.split()
        tokens = [token + ":00" if ":" in token and token.count(":") == 1 else token
                  for token in tokens]
        normalized.add(" ".join(tokens))
    return frozenset(normalized)


def registry_schedule_audit(run: Runner, repo_root: Path = REPO_ROOT) -> list[str]:
    """Report installed public-engine schedules absent from the audit-only registry."""
    try:
        registry = job_contract.load_registry(repo_root)
    except job_contract.JobContractError as exc:
        return [f"invalid-registry:{exc}"]
    registered_units = {
        job.service_unit for job in registry.jobs if job.timer_unit and job.service_unit
    }
    registered_timer_specs = {
        job.service_unit: "timer " + "; ".join(job.schedules)
        for job in registry.jobs if job.timer_unit and job.service_unit
    }
    cron_entries = job_contract.render_cron_entries(registry, repo_root)
    registered_cron = {
        name.replace("_", "-")
        for name in cron_entries
    }
    registered_cron_specs = {
        str(job.legacy["cron"].get("name", job.job_id)).replace("_", "-"):
        "cron " + str(job.legacy["cron"]["fields"])
        for job in registry.jobs if isinstance(job.legacy.get("cron"), Mapping)
    }
    errors = []
    for schedule in timer_schedules(run):
        unit = schedule.unit
        public = bool(
            unit
            and (unit.startswith("trading-engine-") or unit == "massive-options-daily.service")
        )
        if public and unit not in registered_units:
            errors.append(f"undocumented-installed-timer:{unit}")
        elif public and _timer_spec_key(schedule.spec) != _timer_spec_key(
                registered_timer_specs[unit]):
            errors.append(f"installed-timer-schedule-mismatch:{unit}")
    for schedule in cron_schedules(run):
        name = (schedule.driver or schedule.job).replace("_", "-")
        if (schedule.driver or name == "friday-postflight") and name not in registered_cron:
            errors.append(f"undocumented-installed-cron:{name}")
        elif (schedule.driver or name == "friday-postflight") and (
            schedule.spec != registered_cron_specs[name]
        ):
            errors.append(f"installed-cron-schedule-mismatch:{name}")
    return sorted(set(errors))


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
    rows = db.execute("SELECT started, seconds, result FROM unit_runs WHERE unit=? "
                      "AND COALESCE(started, ended)>=? AND COALESCE(started, ended)<? "
                      "ORDER BY COALESCE(started, ended)",
                      (schedule.unit, since, until)).fetchall()
    return [JobRun(_utc(started) if started else None, seconds,
                   None if result in {"running", "unknown"} else result == "success",
                   result)
            for started, seconds, result in rows]


def _due(schedule: Schedule, start: datetime, end: datetime) -> list[datetime] | None:
    """Scheduled starts whose latest allowed start is before ``end``; None if unknown."""
    if schedule.matcher is None:
        return None
    due = expected_times(schedule.matcher, start,
                         end - timedelta(seconds=schedule.slack_s + RUN_GRACE_S))
    return due[-1:] if schedule.output else due  # one output file proves only the latest run


def _occupied(schedule: Schedule, moment: datetime, item: JobRun) -> bool:
    """A timer that fires while its service is still active starts nothing: the slot is
    taken by the run in progress, not missed."""
    if schedule.unit is None or item.start is None or item.start > moment:
        return False
    if item.seconds is not None:
        return item.start + timedelta(seconds=item.seconds) >= moment
    return item.label == "running"


def _unmatched(schedule: Schedule, due: list[datetime], runs: list[JobRun]) -> list[datetime]:
    late = timedelta(seconds=schedule.slack_s + RUN_GRACE_S)
    return [moment for moment in due if not any(
        item.start is not None and moment - timedelta(minutes=1) <= item.start <= moment + late
        or _occupied(schedule, moment, item)
        for item in runs)]


def _stamp(moment: datetime) -> str:
    return f"{moment:%m-%d %H:%M}Z"


def _runs_cell(runs: list[JobRun]) -> str:
    def one(item: JobRun) -> str:
        stamp = _stamp(item.start) if item.start else "unknown start"
        return f"{stamp} {item.label} {_duration(item.seconds)}".rstrip(" —")
    if len(runs) <= LISTED_RUNS:
        return "; ".join(map(one, runs)) or "—"
    timed = [item.seconds for item in runs if item.seconds is not None]
    spread = f"; median {_duration(median(timed))}, max {_duration(max(timed))}" if timed else ""
    return f"last {one(runs[-1])}{spread}"


def runs_lines(db: sqlite3.Connection, run: Runner, start: datetime,
               end: datetime, receipts: dict[str, list[JobRun]] | None = None
               ) -> tuple[list[str], list[str]]:
    """Missing-run bullets, then the per-job run table and every driver's stages."""
    since, until = _iso(start), _iso(end)
    schedules = timer_schedules(run) + cron_schedules(run)
    for sample in _meta_json(db, "schedule_samples", []):
        for item in sample["items"]:
            if item not in [_schedule_data(s) for s in schedules]:
                schedules.append(_saved_schedule(item))
    known = {item.unit for item in schedules if item.unit}
    schedules += [Schedule(unit.removesuffix(".service"), "—", None, unit=unit) for (unit,) in
                  db.execute("SELECT DISTINCT unit FROM unit_runs WHERE COALESCE(started, ended)>=? "
                             "AND COALESCE(started, ended)<?", (since, until)) if unit not in known]
    drivers = _driver_runs(db, since, until)
    grouped: dict[str, list[Schedule]] = defaultdict(list)
    for schedule in schedules:
        grouped[schedule.job].append(schedule)
    missing, table = [], []
    for job, versions in sorted(grouped.items()):
        schedule = versions[0]
        runs = _job_runs(db, schedule, drivers, since, until)
        # A receipt proves work, not lifecycle. Merge the same invocation's evidence.
        for receipt in (receipts or {}).get(job, []):
            peer = next((r for r in runs if r.start is not None and receipt.start is not None
                         and abs((r.start - receipt.start).total_seconds()) <= 60), None)
            if peer:
                peer.label += "; " + receipt.label
                peer.degraded |= receipt.degraded
            else:
                runs.append(receipt)
        runs.sort(key=lambda r: r.start or end)
        due, observable, unknown = [], [], 0
        intervals = []
        for version in versions:
            observed = _schedule_intervals(db, version, start, end)
            intervals.extend(observed)
            for begin, finish in observed:
                slots = _due(version, begin, finish) or []
                due.extend(slots)
                coverage = _meta_json(db, "coverage:" + (version.unit or "stages"), [])
                for moment in _unmatched(version, slots, runs):
                    covered = any(low <= _iso(moment) and high >= _iso(moment + timedelta(
                        seconds=version.slack_s + RUN_GRACE_S)) for low, high in coverage)
                    if covered and not (version.output and version.appends):
                        observable.append(moment)
                        missing.append(f"- {job}: due {_stamp(moment)} (`{version.spec}`), no run")
                    else:
                        unknown += 1
        known_seconds = sum((finish - begin).total_seconds() for begin, finish in intervals)
        unknown_history = known_seconds < max(0, (end - start).total_seconds())
        known_calendar = any(v.matcher is not None for v in versions)
        unknown_cell = f"{unknown} slots; schedule unknown" if unknown_history else str(unknown)
        if not known_calendar:
            unknown_cell = "schedule unknown"
        spec = "; ".join(dict.fromkeys(v.spec for v in versions))
        due_cell = len(due) if known_calendar else "?"
        absent_cell = len(observable) if known_calendar else "?"
        table.append(f"| {job} | `{spec}` | {due_cell} | {len(runs)} | "
                     f"{sum(r.ok is False for r in runs)} | {sum(r.degraded for r in runs)} | "
                     f"{absent_cell} | {unknown_cell} | "
                     f"{_runs_cell(runs)} |")
    lines = ["", "## Runs", "", f"Requested interval {since} through {until}. Due counts cover "
             "only intervals bracketed by identical installed schedule observations; transitions "
             "and earlier history are unknown. Missing requires readable coverage across the "
             f"allowed start window (timer delay plus {RUN_GRACE_S // 60} minutes). "
             "Receipts prove work; they do not prove process exit. Unknown is never missing.", "",
             "| job | schedule | known due | ran | failed | degraded | missing | unknown | runs |",
             "|---|---|---|---|---|---|---|---|---|", *table]
    stage_lines = [
        f"- {driver} {_stamp(begin)}, {_duration((finish - begin).total_seconds())}: " + " · ".join(
            f"{stage} {_duration(seconds)}" + (f" exit {code}" if code else "")
            for stage, _s, _e, seconds, code in stages)
        for driver, items in sorted(drivers.items()) for begin, finish, stages in items]
    if stage_lines:
        lines += ["", "## Driver stages", "", *stage_lines]
    return missing, lines


def stage_flow_statistics(db: sqlite3.Connection, since: str) -> list[dict]:
    """Return per-driver flow medians/p90s, omitting counters that were never measured."""
    columns = ", ".join(FLOW_FIELDS)
    grouped: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: {field: [] for field in FLOW_FIELDS}
    )
    for row in db.execute(
        f"SELECT driver, {columns} FROM stage_runs WHERE ended>=?", (since,)  # noqa: S608
    ):
        driver, *values = row
        for metric, value in zip(FLOW_FIELDS, values, strict=True):
            if value is not None:
                grouped[driver][metric].append(float(value))
    result = []
    for driver, metrics in sorted(grouped.items()):
        for metric, values in metrics.items():
            if not values:
                continue
            ordered = sorted(values)
            p90 = ordered[max(0, math.ceil(len(ordered) * 0.9) - 1)]
            result.append(
                {
                    "driver": driver,
                    "field": metric,
                    "samples": len(values),
                    "median": median(values),
                    "p90": p90,
                }
            )
    return result


def report(hours: int, ops_dir: Path = OPS_DIR, now: datetime | None = None,
           run: Runner = _run, db_path: Path = DEFAULT_DB) -> str:
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
        missing_hours = max(0, hours - len(rows))
        out.append(f"{missing_hours} requested hour(s) have no digest coverage; their outcomes "
                   "are unknown. Log history before each file's first offset is unknown.")
        bad = [row for row in rows if row[1] != "OK"]
        if bad:
            out += ["", "| hour | status | failed | errors | warns | digest |",
                    "|---|---|---|---|---|---|"]
            out += [f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} | {r[5]} |" for r in bad]
        failed = db.execute(
            "SELECT unit, started, seconds, exit_code, result FROM unit_runs "
            "WHERE COALESCE(started, ended)>=? "
            "AND result NOT IN ('success','running','unknown') ORDER BY started",
            (since_iso,)).fetchall()
        failed += db.execute(
            "SELECT driver || ':' || stage, started, seconds, exit_code, 'failed' FROM stage_runs "
            "WHERE ended>=? AND exit_code<>0", (since_iso,)).fetchall()
        if failed:
            out += ["", "## Failed runs", ""]
            out += [f"- {u} at {s or 'unknown start'} ({_duration(sec)}): {res}, exit {code}"
                    for u, s, sec, code, res in failed]
        registered = db.execute(
            "SELECT job_id, scheduled_for, attempt, seconds, work_status, process_exit, reason, "
            "retry_disposition FROM job_runs WHERE ended>=? ORDER BY ended, attempt",
            (since_iso,),
        ).fetchall()
        if registered:
            out += [
                "", "## Registered job receipts", "",
                "| job | scheduled | attempt | duration | status | exit | retry | reason |",
                "|---|---|---|---|---|---|---|---|",
            ]
            out += [
                f"| {job} | {scheduled} | {attempt} | {_duration(seconds)} | {status} | "
                f"{code} | {retry} | {_markdown_cell(reason)} |"
                for job, scheduled, attempt, seconds, status, code, reason, retry in registered
            ]
        start = floor_hour(now) - timedelta(hours=hours)
        receipts, receipt_gaps = work_receipts(db_path, start, now, ops_dir.parent)
        if receipt_gaps:
            out += ["", "Work coverage: " + "; ".join(receipt_gaps)]
        degraded = [f"- [WARN] {job} at {_iso(r.start)}: {r.label}" for job, items in
                    receipts.items() for r in items if r.degraded]
        if degraded:
            out += ["", "## Degraded work", "", *degraded]
        missing, run_lines = runs_lines(db, run, start, now, receipts)
        if missing:
            out += ["", "## Missing runs", "", *missing]
        out += run_lines
        flow = stage_flow_statistics(db, since_iso)
        if flow:
            out += [
                "", "## Stage flow", "",
                "| driver | metric | samples | median | p90 |",
                "|---|---|---:|---:|---:|",
            ]
            out += [
                f"| {row['driver']} | {row['field']} | {row['samples']} | "
                f"{_flow_value(row['median'], row['field'])} | "
                f"{_flow_value(row['p90'], row['field'])} |"
                for row in flow
            ]
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
