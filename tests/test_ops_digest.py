from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest

from engine.lib import db as engine_db
from tools import ops_digest

NOW = datetime(2026, 10, 10, 3, 5, tzinfo=UTC)
REAL_CONTRACT_PROBE = ops_digest.contract_probe


CONTRACT_OK = {"status": "ok", "checked_at": "2026-10-10T03:05:00+00:00",
               "modes": ["static", "live"], "violations": [], "exceptions": [], "errors": [],
               "counts": {}}


INVARIANTS_IDLE = {"ran": False, "reason": "no published snapshot", "result": None,
                   "error": None}
REAL_INVARIANTS_PROBE = ops_digest.invariants_probe


@pytest.fixture(autouse=True)
def _no_host_units(tmp_path, monkeypatch):
    monkeypatch.setattr(ops_digest, "USER_UNIT_DIR", tmp_path / "no-units")
    monkeypatch.setattr(ops_digest, "HOST_LOG_GLOBS", ())
    monkeypatch.setattr(ops_digest, "contract_probe", lambda _now: CONTRACT_OK)
    monkeypatch.setattr(ops_digest, "invariants_probe", lambda _ops_dir: INVARIANTS_IDLE)


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
            if "--list-boots" in args:
                return "0 boot Sat 2026-10-10 00:00:00 UTC—Sat 2026-10-10 03:00:00 UTC"
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


@pytest.mark.parametrize("kind,code,result", [
    ("killed", 15, "success"), ("killed", 15, "signal"),
    ("exited", 1, "exit-code"), ("exited", 75, "success")])
def test_systemd_result_and_termination_survive_storage(tmp_path, kind, code, result):
    unit = "sample.service"
    finish = (f"{unit}: Succeeded." if result == "success" else
              f"{unit}: Failed with result '{result}'.")
    raw = "\n".join([
        _entry("2026-10-10T02:40:00Z",
               f"{unit}: Main process exited, code={kind}, status={code}/n/a", "systemd"),
        _entry("2026-10-10T02:40:01Z", finish, "systemd")])
    with closing(ops_digest.open_db(tmp_path)) as db:
        for _ in range(2):
            [row] = ops_digest.store_runs(db, ops_digest.parse_journal(
                unit, raw, ops_digest.SourceSignals()))
        assert (row["started"], row["seconds"], row["termination_kind"], row["exit_code"],
                row["result"]) == (None, None, kind, code, result)
        assert db.execute("SELECT COUNT(*) FROM unit_runs").fetchone()[0] == 1


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

    report = ops_digest.report(24, tmp_path / "logs" / "ops", now=NOW, run=_fake_run({}))

    assert "1 FAIL" in report
    assert f"{unit}.service at 2026-10-10T02:30:00Z (10m00s): exit-code, exit 75" in report
    assert "price_verification=issues" in report


def test_clean_stop_that_systemd_reports_as_success_is_not_a_failed_run(tmp_path):
    # A restart of the API on 2026-10-15: SIGTERM is a clean exit for systemd, which logs the
    # signal as status=15 and then "Succeeded."; the digest counted the exit status as a failure.
    unit = "trading-engine-api.service"
    stop = [("Stopping Trading engine paper API...", "systemd"),
            (f"{unit}: Main process exited, code=killed, status=15/TERM", "systemd"),
            (f"{unit}: Succeeded.", "systemd"), ("Stopped Trading engine paper API.", "systemd")]
    journal = {unit: "\n".join(_entry("2026-10-10T02:46:54+00:00", *line) for line in stop)}

    [hour] = _collect(tmp_path, journal)
    report = ops_digest.report(24, tmp_path / "logs" / "ops", now=NOW, run=_fake_run(journal))

    assert hour["status"] == "OK" and "0 failed run(s)" in hour["text"]
    assert "| trading-engine-api | — | 02:46:54 | — | — | success (exit 15) [killed] |" in (
        hour["text"])
    assert "1 OK" in report and "Failed runs" not in report
    assert "| trading-engine-api | `—` | ? | 1 | 0 | 0 | ? | schedule unknown |" in report


