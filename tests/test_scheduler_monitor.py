"""Tests for scheduler installation monitoring."""

import os
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from server import (
    scheduler_monitor,
)

ROOT = Path(__file__).resolve().parents[1]


def _installed_crontab(repo_root):
    return "\n".join(
        (
            *scheduler_monitor.expected_cron_entries(repo_root).values(),
            *scheduler_monitor.expected_auxiliary_cron_entries(repo_root).values(),
        )
    )


def _recent_utc(hours=1.0):
    moment = datetime.now(UTC) - timedelta(hours=hours)
    return moment.isoformat(timespec="seconds")


def _healthy_unit_and_backup_probes(
    monkeypatch, *, disabled=(), failed=(), state=("ok", None), commit_at=None
):
    host = scheduler_monitor.scheduler_host
    monkeypatch.setattr(
        host,
        "user_unit_enablement",
        lambda units: {unit: "disabled" if unit in disabled else "enabled" for unit in units},
    )
    monkeypatch.setattr(host, "failed_user_units", lambda: tuple(failed))
    status, at = state
    monkeypatch.setattr(
        host,
        "backup_state",
        lambda _path: (status, _recent_utc() if at is None and status == "ok" else at),
    )
    monkeypatch.setattr(host, "last_backup_commit", lambda _repository: commit_at)


def test_scheduler_status_runs_inside_one_command_budget(monkeypatch, tmp_path):
    events = []

    @contextmanager
    def fake_budget():
        events.append("enter")
        try:
            yield
        finally:
            events.append("exit")

    def fake_status(repo_root):
        assert repo_root == tmp_path
        events.append("status")
        return {"status": "ok"}

    monkeypatch.setattr(scheduler_monitor, "command_budget", fake_budget)
    monkeypatch.setattr(scheduler_monitor, "_status", fake_status)

    assert scheduler_monitor.status(repo_root=tmp_path) == {"status": "ok"}
    assert events == ["enter", "status", "exit"]


def _healthy_observation(tmp_path):
    return scheduler_monitor._SchedulerObservation(
        crontab_text=_installed_crontab(tmp_path),
        crontab_error=None,
        service_state="active",
        service_unit="cron",
        service_enabled="enabled",
        timezone_name="Etc/UTC",
        unexecutable_drivers=(),
        unlaunchable_auxiliary_entries=(),
        unsafe_log_targets=(),
        log_directory_writable=True,
        launch_identities=(),
    )


@pytest.mark.parametrize(
    ("field", "changed"),
    [
        ("crontab_text", "changed"),
        ("crontab_error", "crontab-unreadable"),
        ("service_state", "inactive"),
        ("service_unit", "crond"),
        ("service_enabled", "disabled"),
        ("timezone_name", "Asia/Singapore"),
        ("unexecutable_drivers", ("run_daily",)),
        ("unlaunchable_auxiliary_entries", ("friday_postflight",)),
        ("unsafe_log_targets", ("run_daily",)),
        ("log_directory_writable", False),
    ],
)
def test_scheduler_rejects_changed_observation(monkeypatch, tmp_path, field, changed):
    initial = _healthy_observation(tmp_path)
    observations = iter((initial, replace(initial, **{field: changed})))
    monkeypatch.setattr(
        scheduler_monitor, "_observation", lambda repo_root: next(observations)
    )

    assert scheduler_monitor.status(repo_root=tmp_path) == scheduler_monitor.invalid_status(
        "projection-error"
    )


def test_scheduler_detects_executable_replacement_between_observations(
    monkeypatch, tmp_path
):
    engine_dir = tmp_path / "engine"
    engine_dir.mkdir()
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    for name in scheduler_monitor.expected_cron_entries(tmp_path):
        script = engine_dir / f"{name}.sh"
        script.write_text("#!/bin/sh\n")
        script.chmod(0o755)
    postflight_python = tmp_path / ".venv" / "bin" / "python"
    postflight_python.parent.mkdir(parents=True)
    postflight_python.write_text("#!/bin/sh\n")
    postflight_python.chmod(0o755)
    postflight_module = tmp_path / "tools" / "verify_friday_postflight.py"
    postflight_module.parent.mkdir()
    postflight_module.write_text("")
    monkeypatch.setattr(
        scheduler_monitor.scheduler_host,
        "read_user_crontab",
        lambda: (_installed_crontab(tmp_path), None),
    )
    monkeypatch.setattr(
        scheduler_monitor.scheduler_host, "cron_service", lambda: ("active", "cron")
    )
    monkeypatch.setattr(
        scheduler_monitor.scheduler_host, "service_enabled", lambda unit: "enabled"
    )
    monkeypatch.setattr(
        scheduler_monitor.scheduler_host, "system_timezone", lambda: "Etc/UTC"
    )
    original_observation = scheduler_monitor._observation
    observations = 0
    replacement = engine_dir / "replacement.sh"
    replacement.write_text("#!/bin/sh\nexit 1\n")
    replacement.chmod(0o755)

    def observe_then_change(repo_root):
        nonlocal observations
        result = original_observation(repo_root)
        observations += 1
        if observations == 1:
            replacement.replace(engine_dir / "run_daily.sh")
        return result

    monkeypatch.setattr(scheduler_monitor, "_observation", observe_then_change)

    assert scheduler_monitor.status(repo_root=tmp_path) == scheduler_monitor.invalid_status(
        "projection-error"
    )
    assert observations == 2


