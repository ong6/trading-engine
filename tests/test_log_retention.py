"""Tests for bounded log retention (tools/log_retention.py) and its ops-digest hook."""

from __future__ import annotations

import gzip
import json
import os
import sqlite3
import subprocess
from contextlib import closing
from datetime import UTC, datetime, timedelta

import pytest

from server import driver_log, driver_monitor
from tools import log_retention, ops_digest

NOW = datetime(2026, 10, 20, 10, 8, tzinfo=UTC)
OLD = (NOW - timedelta(days=90)).timestamp()


def _no_evidence(_args, _timeout):
    return ""


def _cited(*names):
    return lambda _args, _timeout: "".join(f"logs/{name}\n" for name in names)


def _age(path, stamp=OLD):
    os.utime(path, (stamp, stamp))


def _run_block(driver, start, end, *, lines=200, failed=False):
    out = [f"=== {driver} {start} ==="]
    out += [f"STAGE driver={driver} run_id=r stage=collect started={start} ended={end} "
            "seconds=1.0 exit=0"]
    out += [f"[{driver}] progress line {i} " + "x" * 80 for i in range(lines)]
    if failed:
        out.append(f"TODO: {driver} failed {end} (stage=collect exit 1) — inspect log")
    else:
        out.append(f"=== done {end} ===")
    return "\n".join(out) + "\n"


def _cron_logs(logs):
    logs.mkdir(exist_ok=True)
    (logs / "cron.log").write_text(
        _run_block("run_daily", "2026-10-15T22:30:01Z", "2026-10-16T01:00:00Z")
        + _run_block("run_daily", "2026-10-16T22:30:01Z", "2026-10-17T01:00:00Z", failed=True)
        + _run_block("run_daily", "2026-10-19T22:30:01Z", "2026-10-20T01:00:00Z"))
    (logs / "verify-cron.log").write_text(
        _run_block("run_weekly_verify", "2026-10-10T02:00:00Z", "2026-10-10T02:40:00Z")
        + _run_block("run_weekly_verify", "2026-10-17T02:00:00Z", "2026-10-17T02:40:00Z",
                     failed=True))
    (logs / "liquid-cron.log").write_text(
        _run_block("run_weekly_liquid", "2026-10-18T02:00:00Z", "2026-10-18T03:00:00Z"))
    (logs / "walkforward-cron.log").write_text(
        _run_block("run_weekly_walkforward", "2026-10-18T06:00:00Z", "2026-10-18T09:00:00Z")
        + "=== run_weekly_walkforward 2026-10-19T06:00:00Z ===\n"
        + "TODO: run_weekly_walkforward failed 2026-10-19T06:00:02Z (stage=enqueue exit 1)\n")
    for path in logs.glob("*cron.log"):
        _age(path, (NOW - timedelta(hours=2)).timestamp())


def _config(**overrides):
    values = {"cap_bytes": 4096, "tail_bytes": 2048, "days": 60} | overrides
    return log_retention.Config(**values)


def test_rotation_keeps_every_monitor_result_and_archives_the_whole_log(tmp_path):
    logs = tmp_path / "logs"
    _cron_logs(logs)
    originals = {path.name: path.read_bytes() for path in logs.glob("*cron.log")}
    inodes = {path.name: path.stat().st_ino for path in logs.glob("*cron.log")}
    before = driver_monitor.driver_statuses(logs_dir=logs, repo_root=tmp_path, now=NOW)

    result = log_retention.run_retention(
        logs, repo_root=tmp_path, now=NOW, config=_config(apply=True), run=_no_evidence)

    assert sorted(item["path"].name for item in result.rotate) == sorted(originals)
    assert result.errors == []
    after = driver_monitor.driver_statuses(logs_dir=logs, repo_root=tmp_path, now=NOW)
    assert after == before
    assert after["nightly"]["status"] == "ok"
    assert after["weekly_verify"]["status"] == "failed"
    assert after["weekly_walkforward"]["status"] == "failed"
    for name, original in originals.items():
        live = logs / name
        assert live.stat().st_ino == inodes[name]  # rewritten in place: cron's >> keeps working
        assert live.stat().st_size < len(original)
        archive = next((logs / "rotated").glob(f"{name.removesuffix('.log')}-*.log.gz"))
        assert gzip.decompress(archive.read_bytes()) == original
        text = live.read_text()
        assert text.startswith("--- log-retention 20261020T100800Z:")
        for line in original.decode().splitlines():
            if line.startswith(("=== ", "TODO: ", "STAGE driver=")):
                assert line in text.splitlines()
        assert text.endswith(original.decode()[-500:])


def test_rotated_log_parses_like_the_original_for_each_driver(tmp_path):
    logs = tmp_path / "logs"
    _cron_logs(logs)
    for path in sorted(logs.glob("*cron.log")):
        before = driver_log.driver_status(path, now=NOW)
        log_retention.rotate(path, now=NOW, tail_bytes=300)
        assert driver_log.driver_status(path, now=NOW) == before, path.name