def _backup_journal(*messages: str) -> dict[str, str]:
    unit = "trading-data-backup.service"
    lines = [("Starting Back up the trading engine store...", "systemd"),
             *((message, "python") for message in messages),
             (f"{unit}: Succeeded.", "systemd"), ("Started Back up the trading engine store.",
                                                  "systemd")]
    return {unit: "\n".join(_entry("2026-10-10T02:34:53+00:00", *line) for line in lines)}


def test_backup_that_exits_75_on_busy_locks_is_reported_as_skipped(tmp_path):
    # 2026-10-19 04:34 and 10:33: backup.py exited 75 (SuccessExitStatus=75), systemd logged
    # "Succeeded." and the digest said success although nothing was backed up.
    journal = _backup_journal(
        "2026-10-19T04:34:53Z push preflight passed",
        "2026-10-19T04:34:53Z engine locks busy: active process holds .queue-drain.lock; "
        "backup not started",
    )

    [hour] = _collect(tmp_path, journal)

    assert hour["status"] == "WARN" and "0 failed run(s)" in hour["text"]
    assert "| trading-data-backup | 02:34:53 | 02:34:53 | 0s | — | skipped/retry (exit 75) |" in (
        hour["text"])
    assert "success" not in hour["text"].split("## Unit runs")[1].split("\n\n")[1]


def test_backup_that_completes_is_still_a_success(tmp_path):
    journal = _backup_journal("2026-10-10T02:34:53Z backup 20261010T023300Z: 6 tables changed")

    [hour] = _collect(tmp_path, journal)

    assert hour["status"] == "OK"
    assert "| trading-data-backup | 02:34:53 | 02:34:53 | 0s | — | success |" in hour["text"]


def test_failure_whose_result_lands_in_the_next_hour_keeps_its_exit_code(tmp_path):
    # The exit line falls in hour 02 and systemd's result line in hour 03. Storing hour 03
    # overwrote the run's exit status with NULL, so the report said "exit None".
    unit = "trading-engine-p15-scoring.service"
    lines = [("2026-10-10T02:30:00+00:00", "Starting Nightly scoring..."),
             ("2026-10-10T02:59:59+00:00",
              f"{unit}: Main process exited, code=exited, status=75/n/a"),
             ("2026-10-10T03:00:01+00:00", f"{unit}: Failed with result 'exit-code'.")]
    entries = [(datetime.fromisoformat(s).timestamp(), _entry(s, m, "systemd")) for s, m in lines]
    units = _fake_run({unit: ""})

    def run(args, timeout):
        if args[0] != "journalctl":
            return units(args, timeout)
        if "--list-boots" in args:
            return units(args, timeout)
        since, until = (int(args[args.index(flag) + 1][1:]) for flag in ("--since", "--until"))
        return "\n".join(entry for when, entry in entries if since <= when < until)

    logs = tmp_path / "logs"
    logs.mkdir()
    later = datetime(2026, 10, 10, 4, 5, tzinfo=UTC)
    paths = {"logs_dir": logs, "ops_dir": logs / "ops", "db_path": tmp_path / "store.duckdb"}
    [first] = ops_digest.collect(now=NOW, run=run, fetch=_fetch, **paths)
    [second] = ops_digest.collect(now=later, run=run, fetch=_fetch, **paths)
    report = ops_digest.report(24, logs / "ops", now=later, run=_fake_run({}))

    assert first["status"] == "OK" and second["status"] == "FAIL"
    assert "| exit-code (exit 75) [exited] |" in second["text"]
    assert f"{unit} at 2026-10-10T02:30:00Z (30m01s): exit-code, exit 75" in report
    assert "exit None" not in report


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


