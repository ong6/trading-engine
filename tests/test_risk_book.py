"""Discretionary-book valuation and open-risk tests."""

import pytest

from server import risk_book
from sim.schema import INITIAL_CASH
from tests.conftest import insert_bars
from tests.risk_test_helpers import open_book, populate_risk_con, spy_days

EQ = INITIAL_CASH


@pytest.fixture
def risk_con(con):
    return populate_risk_con(con)


def test_disc_state_equity_and_default(risk_con):
    assert risk_book.disc_state(risk_con)["equity"] == INITIAL_CASH
    risk_con.execute(
        "UPDATE prices SET open=119, high=121, low=118, close=120 WHERE ticker='AAA' AND date=?",
        [spy_days()[-1]],
    )
    open_book(risk_con, 10_000.0, [("AAA", 100.0, 100.0)])
    st = risk_book.disc_state(risk_con)
    assert st["exists"] and st["equity"] == pytest.approx(10_000 + 12_000)
    assert st["positions"][0]["stop"] is None


def test_disc_state_does_not_treat_retired_book_as_current(risk_con):
    open_book(risk_con, 10_000.0, [("AAA", 100.0, 100.0)])
    risk_con.execute("UPDATE portfolios SET active = FALSE WHERE id = 'discretionary'")

    assert risk_book.disc_state(risk_con) == {
        "exists": False,
        "cash": INITIAL_CASH,
        "equity": INITIAL_CASH,
        "positions": [],
    }


def test_open_risk_uses_stored_stop(risk_con):
    open_book(risk_con, EQ, [("AAA", 10.0, 100.0)])
    risk_con.execute(
        "INSERT INTO disc_tickets (id, ticker, stop, status, created_at) "
        "VALUES (1, 'AAA', 95, 'filled', now())"
    )
    st = risk_book.disc_state(risk_con)
    assert st["positions"][0]["stop"] == 95.0
    assert risk_book.open_disc_risk(risk_con, st) == pytest.approx(50.0)  # 10 x (100-95)
    risk_con.execute("UPDATE disc_tickets SET stop = 120")  # stop above cost -> floor 0
    assert risk_book.open_disc_risk(risk_con, risk_book.disc_state(risk_con)) == 0.0


def test_disc_state_bulk_loads_latest_real_marks_and_stops(risk_con):
    days = spy_days()
    open_book(risk_con, 1_000.0, [("AAA", 2.0, 90.0), ("BBB", 3.0, 40.0)])
    insert_bars(
        risk_con,
        "BBB",
        days[-2:],
        open_=[50.0, 500.0],
        high=[51.0, 500.0],
        low=[49.0, 500.0],
        close=[50.0, 500.0],
        volume=[1_000, 0],
    )
    risk_con.execute(
        "INSERT INTO disc_tickets (id, ticker, stop, status, created_at) VALUES "
        "(1, 'AAA', 80, 'filled', TIMESTAMP '2026-09-01 12:00:00'), "
        "(2, 'AAA', 85, 'cancelled', TIMESTAMP '2026-09-03 12:00:00'), "
        "(3, 'AAA', 88, 'submitted', TIMESTAMP '2026-09-02 12:00:00'), "
        "(4, 'BBB', 45, 'filled', TIMESTAMP '2026-09-02 12:00:00')"
    )

    state = risk_book.disc_state(risk_con, as_of=days[-1])

    assert state["positions"] == [
        {"ticker": "AAA", "qty": 2.0, "avg_cost": 90.0, "stop": 88.0, "close": 100.0},
        {"ticker": "BBB", "qty": 3.0, "avg_cost": 40.0, "stop": 45.0, "close": 50.0},
    ]
    assert state["equity"] == pytest.approx(1_350.0)


def test_disc_state_query_count_does_not_grow_with_positions(risk_con):
    class CountingConnection:
        def __init__(self, actual):
            self.actual = actual
            self.execute_count = 0

        def execute(self, *args, **kwargs):
            self.execute_count += 1
            return self.actual.execute(*args, **kwargs)

    days = spy_days()
    open_book(risk_con, 1_000.0, [("AAA", 2.0, 90.0)])
    one_position = CountingConnection(risk_con)
    risk_book.disc_state(one_position, as_of=days[-1])

    for ticker in ("BBB", "CCC", "DDD"):
        risk_con.execute(
            "INSERT INTO sim_positions VALUES ('discretionary', ?, 1, 50)", [ticker]
        )
        insert_bars(
            risk_con,
            ticker,
            days[-1:],
            open_=50.0,
            high=51.0,
            low=49.0,
            close=50.0,
        )
    four_positions = CountingConnection(risk_con)
    state = risk_book.disc_state(four_positions, as_of=days[-1])

    assert len(state["positions"]) == 4
    assert four_positions.execute_count == one_position.execute_count
