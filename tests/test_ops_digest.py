from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest

from engine.lib import db as engine_db
from tools import ops_digest

NOW = datetime(2026, 10, 10, 3, 5, tzinfo=UTC)


def _entry(stamp: str, message: str, ident: str = "python") -> str:
    micros = int(datetime.fromisoformat(stamp).timestamp() * 1e6)
    return json.dumps({"__REALTIME_TIMESTAMP": str(micros), "MESSAGE": message,
                       "SYSLOG_IDENTIFIER": ident})


def _journal(unit: str, *, exit_code: int = 0) -> str:
    lines = [
        _entry("2026-10-10T02:30:00+00:00", "Starting Nightly scoring...", "systemd"),
        _entry("2026-10-10T02:31:00+00:00", "WARN: 3 names withheld"),
        _entry("2026-10-10T02:32:00+00:00", "scored 40 names"),
    ]
    if exit_code:
        lines += [
            _entry("2026-10-10T02:40:00+00:00",
                   f"{unit}: Main process exited, code=exited, status={exit_code}/n/a",
                   "systemd"),
            _entry("2026-10-10T02:40:00+00:00",
                   f"{unit}: Failed with result 'exit-code'.", "systemd"),
        ]
    else:
        lines.append(_entry("2026-10-10T02:48:20+00:00", f"{unit}: Succeeded.", "systemd"))
    return "\n".join(lines)


def _fake_run(journal: dict[str, str]):
    def run(args, _timeout):
        if args[:3] == ["systemctl", "--user", "list-timers"]:
            return "".join(f"x x x x x x x {u[:-8]}.timer {u}\n" for u in journal)
        if args[:3] == ["systemctl", "--user", "list-units"]:
            return "dbus.service loaded active running D-Bus\n"
        if args[0] == "journalctl":
            return journal.get(args[args.index("-u") + 1], "")
        if args[0] == "git":
            return "0\n" if "rev-list" in args else " M data/reports/league.md\n"
        return None
    return run


def _fetch(url, _timeout):
    if url.endswith("/meta"):
        return 200, 40, json.dumps({"nightly": {"status": "ok"},
                                    "price_verification": {"status": "issues"}}).encode()
    return 200, 3, b"{}"


def _collect(tmp_path, journal, now=NOW):
    logs = tmp_path / "logs"
    logs.mkdir(exist_ok=True)
    return ops_digest.collect(now=now, run=_fake_run(journal), fetch=_fetch, logs_dir=logs,
                              ops_dir=logs / "ops", db_path=tmp_path / "store.duckdb")


def test_classify_and_signature():
    assert ops_digest.classify("Traceback (most recent call last):") == "error"
    assert ops_digest.classify("TODO: run_daily failed (stage=collect exit 1)") == "error"
    assert ops_digest.classify('{"status": "failed", "job": 726}') == "error"
    assert ops_digest.classify("[collect] 26 names failed to download, record withheld") == (
        "warn")
    assert ops_digest.classify("scored 40 names") is None
    assert ops_digest.signature("job 726 took 12.5s at deadbeef12") == (
        "job # took #.#s at <hex>")


def test_parse_journal_pairs_runs_and_classifies_output():
    unit = "trading-engine-p15-scoring.service"
    signals = ops_digest.SourceSignals()
    runs = ops_digest.parse_journal(unit, _journal(unit), signals)
    assert [(r.started, r.ended, r.exit_code, r.result) for r in runs] == [
        ("2026-10-10T02:30:00Z", "2026-10-10T02:48:20Z", 0, "success")]
    assert signals.lines == 2 and signals.counts == {"error": 0, "warn": 1}

    failed = ops_digest.parse_journal(unit, _journal(unit, exit_code=75),
                                      ops_digest.SourceSignals())
    assert (failed[0].exit_code, failed[0].result) == (75, "exit-code")


def test_parse_journal_closes_run_started_in_earlier_hour():
    unit = "long.service"
    raw = _entry("2026-10-10T03:10:00+00:00", f"{unit}: Succeeded.", "systemd")
    runs = ops_digest.parse_journal(unit, raw, ops_digest.SourceSignals())
    assert (runs[0].started, runs[0].ended, runs[0].result) == (
        None, "2026-10-10T03:10:00Z", "success")


