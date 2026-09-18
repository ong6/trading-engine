"""Deterministic broker-neutral snapshot and reconciliation tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from server import broker_reconciliation
from server.broker_contract import (
    BrokerAccount,
    BrokerFill,
    BrokerOrder,
    BrokerPosition,
    BrokerStateError,
    BrokerStateUnavailable,
    FillBatch,
)

SIGNAL_DATE = date(2026, 9, 11)
FILL_DATE = date(2026, 9, 14)


class _SnapshotAdapter:
    def __init__(
        self,
        *,
        account_id,
        cash=1_000.0,
        positions=(),
        orders=(),
        fills=(),
        page_size=500,
    ):
        self.account_id = account_id
        self.account = BrokerAccount(
            account_id=account_id,
            venue=f"venue-{account_id}",
            environment="simulator",
            active=True,
            currency="USD",
            cash=cash,
            buying_power=cash,
            initial_cash=1_000.0,
            margin_enabled=False,
        )
        self.positions = tuple(positions)
        self.orders = tuple(orders)
        self.fills = tuple(fills)
        self.page_size = page_size

    def get_account(self, account_id):
        assert account_id == self.account_id
        return self.account

    def get_positions(self, account_id):
        assert account_id == self.account_id
        return self.positions

    def get_open_orders(self, account_id):
        assert account_id == self.account_id
        return self.orders

    def stream_fills(self, account_id, *, after=None, limit=100):
        assert account_id == self.account_id
        offset = 0 if after is None else int(after.split(":")[-1])
        page_limit = min(limit, self.page_size)
        visible = self.fills[offset : offset + page_limit]
        next_offset = offset + len(visible)
        return FillBatch(
            fills=visible,
            next_cursor=f"cursor:{next_offset}" if visible else after,
            truncated=next_offset < len(self.fills),
        )


class _UnavailableAdapter:
    def get_account(self, account_id):
        raise BrokerStateUnavailable("test adapter unavailable")


def _position(account_id, *, quantity=2.0):
    return BrokerPosition(
        account_id=account_id,
        symbol="SPY",
        quantity=quantity,
        average_price=500.0,
    )


def _order(account_id, native_id):
    return BrokerOrder(
        broker_order_id=native_id,
        idempotency_key="intent-1",
        account_id=account_id,
        symbol="QQQ",
        side="buy",
        quantity=1.0,
        signal_date=SIGNAL_DATE,
        status="pending",
        rejection_reason=None,
    )


def _fill(account_id, native_order_id, execution_id, *, price=500.5):
    return BrokerFill(
        execution_id=execution_id,
        broker_order_id=native_order_id,
        idempotency_key="intent-2",
        account_id=account_id,
        symbol="SPY",
        side="buy",
        quantity=2.0,
        occurred_on=FILL_DATE,
        reference_price=500.0,
        price=price,
        total_cost_bps=10.0,
    )


def _adapter(account_id, *, cash=1_000.0, position_qty=2.0, fill_price=500.5):
    return _SnapshotAdapter(
        account_id=account_id,
        cash=cash,
        positions=(_position(account_id, quantity=position_qty),),
        orders=(_order(account_id, f"{account_id}-order:1"),),
        fills=(_fill(account_id, f"{account_id}-order:2", f"{account_id}-fill:1", price=fill_price),),
    )


def test_cross_venue_native_identifiers_do_not_create_false_difference(con):
    expected = _adapter("sim-account")
    observed = _adapter("paper-account")

    result = broker_reconciliation.reconcile(
        con,
        reconciliation_key="recon-cross-venue",
        expected_adapter=expected,
        expected_account_id="sim-account",
        observed_adapter=observed,
        observed_account_id="paper-account",
    )

    assert result.status == "match"
    assert result.differences == ()
    assert con.execute(
        "SELECT role, account_id FROM broker_snapshots ORDER BY role"
    ).fetchall() == [
        ("expected", "sim-account"),
        ("observed", "paper-account"),
    ]
    status, expected_payload, observed_payload = con.execute(
        "SELECT status, expected_payload, observed_payload FROM broker_reconciliations"
    ).fetchone()
    assert status == "match"
    assert expected_payload == observed_payload
    retained = con.execute(
        "SELECT snapshot_payload FROM broker_snapshots WHERE role = 'observed'"
    ).fetchone()[0]
    assert "paper-account-order:1" in retained
    assert "paper-account-fill:1" in retained


def test_reconciliation_classifies_account_position_and_fill_differences(con):
    result = broker_reconciliation.reconcile(
        con,
        reconciliation_key="recon-differences",
        expected_adapter=_adapter("sim-account"),
        expected_account_id="sim-account",
        observed_adapter=_adapter(
            "paper-account",
            cash=900.0,
            position_qty=1.5,
            fill_price=501.0,
        ),
        observed_account_id="paper-account",
    )

    assert result.status == "difference"
    assert {difference.classification for difference in result.differences} == {
        "account_buying_power",
        "account_cash",
        "position_quantity",
        "fill_price",
    }
    detail = con.execute(
        "SELECT detail FROM broker_reconciliations"
    ).fetchone()[0]
    assert '"difference_count":4' in detail
    assert '"fill_price"' in detail
    stored_differences = con.execute(
        "SELECT difference_sequence, difference_payload "
        "FROM broker_reconciliation_differences ORDER BY difference_sequence"
    ).fetchall()
    assert [sequence for sequence, _payload in stored_differences] == [1, 2, 3, 4]
    assert any('"classification":"fill_price"' in payload for _sequence, payload in stored_differences)


def test_snapshot_consumes_all_bounded_fill_pages():
    account_id = "sim-account"
    fills = tuple(
        replace(
            _fill(account_id, f"order:{index}", f"fill:{index}"),
            idempotency_key=f"intent-{index}",
        )
        for index in range(1, 4)
    )
    snapshot = broker_reconciliation.capture_snapshot(
        _SnapshotAdapter(
            account_id=account_id,
            fills=fills,
            page_size=1,
        ),
        account_id,
    )

    assert {fill.execution_id for fill in snapshot.fills} == {
        "fill:1",
        "fill:2",
        "fill:3",
    }


def test_snapshot_rejects_nonadvancing_fill_cursor():
    class BrokenCursorAdapter(_SnapshotAdapter):
        def stream_fills(self, account_id, *, after=None, limit=100):
            return FillBatch(
                fills=(self.fills[0],),
                next_cursor="same-cursor",
                truncated=True,
            )

    account_id = "sim-account"
    adapter = BrokenCursorAdapter(
        account_id=account_id,
        fills=(_fill(account_id, "order:1", "fill:1"),),
    )
    with pytest.raises(BrokerStateError, match="did not advance"):
        broker_reconciliation.capture_snapshot(adapter, account_id)


def test_snapshot_rejects_state_that_changes_during_capture():
    class ChangingAdapter(_SnapshotAdapter):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.account_reads = 0

        def get_account(self, account_id):
            account = super().get_account(account_id)
            self.account_reads += 1
            return (
                account
                if self.account_reads == 1
                else replace(account, cash=account.cash - 1, buying_power=account.cash - 1)
            )

    account_id = "sim-account"
    with pytest.raises(BrokerStateError, match="changed during snapshot"):
        broker_reconciliation.capture_snapshot(
            ChangingAdapter(account_id=account_id),
            account_id,
        )


def test_snapshot_rejects_terminal_order_returned_as_open():
    account_id = "sim-account"
    terminal = replace(
        _order(account_id, "sim-order:1"),
        status="cancelled",
        rejection_reason="already cancelled",
    )

    with pytest.raises(BrokerStateError, match="open-order collection"):
        broker_reconciliation.capture_snapshot(
            _SnapshotAdapter(
                account_id=account_id,
                orders=(terminal,),
            ),
            account_id,
        )


def test_partial_fill_and_expiration_are_representable_and_compared():
    expected_order = _order("sim-account", "sim-order:1")
    observed_order = replace(
        _order("paper-account", "paper-order:1"),
        status="partially_filled",
        filled_quantity=0.4,
    )
    expected = broker_reconciliation.capture_snapshot(
        _SnapshotAdapter(
            account_id="sim-account",
            orders=(expected_order,),
        ),
        "sim-account",
    )
    observed = broker_reconciliation.capture_snapshot(
        _SnapshotAdapter(
            account_id="paper-account",
            orders=(observed_order,),
        ),
        "paper-account",
    )

    assert [
        difference.classification
        for difference in broker_reconciliation.compare(expected, observed)
    ] == ["order_filled_quantity", "order_status"]
    expired = replace(
        observed_order,
        status="expired",
        rejection_reason="day order expired",
    )
    assert expired.status == "expired"


@pytest.mark.parametrize(
    ("status", "filled_quantity"),
    [
        ("pending", 0.1),
        ("partially_filled", 0.0),
        ("partially_filled", 1.0),
        ("filled", 0.0),
    ],
)
def test_order_status_requires_consistent_filled_quantity(status, filled_quantity):
    with pytest.raises(ValueError, match="filled"):
        replace(
            _order("paper-account", "paper-order:1"),
            status=status,
            filled_quantity=filled_quantity,
        )


def test_unavailable_observed_adapter_is_durable_and_not_a_match(con):
    result = broker_reconciliation.reconcile(
        con,
        reconciliation_key="recon-unavailable",
        expected_adapter=_adapter("sim-account"),
        expected_account_id="sim-account",
        observed_adapter=_UnavailableAdapter(),
        observed_account_id="live-disabled",
    )

    assert result.status == "unavailable"
    assert result.expected is not None
    assert result.observed is None
    assert [difference.classification for difference in result.differences] == [
        "observed_unavailable"
    ]
    assert con.execute(
        "SELECT status, observed_payload FROM broker_reconciliations"
    ).fetchone() == ("unavailable", None)
    assert con.execute(
        "SELECT role FROM broker_snapshots"
    ).fetchall() == [("expected",)]
    assert con.execute(
        "SELECT difference_payload FROM broker_reconciliation_differences"
    ).fetchone()[0] == (
        '{"classification":"observed_unavailable","expected":"available",'
        '"field":"account","key":"live-disabled","observed":"unavailable"}'
    )


def test_reconciliation_key_replay_is_exact_and_conflicts_fail_closed(con):
    kwargs = {
        "reconciliation_key": "recon-replay",
        "expected_adapter": _adapter("sim-account"),
        "expected_account_id": "sim-account",
        "observed_adapter": _adapter("paper-account"),
        "observed_account_id": "paper-account",
    }
    first = broker_reconciliation.reconcile(con, **kwargs)
    replay = broker_reconciliation.reconcile(con, **kwargs)
    assert first == replay
    assert con.execute("SELECT COUNT(*) FROM broker_reconciliations").fetchone() == (1,)
    assert con.execute("SELECT COUNT(*) FROM broker_snapshots").fetchone() == (2,)
    assert con.execute(
        "SELECT COUNT(*) FROM broker_reconciliation_differences"
    ).fetchone() == (0,)

    kwargs["observed_adapter"] = _adapter("paper-account", cash=999.0)
    with pytest.raises(BrokerStateError, match="snapshot conflicts"):
        broker_reconciliation.reconcile(con, **kwargs)
    assert con.execute("SELECT COUNT(*) FROM broker_reconciliations").fetchone() == (1,)
    assert con.execute("SELECT COUNT(*) FROM broker_snapshots").fetchone() == (2,)


def test_reconciliation_rejects_expected_state_change_across_venue_reads(con):
    class ChangingExpectedAdapter(_SnapshotAdapter):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.snapshot_reads = 0

        def get_account(self, account_id):
            account = super().get_account(account_id)
            self.snapshot_reads += 1
            # capture_snapshot reads the account twice. The later expected
            # capture starts on read three.
            return (
                account
                if self.snapshot_reads <= 2
                else replace(account, cash=999.0, buying_power=999.0)
            )

    with pytest.raises(BrokerStateError, match="cross-venue reconciliation"):
        broker_reconciliation.reconcile(
            con,
            reconciliation_key="recon-changing-expected",
            expected_adapter=ChangingExpectedAdapter(account_id="sim-account"),
            expected_account_id="sim-account",
            observed_adapter=_adapter("paper-account"),
            observed_account_id="paper-account",
        )

    assert con.execute(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_name IN ('broker_snapshots', 'broker_reconciliations')"
    ).fetchone() == (0,)
