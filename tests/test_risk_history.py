"""Realized discretionary history and circuit-breaker tests."""

from datetime import datetime

import duckdb
import pytest

from server import risk_history
from tests.risk_test_helpers import insert_trip, populate_risk_con, spy_days


@pytest.fixture
def risk_con(con):
    return populate_risk_con(con)


def test_closed_round_trips_fifo_and_realized_r(risk_con):
    days = spy_days()
    insert_trip(risk_con, 1, "AAA", "buy", 10, days[-10], 100.0, entry=100.0, stop=95.0)
    insert_trip(risk_con, 2, "AAA", "buy", 10, days[-9], 110.0, entry=110.0, stop=100.0)
    insert_trip(risk_con, 3, "AAA", "sell", 15, days[-8], 90.0)
    trips = risk_history.closed_round_trips(risk_con)
    assert [(t["qty"], t["entry_px"], t["realized_r"]) for t in trips] == [
        (10.0, 100.0, pytest.approx(-2.0)),
        (5.0, 110.0, pytest.approx(-2.0)),
    ]

    recent, matching_count = risk_history.recent_round_trips(risk_con, 1)
    assert matching_count == 2
    assert [(trip["qty"], trip["entry_px"]) for trip in recent] == [(5.0, 110.0)]


def test_recent_round_trips_crosses_fill_scan_batches_with_exact_count(risk_con):
    days = spy_days()
    trip_count = risk_history.FILL_SCAN_BATCH_SIZE // 2 + 5
    for index in range(trip_count):
        ticker = f"T{index:03d}"
        buy_id = 2 * index + 1
        sell_id = buy_id + 1
        insert_trip(
            risk_con,
            buy_id,
            ticker,
            "buy",
            1,
            days[-2],
            100.0,
            entry=100.0,
            stop=99.0,
        )
        insert_trip(risk_con, sell_id, ticker, "sell", 1, days[-1], 101.0)

    recent, matching_count = risk_history.recent_round_trips(risk_con, 3)

    assert matching_count == trip_count
    assert [trip["ticker"] for trip in recent] == [
        f"T{trip_count - offset:03d}" for offset in (1, 2, 3)
    ]
    assert all(trip["realized_r"] == pytest.approx(1.0) for trip in recent)


def test_round_trip_without_stop_falls_back_to_unit_r(risk_con):
    days = spy_days()
    insert_trip(risk_con, 1, "AAA", "buy", 10, days[-10], 100.0)
    insert_trip(risk_con, 2, "AAA", "sell", 10, days[-9], 130.0)
    assert risk_history.closed_round_trips(risk_con)[0]["realized_r"] == 1.0


def test_empty_circuit_breaker_does_not_require_price_history(con):
    con.execute("DROP TABLE prices")

    assert risk_history.circuit_breaker(con) == {
        "status": "pass",
        "detail": "no closed discretionary round-trips",
    }


def test_closed_trip_requires_price_history_for_circuit_breaker(risk_con):
    days = spy_days()
    insert_trip(risk_con, 1, "A", "buy", 1, days[-2], 100.0, entry=100.0, stop=99.0)
    insert_trip(risk_con, 2, "A", "sell", 1, days[-1], 101.0)
    risk_con.execute("DROP TABLE prices")

    with pytest.raises(duckdb.Error, match="prices"):
        risk_history.circuit_breaker(risk_con)


def test_round_trip_ignores_unmatched_sale_and_preserves_remaining_buy_lot(risk_con):
    days = spy_days()
    insert_trip(risk_con, 1, "A", "sell", 2, days[-4], 99.0)
    insert_trip(risk_con, 2, "A", "buy", 3, days[-3], 100.0, entry=100.0, stop=99.0)
    insert_trip(risk_con, 3, "A", "sell", 1, days[-2], 102.0)
    insert_trip(risk_con, 4, "A", "sell", 2, days[-1], 103.0)

    assert [
        (trip["qty"], trip["entry_px"], trip["exit_px"], trip["realized_r"])
        for trip in risk_history.closed_round_trips(risk_con)
    ] == [
        (1.0, 100.0, 102.0, pytest.approx(2.0)),
        (2.0, 100.0, 103.0, pytest.approx(3.0)),
    ]


def test_circuit_breaker_three_losers(risk_con):
    days = spy_days()
    assert risk_history.circuit_breaker(risk_con)["status"] == "pass"
    for i, tk in enumerate(("A", "B", "C")):
        insert_trip(risk_con, 10 + i, tk, "buy", 1, days[-40 + i], 100.0, entry=100.0, stop=90.0)
        insert_trip(risk_con, 20 + i, tk, "sell", 1, days[-30 + i], 99.0)  # -0.1R each
    cb = risk_history.circuit_breaker(risk_con)
    assert cb["status"] == "fail" and "consecutive" in cb["detail"]
    # a review marker after the last exit clears it
    risk_con.execute(
        "INSERT INTO review_markers VALUES (?, 'circuit_breaker')",
        [datetime.combine(days[-20], datetime.min.time())],
    )
    assert risk_history.circuit_breaker(risk_con)["status"] == "pass"


def test_circuit_breaker_minus_five_r_in_window(risk_con):
    days = spy_days()
    insert_trip(risk_con, 1, "A", "buy", 10, days[-10], 100.0, entry=100.0, stop=99.0)
    insert_trip(risk_con, 2, "A", "sell", 10, days[-2], 94.0)  # -6R, in last 5 sessions
    insert_trip(risk_con, 3, "B", "buy", 1, days[-10], 100.0, entry=100.0, stop=99.0)
    insert_trip(risk_con, 4, "B", "sell", 1, days[-1], 101.0)  # +1R -> not 3 losers
    cb = risk_history.circuit_breaker(risk_con)
    assert cb["status"] == "fail" and "-5.0R" in cb["detail"]


def test_circuit_breaker_old_loss_outside_window_passes(risk_con):
    days = spy_days()
    insert_trip(risk_con, 1, "A", "buy", 10, days[-30], 100.0, entry=100.0, stop=99.0)
    insert_trip(risk_con, 2, "A", "sell", 10, days[-20], 90.0)  # -10R but stale
    assert risk_history.circuit_breaker(risk_con)["status"] == "pass"