def test_read_new_lines_starts_at_end_then_follows_and_resets(tmp_path):
    with closing(sqlite3.connect(":memory:")) as db:
        _follow_log(db, tmp_path / "x.log")


def _follow_log(db, log):
    db.executescript(ops_digest.SCHEMA)
    log.write_text("old history\n")
    assert ops_digest.read_new_lines(db, log) == ([], 0)
    with log.open("a") as handle:
        handle.write("first\nsecond\npartial")
    assert ops_digest.read_new_lines(db, log) == (["first", "second"], 13)
    with log.open("a") as handle:
        handle.write(" line\n")
    assert ops_digest.read_new_lines(db, log) == (["partial line"], 13)
    log.write_text("rotated\n")
    assert ops_digest.read_new_lines(db, log) == (["rotated"], 8)


def test_collect_writes_digest_and_metrics(tmp_path):
    unit = "trading-engine-p15-scoring"
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "run-2026-10-10.log").write_text("")
    (logs / "cron.log").write_text("")
    _collect(tmp_path, {f"{unit}.service": _journal(f"{unit}.service")},
             now=datetime(2026, 10, 10, 2, 5, tzinfo=UTC))
    (logs / "run-2026-10-10.log").write_text("TODO: run_daily failed (stage=x exit 1)\nok\n")
    (logs / "cron.log").write_text("TODO: run_daily failed (stage=x exit 1)\nlock busy ERROR\n")
    (logs / "stage-timings.jsonl").write_text(json.dumps({
        "driver": "run_daily", "run_id": "r1", "stage": "collect",
        "started": "2026-10-10T02:00:00Z", "ended": "2026-10-10T02:02:30Z",
        "seconds": 150.0, "exit": 0}) + "\n")

    results = _collect(tmp_path, {f"{unit}.service": _journal(f"{unit}.service")})

    assert [(r["hour"], r["status"]) for r in results] == [("2026-10-10T02", "WARN")]
    text = (logs / "ops" / "latest.md").read_text()
    assert "Ops digest 2026-10-10 02:00–03:00 UTC — WARN" in text
    assert f"| {unit} | 02:30:00 | 02:48:20 | 18m20s |" in text
    assert "| run_daily | collect | 02:02:30 | 2m30s | 0 |" in text
    assert "price_verification=issues" in text
    assert "dbus" not in text
    with closing(sqlite3.connect(logs / "ops" / "ops.sqlite")) as db:
        _check_metrics(db)


def _check_metrics(db):
    counts = dict(db.execute(
        "SELECT source, errors FROM log_counts WHERE hour='2026-10-10T02'").fetchall())
    # the cron.log copy of a line already in the dated log is not counted twice
    assert counts["file:run-2026-10-10.log"] == 1
    assert counts["file:cron.log"] == 1
    assert db.execute("SELECT result, seconds FROM unit_runs").fetchall() == [
        ("success", 1100.0)]
    assert "ERROR" not in json.dumps(db.execute("SELECT * FROM log_counts").fetchall())


def test_failed_run_marks_hour_and_report_lists_it(tmp_path):
    unit = "trading-engine-p15-scoring"
    _collect(tmp_path, {f"{unit}.service": _journal(f"{unit}.service", exit_code=75)})

    report = ops_digest.report(24, tmp_path / "logs" / "ops", now=NOW)

    assert "1 FAIL" in report
    assert f"{unit}.service at 2026-10-10T02:30:00Z (10m00s): exit-code, exit 75" in report
    assert "price_verification=issues" in report


