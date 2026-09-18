"""Persistent shadow scheduling is explicit, hash-bound, and fail closed."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import duckdb
import pytest

from server import agent_policy, agent_shadow_schedule

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)


def _registration(path):
    path.write_text(agent_policy.REGISTRATION_PATH.read_text())


def test_missing_control_is_disabled_without_invoking_runner(tmp_path, monkeypatch):
    registration = tmp_path / "registration.json"
    _registration(registration)
    monkeypatch.setattr(
        agent_shadow_schedule.agent_shadow_runner,
        "run",
        lambda *_args, **_kwargs: pytest.fail("disabled schedule must not run"),
    )

    result = agent_shadow_schedule.run_scheduled(
        registration_path=registration,
        control_path=tmp_path / "missing.json",
    )

    assert result == {
        "status": "disabled",
        "reason": "control_missing_or_invalid",
        "execution_authority": "none",
    }


def test_disabled_run_does_not_open_database_or_mutate_ledgers(
    tmp_path, monkeypatch
):
    registration = tmp_path / "registration.json"
    control = tmp_path / "control.json"
    _registration(registration)
    agent_shadow_schedule.set_control(
        False,
        "operator disabled shadow observation",
        registration_path=registration,
        control_path=control,
        now=NOW,
    )
    monkeypatch.setattr(
        agent_shadow_schedule.agent_shadow_runner,
        "run",
        lambda *_args, **_kwargs: pytest.fail(
            "disabled schedule must not open DuckDB or invoke Trae"
        ),
    )
    before = tuple(tmp_path.iterdir())

    result = agent_shadow_schedule.run_scheduled(
        registration_path=registration,
        control_path=control,
    )

    assert result["status"] == "disabled"
    assert tuple(tmp_path.iterdir()) == before


def test_enable_is_hash_bound_and_scheduled_run_uses_only_registration(
    tmp_path, monkeypatch
):
    registration = tmp_path / "registration.json"
    control = tmp_path / "control.json"
    _registration(registration)
    status = agent_shadow_schedule.set_control(
        True,
        "operator enabled shadow observation",
        registration_path=registration,
        control_path=control,
        now=NOW,
    )
    observed = []
    monkeypatch.setattr(
        agent_shadow_schedule.agent_shadow_runner,
        "run",
        lambda strategy, ticker, **kwargs: (
            observed.append((strategy, ticker, kwargs))
            or {"status": "no_action", "execution_authority": "none"}
        ),
    )

    result = agent_shadow_schedule.run_scheduled(
        registration_path=registration,
        control_path=control,
    )

    assert status["enabled"] is True
    assert status["execution_authority"] == "none"
    assert status["schedule"]["persistent"] is True
    assert status["retry_policy"]["decision_regeneration"] is False
    assert result == {"status": "no_action", "execution_authority": "none"}
    assert observed == [
        (
            "dual_momentum",
            "SPY",
            {
                "mode": "agent_only",
                "policy_id": "dual_momentum_agent_shadow_v1",
                "policy_path": registration,
            },
        )
    ]
    assert control.stat().st_mode & 0o777 == 0o644


def test_scheduled_invocation_replays_existing_runner_window(
    tmp_path, monkeypatch
):
    registration = tmp_path / "registration.json"
    control = tmp_path / "control.json"
    _registration(registration)
    agent_shadow_schedule.set_control(
        True,
        "operator enabled shadow observation",
        registration_path=registration,
        control_path=control,
        now=NOW,
    )
    replay = {
        "status": "no_action",
        "replayed": True,
        "execution_authority": "none",
    }
    calls = []
    monkeypatch.setattr(
        agent_shadow_schedule.agent_shadow_runner,
        "run",
        lambda strategy, ticker, **kwargs: (
            calls.append((strategy, ticker, kwargs)) or replay
        ),
    )

    assert agent_shadow_schedule.run_scheduled(
        registration_path=registration,
        control_path=control,
    ) == replay
    assert calls == [
        (
            "dual_momentum",
            "SPY",
            {
                "mode": "agent_only",
                "policy_id": "dual_momentum_agent_shadow_v1",
                "policy_path": registration,
            },
        )
    ]


def test_registration_change_disables_existing_control(tmp_path):
    registration = tmp_path / "registration.json"
    control = tmp_path / "control.json"
    _registration(registration)
    agent_shadow_schedule.set_control(
        True,
        "operator enabled shadow observation",
        registration_path=registration,
        control_path=control,
        now=NOW,
    )
    payload = json.loads(registration.read_text())
    payload["scheduled_ticker"] = "EFA"
    registration.write_text(json.dumps(payload))

    status = agent_shadow_schedule.control_status(
        registration_path=registration,
        control_path=control,
    )
    assert status["enabled"] is False
    assert status["reason"] == "control_missing_or_invalid"


def test_invalid_or_future_dated_control_fails_closed(tmp_path):
    registration = tmp_path / "registration.json"
    control = tmp_path / "control.json"
    _registration(registration)
    _registered, registration_sha256 = agent_shadow_schedule.registration(registration)
    control.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "enabled": True,
                "registration_sha256": registration_sha256,
                "reason": "future control",
                "updated_at": "2999-01-01T00:00:00Z",
            }
        )
    )

    status = agent_shadow_schedule.control_status(
        registration_path=registration,
        control_path=control,
    )

    assert status["enabled"] is False
    assert status["reason"] == "control_missing_or_invalid"


def test_disable_persists_across_process_invocations(tmp_path):
    registration = tmp_path / "registration.json"
    control = tmp_path / "control.json"
    _registration(registration)
    agent_shadow_schedule.set_control(
        False,
        "operator kill switch",
        registration_path=registration,
        control_path=control,
        now=NOW,
    )

    first = agent_shadow_schedule.control_status(
        registration_path=registration,
        control_path=control,
    )
    second = agent_shadow_schedule.control_status(
        registration_path=registration,
        control_path=control,
    )

    assert first == second
    assert first["enabled"] is False
    assert first["reason"] == "operator kill switch"


def test_systemd_units_are_bounded_and_do_not_enable_execution():
    service = (
        agent_shadow_schedule.REPO_ROOT
        / "server"
        / "trading-engine-agent-shadow.service"
    ).read_text()
    timer = (
        agent_shadow_schedule.REPO_ROOT
        / "server"
        / "trading-engine-agent-shadow.timer"
    ).read_text()

    assert "server.agent_shadow_schedule run" in service
    assert "agent_price_observations" not in service
    assert "Restart=on-failure" in service
    assert "StartLimitBurst=3" in service
    assert "Type=exec" in service
    assert "TimeoutStartSec=5min" in service
    assert "Wants=network-online.target trae-proxy.service" in service
    assert "[Install]" not in service
    assert "OnCalendar=Tue..Sat *-*-* 01:30:00 UTC" in timer
    assert "Persistent=true" in timer


def test_data_capture_has_a_separate_persistent_timer():
    root = agent_shadow_schedule.REPO_ROOT / "server"
    service = (root / "trading-engine-agent-data-capture.service").read_text()
    timer = (root / "trading-engine-agent-data-capture.timer").read_text()

    assert "Type=oneshot" in service
    assert "server.agent_price_observations capture" in service
    assert "server.agent_corporate_action_observations capture" in service
    assert "server.agent_provider_responses capture" in service
    assert "server.agent_independent_price_evidence capture" in service
    assert "agent_shadow_schedule" not in service
    assert "trae-proxy.service" not in service
    assert "[Install]" not in service
    assert "OnCalendar=Tue..Sat *-*-* 01:25:00 UTC" in timer
    assert "Persistent=true" in timer
    assert "Unit=trading-engine-agent-data-capture.service" in timer


@pytest.mark.parametrize(
    "error",
    (
        agent_shadow_schedule.ScheduleError("registration failed"),
        agent_shadow_schedule.agent_shadow_runner.ShadowRunError("runner failed"),
        agent_shadow_schedule.agent_context.ContextError("context failed"),
        agent_shadow_schedule.agent_shadow_store.IdentifierSpaceExhausted(
            "identifier failed"
        ),
        duckdb.Error("database failed"),
        OSError("filesystem failed"),
    ),
)
def test_run_cli_emits_bounded_json_for_expected_failures(monkeypatch, capsys, error):
    monkeypatch.setattr(
        agent_shadow_schedule,
        "run_scheduled",
        lambda: (_ for _ in ()).throw(error),
    )

    assert agent_shadow_schedule.main(["run"]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "failed"
    assert 0 < len(output["reason"]) <= agent_shadow_schedule.MAX_FAILURE_REASON_CHARS
    assert output["execution_authority"] == "none"


def test_registration_and_control_symlinks_fail_closed(tmp_path):
    registration = tmp_path / "registration.json"
    registration_target = tmp_path / "registration-target.json"
    _registration(registration_target)
    registration.symlink_to(registration_target)

    with pytest.raises(agent_shadow_schedule.ScheduleError, match="unavailable or invalid"):
        agent_shadow_schedule.registration(registration)

    registration.unlink()
    _registration(registration)
    control_target = tmp_path / "control-target.json"
    control_target.write_text("{}")
    control = tmp_path / "control.json"
    control.symlink_to(control_target)

    status = agent_shadow_schedule.control_status(
        registration_path=registration,
        control_path=control,
    )

    assert status["enabled"] is False
    assert status["reason"] == "control_missing_or_invalid"
    assert status["control_updated_at"] is None
