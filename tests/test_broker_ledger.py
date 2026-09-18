"""Durable broker lifecycle and uncertain-submission tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pytest

from engine.lib import db
from server import broker_ledger, broker_risk, broker_submission
from server.broker_contract import (
    BrokerFill,
    BrokerIdempotencyConflict,
    BrokerOrder,
    BrokerRiskRejected,
    BrokerStateError,
    BrokerSubmissionUncertain,
    SubmitOrderRequest,
)
from server.simulator_broker_adapter import SimulatorBrokerAdapter

SIGNAL_DATE = date(2026, 9, 11)
NOW = datetime(2026, 9, 11, 14, 30, tzinfo=timezone.utc)


def _request(*, key="intent-1", quantity=2.0):
    return SubmitOrderRequest(
        idempotency_key=key,
        account_id="paper-account",
        symbol="SPY",
        side="buy",
        quantity=quantity,
        signal_date=SIGNAL_DATE,
    )


def _order(request=None):
    request = request or _request()
    return BrokerOrder(
        broker_order_id="paper-order:1",
        idempotency_key=request.idempotency_key,
        account_id=request.account_id,
        symbol=request.symbol,
        side=request.side,
        quantity=request.quantity,
        signal_date=request.signal_date,
        status="pending",
        rejection_reason=None,
    )


def _fill():
    return BrokerFill(
        execution_id="paper-fill:1",
        broker_order_id="paper-order:1",
        idempotency_key="intent-1",
        account_id="paper-account",
        symbol="SPY",
        side="buy",
        quantity=2.0,
        occurred_on=date(2026, 9, 14),
        reference_price=500.0,
        price=500.5,
        total_cost_bps=10.0,
    )


def _risk_decision(
    request,
    *,
    passed=True,
    observed_at=NOW,
    policy_update=None,
    snapshot_update=None,
):
    policy = broker_risk.RiskPolicy(
        policy_id="paper-risk-v1",
        account_id=request.account_id,
        strategy_id="test-strategy",
        release_sha256="a" * 64,
        strategy_config_sha256="b" * 64,
        execution_profile_id="baseline-v1",
        execution_profile_sha256="c" * 64,
        allowed_symbols=("SPY",),
        capital_ceiling=10_000.0,
        max_gross_exposure=10_000.0,
        max_position_fraction=0.5,
        max_order_notional=5_000.0,
        max_daily_turnover=10_000.0,
        max_daily_orders=5,
        max_participation=0.01,
        max_daily_loss_fraction=0.02,
        max_drawdown_fraction=0.10,
        max_reference_deviation_fraction=0.02,
        max_quote_age_seconds=60,
        max_reconciliation_age_seconds=60,
        decision_ttl_seconds=30,
    )
    policy = replace(policy, **(policy_update or {}))
    identity = broker_risk.RiskIdentity(
        policy_id=policy.policy_id,
        strategy_id=policy.strategy_id,
        release_sha256=policy.release_sha256,
        strategy_config_sha256=policy.strategy_config_sha256,
        execution_profile_id=policy.execution_profile_id,
        execution_profile_sha256=policy.execution_profile_sha256,
    )
    snapshot = broker_risk.PreTradeSnapshot(
        as_of=request.signal_date,
        quote_date=request.signal_date,
        observed_at=observed_at,
        quote_at=observed_at - timedelta(seconds=5),
        reconciliation_at=observed_at - timedelta(seconds=2),
        account_snapshot_sha256="d" * 64,
        reconciliation_sha256="e" * 64,
        market_state_sha256="f" * 64,
        performance_state_sha256="1" * 64,
        operational_control_sha256="0" * 64,
        quote_price=100.0,
        reference_price=100.0,
        median_dollar_volume=1_000_000.0,
        account_active=True,
        margin_enabled=False,
        instrument_type="etf",
        instrument_active=True,
        instrument_liquid=True,
        instrument_quarantined=False,
        market_session_open=True,
        clock_synchronized=True,
        storage_healthy=True,
        broker_healthy=True,
        reconciled=passed,
        operational_halt=False,
        corporate_action_clear=True,
        currency="USD",
        cash=10_000.0,
        buying_power=10_000.0,
        equity=10_000.0,
        gross_exposure=0.0,
        symbol_exposure=0.0,
        held_quantity=10.0,
        pending_sell_quantity=0.0,
        reserved_buy_notional=0.0,
        reserved_symbol_buy_notional=0.0,
        reserved_turnover_notional=0.0,
        reserved_order_count=0,
        daily_turnover=0.0,
        daily_order_count=0,
        daily_pnl=0.0,
        drawdown_fraction=0.0,
    )
    snapshot = replace(snapshot, **(snapshot_update or {}))
    return broker_risk.evaluate(policy, identity, request, snapshot)


class _Adapter:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = 0

    def submit_order(self, request):
        self.calls += 1
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


def test_intent_and_acknowledgement_are_immutable_and_replay_safe(con):
    broker_ledger.init_broker_ledger_schema(con)
    request = _request()
    with db.transaction(con):
        assert broker_ledger.begin_submission(con, request, now=NOW) == "uncertain"
    with db.transaction(con):
        broker_ledger.acknowledge_submission(con, request, _order(request), now=NOW)
    with db.transaction(con):
        broker_ledger.acknowledge_submission(con, request, _order(request), now=NOW)

    assert broker_ledger.submission_state(con, request.idempotency_key) == "acknowledged"
    assert broker_ledger.acknowledged_order(con, request.idempotency_key) == _order(request)
    assert con.execute("SELECT COUNT(*) FROM broker_intents").fetchone() == (1,)
    assert con.execute(
        "SELECT event_sequence, event_type FROM broker_submission_events ORDER BY event_sequence"
    ).fetchall() == [
        (1, "submission_started"),
        (2, "submission_acknowledged"),
    ]

    with pytest.raises(BrokerIdempotencyConflict, match="conflicts"):
        broker_ledger.record_intent(con, _request(quantity=3.0), now=NOW)


def test_started_submission_remains_uncertain_and_blocks_reentry(con):
    broker_ledger.init_broker_ledger_schema(con)
    request = _request()
    with db.transaction(con):
        broker_ledger.begin_submission(con, request, now=NOW)

    with pytest.raises(BrokerSubmissionUncertain, match="requires reconciliation"):
        with db.transaction(con):
            broker_ledger.begin_submission(con, request, now=NOW)

    assert broker_ledger.submission_state(con, request.idempotency_key) == "uncertain"


def test_submit_once_replays_acknowledged_order_without_adapter_call(con):
    request = _request()
    adapter = _Adapter(_order(request))

    decision = _risk_decision(request)
    first = broker_submission.submit_once(
        con, adapter, request, risk_decision=decision, now=NOW
    )
    replay = broker_submission.submit_once(
        con,
        adapter,
        request,
        risk_decision=decision,
        now=NOW + timedelta(minutes=10),
    )

    assert first == replay == _order(request)
    assert adapter.calls == 1
    assert broker_ledger.submission_state(con, request.idempotency_key) == "acknowledged"


def test_submit_once_failure_persists_uncertainty_and_never_blind_retries(con):
    request = _request()
    adapter = _Adapter(TimeoutError("provider timeout"))
    decision = _risk_decision(request)

    with pytest.raises(TimeoutError, match="provider timeout"):
        broker_submission.submit_once(
            con, adapter, request, risk_decision=decision, now=NOW
        )
    assert broker_ledger.submission_state(con, request.idempotency_key) == "uncertain"

    with pytest.raises(BrokerSubmissionUncertain, match="requires reconciliation"):
        broker_submission.submit_once(
            con,
            adapter,
            request,
            risk_decision=decision,
            now=NOW + timedelta(minutes=10),
        )
    assert adapter.calls == 1


def test_mismatched_adapter_acknowledgement_leaves_uncertain(con):
    request = _request()
    adapter = _Adapter(replace(_order(request), quantity=3.0))

    with pytest.raises(BrokerStateError, match="does not match intent"):
        broker_submission.submit_once(
            con,
            adapter,
            request,
            risk_decision=_risk_decision(request),
            now=NOW,
        )

    assert adapter.calls == 1
    assert broker_ledger.submission_state(con, request.idempotency_key) == "uncertain"
    assert broker_ledger.acknowledged_order(con, request.idempotency_key) is None


def test_malformed_adapter_acknowledgement_leaves_uncertain(con):
    request = _request()
    adapter = _Adapter({"not": "a broker order"})

    with pytest.raises(BrokerStateError, match="invalid order acknowledgement"):
        broker_submission.submit_once(
            con,
            adapter,
            request,
            risk_decision=_risk_decision(request),
            now=NOW,
        )

    assert adapter.calls == 1
    assert broker_ledger.submission_state(con, request.idempotency_key) == "uncertain"
    assert broker_ledger.acknowledged_order(con, request.idempotency_key) is None


def test_execution_observation_is_append_only_with_exact_replay(con):
    broker_ledger.init_broker_ledger_schema(con)
    fill = _fill()

    first = broker_ledger.record_execution(con, fill, now=NOW)
    replay = broker_ledger.record_execution(con, fill, now=NOW)

    assert first == replay
    assert con.execute("SELECT COUNT(*) FROM broker_executions").fetchone() == (1,)
    with pytest.raises(BrokerStateError, match="conflicts"):
        broker_ledger.record_execution(con, replace(fill, price=501.0), now=NOW)


def test_order_observation_is_append_only_and_retains_status_payload(con):
    broker_ledger.init_broker_ledger_schema(con)
    order = _order()
    first = broker_ledger.record_order_observation(
        con,
        observation_key="order-observation-1",
        order=order,
        now=NOW,
    )
    replay = broker_ledger.record_order_observation(
        con,
        observation_key="order-observation-1",
        order=order,
        now=NOW,
    )

    assert first == replay
    payload = con.execute(
        "SELECT order_payload FROM broker_order_observations"
    ).fetchone()[0]
    assert '"status":"pending"' in payload
    with pytest.raises(BrokerStateError, match="conflicts"):
        broker_ledger.record_order_observation(
            con,
            observation_key="order-observation-1",
            order=replace(
                order,
                status="cancelled",
                rejection_reason="cancelled by test",
            ),
            now=NOW,
        )


def test_reconciliation_is_immutable_and_match_requires_equal_state(con):
    broker_ledger.init_broker_ledger_schema(con)
    state = {"cash": 1000.0, "positions": []}
    broker_ledger.record_reconciliation(
        con,
        reconciliation_key="recon-1",
        account_id="paper-account",
        status="match",
        expected=state,
        observed=state,
        detail="account state matched",
        now=NOW,
    )
    broker_ledger.record_reconciliation(
        con,
        reconciliation_key="recon-1",
        account_id="paper-account",
        status="match",
        expected=state,
        observed=state,
        detail="account state matched",
        now=NOW,
    )
    assert con.execute("SELECT COUNT(*) FROM broker_reconciliations").fetchone() == (1,)
    expected_payload, observed_payload = con.execute(
        "SELECT expected_payload, observed_payload FROM broker_reconciliations"
    ).fetchone()
    assert expected_payload == observed_payload == '{"cash":1000.0,"positions":[]}'

    with pytest.raises(ValueError, match="requires equal"):
        broker_ledger.record_reconciliation(
            con,
            reconciliation_key="recon-2",
            account_id="paper-account",
            status="match",
            expected=state,
            observed={"cash": 999.0, "positions": []},
            detail="incorrect match",
            now=NOW,
        )
    with pytest.raises(BrokerStateError, match="conflicts"):
        broker_ledger.record_reconciliation(
            con,
            reconciliation_key="recon-1",
            account_id="paper-account",
            status="difference",
            expected=state,
            observed={"cash": 999.0, "positions": []},
            detail="changed result",
            now=NOW,
        )


def test_reconciliation_difference_rows_require_parent_and_consistent_status(con):
    broker_ledger.init_broker_ledger_schema(con)
    difference = (
        {
            "classification": "account_cash",
            "key": "account",
            "field": "cash",
            "expected": 1000.0,
            "observed": 999.0,
        },
    )
    with pytest.raises(BrokerStateError, match="result is unavailable"):
        broker_ledger.record_reconciliation_differences(
            con,
            reconciliation_key="missing-recon",
            differences=difference,
            now=NOW,
        )

    broker_ledger.record_reconciliation(
        con,
        reconciliation_key="matching-recon",
        account_id="paper-account",
        status="match",
        expected={"cash": 1000.0},
        observed={"cash": 1000.0},
        detail="matched",
        now=NOW,
    )
    with pytest.raises(BrokerStateError, match="conflicts with result status"):
        broker_ledger.record_reconciliation_differences(
            con,
            reconciliation_key="matching-recon",
            differences=difference,
            now=NOW,
        )


def test_corrupt_acknowledgement_payload_fails_closed(con):
    broker_ledger.init_broker_ledger_schema(con)
    request = _request()
    with db.transaction(con):
        broker_ledger.begin_submission(con, request, now=NOW)
    with db.transaction(con):
        broker_ledger.acknowledge_submission(con, request, _order(request), now=NOW)
    con.execute(
        "UPDATE broker_submission_events SET order_payload = '{}' "
        "WHERE idempotency_key = ? AND event_sequence = 2",
        [request.idempotency_key],
    )

    with pytest.raises(BrokerStateError, match="payload is invalid"):
        broker_ledger.acknowledged_order(con, request.idempotency_key)


def test_submit_once_rejects_conflicting_replay_before_adapter_call(con):
    original = _request()
    adapter = _Adapter(_order(original))
    broker_submission.submit_once(
        con,
        adapter,
        original,
        risk_decision=_risk_decision(original),
        now=NOW,
    )

    with pytest.raises(BrokerIdempotencyConflict, match="conflicts"):
        conflicting = _request(quantity=3.0)
        broker_submission.submit_once(
            con,
            adapter,
            conflicting,
            risk_decision=_risk_decision(conflicting),
            now=NOW,
        )

    assert adapter.calls == 1


def test_coordinator_integrates_with_simulator_without_agent_or_fill_authority(con):
    con.execute(
        "INSERT INTO portfolios (id, name, strategy, config, created, active, "
        "cash, initial_cash, execution_profile) "
        "VALUES ('paper-account', 'Paper', 'none', '{}', ?, TRUE, "
        "39000, 39000, 'baseline_v1')",
        [SIGNAL_DATE],
    )
    request = _request()
    adapter = SimulatorBrokerAdapter(con)

    decision = _risk_decision(request)
    order = broker_submission.submit_once(
        con, adapter, request, risk_decision=decision, now=NOW
    )
    replay = broker_submission.submit_once(
        con,
        adapter,
        request,
        risk_decision=decision,
        now=NOW + timedelta(minutes=10),
    )

    assert order == replay
    assert order.broker_order_id == "sim-order:1"
    assert order.idempotency_key == "intent-1"
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone() == (1,)
    assert con.execute("SELECT COUNT(*) FROM sim_fills").fetchone() == (0,)


def test_failed_risk_is_retained_and_stops_before_submission_event(con):
    request = _request()
    adapter = _Adapter(_order(request))

    with pytest.raises(BrokerRiskRejected, match="risk rejected"):
        broker_submission.submit_once(
            con,
            adapter,
            request,
            risk_decision=_risk_decision(request, passed=False),
            now=NOW,
        )

    assert adapter.calls == 0
    assert con.execute("SELECT COUNT(*) FROM broker_risk_decisions").fetchone() == (1,)
    assert con.execute("SELECT COUNT(*) FROM broker_submission_events").fetchone() == (0,)


@pytest.mark.parametrize(
    "snapshot_update",
    [
        {"quote_at": NOW - timedelta(seconds=61)},
        {"reconciled": False},
        {"operational_halt": True},
        {"corporate_action_clear": False},
        {"reserved_buy_notional": 9_900.0},
        {"reserved_turnover_notional": 9_900.0},
        {"reserved_order_count": 5},
        {"daily_pnl": -300.0},
        {"drawdown_fraction": 0.11},
    ],
)
def test_risk_faults_stop_before_submission_boundary(con, snapshot_update):
    request = _request()
    adapter = _Adapter(_order(request))

    with pytest.raises(BrokerRiskRejected, match="risk rejected"):
        broker_submission.submit_once(
            con,
            adapter,
            request,
            risk_decision=_risk_decision(
                request,
                snapshot_update=snapshot_update,
            ),
            now=NOW,
        )

    assert adapter.calls == 0
    assert con.execute("SELECT COUNT(*) FROM broker_risk_decisions").fetchone() == (1,)
    assert con.execute("SELECT COUNT(*) FROM broker_submission_events").fetchone() == (0,)


def test_expired_risk_stops_before_submission_event_or_adapter_call(con):
    request = _request()
    adapter = _Adapter(_order(request))

    with pytest.raises(BrokerRiskRejected, match="decision expired"):
        broker_submission.submit_once(
            con,
            adapter,
            request,
            risk_decision=_risk_decision(request),
            now=NOW + timedelta(seconds=30),
        )

    assert adapter.calls == 0
    assert con.execute("SELECT COUNT(*) FROM broker_risk_decisions").fetchone() == (1,)
    assert con.execute("SELECT COUNT(*) FROM broker_submission_events").fetchone() == (0,)


def test_expired_risk_cannot_be_replaced_for_the_same_intent_key(con):
    request = _request()
    adapter = _Adapter(_order(request))
    expired = _risk_decision(request)

    with pytest.raises(BrokerRiskRejected, match="decision expired"):
        broker_submission.submit_once(
            con,
            adapter,
            request,
            risk_decision=expired,
            now=NOW + timedelta(seconds=30),
        )

    replacement = _risk_decision(
        request,
        observed_at=NOW + timedelta(seconds=31),
    )
    with pytest.raises(BrokerStateError, match="risk decision conflicts"):
        broker_submission.submit_once(
            con,
            adapter,
            request,
            risk_decision=replacement,
            now=NOW + timedelta(seconds=31),
        )

    assert adapter.calls == 0
    assert con.execute("SELECT COUNT(*) FROM broker_risk_decisions").fetchone() == (1,)
    assert con.execute("SELECT COUNT(*) FROM broker_submission_events").fetchone() == (0,)


def test_missing_or_duplicate_submission_events_fail_closed(con):
    broker_ledger.init_broker_ledger_schema(con)
    request = _request()
    intent_sha256 = broker_ledger.record_intent(con, request, now=NOW)
    con.execute(
        "INSERT INTO broker_submission_events "
        "(idempotency_key, event_sequence, account_id, intent_sha256, event_type, "
        "occurred_at) VALUES (?, 2, ?, ?, 'submission_acknowledged', ?)",
        [request.idempotency_key, request.account_id, intent_sha256, NOW],
    )
    with pytest.raises(BrokerStateError, match="sequence is invalid"):
        broker_ledger.submission_state(con, request.idempotency_key)

    con.execute("DELETE FROM broker_submission_events")
    con.execute(
        "INSERT INTO broker_submission_events "
        "(idempotency_key, event_sequence, account_id, intent_sha256, event_type, "
        "occurred_at) VALUES (?, 1, ?, ?, 'submission_started', ?), "
        "(?, 2, ?, ?, 'submission_started', ?)",
        [
            request.idempotency_key,
            request.account_id,
            intent_sha256,
            NOW,
            request.idempotency_key,
            request.account_id,
            intent_sha256,
            NOW,
        ],
    )
    with pytest.raises(BrokerStateError, match="sequence is invalid"):
        broker_ledger.submission_state(con, request.idempotency_key)


def test_submission_state_rejects_tampered_or_missing_intent(con):
    broker_ledger.init_broker_ledger_schema(con)
    request = _request()
    with db.transaction(con):
        broker_ledger.begin_submission(con, request, now=NOW)
    con.execute(
        "UPDATE broker_intents SET intent_payload = '{}' WHERE idempotency_key = ?",
        [request.idempotency_key],
    )
    with pytest.raises(BrokerStateError, match="intent payload is invalid"):
        broker_ledger.submission_state(con, request.idempotency_key)

    con.execute("DELETE FROM broker_intents")
    with pytest.raises(BrokerStateError, match="has no intent"):
        broker_ledger.submission_state(con, request.idempotency_key)