def test_scheduler_observation_allows_log_append(monkeypatch, tmp_path):
    engine_dir = tmp_path / "engine"
    engine_dir.mkdir()
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    for name in scheduler_monitor.expected_cron_entries(tmp_path):
        script = engine_dir / f"{name}.sh"
        script.write_text("#!/bin/sh\n")
        script.chmod(0o755)
    postflight_python = tmp_path / ".venv" / "bin" / "python"
    postflight_python.parent.mkdir(parents=True)
    postflight_python.write_text("#!/bin/sh\n")
    postflight_python.chmod(0o755)
    postflight_module = tmp_path / "tools" / "verify_friday_postflight.py"
    postflight_module.parent.mkdir()
    postflight_module.write_text("")
    log_path = scheduler_monitor.managed_log_targets(tmp_path)["run_daily"]
    log_path.write_text("start\n")
    monkeypatch.setattr(
        scheduler_monitor.scheduler_host,
        "read_user_crontab",
        lambda: (_installed_crontab(tmp_path), None),
    )
    monkeypatch.setattr(
        scheduler_monitor.scheduler_host, "cron_service", lambda: ("active", "cron")
    )
    monkeypatch.setattr(
        scheduler_monitor.scheduler_host, "service_enabled", lambda unit: "enabled"
    )
    monkeypatch.setattr(
        scheduler_monitor.scheduler_host, "system_timezone", lambda: "Etc/UTC"
    )

    initial = scheduler_monitor._observation(tmp_path)
    with log_path.open("a") as destination:
        destination.write("finish\n")

    assert scheduler_monitor._observation(tmp_path) == initial


def test_scheduler_detects_log_replacement_between_observations(monkeypatch, tmp_path):
    engine_dir = tmp_path / "engine"
    engine_dir.mkdir()
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    for name in scheduler_monitor.expected_cron_entries(tmp_path):
        script = engine_dir / f"{name}.sh"
        script.write_text("#!/bin/sh\n")
        script.chmod(0o755)
    postflight_python = tmp_path / ".venv" / "bin" / "python"
    postflight_python.parent.mkdir(parents=True)
    postflight_python.write_text("#!/bin/sh\n")
    postflight_python.chmod(0o755)
    postflight_module = tmp_path / "tools" / "verify_friday_postflight.py"
    postflight_module.parent.mkdir()
    postflight_module.write_text("")
    log_path = scheduler_monitor.managed_log_targets(tmp_path)["run_daily"]
    log_path.write_text("original\n")
    replacement = logs_dir / "replacement.log"
    replacement.write_text("replacement\n")
    monkeypatch.setattr(
        scheduler_monitor.scheduler_host,
        "read_user_crontab",
        lambda: (_installed_crontab(tmp_path), None),
    )
    monkeypatch.setattr(
        scheduler_monitor.scheduler_host, "cron_service", lambda: ("active", "cron")
    )
    monkeypatch.setattr(
        scheduler_monitor.scheduler_host, "service_enabled", lambda unit: "enabled"
    )
    monkeypatch.setattr(
        scheduler_monitor.scheduler_host, "system_timezone", lambda: "Etc/UTC"
    )
    original_observation = scheduler_monitor._observation
    observations = 0

    def observe_then_replace(repo_root):
        nonlocal observations
        result = original_observation(repo_root)
        observations += 1
        if observations == 1:
            replacement.replace(log_path)
        return result

    monkeypatch.setattr(scheduler_monitor, "_observation", observe_then_replace)

    assert scheduler_monitor.status(repo_root=tmp_path) == scheduler_monitor.invalid_status(
        "projection-error"
    )
    assert observations == 2


def test_scheduler_accepts_each_exact_entry_once(tmp_path):
    expected = scheduler_monitor.expected_cron_entries(tmp_path)
    result = scheduler_monitor.evaluate_scheduler(
        "# unrelated comments are ignored\n" + _installed_crontab(tmp_path),
        "active",
        service_unit="cron",
        repo_root=tmp_path,
    )

    assert result == {
        "status": "ok",
        "cron_service": "active",
        "cron_service_unit": "cron",
        "cron_service_enabled": "enabled",
        "timezone": "UTC",
        "expected_timezone": "UTC",
        "timezone_ok": True,
        "expected_entries": 5,
        "matched_entries": 5,
        "missing_drivers": [],
        "duplicate_drivers": [],
        "auxiliary_expected_entries": 1,
        "auxiliary_matched_entries": 1,
        "missing_auxiliary_entries": [],
        "duplicate_auxiliary_entries": [],
        "unlaunchable_auxiliary_entries": [],
        "unexecutable_drivers": [],
        "unsafe_log_targets": [],
        "log_directory_writable": True,
    }
    assert set(expected) == {
        "run_daily",
        "run_weekly_verify",
        "run_weekend_sweeps",
        "run_weekly_liquid",
        "run_weekly_walkforward",
    }


def test_scheduler_reports_missing_and_duplicate_driver_entries(tmp_path):
    expected = scheduler_monitor.expected_cron_entries(tmp_path)
    lines = [
        *expected.values(),
        *scheduler_monitor.expected_auxiliary_cron_entries(tmp_path).values(),
    ]
    lines.remove(expected["run_weekly_verify"])
    lines.append(expected["run_daily"])

    result = scheduler_monitor.evaluate_scheduler(
        "\n".join(lines), "active", service_unit="cron", repo_root=tmp_path
    )

    assert result["status"] == "misconfigured"
    assert result["matched_entries"] == 3
    assert result["missing_drivers"] == ["run_weekly_verify"]
    assert result["duplicate_drivers"] == ["run_daily"]


@pytest.mark.parametrize(
    "command",
    [
        "{driver} >> {log} 2>&1",
        "{driver}; true",
        "{driver}%mail body",
        "'{driver}' >> {log} 2>&1",
    ],
)
def test_scheduler_rejects_alternate_duplicate_driver_invocation(tmp_path, command):
    expected = scheduler_monitor.expected_cron_entries(tmp_path)
    alternate = "0 23 * * 1-5 " + command.format(
        driver=tmp_path / "engine" / "run_daily.sh",
        log=tmp_path / "logs" / "cron.log",
    )

    result = scheduler_monitor.evaluate_scheduler(
        "\n".join(
            (
                *expected.values(),
                *scheduler_monitor.expected_auxiliary_cron_entries(tmp_path).values(),
                alternate,
            )
        ),
        "active",
        repo_root=tmp_path,
    )

    assert result["status"] == "misconfigured"
    assert result["matched_entries"] == 5
    assert result["missing_drivers"] == []
    assert result["duplicate_drivers"] == ["run_daily"]