def test_calendar_and_cron_specs_expand_to_due_starts():
    preopen = ops_digest.calendar_matcher("Mon..Fri *-*-* 09:05:00 America/New_York")
    events = ops_digest.calendar_matcher("Mon..Fri *-*-* 10..15:05,20,35,50:00 America/New_York")
    monthly = ops_digest.calendar_matcher("*-*-03 06:30:00 UTC")
    nightly = ops_digest.cron_matcher("30 22 * * 1-5".split())
    saturday = ops_digest.cron_matcher("15 5 * * 6".split())
    week = (datetime(2026, 10, 14, tzinfo=UTC), datetime(2026, 10, 18, tzinfo=UTC))

    assert ops_digest.expected_times(preopen, *week) == [
        datetime(2026, 10, day, 13, 5, tzinfo=UTC) for day in (14, 15, 16)]
    assert ops_digest.expected_times(  # New York leaves daylight time on 2026-11-01
        preopen, datetime(2026, 11, 2, tzinfo=UTC), datetime(2026, 11, 3, tzinfo=UTC)) == [
        datetime(2026, 11, 2, 14, 5, tzinfo=UTC)]
    assert len(ops_digest.expected_times(events, *week)) == 72
    assert ops_digest.expected_times(
        monthly, datetime(2026, 11, 1, tzinfo=UTC), datetime(2026, 12, 1, tzinfo=UTC)) == [
        datetime(2026, 11, 3, 6, 30, tzinfo=UTC)]
    assert ops_digest.expected_times(nightly, *week) == [
        datetime(2026, 10, day, 22, 30, tzinfo=UTC) for day in (14, 15, 16)]
    assert ops_digest.expected_times(saturday, *week) == [
        datetime(2026, 10, 17, 5, 15, tzinfo=UTC)]


def _schedule_run(tmp_path):
    preopen = "trading-engine-p15-preopen"
    shown = (
        f"Unit={preopen}.service\nTimersCalendar={{ OnCalendar=Mon..Fri *-*-* 09:05:00 "
        "America/New_York ; next_elapse=Mon 2026-10-19 13:05:00 UTC }\nAccuracyUSec=1min\n"
        "RandomizedDelayUSec=0\n\nUnit=store-sync.service\nTimersMonotonic={ "
        "OnUnitActiveUSec=15min ; next_elapse=5min }\nAccuracyUSec=1min\nRandomizedDelayUSec=0\n")
    crontab = (
        "MAILTO=nobody\n@reboot /x/ensure.sh\n"
        "30 22 * * 1-5 /x/engine/run_daily.sh >> /x/logs/cron.log 2>&1\n"
        f"15 5 * * 6 cd /x && python -m tools.postflight > {tmp_path}/friday-postflight.log 2>&1\n")

    def run(args, _timeout):
        if args[:3] == ["systemctl", "--user", "list-timers"]:
            return (f"n/a n/a n/a n/a {preopen}.timer {preopen}.service\n"
                    "n/a n/a n/a n/a store-sync.timer store-sync.service\n")
        if args[:3] == ["systemctl", "--user", "show"]:
            return shown
        return crontab if args == ["crontab", "-l"] else None
    return run


