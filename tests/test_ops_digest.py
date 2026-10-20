from __future__ import annotations

import json
import os
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
from server import agent_model_client
from tools import ops_digest

NOW = datetime(2026, 10, 10, 3, 5, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _no_host_units(tmp_path, monkeypatch):
    monkeypatch.setattr(ops_digest, "USER_UNIT_DIR", tmp_path / "no-units")


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
        if args[1:] == ["--version"]:
            return "traecli 0.210.1\n"
        return None
    return run


def _gateway_health(**overrides):
    return {
        "ok": True, "proxy_version": agent_model_client.REQUIRED_PROXY_VERSION,
        "proxy_source_sha256": agent_model_client.REQUIRED_PROXY_SOURCE_SHA256,
        "traex": "traecli 0.210.1", "token": {"present": True, "hours_left": 170.0},
        "relogin": {"last_ok": True}, "catalog": {"age_s": 3600}, **overrides,
    }


def _gateway_fetch(health):
    def fetch(url, timeout):
        if url == ops_digest.GATEWAY_URL + "/healthz":
            return 200, 2, json.dumps(health).encode()
        if url == ops_digest.GATEWAY_URL + "/v1/models":
            return 200, 2, json.dumps({"object": "list", "data": [
                agent_model_client.EXPECTED_MODEL_CATALOG_ENTRY]}).encode()
        if url.endswith("/meta"):
            return 200, 40, json.dumps({"nightly": {"status": "ok"},
                                        "price_verification": {"status": "issues"}}).encode()
        return 200, 3, b"{}"
    return fetch


_fetch = _gateway_fetch(_gateway_health())


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
    assert "| trading-engine-api | 02:46:54 | 02:46:54 | 0s | — | success (exit 15) |" in (
        hour["text"])
    assert "1 OK" in report and "Failed runs" not in report
    assert "| trading-engine-api | `—` | ? | 1 | 0 | ? |" in report


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
    assert "| exit-code (exit 75) |" in second["text"]
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
        db.executemany("INSERT INTO hours (hour, status) VALUES (?, 'OK')",
                       [(f"2026-10-17T{hour:02}",) for hour in range(12)])
        db.executemany("INSERT INTO unit_runs VALUES (?,?,?,?,?,?)", [
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
            "| 3 | 2 | 1 | 1 | 10-14 13:05Z exit-code 1s; 10-16 13:05Z success 10s |") in report
    assert "| run_daily | `cron 30 22 * * 1-5` | 3 | 2 | 1 | 1 |" in report
    assert ("| friday-postflight | `cron 15 5 * * 6` | 1 | 1 | 0 | 0 | "
            "10-17 05:16Z output written |") in report
    assert "| store-sync | `timer OnUnitActiveUSec=15min` | ? | 1 | 0 | ? |" in report
    assert "- run_daily 10-14 22:30Z, 53m00s: collect 4m00s · snapshot 1m00s" in report
    assert "- run_daily 10-16 22:30Z, 1m02s: collect 1m00s exit 1" in report


def test_installed_services_are_discovered_without_a_timer(tmp_path, monkeypatch):
    units = tmp_path / "units"
    units.mkdir()
    (units / "report-after-settle.service").write_text("[Service]\n")
    (units / "template@.service").write_text("[Service]\n")
    monkeypatch.setattr(ops_digest, "USER_UNIT_DIR", units)

    assert ops_digest.discover_units(_fake_run({})) == ["report-after-settle.service"]


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


@pytest.mark.parametrize(("health", "status", "detail"), [
    (_gateway_health(), "OK", "Gateway OK: startup runtime 0.210.1, installed 0.210.1"),
    (_gateway_health(token={"present": True, "hours_left": 12.0}), "WARN",
     "- [warn] token_hours_left: observed `12.0`"),
    (_gateway_health(traex="traecli 0.299.9"), "FAIL", "- [fail] startup_runtime"),
])
def test_hourly_digest_embeds_the_model_gateway_preflight(tmp_path, health, status, detail):
    logs = tmp_path / "logs"
    logs.mkdir()
    requested = []
    fetch = _gateway_fetch(health)

    def recording(url, timeout):
        requested.append(url)
        return fetch(url, timeout)

    [hour] = ops_digest.collect(now=NOW, run=_fake_run({}), fetch=recording, logs_dir=logs,
                                ops_dir=logs / "ops", db_path=tmp_path / "store.duckdb")

    assert hour["status"] == status
    assert "## Model gateway" in hour["text"] and detail in hour["text"]
    gateway = [url for url in requested if url.startswith(ops_digest.GATEWAY_URL)]
    assert gateway == [ops_digest.GATEWAY_URL + "/healthz", ops_digest.GATEWAY_URL + "/v1/models"]
