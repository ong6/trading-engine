"""Halt-first, fail-closed emergency cancellation tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone

import pytest

from server import broker_emergency_stop, broker_ledger
from server.broker_contract import (
    BrokerAccount,
    BrokerCancellationUncertain,
    BrokerOrder,
    BrokerStateError,
    FillBatch,
)

NOW = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
ACCOUNT_ID = "paper-account"


def _order(index: int) -> BrokerOrder:
    return BrokerOrder(
        broker_order_id=f"paper-order:{index}",
        idempotency_key=f"intent-{index}",
        account_id=ACCOUNT_ID,
        symbol="SPY" if index == 1 else "QQQ",
        side="buy",
        quantity=float(index),
        signal_date=date(2026, 9, 11),
        status="pending",
        rejection_reason=None,
    )


class _Adapter:
    def __init__(
        self,
        con,
        orders=(),
        *,
        fail_on_call: int | None = None,
        malformed_on_call: int | None = None,
        mismatch_on_call: int | None = None,
        retain_cancelled: bool = False,
        fail_reads_after_cancellation: bool = False,
    ):
        self.con = con
        self.orders = {order.broker_order_id: order for order in orders}
        self.fail_on_call = fail_on_call
        self.malformed_on_call = malformed_on_call
        self.mismatch_on_call = mismatch_on_call
        self.retain_cancelled = retain_cancelled
        self.fail_reads_after_cancellation = fail_reads_after_cancellation
        self.cancel_calls = []
        self.read_calls = 0

    def _assert_halted(self):
        row = self.con.execute(
            "SELECT event_type FROM broker_risk_control_events "
            "WHERE account_id = ? ORDER BY event_sequence LIMIT 1",
            [ACCOUNT_ID],
        ).fetchone()
        assert row == ("halt",)

    def get_account(self, account_id):
        self._assert_halted()
        if self.fail_reads_after_cancellation and self.cancel_calls:
            raise TimeoutError("final snapshot timed out")
        self.read_calls += 1
        return BrokerAccount(
            account_id=account_id,
            venue="test-paper",
            environment="paper",
            active=True,
            currency="USD",
            cash=10_000.0,
            buying_power=10_000.0,
            initial_cash=10_000.0,
            margin_enabled=False,
        )

    def get_positions(self, account_id):
        self._assert_halted()
        return ()

    def get_open_orders(self, account_id):
        self._assert_halted()
        return tuple(self.orders.values())

    def stream_fills(self, account_id, *, after=None, limit=100):
        self._assert_halted()
        return FillBatch(fills=(), next_cursor=after, truncated=False)

    def cancel_order(self, account_id, broker_order_id):
        self._assert_halted()
        started = self.con.execute(
            "SELECT event_type FROM broker_cancellation_events "
            "WHERE account_id = ? AND broker_order_id = ? AND event_sequence = 1",
            [account_id, broker_order_id],
        ).fetchone()
        assert started == ("cancellation_started",)
        self.cancel_calls.append(broker_order_id)
        call = len(self.cancel_calls)
        order = self.orders[broker_order_id]
        if call == self.fail_on_call:
            self.orders.pop(broker_order_id)
            raise TimeoutError("cancellation timed out")
        if call == self.malformed_on_call:
            return {"status": "cancelled"}
        if not self.retain_cancelled:
            self.orders.pop(broker_order_id)
        acknowledgement = replace(
            order,
            status="cancelled",
            rejection_reason="cancelled by emergency stop",
        )
        if call == self.mismatch_on_call:
            return replace(acknowledgement, broker_order_id="paper-order:999")
        return acknowledgement


def _stop(con, adapter):
    return broker_emergency_stop.cancel_all_and_halt(
        con,
        adapter,
        ACCOUNT_ID,
        halt_key="emergency-halt-1",
        reason="operator emergency stop",
        now=NOW,
    )


def test_success_is_halt_first_durable_and_exactly_replayable(con):
    adapter = _Adapter(con, (_order(1), _order(2)))

    first = _stop(con, adapter)
    replay = _stop(con, adapter)

    assert first == replay
    assert first["status"] == "halted_cancelled"
    assert first["cancelled_order_ids"] == ["paper-order:1", "paper-order:2"]
    assert first["cancelled_count"] == 2
    assert first["remaining_open_order_count"] == 0
    assert first["submission_authority"] == "none"
    assert len(first["result_sha256"]) == 64
    assert adapter.cancel_calls == ["paper-order:1", "paper-order:2"]
    assert con.execute(
        "SELECT event_sequence, event_type FROM broker_emergency_stop_events "
        "ORDER BY event_sequence"
    ).fetchall() == [
        (1, "emergency_stop_started"),
        (2, "emergency_stop_completed"),
    ]
    assert con.execute(
        "SELECT COUNT(*) FROM broker_cancellation_events"
    ).fetchone() == (4,)


def test_timeout_leaves_halt_and_uncertainty_and_blocks_blind_retry(con):
    adapter = _Adapter(con, (_order(1),), fail_on_call=1)

    with pytest.raises(TimeoutError, match="timed out"):
        _stop(con, adapter)

    assert con.execute(
        "SELECT COUNT(*) FROM broker_risk_control_events"
    ).fetchone() == (1,)
    assert broker_ledger.cancellation_states_for_account(con, ACCOUNT_ID) == {
        broker_emergency_stop._cancellation_key("emergency-halt-1", _order(1)): (
            "uncertain"
        )
    }
    with pytest.raises(BrokerCancellationUncertain, match="uncertain cancellation"):
        _stop(con, adapter)
    assert adapter.cancel_calls == ["paper-order:1"]


def test_malformed_acknowledgement_remains_uncertain(con):
    adapter = _Adapter(con, (_order(1),), malformed_on_call=1)

    with pytest.raises(BrokerStateError, match="does not match planned order"):
        _stop(con, adapter)

    with pytest.raises(BrokerCancellationUncertain, match="uncertain cancellation"):
        _stop(con, adapter)
    assert adapter.cancel_calls == ["paper-order:1"]


def test_mismatched_acknowledgement_remains_uncertain(con):
    adapter = _Adapter(con, (_order(1),), mismatch_on_call=1)

    with pytest.raises(BrokerStateError, match="does not match planned order"):
        _stop(con, adapter)

    with pytest.raises(BrokerCancellationUncertain, match="uncertain cancellation"):
        _stop(con, adapter)
    assert adapter.cancel_calls == ["paper-order:1"]


def test_partial_success_is_retained_when_later_cancellation_times_out(con):
    adapter = _Adapter(con, (_order(1), _order(2)), fail_on_call=2)

    with pytest.raises(TimeoutError, match="timed out"):
        _stop(con, adapter)

    states = broker_ledger.cancellation_states_for_account(con, ACCOUNT_ID)
    assert sorted(states.values()) == ["acknowledged", "uncertain"]
    assert adapter.cancel_calls == ["paper-order:1", "paper-order:2"]
    with pytest.raises(BrokerCancellationUncertain, match="uncertain cancellation"):
        _stop(con, adapter)
    assert adapter.cancel_calls == ["paper-order:1", "paper-order:2"]


def test_new_halt_key_cannot_bypass_an_in_progress_operation(con):
    adapter = _Adapter(con, (_order(1),), fail_on_call=1)
    with pytest.raises(TimeoutError):
        _stop(con, adapter)

    with pytest.raises(BrokerStateError, match="already in progress"):
        broker_emergency_stop.cancel_all_and_halt(
            con,
            adapter,
            ACCOUNT_ID,
            halt_key="emergency-halt-2",
            reason="second emergency stop",
            now=NOW,
        )

    assert adapter.cancel_calls == ["paper-order:1"]
    assert con.execute(
        "SELECT COUNT(*) FROM broker_risk_control_events"
    ).fetchone() == (2,)


def test_final_snapshot_failure_keeps_halt_and_recovers_without_recancelling(con):
    adapter = _Adapter(
        con,
        (_order(1),),
        fail_reads_after_cancellation=True,
    )

    with pytest.raises(TimeoutError, match="final snapshot timed out"):
        _stop(con, adapter)

    assert set(
        broker_ledger.cancellation_states_for_account(con, ACCOUNT_ID).values()
    ) == {"acknowledged"}
    assert con.execute(
        "SELECT COUNT(*) FROM broker_emergency_stop_events"
    ).fetchone() == (1,)
    adapter.fail_reads_after_cancellation = False
    result = _stop(con, adapter)
    assert result["status"] == "halted_cancelled"
    assert adapter.cancel_calls == ["paper-order:1"]


def test_cancel_acknowledgement_must_remove_order_before_completion(con):
    adapter = _Adapter(con, (_order(1),), retain_cancelled=True)

    with pytest.raises(BrokerStateError, match="open orders remain"):
        _stop(con, adapter)

    assert set(
        broker_ledger.cancellation_states_for_account(con, ACCOUNT_ID).values()
    ) == {"acknowledged"}
    with pytest.raises(BrokerStateError, match="conflicts"):
        _stop(con, adapter)
    assert adapter.cancel_calls == ["paper-order:1"]


def test_tampered_operation_or_cancellation_evidence_fails_closed(con):
    adapter = _Adapter(con, (_order(1),))
    _stop(con, adapter)
    con.execute(
        "UPDATE broker_emergency_stop_events SET event_payload = '{}' "
        "WHERE halt_key = 'emergency-halt-1' AND event_sequence = 1"
    )
    with pytest.raises(BrokerStateError, match="event is invalid"):
        _stop(con, adapter)


def test_tampered_cancellation_sequence_fails_closed(con):
    adapter = _Adapter(con, (_order(1),), fail_on_call=1)
    with pytest.raises(TimeoutError):
        _stop(con, adapter)
    con.execute(
        "UPDATE broker_cancellation_events SET event_type = 'tampered' "
        "WHERE event_sequence = 1"
    )
    with pytest.raises(BrokerStateError, match="sequence is invalid"):
        _stop(con, adapter)


def test_completed_replay_verifies_retained_cancellation_acknowledgement(con):
    adapter = _Adapter(con, (_order(1),))
    _stop(con, adapter)
    con.execute(
        "UPDATE broker_cancellation_events SET order_payload = '{}' "
        "WHERE event_sequence = 2"
    )

    with pytest.raises(BrokerStateError, match="payload is invalid"):
        _stop(con, adapter)