def test_report_lists_every_run_and_stage_against_the_schedules(tmp_path):
    ops = tmp_path / "ops"
    with closing(ops_digest.open_db(ops)) as db:
        begin = datetime(2026, 10, 14, 12, tzinfo=UTC)
        finish = datetime(2026, 10, 17, 12, 30, tzinfo=UTC)
        for moment in (begin, finish):
            ops_digest.sample_schedules(db, _schedule_run(tmp_path), moment)
        for source in ("trading-engine-p15-preopen.service", "stages"):
            ops_digest.record_coverage(db, source, begin, finish)
        db.executemany("INSERT INTO hours (hour, status) VALUES (?, 'OK')",
                       [(f"2026-10-17T{hour:02}",) for hour in range(12)])
        db.executemany("INSERT INTO unit_runs (unit, started, ended, seconds, exit_code, result) "
                       "VALUES (?,?,?,?,?,?)", [
            ("trading-engine-p15-preopen.service", "2026-10-14T13:05:58Z",
             "2026-10-14T13:05:59Z", 1.0, 1, "exit-code"),
            ("trading-engine-p15-preopen.service", "2026-10-16T13:05:07Z",
             "2026-10-16T13:05:17Z", 10.0, 0, "success"),
            ("store-sync.service", "2026-10-16T13:00:00Z", "2026-10-16T13:00:03Z", 3.0, 0,
             "success")])
        db.executemany("INSERT INTO stage_runs VALUES (?,?,?,?,?,?,?)", [
            ("run_daily-20261014T223001.1Z-7", "collect", "run_daily", "2026-10-14T22:30:03Z",
             "2026-10-14T22:34:03Z", 240.0, 0),
            ("run_daily-20261014T223001.1Z-7", "snapshot", "run_daily", "2026-10-14T23:22:01Z",
             "2026-10-14T23:23:01Z", 60.0, 0),
            ("run_daily-20261016T223001.1Z-8", "collect", "run_daily", "2026-10-16T22:30:03Z",
             "2026-10-16T22:31:03Z", 60.0, 1)])
        db.commit()
    postflight = tmp_path / "friday-postflight.log"
    postflight.write_text("")
    stamp = datetime(2026, 10, 17, 5, 16, tzinfo=UTC).timestamp()
    os.utime(postflight, (stamp, stamp))

    report = ops_digest.report(72, ops, now=datetime(2026, 10, 17, 12, 30, tzinfo=UTC),
                               run=_schedule_run(tmp_path))

    missing = report[report.index("## Missing runs"):report.index("## Runs")]
    assert "- trading-engine-p15-preopen: due 10-15 13:05Z" in missing
    assert "- run_daily: due 10-15 22:30Z" in missing
    assert missing.count("\n- ") == 2
    assert ("| trading-engine-p15-preopen | `timer Mon..Fri *-*-* 09:05:00 America/New_York` "
            "| 3 | 2 | 1 | 0 | 1 | 0 | 10-14 13:05Z exit-code 1s; 10-16 13:05Z success 10s |") in report
    assert "| run_daily | `cron 30 22 * * 1-5` | 3 | 2 | 1 | 0 | 1 | 0 |" in report
    assert ("| friday-postflight | `cron 15 5 * * 6` | 1 | 1 | 0 | 0 | 0 | "
            "0 | 10-17 05:16Z output written |") in report
    assert "| store-sync | `timer OnUnitActiveUSec=15min` | ? | 1 | 0 | 0 | ? | schedule unknown |" in report
    assert "- run_daily 10-14 22:30Z, 53m00s: collect 4m00s · snapshot 1m00s" in report
    assert "- run_daily 10-16 22:30Z, 1m02s: collect 1m00s exit 1" in report


def test_installed_services_are_discovered_without_a_timer(tmp_path, monkeypatch):
    units = tmp_path / "units"
    units.mkdir()
    (units / "report-after-settle.service").write_text("[Service]\n")
    (units / "template@.service").write_text("[Service]\n")
    monkeypatch.setattr(ops_digest, "USER_UNIT_DIR", units)

    assert ops_digest.discover_units(_fake_run({})) == ["report-after-settle.service"]


def test_current_schedule_does_not_invent_missing_unobserved_history(tmp_path):
    with closing(ops_digest.open_db(tmp_path)) as db:
        missing, lines = ops_digest.runs_lines(
            db, _schedule_run(tmp_path), datetime(2026, 10, 3, tzinfo=UTC),
            datetime(2026, 10, 17, tzinfo=UTC))
    assert missing == []
    assert "unknown" in "\n".join(lines).lower()