def test_scheduler_rejects_missing_or_duplicate_auxiliary_postflight(tmp_path):
    production = list(scheduler_monitor.expected_cron_entries(tmp_path).values())
    postflight = next(
        iter(scheduler_monitor.expected_auxiliary_cron_entries(tmp_path).values())
    )

    missing = scheduler_monitor.evaluate_scheduler(
        "\n".join(production), "active", repo_root=tmp_path
    )
    duplicate = scheduler_monitor.evaluate_scheduler(
        "\n".join((*production, postflight, postflight)), "active", repo_root=tmp_path
    )

    assert missing["status"] == "misconfigured"
    assert missing["matched_entries"] == 5
    assert missing["auxiliary_matched_entries"] == 0
    assert missing["missing_auxiliary_entries"] == ["friday_postflight"]
    assert duplicate["status"] == "misconfigured"
    assert duplicate["auxiliary_matched_entries"] == 0
    assert duplicate["duplicate_auxiliary_entries"] == ["friday_postflight"]


@pytest.mark.parametrize(
    "alternate",
    [
        ".venv/bin/python tools/verify_friday_postflight.py --publish",
        "/usr/bin/python /repo/tools/verify_friday_postflight.py --publish",
        ".venv/bin/python -m tools.verify_friday_postflight; true",
        ".venv/bin/python -m 'tools.verify_friday_postflight' --publish",
    ],
)
def test_scheduler_detects_alternate_postflight_invocation_as_duplicate(tmp_path, alternate):
    expected = _installed_crontab(tmp_path)

    result = scheduler_monitor.evaluate_scheduler(
        f"{expected}\n0 7 * * 6 {alternate}", "active", repo_root=tmp_path
    )

    assert result["status"] == "misconfigured"
    assert result["duplicate_auxiliary_entries"] == ["friday_postflight"]


def test_scheduler_does_not_count_malformed_or_partial_managed_names(tmp_path):
    expected = _installed_crontab(tmp_path)
    unrelated = (
        f"0 7 * * 6 echo '{tmp_path}/engine/run_daily.sh",
        f"0 8 * * 6 {tmp_path}/engine/run_daily.sh.backup",
        "0 9 * * 6 .venv/bin/python -m tools.verify_friday_postflight_backup",
        f"0 10 * * 6 echo ok # {tmp_path}/engine/run_daily.sh",
        "0 11 * * 6 echo ok # tools.verify_friday_postflight",
        rf"0 12 * * 6 {tmp_path}/engine/run_daily.sh\%literal",
    )

    result = scheduler_monitor.evaluate_scheduler(
        "\n".join((expected, *unrelated)), "active", repo_root=tmp_path
    )

    assert result["status"] == "ok"
    assert result["duplicate_drivers"] == []
    assert result["duplicate_auxiliary_entries"] == []


def test_scheduler_counts_managed_name_inside_quoted_shell_word(tmp_path):
    expected = _installed_crontab(tmp_path)
    extra = f'0 8 * * 6 echo "prefix {tmp_path}/engine/run_daily.sh suffix"'

    result = scheduler_monitor.evaluate_scheduler(
        f"{expected}\n{extra}", "active", repo_root=tmp_path
    )

    assert result["status"] == "ok"
    assert result["duplicate_drivers"] == []


@pytest.mark.parametrize("service_state", ["inactive", "failed", "deactivating"])
def test_scheduler_reports_inactive_daemon(tmp_path, service_state):
    crontab = _installed_crontab(tmp_path)

    result = scheduler_monitor.evaluate_scheduler(crontab, service_state, repo_root=tmp_path)

    assert result["status"] == "inactive"
    assert result["cron_service"] == service_state
    assert result["matched_entries"] == 5


def test_scheduler_reports_unknown_daemon(tmp_path):
    crontab = _installed_crontab(tmp_path)

    unknown = scheduler_monitor.evaluate_scheduler(crontab, "unknown", repo_root=tmp_path)

    assert unknown["status"] == "unknown"


@pytest.mark.parametrize("service_enabled", ["disabled", "masked"])
def test_scheduler_rejects_daemon_not_enabled_for_boot(tmp_path, service_enabled):
    crontab = _installed_crontab(tmp_path)

    result = scheduler_monitor.evaluate_scheduler(
        crontab, "active", service_enabled=service_enabled, repo_root=tmp_path
    )

    assert result["status"] == "misconfigured"
    assert result["cron_service_enabled"] == service_enabled


def test_scheduler_reports_unknown_enablement(tmp_path):
    crontab = _installed_crontab(tmp_path)

    result = scheduler_monitor.evaluate_scheduler(
        crontab, "active", service_enabled="unknown", repo_root=tmp_path
    )

    assert result["status"] == "unknown"


@pytest.mark.parametrize("timezone_name", ["America/New_York", "unknown"])
def test_scheduler_rejects_non_utc_or_unknown_timezone(tmp_path, timezone_name):
    crontab = _installed_crontab(tmp_path)

    result = scheduler_monitor.evaluate_scheduler(
        crontab, "active", timezone_name=timezone_name, repo_root=tmp_path
    )

    assert result["status"] == "misconfigured"
    assert result["timezone"] == timezone_name
    assert result["expected_timezone"] == "UTC"
    assert result["timezone_ok"] is False


@pytest.mark.parametrize(
    ("unexecutable", "unlaunchable_auxiliary", "unsafe_log", "logs_writable"),
    [
        ("run_daily", None, None, True),
        (None, "friday_postflight", None, True),
        (None, None, "run_weekly_verify", True),
        (None, None, None, False),
    ],
)
def test_scheduler_rejects_unlaunchable_driver_or_log_directory(
    tmp_path, unexecutable, unlaunchable_auxiliary, unsafe_log, logs_writable
):
    crontab = _installed_crontab(tmp_path)

    result = scheduler_monitor.evaluate_scheduler(
        crontab,
        "active",
        unexecutable_drivers=(unexecutable,) if unexecutable else (),
        unlaunchable_auxiliary_entries=(
            (unlaunchable_auxiliary,) if unlaunchable_auxiliary else ()
        ),
        unsafe_log_targets=(unsafe_log,) if unsafe_log else (),
        log_directory_writable=logs_writable,
        repo_root=tmp_path,
    )

    assert result["status"] == "misconfigured"
    assert result["unexecutable_drivers"] == ([unexecutable] if unexecutable else [])
    assert result["unlaunchable_auxiliary_entries"] == (
        [unlaunchable_auxiliary] if unlaunchable_auxiliary else []
    )
    assert result["unsafe_log_targets"] == ([unsafe_log] if unsafe_log else [])
    assert result["log_directory_writable"] is logs_writable