def test_dry_run_lists_candidates_and_changes_nothing(tmp_path):
    logs = tmp_path / "logs"
    _cron_logs(logs)
    for name in ("run-2026-07-17.log", "run-2026-08-03.log", "sweeps-2026-08-15.log",
                 "farm-recovery-2026-07-24.log", "run-2026-10-19.log", "server.log",
                 "postdeploy-run_weekly_verify.log"):
        (logs / name).write_text("output\n")
        _age(logs / name)
    (logs / "manual-2026-07-01.log").write_text("still written\n")  # old name, fresh mtime
    (logs / "rotated").mkdir()
    (logs / "rotated" / "cron-20260701T100800Z.log.gz").write_bytes(gzip.compress(b"x\n"))
    (logs / "rotated" / "cron-20261001T100800Z.log.gz").write_bytes(gzip.compress(b"x\n"))
    snapshot = {path: (path.stat().st_size, path.stat().st_mtime_ns)
                for path in logs.rglob("*")}
    config = _config(keep=("farm-recovery-*",))

    result = log_retention.run_retention(
        logs, repo_root=tmp_path, now=NOW, config=config, run=_cited("run-2026-08-03.log"))

    assert not result.applied
    assert [item["path"].name for item in result.delete] == [
        "run-2026-07-17.log", "sweeps-2026-08-15.log", "cron-20260701T100800Z.log.gz"]
    assert len(result.rotate) == 4
    reasons = {item["path"].name: item["reason"] for item in result.kept}
    assert reasons == {"farm-recovery-2026-07-24.log": "keep pattern",
                       "manual-2026-07-01.log": "modified within the retention window",
                       "run-2026-08-03.log": "referenced by tracked evidence"}
    assert {path: (path.stat().st_size, path.stat().st_mtime_ns)
            for path in logs.rglob("*")} == snapshot
    text = log_retention.render(result, now=NOW, config=config)
    assert "dry run (nothing changed)" in text
    assert "- rotated/cron-20260701T100800Z.log.gz" in text and "would delete" in text.lower()


def test_unavailable_evidence_scan_expires_nothing(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "run-2026-07-17.log").write_text("output\n")
    _age(logs / "run-2026-07-17.log")

    result = log_retention.run_retention(
        logs, repo_root=tmp_path, now=NOW, config=_config(apply=True),
        run=lambda _args, _timeout: None)

    assert result.delete == [] and (logs / "run-2026-07-17.log").exists()
    assert result.kept[0]["reason"] == "evidence scan unavailable"
    assert result.errors


def test_busy_or_recent_cumulative_logs_are_not_rotated(tmp_path, monkeypatch):
    logs = tmp_path / "logs"
    _cron_logs(logs)
    _age(logs / "liquid-cron.log", (NOW - timedelta(minutes=3)).timestamp())
    monkeypatch.setattr(log_retention, "_lock_held",
                        lambda path: True if path.name == ".nightly.lock" else None)

    result = log_retention.plan(logs, repo_root=tmp_path, now=NOW, config=_config(),
                                run=_no_evidence)

    assert sorted(item["path"].name for item in result.rotate) == [
        "verify-cron.log", "walkforward-cron.log"]
    assert {item["path"].name: item["reason"] for item in result.kept} == {
        "cron.log": "driver running (lock held)",
        "liquid-cron.log": "written in the last 15 minutes"}


def test_rotation_aborts_if_the_log_grows_mid_read(tmp_path, monkeypatch):
    logs = tmp_path / "logs"
    _cron_logs(logs)
    path = logs / "cron.log"
    original = path.read_bytes()
    real_open = log_retention.gzip.open

    def growing(*args, **kwargs):
        with path.open("ab") as writer:
            writer.write(b"late line\n")
        return real_open(*args, **kwargs)

    monkeypatch.setattr(log_retention.gzip, "open", growing)
    with pytest.raises(RuntimeError, match="changed while rotating"):
        log_retention.rotate(path, now=NOW, tail_bytes=2048)
    assert path.read_bytes() == original + b"late line\n"
    assert not list((logs / "rotated").glob("*.gz")) and not list((logs / "rotated").glob("*tmp"))


def test_apply_then_replan_is_empty(tmp_path):
    logs = tmp_path / "logs"
    _cron_logs(logs)
    (logs / "run-2026-07-17.log").write_text("output\n")
    _age(logs / "run-2026-07-17.log")
    later = NOW + timedelta(hours=1)

    done = log_retention.run_retention(logs, repo_root=tmp_path, now=NOW,
                                       config=_config(apply=True, cap_bytes=8192),
                                       run=_no_evidence)
    for path in logs.glob("*cron.log"):
        _age(path, (later - timedelta(hours=1)).timestamp())
    again = log_retention.plan(logs, repo_root=tmp_path, now=later,
                               config=_config(cap_bytes=8192), run=_no_evidence)

    assert done.applied and [item["path"].name for item in done.delete] == [
        "run-2026-07-17.log"]
    assert not (logs / "run-2026-07-17.log").exists()
    assert again.rotate == [] and again.delete == []


