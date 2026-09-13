"""Idempotent, scope-limited unattended automation installation."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

import pytest

from tools import install_automation

REAL_SERVICE_STATE = install_automation._service_state
REAL_LINGER_STATE = install_automation._linger_state
REAL_HOST_CONTINUITY = install_automation._host_continuity


@pytest.fixture(autouse=True)
def healthy_service_states(monkeypatch):
    monkeypatch.setattr(
        install_automation,
        "_service_state",
        lambda action, _unit: "enabled" if action == "is-enabled" else "active",
    )
    monkeypatch.setattr(install_automation, "_linger_state", lambda: "yes")
    monkeypatch.setattr(
        install_automation,
        "_host_continuity",
        lambda _root: {
            "cron_service": "active",
            "cron_service_unit": "cron",
            "cron_service_enabled": "enabled",
            "timezone": "UTC",
            "timezone_ok": True,
            "log_directory_writable": True,
            "unsafe_log_targets": [],
        },
    )


def _repo(tmp_path: Path) -> tuple[Path, Path]:
    home = tmp_path / "home"
    root = home / "trading-engine"
    for relative in install_automation.UNIT_SOURCES.values():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"unit:{relative}\n")
    for name in install_automation.scheduler_monitor.expected_cron_entries(root):
        path = root / "engine" / f"{name}.sh"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\n")
        path.chmod(0o755)
    python = root / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\n")
    python.chmod(0o755)
    verifier = root / "tools" / "verify_friday_postflight.py"
    verifier.parent.mkdir()
    verifier.write_text("")
    return root, home


def test_render_crontab_preserves_unrelated_entries_and_is_idempotent(tmp_path):
    root, _home = _repo(tmp_path)
    old_entries = install_automation.managed_entries(root)
    current = "MAILTO=owner@example.invalid\n17 * * * * /other/watchdog\n" + old_entries[0] + "\n"

    rendered = install_automation.render_crontab(current, root)

    assert "MAILTO=owner@example.invalid" in rendered
    assert "17 * * * * /other/watchdog" in rendered
    assert rendered.count(install_automation.BEGIN_MARKER) == 1
    assert rendered.count(install_automation.END_MARKER) == 1
    assert all(rendered.count(entry) == 1 for entry in old_entries)
    assert install_automation.render_crontab(rendered, root) == rendered


def test_render_crontab_preserves_another_checkout_postflight(tmp_path):
    root, _home = _repo(tmp_path)
    other = (
        "15 5 * * 6 cd /srv/other-engine && .venv/bin/python -m "
        "tools.verify_friday_postflight --publish > /srv/other-engine/postflight.log 2>&1"
    )

    rendered = install_automation.render_crontab(other + "\n", root)

    assert other in rendered


@pytest.mark.parametrize(
    "text",
    (
        f"{install_automation.BEGIN_MARKER}\n",
        f"{install_automation.END_MARKER}\n",
        f"{install_automation.BEGIN_MARKER}\n{install_automation.BEGIN_MARKER}\n",
    ),
)
def test_render_crontab_rejects_malformed_managed_blocks(tmp_path, text):
    root, _home = _repo(tmp_path)

    with pytest.raises(ValueError):
        install_automation.render_crontab(text, root)


def test_plan_reports_drift_without_writing(tmp_path, monkeypatch):
    root, home = _repo(tmp_path)
    monkeypatch.setattr(install_automation, "_read_crontab", lambda: "5 * * * * /other/job\n")

    summary, desired = install_automation.plan(root, home)

    assert summary["status"] == "changes-required"
    assert summary["applied"] is False
    assert summary["changes"]["crontab"] is True
    assert summary["changes"]["service_units"] == sorted(install_automation.UNIT_SOURCES)
    assert "5 * * * * /other/job" in desired
    assert set(summary["launch_sources"]) == {
        *install_automation.scheduler_monitor.expected_cron_entries(root),
        "friday_postflight",
    }
    assert all(
        len(source["source_sha256"]) == 64
        for source in summary["launch_sources"].values()
    )


def test_plan_is_ok_when_units_and_managed_cron_match(tmp_path, monkeypatch):
    root, home = _repo(tmp_path)
    unit_dir = home / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True)
    for unit, relative in install_automation.UNIT_SOURCES.items():
        (unit_dir / unit).write_bytes((root / relative).read_bytes())
    current = install_automation.render_crontab("5 * * * * /other/job\n", root)
    monkeypatch.setattr(install_automation, "_read_crontab", lambda: current)

    summary, desired = install_automation.plan(root, home)

    assert summary["status"] == "ok"
    assert summary["changes"] == {
        "crontab": False,
        "service_units": [],
        "enable_units": [],
        "start_units": [],
        "enable_linger": False,
    }
    assert summary["linger"] == "yes"
    assert all(state["enabled"] == "enabled" for state in summary["service_units"].values())
    assert all(state["active"] == "active" for state in summary["service_units"].values())
    assert desired == current


def test_plan_reports_disabled_and_inactive_units_as_drift(tmp_path, monkeypatch):
    root, home = _repo(tmp_path)
    unit_dir = home / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True)
    for unit, relative in install_automation.UNIT_SOURCES.items():
        (unit_dir / unit).write_bytes((root / relative).read_bytes())
    current = install_automation.render_crontab("", root)
    units = sorted(install_automation.UNIT_SOURCES)

    def state(action, unit):
        if unit != units[0]:
            return "enabled" if action == "is-enabled" else "active"
        return "disabled" if action == "is-enabled" else "inactive"

    monkeypatch.setattr(install_automation, "_service_state", state)
    monkeypatch.setattr(install_automation, "_read_crontab", lambda: current)

    summary, _desired = install_automation.plan(root, home)

    assert summary["status"] == "changes-required"
    assert summary["changes"]["service_units"] == []
    assert summary["changes"]["enable_units"] == [units[0]]
    assert summary["changes"]["start_units"] == [units[0]]
    assert summary["service_units"][units[0]]["enabled"] == "disabled"
    assert summary["service_units"][units[0]]["active"] == "inactive"


def test_service_state_fails_closed_when_systemctl_is_unavailable(monkeypatch):
    monkeypatch.setattr(
        install_automation,
        "_run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("missing")),
    )

    assert REAL_SERVICE_STATE("is-active", "example.service") == "unknown"


def test_linger_state_fails_closed_when_logind_is_unavailable(monkeypatch):
    monkeypatch.setattr(
        install_automation,
        "_run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("missing")),
    )

    assert REAL_LINGER_STATE() == "unknown"


def test_plan_reports_disabled_linger_as_drift(tmp_path, monkeypatch):
    root, home = _repo(tmp_path)
    unit_dir = home / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True)
    for unit, relative in install_automation.UNIT_SOURCES.items():
        (unit_dir / unit).write_bytes((root / relative).read_bytes())
    current = install_automation.render_crontab("", root)
    monkeypatch.setattr(install_automation, "_read_crontab", lambda: current)
    monkeypatch.setattr(install_automation, "_linger_state", lambda: "no")

    summary, _desired = install_automation.plan(root, home)

    assert summary["status"] == "changes-required"
    assert summary["linger"] == "no"
    assert summary["changes"]["enable_linger"] is True


def test_plan_fails_closed_on_unrepairable_host_prerequisites(tmp_path, monkeypatch):
    root, home = _repo(tmp_path)
    monkeypatch.setattr(install_automation, "_read_crontab", lambda: "")
    monkeypatch.setattr(
        install_automation,
        "_host_continuity",
        lambda _root: {
            "cron_service": "inactive",
            "cron_service_unit": "cron",
            "cron_service_enabled": "disabled",
            "timezone": "Asia/Singapore",
            "timezone_ok": False,
            "log_directory_writable": False,
            "unsafe_log_targets": ["friday_postflight", "run_daily"],
        },
    )

    summary, _desired = install_automation.plan(root, home)

    assert summary["status"] == "invalid"
    assert summary["errors"] == [
        "cron-service-not-active:inactive",
        "cron-service-not-enabled:disabled",
        "timezone-not-utc:Asia/Singapore",
        "log-directory-not-writable",
        "unsafe-log-target:friday_postflight",
        "unsafe-log-target:run_daily",
    ]
    assert summary["host"]["timezone_ok"] is False


def test_host_continuity_rejects_symlinked_log_directory(tmp_path, monkeypatch):
    external = tmp_path / "external-logs"
    external.mkdir()
    (tmp_path / "logs").symlink_to(external, target_is_directory=True)
    monkeypatch.setattr(
        install_automation.scheduler_monitor.scheduler_host,
        "cron_service",
        lambda: ("active", "cron"),
    )
    monkeypatch.setattr(
        install_automation.scheduler_monitor.scheduler_host,
        "service_enabled",
        lambda _unit: "enabled",
    )
    monkeypatch.setattr(
        install_automation.scheduler_monitor.scheduler_host,
        "system_timezone",
        lambda: "UTC",
    )

    host = REAL_HOST_CONTINUITY(tmp_path)

    assert host["log_directory_writable"] is False
    assert install_automation._host_errors(host) == ["log-directory-not-writable"]


def test_host_continuity_rejects_unsafe_managed_log_target(tmp_path, monkeypatch):
    logs = tmp_path / "logs"
    logs.mkdir()
    target = install_automation.scheduler_monitor.managed_log_targets(tmp_path)["run_daily"]
    target.symlink_to(tmp_path / "missing.log")
    monkeypatch.setattr(
        install_automation.scheduler_monitor.scheduler_host,
        "cron_service",
        lambda: ("active", "cron"),
    )
    monkeypatch.setattr(
        install_automation.scheduler_monitor.scheduler_host,
        "service_enabled",
        lambda _unit: "enabled",
    )
    monkeypatch.setattr(
        install_automation.scheduler_monitor.scheduler_host,
        "system_timezone",
        lambda: "UTC",
    )

    host = REAL_HOST_CONTINUITY(tmp_path)

    assert host["unsafe_log_targets"] == ["run_daily"]
    assert install_automation._host_errors(host) == ["unsafe-log-target:run_daily"]


def test_plan_reports_symlinked_installed_unit_as_drift(tmp_path, monkeypatch):
    root, home = _repo(tmp_path)
    unit_dir = home / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True)
    units = list(install_automation.UNIT_SOURCES.items())
    symlinked_unit, symlinked_source = units[0]
    (unit_dir / symlinked_unit).symlink_to(root / symlinked_source)
    for unit, relative in units[1:]:
        (unit_dir / unit).write_bytes((root / relative).read_bytes())
    current = install_automation.render_crontab("", root)
    monkeypatch.setattr(install_automation, "_read_crontab", lambda: current)

    summary, _desired = install_automation.plan(root, home)

    assert summary["status"] == "changes-required"
    assert summary["changes"]["service_units"] == [symlinked_unit]
    assert summary["service_units"][symlinked_unit]["matches"] is False


def test_plan_rejects_installed_unit_replaced_during_descriptor_read(tmp_path, monkeypatch):
    root, home = _repo(tmp_path)
    unit_dir = home / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True)
    units = list(install_automation.UNIT_SOURCES.items())
    replaced_unit, replaced_source = units[0]
    target = unit_dir / replaced_unit
    target.write_bytes((root / replaced_source).read_bytes())
    target_inode = target.stat().st_ino
    for unit, relative in units[1:]:
        (unit_dir / unit).write_bytes((root / relative).read_bytes())
    current = install_automation.render_crontab("", root)
    monkeypatch.setattr(install_automation, "_read_crontab", lambda: current)
    original_read = install_automation.os.read
    replaced = False

    def read_then_replace(descriptor, size):
        nonlocal replaced
        chunk = original_read(descriptor, size)
        if chunk and not replaced and os.fstat(descriptor).st_ino == target_inode:
            replaced = True
            target.unlink()
            target.symlink_to(root / replaced_source)
        return chunk

    monkeypatch.setattr(install_automation.os, "read", read_then_replace)

    summary, _desired = install_automation.plan(root, home)

    assert replaced is True
    assert summary["changes"]["service_units"] == [replaced_unit]
    assert summary["service_units"][replaced_unit]["matches"] is False


def test_plan_rejects_installed_unit_below_symlinked_directory(tmp_path, monkeypatch):
    root, home = _repo(tmp_path)
    external = tmp_path / "external-user-units"
    external.mkdir()
    unit_dir = home / ".config" / "systemd"
    unit_dir.mkdir(parents=True)
    (unit_dir / "user").symlink_to(external, target_is_directory=True)
    for unit, relative in install_automation.UNIT_SOURCES.items():
        (external / unit).write_bytes((root / relative).read_bytes())
    current = install_automation.render_crontab("", root)
    monkeypatch.setattr(install_automation, "_read_crontab", lambda: current)

    summary, _desired = install_automation.plan(root, home)

    assert summary["status"] == "invalid"
    assert "installed-unit-directory-has-symlink" in summary["errors"]
    assert summary["changes"]["service_units"] == sorted(install_automation.UNIT_SOURCES)
    assert all(not state["matches"] for state in summary["service_units"].values())


def test_plan_rejects_symlinked_unit_source(tmp_path, monkeypatch):
    root, home = _repo(tmp_path)
    relative = next(iter(install_automation.UNIT_SOURCES.values()))
    source = root / relative
    linked_source = root / "linked-unit.service"
    source.replace(linked_source)
    source.symlink_to(linked_source)
    monkeypatch.setattr(install_automation, "_read_crontab", lambda: "")

    summary, _desired = install_automation.plan(root, home)

    assert summary["status"] == "invalid"
    assert f"not-regular:{relative.as_posix()}" in summary["errors"]


def test_plan_rejects_unit_source_below_symlinked_directory(tmp_path, monkeypatch):
    root, home = _repo(tmp_path)
    external = tmp_path / "external-server"
    (root / "server").replace(external)
    (root / "server").symlink_to(external, target_is_directory=True)
    monkeypatch.setattr(install_automation, "_read_crontab", lambda: "")

    summary, _desired = install_automation.plan(root, home)

    assert summary["status"] == "invalid"
    assert "not-regular:server/trading-engine-api.service" in summary["errors"]


def test_plan_rejects_unit_source_changed_during_descriptor_read(tmp_path, monkeypatch):
    root, home = _repo(tmp_path)
    relative = next(iter(install_automation.UNIT_SOURCES.values()))
    source = root / relative
    source_inode = source.stat().st_ino
    monkeypatch.setattr(install_automation, "_read_crontab", lambda: "")
    original_read = install_automation.os.read
    changed = False

    def read_then_change(descriptor, size):
        nonlocal changed
        chunk = original_read(descriptor, size)
        if chunk and not changed and os.fstat(descriptor).st_ino == source_inode:
            changed = True
            source.write_text("changed during read\n")
        return chunk

    monkeypatch.setattr(install_automation.os, "read", read_then_change)

    summary, _desired = install_automation.plan(root, home)

    assert changed is True
    assert summary["status"] == "invalid"
    assert f"unsafe-service-unit-source:{relative.as_posix()}" in summary["errors"]


def test_plan_rejects_symlinked_cron_driver(tmp_path, monkeypatch):
    root, home = _repo(tmp_path)
    name = next(iter(install_automation.scheduler_monitor.expected_cron_entries(root)))
    driver = root / "engine" / f"{name}.sh"
    linked_driver = root / "linked-driver.sh"
    driver.replace(linked_driver)
    driver.symlink_to(linked_driver)
    monkeypatch.setattr(install_automation, "_read_crontab", lambda: "")

    summary, _desired = install_automation.plan(root, home)

    assert summary["status"] == "invalid"
    assert f"not-regular:engine/{name}.sh" in summary["errors"]


def test_plan_rejects_postflight_below_symlinked_directory(tmp_path, monkeypatch):
    root, home = _repo(tmp_path)
    external = tmp_path / "external-tools"
    (root / "tools").replace(external)
    (root / "tools").symlink_to(external, target_is_directory=True)
    monkeypatch.setattr(install_automation, "_read_crontab", lambda: "")

    summary, _desired = install_automation.plan(root, home)

    assert summary["status"] == "invalid"
    assert "not-regular:tools/verify_friday_postflight.py" in summary["errors"]


def test_plan_rejects_cron_driver_changed_during_descriptor_read(tmp_path, monkeypatch):
    root, home = _repo(tmp_path)
    name = next(iter(install_automation.scheduler_monitor.expected_cron_entries(root)))
    driver = root / "engine" / f"{name}.sh"
    driver_inode = driver.stat().st_ino
    monkeypatch.setattr(install_automation, "_read_crontab", lambda: "")
    original_read = install_automation.os.read
    changed = False

    def read_then_change(descriptor, size):
        nonlocal changed
        chunk = original_read(descriptor, size)
        if chunk and not changed and os.fstat(descriptor).st_ino == driver_inode:
            changed = True
            driver.write_text("#!/bin/sh\necho changed\n")
            driver.chmod(0o755)
        return chunk

    monkeypatch.setattr(install_automation.os, "read", read_then_change)

    summary, _desired = install_automation.plan(root, home)

    assert changed is True
    assert summary["status"] == "invalid"
    assert f"unsafe-launch-source:engine/{name}.sh" in summary["errors"]
    assert summary["launch_sources"][name]["source_sha256"] is None


def test_plan_rejects_cron_driver_losing_execute_permission_before_descriptor_check(
    tmp_path, monkeypatch
):
    root, home = _repo(tmp_path)
    name = next(iter(install_automation.scheduler_monitor.expected_cron_entries(root)))
    driver = root / "engine" / f"{name}.sh"
    original_validate = install_automation._validate_launch_file
    changed = False

    def validate_then_chmod(repo_root, relative, *, access_mode, access_label):
        nonlocal changed
        result = original_validate(
            repo_root,
            relative,
            access_mode=access_mode,
            access_label=access_label,
        )
        if relative == Path("engine") / f"{name}.sh" and not changed:
            changed = True
            driver.chmod(0o644)
        return result

    monkeypatch.setattr(install_automation, "_validate_launch_file", validate_then_chmod)
    monkeypatch.setattr(install_automation, "_read_crontab", lambda: "")

    summary, _desired = install_automation.plan(root, home)

    assert changed is True
    assert summary["status"] == "invalid"
    assert f"unsafe-launch-source:engine/{name}.sh" in summary["errors"]
    assert summary["launch_sources"][name]["source_sha256"] is None


def test_launch_source_permission_change_during_descriptor_read_is_rejected(tmp_path, monkeypatch):
    root, _home = _repo(tmp_path)
    name = next(iter(install_automation.scheduler_monitor.expected_cron_entries(root)))
    relative = Path("engine") / f"{name}.sh"
    driver = root / relative
    driver_inode = driver.stat().st_ino
    original_read = install_automation.os.read
    changed = False

    def read_then_chmod(descriptor, size):
        nonlocal changed
        chunk = original_read(descriptor, size)
        if chunk and not changed and os.fstat(descriptor).st_ino == driver_inode:
            changed = True
            driver.chmod(0o644)
        return chunk

    monkeypatch.setattr(install_automation.os, "read", read_then_chmod)

    with pytest.raises(RuntimeError, match="automation launch source changed"):
        install_automation._read_stable_regular_file(
            root,
            relative,
            label="automation launch source",
            access_mode=os.X_OK,
            access_label="executable",
        )

    assert changed is True


def test_plan_rejects_service_working_directory_mismatch(tmp_path, monkeypatch):
    root, home = _repo(tmp_path)
    moved = tmp_path / "moved"
    root.rename(moved)
    monkeypatch.setattr(install_automation, "_read_crontab", lambda: "")

    summary, _desired = install_automation.plan(moved, home)

    assert summary["status"] == "invalid"
    assert "service-working-directory-mismatch" in summary["errors"]


def test_plan_rejects_checkout_path_that_cron_cannot_quote(tmp_path, monkeypatch):
    home = tmp_path / "home with spaces"
    root = home / "trading-engine"
    root.mkdir(parents=True)
    monkeypatch.setattr(install_automation, "_read_crontab", lambda: "")

    summary, _desired = install_automation.plan(root, home)

    assert summary["status"] == "invalid"
    assert "repo-root-not-cron-safe" in summary["errors"]


def test_apply_changes_only_drifted_unit_and_crontab(tmp_path, monkeypatch):
    root, home = _repo(tmp_path)
    unit_dir = home / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True)
    api = "trading-engine-api.service"
    ui = "trading-engine-ui.service"
    (unit_dir / api).write_text("old\n")
    (unit_dir / ui).write_bytes((root / install_automation.UNIT_SOURCES[ui]).read_bytes())
    current = "5 * * * * /other/job\n"
    installed_crontab = {"text": current}
    monkeypatch.setattr(
        install_automation, "_read_crontab", lambda: installed_crontab["text"]
    )
    summary, desired = install_automation.plan(root, home)
    calls = []

    def checked(args, *, input_text=None):
        calls.append((args, input_text))
        if args[:2] == ["crontab", "-"]:
            installed_crontab["text"] = input_text

    monkeypatch.setattr(install_automation, "_checked", checked)
    monkeypatch.setattr(
        install_automation.scheduler_monitor,
        "status",
        lambda **_kwargs: {"status": "ok"},
    )

    result = install_automation.apply(summary, desired, root, home)

    assert result["status"] == "ok"
    assert result["applied"] is True
    assert (["crontab", "-"], desired) in calls
    assert (["systemctl", "--user", "daemon-reload"], None) in calls
    assert (["systemctl", "--user", "restart", api], None) in calls
    assert (["systemctl", "--user", "start", ui], None) not in calls
    assert (["systemctl", "--user", "is-enabled", api, ui], None) in calls
    assert (["systemctl", "--user", "is-active", api, ui], None) in calls
    assert not any(api in args and ui in args and "restart" in args for args, _input in calls)
    assert (unit_dir / api).read_bytes() == (
        root / install_automation.UNIT_SOURCES[api]
    ).read_bytes()


def test_apply_is_mutation_free_when_replanned_state_is_converged(tmp_path, monkeypatch):
    root, home = _repo(tmp_path)
    unit_dir = home / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True)
    for unit, relative in install_automation.UNIT_SOURCES.items():
        (unit_dir / unit).write_bytes((root / relative).read_bytes())
    current = install_automation.render_crontab("", root)
    monkeypatch.setattr(install_automation, "_read_crontab", lambda: current)
    calls = []
    monkeypatch.setattr(
        install_automation,
        "_checked",
        lambda args, *, input_text=None: calls.append((args, input_text)),
    )
    monkeypatch.setattr(
        install_automation.scheduler_monitor,
        "status",
        lambda **_kwargs: {"status": "ok"},
    )
    summary, desired = install_automation.plan(root, home)

    result = install_automation.apply(summary, desired, root, home)

    units = sorted(install_automation.UNIT_SOURCES)
    assert result["status"] == "ok"
    assert result["changes"] == summary["changes"]
    assert calls == [
        (["systemctl", "--user", "is-enabled", *units], None),
        (["systemctl", "--user", "is-active", *units], None),
    ]


def test_apply_repairs_service_state_without_reinstall_or_restart(tmp_path, monkeypatch):
    root, home = _repo(tmp_path)
    unit_dir = home / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True)
    for unit, relative in install_automation.UNIT_SOURCES.items():
        (unit_dir / unit).write_bytes((root / relative).read_bytes())
    current = install_automation.render_crontab("", root)
    states = {
        unit: {"enabled": "disabled", "active": "inactive"}
        for unit in install_automation.UNIT_SOURCES
    }

    def state(action, unit):
        field = "enabled" if action == "is-enabled" else "active"
        return states[unit][field]

    calls = []

    def checked(args, *, input_text=None):
        calls.append((args, input_text))
        if args[:3] == ["systemctl", "--user", "enable"]:
            for unit in args[3:]:
                states[unit]["enabled"] = "enabled"
        if args[:3] == ["systemctl", "--user", "start"]:
            for unit in args[3:]:
                states[unit]["active"] = "active"

    monkeypatch.setattr(install_automation, "_service_state", state)
    monkeypatch.setattr(install_automation, "_read_crontab", lambda: current)
    monkeypatch.setattr(install_automation, "_checked", checked)
    monkeypatch.setattr(
        install_automation.scheduler_monitor,
        "status",
        lambda **_kwargs: {"status": "ok"},
    )
    summary, desired = install_automation.plan(root, home)

    result = install_automation.apply(summary, desired, root, home)

    units = sorted(install_automation.UNIT_SOURCES)
    assert result["status"] == "ok"
    assert result["changes"]["service_units"] == []
    assert result["changes"]["enable_units"] == units
    assert result["changes"]["start_units"] == units
    assert (["systemctl", "--user", "enable", *units], None) in calls
    assert (["systemctl", "--user", "start", *units], None) in calls
    assert not any(args[0] == "install" for args, _input in calls)
    assert not any("restart" in args for args, _input in calls)


def test_apply_repairs_service_state_changed_after_matching_replan(tmp_path, monkeypatch):
    root, home = _repo(tmp_path)
    unit_dir = home / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True)
    for unit, relative in install_automation.UNIT_SOURCES.items():
        (unit_dir / unit).write_bytes((root / relative).read_bytes())
    current = install_automation.render_crontab("", root)
    states = {
        unit: {"enabled": "enabled", "active": "active"}
        for unit in install_automation.UNIT_SOURCES
    }
    changed_unit = next(iter(install_automation.UNIT_SOURCES))

    def state(action, unit):
        field = "enabled" if action == "is-enabled" else "active"
        return states[unit][field]

    monkeypatch.setattr(install_automation, "_service_state", state)
    monkeypatch.setattr(install_automation, "_read_crontab", lambda: current)
    stale_summary, stale_desired = install_automation.plan(root, home)
    original_reconcile = install_automation._reconcile_units

    def reconcile_then_disable(requested_home, snapshots):
        changed = original_reconcile(requested_home, snapshots)
        states[changed_unit] = {"enabled": "disabled", "active": "inactive"}
        return changed

    calls = []

    def checked(args, *, input_text=None):
        calls.append((args, input_text))
        if args[:3] == ["systemctl", "--user", "enable"]:
            for unit in args[3:]:
                states[unit]["enabled"] = "enabled"
        if args[:3] == ["systemctl", "--user", "start"]:
            for unit in args[3:]:
                states[unit]["active"] = "active"

    monkeypatch.setattr(install_automation, "_reconcile_units", reconcile_then_disable)
    monkeypatch.setattr(install_automation, "_checked", checked)
    monkeypatch.setattr(
        install_automation.scheduler_monitor,
        "status",
        lambda **_kwargs: {"status": "ok"},
    )

    result = install_automation.apply(stale_summary, stale_desired, root, home)

    assert result["status"] == "ok"
    assert result["changes"]["enable_units"] == [changed_unit]
    assert result["changes"]["start_units"] == [changed_unit]
    assert (["systemctl", "--user", "enable", changed_unit], None) in calls
    assert (["systemctl", "--user", "start", changed_unit], None) in calls


def test_apply_enables_linger_when_it_is_disabled(tmp_path, monkeypatch):
    root, home = _repo(tmp_path)
    unit_dir = home / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True)
    for unit, relative in install_automation.UNIT_SOURCES.items():
        (unit_dir / unit).write_bytes((root / relative).read_bytes())
    current = install_automation.render_crontab("", root)
    linger = {"state": "no"}
    calls = []

    def checked(args, *, input_text=None):
        calls.append((args, input_text))
        if args[:2] == ["loginctl", "enable-linger"]:
            linger["state"] = "yes"

    monkeypatch.setattr(install_automation, "_read_crontab", lambda: current)
    monkeypatch.setattr(install_automation, "_linger_state", lambda: linger["state"])
    monkeypatch.setattr(install_automation, "_checked", checked)
    monkeypatch.setattr(
        install_automation.scheduler_monitor,
        "status",
        lambda **_kwargs: {"status": "ok"},
    )
    summary, desired = install_automation.plan(root, home)

    result = install_automation.apply(summary, desired, root, home)

    assert result["status"] == "ok"
    assert result["linger"] == "yes"
    assert result["changes"]["enable_linger"] is True
    assert (["loginctl", "enable-linger", str(os.getuid())], None) in calls


def test_apply_enables_linger_disabled_after_matching_replan(tmp_path, monkeypatch):
    root, home = _repo(tmp_path)
    unit_dir = home / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True)
    for unit, relative in install_automation.UNIT_SOURCES.items():
        (unit_dir / unit).write_bytes((root / relative).read_bytes())
    current = install_automation.render_crontab("", root)
    linger = {"state": "yes"}
    monkeypatch.setattr(install_automation, "_read_crontab", lambda: current)
    monkeypatch.setattr(install_automation, "_linger_state", lambda: linger["state"])
    stale_summary, stale_desired = install_automation.plan(root, home)
    original_snapshot = install_automation._snapshot_unit_sources

    def snapshot_then_disable(repo_root, summary):
        result = original_snapshot(repo_root, summary)
        linger["state"] = "no"
        return result

    calls = []

    def checked(args, *, input_text=None):
        calls.append((args, input_text))
        if args[:2] == ["loginctl", "enable-linger"]:
            linger["state"] = "yes"

    monkeypatch.setattr(install_automation, "_snapshot_unit_sources", snapshot_then_disable)
    monkeypatch.setattr(install_automation, "_checked", checked)
    monkeypatch.setattr(
        install_automation.scheduler_monitor,
        "status",
        lambda **_kwargs: {"status": "ok"},
    )

    result = install_automation.apply(stale_summary, stale_desired, root, home)

    assert result["status"] == "ok"
    assert result["changes"]["enable_linger"] is True
    assert (["loginctl", "enable-linger", str(os.getuid())], None) in calls


def test_apply_replans_and_preserves_a_concurrent_unrelated_crontab_edit(tmp_path, monkeypatch):
    root, home = _repo(tmp_path)
    unit_dir = home / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True)
    for unit, relative in install_automation.UNIT_SOURCES.items():
        (unit_dir / unit).write_bytes((root / relative).read_bytes())
    initial = "5 * * * * /other/original\n"
    current = {"text": initial}
    monkeypatch.setattr(install_automation, "_read_crontab", lambda: current["text"])
    stale_summary, stale_desired = install_automation.plan(root, home)
    current["text"] += "17 * * * * /other/concurrent\n"
    calls = []

    def checked(args, *, input_text=None):
        calls.append((args, input_text))
        if args[:2] == ["crontab", "-"]:
            current["text"] = input_text

    monkeypatch.setattr(install_automation, "_checked", checked)
    monkeypatch.setattr(
        install_automation.scheduler_monitor,
        "status",
        lambda **_kwargs: {"status": "ok"},
    )

    result = install_automation.apply(stale_summary, stale_desired, root, home)

    assert result["status"] == "ok"
    assert "/other/original" in current["text"]
    assert "/other/concurrent" in current["text"]
    assert stale_desired != current["text"]


def test_apply_refreshes_crontab_after_preparing_unit_changes(tmp_path, monkeypatch):
    root, home = _repo(tmp_path)
    initial = "5 * * * * /other/original\n"
    current = {"text": initial}
    monkeypatch.setattr(install_automation, "_read_crontab", lambda: current["text"])
    stale_summary, stale_desired = install_automation.plan(root, home)
    original_install = install_automation._reconcile_units

    def install_then_edit(requested_home, snapshots):
        changed_units = original_install(requested_home, snapshots)
        current["text"] += "17 * * * * /other/concurrent\n"
        return changed_units

    calls = []

    def checked(args, *, input_text=None):
        calls.append((args, input_text))
        if args[:2] == ["crontab", "-"]:
            current["text"] = input_text

    monkeypatch.setattr(install_automation, "_reconcile_units", install_then_edit)
    monkeypatch.setattr(install_automation, "_checked", checked)
    monkeypatch.setattr(
        install_automation.scheduler_monitor,
        "status",
        lambda **_kwargs: {"status": "ok"},
    )

    result = install_automation.apply(stale_summary, stale_desired, root, home)

    assert result["status"] == "ok"
    assert "/other/original" in current["text"]
    assert "/other/concurrent" in current["text"]
    assert stale_desired != current["text"]


def test_apply_repairs_crontab_changed_after_matching_replan(tmp_path, monkeypatch):
    root, home = _repo(tmp_path)
    unit_dir = home / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True)
    for unit, relative in install_automation.UNIT_SOURCES.items():
        (unit_dir / unit).write_bytes((root / relative).read_bytes())
    expected = install_automation.render_crontab("5 * * * * /other/original\n", root)
    current = {"text": expected}
    monkeypatch.setattr(install_automation, "_read_crontab", lambda: current["text"])
    stale_summary, stale_desired = install_automation.plan(root, home)
    original_snapshot = install_automation._snapshot_unit_sources
    changed = False

    def snapshot_then_edit(repo_root, summary):
        nonlocal changed
        result = original_snapshot(repo_root, summary)
        if not changed:
            changed = True
            current["text"] = "17 * * * * /other/concurrent\n"
        return result

    calls = []

    def checked(args, *, input_text=None):
        calls.append((args, input_text))
        if args[:2] == ["crontab", "-"]:
            current["text"] = input_text

    monkeypatch.setattr(install_automation, "_snapshot_unit_sources", snapshot_then_edit)
    monkeypatch.setattr(install_automation, "_checked", checked)
    monkeypatch.setattr(
        install_automation.scheduler_monitor,
        "status",
        lambda **_kwargs: {"status": "ok"},
    )

    result = install_automation.apply(stale_summary, stale_desired, root, home)

    assert changed is True
    assert result["status"] == "ok"
    assert result["changes"]["crontab"] is True
    assert "/other/concurrent" in current["text"]
    assert install_automation.BEGIN_MARKER in current["text"]


def test_apply_replans_and_rejects_newly_unsafe_source(tmp_path, monkeypatch):
    root, home = _repo(tmp_path)
    monkeypatch.setattr(install_automation, "_read_crontab", lambda: "")
    summary, desired = install_automation.plan(root, home)
    name = next(iter(install_automation.scheduler_monitor.expected_cron_entries(root)))
    driver = root / "engine" / f"{name}.sh"
    linked_driver = root / "linked-driver.sh"
    driver.replace(linked_driver)
    driver.symlink_to(linked_driver)
    calls = []
    monkeypatch.setattr(
        install_automation,
        "_checked",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    with pytest.raises(RuntimeError, match="refusing invalid automation plan"):
        install_automation.apply(summary, desired, root, home)

    assert calls == []


def test_apply_rejects_cron_driver_changed_after_replan(tmp_path, monkeypatch):
    root, home = _repo(tmp_path)
    monkeypatch.setattr(install_automation, "_read_crontab", lambda: "")
    stale_summary, stale_desired = install_automation.plan(root, home)
    name = next(iter(install_automation.scheduler_monitor.expected_cron_entries(root)))
    driver = root / "engine" / f"{name}.sh"
    original_plan = install_automation.plan
    changed = False

    def plan_then_change(repo_root, requested_home):
        nonlocal changed
        result = original_plan(repo_root, requested_home)
        if not changed:
            changed = True
            driver.write_text("#!/bin/sh\necho changed\n")
            driver.chmod(0o755)
        return result

    calls = []
    monkeypatch.setattr(install_automation, "plan", plan_then_change)
    monkeypatch.setattr(
        install_automation,
        "_checked",
        lambda args, *, input_text=None: calls.append((args, input_text)),
    )
    monkeypatch.setattr(
        install_automation.scheduler_monitor,
        "status",
        lambda **_kwargs: {"status": "ok"},
    )

    with pytest.raises(RuntimeError, match="launch source changed after replan"):
        install_automation.apply(stale_summary, stale_desired, root, home)

    assert changed is True
    assert calls == []
    assert not (home / ".config" / "systemd" / "user").exists()


def test_apply_rejects_unit_source_changed_after_replan(tmp_path, monkeypatch):
    root, home = _repo(tmp_path)
    monkeypatch.setattr(install_automation, "_read_crontab", lambda: "")
    stale_summary, stale_desired = install_automation.plan(root, home)
    source = root / next(iter(install_automation.UNIT_SOURCES.values()))
    original_plan = install_automation.plan
    changed = False

    def plan_then_change(repo_root, requested_home):
        nonlocal changed
        result = original_plan(repo_root, requested_home)
        if not changed:
            changed = True
            source.write_text("changed after replan\n")
        return result

    calls = []

    def checked(args, *, input_text=None):
        calls.append((args, input_text))

    monkeypatch.setattr(install_automation, "plan", plan_then_change)
    monkeypatch.setattr(install_automation, "_checked", checked)
    monkeypatch.setattr(
        install_automation.scheduler_monitor,
        "status",
        lambda **_kwargs: {"status": "ok"},
    )

    with pytest.raises(RuntimeError, match="service unit source changed after replan"):
        install_automation.apply(stale_summary, stale_desired, root, home)

    assert changed is True
    assert calls == []


def test_apply_rejects_matching_unit_source_changed_after_replan(tmp_path, monkeypatch):
    root, home = _repo(tmp_path)
    unit_dir = home / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True)
    for unit, relative in install_automation.UNIT_SOURCES.items():
        (unit_dir / unit).write_bytes((root / relative).read_bytes())
    current = {"text": "5 * * * * /other/original\n"}
    monkeypatch.setattr(install_automation, "_read_crontab", lambda: current["text"])
    stale_summary, stale_desired = install_automation.plan(root, home)
    source = root / next(iter(install_automation.UNIT_SOURCES.values()))
    original_plan = install_automation.plan
    changed = False

    def plan_then_change(repo_root, requested_home):
        nonlocal changed
        result = original_plan(repo_root, requested_home)
        if not changed:
            changed = True
            source.write_text("changed after replan\n")
        return result

    calls = []
    monkeypatch.setattr(install_automation, "plan", plan_then_change)
    monkeypatch.setattr(
        install_automation,
        "_checked",
        lambda args, *, input_text=None: calls.append((args, input_text)),
    )

    with pytest.raises(RuntimeError, match="service unit source changed after replan"):
        install_automation.apply(stale_summary, stale_desired, root, home)

    assert changed is True
    assert calls == []


def test_apply_repairs_installed_unit_changed_after_matching_replan(tmp_path, monkeypatch):
    root, home = _repo(tmp_path)
    unit_dir = home / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True)
    for unit, relative in install_automation.UNIT_SOURCES.items():
        (unit_dir / unit).write_bytes((root / relative).read_bytes())
    current = install_automation.render_crontab("", root)
    monkeypatch.setattr(install_automation, "_read_crontab", lambda: current)
    stale_summary, stale_desired = install_automation.plan(root, home)
    changed_unit = next(iter(install_automation.UNIT_SOURCES))
    target = unit_dir / changed_unit
    original_snapshot = install_automation._snapshot_unit_sources
    changed = False

    def snapshot_then_change(repo_root, summary):
        nonlocal changed
        result = original_snapshot(repo_root, summary)
        if not changed:
            changed = True
            target.write_text("changed after replan\n")
        return result

    calls = []

    def checked(args, *, input_text=None):
        calls.append((args, input_text))

    monkeypatch.setattr(install_automation, "_snapshot_unit_sources", snapshot_then_change)
    monkeypatch.setattr(install_automation, "_checked", checked)
    monkeypatch.setattr(
        install_automation.scheduler_monitor,
        "status",
        lambda **_kwargs: {"status": "ok"},
    )

    result = install_automation.apply(stale_summary, stale_desired, root, home)

    assert changed is True
    assert result["status"] == "ok"
    assert result["changes"]["service_units"] == [changed_unit]
    assert target.read_bytes() == (
        root / install_automation.UNIT_SOURCES[changed_unit]
    ).read_bytes()
    assert (["systemctl", "--user", "restart", changed_unit], None) in calls


def test_apply_does_not_write_through_unit_directory_replacement(tmp_path, monkeypatch):
    root, home = _repo(tmp_path)
    monkeypatch.setattr(install_automation, "_read_crontab", lambda: "")
    stale_summary, stale_desired = install_automation.plan(root, home)
    unit_dir = home / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True)
    displaced = home / "displaced-user-units"
    replacement = home / "replacement-user-units"
    replacement.mkdir()
    original_plan = install_automation.plan
    replaced = False

    def plan_then_replace(repo_root, requested_home):
        nonlocal replaced
        result = original_plan(repo_root, requested_home)
        if not replaced:
            replaced = True
            unit_dir.replace(displaced)
            unit_dir.symlink_to(replacement, target_is_directory=True)
        return result

    calls = []

    def checked(args, *, input_text=None):
        calls.append((args, input_text))

    monkeypatch.setattr(install_automation, "plan", plan_then_replace)
    monkeypatch.setattr(install_automation, "_checked", checked)

    with pytest.raises(RuntimeError, match="service unit directory changed after replan"):
        install_automation.apply(stale_summary, stale_desired, root, home)

    assert replaced is True
    assert not any(replacement.iterdir())
    assert calls == []


def test_apply_does_not_write_to_regular_unit_directory_replaced_after_comparison(
    tmp_path, monkeypatch
):
    root, home = _repo(tmp_path)
    monkeypatch.setattr(install_automation, "_read_crontab", lambda: "")
    unit_dir = home / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True)
    for unit in install_automation.UNIT_SOURCES:
        (unit_dir / unit).write_text("old\n")
    stale_summary, stale_desired = install_automation.plan(root, home)
    displaced = home / "displaced-user-units"
    replacement = home / "replacement-user-units"
    replacement.mkdir()
    original_changed = install_automation._changed_unit_snapshots
    replaced = False

    def compare_then_replace(directory_fd, snapshots):
        nonlocal replaced
        result = original_changed(directory_fd, snapshots)
        if not replaced:
            replaced = True
            unit_dir.replace(displaced)
            replacement.replace(unit_dir)
        return result

    calls = []
    monkeypatch.setattr(install_automation, "_changed_unit_snapshots", compare_then_replace)
    monkeypatch.setattr(
        install_automation,
        "_checked",
        lambda args, *, input_text=None: calls.append((args, input_text)),
    )

    with pytest.raises(RuntimeError, match="service unit directory changed after replan"):
        install_automation.apply(stale_summary, stale_desired, root, home)

    assert replaced is True
    assert not any(unit_dir.iterdir())
    assert all(
        (displaced / unit).read_bytes()
        == (root / install_automation.UNIT_SOURCES[unit]).read_bytes()
        for unit in install_automation.UNIT_SOURCES
    )
    assert calls == []


def test_apply_rejects_regular_unit_directory_replaced_between_secure_opens(
    tmp_path, monkeypatch
):
    root, home = _repo(tmp_path)
    monkeypatch.setattr(install_automation, "_read_crontab", lambda: "")
    unit_dir = home / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True)
    for unit in install_automation.UNIT_SOURCES:
        (unit_dir / unit).write_text("old\n")
    stale_summary, stale_desired = install_automation.plan(root, home)
    displaced = home / "displaced-user-units"
    replacement = home / "replacement-user-units"
    replacement.mkdir()
    original_chain = install_automation._directory_chain
    replaced = False

    @contextmanager
    def open_then_replace(anchor, parts, *, create=False):
        nonlocal replaced
        with original_chain(anchor, parts, create=create) as opened:
            if create and not replaced and tuple(parts) == (".config", "systemd", "user"):
                replaced = True
                unit_dir.replace(displaced)
                replacement.replace(unit_dir)
            yield opened

    calls = []
    monkeypatch.setattr(install_automation, "_directory_chain", open_then_replace)
    monkeypatch.setattr(
        install_automation,
        "_checked",
        lambda args, *, input_text=None: calls.append((args, input_text)),
    )

    with pytest.raises(RuntimeError, match="service unit directory changed after replan"):
        install_automation.apply(stale_summary, stale_desired, root, home)

    assert replaced is True
    assert not any(unit_dir.iterdir())
    assert all((displaced / unit).read_text() == "old\n" for unit in install_automation.UNIT_SOURCES)
    assert calls == []


def test_apply_detects_unit_directory_replaced_after_open(tmp_path, monkeypatch):
    root, home = _repo(tmp_path)
    monkeypatch.setattr(install_automation, "_read_crontab", lambda: "")
    stale_summary, stale_desired = install_automation.plan(root, home)
    unit_dir = home / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True)
    displaced = home / "displaced-user-units"
    replacement = home / "replacement-user-units"
    replacement.mkdir()
    original_install = install_automation._install_unit_snapshot
    replaced = False

    def replace_then_install(directory_fd, unit, content):
        nonlocal replaced
        if not replaced:
            replaced = True
            unit_dir.replace(displaced)
            replacement.replace(unit_dir)
        original_install(directory_fd, unit, content)

    monkeypatch.setattr(
        install_automation, "_install_unit_snapshot", replace_then_install
    )
    monkeypatch.setattr(install_automation, "_checked", lambda *_args, **_kwargs: None)

    with pytest.raises(RuntimeError, match="service unit directory changed after replan"):
        install_automation.apply(stale_summary, stale_desired, root, home)

    assert replaced is True
    assert not any(unit_dir.iterdir())
    assert sorted(path.name for path in displaced.iterdir()) == sorted(
        install_automation.UNIT_SOURCES
    )


def test_unit_snapshot_interrupt_cleans_temporary_file(tmp_path, monkeypatch):
    unit_dir = tmp_path / "units"
    unit_dir.mkdir()
    descriptor = os.open(unit_dir, os.O_RDONLY | os.O_DIRECTORY)
    original_write = install_automation.os.write

    def interrupt_write(target_fd, content):
        original_write(target_fd, content[:1])
        raise KeyboardInterrupt

    monkeypatch.setattr(install_automation.os, "write", interrupt_write)
    try:
        with pytest.raises(KeyboardInterrupt):
            install_automation._install_unit_snapshot(
                descriptor, "example.service", b"unit contents\n"
            )
    finally:
        os.close(descriptor)

    assert list(unit_dir.iterdir()) == []


def test_unit_snapshot_preserves_unexpected_directory_target(tmp_path):
    unit_dir = tmp_path / "units"
    target = unit_dir / "example.service"
    target.mkdir(parents=True)
    descriptor = os.open(unit_dir, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(RuntimeError, match="could not install service unit"):
            install_automation._install_unit_snapshot(
                descriptor, target.name, b"unit contents\n"
            )
    finally:
        os.close(descriptor)

    assert target.is_dir()
    assert list(target.iterdir()) == []
    assert [path for path in unit_dir.iterdir() if path.name != target.name] == []


def test_unit_source_changed_during_descriptor_read_is_rejected(tmp_path, monkeypatch):
    root, _home = _repo(tmp_path)
    relative = next(iter(install_automation.UNIT_SOURCES.values()))
    source = root / relative
    source_inode = source.stat().st_ino
    original_read = install_automation.os.read
    changed = False

    def read_then_change(descriptor, size):
        nonlocal changed
        chunk = original_read(descriptor, size)
        if chunk and not changed and os.fstat(descriptor).st_ino == source_inode:
            changed = True
            source.write_text("changed during read\n")
        return chunk

    monkeypatch.setattr(install_automation.os, "read", read_then_change)

    with pytest.raises(RuntimeError, match="service unit source changed"):
        install_automation._read_unit_source(root, relative)

    assert changed is True


def test_apply_fails_if_installed_state_does_not_converge(tmp_path, monkeypatch):
    root, home = _repo(tmp_path)
    monkeypatch.setattr(install_automation, "_read_crontab", lambda: "")
    summary, desired = install_automation.plan(root, home)
    monkeypatch.setattr(install_automation, "_checked", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        install_automation,
        "_install_unit_snapshot",
        lambda *_args, **_kwargs: None,
    )

    with pytest.raises(RuntimeError, match="installed service units do not match"):
        install_automation.apply(summary, desired, root, home)