def test_managed_log_targets_allow_absent_or_regular_files(tmp_path):
    targets = scheduler_monitor.managed_log_targets(tmp_path)

    assert set(targets) == {
        *scheduler_monitor.expected_cron_entries(tmp_path),
        "friday_postflight",
    }
    assert scheduler_monitor.unsafe_log_targets(tmp_path) == ()

    (tmp_path / "logs").mkdir()
    for target in targets.values():
        target.write_text("safe\n")

    assert scheduler_monitor.unsafe_log_targets(tmp_path) == ()


@pytest.mark.parametrize(
    ("target_name", "kind"),
    [
        ("run_daily", "symlink"),
        ("run_weekly_verify", "dangling-symlink"),
        ("run_weekend_sweeps", "directory"),
        ("friday_postflight", "fifo"),
    ],
)
def test_managed_log_targets_reject_non_regular_files(tmp_path, target_name, kind):
    logs = tmp_path / "logs"
    logs.mkdir()
    target = scheduler_monitor.managed_log_targets(tmp_path)[target_name]
    if kind == "symlink":
        external = tmp_path / "external.log"
        external.write_text("external\n")
        target.symlink_to(external)
    elif kind == "dangling-symlink":
        target.symlink_to(tmp_path / "missing.log")
    elif kind == "directory":
        target.mkdir()
    else:
        os.mkfifo(target)

    assert scheduler_monitor.unsafe_log_targets(tmp_path) == (target_name,)


def test_managed_log_targets_reject_regular_file_replaced_during_probe(
    tmp_path, monkeypatch
):
    logs = tmp_path / "logs"
    logs.mkdir()
    target_name = "run_daily"
    target = scheduler_monitor.managed_log_targets(tmp_path)[target_name]
    target.write_text("safe\n")
    replacement = logs / "replacement.log"
    replacement.write_text("safe\n")
    original_stat = scheduler_monitor.os.stat
    inspected = False

    def stat_then_replace(path, *args, **kwargs):
        nonlocal inspected
        result = original_stat(path, *args, **kwargs)
        if path == target.name and kwargs.get("dir_fd") is not None and not inspected:
            inspected = True
            replacement.replace(target)
        return result

    monkeypatch.setattr(scheduler_monitor.os, "stat", stat_then_replace)

    assert scheduler_monitor.unsafe_log_targets(tmp_path) == (target_name,)
    assert inspected is True


def test_managed_log_targets_reject_file_removed_during_probe(tmp_path, monkeypatch):
    logs = tmp_path / "logs"
    logs.mkdir()
    target_name = "run_daily"
    target = scheduler_monitor.managed_log_targets(tmp_path)[target_name]
    target.write_text("safe\n")
    original_stat = scheduler_monitor.os.stat
    inspected = False

    def stat_then_remove(path, *args, **kwargs):
        nonlocal inspected
        result = original_stat(path, *args, **kwargs)
        if path == target.name and kwargs.get("dir_fd") is not None and not inspected:
            inspected = True
            target.unlink()
        return result

    monkeypatch.setattr(scheduler_monitor.os, "stat", stat_then_remove)

    assert scheduler_monitor.unsafe_log_targets(tmp_path) == (target_name,)
    assert inspected is True


def test_managed_log_targets_allow_file_appended_during_probe(tmp_path, monkeypatch):
    logs = tmp_path / "logs"
    logs.mkdir()
    target = scheduler_monitor.managed_log_targets(tmp_path)["run_daily"]
    target.write_text("start\n")
    original_stat = scheduler_monitor.os.stat
    inspected = False

    def stat_then_append(path, *args, **kwargs):
        nonlocal inspected
        result = original_stat(path, *args, **kwargs)
        if path == target.name and kwargs.get("dir_fd") is not None and not inspected:
            inspected = True
            with target.open("a") as destination:
                destination.write("finish\n")
        return result

    monkeypatch.setattr(scheduler_monitor.os, "stat", stat_then_append)

    assert scheduler_monitor.unsafe_log_targets(tmp_path) == ()
    assert inspected is True


def test_managed_log_targets_reject_file_appearing_during_probe(tmp_path, monkeypatch):
    logs = tmp_path / "logs"
    logs.mkdir()
    target_name = "run_daily"
    target = scheduler_monitor.managed_log_targets(tmp_path)[target_name]
    original_open = scheduler_monitor.os.open
    inspected = False

    def open_then_create(path, flags, *args, **kwargs):
        nonlocal inspected
        try:
            return original_open(path, flags, *args, **kwargs)
        except FileNotFoundError:
            if path == target.name and not inspected:
                inspected = True
                target.write_text("appeared\n")
            raise

    monkeypatch.setattr(scheduler_monitor.os, "open", open_then_create)

    assert scheduler_monitor.unsafe_log_targets(tmp_path) == (target_name,)
    assert inspected is True


def test_scheduler_status_fails_when_managed_log_target_is_unsafe(tmp_path, monkeypatch):
    monkeypatch.setattr(
        scheduler_monitor.scheduler_host,
        "read_user_crontab",
        lambda: (_installed_crontab(tmp_path), None),
    )
    monkeypatch.setattr(
        scheduler_monitor.scheduler_host, "cron_service", lambda: ("active", "cron")
    )
    monkeypatch.setattr(
        scheduler_monitor.scheduler_host, "service_enabled", lambda _unit: "enabled"
    )
    monkeypatch.setattr(
        scheduler_monitor.scheduler_host, "system_timezone", lambda: "UTC"
    )
    monkeypatch.setattr(
        scheduler_monitor,
        "_launch_prerequisites",
        lambda _root: ((), (), ("friday_postflight",), True, ()),
    )

    result = scheduler_monitor.status(repo_root=tmp_path)

    assert result["status"] == "misconfigured"
    assert result["unsafe_log_targets"] == ["friday_postflight"]


