import json
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tools import driver_watchdog

PROC = Path("/proc")
STALLED = "exec 9>\"$(dirname \"$0\")/../.test.lock\"\nflock 9\nsleep 600\n"
ORPHANING = ("exec 9>\"$(dirname \"$0\")/../.test.lock\"\nflock 9\n"
             "( sleep 600 & )\nsleep 600\n")
BUSY = "exec 9>\"$(dirname \"$0\")/../.test.lock\"\nflock 9\nwhile :; do :; done\n"
LATER = timedelta(seconds=150)


@pytest.fixture
def engine(tmp_path, monkeypatch):
    (tmp_path / "engine").mkdir()
    (tmp_path / "logs").mkdir()
    manifest = {"units": [], "cron": [{"name": "run_test", "state": "enabled",
                                       "match": "{engine}/engine/run_test.sh",
                                       "max_runtime": "100s"}]}
    monkeypatch.setattr(driver_watchdog.schedule_contract, "load_manifest", lambda: manifest)
    monkeypatch.setattr(driver_watchdog, "reset_failed_units", lambda manifest: [])
    return tmp_path


def _start(engine: Path, body: str) -> subprocess.Popen:
    script = engine / "engine/run_test.sh"
    script.write_text("#!/usr/bin/env bash\nDRIVER_LOCK=.test.lock\n" + body)
    process = subprocess.Popen(["bash", str(script)], start_new_session=True)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if driver_watchdog.lock_is_held(PROC, engine / ".test.lock"):
            return process
        time.sleep(0.05)
    _stop(process)
    raise AssertionError("driver never took its lock")