def test_fourteen_day_schedule_change_short_journal_and_dated_receipts(tmp_path):
    start = datetime(2026, 10, 3, tzinfo=UTC)
    end = start + timedelta(days=14)
    change = start + timedelta(days=7)
    job = "trading-engine-ops-digest"

    def installed(minute):
        def run(args, _timeout):
            if "list-timers" in args:
                return f"x {job}.timer {job}.service"
            if "show" in args:
                return (f"Unit={job}.service\nTimersCalendar={{ OnCalendar=*-*-* "
                        f"*:0{minute}:00 UTC ; }}\nAccuracyUSec=1min\nRandomizedDelayUSec=0\n")
            return ""
        return run

    old, new = installed(5), installed(8)
    receipts = {job: [ops_digest.JobRun(start + timedelta(hours=h, minutes=5 if h < 168 else 8),
                                       None, None, "receipt completed; exit unknown")
                      for h in range(336) if h != 200]}
    with closing(ops_digest.open_db(tmp_path)) as db:
        for moment, runner in ((start, old), (change - timedelta(minutes=1), old),
                               (change, new), (end, new)):
            ops_digest.sample_schedules(db, runner, moment)
        ops_digest.record_coverage(db, f"{job}.service", change, end)
        missing, lines = ops_digest.runs_lines(db, new, start, end, receipts)
    assert len(missing) == 1 and "10-11 08:08Z" in missing[0]
    table = "\n".join(lines)
    assert table.count(f"| {job} |") == 1
    assert "| 336 | 335 | 0 | 0 | 1 |" in table
    assert "schedule unknown" in table  # transition interval is never backdated


def test_missing_requires_coverage_of_entire_start_window(tmp_path):
    begin = datetime(2026, 10, 14, tzinfo=UTC)
    finish = begin + timedelta(days=1)
    runner = _schedule_run(tmp_path)
    with closing(ops_digest.open_db(tmp_path)) as db:
        for moment in (begin, finish):
            ops_digest.sample_schedules(db, runner, moment)
        # The journal stops during the six-minute allowed pre-open start window.
        ops_digest.record_coverage(db, "trading-engine-p15-preopen.service", begin,
                                   begin + timedelta(hours=13, minutes=6))
        missing, lines = ops_digest.runs_lines(db, runner, begin, finish)
    assert missing == []
    assert "| 1 | 0 | 0 | 0 | 0 | 1 |" in "\n".join(lines)


def test_work_receipts_read_only_from_resolved_snapshot(tmp_path, monkeypatch):
    from types import SimpleNamespace

    published = tmp_path / "published.duckdb"
    with duckdb.connect(str(published)) as con:
        con.execute("CREATE TABLE p15_event_windows (observed_at TIMESTAMP, "
                    "completed_at TIMESTAMP, status VARCHAR, reason VARCHAR)")
        con.execute("INSERT INTO p15_event_windows VALUES ('2026-10-05 13:35:59', "
                    "'2026-10-05 13:37:27', 'completed', NULL)")
    before = published.read_bytes()
    monkeypatch.setattr(ops_digest, "latest_snapshot", lambda database:
                        SimpleNamespace(path=published))
    receipts, gaps = ops_digest.work_receipts(tmp_path / "absent-primary.duckdb",
                                             datetime(2026, 10, 3, tzinfo=UTC), NOW)
    [row] = receipts["trading-engine-p15-events"]
    assert row.start == datetime(2026, 10, 5, 13, 35, 59, tzinfo=UTC)
    assert row.ok is None and row.seconds is None and row.label.endswith("exit unknown")
    assert len(gaps) == 3 and before == published.read_bytes()
    assert not (tmp_path / "absent-primary.duckdb").exists()


def test_dated_observer_receipts_are_used_before_text_tail_coverage(tmp_path):
    log = tmp_path / "hourly_market_watch_v5.jsonl"
    log.write_text("\n".join(json.dumps({"observed_at": f"2026-10-0{day}T14:15:00+00:00",
                    "completed_at": f"2026-10-0{day}T14:16:00+00:00", "unavailable_count": 1})
                    for day in (5, 6)))
    receipts, gaps = ops_digest.work_receipts(tmp_path / "absent.duckdb",
                datetime(2026, 10, 3, tzinfo=UTC), NOW, tmp_path)
    rows = receipts["trading-engine-hourly-opportunity"]
    assert len(rows) == 2 and all(r.degraded and r.ok is None for r in rows)
    assert "no published snapshot" in gaps[0]


