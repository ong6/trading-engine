"""Uncertain broker submissions are adjudicated without retry authority."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pytest

from engine.lib import db
from server import (
    broker_ledger,
    broker_risk_control,
    broker_submission,
    broker_submission_resolution,
)
from server.broker_contract import (
    BrokerAccount,
    BrokerFill,
    BrokerOrder,
    BrokerStateError,
    BrokerSubmissionUncertain,
    FillBatch,
    SubmitOrderRequest,
)
from tests.test_broker_ledger import _risk_decision

SIGNAL_DATE = date(2026, 9, 14)
STARTED_AT = datetime(2026, 9, 14, 14, 30, tzinfo=timezone.utc)
RESOLVED_AT = STARTED_AT + timedelta(seconds=10)
ACCOUNT = "paper-account"


def _request(*, key="uncertain-intent", quantity=2.0):
    return SubmitOrderRequest(
        idempotency_key=key,
        account_id=ACCOUNT,
        symbol="SPY",
        side="buy",
        quantity=quantity,
        signal_date=SIGNAL_DATE,
    )


def _order(request=None, *, filled_quantity=0.0):
    request = request or _request()
    return BrokerOrder(
        broker_order_id="venue-order:1",
        idempotency_key=request.idempotency_key,
        account_id=request.account_id,
        symbol=request.symbol,
        side=request.side,
        quantity=request.quantity,
        signal_date=request.signal_date,
        status="partially_filled" if filled_quantity else "pending",
        rejection_reason=None,
        filled_quantity=filled_quantity,
    )


def _fill(
    request=None,
    *,
    execution_id="venue-fill:1",
    broker_order_id="venue-order:1",
    quantity=2.0,
):
    request = request or _request()
    return BrokerFill(
        execution_id=execution_id,
        broker_order_id=broker_order_id,
        idempotency_key=request.idempotency_key,
        account_id=request.account_id,
        symbol=request.symbol,
        side=request.side,
        quantity=quantity,
        occurred_on=SIGNAL_DATE,
        reference_price=500.0,
        price=500.5,
        total_cost_bps=10.0,
    )


class _Adapter:
    def __init__(self, *, orders=(), fills=()):
        self.account = BrokerAccount(
            account_id=ACCOUNT,
            venue="paper-test",
            environment="paper",
            active=True,
            currency="USD",
            cash=10_000.0,
            buying_power=10_000.0,
            initial_cash=10_000.0,
            margin_enabled=False,
        )
        self.orders = tuple(orders)
        self.fills = tuple(fills)
        self.submit_calls = 0
        self.cancel_calls = 0

    def get_account(self, account_id):
        assert account_id == ACCOUNT
        return self.account

    def get_positions(self, account_id):
        assert account_id == ACCOUNT
        return ()

    def get_open_orders(self, account_id):
        assert account_id == ACCOUNT
        return self.orders

    def stream_fills(self, account_id, *, after=None, limit=100):
        assert account_id == ACCOUNT
        assert limit >= len(self.fills)
        return FillBatch(fills=self.fills, next_cursor=after, truncated=False)

    def submit_order(self, _request):
        self.submit_calls += 1
        raise AssertionError("resolution must not submit")

    def cancel_order(self, _account_id, _broker_order_id):
        self.cancel_calls += 1
        raise AssertionError("resolution must not cancel")


def _start_and_halt(con, request=None):
    request = request or _request()
    broker_ledger.init_broker_ledger_schema(con)
    with db.transaction(con):
        broker_ledger.begin_submission(con, request, now=STARTED_AT)
    broker_risk_control.record_halt(
        con,
        halt_key=f"resolve-halt-{request.idempotency_key}",
        account_id=request.account_id,
        reason="adjudicate uncertain submission",
        now=STARTED_AT + timedelta(seconds=1),
    )
    return request


def _resolve(con, adapter, request=None, *, key="resolution-1", now=RESOLVED_AT):
    request = request or _request()
    return broker_submission_resolution.resolve_uncertain(
        con,
        adapter,
        request.idempotency_key,
        resolution_key=key,
        now=now,
    )


@pytest.mark.parametrize(
    ("adapter", "outcome", "filled_quantity"),
    [
        (_Adapter(orders=(_order(),)), "observed_open", 0.0),
        (_Adapter(fills=(_fill(),)), "observed_filled", 2.0),
        (
            _Adapter(fills=(_fill(quantity=0.5),)),
            "observed_terminal_partial_fill",
            0.5,
        ),
        (_Adapter(), "not_observed_burned", 0.0),
    ],
)
def test_stable_evidence_classifies_uncertain_submission(
    con,
    adapter,
    outcome,
    filled_quantity,
):
    request = _start_and_halt(con)

    result = _resolve(con, adapter, request)

    assert result["outcome"] == outcome
    assert result["observed_filled_quantity"] == filled_quantity
    assert result["retry_permitted"] is False
    assert result["submission_authority"] == "none"
    assert result["operational_control"]["halted"] is True
    assert result["operational_control"]["event_count"] == 1
    assert len(result["evidence_sha256"]) == 64
    assert adapter.submit_calls == adapter.cancel_calls == 0
    assert broker_ledger.submission_state(con, request.idempotency_key) == "uncertain"
    assert broker_ledger.submission_resolution(con, request.idempotency_key) == result


def test_exact_replay_is_idempotent_and_conflicting_key_fails(con):
    request = _start_and_halt(con)
    adapter = _Adapter()
    first = _resolve(con, adapter, request)
    replay = _resolve(
        con,
        _Adapter(),
        request,
    )

    assert replay == first
    assert con.execute(
        "SELECT COUNT(*) FROM broker_submission_resolutions"
    ).fetchone() == (1,)
    with pytest.raises(BrokerStateError, match="replay"):
        _resolve(con, adapter, request, key="different-resolution")
    with pytest.raises(BrokerStateError, match="replay"):
        _resolve(con, adapter, request, now=RESOLVED_AT + timedelta(minutes=1))


def test_resolution_key_cannot_be_reused_for_another_intent(con):
    first = _start_and_halt(con)
    _resolve(con, _Adapter(), first, key="shared-resolution")
    second = _start_and_halt(
        con,
        _request(key="second-uncertain-intent"),
    )

    with pytest.raises(BrokerStateError, match="already used"):
        _resolve(con, _Adapter(), second, key="shared-resolution")

    assert broker_ledger.submission_resolution(
        con, second.idempotency_key
    ) is None


def test_resolution_requires_durable_halt_and_post_submission_time(con):
    request = _request()
    broker_ledger.init_broker_ledger_schema(con)
    with db.transaction(con):
        broker_ledger.begin_submission(con, request, now=STARTED_AT)

    with pytest.raises(BrokerStateError, match="durable halted"):
        _resolve(con, _Adapter(), request)

    broker_risk_control.record_halt(
        con,
        halt_key="late-halt",
        account_id=ACCOUNT,
        reason="test",
        now=STARTED_AT + timedelta(seconds=1),
    )
    with pytest.raises(ValueError, match="precedes submission"):
        _resolve(con, _Adapter(), request, now=STARTED_AT - timedelta(seconds=1))


@pytest.mark.parametrize(
    ("adapter", "detail"),
    [
        (
            _Adapter(orders=(replace(_order(), symbol="QQQ"),)),
            "conflicts with immutable intent",
        ),
        (
            _Adapter(
                orders=(_order(filled_quantity=0.5),),
                fills=(_fill(quantity=0.25),),
            ),
            "order and fill evidence disagree",
        ),
        (
            _Adapter(
                fills=(
                    _fill(quantity=1.5),
                    _fill(execution_id="venue-fill:2", quantity=1.0),
                )
            ),
            "exceeds intent quantity",
        ),
        (
            _Adapter(
                fills=(
                    _fill(quantity=1.0),
                    _fill(
                        execution_id="venue-fill:2",
                        broker_order_id="venue-order:2",
                        quantity=1.0,
                    ),
                )
            ),
            "conflicting broker order identifiers",
        ),
    ],
)
def test_mismatched_or_ambiguous_venue_evidence_fails_closed(
    con,
    adapter,
    detail,
):
    _start_and_halt(con)

    with pytest.raises(BrokerStateError, match=detail):
        _resolve(con, adapter)

    assert con.execute(
        "SELECT COUNT(*) FROM broker_submission_resolutions"
    ).fetchone() == (0,)
    assert adapter.submit_calls == adapter.cancel_calls == 0


def test_state_change_during_capture_fails_without_recording(con):
    class _ChangingAdapter(_Adapter):
        def __init__(self):
            super().__init__()
            self.reads = 0

        def get_account(self, account_id):
            account = super().get_account(account_id)
            self.reads += 1
            return (
                account
                if self.reads == 1
                else replace(account, cash=9_999.0, buying_power=9_999.0)
            )

    _start_and_halt(con)
    adapter = _ChangingAdapter()

    with pytest.raises(BrokerStateError, match="changed during snapshot"):
        _resolve(con, adapter)

    assert con.execute(
        "SELECT COUNT(*) FROM broker_submission_resolutions"
    ).fetchone() == (0,)


def test_duplicate_matching_orders_fail_before_resolution_write(con):
    class _DuplicateOrderAdapter(_Adapter):
        def get_open_orders(self, account_id):
            assert account_id == ACCOUNT
            return (
                _order(),
                replace(_order(), broker_order_id="venue-order:2"),
            )

    _start_and_halt(con)
    adapter = _DuplicateOrderAdapter()

    with pytest.raises(BrokerStateError, match="duplicate open-order idempotency"):
        _resolve(con, adapter)

    assert con.execute(
        "SELECT COUNT(*) FROM broker_submission_resolutions"
    ).fetchone() == (0,)
    assert adapter.submit_calls == adapter.cancel_calls == 0


def test_tampering_fails_closed_and_restart_preserves_resolution(tmp_path):
    database = tmp_path / "submission-resolution.duckdb"
    con = db.connect(database)
    try:
        request = _start_and_halt(con)
        result = _resolve(con, _Adapter(), request)
    finally:
        con.close()

    con = db.connect(database)
    try:
        assert broker_ledger.submission_resolution(
            con, request.idempotency_key
        ) == result
        con.execute(
            "UPDATE broker_submission_resolutions SET evidence_payload = '{}'"
        )
        with pytest.raises(BrokerStateError, match="resolution"):
            broker_ledger.submission_resolution(con, request.idempotency_key)
    finally:
        con.close()


def test_resolved_absence_never_allows_submit_once_retry(con):
    request = _start_and_halt(con)
    adapter = _Adapter()
    result = _resolve(con, adapter, request)
    assert result["outcome"] == "not_observed_burned"

    with pytest.raises(BrokerSubmissionUncertain, match="requires reconciliation"):
        broker_submission.submit_once(
            con,
            adapter,
            request,
            risk_decision=_risk_decision(request, observed_at=RESOLVED_AT),
            now=RESOLVED_AT,
        )

    assert adapter.submit_calls == 0


def test_module_exposes_no_submit_cancel_or_authority_surface():
    assert {
        "submit_once",
        "submit_order",
        "cancel_order",
        "enable",
        "activate",
        "grant_lease",
        "authorize",
    }.isdisjoint(vars(broker_submission_resolution))
