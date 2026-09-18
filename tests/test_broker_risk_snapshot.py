"""Pre-trade snapshots are assembled from bounded, hash-bound evidence."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pytest

from engine.lib.provenance import canonical_sha256
from server import (
    broker_ledger,
    broker_reconciliation,
    broker_risk,
    broker_risk_control,
    broker_risk_snapshot,
)
from server.broker_contract import (
    BrokerAccount,
    BrokerOrder,
    BrokerPosition,
    BrokerStateError,
    FillBatch,
    SubmitOrderRequest,
)

AS_OF = date(2026, 9, 14)
NOW = datetime(2026, 9, 14, 14, 30, tzinfo=timezone.utc)
ACCOUNT = "paper-account"


class _Adapter:
    def __init__(self):
        self.account = BrokerAccount(
            account_id=ACCOUNT,
            venue="paper-test",
            environment="paper",
            active=True,
            currency="USD",
            cash=5_000.0,
            buying_power=5_000.0,
            initial_cash=5_000.0,
            margin_enabled=False,
        )
        self.positions = (
            BrokerPosition(
                account_id=ACCOUNT,
                symbol="QQQ",
                quantity=1.0,
                average_price=190.0,
            ),
            BrokerPosition(
                account_id=ACCOUNT,
                symbol="SPY",
                quantity=10.0,
                average_price=100.0,
            ),
        )
        self.orders = (
            BrokerOrder(
                broker_order_id="paper-order:1",
                idempotency_key="pending-spy-buy",
                account_id=ACCOUNT,
                symbol="SPY",
                side="buy",
                quantity=10.0,
                signal_date=AS_OF,
                status="partially_filled",
                rejection_reason=None,
                filled_quantity=4.0,
            ),
            BrokerOrder(
                broker_order_id="paper-order:2",
                idempotency_key="pending-spy-sell",
                account_id=ACCOUNT,
                symbol="SPY",
                side="sell",
                quantity=5.0,
                signal_date=AS_OF,
                status="pending",
                rejection_reason=None,
            ),
            BrokerOrder(
                broker_order_id="paper-order:3",
                idempotency_key="pending-qqq-buy",
                account_id=ACCOUNT,
                symbol="QQQ",
                side="buy",
                quantity=2.0,
                signal_date=AS_OF,
                status="pending",
                rejection_reason=None,
            ),
        )

    def get_account(self, account_id):
        assert account_id == ACCOUNT
        return self.account

    def get_positions(self, account_id):
        assert account_id == ACCOUNT
        return self.positions

    def get_open_orders(self, account_id):
        assert account_id == ACCOUNT
        return self.orders

    def stream_fills(self, account_id, *, after=None, limit=100):
        assert account_id == ACCOUNT
        return FillBatch(fills=(), next_cursor=after, truncated=False)


def _request():
    return SubmitOrderRequest(
        idempotency_key="new-intent",
        account_id=ACCOUNT,
        symbol="SPY",
        side="buy",
        quantity=1.0,
        signal_date=AS_OF,
    )


def _market(*, marks=None):
    return broker_risk_snapshot.MarketRiskEvidence(
        as_of=AS_OF,
        observed_at=NOW,
        quote_date=AS_OF,
        quote_at=NOW - timedelta(seconds=5),
        quote_price=110.0,
        reference_price=110.0,
        median_dollar_volume=10_000_000.0,
        position_marks=marks
        or (
            broker_risk_snapshot.PositionMark("QQQ", 200.0),
            broker_risk_snapshot.PositionMark("SPY", 110.0),
        ),
        instrument_type="etf",
        instrument_active=True,
        instrument_liquid=True,
        instrument_quarantined=False,
        market_session_open=True,
        clock_synchronized=True,
        storage_healthy=True,
        broker_healthy=True,
        corporate_action_clear=True,
    )


def _performance():
    return broker_risk_snapshot.PerformanceRiskEvidence(
        daily_turnover=100.0,
        daily_order_count=1,
        daily_pnl=-10.0,
        drawdown_fraction=0.01,
    )


def _record_reconciliation(con, adapter, *, status="match"):
    snapshot = broker_reconciliation.capture_snapshot(adapter, ACCOUNT)
    expected = snapshot.comparable_payload()
    observed = expected if status == "match" else {**expected, "account": {**expected["account"], "cash": 4_999.0}}
    broker_ledger.init_broker_ledger_schema(con)
    broker_ledger.record_reconciliation(
        con,
        reconciliation_key=f"risk-recon-{status}",
        account_id=ACCOUNT,
        status=status,
        expected=expected,
        observed=observed,
        detail=f"{status} test evidence",
        now=NOW - timedelta(seconds=2),
    )


def test_assembler_derives_exposure_reservations_and_source_hashes(con):
    adapter = _Adapter()
    _record_reconciliation(con, adapter)

    snapshot = broker_risk_snapshot.assemble(
        con,
        adapter,
        _request(),
        reconciliation_key="risk-recon-match",
        market=_market(),
        performance=_performance(),
    )

    assert snapshot.reconciled is True
    assert snapshot.operational_halt is True
    assert snapshot.account_active is True
    assert snapshot.margin_enabled is False
    assert snapshot.cash == snapshot.buying_power == 5_000.0
    assert snapshot.gross_exposure == 1_300.0
    assert snapshot.symbol_exposure == 1_100.0
    assert snapshot.equity == 6_300.0
    assert snapshot.held_quantity == 10.0
    assert snapshot.pending_sell_quantity == 5.0
    assert snapshot.reserved_buy_notional == 1_060.0
    assert snapshot.reserved_symbol_buy_notional == 660.0
    assert snapshot.reserved_turnover_notional == 1_610.0
    assert snapshot.reserved_order_count == 3
    assert snapshot.account_snapshot_sha256 == canonical_sha256(
        broker_reconciliation.capture_snapshot(adapter, ACCOUNT).comparable_payload()
    )
    assert snapshot.market_state_sha256 == canonical_sha256(_market().payload())
    assert snapshot.performance_state_sha256 == canonical_sha256(
        _performance().payload()
    )
    assert len(snapshot.reconciliation_sha256) == 64
    assert len(snapshot.operational_control_sha256) == 64


def test_assembled_snapshot_is_default_halted_at_risk_gate(con):
    adapter = _Adapter()
    _record_reconciliation(con, adapter)
    snapshot = broker_risk_snapshot.assemble(
        con,
        adapter,
        _request(),
        reconciliation_key="risk-recon-match",
        market=_market(),
        performance=_performance(),
    )
    policy = broker_risk.RiskPolicy(
        policy_id="paper-risk-v1",
        account_id=ACCOUNT,
        strategy_id="test-strategy",
        release_sha256="a" * 64,
        strategy_config_sha256="b" * 64,
        execution_profile_id="baseline-v1",
        execution_profile_sha256="c" * 64,
        allowed_symbols=("SPY",),
        capital_ceiling=10_000.0,
        max_gross_exposure=10_000.0,
        max_position_fraction=0.5,
        max_order_notional=1_000.0,
        max_daily_turnover=5_000.0,
        max_daily_orders=10,
        max_participation=0.01,
        max_daily_loss_fraction=0.02,
        max_drawdown_fraction=0.10,
        max_reference_deviation_fraction=0.02,
        max_quote_age_seconds=60,
        max_reconciliation_age_seconds=60,
        decision_ttl_seconds=30,
    )
    identity = broker_risk.RiskIdentity(
        policy_id=policy.policy_id,
        strategy_id=policy.strategy_id,
        release_sha256=policy.release_sha256,
        strategy_config_sha256=policy.strategy_config_sha256,
        execution_profile_id=policy.execution_profile_id,
        execution_profile_sha256=policy.execution_profile_sha256,
    )

    decision = broker_risk.evaluate(policy, identity, _request(), snapshot)

    assert decision["status"] == "fail"
    assert decision["failed_gates"] == ["operational_control"]
    assert broker_risk.verify(decision) == decision


def test_assembler_rejects_missing_or_extra_market_marks(con):
    adapter = _Adapter()
    _record_reconciliation(con, adapter)
    request = _request()

    with pytest.raises(BrokerStateError, match="marks do not exactly cover"):
        broker_risk_snapshot.assemble(
            con,
            adapter,
            request,
            reconciliation_key="risk-recon-match",
            market=_market(
                marks=(broker_risk_snapshot.PositionMark("SPY", 110.0),)
            ),
            performance=_performance(),
        )


def test_reconciliation_difference_is_retained_as_failed_snapshot_input(con):
    adapter = _Adapter()
    _record_reconciliation(con, adapter, status="difference")

    snapshot = broker_risk_snapshot.assemble(
        con,
        adapter,
        _request(),
        reconciliation_key="risk-recon-difference",
        market=_market(),
        performance=_performance(),
    )

    assert snapshot.reconciled is False
    assert snapshot.reconciliation_at == NOW - timedelta(seconds=2)


def test_stale_reconciliation_fails_the_evaluated_snapshot(con):
    adapter = _Adapter()
    snapshot = broker_reconciliation.capture_snapshot(adapter, ACCOUNT)
    comparable = snapshot.comparable_payload()
    broker_ledger.init_broker_ledger_schema(con)
    broker_ledger.record_reconciliation(
        con,
        reconciliation_key="risk-recon-stale",
        account_id=ACCOUNT,
        status="match",
        expected=comparable,
        observed=comparable,
        detail="stale test evidence",
        now=NOW - timedelta(seconds=61),
    )
    assembled = broker_risk_snapshot.assemble(
        con,
        adapter,
        _request(),
        reconciliation_key="risk-recon-stale",
        market=_market(),
        performance=_performance(),
    )
    policy = broker_risk.RiskPolicy(
        policy_id="paper-risk-v1",
        account_id=ACCOUNT,
        strategy_id="test-strategy",
        release_sha256="a" * 64,
        strategy_config_sha256="b" * 64,
        execution_profile_id="baseline-v1",
        execution_profile_sha256="c" * 64,
        allowed_symbols=("SPY",),
        capital_ceiling=10_000.0,
        max_gross_exposure=10_000.0,
        max_position_fraction=0.5,
        max_order_notional=1_000.0,
        max_daily_turnover=5_000.0,
        max_daily_orders=10,
        max_participation=0.01,
        max_daily_loss_fraction=0.02,
        max_drawdown_fraction=0.10,
        max_reference_deviation_fraction=0.02,
        max_quote_age_seconds=60,
        max_reconciliation_age_seconds=60,
        decision_ttl_seconds=30,
    )
    identity = broker_risk.RiskIdentity(
        policy_id=policy.policy_id,
        strategy_id=policy.strategy_id,
        release_sha256=policy.release_sha256,
        strategy_config_sha256=policy.strategy_config_sha256,
        execution_profile_id=policy.execution_profile_id,
        execution_profile_sha256=policy.execution_profile_sha256,
    )

    decision = broker_risk.evaluate(policy, identity, _request(), assembled)

    assert "reconciliation" in decision["failed_gates"]
    assert "operational_control" in decision["failed_gates"]
    assert decision["computed"]["reconciliation_age_seconds"] == 61.0


def test_reconciliation_must_bind_exact_current_account_snapshot(con):
    adapter = _Adapter()
    _record_reconciliation(con, adapter)
    adapter.account = replace(adapter.account, cash=4_999.0, buying_power=4_999.0)

    with pytest.raises(BrokerStateError, match="evidence is invalid"):
        broker_risk_snapshot.assemble(
            con,
            adapter,
            _request(),
            reconciliation_key="risk-recon-match",
            market=_market(),
            performance=_performance(),
        )


def test_assembler_rejects_state_change_after_evidence_read(con):
    class _ChangesAfterInitialCapture(_Adapter):
        def __init__(self):
            super().__init__()
            self.account_reads = 0

        def get_account(self, account_id):
            self.account_reads += 1
            account = super().get_account(account_id)
            if self.account_reads <= 2:
                return account
            return replace(account, cash=4_999.0, buying_power=4_999.0)

    adapter = _ChangesAfterInitialCapture()
    _record_reconciliation(con, adapter)
    adapter.account_reads = 0

    with pytest.raises(BrokerStateError, match="risk snapshot was assembled"):
        broker_risk_snapshot.assemble(
            con,
            adapter,
            _request(),
            reconciliation_key="risk-recon-match",
            market=_market(),
            performance=_performance(),
        )


def test_assembler_requires_retained_reconciliation(con):
    with pytest.raises(BrokerStateError, match="evidence is unavailable"):
        broker_risk_snapshot.assemble(
            con,
            _Adapter(),
            _request(),
            reconciliation_key="missing-reconciliation",
            market=_market(),
            performance=_performance(),
        )


def test_recorded_halt_identity_changes_assembled_snapshot(con):
    adapter = _Adapter()
    _record_reconciliation(con, adapter)
    before = broker_risk_snapshot.assemble(
        con,
        adapter,
        _request(),
        reconciliation_key="risk-recon-match",
        market=_market(),
        performance=_performance(),
    )
    broker_risk_control.record_halt(
        con,
        halt_key="halt-risk-snapshot",
        account_id=ACCOUNT,
        reason="operator halt",
        now=NOW,
    )
    after = broker_risk_snapshot.assemble(
        con,
        adapter,
        _request(),
        reconciliation_key="risk-recon-match",
        market=_market(),
        performance=_performance(),
    )

    assert before.operational_halt is after.operational_halt is True
    assert before.operational_control_sha256 != after.operational_control_sha256


def test_market_evidence_rejects_duplicate_marks():
    with pytest.raises(broker_risk.RiskContractError, match="sorted unique"):
        _market(
            marks=(
                broker_risk_snapshot.PositionMark("SPY", 110.0),
                broker_risk_snapshot.PositionMark("SPY", 111.0),
            )
        )