@pytest.mark.parametrize("line,level", [
    ("fetch failed", "error"), ("push failed", "error"),
    ("operator_digest failed (non-fatal)", "error"),
    ("[agent-data-capture] status=failed failed_steps=price_observations", "error"),
    ("fatal: could not read from remote repository", "error"),
    ("rebase conflict: left for a session to resolve", "warn"),
    ("ERROR: python interpreter missing — cannot start", "error"),
    ("ERROR: relaunch did not come up", "error"),
    ('{"status": "unavailable", "reason": "pre-open evidence is invalid"}', "warn"),
    ('{"status": "late"}', "warn"),
    ("[backfill] processed=20 with_data=19 failed=1", "warn"),
    ('{"backfill": {"processed": 20, "failed": 1}}', "warn"),
    ("[queue] job 1 (archive) refused: memory exceeds budget", "warn"),
    ("[queue] disk watchdog: refusing archive job 1", "warn"),
    ("[queue] resource guard tripped; leaving 2 jobs pending", "warn"),
    ("[queue] drain budget exhausted; leaving 2 pending jobs", "warn"),
    ("[queue] job 1 failed: bad params JSON", "error"),
    ("active process holds .nightly.lock; backup not started", "warn"),
    ("[backfill] processed=20 with_data=20 failed=0", None),
    ("[queue] no pending jobs; nothing to do", None),
    ("no open recurring sweep grids", None),
    ("snapshot younger than 120 minutes; publication skipped", None),
    ("skip: not on main", None), ("SKIP: another ensure_scraper is running", None),
    ('{"status": "no_session"}', None),
    ("already successfully backed up today", None)])
def test_host_failure_and_fail_soft_messages(line, level):
    assert ops_digest.classify(line) == level


def test_structured_snapshot_throttle_is_a_valid_noop():
    assert ops_digest.classify(json.dumps({"status": "skipped", "reason":
        "latest snapshot is 55.1 minutes old; minimum age is 120 minutes"})) is None


@pytest.mark.parametrize("code,kind", [(15, "killed"), (75, "exited")])
def test_success_in_next_hour_preserves_actual_termination(tmp_path, code, kind):
    unit = "sample.service"
    with closing(ops_digest.open_db(tmp_path)) as db:
        ops_digest.store_runs(db, [ops_digest.UnitRun(unit, "2026-10-10T02:01:00Z",
                                                    exit_code=code, termination_kind=kind)])
        [row] = ops_digest.store_runs(db, ops_digest.parse_journal(unit, _entry(
            "2026-10-10T03:01:00Z", f"{unit}: Succeeded.", "systemd"),
            ops_digest.SourceSignals()))
    assert (row["exit_code"], row["termination_kind"], row["result"]) == (code, kind, "success")


def test_host_sources_expand_home_globs_and_are_counted_once(tmp_path, monkeypatch):
    host = tmp_path / "host"
    state = host / ".local" / "state"
    state.mkdir(parents=True)
    log = state / "store-sync.log"
    log.write_text("old history\n")
    logs = tmp_path / "logs"
    ops = logs / "ops"
    ops.mkdir(parents=True)
    (ops / "sources.txt").write_text("# existing sources\n$HOME/.local/state/*.log\n"
                                     "~/.local/state/store-sync.log\n")
    monkeypatch.setenv("HOME", str(host))
    monkeypatch.setattr(ops_digest, "HOST_LOG_GLOBS", ("~/.local/state/*.log",))
    assert ops_digest._log_sources(logs, ops) == [log]
    _collect(tmp_path, {})
    log.write_text("old history\nfetch failed\npush failed\n")
    [hour] = _collect(tmp_path, {}, now=NOW + timedelta(hours=1))
    assert hour["status"] == "WARN"
    with closing(sqlite3.connect(ops / "ops.sqlite")) as db:
        assert db.execute("SELECT SUM(errors) FROM log_counts").fetchone()[0] == 2


def test_warning_only_hour_is_degraded_and_noops_stay_ok(tmp_path):
    journal = {"sample.service": _entry("2026-10-10T02:10:00Z",
                "[backfill] processed=20 with_data=19 failed=1")}
    [hour] = _collect(tmp_path, journal)
    assert hour["status"] == "WARN" and "1 warning line(s)" in hour["text"]
    journal = {"sample.service": _entry("2026-10-10T03:10:00Z", "no open recurring sweep grids")}
    [hour] = _collect(tmp_path, journal, now=NOW + timedelta(hours=1))
    assert hour["status"] == "OK"


