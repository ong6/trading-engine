"""Runtime/control bindings are process-local, verified, and non-authorizing."""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict
from datetime import datetime, timezone

import pytest

from engine.lib.provenance import canonical_sha256
from server import broker_paper_runtime, broker_risk_control

NOW = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)


def _halt(con):
    return broker_risk_control.record_halt(
        con,
        halt_key="paper-runtime-halt-1",
        account_id="paper-account",
        reason="explicit default halt before any authority design",
        now=NOW,
    )


def test_loader_derives_current_epoch_and_twice_verified_control(con):
    status = _halt(con)

    first = broker_paper_runtime.load_runtime_control(con, "paper-account")
    second = broker_paper_runtime.load_runtime_control(con, "paper-account")

    assert first == second
    assert first.account_id == "paper-account"
    assert first.runtime_epoch_sha256 == broker_paper_runtime.runtime_epoch_sha256()
    assert first.control.event_count == status.event_count
    assert first.control.latest_event_sha256 == status.latest_event_sha256
    assert first.control_status_sha256 == canonical_sha256(asdict(status))
    assert len(first.evidence_sha256) == 64
    assert first.execution_authority == "none"


def test_runtime_epoch_changes_in_a_new_process_and_is_not_environment_driven():
    code = (
        "import json; "
        "from server.broker_paper_runtime import runtime_epoch_sha256; "
        "print(json.dumps(runtime_epoch_sha256()))"
    )
    first = subprocess.run(
        [".venv/bin/python", "-c", code],
        check=True,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "PAPER_RUNTIME_EPOCH": "attacker-value"},
    ).stdout
    second = subprocess.run(
        [".venv/bin/python", "-c", code],
        check=True,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "PAPER_RUNTIME_EPOCH": "attacker-value"},
    ).stdout

    assert json.loads(first) != json.loads(second)
    assert json.loads(first) != "attacker-value"
    assert json.loads(second) != "attacker-value"


def test_loader_rejects_missing_control_anchor(con):
    with pytest.raises(
        broker_paper_runtime.PaperRuntimeError,
        match="requires a verified halt-chain anchor",
    ):
        broker_paper_runtime.load_runtime_control(con, "paper-account")


def test_loader_rejects_tampered_control_chain(con):
    _halt(con)
    con.execute(
        "UPDATE broker_risk_control_events SET reason = 'tampered' "
        "WHERE account_id = 'paper-account'"
    )

    with pytest.raises(
        broker_paper_runtime.PaperRuntimeError,
        match="verification failed",
    ):
        broker_paper_runtime.load_runtime_control(con, "paper-account")


def test_loader_rejects_control_change_between_reads(con, monkeypatch):
    first = _halt(con)
    second = broker_risk_control.RiskControlStatus(
        schema_version=first.schema_version,
        account_id=first.account_id,
        halted=True,
        reason="later halt",
        event_count=first.event_count + 1,
        latest_event_sha256="f" * 64,
    )
    values = iter((first, second))
    monkeypatch.setattr(
        broker_paper_runtime.broker_risk_control,
        "status",
        lambda *_args: next(values),
    )

    with pytest.raises(
        broker_paper_runtime.PaperRuntimeError,
        match="changed during capture",
    ):
        broker_paper_runtime.load_runtime_control(con, "paper-account")


def test_module_has_no_writer_or_authority_surface():
    assert {
        "append",
        "activate",
        "consume",
        "persist",
        "record_halt",
        "reserve",
        "submit",
        "renew",
        "revoke",
    }.isdisjoint(vars(broker_paper_runtime))
    assert set(broker_paper_runtime.load_runtime_control.__globals__).isdisjoint(
        {
            "http",
            "requests",
            "urllib",
            "socket",
            "BrokerAdapter",
        }
    )