def test_scheduler_status_checks_auxiliary_launch_prerequisites(tmp_path, monkeypatch):
    engine_dir = tmp_path / "engine"
    engine_dir.mkdir()
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    for name in scheduler_monitor.expected_cron_entries(tmp_path):
        script = engine_dir / f"{name}.sh"
        script.write_text("#!/bin/sh\n")
        script.chmod(0o755)
    monkeypatch.setattr(
        scheduler_monitor.scheduler_host,
        "read_user_crontab",
        lambda: (_installed_crontab(tmp_path), None),
    )
    monkeypatch.setattr(
        scheduler_monitor.scheduler_host, "cron_service", lambda: ("active", "cron")
    )
    monkeypatch.setattr(
        scheduler_monitor.scheduler_host, "service_enabled", lambda unit: "enabled"
    )
    monkeypatch.setattr(
        scheduler_monitor.scheduler_host, "system_timezone", lambda: "Etc/UTC"
    )

    result = scheduler_monitor.status(repo_root=tmp_path)

    assert result["status"] == "misconfigured"
    assert result["matched_entries"] == 5
    assert result["auxiliary_matched_entries"] == 1
    assert result["unlaunchable_auxiliary_entries"] == ["friday_postflight"]


def test_scheduler_rejects_directories_at_expected_executable_paths(tmp_path, monkeypatch):
    engine_dir = tmp_path / "engine"
    engine_dir.mkdir()
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    for name in scheduler_monitor.expected_cron_entries(tmp_path):
        path = engine_dir / f"{name}.sh"
        if name == "run_daily":
            path.mkdir()
        else:
            path.write_text("#!/bin/sh\n")
            path.chmod(0o755)
    postflight_python = tmp_path / ".venv" / "bin" / "python"
    postflight_python.mkdir(parents=True)
    postflight_module = tmp_path / "tools" / "verify_friday_postflight.py"
    postflight_module.parent.mkdir()
    postflight_module.mkdir()
    monkeypatch.setattr(
        scheduler_monitor.scheduler_host,
        "read_user_crontab",
        lambda: (_installed_crontab(tmp_path), None),
    )
    monkeypatch.setattr(
        scheduler_monitor.scheduler_host, "cron_service", lambda: ("active", "cron")
    )
    monkeypatch.setattr(
        scheduler_monitor.scheduler_host, "service_enabled", lambda unit: "enabled"
    )
    monkeypatch.setattr(
        scheduler_monitor.scheduler_host, "system_timezone", lambda: "Etc/UTC"
    )

    result = scheduler_monitor.status(repo_root=tmp_path)

    assert result["status"] == "misconfigured"
    assert result["unexecutable_drivers"] == ["run_daily"]
    assert result["unlaunchable_auxiliary_entries"] == ["friday_postflight"]


def test_scheduler_rejects_symlinked_launch_sources(tmp_path, monkeypatch):
    engine_dir = tmp_path / "engine"
    engine_dir.mkdir()
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    for name in scheduler_monitor.expected_cron_entries(tmp_path):
        script = engine_dir / f"{name}.sh"
        script.write_text("#!/bin/sh\n")
        script.chmod(0o755)
    linked_driver = tmp_path / "linked-driver.sh"
    driver = engine_dir / "run_daily.sh"
    driver.replace(linked_driver)
    driver.symlink_to(linked_driver)
    postflight_python = tmp_path / ".venv" / "bin" / "python"
    postflight_python.parent.mkdir(parents=True)
    postflight_python.write_text("#!/bin/sh\n")
    postflight_python.chmod(0o755)
    external_tools = tmp_path / "external-tools"
    external_tools.mkdir()
    (external_tools / "verify_friday_postflight.py").write_text("")
    (tmp_path / "tools").symlink_to(external_tools, target_is_directory=True)
    monkeypatch.setattr(
        scheduler_monitor.scheduler_host,
        "read_user_crontab",
        lambda: (_installed_crontab(tmp_path), None),
    )
    monkeypatch.setattr(
        scheduler_monitor.scheduler_host, "cron_service", lambda: ("active", "cron")
    )
    monkeypatch.setattr(
        scheduler_monitor.scheduler_host, "service_enabled", lambda unit: "enabled"
    )
    monkeypatch.setattr(
        scheduler_monitor.scheduler_host, "system_timezone", lambda: "Etc/UTC"
    )

    result = scheduler_monitor.status(repo_root=tmp_path)

    assert result["status"] == "misconfigured"
    assert result["unexecutable_drivers"] == ["run_daily"]
    assert result["unlaunchable_auxiliary_entries"] == ["friday_postflight"]


def test_scheduler_rejects_launch_source_replaced_during_probe(tmp_path, monkeypatch):
    engine_dir = tmp_path / "engine"
    engine_dir.mkdir()
    driver = engine_dir / "run_daily.sh"
    driver.write_text("#!/bin/sh\n")
    driver.chmod(0o755)
    replacement = engine_dir / "replacement.sh"
    replacement.write_text("#!/bin/sh\n")
    replacement.chmod(0o755)
    original_stat = scheduler_monitor.os.stat
    inspected = False

    def stat_then_replace(path, *args, **kwargs):
        nonlocal inspected
        result = original_stat(path, *args, **kwargs)
        if path == driver.name and kwargs.get("dir_fd") is not None and not inspected:
            inspected = True
            replacement.replace(driver)
        return result

    monkeypatch.setattr(scheduler_monitor.os, "stat", stat_then_replace)

    assert not scheduler_monitor._is_in_tree_accessible_file(
        tmp_path, Path("engine/run_daily.sh"), os.X_OK
    )
    assert inspected is True


