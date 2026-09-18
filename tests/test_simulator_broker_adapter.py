"""Broker-neutral contract tests against the existing paper simulator."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from server.broker_contract import (
    BrokerAccountInactive,
    BrokerAdapter,
    BrokerIdempotencyConflict,
    BrokerOrderNotCancelable,
    BrokerOrderNotFound,
    BrokerStateError,
    SubmitOrderRequest,
)
from server.simulator_broker_adapter import SimulatorBrokerAdapter
from sim import league

ACCOUNT = "adapter-paper"
SIGNAL_DATE = date(2024, 6, 3)
FILL_DATE = date(2024, 6, 4)


def _account(con, *, active=True, cash=39_000.0):
    con.execute(
        "INSERT INTO portfolios (id, name, strategy, config, created, active, "
        "cash, initial_cash, execution_profile) "
        "VALUES (?, 'Adapter paper', 'none', '{}', ?, ?, ?, 39000, 'baseline_v1')",
        [ACCOUNT, SIGNAL_DATE, active, cash],
    )


def _request(
    *,
    key="adapter-intent-101",
    symbol="AAA",
    side="buy",
    quantity=10.0,
    signal_date=SIGNAL_DATE,
):
    return SubmitOrderRequest(
        idempotency_key=key,
        account_id=ACCOUNT,
        symbol=symbol,
        side=side,
        quantity=quantity,
        signal_date=signal_date,
    )


def _bars(con, symbol, *, open_price=100.0):
    history = [SIGNAL_DATE - timedelta(days=offset) for offset in range(30, 0, -1)]
    con.executemany(
        "INSERT INTO prices (ticker, date, open, high, low, close, volume) "
        "VALUES (?, ?, ?, ?, ?, ?, 1000000)",
        [
            (symbol, observation_date, open_price, open_price, open_price, open_price)
            for observation_date in [*history, SIGNAL_DATE, FILL_DATE]
        ],
    )


def test_implements_broker_contract_and_projects_account_positions(con):
    _account(con, cash=37_000.0)
    con.execute(
        "INSERT INTO sim_positions VALUES (?, 'AAA', 20, 100), (?, 'ZZZ', 5, 200)",
        [ACCOUNT, ACCOUNT],
    )
    adapter = SimulatorBrokerAdapter(con)

    assert isinstance(adapter, BrokerAdapter)
    account = adapter.get_account(ACCOUNT)
    assert account.account_id == ACCOUNT
    assert account.venue == "local-simulator"
    assert account.environment == "simulator"
    assert account.active is True
    assert account.currency == "USD"
    assert account.cash == account.buying_power == 37_000.0
    assert account.initial_cash == 39_000.0
    assert [
        (position.symbol, position.quantity, position.average_price)
        for position in adapter.get_positions(ACCOUNT)
    ] == [("AAA", 20.0, 100.0), ("ZZZ", 5.0, 200.0)]
    assert con.execute(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_name = 'simulator_broker_order_keys'"
    ).fetchone() == (0,)


def test_submit_is_exactly_idempotent_and_conflicting_reuse_fails_closed(con):
    _account(con)
    adapter = SimulatorBrokerAdapter(con)

    first = adapter.submit_order(_request())
    replay = adapter.submit_order(_request())

    assert first == replay
    assert first.broker_order_id == "sim-order:1"
    assert first.idempotency_key == "adapter-intent-101"
    assert first.status == "pending"
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone() == (1,)
    assert con.execute(
        "SELECT idempotency_key, order_id FROM simulator_broker_order_keys"
    ).fetchone() == ("adapter-intent-101", 1)

    with pytest.raises(BrokerIdempotencyConflict, match="different order terms"):
        adapter.submit_order(_request(quantity=11))
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone() == (1,)
    assert con.execute("SELECT qty FROM sim_orders WHERE id = 1").fetchone() == (10.0,)


def test_submission_requires_active_account_and_rolls_back(con):
    _account(con, active=False)
    adapter = SimulatorBrokerAdapter(con)

    with pytest.raises(BrokerAccountInactive):
        adapter.submit_order(_request())

    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone() == (0,)


def test_open_orders_and_cancel_are_account_scoped_and_idempotent(con):
    _account(con)
    adapter = SimulatorBrokerAdapter(con)
    submitted = adapter.submit_order(_request())

    assert adapter.get_open_orders(ACCOUNT) == (submitted,)
    cancelled = adapter.cancel_order(ACCOUNT, submitted.broker_order_id)
    replay = adapter.cancel_order(ACCOUNT, submitted.broker_order_id)

    assert cancelled == replay
    assert cancelled.status == "cancelled"
    assert cancelled.rejection_reason == "cancelled through simulator adapter"
    assert adapter.get_open_orders(ACCOUNT) == ()

    with pytest.raises(BrokerOrderNotFound):
        adapter.cancel_order(ACCOUNT, "sim-order:999")


def test_terminal_filled_order_cannot_be_cancelled(con):
    _account(con)
    _bars(con, "AAA")
    adapter = SimulatorBrokerAdapter(con)
    submitted = adapter.submit_order(_request())
    assert league.fill_pending(con, FILL_DATE)["filled"] == 1

    with pytest.raises(BrokerOrderNotCancelable, match="filled"):
        adapter.cancel_order(ACCOUNT, submitted.broker_order_id)

    assert con.execute(
        "SELECT status FROM sim_orders WHERE id = 1"
    ).fetchone() == ("filled",)


def test_existing_simulator_fill_semantics_are_observed_without_new_fill_path(con):
    _account(con)
    _bars(con, "AAA")
    adapter = SimulatorBrokerAdapter(con)
    adapter.submit_order(_request())

    assert adapter.stream_fills(ACCOUNT).fills == ()
    assert league.fill_pending(con, FILL_DATE) == {
        "filled": 1,
        "rejected": 0,
        "pending": 0,
    }

    batch = adapter.stream_fills(ACCOUNT)
    assert batch.truncated is False
    assert batch.next_cursor == "sim-fill:1"
    assert len(batch.fills) == 1
    fill = batch.fills[0]
    assert fill.execution_id == "sim-fill:1"
    assert fill.broker_order_id == "sim-order:1"
    assert fill.idempotency_key == "adapter-intent-101"
    assert fill.account_id == ACCOUNT
    assert fill.symbol == "AAA"
    assert fill.side == "buy"
    assert fill.quantity == 10.0
    assert fill.occurred_on == FILL_DATE
    assert fill.reference_price == 100.0
    assert fill.price == pytest.approx(100.1)
    assert fill.total_cost_bps == pytest.approx(10.0)
    assert adapter.stream_fills(ACCOUNT, after=batch.next_cursor).fills == ()


def test_fill_observation_is_bounded_cursor_ordered_and_account_scoped(con):
    _account(con)
    other = "other-paper"
    con.execute(
        "INSERT INTO portfolios (id, name, strategy, config, created, active, "
        "cash, initial_cash, execution_profile) "
        "VALUES (?, 'Other', 'none', '{}', ?, TRUE, 39000, 39000, 'baseline_v1')",
        [other, SIGNAL_DATE],
    )
    for order_id, account, symbol in (
        (101, ACCOUNT, "AAA"),
        (102, ACCOUNT, "BBB"),
        (103, other, "ZZZ"),
    ):
        con.execute(
            "INSERT INTO sim_orders VALUES (?, ?, ?, 'buy', 1, ?, 'filled', NULL)",
            [order_id, account, symbol, SIGNAL_DATE],
        )
        con.execute(
            "INSERT INTO sim_fills VALUES (?, ?, ?, 'buy', 1, ?, 100, 100.1, 10, 10)",
            [order_id, account, symbol, FILL_DATE],
        )

    adapter = SimulatorBrokerAdapter(con)
    first = adapter.stream_fills(ACCOUNT, limit=1)
    second = adapter.stream_fills(ACCOUNT, after=first.next_cursor, limit=1)

    assert [fill.execution_id for fill in first.fills] == ["sim-fill:101"]
    assert first.next_cursor == "sim-fill:101"
    assert first.truncated is True
    assert [fill.execution_id for fill in second.fills] == ["sim-fill:102"]
    assert second.next_cursor == "sim-fill:102"
    assert second.truncated is False


def test_corrupt_simulator_state_fails_closed_without_rewriting_it(con):
    _account(con)
    con.execute(
        "INSERT INTO sim_orders VALUES "
        "(101, ?, 'AAA', 'buy', 1, ?, 'filled', NULL)",
        [ACCOUNT, SIGNAL_DATE],
    )
    con.execute(
        "INSERT INTO sim_fills VALUES "
        "(101, ?, 'WRONG', 'buy', 1, ?, 100, 100.1, 10, 10)",
        [ACCOUNT, FILL_DATE],
    )
    adapter = SimulatorBrokerAdapter(con)

    with pytest.raises(BrokerStateError, match="does not match"):
        adapter.stream_fills(ACCOUNT)

    assert con.execute("SELECT ticker FROM sim_fills").fetchone() == ("WRONG",)


@pytest.mark.parametrize("corruption", ["orphan", "duplicate", "cross_account_duplicate"])
def test_orphaned_or_duplicate_fill_state_fails_closed(con, corruption):
    _account(con)
    if corruption == "orphan":
        con.execute(
            "INSERT INTO sim_fills VALUES "
            "(101, ?, 'AAA', 'buy', 1, ?, 100, 100.1, 10, 10)",
            [ACCOUNT, FILL_DATE],
        )
    else:
        con.execute(
            "INSERT INTO sim_orders VALUES "
            "(101, ?, 'AAA', 'buy', 1, ?, 'filled', NULL)",
            [ACCOUNT, SIGNAL_DATE],
        )
        duplicate_account = ACCOUNT if corruption == "duplicate" else "other-paper"
        con.execute(
            "INSERT INTO sim_fills VALUES "
            "(101, ?, 'AAA', 'buy', 1, ?, 100, 100.1, 10, 10), "
            "(101, ?, 'AAA', 'buy', 1, ?, 100, 100.1, 10, 10)",
            [ACCOUNT, FILL_DATE, duplicate_account, FILL_DATE],
        )

    with pytest.raises(BrokerStateError, match="does not match"):
        SimulatorBrokerAdapter(con).stream_fills(ACCOUNT)
