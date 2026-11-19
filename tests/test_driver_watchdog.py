import json
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tools import driver_watchdog

STALLED = "exec 9>\"$(dirname \"$0\")/../.test.lock\"\nflock 9\nsleep 600\n"
BUSY = "exec 9>\"$(dirname \"$0\")/../.test.lock\"\nflock 9\nwhile :; do :; done\n"


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
        if driver_watchdog.lock_holders(Path("/proc"), engine / ".test.lock"):
            return process
        time.sleep(0.05)
    process.kill()
    raise AssertionError("driver never took its lock")


def test_a_stalled_driver_past_its_runtime_is_terminated(engine):
    process = _start(engine, STALLED)
    try:
        receipts = driver_watchdog.check(engine, now=datetime.now(UTC) + timedelta(seconds=150),
                                         sample_seconds=0.5)
        process.wait(timeout=40)
    finally:
        if process.poll() is None:
            process.kill()
    [receipt] = receipts
    assert receipt["status"] == "failed" and receipt["action"] == "terminated"
    assert receipt["reason"] == "stalled" and receipt["survivors"] == []
    assert "== py-spy" not in Path(receipt["stacks"]).read_text()  # bash, not Python
    assert not driver_watchdog.lock_holders(Path("/proc"), engine / ".test.lock")


def test_a_busy_overdue_driver_is_reported_but_left_running(engine):
    process = _start(engine, BUSY)
    try:
        receipts = driver_watchdog.check(engine, now=datetime.now(UTC) + timedelta(seconds=150),
                                         sample_seconds=0.5)
        assert process.poll() is None
    finally:
        process.kill()
    assert [(r["status"], r["action"]) for r in receipts] == [("degraded", "none")]


def test_a_driver_inside_its_runtime_or_a_foreign_holder_is_ignored(engine):
    process = _start(engine, STALLED)
    try:
        assert driver_watchdog.check(engine, sample_seconds=0.1) == []
    finally:
        process.kill()
    holder = subprocess.Popen(["flock", str(engine / ".test.lock"), "sleep", "600"],
                              start_new_session=True)
    (engine / "engine/run_test.sh").write_text("DRIVER_LOCK=.test.lock\n")
    try:
        time.sleep(0.3)
        later = datetime.now(UTC) + timedelta(hours=5)
        assert driver_watchdog.check(engine, now=later, sample_seconds=0.1) == []
        assert holder.poll() is None
    finally:
        holder.kill()


def test_dry_run_reports_without_terminating(engine):
    process = _start(engine, STALLED)
    try:
        receipts = driver_watchdog.check(engine, now=datetime.now(UTC) + timedelta(seconds=150),
                                         sample_seconds=0.3, act=False)
        assert process.poll() is None
    finally:
        process.kill()
    assert [(r["status"], r["action"]) for r in receipts] == [("failed", "dry-run")]


@pytest.mark.parametrize(("now", "others", "expected"), [
    (datetime(2026, 11, 19, 4, 30, tzinfo=UTC), False, "started"),          # Thursday
    (datetime(2026, 11, 19, 13, 0, tzinfo=UTC), False, "outside-window"),   # too near pre-open
    (datetime(2026, 11, 21, 4, 30, tzinfo=UTC), False, "outside-window"),   # Saturday
    (datetime(2026, 11, 19, 4, 30, tzinfo=UTC), True, "another-driver-running"),
])
def test_catch_up_runs_once_per_day_inside_its_window(tmp_path, monkeypatch, now, others,
                                                      expected):
    calls = []
    monkeypatch.setattr(driver_watchdog.subprocess, "run",
                        lambda command, **kwargs: calls.append(command)
                        or subprocess.CompletedProcess(command, 0, "", ""))
    state = tmp_path / "state.json"
    assert driver_watchdog.catch_up(tmp_path, now, state, others) == expected
    assert len(calls) == (expected == "started")
    if expected == "started":
        assert calls[0][:3] == ["systemd-run", "--user",
                                f"--unit={driver_watchdog.CATCH_UP_UNIT}"]
        assert json.loads(state.read_text()) == {"catch_up_day": "2026-11-19"}
        assert driver_watchdog.catch_up(tmp_path, now, state, others) == "already-ran-today"


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