def test_scheduler_rejects_launch_parent_replaced_during_probe(tmp_path, monkeypatch):
    engine_dir = tmp_path / "engine"
    engine_dir.mkdir()
    driver = engine_dir / "run_daily.sh"
    driver.write_text("#!/bin/sh\n")
    driver.chmod(0o755)
    original_open = scheduler_monitor.os.open
    root_opens = 0

    def open_then_replace(path, flags, *args, **kwargs):
        nonlocal root_opens
        descriptor = original_open(path, flags, *args, **kwargs)
        if path == tmp_path:
            root_opens += 1
            if root_opens == 2:
                engine_dir.rename(tmp_path / "original-engine")
                engine_dir.mkdir()
                replacement = engine_dir / "run_daily.sh"
                replacement.write_text("#!/bin/sh\n")
                replacement.chmod(0o755)
        return descriptor

    monkeypatch.setattr(scheduler_monitor.os, "open", open_then_replace)

    assert not scheduler_monitor._is_in_tree_accessible_file(
        tmp_path, Path("engine/run_daily.sh"), os.X_OK
    )
    assert root_opens == 2


def test_scheduler_rejects_log_directory_replaced_during_probe(tmp_path, monkeypatch):
    logs = tmp_path / "logs"
    logs.mkdir()
    original_stat = scheduler_monitor.os.stat
    inspected = False

    def stat_then_replace(path, *args, **kwargs):
        nonlocal inspected
        result = original_stat(path, *args, **kwargs)
        if path == logs.name and kwargs.get("dir_fd") is not None and not inspected:
            inspected = True
            logs.rename(tmp_path / "original-logs")
            logs.mkdir()
        return result

    monkeypatch.setattr(scheduler_monitor.os, "stat", stat_then_replace)

    assert not scheduler_monitor._is_in_tree_writable_directory(tmp_path, Path("logs"))
    assert inspected is True


def test_scheduler_rejects_symlinked_log_directory(tmp_path, monkeypatch):
    engine_dir = tmp_path / "engine"
    engine_dir.mkdir()
    external_logs = tmp_path / "external-logs"
    external_logs.mkdir()
    (tmp_path / "logs").symlink_to(external_logs, target_is_directory=True)
    for name in scheduler_monitor.expected_cron_entries(tmp_path):
        script = engine_dir / f"{name}.sh"
        script.write_text("#!/bin/sh\n")
        script.chmod(0o755)
    postflight_python = tmp_path / ".venv" / "bin" / "python"
    postflight_python.parent.mkdir(parents=True)
    postflight_python.write_text("#!/bin/sh\n")
    postflight_python.chmod(0o755)
    postflight_module = tmp_path / "tools" / "verify_friday_postflight.py"
    postflight_module.parent.mkdir()
    postflight_module.write_text("")
    monkeypatch.setattr(
        scheduler_monitor.scheduler_host,
        "read_user_crontab",
        lambda: (_installed_crontab(tmp_path), None),
    )
    monkeypatch.setattr(
        scheduler_monitor.scheduler_host, "cron_service", lambda: ("active", "cron")
    )
    monkeypatch.setattr(
        scheduler_monitor.scheduler_host, "service_enabled", lambda unit: "enabled"
    )
    monkeypatch.setattr(
        scheduler_monitor.scheduler_host, "system_timezone", lambda: "UTC"
    )

    result = scheduler_monitor.status(repo_root=tmp_path)

    assert result["status"] == "misconfigured"
    assert result["log_directory_writable"] is False


def test_scheduler_status_fails_closed_when_crontab_is_unreadable(tmp_path, monkeypatch):
    engine_dir = tmp_path / "engine"
    engine_dir.mkdir()
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    for name in scheduler_monitor.expected_cron_entries(tmp_path):
        script = engine_dir / f"{name}.sh"
        script.write_text("#!/bin/sh\n")
        script.chmod(0o755)
    postflight_python = tmp_path / ".venv" / "bin" / "python"
    postflight_python.parent.mkdir(parents=True)
    postflight_python.write_text("#!/bin/sh\n")
    postflight_python.chmod(0o755)
    postflight_module = tmp_path / "tools" / "verify_friday_postflight.py"
    postflight_module.parent.mkdir()
    postflight_module.write_text("")
    monkeypatch.setattr(
        scheduler_monitor.scheduler_host,
        "read_user_crontab",
        lambda: (None, "crontab-unreadable"),
    )
    _healthy_unit_and_backup_probes(monkeypatch)
    monkeypatch.setattr(
        scheduler_monitor.scheduler_host, "cron_service", lambda: ("active", "cron")
    )
    monkeypatch.setattr(
        scheduler_monitor.scheduler_host, "service_enabled", lambda unit: "enabled"
    )
    monkeypatch.setattr(
        scheduler_monitor.scheduler_host, "system_timezone", lambda: "Etc/UTC"
    )

    result = scheduler_monitor.status(repo_root=tmp_path)

    assert result == {
        "status": "invalid",
        "reason": "crontab-unreadable",
        "cron_service": "active",
        "cron_service_unit": "cron",
        "cron_service_enabled": "enabled",
        "timezone": "Etc/UTC",
        "expected_timezone": "UTC",
        "timezone_ok": True,
        "expected_entries": 5,
        "matched_entries": 0,
        "missing_drivers": [],
        "duplicate_drivers": [],
        "auxiliary_expected_entries": 1,
        "auxiliary_matched_entries": 0,
        "missing_auxiliary_entries": [],
        "duplicate_auxiliary_entries": [],
        "unlaunchable_auxiliary_entries": [],
        "unexecutable_drivers": [],
        "unsafe_log_targets": [],
        "log_directory_writable": True,
        "user_units": {
            "status": "ok",
            "autostart_expected": len(scheduler_monitor.AUTOSTART_UNITS),
            "autostart_not_enabled": [],
            "failed": [],
        },
        "backup": {
            "status": "current",
            "state": "ok",
            "last_success_at": result["backup"]["last_success_at"],
            "age_hours": result["backup"]["age_hours"],
            "stale_after_hours": 26,
        },
    }