def test_backfill_is_bounded_and_lock_skips_concurrent_run(tmp_path):
    first = _collect(tmp_path, {}, now=datetime(2026, 10, 1, 0, 5, tzinfo=UTC))
    assert len(first) == 1
    later = _collect(tmp_path, {}, now=NOW)
    assert len(later) == ops_digest.MAX_BACKFILL_HOURS
    ops = tmp_path / "logs" / "ops"
    import fcntl
    with (ops / ".lock").open("w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        assert _collect(tmp_path, {}, now=datetime(2026, 10, 10, 9, 5, tzinfo=UTC)) == []


def test_footprint_counts_the_whole_store_directory(tmp_path):
    # The digest reported "store 9,983.6 MB" (market.duckdb alone) while store/ held 63 GB.
    store = tmp_path / "store"
    (store / "snapshots").mkdir(parents=True)
    with (store / "market.duckdb").open("wb") as handle:
        handle.truncate(1_048_576)
    with (store / "snapshots" / "market-1.duckdb").open("wb") as handle:
        handle.truncate(3 * 1_048_576)
    (store / "snapshots" / "market-latest.duckdb").symlink_to("market-1.duckdb")
    logs = tmp_path / "logs"
    logs.mkdir()

    fp = ops_digest.footprint(_fake_run({}), logs, store / "market.duckdb")
    ops_digest.collect(now=NOW, run=_fake_run({}), fetch=_fetch, logs_dir=logs,
                       ops_dir=logs / "ops", db_path=store / "market.duckdb")

    assert (fp["db_bytes"], fp["store_bytes"]) == (1_048_576, 4 * 1_048_576)
    assert "store 4.0 MB (market.duckdb 1.0 MB)" in (logs / "ops" / "latest.md").read_text()


ROOT = Path(__file__).resolve().parents[1]
DIGEST_TIMER = "trading-engine-ops-digest.timer"
_SPAN_UNITS = {"s": 1, "sec": 1, "m": 60, "min": 60, "h": 3600}


def _span(value: str) -> int:
    match = re.fullmatch(r"(\d+)\s*(s|sec|m|min|h)?", value.strip())
    assert match, value
    return int(match[1]) * _SPAN_UNITS[match[2] or "s"]


def _start_windows(timer: Path, *, runtime_s: int = 0) -> list[tuple[int, int]]:
    """Seconds-of-the-hour windows in which a timer can fire (whole-hour time zones only)."""
    settings: dict[str, list[str]] = {}
    for line in timer.read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep:
            settings.setdefault(key.strip(), []).append(value.strip())
    slack = (_span(settings.get("AccuracySec", ["1min"])[-1])
             + _span(settings.get("RandomizedDelaySec", ["0"])[-1]) + runtime_s)
    windows = []
    for spec in settings.get("OnCalendar", []):
        field = next(token for token in spec.split() if ":" in token).split(":")[1]
        minutes = range(60) if field == "*" else [
            minute for part in field.split(",")
            for minute in range(int(part.split("..")[0]), int(part.split("..")[-1]) + 1)
        ]
        windows += [(minute * 60, minute * 60 + slack) for minute in minutes]
    return windows


def _overlaps(first: tuple[int, int], second: tuple[int, int]) -> bool:
    return any(first[0] < second[1] + shift and second[0] + shift < first[1]
               for shift in (-3600, 0, 3600))


def test_a_held_reader_refuses_a_fail_fast_writer(tmp_path):
    # The digest's /meta probe makes the API hold a read-only store connection; the P15
    # pre-open then opened the writer once (wait_s=0) and failed on 2026-10-13 and 10-14.
    store = tmp_path / "market.duckdb"
    duckdb.connect(str(store)).close()
    hold = ("import sys, duckdb; con = duckdb.connect(sys.argv[1], read_only=True); "
            "print('open', flush=True); sys.stdin.read()")
    with subprocess.Popen([sys.executable, "-c", hold, str(store)], stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, text=True) as reader:
        try:
            assert reader.stdout.readline().strip() == "open"
            with pytest.raises(duckdb.IOException) as refused:
                engine_db.connect(store, wait_s=0)
        finally:
            reader.communicate("")
    assert engine_db.is_lock_error(refused.value)
    assert "read-only mode" in str(refused.value)  # the holder is a reader, not a writer
    engine_db.connect(store, wait_s=0).close()


def test_digest_timer_never_fires_with_another_timer():
    digest = _start_windows(ROOT / "server" / DIGEST_TIMER, runtime_s=60)
    assert digest
    for timer in sorted((ROOT / "server").glob("*.timer")):
        if timer.name == DIGEST_TIMER:
            continue
        clashes = [(ours, theirs) for ours in digest for theirs in _start_windows(timer)
                   if _overlaps(ours, theirs)]
        assert not clashes, f"{DIGEST_TIMER} can fire with {timer.name}: {clashes[:3]}"