def test_referenced_logs_reads_tracked_text_only(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "audit.md").write_text(
        "see `logs/run-2026-08-19.log` and logs/queue-handoff-2026-09-06-v4.log.\n")
    (tmp_path / "untracked.md").write_text("logs/run-2026-08-20.log\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "docs/audit.md"], check=True)

    found = log_retention.referenced_logs(tmp_path)

    assert found == {"run-2026-08-19.log", "queue-handoff-2026-09-06-v4.log"}
    assert log_retention.referenced_logs(tmp_path / "docs" / "missing") is None


def test_load_config_defaults_and_overrides(tmp_path):
    assert log_retention.load_config(tmp_path) == log_retention.Config()
    (tmp_path / "retention.json").write_text("{not json")
    assert log_retention.load_config(tmp_path) == log_retention.Config()
    (tmp_path / "retention.json").write_text(json.dumps(
        {"apply": True, "days": 30, "cap_mb": 2, "tail_kb": 64, "keep": ["wf-*"]}))
    assert log_retention.load_config(tmp_path) == log_retention.Config(
        apply=True, days=30, cap_bytes=2 * 1024 * 1024, tail_bytes=64 * 1024, keep=("wf-*",))
    (tmp_path / "retention.json").write_text(json.dumps({"apply": "yes"}))
    assert log_retention.load_config(tmp_path).apply is False


def test_cli_defaults_to_dry_run(tmp_path, capsys, monkeypatch):
    logs = tmp_path / "logs"
    _cron_logs(logs)
    (logs / "run-2026-07-17.log").write_text("output\n")
    _age(logs / "run-2026-07-17.log")
    monkeypatch.setattr(log_retention, "_run", _no_evidence)
    monkeypatch.setattr(log_retention, "datetime",
                        type("FixedClock", (datetime,), {"now": staticmethod(lambda tz=None: NOW)}))
    before = sorted((p.name, p.stat().st_size) for p in logs.iterdir())

    assert log_retention.main(["--logs-dir", str(logs), "--cap-mb", "0.004"]) == 0

    out = capsys.readouterr().out
    assert "dry run (nothing changed)" in out
    assert "- run-2026-07-17.log" in out and "- cron.log" in out
    assert sorted((p.name, p.stat().st_size) for p in logs.iterdir()) == before


def _digest(tmp_path, now):
    logs = tmp_path / "logs"
    return ops_digest.collect(now=now, run=lambda _a, _t: None,
                              fetch=lambda _u, _t: (200, 1, b"{}"), logs_dir=logs,
                              ops_dir=logs / "ops", db_path=tmp_path / "store.duckdb")


def test_ops_digest_runs_retention_once_a_day_and_moves_the_read_offset(tmp_path, monkeypatch):
    monkeypatch.setattr(ops_digest, "USER_UNIT_DIR", tmp_path / "no-units")
    monkeypatch.setattr(log_retention, "_run", _no_evidence)
    monkeypatch.setattr(log_retention, "DEFAULT_CAP_BYTES", 4096)
    logs = tmp_path / "logs"
    _cron_logs(logs)
    (logs / "run-2026-07-17.log").write_text("output\n")
    _age(logs / "run-2026-07-17.log")
    _digest(tmp_path, NOW - timedelta(hours=2))  # 08:08: before the retention hour
    assert not (logs / "ops" / "retention.md").exists()

    _digest(tmp_path, NOW)  # first collection from 10:00, no host config: dry run
    report = (logs / "ops" / "retention.md").read_text()
    assert "dry run (nothing changed)" in report and "- run-2026-07-17.log" in report
    assert (logs / "run-2026-07-17.log").exists()
    assert not (logs / "rotated").exists()

    (logs / "ops" / "retention.json").write_text(json.dumps(
        {"apply": True, "cap_mb": 0.004, "tail_kb": 2}))
    _digest(tmp_path, NOW + timedelta(hours=1))  # same UTC day: not repeated
    assert (logs / "run-2026-07-17.log").exists()

    _digest(tmp_path, NOW + timedelta(days=1))
    assert not (logs / "run-2026-07-17.log").exists()
    assert "applied" in (logs / "ops" / "retention.md").read_text()
    cron = logs / "cron.log"
    with closing(sqlite3.connect(logs / "ops" / "ops.sqlite")) as db:
        assert db.execute("SELECT inode, offset FROM file_offsets WHERE path=?",
                          (str(cron),)).fetchone() == (cron.stat().st_ino, cron.stat().st_size)
    with cron.open("a") as handle:
        handle.write("=== run_daily 2026-10-21T22:30:01Z ===\n")
    [hour] = _digest(tmp_path, NOW + timedelta(days=1, hours=1))
    with closing(sqlite3.connect(logs / "ops" / "ops.sqlite")) as db:
        lines = db.execute("SELECT lines FROM log_counts WHERE hour=? AND source='file:cron.log'",
                           (hour["hour"],)).fetchone()
    assert lines == (1,)  # only the new line, not the retained tail again
