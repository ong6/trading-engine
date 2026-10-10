from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime

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