def test_unavailable_preopen_receipt_degrades_successful_exit(tmp_path, monkeypatch):
    from types import SimpleNamespace

    published = tmp_path / "published.duckdb"
    with duckdb.connect(str(published)) as con:
        con.execute("CREATE TABLE p15_preopen_runs (started_at TIMESTAMP, "
                    "completed_at TIMESTAMP, status VARCHAR, reason VARCHAR)")
        con.execute("INSERT INTO p15_preopen_runs VALUES ('2026-10-10 02:30:05', "
                    "'2026-10-10 02:31:00', 'unavailable', 'pre-open evidence is invalid')")
    monkeypatch.setattr(ops_digest, "latest_snapshot", lambda database:
                        SimpleNamespace(path=published))
    unit = "trading-engine-p15-preopen.service"
    [hour] = _collect(tmp_path, {unit: _journal(unit)})
    report = ops_digest.report(24, tmp_path / "logs" / "ops", now=NOW,
                               run=_fake_run({unit: ""}))
    assert hour["status"] == "WARN" and "0 failed run(s)" in hour["text"]
    assert "Degraded work receipts" in hour["text"]
    assert "[WARN] trading-engine-p15-preopen" in report
    assert "| 1 | 0 | 1 | ? |" in report  # one run, lifecycle failure 0, degradation 1


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


def test_moved_sunday_history_slot_finishes_before_weekly_readers():
    timer = ROOT / "server" / "trading-engine-tradingview-history.timer"
    specs = [line.split("=", 1)[1] for line in timer.read_text().splitlines()
             if line.startswith("OnCalendar=")]
    matcher = ops_digest._any_of([ops_digest.calendar_matcher(s) for s in specs])
    sunday = datetime(2026, 10, 18, tzinfo=UTC)
    slots = ops_digest.expected_times(matcher, sunday, sunday + timedelta(days=1))
    assert [s.hour for s in slots] == [1, 3, 11, 15, 19, 23]
    saturday = sunday - timedelta(days=1)
    assert [s.hour for s in ops_digest.expected_times(matcher, saturday, sunday)] == [
        3, 7, 11, 15, 19, 23]
    service = ROOT / "server" / "trading-engine-tradingview-history.service"
    timeout = next(line.split("=", 1)[1] for line in service.read_text().splitlines()
                   if line.startswith("TimeoutStartSec="))
    delay = next(line.split("=", 1)[1] for line in timer.read_text().splitlines()
                 if line.startswith("RandomizedDelaySec="))
    latest_end = slots[0] + timedelta(seconds=_span(timeout) + _span(delay) + 60)
    assert latest_end < sunday + timedelta(hours=6)


def test_schedule_contract_violation_is_published_and_warns(tmp_path, monkeypatch):
    holder = {"rule": "foreign-holder", "subject": "pid 4242",
              "detail": {"pid": 4242, "database": "store/market.duckdb", "mode": "write",
                         "cmdline": "uv run pytest", "cgroup": "0::/user.slice/session-c9.scope"}}
    monkeypatch.setattr(ops_digest, "contract_probe", lambda now: {
        **CONTRACT_OK, "status": "violations", "violations": [holder]})

    [hour] = _collect(tmp_path, {})

    assert hour["status"] == "WARN"
    assert "## Schedule contract" in hour["text"]
    assert "- foreign-holder: pid 4242 (pid 4242, database store/market.duckdb" in hour["text"]
    written = json.loads((tmp_path / "logs" / "ops" / "schedule-contract.json").read_text())
    assert written["violations"] == [holder]


