"""Startup assessment proves reconciled, submission-disabled recovery state."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from engine.lib import db
from engine.lib.provenance import canonical_sha256
from server import (
    broker_emergency_stop,
    broker_ledger,
    broker_reconciliation,
    broker_risk_control,
    broker_startup_readiness,
    broker_submission_resolution,
)
from server.broker_contract import BrokerOrder, BrokerStateError
from tests.test_broker_risk_snapshot import ACCOUNT, NOW, _Adapter, _request


def _record_reconciliation(con, adapter, *, status="match", observed_at=NOW):
    snapshot = broker_reconciliation.capture_snapshot(adapter, ACCOUNT)
    expected = snapshot.comparable_payload()
    observed = (
        expected
        if status == "match"
        else {**expected, "account": {**expected["account"], "cash": 4_999.0}}
    )
    broker_ledger.init_broker_ledger_schema(con)
    broker_ledger.record_reconciliation(
        con,
        reconciliation_key=f"startup-{status}",
        account_id=ACCOUNT,
        status=status,
        expected=expected,
        observed=observed,
        detail=f"{status} startup evidence",
        now=observed_at,
    )


def test_startup_assessment_can_only_report_reconciled_and_halted(con):
    adapter = _Adapter()
    _record_reconciliation(con, adapter, observed_at=NOW - timedelta(seconds=2))

    result = broker_startup_readiness.assess(
        con,
        adapter,
        ACCOUNT,
        reconciliation_key="startup-match",
        now=NOW,
        max_reconciliation_age_seconds=60,
    )

    assert result["status"] == "reconciled_halted"
    assert result["safe_halted"] is True
    assert result["submission_authority"] == "none"
    assert result["schema_version"] == 2
    assert result["account_active"] is True
    assert result["reconciliation_status"] == "match"
    assert result["reconciliation_age_seconds"] == 2.0
    assert result["max_reconciliation_age_seconds"] == 60
    assert result["operational_control"]["halted"] is True
    assert result["uncertain_submission_keys"] == []
    assert result["resolved_submissions"] == []
    assert result["resolved_open_submission_keys"] == []
    assert result["uncertain_cancellation_keys"] == []
    assert result["incomplete_emergency_stop_keys"] == []
    assert result["reasons"] == []
    body = {key: value for key, value in result.items() if key != "assessment_sha256"}
    assert result["assessment_sha256"] == canonical_sha256(body)
    assert (
        broker_startup_readiness.verify_assessment(
            result,
            account_id=ACCOUNT,
            trusted_assessment_sha256=result["assessment_sha256"],
        )
        == result
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("account_active", False),
        ("reconciliation_status", "difference"),
        ("reconciliation_age_seconds", 61.0),
        ("safe_halted", False),
        ("submission_authority", "paper"),
    ],
)
def test_startup_verifier_rejects_rehashed_semantic_forgery(
    con,
    field,
    value,
):
    adapter = _Adapter()
    _record_reconciliation(con, adapter, observed_at=NOW - timedelta(seconds=2))
    result = broker_startup_readiness.assess(
        con,
        adapter,
        ACCOUNT,
        reconciliation_key="startup-match",
        now=NOW,
        max_reconciliation_age_seconds=60,
    )
    forged = {**result, field: value}
    body = {
        key: item
        for key, item in forged.items()
        if key != "assessment_sha256"
    }
    forged["assessment_sha256"] = canonical_sha256(body)

    with pytest.raises(ValueError, match="startup"):
        broker_startup_readiness.verify_assessment(
            forged,
            account_id=ACCOUNT,
            trusted_assessment_sha256=forged["assessment_sha256"],
        )


@pytest.mark.parametrize(
    ("status", "observed_at", "reason"),
    [
        ("difference", NOW - timedelta(seconds=2), "reconciliation_difference"),
        ("match", NOW - timedelta(seconds=61), "reconciliation_stale_or_future"),
        ("match", NOW + timedelta(seconds=1), "reconciliation_stale_or_future"),
    ],
)
def test_startup_assessment_blocks_bad_reconciliation(
    con,
    status,
    observed_at,
    reason,
):
    adapter = _Adapter()
    _record_reconciliation(
        con,
        adapter,
        status=status,
        observed_at=observed_at,
    )

    result = broker_startup_readiness.assess(
        con,
        adapter,
        ACCOUNT,
        reconciliation_key=f"startup-{status}",
        now=NOW,
        max_reconciliation_age_seconds=60,
    )

    assert result["status"] == "blocked"
    assert result["safe_halted"] is False
    assert result["submission_authority"] == "none"
    assert reason in result["reasons"]


def test_startup_assessment_blocks_uncertain_submission(con):
    adapter = _Adapter()
    _record_reconciliation(con, adapter, observed_at=NOW - timedelta(seconds=2))
    request = _request()
    with db.transaction(con):
        broker_ledger.begin_submission(con, request, now=NOW)

    result = broker_startup_readiness.assess(
        con,
        adapter,
        ACCOUNT,
        reconciliation_key="startup-match",
        now=NOW,
        max_reconciliation_age_seconds=60,
    )

    assert result["status"] == "blocked"
    assert result["safe_halted"] is False
    assert result["uncertain_submission_keys"] == [request.idempotency_key]
    assert "uncertain_submissions" in result["reasons"]


def test_resolved_absence_is_audited_without_remaining_ambiguous(con):
    adapter = _Adapter()
    _record_reconciliation(con, adapter, observed_at=NOW - timedelta(seconds=2))
    request = _request()
    with db.transaction(con):
        broker_ledger.begin_submission(con, request, now=NOW)
    broker_risk_control.record_halt(
        con,
        halt_key="resolved-absence-halt",
        account_id=ACCOUNT,
        reason="resolve startup uncertainty",
        now=NOW + timedelta(seconds=1),
    )
    resolution = broker_submission_resolution.resolve_uncertain(
        con,
        adapter,
        request.idempotency_key,
        resolution_key="resolved-absence",
        now=NOW + timedelta(seconds=2),
    )

    result = broker_startup_readiness.assess(
        con,
        adapter,
        ACCOUNT,
        reconciliation_key="startup-match",
        now=NOW + timedelta(seconds=3),
        max_reconciliation_age_seconds=60,
    )

    assert result["status"] == "reconciled_halted"
    assert result["safe_halted"] is True
    assert result["uncertain_submission_keys"] == []
    assert result["resolved_open_submission_keys"] == []
    assert result["resolved_submissions"] == [
        {
            "idempotency_key": request.idempotency_key,
            "resolution_key": "resolved-absence",
            "outcome": "not_observed_burned",
            "resolution_sha256": resolution["resolution_sha256"],
            "retry_permitted": False,
        }
    ]
    assert result["submission_authority"] == "none"


def test_resolved_open_order_remains_a_startup_blocker(con):
    adapter = _Adapter()
    request = _request()
    adapter.orders = (
        *adapter.orders,
        BrokerOrder(
            broker_order_id="paper-order:resolved-open",
            idempotency_key=request.idempotency_key,
            account_id=request.account_id,
            symbol=request.symbol,
            side=request.side,
            quantity=request.quantity,
            signal_date=request.signal_date,
            status="pending",
            rejection_reason=None,
        ),
    )
    _record_reconciliation(con, adapter, observed_at=NOW - timedelta(seconds=2))
    with db.transaction(con):
        broker_ledger.begin_submission(con, request, now=NOW)
    broker_risk_control.record_halt(
        con,
        halt_key="resolved-open-halt",
        account_id=ACCOUNT,
        reason="resolve startup uncertainty",
        now=NOW + timedelta(seconds=1),
    )
    broker_submission_resolution.resolve_uncertain(
        con,
        adapter,
        request.idempotency_key,
        resolution_key="resolved-open",
        now=NOW + timedelta(seconds=2),
    )

    result = broker_startup_readiness.assess(
        con,
        adapter,
        ACCOUNT,
        reconciliation_key="startup-match",
        now=NOW + timedelta(seconds=3),
        max_reconciliation_age_seconds=60,
    )

    assert result["status"] == "blocked"
    assert result["safe_halted"] is False
    assert result["uncertain_submission_keys"] == []
    assert result["resolved_open_submission_keys"] == [request.idempotency_key]
    assert "resolved_open_submissions" in result["reasons"]
    assert result["submission_authority"] == "none"


def test_startup_assessment_blocks_uncertain_cancellation_and_incomplete_stop(con):
    adapter = _Adapter()
    _record_reconciliation(con, adapter, observed_at=NOW - timedelta(seconds=2))
    order = adapter.orders[0]
    halt_key = "startup-emergency-halt"
    broker_risk_control.record_halt(
        con,
        halt_key=halt_key,
        account_id=ACCOUNT,
        reason="startup cancellation drill",
        now=NOW - timedelta(seconds=1),
    )
    start_payload = broker_emergency_stop._start_payload(
        halt_key=halt_key,
        account_id=ACCOUNT,
        reason="startup cancellation drill",
        halt_event_sha256=broker_risk_control.halt_event_sha256(
            con,
            halt_key=halt_key,
            account_id=ACCOUNT,
        ),
        snapshot=broker_reconciliation.capture_snapshot(adapter, ACCOUNT),
        occurred_at=(NOW - timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
    )
    with db.transaction(con):
        broker_ledger.record_emergency_stop_event(
            con,
            halt_key=halt_key,
            account_id=ACCOUNT,
            event_type="emergency_stop_started",
            payload=start_payload,
            now=NOW - timedelta(seconds=1),
        )
        broker_ledger.begin_cancellation(
            con,
            cancellation_key=broker_emergency_stop._cancellation_key(
                halt_key,
                order,
            ),
            account_id=ACCOUNT,
            broker_order_id=order.broker_order_id,
            now=NOW - timedelta(seconds=1),
        )

    result = broker_startup_readiness.assess(
        con,
        adapter,
        ACCOUNT,
        reconciliation_key="startup-match",
        now=NOW,
        max_reconciliation_age_seconds=60,
    )

    assert result["status"] == "blocked"
    assert result["safe_halted"] is False
    assert len(result["uncertain_cancellation_keys"]) == 1
    assert result["incomplete_emergency_stop_keys"] == [halt_key]
    assert "uncertain_cancellations" in result["reasons"]
    assert "incomplete_emergency_stops" in result["reasons"]
    assert result["submission_authority"] == "none"


def test_startup_assessment_rejects_state_change_across_read_window(con):
    class _ChangingAdapter(_Adapter):
        def __init__(self):
            super().__init__()
            self.account_reads = 0

        def get_account(self, account_id):
            self.account_reads += 1
            account = super().get_account(account_id)
            if self.account_reads <= 2:
                return account
            return replace(account, cash=4_999.0, buying_power=4_999.0)

    adapter = _ChangingAdapter()
    _record_reconciliation(con, adapter, observed_at=NOW - timedelta(seconds=2))
    adapter.account_reads = 0

    with pytest.raises(BrokerStateError, match="startup reconciliation assessment"):
        broker_startup_readiness.assess(
            con,
            adapter,
            ACCOUNT,
            reconciliation_key="startup-match",
            now=NOW,
            max_reconciliation_age_seconds=60,
        )


def test_restart_preserves_halted_startup_assessment(tmp_path):
    database = tmp_path / "startup.duckdb"
    adapter = _Adapter()
    con = db.connect(database)
    try:
        _record_reconciliation(con, adapter, observed_at=NOW - timedelta(seconds=2))
        broker_risk_control.record_halt(
            con,
            halt_key="startup-halt",
            account_id=ACCOUNT,
            reason="restart must remain halted",
            now=NOW - timedelta(seconds=1),
        )
    finally:
        con.close()

    con = db.connect(database, read_only=True)
    try:
        result = broker_startup_readiness.assess(
            con,
            adapter,
            ACCOUNT,
            reconciliation_key="startup-match",
            now=NOW,
            max_reconciliation_age_seconds=60,
        )
    finally:
        con.close()

    assert result["status"] == "reconciled_halted"
    assert result["operational_control"]["reason"] == "restart must remain halted"
    assert result["submission_authority"] == "none"


def test_startup_module_has_no_mutation_or_enable_surface():
    assert {
        "submit_once",
        "submit_order",
        "cancel_order",
        "enable",
        "clear",
        "grant_lease",
        "authorize",
    }.isdisjoint(vars(broker_startup_readiness))
