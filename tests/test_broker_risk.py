"""Independent pure pre-trade risk contract tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pytest

from server import broker_ledger, broker_risk
from server.broker_contract import BrokerStateError, SubmitOrderRequest

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
SIGNAL_DATE = date(2026, 9, 14)
OBSERVED_AT = datetime(2026, 9, 14, 14, 30, 30, tzinfo=timezone.utc)


def _policy():
    return broker_risk.RiskPolicy(
        policy_id="paper-risk-v1",
        account_id="paper-account",
        strategy_id="dual-momentum",
        release_sha256=HASH_A,
        strategy_config_sha256=HASH_B,
        execution_profile_id="baseline-v1",
        execution_profile_sha256=HASH_C,
        allowed_symbols=("QQQ", "SPY"),
        capital_ceiling=10_000.0,
        max_gross_exposure=10_000.0,
        max_position_fraction=0.25,
        max_order_notional=2_000.0,
        max_daily_turnover=5_000.0,
        max_daily_orders=5,
        max_participation=0.01,
        max_daily_loss_fraction=0.02,
        max_drawdown_fraction=0.10,
        max_reference_deviation_fraction=0.02,
        max_quote_age_seconds=60,
        max_reconciliation_age_seconds=60,
        decision_ttl_seconds=30,
    )


def _identity():
    policy = _policy()
    return broker_risk.RiskIdentity(
        policy_id=policy.policy_id,
        strategy_id=policy.strategy_id,
        release_sha256=policy.release_sha256,
        strategy_config_sha256=policy.strategy_config_sha256,
        execution_profile_id=policy.execution_profile_id,
        execution_profile_sha256=policy.execution_profile_sha256,
    )


def _request(*, side="buy", quantity=10.0, symbol="SPY"):
    return SubmitOrderRequest(
        idempotency_key="risk-intent-1",
        account_id="paper-account",
        symbol=symbol,
        side=side,
        quantity=quantity,
        signal_date=SIGNAL_DATE,
    )


def _snapshot():
    return broker_risk.PreTradeSnapshot(
        as_of=SIGNAL_DATE,
        quote_date=SIGNAL_DATE,
        observed_at=OBSERVED_AT,
        quote_at=OBSERVED_AT - timedelta(seconds=5),
        reconciliation_at=OBSERVED_AT - timedelta(seconds=2),
        account_snapshot_sha256=HASH_A,
        reconciliation_sha256=HASH_B,
        market_state_sha256=HASH_C,
        performance_state_sha256="e" * 64,
        operational_control_sha256="d" * 64,
        quote_price=100.0,
        reference_price=100.5,
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
        reconciled=True,
        operational_halt=False,
        corporate_action_clear=True,
        currency="USD",
        cash=20_000.0,
        buying_power=20_000.0,
        equity=20_000.0,
        gross_exposure=2_000.0,
        symbol_exposure=1_000.0,
        held_quantity=20.0,
        pending_sell_quantity=0.0,
        reserved_buy_notional=0.0,
        reserved_symbol_buy_notional=0.0,
        reserved_turnover_notional=0.0,
        reserved_order_count=0,
        daily_turnover=500.0,
        daily_order_count=1,
        daily_pnl=-100.0,
        drawdown_fraction=0.03,
    )


def test_complete_healthy_snapshot_passes_and_is_hash_bound():
    decision = broker_risk.evaluate(
        _policy(),
        _identity(),
        _request(),
        _snapshot(),
    )

    assert broker_risk.verify(decision) == decision
    assert decision["status"] == "pass"
    assert decision["execution_authority"] == "none"
    assert decision["failed_gates"] == []
    assert tuple(gate["name"] for gate in decision["gates"]) == broker_risk.GATE_NAMES
    assert decision["computed"]["notional"] == 1_005.0
    assert decision["computed"]["participation"] == 0.001005


@pytest.mark.parametrize(
    ("identity_update", "request_update", "snapshot_update", "failed_gate"),
    [
        ({"release_sha256": "d" * 64}, {}, {}, "identity"),
        ({}, {}, {"account_active": False}, "account"),
        ({}, {}, {"margin_enabled": True}, "account"),
        ({}, {}, {"buying_power": 20_001.0}, "account"),
        ({}, {"symbol": "IWM"}, {}, "instrument"),
        ({}, {}, {"instrument_quarantined": True}, "instrument"),
        ({}, {}, {"market_session_open": False}, "market_session"),
        (
            {},
            {},
            {"observed_at": OBSERVED_AT + timedelta(days=1)},
            "market_session",
        ),
        ({}, {}, {"clock_synchronized": False}, "dependency_health"),
        ({}, {}, {"storage_healthy": False}, "dependency_health"),
        ({}, {}, {"broker_healthy": False}, "dependency_health"),
        ({}, {}, {"reconciled": False}, "reconciliation"),
        (
            {},
            {},
            {"reconciliation_at": OBSERVED_AT - timedelta(seconds=61)},
            "reconciliation",
        ),
        ({}, {}, {"operational_halt": True}, "operational_control"),
        ({}, {}, {"corporate_action_clear": False}, "corporate_action"),
        ({}, {}, {"quote_date": date(2026, 9, 11)}, "market_data"),
        (
            {},
            {},
            {"quote_at": OBSERVED_AT - timedelta(seconds=61)},
            "market_data",
        ),
        ({}, {}, {"reference_price": 103.0}, "market_data"),
        ({}, {"quantity": 21.0}, {}, "order_notional"),
        ({}, {}, {"cash": 500.0}, "cash"),
        ({}, {}, {"buying_power": 500.0}, "cash"),
        ({}, {}, {"gross_exposure": 9_500.0}, "capital_allocation"),
        ({}, {}, {"gross_exposure": 9_500.0}, "gross_exposure"),
        ({}, {}, {"reserved_buy_notional": 8_000.0}, "capital_allocation"),
        ({}, {}, {"reserved_buy_notional": 8_000.0}, "gross_exposure"),
        ({}, {}, {"reserved_buy_notional": 19_500.0}, "cash"),
        ({}, {}, {"symbol_exposure": 4_500.0}, "position_concentration"),
        (
            {},
            {},
            {"reserved_symbol_buy_notional": 3_500.0},
            "position_concentration",
        ),
        ({}, {}, {"daily_turnover": 4_500.0}, "daily_turnover"),
        ({}, {}, {"reserved_turnover_notional": 4_000.0}, "daily_turnover"),
        ({}, {}, {"daily_order_count": 5}, "daily_order_count"),
        ({}, {}, {"reserved_order_count": 4}, "daily_order_count"),
        ({}, {}, {"median_dollar_volume": None}, "liquidity_participation"),
        ({}, {}, {"median_dollar_volume": 50_000.0}, "liquidity_participation"),
        ({}, {}, {"daily_pnl": -500.0}, "daily_loss"),
        ({}, {}, {"drawdown_fraction": 0.11}, "drawdown"),
    ],
)
def test_each_adverse_condition_fails_named_gate(
    identity_update,
    request_update,
    snapshot_update,
    failed_gate,
):
    decision = broker_risk.evaluate(
        _policy(),
        replace(_identity(), **identity_update),
        replace(_request(), **request_update),
        replace(_snapshot(), **snapshot_update),
    )

    assert decision["status"] == "fail"
    assert failed_gate in decision["failed_gates"]
    assert broker_risk.verify(decision) == decision


def test_quote_timestamp_must_fall_on_declared_quote_date():
    observed_at = datetime(2026, 9, 14, 0, 0, 30, tzinfo=timezone.utc)
    snapshot = replace(
        _snapshot(),
        observed_at=observed_at,
        quote_at=observed_at - timedelta(seconds=31),
    )

    decision = broker_risk.evaluate(_policy(), _identity(), _request(), snapshot)

    assert "market_data" in decision["failed_gates"]
    assert decision["computed"]["quote_age_seconds"] == 31.0
    assert broker_risk.verify(decision) == decision


def test_pending_order_reservations_are_bound_into_computed_exposure():
    snapshot = replace(
        _snapshot(),
        reserved_buy_notional=500.0,
        reserved_symbol_buy_notional=400.0,
        reserved_turnover_notional=300.0,
        reserved_order_count=2,
    )

    decision = broker_risk.evaluate(_policy(), _identity(), _request(), snapshot)

    assert decision["status"] == "pass"
    assert decision["computed"]["resulting_gross_exposure"] == 3_505.0
    assert decision["computed"]["resulting_symbol_exposure"] == 2_405.0
    assert decision["computed"]["reserved_buy_notional"] == 500.0
    assert decision["computed"]["reserved_symbol_buy_notional"] == 400.0
    assert decision["computed"]["reserved_turnover_notional"] == 300.0
    assert decision["computed"]["reserved_order_count"] == 2
    assert broker_risk.verify(decision) == decision


def test_sell_is_close_only_after_pending_inventory_reservation():
    request = _request(side="sell", quantity=6.0)
    snapshot = replace(
        _snapshot(),
        gross_exposure=2_000.0,
        symbol_exposure=1_000.0,
        held_quantity=10.0,
        pending_sell_quantity=5.0,
    )

    decision = broker_risk.evaluate(_policy(), _identity(), request, snapshot)

    assert "order_constraints" in decision["failed_gates"]
    assert decision["computed"]["available_to_sell"] == 5.0


def test_existing_sell_reservations_cannot_exceed_inventory_for_a_buy():
    decision = broker_risk.evaluate(
        _policy(),
        _identity(),
        _request(side="buy"),
        replace(
            _snapshot(),
            held_quantity=5.0,
            pending_sell_quantity=6.0,
        ),
    )

    assert "order_constraints" in decision["failed_gates"]
    assert decision["computed"]["available_to_sell"] == 0.0
    assert broker_risk.verify(decision) == decision


def test_malformed_nonfinite_snapshot_is_rejected_before_evaluation():
    with pytest.raises(broker_risk.RiskContractError, match="positive finite"):
        replace(_snapshot(), quote_price=float("nan"))


def test_policy_rejects_incoherent_limits():
    with pytest.raises(broker_risk.RiskContractError, match="order-notional"):
        replace(_policy(), max_order_notional=11_000.0)


def test_retained_decision_tampering_fails_verification():
    decision = broker_risk.evaluate(
        _policy(),
        _identity(),
        _request(),
        _snapshot(),
    )
    tampered = {
        **decision,
        "computed": {
            **decision["computed"],
            "notional": 1.0,
        },
    }

    with pytest.raises(broker_risk.RiskContractError, match="hash does not match"):
        broker_risk.verify(tampered)


def test_risk_decision_ledger_binds_intent_and_accepts_exact_replay(con):
    request = _request()
    decision = broker_risk.evaluate(
        _policy(),
        _identity(),
        request,
        _snapshot(),
    )
    broker_ledger.init_broker_ledger_schema(con)

    first = broker_ledger.record_risk_decision(
        con,
        request=request,
        decision=decision,
    )
    replay = broker_ledger.record_risk_decision(
        con,
        request=request,
        decision=decision,
    )

    assert first == replay == decision["decision_sha256"]
    assert con.execute("SELECT COUNT(*) FROM broker_risk_decisions").fetchone() == (1,)
    assert con.execute("SELECT COUNT(*) FROM broker_intents").fetchone() == (1,)


def test_risk_decision_ledger_rejects_request_mismatch_and_tampering(con):
    request = _request()
    decision = broker_risk.evaluate(
        _policy(),
        _identity(),
        request,
        _snapshot(),
    )
    broker_ledger.init_broker_ledger_schema(con)

    with pytest.raises(broker_risk.RiskContractError, match="outcome is inconsistent"):
        broker_ledger.record_risk_decision(
            con,
            request=request,
            decision={**decision, "status": "fail"},
        )
    with pytest.raises(BrokerStateError, match="does not match broker intent"):
        broker_ledger.record_risk_decision(
            con,
            request=replace(request, quantity=9.0),
            decision=decision,
        )
    assert con.execute("SELECT COUNT(*) FROM broker_risk_decisions").fetchone() == (0,)


def test_risk_module_has_no_mutation_or_external_access_imports():
    names = set(broker_risk.evaluate.__globals__)
    assert names.isdisjoint(
        {
            "duckdb",
            "db",
            "http",
            "requests",
            "urllib",
            "socket",
            "subprocess",
            "os",
            "BrokerAdapter",
        }
    )