def test_invalid_scheduler_status_has_complete_safe_defaults():
    assert scheduler_monitor.invalid_status("projection-error") == {
        "status": "invalid",
        "reason": "projection-error",
        "cron_service": "unknown",
        "cron_service_unit": None,
        "cron_service_enabled": "unknown",
        "timezone": "unknown",
        "expected_timezone": "UTC",
        "timezone_ok": False,
        "expected_entries": 5,
        "matched_entries": 0,
        "missing_drivers": [],
        "duplicate_drivers": [],
        "auxiliary_expected_entries": 1,
        "auxiliary_matched_entries": 0,
        "missing_auxiliary_entries": [],
        "duplicate_auxiliary_entries": [],
        "unlaunchable_auxiliary_entries": [],
        "unexecutable_drivers": [],
        "unsafe_log_targets": [],
        "log_directory_writable": False,
        "user_units": {
            "status": "unknown",
            "autostart_expected": len(scheduler_monitor.AUTOSTART_UNITS),
            "autostart_not_enabled": [],
            "failed": [],
        },
        "backup": {
            "status": "unknown",
            "state": "unknown",
            "last_success_at": None,
            "age_hours": None,
            "stale_after_hours": 26,
        },
    }


def test_invalid_scheduler_status_rejects_undocumented_reason():
    with pytest.raises(ValueError, match="unknown scheduler invalid reason"):
        scheduler_monitor.invalid_status("invented")


def _healthy_cron(monkeypatch, tmp_path):
    host = scheduler_monitor.scheduler_host
    monkeypatch.setattr(host, "read_user_crontab", lambda: (_installed_crontab(tmp_path), None))
    monkeypatch.setattr(host, "cron_service", lambda: ("active", "cron"))
    monkeypatch.setattr(host, "service_enabled", lambda _unit: "enabled")
    monkeypatch.setattr(host, "system_timezone", lambda: "Etc/UTC")
    monkeypatch.setattr(
        scheduler_monitor, "_launch_prerequisites", lambda _root: ((), (), (), True, ())
    )


def test_scheduler_is_ok_only_with_enabled_units_and_a_current_backup(monkeypatch, tmp_path):
    _healthy_cron(monkeypatch, tmp_path)
    _healthy_unit_and_backup_probes(monkeypatch)

    result = scheduler_monitor.status(repo_root=tmp_path)

    assert result["status"] == "ok"
    assert result["user_units"]["status"] == "ok"
    assert result["backup"]["status"] == "current"


def test_scheduler_degrades_on_failed_units_and_disabled_autostart(monkeypatch, tmp_path):
    _healthy_cron(monkeypatch, tmp_path)
    _healthy_unit_and_backup_probes(
        monkeypatch,
        disabled=("trading-engine-p15-scoring.timer",),
        failed=(
            "trading-engine-p15-preopen.service",
            "massive-options-daily.service",
            "p22-rb-massive-options-daily.service",
        ),
    )

    result = scheduler_monitor.status(repo_root=tmp_path)

    assert result["status"] == "degraded"
    assert result["matched_entries"] == result["expected_entries"]
    assert result["user_units"] == {
        "status": "degraded",
        "autostart_expected": len(scheduler_monitor.AUTOSTART_UNITS),
        "autostart_not_enabled": ["trading-engine-p15-scoring.timer"],
        "failed": [
            "massive-options-daily.service",
            "p22-rb-massive-options-daily.service",
            "trading-engine-p15-preopen.service",
        ],
    }


def test_scheduler_checks_only_autostart_units_for_enablement(monkeypatch, tmp_path):
    _healthy_cron(monkeypatch, tmp_path)
    _healthy_unit_and_backup_probes(monkeypatch)
    asked = []
    monkeypatch.setattr(
        scheduler_monitor.scheduler_host,
        "user_unit_enablement",
        lambda units: asked.append(units) or {unit: "enabled" for unit in units},
    )

    assert scheduler_monitor.status(repo_root=tmp_path)["status"] == "ok"
    assert asked and set(asked[0]) == scheduler_monitor.AUTOSTART_UNITS
    assert not scheduler_monitor.HELD_UNITS & set(asked[0])


def test_scheduler_degrades_when_backup_only_retried(monkeypatch, tmp_path):
    # 2026-10-19: both timer slots exited 75 (state retry, unit "Succeeded"); the last
    # backup commit was a manual run more than a day earlier.
    _healthy_cron(monkeypatch, tmp_path)
    _healthy_unit_and_backup_probes(
        monkeypatch,
        state=("retry", _recent_utc(1)),
        commit_at=_recent_utc(38),
    )

    result = scheduler_monitor.status(repo_root=tmp_path)

    assert result["status"] == "degraded"
    assert result["backup"]["status"] == "stale"
    assert result["backup"]["state"] == "retry"
    assert result["backup"]["age_hours"] == pytest.approx(38, abs=0.2)


def test_scheduler_degrades_when_unit_or_backup_probes_are_unreadable(monkeypatch, tmp_path):
    _healthy_cron(monkeypatch, tmp_path)
    _healthy_unit_and_backup_probes(monkeypatch, state=("absent", None))
    monkeypatch.setattr(scheduler_monitor.scheduler_host, "failed_user_units", lambda: None)

    result = scheduler_monitor.status(repo_root=tmp_path)

    assert result["status"] == "degraded"
    assert result["user_units"]["status"] == "unknown"
    assert result["backup"]["status"] == "unknown"
    assert result["backup"]["state"] == "absent"


def test_cron_problems_keep_precedence_over_degraded(monkeypatch, tmp_path):
    _healthy_cron(monkeypatch, tmp_path)
    _healthy_unit_and_backup_probes(monkeypatch, failed=("x.service",))
    monkeypatch.setattr(scheduler_monitor.scheduler_host, "system_timezone", lambda: "Asia/Tokyo")

    assert scheduler_monitor.status(repo_root=tmp_path)["status"] == "misconfigured"