def test_schedule_contract_probe_crash_is_a_collection_gap(tmp_path, monkeypatch):
    monkeypatch.setattr(ops_digest.schedule_contract, "check",
                        lambda **_: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(ops_digest, "contract_probe", REAL_CONTRACT_PROBE)

    [hour] = _collect(tmp_path, {})

    assert hour["status"] == "WARN"
    assert "schedule contract probe: probe crashed: RuntimeError" in hour["text"]


def _invariants_result(sha: str, status: str = "regression") -> dict:
    regression = {"subject": "DDS 2026-10-12", "class": "stale_provisional", "detail": {}}
    return {
        "status": status, "mode": "shadow", "checked_at": "2026-10-10T03:05:30+00:00",
        "regression_count": 4 if status == "regression" else 0,
        "snapshot": {"name": "market-20261010T025000000000Z.duckdb", "sha256": sha},
        "invariants": {
            "ohlc_geometry": {"status": status, "regression_count": 4,
                              "regressions": [regression] * 4, "error": None},
            "fee_row_per_fill": {"status": "pass", "regression_count": 0, "regressions": [],
                                 "error": None},
        },
    }


def test_shadow_invariant_regressions_are_listed_but_never_change_the_hour(tmp_path,
                                                                           monkeypatch):
    monkeypatch.setattr(ops_digest, "invariants_probe", lambda _ops_dir: {
        "ran": True, "reason": None, "result": _invariants_result("a" * 64), "error": None})

    [hour] = _collect(tmp_path, {})

    assert hour["status"] == "OK"
    assert "## Invariants (shadow)" in hour["text"]
    assert "regression: 4 regression(s) on market-20261010T025000000000Z.duckdb" in hour["text"]
    assert ("- ohlc_geometry: regression, 4 regression(s): stale_provisional DDS 2026-10-12, "
            "stale_provisional DDS 2026-10-12, stale_provisional DDS 2026-10-12 and 1 more"
            in hour["text"])
    assert "fee_row_per_fill" not in hour["text"]


def test_invariants_run_only_when_the_published_snapshot_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(ops_digest, "invariants_probe", REAL_INVARIANTS_PROBE)
    published = {"sha": "a" * 64}
    monkeypatch.setattr(ops_digest, "latest_snapshot",
                        lambda _db: SimpleNamespace(sha256=published["sha"]))
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        out = Path(args[args.index("--publish") + 1])
        out.write_text(json.dumps(_invariants_result(published["sha"], "pass")))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(ops_digest.subprocess, "run", run)
    ops = tmp_path / "ops"
    ops.mkdir()

    first = ops_digest.invariants_probe(ops)
    again = ops_digest.invariants_probe(ops)
    published["sha"] = "b" * 64
    moved = ops_digest.invariants_probe(ops)

    assert (first["ran"], again["ran"], moved["ran"]) == (True, False, True)
    assert again["reason"] == "snapshot unchanged" and again["result"]["status"] == "pass"
    assert len(calls) == 2
    assert calls[0][1:5] == ["-m", "tools.check_invariants", "--snapshot", "latest"]
    assert "--gate" not in calls[0]


def test_invariants_probe_retries_errors_and_reports_a_timeout(tmp_path, monkeypatch):
    monkeypatch.setattr(ops_digest, "latest_snapshot",
                        lambda _db: SimpleNamespace(sha256="a" * 64))
    ops = tmp_path / "ops"
    ops.mkdir()
    (ops / ops_digest.INVARIANTS_RESULT).write_text(json.dumps(
        {"status": "error", "snapshot": {"sha256": "a" * 64}}))

    def slow(args, **kwargs):
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])

    monkeypatch.setattr(ops_digest.subprocess, "run", slow)
    result = REAL_INVARIANTS_PROBE(ops)
    assert result["ran"] is True
    assert result["error"] == f"timed out after {ops_digest.INVARIANTS_TIMEOUT_S}s"

    monkeypatch.setattr(ops_digest, "invariants_probe", lambda _ops_dir: result)
    # The snapshot stub above has no file; revision-15 work receipts read the
    # snapshot through the same helper, so keep them out of this probe test.
    monkeypatch.setattr(ops_digest, "work_receipts", lambda *_args: ({}, []))
    [hour] = _collect(tmp_path, {})
    assert "invariants probe: timed out" in hour["text"]
    assert hour["status"] == "OK"
