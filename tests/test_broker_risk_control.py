"""The internal broker-risk control is durable, one-way, and default halted."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import duckdb
import pytest

from server import broker_risk_control
from server.broker_contract import BrokerStateError

NOW = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)


def test_missing_state_is_halted_without_creating_schema(con):
    first = broker_risk_control.status(con, "paper-account")
    second = broker_risk_control.status(con, "paper-account")

    assert first == second == broker_risk_control.RiskControlStatus(
        schema_version=1,
        account_id="paper-account",
        halted=True,
        reason="default_halted_no_control_event",
        event_count=0,
        latest_event_sha256=None,
    )
    assert con.execute(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_name = 'broker_risk_control_events'"
    ).fetchone() == (0,)


def test_halt_events_are_append_only_hash_chained_and_survive_reopen(tmp_path):
    database = tmp_path / "control.duckdb"

    con = duckdb.connect(str(database))
    try:
        first = broker_risk_control.record_halt(
            con,
            halt_key="halt-1",
            account_id="paper-account",
            reason="operator emergency halt",
            now=NOW,
        )
        replay = broker_risk_control.record_halt(
            con,
            halt_key="halt-1",
            account_id="paper-account",
            reason="operator emergency halt",
            now=NOW + timedelta(minutes=1),
        )
        second = broker_risk_control.record_halt(
            con,
            halt_key="halt-2",
            account_id="paper-account",
            reason="reconciliation mismatch",
            now=NOW + timedelta(minutes=2),
        )
    finally:
        con.close()

    assert first.halted is True
    assert replay == first
    assert second.halted is True
    assert second.event_count == 2
    assert second.reason == "reconciliation mismatch"
    assert second.latest_event_sha256 is not None

    con = duckdb.connect(str(database), read_only=True)
    try:
        restarted = broker_risk_control.status(con, "paper-account")
        rows = con.execute(
            "SELECT event_sequence, prior_event_sha256, event_sha256 "
            "FROM broker_risk_control_events ORDER BY event_sequence"
        ).fetchall()
    finally:
        con.close()
    assert restarted == second
    assert rows[0][1] is None
    assert rows[1][1] == rows[0][2]


def test_halt_key_conflict_and_tampering_fail_closed(con):
    broker_risk_control.record_halt(
        con,
        halt_key="halt-1",
        account_id="paper-account",
        reason="risk breach",
        now=NOW,
    )
    with pytest.raises(BrokerStateError, match="conflicts"):
        broker_risk_control.record_halt(
            con,
            halt_key="halt-1",
            account_id="paper-account",
            reason="different reason",
            now=NOW,
        )

    con.execute(
        "UPDATE broker_risk_control_events SET reason = 'tampered' "
        "WHERE halt_key = 'halt-1'"
    )
    with pytest.raises(BrokerStateError, match="event is invalid"):
        broker_risk_control.status(con, "paper-account")


def test_halt_event_timestamp_cannot_move_backwards(con):
    broker_risk_control.record_halt(
        con,
        halt_key="halt-1",
        account_id="paper-account",
        reason="first halt",
        now=NOW,
    )

    with pytest.raises(ValueError, match="precedes"):
        broker_risk_control.record_halt(
            con,
            halt_key="halt-2",
            account_id="paper-account",
            reason="backdated halt",
            now=NOW - timedelta(seconds=1),
        )

    assert broker_risk_control.status(con, "paper-account").event_count == 1


def test_module_exposes_no_enable_clear_or_lease_operation():
    assert {
        "enable",
        "disable",
        "clear",
        "set_control",
        "grant",
        "grant_lease",
        "authorize",
    }.isdisjoint(vars(broker_risk_control))


def test_cli_is_an_independent_one_way_halt_path(tmp_path, capsys):
    database = tmp_path / "control.duckdb"

    assert broker_risk_control.main(
        [
            "--db",
            str(database),
            "halt",
            "--account",
            "paper-account",
            "--halt-key",
            "operator-halt-1",
            "--reason",
            "independent operator halt",
        ]
    ) == 0
    halted = json.loads(capsys.readouterr().out)
    assert halted["halted"] is True
    assert halted["reason"] == "independent operator halt"
    assert halted["execution_authority"] == "none"

    assert broker_risk_control.main(
        [
            "--db",
            str(database),
            "status",
            "--account",
            "paper-account",
        ]
    ) == 0
    restarted = json.loads(capsys.readouterr().out)
    assert restarted == halted


def test_cli_has_no_enable_or_clear_command():
    with pytest.raises(SystemExit) as error:
        broker_risk_control.main(["enable"])
    assert error.value.code != 0