@pytest.mark.parametrize(
    ("state", "state_hours", "commit_hours", "expected", "age"),
    [
        ("ok", 2, 30, "current", 2),
        ("ok", None, 25.9, "current", 25.9),
        ("retry", 1, 26.2, "stale", 26.2),
        ("failed", 1, None, "unknown", None),
        ("ok", 27, None, "stale", 27),
    ],
)
def test_backup_age_counts_only_clean_runs_and_backup_commits(
    state, state_hours, commit_hours, expected, age
):
    now = datetime(2026, 10, 20, 12, tzinfo=UTC)

    def at(hours):
        return None if hours is None else (now - timedelta(hours=hours)).isoformat()

    result = scheduler_monitor.backup_status(
        state, at(state_hours), at(commit_hours), now=now
    )

    assert result["status"] == expected
    assert result["age_hours"] == age
    assert result["state"] == state


class _Completed:
    def __init__(self, stdout, returncode=0, stderr=""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


def test_user_unit_enablement_parses_one_show_query(monkeypatch):
    calls = []

    def run(args):
        calls.append(args)
        return _Completed(
            "Id=a.timer\nUnitFileState=enabled\n\n"
            "Id=b.timer\nUnitFileState=disabled\n\n"
            "Id=c.timer\nUnitFileState=\n"
        )

    monkeypatch.setattr(scheduler_monitor.scheduler_host, "run_bounded", run)

    states = scheduler_monitor.scheduler_host.user_unit_enablement(
        ("a.timer", "b.timer", "c.timer")
    )

    assert states == {"a.timer": "enabled", "b.timer": "disabled", "c.timer": "not-found"}
    assert len(calls) == 1 and calls[0][:2] == ["systemctl", "--user"]


@pytest.mark.parametrize(
    "stdout",
    [
        "Id=a.timer\nUnitFileState=enabled\n",
        "Id=a.timer\nUnitFileState=enabled\n\nId=other.timer\nUnitFileState=enabled\n",
        "Id=a.timer\nUnitFileState=enabled\nExtra=1\n\nId=b.timer\nUnitFileState=enabled\n",
    ],
)
def test_user_unit_enablement_fails_closed_on_unexpected_output(monkeypatch, stdout):
    monkeypatch.setattr(
        scheduler_monitor.scheduler_host, "run_bounded", lambda _args: _Completed(stdout)
    )

    assert scheduler_monitor.scheduler_host.user_unit_enablement(("a.timer", "b.timer")) is None


def test_failed_user_units_reads_plain_list(monkeypatch):
    stdout = (
        "massive-options-daily.service        loaded    failed failed Capture\n"
        "p22-rb-massive-options-daily.service not-found failed failed p22-rb\n"
    )
    monkeypatch.setattr(
        scheduler_monitor.scheduler_host, "run_bounded", lambda _args: _Completed(stdout)
    )

    assert scheduler_monitor.scheduler_host.failed_user_units() == (
        "massive-options-daily.service",
        "p22-rb-massive-options-daily.service",
    )


def test_failed_user_units_fails_closed(monkeypatch):
    host = scheduler_monitor.scheduler_host
    monkeypatch.setattr(host, "run_bounded", lambda _args: None)
    assert host.failed_user_units() is None
    monkeypatch.setattr(host, "run_bounded", lambda _args: _Completed("● bad unit\n"))
    assert host.failed_user_units() is None


def test_backup_state_reads_the_backup_script_record(tmp_path):
    host = scheduler_monitor.scheduler_host
    path = tmp_path / "trading-data-backup.json"
    assert host.backup_state(path) == ("absent", None)
    path.write_text(
        '{"at": "2026-10-19T10:33:46+00:00", "status": "retry", "stamp": "x", '
        '"reason": "active process holds .queue-drain.lock"}\n'
    )
    assert host.backup_state(path) == ("retry", "2026-10-19T10:33:46+00:00")
    path.write_text('{"status": "invented"}')
    assert host.backup_state(path) == ("unknown", None)
    path.write_text("not json")
    assert host.backup_state(path) == ("unknown", None)


def test_last_backup_commit_normalizes_git_time(monkeypatch, tmp_path):
    host = scheduler_monitor.scheduler_host
    calls = []

    def run(args):
        calls.append(args)
        return _Completed("2026-10-18T21:20:08+08:00\n")

    monkeypatch.setattr(host, "run_bounded", run)

    assert host.last_backup_commit(tmp_path) == "2026-10-18T13:20:08+00:00"
    assert calls[0][:4] == ["git", "-C", str(tmp_path), "log"]
    monkeypatch.setattr(host, "run_bounded", lambda _args: _Completed("", returncode=128))
    assert host.last_backup_commit(tmp_path) is None


def _registry_repo(tmp_path: Path) -> Path:
    (tmp_path / "ops").mkdir()
    (tmp_path / "ops/jobs.toml").write_text((ROOT / "ops/jobs.toml").read_text())
    server = tmp_path / "server"
    server.mkdir()
    for path in (ROOT / "server").glob("*.service"):
        if path.name in scheduler_monitor.job_contract.render_units(
            scheduler_monitor.job_contract.load_registry(ROOT)
        ):
            (server / path.name).write_text(path.read_text())
    for path in (ROOT / "server").glob("*.timer"):
        (server / path.name).write_text(path.read_text())
    return tmp_path


def test_job_registry_audits_legacy_sources_without_becoming_scheduler():
    audit = scheduler_monitor.registry_audit(ROOT)
    assert audit == {
        "status": "ok",
        "mode": "audit-only",
        "jobs": 21,
        "scheduled_jobs": 20,
        "registered_timers": 14,
        "registered_cron": 6,
        "errors": [],
    }


def test_job_registry_reports_an_undocumented_source_timer(tmp_path):
    repo = _registry_repo(tmp_path)
    (repo / "server/rogue.timer").write_text("[Timer]\nOnCalendar=*-*-* 00:00:00 UTC\n")

    audit = scheduler_monitor.registry_audit(repo)

    assert audit["status"] == "mismatch"
    assert audit["errors"] == ["undocumented-timer:rogue.timer"]