def _stop(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.kill()
    process.wait()


def test_a_stalled_driver_is_terminated_on_the_second_pass_and_waiters_survive(engine):
    process = _start(engine, STALLED)
    waiter = subprocess.Popen(["bash", "-c", f"exec 8>>{engine / '.test.lock'}; sleep 600"],
                              start_new_session=True)
    try:
        now = datetime.now(UTC) + LATER
        first = driver_watchdog.check(engine, now=now, sample_seconds=0.3)
        assert [(r["status"], r["action"]) for r in first] == [("degraded", "watching")]
        assert process.poll() is None
        second = driver_watchdog.check(engine, now=now + timedelta(minutes=10),
                                       sample_seconds=0.3)
        process.wait(timeout=40)
        assert waiter.poll() is None, "a process that only has the lock open is never signalled"
    finally:
        _stop(process)
        _stop(waiter)
    assert [(r["status"], r["action"]) for r in second] == [
        ("failed", "terminating"), ("failed", "terminated")]
    assert second[0]["reason"] == "stalled" and second[1]["survivors"] == []
    assert waiter.pid not in second[0]["pids"]
    assert "== py-spy" not in Path(second[0]["stacks"]).read_text()  # bash, not Python
    assert not driver_watchdog.lock_is_held(PROC, engine / ".test.lock")


def test_an_orphan_keeping_the_lock_is_terminated_with_its_run(engine):
    process = _start(engine, ORPHANING)
    try:
        now = datetime.now(UTC) + LATER
        driver_watchdog.check(engine, now=now, sample_seconds=0.2)
        receipts = driver_watchdog.check(engine, now=now + timedelta(minutes=10),
                                         sample_seconds=0.2)
        process.wait(timeout=40)
    finally:
        _stop(process)
    assert receipts[-1]["action"] == "terminated"
    assert receipts[-1]["lock_still_held"] is False and receipts[-1]["survivors"] == []
    assert not driver_watchdog.lock_holders(PROC, engine / ".test.lock")


def test_an_unconfirmed_stall_expires(engine):
    process = _start(engine, STALLED)
    try:
        now = datetime.now(UTC) + LATER
        driver_watchdog.check(engine, now=now, sample_seconds=0.2)
        late = driver_watchdog.check(engine, now=now + timedelta(hours=1), sample_seconds=0.2)
        assert process.poll() is None
    finally:
        _stop(process)
    assert [r["action"] for r in late] == ["watching"]


def test_a_busy_overdue_driver_is_reported_but_left_running(engine):
    process = _start(engine, BUSY)
    try:
        receipts = driver_watchdog.check(engine, now=datetime.now(UTC) + LATER,
                                         sample_seconds=0.5)
        assert process.poll() is None
    finally:
        _stop(process)
    assert [(r["status"], r["action"]) for r in receipts] == [("degraded", "none")]


def test_a_driver_inside_its_runtime_or_a_foreign_holder_is_ignored(engine):
    process = _start(engine, STALLED)
    try:
        assert driver_watchdog.check(engine, sample_seconds=0.1) == []
    finally:
        _stop(process)
    holder = subprocess.Popen(["flock", str(engine / ".test.lock"), "sleep", "600"],
                              start_new_session=True)
    try:
        time.sleep(0.3)
        later = datetime.now(UTC) + timedelta(hours=5)
        assert driver_watchdog.check(engine, now=later, sample_seconds=0.1) == []
        assert driver_watchdog.check(engine, now=later, sample_seconds=0.1) == []
        assert holder.poll() is None
    finally:
        _stop(holder)


def test_dry_run_reports_without_terminating(engine):
    process = _start(engine, STALLED)
    try:
        receipts = driver_watchdog.check(engine, now=datetime.now(UTC) + LATER,
                                         sample_seconds=0.3, act=False)
        assert process.poll() is None
    finally:
        _stop(process)
    assert [(r["status"], r["action"]) for r in receipts] == [("failed", "dry-run")]
    assert not (engine / "logs/.driver-watchdog-state.json").exists()


THURSDAY = datetime(2026, 11, 19, 4, 30, tzinfo=UTC)


def _advance(tmp_path, monkeypatch, state, *, now=THURSDAY, held=False, start=True, shown=""):
    started = []
    monkeypatch.setattr(driver_watchdog, "_start_catch_up",
                        lambda engine, now: started.append(now) or start)
    monkeypatch.setattr(driver_watchdog, "_systemctl",
                        lambda *args: subprocess.CompletedProcess(args, 0, shown, ""))
    receipts = []
    driver_watchdog.advance_catch_up(tmp_path, now, state, lambda: held, receipts.append)
    return started, [r["action"] for r in receipts]


def _owed(**extra):
    return {"catch_up": {"day": "2026-11-19", "status": "owed", "attempts": 0, **extra}}


@pytest.mark.parametrize(("now", "held", "started"), [
    (THURSDAY, False, True),
    (THURSDAY.replace(hour=13), False, False),        # too near the pre-open
    (datetime(2026, 11, 20, 4, 30, tzinfo=UTC), False, False),  # owed day has passed
    (THURSDAY, True, False),                          # the lock is still held
])
def test_an_owed_catch_up_starts_only_inside_its_window(tmp_path, monkeypatch, now, held, started):
    state = _owed()
    calls, actions = _advance(tmp_path, monkeypatch, state, now=now, held=held)
    assert bool(calls) is started
    if now.date() != THURSDAY.date():
        assert "catch_up" not in state and actions == ["catch-up-expired"]
    else:
        assert actions == (["catch-up-started"] if started else [])


def test_a_saturday_stall_owes_nothing_it_can_start(tmp_path, monkeypatch):
    saturday = datetime(2026, 11, 21, 4, 30, tzinfo=UTC)
    state = {"catch_up": {"day": "2026-11-21", "status": "owed", "attempts": 0}}
    calls, _ = _advance(tmp_path, monkeypatch, state, now=saturday)
    assert calls == [] and state["catch_up"]["status"] == "owed"


def test_a_started_catch_up_is_watched_retried_and_bounded(tmp_path, monkeypatch):
    state = _owed(status="started", attempts=1)
    _, actions = _advance(tmp_path, monkeypatch, state, shown="ActiveState=active\nResult=success\n")
    assert actions == [] and state["catch_up"]["status"] == "started"
    _, actions = _advance(tmp_path, monkeypatch, state, shown="ActiveState=failed\nResult=exit-code\n")
    assert actions == ["catch-up-failed", "catch-up-started"]
    assert state["catch_up"] == {"day": "2026-11-19", "status": "started", "attempts": 2}
    _, actions = _advance(tmp_path, monkeypatch, state, shown="")
    assert actions == [] and state["catch_up"]["status"] == "started"  # unreadable: wait
    calls = []
    monkeypatch.setattr(driver_watchdog, "_systemctl",
                        lambda *args: calls.append(args)
                        or subprocess.CompletedProcess(args, 0, "ActiveState=inactive\n", ""))
    receipts = []
    driver_watchdog.advance_catch_up(tmp_path, THURSDAY, state, lambda: False, receipts.append)
    assert [r["action"] for r in receipts] == ["catch-up-finished"]
    assert receipts[0]["p15_scoring_started"] is True and state["catch_up"]["status"] == "done"
    assert ("start", "--no-block", driver_watchdog.P15_SCORING_UNIT) in calls
    exhausted = _owed(attempts=driver_watchdog.CATCH_UP_ATTEMPTS)
    calls, actions = _advance(tmp_path, monkeypatch, exhausted)
    assert calls == [] and actions == ["catch-up-gave-up"]


def test_the_catch_up_run_ends_before_the_pre_open(tmp_path, monkeypatch):
    commands = []
    monkeypatch.setattr(driver_watchdog.subprocess, "run",
                        lambda command, **kwargs: commands.append(command)
                        or subprocess.CompletedProcess(command, 0, "", ""))
    assert driver_watchdog._start_catch_up(tmp_path, THURSDAY.replace(hour=11, minute=45))
    [command] = [c for c in commands if c[0] == "systemd-run"]
    assert commands[0][-2:] == ["reset-failed", driver_watchdog.CATCH_UP_UNIT]
    assert command[:3] == ["systemd-run", "--user", f"--unit={driver_watchdog.CATCH_UP_UNIT}"]
    assert "--property=RuntimeMaxSec=3600s" in command


def test_reset_failed_touches_only_this_repositorys_units(monkeypatch):
    calls = []

    def fake(*args):
        calls.append(args)
        listed = "trading-engine-hourly-opportunity.service loaded failed failed x\n" \
                 "live-287-signal.service loaded failed failed y\n"
        return subprocess.CompletedProcess(args, 0, listed, "")

    monkeypatch.setattr(driver_watchdog, "_systemctl", fake)
    manifest = {"units": [{"unit": "trading-engine-hourly-opportunity.service", "origin": "repo"},
                          {"unit": "live-287-signal.service", "origin": "external"}]}
    assert driver_watchdog.reset_failed_units(manifest) == [
        "trading-engine-hourly-opportunity.service"]
    assert calls[-1] == ("reset-failed", "trading-engine-hourly-opportunity.service")


def test_the_pause_file_disables_the_watchdog(tmp_path, capsys):
    (tmp_path / ".driver-watchdog.disabled").touch()
    assert driver_watchdog.main(["--engine-root", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out) == {"status": "disabled"}


def test_every_contract_driver_has_a_lock_and_a_runtime():
    root = Path(__file__).resolve().parents[1]
    manifest = driver_watchdog.schedule_contract.load_manifest()
    found = {d["name"]: d for d in driver_watchdog.drivers(manifest, root)}
    assert set(found) == {"run_daily", "run_weekly_verify", "run_weekend_sweeps",
                          "run_weekly_liquid", "run_weekly_walkforward"}
    assert found["run_daily"]["lock"] == root / ".nightly.lock"
    assert found["run_daily"]["limit"] == 6 * 3600
